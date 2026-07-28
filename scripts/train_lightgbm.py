from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MarketDataConfig  # noqa: E402
from src.data.collectors import current_code_commit_sha  # noqa: E402
from src.data.snapshot_store import SnapshotStore  # noqa: E402
from src.features.catalog import catalog_file_checksum  # noqa: E402
from src.modeling.dataset import build_training_dataset  # noqa: E402
from src.modeling.pipeline import LightGBMWalkForwardPipeline  # noqa: E402
from src.modeling.prediction_universe import PredictionUniverseInputAssembler  # noqa: E402
from src.modeling.registry import ModelRegistry  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train immutable LightGBM walk-forward fold artifacts"
    )
    parser.add_argument("--yfinance-raw-snapshot-id", action="append", required=True)
    parser.add_argument("--isyatirim-raw-snapshot-id", action="append", required=True)
    parser.add_argument("--identity-snapshot-id", required=True)
    parser.add_argument("--feature-snapshot-id", required=True)
    parser.add_argument("--label-snapshot-id", required=True)
    parser.add_argument("--xu100-snapshot-id", required=True)
    parser.add_argument("--calendar-snapshot-id", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--first-test-start-date", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--models-root", type=Path, default=Path("models/lightgbm"))
    parser.add_argument("--feature-catalog", type=Path, default=Path("FEATURE_CATALOG.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base = MarketDataConfig()
    training = replace(base.training, artifact_root=args.models_root)
    config = replace(base, data_root=args.data_root, training=training)
    store = SnapshotStore(config)
    assembly = PredictionUniverseInputAssembler(
        store, catalog_path=args.feature_catalog
    ).assemble(
        yfinance_raw_snapshot_ids=args.yfinance_raw_snapshot_id,
        isyatirim_raw_snapshot_ids=args.isyatirim_raw_snapshot_id,
        identity_snapshot_id=args.identity_snapshot_id,
        feature_snapshot_id=args.feature_snapshot_id,
        xu100_snapshot_id=args.xu100_snapshot_id,
        calendar_snapshot_id=args.calendar_snapshot_id,
        minimum_history_sessions=training.minimum_feature_history_sessions,
    )
    label_meta = store.get_snapshot(args.label_snapshot_id)
    if not store.is_usable(label_meta) or (
        label_meta.source,
        label_meta.dataset_type,
        label_meta.layer,
    ) != ("labels", config.label.label_dataset_type, "derived"):
        raise RuntimeError("label snapshot is not verified labels/three_day_target/derived")
    labels = store.read_dataframe(label_meta)
    dataset = build_training_dataset(
        assembly.universe,
        assembly.features,
        labels,
        assembly.calendar,
        as_of_date=args.as_of_date,
        feature_snapshot_id=args.feature_snapshot_id,
        label_snapshot_id=args.label_snapshot_id,
    )
    feature_meta = store.get_snapshot(args.feature_snapshot_id)
    result = LightGBMWalkForwardPipeline(
        training,
        registry=ModelRegistry(args.models_root),
        code_commit_sha=current_code_commit_sha(),
    ).run(
        dataset,
        assembly.calendar,
        as_of_date=args.as_of_date,
        first_test_start_date=args.first_test_start_date,
        feature_snapshot_id=args.feature_snapshot_id,
        feature_snapshot_checksum=feature_meta.content_checksum,
        label_snapshot_id=args.label_snapshot_id,
        label_snapshot_checksum=label_meta.content_checksum,
        feature_catalog_checksum=catalog_file_checksum(args.feature_catalog),
    )
    print(
        json.dumps(
            {
                "experiment_id": result.artifact.experiment_id,
                "artifact_path": str(result.artifact.path),
                "created": result.artifact.created,
                "fold_count": len(result.folds),
                "oos_row_count": len(result.oos_predictions),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
