from __future__ import annotations

import pandas as pd

from src.modeling.metrics import (
    classification_metrics,
    daily_precision_at_k,
    deterministic_daily_rank,
)


def _predictions() -> pd.DataFrame:
    rows = []
    for date, count in (("2024-01-02", 12), ("2024-01-03", 3)):
        for number in range(count):
            rows.append(
                {
                    "security_id": f"SEC_{number:03d}",
                    "prediction_date": date,
                    "probability_up_5pct": 1.0 - number / 20,
                    "prediction_eligible": True,
                    "label": (pd.NA if number == 0 else int(number % 2 == 0)),
                }
            )
    return pd.DataFrame(rows)


def test_daily_rank_is_probability_desc_security_asc_deterministic() -> None:
    frame = pd.DataFrame(
        {
            "security_id": ["SEC_B", "SEC_A", "SEC_C"],
            "prediction_date": ["2024-01-02"] * 3,
            "probability_up_5pct": [0.8, 0.8, 0.7],
        }
    )
    ranked = deterministic_daily_rank(frame)

    assert ranked["security_id"].tolist() == ["SEC_A", "SEC_B", "SEC_C"]
    assert ranked["daily_rank"].tolist() == [1, 2, 3]


def test_precision_at_k_handles_short_days_and_does_not_replace_na_label() -> None:
    detail, summary = daily_precision_at_k(_predictions(), k=5)
    first = detail.loc[detail["prediction_date"].eq(pd.Timestamp("2024-01-02"))].iloc[0]
    second = detail.loc[detail["prediction_date"].eq(pd.Timestamp("2024-01-03"))].iloc[0]

    assert first["selected_count"] == 5
    assert first["valid_label_count"] == 4
    assert first["positive_count"] == 2
    assert first["precision_at_k"] == 0.5
    assert second["effective_k"] == 3
    assert second["label_coverage_at_k"] == 2 / 3
    assert summary["date_count"] == 2


def test_precision_at_10_is_date_first_macro_and_pooled_are_separate() -> None:
    detail, summary = daily_precision_at_k(_predictions(), k=10)

    assert set(detail["requested_k"]) == {10}
    assert summary["macro_precision_at_k"] is not None
    assert summary["pooled_precision_at_k"] is not None


def test_single_class_fold_has_na_undefined_auc_metrics() -> None:
    metrics = classification_metrics([0, 0, 0], [0.1, 0.2, 0.3])

    assert metrics["roc_auc"] is None
    assert metrics["pr_auc"] is None
    assert metrics["recall"] is None
    assert metrics["confusion_matrix"] == {"tn": 3, "fp": 0, "fn": 0, "tp": 0}


def test_no_available_oos_labels_returns_explicit_na_metrics() -> None:
    metrics = classification_metrics([], [])

    assert metrics["row_count"] == 0
    assert metrics["accuracy"] is None
    assert metrics["roc_auc"] is None
    assert metrics["brier_score"] is None
    assert metrics["calibration"]["effective_bins"] == 0


def test_calibration_contains_ten_quantile_bins_and_brier_score() -> None:
    labels = [0, 1] * 10
    probabilities = [value / 20 for value in range(20)]
    metrics = classification_metrics(labels, probabilities)

    assert metrics["brier_score"] >= 0
    assert metrics["calibration"]["effective_bins"] == 10
    assert len(metrics["calibration"]["bins"]) == 10
    assert metrics["calibration"]["weighted_absolute_calibration_gap"] >= 0
