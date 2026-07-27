"""Exact leakage-safe implementation of the 28 non-cross-sectional features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from src.features.catalog import BASELINE_V1_BASE_FEATURES


FEATURE_MINIMUM_HISTORY: Mapping[str, int] = {
    "ret_1": 2,
    "ret_2": 3,
    "ret_3": 4,
    "ret_5": 6,
    "ret_10": 11,
    "ret_20": 21,
    "close_to_sma_5": 5,
    "close_to_sma_20": 20,
    "distance_from_high_20": 20,
    "positive_day_ratio_5": 6,
    "return_volatility_5": 6,
    "return_volatility_20": 21,
    "volatility_ratio_5_20": 21,
    "true_range_pct": 2,
    "range_expansion_5_20": 21,
    "log_median_tl_volume_20": 20,
    "tl_volume_ratio_5_20": 20,
    "tl_volume_zscore_20": 21,
    "tl_volume_cv_20": 20,
    "amihud_20": 21,
    "overnight_gap": 2,
    "intraday_return": 1,
    "close_location_value": 1,
    "rsi_14_sma": 15,
    "market_ret_1": 2,
    "relative_ret_1": 2,
    "relative_ret_5": 6,
    "relative_ret_20": 21,
}

VOLUME_FEATURES = {
    "log_median_tl_volume_20",
    "tl_volume_ratio_5_20",
    "tl_volume_zscore_20",
    "tl_volume_cv_20",
    "amihud_20",
}
MARKET_FEATURES = {
    "market_ret_1",
    "relative_ret_1",
    "relative_ret_5",
    "relative_ret_20",
}


@dataclass(frozen=True)
class BaselineComputation:
    frame: pd.DataFrame
    reason_masks: Mapping[str, Mapping[str, pd.Series]]


def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide only finite values by a finite, strictly positive denominator."""

    left = pd.to_numeric(numerator, errors="coerce").astype("float64")
    right = pd.to_numeric(denominator, errors="coerce").astype("float64")
    valid = np.isfinite(left) & np.isfinite(right) & right.gt(0)
    result = pd.Series(np.nan, index=left.index, dtype="float64")
    result.loc[valid] = left.loc[valid] / right.loc[valid]
    return result


def compute_baseline_features(aligned: pd.DataFrame) -> BaselineComputation:
    """Compute exact-session shifts/rolls on an already aligned global grid."""

    required = {
        "security_id",
        "prediction_date",
        "session_index",
        "_source_row_present",
        "yf_provider_open",
        "yf_provider_high",
        "yf_provider_low",
        "yf_provider_close",
        "is_tl_volume",
        "validated_xu100_close",
    }
    missing = required.difference(aligned.columns)
    if missing:
        raise ValueError(f"baseline input fields missing: {sorted(missing)}")
    groups: list[pd.DataFrame] = []
    for _, source in aligned.groupby("security_id", sort=True, group_keys=False):
        groups.append(_compute_one_security(source.sort_values("session_index").copy()))
    result = pd.concat(groups, ignore_index=True).sort_values(
        ["security_id", "session_index"]
    ).reset_index(drop=True)
    reason_masks = _build_reason_masks(result)
    return BaselineComputation(result, reason_masks)


