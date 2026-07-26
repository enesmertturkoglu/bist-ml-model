"""Create an immutable three-BIST-day target-label snapshot and report."""

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
from src.data.label_pipeline import LabelGenerationPipeline  # noqa: E402
from src.data.price_limits import PriceStepTable  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-snapshot-id", required=True)
    parser.add_argument(
        "--price-step-table",
        type=Path,
        help=(
            "versioned official tick-size CSV; defaults to the centrally configured "
            "BIST equity reference file"
        ),
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/labels"))
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
    pipeline = LabelGenerationPipeline(
        config,
        code_commit_sha=current_code_commit_sha(PROJECT_ROOT),
    )
    result = pipeline.run(
        args.clean_snapshot_id,
        price_steps,
        exception_limit=args.exception_limit,
    )

    args.report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.report_dir / "label_summary.json"
    exceptions_path = args.report_dir / "label_exception_examples.csv"
    summary_payload = {
        "label_snapshot_id": result.snapshot.metadata.snapshot_id,
        "label_snapshot_created": result.snapshot.created,
        "label_snapshot_checksum": result.snapshot.metadata.content_checksum,
        "input_clean_snapshot_id": args.clean_snapshot_id,
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
