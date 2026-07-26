from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from scripts import source_acceptance_test as MODULE


def _split_frame(
    *,
    tickers: list[str],
    dates: list[str],
    splits: list[float],
    opens: list[float] | None = None,
) -> pd.DataFrame:
    prices = opens or [10.0] * len(dates)
    return pd.DataFrame(
        {
            "ticker": tickers,
            "date": pd.to_datetime(dates),
            "yf_provider_open": prices,
            "yf_provider_high": prices,
            "yf_provider_low": prices,
            "yf_provider_close": prices,
            "yf_stock_splits": splits,
        }
    )


def test_build_periods_uses_exact_90_calendar_days_inclusively() -> None:
    periods = {period.name: period for period in MODULE.build_periods(date(2026, 7, 26))}

    assert periods["recent_90_calendar_days"].start == date(2026, 4, 28)
    assert periods["recent_90_calendar_days"].end == date(2026, 7, 26)
    assert (periods["recent_90_calendar_days"].end - periods["recent_90_calendar_days"].start).days + 1 == 90


def test_normalize_yfinance_history_preserves_istanbul_calendar_date() -> None:
    index = pd.DatetimeIndex(["2020-03-13 00:00:00"], tz="Europe/Istanbul", name="Date")
    raw = pd.DataFrame(
        {
            "Open": [8.48],
            "High": [9.32],
            "Low": [8.14],
            "Close": [9.10],
            "Adj Close": [8.89],
            "Volume": [100],
            "Dividends": [0.0],
            "Stock Splits": [0.0],
        },
        index=index,
    )

    normalized = MODULE.normalize_yfinance_history(raw, "THYAO")

    assert normalized.loc[0, "date"] == pd.Timestamp("2020-03-13")
    assert normalized.loc[0, "ticker"] == "THYAO"
    assert normalized.loc[0, "yf_open"] == 8.48
    assert normalized.loc[0, "yf_provider_open"] == 8.48
    assert normalized.loc[0, "yf_provider_adjusted_close"] == 8.89
    assert normalized.loc[0, "yf_future_split_factor"] == 1.0
    assert normalized.loc[0, "yf_nominal_open"] == 8.48


def test_future_split_factor_is_one_when_there_is_no_split() -> None:
    frame = _split_frame(
        tickers=["AAA", "AAA"],
        dates=["2024-08-09", "2024-08-12"],
        splits=[0.0, 0.0],
    )

    result = MODULE.add_future_split_normalization(frame)

    assert result["yf_future_split_factor"].tolist() == [1.0, 1.0]


def test_future_split_factor_excludes_split_day_and_days_after_it() -> None:
    frame = _split_frame(
        tickers=["AAA", "AAA", "AAA"],
        dates=["2024-08-09", "2024-08-12", "2024-08-13"],
        splits=[0.0, 8.0, 0.0],
        opens=[10.0, 80.0, 82.0],
    )

    result = MODULE.add_future_split_normalization(frame)

    assert result["yf_future_split_factor"].tolist() == [8.0, 1.0, 1.0]
    assert result["yf_nominal_open"].tolist() == [80.0, 80.0, 82.0]


def test_future_split_factor_multiplies_all_strictly_later_splits() -> None:
    frame = _split_frame(
        tickers=["AAA"] * 5,
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        splits=[0.0, 2.0, 0.0, 3.0, 0.0],
    )

    result = MODULE.add_future_split_normalization(frame)

    assert result["yf_future_split_factor"].tolist() == [6.0, 3.0, 3.0, 1.0, 1.0]


def test_same_split_factor_preserves_ohlc_ratios() -> None:
    frame = _split_frame(
        tickers=["AAA", "AAA"],
        dates=["2024-08-09", "2024-08-12"],
        splits=[0.0, 8.0],
        opens=[10.0, 80.0],
    )
    frame["yf_provider_high"] = [12.0, 88.0]
    frame["yf_provider_low"] = [9.0, 72.0]
    frame["yf_provider_close"] = [11.0, 84.0]

    result = MODULE.add_future_split_normalization(frame)

    first = result.iloc[0]
    assert first["yf_future_split_factor"] == 8.0
    for field in ("open", "high", "low", "close"):
        assert first[f"yf_nominal_{field}"] == first[f"yf_provider_{field}"] * 8.0
    assert first["yf_nominal_high"] / first["yf_nominal_open"] == (
        first["yf_provider_high"] / first["yf_provider_open"]
    )
    assert first["yf_nominal_close"] / first["yf_nominal_open"] == (
        first["yf_provider_close"] / first["yf_provider_open"]
    )


