"""Global BIST session calendar derived only from verified İş Yatırım stock days."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from src.data.collectors import current_code_commit_sha
from src.data.snapshot_store import SnapshotMetadata, SnapshotRequest, SnapshotStore


class GlobalCalendarError(RuntimeError):
    """Raised when a safe global session calendar cannot be constructed."""


@dataclass(frozen=True)
class GlobalCalendarResult:
    snapshot: SnapshotMetadata
    source_security_count: int
    session_count: int


def build_global_calendar(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Return the sorted union of observed stock sessions; never synthesize weekdays."""

    observed: list[pd.Series] = []
    for frame in frames:
        if "HGDG_TARIH" not in frame.columns:
            raise GlobalCalendarError("İş Yatırım input is missing HGDG_TARIH")
        dates = pd.to_datetime(frame["HGDG_TARIH"], errors="raise").dt.normalize()
        observed.append(dates)
    if not observed:
        raise GlobalCalendarError("at least one İş Yatırım stock snapshot is required")
    sessions = pd.concat(observed, ignore_index=True).dropna().drop_duplicates().sort_values()
    if sessions.empty:
        raise GlobalCalendarError("no observed İş Yatırım sessions were found")
    result = pd.DataFrame({"session_date": sessions.reset_index(drop=True)})
    result["session_index"] = pd.Series(range(len(result)), dtype="int64")
    if result["session_date"].duplicated().any() or not result["session_date"].is_monotonic_increasing:
        raise GlobalCalendarError("global calendar must be unique and increasing")
    return result.loc[:, ["session_date", "session_index"]]


class GlobalCalendarPipeline:
    """Verify stock snapshots and persist the global session-date union."""

    def __init__(self, snapshot_store: SnapshotStore, *, code_commit_sha: str | None = None) -> None:
        self.snapshot_store = snapshot_store
        self.code_commit_sha = code_commit_sha or current_code_commit_sha()

    def run(self, stock_snapshot_ids: Sequence[str]) -> GlobalCalendarResult:
        if not stock_snapshot_ids:
            raise GlobalCalendarError("stock_snapshot_ids cannot be empty")
        metadata: list[SnapshotMetadata] = []
        frames: list[pd.DataFrame] = []
        tickers: set[str] = set()
        for snapshot_id in stock_snapshot_ids:
            item = self.snapshot_store.get_snapshot(snapshot_id)
            if not self.snapshot_store.is_usable(item):
                raise GlobalCalendarError(f"snapshot is not COMPLETE and verified: {snapshot_id}")
            if item.source != "isyatirim" or item.dataset_type != "equity_history" or item.layer != "raw":
                raise GlobalCalendarError(f"not a raw İş Yatırım equity snapshot: {snapshot_id}")
            metadata.append(item)
            frames.append(self.snapshot_store.read_dataframe(item))
            tickers.add(item.ticker_or_instrument)
        calendar = build_global_calendar(frames)
        start = calendar["session_date"].min().date()
        end = calendar["session_date"].max().date()
        context = {
            "input_snapshot_ids": sorted(stock_snapshot_ids),
            "input_content_checksums": {
                item.snapshot_id: item.content_checksum for item in metadata
            },
            "calendar_method": "verified_isyatirim_stock_session_union_v1",
            "code_commit_sha": self.code_commit_sha,
        }
        request = SnapshotRequest(
            source="isyatirim",
            dataset_type="global_bist_sessions",
            ticker_or_instrument="BIST",
            request_start_date=start,
            request_end_date=end,
            request_parameters={"method": "observed_stock_session_union", "synthetic_days": False},
            provider_library_version="repo-derived",
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=tuple(sorted(stock_snapshot_ids)),
            identity_columns=("session_date",),
            revision_context=context,
        )
        written = self.snapshot_store.save_dataframe(calendar, request)
        return GlobalCalendarResult(written.metadata, len(tickers), len(calendar))
