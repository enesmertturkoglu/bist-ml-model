"""Market-data collectors backed by immutable snapshot storage."""

from __future__ import annotations

import importlib.metadata
import subprocess
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from src.config import MarketDataConfig, SnapshotStatus
from src.data.isyatirim_client import IsYatirimClient, IsYatirimFetchError
from src.data.security_identity import (
    TickerMapping,
    normalize_ticker,
    plan_active_ticker_collection,
)
from src.data.snapshot_store import (
    SnapshotMetadata,
    SnapshotRequest,
    SnapshotStore,
)
from src.data.yfinance_normalization import (
    YFINANCE_REQUIRED_COLUMNS,
    nominal_ohlc_snapshot_frame,
    normalize_yfinance_history,
    prepare_raw_yfinance_history,
)


YFinanceFetcher = Callable[[str, date, date, float], pd.DataFrame]
ISYATIRIM_SNAPSHOT_REQUIRED_COLUMNS = {
    "HGDG_HS_KODU",
    "HGDG_TARIH",
    "HGDG_KAPANIS",
    "HGDG_AOF",
    "HGDG_MIN",
    "HGDG_MAX",
    "HGDG_HACIM",
    "HG_KAPANIS",
    "HG_AOF",
    "HG_MIN",
    "HG_MAX",
    "HG_HACIM",
    "END_ENDEKS_KODU",
    "END_TARIH",
    "END_SEANS",
    "END_DEGER",
    "PD",
    "PD_USD",
    "HAO_PD",
    "HAO_PD_USD",
}


@dataclass(frozen=True)
class SourceCollectionResult:
    source: str
    raw_snapshot: SnapshotMetadata
    derived_snapshots: tuple[SnapshotMetadata, ...] = ()

    @property
    def complete(self) -> bool:
        return self.raw_snapshot.snapshot_status is SnapshotStatus.COMPLETE and all(
            item.snapshot_status is SnapshotStatus.COMPLETE
            for item in self.derived_snapshots
        )


@dataclass(frozen=True)
class TickerCollectionResult:
    ticker: str
    source_results: tuple[SourceCollectionResult, ...]

    @property
    def complete(self) -> bool:
        return all(item.complete for item in self.source_results)


