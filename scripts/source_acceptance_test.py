"""Run the local single-price-source acceptance test.

yFinance nominal OHLC is the only price series evaluated for entry, label,
exit and upper-limit calculations. İş Yatırım supplies the BIST calendar,
TRY volume and auxiliary quality signals; its prices are comparison-only.

The script intentionally writes aggregate metrics, corporate-action event rows
and a Markdown summary. Versioned raw-source storage belongs to the subsequent
data-collection pipeline and is not implemented by this acceptance runner.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import math
import platform
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
import yfinance as yf
from isyatirimhisse import fetch_stock_data


DEFAULT_TICKERS = (
    "THYAO",
    "GARAN",
    "ASELS",
    "BIMAS",
    "TUPRS",
    "EREGL",
    "SISE",
    "SASA",
    "KCHOL",
    "HEKTS",
)
FULL_PERIOD_TICKERS = ("THYAO", "BIMAS", "TUPRS", "SISE", "SASA")

# HGDG fields are the historically adjusted series; HG fields are raw.
ISYATIRIM_REQUIRED_COLUMNS = {
    "HGDG_HS_KODU",
    "HGDG_TARIH",
    "HGDG_KAPANIS",
    "HGDG_AOF",
    "HGDG_MIN",
    "HGDG_MAX",
    "HGDG_HACIM",
    "HG_KAPANIS",
    "HG_AOF",
    "HG_MIN",
    "HG_MAX",
    "HG_HACIM",
}
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
YFINANCE_PRICE_COLUMNS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
YFINANCE_KNOWN_ACTION_COLUMNS = {"Dividends", "Stock Splits", "Capital Gains"}

# This is a numerical noise tolerance, not a BIST price-step tolerance.
ADJUSTMENT_FACTOR_RTOL = 1e-4
ADJUSTMENT_FACTOR_ATOL = 5e-5
PRICE_COMPARE_ATOL = 1e-8

# This acceptance module does not define model features. Keeping the explicit
# list makes it testable that normalization/action fields never become signals.
MODEL_FEATURE_COLUMNS: tuple[str, ...] = ()
NON_FEATURE_NORMALIZATION_COLUMNS = {
    "yf_future_split_factor",
    "yf_stock_splits",
    "yf_dividends",
    "yf_capital_gains",
    "yf_other_action_value",
}


@dataclass(frozen=True)
class PeriodSpec:
    name: str
    start: date
    end: date
    tickers: tuple[str, ...]


def build_periods(run_date: date) -> tuple[PeriodSpec, ...]:
    """Build inclusive acceptance-test periods for a given run date."""
    return (
        PeriodSpec(
            "start_boundary",
            date(2020, 3, 13),
            date(2020, 4, 15),
            DEFAULT_TICKERS,
        ),
        PeriodSpec(
            "price_step_change",
            date(2023, 10, 20),
            date(2023, 11, 20),
            DEFAULT_TICKERS,
        ),
        PeriodSpec(
            "recent_90_calendar_days",
            run_date - timedelta(days=89),
            run_date,
            DEFAULT_TICKERS,
        ),
        PeriodSpec(
            "full_period",
            date(2020, 3, 13),
            run_date,
            FULL_PERIOD_TICKERS,
        ),
    )


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def normalize_yfinance_history(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize a yFinance history response while preserving local dates."""
    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date"])

    frame = raw.copy()
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize()
    frame.index.name = "date"
    frame = frame.reset_index()
    frame["ticker"] = ticker

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
    for target in rename.values():
        if target not in frame:
            frame[target] = 0.0 if target.startswith("yf_") and target not in {
                "yf_provider_open",
                "yf_provider_high",
                "yf_provider_low",
                "yf_provider_close",
                "yf_provider_adjusted_close",
                "yf_share_volume",
            } else np.nan

    known_source_columns = YFINANCE_PRICE_COLUMNS | YFINANCE_KNOWN_ACTION_COLUMNS
    other_action_columns = [
        column
        for column in raw.columns
        if column not in known_source_columns
        and pd.api.types.is_numeric_dtype(raw[column])
    ]
    if other_action_columns:
        other = raw[other_action_columns].fillna(0).abs().sum(axis=1)
        other.index = frame.index if isinstance(frame.index, pd.DatetimeIndex) else other.index
        # reset_index changed the frame index, so assign positionally.
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
    available only for callers written before the single-source decision; all
    price-dependent acceptance logic uses ``yf_nominal_*`` fields.
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


