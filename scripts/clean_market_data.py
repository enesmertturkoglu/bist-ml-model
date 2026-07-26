"""Create a verified D022/D023 clean snapshot and quality report."""

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
from src.data.cleaning_pipeline import (  # noqa: E402
    CleaningSnapshotSet,
    MarketDataCleaningPipeline,
)
from src.data.collectors import current_code_commit_sha  # noqa: E402
from src.data.price_limits import PriceStepTable  # noqa: E402
from src.data.security_identity import TickerMapping  # noqa: E402


def _snapshot_set(value: str) -> CleaningSnapshotSet:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4 or any(not part for part in parts):
        raise argparse.ArgumentTypeError(
            "snapshot set must be TICKER,ISYATIRIM_RAW_ID,YFINANCE_RAW_ID,YFINANCE_NOMINAL_ID"
        )
    return CleaningSnapshotSet(parts[0].upper(), parts[1], parts[2], parts[3])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-set",
        action="append",
        required=True,
        type=_snapshot_set,
        help="repeatable TICKER,IS_RAW_ID,YF_RAW_ID,YF_NOMINAL_ID input",
    )
    parser.add_argument(
        "--price-step-table",
        type=Path,
        help=(
            "versioned official tick-size CSV; defaults to the centrally configured "
            "BIST equity reference file"
        ),
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--security-identity-snapshot-id")
    parser.add_argument(
        "--ticker-mapping",
        type=Path,
        default=PROJECT_ROOT / MarketDataConfig().security_ticker_mapping_path,
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("reports/data_cleaning")
    )
    parser.add_argument("--exception-limit", type=int, default=20)
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = replace(MarketDataConfig(), data_root=args.data_root)
    reference_path = (
        args.price_step_table
        if args.price_step_table is not None
        else PROJECT_ROOT / config.tick_size_reference_path
    )
    price_steps = PriceStepTable.from_csv(reference_path)
    mapping = (
        TickerMapping.from_csv(
            args.ticker_mapping,
            checksum_algorithm=config.checksum_algorithm,
        )
        if args.security_identity_snapshot_id is not None
        else None
    )
    pipeline = MarketDataCleaningPipeline(
        config,
        code_commit_sha=current_code_commit_sha(PROJECT_ROOT),
    )
    result = pipeline.run(
        args.snapshot_set,
        price_steps,
        exception_limit=args.exception_limit,
        security_identity_snapshot_id=args.security_identity_snapshot_id,
        ticker_mapping=mapping,
    )
    args.report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.report_dir / "cleaning_summary.json"
    exceptions_path = args.report_dir / "cleaning_exception_examples.csv"
    summary_payload = {
        "clean_snapshot_id": result.snapshot.metadata.snapshot_id,
        "clean_snapshot_created": result.snapshot.created,
        "clean_snapshot_checksum": result.snapshot.metadata.content_checksum,
        "summary": result.summary,
    }
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    result.exception_examples.to_csv(exceptions_path, index=False)
    print(json.dumps(summary_payload, ensure_ascii=False, sort_keys=True))
    print(f"tick_size_reference={reference_path}")
    print(f"summary_report={summary_path}")
    print(f"exception_report={exceptions_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
