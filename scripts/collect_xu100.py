from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MarketDataConfig  # noqa: E402
from src.data.snapshot_store import SnapshotStore  # noqa: E402
from src.data.xu100_pipeline import (
    Xu100Pipeline,
    cross_check_end_fields,
    cross_check_yfinance,
)  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and validate independent XU100 history")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--global-calendar-snapshot-id", required=True)
    parser.add_argument("--isyatirim-stock-snapshot-id", action="append", default=[])
    parser.add_argument("--skip-yfinance-cross-check", action="store_true")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = replace(MarketDataConfig(), data_root=args.data_root)
    store = SnapshotStore(config)
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    result = Xu100Pipeline(config, snapshot_store=store).run(
        start,
        end,
        global_calendar_snapshot_id=args.global_calendar_snapshot_id,
    )
    validated = store.read_dataframe(result.validated_snapshot)
    report: dict[str, object] = {
        "raw_snapshot_id": result.raw_snapshot.snapshot_id,
        "validated_snapshot_id": result.validated_snapshot.snapshot_id,
        "timestamp_validation": asdict(result.validation_report),
    }
    if args.isyatirim_stock_snapshot_id:
        frames = [store.read_dataframe(value) for value in args.isyatirim_stock_snapshot_id]
        report["end_cross_check"] = cross_check_end_fields(frames, validated)
    if not args.skip_yfinance_cross_check:
        import yfinance as yf

        yf_frame = yf.download(
            "XU100.IS",
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=False,
            progress=False,
        )
        if getattr(yf_frame.columns, "nlevels", 1) > 1:
            yf_frame.columns = yf_frame.columns.get_level_values(0)
        report["yfinance_cross_check"] = cross_check_yfinance(yf_frame, validated)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
