from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
import threading

import pandas as pd
import pytest

from src.config import MarketDataConfig
from src.data.active_universe import build_history_collection_manifest
from src.data.full_history_pipeline import (
    FullHistoryContext,
    FullHistoryError,
    FullHistoryPaths,
    FullHistoryPipeline,
    ManifestOutcome,
    PreparedManifestRow,
    PreparedSecurity,
    atomic_write_text,
    build_collection_failures,
    build_collection_gaps,
    build_collection_status,
    build_collection_summary,
    build_mapping_review,
)
from src.data.collectors import ProviderGap
from src.data.isyatirim_client import GlobalRequestLimiter, NO_DATA_IN_RANGE
from src.data.security_identity import MAPPING_COLUMNS, TickerMapping, generate_security_id
from src.data.snapshot_store import SnapshotRequest, SnapshotStore


class NeverCollector:
    def __init__(self) -> None:
        self.calls = 0

    def collect_ticker(self, *_: object, **__: object) -> object:
        self.calls += 1
        raise AssertionError("provider must not be called")


def _fixture(tmp_path: Path):
    config = replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )
    store = SnapshotStore(config)
    as_of = date(2026, 7, 29)
    start = date(2020, 3, 13)
    tickers = ["AAA", "BBB"]
    universe = pd.DataFrame(
        {
            "security_id": [generate_security_id(value) for value in tickers],
            "current_ticker": tickers,
            "company_name": ["AAA A.Ş.", "BBB A.Ş."],
            "market_group": ["PAY PİYASASI", "PAY PİYASASI"],
            "market_name": ["YILDIZ PAZAR", "ANA PAZAR"],
            "instrument_type": ["EQUITY", "EQUITY"],
            "universe_version": ["bist_active_universe_v1"] * 2,
            "as_of_date": [as_of.isoformat()] * 2,
        }
    )
    active_csv = tmp_path / "active.csv"
    active_payload = universe.to_csv(index=False, lineterminator="\n")
    active_csv.write_text(active_payload, encoding="utf-8", newline="\n")
    active_checksum = hashlib.sha256(active_payload.encode("utf-8")).hexdigest()
    mapping_path = tmp_path / "bist_security_ticker_map_v1.csv"
    mapping_path.write_text(
        ",".join(MAPPING_COLUMNS) + "\n", encoding="utf-8", newline="\n"
    )
    mapping = TickerMapping.from_csv(mapping_path)
    request = SnapshotRequest(
        source="universe",
        dataset_type="active_bist_equities",
        ticker_or_instrument="BIST_ACTIVE_EQUITIES",
        request_start_date=as_of,
        request_end_date=as_of,
        request_parameters={
            "universe_version": "bist_active_universe_v1",
            "as_of_date": as_of.isoformat(),
        },
        code_commit_sha="a" * 40,
        layer="derived",
        input_snapshot_ids=(),
        identity_columns=("security_id",),
        revision_context={
            "input_snapshot_ids": [],
            "input_content_checksums": {},
            "active_universe_file_checksum": active_checksum,
            "ticker_mapping_version": mapping.version,
            "ticker_mapping_checksum": mapping.checksum,
            "as_of_date": as_of.isoformat(),
            "parser_version": "test",
            "code_commit_sha": "a" * 40,
            "included_security_count": 2,
            "excluded_candidate_count": 0,
        },
    )
    active = store.save_dataframe(universe, request).metadata
    manifest = build_history_collection_manifest(
        universe, mapping, start_date=start, end_date=as_of
    )
    manifest_path = tmp_path / "manifest.csv"
    manifest.to_csv(manifest_path, index=False, lineterminator="\n")
    price_steps = tmp_path / "price_steps.csv"
    price_steps.write_text("fixture\n", encoding="utf-8")
    catalog = tmp_path / "FEATURE_CATALOG.md"
    catalog.write_text("# fixture\n", encoding="utf-8")
    report_root = tmp_path / "reports"
    context = FullHistoryContext(
        active_universe_snapshot_id=active.snapshot_id,
        universe_version="bist_active_universe_v1",
        active_universe_as_of_date=as_of,
        master_security_count=2,
        collection_start_date=start,
        model_period_start_date=start,
        collection_end_date=as_of,
    )
    paths = FullHistoryPaths(
        manifest=manifest_path,
        mapping=mapping_path,
        active_universe_csv=active_csv,
        price_steps=price_steps,
        feature_catalog=catalog,
        report_root=report_root,
    )
    pipeline = FullHistoryPipeline(
        config,
        context=context,
        paths=paths,
        snapshot_store=store,
        code_commit_sha="a" * 40,
    )
    return pipeline, manifest_path


