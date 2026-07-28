from __future__ import annotations

import json

import pandas as pd

from src.modeling.registry import (
    FoldArtifact,
    ModelRegistry,
    training_fingerprint,
)


class _Booster:
    def __init__(self, text: str) -> None:
        self.text = text

    def save_model(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.text)


class _Model:
    def __init__(self, text: str) -> None:
        self.booster_ = _Booster(text)


def _fingerprint(seed: int = 42) -> str:
    return training_fingerprint(
        code_commit_sha="a" * 40,
        config_checksum="config",
        feature_snapshot_checksum="feature",
        label_snapshot_checksum="label",
        feature_catalog_checksum="catalog",
        fold_definitions=[{"fold_id": "fold_001"}],
        random_seed=seed,
    )


def _write(registry: ModelRegistry, fingerprint: str, text: str = "model"):
    return registry.write_experiment(
        fingerprint=fingerprint,
        metadata={"model_version": "pending"},
        config={"seed": 42},
        feature_schema={"feature_count": 32},
        fold_definitions=[{"fold_id": "fold_001"}],
        fold_metrics=[{"fold_id": "fold_001", "accuracy": 0.5}],
        oos_metrics={"accuracy": 0.5},
        oos_predictions=pd.DataFrame(
            {"security_id": ["SEC_A"], "probability_up_5pct": [0.6]}
        ),
        fold_artifacts=[FoldArtifact("fold_001", _Model(text), {"fold_id": "fold_001"})],
    )


def test_registry_writes_required_immutable_artifact_tree(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "models" / "lightgbm")
    result = _write(registry, _fingerprint())

    assert result.created
    assert all((result.path / name).is_file() for name in registry.REQUIRED_FILES)
    assert (result.path / "folds" / "fold_001" / "model.txt").read_text() == "model"
    metadata = json.loads((result.path / "metadata.json").read_text())
    assert metadata["training_fingerprint"] == _fingerprint()


def test_same_fingerprint_is_idempotent_without_new_directory(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "models" / "lightgbm")
    first = _write(registry, _fingerprint())
    second = _write(registry, _fingerprint(), text="different")

    assert first.experiment_id == second.experiment_id
    assert not second.created
    assert len([path for path in registry.root.iterdir() if not path.name.startswith(".")]) == 1
    assert (first.path / "folds" / "fold_001" / "model.txt").read_text() == "model"


def test_changed_fingerprint_preserves_old_artifact(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "models" / "lightgbm")
    first = _write(registry, _fingerprint(42), text="old")
    second = _write(registry, _fingerprint(43), text="new")

    assert first.path != second.path
    assert (first.path / "folds" / "fold_001" / "model.txt").read_text() == "old"
    assert (second.path / "folds" / "fold_001" / "model.txt").read_text() == "new"


def test_fingerprint_binds_seed_and_fold_definitions() -> None:
    assert _fingerprint(42) == _fingerprint(42)
    assert _fingerprint(42) != _fingerprint(43)
