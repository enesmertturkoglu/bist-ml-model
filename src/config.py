"""Central configuration for market-data collection, cleaning and storage."""

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
class CleaningConfig:
    """D022/D023/D026 rules stable across auditable cleaning runs."""

    upper_limit_margin: str = "0.10"
    instrument_type: str = "EQUITY"
    limit_price_relative_tolerance: float = 1e-12
    limit_price_absolute_tolerance: float = 1e-8
    adjustment_factor_relative_tolerance: float = 1e-4
    adjustment_factor_absolute_tolerance: float = 5e-5
    cross_source_price_absolute_tolerance: float = 1e-8
    corporate_action_horizon_days: int = 3
    clean_dataset_type: str = "market_data_eligibility"
    cleaning_version: str = "d022-d023-tick-size-v2"
    reason_priority: tuple[str, ...] = (
        "NO_OPEN",
        "NO_TRADE",
        "INVALID_OHLC",
        "NO_PREVIOUS_CLOSE",
        "SPECIAL_MARGIN_OR_CORPORATE_ACTION",
        "LIMIT_OPEN",
        "CORPORATE_ACTION_WINDOW",
        "PRICE_STEP_UNAVAILABLE",
    )

    def checksum(self, algorithm: str = "sha256") -> str:
        """Return a stable checksum of the effective cleaning contract."""

        encoded = json.dumps(
            _json_ready(asdict(self)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.new(algorithm, encoded).hexdigest()


@dataclass(frozen=True)
class LabelConfig:
    """D011-D014 label contract kept stable and auditable."""

    target_return: str = "0.05"
    horizon_days: int = 3
    instrument_type: str = "EQUITY"
    label_dataset_type: str = "three_day_target"
    label_version: str = "d011-d014-d020-d023-d024-d026-v1"

    def checksum(self, algorithm: str = "sha256") -> str:
        """Return a stable checksum of the effective label contract."""

        encoded = json.dumps(
            _json_ready(asdict(self)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.new(algorithm, encoded).hexdigest()


@dataclass(frozen=True)
class MarketDataConfig:
    """Filesystem, date, checksum and provider settings for data collection."""

    data_root: Path = Path("data")
    operational_cache_root: Path = Path(".cache/market_data")
    tick_size_reference_path: Path = Path(
        "reference_data/bist_equity_tick_sizes_v1.csv"
    )
    security_ticker_mapping_path: Path = Path(
        "reference_data/bist_security_ticker_map_v1.csv"
    )
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
    cleaning: CleaningConfig = field(default_factory=CleaningConfig)
    label: LabelConfig = field(default_factory=LabelConfig)
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