def _complete(row_number: int, security_id: str, ticker: str) -> ManifestOutcome:
    return ManifestOutcome(
        row_number=row_number,
        security_id=security_id,
        current_ticker=ticker,
        provider_ticker=ticker,
        period_start="2020-03-13",
        period_end="2026-07-29",
        isyatirim_status="COMPLETE",
        yfinance_status="COMPLETE",
        isyatirim_raw_snapshot_id=f"is-{ticker}",
        yfinance_raw_snapshot_id=f"yf-{ticker}",
        nominal_snapshot_id=f"nom-{ticker}",
        isyatirim_dates=("2020-03-13", "2020-03-16"),
        yfinance_dates=("2020-03-13", "2020-03-16"),
    )


def test_preflight_validates_snapshot_manifest_mapping_and_scope(tmp_path: Path) -> None:
    pipeline, _ = _fixture(tmp_path)

    result = pipeline.preflight()

    assert len(result.universe) == 2
    assert len(result.manifest) == 2
    assert result.mapping.frame.empty
    assert result.active_metadata.source == "universe"


def test_pipeline_resolves_current_code_sha_when_not_explicitly_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, _ = _fixture(tmp_path)
    monkeypatch.setattr(
        "src.data.full_history_pipeline.current_code_commit_sha", lambda: "f" * 40
    )

    resolved = FullHistoryPipeline(
        pipeline.config,
        context=pipeline.context,
        paths=pipeline.paths,
        snapshot_store=pipeline.snapshot_store,
    )

    assert resolved.code_commit_sha == "f" * 40


def test_invalid_preflight_stops_before_provider_call(tmp_path: Path) -> None:
    pipeline, manifest_path = _fixture(tmp_path)
    manifest = pd.read_csv(manifest_path)
    pd.concat([manifest, manifest.iloc[[0]]], ignore_index=True).to_csv(
        manifest_path, index=False
    )
    collector = NeverCollector()
    pipeline.collector = collector

    with pytest.raises(FullHistoryError, match="manifest"):
        pipeline.run()

    assert collector.calls == 0


def test_failed_security_does_not_remove_successful_snapshot_scope(tmp_path: Path) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    second = preflight.manifest.iloc[1]
    outcomes = [
        _complete(0, str(first.security_id), str(first.current_ticker)),
        ManifestOutcome(
            row_number=1,
            security_id=str(second.security_id),
            current_ticker=str(second.current_ticker),
            provider_ticker=str(second.provider_ticker),
            period_start=str(second.period_start),
            period_end=str(second.period_end),
            isyatirim_status="FAILED",
            yfinance_status="FAILED",
            isyatirim_raw_snapshot_id="failed-is",
            yfinance_raw_snapshot_id="failed-yf",
            nominal_snapshot_id="",
            failure_stage="YFINANCE",
            failure_class="TimeoutError",
            failure_reason="provider timeout",
        ),
    ]

    status = build_collection_status(preflight, outcomes)
    summary = build_collection_summary(status)

    successful = status.loc[status["security_id"].eq(str(first.security_id))].iloc[0]
    assert successful["collection_complete"]
    assert successful["raw_snapshot_ids"] == f"is-{first.current_ticker}|yf-{first.current_ticker}"
    assert summary["complete_security_count"] == 1
    assert summary["failed_security_count"] == 1


def test_run_provenance_records_used_and_excluded_security_scope(tmp_path: Path) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    status = build_collection_status(
        preflight, [_complete(0, str(first.security_id), str(first.current_ticker))]
    )
    summary = build_collection_summary(status)

    provenance = pipeline._run_provenance(
        preflight,
        status,
        summary,
        run_status="PARTIAL",
        run_started_at_utc="2026-07-29T00:00:00Z",
        used_security_ids=[str(first.security_id)],
        excluded_security_ids=[str(preflight.manifest.iloc[1].security_id)],
        snapshots=(),
    )

    assert provenance["used_security_ids"] == [str(first.security_id)]
    assert provenance["excluded_security_ids"] == [
        str(preflight.manifest.iloc[1].security_id)
    ]
    assert not provenance["experiment_ready"]


