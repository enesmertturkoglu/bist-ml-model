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
from src.features.pipeline import BaselineFeaturePipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate verified baseline_v1 feature snapshot")
    parser.add_argument("--yfinance-raw-snapshot-id", action="append", required=True)
    parser.add_argument("--isyatirim-raw-snapshot-id", action="append", required=True)
    parser.add_argument("--identity-snapshot-id", required=True)
    parser.add_argument("--xu100-snapshot-id", required=True)
    parser.add_argument("--calendar-snapshot-id", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--quality-report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = replace(MarketDataConfig(), data_root=args.data_root)
    result = BaselineFeaturePipeline(
        config, snapshot_store=SnapshotStore(config)
    ).run(
        yfinance_raw_snapshot_ids=args.yfinance_raw_snapshot_id,
        isyatirim_raw_snapshot_ids=args.isyatirim_raw_snapshot_id,
        identity_snapshot_id=args.identity_snapshot_id,
        xu100_snapshot_id=args.xu100_snapshot_id,
        calendar_snapshot_id=args.calendar_snapshot_id,
    )
    if args.quality_report:
        args.quality_report.parent.mkdir(parents=True, exist_ok=True)
        result.quality_summary.to_csv(args.quality_report, index=False)
    print(
        json.dumps(
            {
                "snapshot_id": result.snapshot.snapshot_id,
                "content_checksum": result.snapshot.content_checksum,
                "row_count": len(result.frame),
                "feature_count": 32,
                "quality_report": str(args.quality_report) if args.quality_report else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
