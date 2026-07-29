"""Data-only feasibility scan for every possible first walk-forward test date."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.config import ModelTrainingConfig
from src.data.full_history_pipeline import atomic_write_csv, atomic_write_text
from src.modeling.walk_forward import WalkForwardError, generate_walk_forward_folds


FEASIBILITY_COLUMNS: tuple[str, ...] = (
    "candidate_first_test_date",
    "feasible",
    "failure_reason",
    "warmup_session_count",
    "fit_start_date",
    "fit_end_date",
    "fit_calendar_session_count",
    "fit_contract_labeled_session_count",
    "fit_purged_session_count",
    "fit_available_label_session_count",
    "fit_row_count",
    "fit_positive_count",
    "fit_negative_count",
    "fit_daily_row_count_min",
    "fit_daily_row_count_median",
    "fit_daily_row_count_max",
    "fit_2020_2021_session_count",
    "fit_2020_2021_row_count",
    "validation_start_date",
    "validation_end_date",
    "validation_calendar_session_count",
    "validation_contract_labeled_session_count",
    "validation_purged_session_count",
    "validation_available_label_session_count",
    "validation_row_count",
    "validation_positive_count",
    "validation_negative_count",
    "validation_daily_row_count_min",
    "validation_daily_row_count_median",
    "validation_daily_row_count_max",
    "validation_2020_2021_session_count",
    "validation_2020_2021_row_count",
    "test_start_date",
    "test_end_date",
    "test_calendar_session_count",
    "test_row_count",
    "test_labeled_row_count",
    "test_positive_count",
    "test_negative_count",
    "test_na_label_count",
    "test_daily_row_count_min",
    "test_daily_row_count_median",
    "test_daily_row_count_max",
    "total_complete_fold_count",
)


class FoldFeasibilityError(ValueError):
    """Raised when the panel cannot be scanned under the D031 contract."""


@dataclass(frozen=True)
class FoldFeasibilityResult:
    candidates: pd.DataFrame
    earliest_feasible_date: str | None
    alternative_dates: tuple[str, ...]
    recommended_first_test_date: str | None
    recommended_total_fold_count: int


def scan_fold_feasibility(
    panel: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    as_of_date: str | pd.Timestamp,
    config: ModelTrainingConfig | None = None,
) -> FoldFeasibilityResult:
    """Scan every global session without fitting or importing LightGBM."""

    settings = config or ModelTrainingConfig()
    required = {
        "security_id",
        "prediction_date",
        "prediction_eligible",
        "label_available_date",
        "label_status",
        "label",
    }
    missing = required.difference(panel.columns)
    if missing:
        raise FoldFeasibilityError(f"training panel fields missing: {sorted(missing)}")
    if panel.duplicated(["security_id", "prediction_date"]).any():
        raise FoldFeasibilityError("duplicate training panel security/date key")
    sessions = _normalize_calendar(calendar, pd.Timestamp(as_of_date).normalize())
    frame = panel.copy()
    frame["prediction_date"] = pd.to_datetime(
        frame["prediction_date"], errors="raise"
    ).dt.normalize()
    frame["label_available_date"] = pd.to_datetime(
        frame["label_available_date"], errors="coerce"
    ).dt.normalize()
    eligible = frame["prediction_eligible"].eq(True)
    labeled = (
        frame["label_status"].eq("LABELED")
        & frame["label"].isin([0, 1])
        & frame["label_available_date"].notna()
    )
    fit_source = frame.loc[eligible & labeled].copy()
    test_source = frame.loc[eligible].copy()
    date_stats = _daily_stats(fit_source, sessions)
    test_stats = _daily_test_stats(test_source, sessions)
    rows: list[dict[str, Any]] = []
    for candidate in sessions:
        base = _empty_candidate(candidate, settings)
        try:
            folds = generate_walk_forward_folds(
                calendar,
                first_test_start_date=candidate,
                as_of_date=as_of_date,
                config=settings,
            )
        except WalkForwardError as exc:
            base["failure_reason"] = str(exc)
            rows.append(base)
            continue
        fold = folds[0]
        fit_dates = _date_range(
            sessions,
            pd.Timestamp(fold.training_start_date),
            pd.Timestamp(fold.training_end_date),
        )
        validation_dates = _date_range(
            sessions,
            pd.Timestamp(fold.validation_start_date),
            pd.Timestamp(fold.validation_end_date),
        )
        test_dates = _date_range(
            sessions,
            pd.Timestamp(fold.test_start_date),
            pd.Timestamp(fold.test_end_date),
        )
        validation_start = pd.Timestamp(fold.validation_start_date)
        test_start = pd.Timestamp(fold.test_start_date)
        # D031 availability is already encoded in label_available_date. Aggregating
        # by prediction date keeps every BIST date wholly in one split.
        fit_stats = _window_stats(
            date_stats.loc[fit_dates],
            available_before=validation_start,
        )
        validation_stats = _window_stats(
            date_stats.loc[validation_dates],
            available_before=test_start,
        )
        test_window = test_stats.loc[test_dates]
        base.update(
            {
                "fit_start_date": fold.training_start_date,
                "fit_end_date": fold.training_end_date,
                "fit_calendar_session_count": fold.fit_calendar_session_count,
                "fit_contract_labeled_session_count": fold.fit_labeled_session_count,
                "fit_purged_session_count": fold.fit_purged_session_count,
                "fit_available_label_session_count": fit_stats["session_count"],
                "fit_row_count": fit_stats["row_count"],
                "fit_positive_count": fit_stats["positive_count"],
                "fit_negative_count": fit_stats["negative_count"],
                "fit_daily_row_count_min": fit_stats["daily_min"],
                "fit_daily_row_count_median": fit_stats["daily_median"],
                "fit_daily_row_count_max": fit_stats["daily_max"],
                "fit_2020_2021_session_count": fit_stats["early_session_count"],
                "fit_2020_2021_row_count": fit_stats["early_row_count"],
                "validation_start_date": fold.validation_start_date,
                "validation_end_date": fold.validation_end_date,
                "validation_calendar_session_count": fold.validation_calendar_session_count,
                "validation_contract_labeled_session_count": fold.validation_labeled_session_count,
                "validation_purged_session_count": fold.validation_purged_session_count,
                "validation_available_label_session_count": validation_stats[
                    "session_count"
                ],
                "validation_row_count": validation_stats["row_count"],
                "validation_positive_count": validation_stats["positive_count"],
                "validation_negative_count": validation_stats["negative_count"],
                "validation_daily_row_count_min": validation_stats["daily_min"],
                "validation_daily_row_count_median": validation_stats["daily_median"],
                "validation_daily_row_count_max": validation_stats["daily_max"],
                "validation_2020_2021_session_count": validation_stats[
                    "early_session_count"
                ],
                "validation_2020_2021_row_count": validation_stats["early_row_count"],
                "test_start_date": fold.test_start_date,
                "test_end_date": fold.test_end_date,
                "test_calendar_session_count": fold.test_calendar_session_count,
                "test_row_count": int(test_window["row_count"].sum()),
                "test_labeled_row_count": int(test_window["labeled_count"].sum()),
                "test_positive_count": int(test_window["positive_count"].sum()),
                "test_negative_count": int(test_window["negative_count"].sum()),
                "test_na_label_count": int(test_window["na_count"].sum()),
                "test_daily_row_count_min": int(test_window["row_count"].min()),
                "test_daily_row_count_median": float(test_window["row_count"].median()),
                "test_daily_row_count_max": int(test_window["row_count"].max()),
                "total_complete_fold_count": len(folds),
            }
        )
        failures = _feasibility_failures(base, settings)
        base["feasible"] = not failures
        base["failure_reason"] = "|".join(failures)
        rows.append(base)
    candidates = pd.DataFrame(rows, columns=FEASIBILITY_COLUMNS)
    feasible = candidates.loc[candidates["feasible"].eq(True)].reset_index(drop=True)
    earliest = (
        str(feasible.iloc[0]["candidate_first_test_date"]) if not feasible.empty else None
    )
    alternatives = _alternatives(feasible)
    recommended = earliest
    total_folds = (
        int(feasible.iloc[0]["total_complete_fold_count"])
        if not feasible.empty
        else 0
    )
    return FoldFeasibilityResult(
        candidates=candidates,
        earliest_feasible_date=earliest,
        alternative_dates=alternatives,
        recommended_first_test_date=recommended,
        recommended_total_fold_count=total_folds,
    )


def write_fold_feasibility_reports(
    panel: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    report_root: Path,
    as_of_date: str | pd.Timestamp,
    config: ModelTrainingConfig | None = None,
) -> dict[str, Path]:
    result = scan_fold_feasibility(
        panel, calendar, as_of_date=as_of_date, config=config
    )
    csv_path = Path(report_root) / "fold_feasibility.csv"
    summary_path = Path(report_root) / "fold_feasibility_summary.md"
    atomic_write_csv(csv_path, result.candidates)
    atomic_write_text(summary_path, render_fold_feasibility_summary(result))
    return {"fold_feasibility": csv_path, "fold_feasibility_summary": summary_path}


def render_fold_feasibility_summary(result: FoldFeasibilityResult) -> str:
    feasible = result.candidates.loc[result.candidates["feasible"].eq(True)]
    selected_dates = [
        value
        for value in (result.earliest_feasible_date, *result.alternative_dates)
        if value is not None
    ]
    selected = feasible.loc[
        feasible["candidate_first_test_date"].isin(selected_dates)
    ]
    lines = [
        "# Fold Feasibility Summary",
        "",
        f"- Teknik olarak mümkün en erken tarih: `{result.earliest_feasible_date or 'YOK'}`",
        "- Daha uzun fit geçmişine sahip alternatifler: "
        + (", ".join(f"`{value}`" for value in result.alternative_dates) or "YOK"),
        f"- Veri üzerinden önerilen sade ilk test tarihi: `{result.recommended_first_test_date or 'YOK'}`",
        f"- Önerilen tarihten üretilecek toplam tam fold: `{result.recommended_total_fold_count}`",
        "- Öneri gerekçesi: bağlayıcı eşikleri geçen en erken tarih, yeni bir minimum row eşiği eklemeden en uzun OOS fold dizisini korur.",
        "- LightGBM eğitimi çalıştırılmadı; bu yalnız veri ve takvim feasibility raporudur.",
        "",
        "## Seçili adayların row ve sınıf dağılımı",
        "",
    ]
    if selected.empty:
        lines.append("Feasible aday bulunamadı.")
    else:
        columns = [
            "candidate_first_test_date",
            "fit_row_count",
            "fit_positive_count",
            "fit_negative_count",
            "validation_row_count",
            "validation_positive_count",
            "validation_negative_count",
            "test_row_count",
            "fit_2020_2021_row_count",
            "validation_2020_2021_row_count",
            "total_complete_fold_count",
        ]
        lines.extend(_markdown_table(selected.loc[:, columns]))
    lines.extend(
        [
            "",
            "## 2020–2021 kapsamı",
            "",
            "Tablodaki `fit_2020_2021_*` ve `validation_2020_2021_*` alanları, erken dönemin ilgili pencereye gerçekten giren kullanılabilir label oturumu ve satır kapsamını verir.",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_calendar(calendar: pd.DataFrame, cutoff: pd.Timestamp) -> list[pd.Timestamp]:
    required = {"session_date", "session_index"}
    if not required.issubset(calendar.columns):
        raise FoldFeasibilityError("global calendar fields missing")
    frame = calendar.loc[:, ["session_date", "session_index"]].copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
    frame["session_index"] = pd.to_numeric(frame["session_index"], errors="raise")
    frame = frame.sort_values("session_index").reset_index(drop=True)
    if frame["session_date"].duplicated().any():
        raise FoldFeasibilityError("duplicate global calendar session")
    if frame["session_index"].tolist() != list(range(len(frame))):
        raise FoldFeasibilityError("global calendar index is not contiguous")
    return frame.loc[frame["session_date"].le(cutoff), "session_date"].tolist()


def _daily_stats(source: pd.DataFrame, sessions: list[pd.Timestamp]) -> pd.DataFrame:
    grouped = source.groupby("prediction_date", sort=True).agg(
        row_count=("security_id", "size"),
        positive_count=("label", lambda values: int(values.eq(1).sum())),
        negative_count=("label", lambda values: int(values.eq(0).sum())),
        label_available_date=("label_available_date", "max"),
    )
    result = grouped.reindex(sessions)
    for column in ("row_count", "positive_count", "negative_count"):
        result[column] = result[column].fillna(0).astype(int)
    return result


def _daily_test_stats(source: pd.DataFrame, sessions: list[pd.Timestamp]) -> pd.DataFrame:
    grouped = source.groupby("prediction_date", sort=True).agg(
        row_count=("security_id", "size"),
        labeled_count=("label_status", lambda values: int(values.eq("LABELED").sum())),
        positive_count=("label", lambda values: int(values.eq(1).sum())),
        negative_count=("label", lambda values: int(values.eq(0).sum())),
        na_count=("label_status", lambda values: int(values.ne("LABELED").sum())),
    )
    return grouped.reindex(sessions, fill_value=0)


def _window_stats(
    daily: pd.DataFrame,
    *,
    available_before: pd.Timestamp,
) -> dict[str, int | float]:
    usable = daily.loc[
        daily["label_available_date"].notna()
        & daily["label_available_date"].lt(available_before)
    ]
    counts = usable["row_count"]
    early = usable.index.to_series().dt.year.isin([2020, 2021])
    return {
        "session_count": int((counts > 0).sum()),
        "row_count": int(usable["row_count"].sum()),
        "positive_count": int(usable["positive_count"].sum()),
        "negative_count": int(usable["negative_count"].sum()),
        "daily_min": int(counts.min()) if len(counts) else 0,
        "daily_median": float(counts.median()) if len(counts) else 0.0,
        "daily_max": int(counts.max()) if len(counts) else 0,
        "early_session_count": int((usable.loc[early, "row_count"] > 0).sum()),
        "early_row_count": int(usable.loc[early, "row_count"].sum()),
    }


def _date_range(
    sessions: list[pd.Timestamp], start: pd.Timestamp, end: pd.Timestamp
) -> list[pd.Timestamp]:
    return [value for value in sessions if start <= value <= end]


def _empty_candidate(
    candidate: pd.Timestamp, settings: ModelTrainingConfig
) -> dict[str, Any]:
    row = {column: 0 for column in FEASIBILITY_COLUMNS}
    row.update(
        {
            "candidate_first_test_date": candidate.date().isoformat(),
            "feasible": False,
            "failure_reason": "",
            "warmup_session_count": settings.minimum_feature_history_sessions - 1,
            "fit_start_date": "",
            "fit_end_date": "",
            "validation_start_date": "",
            "validation_end_date": "",
            "test_start_date": "",
            "test_end_date": "",
        }
    )
    return row


def _feasibility_failures(
    row: Mapping[str, Any], settings: ModelTrainingConfig
) -> list[str]:
    failures: list[str] = []
    if int(row["warmup_session_count"]) != settings.minimum_feature_history_sessions - 1:
        failures.append("WARMUP_INCOMPLETE")
    if int(row["fit_available_label_session_count"]) < settings.minimum_training_sessions:
        failures.append("FIT_LABELED_SESSIONS_BELOW_252")
    if int(row["validation_calendar_session_count"]) != settings.validation_sessions:
        failures.append("VALIDATION_CALENDAR_NOT_60")
    if int(row["validation_available_label_session_count"]) != (
        settings.validation_sessions - settings.label_horizon_sessions
    ):
        failures.append("VALIDATION_AVAILABLE_LABEL_SESSIONS_NOT_57")
    if int(row["test_calendar_session_count"]) != settings.test_sessions:
        failures.append("TEST_CALENDAR_NOT_20")
    if int(row["fit_positive_count"]) == 0 or int(row["fit_negative_count"]) == 0:
        failures.append("FIT_MISSING_BINARY_CLASS")
    if int(row["validation_positive_count"]) == 0 or int(row["validation_negative_count"]) == 0:
        failures.append("VALIDATION_MISSING_BINARY_CLASS")
    if int(row["fit_row_count"]) == 0:
        failures.append("FIT_EMPTY")
    if int(row["validation_row_count"]) == 0:
        failures.append("VALIDATION_EMPTY")
    if int(row["test_row_count"]) == 0:
        failures.append("TEST_EMPTY")
    return failures


def _alternatives(feasible: pd.DataFrame) -> tuple[str, ...]:
    if len(feasible) < 2:
        return ()
    positions = [min(value, len(feasible) - 1) for value in (20, 40, 60)]
    alternatives: list[str] = []
    for position in positions:
        value = str(feasible.iloc[position]["candidate_first_test_date"])
        if value not in alternatives:
            alternatives.append(value)
    return tuple(alternatives)


def _markdown_table(frame: pd.DataFrame) -> list[str]:
    columns = list(map(str, frame.columns))
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for record in frame.to_dict(orient="records"):
        rows.append("| " + " | ".join(str(record[column]) for column in columns) + " |")
    return rows