def test_mapping_review_is_deterministic_and_never_infers_alias(tmp_path: Path) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    outcome = _complete(0, str(first.security_id), str(first.current_ticker))
    status = build_collection_status(preflight, [outcome])
    calendar = pd.DataFrame(
        {"session_date": pd.to_datetime(["2020-03-13", "2020-03-16", "2020-03-17"])}
    )

    left = build_mapping_review(status, [outcome], calendar)
    right = build_mapping_review(status, [outcome], calendar)

    pd.testing.assert_frame_equal(left, right)
    assert left["possible_historical_ticker"].eq("").all()
    assert left["official_evidence_status"].eq("OFFICIAL_EVIDENCE_REQUIRED").all()


def test_atomic_checkpoint_failure_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "checkpoint.csv"
    target.write_text("previous\n", encoding="utf-8")

    def fail_replace(_: object, __: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("src.data.full_history_pipeline.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated"):
        atomic_write_text(target, "new\n")

    assert target.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_summary_counts_unattempted_and_nominal_success_rate(tmp_path: Path) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    status = build_collection_status(
        preflight, [_complete(0, str(first.security_id), str(first.current_ticker))]
    )

    summary = build_collection_summary(status)

    assert summary["attempted_security_count"] == 1
    assert summary["unattempted_security_count"] == 1
    assert summary["nominal_success_rate"] == 1.0
    assert summary["provider_success_rate_denominator"].startswith(
        "attempted_security_count"
    )


def test_gap_and_failure_reports_preserve_real_missing_ranges(
    tmp_path: Path,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    gap = ProviderGap(
        start_date="2020-07-01",
        end_date="2020-12-31",
        failure_class="TIME_BUDGET_EXCEEDED",
        failure_reason="budget exhausted",
        retry_recommended=True,
    )
    outcome = ManifestOutcome(
        row_number=0,
        security_id=str(first.security_id),
        current_ticker=str(first.current_ticker),
        provider_ticker=str(first.provider_ticker),
        period_start=str(first.period_start),
        period_end=str(first.period_end),
        isyatirim_status="PARTIAL",
        yfinance_status="FAILED",
        nominal_status="FAILED",
        isyatirim_raw_snapshot_id="partial-is",
        yfinance_raw_snapshot_id="failed-yf",
        nominal_snapshot_id="",
        failure_stage="ISYATIRIM",
        failure_class="TIME_BUDGET_EXCEEDED",
        failure_reason="budget exhausted",
        collection_pass=2,
        gaps=(("ISYATIRIM", gap),),
        last_successful_stage="ISYATIRIM_RAW",
        retry_recommended=True,
        elapsed_seconds=1800.0,
        security_budget_seconds=1800.0,
        network_request_count=3,
        cache_hit_count=2,
        retry_count=1,
        timeout_count=1,
    )
    status = build_collection_status(preflight, [outcome])

    gaps = build_collection_gaps(status, [outcome])
    failures = build_collection_failures(status)

    assert gaps.loc[0, "missing_start_date"] == "2020-07-01"
    assert gaps.loc[0, "missing_end_date"] == "2020-12-31"
    assert gaps.loc[0, "failure_class"] == "TIME_BUDGET_EXCEEDED"
    assert status.loc[0, "last_successful_stage"] == "ISYATIRIM_RAW"
    assert failures.empty


def test_two_pass_collection_retries_only_incomplete_security_and_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    calls: list[tuple[int, str]] = []
    checkpoints: list[pd.DataFrame] = []

    def fake_collect(
        _collector: object,
        row_number: int,
        row: pd.Series,
        *,
        collection_pass: int,
        **_: object,
    ) -> ManifestOutcome:
        security_id = str(row["security_id"])
        ticker = str(row["current_ticker"])
        calls.append((collection_pass, security_id))
        if collection_pass == 1 and ticker == "AAA":
            return ManifestOutcome(
                row_number=row_number,
                security_id=security_id,
                current_ticker=ticker,
                provider_ticker=ticker,
                period_start=str(row["period_start"]),
                period_end=str(row["period_end"]),
                isyatirim_status="FAILED",
                yfinance_status="FAILED",
                nominal_status="FAILED",
                isyatirim_raw_snapshot_id="failed-is",
                yfinance_raw_snapshot_id="failed-yf",
                nominal_snapshot_id="",
                failure_stage="ISYATIRIM",
                failure_class="TimeoutError",
                failure_reason="provider timeout",
                collection_pass=1,
                retry_recommended=True,
            )
        result = _complete(row_number, security_id, ticker)
        return replace(result, collection_pass=collection_pass)

    monkeypatch.setattr(pipeline, "_collect_manifest_row", fake_collect)
    monkeypatch.setattr(
        pipeline,
        "_write_collection_checkpoint",
        lambda status, *_args, **_kwargs: checkpoints.append(status.copy()),
    )

    outcomes, status, summary, passes = pipeline.collect_manifest(preflight)

    aaa_id = str(
        preflight.universe.loc[
            preflight.universe["current_ticker"].eq("AAA"), "security_id"
        ].iloc[0]
    )
    bbb_id = str(
        preflight.universe.loc[
            preflight.universe["current_ticker"].eq("BBB"), "security_id"
        ].iloc[0]
    )
    assert calls == [(1, aaa_id), (1, bbb_id), (2, aaa_id)]
    assert len(checkpoints) == 3
    assert status["status"].eq("COMPLETE").all()
    assert summary["retry_pass_attempted_count"] == 1
    assert summary["retry_pass_recovered_count"] == 1
    assert summary["unattempted_security_count"] == 0
    assert passes["retry_security_ids"] == [aaa_id]
    assert len(outcomes) == 2


def test_legacy_checkpoint_resume_starts_with_first_unattempted_security(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    first_id = str(first.security_id)
    second = preflight.manifest.iloc[1]
    second_id = str(second.security_id)
    partial = ManifestOutcome(
        row_number=0,
        security_id=first_id,
        current_ticker=str(first.current_ticker),
        provider_ticker=str(first.provider_ticker),
        period_start=str(first.period_start),
        period_end=str(first.period_end),
        isyatirim_status="FAILED",
        yfinance_status="FAILED",
        nominal_status="FAILED",
        isyatirim_raw_snapshot_id="",
        yfinance_raw_snapshot_id="",
        nominal_snapshot_id="",
        failure_stage="ISYATIRIM",
        failure_class="TIME_BUDGET_EXCEEDED",
        failure_reason="budget exhausted",
        collection_pass=1,
        retry_recommended=True,
    )
    status = build_collection_status(preflight, [partial])
    summary = build_collection_summary(status)
    provenance = pipeline._run_provenance(
        preflight,
        status,
        summary,
        run_status="COLLECTING_PASS_1",
        run_started_at_utc="2026-07-31T00:00:00Z",
        used_security_ids=(),
        excluded_security_ids=(),
        snapshots=(),
        outcomes=(partial,),
        collection_passes={
            "first_pass_started_at_utc": "2026-07-31T00:00:00Z",
            "first_pass_finished_at_utc": None,
            "retry_pass_started_at_utc": None,
            "retry_pass_finished_at_utc": None,
        },
    )
    pipeline._checkpoint_attempt_history = (partial,)
    pipeline._write_collection_checkpoint(status, summary, provenance, (partial,))
    (pipeline.paths.report_root / "collection_outcomes.json").unlink()

    calls: list[tuple[int, str]] = []

    def fake_collect(
        _collector: object,
        row_number: int,
        row: pd.Series,
        *,
        collection_pass: int,
        **_: object,
    ) -> ManifestOutcome:
        security_id = str(row["security_id"])
        calls.append((collection_pass, security_id))
        return replace(
            _complete(row_number, security_id, str(row["current_ticker"])),
            collection_pass=collection_pass,
        )

    monkeypatch.setattr(pipeline, "_collect_manifest_row", fake_collect)

    outcomes, result_status, _, _ = pipeline.collect_manifest(preflight)

    assert calls == [(1, second_id), (2, first_id)]
    assert len(outcomes) == 2
    assert result_status["status"].eq("COMPLETE").all()
    payload = json.loads(
        (pipeline.paths.report_root / "collection_outcomes.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["schema_version"] == "full_history_manifest_outcomes_v2_compact"
    assert "isyatirim_dates" not in payload["latest_outcomes"][0]
    assert "yfinance_dates" not in payload["latest_outcomes"][0]
    assert len(payload["latest_outcomes"]) == 2
    assert len(payload["attempt_history"]) == 3


def test_v1_outcome_checkpoint_remains_readable_without_migration_loss(
    tmp_path: Path,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    row = preflight.manifest.iloc[0]
    outcome = ManifestOutcome(
        row_number=0,
        security_id=str(row.security_id),
        current_ticker=str(row.current_ticker),
        provider_ticker=str(row.provider_ticker),
        period_start=str(row.period_start),
        period_end=str(row.period_end),
        isyatirim_status="FAILED",
        yfinance_status="FAILED",
        nominal_status="FAILED",
        isyatirim_raw_snapshot_id="",
        yfinance_raw_snapshot_id="",
        nominal_snapshot_id="",
        isyatirim_dates=("2020-03-13",),
        yfinance_dates=("2020-03-13",),
        failure_stage="FIXTURE",
        failure_class="TimeoutError",
        failure_reason="fixture",
        collection_pass=1,
        retry_recommended=True,
    )
    status = build_collection_status(preflight, (outcome,))
    summary = build_collection_summary(status)
    provenance = pipeline._run_provenance(
        preflight,
        status,
        summary,
        run_status="COLLECTING_PASS_1",
        run_started_at_utc="2026-08-04T00:00:00Z",
        used_security_ids=(),
        excluded_security_ids=(),
        snapshots=(),
        outcomes=(outcome,),
    )
    pipeline._write_collection_checkpoint(status, summary, provenance, (outcome,))
    outcome_path = pipeline.paths.report_root / "collection_outcomes.json"
    payload = json.loads(outcome_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "full_history_manifest_outcomes_v1"
    for key in ("latest_outcomes", "attempt_history"):
        payload[key][0]["isyatirim_dates"] = ["2020-03-13"]
        payload[key][0]["yfinance_dates"] = ["2020-03-13"]
    outcome_path.write_text(json.dumps(payload), encoding="utf-8")

    restored, history, _ = pipeline._load_collection_checkpoint(preflight)

    assert restored[0].isyatirim_dates == ("2020-03-13",)
    assert restored[0].yfinance_dates == ("2020-03-13",)
    assert history[0].isyatirim_dates == ("2020-03-13",)


def test_compact_checkpoint_hydrates_dates_from_verified_snapshots(
    tmp_path: Path,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    row = preflight.manifest.iloc[0]
    request_values = {
        "ticker_or_instrument": str(row.provider_ticker),
        "request_start_date": date.fromisoformat(str(row.period_start)),
        "request_end_date": date.fromisoformat(str(row.period_end)),
        "request_parameters": {"fixture": True},
        "code_commit_sha": "a" * 40,
        "layer": "raw",
        "input_snapshot_ids": (),
    }
    is_snapshot = pipeline.snapshot_store.save_dataframe(
        pd.DataFrame({"HGDG_TARIH": pd.to_datetime(["2020-03-13"])}),
        SnapshotRequest(
            source="isyatirim",
            dataset_type="historical_equity",
            identity_columns=("HGDG_TARIH",),
            **request_values,
        ),
    ).metadata
    yf_snapshot = pipeline.snapshot_store.save_dataframe(
        pd.DataFrame({"date": pd.to_datetime(["2020-03-13"])}),
        SnapshotRequest(
            source="yfinance",
            dataset_type="historical_equity",
            identity_columns=("date",),
            **request_values,
        ),
    ).metadata
    outcome = ManifestOutcome(
        row_number=0,
        security_id=str(row.security_id),
        current_ticker=str(row.current_ticker),
        provider_ticker=str(row.provider_ticker),
        period_start=str(row.period_start),
        period_end=str(row.period_end),
        isyatirim_status="COMPLETE",
        yfinance_status="COMPLETE",
        nominal_status="FAILED",
        isyatirim_raw_snapshot_id=is_snapshot.snapshot_id,
        yfinance_raw_snapshot_id=yf_snapshot.snapshot_id,
        nominal_snapshot_id="",
        isyatirim_dates=("2020-03-13",),
        yfinance_dates=("2020-03-13",),
        collection_pass=1,
    )
    status = build_collection_status(preflight, (outcome,))
    summary = build_collection_summary(status)
    provenance = pipeline._run_provenance(
        preflight,
        status,
        summary,
        run_status="COLLECTING_PASS_1",
        run_started_at_utc="2026-08-04T00:00:00Z",
        used_security_ids=(),
        excluded_security_ids=(),
        snapshots=(),
        outcomes=(outcome,),
    )
    pipeline._write_collection_checkpoint(status, summary, provenance, (outcome,))

    restored, history, _ = pipeline._load_collection_checkpoint(preflight)

    assert restored[0].isyatirim_dates == ("2020-03-13",)
    assert restored[0].yfinance_dates == ("2020-03-13",)
    assert history[0].isyatirim_dates == ("2020-03-13",)


def test_resumed_retry_checkpoint_does_not_start_a_third_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    calls: list[tuple[int, str]] = []

    def partial_collect(
        _collector: object,
        row_number: int,
        row: pd.Series,
        *,
        collection_pass: int,
        **_: object,
    ) -> ManifestOutcome:
        security_id = str(row["security_id"])
        calls.append((collection_pass, security_id))
        return ManifestOutcome(
            row_number=row_number,
            security_id=security_id,
            current_ticker=str(row["current_ticker"]),
            provider_ticker=str(row["provider_ticker"]),
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            isyatirim_status="FAILED",
            yfinance_status="FAILED",
            nominal_status="FAILED",
            isyatirim_raw_snapshot_id="",
            yfinance_raw_snapshot_id="",
            nominal_snapshot_id="",
            failure_stage="ISYATIRIM",
            failure_class="TIME_BUDGET_EXCEEDED",
            failure_reason="budget exhausted",
            collection_pass=collection_pass,
            retry_recommended=True,
        )

    monkeypatch.setattr(pipeline, "_collect_manifest_row", partial_collect)
    pipeline.collect_manifest(preflight)
    assert len(calls) == 4

    monkeypatch.setattr(
        pipeline,
        "_collect_manifest_row",
        lambda *_args, **_kwargs: pytest.fail("third provider attempt was started"),
    )
    outcomes, status, _, _ = pipeline.collect_manifest(preflight)

    assert len(outcomes) == 2
    assert status["status"].eq("FAILED").all()
    assert status["last_collection_pass"].astype(int).eq(2).all()


def test_run_starts_derived_only_after_both_collection_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    outcomes = tuple(
        _complete(index, str(row.security_id), str(row.current_ticker))
        for index, row in preflight.manifest.iterrows()
    )
    status = build_collection_status(preflight, outcomes)
    summary = build_collection_summary(status)
    passes_finished = False
    derived_called = False

    def fake_collect(*_: object, **__: object):
        nonlocal passes_finished
        passes_finished = True
        return outcomes, status, summary, {
            "first_pass_finished_at_utc": "2026-07-29T01:00:00Z",
            "retry_pass_finished_at_utc": "2026-07-29T02:00:00Z",
        }

    def fake_derived(*_: object, **__: object):
        nonlocal derived_called
        assert passes_finished
        derived_called = True
        raise RuntimeError("stop after gating assertion")

    monkeypatch.setattr(pipeline, "preflight", lambda: preflight)
    monkeypatch.setattr(pipeline, "collect_manifest", fake_collect)
    monkeypatch.setattr(pipeline, "run_derived", fake_derived)

    result = pipeline.run()

    assert derived_called
    assert result.derived is None
    assert not result.preflight.universe.empty


def test_retry_remaining_security_is_excluded_from_derived_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    first = preflight.manifest.iloc[0]
    second = preflight.manifest.iloc[1]
    complete = _complete(0, str(first.security_id), str(first.current_ticker))
    failed = ManifestOutcome(
        row_number=1,
        security_id=str(second.security_id),
        current_ticker=str(second.current_ticker),
        provider_ticker=str(second.provider_ticker),
        period_start=str(second.period_start),
        period_end=str(second.period_end),
        isyatirim_status="FAILED",
        yfinance_status="FAILED",
        nominal_status="FAILED",
        isyatirim_raw_snapshot_id="failed-is",
        yfinance_raw_snapshot_id="failed-yf",
        nominal_snapshot_id="",
        failure_stage="ISYATIRIM",
        failure_class="TIME_BUDGET_EXCEEDED",
        failure_reason="retry budget exhausted",
        collection_pass=2,
        retry_recommended=True,
    )
    outcomes = (complete, failed)
    status = build_collection_status(preflight, outcomes)
    summary = build_collection_summary(status)
    captured_used: tuple[str, ...] = ()

    def fake_derived(
        _preflight: object,
        _outcomes: object,
        used_security_ids: tuple[str, ...],
        **_: object,
    ) -> object:
        nonlocal captured_used
        captured_used = used_security_ids
        raise RuntimeError("stop after scope assertion")

    monkeypatch.setattr(pipeline, "preflight", lambda: preflight)
    monkeypatch.setattr(
        pipeline,
        "collect_manifest",
        lambda *_args, **_kwargs: (outcomes, status, summary, {}),
    )
    monkeypatch.setattr(pipeline, "run_derived", fake_derived)

    result = pipeline.run()

    assert captured_used == (str(first.security_id),)
    assert result.used_security_ids == (str(first.security_id),)
    assert result.excluded_security_ids == (str(second.security_id),)


def test_verified_empty_both_provider_history_classifies_no_history(
    tmp_path: Path,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    row = preflight.manifest.iloc[0]
    outcome = ManifestOutcome(
        row_number=0,
        security_id=str(row.security_id),
        current_ticker=str(row.current_ticker),
        provider_ticker=str(row.provider_ticker),
        period_start=str(row.period_start),
        period_end=str(row.period_end),
        isyatirim_status=NO_DATA_IN_RANGE,
        yfinance_status="FAILED",
        nominal_status="FAILED",
        isyatirim_raw_snapshot_id="",
        yfinance_raw_snapshot_id="",
        nominal_snapshot_id="",
        failure_stage="YFINANCE",
        failure_class="RuntimeError",
        failure_reason="yFinance returned no rows for AAA",
        retry_recommended=False,
    )

    status = build_collection_status(preflight, [outcome])

    assert status.loc[0, "status"] == "NO_HISTORY"
    assert status.loc[0, "isyatirim_status"] == NO_DATA_IN_RANGE
    assert not status.loc[0, "retry_recommended"]


def test_empty_old_isyatirim_coverage_with_yfinance_data_is_partial_not_failed(
    tmp_path: Path,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    preflight = pipeline.preflight()
    row = preflight.manifest.iloc[0]
    outcome = ManifestOutcome(
        row_number=0,
        security_id=str(row.security_id),
        current_ticker=str(row.current_ticker),
        provider_ticker=str(row.provider_ticker),
        period_start=str(row.period_start),
        period_end=str(row.period_end),
        isyatirim_status=NO_DATA_IN_RANGE,
        yfinance_status="COMPLETE",
        nominal_status="COMPLETE",
        isyatirim_raw_snapshot_id="",
        yfinance_raw_snapshot_id="yf",
        nominal_snapshot_id="nominal",
        yfinance_dates=("2024-01-02",),
        retry_recommended=False,
    )

    status = build_collection_status(preflight, [outcome])

    assert status.loc[0, "status"] == "PARTIAL"
    assert status.loc[0, "failure_class"] == ""
    assert not status.loc[0, "retry_recommended"]


@pytest.mark.parametrize("workers", [1, 3])
def test_worker_count_preserves_manifest_order_and_unique_security_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workers: int,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    pipeline.config = replace(
        pipeline.config,
        security_worker_count=workers,
        global_request_interval_seconds=0,
    )
    preflight = pipeline.preflight()
    security_order = list(preflight.universe["security_id"].astype(str))
    manifest_groups = {
        str(key): group.sort_index()
        for key, group in preflight.manifest.groupby("security_id", sort=False)
    }
    eligible = {
        security_id: tuple(map(int, manifest_groups[security_id].index))
        for security_id in security_order
    }
    active: set[str] = set()
    seen: list[str] = []

    def fake_collect(
        _writer: object,
        row_number: int,
        row: pd.Series,
        **_: object,
    ) -> ManifestOutcome:
        security_id = str(row["security_id"])
        seen.append(security_id)
        return _complete(row_number, security_id, str(row["current_ticker"]))

    def fake_prepare_security(
        _preflight: object,
        _limiter: object,
        security_id: str,
        security_position: int,
        rows: pd.DataFrame,
        **kwargs: object,
    ) -> PreparedSecurity:
        assert security_id not in active
        active.add(security_id)
        seen.append(security_id)
        prepared_rows = tuple(
            PreparedManifestRow(
                row_number=int(row_number),
                row=row.to_dict(),
                prepared=None,
                error=None,
                collection_pass=int(kwargs["collection_pass"]),
                security_position=security_position,
                security_started_at=0.0,
                security_budget_seconds=float(kwargs["security_budget_seconds"]),
                elapsed_seconds=0.0,
            )
            for row_number, row in rows.iterrows()
        )
        active.remove(security_id)
        return PreparedSecurity(security_id, security_position, 0.0, prepared_rows)

    def fake_commit(_writer: object, item: PreparedManifestRow) -> ManifestOutcome:
        return _complete(
            item.row_number,
            str(item.row["security_id"]),
            str(item.row["current_ticker"]),
        )

    monkeypatch.setattr(pipeline, "_collect_manifest_row", fake_collect)
    if workers == 3:
        # Remove the instance override from the worker-count compatibility gate
        # and patch the class-level methods used by parallel preparation/commit.
        del pipeline.__dict__["_collect_manifest_row"]
        monkeypatch.setattr(pipeline, "_prepare_security", fake_prepare_security)
        monkeypatch.setattr(pipeline, "_commit_prepared_manifest_row", fake_commit)
    limiter = GlobalRequestLimiter(
        max_concurrency=2, request_interval_seconds=0
    )

    results = list(
        pipeline._collection_pass_results(
            preflight,
            object(),
            limiter,
            security_order,
            security_order,
            manifest_groups,
            eligible,
            collection_pass=1,
            security_budget_seconds=1200,
            refresh=False,
        )
    )

    assert [security_id for _, security_id, _, _ in results] == security_order
    assert sorted(seen) == sorted(security_order)
    assert len(seen) == len(set(seen))
    outcomes = tuple(item for *_, batch in results for item in batch)
    status = build_collection_status(preflight, outcomes)
    assert status["security_id"].tolist() == security_order
    assert status["status"].eq("COMPLETE").all()


def test_rolling_workers_submit_next_security_before_slow_predecessor_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, _ = _fixture(tmp_path)
    pipeline.config = replace(
        pipeline.config,
        security_worker_count=2,
        global_request_interval_seconds=0,
    )
    base = pipeline.preflight()
    third_id = generate_security_id("CCC")
    third_universe = base.universe.iloc[[0]].copy()
    third_universe.loc[:, "security_id"] = third_id
    third_universe.loc[:, "current_ticker"] = "CCC"
    third_manifest = base.manifest.iloc[[0]].copy()
    third_manifest.loc[:, "security_id"] = third_id
    third_manifest.loc[:, "current_ticker"] = "CCC"
    third_manifest.loc[:, "provider_ticker"] = "CCC"
    preflight = replace(
        base,
        universe=pd.concat([base.universe, third_universe], ignore_index=True),
        manifest=pd.concat([base.manifest, third_manifest], ignore_index=True),
    )
    security_order = list(preflight.universe["security_id"].astype(str))
    manifest_groups = {
        str(key): group.sort_index()
        for key, group in preflight.manifest.groupby("security_id", sort=False)
    }
    eligible = {
        security_id: tuple(map(int, manifest_groups[security_id].index))
        for security_id in security_order
    }
    third_started = threading.Event()

    def fake_prepare_security(
        _preflight: object,
        _limiter: object,
        security_id: str,
        security_position: int,
        rows: pd.DataFrame,
        **kwargs: object,
    ) -> PreparedSecurity:
        if security_id == security_order[0]:
            assert third_started.wait(timeout=2)
        elif security_id == security_order[2]:
            third_started.set()
        prepared_rows = tuple(
            PreparedManifestRow(
                row_number=int(row_number),
                row=row.to_dict(),
                prepared=None,
                error=None,
                collection_pass=int(kwargs["collection_pass"]),
                security_position=security_position,
                security_started_at=0.0,
                security_budget_seconds=float(kwargs["security_budget_seconds"]),
                elapsed_seconds=0.0,
            )
            for row_number, row in rows.iterrows()
        )
        return PreparedSecurity(security_id, security_position, 0.0, prepared_rows)

    def fake_commit(_writer: object, item: PreparedManifestRow) -> ManifestOutcome:
        return _complete(
            item.row_number,
            str(item.row["security_id"]),
            str(item.row["current_ticker"]),
        )

    monkeypatch.setattr(pipeline, "_prepare_security", fake_prepare_security)
    monkeypatch.setattr(pipeline, "_commit_prepared_manifest_row", fake_commit)
    limiter = GlobalRequestLimiter(max_concurrency=2, request_interval_seconds=0)

    results = list(
        pipeline._collection_pass_results(
            preflight,
            object(),
            limiter,
            security_order,
            security_order,
            manifest_groups,
            eligible,
            collection_pass=1,
            security_budget_seconds=1200,
            refresh=False,
        )
    )

    assert third_started.is_set()
    assert [security_id for _, security_id, _, _ in results] == security_order