def normalize_isyatirim_history(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize only the İş Yatırım fields used by the acceptance test."""
    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date"])

    missing = ISYATIRIM_REQUIRED_COLUMNS.difference(raw.columns)
    if missing:
        raise ValueError(f"İş Yatırım required columns missing for {ticker}: {sorted(missing)}")

    frame = raw.rename(
        columns={
            "HGDG_TARIH": "date",
            "HGDG_KAPANIS": "is_adjusted_close",
            "HGDG_AOF": "is_adjusted_weighted_average",
            "HGDG_MIN": "is_adjusted_low",
            "HGDG_MAX": "is_adjusted_high",
            "HGDG_HACIM": "is_tl_volume",
            "HG_KAPANIS": "is_raw_close",
            "HG_AOF": "is_raw_weighted_average",
            "HG_MIN": "is_raw_low",
            "HG_MAX": "is_raw_high",
            "HG_HACIM": "is_raw_tl_volume",
            "PD": "is_market_cap_try",
            "PD_USD": "is_market_cap_usd",
            "HAO_PD": "is_free_float_market_cap_try",
            "HAO_PD_USD": "is_free_float_market_cap_usd",
        }
    ).copy()
    frame["ticker"] = ticker
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()

    keep = [
        "ticker",
        "date",
        "is_raw_high",
        "is_raw_low",
        "is_raw_close",
        "is_raw_weighted_average",
        "is_adjusted_high",
        "is_adjusted_low",
        "is_adjusted_close",
        "is_adjusted_weighted_average",
        "is_tl_volume",
        "is_raw_tl_volume",
        "is_market_cap_try",
        "is_market_cap_usd",
        "is_free_float_market_cap_try",
        "is_free_float_market_cap_usd",
    ]
    for column in keep:
        if column not in frame:
            frame[column] = np.nan
    return frame[keep].sort_values(["ticker", "date"]).drop_duplicates(
        ["ticker", "date"], keep="last"
    ).reset_index(drop=True)


def mark_adjustment_factor_changes(
    frame: pd.DataFrame,
    *,
    rtol: float = ADJUSTMENT_FACTOR_RTOL,
    atol: float = ADJUSTMENT_FACTOR_ATOL,
) -> pd.DataFrame:
    """Calculate adjusted/raw factor and flag material day-to-day changes."""
    result = frame.sort_values(["ticker", "date"]).copy()
    valid = result["is_raw_close"].notna() & result["is_raw_close"].gt(0)
    result["adjustment_factor"] = np.nan
    result.loc[valid, "adjustment_factor"] = (
        result.loc[valid, "is_adjusted_close"] / result.loc[valid, "is_raw_close"]
    )
    result["previous_adjustment_factor"] = result.groupby("ticker")[
        "adjustment_factor"
    ].shift(1)
    comparable = result[["adjustment_factor", "previous_adjustment_factor"]].notna().all(axis=1)
    result["adjustment_factor_changed"] = False
    result.loc[comparable, "adjustment_factor_changed"] = ~np.isclose(
        result.loc[comparable, "adjustment_factor"],
        result.loc[comparable, "previous_adjustment_factor"],
        rtol=rtol,
        atol=atol,
    )
    return result


def build_quality_frame(is_frame: pd.DataFrame, yf_frame: pd.DataFrame) -> pd.DataFrame:
    """Build single-source OHLC acceptance and cross-source warning fields."""
    is_marked = mark_adjustment_factor_changes(is_frame)
    prepared_yf = add_future_split_normalization(yf_frame)
    merged = is_marked.merge(
        prepared_yf,
        on=["ticker", "date"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    merged["is_isyatirim_date"] = True
    merged["has_yfinance_row"] = merged["_merge"].eq("both")
    merged = merged.drop(columns="_merge")

    merged["has_open"] = (
        merged["yf_nominal_open"].notna() & merged["yf_nominal_open"].gt(0)
    )
    merged["has_isyatirim_tl_volume"] = merged["is_tl_volume"].notna()
    merged["has_yfinance_share_volume"] = merged["yf_share_volume"].notna()
    merged["both_volumes_zero"] = (
        merged["is_tl_volume"].eq(0) & merged["yf_share_volume"].eq(0)
    )
    merged["both_volumes_missing"] = (
        merged["is_tl_volume"].isna() & merged["yf_share_volume"].isna()
    )
    merged["one_volume_missing"] = (
        merged["is_tl_volume"].isna() ^ merged["yf_share_volume"].isna()
    )
    merged["one_volume_zero_other_positive"] = (
        (merged["is_tl_volume"].eq(0) & merged["yf_share_volume"].gt(0))
        | (merged["yf_share_volume"].eq(0) & merged["is_tl_volume"].gt(0))
    )

    nominal_ohlc_columns = [
        "yf_nominal_open",
        "yf_nominal_high",
        "yf_nominal_low",
        "yf_nominal_close",
    ]
    merged["missing_nominal_open"] = merged["yf_nominal_open"].isna()
    merged["missing_nominal_high"] = merged["yf_nominal_high"].isna()
    merged["missing_nominal_low"] = merged["yf_nominal_low"].isna()
    merged["missing_nominal_close"] = merged["yf_nominal_close"].isna()
    merged["missing_nominal_high_low_close"] = merged[
        ["missing_nominal_high", "missing_nominal_low", "missing_nominal_close"]
    ].any(axis=1)
    evaluable_ohlc = merged[nominal_ohlc_columns].notna().all(axis=1)
    positive_ohlc = merged[nominal_ohlc_columns].gt(0).all(axis=1)
    merged["valid_nominal_ohlc"] = pd.Series(
        pd.NA, index=merged.index, dtype="boolean"
    )
    merged.loc[evaluable_ohlc, "valid_nominal_ohlc"] = (
        positive_ohlc.loc[evaluable_ohlc]
        & merged.loc[evaluable_ohlc, "yf_nominal_low"].le(
            merged.loc[evaluable_ohlc, "yf_nominal_open"]
        )
        & merged.loc[evaluable_ohlc, "yf_nominal_open"].le(
            merged.loc[evaluable_ohlc, "yf_nominal_high"]
        )
        & merged.loc[evaluable_ohlc, "yf_nominal_low"].le(
            merged.loc[evaluable_ohlc, "yf_nominal_close"]
        )
        & merged.loc[evaluable_ohlc, "yf_nominal_close"].le(
            merged.loc[evaluable_ohlc, "yf_nominal_high"]
        )
    )
    # Temporary compatibility alias; it now means yFinance nominal OHLC only.
    merged["valid_ohlc"] = merged["valid_nominal_ohlc"]

    split_factor = pd.to_numeric(merged["yf_future_split_factor"], errors="coerce")
    merged["split_factor_unavailable"] = (
        merged["has_yfinance_row"]
        & (split_factor.isna() | ~np.isfinite(split_factor) | split_factor.le(0))
    )
    conversion_checks: list[pd.Series] = []
    for field in ("open", "high", "low", "close"):
        provider = merged[f"yf_provider_{field}"]
        nominal = merged[f"yf_nominal_{field}"]
        comparable = provider.notna() & split_factor.notna()
        field_check = pd.Series(True, index=merged.index)
        field_check.loc[comparable] = np.isclose(
            nominal.loc[comparable],
            provider.loc[comparable] * split_factor.loc[comparable],
            rtol=1e-12,
            atol=1e-12,
        )
        conversion_checks.append(field_check)
    merged["nominal_conversion_consistent"] = pd.concat(
        conversion_checks, axis=1
    ).all(axis=1)

    provider_open_columns = ["is_raw_low", "yf_provider_open", "is_raw_high"]
    nominal_open_columns = ["is_raw_low", "yf_nominal_open", "is_raw_high"]
    provider_open_evaluable = merged[provider_open_columns].notna().all(axis=1)
    nominal_open_evaluable = merged[nominal_open_columns].notna().all(axis=1)
    merged["provider_open_within_is_range"] = pd.Series(
        pd.NA, index=merged.index, dtype="boolean"
    )
    merged["nominal_open_within_is_range"] = pd.Series(
        pd.NA, index=merged.index, dtype="boolean"
    )
    merged.loc[provider_open_evaluable, "provider_open_within_is_range"] = (
        merged.loc[provider_open_evaluable, "is_raw_low"].le(
            merged.loc[provider_open_evaluable, "yf_provider_open"]
        )
        & merged.loc[provider_open_evaluable, "yf_provider_open"].le(
            merged.loc[provider_open_evaluable, "is_raw_high"]
        )
    )
    merged.loc[nominal_open_evaluable, "nominal_open_within_is_range"] = (
        merged.loc[nominal_open_evaluable, "is_raw_low"].le(
            merged.loc[nominal_open_evaluable, "yf_nominal_open"]
        )
        & merged.loc[nominal_open_evaluable, "yf_nominal_open"].le(
            merged.loc[nominal_open_evaluable, "is_raw_high"]
        )
    )
    for prefix, open_column in (
        ("provider", "yf_provider_open"),
        ("nominal", "yf_nominal_open"),
    ):
        below = (merged["is_raw_low"] - merged[open_column]).clip(lower=0)
        above = (merged[open_column] - merged["is_raw_high"]).clip(lower=0)
        gap = pd.concat([below, above], axis=1).max(axis=1)
        evaluable = merged[["is_raw_low", open_column, "is_raw_high"]].notna().all(axis=1)
        merged[f"{prefix}_open_range_gap"] = gap.where(evaluable)
        merged[f"{prefix}_open_range_gap_pct"] = (
            gap.div(merged["is_raw_close"].abs().replace(0, np.nan)).mul(100).where(evaluable)
        )

    comparable_flags: list[pd.Series] = []
    for field in ("high", "low", "close"):
        is_column = f"is_raw_{field}"
        yf_column = f"yf_provider_{field}"
        comparable = merged[[is_column, yf_column]].notna().all(axis=1)
        difference = (merged[is_column] - merged[yf_column]).abs()
        merged[f"{field}_absolute_difference"] = difference.where(comparable)
        denominator = merged[is_column].abs().replace(0, np.nan)
        merged[f"{field}_percentage_difference"] = (
            difference.div(denominator).mul(100).where(comparable)
        )
        comparable_flags.append(comparable & difference.gt(PRICE_COMPARE_ATOL))

    any_comparable = merged[
        ["high_absolute_difference", "low_absolute_difference", "close_absolute_difference"]
    ].notna().any(axis=1)
    merged["source_price_conflict"] = pd.Series(pd.NA, index=merged.index, dtype="boolean")
    merged.loc[any_comparable, "source_price_conflict"] = pd.concat(
        comparable_flags, axis=1
    ).any(axis=1).loc[any_comparable]

    nominal_comparable_flags: list[pd.Series] = []
    for field in ("high", "low", "close"):
        is_column = f"is_raw_{field}"
        yf_column = f"yf_nominal_{field}"
        comparable = merged[[is_column, yf_column]].notna().all(axis=1)
        difference = (merged[is_column] - merged[yf_column]).abs()
        merged[f"nominal_{field}_absolute_difference"] = difference.where(comparable)
        denominator = merged[is_column].abs().replace(0, np.nan)
        merged[f"nominal_{field}_percentage_difference"] = (
            difference.div(denominator).mul(100).where(comparable)
        )
        nominal_comparable_flags.append(comparable & difference.gt(PRICE_COMPARE_ATOL))
    nominal_any_comparable = merged[
        [
            "nominal_high_absolute_difference",
            "nominal_low_absolute_difference",
            "nominal_close_absolute_difference",
        ]
    ].notna().any(axis=1)
    merged["nominal_source_price_conflict"] = pd.Series(
        pd.NA, index=merged.index, dtype="boolean"
    )
    merged.loc[nominal_any_comparable, "nominal_source_price_conflict"] = pd.concat(
        nominal_comparable_flags, axis=1
    ).any(axis=1).loc[nominal_any_comparable]
    merged["cross_source_price_warning"] = merged[
        "nominal_source_price_conflict"
    ]

    for column in ("yf_dividends", "yf_stock_splits", "yf_capital_gains", "yf_other_action_value"):
        if column not in merged:
            merged[column] = 0.0
    merged["has_yfinance_dividend"] = merged["yf_dividends"].fillna(0).ne(0)
    merged["has_yfinance_split"] = merged["yf_stock_splits"].fillna(0).ne(0)
    merged["has_yfinance_other_action"] = (
        merged[["yf_capital_gains", "yf_other_action_value"]].fillna(0).abs().sum(axis=1).gt(0)
    )
    merged["has_yfinance_action"] = merged[
        ["has_yfinance_dividend", "has_yfinance_split", "has_yfinance_other_action"]
    ].any(axis=1)
    merged["has_any_corporate_action_signal"] = (
        merged["adjustment_factor_changed"] | merged["has_yfinance_action"]
    )
    merged["normal_day"] = ~merged["has_any_corporate_action_signal"]
    merged["dividend_day"] = merged["has_yfinance_dividend"]
    merged["split_day"] = merged["has_yfinance_split"]
    merged["adjustment_factor_change_day"] = merged["adjustment_factor_changed"]
    merged["corporate_action_source"] = np.select(
        [
            merged["adjustment_factor_changed"] & merged["has_yfinance_action"],
            merged["adjustment_factor_changed"],
            merged["has_yfinance_action"],
        ],
        ["both", "isyatirim_only", "yfinance_only"],
        default="none",
    )

    future_action_flags = [
        merged.groupby("ticker", sort=False)["has_any_corporate_action_signal"]
        .shift(-offset, fill_value=False)
        .astype(bool)
        for offset in (1, 2, 3)
    ]
    merged["corporate_action_window"] = pd.concat(
        future_action_flags, axis=1
    ).any(axis=1)

    merged["volume_quality_flag"] = pd.Series(
        pd.NA, index=merged.index, dtype="string"
    )
    volume_conflict = merged["one_volume_missing"] | merged[
        "one_volume_zero_other_positive"
    ]
    merged.loc[volume_conflict, "volume_quality_flag"] = "SOURCE_VOLUME_CONFLICT"

    merged["entry_eligible"] = pd.Series(True, index=merged.index, dtype="boolean")
    merged["entry_exclusion_reason"] = pd.Series(
        pd.NA, index=merged.index, dtype="string"
    )
    no_open = ~merged["has_open"]
    no_trade = ~no_open & merged["both_volumes_zero"]
    invalid_ohlc = (
        ~no_open & ~no_trade & merged["valid_nominal_ohlc"].eq(False)
    )
    unresolved_volume = (
        ~no_open & ~no_trade & merged["both_volumes_missing"]
    )
    merged.loc[no_open, ["entry_eligible", "entry_exclusion_reason"]] = [
        False,
        "NO_OPEN",
    ]
    merged.loc[no_trade, ["entry_eligible", "entry_exclusion_reason"]] = [
        False,
        "NO_TRADE",
    ]
    merged.loc[invalid_ohlc, ["entry_eligible", "entry_exclusion_reason"]] = [
        False,
        "INVALID_OHLC",
    ]
    # D022 intentionally leaves this case unresolved rather than inventing a rule.
    merged.loc[unresolved_volume, "entry_eligible"] = pd.NA

    merged["label_eligible"] = pd.Series(True, index=merged.index, dtype="boolean")
    merged["label_exclusion_reason"] = pd.Series(
        pd.NA, index=merged.index, dtype="string"
    )
    merged.loc[
        merged["corporate_action_window"],
        ["label_eligible", "label_exclusion_reason"],
    ] = [False, "CORPORATE_ACTION_WINDOW"]
    return merged.sort_values(["ticker", "date"]).reset_index(drop=True)


def _safe_rate(count: int, denominator: int) -> float:
    return count / denominator if denominator else math.nan


def _quantile(series: pd.Series, quantile: float) -> float:
    clean = series.dropna()
    return float(clean.quantile(quantile)) if not clean.empty else math.nan


def calculate_metric_row(frame: pd.DataFrame, ticker: str, period: PeriodSpec) -> dict[str, object]:
    expected_days = len(frame)
    yfinance_matches = int(frame["has_yfinance_row"].sum())
    missing_open = int(frame["missing_nominal_open"].sum())
    evaluable_ohlc = int(frame["valid_nominal_ohlc"].notna().sum())
    invalid_ohlc = int(frame["valid_nominal_ohlc"].eq(False).sum())
    provider_open_evaluable = int(frame["provider_open_within_is_range"].notna().sum())
    provider_open_inconsistent = int(
        frame["provider_open_within_is_range"].eq(False).sum()
    )
    nominal_open_evaluable = int(frame["nominal_open_within_is_range"].notna().sum())
    nominal_open_inconsistent = int(
        frame["nominal_open_within_is_range"].eq(False).sum()
    )
    result: dict[str, object] = {
        "period": period.name,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "ticker": ticker,
        "expected_isyatirim_days": expected_days,
        "yfinance_matching_days": yfinance_matches,
        "yfinance_date_match_rate": _safe_rate(yfinance_matches, expected_days),
        "missing_nominal_open_count": missing_open,
        "missing_nominal_open_rate": _safe_rate(missing_open, expected_days),
        "missing_nominal_high_count": int(frame["missing_nominal_high"].sum()),
        "missing_nominal_low_count": int(frame["missing_nominal_low"].sum()),
        "missing_nominal_close_count": int(frame["missing_nominal_close"].sum()),
        "missing_nominal_high_low_close_count": int(
            frame["missing_nominal_high_low_close"].sum()
        ),
        "nominal_ohlc_evaluable_count": evaluable_ohlc,
        "invalid_nominal_ohlc_count": invalid_ohlc,
        "nominal_ohlc_validity_rate": _safe_rate(
            evaluable_ohlc - invalid_ohlc, evaluable_ohlc
        ),
        "split_factor_unavailable_count": int(
            frame["split_factor_unavailable"].sum()
        ),
        "corporate_action_window_count": int(
            frame["corporate_action_window"].sum()
        ),
        "cross_source_price_warning_count": int(
            frame["cross_source_price_warning"].eq(True).sum()
        ),
        "isyatirim_tl_volume_missing_count": int(frame["is_tl_volume"].isna().sum()),
        "isyatirim_tl_volume_zero_count": int(frame["is_tl_volume"].eq(0).sum()),
        "yfinance_share_volume_missing_count": int(frame["yf_share_volume"].isna().sum()),
        "yfinance_share_volume_zero_count": int(frame["yf_share_volume"].eq(0).sum()),
        "both_volumes_zero_count": int(frame["both_volumes_zero"].sum()),
        "both_volumes_missing_count": int(frame["both_volumes_missing"].sum()),
        "open_present_both_volumes_missing_count": int(
            (frame["has_open"] & frame["both_volumes_missing"]).sum()
        ),
        "one_volume_missing_count": int(frame["one_volume_missing"].sum()),
        "one_volume_zero_other_positive_count": int(
            frame["one_volume_zero_other_positive"].sum()
        ),
        "no_open_status_count": int(frame["entry_exclusion_reason"].eq("NO_OPEN").sum()),
        "invalid_ohlc_status_count": int(
            frame["entry_exclusion_reason"].eq("INVALID_OHLC").sum()
        ),
        "corporate_action_window_status_count": int(
            frame["label_exclusion_reason"].eq("CORPORATE_ACTION_WINDOW").sum()
        ),
        "provider_open_evaluable_count": provider_open_evaluable,
        "provider_open_inconsistency_count": provider_open_inconsistent,
        "provider_open_validity_rate": _safe_rate(
            provider_open_evaluable - provider_open_inconsistent,
            provider_open_evaluable,
        ),
        "nominal_open_evaluable_count": nominal_open_evaluable,
        "nominal_open_inconsistency_count": nominal_open_inconsistent,
        "nominal_open_validity_rate": _safe_rate(
            nominal_open_evaluable - nominal_open_inconsistent,
            nominal_open_evaluable,
        ),
        "open_validity_rate_change": (
            _safe_rate(
                nominal_open_evaluable - nominal_open_inconsistent,
                nominal_open_evaluable,
            )
            - _safe_rate(
                provider_open_evaluable - provider_open_inconsistent,
                provider_open_evaluable,
            )
        ),
        "source_price_conflict_count": int(frame["source_price_conflict"].eq(True).sum()),
        "nominal_source_price_conflict_count": int(
            frame["nominal_source_price_conflict"].eq(True).sum()
        ),
        "adjustment_factor_change_count": int(frame["adjustment_factor_changed"].sum()),
        "yfinance_dividend_event_count": int(frame["has_yfinance_dividend"].sum()),
        "yfinance_split_event_count": int(frame["has_yfinance_split"].sum()),
        "both_sources_action_signal_count": int(frame["corporate_action_source"].eq("both").sum()),
        "isyatirim_only_action_signal_count": int(
            frame["corporate_action_source"].eq("isyatirim_only").sum()
        ),
        "yfinance_only_action_signal_count": int(
            frame["corporate_action_source"].eq("yfinance_only").sum()
        ),
    }
    for field in ("high", "low", "close"):
        for kind in ("absolute", "percentage"):
            column = f"{field}_{kind}_difference"
            result[f"{column}_median"] = _quantile(frame[column], 0.50)
            result[f"{column}_p95"] = _quantile(frame[column], 0.95)
            result[f"{column}_max"] = float(frame[column].max()) if frame[column].notna().any() else math.nan
            nominal_column = f"nominal_{column}"
            result[f"{nominal_column}_median"] = _quantile(
                frame[nominal_column], 0.50
            )
            result[f"{nominal_column}_p95"] = _quantile(
                frame[nominal_column], 0.95
            )
            result[f"{nominal_column}_max"] = (
                float(frame[nominal_column].max())
                if frame[nominal_column].notna().any()
                else math.nan
            )
    return result


def calculate_metrics(quality: pd.DataFrame, periods: Iterable[PeriodSpec]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for period in periods:
        start = pd.Timestamp(period.start)
        end = pd.Timestamp(period.end)
        period_frames: list[pd.DataFrame] = []
        for ticker in period.tickers:
            frame = quality[
                quality["ticker"].eq(ticker)
                & quality["date"].between(start, end, inclusive="both")
            ]
            rows.append(calculate_metric_row(frame, ticker, period))
            period_frames.append(frame)
        aggregate = pd.concat(period_frames, ignore_index=True) if period_frames else quality.iloc[0:0]
        rows.append(calculate_metric_row(aggregate, "__ALL__", period))
    return pd.DataFrame(rows)


def _calculate_scale_row(
    frame: pd.DataFrame,
    *,
    period: PeriodSpec,
    ticker: str,
    day_group: str,
    ticker_has_split: bool,
) -> dict[str, object]:
    provider_evaluable = int(frame["provider_open_within_is_range"].notna().sum())
    provider_inconsistent = int(
        frame["provider_open_within_is_range"].eq(False).sum()
    )
    nominal_evaluable = int(frame["nominal_open_within_is_range"].notna().sum())
    nominal_inconsistent = int(frame["nominal_open_within_is_range"].eq(False).sum())
    provider_rate = _safe_rate(
        provider_evaluable - provider_inconsistent, provider_evaluable
    )
    nominal_rate = _safe_rate(
        nominal_evaluable - nominal_inconsistent, nominal_evaluable
    )
    comparable = frame[
        ["provider_open_within_is_range", "nominal_open_within_is_range"]
    ].notna().all(axis=1)
    improved = int(
        (
            comparable
            & frame["provider_open_within_is_range"].eq(False)
            & frame["nominal_open_within_is_range"].eq(True)
        ).sum()
    )
    worsened = int(
        (
            comparable
            & frame["provider_open_within_is_range"].eq(True)
            & frame["nominal_open_within_is_range"].eq(False)
        ).sum()
    )
    return {
        "period": period.name,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "ticker": ticker,
        "ticker_has_split": ticker_has_split,
        "day_group": day_group,
        "row_count": len(frame),
        "provider_evaluable_count": provider_evaluable,
        "provider_inconsistency_count": provider_inconsistent,
        "provider_validity_rate": provider_rate,
        "nominal_evaluable_count": nominal_evaluable,
        "nominal_inconsistency_count": nominal_inconsistent,
        "nominal_validity_rate": nominal_rate,
        "validity_rate_change": nominal_rate - provider_rate,
        "provider_to_nominal_improved_count": improved,
        "provider_to_nominal_worsened_count": worsened,
        "provider_open_range_gap_median": _quantile(
            frame["provider_open_range_gap"], 0.50
        ),
        "provider_open_range_gap_p95": _quantile(
            frame["provider_open_range_gap"], 0.95
        ),
        "provider_open_range_gap_max": (
            float(frame["provider_open_range_gap"].max())
            if frame["provider_open_range_gap"].notna().any()
            else math.nan
        ),
        "nominal_open_range_gap_median": _quantile(
            frame["nominal_open_range_gap"], 0.50
        ),
        "nominal_open_range_gap_p95": _quantile(
            frame["nominal_open_range_gap"], 0.95
        ),
        "nominal_open_range_gap_max": (
            float(frame["nominal_open_range_gap"].max())
            if frame["nominal_open_range_gap"].notna().any()
            else math.nan
        ),
    }


def calculate_scale_metrics(
    quality: pd.DataFrame, periods: Iterable[PeriodSpec]
) -> pd.DataFrame:
    """Compare provider and reconstructed nominal open scales by scope."""
    rows: list[dict[str, object]] = []
    split_tickers = set(quality.loc[quality["has_yfinance_split"], "ticker"])
    day_groups = (
        ("all_days", None),
        ("normal_day", "normal_day"),
        ("dividend_day", "dividend_day"),
        ("split_day", "split_day"),
        ("adjustment_factor_change_day", "adjustment_factor_change_day"),
    )
    for period in periods:
        base = quality[
            quality["ticker"].isin(period.tickers)
            & quality["date"].between(
                pd.Timestamp(period.start), pd.Timestamp(period.end), inclusive="both"
            )
        ]
        scopes: list[tuple[str, pd.DataFrame, bool]] = [
            (
                ticker,
                base[base["ticker"].eq(ticker)],
                ticker in split_tickers,
            )
            for ticker in period.tickers
        ]
        scopes.append(("__ALL__", base, bool(set(period.tickers) & split_tickers)))
        split_scope = base[base["ticker"].isin(split_tickers)]
        if not split_scope.empty:
            scopes.append(("__SPLIT_TICKERS__", split_scope, True))

        for ticker, scope, ticker_has_split in scopes:
            for day_group, flag_column in day_groups:
                frame = scope if flag_column is None else scope[scope[flag_column]]
                rows.append(
                    _calculate_scale_row(
                        frame,
                        period=period,
                        ticker=ticker,
                        day_group=day_group,
                        ticker_has_split=ticker_has_split,
                    )
                )
    return pd.DataFrame(rows)


def build_remaining_mismatch_examples(
    quality: pd.DataFrame, period: PeriodSpec, limit: int = 20
) -> pd.DataFrame:
    """Return the largest normal-day nominal-open range misses without duplicates."""
    frame = quality[
        quality["ticker"].isin(period.tickers)
        & quality["date"].between(
            pd.Timestamp(period.start), pd.Timestamp(period.end), inclusive="both"
        )
        & quality["normal_day"]
        & quality["nominal_open_within_is_range"].eq(False)
    ].copy()
    columns = [
        "ticker",
        "date",
        "yf_provider_open",
        "yf_future_split_factor",
        "yf_nominal_open",
        "is_raw_low",
        "is_raw_high",
        "is_raw_close",
        "provider_open_within_is_range",
        "nominal_open_within_is_range",
        "nominal_open_range_gap",
        "nominal_open_range_gap_pct",
    ]
    return frame.nlargest(limit, "nominal_open_range_gap")[columns].reset_index(
        drop=True
    )


def determine_acceptance_status(
    *,
    required_is: bool,
    required_yf: bool,
    errors: list[str],
    quality: pd.DataFrame,
) -> tuple[str, str]:
    """Return PASS/PARTIAL/FAIL without a cross-source percentage threshold."""
    if errors:
        return (
            "FAIL",
            f"Kaynak koşusu {len(errors)} sağlayıcı hatasıyla eksik kaldı; "
            "gerekli tüm hisse ve dönemler alınamadı.",
        )
    if not required_is or not required_yf or quality.empty:
        return "FAIL", "Gerekli kaynak, alan veya eksiksiz veri koşusu sağlanamadı."

    required_quality_columns = {
        "valid_nominal_ohlc",
        "split_factor_unavailable",
        "nominal_conversion_consistent",
        "entry_exclusion_reason",
        "label_exclusion_reason",
        "cross_source_price_warning",
    }
    missing_quality_columns = required_quality_columns.difference(quality.columns)
    if missing_quality_columns:
        return (
            "FAIL",
            f"Gerekli kalite alanları üretilemedi: {sorted(missing_quality_columns)}",
        )
    if bool(quality["split_factor_unavailable"].any()):
        return "FAIL", "En az bir yFinance satırında split faktörü üretilemedi."
    if not bool(quality["nominal_conversion_consistent"].all()):
        return "FAIL", "Nominal OHLC alanlarına aynı split faktörü uygulanmadı."
    if not bool(quality["has_yfinance_split"].any()):
        return "PARTIAL", "Gerçek bir split olayı gözlenmedi; unit testleri geçtiği halde gerçek veri doğrulaması yapılamadı."

    evaluable = quality["valid_nominal_ohlc"].notna()
    if not bool(evaluable.any()):
        return "FAIL", "Değerlendirilebilir nominal OHLC satırı üretilemedi."
    if not bool(quality.loc[evaluable, "valid_nominal_ohlc"].any()):
        return "FAIL", "Değerlendirilebilir nominal OHLC satırlarının tamamı geçersiz."

    missing_rows = int((~evaluable).sum())
    invalid_rows = int(quality["valid_nominal_ohlc"].eq(False).sum())
    warning_rows = int(quality["cross_source_price_warning"].eq(True).sum())
    return (
        "PASS",
        "yFinance nominal OHLC üretimi ve iç tutarlılığı doğrulandı; "
        f"{missing_rows} eksik ve {invalid_rows} geçersiz satır açık durum kodlarıyla "
        f"dışlanabilir. {warning_rows} çapraz kaynak fiyat farkı yalnız kalite "
        "uyarısıdır ve kabul sonucunu etkilemez.",
    )


def _fetch_with_retry(function: Callable[[], pd.DataFrame], source: str, ticker: str) -> pd.DataFrame:
    last_error: Exception | None = None
    maximum_attempts = 5
    for attempt in range(1, maximum_attempts + 1):
        try:
            return function()
        except Exception as error:  # network/provider errors need retry context
            last_error = error
            if attempt < maximum_attempts:
                time.sleep(attempt * 3)
    raise RuntimeError(
        f"{source} failed for {ticker} after {maximum_attempts} attempts: {last_error}"
    ) from last_error


def fetch_isyatirim_in_chunks(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch at most one calendar year per request to reduce provider timeouts."""
    chunks: list[pd.DataFrame] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(date(chunk_start.year, 12, 31), end)
        label = f"{ticker} {chunk_start.isoformat()}..{chunk_end.isoformat()}"
        chunk = _fetch_with_retry(
            lambda start_value=chunk_start, end_value=chunk_end: fetch_stock_data(
                ticker,
                start_value.strftime("%d-%m-%Y"),
                end_value.strftime("%d-%m-%Y"),
            ),
            "İş Yatırım",
            label,
        )
        chunks.append(chunk)
        chunk_start = chunk_end + timedelta(days=1)
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True).drop_duplicates(
        ["HGDG_HS_KODU", "HGDG_TARIH"], keep="last"
    )


