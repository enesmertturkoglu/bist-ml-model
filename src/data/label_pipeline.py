"""Verified clean-snapshot orchestration for immutable label snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.config import MarketDataConfig
from src.data.labels import build_three_day_target_labels, summarize_labels
from src.data.price_limits import PriceStepTable
from src.data.snapshot_store import SnapshotRequest, SnapshotStore, SnapshotWriteResult


class LabelInputError(ValueError):
    """Raised when a source clean snapshot is not safe for label generation."""


@dataclass(frozen=True)
class LabelRunResult:
    snapshot: SnapshotWriteResult
    frame: pd.DataFrame
    summary: dict[str, Any]
    exception_examples: pd.DataFrame


class LabelGenerationPipeline:
    """Read one verified clean snapshot and write one derived label snapshot."""

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        code_commit_sha: str = "unknown",
    ) -> None:
        self.config = config or MarketDataConfig()
        self.snapshot_store = snapshot_store or SnapshotStore(self.config)
        self.code_commit_sha = code_commit_sha or "unknown"

    def run(
        self,
        clean_snapshot_id: str,
        price_steps: PriceStepTable,
        *,
        exception_limit: int = 20,
    ) -> LabelRunResult:
        metadata = self.snapshot_store.get_snapshot(clean_snapshot_id)
        if not self.snapshot_store.is_usable(metadata):
            raise LabelInputError(
                f"clean snapshot {clean_snapshot_id} is not verified COMPLETE"
            )
        expected = (
            "cleaning",
            self.config.cleaning.clean_dataset_type,
            "derived",
        )
        actual = (metadata.source, metadata.dataset_type, metadata.layer)
        if actual != expected:
            raise LabelInputError(
                f"snapshot {clean_snapshot_id} is not "
                f"{expected[0]}/{expected[1]}/{expected[2]}"
            )

        clean = self.snapshot_store.read_dataframe(metadata)
        if "prediction_date" not in clean.columns:
            raise LabelInputError("clean snapshot has no prediction_date field")
        prediction_dates = pd.to_datetime(clean["prediction_date"]).dt.normalize()
        clean = clean.loc[
            prediction_dates.ge(pd.Timestamp(self.config.model_start_date))
        ].copy()
        if clean.empty:
            raise LabelInputError(
                "clean snapshot has no rows in the D020 model period"
            )

        labels = build_three_day_target_labels(
            clean,
            price_steps,
            config=self.config.label,
        )
        label_config_checksum = self.config.label.checksum(
            self.config.checksum_algorithm
        )
        labels["input_clean_snapshot_id"] = metadata.snapshot_id
        labels["input_clean_snapshot_checksum"] = metadata.content_checksum
        labels["label_config_checksum"] = label_config_checksum
        labels["label_code_commit_sha"] = self.code_commit_sha
        labels["label_version"] = self.config.label.label_version
        self._guard_label_schema(labels)

        request = SnapshotRequest(
            source="labels",
            dataset_type=self.config.label.label_dataset_type,
            ticker_or_instrument=metadata.ticker_or_instrument,
            request_start_date=metadata.request_start_date,
            request_end_date=metadata.request_end_date,
            request_parameters={
                "label_version": self.config.label.label_version,
                "label_config_checksum": label_config_checksum,
                "target_return": self.config.label.target_return,
                "horizon_days": self.config.label.horizon_days,
                "instrument_type": self.config.label.instrument_type,
                "input_clean_snapshot_id": metadata.snapshot_id,
                "input_clean_snapshot_checksum": metadata.content_checksum,
                "price_step_table_checksum": price_steps.checksum(
                    self.config.checksum_algorithm
                ),
                "tick_rule_set_ids": list(price_steps.rule_set_ids),
            },
            provider_library_version="derived-labels-v1",
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=(metadata.snapshot_id,),
            identity_columns=("ticker", "prediction_date"),
        )
        written = self.snapshot_store.save_dataframe(labels, request)
        summary = summarize_labels(labels)
        exceptions = labels.loc[labels["label_status"].eq("NA")].head(
            max(0, exception_limit)
        )
        return LabelRunResult(
            snapshot=written,
            frame=labels,
            summary=summary,
            exception_examples=exceptions.reset_index(drop=True),
        )

    @staticmethod
    def _guard_label_schema(frame: pd.DataFrame) -> None:
        forbidden = {
            "feature",
            "prediction",
            "model_version",
            "yf_provider_open",
            "yf_provider_high",
            "yf_provider_low",
            "yf_provider_close",
            "yf_future_split_factor",
        }
        present = forbidden.intersection(frame.columns)
        if present:
            raise RuntimeError(
                f"label snapshot contains forbidden fields: {sorted(present)}"
            )
