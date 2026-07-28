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
from src.data.calendar_pipeline import GlobalCalendarPipeline  # noqa: E402
from src.data.snapshot_store import SnapshotStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build verified global BIST session calendar")
    parser.add_argument("--isyatirim-raw-snapshot-id", action="append", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = replace(MarketDataConfig(), data_root=args.data_root)
    result = GlobalCalendarPipeline(SnapshotStore(config)).run(
        args.isyatirim_raw_snapshot_id
    )
    report = {
        "snapshot_id": result.snapshot.snapshot_id,
        "content_checksum": result.snapshot.content_checksum,
        "source_security_count": result.source_security_count,
        "session_count": result.session_count,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
