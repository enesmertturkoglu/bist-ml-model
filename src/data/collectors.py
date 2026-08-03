"""Market-data collectors backed by immutable snapshot storage."""

from __future__ import annotations

import importlib.metadata
import inspect
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from src.config import MarketDataConfig, SnapshotStatus
from src.data.isyatirim_client import (
    DATA_IN_RANGE,
    NO_DATA_IN_RANGE,
    TIME_BUDGET_EXCEEDED,
    GlobalRequestLimiter,
    IsYatirimBudgetFetchError,
    IsYatirimClient,
    IsYatirimFetchError,
    IsYatirimSchemaError,
)
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
class ProviderGap:
    start_date: str
    end_date: str
    failure_class: str
    failure_reason: str
    retry_recommended: bool


@dataclass(frozen=True)
class SourceCollectionResult:
    source: str
    raw_snapshot: SnapshotMetadata | None
    derived_snapshots: tuple[SnapshotMetadata, ...] = ()
    failure_class: str | None = None
    failure_reason: str | None = None
    missing_ranges: tuple[ProviderGap, ...] = ()
    metrics: Mapping[str, int | float] = field(default_factory=dict)
    retry_recommended: bool = False
    result: str = DATA_IN_RANGE
    operational_hint_date: str = ""

    @property
    def complete(self) -> bool:
        return self.raw_snapshot is not None and (
            self.raw_snapshot.snapshot_status is SnapshotStatus.COMPLETE
        ) and all(
            item.snapshot_status is SnapshotStatus.COMPLETE
            for item in self.derived_snapshots
        )


@dataclass(frozen=True)
class PreparedSourceCollection:
    """Fetch/parse result that contains no shared snapshot/report writes."""

    source: str
    raw_request: SnapshotRequest
    raw_frame: pd.DataFrame | None = None
    raw_existing: SnapshotMetadata | None = None
    raw_error: Exception | None = None
    raw_partial_data: pd.DataFrame | None = None
    derived_frame: pd.DataFrame | None = None
    derived_existing: SnapshotMetadata | None = None
    derived_error: Exception | None = None
    missing_ranges: tuple[ProviderGap, ...] = ()
    metrics: Mapping[str, int | float] = field(default_factory=dict)
    retry_recommended: bool = False
    result: str = DATA_IN_RANGE
    operational_hint_date: str = ""


