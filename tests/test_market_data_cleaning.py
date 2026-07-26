from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.data.cleaning import (
    NON_FEATURE_AUDIT_COLUMNS,
    add_corporate_action_windows,
    add_daily_corporate_action_signals,
    build_clean_eligibility_frame,
    evaluate_basic_entry_eligibility,
    evaluate_volume_quality,
    summarize_cleaning,
    validate_nominal_ohlc,
)
from src.data.price_limits import (
    PriceStepRule,
    PriceStepRuleError,
    PriceStepTable,
    calculate_upper_limit,
    floor_to_price_step,
    prices_equal,
)


CALENDAR = pd.date_range("2024-01-01", periods=6, freq="D")


def _price_steps(step: str = "0.01") -> PriceStepTable:
    return PriceStepTable(
        [PriceStepRule("2020-01-01", None, "0", None, step)]
    )


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA"] * len(CALENDAR),
            "date": CALENDAR,
            "yf_nominal_open": [10.0] * len(CALENDAR),
            "yf_nominal_high": [10.5] * len(CALENDAR),
            "yf_nominal_low": [9.5] * len(CALENDAR),
            "yf_nominal_close": [10.0] * len(CALENDAR),
            "is_raw_high": [10.5] * len(CALENDAR),
            "is_raw_low": [9.5] * len(CALENDAR),
            "is_raw_close": [10.0] * len(CALENDAR),
            "is_tl_volume": [1000.0] * len(CALENDAR),
            "yf_share_volume": [100.0] * len(CALENDAR),
            "adjustment_factor_changed": [False] * len(CALENDAR),
            "yf_dividends": [0.0] * len(CALENDAR),
            "yf_stock_splits": [0.0] * len(CALENDAR),
            "yf_capital_gains": [0.0] * len(CALENDAR),
            "yf_other_action_value": [0.0] * len(CALENDAR),
        }
    )


def _clean(frame: pd.DataFrame | None = None, steps: PriceStepTable | None = None) -> pd.DataFrame:
    return build_clean_eligibility_frame(
        frame if frame is not None else _daily(),
        CALENDAR,
        steps if steps is not None else _price_steps(),
    )


def test_normal_entry_is_eligible() -> None:
    result = _clean()

    assert result["entry_eligible"].eq(True).all()
    assert result["entry_exclusion_reasons"].tolist() == [[], [], []]


@pytest.mark.parametrize("open_value", [np.nan, 0.0, -1.0])
def test_missing_or_nonpositive_open_is_no_open(open_value: float) -> None:
    frame = _daily()
    frame.loc[1, "yf_nominal_open"] = open_value

    row = _clean(frame).iloc[0]

    assert not bool(row["entry_eligible"])
    assert row["entry_exclusion_reason"] == "NO_OPEN"


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("yf_nominal_high", np.nan),
        ("yf_nominal_low", 10.1),
        ("yf_nominal_high", 9.9),
        ("yf_nominal_close", 9.4),
        ("yf_nominal_close", 10.6),
        ("yf_nominal_low", 0.0),
    ],
)
def test_invalid_nominal_ohlc_is_excluded(column: str, value: float) -> None:
    frame = _daily()
    frame.loc[1, column] = value

    row = _clean(frame).iloc[0]

    assert row["ohlc_quality_flag"] == "INVALID_OHLC"
    assert "INVALID_OHLC" in row["entry_exclusion_reasons"]


def test_both_volumes_zero_is_no_trade() -> None:
    frame = _daily()
    frame.loc[1, ["is_tl_volume", "yf_share_volume"]] = 0.0

    row = _clean(frame).iloc[0]

    assert row["entry_exclusion_reason"] == "NO_TRADE"
    assert not bool(row["entry_eligible"])


@pytest.mark.parametrize(
    ("is_volume", "yf_volume"),
    [(100.0, 0.0), (100.0, np.nan), (0.0, 100.0), (np.nan, 100.0)],
)
def test_one_positive_volume_keeps_entry_with_warning(
    is_volume: float, yf_volume: float
) -> None:
    frame = _daily()
    frame.loc[1, ["is_tl_volume", "yf_share_volume"]] = [is_volume, yf_volume]

    row = _clean(frame).iloc[0]

    assert bool(row["entry_eligible"])
    assert row["volume_quality_flag"] == "SOURCE_VOLUME_CONFLICT"


def test_both_volumes_missing_is_unresolved() -> None:
    frame = _daily()
    frame.loc[1, ["is_tl_volume", "yf_share_volume"]] = np.nan

    row = _clean(frame).iloc[0]

    assert pd.isna(row["entry_eligible"])
    assert bool(row["requires_review"])
    assert row["volume_quality_flag"] == "BOTH_VOLUMES_MISSING_UNRESOLVED"


