from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.catalog import BASELINE_V1_FEATURES
from src.modeling.dataset import (
    TrainingDatasetError,
    assign_label_available_dates,
    build_training_dataset,
    model_matrix,
)
from src.modeling.prediction_universe import build_prediction_universe
from tests.modeling_support import synthetic_frames


def test_label_availability_uses_third_global_session_not_ticker_shift() -> None:
    _, _, _, calendar, _, labels = synthetic_frames(securities=2, sessions=8)
    missing_ticker_day = labels.loc[
        ~(labels["security_id"].eq("SEC_000") & labels["prediction_date"].eq(calendar.loc[1, "session_date"]))
    ]
    result = assign_label_available_dates(missing_ticker_day, calendar)
    first = result.loc[result["prediction_date"].eq(calendar.loc[0, "session_date"])]

    assert first["label_available_date"].nunique() == 1
    assert first["label_available_date"].iloc[0] == calendar.loc[3, "session_date"]


def test_feature_and_label_join_is_security_date_one_to_one() -> None:
    master, observations, features, calendar, xu100, labels = synthetic_frames(
        securities=2, sessions=25
    )
    universe = build_prediction_universe(master, observations, features, calendar, xu100)

    with pytest.raises(TrainingDatasetError, match="feature join key"):
        build_training_dataset(
            universe,
            pd.concat([features, features.iloc[[0]]], ignore_index=True),
            labels,
            calendar,
            as_of_date=calendar["session_date"].max(),
            feature_snapshot_id="f",
            label_snapshot_id="l",
        )
    with pytest.raises(TrainingDatasetError, match="label join key"):
        build_training_dataset(
            universe,
            features,
            pd.concat([labels, labels.iloc[[0]]], ignore_index=True),
            calendar,
            as_of_date=calendar["session_date"].max(),
            feature_snapshot_id="f",
            label_snapshot_id="l",
        )


def test_training_rows_require_eligibility_valid_label_and_as_of_availability() -> None:
    master, observations, features, calendar, xu100, labels = synthetic_frames(
        securities=2, sessions=25
    )
    universe = build_prediction_universe(master, observations, features, calendar, xu100)
    cutoff = calendar.loc[22, "session_date"]
    dataset = build_training_dataset(
        universe,
        features,
        labels,
        calendar,
        as_of_date=cutoff,
        feature_snapshot_id="f",
        label_snapshot_id="l",
    )

    assert dataset.model_rows["prediction_eligible"].all()
    assert dataset.model_rows["label_status"].eq("LABELED").all()
    assert set(dataset.model_rows["label"].unique()).issubset({0, 1})
    assert dataset.model_rows["label_available_date"].le(cutoff).all()


def test_model_matrix_is_exact_32_and_preserves_nan_without_audit_fields() -> None:
    master, observations, features, calendar, xu100, labels = synthetic_frames(
        securities=2, sessions=30
    )
    universe = build_prediction_universe(master, observations, features, calendar, xu100)
    dataset = build_training_dataset(
        universe,
        features,
        labels,
        calendar,
        as_of_date=calendar["session_date"].max(),
        feature_snapshot_id="f",
        label_snapshot_id="l",
    )
    matrix = model_matrix(dataset.panel)

    assert list(matrix.columns) == list(BASELINE_V1_FEATURES)
    assert matrix.shape[1] == 32
    assert matrix["ret_20"].isna().any()
    assert {"security_id", "prediction_date", "label", "feature_snapshot_id"}.isdisjoint(matrix.columns)


def test_feature_schema_mismatch_is_explicit() -> None:
    master, observations, features, calendar, xu100, labels = synthetic_frames(
        securities=2, sessions=25
    )
    universe = build_prediction_universe(master, observations, features, calendar, xu100)

    with pytest.raises(TrainingDatasetError, match="schema mismatch"):
        build_training_dataset(
            universe,
            features.drop(columns=BASELINE_V1_FEATURES[-1]),
            labels,
            calendar,
            as_of_date=calendar["session_date"].max(),
            feature_snapshot_id="f",
            label_snapshot_id="l",
        )
