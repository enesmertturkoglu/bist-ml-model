"""Reusable D022/D023 market-data cleaning and eligibility rules."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from src.config import CleaningConfig
from src.data.price_limits import (
    PriceStepTable,
    calculate_raw_upper_limit,
    calculate_upper_limit,
    is_above_price,
    prices_equal,
)
from src.data.yfinance_normalization import (
    YFINANCE_KNOWN_ACTION_COLUMNS,
    YFINANCE_PRICE_COLUMNS,
)


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
NOMINAL_OHLC_COLUMNS = (
    "yf_nominal_open",
    "yf_nominal_high",
    "yf_nominal_low",
    "yf_nominal_close",
)
NON_FEATURE_AUDIT_COLUMNS = {
    "yf_future_split_factor",
    "yf_stock_splits",
    "yf_dividends",
    "yf_capital_gains",
    "yf_other_action_value",
    "corporate_action_flag",
    "corporate_action_window_flag",
    "corporate_action_signal_sources",
    "input_snapshot_ids",
    "input_snapshot_checksums",
}


def normalize_isyatirim_history(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize İş Yatırım calendar, volume and audit fields without using its prices."""

    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date"])
    missing = ISYATIRIM_REQUIRED_COLUMNS.difference(raw.columns)
    if missing:
        raise ValueError(
            f"İş Yatırım required columns missing for {ticker}: {sorted(missing)}"
        )
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
    frame["ticker"] = ticker.strip().upper()
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
    return (
        frame[keep]
        .sort_values(["ticker", "date"])
        .drop_duplicates(["ticker", "date"], keep="last")
        .reset_index(drop=True)
    )


