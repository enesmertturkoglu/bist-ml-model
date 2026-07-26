"""Central configuration for market-data collection and snapshot storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any


class SnapshotStatus(str, Enum):
    """Lifecycle states recorded for every snapshot attempt."""

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True)
class ProviderRequestConfig:
    """Provider access settings kept out of collection code."""

    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    request_delay_seconds: float = 0.0
    minimum_chunk_months: int | None = None


@dataclass(frozen=True)
class MarketDataConfig:
    """Filesystem, date, checksum and provider settings for data collection."""

    data_root: Path = Path("data")
    operational_cache_root: Path = Path(".cache/market_data")
    raw_directory_name: str = "raw"
    derived_directory_name: str = "derived"
    manifest_directory_name: str = "manifests"
    snapshot_manifest_filename: str = "snapshots.jsonl"
    revision_log_filename: str = "provider_revisions.jsonl"
    model_start_date: date = date(2020, 3, 13)
    # The exact warm-up horizon is intentionally not a product decision here.
    # Collection commands must receive an explicit start date while this is None.
    warmup_start_date: date | None = None
    checksum_algorithm: str = "sha256"
    snapshot_statuses: tuple[str, ...] = tuple(status.value for status in SnapshotStatus)
    isyatirim: ProviderRequestConfig = field(
        default_factory=lambda: ProviderRequestConfig(
            timeout_seconds=60.0,
            max_retries=5,
            retry_backoff_seconds=1.0,
            request_delay_seconds=1.0,
            minimum_chunk_months=3,
        )
    )
    yfinance: ProviderRequestConfig = field(
        default_factory=lambda: ProviderRequestConfig(
            timeout_seconds=30.0,
            max_retries=5,
            retry_backoff_seconds=3.0,
        )
    )

    @property
    def raw_data_root(self) -> Path:
        return self.data_root / self.raw_directory_name

    @property
    def derived_data_root(self) -> Path:
        return self.data_root / self.derived_directory_name

    @property
    def manifest_root(self) -> Path:
        return self.data_root / self.manifest_directory_name

    @property
    def isyatirim_cache_root(self) -> Path:
        return self.operational_cache_root / "isyatirim"

    @property
    def snapshot_manifest_path(self) -> Path:
        return self.manifest_root / self.snapshot_manifest_filename

    @property
    def revision_log_path(self) -> Path:
        return self.manifest_root / self.revision_log_filename

    def checksum(self) -> str:
        """Return a stable checksum of all effective configuration values."""

        payload = _json_ready(asdict(self))
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.new(self.checksum_algorithm, encoded).hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value