class MarketDataCollector:
    """Collect İş Yatırım/yFinance independently and snapshot every outcome."""

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        isyatirim_client: IsYatirimClient | None = None,
        yfinance_fetcher: YFinanceFetcher | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        code_commit_sha: str | None = None,
        ticker_mapping: TickerMapping | None = None,
    ) -> None:
        self.config = config or MarketDataConfig()
        self.snapshot_store = snapshot_store or SnapshotStore(self.config)
        is_config = self.config.isyatirim
        self.isyatirim_client = isyatirim_client or IsYatirimClient(
            timeout_seconds=is_config.timeout_seconds,
            max_retries=is_config.max_retries,
            minimum_chunk_months=is_config.minimum_chunk_months or 3,
            request_delay_seconds=is_config.request_delay_seconds,
            cache_dir=self.config.isyatirim_cache_root,
        )
        self.yfinance_fetcher = yfinance_fetcher or _fetch_yfinance_history
        self.sleep_func = sleep_func
        self.code_commit_sha = code_commit_sha or current_code_commit_sha()
        self.ticker_mapping = ticker_mapping
        self.isyatirim_version = _package_version("isyatirimhisse")
        self.yfinance_version = _package_version("yfinance")

    def collect_isyatirim(
        self, ticker: str, start_date: date, end_date: date
    ) -> SourceCollectionResult:
        ticker = normalize_ticker(ticker)
        request = SnapshotRequest(
            source="isyatirim",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={
                "endpoint": "HisseTekil",
                "inclusive_end": True,
            },
            provider_library_version=self.isyatirim_version,
            code_commit_sha=self.code_commit_sha,
            layer="raw",
            identity_columns=("HGDG_HS_KODU", "HGDG_TARIH"),
        )
        frame: pd.DataFrame | None = None
        try:
            frame = self.isyatirim_client.fetch_history(ticker, start_date, end_date)
            _require_columns(
                frame,
                ISYATIRIM_SNAPSHOT_REQUIRED_COLUMNS,
                source="İş Yatırım",
                ticker=ticker,
            )
        except IsYatirimFetchError as error:
            written = self.snapshot_store.record_failed_attempt(
                request, error, partial_data=error.partial_data
            )
        except Exception as error:  # provider/schema failures must be auditable
            written = self.snapshot_store.record_failed_attempt(
                request, error, partial_data=frame
            )
        else:
            written = self.snapshot_store.save_dataframe(frame, request)
        return SourceCollectionResult("isyatirim", written.metadata)

    def collect_yfinance(
        self, ticker: str, start_date: date, end_date: date
    ) -> SourceCollectionResult:
        ticker = normalize_ticker(ticker)
        raw_request = SnapshotRequest(
            source="yfinance",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={
                "provider_ticker": f"{ticker.strip().upper()}.IS",
                "auto_adjust": False,
                "actions": True,
                "inclusive_end": True,
            },
            provider_library_version=self.yfinance_version,
            code_commit_sha=self.code_commit_sha,
            layer="raw",
            identity_columns=("ticker", "date"),
        )
        raw: pd.DataFrame | None = None
        try:
            raw = self._fetch_yfinance_with_retry(ticker, start_date, end_date)
            _require_columns(
                raw,
                YFINANCE_REQUIRED_COLUMNS,
                source="yFinance",
                ticker=ticker,
            )
            prepared = prepare_raw_yfinance_history(raw, ticker)
        except Exception as error:  # provider failures must be auditable
            partial = (
                prepare_raw_yfinance_history(raw, ticker)
                if raw is not None and not raw.empty
                else None
            )
            written = self.snapshot_store.record_failed_attempt(
                raw_request, error, partial_data=partial
            )
            return SourceCollectionResult("yfinance", written.metadata)

        raw_written = self.snapshot_store.save_dataframe(prepared, raw_request)
        derived_request = SnapshotRequest(
            source="yfinance",
            dataset_type="nominal_ohlc",
            ticker_or_instrument=ticker,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={"normalization_decision": "D024", "version": "v1"},
            provider_library_version=self.yfinance_version,
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=(raw_written.metadata.snapshot_id,),
            identity_columns=("ticker", "date"),
        )
        try:
            normalized = normalize_yfinance_history(raw, ticker)
            nominal = nominal_ohlc_snapshot_frame(normalized)
        except Exception as error:
            derived_written = self.snapshot_store.record_failed_attempt(
                derived_request, error
            )
        else:
            derived_written = self.snapshot_store.save_dataframe(
                nominal, derived_request
            )
        return SourceCollectionResult(
            "yfinance",
            raw_written.metadata,
            (derived_written.metadata,),
        )

    def collect_ticker(
        self, ticker: str, start_date: date, end_date: date
    ) -> TickerCollectionResult:
        """Run both providers even if one source returns a failed snapshot."""

        normalized_ticker = normalize_ticker(ticker)
        results = (
            self.collect_isyatirim(normalized_ticker, start_date, end_date),
            self.collect_yfinance(normalized_ticker, start_date, end_date),
        )
        return TickerCollectionResult(normalized_ticker, results)

    def collect_many(
        self, tickers: Iterable[str], start_date: date, end_date: date
    ) -> tuple[TickerCollectionResult, ...]:
        if self.ticker_mapping is not None:
            periods = plan_active_ticker_collection(
                tickers,
                start_date,
                end_date,
                self.ticker_mapping,
            )
            return tuple(
                self.collect_ticker(period.ticker, period.start_date, period.end_date)
                for period in periods
            )
        return tuple(
            self.collect_ticker(ticker, start_date, end_date) for ticker in tickers
        )

    def _fetch_yfinance_with_retry(
        self, ticker: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        settings = self.config.yfinance
        last_error: Exception | None = None
        for attempt in range(1, settings.max_retries + 1):
            try:
                frame = self.yfinance_fetcher(
                    ticker,
                    start_date,
                    end_date,
                    settings.timeout_seconds,
                )
                if frame.empty:
                    raise ValueError(f"yFinance returned no rows for {ticker}")
                return frame
            except Exception as error:
                last_error = error
                if attempt < settings.max_retries:
                    self.sleep_func(settings.retry_backoff_seconds * attempt)
        assert last_error is not None
        raise RuntimeError(
            f"yFinance failed for {ticker} after {settings.max_retries} attempts: "
            f"{last_error}"
        ) from last_error


def _fetch_yfinance_history(
    ticker: str, start_date: date, end_date: date, timeout_seconds: float
) -> pd.DataFrame:
    import yfinance as yf

    return yf.Ticker(f"{normalize_ticker(ticker)}.IS").history(
        start=start_date.isoformat(),
        # yFinance end is exclusive; collection requests use inclusive dates.
        end=(end_date + timedelta(days=1)).isoformat(),
        auto_adjust=False,
        actions=True,
        timeout=timeout_seconds,
    )


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    source: str,
    ticker: str,
) -> None:
    missing = required.difference(map(str, frame.columns))
    if missing:
        raise ValueError(
            f"{source} required snapshot fields missing for {ticker}: {sorted(missing)}"
        )


def current_code_commit_sha(repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root.resolve().as_posix()}",
                "rev-parse",
                "HEAD",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
