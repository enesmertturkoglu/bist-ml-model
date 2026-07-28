"""End-to-end LightGBM walk-forward training without live prediction/backtest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import ModelTrainingConfig
from src.features.catalog import BASELINE_V1_FEATURES
from src.modeling.dataset import TrainingDataset, model_matrix
from src.modeling.lightgbm_training import fit_lightgbm_fold, positive_class_probability
from src.modeling.metrics import (
    classification_metrics,
    daily_precision_at_k,
    deterministic_daily_rank,
)
from src.modeling.registry import (
    FoldArtifact,
    ModelArtifactResult,
    ModelRegistry,
    training_fingerprint,
)
from src.modeling.walk_forward import (
    WalkForwardFold,
    generate_walk_forward_folds,
    split_fold_rows,
    validate_fold_classes,
)


class TrainingPipelineError(RuntimeError):
    """Raised when an experiment cannot satisfy the binding training contract."""


@dataclass(frozen=True)
class TrainingRunResult:
    artifact: ModelArtifactResult
    folds: tuple[WalkForwardFold, ...]
    oos_predictions: pd.DataFrame
    fold_metrics: tuple[dict[str, Any], ...]
    oos_metrics: dict[str, Any]


class LightGBMWalkForwardPipeline:
    """Train one fresh LGBMClassifier per explicit 20-session test block."""

    def __init__(
        self,
        config: ModelTrainingConfig | None = None,
        *,
        registry: ModelRegistry | None = None,
        code_commit_sha: str = "unknown",
    ) -> None:
        self.config = config or ModelTrainingConfig()
        self.registry = registry or ModelRegistry(self.config.artifact_root)
        self.code_commit_sha = code_commit_sha or "unknown"

    def run(
        self,
        dataset: TrainingDataset,
        calendar: pd.DataFrame,
        *,
        as_of_date: str | pd.Timestamp,
        first_test_start_date: str | pd.Timestamp,
        feature_snapshot_id: str,
        feature_snapshot_checksum: str,
        label_snapshot_id: str,
        label_snapshot_checksum: str,
        active_universe_snapshot_id: str,
        active_universe_snapshot_checksum: str,
        active_universe_version: str,
        active_universe_as_of_date: str,
        feature_catalog_checksum: str,
    ) -> TrainingRunResult:
        folds = generate_walk_forward_folds(
            calendar,
            first_test_start_date=first_test_start_date,
            as_of_date=as_of_date,
            config=self.config,
        )
        fold_definitions = [fold.to_dict() for fold in folds]
        fingerprint = training_fingerprint(
            code_commit_sha=self.code_commit_sha,
            config_checksum=self.config.checksum(),
            feature_snapshot_checksum=feature_snapshot_checksum,
            label_snapshot_checksum=label_snapshot_checksum,
            active_universe_snapshot_id=active_universe_snapshot_id,
            active_universe_snapshot_checksum=active_universe_snapshot_checksum,
            active_universe_version=active_universe_version,
            active_universe_as_of_date=active_universe_as_of_date,
            feature_catalog_checksum=feature_catalog_checksum,
            fold_definitions=fold_definitions,
            random_seed=self.config.random_state,
        )
        existing = self.registry.find_by_fingerprint(fingerprint)
        if existing is not None:
            predictions = pd.read_json(
                existing.path / "oos_predictions.jsonl", lines=True
            )
            stored_fold_metrics = json.loads(
                (existing.path / "fold_metrics.json").read_text(encoding="utf-8")
            )
            oos_metrics = json.loads(
                (existing.path / "oos_metrics.json").read_text(encoding="utf-8")
            )
            return TrainingRunResult(
                existing,
                folds,
                predictions,
                tuple(stored_fold_metrics),
                oos_metrics,
            )

        experiment_id = self.registry.experiment_id_for(fingerprint)
        fold_artifacts: list[FoldArtifact] = []
        fold_metrics: list[dict[str, Any]] = []
        prediction_frames: list[pd.DataFrame] = []
        last_fit = None
        last_validation = None
        for fold in folds:
            rows = split_fold_rows(dataset.panel, fold)
            validate_fold_classes(rows)
            fitted = fit_lightgbm_fold(rows.fit, rows.validation, config=self.config)
            probability = positive_class_probability(fitted.model, model_matrix(rows.test))
            model_version = f"{experiment_id}_{fold.fold_id}"
            scored = rows.test.copy()
            scored["model_version"] = model_version
            scored["fold_id"] = fold.fold_id
            scored["probability_up_5pct"] = probability
            scored["predicted_class_default_threshold"] = (
                scored["probability_up_5pct"].ge(self.config.classification_threshold).astype(int)
            )
            unavailable_at_cutoff = (
                scored["label_available_date"].isna()
                | scored["label_available_date"].gt(pd.Timestamp(as_of_date).normalize())
            )
            scored.loc[unavailable_at_cutoff, "label"] = pd.NA
            scored.loc[unavailable_at_cutoff, "label_status"] = "NA"
            scored = deterministic_daily_rank(scored)
            oos = self._oos_projection(
                scored,
                feature_snapshot_id=feature_snapshot_id,
                label_snapshot_id=label_snapshot_id,
            )
            valid = (
                oos["label_status"].eq("LABELED")
                & oos["label"].isin([0, 1])
            )
            test_metrics = classification_metrics(
                oos.loc[valid, "label"].astype(int),
                oos.loc[valid, "probability_up_5pct"],
                threshold=self.config.classification_threshold,
                calibration_bins=self.config.calibration_bins,
            )
            p5_detail, p5_summary = daily_precision_at_k(oos, k=5)
            p10_detail, p10_summary = daily_precision_at_k(oos, k=10)
            metrics = {
                "fold_id": fold.fold_id,
                "model_version": model_version,
                "fit_used_session_count": int(rows.fit["prediction_date"].nunique()),
                "validation_used_session_count": int(
                    rows.validation["prediction_date"].nunique()
                ),
                "test_scored_session_count": int(rows.test["prediction_date"].nunique()),
                "fit_row_count": int(len(rows.fit)),
                "validation_row_count": int(len(rows.validation)),
                "test_scored_row_count": int(len(rows.test)),
                "fit_positive_class_rate": float(rows.fit["label"].astype(int).mean()),
                "validation_positive_class_rate": float(rows.validation["label"].astype(int).mean()),
                "test_positive_class_rate": test_metrics["positive_class_rate"],
                "best_iteration": fitted.best_iteration,
                "training_metrics": fitted.training_metrics,
                "validation_metrics": fitted.validation_metrics,
                "test_metrics": test_metrics,
                "daily_precision_at_5": p5_detail.to_dict(orient="records"),
                "precision_at_5_summary": p5_summary,
                "daily_precision_at_10": p10_detail.to_dict(orient="records"),
                "precision_at_10_summary": p10_summary,
            }
            fold_metrics.append(metrics)
            fold_metadata = {
                **fold.to_dict(),
                **{key: metrics[key] for key in (
                    "fold_id",
                    "model_version",
                    "fit_used_session_count",
                    "validation_used_session_count",
                    "test_scored_session_count",
                    "fit_row_count",
                    "validation_row_count",
                    "test_scored_row_count",
                    "fit_positive_class_rate",
                    "validation_positive_class_rate",
                    "best_iteration",
                    "training_metrics",
                    "validation_metrics",
                    "test_metrics",
                )},
                "feature_snapshot_id": feature_snapshot_id,
                "feature_snapshot_checksum": feature_snapshot_checksum,
                "label_snapshot_id": label_snapshot_id,
                "label_snapshot_checksum": label_snapshot_checksum,
                "active_universe_snapshot_id": active_universe_snapshot_id,
                "active_universe_snapshot_checksum": active_universe_snapshot_checksum,
                "active_universe_version": active_universe_version,
                "active_universe_as_of_date": active_universe_as_of_date,
                "feature_names_in_order": list(BASELINE_V1_FEATURES),
                "lightgbm_parameters": self.config.lightgbm_parameters,
                "random_seed": self.config.random_state,
                "code_commit_sha": self.code_commit_sha,
                "training_fingerprint": fingerprint,
            }
            fold_artifacts.append(FoldArtifact(fold.fold_id, fitted.model, fold_metadata))
            prediction_frames.append(oos)
            last_fit = (rows.fit, fitted.training_metrics)
            last_validation = (rows.validation, fitted.validation_metrics)

        combined = pd.concat(prediction_frames, ignore_index=True)
        combined = combined.sort_values(
            ["prediction_date", "fold_id", "daily_rank"]
        ).reset_index(drop=True)
        valid_combined = combined["label_status"].eq("LABELED") & combined["label"].isin([0, 1])
        combined_metrics = classification_metrics(
            combined.loc[valid_combined, "label"].astype(int),
            combined.loc[valid_combined, "probability_up_5pct"],
            threshold=self.config.classification_threshold,
            calibration_bins=self.config.calibration_bins,
        )
        p5_detail, p5_summary = daily_precision_at_k(combined, k=5)
        p10_detail, p10_summary = daily_precision_at_k(combined, k=10)
        oos_metrics = {
            "classification": combined_metrics,
            "daily_precision_at_5": p5_detail.to_dict(orient="records"),
            "precision_at_5_summary": p5_summary,
            "daily_precision_at_10": p10_detail.to_dict(orient="records"),
            "precision_at_10_summary": p10_summary,
        }
        assert last_fit is not None and last_validation is not None
        fit_frame, training_metrics = last_fit
        validation_frame, validation_metrics = last_validation
        latest_label_date = dataset.model_rows["label_available_date"].max()
        metadata = {
            "model_version": f"{experiment_id}_{folds[-1].fold_id}",
            "training_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "as_of_date": pd.Timestamp(as_of_date).date().isoformat(),
            "training_start_date": folds[-1].training_start_date,
            "training_end_date": folds[-1].training_end_date,
            "validation_start_date": folds[-1].validation_start_date,
            "validation_end_date": folds[-1].validation_end_date,
            "latest_available_label_date": (
                pd.Timestamp(latest_label_date).date().isoformat()
                if pd.notna(latest_label_date)
                else None
            ),
            "feature_snapshot_id": feature_snapshot_id,
            "feature_snapshot_checksum": feature_snapshot_checksum,
            "label_snapshot_id": label_snapshot_id,
            "label_snapshot_checksum": label_snapshot_checksum,
            "active_universe_snapshot_id": active_universe_snapshot_id,
            "active_universe_snapshot_checksum": active_universe_snapshot_checksum,
            "active_universe_version": active_universe_version,
            "active_universe_as_of_date": active_universe_as_of_date,
            "feature_catalog_checksum": feature_catalog_checksum,
            "feature_names_in_order": list(BASELINE_V1_FEATURES),
            "lightgbm_parameters": self.config.lightgbm_parameters,
            "random_seed": self.config.random_state,
            "code_commit_sha": self.code_commit_sha,
            "training_row_count": int(len(fit_frame)),
            "validation_row_count": int(len(validation_frame)),
            "positive_class_rate": float(fit_frame["label"].astype(int).mean()),
            "fold_definitions": fold_definitions,
            "training_metrics": training_metrics,
            "validation_metrics": validation_metrics,
            "out_of_sample_metrics": oos_metrics,
            "training_fingerprint": fingerprint,
        }
        artifact = self.registry.write_experiment(
            fingerprint=fingerprint,
            metadata=metadata,
            config={
                "training_config": asdict(self.config),
                "training_config_checksum": self.config.checksum(),
            },
            feature_schema={
                "feature_set_id": "baseline_v1",
                "feature_count": len(BASELINE_V1_FEATURES),
                "feature_names_in_order": list(BASELINE_V1_FEATURES),
                "feature_catalog_checksum": feature_catalog_checksum,
            },
            fold_definitions=fold_definitions,
            fold_metrics=fold_metrics,
            oos_metrics=oos_metrics,
            oos_predictions=combined,
            fold_artifacts=fold_artifacts,
        )
        return TrainingRunResult(
            artifact,
            folds,
            combined,
            tuple(fold_metrics),
            oos_metrics,
        )

    @staticmethod
    def _oos_projection(
        frame: pd.DataFrame,
        *,
        feature_snapshot_id: str,
        label_snapshot_id: str,
    ) -> pd.DataFrame:
        result = frame.copy()
        if "observed_ticker" not in result.columns:
            result["observed_ticker"] = pd.NA
        required = [
            "security_id",
            "observed_ticker",
            "prediction_date",
            "model_version",
            "fold_id",
            "probability_up_5pct",
            "predicted_class_default_threshold",
            "daily_rank",
            "prediction_eligible",
            "prediction_exclusion_reason",
            "label",
            "label_status",
        ]
        missing = set(required).difference(result.columns)
        if missing:
            raise TrainingPipelineError(f"OOS fields missing: {sorted(missing)}")
        result["feature_snapshot_id"] = feature_snapshot_id
        result["label_snapshot_id"] = label_snapshot_id
        return result.loc[
            :,
            [*required, "feature_snapshot_id", "label_snapshot_id"],
        ]
