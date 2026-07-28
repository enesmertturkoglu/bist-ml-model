from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import ModelTrainingConfig
from src.features.catalog import BASELINE_V1_FEATURES
from src.modeling import lightgbm_training
from src.modeling.dataset import model_matrix
from src.modeling.lightgbm_training import fit_lightgbm_fold, positive_class_probability
from src.modeling.walk_forward import (
    generate_walk_forward_folds,
    split_fold_rows,
    validate_fold_classes,
)
from tests.modeling_support import fast_training_config, synthetic_dataset


class _FakeBooster:
    def save_model(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("fake lightgbm model\n")


class _FakeLGBMClassifier:
    last_instance = None

    def __init__(self, **parameters: object) -> None:
        self.parameters = parameters
        self.classes_ = np.array([0, 1])
        self.best_iteration_ = 7
        self.booster_ = _FakeBooster()
        self.fit_arguments = None
        _FakeLGBMClassifier.last_instance = self

    def fit(self, x, y, **kwargs):
        self.fit_arguments = (x.copy(), y.copy(), kwargs)
        return self

    def predict_proba(self, x):
        raw = pd.to_numeric(x.iloc[:, 0], errors="coerce").fillna(0).to_numpy()
        probability = 1 / (1 + np.exp(-raw))
        return np.column_stack([1 - probability, probability])


def test_baseline_parameters_are_exact_and_only_lgbmclassifier_is_constructed(monkeypatch) -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=80)
    config = fast_training_config()
    fold = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[69, "session_date"],
        config=config,
    )[0]
    rows = split_fold_rows(dataset.panel, fold)
    validate_fold_classes(rows)
    monkeypatch.setattr(
        lightgbm_training,
        "_lightgbm_api",
        lambda: (_FakeLGBMClassifier, lambda *args, **kwargs: ("early", args, kwargs), lambda **kwargs: ("log", kwargs)),
    )

    fitted = fit_lightgbm_fold(rows.fit, rows.validation, config=config)

    assert isinstance(fitted.model, _FakeLGBMClassifier)
    assert fitted.model.parameters == config.lightgbm_parameters
    assert ModelTrainingConfig().lightgbm_parameters == {
        "objective": "binary",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "min_data_in_leaf": 100,
        "n_estimators": 1000,
        "random_state": 42,
        "verbosity": -1,
        "deterministic": True,
        "force_col_wise": True,
        "n_jobs": 1,
        "feature_fraction": 1.0,
        "bagging_fraction": 1.0,
        "bagging_freq": 0,
        "scale_pos_weight": 1.0,
        "is_unbalance": False,
    }


def test_early_stopping_receives_only_validation_not_test(monkeypatch) -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=80)
    config = fast_training_config()
    fold = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[69, "session_date"],
        config=config,
    )[0]
    rows = split_fold_rows(dataset.panel, fold)
    monkeypatch.setattr(
        lightgbm_training,
        "_lightgbm_api",
        lambda: (_FakeLGBMClassifier, lambda *args, **kwargs: "early", lambda **kwargs: "log"),
    )

    fit_lightgbm_fold(rows.fit, rows.validation, config=config)
    _, _, kwargs = _FakeLGBMClassifier.last_instance.fit_arguments
    eval_x, eval_y = kwargs["eval_set"][0]

    pd.testing.assert_frame_equal(eval_x.reset_index(drop=True), model_matrix(rows.validation).reset_index(drop=True))
    assert eval_y.reset_index(drop=True).equals(rows.validation["label"].astype(int).reset_index(drop=True))
    assert len(kwargs["eval_set"]) == 1


def test_positive_class_probability_uses_second_column() -> None:
    class Model:
        classes_ = np.array([0, 1])

        def predict_proba(self, features):
            return np.array([[0.9, 0.1], [0.2, 0.8]])

    result = positive_class_probability(Model(), pd.DataFrame({"x": [1, 2]}))

    assert result.tolist() == [0.1, 0.8]


def test_real_lightgbm_same_seed_and_inputs_are_reproducible() -> None:
    dataset, calendar, _, _ = synthetic_dataset(sessions=80)
    config = fast_training_config()
    fold = generate_walk_forward_folds(
        calendar,
        first_test_start_date=calendar.loc[60, "session_date"],
        as_of_date=calendar.loc[69, "session_date"],
        config=config,
    )[0]
    rows = split_fold_rows(dataset.panel, fold)

    first = fit_lightgbm_fold(rows.fit, rows.validation, config=config)
    second = fit_lightgbm_fold(rows.fit, rows.validation, config=config)
    first_probability = positive_class_probability(first.model, model_matrix(rows.test))
    second_probability = positive_class_probability(second.model, model_matrix(rows.test))

    np.testing.assert_allclose(first_probability, second_probability, rtol=0, atol=0)
    assert first.best_iteration == second.best_iteration
