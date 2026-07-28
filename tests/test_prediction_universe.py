from __future__ import annotations

import pandas as pd
import pytest

from src.modeling.prediction_universe import (
    PredictionUniverseError,
    build_prediction_universe,
)
from tests.modeling_support import synthetic_frames


def _reason(universe: pd.DataFrame, security: str, date: pd.Timestamp) -> object:
    return universe.loc[
        universe["security_id"].eq(security)
        & universe["prediction_date"].eq(date),
        "prediction_exclusion_reason",
    ].iloc[0]


def test_prediction_universe_uses_only_t_known_fields_and_21_sessions() -> None:
    master, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=2, sessions=25
    )
    universe = build_prediction_universe(master, observations, features, calendar, xu100)

    assert _reason(universe, "SEC_000", calendar.loc[19, "session_date"]) == "INSUFFICIENT_HISTORY"
    assert bool(
        universe.loc[
            universe["security_id"].eq("SEC_000")
            & universe["prediction_date"].eq(calendar.loc[20, "session_date"]),
            "prediction_eligible",
        ].iloc[0]
    )


def test_prediction_universe_reports_t_observation_ohlc_and_trade_reasons() -> None:
    master, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=3, sessions=25
    )
    date = calendar.loc[22, "session_date"]
    observations = observations.loc[
        ~(observations["security_id"].eq("SEC_000") & observations["prediction_date"].eq(date))
    ].copy()
    observations.loc[
        observations["security_id"].eq("SEC_001") & observations["prediction_date"].eq(date),
        "yf_nominal_high",
    ] = 1.0
    trade_mask = observations["security_id"].eq("SEC_002") & observations["prediction_date"].eq(date)
    observations.loc[trade_mask, ["is_tl_volume", "yf_share_volume"]] = 0.0

    universe = build_prediction_universe(master, observations, features, calendar, xu100)

    assert _reason(universe, "SEC_000", date) == "NO_T_OBSERVATION"
    assert _reason(universe, "SEC_001", date) == "INVALID_T_OHLC"
    assert _reason(universe, "SEC_002", date) == "NO_TRADE_ON_T"


def test_prediction_universe_reports_missing_evidence_feature_and_xu100() -> None:
    master, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=3, sessions=25
    )
    date = calendar.loc[22, "session_date"]
    mask = observations["security_id"].eq("SEC_000") & observations["prediction_date"].eq(date)
    observations.loc[mask, ["is_tl_volume", "yf_share_volume"]] = pd.NA
    features = features.loc[
        ~(features["security_id"].eq("SEC_001") & features["prediction_date"].eq(date))
    ]
    xu100.loc[xu100["prediction_date"].eq(date), "validated_xu100_close"] = pd.NA

    universe = build_prediction_universe(master, observations, features, calendar, xu100)

    assert _reason(universe, "SEC_000", date) == "MISSING_TRADE_EVIDENCE"
    assert _reason(universe, "SEC_001", date) == "MISSING_FEATURE_ROW"
    assert _reason(universe, "SEC_002", date) == "MISSING_XU100_SESSION"


def test_observed_security_outside_master_is_reported() -> None:
    master, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=2, sessions=25
    )
    outside_observation = observations.loc[observations["security_id"].eq("SEC_000")].copy()
    outside_observation["security_id"] = "SEC_OUTSIDE"
    outside_observation["observed_ticker"] = "OUT"
    outside_feature = features.loc[features["security_id"].eq("SEC_000")].copy()
    outside_feature["security_id"] = "SEC_OUTSIDE"
    universe = build_prediction_universe(
        master,
        pd.concat([observations, outside_observation], ignore_index=True),
        pd.concat([features, outside_feature], ignore_index=True),
        calendar,
        xu100,
    )

    assert _reason(universe, "SEC_OUTSIDE", calendar.loc[22, "session_date"]) == "NOT_IN_MASTER_UNIVERSE"


def test_date_effective_master_membership_is_evaluated_per_session() -> None:
    _, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=2, sessions=25
    )
    first_date = calendar.loc[22, "session_date"]
    second_date = calendar.loc[23, "session_date"]
    master = pd.DataFrame(
        {
            "security_id": ["SEC_000", "SEC_001", "SEC_000"],
            "prediction_date": [first_date, first_date, second_date],
        }
    )

    universe = build_prediction_universe(master, observations, features, calendar, xu100)

    assert bool(
        universe.loc[
            universe["security_id"].eq("SEC_001")
            & universe["prediction_date"].eq(first_date),
            "prediction_eligible",
        ].iloc[0]
    )
    assert _reason(universe, "SEC_001", second_date) == "NOT_IN_MASTER_UNIVERSE"


def test_duplicate_feature_key_fails_instead_of_silent_drop() -> None:
    master, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=2, sessions=25
    )
    duplicate = pd.concat([features, features.iloc[[0]]], ignore_index=True)

    with pytest.raises(PredictionUniverseError, match="DUPLICATE_FEATURE_ROW"):
        build_prediction_universe(master, observations, duplicate, calendar, xu100)


def test_t_plus_one_and_label_fields_cannot_define_universe() -> None:
    master, observations, features, calendar, xu100, _ = synthetic_frames(
        securities=2, sessions=25
    )

    with pytest.raises(PredictionUniverseError, match="future/outcome"):
        build_prediction_universe(
            master,
            observations.assign(entry_eligible=True, label=1),
            features,
            calendar,
            xu100,
        )
