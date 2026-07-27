"""End-to-end verified baseline_v1 feature snapshot orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from src.config import MarketDataConfig
from src.data.collectors import current_code_commit_sha
from src.data.snapshot_store import SnapshotMetadata, SnapshotRequest, SnapshotStore
from src.features.baseline_v1 import compute_baseline_features
from src.features.calendar_alignment import align_to_global_calendar
from src.features.catalog import (
    BASELINE_V1_CROSS_SECTIONAL_FEATURES,
    BASELINE_V1_FEATURES,
    catalog_file_checksum,
)
from src.features.cross_sectional import add_cross_sectional_features
from src.features.input_assembler import FeatureInputAssembler
from src.features.quality import build_quality_summary


class FeaturePipelineError(RuntimeError):
    """Raised when baseline_v1 cannot be emitted under the binding contract."""


@dataclass(frozen=True)
class FeaturePipelineResult:
    snapshot: SnapshotMetadata
    frame: pd.DataFrame
    quality_summary: pd.DataFrame


class BaselineFeaturePipeline:
    """Assemble verified sources, compute exactly 32 features, persist lineage."""

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        code_commit_sha: str | None = None,
        catalog_path: str | Path = Path("FEATURE_CATALOG.md"),
    ) -> None:
        self.config = config or MarketDataConfig()
        self.snapshot_store = snapshot_store or SnapshotStore(self.config)
        self.code_commit_sha = code_commit_sha or current_code_commit_sha()
        self.catalog_path = Path(catalog_path)

    def run(
        self,
        *,
        yfinance_raw_snapshot_ids: Sequence[str],
        isyatirim_raw_snapshot_ids: Sequence[str],
        identity_snapshot_id: str,
        xu100_snapshot_id: str,
        calendar_snapshot_id: str,
    ) -> FeaturePipelineResult:
        assembly = FeatureInputAssembler(self.snapshot_store).assemble(
            yfinance_raw_snapshot_ids=yfinance_raw_snapshot_ids,
            isyatirim_raw_snapshot_ids=isyatirim_raw_snapshot_ids,
            identity_snapshot_id=identity_snapshot_id,
            xu100_snapshot_id=xu100_snapshot_id,
            calendar_snapshot_id=calendar_snapshot_id,
        )
        aligned = align_to_global_calendar(
            assembly.frame, assembly.calendar, assembly.benchmark
        )
        baseline = compute_baseline_features(aligned)
        actual_mask = baseline.frame["_source_row_present"].astype(bool)
        actual = baseline.frame.loc[actual_mask].copy()
        cross = add_cross_sectional_features(
            actual,
            minimum_securities=self.config.feature.minimum_cross_section_size,
        )
        reason_masks: dict[str, dict[str, pd.Series]] = {}
        actual_indices = actual.index
        for feature, masks in baseline.reason_masks.items():
            reason_masks[feature] = {
                reason: mask.loc[actual_indices] for reason, mask in masks.items()
            }
        for feature in BASELINE_V1_CROSS_SECTIONAL_FEATURES:
            source = {
                "cs_ret_1_rank": "ret_1",
                "cs_ret_5_rank": "ret_5",
                "cs_relative_ret_5_rank": "relative_ret_5",
                "cs_volume_anomaly_rank": "tl_volume_zscore_20",
            }[feature]
            insufficient = cross.insufficient_masks[feature]
            source_reasons = reason_masks[source]
            reason_masks[feature] = {
                "warmup": source_reasons["warmup"],
                "source_missing": source_reasons["source_missing"],
                "invalid_math": source_reasons["invalid_math"],
                "xu100_missing": source_reasons["xu100_missing"],
                "cross_section_insufficient": insufficient,
                "infinite_replaced": source_reasons["infinite_replaced"],
            }
        output = cross.frame.loc[
            :, ["security_id", "prediction_date", *BASELINE_V1_FEATURES]
        ].sort_values(["security_id", "prediction_date"])
        output = output.reset_index(drop=True)
        normalized_masks: dict[str, dict[str, pd.Series]] = {}
        output_order = cross.frame.loc[
            actual_indices, ["security_id", "prediction_date"]
        ].sort_values(["security_id", "prediction_date"]).index
        for feature, masks in reason_masks.items():
            normalized_masks[feature] = {
                reason: mask.loc[output_order].reset_index(drop=True)
                for reason, mask in masks.items()
            }
        _validate_feature_output(output)
        quality = build_quality_summary(output, normalized_masks)
        input_metadata = assembly.metadata
        checksum_by_id = {
            item.snapshot_id: item.content_checksum for item in input_metadata
        }
        catalog_checksum = catalog_file_checksum(
            self.catalog_path, self.config.checksum_algorithm
        )
        feature_config_checksum = self.config.feature.checksum(
            self.config.checksum_algorithm
        )
        context = {
            "input_snapshot_ids": [item.snapshot_id for item in input_metadata],
            "input_content_checksums": checksum_by_id,
            "xu100_snapshot_id": xu100_snapshot_id,
            "xu100_checksum": checksum_by_id[xu100_snapshot_id],
            "global_calendar_snapshot_id": calendar_snapshot_id,
            "global_calendar_checksum": checksum_by_id[calendar_snapshot_id],
            "ticker_mapping_version": assembly.mapping_version,
            "ticker_mapping_checksum": assembly.mapping_checksum,
            "feature_catalog_version": self.config.feature.feature_catalog_version,
            "feature_catalog_file_sha256": catalog_checksum,
            "feature_config_checksum": feature_config_checksum,
            "market_data_config_checksum": self.config.checksum(),
            "code_commit_sha": self.code_commit_sha,
            "feature_count": len(BASELINE_V1_FEATURES),
            "feature_names": list(BASELINE_V1_FEATURES),
            "quality_summary": quality.to_dict(orient="records"),
        }
        request = SnapshotRequest(
            source="features",
            dataset_type=self.config.feature.feature_dataset_type,
            ticker_or_instrument="BIST_PANEL",
            request_start_date=pd.to_datetime(output["prediction_date"]).min().date(),
            request_end_date=pd.to_datetime(output["prediction_date"]).max().date(),
            request_parameters={
                "feature_set_id": self.config.feature.feature_set_id,
                "feature_catalog_version": self.config.feature.feature_catalog_version,
                "minimum_cross_section_size": self.config.feature.minimum_cross_section_size,
            },
            provider_library_version="baseline-feature-pipeline-v1",
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=tuple(item.snapshot_id for item in input_metadata),
            identity_columns=("security_id", "prediction_date"),
            revision_context=context,
        )
        written = self.snapshot_store.save_dataframe(output, request)
        return FeaturePipelineResult(written.metadata, output, quality)


def _validate_feature_output(frame: pd.DataFrame) -> None:
    expected = ["security_id", "prediction_date", *BASELINE_V1_FEATURES]
    if list(frame.columns) != expected:
        raise FeaturePipelineError("feature output does not have the exact baseline_v1 order")
    if len(BASELINE_V1_FEATURES) != 32:
        raise FeaturePipelineError("baseline_v1 must contain exactly 32 features")
    if frame.empty:
        raise FeaturePipelineError("feature output cannot be empty")
    if frame[["security_id", "prediction_date"]].isna().any().any():
        raise FeaturePipelineError("feature identifiers cannot be missing")
    if frame.duplicated(["security_id", "prediction_date"]).any():
        raise FeaturePipelineError("duplicate feature key")
    numeric = frame.loc[:, BASELINE_V1_FEATURES].apply(pd.to_numeric, errors="coerce")
    if np.isinf(numeric.to_numpy(dtype="float64")).any():
        raise FeaturePipelineError("feature output contains infinity")


def validate_feature_snapshot(
    snapshot_store: SnapshotStore,
    snapshot_id: str,
    *,
    expected_catalog_checksum: str,
) -> SnapshotMetadata:
    """Verify physical integrity, exact schema and binding catalog checksum."""

    metadata = snapshot_store.get_snapshot(snapshot_id)
    if not snapshot_store.is_usable(metadata):
        raise FeaturePipelineError("feature snapshot is not verified COMPLETE")
    if (metadata.source, metadata.dataset_type, metadata.layer) != (
        "features",
        "baseline_v1",
        "derived",
    ):
        raise FeaturePipelineError("snapshot is not features/baseline_v1/derived")
    context = metadata.revision_context
    if context.get("feature_catalog_file_sha256") != expected_catalog_checksum:
        raise FeaturePipelineError("feature catalog checksum mismatch")
    if context.get("feature_names") != list(BASELINE_V1_FEATURES):
        raise FeaturePipelineError("feature order metadata mismatch")
    frame = snapshot_store.read_dataframe(metadata)
    expected_columns = ["security_id", "prediction_date", *BASELINE_V1_FEATURES]
    if set(frame.columns) != set(expected_columns):
        raise FeaturePipelineError("feature snapshot schema mismatch")
    _validate_feature_output(frame.loc[:, expected_columns])
    return metadata
