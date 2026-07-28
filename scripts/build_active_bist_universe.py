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
    ActiveUniverseError,
    build_active_universe,
    empty_mapping,
    fetch_official_sources,
    parse_kap_companies_html,
    parse_kap_markets_html,
    save_active_universe_snapshot,
    save_official_source_snapshots,
    source_manifest_frame,
    validate_borsa_istanbul_cross_check,
    write_csv_deterministic,
)
from src.data.collectors import current_code_commit_sha  # noqa: E402
from src.data.snapshot_store import SnapshotStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the official-source active BIST equity universe"
    )
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--report-dir", type=Path, default=Path("reports/universe"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--universe-file",
        type=Path,
        default=Path("reference_data/bist_active_universe_v1.csv"),
    )
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=Path("reference_data/bist_security_ticker_map_v1.csv"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    code_sha = current_code_commit_sha()
    sources = fetch_official_sources(
        args.as_of_date,
        timeout_seconds=args.timeout_seconds,
        code_commit_sha=code_sha,
    )
    by_name = {source.source_name: source for source in sources}
    required = {
        "KAP_BIST_COMPANIES",
        "KAP_MARKETS",
        "KAP_ENDED_MEMBERS",
        "BORSA_ISTANBUL_TRADED_COMPANIES",
    }
    if set(by_name) != required:
        raise ActiveUniverseError("official source set is incomplete")
    companies = parse_kap_companies_html(by_name["KAP_BIST_COMPANIES"].raw_content)
    markets = parse_kap_markets_html(by_name["KAP_MARKETS"].raw_content)
    ended = parse_kap_companies_html(by_name["KAP_ENDED_MEMBERS"].raw_content)
    validate_borsa_istanbul_cross_check(
        by_name["BORSA_ISTANBUL_TRADED_COMPANIES"].raw_content
    )
    build = build_active_universe(
        as_of_date=args.as_of_date,
        kap_companies=companies,
        kap_markets=markets,
        ended_members=ended,
    )

    config = replace(MarketDataConfig(), data_root=args.data_root)
    store = SnapshotStore(config)
    source_snapshots = save_official_source_snapshots(sources, store)
    universe_checksum = write_csv_deterministic(build.universe, args.universe_file)
    mapping = empty_mapping(args.mapping_file)
    active_snapshot = save_active_universe_snapshot(
        build.universe,
        as_of_date=args.as_of_date,
        source_metadata=[item.metadata for item in source_snapshots],
        active_universe_file_checksum=universe_checksum,
        mapping=mapping,
        excluded_candidate_count=int(build.summary["excluded_count"]),
        snapshot_store=store,
        code_commit_sha=code_sha,
    )

    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_csv_deterministic(
        build.audit, args.report_dir / "bist_active_universe_v1_audit.csv"
    )
    write_csv_deterministic(
        build.mapping_review, args.report_dir / "ticker_mapping_review_v1.csv"
    )
    source_manifest = source_manifest_frame(sources, source_snapshots)
    write_csv_deterministic(
        source_manifest, args.report_dir / "active_universe_source_manifest_v1.csv"
    )
    summary = {
        **dict(build.summary),
        "active_universe_file_checksum": universe_checksum,
        "ticker_mapping_version": mapping.version,
        "ticker_mapping_checksum": mapping.checksum,
        "confirmed_historical_ticker_mapping_count": int(
            (~mapping.frame["is_current_ticker"]).sum()
        ),
        "manual_review_mapping_count": int(
            build.mapping_review["review_status"].eq("NEEDS_MANUAL_REVIEW").sum()
        ),
        "source_snapshots": [
            {
                "source_name": source.source_name,
                "snapshot_id": snapshot.metadata.snapshot_id,
                "content_checksum": snapshot.metadata.content_checksum,
                "raw_content_checksum": source.raw_content_checksum,
                "created": snapshot.created,
            }
            for source, snapshot in zip(sources, source_snapshots, strict=True)
        ],
        "active_universe_snapshot_id": active_snapshot.metadata.snapshot_id,
        "active_universe_snapshot_checksum": active_snapshot.metadata.content_checksum,
        "active_universe_snapshot_created": active_snapshot.created,
    }
    summary_path = args.report_dir / "bist_active_universe_v1_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
