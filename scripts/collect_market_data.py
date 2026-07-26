"""Collect İş Yatırım and yFinance data into immutable snapshots."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MarketDataConfig  # noqa: E402
from src.data.collectors import MarketDataCollector  # noqa: E402


def parse_args() -> argparse.Namespace:
    defaults = MarketDataConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tickers",
        nargs="+",
        help="BİST tickers without the yFinance .IS suffix",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=defaults.warmup_start_date or defaults.model_start_date,
        help=(
            "Inclusive collection start date (YYYY-MM-DD). Defaults to the "
            "configured warm-up start, or the 2020-03-13 model start while "
            "the warm-up horizon remains undecided."
        ),
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Inclusive collection end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=defaults.data_root,
        help="Root containing raw, derived and manifest layers",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.start_date > args.end_date:
        raise SystemExit("--start-date must be on or before --end-date")
    config = replace(MarketDataConfig(), data_root=args.data_root)
    collector = MarketDataCollector(config)
    results = collector.collect_many(args.tickers, args.start_date, args.end_date)
    for ticker_result in results:
        print(f"{ticker_result.ticker}: complete={ticker_result.complete}")
        for source_result in ticker_result.source_results:
            snapshots = (source_result.raw_snapshot, *source_result.derived_snapshots)
            for snapshot in snapshots:
                print(
                    "  "
                    f"source={snapshot.source} layer={snapshot.layer} "
                    f"dataset={snapshot.dataset_type} status={snapshot.snapshot_status.value} "
                    f"revision={snapshot.revision_number} id={snapshot.snapshot_id}"
                )
    return 0 if all(item.complete for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
