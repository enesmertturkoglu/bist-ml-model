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
from src.data.active_universe import validate_active_universe_snapshot  # noqa: E402
from src.data.snapshot_store import SnapshotStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an active BIST universe snapshot")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = SnapshotStore(replace(MarketDataConfig(), data_root=args.data_root))
    metadata = validate_active_universe_snapshot(store, args.snapshot_id)
    print(
        json.dumps(
            {
                "snapshot_id": metadata.snapshot_id,
                "content_checksum": metadata.content_checksum,
                "row_count": metadata.row_count,
                "revision_number": metadata.revision_number,
                "as_of_date": metadata.revision_context["as_of_date"],
                "universe_version": metadata.request_parameters["universe_version"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
