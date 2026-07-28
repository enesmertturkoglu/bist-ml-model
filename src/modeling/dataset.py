"""One-to-one feature/label joins and global-calendar label availability."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.features.catalog import BASELINE_V1_FEATURES
class TrainingDatasetError(ValueError):
    """Raised when a training panel violates its schema or temporal contract."""


@dataclass(frozen=True)
class TrainingDataset:
    panel: pd.DataFrame
    model_rows: pd.DataFrame
    feature_names: tuple[str, ...]
    as_of_date: pd.Timestamp


def assign_label_available_dates(
    labels: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    horizon_sessions: int = 3,
) -> pd.DataFrame:
    """Map T to the third following global BIST session; never ticker-shift."""

    if horizon_sessions != 3:
        raise TrainingDatasetError("binding label availability horizon must be three")
    if "prediction_date" not in labels.columns:
        raise TrainingDatasetError("label frame has no prediction_date")
    required_calendar = {"session_date", "session_index"}
    if not required_calendar.issubset(calendar.columns):
        raise TrainingDatasetError("global calendar fields missing")
    sessions = calendar.loc[:, ["session_date", "session_index"]].copy()
    sessions["session_date"] = pd.to_datetime(sessions["session_date"], errors="raise").dt.normalize()
    sessions["session_index"] = pd.to_numeric(sessions["session_index"], errors="raise")
    if sessions["session_date"].duplicated().any():
        raise TrainingDatasetError("global calendar contains duplicate sessions")
    sessions = sessions.sort_values("session_index").reset_index(drop=True)
    if sessions["session_index"].tolist() != list(range(len(sessions))):
        raise TrainingDatasetError("global calendar session_index must be contiguous")
    date_by_index = sessions.set_index("session_index")["session_date"]
    index_by_date = sessions.set_index("session_date")["session_index"]

    result = labels.copy()
    result["prediction_date"] = pd.to_datetime(
        result["prediction_date"], errors="raise"
    ).dt.normalize()
    prediction_index = result["prediction_date"].map(index_by_date)
    if prediction_index.isna().any():
        raise TrainingDatasetError("label prediction_date falls outside global calendar")
    result["label_available_date"] = (prediction_index + horizon_sessions).map(
        date_by_index
    )
    return result


def _validate_features(features: pd.DataFrame) -> pd.DataFrame:
    expected = ["security_id", "prediction_date", *BASELINE_V1_FEATURES]
    if set(features.columns) != set(expected) or len(features.columns) != len(expected):
        raise TrainingDatasetError("feature schema mismatch for baseline_v1")
    frame = features.loc[:, expected].copy()
    frame["security_id"] = frame["security_id"].astype(str)
    frame["prediction_date"] = pd.to_datetime(
        frame["prediction_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["security_id", "prediction_date"]).any():
        raise TrainingDatasetError("feature join key is not one-to-one")
    return frame


def build_training_dataset(
    prediction_universe: pd.DataFrame,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    as_of_date: str | pd.Timestamp,
    feature_snapshot_id: str,
    label_snapshot_id: str,
) -> TrainingDataset:
    """Build the auditable panel and filter only concluded labels for fitting."""

    universe_required = {
        "security_id",
        "prediction_date",
        "prediction_eligible",
        "prediction_exclusion_reason",
    }
    if not universe_required.issubset(prediction_universe.columns):
        raise TrainingDatasetError("prediction universe fields missing")
    universe = prediction_universe.copy()
    universe["security_id"] = universe["security_id"].astype(str)
    universe["prediction_date"] = pd.to_datetime(
        universe["prediction_date"], errors="raise"
    ).dt.normalize()
    if universe.duplicated(["security_id", "prediction_date"]).any():
        raise TrainingDatasetError("prediction universe key is not one-to-one")

    feature_frame = _validate_features(features)
    label_required = {"security_id", "prediction_date", "label", "label_status"}
    if not label_required.issubset(labels.columns):
        raise TrainingDatasetError("label fields missing")
    label_frame = labels.copy()
    label_frame["security_id"] = label_frame["security_id"].astype(str)
    label_frame["prediction_date"] = pd.to_datetime(
        label_frame["prediction_date"], errors="raise"
    ).dt.normalize()
    if label_frame.duplicated(["security_id", "prediction_date"]).any():
        raise TrainingDatasetError("label join key is not one-to-one")
    label_frame = assign_label_available_dates(label_frame, calendar)

    try:
        panel = universe.merge(
            feature_frame,
            on=["security_id", "prediction_date"],
            how="left",
            validate="one_to_one",
        ).merge(
            label_frame,
            on=["security_id", "prediction_date"],
            how="left",
            validate="one_to_one",
            suffixes=("", "_label"),
        )
    except pd.errors.MergeError as exc:
        raise TrainingDatasetError("feature/label join is not one-to-one") from exc
    cutoff = pd.Timestamp(as_of_date).normalize()
    panel["feature_snapshot_id"] = str(feature_snapshot_id)
    panel["label_snapshot_id"] = str(label_snapshot_id)
    valid_label = (
        panel["label_status"].eq("LABELED")
        & panel["label"].isin([0, 1])
        & panel["label_available_date"].notna()
        & panel["label_available_date"].le(cutoff)
    )
    eligible = panel["prediction_eligible"].eq(True)
    model_rows = panel.loc[eligible & valid_label].copy()
    if not model_rows.empty:
        model_rows["label"] = model_rows["label"].astype(int)
    return TrainingDataset(
        panel=panel.sort_values(["prediction_date", "security_id"]).reset_index(drop=True),
        model_rows=model_rows.sort_values(["prediction_date", "security_id"]).reset_index(drop=True),
        feature_names=BASELINE_V1_FEATURES,
        as_of_date=cutoff,
    )


def model_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Project exactly the ordered 32 features and preserve NaN values."""

    missing = set(BASELINE_V1_FEATURES).difference(frame.columns)
    if missing:
        raise TrainingDatasetError(f"model feature fields missing: {sorted(missing)}")
    matrix = frame.loc[:, BASELINE_V1_FEATURES].apply(pd.to_numeric, errors="coerce")
    if list(matrix.columns) != list(BASELINE_V1_FEATURES):
        raise TrainingDatasetError("model feature order mismatch")
    return matrix