def extract_yfinance_auxiliary(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Read only volume/actions from a stored raw yFinance frame.

    Provider OHLC columns are deliberately omitted so price-dependent cleaning
    cannot accidentally bypass the verified nominal snapshot.
    """

    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date"])
    if "date" not in raw:
        raise ValueError("stored yFinance raw snapshot is missing date")
    frame = raw.copy()
    frame["ticker"] = ticker.strip().upper()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    rename = {
        "Volume": "yf_share_volume",
        "Dividends": "yf_dividends",
        "Stock Splits": "yf_stock_splits",
        "Capital Gains": "yf_capital_gains",
    }
    frame = frame.rename(columns=rename)
    for target in rename.values():
        if target not in frame:
            frame[target] = np.nan if target == "yf_share_volume" else 0.0

    known = {
        *YFINANCE_PRICE_COLUMNS,
        *YFINANCE_KNOWN_ACTION_COLUMNS,
        "ticker",
        "date",
        *rename.values(),
    }
    other_columns = [column for column in raw.columns if str(column) not in known]
    other_values = pd.DataFrame(index=frame.index)
    for column in other_columns:
        converted = pd.to_numeric(raw[column], errors="coerce")
        if converted.notna().any():
            other_values[str(column)] = converted
    frame["yf_other_action_value"] = (
        other_values.fillna(0).abs().sum(axis=1) if not other_values.empty else 0.0
    )
    keep = [
        "ticker",
        "date",
        "yf_share_volume",
        "yf_dividends",
        "yf_stock_splits",
        "yf_capital_gains",
        "yf_other_action_value",
    ]
    return (
        frame[keep]
        .sort_values(["ticker", "date"])
        .drop_duplicates(["ticker", "date"], keep="last")
        .reset_index(drop=True)
    )


def mark_adjustment_factor_changes(
    frame: pd.DataFrame,
    *,
    rtol: float = 1e-4,
    atol: float = 5e-5,
) -> pd.DataFrame:
    """Flag material changes in İş Yatırım adjusted/raw close ratio."""

    result = frame.sort_values(["ticker", "date"]).copy()
    raw_close = pd.to_numeric(result["is_raw_close"], errors="coerce")
    adjusted_close = pd.to_numeric(result["is_adjusted_close"], errors="coerce")
    valid = raw_close.notna() & np.isfinite(raw_close) & raw_close.gt(0)
    result["adjustment_factor"] = np.nan
    result.loc[valid, "adjustment_factor"] = adjusted_close.loc[valid] / raw_close.loc[valid]
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


def validate_nominal_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate OHLC solely on yFinance nominal values."""

    missing = set(NOMINAL_OHLC_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"nominal OHLC fields missing: {sorted(missing)}")
    result = frame.copy()
    for column in NOMINAL_OHLC_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        result[f"missing_{column.removeprefix('yf_')}"] = result[column].isna()

    open_value = result["yf_nominal_open"]
    result["has_open"] = open_value.notna() & np.isfinite(open_value) & open_value.gt(0)
    other_columns = list(NOMINAL_OHLC_COLUMNS[1:])
    complete = result[list(NOMINAL_OHLC_COLUMNS)].notna().all(axis=1)
    finite = pd.DataFrame(
        {column: np.isfinite(result[column]) for column in NOMINAL_OHLC_COLUMNS}
    ).all(axis=1)
    positive = result[list(NOMINAL_OHLC_COLUMNS)].gt(0).all(axis=1)
    relationships = (
        result["yf_nominal_low"].le(result["yf_nominal_open"])
        & result["yf_nominal_open"].le(result["yf_nominal_high"])
        & result["yf_nominal_low"].le(result["yf_nominal_close"])
        & result["yf_nominal_close"].le(result["yf_nominal_high"])
    )
    valid = complete & finite & positive & relationships
    result["valid_nominal_ohlc"] = pd.Series(pd.NA, index=result.index, dtype="boolean")
    result.loc[result["has_open"], "valid_nominal_ohlc"] = valid.loc[result["has_open"]]
    result["valid_ohlc"] = result["valid_nominal_ohlc"]
    result["missing_nominal_high_low_close"] = result[other_columns].isna().any(axis=1)
    result["ohlc_quality_flag"] = np.select(
        [
            ~result["has_open"],
            result["valid_nominal_ohlc"].eq(False).fillna(False).to_numpy(dtype=bool),
        ],
        ["NO_OPEN", "INVALID_OHLC"],
        default="VALID",
    )
    return result


def evaluate_volume_quality(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply D022 dual-volume rules without inventing a liquidity threshold."""

    result = frame.copy()
    for column in ("is_tl_volume", "yf_share_volume"):
        if column not in result:
            result[column] = np.nan
        result[column] = pd.to_numeric(result[column], errors="coerce")
    is_volume = result["is_tl_volume"]
    yf_volume = result["yf_share_volume"]
    is_positive = is_volume.gt(0)
    yf_positive = yf_volume.gt(0)
    result["has_isyatirim_tl_volume"] = is_volume.notna()
    result["has_yfinance_share_volume"] = yf_volume.notna()
    result["both_volumes_zero"] = is_volume.eq(0) & yf_volume.eq(0)
    result["both_volumes_missing"] = is_volume.isna() & yf_volume.isna()
    result["one_volume_missing"] = is_volume.isna() ^ yf_volume.isna()
    result["one_volume_zero_other_positive"] = (
        (is_volume.eq(0) & yf_positive) | (yf_volume.eq(0) & is_positive)
    )
    result["positive_volume_evidence"] = is_positive | yf_positive
    result["volume_source_conflict"] = result["positive_volume_evidence"] & (
        result["one_volume_missing"] | result["one_volume_zero_other_positive"]
    )
    invalid_negative = is_volume.lt(0) | yf_volume.lt(0)
    insufficient = (
        ~result["both_volumes_zero"]
        & ~result["both_volumes_missing"]
        & ~result["positive_volume_evidence"]
    )
    result["volume_requires_review"] = result["both_volumes_missing"] | invalid_negative | insufficient
    result["volume_quality_flag"] = np.select(
        [
            result["both_volumes_zero"],
            result["both_volumes_missing"],
            result["volume_source_conflict"],
            invalid_negative,
            insufficient,
        ],
        [
            "BOTH_VOLUMES_ZERO",
            "BOTH_VOLUMES_MISSING_UNRESOLVED",
            "SOURCE_VOLUME_CONFLICT",
            "INVALID_VOLUME_REQUIRES_REVIEW",
            "VOLUME_EVIDENCE_INSUFFICIENT",
        ],
        default="POSITIVE_VOLUME_CONFIRMED",
    )
    return result


def add_daily_corporate_action_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Combine independent daily action evidence while retaining its sources."""

    result = frame.copy()
    for column in (
        "yf_dividends",
        "yf_stock_splits",
        "yf_capital_gains",
        "yf_other_action_value",
    ):
        if column not in result:
            result[column] = 0.0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
    if "adjustment_factor_changed" not in result:
        result["adjustment_factor_changed"] = False
    is_action = result["adjustment_factor_changed"].fillna(False).astype(bool)
    result["has_yfinance_dividend"] = result["yf_dividends"].ne(0)
    result["has_yfinance_split"] = result["yf_stock_splits"].ne(0)
    result["has_yfinance_other_action"] = result[
        ["yf_capital_gains", "yf_other_action_value"]
    ].abs().sum(axis=1).gt(0)
    yf_action = result[
        ["has_yfinance_dividend", "has_yfinance_split", "has_yfinance_other_action"]
    ].any(axis=1)
    result["has_yfinance_action"] = yf_action
    result["corporate_action_flag"] = is_action | yf_action
    result["has_any_corporate_action_signal"] = result["corporate_action_flag"]
    result["normal_day"] = ~result["corporate_action_flag"]
    result["dividend_day"] = result["has_yfinance_dividend"]
    result["split_day"] = result["has_yfinance_split"]
    result["adjustment_factor_change_day"] = is_action
    result["corporate_action_source"] = np.select(
        [is_action & yf_action, is_action, yf_action],
        ["both", "isyatirim_only", "yfinance_only"],
        default="none",
    )
    result["corporate_action_source_count"] = is_action.astype(int) + yf_action.astype(int)
    result["corporate_action_source_agreement"] = np.select(
        [is_action & yf_action, is_action ^ yf_action],
        ["BOTH_SOURCES", "SINGLE_SOURCE"],
        default="NO_SIGNAL",
    )
    result["corporate_action_signal_sources"] = [
        [
            *(["isyatirim_adjustment_factor"] if is_flag else []),
            *(["yfinance_actions"] if yf_flag else []),
        ]
        for is_flag, yf_flag in zip(is_action, yf_action, strict=True)
    ]
    return result


def add_corporate_action_windows(
    frame: pd.DataFrame,
    bist_calendar: Sequence[pd.Timestamp | str],
    *,
    horizon_days: int = 3,
) -> pd.DataFrame:
    """Build T+1..T+horizon action windows on the global BIST calendar."""

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    calendar = tuple(sorted(pd.to_datetime(pd.Index(bist_calendar)).normalize().unique()))
    position = {value: index for index, value in enumerate(calendar)}
    action_lookup = {
        (str(row.ticker), pd.Timestamp(row.date)): bool(row.corporate_action_flag)
        for row in result[["ticker", "date", "corporate_action_flag"]].itertuples(index=False)
    }
    source_lookup = {
        (str(row.ticker), pd.Timestamp(row.date)): list(row.corporate_action_signal_sources)
        for row in result[["ticker", "date", "corporate_action_signal_sources"]].itertuples(index=False)
    }
    flags: list[bool] = []
    dates_values: list[list[str]] = []
    sources_values: list[list[str]] = []
    complete_values: list[bool] = []
    for row in result[["ticker", "date"]].itertuples(index=False):
        index = position.get(pd.Timestamp(row.date))
        if index is None:
            raise ValueError(f"date {row.date} is absent from the supplied BIST calendar")
        future_dates = calendar[index + 1 : index + 1 + horizon_days]
        complete_values.append(len(future_dates) == horizon_days)
        signalled_dates = [
            value for value in future_dates if action_lookup.get((str(row.ticker), value), False)
        ]
        flags.append(bool(signalled_dates))
        dates_values.append([value.date().isoformat() for value in signalled_dates])
        sources = {
            source
            for value in signalled_dates
            for source in source_lookup.get((str(row.ticker), value), [])
        }
        sources_values.append(sorted(sources))
    result["corporate_action_window"] = flags
    result["corporate_action_window_flag"] = flags
    result["corporate_action_window_dates"] = dates_values
    result["corporate_action_window_signal_sources"] = sources_values
    result["corporate_action_window_complete"] = complete_values
    return result


def add_cross_source_price_warning(
    frame: pd.DataFrame,
    *,
    absolute_tolerance: float = 1e-8,
) -> pd.DataFrame:
    """Compare sources for audit only; never alter nominal prices or eligibility."""

    result = frame.copy()
    comparisons: list[pd.Series] = []
    for field in ("high", "low", "close"):
        is_column = f"is_raw_{field}"
        yf_column = f"yf_nominal_{field}"
        if is_column not in result:
            result[is_column] = np.nan
        comparable = result[[is_column, yf_column]].notna().all(axis=1)
        difference = (result[is_column] - result[yf_column]).abs()
        result[f"nominal_{field}_absolute_difference"] = difference.where(comparable)
        result[f"nominal_{field}_percentage_difference"] = (
            difference.div(result[is_column].abs().replace(0, np.nan)).mul(100).where(comparable)
        )
        comparisons.append(comparable & difference.gt(absolute_tolerance))
    any_comparable = result[
        [f"nominal_{field}_absolute_difference" for field in ("high", "low", "close")]
    ].notna().any(axis=1)
    result["cross_source_price_warning"] = pd.Series(
        pd.NA, index=result.index, dtype="boolean"
    )
    result.loc[any_comparable, "cross_source_price_warning"] = pd.concat(
        comparisons, axis=1
    ).any(axis=1).loc[any_comparable]
    return result


def _ordered_reasons(reasons: Iterable[str], priority: Sequence[str]) -> list[str]:
    unique = set(reasons)
    rank = {reason: index for index, reason in enumerate(priority)}
    return sorted(unique, key=lambda reason: (rank.get(reason, len(rank)), reason))


def evaluate_basic_entry_eligibility(
    frame: pd.DataFrame,
    *,
    reason_priority: Sequence[str] = CleaningConfig().reason_priority,
) -> pd.DataFrame:
    """Apply OHLC and volume-only entry rules shared with source acceptance."""

    result = frame.copy()
    reasons: list[list[str]] = []
    eligible: list[bool | pd._libs.missing.NAType] = []
    review: list[bool] = []
    for row in result.itertuples(index=False):
        row_reasons: list[str] = []
        if not bool(row.has_open):
            row_reasons.append("NO_OPEN")
        if bool(row.both_volumes_zero):
            row_reasons.append("NO_TRADE")
        if getattr(row, "ohlc_quality_flag") == "INVALID_OHLC":
            row_reasons.append("INVALID_OHLC")
        row_reasons = _ordered_reasons(row_reasons, reason_priority)
        unresolved = bool(row.volume_requires_review)
        reasons.append(row_reasons)
        review.append(unresolved)
        if row_reasons:
            eligible.append(False)
        elif unresolved:
            eligible.append(pd.NA)
        else:
            eligible.append(True)
    result["entry_exclusion_reasons"] = reasons
    result["entry_exclusion_reason"] = pd.Series(
        [values[0] if values else pd.NA for values in reasons], dtype="string"
    )
    result["entry_eligible"] = pd.Series(eligible, dtype="boolean")
    result["requires_review"] = review
    return result


def _calendar_grid(frame: pd.DataFrame, bist_calendar: Sequence[Any]) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.Index(bist_calendar))).normalize().unique().sort_values()
    tickers = sorted(map(str, frame["ticker"].dropna().unique()))
    grid = pd.MultiIndex.from_product(
        [tickers, calendar], names=["ticker", "date"]
    ).to_frame(index=False)
    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    if prepared.duplicated(["ticker", "date"]).any():
        raise ValueError("daily cleaning input contains duplicate ticker/date rows")
    return grid.merge(prepared, on=["ticker", "date"], how="left", validate="one_to_one")