@dataclass(frozen=True)
class PreparedTickerCollection:
    ticker: str
    source_results: tuple[PreparedSourceCollection, ...]


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
        monotonic_func: Callable[[], float] = time.monotonic,
        progress_func: Callable[[str], None] | None = None,
        request_limiter: GlobalRequestLimiter | None = None,
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
            monotonic_func=monotonic_func,
            progress_func=progress_func,
            request_limiter=request_limiter,
        )
        self.yfinance_fetcher = yfinance_fetcher or _fetch_yfinance_history
        self.sleep_func = sleep_func
        self.code_commit_sha = code_commit_sha or current_code_commit_sha()
        self.ticker_mapping = ticker_mapping
        self.monotonic_func = monotonic_func
        self.progress_func = progress_func
        self._last_yfinance_metrics: dict[str, int | float] = {}
        self.isyatirim_version = _package_version("isyatirimhisse")
        self.yfinance_version = _package_version("yfinance")

    def collect_isyatirim(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        security_budget_seconds: float | None = None,
        security_started_at: float | None = None,
        collection_pass: int = 1,
        security_id: str = "",
        manifest_position: int = 0,
        manifest_total: int = 0,
    ) -> SourceCollectionResult:
        ticker = normalize_ticker(ticker)
        request = self.isyatirim_request(ticker, start_date, end_date)
        if not refresh:
            existing = self.snapshot_store.find_usable_snapshot(request)
            if existing is not None:
                self._log(
                    f"[ISYATIRIM][{ticker}][{start_date.isoformat()}.."
                    f"{end_date.isoformat()}] verified COMPLETE snapshot cache hit"
                )
                return SourceCollectionResult(
                    "isyatirim", existing, metrics={"cache_hit_count": 1}
                )
        frame: pd.DataFrame | None = None
        before = _isyatirim_metric_counters(self.isyatirim_client)
        try:
            budget_kwargs: dict[str, Any] = {}
            if security_budget_seconds is not None:
                budget_kwargs = {
                    "security_budget_seconds": security_budget_seconds,
                    "security_started_at": security_started_at,
                    "collection_pass": collection_pass,
                    "security_id": security_id,
                    "manifest_position": manifest_position,
                    "manifest_total": manifest_total,
                }
            frame = self.isyatirim_client.fetch_history(
                ticker, start_date, end_date, **budget_kwargs
            )
            if frame.empty:
                metrics = _metric_delta(
                    before, _isyatirim_metric_counters(self.isyatirim_client)
                )
                return SourceCollectionResult(
                    "isyatirim",
                    None,
                    metrics=metrics,
                    result=NO_DATA_IN_RANGE,
                )
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
            budget_exceeded = isinstance(error, IsYatirimBudgetFetchError) or any(
                item.error_type == TIME_BUDGET_EXCEEDED for item in error.failures
            )
            failure_class = (
                TIME_BUDGET_EXCEEDED if budget_exceeded else type(error).__name__
            )
            failure = (failure_class, str(error))
            gaps = tuple(
                ProviderGap(
                    start_date=item.start_date.isoformat(),
                    end_date=item.end_date.isoformat(),
                    failure_class=item.error_type,
                    failure_reason=item.message,
                    retry_recommended=item.error_type != "IsYatirimSchemaError",
                )
                for item in error.failures
            )
        except Exception as error:  # provider/schema failures must be auditable
            written = self.snapshot_store.record_failed_attempt(
                request, error, partial_data=frame
            )
            failure = (type(error).__name__, str(error))
            gaps = (
                ProviderGap(
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    failure_class=type(error).__name__,
                    failure_reason=str(error),
                    retry_recommended=not isinstance(
                        error, (IsYatirimSchemaError, ValueError)
                    ),
                ),
            )
        else:
            written = self.snapshot_store.save_dataframe(frame, request)
            failure = (None, None)
            gaps = ()
        metrics = _metric_delta(before, _isyatirim_metric_counters(self.isyatirim_client))
        return SourceCollectionResult(
            "isyatirim",
            written.metadata,
            failure_class=failure[0],
            failure_reason=failure[1],
            missing_ranges=gaps,
            metrics=metrics,
            retry_recommended=any(item.retry_recommended for item in gaps),
        )

    def collect_yfinance(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
    ) -> SourceCollectionResult:
        ticker = normalize_ticker(ticker)
        raw_request = self.yfinance_raw_request(ticker, start_date, end_date)
        raw_existing = (
            None
            if refresh
            else self.snapshot_store.find_usable_snapshot(raw_request)
        )
        if raw_existing is not None:
            derived_request = self.yfinance_nominal_request(
                ticker, start_date, end_date, raw_existing.snapshot_id
            )
            nominal_existing = self.snapshot_store.find_usable_snapshot(
                derived_request
            )
            if nominal_existing is not None:
                return SourceCollectionResult(
                    "yfinance",
                    raw_existing,
                    (nominal_existing,),
                    metrics={"cache_hit_count": 2},
                )
            try:
                prepared = self.snapshot_store.read_dataframe(raw_existing)
                raw = _prepared_yfinance_provider_frame(prepared)
                normalized = normalize_yfinance_history(raw, ticker)
                nominal = nominal_ohlc_snapshot_frame(normalized)
            except Exception as error:
                derived_written = self.snapshot_store.record_failed_attempt(
                    derived_request, error
                )
                failure = (type(error).__name__, str(error))
            else:
                derived_written = self.snapshot_store.save_dataframe(
                    nominal, derived_request
                )
                failure = (None, None)
            return SourceCollectionResult(
                "yfinance",
                raw_existing,
                (derived_written.metadata,),
                failure_class=failure[0],
                failure_reason=failure[1],
                missing_ranges=(
                    ProviderGap(
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        failure_class=str(failure[0]),
                        failure_reason=str(failure[1]),
                        retry_recommended=True,
                    ),
                )
                if failure[0]
                else (),
                metrics={"cache_hit_count": 1},
                retry_recommended=bool(failure[0]),
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
            return SourceCollectionResult(
                "yfinance",
                written.metadata,
                failure_class=type(error).__name__,
                failure_reason=str(error),
                missing_ranges=(
                    ProviderGap(
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        failure_class=type(error).__name__,
                        failure_reason=str(error),
                        retry_recommended=not isinstance(error, ValueError),
                    ),
                ),
                metrics=self._last_yfinance_metrics,
                retry_recommended=not isinstance(error, ValueError),
            )

        raw_written = self.snapshot_store.save_dataframe(prepared, raw_request)
        derived_request = self.yfinance_nominal_request(
            ticker,
            start_date,
            end_date,
            raw_written.metadata.snapshot_id,
        )
        try:
            normalized = normalize_yfinance_history(raw, ticker)
            nominal = nominal_ohlc_snapshot_frame(normalized)
        except Exception as error:
            derived_written = self.snapshot_store.record_failed_attempt(
                derived_request, error
            )
            failure = (type(error).__name__, str(error))
        else:
            derived_written = self.snapshot_store.save_dataframe(
                nominal, derived_request
            )
            failure = (None, None)
        return SourceCollectionResult(
            "yfinance",
            raw_written.metadata,
            (derived_written.metadata,),
            failure_class=failure[0],
            failure_reason=failure[1],
            missing_ranges=(
                ProviderGap(
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    failure_class=str(failure[0]),
                    failure_reason=str(failure[1]),
                    retry_recommended=True,
                ),
            )
            if failure[0]
            else (),
            metrics=self._last_yfinance_metrics,
            retry_recommended=bool(failure[0]),
        )

    def prepare_isyatirim(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        security_budget_seconds: float | None = None,
        security_started_at: float | None = None,
        collection_pass: int = 1,
        security_id: str = "",
        manifest_position: int = 0,
        manifest_total: int = 0,
        first_observed_hint: date | None = None,
    ) -> PreparedSourceCollection:
        """Fetch/validate İş Yatırım data without writing shared snapshots."""

        ticker = normalize_ticker(ticker)
        request = self.isyatirim_request(ticker, start_date, end_date)
        if not refresh:
            existing = self.snapshot_store.find_usable_snapshot(request)
            if existing is not None:
                return PreparedSourceCollection(
                    "isyatirim",
                    request,
                    raw_existing=existing,
                    metrics={"cache_hit_count": 1},
                    operational_hint_date=(
                        first_observed_hint.isoformat()
                        if first_observed_hint is not None
                        else ""
                    ),
                )

        before = _isyatirim_metric_counters(self.isyatirim_client)
        frame: pd.DataFrame | None = None
        previous_refresh = getattr(self.isyatirim_client, "refresh_cache", False)
        if hasattr(self.isyatirim_client, "refresh_cache"):
            self.isyatirim_client.refresh_cache = bool(refresh)
        try:
            kwargs: dict[str, Any] = {}
            if security_budget_seconds is not None:
                kwargs.update(
                    {
                        "security_budget_seconds": security_budget_seconds,
                        "security_started_at": security_started_at,
                        "collection_pass": collection_pass,
                        "security_id": security_id,
                        "manifest_position": manifest_position,
                        "manifest_total": manifest_total,
                    }
                )
            if first_observed_hint is not None and _accepts_keyword(
                self.isyatirim_client.fetch_history, "first_observed_hint"
            ):
                kwargs["first_observed_hint"] = first_observed_hint
            frame = self.isyatirim_client.fetch_history(
                ticker, start_date, end_date, **kwargs
            )
            if not frame.empty:
                _require_columns(
                    frame,
                    ISYATIRIM_SNAPSHOT_REQUIRED_COLUMNS,
                    source="İş Yatırım",
                    ticker=ticker,
                )
        except IsYatirimFetchError as error:
            budget_exceeded = isinstance(error, IsYatirimBudgetFetchError) or any(
                item.error_type == TIME_BUDGET_EXCEEDED for item in error.failures
            )
            failure_class = (
                TIME_BUDGET_EXCEEDED if budget_exceeded else type(error).__name__
            )
            gaps = tuple(
                ProviderGap(
                    start_date=item.start_date.isoformat(),
                    end_date=item.end_date.isoformat(),
                    failure_class=item.error_type,
                    failure_reason=item.message,
                    retry_recommended=item.error_type != "IsYatirimSchemaError",
                )
                for item in error.failures
            )
            return PreparedSourceCollection(
                "isyatirim",
                request,
                raw_error=error,
                raw_partial_data=error.partial_data,
                missing_ranges=gaps,
                metrics=_metric_delta(
                    before, _isyatirim_metric_counters(self.isyatirim_client)
                ),
                retry_recommended=any(item.retry_recommended for item in gaps),
                operational_hint_date=(
                    first_observed_hint.isoformat()
                    if first_observed_hint is not None
                    else ""
                ),
            )
        except Exception as error:
            gap = ProviderGap(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                failure_class=type(error).__name__,
                failure_reason=str(error),
                retry_recommended=not isinstance(
                    error, (IsYatirimSchemaError, ValueError)
                ),
            )
            return PreparedSourceCollection(
                "isyatirim",
                request,
                raw_error=error,
                raw_partial_data=frame,
                missing_ranges=(gap,),
                metrics=_metric_delta(
                    before, _isyatirim_metric_counters(self.isyatirim_client)
                ),
                retry_recommended=gap.retry_recommended,
                operational_hint_date=(
                    first_observed_hint.isoformat()
                    if first_observed_hint is not None
                    else ""
                ),
            )
        finally:
            if hasattr(self.isyatirim_client, "refresh_cache"):
                self.isyatirim_client.refresh_cache = previous_refresh

        metrics = _metric_delta(
            before, _isyatirim_metric_counters(self.isyatirim_client)
        )
        if frame is None or frame.empty:
            return PreparedSourceCollection(
                "isyatirim",
                request,
                raw_frame=pd.DataFrame(),
                metrics=metrics,
                result=NO_DATA_IN_RANGE,
                operational_hint_date=(
                    first_observed_hint.isoformat()
                    if first_observed_hint is not None
                    else ""
                ),
            )
        return PreparedSourceCollection(
            "isyatirim",
            request,
            raw_frame=frame,
            metrics=metrics,
            operational_hint_date=(
                first_observed_hint.isoformat()
                if first_observed_hint is not None
                else ""
            ),
        )

    def prepare_yfinance(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
    ) -> PreparedSourceCollection:
        """Fetch/normalize yFinance data without writing shared snapshots."""

        ticker = normalize_ticker(ticker)
        raw_request = self.yfinance_raw_request(ticker, start_date, end_date)
        raw_existing = (
            None if refresh else self.snapshot_store.find_usable_snapshot(raw_request)
        )
        if raw_existing is not None:
            prepared = self.snapshot_store.read_dataframe(raw_existing)
            raw = _prepared_yfinance_provider_frame(prepared)
            hint = _first_observed_date(prepared)
            derived_request = self.yfinance_nominal_request(
                ticker, start_date, end_date, raw_existing.snapshot_id
            )
            derived_existing = self.snapshot_store.find_usable_snapshot(
                derived_request
            )
            if derived_existing is not None:
                return PreparedSourceCollection(
                    "yfinance",
                    raw_request,
                    raw_existing=raw_existing,
                    derived_existing=derived_existing,
                    metrics={"cache_hit_count": 2},
                    operational_hint_date=hint,
                )
            try:
                nominal = nominal_ohlc_snapshot_frame(
                    normalize_yfinance_history(raw, ticker)
                )
            except Exception as error:
                return PreparedSourceCollection(
                    "yfinance",
                    raw_request,
                    raw_existing=raw_existing,
                    derived_error=error,
                    metrics={"cache_hit_count": 1},
                    retry_recommended=True,
                    operational_hint_date=hint,
                )
            return PreparedSourceCollection(
                "yfinance",
                raw_request,
                raw_existing=raw_existing,
                derived_frame=nominal,
                metrics={"cache_hit_count": 1},
                operational_hint_date=hint,
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
        except Exception as error:
            partial = (
                prepare_raw_yfinance_history(raw, ticker)
                if raw is not None and not raw.empty
                else None
            )
            return PreparedSourceCollection(
                "yfinance",
                raw_request,
                raw_error=error,
                raw_partial_data=partial,
                missing_ranges=(
                    ProviderGap(
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        failure_class=type(error).__name__,
                        failure_reason=str(error),
                        retry_recommended=not isinstance(error, ValueError),
                    ),
                ),
                metrics=dict(self._last_yfinance_metrics),
                retry_recommended=not isinstance(error, ValueError),
            )
        hint = _first_observed_date(prepared)
        try:
            nominal = nominal_ohlc_snapshot_frame(
                normalize_yfinance_history(raw, ticker)
            )
        except Exception as error:
            return PreparedSourceCollection(
                "yfinance",
                raw_request,
                raw_frame=prepared,
                derived_error=error,
                metrics=dict(self._last_yfinance_metrics),
                retry_recommended=True,
                operational_hint_date=hint,
            )
        return PreparedSourceCollection(
            "yfinance",
            raw_request,
            raw_frame=prepared,
            derived_frame=nominal,
            metrics=dict(self._last_yfinance_metrics),
            operational_hint_date=hint,
        )

    def prepare_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        isyatirim_security_budget_seconds: float | None = None,
        isyatirim_security_started_at: float | None = None,
        collection_pass: int = 1,
        security_id: str = "",
        manifest_position: int = 0,
        manifest_total: int = 0,
    ) -> PreparedTickerCollection:
        """Prepare both providers; yFinance first date is only an ordering hint."""

        normalized = normalize_ticker(ticker)
        yfinance = self.prepare_yfinance(
            normalized, start_date, end_date, refresh=refresh
        )
        hint = (
            date.fromisoformat(yfinance.operational_hint_date)
            if yfinance.operational_hint_date
            else None
        )
        isyatirim = self.prepare_isyatirim(
            normalized,
            start_date,
            end_date,
            refresh=refresh,
            security_budget_seconds=isyatirim_security_budget_seconds,
            security_started_at=isyatirim_security_started_at,
            collection_pass=collection_pass,
            security_id=security_id,
            manifest_position=manifest_position,
            manifest_total=manifest_total,
            first_observed_hint=hint,
        )
        return PreparedTickerCollection(normalized, (isyatirim, yfinance))

    def commit_prepared_ticker(
        self, prepared: PreparedTickerCollection
    ) -> TickerCollectionResult:
        """Single-writer commit boundary for one fully prepared ticker result."""

        committed = tuple(
            self._commit_prepared_source(item) for item in prepared.source_results
        )
        return TickerCollectionResult(prepared.ticker, committed)

    def _commit_prepared_source(
        self, prepared: PreparedSourceCollection
    ) -> SourceCollectionResult:
        if prepared.source == "isyatirim":
            if prepared.raw_existing is not None:
                return SourceCollectionResult(
                    "isyatirim",
                    prepared.raw_existing,
                    metrics=prepared.metrics,
                    result=prepared.result,
                    operational_hint_date=prepared.operational_hint_date,
                )
            if prepared.result == NO_DATA_IN_RANGE and prepared.raw_error is None:
                return SourceCollectionResult(
                    "isyatirim",
                    None,
                    metrics=prepared.metrics,
                    result=NO_DATA_IN_RANGE,
                    operational_hint_date=prepared.operational_hint_date,
                )
            if prepared.raw_error is not None:
                written = self.snapshot_store.record_failed_attempt(
                    prepared.raw_request,
                    prepared.raw_error,
                    partial_data=prepared.raw_partial_data,
                )
                failure_class = (
                    TIME_BUDGET_EXCEEDED
                    if isinstance(prepared.raw_error, IsYatirimBudgetFetchError)
                    or any(
                        item.failure_class == TIME_BUDGET_EXCEEDED
                        for item in prepared.missing_ranges
                    )
                    else type(prepared.raw_error).__name__
                )
                return SourceCollectionResult(
                    "isyatirim",
                    written.metadata,
                    failure_class=failure_class,
                    failure_reason=str(prepared.raw_error),
                    missing_ranges=prepared.missing_ranges,
                    metrics=prepared.metrics,
                    retry_recommended=prepared.retry_recommended,
                    operational_hint_date=prepared.operational_hint_date,
                )
            assert prepared.raw_frame is not None and not prepared.raw_frame.empty
            written = self.snapshot_store.save_dataframe(
                prepared.raw_frame, prepared.raw_request
            )
            return SourceCollectionResult(
                "isyatirim",
                written.metadata,
                metrics=prepared.metrics,
                operational_hint_date=prepared.operational_hint_date,
            )

        if prepared.source != "yfinance":
            raise ValueError(f"unsupported prepared source: {prepared.source}")
        if prepared.raw_error is not None:
            written = self.snapshot_store.record_failed_attempt(
                prepared.raw_request,
                prepared.raw_error,
                partial_data=prepared.raw_partial_data,
            )
            return SourceCollectionResult(
                "yfinance",
                written.metadata,
                failure_class=type(prepared.raw_error).__name__,
                failure_reason=str(prepared.raw_error),
                missing_ranges=prepared.missing_ranges,
                metrics=prepared.metrics,
                retry_recommended=prepared.retry_recommended,
            )
        if prepared.raw_existing is not None:
            raw_metadata = prepared.raw_existing
        else:
            assert prepared.raw_frame is not None
            raw_metadata = self.snapshot_store.save_dataframe(
                prepared.raw_frame, prepared.raw_request
            ).metadata
        derived_request = self.yfinance_nominal_request(
            prepared.raw_request.ticker_or_instrument,
            prepared.raw_request.request_start_date,
            prepared.raw_request.request_end_date,
            raw_metadata.snapshot_id,
        )
        if prepared.derived_existing is not None:
            derived_metadata = prepared.derived_existing
            failure_class = None
            failure_reason = None
        elif prepared.derived_error is not None:
            derived_metadata = self.snapshot_store.record_failed_attempt(
                derived_request, prepared.derived_error
            ).metadata
            failure_class = type(prepared.derived_error).__name__
            failure_reason = str(prepared.derived_error)
        else:
            assert prepared.derived_frame is not None
            derived_metadata = self.snapshot_store.save_dataframe(
                prepared.derived_frame, derived_request
            ).metadata
            failure_class = None
            failure_reason = None
        return SourceCollectionResult(
            "yfinance",
            raw_metadata,
            (derived_metadata,),
            failure_class=failure_class,
            failure_reason=failure_reason,
            missing_ranges=prepared.missing_ranges,
            metrics=prepared.metrics,
            retry_recommended=prepared.retry_recommended,
            operational_hint_date=prepared.operational_hint_date,
        )

    def collect_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        isyatirim_security_budget_seconds: float | None = None,
        isyatirim_security_started_at: float | None = None,
        collection_pass: int = 1,
        security_id: str = "",
        manifest_position: int = 0,
        manifest_total: int = 0,
    ) -> TickerCollectionResult:
        """Prepare both providers, then commit them through this single writer."""

        prepared = self.prepare_ticker(
            ticker,
            start_date,
            end_date,
            refresh=refresh,
            isyatirim_security_budget_seconds=isyatirim_security_budget_seconds,
            isyatirim_security_started_at=isyatirim_security_started_at,
            collection_pass=collection_pass,
            security_id=security_id,
            manifest_position=manifest_position,
            manifest_total=manifest_total,
        )
        return self.commit_prepared_ticker(prepared)

    def collect_many(
        self,
        tickers: Iterable[str],
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
    ) -> tuple[TickerCollectionResult, ...]:
        if self.ticker_mapping is not None:
            periods = plan_active_ticker_collection(
                tickers,
                start_date,
                end_date,
                self.ticker_mapping,
            )
            return tuple(
                self.collect_ticker(
                    period.ticker,
                    period.start_date,
                    period.end_date,
                    refresh=refresh,
                )
                for period in periods
            )
        return tuple(
            self.collect_ticker(
                ticker, start_date, end_date, refresh=refresh
            )
            for ticker in tickers
        )

    def isyatirim_request(
        self, ticker: str, start_date: date, end_date: date
    ) -> SnapshotRequest:
        ticker = normalize_ticker(ticker)
        return SnapshotRequest(
            source="isyatirim",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={"endpoint": "HisseTekil", "inclusive_end": True},
            provider_library_version=self.isyatirim_version,
            code_commit_sha=self.code_commit_sha,
            layer="raw",
            identity_columns=("HGDG_HS_KODU", "HGDG_TARIH"),
        )

    def yfinance_raw_request(
        self, ticker: str, start_date: date, end_date: date
    ) -> SnapshotRequest:
        ticker = normalize_ticker(ticker)
        return SnapshotRequest(
            source="yfinance",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={
                "provider_ticker": f"{ticker}.IS",
                "auto_adjust": False,
                "actions": True,
                "inclusive_end": True,
            },
            provider_library_version=self.yfinance_version,
            code_commit_sha=self.code_commit_sha,
            layer="raw",
            identity_columns=("ticker", "date"),
        )

    def yfinance_nominal_request(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        raw_snapshot_id: str,
    ) -> SnapshotRequest:
        ticker = normalize_ticker(ticker)
        return SnapshotRequest(
            source="yfinance",
            dataset_type="nominal_ohlc",
            ticker_or_instrument=ticker,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={"normalization_decision": "D024", "version": "v1"},
            provider_library_version=self.yfinance_version,
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=(raw_snapshot_id,),
            identity_columns=("ticker", "date"),
        )

    def _fetch_yfinance_with_retry(
        self, ticker: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        settings = self.config.yfinance
        last_error: Exception | None = None
        self._last_yfinance_metrics = {
            "network_request_count": 0,
            "cache_hit_count": 0,
            "retry_count": 0,
            "timeout_count": 0,
        }
        for attempt in range(1, settings.max_retries + 1):
            try:
                self._last_yfinance_metrics["network_request_count"] += 1
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
                if isinstance(error, TimeoutError):
                    self._last_yfinance_metrics["timeout_count"] += 1
                if attempt < settings.max_retries:
                    self._last_yfinance_metrics["retry_count"] += 1
                    self.sleep_func(settings.retry_backoff_seconds * attempt)
        assert last_error is not None
        raise RuntimeError(
            f"yFinance failed for {ticker} after {settings.max_retries} attempts: "
            f"{last_error}"
        ) from last_error

    def _log(self, message: str) -> None:
        if self.progress_func is not None:
            self.progress_func(message)


def _isyatirim_metric_counters(client: object) -> dict[str, int | float]:
    stats = getattr(client, "stats", None)
    return {
        "network_request_count": int(getattr(stats, "network_requests", 0)),
        "cache_hit_count": int(getattr(stats, "cache_hits", 0)),
        "retry_count": int(getattr(stats, "retry_count", 0)),
        "timeout_count": int(getattr(stats, "timeout_count", 0)),
        "empty_range_count": int(getattr(stats, "no_data_range_count", 0)),
        "empty_range_cache_hit_count": int(
            getattr(stats, "empty_range_cache_hits", 0)
        ),
    }


def _metric_delta(
    before: Mapping[str, int | float], after: Mapping[str, int | float]
) -> dict[str, int | float]:
    return {
        key: max(0, float(after.get(key, 0)) - float(before.get(key, 0)))
        for key in after
    }


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


def _prepared_yfinance_provider_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Restore the provider-shaped frame from an immutable prepared raw snapshot."""

    missing = {"ticker", "date", *YFINANCE_REQUIRED_COLUMNS}.difference(frame.columns)
    if missing:
        raise ValueError(
            f"stored yFinance raw snapshot fields missing: {sorted(missing)}"
        )
    restored = frame.drop(columns=["ticker"]).copy()
    restored["date"] = pd.to_datetime(restored["date"], errors="raise")
    return restored.set_index("date")


def _first_observed_date(frame: pd.DataFrame) -> str:
    if "date" not in frame.columns or frame.empty:
        return ""
    values = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if values.empty:
        return ""
    return values.min().date().isoformat()


def _accepts_keyword(function: Callable[..., Any], keyword: str) -> bool:
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        item.name == keyword or item.kind is inspect.Parameter.VAR_KEYWORD
        for item in parameters
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