def fetch_sources(
    tickers: Iterable[str], start: date, end: date
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], list[str], list[str]]:
    is_frames: list[pd.DataFrame] = []
    yf_frames: list[pd.DataFrame] = []
    is_columns: set[str] = set()
    yf_columns: set[str] = set()
    errors: list[str] = []

    for ticker in tickers:
        print(f"Fetching {ticker}: İş Yatırım", flush=True)
        try:
            raw_is = fetch_isyatirim_in_chunks(ticker, start, end)
            is_columns.update(map(str, raw_is.columns))
            is_frames.append(normalize_isyatirim_history(raw_is, ticker))
        except Exception as error:
            errors.append(str(error))

        print(f"Fetching {ticker}: yFinance", flush=True)
        try:
            # yFinance's end boundary is exclusive; add one day for inclusive periods.
            raw_yf = _fetch_with_retry(
                lambda: yf.Ticker(f"{ticker}.IS").history(
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                    actions=True,
                ),
                "yFinance",
                ticker,
            )
            if raw_yf.empty:
                raise ValueError(f"yFinance returned no rows for {ticker}")
            yf_columns.update(map(str, raw_yf.columns))
            yf_frames.append(normalize_yfinance_history(raw_yf, ticker))
        except Exception as error:
            errors.append(str(error))

    empty_is = pd.DataFrame(columns=["ticker", "date"])
    empty_yf = pd.DataFrame(columns=["ticker", "date"])
    return (
        pd.concat(is_frames, ignore_index=True) if is_frames else empty_is,
        pd.concat(yf_frames, ignore_index=True) if yf_frames else empty_yf,
        sorted(is_columns),
        sorted(yf_columns),
        errors,
    )