def test_future_split_factor_safely_ignores_zero_missing_and_invalid_values() -> None:
    frame = _split_frame(
        tickers=["AAA"] * 5,
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        splits=[0.0, np.nan, -2.0, np.inf, 0.0],
    )

    result = MODULE.add_future_split_normalization(frame)

    assert result["yf_future_split_factor"].tolist() == [1.0] * 5
    assert result["yf_split_value_ignored"].tolist() == [False, False, True, True, False]


def test_future_split_factor_isolated_by_ticker() -> None:
    frame = _split_frame(
        tickers=["AAA", "AAA", "BBB", "BBB"],
        dates=["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
        splits=[0.0, 2.0, 0.0, 3.0],
    )

    result = MODULE.add_future_split_normalization(frame)

    assert result.loc[result["ticker"].eq("AAA"), "yf_future_split_factor"].tolist() == [2.0, 1.0]
    assert result.loc[result["ticker"].eq("BBB"), "yf_future_split_factor"].tolist() == [3.0, 1.0]


def test_adjustment_factor_tolerance_ignores_rounding_but_flags_event() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "AAA"],
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "is_raw_close": [10.0, 10.0, 10.0],
            "is_adjusted_close": [0.20140, 0.20150, 0.22000],
        }
    )

    marked = MODULE.mark_adjustment_factor_changes(frame)

    assert marked["adjustment_factor_changed"].tolist() == [False, False, True]


def test_quality_flags_use_isyatirim_calendar_and_nominal_yfinance_ohlc() -> None:
    is_frame = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "is_raw_high": [11.0, 11.0],
            "is_raw_low": [9.0, 9.0],
            "is_raw_close": [10.0, 10.0],
            "is_raw_weighted_average": [10.0, 10.0],
            "is_adjusted_high": [11.0, 11.0],
            "is_adjusted_low": [9.0, 9.0],
            "is_adjusted_close": [10.0, 10.0],
            "is_adjusted_weighted_average": [10.0, 10.0],
            "is_tl_volume": [1000.0, np.nan],
            "is_raw_tl_volume": [1000.0, np.nan],
            "is_market_cap_try": [np.nan, np.nan],
            "is_market_cap_usd": [np.nan, np.nan],
            "is_free_float_market_cap_try": [np.nan, np.nan],
            "is_free_float_market_cap_usd": [np.nan, np.nan],
        }
    )
    yf_frame = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "date": pd.to_datetime(["2024-01-01"]),
            "yf_open": [9.5],
            "yf_high": [11.0],
            "yf_low": [9.0],
            "yf_close": [10.0],
            "yf_provider_adjusted_close": [10.0],
            "yf_share_volume": [200.0],
            "yf_dividends": [0.0],
            "yf_stock_splits": [0.0],
            "yf_capital_gains": [0.0],
            "yf_other_action_value": [0.0],
        }
    )

    quality = MODULE.build_quality_frame(is_frame, yf_frame)

    assert len(quality) == 2
    assert quality["has_yfinance_row"].tolist() == [True, False]
    assert quality["valid_nominal_ohlc"].tolist() == [True, pd.NA]
    assert quality["both_volumes_missing"].tolist() == [False, True]


def test_nominal_open_repair_can_restore_isyatirim_range_without_mutating_provider() -> None:
    is_frame = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "date": pd.to_datetime(["2024-08-09", "2024-08-12"]),
            "is_raw_high": [81.0, 82.0],
            "is_raw_low": [79.0, 78.0],
            "is_raw_close": [80.0, 80.0],
            "is_raw_weighted_average": [80.0, 80.0],
            "is_adjusted_high": [10.125, 82.0],
            "is_adjusted_low": [9.875, 78.0],
            "is_adjusted_close": [10.0, 80.0],
            "is_adjusted_weighted_average": [10.0, 80.0],
            "is_tl_volume": [1000.0, 1000.0],
            "is_raw_tl_volume": [1000.0, 1000.0],
            "is_market_cap_try": [np.nan, np.nan],
            "is_market_cap_usd": [np.nan, np.nan],
            "is_free_float_market_cap_try": [np.nan, np.nan],
            "is_free_float_market_cap_usd": [np.nan, np.nan],
        }
    )
    yf_frame = _split_frame(
        tickers=["AAA", "AAA"],
        dates=["2024-08-09", "2024-08-12"],
        splits=[0.0, 8.0],
        opens=[10.0, 80.0],
    )
    yf_frame["yf_provider_adjusted_close"] = [10.0, 80.0]
    yf_frame["yf_share_volume"] = [100.0, 100.0]
    yf_frame["yf_dividends"] = [0.0, 0.0]
    yf_frame["yf_capital_gains"] = [0.0, 0.0]
    yf_frame["yf_other_action_value"] = [0.0, 0.0]

    quality = MODULE.build_quality_frame(is_frame, yf_frame)

    assert quality["yf_provider_open"].tolist() == [10.0, 80.0]
    assert quality["yf_provider_high"].tolist() == [10.0, 80.0]
    assert quality["yf_provider_low"].tolist() == [10.0, 80.0]
    assert quality["yf_provider_close"].tolist() == [10.0, 80.0]
    assert quality["yf_nominal_open"].tolist() == [80.0, 80.0]
    assert quality["provider_open_within_is_range"].tolist() == [False, True]
    assert quality["nominal_open_within_is_range"].tolist() == [True, True]