def _valid_positive(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").astype("float64")
    return numeric.where(np.isfinite(numeric) & numeric.gt(0))


def _compute_one_security(frame: pd.DataFrame) -> pd.DataFrame:
    price_input = frame[
        [
            "yf_provider_open",
            "yf_provider_high",
            "yf_provider_low",
            "yf_provider_close",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    frame["_input_infinite_price"] = np.isinf(
        price_input.to_numpy(dtype="float64")
    ).any(axis=1)
    frame["_input_infinite_volume"] = np.isinf(
        pd.to_numeric(frame["is_tl_volume"], errors="coerce").to_numpy(
            dtype="float64"
        )
    )
    frame["_input_infinite_market"] = np.isinf(
        pd.to_numeric(frame["validated_xu100_close"], errors="coerce").to_numpy(
            dtype="float64"
        )
    )
    o = _valid_positive(frame["yf_provider_open"])
    h = _valid_positive(frame["yf_provider_high"])
    low = _valid_positive(frame["yf_provider_low"])
    close = _valid_positive(frame["yf_provider_close"])
    volume = _valid_positive(frame["is_tl_volume"])
    market = _valid_positive(frame["validated_xu100_close"])

    returns: dict[int, pd.Series] = {}
    market_returns: dict[int, pd.Series] = {}
    for days in (1, 2, 3, 5, 10, 20):
        returns[days] = safe_div(close, close.shift(days)) - 1.0
    for days in (1, 5, 20):
        market_returns[days] = safe_div(market, market.shift(days)) - 1.0

    frame["ret_1"] = returns[1]
    frame["ret_2"] = returns[2]
    frame["ret_3"] = returns[3]
    frame["ret_5"] = returns[5]
    frame["ret_10"] = returns[10]
    frame["ret_20"] = returns[20]
    sma5 = close.rolling(5, min_periods=5).mean()
    sma20 = close.rolling(20, min_periods=20).mean()
    frame["close_to_sma_5"] = safe_div(close, sma5) - 1.0
    frame["close_to_sma_20"] = safe_div(close, sma20) - 1.0
    frame["distance_from_high_20"] = (
        safe_div(close, h.rolling(20, min_periods=20).max()) - 1.0
    )
    positive = returns[1].gt(0).where(returns[1].notna()).astype("float64")
    frame["positive_day_ratio_5"] = positive.rolling(5, min_periods=5).mean()
    volatility5 = returns[1].rolling(5, min_periods=5).std(ddof=1)
    volatility20 = returns[1].rolling(20, min_periods=20).std(ddof=1)
    frame["return_volatility_5"] = volatility5
    frame["return_volatility_20"] = volatility20
    frame["volatility_ratio_5_20"] = safe_div(volatility5, volatility20)

    previous_close = close.shift(1)
    tr = pd.concat(
        [h - low, (h - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1, skipna=False)
    tr_pct = safe_div(tr, previous_close)
    frame["true_range_pct"] = tr_pct
    frame["range_expansion_5_20"] = safe_div(
        tr_pct.rolling(5, min_periods=5).mean(),
        tr_pct.rolling(20, min_periods=20).mean(),
    )

    log_volume = np.log1p(volume)
    frame["log_median_tl_volume_20"] = np.log1p(
        volume.rolling(20, min_periods=20).median()
    )
    frame["tl_volume_ratio_5_20"] = safe_div(
        volume.rolling(5, min_periods=5).mean(),
        volume.rolling(20, min_periods=20).mean(),
    )
    prior_mean = log_volume.rolling(20, min_periods=20).mean().shift(1)
    prior_std = log_volume.rolling(20, min_periods=20).std(ddof=1).shift(1)
    frame["tl_volume_zscore_20"] = safe_div(log_volume - prior_mean, prior_std)
    frame["tl_volume_cv_20"] = safe_div(
        volume.rolling(20, min_periods=20).std(ddof=1),
        volume.rolling(20, min_periods=20).mean(),
    )
    illiquidity = safe_div(returns[1].abs(), volume)
    frame["amihud_20"] = np.log1p(
        1_000_000_000.0 * illiquidity.rolling(20, min_periods=20).mean()
    )
    frame["overnight_gap"] = safe_div(o, previous_close) - 1.0
    frame["intraday_return"] = safe_div(close, o) - 1.0
    frame["close_location_value"] = safe_div(2.0 * close - h - low, h - low)

    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    average_gain = gains.rolling(14, min_periods=14).mean()
    average_loss = losses.rolling(14, min_periods=14).mean()
    rsi = pd.Series(np.nan, index=frame.index, dtype="float64")
    both_zero = average_gain.eq(0) & average_loss.eq(0)
    gain_only = average_gain.gt(0) & average_loss.eq(0)
    loss_only = average_gain.eq(0) & average_loss.gt(0)
    regular = average_gain.gt(0) & average_loss.gt(0)
    rsi.loc[both_zero] = 50.0
    rsi.loc[gain_only] = 100.0
    rsi.loc[loss_only] = 0.0
    ratio = safe_div(average_gain, average_loss)
    rsi.loc[regular] = 100.0 - 100.0 / (1.0 + ratio.loc[regular])
    frame["rsi_14_sma"] = rsi
    frame["market_ret_1"] = market_returns[1]
    frame["relative_ret_1"] = returns[1] - market_returns[1]
    frame["relative_ret_5"] = returns[5] - market_returns[5]
    frame["relative_ret_20"] = returns[20] - market_returns[20]
    for feature in BASELINE_V1_BASE_FEATURES:
        numeric = pd.to_numeric(frame[feature], errors="coerce").astype("float64")
        frame[f"_infinite_{feature}"] = np.isinf(numeric)
        frame[feature] = numeric.where(np.isfinite(numeric))
    return frame


def _build_reason_masks(
    frame: pd.DataFrame,
) -> dict[str, dict[str, pd.Series]]:
    position = frame.groupby("security_id", sort=False).cumcount()
    stock_missing_now = frame[
        [
            "yf_provider_open",
            "yf_provider_high",
            "yf_provider_low",
            "yf_provider_close",
        ]
    ].apply(pd.to_numeric, errors="coerce").isna().any(axis=1)
    volume_missing_now = pd.to_numeric(frame["is_tl_volume"], errors="coerce").isna()
    market_missing_now = pd.to_numeric(
        frame["validated_xu100_close"], errors="coerce"
    ).isna()
    masks: dict[str, dict[str, pd.Series]] = {}
    for feature in BASELINE_V1_BASE_FEATURES:
        history = FEATURE_MINIMUM_HISTORY[feature]
        warmup = position.lt(history - 1) & frame[feature].isna()
        source_now = volume_missing_now if feature in VOLUME_FEATURES else stock_missing_now
        if feature == "amihud_20":
            source_now = source_now | stock_missing_now
        source_window = source_now.groupby(frame["security_id"], sort=False).transform(
            lambda values: values.rolling(history, min_periods=1).max().astype(bool)
        )
        source_missing = frame[feature].isna() & ~warmup & source_window
        xu_window = market_missing_now.groupby(frame["security_id"], sort=False).transform(
            lambda values: values.rolling(history, min_periods=1).max().astype(bool)
        )
        xu_missing = (
            frame[feature].isna() & ~warmup & xu_window
            if feature in MARKET_FEATURES
            else pd.Series(False, index=frame.index)
        )
        invalid_math = frame[feature].isna() & ~warmup & ~source_missing & ~xu_missing
        input_infinite = (
            frame["_input_infinite_volume"].astype(bool)
            if feature in VOLUME_FEATURES
            else frame["_input_infinite_price"].astype(bool)
        )
        if feature == "amihud_20":
            input_infinite = input_infinite | frame["_input_infinite_price"].astype(bool)
        if feature in MARKET_FEATURES:
            input_infinite = input_infinite | frame["_input_infinite_market"].astype(bool)
        infinite_window = input_infinite.groupby(
            frame["security_id"], sort=False
        ).transform(
            lambda values: values.rolling(history, min_periods=1).max().astype(bool)
        )
        masks[feature] = {
            "warmup": warmup,
            "source_missing": source_missing,
            "invalid_math": invalid_math,
            "xu100_missing": xu_missing,
            "cross_section_insufficient": pd.Series(False, index=frame.index),
            "infinite_replaced": frame[f"_infinite_{feature}"].astype(bool)
            | (infinite_window & frame[feature].isna()),
        }
    return masks
