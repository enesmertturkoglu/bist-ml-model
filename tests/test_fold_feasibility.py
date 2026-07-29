from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.full_history_pipeline import sha256_file
from src.modeling.dataset import build_training_dataset
from src.modeling.fold_feasibility import (
    FEASIBILITY_COLUMNS,
    render_fold_feasibility_summary,
    scan_fold_feasibility,
    write_fold_feasibility_reports,
)
from src.modeling.prediction_universe import build_prediction_universe
from tests.modeling_support import synthetic_frames


def _dataset(sessions: int = 375):
    master, observations, features, calendar, xu100, labels = synthetic_frames(
        securities=4, sessions=sessions
    )
    universe = build_prediction_universe(
        master, observations, features, calendar, xu100
    )
    dataset = build_training_dataset(
        universe,
        features,
        labels,
        calendar,
        as_of_date=calendar["session_date"].max(),
        feature_snapshot_id="features",
        label_snapshot_id="labels",
    )
    return dataset, calendar


def test_every_global_session_is_scanned_and_earliest_contract_date_is_feasible() -> None:
    dataset, calendar = _dataset()

    result = scan_fold_feasibility(
        dataset.panel,
        calendar,
        as_of_date=calendar["session_date"].max(),
    )

    expected = calendar.loc[335, "session_date"].date().isoformat()
    assert list(result.candidates.columns) == list(FEASIBILITY_COLUMNS)
    assert len(result.candidates) == len(calendar)
    assert result.earliest_feasible_date == expected
    earliest = result.candidates.loc[
        result.candidates["candidate_first_test_date"].eq(expected)
    ].iloc[0]
    assert earliest["warmup_session_count"] == 20
    assert earliest["fit_available_label_session_count"] == 252
    assert earliest["validation_calendar_session_count"] == 60
    assert earliest["validation_available_label_session_count"] == 57
    assert earliest["test_calendar_session_count"] == 20
    assert earliest["fit_positive_count"] > 0
    assert earliest["fit_negative_count"] > 0
    assert earliest["validation_positive_count"] > 0
    assert earliest["validation_negative_count"] > 0
    assert earliest["total_complete_fold_count"] == 2


def test_missing_validation_class_is_reported_without_training() -> None:
    dataset, calendar = _dataset()
    panel = dataset.panel.copy()
    first_test = calendar.loc[335, "session_date"]
    validation_start = calendar.loc[275, "session_date"]
    validation_usable_end = calendar.loc[331, "session_date"]
    mask = panel["prediction_date"].between(validation_start, validation_usable_end)
    panel.loc[mask & panel["label_status"].eq("LABELED"), "label"] = 0

    result = scan_fold_feasibility(
        panel, calendar, as_of_date=calendar["session_date"].max()
    )
    candidate = result.candidates.loc[
        result.candidates["candidate_first_test_date"].eq(
            first_test.date().isoformat()
        )
    ].iloc[0]

    assert not candidate["feasible"]
    assert "VALIDATION_MISSING_BINARY_CLASS" in candidate["failure_reason"]


def test_reports_are_deterministic_and_state_no_lightgbm_run(tmp_path: Path) -> None:
    dataset, calendar = _dataset()
    first = write_fold_feasibility_reports(
        dataset.panel,
        calendar,
        report_root=tmp_path / "first",
        as_of_date=calendar["session_date"].max(),
    )
    second = write_fold_feasibility_reports(
        dataset.panel,
        calendar,
        report_root=tmp_path / "second",
        as_of_date=calendar["session_date"].max(),
    )

    assert sha256_file(first["fold_feasibility"]) == sha256_file(
        second["fold_feasibility"]
    )
    assert sha256_file(first["fold_feasibility_summary"]) == sha256_file(
        second["fold_feasibility_summary"]
    )
    summary = first["fold_feasibility_summary"].read_text(encoding="utf-8")
    assert "LightGBM eğitimi çalıştırılmadı" in summary


def test_summary_contains_three_longer_history_alternatives_when_available() -> None:
    dataset, calendar = _dataset(sessions=420)
    result = scan_fold_feasibility(
        dataset.panel, calendar, as_of_date=calendar["session_date"].max()
    )
    summary = render_fold_feasibility_summary(result)

    assert len(result.alternative_dates) == 3
    assert all(value in summary for value in result.alternative_dates)
