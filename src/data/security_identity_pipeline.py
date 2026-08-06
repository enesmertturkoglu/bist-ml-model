"""Verified nominal-snapshot orchestration for security identity snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from src.config import MarketDataConfig
from src.data.security_identity import TickerMapping, merge_security_history
from src.data.snapshot_store import (
    SnapshotMetadata,
    SnapshotRequest,
    SnapshotStore,
    SnapshotWriteResult,
)


NOMINAL_IDENTITY_INPUT_COLUMNS = (
    "ticker",
    "date",
    "yf_nominal_open",
    "yf_nominal_high",
    "yf_nominal_low",
    "yf_nominal_close",
)


class SecurityIdentityInputError(ValueError):
    """Raised when nominal lineage is incomplete or cannot be trusted."""


@dataclass(frozen=True)
class SecurityIdentityRunResult:
    snapshot: SnapshotWriteResult
    frame: pd.DataFrame
    summary: dict[str, Any]


class SecurityIdentityPipeline:
    """Merge verified nominal ticker snapshots into immutable security series."""

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
        nominal_snapshot_ids: Sequence[str],
        mapping: TickerMapping,
    ) -> SecurityIdentityRunResult:
        if not nominal_snapshot_ids:
            raise SecurityIdentityInputError(
                "at least one nominal snapshot is required"
            )
        if len(set(map(str, nominal_snapshot_ids))) != len(nominal_snapshot_ids):
            raise SecurityIdentityInputError("nominal snapshot IDs must be unique")
        metadata = [self._verify_nominal(value) for value in nominal_snapshot_ids]
        frames = [self._read_nominal(value) for value in metadata]
        combined = pd.concat(frames, ignore_index=True, sort=False)
        identity = merge_security_history(combined, mapping)
        if identity.empty:
            raise SecurityIdentityInputError(
                "mapping validity removed every nominal input row"
            )

        input_ids = tuple(value.snapshot_id for value in metadata)
        input_checksums = tuple(value.content_checksum for value in metadata)
        input_checksum_by_id = {
            value.snapshot_id: value.content_checksum for value in metadata
        }
        security_ids = sorted(map(str, identity["security_id"].unique()))
        revision_context = {
            "input_snapshot_ids": list(input_ids),
            "input_content_checksums": input_checksum_by_id,
            "identity_version": "d027-v1",
            "ticker_mapping_version": mapping.version,
            "ticker_mapping_checksum": mapping.checksum,
            "code_commit_sha": self.code_commit_sha,
        }
        request = SnapshotRequest(
            source="security_identity",
            dataset_type="nominal_ohlc",
            ticker_or_instrument=(
                security_ids[0] if len(security_ids) == 1 else "BIST_BATCH"
            ),
            request_start_date=min(value.request_start_date for value in metadata),
            request_end_date=max(value.request_end_date for value in metadata),
            request_parameters={
                "identity_version": "d027-v1",
                "ticker_mapping_version": mapping.version,
                "ticker_mapping_checksum": mapping.checksum,
                "input_snapshot_ids": list(input_ids),
                "input_snapshot_checksums": list(input_checksums),
            },
            provider_library_version="derived-security-identity-v1",
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=input_ids,
            identity_columns=("security_id", "date"),
            revision_context=revision_context,
        )
        written = self.snapshot_store.save_dataframe(identity, request)
        statuses = (
            identity["ticker_mapping_status"].astype(str).value_counts().sort_index()
        )
        summary = {
            "row_count": int(len(identity)),
            "security_count": int(identity["security_id"].nunique()),
            "observed_ticker_count": int(identity["observed_ticker"].nunique()),
            "mapping_status_counts": {
                str(key): int(value) for key, value in statuses.items()
            },
            "ticker_mapping_version": mapping.version,
            "ticker_mapping_checksum": mapping.checksum,
        }
        return SecurityIdentityRunResult(written, identity, summary)

    def _verify_nominal(self, snapshot_id: str) -> SnapshotMetadata:
        metadata = self.snapshot_store.get_snapshot(snapshot_id)
        if not self.snapshot_store.is_usable(metadata):
            raise SecurityIdentityInputError(
                f"nominal snapshot {snapshot_id} is not verified COMPLETE"
            )
        if (metadata.source, metadata.dataset_type, metadata.layer) != (
            "yfinance",
            "nominal_ohlc",
            "derived",
        ):
            raise SecurityIdentityInputError(
                f"snapshot {snapshot_id} is not yfinance/nominal_ohlc/derived"
            )
        if len(metadata.input_snapshot_ids) != 1:
            raise SecurityIdentityInputError(
                f"nominal snapshot {snapshot_id} must reference one raw snapshot"
            )
        raw = self.snapshot_store.get_snapshot(metadata.input_snapshot_ids[0])
        if not self.snapshot_store.is_usable(raw) or (
            raw.source,
            raw.dataset_type,
            raw.layer,
        ) != ("yfinance", "equity_history", "raw"):
            raise SecurityIdentityInputError(
                f"nominal snapshot {snapshot_id} raw lineage is not verified"
            )
        return metadata

    def _read_nominal(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        missing = set(NOMINAL_IDENTITY_INPUT_COLUMNS).difference(frame.columns)
        if missing:
            raise SecurityIdentityInputError(
                f"nominal snapshot {metadata.snapshot_id} fields missing: {sorted(missing)}"
            )
        result = frame.loc[:, NOMINAL_IDENTITY_INPUT_COLUMNS].copy()
        result["date"] = pd.to_datetime(result["date"]).dt.normalize()
        return result
