from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MarketDataConfig  # noqa: E402
from src.data.active_universe import (  # noqa: E402
    build_history_collection_manifest,
    validate_active_universe_snapshot,
    write_csv_deterministic,
)
from src.data.security_identity import TickerMapping  # noqa: E402
from src.data.snapshot_store import SnapshotStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan full-history provider requests for the active BIST universe"
    )
    parser.add_argument("--active-universe-snapshot-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/universe/full_history_collection_manifest_v1.csv"),
    )
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=Path("reference_data/bist_security_ticker_map_v1.csv"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = SnapshotStore(replace(MarketDataConfig(), data_root=args.data_root))
    metadata = validate_active_universe_snapshot(
        store, args.active_universe_snapshot_id
    )
    universe = store.read_dataframe(metadata)
    mapping = TickerMapping.from_csv(args.mapping_file)
    manifest = build_history_collection_manifest(
        universe,
        mapping,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    checksum = write_csv_deterministic(manifest, args.output)
    print(
        json.dumps(
            {
                "active_universe_snapshot_id": metadata.snapshot_id,
                "row_count": len(manifest),
                "output": str(args.output),
                "checksum": checksum,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