def test_price_difference_is_absolute_and_relative_to_isyatirim_raw() -> None:
    is_frame = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "date": pd.to_datetime(["2024-01-01"]),
            "is_raw_high": [11.0],
            "is_raw_low": [9.0],
            "is_raw_close": [10.0],
            "is_raw_weighted_average": [10.0],
            "is_adjusted_high": [11.0],
            "is_adjusted_low": [9.0],
            "is_adjusted_close": [10.0],
            "is_adjusted_weighted_average": [10.0],
            "is_tl_volume": [1000.0],
            "is_raw_tl_volume": [1000.0],
            "is_market_cap_try": [np.nan],
            "is_market_cap_usd": [np.nan],
            "is_free_float_market_cap_try": [np.nan],
            "is_free_float_market_cap_usd": [np.nan],
        }
    )
    yf_frame = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "date": pd.to_datetime(["2024-01-01"]),
            "yf_open": [9.5],
            "yf_high": [10.5],
            "yf_low": [9.0],
            "yf_close": [9.0],
            "yf_provider_adjusted_close": [9.0],
            "yf_share_volume": [200.0],
            "yf_dividends": [0.0],
            "yf_stock_splits": [0.0],
            "yf_capital_gains": [0.0],
            "yf_other_action_value": [0.0],
        }
    )

    quality = MODULE.build_quality_frame(is_frame, yf_frame)

    assert quality.loc[0, "high_absolute_difference"] == 0.5
    assert quality.loc[0, "close_absolute_difference"] == 1.0
    assert quality.loc[0, "close_percentage_difference"] == 10.0
    assert bool(quality.loc[0, "source_price_conflict"])
    assert bool(quality.loc[0, "cross_source_price_warning"])
    assert bool(quality.loc[0, "entry_eligible"])


def test_acceptance_status_ignores_cross_source_price_warning() -> None:
    quality = pd.DataFrame(
        {
            "has_yfinance_split": [True],
            "valid_nominal_ohlc": pd.Series([True], dtype="boolean"),
            "split_factor_unavailable": [False],
            "nominal_conversion_consistent": [True],
            "entry_exclusion_reason": pd.Series([pd.NA], dtype="string"),
            "label_exclusion_reason": pd.Series([pd.NA], dtype="string"),
            "cross_source_price_warning": pd.Series([True], dtype="boolean"),
        }
    )

    status, reason = MODULE.determine_acceptance_status(
        required_is=True,
        required_yf=True,
        errors=[],
        quality=quality,
    )

    assert status == "PASS"
    assert "yalnız kalite uyarısıdır" in reason


def test_acceptance_status_fails_when_a_required_source_failed() -> None:
    status, _ = MODULE.determine_acceptance_status(
        required_is=True,
        required_yf=True,
        errors=["provider timeout"],
        quality=pd.DataFrame({"has_yfinance_split": [True]}),
    )

    assert status == "FAIL"


