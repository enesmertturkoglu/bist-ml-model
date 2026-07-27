from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.config import MarketDataConfig
from src.data.calendar_pipeline import (
    GlobalCalendarError,
    GlobalCalendarPipeline,
    build_global_calendar,
)
from src.data.snapshot_store import SnapshotRequest, SnapshotStore


def _frame(ticker: str, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"HGDG_HS_KODU": ticker, "HGDG_TARIH": pd.to_datetime(dates), "HGDG_HACIM": 1.0}
    )


def _config(tmp_path: Path) -> MarketDataConfig:
    return replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )


def _save_stock(store: SnapshotStore, ticker: str, dates: list[str]) -> str:
    result = store.save_dataframe(
        _frame(ticker, dates),
        SnapshotRequest(
            source="isyatirim",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=min(dates),
            request_end_date=max(dates),
            layer="raw",
            identity_columns=("HGDG_HS_KODU", "HGDG_TARIH"),
        ),
    )
    return result.metadata.snapshot_id


def test_global_calendar_uses_union_without_synthetic_weekdays() -> None:
    calendar = build_global_calendar(
        [
            _frame("AAA", ["2024-01-02", "2024-01-04"]),
            _frame("BBB", ["2024-01-02", "2024-01-03"]),
        ]
    )

    assert calendar["session_date"].tolist() == list(
        pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    )
    assert calendar["session_index"].tolist() == [0, 1, 2]


def test_individual_missing_day_does_not_remove_global_session(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    ids = [
        _save_stock(store, "AAA", ["2024-01-02", "2024-01-04"]),
        _save_stock(store, "BBB", ["2024-01-02", "2024-01-03", "2024-01-04"]),
    ]

    result = GlobalCalendarPipeline(store, code_commit_sha="a" * 40).run(ids)
    saved = store.read_dataframe(result.snapshot)

    assert result.source_security_count == 2
    assert result.session_count == 3
    assert pd.Timestamp("2024-01-03") in set(pd.to_datetime(saved["session_date"]))
    assert result.snapshot.revision_context_checksum is not None
    assert set(result.snapshot.input_snapshot_ids) == set(ids)


def test_calendar_rejects_non_isyatirim_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    snapshot = store.save_dataframe(
        _frame("AAA", ["2024-01-02"]),
        SnapshotRequest(
            source="yfinance",
            dataset_type="equity_history",
            ticker_or_instrument="AAA",
            request_start_date="2024-01-02",
            request_end_date="2024-01-02",
        ),
    ).metadata

    with pytest.raises(GlobalCalendarError, match="not a raw İş Yatırım"):
        GlobalCalendarPipeline(store).run([snapshot.snapshot_id])
