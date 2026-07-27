from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.baseline_v1 import compute_baseline_features
from src.features.catalog import BASELINE_V1_BASE_FEATURES, BASELINE_V1_FEATURES


def _aligned(rows: int = 30, *, security_id: str = "SEC_A") -> pd.DataFrame:
    index = np.arange(rows, dtype="float64")
    close = 100.0 + index
    return pd.DataFrame(
        {
            "security_id": security_id,
            "prediction_date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "session_index": np.arange(rows),
            "_source_row_present": True,
            "yf_provider_open": close - 0.5,
            "yf_provider_high": close + 1.0,
            "yf_provider_low": close - 1.0,
            "yf_provider_close": close,
            "is_tl_volume": 1_000_000.0 + index * 10_000.0,
            "validated_xu100_close": 7_000.0 + index * 5.0,
        }
    )


def test_catalog_has_exactly_32_unique_features_and_28_base_features() -> None:
    assert len(BASELINE_V1_FEATURES) == 32
    assert len(set(BASELINE_V1_FEATURES)) == 32
    assert len(BASELINE_V1_BASE_FEATURES) == 28


def test_return_and_market_relative_formulas_use_exact_session_lags() -> None:
    result = compute_baseline_features(_aligned()).frame
    row = result.iloc[20]

    assert np.isclose(row["ret_1"], 120.0 / 119.0 - 1.0)
    assert np.isclose(row["ret_5"], 120.0 / 115.0 - 1.0)
    market_ret_5 = 7_100.0 / 7_075.0 - 1.0
    assert np.isclose(row["relative_ret_5"], row["ret_5"] - market_ret_5)


def test_missing_global_session_does_not_compress_shift_or_rolling_window() -> None:
    frame = _aligned()
    frame.loc[10, [
        "yf_provider_open",
        "yf_provider_high",
        "yf_provider_low",
        "yf_provider_close",
        "is_tl_volume",
    ]] = np.nan
    frame.loc[10, "_source_row_present"] = False
    result = compute_baseline_features(frame).frame

    assert np.isnan(result.loc[11, "ret_1"])
    assert np.isnan(result.loc[14, "close_to_sma_5"])
    assert np.isnan(result.loc[29, "return_volatility_20"])


def test_full_window_warmup_is_nan() -> None:
    result = compute_baseline_features(_aligned()).frame

    assert result.loc[:19, "ret_20"].isna().all()
    assert result.loc[:18, "close_to_sma_20"].isna().all()
    assert result.loc[:19, "tl_volume_zscore_20"].isna().all()
    assert result.loc[:13, "rsi_14_sma"].isna().all()


def test_price_features_are_invariant_to_positive_constant_scaling() -> None:
    source = _aligned()
    scaled = source.copy()
    price_columns = [
        "yf_provider_open",
        "yf_provider_high",
        "yf_provider_low",
        "yf_provider_close",
    ]
    scaled[price_columns] = scaled[price_columns] * 37.5
    left = compute_baseline_features(source).frame
    right = compute_baseline_features(scaled).frame
    price_derived = [
        name
        for name in BASELINE_V1_BASE_FEATURES
        if name
        not in {
            "log_median_tl_volume_20",
            "tl_volume_ratio_5_20",
            "tl_volume_zscore_20",
            "tl_volume_cv_20",
            "amihud_20",
            "market_ret_1",
        }
    ]

    for feature in price_derived:
        assert np.allclose(left[feature], right[feature], equal_nan=True), feature


def test_cutler_rsi_edge_cases_are_explicit() -> None:
    flat = _aligned()
    flat[["yf_provider_open", "yf_provider_high", "yf_provider_low", "yf_provider_close"]] = [
        100.0,
        101.0,
        99.0,
        100.0,
    ]
    rising = _aligned()
    falling = _aligned()
    falling_close = 200.0 - np.arange(len(falling), dtype="float64")
    falling["yf_provider_close"] = falling_close
    falling["yf_provider_open"] = falling_close + 0.5
    falling["yf_provider_high"] = falling_close + 1.0
    falling["yf_provider_low"] = falling_close - 1.0

    assert compute_baseline_features(flat).frame.loc[14, "rsi_14_sma"] == 50.0
    assert compute_baseline_features(rising).frame.loc[14, "rsi_14_sma"] == 100.0
    assert compute_baseline_features(falling).frame.loc[14, "rsi_14_sma"] == 0.0


def test_invalid_denominators_and_infinity_become_nan() -> None:
    frame = _aligned()
    frame.loc[25, "yf_provider_high"] = frame.loc[25, "yf_provider_low"]
    frame.loc[26, "is_tl_volume"] = np.inf
    computation = compute_baseline_features(frame)
    result = computation.frame

    assert np.isnan(result.loc[25, "close_location_value"])
    assert np.isnan(result.loc[26, "tl_volume_zscore_20"])
    assert not np.isinf(result.loc[:, BASELINE_V1_BASE_FEATURES].to_numpy()).any()
    assert computation.reason_masks["tl_volume_zscore_20"][
        "infinite_replaced"
    ].loc[26]