def test_nominal_ohlc_is_validated_only_against_itself() -> None:
    is_frame = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "date": pd.to_datetime(["2024-01-01"]),
            "is_raw_high": [5.0],
            "is_raw_low": [4.0],
            "is_raw_close": [4.5],
            "is_raw_weighted_average": [4.5],
            "is_adjusted_high": [5.0],
            "is_adjusted_low": [4.0],
            "is_adjusted_close": [4.5],
            "is_adjusted_weighted_average": [4.5],
            "is_tl_volume": [1000.0],
            "is_raw_tl_volume": [1000.0],
            "is_market_cap_try": [np.nan],
            "is_market_cap_usd": [np.nan],
            "is_free_float_market_cap_try": [np.nan],
            "is_free_float_market_cap_usd": [np.nan],
        }
    )
    yf_frame = _split_frame(
        tickers=["AAA"],
        dates=["2024-01-01"],
        splits=[2.0],
        opens=[10.0],
    )
    yf_frame["yf_provider_high"] = [11.0]
    yf_frame["yf_provider_low"] = [9.0]
    yf_frame["yf_provider_close"] = [10.5]
    yf_frame["yf_provider_adjusted_close"] = [10.5]
    yf_frame["yf_share_volume"] = [100.0]
    yf_frame["yf_dividends"] = [0.0]
    yf_frame["yf_capital_gains"] = [0.0]
    yf_frame["yf_other_action_value"] = [0.0]

    quality = MODULE.build_quality_frame(is_frame, yf_frame)

    assert bool(quality.loc[0, "valid_nominal_ohlc"])
    assert bool(quality.loc[0, "cross_source_price_warning"])
    assert bool(quality.loc[0, "entry_eligible"])


def test_missing_nominal_open_produces_no_open() -> None:
    is_frame = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "date": pd.to_datetime(["2024-01-01"]),
            "is_raw_high": [11.0],
            "is_raw_low": [9.0],
            "is_raw_close": [10.0],
            "is_raw_weighted_average": [10.0],
            "is_adjusted_high": [11.0],
            "is_adjusted_low": [9.0],
            "is_adjusted_close": [10.0],
            "is_adjusted_weighted_average": [10.0],
            "is_tl_volume": [1000.0],
            "is_raw_tl_volume": [1000.0],
            "is_market_cap_try": [np.nan],
            "is_market_cap_usd": [np.nan],
            "is_free_float_market_cap_try": [np.nan],
            "is_free_float_market_cap_usd": [np.nan],
        }
    )
    yf_frame = _split_frame(
        tickers=["AAA"],
        dates=["2024-01-01"],
        splits=[0.0],
        opens=[np.nan],
    )
    yf_frame["yf_provider_adjusted_close"] = [10.0]
    yf_frame["yf_share_volume"] = [100.0]
    yf_frame["yf_dividends"] = [0.0]
    yf_frame["yf_capital_gains"] = [0.0]
    yf_frame["yf_other_action_value"] = [0.0]

    quality = MODULE.build_quality_frame(is_frame, yf_frame)

    assert not bool(quality.loc[0, "entry_eligible"])
    assert quality.loc[0, "entry_exclusion_reason"] == "NO_OPEN"


def test_future_corporate_action_produces_corporate_action_window() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    is_frame = pd.DataFrame(
        {
            "ticker": ["AAA"] * 4,
            "date": dates,
            "is_raw_high": [11.0] * 4,
            "is_raw_low": [9.0] * 4,
            "is_raw_close": [10.0] * 4,
            "is_raw_weighted_average": [10.0] * 4,
            "is_adjusted_high": [11.0] * 4,
            "is_adjusted_low": [9.0] * 4,
            "is_adjusted_close": [10.0] * 4,
            "is_adjusted_weighted_average": [10.0] * 4,
            "is_tl_volume": [1000.0] * 4,
            "is_raw_tl_volume": [1000.0] * 4,
            "is_market_cap_try": [np.nan] * 4,
            "is_market_cap_usd": [np.nan] * 4,
            "is_free_float_market_cap_try": [np.nan] * 4,
            "is_free_float_market_cap_usd": [np.nan] * 4,
        }
    )
    yf_frame = _split_frame(
        tickers=["AAA"] * 4,
        dates=[value.strftime("%Y-%m-%d") for value in dates],
        splits=[0.0] * 4,
    )
    yf_frame["yf_provider_adjusted_close"] = [10.0] * 4
    yf_frame["yf_share_volume"] = [100.0] * 4
    yf_frame["yf_dividends"] = [0.0, 0.0, 0.0, 1.0]
    yf_frame["yf_capital_gains"] = [0.0] * 4
    yf_frame["yf_other_action_value"] = [0.0] * 4

    quality = MODULE.build_quality_frame(is_frame, yf_frame)

    assert quality["corporate_action_window"].tolist() == [True, True, True, False]
    assert quality.loc[0, "label_exclusion_reason"] == "CORPORATE_ACTION_WINDOW"
    assert not bool(quality.loc[0, "label_eligible"])


def test_split_factor_is_not_a_model_feature() -> None:
    assert "yf_future_split_factor" not in MODULE.MODEL_FEATURE_COLUMNS
    assert MODULE.NON_FEATURE_NORMALIZATION_COLUMNS.isdisjoint(
        MODULE.MODEL_FEATURE_COLUMNS
    )