def build_clean_eligibility_frame(
    daily_frame: pd.DataFrame,
    bist_calendar: Sequence[Any],
    price_steps: PriceStepTable,
    *,
    config: CleaningConfig | None = None,
) -> pd.DataFrame:
    """Create historical T prediction rows with T+1 entry eligibility.

    Only rows with a complete T+1..T+3 BIST-calendar window are emitted. Future
    action-window values are audit/exclusion fields and must never be features.
    """

    settings = config or CleaningConfig()
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.Index(bist_calendar))).normalize().unique().sort_values()
    if len(calendar) <= settings.corporate_action_horizon_days:
        return pd.DataFrame()
    result = _calendar_grid(daily_frame, calendar)
    result = validate_nominal_ohlc(result)
    result = evaluate_volume_quality(result)
    result = add_daily_corporate_action_signals(result)
    result = add_corporate_action_windows(
        result,
        calendar,
        horizon_days=settings.corporate_action_horizon_days,
    )
    result = add_cross_source_price_warning(
        result,
        absolute_tolerance=settings.cross_source_price_absolute_tolerance,
    )
    result = evaluate_basic_entry_eligibility(
        result, reason_priority=settings.reason_priority
    )

    valid_close = result["yf_nominal_close"].where(result["ohlc_quality_flag"].eq("VALID"))
    result["previous_nominal_close"] = valid_close.groupby(result["ticker"]).transform(
        lambda values: values.shift(1).ffill()
    )
    raw_limits: list[float | None] = []
    steps: list[float | None] = []
    limits: list[float | None] = []
    for row in result[["date", "previous_nominal_close"]].itertuples(index=False):
        raw_limit = calculate_raw_upper_limit(
            row.previous_nominal_close,
            margin=settings.upper_limit_margin,
        )
        calculation = calculate_upper_limit(
            row.previous_nominal_close,
            row.date,
            price_steps,
            margin=settings.upper_limit_margin,
        )
        raw_limits.append(calculation.raw_upper_limit if calculation else raw_limit)
        steps.append(calculation.price_step if calculation else None)
        limits.append(calculation.estimated_upper_limit if calculation else None)
    result["raw_upper_limit"] = raw_limits
    result["price_step"] = steps
    result["estimated_upper_limit"] = limits

    daily_lookup = result.set_index(["ticker", "date"], drop=False)
    output_rows: list[dict[str, Any]] = []
    last_prediction_position = len(calendar) - settings.corporate_action_horizon_days
    for ticker in sorted(result["ticker"].unique()):
        for position in range(last_prediction_position):
            prediction_date = calendar[position]
            entry_date = calendar[position + 1]
            prediction_row = daily_lookup.loc[(ticker, prediction_date)]
            entry_row = daily_lookup.loc[(ticker, entry_date)]
            reasons = list(entry_row["entry_exclusion_reasons"])
            requires_review = bool(entry_row["requires_review"])
            previous_close = entry_row["previous_nominal_close"]
            estimated_limit = entry_row["estimated_upper_limit"]
            if pd.isna(previous_close):
                reasons.append("NO_PREVIOUS_CLOSE")
                requires_review = True
            elif pd.isna(estimated_limit):
                reasons.append("PRICE_STEP_UNAVAILABLE")
                requires_review = True
            else:
                open_value = entry_row["yf_nominal_open"]
                high_value = entry_row["yf_nominal_high"]
                if pd.notna(open_value) and pd.notna(high_value) and (
                    is_above_price(
                        open_value,
                        estimated_limit,
                        relative_tolerance=settings.limit_price_relative_tolerance,
                        absolute_tolerance=settings.limit_price_absolute_tolerance,
                    )
                    or is_above_price(
                        high_value,
                        estimated_limit,
                        relative_tolerance=settings.limit_price_relative_tolerance,
                        absolute_tolerance=settings.limit_price_absolute_tolerance,
                    )
                ):
                    reasons.append("SPECIAL_MARGIN_OR_CORPORATE_ACTION")
                    requires_review = True
                elif pd.notna(open_value) and prices_equal(
                    open_value,
                    estimated_limit,
                    relative_tolerance=settings.limit_price_relative_tolerance,
                    absolute_tolerance=settings.limit_price_absolute_tolerance,
                ):
                    reasons.append("LIMIT_OPEN")
            if bool(prediction_row["corporate_action_window_flag"]):
                reasons.append("CORPORATE_ACTION_WINDOW")
            reasons = _ordered_reasons(reasons, settings.reason_priority)
            hard_reasons = [reason for reason in reasons if reason != "PRICE_STEP_UNAVAILABLE"]
            if hard_reasons:
                eligible: bool | pd._libs.missing.NAType = False
            elif requires_review or "PRICE_STEP_UNAVAILABLE" in reasons:
                eligible = pd.NA
            else:
                eligible = True
            output_rows.append(
                {
                    "ticker": ticker,
                    "trade_date": entry_date,
                    "prediction_date": prediction_date,
                    "entry_date": entry_date,
                    "yf_nominal_open": entry_row["yf_nominal_open"],
                    "yf_nominal_high": entry_row["yf_nominal_high"],
                    "yf_nominal_low": entry_row["yf_nominal_low"],
                    "yf_nominal_close": entry_row["yf_nominal_close"],
                    "is_tl_volume": entry_row["is_tl_volume"],
                    "yf_share_volume": entry_row["yf_share_volume"],
                    "previous_nominal_close": previous_close,
                    "raw_upper_limit": entry_row["raw_upper_limit"],
                    "price_step": entry_row["price_step"],
                    "estimated_upper_limit": estimated_limit,
                    "ohlc_quality_flag": entry_row["ohlc_quality_flag"],
                    "volume_quality_flag": entry_row["volume_quality_flag"],
                    "cross_source_price_warning": entry_row["cross_source_price_warning"],
                    "corporate_action_flag": entry_row["corporate_action_flag"],
                    "corporate_action_signal_sources": entry_row[
                        "corporate_action_signal_sources"
                    ],
                    "corporate_action_source_count": entry_row[
                        "corporate_action_source_count"
                    ],
                    "corporate_action_source_agreement": entry_row[
                        "corporate_action_source_agreement"
                    ],
                    "corporate_action_window_flag": prediction_row[
                        "corporate_action_window_flag"
                    ],
                    "corporate_action_window_dates": prediction_row[
                        "corporate_action_window_dates"
                    ],
                    "corporate_action_window_signal_sources": prediction_row[
                        "corporate_action_window_signal_sources"
                    ],
                    "entry_eligible": eligible,
                    "entry_exclusion_reason": reasons[0] if reasons else pd.NA,
                    "entry_exclusion_reasons": reasons,
                    "entry_exclusion_detail": (
                        "FIRST_TRADING_DAY_OR_NO_HISTORY"
                        if "NO_PREVIOUS_CLOSE" in reasons
                        else pd.NA
                    ),
                    "requires_review": requires_review,
                }
            )
    output = pd.DataFrame(output_rows)
    if not output.empty:
        output["entry_eligible"] = pd.Series(output["entry_eligible"], dtype="boolean")
        output["entry_exclusion_reason"] = output["entry_exclusion_reason"].astype("string")
        output["entry_exclusion_detail"] = output["entry_exclusion_detail"].astype("string")
    return output.sort_values(["ticker", "prediction_date"]).reset_index(drop=True)


