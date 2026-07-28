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
from src.data.snapshot_store import SnapshotStore  # noqa: E402
from src.features.catalog import catalog_file_checksum  # noqa: E402
from src.features.pipeline import validate_feature_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a baseline_v1 feature snapshot")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--feature-catalog", type=Path, default=Path("FEATURE_CATALOG.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = replace(MarketDataConfig(), data_root=args.data_root)
    metadata = validate_feature_snapshot(
        SnapshotStore(config),
        args.snapshot_id,
        expected_catalog_checksum=catalog_file_checksum(args.feature_catalog),
    )
    print(
        json.dumps(
            {
                "snapshot_id": metadata.snapshot_id,
                "status": metadata.snapshot_status.value,
                "row_count": metadata.row_count,
                "content_checksum": metadata.content_checksum,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
