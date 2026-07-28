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
class FeatureConfig:
    """D028 baseline feature contract and deterministic quality thresholds."""

    feature_set_id: str = "baseline_v1"
    feature_catalog_version: str = "baseline_v1"
    feature_dataset_type: str = "baseline_v1"
    minimum_cross_section_size: int = 20

    def checksum(self, algorithm: str = "sha256") -> str:
        """Return a stable checksum of the effective feature contract."""

        encoded = json.dumps(
            _json_ready(asdict(self)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.new(algorithm, encoded).hexdigest()


@dataclass(frozen=True)
class ModelTrainingConfig:
    """D030 LightGBM and walk-forward contract kept in one auditable config."""

    model_family: str = "lightgbm"
    training_window: str = "expanding"
    validation_sessions: int = 60
    test_sessions: int = 20
    minimum_training_sessions: int = 252
    label_horizon_sessions: int = 3
    minimum_feature_history_sessions: int = 21
    early_stopping_rounds: int = 100
    early_stopping_metric: str = "binary_logloss"
    classification_threshold: float = 0.50
    calibration_bins: int = 10
    artifact_root: Path = Path("models/lightgbm")
    objective: str = "binary"
    boosting_type: str = "gbdt"
    learning_rate: float = 0.05
    num_leaves: int = 31
    max_depth: int = 6
    min_data_in_leaf: int = 100
    n_estimators: int = 1000
    random_state: int = 42
    verbosity: int = -1
    deterministic: bool = True
    force_col_wise: bool = True
    n_jobs: int = 1
    feature_fraction: float = 1.0
    bagging_fraction: float = 1.0
    bagging_freq: int = 0
    scale_pos_weight: float = 1.0
    is_unbalance: bool = False

    @property
    def lightgbm_parameters(self) -> dict[str, Any]:
        """Return exactly the binding baseline LGBMClassifier parameters."""

        return {
            "objective": self.objective,
            "boosting_type": self.boosting_type,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "max_depth": self.max_depth,
            "min_data_in_leaf": self.min_data_in_leaf,
            "n_estimators": self.n_estimators,
            "random_state": self.random_state,
            "verbosity": self.verbosity,
            "deterministic": self.deterministic,
            "force_col_wise": self.force_col_wise,
            "n_jobs": self.n_jobs,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "scale_pos_weight": self.scale_pos_weight,
            "is_unbalance": self.is_unbalance,
        }

    def checksum(self, algorithm: str = "sha256") -> str:
        """Return a stable checksum of the complete training contract."""

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
    feature: FeatureConfig = field(default_factory=FeatureConfig)
    training: ModelTrainingConfig = field(default_factory=ModelTrainingConfig)
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
