"""Run the resumable frozen-universe BIST full-history data chain."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MarketDataConfig  # noqa: E402
from src.data.full_history_pipeline import (  # noqa: E402
    DEFAULT_ACTIVE_UNIVERSE_SNAPSHOT_ID,
    DEFAULT_AS_OF_DATE,
    DEFAULT_COLLECTION_END_DATE,
    DEFAULT_COLLECTION_START_DATE,
    DEFAULT_MASTER_SECURITY_COUNT,
    FullHistoryContext,
    FullHistoryPaths,
    FullHistoryPipeline,
)
from src.data.snapshot_store import SnapshotStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--active-universe-snapshot-id",
        default=DEFAULT_ACTIVE_UNIVERSE_SNAPSHOT_ID,
    )
    parser.add_argument(
        "--universe-version", default="bist_active_universe_v1"
    )
    parser.add_argument(
        "--active-universe-as-of-date",
        type=date.fromisoformat,
        default=DEFAULT_AS_OF_DATE,
    )
    parser.add_argument(
        "--master-security-count", type=int, default=DEFAULT_MASTER_SECURITY_COUNT
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=DEFAULT_COLLECTION_START_DATE,
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=DEFAULT_COLLECTION_END_DATE,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("reports/universe/full_history_collection_manifest_v1.csv"),
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("reference_data/bist_security_ticker_map_v1.csv"),
    )
    parser.add_argument(
        "--active-universe-csv",
        type=Path,
        default=Path("reference_data/bist_active_universe_v1.csv"),
    )
    parser.add_argument(
        "--price-steps",
        type=Path,
        default=Path("reference_data/bist_equity_tick_sizes_v1.csv"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--report-root", type=Path, default=Path("reports/full_history")
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refetch verified COMPLETE raw snapshots instead of resuming them",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate frozen inputs and exit before constructing provider clients",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = FullHistoryContext(
        active_universe_snapshot_id=args.active_universe_snapshot_id,
        universe_version=args.universe_version,
        active_universe_as_of_date=args.active_universe_as_of_date,
        master_security_count=args.master_security_count,
        collection_start_date=args.start_date,
        model_period_start_date=DEFAULT_COLLECTION_START_DATE,
        collection_end_date=args.end_date,
    )
    paths = FullHistoryPaths(
        manifest=args.manifest,
        mapping=args.mapping,
        active_universe_csv=args.active_universe_csv,
        price_steps=args.price_steps,
        report_root=args.report_root,
    )
    config = replace(MarketDataConfig(), data_root=args.data_root)
    store = SnapshotStore(config)
    pipeline = FullHistoryPipeline(
        config, context=context, paths=paths, snapshot_store=store
    )
    if args.preflight_only:
        result = pipeline.preflight()
        print(
            json.dumps(
                {
                    "preflight": "PASS",
                    "active_universe_snapshot_id": result.active_metadata.snapshot_id,
                    "active_universe_checksum": result.active_metadata.content_checksum,
                    "security_count": len(result.universe),
                    "manifest_row_count": len(result.manifest),
                    "mapping_version": result.mapping.version,
                    "mapping_checksum": result.mapping.checksum,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = pipeline.run(refresh=args.refresh)
    print(
        json.dumps(
            {
                "run_status": result.run_status,
                "summary": dict(result.summary),
                "used_security_count": len(result.used_security_ids),
                "excluded_security_count": len(result.excluded_security_ids),
                "reports": {
                    key: str(value) for key, value in result.reports.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.run_status == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
