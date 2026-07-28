"""Classification, calibration and date-first Precision@K metrics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


class MetricError(ValueError):
    """Raised when prediction metric inputs are malformed."""


def deterministic_daily_rank(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort by probability DESC then security_id ASC and assign 1-based ranks."""

    required = {"prediction_date", "security_id", "probability_up_5pct"}
    if not required.issubset(frame.columns):
        raise MetricError("ranking fields missing")
    result = frame.copy()
    result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
    result = result.sort_values(
        ["prediction_date", "probability_up_5pct", "security_id"],
        ascending=[True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    result["daily_rank"] = result.groupby("prediction_date", sort=False).cumcount() + 1
    return result


def calibration_summary(
    y_true: pd.Series | np.ndarray,
    probabilities: pd.Series | np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, Any]:
    labels = np.asarray(y_true, dtype=int)
    probs = np.asarray(probabilities, dtype=float)
    if len(labels) != len(probs) or len(labels) == 0:
        raise MetricError("calibration requires equally sized non-empty arrays")
    if not np.isfinite(probs).all() or ((probs < 0) | (probs > 1)).any():
        raise MetricError("probabilities must be finite and within [0, 1]")
    bucket_count = min(max(1, int(bins)), len(probs))
    order = np.lexsort((np.arange(len(probs)), probs))
    assignments = np.empty(len(probs), dtype=int)
    for bin_number, indices in enumerate(np.array_split(order, bucket_count), start=1):
        assignments[indices] = bin_number
    detail: list[dict[str, Any]] = []
    weighted_gap = 0.0
    for bin_number in range(1, bucket_count + 1):
        mask = assignments == bin_number
        count = int(mask.sum())
        mean_probability = float(probs[mask].mean())
        observed_rate = float(labels[mask].mean())
        gap = abs(mean_probability - observed_rate)
        weighted_gap += gap * count / len(labels)
        detail.append(
            {
                "bin": bin_number,
                "count": count,
                "mean_prediction": mean_probability,
                "observed_positive_rate": observed_rate,
                "absolute_calibration_gap": gap,
            }
        )
    return {
        "requested_bins": int(bins),
        "effective_bins": bucket_count,
        "weighted_absolute_calibration_gap": float(weighted_gap),
        "bins": detail,
    }


def classification_metrics(
    y_true: pd.Series | np.ndarray,
    probabilities: pd.Series | np.ndarray,
    *,
    threshold: float = 0.50,
    calibration_bins: int = 10,
) -> dict[str, Any]:
    labels = np.asarray(y_true, dtype=int)
    probs = np.asarray(probabilities, dtype=float)
    if len(labels) != len(probs):
        raise MetricError("classification metrics require aligned inputs")
    if len(labels) == 0:
        return {
            "row_count": 0,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1_score": None,
            "roc_auc": None,
            "pr_auc": None,
            "confusion_matrix": {"tn": 0, "fp": 0, "fn": 0, "tp": 0},
            "positive_class_rate": None,
            "predicted_positive_rate": None,
            "brier_score": None,
            "calibration": {
                "requested_bins": int(calibration_bins),
                "effective_bins": 0,
                "weighted_absolute_calibration_gap": None,
                "bins": [],
            },
        }
    if not set(np.unique(labels).tolist()).issubset({0, 1}):
        raise MetricError("labels must be binary")
    if not np.isfinite(probs).all() or ((probs < 0) | (probs > 1)).any():
        raise MetricError("probabilities must be finite and within [0, 1]")
    predicted = (probs >= threshold).astype(int)
    unique = set(np.unique(labels).tolist())
    matrix = confusion_matrix(labels, predicted, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    precision = float(precision_score(labels, predicted, zero_division=0)) if tp + fp else None
    recall = float(recall_score(labels, predicted, zero_division=0)) if tp + fn else None
    f1 = float(f1_score(labels, predicted, zero_division=0)) if precision is not None and recall is not None and precision + recall > 0 else None
    return {
        "row_count": int(len(labels)),
        "accuracy": float(accuracy_score(labels, predicted)),
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "roc_auc": float(roc_auc_score(labels, probs)) if unique == {0, 1} else None,
        "pr_auc": float(average_precision_score(labels, probs)) if unique == {0, 1} else None,
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "positive_class_rate": float(labels.mean()),
        "predicted_positive_rate": float(predicted.mean()),
        "brier_score": float(brier_score_loss(labels, probs)),
        "calibration": calibration_summary(labels, probs, bins=calibration_bins),
    }


def daily_precision_at_k(
    predictions: pd.DataFrame,
    *,
    k: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select first, then measure available labels without backfilling NA picks."""

    if k <= 0:
        raise MetricError("k must be positive")
    required = {
        "security_id",
        "prediction_date",
        "probability_up_5pct",
        "prediction_eligible",
        "label",
    }
    if not required.issubset(predictions.columns):
        raise MetricError("Precision@K fields missing")
    ranked = deterministic_daily_rank(
        predictions.loc[predictions["prediction_eligible"].eq(True)].copy()
    )
    rows: list[dict[str, Any]] = []
    for prediction_date, day in ranked.groupby("prediction_date", sort=True):
        effective_k = min(k, len(day))
        selected = day.iloc[:effective_k]
        labels = pd.to_numeric(selected["label"], errors="coerce")
        valid = labels.isin([0, 1])
        valid_count = int(valid.sum())
        positive_count = int(labels.loc[valid].eq(1).sum())
        rows.append(
            {
                "prediction_date": prediction_date,
                "requested_k": int(k),
                "effective_k": int(effective_k),
                "selected_count": int(len(selected)),
                "valid_label_count": valid_count,
                "positive_count": positive_count,
                "precision_at_k": (
                    float(positive_count / valid_count) if valid_count else None
                ),
                "label_coverage_at_k": (
                    float(valid_count / len(selected)) if len(selected) else None
                ),
            }
        )
    detail = pd.DataFrame(
        rows,
        columns=[
            "prediction_date",
            "requested_k",
            "effective_k",
            "selected_count",
            "valid_label_count",
            "positive_count",
            "precision_at_k",
            "label_coverage_at_k",
        ],
    )
    precision_values = pd.to_numeric(detail["precision_at_k"], errors="coerce")
    total_valid = int(detail["valid_label_count"].sum())
    total_positive = int(detail["positive_count"].sum())
    summary = {
        "requested_k": int(k),
        "date_count": int(len(detail)),
        "macro_precision_at_k": (
            float(precision_values.mean()) if precision_values.notna().any() else None
        ),
        "pooled_precision_at_k": (
            float(total_positive / total_valid) if total_valid else None
        ),
        "pooled_valid_label_count": total_valid,
        "pooled_positive_count": total_positive,
    }
    return detail, summary