def test_low_positive_volume_has_no_liquidity_threshold() -> None:
    frame = _daily()
    frame.loc[1, ["is_tl_volume", "yf_share_volume"]] = [0.01, 1.0]

    row = _clean(frame).iloc[0]

    assert bool(row["entry_eligible"])
    assert row["volume_quality_flag"] == "POSITIVE_VOLUME_CONFIRMED"


def test_previous_valid_close_skips_invalid_intermediate_day() -> None:
    frame = _daily()
    frame.loc[1, "yf_nominal_high"] = 9.0
    frame.loc[2, ["yf_nominal_open", "yf_nominal_high", "yf_nominal_low", "yf_nominal_close"]] = [
        10.0,
        10.5,
        9.5,
        10.0,
    ]

    row = _clean(frame).loc[lambda value: value["prediction_date"].eq(CALENDAR[1])].iloc[0]

    assert row["previous_nominal_close"] == 10.0


def test_first_day_without_history_has_detailed_reason() -> None:
    frame = _daily()
    frame.loc[0, ["yf_nominal_open", "yf_nominal_high", "yf_nominal_low", "yf_nominal_close"]] = np.nan

    row = _clean(frame).iloc[0]

    assert "NO_PREVIOUS_CLOSE" in row["entry_exclusion_reasons"]
    assert row["entry_exclusion_detail"] == "FIRST_TRADING_DAY_OR_NO_HISTORY"
    assert bool(row["requires_review"])


def test_upper_limit_uses_ten_percent_and_inward_floor() -> None:
    result = calculate_upper_limit(1.133, "2024-01-02", _price_steps())

    assert result is not None
    assert result.raw_upper_limit == Decimal("1.2463")
    assert result.estimated_upper_limit == Decimal("1.24")


def test_floor_to_price_step_uses_decimal_arithmetic() -> None:
    assert floor_to_price_step("1.2463", "0.01") == Decimal("1.24")


def test_exact_upper_limit_open_is_excluded() -> None:
    frame = _daily()
    frame.loc[1, ["yf_nominal_open", "yf_nominal_high", "yf_nominal_low", "yf_nominal_close"]] = [
        11.0,
        11.0,
        10.5,
        11.0,
    ]

    row = _clean(frame).iloc[0]

    assert row["entry_exclusion_reason"] == "LIMIT_OPEN"


def test_one_full_tick_below_limit_is_not_limit_open() -> None:
    frame = _daily()
    frame.loc[1, ["yf_nominal_open", "yf_nominal_high", "yf_nominal_low", "yf_nominal_close"]] = [
        10.99,
        10.99,
        10.5,
        10.99,
    ]

    row = _clean(frame).iloc[0]

    assert bool(row["entry_eligible"])
    assert "LIMIT_OPEN" not in row["entry_exclusion_reasons"]


@pytest.mark.parametrize("field", ["yf_nominal_open", "yf_nominal_high"])
def test_open_or_high_above_estimated_limit_is_special_review(field: str) -> None:
    frame = _daily()
    frame.loc[1, ["yf_nominal_open", "yf_nominal_high", "yf_nominal_low", "yf_nominal_close"]] = [
        10.9,
        10.9,
        10.5,
        10.9,
    ]
    frame.loc[1, field] = 11.01
    if field == "yf_nominal_open":
        frame.loc[1, "yf_nominal_high"] = 11.01

    row = _clean(frame).iloc[0]

    assert row["entry_exclusion_reason"] == "SPECIAL_MARGIN_OR_CORPORATE_ACTION"
    assert bool(row["requires_review"])


def test_limit_comparison_accepts_only_small_floating_noise() -> None:
    assert prices_equal(11.0 + 1e-9, 11.0)
    assert not prices_equal(10.99, 11.0)


@pytest.mark.parametrize("action_offset", [1, 2, 3])
def test_corporate_action_on_t_plus_one_to_three_excludes(action_offset: int) -> None:
    frame = _daily()
    frame.loc[action_offset, "yf_dividends"] = 1.0

    row = _clean(frame).iloc[0]

    assert bool(row["corporate_action_window_flag"])
    assert "CORPORATE_ACTION_WINDOW" in row["entry_exclusion_reasons"]
    assert not bool(row["entry_eligible"])


def test_no_corporate_action_window_remains_eligible() -> None:
    row = _clean().iloc[0]

    assert not bool(row["corporate_action_window_flag"])
    assert bool(row["entry_eligible"])


