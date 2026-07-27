"""Exact global-session grid alignment without filling source observations."""

from __future__ import annotations

import pandas as pd

from src.features.input_assembler import FEATURE_INPUT_COLUMNS, FeatureInputError


def align_to_global_calendar(
    frame: pd.DataFrame,
    calendar: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    """Expand each security to the observed global grid for correct shifts/rolls."""

    missing = set(FEATURE_INPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise FeatureInputError(f"aligned input fields missing: {sorted(missing)}")
    sessions = calendar.loc[:, ["session_date", "session_index"]].copy()
    sessions["session_date"] = pd.to_datetime(sessions["session_date"]).dt.normalize()
    if sessions["session_date"].duplicated().any() or not sessions["session_date"].is_monotonic_increasing:
        raise FeatureInputError("global calendar must be unique and increasing")
    actual = frame.copy()
    actual["prediction_date"] = pd.to_datetime(actual["prediction_date"]).dt.normalize()
    actual = actual.drop(columns=["validated_xu100_close"])
    actual["_source_row_present"] = True
    securities = pd.DataFrame({"security_id": sorted(actual["security_id"].astype(str).unique())})
    securities["_join"] = 1
    sessions["_join"] = 1
    grid = securities.merge(sessions, on="_join", how="inner").drop(columns="_join")
    grid = grid.rename(columns={"session_date": "prediction_date"})
    aligned = grid.merge(
        actual,
        on=["security_id", "prediction_date"],
        how="left",
        validate="one_to_one",
    )
    market = benchmark.copy()
    market["prediction_date"] = pd.to_datetime(market["prediction_date"]).dt.normalize()
    aligned = aligned.merge(market, on="prediction_date", how="left", validate="many_to_one")
    aligned["_source_row_present"] = aligned["_source_row_present"].fillna(False).astype(bool)
    return aligned.sort_values(["security_id", "session_index"]).reset_index(drop=True)
