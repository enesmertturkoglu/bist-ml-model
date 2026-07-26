from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from src.config import MarketDataConfig, SnapshotStatus
from src.data.collectors import MarketDataCollector
from src.data.isyatirim_client import IsYatirimFetchError, RequestFailure
from src.data.snapshot_store import SnapshotStore


class FakeIsYatirimClient:
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None) -> None:
        self.frame = frame
        self.error = error
        self.calls: list[tuple[str, date, date]] = []

    def fetch_history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        if self.error is not None:
            raise self.error
        assert self.frame is not None
        return self.frame.copy()


def _config(tmp_path: Path, *, yfinance_retries: int = 2) -> MarketDataConfig:
    defaults = MarketDataConfig()
    return replace(
        defaults,
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
        yfinance=replace(defaults.yfinance, max_retries=yfinance_retries),
    )


def _isyatirim_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "HGDG_HS_KODU": ["AAA", "AAA"],
            "HGDG_TARIH": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "HGDG_KAPANIS": [5.0, 20.0],
            "HGDG_AOF": [5.1, 20.1],
            "HGDG_MIN": [4.5, 19.0],
            "HGDG_MAX": [5.5, 21.0],
            "HGDG_HACIM": [1_000_000.0, 2_000_000.0],
            "HG_KAPANIS": [10.0, 20.0],
            "HG_AOF": [10.2, 20.1],
            "HG_MIN": [9.0, 19.0],
            "HG_MAX": [11.0, 21.0],
            "HG_HACIM": [1_000_000.0, 2_000_000.0],
            "END_ENDEKS_KODU": ["XU100", "XU100"],
            "END_TARIH": [1704067200000, 1704153600000],
            "END_SEANS": [2, 2],
            "END_DEGER": [8000.0, 8100.0],
            "PD": [1_000_000_000.0, 2_000_000_000.0],
            "PD_USD": [33_000_000.0, 66_000_000.0],
            "HAO_PD": [500_000_000.0, 1_000_000_000.0],
            "HAO_PD_USD": [16_500_000.0, 33_000_000.0],
        }
    )


def _yfinance_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(
        ["2024-01-01 00:00:00", "2024-01-02 00:00:00"],
        tz="Europe/Istanbul",
        name="Date",
    )
    return pd.DataFrame(
        {
            "Open": [10.0, 20.0],
            "High": [11.0, 21.0],
            "Low": [9.0, 19.0],
            "Close": [10.5, 20.5],
            "Adj Close": [5.25, 20.5],
            "Volume": [100, 200],
            "Dividends": [0.0, 0.5],
            "Stock Splits": [0.0, 2.0],
        },
        index=index,
    )