def test_corporate_action_sources_are_retained_independently() -> None:
    frame = _daily().iloc[:1].copy()
    frame["adjustment_factor_changed"] = True
    frame["yf_stock_splits"] = 2.0

    row = add_daily_corporate_action_signals(frame).iloc[0]

    assert row["corporate_action_source_count"] == 2
    assert row["corporate_action_source_agreement"] == "BOTH_SOURCES"
    assert row["corporate_action_signal_sources"] == [
        "isyatirim_adjustment_factor",
        "yfinance_actions",
    ]


def test_action_window_uses_global_calendar_when_ticker_row_is_missing() -> None:
    frame = _daily().drop(index=1).reset_index(drop=True)
    frame.loc[frame["date"].eq(CALENDAR[3]), "yf_dividends"] = 1.0
    signalled = add_daily_corporate_action_signals(frame)

    windowed = add_corporate_action_windows(signalled, CALENDAR)
    first = windowed.loc[windowed["date"].eq(CALENDAR[0])].iloc[0]

    assert first["corporate_action_window_dates"] == ["2024-01-04"]


def test_multiple_reasons_preserve_deterministic_full_list() -> None:
    frame = _daily()
    frame.loc[1, "yf_nominal_open"] = np.nan
    frame.loc[1, ["is_tl_volume", "yf_share_volume"]] = 0.0
    frame.loc[2, "yf_dividends"] = 1.0

    row = _clean(frame).iloc[0]

    assert row["entry_exclusion_reasons"] == [
        "NO_OPEN",
        "NO_TRADE",
        "CORPORATE_ACTION_WINDOW",
    ]
    assert row["entry_exclusion_reason"] == "NO_OPEN"


def test_cross_source_price_warning_does_not_exclude() -> None:
    frame = _daily()
    frame.loc[1, "is_raw_close"] = 99.0

    row = _clean(frame).iloc[0]

    assert bool(row["cross_source_price_warning"])
    assert bool(row["entry_eligible"])


def test_missing_price_step_rule_is_explicit_review_not_guess() -> None:
    row = _clean(steps=PriceStepTable()).iloc[0]

    assert pd.isna(row["entry_eligible"])
    assert bool(row["requires_review"])
    assert row["entry_exclusion_reason"] == "PRICE_STEP_UNAVAILABLE"
    assert row["raw_upper_limit"] == 11.0
    assert pd.isna(row["estimated_upper_limit"])
    assert row["price_step_resolution_status"] == "UNAVAILABLE"


def test_resolved_price_step_metadata_is_retained() -> None:
    row = _clean().iloc[0]

    assert row["tick_size"] == row["price_step"] == 0.01
    assert row["tick_rule_set_id"] == "UNVERSIONED"
    assert row["tick_rule_effective_from"] == "2020-01-01"
    assert row["price_step_resolution_status"] == "RESOLVED"


def test_price_step_table_rejects_ambiguous_rules() -> None:
    table = PriceStepTable(
        [
            PriceStepRule("2024-01-01", None, "0", None, "0.01"),
            PriceStepRule("2024-01-01", None, "0", None, "0.02"),
        ]
    )

    with pytest.raises(PriceStepRuleError, match="ambiguous"):
        table.resolve("2024-01-02", "10")


def test_clean_output_contains_no_provider_or_label_fields() -> None:
    result = _clean()

    assert not any(column.startswith("yf_provider_") for column in result.columns)
    assert {"label", "target", "prediction", "yf_future_split_factor"}.isdisjoint(
        result.columns
    )


def test_future_and_action_audit_fields_are_explicitly_non_features() -> None:
    assert {
        "yf_future_split_factor",
        "corporate_action_window_flag",
        "corporate_action_signal_sources",
    }.issubset(NON_FEATURE_AUDIT_COLUMNS)


def test_summary_reports_required_quality_counts() -> None:
    frame = _daily()
    frame.loc[1, ["is_tl_volume", "yf_share_volume"]] = np.nan
    cleaned = _clean(frame)

    summary = summarize_cleaning(cleaned)

    assert summary["entry_eligible_unresolved"] == 1
    assert summary["both_volumes_missing"] == 1


def test_basic_eligibility_uses_shared_ohlc_and_volume_results() -> None:
    frame = pd.DataFrame(
        {
            "yf_nominal_open": [10.0],
            "yf_nominal_high": [11.0],
            "yf_nominal_low": [9.0],
            "yf_nominal_close": [10.0],
            "is_tl_volume": [100.0],
            "yf_share_volume": [10.0],
        }
    )
    evaluated = evaluate_basic_entry_eligibility(
        evaluate_volume_quality(validate_nominal_ohlc(frame))
    )

    assert bool(evaluated.loc[0, "entry_eligible"])
