"""Immutable file-based LightGBM experiment registry and fingerprinting."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class ModelRegistryError(RuntimeError):
    """Raised when an immutable model artifact cannot be resolved or committed."""


@dataclass(frozen=True)
class FoldArtifact:
    fold_id: str
    model: Any
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ModelArtifactResult:
    experiment_id: str
    path: Path
    metadata: Mapping[str, Any]
    created: bool


def _json_ready(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, np.generic):
        return _json_ready(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value) if not isinstance(value, (str, bytes)) else False:
        return None
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def training_fingerprint(
    *,
    code_commit_sha: str,
    config_checksum: str,
    feature_snapshot_checksum: str,
    label_snapshot_checksum: str,
    active_universe_snapshot_id: str,
    active_universe_snapshot_checksum: str,
    active_universe_version: str,
    active_universe_as_of_date: str,
    feature_catalog_checksum: str,
    fold_definitions: Sequence[Mapping[str, Any]],
    random_seed: int,
    algorithm: str = "sha256",
) -> str:
    payload = {
        "code_commit_sha": code_commit_sha,
        "config_checksum": config_checksum,
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "label_snapshot_checksum": label_snapshot_checksum,
        "active_universe_snapshot_id": active_universe_snapshot_id,
        "active_universe_snapshot_checksum": active_universe_snapshot_checksum,
        "active_universe_version": active_universe_version,
        "active_universe_as_of_date": active_universe_as_of_date,
        "feature_catalog_checksum": feature_catalog_checksum,
        "fold_definitions": list(fold_definitions),
        "random_seed": int(random_seed),
    }
    return hashlib.new(algorithm, canonical_json(payload).encode("utf-8")).hexdigest()


class ModelRegistry:
    """Commit a complete experiment directory once, then return it idempotently."""

    REQUIRED_FILES = (
        "metadata.json",
        "config.json",
        "feature_schema.json",
        "fold_definitions.json",
        "fold_metrics.json",
        "oos_metrics.json",
        "oos_predictions.jsonl",
    )

    def __init__(self, root: str | Path = Path("models/lightgbm")) -> None:
        self.root = Path(root)

    @staticmethod
    def experiment_id_for(fingerprint: str) -> str:
        return f"lgbm_{fingerprint[:16]}"

    def find_by_fingerprint(self, fingerprint: str) -> ModelArtifactResult | None:
        if not self.root.exists():
            return None
        matches: list[ModelArtifactResult] = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.name.startswith(".artifact-tmp-"):
                continue
            metadata_path = directory / "metadata.json"
            if not metadata_path.is_file():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("training_fingerprint") == fingerprint:
                self._verify_complete(directory, metadata)
                matches.append(
                    ModelArtifactResult(directory.name, directory, metadata, False)
                )
        if len(matches) > 1:
            raise ModelRegistryError("multiple experiments have the same fingerprint")
        return matches[0] if matches else None

    def write_experiment(
        self,
        *,
        fingerprint: str,
        metadata: Mapping[str, Any],
        config: Mapping[str, Any],
        feature_schema: Mapping[str, Any],
        fold_definitions: Sequence[Mapping[str, Any]],
        fold_metrics: Sequence[Mapping[str, Any]],
        oos_metrics: Mapping[str, Any],
        oos_predictions: pd.DataFrame,
        fold_artifacts: Sequence[FoldArtifact],
    ) -> ModelArtifactResult:
        existing = self.find_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        experiment_id = self.experiment_id_for(fingerprint)
        complete_metadata = dict(metadata)
        complete_metadata["experiment_id"] = experiment_id
        complete_metadata["training_fingerprint"] = fingerprint
        final_directory = self.root / experiment_id
        self.root.mkdir(parents=True, exist_ok=True)
        if final_directory.exists():
            raise ModelRegistryError(
                f"immutable experiment path already exists: {final_directory}"
            )
        temporary = self.root / f".artifact-tmp-{secrets.token_hex(8)}"
        temporary.mkdir()
        committed = False
        try:
            self._write_json(temporary / "metadata.json", complete_metadata)
            self._write_json(temporary / "config.json", config)
            self._write_json(temporary / "feature_schema.json", feature_schema)
            self._write_json(temporary / "fold_definitions.json", list(fold_definitions))
            self._write_json(temporary / "fold_metrics.json", list(fold_metrics))
            self._write_json(temporary / "oos_metrics.json", oos_metrics)
            self._write_jsonl(temporary / "oos_predictions.jsonl", oos_predictions)
            folds_root = temporary / "folds"
            folds_root.mkdir()
            for artifact in fold_artifacts:
                fold_directory = folds_root / artifact.fold_id
                fold_directory.mkdir()
                booster = getattr(artifact.model, "booster_", None)
                if booster is None or not hasattr(booster, "save_model"):
                    raise ModelRegistryError("fold model has no LightGBM booster_ to save")
                booster.save_model(str(fold_directory / "model.txt"))
                self._write_json(fold_directory / "metadata.json", artifact.metadata)
            self._replace_path(temporary, final_directory)
            committed = True
            self._verify_complete(final_directory, complete_metadata)
        finally:
            if not committed and temporary.exists():
                shutil.rmtree(temporary)
        return ModelArtifactResult(
            experiment_id,
            final_directory,
            _json_ready(complete_metadata),
            True,
        )

    def _verify_complete(self, directory: Path, metadata: Mapping[str, Any]) -> None:
        missing = [name for name in self.REQUIRED_FILES if not (directory / name).is_file()]
        if missing:
            raise ModelRegistryError(
                f"experiment {directory.name} is incomplete: {missing}"
            )
        if metadata.get("experiment_id") != directory.name:
            raise ModelRegistryError("experiment metadata/path identity mismatch")
        definitions = json.loads(
            (directory / "fold_definitions.json").read_text(encoding="utf-8")
        )
        for fold in definitions:
            fold_id = str(fold["fold_id"])
            fold_directory = directory / "folds" / fold_id
            if not (fold_directory / "model.txt").is_file() or not (
                fold_directory / "metadata.json"
            ).is_file():
                raise ModelRegistryError(f"missing immutable fold artifact: {fold_id}")

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        payload = json.dumps(
            _json_ready(value), ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"
        path.write_text(payload, encoding="utf-8", newline="\n")

    @staticmethod
    def _write_jsonl(path: Path, frame: pd.DataFrame) -> None:
        records = frame.to_dict(orient="records")
        payload = "".join(canonical_json(record) + "\n" for record in records)
        path.write_text(payload, encoding="utf-8", newline="\n")

    @staticmethod
    def _replace_path(source: Path, destination: Path) -> None:
        for attempt in range(5):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
