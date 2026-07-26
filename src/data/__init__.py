"""Data-access clients used by the project."""

from .isyatirim_client import (
    ClientStats,
    IsYatirimClient,
    IsYatirimFetchError,
    IsYatirimSchemaError,
    fetch_isyatirim_history,
)
from .snapshot_store import (
    ProviderRevision,
    SnapshotCorruptError,
    SnapshotMetadata,
    SnapshotRequest,
    SnapshotStore,
    SnapshotWriteResult,
    canonicalize_dataframe,
)
from .yfinance_normalization import (
    add_future_split_normalization,
    nominal_ohlc_snapshot_frame,
    normalize_yfinance_history,
    prepare_raw_yfinance_history,
)

__all__ = [
    "ClientStats",
    "IsYatirimClient",
    "IsYatirimFetchError",
    "IsYatirimSchemaError",
    "ProviderRevision",
    "SnapshotCorruptError",
    "SnapshotMetadata",
    "SnapshotRequest",
    "SnapshotStore",
    "SnapshotWriteResult",
    "add_future_split_normalization",
    "canonicalize_dataframe",
    "fetch_isyatirim_history",
    "nominal_ohlc_snapshot_frame",
    "normalize_yfinance_history",
    "prepare_raw_yfinance_history",
]
