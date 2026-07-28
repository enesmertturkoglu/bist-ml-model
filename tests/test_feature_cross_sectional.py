from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.cross_sectional import add_cross_sectional_features
from src.features.input_assembler import FeatureInputError


def _frame(securities: int = 20) -> pd.DataFrame:
    values = np.arange(securities, dtype="float64")
    return pd.DataFrame(
        {
            "security_id": [f"SEC_{value:02d}" for value in range(securities)],
            "prediction_date": pd.Timestamp("2024-01-02"),
            "ret_1": values,
            "ret_5": values,
            "relative_ret_5": values,
            "tl_volume_zscore_20": values,
        }
    )


def test_cross_section_rank_uses_average_ties_and_zero_one_normalization() -> None:
    frame = _frame()
    frame.loc[9:10, "ret_1"] = 9.0
    result = add_cross_sectional_features(frame).frame

    assert result.loc[0, "cs_ret_1_rank"] == 0.0
    assert result.loc[19, "cs_ret_1_rank"] == 1.0
    expected_tie = ((10.0 + 11.0) / 2.0 - 1.0) / 19.0
    assert result.loc[9, "cs_ret_1_rank"] == expected_tie
    assert result.loc[10, "cs_ret_1_rank"] == expected_tie


def test_cross_section_is_prediction_date_local() -> None:
    first = _frame()
    second = _frame()
    second["prediction_date"] = pd.Timestamp("2024-01-03")
    second["ret_1"] = second["ret_1"] + 10_000.0
    result = add_cross_sectional_features(pd.concat([first, second], ignore_index=True)).frame

    assert result.groupby("prediction_date")["cs_ret_1_rank"].min().eq(0.0).all()
    assert result.groupby("prediction_date")["cs_ret_1_rank"].max().eq(1.0).all()


def test_cross_section_below_minimum_is_all_nan() -> None:
    result = add_cross_sectional_features(_frame(19)).frame

    assert result.filter(like="cs_").isna().all().all()


def test_nan_does_not_enter_rank_universe() -> None:
    frame = _frame(21)
    frame.loc[0, "ret_1"] = np.nan
    result = add_cross_sectional_features(frame).frame

    assert np.isnan(result.loc[0, "cs_ret_1_rank"])
    assert result.loc[1, "cs_ret_1_rank"] == 0.0
    assert result.loc[20, "cs_ret_1_rank"] == 1.0


def test_label_or_entry_field_in_rank_input_fails_closed() -> None:
    for forbidden in ("label", "entry_eligible", "target_hit"):
        frame = _frame()
        frame[forbidden] = 0
        with pytest.raises(FeatureInputError, match="forbidden"):
            add_cross_sectional_features(frame)
