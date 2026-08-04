"""Benchmark isolated full-history collection without touching production checkpoints."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MarketDataConfig  # noqa: E402
from src.data.full_history_pipeline import (  # noqa: E402
    FullHistoryContext,
    FullHistoryPaths,
    FullHistoryPipeline,
)
from src.data.snapshot_store import SnapshotStore  # noqa: E402


DEFAULT_TICKERS = (
    "AEFES",
    "MOPAS",
    "EKSUN",
    "TATEN",
    "VBTYZ",
    "MNDRS",
    "TDGYO",
    "PENGD",
    "BORSK",
    "REEDR",
    "BINHO",
    "ASTOR",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--isyatirim-max-concurrency", type=int, default=2)
    parser.add_argument("--global-request-interval-seconds", type=float, default=1.0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _scope_digest(rows: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _benchmark_one(
    base_preflight: Any,
    base_paths: FullHistoryPaths,
    tickers: Sequence[str],
    workers: int,
    root: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    selected = base_preflight.universe.loc[
        base_preflight.universe["current_ticker"].astype(str).isin(tickers)
    ].copy()
    found = set(selected["current_ticker"].astype(str))
    missing = sorted(set(tickers).difference(found))
    if missing:
        raise RuntimeError(f"benchmark tickers not in frozen universe: {missing}")
    security_ids = set(selected["security_id"].astype(str))
    manifest = base_preflight.manifest.loc[
        base_preflight.manifest["security_id"].astype(str).isin(security_ids)
    ].copy()
    preflight = replace(base_preflight, universe=selected, manifest=manifest)

    config = replace(
        MarketDataConfig(),
        data_root=root / "data",
        operational_cache_root=root / "cache",
        security_worker_count=workers,
        isyatirim_max_concurrency=args.isyatirim_max_concurrency,
        global_request_interval_seconds=args.global_request_interval_seconds,
    )
    context = FullHistoryContext(master_security_count=len(selected))
    paths = replace(base_paths, report_root=root / "reports")
    store = SnapshotStore(config)
    pipeline = FullHistoryPipeline(
        config,
        context=context,
        paths=paths,
        snapshot_store=store,
        progress_func=print if args.verbose else (lambda *_: None),
    )
    started = time.perf_counter()
    outcomes, status, summary, _ = pipeline.collect_manifest(preflight)
    elapsed = time.perf_counter() - started

    latest = {item.row_number: item for item in outcomes}
    scope_rows: list[dict[str, Any]] = []
    for row_number in sorted(latest):
        outcome = latest[row_number]
        checksums: dict[str, str] = {}
        for source, snapshot_id in (
            ("isyatirim", outcome.isyatirim_raw_snapshot_id),
            ("yfinance", outcome.yfinance_raw_snapshot_id),
            ("nominal", outcome.nominal_snapshot_id),
        ):
            metadata = store.get_snapshot(snapshot_id) if snapshot_id else None
            checksums[source] = metadata.content_checksum if metadata else ""
        scope_rows.append(
            {
                "security_id": outcome.security_id,
                "ticker": outcome.current_ticker,
                "statuses": [
                    outcome.isyatirim_status,
                    outcome.yfinance_status,
                    outcome.nominal_status,
                ],
                "checksums": checksums,
                "gaps": [
                    [provider, gap.start_date, gap.end_date, gap.failure_class]
                    for provider, gap in outcome.gaps
                ],
            }
        )
    attempted = status.loc[
        ~status["status"].isin(["PENDING", "UNATTEMPTED"])
    ].copy()
    attempt_history = pipeline._checkpoint_attempt_history or outcomes
    total_logical_requests = sum(
        int(item.network_request_count) for item in attempt_history
    )
    telemetry_by_security: dict[str, dict[str, int]] = {}
    for item in attempt_history:
        counters = telemetry_by_security.setdefault(
            item.current_ticker,
            {"network_request_count": 0, "retry_count": 0, "attempt_count": 0},
        )
        counters["network_request_count"] += int(item.network_request_count)
        counters["retry_count"] += int(item.retry_count)
        counters["attempt_count"] += 1
    return {
        "workers": workers,
        "elapsed_seconds": round(elapsed, 3),
        "summary": dict(summary),
        "total_logical_provider_requests": total_logical_requests,
        "attempt_telemetry": telemetry_by_security,
        "used_security_ids": sorted(
            attempted.loc[attempted["status"].eq("COMPLETE"), "security_id"].astype(str)
        ),
        "excluded_security_ids": sorted(
            attempted.loc[~attempted["status"].eq("COMPLETE"), "security_id"].astype(str)
        ),
        "scope_digest": _scope_digest(scope_rows),
        "status_rows": attempted[
            [
                "current_ticker",
                "status",
                "network_request_count",
                "retry_count",
                "cache_hit_count",
            ]
        ].to_dict(orient="records"),
        "scope_rows": scope_rows,
    }


def main() -> int:
    args = parse_args()
    if any(value < 1 for value in args.workers):
        raise SystemExit("workers must be positive")
    base_config = MarketDataConfig()
    base_paths = FullHistoryPaths()
    base_pipeline = FullHistoryPipeline(
        base_config,
        paths=base_paths,
        snapshot_store=SnapshotStore(base_config),
        progress_func=lambda *_: None,
    )
    base_preflight = base_pipeline.preflight()
    with tempfile.TemporaryDirectory(prefix="bist-history-benchmark-") as temp_text:
        temp_root = Path(temp_text)
        results = []
        for run_index, workers in enumerate(args.workers, start=1):
            if args.verbose:
                print(
                    f"[BENCHMARK] workers={workers} tickers={len(args.tickers)} started",
                    flush=True,
                )
            results.append(
                _benchmark_one(
                    base_preflight,
                    base_paths,
                    args.tickers,
                    workers,
                    temp_root / f"run-{run_index}-workers-{workers}",
                    args,
                )
            )
    reference = results[0]
    equivalence = {
        str(item["workers"]): {
            "scope_digest_equal": item["scope_digest"] == reference["scope_digest"],
            "used_scope_equal": item["used_security_ids"]
            == reference["used_security_ids"],
            "excluded_scope_equal": item["excluded_security_ids"]
            == reference["excluded_security_ids"],
        }
        for item in results
    }
    print(
        json.dumps(
            {
                "tickers": list(args.tickers),
                "isolated_from_production": True,
                "results": results,
                "equivalence_against_first_run": equivalence,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
