from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.data.snapshot_store import SnapshotRequest
from src.features.catalog import BASELINE_V1_FEATURES, catalog_file_checksum
from src.features.input_assembler import FeatureInputAssembler, FeatureInputError
from src.features.pipeline import BaselineFeaturePipeline, validate_feature_snapshot
from tests.feature_snapshot_support import make_bundle


def _with_extra_yfinance_row(bundle, row_date: pd.Timestamp):
    yfinance = bundle.store.read_dataframe(bundle.yfinance_ids[0])
    extra_yfinance = yfinance.iloc[[0]].copy()
    extra_yfinance["date"] = row_date
    yfinance = pd.concat([yfinance, extra_yfinance], ignore_index=True)
    start = pd.to_datetime(yfinance["date"]).min().date()
    end = pd.to_datetime(yfinance["date"]).max().date()
    yfinance_id = bundle.store.save_dataframe(
        yfinance,
        SnapshotRequest(
            source="yfinance",
            dataset_type="equity_history",
            ticker_or_instrument="BIST_BATCH",
            request_start_date=start,
            request_end_date=end,
            request_parameters={"auto_adjust": False, "actions": True},
            layer="raw",
            identity_columns=("ticker", "date"),
        ),
    ).metadata.snapshot_id

    identity = bundle.store.read_dataframe(bundle.identity_id)
    extra_identity = identity.iloc[[0]].copy()
    extra_identity["date"] = row_date
    identity = pd.concat([identity, extra_identity], ignore_index=True)
    identity_id = bundle.store.save_dataframe(
        identity,
        SnapshotRequest(
            source="security_identity",
            dataset_type="nominal_ohlc",
            ticker_or_instrument="BIST_BATCH",
            request_start_date=start,
            request_end_date=end,
            request_parameters={
                "ticker_mapping_version": "test-map-v1",
                "ticker_mapping_checksum": "test-map-checksum",
            },
            layer="derived",
            identity_columns=("security_id", "date"),
        ),
    ).metadata.snapshot_id
    return replace(
        bundle,
        yfinance_ids=(yfinance_id,),
        identity_id=identity_id,
    )


def _run(bundle, *, code_sha: str = "a" * 40):
    return BaselineFeaturePipeline(
        bundle.config,
        snapshot_store=bundle.store,
        code_commit_sha=code_sha,
    ).run(
        yfinance_raw_snapshot_ids=bundle.yfinance_ids,
        isyatirim_raw_snapshot_ids=bundle.isyatirim_ids,
        identity_snapshot_id=bundle.identity_id,
        xu100_snapshot_id=bundle.xu100_id,
        calendar_snapshot_id=bundle.calendar_id,
    )