def summarize_cleaning(frame: pd.DataFrame) -> dict[str, Any]:
    """Return compact counts for operational reporting."""

    reason_lists = frame.get("entry_exclusion_reasons", pd.Series(dtype=object))
    all_reasons = (
        reason_lists.explode().dropna().astype("string")
        if not reason_lists.empty
        else pd.Series(dtype="string")
    )
    return {
        "row_count": int(len(frame)),
        "entry_eligible_true": int(frame.get("entry_eligible", pd.Series(dtype="boolean")).eq(True).sum()),
        "entry_eligible_false": int(frame.get("entry_eligible", pd.Series(dtype="boolean")).eq(False).sum()),
        "entry_eligible_unresolved": int(frame.get("entry_eligible", pd.Series(dtype="boolean")).isna().sum()),
        "requires_review": int(frame.get("requires_review", pd.Series(dtype=bool)).fillna(False).sum()),
        "NO_OPEN": int(all_reasons.eq("NO_OPEN").sum()),
        "NO_TRADE": int(all_reasons.eq("NO_TRADE").sum()),
        "INVALID_OHLC": int(all_reasons.eq("INVALID_OHLC").sum()),
        "NO_PREVIOUS_CLOSE": int(all_reasons.eq("NO_PREVIOUS_CLOSE").sum()),
        "LIMIT_OPEN": int(all_reasons.eq("LIMIT_OPEN").sum()),
        "SPECIAL_MARGIN_OR_CORPORATE_ACTION": int(
            all_reasons.eq("SPECIAL_MARGIN_OR_CORPORATE_ACTION").sum()
        ),
        "CORPORATE_ACTION_WINDOW": int(
            all_reasons.eq("CORPORATE_ACTION_WINDOW").sum()
        ),
        "PRICE_STEP_UNAVAILABLE": int(
            all_reasons.eq("PRICE_STEP_UNAVAILABLE").sum()
        ),
        "both_volumes_missing": int(
            frame.get("volume_quality_flag", pd.Series(dtype="string"))
            .eq("BOTH_VOLUMES_MISSING_UNRESOLVED")
            .sum()
        ),
        "one_volume_conflict": int(
            frame.get("volume_quality_flag", pd.Series(dtype="string"))
            .eq("SOURCE_VOLUME_CONFLICT")
            .sum()
        ),
        "corporate_action_window": int(
            frame.get("corporate_action_window_flag", pd.Series(dtype=bool))
            .fillna(False)
            .sum()
        ),
        "cross_source_warning": int(
            frame.get("cross_source_price_warning", pd.Series(dtype="boolean"))
            .eq(True)
            .sum()
        ),
    }
