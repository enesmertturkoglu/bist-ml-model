"""Strict LGBMClassifier fitting with validation-only early stopping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.config import ModelTrainingConfig
from src.modeling.dataset import model_matrix
from src.modeling.metrics import classification_metrics


class LightGBMTrainingError(RuntimeError):
    """Raised when the binding LightGBM training contract cannot be met."""


@dataclass(frozen=True)
class FittedLightGBMFold:
    model: Any
    training_metrics: dict[str, Any]
    validation_metrics: dict[str, Any]
    best_iteration: int | None


def _lightgbm_api() -> tuple[Any, Any, Any]:
    try:
        from lightgbm import LGBMClassifier, early_stopping, log_evaluation
    except ImportError as exc:
        raise LightGBMTrainingError(
            "lightgbm is required; install the LightGBM Python package"
        ) from exc
    return LGBMClassifier, early_stopping, log_evaluation


def fit_lightgbm_fold(
    fit_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    *,
    config: ModelTrainingConfig | None = None,
) -> FittedLightGBMFold:
    """Train from scratch; the test block is deliberately absent from this API."""

    settings = config or ModelTrainingConfig()
    if set(pd.to_numeric(fit_rows["label"], errors="raise").astype(int).unique()) != {0, 1}:
        raise LightGBMTrainingError("fit rows must contain both classes")
    if set(pd.to_numeric(validation_rows["label"], errors="raise").astype(int).unique()) != {0, 1}:
        raise LightGBMTrainingError("validation rows must contain both classes")
    LGBMClassifier, early_stopping, log_evaluation = _lightgbm_api()
    model = LGBMClassifier(**settings.lightgbm_parameters)
    fit_x = model_matrix(fit_rows)
    validation_x = model_matrix(validation_rows)
    fit_y = fit_rows["label"].astype(int)
    validation_y = validation_rows["label"].astype(int)
    model.fit(
        fit_x,
        fit_y,
        eval_set=[(validation_x, validation_y)],
        eval_metric=settings.early_stopping_metric,
        callbacks=[
            early_stopping(settings.early_stopping_rounds, verbose=False),
            log_evaluation(period=0),
        ],
    )
    training_probability = positive_class_probability(model, fit_x)
    validation_probability = positive_class_probability(model, validation_x)
    return FittedLightGBMFold(
        model=model,
        training_metrics=classification_metrics(
            fit_y,
            training_probability,
            threshold=settings.classification_threshold,
            calibration_bins=settings.calibration_bins,
        ),
        validation_metrics=classification_metrics(
            validation_y,
            validation_probability,
            threshold=settings.classification_threshold,
            calibration_bins=settings.calibration_bins,
        ),
        best_iteration=(
            int(model.best_iteration_)
            if getattr(model, "best_iteration_", None) is not None
            else None
        ),
    )


def positive_class_probability(model: Any, features: pd.DataFrame) -> np.ndarray:
    """Return the binding ``predict_proba(X)[:, 1]`` score."""

    probabilities = np.asarray(model.predict_proba(features), dtype=float)
    if probabilities.ndim != 2 or probabilities.shape[1] != 2:
        raise LightGBMTrainingError("binary predict_proba output must have two columns")
    classes = list(getattr(model, "classes_", []))
    if classes != [0, 1]:
        raise LightGBMTrainingError("LightGBM class order must be [0, 1]")
    result = probabilities[:, 1]
    if not np.isfinite(result).all() or ((result < 0) | (result > 1)).any():
        raise LightGBMTrainingError("LightGBM emitted invalid probabilities")
    return result