def test_pipeline_emits_exact_32_feature_schema_and_metadata(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    result = _run(bundle)

    assert list(result.frame.columns) == [
        "security_id",
        "prediction_date",
        *BASELINE_V1_FEATURES,
    ]
    assert len(result.frame) == 20 * 30
    assert not np.isinf(result.frame.loc[:, BASELINE_V1_FEATURES].to_numpy()).any()
    assert result.quality_summary["feature_name"].tolist() == list(BASELINE_V1_FEATURES)
    assert result.snapshot.revision_context["feature_count"] == 32
    assert result.snapshot.revision_context["ticker_mapping_version"] == "test-map-v1"
    assert result.snapshot.revision_context["global_calendar_checksum"]
    validate_feature_snapshot(
        bundle.store,
        result.snapshot.snapshot_id,
        expected_catalog_checksum=catalog_file_checksum(),
    )


def test_pipeline_projects_raw_actions_nominal_fields_and_identifiers_out(tmp_path) -> None:
    bundle = make_bundle(tmp_path, action_value=2.5)
    result = _run(bundle)
    forbidden_fragments = ("nominal", "dividend", "split", "ticker", "checksum", "label")

    for column in result.frame.columns[2:]:
        assert not any(fragment in column.lower() for fragment in forbidden_fragments)


def test_identity_security_id_is_required_without_ticker_fallback(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    identity = bundle.store.read_dataframe(bundle.identity_id).drop(columns="security_id")
    bad_id = bundle.store.save_dataframe(
        identity,
        SnapshotRequest(
            source="security_identity",
            dataset_type="nominal_ohlc",
            ticker_or_instrument="BAD_BATCH",
            request_start_date="2024-01-02",
            request_end_date="2024-02-12",
            layer="derived",
        ),
    ).metadata.snapshot_id

    with pytest.raises(FeatureInputError, match="security_id"):
        FeatureInputAssembler(bundle.store).assemble(
            yfinance_raw_snapshot_ids=bundle.yfinance_ids,
            isyatirim_raw_snapshot_ids=bundle.isyatirim_ids,
            identity_snapshot_id=bad_id,
            xu100_snapshot_id=bundle.xu100_id,
            calendar_snapshot_id=bundle.calendar_id,
        )


def test_cross_sectional_features_are_computed_before_any_label_join(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    result = _run(bundle)
    final_day = result.frame["prediction_date"].max()
    daily = result.frame.loc[result.frame["prediction_date"].eq(final_day)]

    assert daily["cs_ret_1_rank"].notna().sum() == 20
    assert daily["cs_ret_1_rank"].min() == 0.0
    assert daily["cs_ret_1_rank"].max() == 1.0


def test_feature_quality_summary_is_compact_not_per_row_reason_columns(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    result = _run(bundle)

    assert len(result.quality_summary) == 32
    assert set(result.quality_summary.columns) == {
        "feature_name",
        "valid",
        "missing",
        "warmup",
        "source_missing",
        "invalid_math",
        "xu100_missing",
        "cross_section_insufficient",
        "infinite_replaced",
    }
    cs_ret_1 = result.quality_summary.set_index("feature_name").loc["cs_ret_1_rank"]
    assert cs_ret_1["warmup"] == 20
    assert cs_ret_1["source_missing"] == 0
    assert not any(column.startswith("missing_reason_") for column in result.frame.columns)


def test_yfinance_non_session_row_within_calendar_bounds_is_excluded_and_audited(
    tmp_path,
) -> None:
    bundle = make_bundle(tmp_path)
    bundle = _with_extra_yfinance_row(bundle, pd.Timestamp("2024-01-06"))

    assembly = FeatureInputAssembler(bundle.store).assemble(
        yfinance_raw_snapshot_ids=bundle.yfinance_ids,
        isyatirim_raw_snapshot_ids=bundle.isyatirim_ids,
        identity_snapshot_id=bundle.identity_id,
        xu100_snapshot_id=bundle.xu100_id,
        calendar_snapshot_id=bundle.calendar_id,
    )
    result = _run(bundle)

    assert len(assembly.frame) == 20 * 30
    assert assembly.excluded_non_session_rows.to_dict(orient="records") == [
        {
            "observed_ticker": "T000",
            "prediction_date": pd.Timestamp("2024-01-06"),
            "exclusion_reason": (
                "YFINANCE_NON_SESSION_WITHIN_VERIFIED_CALENDAR_BOUNDS"
            ),
        }
    ]
    audit = result.snapshot.revision_context[
        "excluded_non_session_provider_rows"
    ]
    assert audit["row_count"] == 1
    assert audit["ticker_count"] == 1
    assert audit["date_counts"] == {"2024-01-06": 1}
    assert len(audit["checksum"]) == 64


def test_yfinance_row_outside_calendar_bounds_remains_fail_closed(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    bundle = _with_extra_yfinance_row(bundle, pd.Timestamp("2024-03-01"))

    with pytest.raises(FeatureInputError, match="outside verified global calendar bounds"):
        FeatureInputAssembler(bundle.store).assemble(
            yfinance_raw_snapshot_ids=bundle.yfinance_ids,
            isyatirim_raw_snapshot_ids=bundle.isyatirim_ids,
            identity_snapshot_id=bundle.identity_id,
            xu100_snapshot_id=bundle.xu100_id,
            calendar_snapshot_id=bundle.calendar_id,
        )
