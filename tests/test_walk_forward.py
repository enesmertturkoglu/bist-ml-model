from __future__ import annotations

import inspect

import pandas as pd
import pytest

from src.config import ModelTrainingConfig
from src.modeling import walk_forward
from src.modeling.walk_forward import (
    WalkForwardError,
    generate_walk_forward_folds,
    split_fold_rows,
)
from tests.modeling_support import fast_training_config, synthetic_dataset


def test_synthetic_calendar_produces_at_least_two_complete_folds() -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=100)
    config = fast_training_config()
    folds = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[89, "session_date"],
        config=config,
    )

    assert len(folds) == 3
    assert all(
        len(split_fold_rows(dataset.panel, fold).test["prediction_date"].unique())
        == config.test_sessions
        for fold in folds
    )


def test_expanding_fit_and_fixed_validation_test_windows() -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=100)
    config = fast_training_config()
    folds = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[89, "session_date"],
        config=config,
    )
    splits = [split_fold_rows(dataset.panel, fold) for fold in folds]

    assert [len(item.validation["prediction_date"].unique()) for item in splits] == [17, 17, 17]
    assert [len(item.test["prediction_date"].unique()) for item in splits] == [10, 10, 10]
    assert all(
        len(item.fit["prediction_date"].unique()) >= config.minimum_training_sessions
        for item in splits
    )
    assert len(splits[1].fit) > len(splits[0].fit)


def test_strict_label_purge_is_applied_to_fit_and_validation() -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=100)
    fold = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[69, "session_date"],
        config=fast_training_config(),
    )[0]
    rows = split_fold_rows(dataset.panel, fold)

    assert rows.fit["label_available_date"].lt(pd.Timestamp(fold.validation_start_date)).all()
    assert rows.validation["label_available_date"].lt(pd.Timestamp(fold.test_start_date)).all()


def test_same_prediction_date_is_never_split_across_sets() -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=100)
    fold = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[69, "session_date"],
        config=fast_training_config(),
    )[0]
    rows = split_fold_rows(dataset.panel, fold)
    fit_dates = set(rows.fit["prediction_date"])
    validation_dates = set(rows.validation["prediction_date"])
    test_dates = set(rows.test["prediction_date"])

    assert not fit_dates & validation_dates
    assert not fit_dates & test_dates
    assert not validation_dates & test_dates


def test_walk_forward_module_has_no_random_split() -> None:
    source = inspect.getsource(walk_forward)

    assert "train_test_split" not in source
    assert "random_split" not in source


def test_default_first_fold_counts_warmup_and_purge_before_252_fit_sessions() -> None:
    dates = pd.bdate_range("2020-01-02", periods=360)
    calendar = pd.DataFrame(
        {"session_date": dates, "session_index": range(len(dates))}
    )
    config = ModelTrainingConfig()

    with pytest.raises(WalkForwardError, match="post-warm-up purged"):
        generate_walk_forward_folds(
            calendar,
            first_test_start_date=dates[334],
            as_of_date=dates[353],
            config=config,
        )

    folds = generate_walk_forward_folds(
        calendar,
        first_test_start_date=dates[335],
        as_of_date=dates[354],
        config=config,
    )

    assert len(folds) == 1
    assert folds[0].training_start_date == dates[20].date().isoformat()
    assert folds[0].fit_calendar_session_count == 255
    assert folds[0].fit_labeled_session_count == 252
    assert folds[0].fit_purged_session_count == 3


def test_synthetic_data_produces_two_full_60_validation_20_test_folds() -> None:
    dataset, calendar, _, _ = synthetic_dataset(securities=4, sessions=375)
    config = ModelTrainingConfig()

    folds = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[335, "session_date"],
        as_of_date=calendar.loc[374, "session_date"],
        config=config,
    )
    splits = [split_fold_rows(dataset.panel, fold) for fold in folds]

    assert len(folds) == 2
    assert [fold.fit_calendar_session_count for fold in folds] == [255, 275]
    assert [fold.fit_labeled_session_count for fold in folds] == [252, 272]
    assert [fold.fit_purged_session_count for fold in folds] == [3, 3]
    assert [fold.validation_calendar_session_count for fold in folds] == [60, 60]
    assert [fold.validation_labeled_session_count for fold in folds] == [57, 57]
    assert [fold.validation_purged_session_count for fold in folds] == [3, 3]
    assert [fold.test_calendar_session_count for fold in folds] == [20, 20]
    assert [len(rows.fit["prediction_date"].unique()) for rows in splits] == [252, 272]
    assert [len(rows.validation["prediction_date"].unique()) for rows in splits] == [57, 57]
    assert [len(rows.test["prediction_date"].unique()) for rows in splits] == [20, 20]
