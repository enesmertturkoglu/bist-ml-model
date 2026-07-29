from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
from pathlib import Path

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
    atomic_write_text,
    build_collection_status,
    build_collection_summary,
    build_mapping_review,
)
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
