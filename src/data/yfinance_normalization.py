"""yFinance raw-frame preparation and D024 nominal OHLC normalization."""

from __future__ import annotations

import numpy as np
import pandas as pd


YFINANCE_PRICE_COLUMNS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
YFINANCE_KNOWN_ACTION_COLUMNS = {"Dividends", "Stock Splits", "Capital Gains"}
YFINANCE_REQUIRED_COLUMNS = {
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
    "Dividends",
    "Stock Splits",
}


def prepare_raw_yfinance_history(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Make provider rows serializable without changing provider field values.

    The provider's local calendar date and requested ticker are materialized as
    identity columns. Provider columns, including OHLC, volume and actions, keep
    their original names and values in this raw-layer frame.
    """

    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date", *map(str, raw.columns)])

    frame = raw.copy()
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize()
    frame.index.name = "date"
    frame = frame.reset_index()
    frame.insert(0, "ticker", ticker)
    return frame


def normalize_yfinance_history(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize a yFinance history response while preserving local dates."""

    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date"])

    frame = prepare_raw_yfinance_history(raw, ticker)
    rename = {
        "Open": "yf_provider_open",
        "High": "yf_provider_high",
        "Low": "yf_provider_low",
        "Close": "yf_provider_close",
        "Adj Close": "yf_provider_adjusted_close",
        "Volume": "yf_share_volume",
        "Dividends": "yf_dividends",
        "Stock Splits": "yf_stock_splits",
        "Capital Gains": "yf_capital_gains",
    }
    frame = frame.rename(columns=rename)
    nullable_provider_fields = {
        "yf_provider_open",
        "yf_provider_high",
        "yf_provider_low",
        "yf_provider_close",
        "yf_provider_adjusted_close",
        "yf_share_volume",
    }
    for target in rename.values():
        if target not in frame:
            frame[target] = np.nan if target in nullable_provider_fields else 0.0

    known_source_columns = YFINANCE_PRICE_COLUMNS | YFINANCE_KNOWN_ACTION_COLUMNS
    other_action_columns = [
        column
        for column in raw.columns
        if column not in known_source_columns
        and pd.api.types.is_numeric_dtype(raw[column])
    ]
    if other_action_columns:
        other = raw[other_action_columns].fillna(0).abs().sum(axis=1)
        frame["yf_other_action_value"] = other.to_numpy()
    else:
        frame["yf_other_action_value"] = 0.0

    keep = [
        "ticker",
        "date",
        "yf_provider_open",
        "yf_provider_high",
        "yf_provider_low",
        "yf_provider_close",
        "yf_provider_adjusted_close",
        "yf_share_volume",
        "yf_dividends",
        "yf_stock_splits",
        "yf_capital_gains",
        "yf_other_action_value",
    ]
    normalized = frame[keep].sort_values(["ticker", "date"]).reset_index(drop=True)
    return add_future_split_normalization(normalized)


def add_future_split_normalization(frame: pd.DataFrame) -> pd.DataFrame:
    """Restore provider OHLC to each date's nominal scale using later splits.

    A split on a row's own date is deliberately excluded. Zero, missing,
    non-finite and non-positive split values have a neutral factor of one.
    Original provider prices are preserved. Legacy ``yf_*`` aliases remain
    available only for callers written before D024; all price-dependent logic
    must use ``yf_nominal_*`` fields.
    """

    result = frame.sort_values(["ticker", "date"]).copy()
    for field in ("open", "high", "low", "close"):
        provider = f"yf_provider_{field}"
        legacy = f"yf_{field}"
        if provider not in result and legacy in result:
            result[provider] = result[legacy]
        if provider not in result:
            result[provider] = np.nan
        result[legacy] = result[provider]

    if "yf_stock_splits" not in result:
        result["yf_stock_splits"] = 0.0
    raw_splits = pd.to_numeric(result["yf_stock_splits"], errors="coerce")
    valid_split = raw_splits.notna() & np.isfinite(raw_splits) & raw_splits.gt(0)
    effective_split = raw_splits.where(valid_split, 1.0).astype(float)
    result["yf_split_ratio_valid"] = valid_split
    result["yf_split_value_ignored"] = (
        raw_splits.notna() & raw_splits.ne(0) & ~valid_split
    )
    result["yf_effective_split_ratio"] = effective_split

    def strictly_future_product(series: pd.Series) -> pd.Series:
        reversed_product = series.iloc[::-1].cumprod()
        return reversed_product.shift(1, fill_value=1.0).iloc[::-1]

    result["yf_future_split_factor"] = result.groupby(
        "ticker", sort=False
    )["yf_effective_split_ratio"].transform(strictly_future_product)
    for field in ("open", "high", "low", "close"):
        result[f"yf_nominal_{field}"] = (
            result[f"yf_provider_{field}"] * result["yf_future_split_factor"]
        )
    return result


def nominal_ohlc_snapshot_frame(normalized: pd.DataFrame) -> pd.DataFrame:
    """Select only derived nominal-price fields for the derived data layer."""

    columns = [
        "ticker",
        "date",
        "yf_nominal_open",
        "yf_nominal_high",
        "yf_nominal_low",
        "yf_nominal_close",
        "yf_future_split_factor",
        "yf_split_ratio_valid",
        "yf_split_value_ignored",
        "yf_effective_split_ratio",
    ]
    missing = set(columns).difference(normalized.columns)
    if missing:
        raise ValueError(f"nominal snapshot fields missing: {sorted(missing)}")
    return normalized[columns].copy()
