"""Single executable source for the exact baseline_v1 feature order."""

from __future__ import annotations

import hashlib
from pathlib import Path


BASELINE_V1_FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_2",
    "ret_3",
    "ret_5",
    "ret_10",
    "ret_20",
    "close_to_sma_5",
    "close_to_sma_20",
    "distance_from_high_20",
    "positive_day_ratio_5",
    "return_volatility_5",
    "return_volatility_20",
    "volatility_ratio_5_20",
    "true_range_pct",
    "range_expansion_5_20",
    "log_median_tl_volume_20",
    "tl_volume_ratio_5_20",
    "tl_volume_zscore_20",
    "tl_volume_cv_20",
    "amihud_20",
    "overnight_gap",
    "intraday_return",
    "close_location_value",
    "rsi_14_sma",
    "market_ret_1",
    "relative_ret_1",
    "relative_ret_5",
    "relative_ret_20",
    "cs_ret_1_rank",
    "cs_ret_5_rank",
    "cs_relative_ret_5_rank",
    "cs_volume_anomaly_rank",
)

BASELINE_V1_BASE_FEATURES = BASELINE_V1_FEATURES[:28]
BASELINE_V1_CROSS_SECTIONAL_FEATURES = BASELINE_V1_FEATURES[28:]


def catalog_file_checksum(
    path: str | Path = Path("FEATURE_CATALOG.md"), algorithm: str = "sha256"
) -> str:
    """Hash the binding catalog file as raw bytes for snapshot provenance."""

    return hashlib.new(algorithm, Path(path).read_bytes()).hexdigest()
