"""Merge verified nominal snapshots into an immutable security identity layer."""

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
from src.data.security_identity import TickerMapping  # noqa: E402
from src.data.security_identity_pipeline import SecurityIdentityPipeline  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    defaults = MarketDataConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--nominal-snapshot-id",
        action="append",
        required=True,
        help="repeatable verified yfinance/nominal_ohlc snapshot ID",
    )
    parser.add_argument(
        "--ticker-mapping",
        type=Path,
        default=PROJECT_ROOT / defaults.security_ticker_mapping_path,
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--report-dir", type=Path, default=Path("reports/security_identity")
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = replace(MarketDataConfig(), data_root=args.data_root)
    mapping = TickerMapping.from_csv(
        args.ticker_mapping,
        checksum_algorithm=config.checksum_algorithm,
    )
    result = SecurityIdentityPipeline(
        config,
        code_commit_sha=current_code_commit_sha(PROJECT_ROOT),
    ).run(args.nominal_snapshot_id, mapping)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.report_dir / "security_identity_summary.json"
    payload = {
        "security_identity_snapshot_id": result.snapshot.metadata.snapshot_id,
        "security_identity_snapshot_created": result.snapshot.created,
        "security_identity_snapshot_checksum": result.snapshot.metadata.content_checksum,
        "summary": result.summary,
    }
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    print(f"ticker_mapping={args.ticker_mapping}")
    print(f"summary_report={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