def build_actions_report(quality: pd.DataFrame, periods: Iterable[PeriodSpec]) -> pd.DataFrame:
    period_membership: dict[tuple[str, pd.Timestamp], list[str]] = {}
    for period in periods:
        for ticker in period.tickers:
            mask = (
                quality["ticker"].eq(ticker)
                & quality["date"].between(pd.Timestamp(period.start), pd.Timestamp(period.end), inclusive="both")
            )
            for event_date in quality.loc[mask, "date"]:
                period_membership.setdefault((ticker, event_date), []).append(period.name)

    actions = quality[quality["has_any_corporate_action_signal"]].copy()
    actions["periods"] = [
        ";".join(period_membership.get((ticker, event_date), []))
        for ticker, event_date in zip(actions["ticker"], actions["date"])
    ]
    actions = actions[actions["periods"].ne("")]
    columns = [
        "ticker",
        "date",
        "periods",
        "adjustment_factor",
        "previous_adjustment_factor",
        "adjustment_factor_changed",
        "yf_provider_open",
        "yf_future_split_factor",
        "yf_nominal_open",
        "yf_dividends",
        "yf_stock_splits",
        "yf_capital_gains",
        "yf_other_action_value",
        "has_yfinance_dividend",
        "has_yfinance_split",
        "has_yfinance_other_action",
        "normal_day",
        "dividend_day",
        "split_day",
        "adjustment_factor_change_day",
        "corporate_action_source",
    ]
    return actions[columns].sort_values(["ticker", "date"]).reset_index(drop=True)


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "_Kayıt yok._"
    view = frame[columns].copy()
    for column in view.select_dtypes(include="number").columns:
        view[column] = view[column].map(lambda value: "" if pd.isna(value) else f"{value:.6g}")
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    ]
    return "\n".join([header, divider, *rows])