def test_collectors_store_raw_sources_and_nominal_data_in_separate_layers(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    is_client = FakeIsYatirimClient(_isyatirim_frame())
    yf_calls: list[tuple[str, date, date, float]] = []

    def fetch_yfinance(
        ticker: str, start: date, end: date, timeout: float
    ) -> pd.DataFrame:
        yf_calls.append((ticker, start, end, timeout))
        return _yfinance_frame()

    collector = MarketDataCollector(
        config,
        snapshot_store=store,
        isyatirim_client=is_client,
        yfinance_fetcher=fetch_yfinance,
        sleep_func=lambda _: None,
        code_commit_sha="b" * 40,
    )

    result = collector.collect_ticker("aaa", date(2024, 1, 1), date(2024, 1, 2))

    assert result.complete
    assert is_client.calls == [("AAA", date(2024, 1, 1), date(2024, 1, 2))]
    assert yf_calls == [("AAA", date(2024, 1, 1), date(2024, 1, 2), 30.0)]
    is_result, yf_result = result.source_results
    raw_is = store.read_dataframe(is_result.raw_snapshot)
    raw_yf = store.read_dataframe(yf_result.raw_snapshot)
    nominal = store.read_dataframe(yf_result.derived_snapshots[0])

    assert is_result.raw_snapshot.file_path.startswith("raw/isyatirim/")
    assert yf_result.raw_snapshot.file_path.startswith("raw/yfinance/")
    assert yf_result.derived_snapshots[0].file_path.startswith("derived/yfinance/")
    assert raw_is["HGDG_HACIM"].tolist() == [1_000_000, 2_000_000]
    assert raw_is["END_DEGER"].tolist() == [8000, 8100]
    assert raw_is["PD"].tolist() == [1_000_000_000, 2_000_000_000]
    assert raw_yf["Open"].tolist() == [10, 20]
    assert raw_yf["Dividends"].tolist() == [0, 0.5]
    assert raw_yf["Stock Splits"].tolist() == [0, 2]
    assert "yf_future_split_factor" not in raw_yf.columns
    assert nominal["yf_future_split_factor"].tolist() == [2, 1]
    assert nominal["yf_nominal_open"].tolist() == [20, 20]
    assert yf_result.derived_snapshots[0].input_snapshot_ids == (
        yf_result.raw_snapshot.snapshot_id,
    )


def test_source_failure_is_recorded_without_blocking_other_source(tmp_path: Path) -> None:
    config = _config(tmp_path, yfinance_retries=1)
    store = SnapshotStore(config)
    failure = RequestFailure(
        ticker="AAA",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        attempts=1,
        chunk_months=3,
        error_type="Timeout",
        message="provider timeout",
        cache_used=False,
    )
    collector = MarketDataCollector(
        config,
        snapshot_store=store,
        isyatirim_client=FakeIsYatirimClient(error=IsYatirimFetchError([failure])),
        yfinance_fetcher=lambda *_: _yfinance_frame(),
        sleep_func=lambda _: None,
        code_commit_sha="c" * 40,
    )

    result = collector.collect_ticker("AAA", date(2024, 1, 1), date(2024, 1, 2))

    is_result, yf_result = result.source_results
    assert not result.complete
    assert is_result.raw_snapshot.snapshot_status is SnapshotStatus.FAILED
    assert not store.is_usable(is_result.raw_snapshot)
    assert yf_result.complete
    assert store.is_usable(yf_result.raw_snapshot)
    assert store.is_usable(yf_result.derived_snapshots[0])


def test_yfinance_retry_settings_are_centralized_and_network_free(tmp_path: Path) -> None:
    config = _config(tmp_path, yfinance_retries=2)
    attempts = 0
    sleeps: list[float] = []

    def flaky_fetcher(*_: object) -> pd.DataFrame:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary")
        return _yfinance_frame()

    collector = MarketDataCollector(
        config,
        isyatirim_client=FakeIsYatirimClient(_isyatirim_frame()),
        yfinance_fetcher=flaky_fetcher,
        sleep_func=sleeps.append,
        code_commit_sha="d" * 40,
    )

    result = collector.collect_yfinance(
        "AAA", date(2024, 1, 1), date(2024, 1, 2)
    )

    assert result.complete
    assert attempts == 2
    assert sleeps == [config.yfinance.retry_backoff_seconds]


def test_repeated_collection_is_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path, yfinance_retries=1)
    store = SnapshotStore(config)
    collector = MarketDataCollector(
        config,
        snapshot_store=store,
        isyatirim_client=FakeIsYatirimClient(_isyatirim_frame()),
        yfinance_fetcher=lambda *_: _yfinance_frame(),
        sleep_func=lambda _: None,
        code_commit_sha="e" * 40,
    )

    first = collector.collect_ticker("AAA", date(2024, 1, 1), date(2024, 1, 2))
    second = collector.collect_ticker("AAA", date(2024, 1, 1), date(2024, 1, 2))

    first_ids = [
        snapshot.snapshot_id
        for source in first.source_results
        for snapshot in (source.raw_snapshot, *source.derived_snapshots)
    ]
    second_ids = [
        snapshot.snapshot_id
        for source in second.source_results
        for snapshot in (source.raw_snapshot, *source.derived_snapshots)
    ]
    assert second_ids == first_ids
    assert len(store.load_manifest()) == 3


def test_missing_required_provider_field_is_recorded_as_partial(tmp_path: Path) -> None:
    config = _config(tmp_path, yfinance_retries=1)
    store = SnapshotStore(config)
    incomplete = _yfinance_frame().drop(columns=["Stock Splits"])
    collector = MarketDataCollector(
        config,
        snapshot_store=store,
        isyatirim_client=FakeIsYatirimClient(_isyatirim_frame()),
        yfinance_fetcher=lambda *_: incomplete,
        sleep_func=lambda _: None,
        code_commit_sha="f" * 40,
    )

    result = collector.collect_yfinance(
        "AAA", date(2024, 1, 1), date(2024, 1, 2)
    )

    assert result.raw_snapshot.snapshot_status is SnapshotStatus.PARTIAL
    assert "Stock Splits" in (result.raw_snapshot.error_message or "")
    assert result.derived_snapshots == ()
    assert not store.is_usable(result.raw_snapshot)
