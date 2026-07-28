from __future__ import annotations

import json

import pandas as pd

from src.features.catalog import BASELINE_V1_FEATURES
from src.modeling.pipeline import LightGBMWalkForwardPipeline
from src.modeling.registry import ModelRegistry
from tests.modeling_support import fast_training_config, synthetic_dataset


EXPECTED_OOS_COLUMNS = [
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
    "feature_snapshot_id",
    "label_snapshot_id",
]


def test_two_fold_synthetic_pipeline_is_oos_immutable_and_idempotent(tmp_path) -> None:
    dataset, calendar, _, _ = synthetic_dataset(securities=8, sessions=80)
    config = fast_training_config(artifact_root=tmp_path / "models" / "lightgbm")
    pipeline = LightGBMWalkForwardPipeline(
        config,
        registry=ModelRegistry(config.artifact_root),
        code_commit_sha="a" * 40,
    )
    arguments = {
        "as_of_date": calendar.loc[79, "session_date"],
        "first_test_start_date": calendar.loc[60, "session_date"],
        "feature_snapshot_id": "feature-snapshot",
        "feature_snapshot_checksum": "feature-checksum",
        "label_snapshot_id": "label-snapshot",
        "label_snapshot_checksum": "label-checksum",
        "feature_catalog_checksum": "catalog-checksum",
    }

    first = pipeline.run(dataset, calendar, **arguments)
    second = pipeline.run(dataset, calendar, **arguments)

    assert first.artifact.created
    assert not second.artifact.created
    assert first.artifact.experiment_id == second.artifact.experiment_id
    assert len(first.folds) == 2
    assert list(first.oos_predictions.columns) == EXPECTED_OOS_COLUMNS
    assert len(first.oos_predictions) == 2 * 10 * 8
    assert first.oos_predictions["prediction_eligible"].eq(True).all()
    assert first.oos_predictions["probability_up_5pct"].between(0, 1).all()
    assert first.oos_predictions["fold_id"].nunique() == 2
    assert first.oos_predictions["model_version"].nunique() == 2
    assert first.oos_predictions.loc[
        first.oos_predictions["label_status"].eq("NA"), "label"
    ].isna().all()
    assert len(list(config.artifact_root.glob("lgbm_*"))) == 1

    metadata = json.loads(
        (first.artifact.path / "metadata.json").read_text(encoding="utf-8")
    )
    feature_schema = json.loads(
        (first.artifact.path / "feature_schema.json").read_text(encoding="utf-8")
    )
    first_fold_metadata = json.loads(
        (
            first.artifact.path
            / "folds"
            / "fold_001"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["feature_names_in_order"] == list(BASELINE_V1_FEATURES)
    assert metadata["random_seed"] == 42
    assert metadata["training_fingerprint"]
    assert feature_schema["feature_count"] == 32
    assert first_fold_metadata["validation_calendar_session_count"] == 20
    assert first_fold_metadata["validation_labeled_session_count"] == 17
    assert first_fold_metadata["validation_purged_session_count"] == 3
    assert first_fold_metadata["validation_used_session_count"] == 17
    assert first_fold_metadata["fit_calendar_session_count"] == 20
    assert first_fold_metadata["fit_labeled_session_count"] == 17
    assert first_fold_metadata["fit_purged_session_count"] == 3
    assert first_fold_metadata["fit_used_session_count"] == 17
    assert set(first.oos_metrics) == {
        "classification",
        "daily_precision_at_5",
        "precision_at_5_summary",
        "daily_precision_at_10",
        "precision_at_10_summary",
    }

    persisted = pd.read_json(first.artifact.path / "oos_predictions.jsonl", lines=True)
    assert len(persisted) == len(first.oos_predictions)
    assert persisted["security_id"].tolist() == first.oos_predictions["security_id"].tolist()