def write_summary(
    path: Path,
    *,
    run_date: date,
    periods: tuple[PeriodSpec, ...],
    metrics: pd.DataFrame,
    scale_metrics: pd.DataFrame,
    actions: pd.DataFrame,
    remaining_examples: pd.DataFrame,
    quality: pd.DataFrame,
    is_columns: list[str],
    yf_columns: list[str],
    errors: list[str],
    acceptance_status: str,
    acceptance_reason: str,
) -> None:
    aggregate = metrics[metrics["ticker"].eq("__ALL__")]
    overall_observation = quality[
        quality["date"].between(
            pd.Timestamp(date(2020, 3, 13)),
            pd.Timestamp(run_date),
            inclusive="both",
        )
    ]
    required_is_observed = ISYATIRIM_REQUIRED_COLUMNS.issubset(is_columns)
    required_yf_observed = YFINANCE_REQUIRED_COLUMNS.issubset(yf_columns)
    total_yf_events = int(overall_observation["has_yfinance_action"].sum())
    total_factor_changes = int(overall_observation["adjustment_factor_changed"].sum())
    scoped_action_rows = len(actions)
    corporate_action_windows = int(overall_observation["corporate_action_window"].sum())
    open_with_both_missing = int(
        (overall_observation["has_open"] & overall_observation["both_volumes_missing"]).sum()
    )
    d022 = (
        "UYGULANABİLİR"
        if required_is_observed
        and required_yf_observed
        and "entry_exclusion_reason" in quality
        else "UYGULANAMADI"
    )
    d023 = (
        "UYGULANABİLİR (tespit sinyallerinin bilinen sınırlamalarıyla)"
        if total_yf_events > 0
        and total_factor_changes > 0
        and "label_exclusion_reason" in quality
        else "UYGULANAMADI"
    )

    period_lines = "\n".join(
        f"- `{period.name}`: {period.start.isoformat()} – {period.end.isoformat()}; "
        f"{', '.join(period.tickers)}"
        for period in periods
    )
    issue_lines = (
        "\n".join(f"- {error}" for error in errors)
        if errors
        else f"- {acceptance_reason}"
    )
    metric_columns = [
        "period",
        "expected_isyatirim_days",
        "yfinance_matching_days",
        "yfinance_date_match_rate",
        "missing_nominal_open_count",
        "missing_nominal_high_low_close_count",
        "invalid_nominal_ohlc_count",
        "nominal_ohlc_validity_rate",
        "split_factor_unavailable_count",
        "corporate_action_window_count",
        "cross_source_price_warning_count",
        "open_present_both_volumes_missing_count",
    ]
    action_columns = [
        "ticker",
        "date",
        "yf_dividends",
        "yf_stock_splits",
        "yf_future_split_factor",
        "corporate_action_source",
    ]
    example_columns = [
        "ticker",
        "date",
        "yf_nominal_open",
        "is_raw_low",
        "is_raw_high",
        "nominal_open_range_gap",
        "nominal_open_range_gap_pct",
    ]

    next_task = (
        "D022 ve D023 durum kodlarını modüler veri temizleme koduna taşımak; "
        "ardından değişmez ham yFinance yanıtı/split sürümleme altyapısını kurmak."
        if acceptance_status == "PASS"
        else "Sağlayıcı erişimi kararlı olduğunda eksiksiz gerçek veri kabul "
        "koşusunu yeniden çalıştırmak; kabul verilmeden genel veri/label akışına geçmemek."
    )

    text = f"""# Tek Fiyat Kaynağı Kabul Testi Özeti

**Çalıştırma tarihi:** {run_date.isoformat()}

**Üretim zamanı:** {datetime.now().astimezone().isoformat(timespec='seconds')}

**Kaynak kabul sonucu:** `{acceptance_status}`

**Sonuç gerekçesi:** {acceptance_reason}

## Ana fiyat kaynağı

İlk sürümde giriş, label, çıkış, OHLC geçerlilik ve tavan hesabı için tek fiyat kaynağı **yFinance nominal OHLC** serisidir. İş Yatırım fiyatları ana işlem hesabına katılmaz; yalnız `cross_source_price_warning` kalite uyarısı, kurumsal işlem sinyali ve denetim amacıyla kullanılır.

Orijinal yFinance değerleri `yf_provider_open/high/low/close` alanlarında değiştirilmeden tutulur. Nominal dönüşüm:

```text
yf_future_split_factor[t] = t tarihinden kesinlikle sonra gerçekleşen geçerli split oranlarının çarpımı
yf_nominal_price[t] = yf_provider_price[t] × yf_future_split_factor[t]
```

Split gününün kendi oranı aynı günün fiyatına uygulanmaz. Aynı faktör open, high, low ve close alanlarının tamamına uygulanır.

## Kullanılan ortam ve kütüphane sürümleri

- Python: `{platform.python_version()}`
- İşletim sistemi: `{platform.platform()}`
- pandas: `{_package_version('pandas')}`
- numpy: `{_package_version('numpy')}`
- isyatirimhisse: `{_package_version('isyatirimhisse')}`
- yfinance: `{_package_version('yfinance')}`
- requests: `{_package_version('requests')}`
- pytest: `{_package_version('pytest')}`

## Test edilen hisseler ve dönemler

{period_lines}

Ana BİST işlem takvimi İş Yatırım'dan kuruldu. yFinance `end` sınırının hariç olması ve Europe/Istanbul yerel tarihleri açıkça ele alındı.

## Kaynak alanları

- İş Yatırım zorunlu alanları mevcut: **{'evet' if required_is_observed else 'hayır'}**
- yFinance zorunlu alanları mevcut: **{'evet' if required_yf_observed else 'hayır'}**
- İş Yatırım sütunları: `{', '.join(is_columns)}`
- yFinance sütunları: `{', '.join(yf_columns)}`

Bu kabul çalıştırıcısı ham yanıtları repoya yazmaz. D024'ün gerektirdiği değişmez ham yanıt/split sürümleme ve yeniden indirme farkı tespiti, veri toplama altyapısında uygulanması gereken açık tekrarlanabilirlik işidir.

## Nominal OHLC iç tutarlılığı ve eksikler

Ana kontrol yalnız tek kaynaklı nominal alanlarla yapılır:

```text
yf_nominal_low <= yf_nominal_open <= yf_nominal_high
yf_nominal_low <= yf_nominal_close <= yf_nominal_high
```

{_markdown_table(aggregate, metric_columns)}

Tekil eksik veya geçersiz satırlar `NO_OPEN`/`INVALID_OHLC` durumlarıyla `NA` bırakılabilir ve tek başına kabulü başarısız yapmaz. Hisse bazındaki ayrıntılar `source_acceptance_metrics.csv` dosyasındadır.

## Hacim sonuçları

Açılış mevcutken iki hacmin de eksik olduğu benzersiz takvim kaydı: **{open_with_both_missing}**. İş Yatırım TL hacmi ve yFinance pay adedi birlikte sıfırsa `NO_TRADE`; tek kaynak eksik/sıfırsa `SOURCE_VOLUME_CONFLICT` kalite uyarısı üretilir. İki hacim de eksikken open mevcutsa D022 uyarınca yeni bir kesin karar verilmez.

## D022 ve D023 uygulanabilirliği

- **D022: {d022}.** Giriş fiyatı `yf_nominal_open` üzerinden değerlendirilir. `NO_OPEN`, `NO_TRADE` ve `INVALID_OHLC` kodları üretilebilir.
- **D023: {d023}.** `T+1–T+3` içinde kurumsal işlem sinyali bulunan **{corporate_action_windows}** tahmin satırı `CORPORATE_ACTION_WINDOW` ile `NA` yapılabilir.
- Kapsama giren benzersiz action satırı: **{scoped_action_rows}**; yFinance action günü: **{total_yf_events}**; İş Yatırım düzeltme faktörü değişim günü: **{total_factor_changes}**.

{_markdown_table(actions.head(30), action_columns)}

## Çapraz kaynak fiyat kalite uyarıları

İş Yatırım ham fiyatları yFinance nominal fiyatlarıyla yalnız kalite kontrolü için karşılaştırıldı. Farklar `cross_source_price_warning` üretir; satırı otomatik dışlamaz ve `PASS/PARTIAL/FAIL` sonucunu etkilemez. Sabit bir yüzdesel veya fiyat-adımı eşiği eklenmedi.

En büyük normal-gün nominal-open/İş Yatırım aralık farklarından örnekler:

{_markdown_table(remaining_examples, example_columns)}

Ayrıntılı karşılaştırmalar `source_scale_normalization.csv` dosyasındadır. Bunlar ana OHLC başarı metriği değildir.

## Veri sızıntısı kontrolü

- `yf_future_split_factor` ve action alanları `MODEL_FEATURE_COLUMNS` içinde değildir; LightGBM'e ve tahmin sinyaline verilmez.
- Gelecekteki split bilgisi yalnız geçmiş fiyat birimini dönemin nominal ölçeğine geri kurar.
- Aynı split faktörü open, high, low ve close'a birlikte uygulanır; dönüşüm oran ilişkilerini değiştirmez.
- `T+1–T+3` kurumsal işlem penceresi yalnız label/backtest uygunluğunda `NA` üretir, tahmin feature'ı değildir.
- İş Yatırım düzeltilmiş/ham faktörü ve çapraz fiyat farkı yalnız kalite alanıdır.
- Bu görev model feature'ı, label veya backtest sonucu üretmez.

## Tekrarlanabilirlik ve bilinen sınırlamalar

- yFinance geçmiş action ve fiyat değerlerini sonradan revize edebilir.
- Ham yFinance yanıtları ve split kayıtları değişmez veri sürümleriyle saklanmadan eski koşular birebir yeniden üretilemez.
- Bu kabul çalıştırıcısı ham kaynakları sürümlemediği için yeniden indirme farkı henüz otomatik tespit edilmez.
- İş Yatırım düzeltme faktörü olay türünü tek başına kanıtlamaz; KAP ilk sürümün zorunlu kaynağı değildir.

## Başarısız veya eksik kalan kontroller

{issue_lines}

## Açık sorular

- Açılış mevcutken iki hacim alanının da eksik olduğu kayıtların nihai davranışı ayrı karara ihtiyaç duyar.
- İş Yatırım faktör değişim sinyalinin olay tarihi ve türü için ek doğrulama yöntemi gerekebilir.
- Ham veri sürümleme ve sağlayıcı revizyon farkı tespiti veri toplama altyapısında henüz uygulanmadı.

## Önerilen sıradaki görev

{next_task}
"""
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Inclusive analysis end date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/source_acceptance"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    periods = build_periods(args.run_date)
    # Fetch a few preceding sessions so a change on 2020-03-13 can be compared
    # with its prior factor; metrics still begin on the decided model date.
    fetch_start = date(2020, 3, 1)
    is_frame, yf_frame, is_columns, yf_columns, errors = fetch_sources(
        DEFAULT_TICKERS, fetch_start, args.run_date
    )
    if is_frame.empty:
        print("SOURCE_ACCEPTANCE_STATUS=FAIL", file=sys.stderr)
        print("No İş Yatırım rows were fetched; reports cannot be produced.", file=sys.stderr)
        return 2

    quality = build_quality_frame(is_frame, yf_frame)
    metrics = calculate_metrics(quality, periods)
    scale_metrics = calculate_scale_metrics(quality, periods)
    actions = build_actions_report(quality, periods)
    full_period = next(period for period in periods if period.name == "full_period")
    remaining_examples = build_remaining_mismatch_examples(quality, full_period)

    required_is = ISYATIRIM_REQUIRED_COLUMNS.issubset(is_columns)
    required_yf = YFINANCE_REQUIRED_COLUMNS.issubset(yf_columns)
    acceptance_status, acceptance_reason = determine_acceptance_status(
        required_is=required_is,
        required_yf=required_yf,
        errors=errors,
        quality=quality,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "source_acceptance_metrics.csv"
    actions_path = args.output_dir / "source_acceptance_actions.csv"
    scale_path = args.output_dir / "source_scale_normalization.csv"
    summary_path = args.output_dir / "source_acceptance_summary.md"
    metrics.to_csv(metrics_path, index=False, encoding="utf-8")
    actions.to_csv(actions_path, index=False, encoding="utf-8")
    scale_metrics.to_csv(scale_path, index=False, encoding="utf-8")
    write_summary(
        summary_path,
        run_date=args.run_date,
        periods=periods,
        metrics=metrics,
        scale_metrics=scale_metrics,
        actions=actions,
        remaining_examples=remaining_examples,
        quality=quality,
        is_columns=is_columns,
        yf_columns=yf_columns,
        errors=errors,
        acceptance_status=acceptance_status,
        acceptance_reason=acceptance_reason,
    )

    print(f"Wrote {metrics_path}")
    print(f"Wrote {actions_path}")
    print(f"Wrote {scale_path}")
    print(f"Wrote {summary_path}")
    print(f"SOURCE_ACCEPTANCE_STATUS={acceptance_status}")
    print(f"SOURCE_ACCEPTANCE_REASON={acceptance_reason}")
    if acceptance_status == "PARTIAL":
        return 1
    if acceptance_status == "FAIL":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
