from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from src.config import ModelTrainingConfig
from src.features.catalog import BASELINE_V1_FEATURES
from src.modeling.dataset import TrainingDataset, build_training_dataset
from src.modeling.prediction_universe import build_prediction_universe


def synthetic_frames(
    *, securities: int = 8, sessions: int = 100
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dates = pd.bdate_range("2023-01-02", periods=sessions)
    calendar = pd.DataFrame(
        {"session_date": dates, "session_index": range(sessions)}
    )
    xu100 = pd.DataFrame(
        {
            "prediction_date": dates,
            "validated_xu100_close": 5000.0 + np.arange(sessions) * 2.0,
        }
    )
    rows: list[dict[str, object]] = []
    feature_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    master: list[str] = []
    for security_number in range(securities):
        security_id = f"SEC_{security_number:03d}"
        ticker = f"T{security_number:03d}"
        master.append(security_id)
        for date_number, prediction_date in enumerate(dates):
            close = 20.0 + security_number + date_number * 0.03
            rows.append(
                {
                    "security_id": security_id,
                    "observed_ticker": ticker,
                    "prediction_date": prediction_date,
                    "yf_nominal_open": close * 0.995,
                    "yf_nominal_high": close * 1.015,
                    "yf_nominal_low": close * 0.985,
                    "yf_nominal_close": close,
                    "is_tl_volume": 1_000_000.0 + security_number * 10_000 + date_number,
                    "yf_share_volume": 100_000.0 + security_number * 1_000 + date_number,
                }
            )
            values = {
                name: (
                    np.nan
                    if name == "ret_20" and date_number == 25 and security_number == 0
                    else ((date_number + 1) * (security_number + 2) + feature_index) / 1000
                )
                for feature_index, name in enumerate(BASELINE_V1_FEATURES)
            }
            feature_rows.append(
                {
                    "security_id": security_id,
                    "prediction_date": prediction_date,
                    **values,
                }
            )
            label_rows.append(
                {
                    "security_id": security_id,
                    "observed_ticker": ticker,
                    "prediction_date": prediction_date,
                    "label": int((date_number + security_number) % 4 == 0),
                    "label_status": "LABELED",
                }
            )
    return (
        pd.DataFrame({"security_id": master}),
        pd.DataFrame(rows),
        pd.DataFrame(feature_rows),
        calendar,
        xu100,
        pd.DataFrame(label_rows),
    )


def synthetic_dataset(
    *, securities: int = 8, sessions: int = 100
) -> tuple[TrainingDataset, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    master, observations, features, calendar, xu100, labels = synthetic_frames(
        securities=securities, sessions=sessions
    )
    universe = build_prediction_universe(
        master,
        observations,
        features,
        calendar,
        xu100,
        minimum_history_sessions=21,
    )
    dataset = build_training_dataset(
        universe,
        features,
        labels,
        calendar,
        as_of_date=calendar["session_date"].max(),
        feature_snapshot_id="feature-snapshot",
        label_snapshot_id="label-snapshot",
    )
    return dataset, calendar, features, labels


def fast_training_config(**changes: object) -> ModelTrainingConfig:
    return replace(
        ModelTrainingConfig(),
        validation_sessions=20,
        test_sessions=10,
        minimum_training_sessions=15,
        min_data_in_leaf=5,
        n_estimators=80,
        early_stopping_rounds=10,
        **changes,
    )
