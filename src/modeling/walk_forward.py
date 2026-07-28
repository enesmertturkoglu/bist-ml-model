"""Date-grouped expanding walk-forward fold definitions and purged splits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from src.config import ModelTrainingConfig


class WalkForwardError(ValueError):
    """Raised when a requested time split violates the D030 contract."""


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    training_start_date: str
    training_end_date: str
    fit_calendar_session_count: int
    fit_labeled_session_count: int
    fit_purged_session_count: int
    validation_start_date: str
    validation_end_date: str
    validation_calendar_session_count: int
    validation_labeled_session_count: int
    validation_purged_session_count: int
    test_start_date: str
    test_end_date: str
    test_calendar_session_count: int

    @property
    def model_version_suffix(self) -> str:
        return self.fold_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FoldRows:
    fit: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame


def _sessions(calendar: pd.DataFrame, as_of_date: pd.Timestamp) -> list[pd.Timestamp]:
    if not {"session_date", "session_index"}.issubset(calendar.columns):
        raise WalkForwardError("global calendar fields missing")
    frame = calendar.loc[:, ["session_date", "session_index"]].copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
    frame["session_index"] = pd.to_numeric(frame["session_index"], errors="raise")
    if frame["session_date"].duplicated().any():
        raise WalkForwardError("global calendar contains duplicate sessions")
    frame = frame.sort_values("session_index").reset_index(drop=True)
    if frame["session_index"].tolist() != list(range(len(frame))):
        raise WalkForwardError("global calendar session_index must be contiguous")
    return frame.loc[frame["session_date"].le(as_of_date), "session_date"].tolist()


def generate_walk_forward_folds(
    calendar: pd.DataFrame,
    *,
    first_test_start_date: str | pd.Timestamp,
    as_of_date: str | pd.Timestamp,
    config: ModelTrainingConfig | None = None,
) -> tuple[WalkForwardFold, ...]:
    """Generate full 20-session test blocks; the first real date stays explicit."""

    settings = config or ModelTrainingConfig()
    if settings.training_window != "expanding":
        raise WalkForwardError("only expanding training windows are supported")
    if settings.validation_sessions <= settings.label_horizon_sessions:
        raise WalkForwardError(
            "validation window must exceed the label purge horizon"
        )
    cutoff = pd.Timestamp(as_of_date).normalize()
    dates = _sessions(calendar, cutoff)
    if not dates:
        raise WalkForwardError("no calendar sessions at or before as_of_date")
    test_start = pd.Timestamp(first_test_start_date).normalize()
    try:
        first_test_index = dates.index(test_start)
    except ValueError as exc:
        raise WalkForwardError("first_test_start_date is not a global BIST session") from exc
    validation_start_index = first_test_index - settings.validation_sessions
    if validation_start_index < 0:
        raise WalkForwardError("insufficient sessions for the validation window")
    # First remove feature warm-up sessions, then the T+3 labels that are not
    # strictly available before validation_start_date.
    effective_fit_sessions = (
        validation_start_index
        - settings.label_horizon_sessions
        - (settings.minimum_feature_history_sessions - 1)
    )
    if effective_fit_sessions < settings.minimum_training_sessions:
        raise WalkForwardError(
            "insufficient post-warm-up purged fit sessions before first validation"
        )

    folds: list[WalkForwardFold] = []
    training_start_index = settings.minimum_feature_history_sessions - 1
    current_test_index = first_test_index
    fold_number = 1
    while current_test_index + settings.test_sessions <= len(dates):
        validation_start_index = current_test_index - settings.validation_sessions
        if validation_start_index < 0:
            break
        training_end_index = validation_start_index - 1
        validation_end_index = current_test_index - 1
        test_end_index = current_test_index + settings.test_sessions - 1
        fit_calendar_session_count = validation_start_index - training_start_index
        fit_purged_session_count = settings.label_horizon_sessions
        validation_purged_session_count = settings.label_horizon_sessions
        folds.append(
            WalkForwardFold(
                fold_id=f"fold_{fold_number:03d}",
                training_start_date=dates[training_start_index].date().isoformat(),
                training_end_date=dates[training_end_index].date().isoformat(),
                fit_calendar_session_count=fit_calendar_session_count,
                fit_labeled_session_count=(
                    fit_calendar_session_count - fit_purged_session_count
                ),
                fit_purged_session_count=fit_purged_session_count,
                validation_start_date=dates[validation_start_index].date().isoformat(),
                validation_end_date=dates[validation_end_index].date().isoformat(),
                validation_calendar_session_count=settings.validation_sessions,
                validation_labeled_session_count=(
                    settings.validation_sessions - validation_purged_session_count
                ),
                validation_purged_session_count=validation_purged_session_count,
                test_start_date=dates[current_test_index].date().isoformat(),
                test_end_date=dates[test_end_index].date().isoformat(),
                test_calendar_session_count=settings.test_sessions,
            )
        )
        current_test_index += settings.test_sessions
        fold_number += 1
    if not folds:
        raise WalkForwardError("no complete walk-forward test block can be generated")
    return tuple(folds)


def split_fold_rows(panel: pd.DataFrame, fold: WalkForwardFold) -> FoldRows:
    """Apply strict availability purge and keep every date wholly in one group."""

    required = {
        "prediction_date",
        "prediction_eligible",
        "label_available_date",
        "label_status",
        "label",
    }
    if not required.issubset(panel.columns):
        raise WalkForwardError("training panel fields missing")
    frame = panel.copy()
    frame["prediction_date"] = pd.to_datetime(frame["prediction_date"]).dt.normalize()
    frame["label_available_date"] = pd.to_datetime(frame["label_available_date"])
    training_start = pd.Timestamp(fold.training_start_date)
    training_end = pd.Timestamp(fold.training_end_date)
    validation_start = pd.Timestamp(fold.validation_start_date)
    validation_end = pd.Timestamp(fold.validation_end_date)
    test_start = pd.Timestamp(fold.test_start_date)
    test_end = pd.Timestamp(fold.test_end_date)
    eligible = frame["prediction_eligible"].eq(True)
    labeled = frame["label_status"].eq("LABELED") & frame["label"].isin([0, 1])

    fit = frame.loc[
        eligible
        & labeled
        & frame["prediction_date"].between(training_start, training_end)
        & frame["label_available_date"].lt(validation_start)
    ].copy()
    validation = frame.loc[
        eligible
        & labeled
        & frame["prediction_date"].between(validation_start, validation_end)
        & frame["label_available_date"].lt(test_start)
    ].copy()
    test = frame.loc[
        eligible & frame["prediction_date"].between(test_start, test_end)
    ].copy()
    date_sets = [
        set(item["prediction_date"].dropna()) for item in (fit, validation, test)
    ]
    if date_sets[0] & date_sets[1] or date_sets[0] & date_sets[2] or date_sets[1] & date_sets[2]:
        raise WalkForwardError("train/validation/test dates overlap")
    return FoldRows(
        fit.sort_values(["prediction_date", "security_id"]).reset_index(drop=True),
        validation.sort_values(["prediction_date", "security_id"]).reset_index(drop=True),
        test.sort_values(["prediction_date", "security_id"]).reset_index(drop=True),
    )


def validate_fold_classes(rows: FoldRows) -> None:
    """Fail before LightGBM when fit or validation lacks the binary target."""

    if rows.fit.empty or rows.validation.empty or rows.test.empty:
        raise WalkForwardError("fold fit, validation and test must all be non-empty")
    if set(rows.fit["label"].astype(int).unique()) != {0, 1}:
        raise WalkForwardError("fit rows must contain both classes")
    if set(rows.validation["label"].astype(int).unique()) != {0, 1}:
        raise WalkForwardError("validation rows must contain both classes")
