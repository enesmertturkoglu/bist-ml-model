"""Resilient, sequential client for İş Yatırım historical stock data.

The installed ``isyatirimhisse`` package hard-codes a ten-second timeout. This
module intentionally leaves that package untouched and reproduces its public
endpoint/response parsing with configurable timeouts, retry/backoff, adaptive
date chunks and an operational local cache.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

import pandas as pd
import requests


BASE_URL = (
    "https://www.isyatirim.com.tr/_layouts/15/"
    "Isyatirim.Website/Common/Data.aspx/HisseTekil"
)
CACHE_SCHEMA_VERSION = "v2"
LEGACY_CACHE_SCHEMA_VERSIONS = ("v1",)
TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
IDENTITY_COLUMNS = {"HGDG_HS_KODU", "HGDG_TARIH"}
TIME_BUDGET_EXCEEDED = "TIME_BUDGET_EXCEEDED"
NO_DATA_IN_RANGE = "NO_DATA_IN_RANGE"
DATA_IN_RANGE = "DATA_IN_RANGE"

try:
    import truststore

    truststore.inject_into_ssl()
    DEFAULT_SSL_VERIFY = True
except ImportError:  # pragma: no cover - depends on the local Python runtime
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    DEFAULT_SSL_VERIFY = False


class HttpGetter(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


class IsYatirimClientError(RuntimeError):
    """Base exception for repo-local İş Yatırım access errors."""


class IsYatirimSchemaError(IsYatirimClientError):
    """A permanent response-schema problem that must not be retried."""


class TransientProviderError(IsYatirimClientError):
    """A provider response that can reasonably succeed on a later attempt."""


class IsYatirimTimeBudgetExceeded(IsYatirimClientError):
    """Raised when a security-wide collection budget prevents a new request."""


@dataclass
class RequestFailure:
    ticker: str
    start_date: date
    end_date: date
    attempts: int
    chunk_months: int
    error_type: str
    message: str
    cache_used: bool

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["start_date"] = self.start_date.isoformat()
        result["end_date"] = self.end_date.isoformat()
        return result

    def format(self) -> str:
        return (
            f"ticker={self.ticker}; start={self.start_date.isoformat()}; "
            f"end={self.end_date.isoformat()}; attempts={self.attempts}; "
            f"chunk_months={self.chunk_months}; error_type={self.error_type}; "
            f"cache_used={str(self.cache_used).lower()}; error={self.message}"
        )


@dataclass
class CacheIssue:
    path: str
    error_type: str
    message: str


@dataclass
class ClientStats:
    configured_timeout_seconds: float = 60.0
    configured_max_retries: int = 5
    configured_minimum_chunk_months: int = 3
    configured_request_delay_seconds: float = 1.0
    network_requests: int = 0
    cache_hits: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    connection_error_count: int = 0
    http_429_count: int = 0
    http_5xx_count: int = 0
    yearly_requests: int = 0
    six_month_requests: int = 0
    three_month_requests: int = 0
    split_to_six_month_count: int = 0
    split_to_three_month_count: int = 0
    timeout_recovered_chunks: int = 0
    failed_chunks: int = 0
    successful_network_chunks: int = 0
    no_data_range_count: int = 0
    empty_range_cache_hits: int = 0
    cache_corruption_count: int = 0
    time_budget_exceeded_count: int = 0
    failures: list[RequestFailure] = field(default_factory=list)
    cache_issues: list[CacheIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["failures"] = [failure.as_dict() for failure in self.failures]
        return result


class IsYatirimFetchError(IsYatirimClientError):
    """Raised after all adaptive chunks finish with one or more failures."""

    def __init__(
        self,
        failures: Iterable[RequestFailure],
        *,
        partial_data: pd.DataFrame | None = None,
    ) -> None:
        self.failures = list(failures)
        self.partial_data = (
            partial_data.copy() if partial_data is not None else pd.DataFrame()
        )
        super().__init__(" | ".join(failure.format() for failure in self.failures))


class IsYatirimBudgetFetchError(IsYatirimFetchError):
    """A fetch stopped because its shared security budget was exhausted."""


@dataclass
class _AttemptFailure(Exception):
    error: Exception
    attempts: int
    saw_timeout: bool
    allow_adaptive_split: bool


@dataclass
class _SecurityBudget:
    started_at: float
    seconds: float
    monotonic_func: Callable[[], float]
    excluded_seconds: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        return max(
            0.0,
            float(self.monotonic_func()) - self.started_at - self.excluded_seconds,
        )

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.seconds - self.elapsed_seconds)

    @property
    def exhausted(self) -> bool:
        return self.elapsed_seconds >= self.seconds

    def exclude(self, seconds: float) -> None:
        """Exclude successful empty-response time from the security budget."""

        self.excluded_seconds += max(0.0, float(seconds))


@dataclass(frozen=True)
class _ProgressContext:
    collection_pass: int
    security_id: str
    manifest_position: int
    manifest_total: int


class GlobalRequestLimiter:
    """Process-wide İş Yatırım concurrency and request-start pacing gate."""

    def __init__(
        self,
        *,
        max_concurrency: int,
        request_interval_seconds: float,
        monotonic_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        self.max_concurrency = int(max_concurrency)
        self.request_interval_seconds = float(request_interval_seconds)
        self.monotonic_func = monotonic_func
        self.sleep_func = sleep_func
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._pacing_lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self._next_request_at = 0.0
        self._active_requests = 0
        self._maximum_active_requests = 0

    @property
    def maximum_active_requests(self) -> int:
        with self._counter_lock:
            return self._maximum_active_requests

    @contextmanager
    def slot(
        self, *, sleep_func: Callable[[float], None] | None = None
    ) -> Iterable[None]:
        """Yield one globally paced/concurrency-bounded request slot."""

        sleeper = sleep_func or self.sleep_func
        with self._pacing_lock:
            now = float(self.monotonic_func())
            delay = max(0.0, self._next_request_at - now)
            if delay:
                sleeper(delay)
            paced_at = float(self.monotonic_func())
            self._next_request_at = (
                max(self._next_request_at, paced_at)
                + self.request_interval_seconds
            )
        self._semaphore.acquire()
        try:
            with self._counter_lock:
                self._active_requests += 1
                self._maximum_active_requests = max(
                    self._maximum_active_requests, self._active_requests
                )
            yield
        finally:
            with self._counter_lock:
                self._active_requests -= 1
            self._semaphore.release()


def _coerce_date(value: date | str | pd.Timestamp) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(value.day, last_day))


def split_date_range(start: date, end: date, months: int) -> list[tuple[date, date]]:
    """Split an inclusive date range without gaps or duplicate boundary days."""
    if months < 1:
        raise ValueError("months must be positive")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        next_cursor = _add_months(cursor, months)
        if next_cursor <= cursor:  # defensive guard around unusual date arithmetic
            raise RuntimeError("date chunking did not advance")
        chunk_end = min(end, next_cursor - timedelta(days=1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _merge_frames(frames: Iterable[pd.DataFrame], start: date, end: date) -> pd.DataFrame:
    usable = [frame.copy() for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame()
    combined = pd.concat(usable, ignore_index=True, sort=False)
    if "HGDG_TARIH" not in combined or "HGDG_HS_KODU" not in combined:
        raise IsYatirimSchemaError(
            "Combined response lacks HGDG_HS_KODU or HGDG_TARIH"
        )
    combined["HGDG_TARIH"] = pd.to_datetime(
        combined["HGDG_TARIH"], errors="raise", dayfirst=True
    ).dt.normalize()
    lower = pd.Timestamp(start)
    upper = pd.Timestamp(end)
    combined = combined[combined["HGDG_TARIH"].between(lower, upper, inclusive="both")]
    return (
        combined.sort_values(["HGDG_HS_KODU", "HGDG_TARIH"])
        .drop_duplicates(["HGDG_HS_KODU", "HGDG_TARIH"], keep="last")
        .reset_index(drop=True)
    )


class IsYatirimClient:
    """Sequential historical-data client with adaptive chunks and cache."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        max_retries: int = 5,
        minimum_chunk_months: int = 3,
        request_delay_seconds: float = 1.0,
        cache_dir: Path | str = Path(".cache/source_acceptance/isyatirim"),
        refresh_cache: bool = False,
        session: HttpGetter | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        random_func: Callable[[], float] = random.random,
        backoff_base_seconds: float = 1.0,
        backoff_cap_seconds: float = 30.0,
        jitter_max_seconds: float = 0.5,
        ssl_verify: bool = DEFAULT_SSL_VERIFY,
        monotonic_func: Callable[[], float] = time.monotonic,
        progress_func: Callable[[str], None] | None = None,
        request_limiter: GlobalRequestLimiter | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 1:
            raise ValueError("max_retries must be at least one")
        if minimum_chunk_months not in {3, 6, 12}:
            raise ValueError("minimum_chunk_months must be 3, 6 or 12")
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative")
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.minimum_chunk_months = int(minimum_chunk_months)
        self.request_delay_seconds = float(request_delay_seconds)
        self.cache_dir = Path(cache_dir)
        self.refresh_cache = bool(refresh_cache)
        self.session = session or requests.Session()
        self.sleep_func = sleep_func
        self.random_func = random_func
        self.backoff_base_seconds = float(backoff_base_seconds)
        self.backoff_cap_seconds = float(backoff_cap_seconds)
        self.jitter_max_seconds = float(jitter_max_seconds)
        self.ssl_verify = ssl_verify
        self.monotonic_func = monotonic_func
        self.progress_func = progress_func
        self.request_limiter = request_limiter
        self._active_budget: _SecurityBudget | None = None
        self._progress_context: _ProgressContext | None = None
        self.stats = ClientStats(
            configured_timeout_seconds=self.timeout_seconds,
            configured_max_retries=self.max_retries,
            configured_minimum_chunk_months=self.minimum_chunk_months,
            configured_request_delay_seconds=self.request_delay_seconds,
        )
        self._cache_issue_paths: set[str] = set()

    def fetch_history(
        self,
        ticker: str,
        start_date: date | str | pd.Timestamp,
        end_date: date | str | pd.Timestamp,
        *,
        security_budget_seconds: float | None = None,
        security_started_at: float | None = None,
        collection_pass: int = 1,
        security_id: str = "",
        manifest_position: int = 0,
        manifest_total: int = 0,
        first_observed_hint: date | str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        if security_budget_seconds is not None and security_budget_seconds <= 0:
            raise ValueError("security_budget_seconds must be positive")

        previous_budget = self._active_budget
        previous_context = self._progress_context
        self._active_budget = (
            _SecurityBudget(
                started_at=(
                    float(security_started_at)
                    if security_started_at is not None
                    else float(self.monotonic_func())
                ),
                seconds=float(security_budget_seconds),
                monotonic_func=self.monotonic_func,
            )
            if security_budget_seconds is not None
            else None
        )
        self._progress_context = _ProgressContext(
            collection_pass=int(collection_pass),
            security_id=str(security_id),
            manifest_position=int(manifest_position),
            manifest_total=int(manifest_total),
        )
        try:
            frames: list[pd.DataFrame] = []
            failures: list[RequestFailure] = []
            annual_ranges = split_date_range(start, end, 12)
            if first_observed_hint is not None:
                hint = _coerce_date(first_observed_hint)
                containing = [
                    item for item in annual_ranges if item[0] <= hint <= item[1]
                ]
                if containing:
                    selected = containing[0]
                    earlier = [item for item in annual_ranges if item[1] < selected[0]]
                    later = [item for item in annual_ranges if item[0] > selected[1]]
                    annual_ranges = [selected, *reversed(earlier), *later]
                    self._log(
                        f"[ISYATIRIM][{ticker}] yFinance first-observation hint "
                        f"used={hint.isoformat()} verification_range="
                        f"{selected[0].isoformat()}..{selected[1].isoformat()}"
                    )
            for annual_index, (annual_start, annual_end) in enumerate(annual_ranges):
                cached_frames: list[pd.DataFrame] = []
                gaps = [(annual_start, annual_end)]
                cache_used = False
                if not self.refresh_cache:
                    cached_frames, gaps, cache_used = self._load_cached_coverage(
                        ticker, annual_start, annual_end
                    )
                    frames.extend(cached_frames)
                for gap_index, (gap_start, gap_end) in enumerate(gaps):
                    try:
                        frames.extend(
                            self._fetch_range(
                                ticker,
                                gap_start,
                                gap_end,
                                chunk_months=12,
                                inherited_timeout=False,
                                cache_used=cache_used,
                            )
                        )
                    except IsYatirimBudgetFetchError as error:
                        failures.extend(error.failures)
                        if not error.partial_data.empty:
                            frames.append(error.partial_data)
                        failures.extend(
                            self._unattempted_budget_failures(
                                ticker,
                                gaps[gap_index + 1 :],
                                chunk_months=12,
                                cache_used=cache_used,
                            )
                        )
                        for pending_start, pending_end in annual_ranges[
                            annual_index + 1 :
                        ]:
                            pending_cached: list[pd.DataFrame] = []
                            pending_gaps = [(pending_start, pending_end)]
                            pending_cache_used = False
                            if not self.refresh_cache:
                                (
                                    pending_cached,
                                    pending_gaps,
                                    pending_cache_used,
                                ) = self._load_cached_coverage(
                                    ticker, pending_start, pending_end
                                )
                                frames.extend(pending_cached)
                            failures.extend(
                                self._unattempted_budget_failures(
                                    ticker,
                                    pending_gaps,
                                    chunk_months=12,
                                    cache_used=pending_cache_used,
                                )
                            )
                        combined = _merge_frames(frames, start, end)
                        raise IsYatirimBudgetFetchError(
                            failures, partial_data=combined
                        ) from error
                    except IsYatirimFetchError as error:
                        failures.extend(error.failures)
                        if not error.partial_data.empty:
                            frames.append(error.partial_data)

            combined = _merge_frames(frames, start, end)
            if failures:
                raise IsYatirimFetchError(failures, partial_data=combined)
            if combined.empty:
                combined.attrs["result"] = NO_DATA_IN_RANGE
            return combined
        finally:
            self._active_budget = previous_budget
            self._progress_context = previous_context

    def _fetch_range(
        self,
        ticker: str,
        start: date,
        end: date,
        *,
        chunk_months: int,
        inherited_timeout: bool,
        cache_used: bool,
    ) -> list[pd.DataFrame]:
        try:
            frame, saw_timeout = self._request_with_retries(
                ticker, start, end, chunk_months=chunk_months
            )
        except IsYatirimTimeBudgetExceeded as error:
            failure = RequestFailure(
                ticker=ticker,
                start_date=start,
                end_date=end,
                attempts=0,
                chunk_months=chunk_months,
                error_type=TIME_BUDGET_EXCEEDED,
                message=str(error),
                cache_used=cache_used,
            )
            self.stats.failed_chunks += 1
            self.stats.time_budget_exceeded_count += 1
            self.stats.failures.append(failure)
            self._log(
                f"[ISYATIRIM][{ticker}] security budget aşıldı "
                f"failure_class={TIME_BUDGET_EXCEEDED} {self._timing_text()}"
            )
            raise IsYatirimBudgetFetchError([failure]) from error
        except IsYatirimClientError as error:
            failure = RequestFailure(
                ticker=ticker,
                start_date=start,
                end_date=end,
                attempts=1,
                chunk_months=chunk_months,
                error_type=type(error).__name__,
                message=str(error),
                cache_used=cache_used,
            )
            self.stats.failed_chunks += 1
            self.stats.failures.append(failure)
            raise IsYatirimFetchError([failure]) from error
        except _AttemptFailure as attempt_failure:
            next_months = (
                self._next_chunk_months(chunk_months)
                if attempt_failure.allow_adaptive_split
                else None
            )
            if next_months is None:
                failure = RequestFailure(
                    ticker=ticker,
                    start_date=start,
                    end_date=end,
                    attempts=attempt_failure.attempts,
                    chunk_months=chunk_months,
                    error_type=type(attempt_failure.error).__name__,
                    message=str(attempt_failure.error),
                    cache_used=cache_used,
                )
                self.stats.failed_chunks += 1
                self.stats.failures.append(failure)
                raise IsYatirimFetchError([failure]) from attempt_failure.error

            if next_months == 6:
                self.stats.split_to_six_month_count += 1
            elif next_months == 3:
                self.stats.split_to_three_month_count += 1
            self._log(
                f"[ISYATIRIM][{ticker}] {chunk_months}M başarısız, "
                f"{next_months}M chunklara bölünüyor "
                f"range={start.isoformat()}..{end.isoformat()} "
                f"failure_class={type(attempt_failure.error).__name__} "
                f"{self._timing_text()}"
            )

            child_frames: list[pd.DataFrame] = []
            child_failures: list[RequestFailure] = []
            child_ranges = split_date_range(start, end, next_months)
            for child_index, (child_start, child_end) in enumerate(child_ranges):
                try:
                    child_frames.extend(
                        self._fetch_range(
                            ticker,
                            child_start,
                            child_end,
                            chunk_months=next_months,
                            inherited_timeout=(
                                inherited_timeout or attempt_failure.saw_timeout
                            ),
                            cache_used=cache_used,
                        )
                    )
                except IsYatirimBudgetFetchError as child_error:
                    child_failures.extend(child_error.failures)
                    if not child_error.partial_data.empty:
                        child_frames.append(child_error.partial_data)
                    child_failures.extend(
                        self._unattempted_budget_failures(
                            ticker,
                            child_ranges[child_index + 1 :],
                            chunk_months=next_months,
                            cache_used=cache_used,
                        )
                    )
                    partial = _merge_frames(child_frames, start, end)
                    raise IsYatirimBudgetFetchError(
                        child_failures, partial_data=partial
                    ) from child_error
                except IsYatirimFetchError as child_error:
                    child_failures.extend(child_error.failures)
                    if not child_error.partial_data.empty:
                        child_frames.append(child_error.partial_data)
            partial = _merge_frames(child_frames, start, end)
            if child_failures:
                raise IsYatirimFetchError(child_failures, partial_data=partial)
            return child_frames

        self.stats.successful_network_chunks += 1
        if saw_timeout or inherited_timeout:
            self.stats.timeout_recovered_chunks += 1
        if frame.empty:
            self.stats.no_data_range_count += 1
            self._write_empty_cache(ticker, start, end)
            self._log(
                f"[ISYATIRIM][{ticker}][{start.isoformat()}..{end.isoformat()}] "
                f"{NO_DATA_IN_RANGE}; retry/split yapılmadı {self._timing_text()}"
            )
            return []
        self._write_cache(ticker, start, end, frame)
        return [frame]

    def _next_chunk_months(self, chunk_months: int) -> int | None:
        if chunk_months > 6 and self.minimum_chunk_months <= 6:
            return 6
        if chunk_months > 3 and self.minimum_chunk_months <= 3:
            return 3
        return None

    @staticmethod
    def _unattempted_budget_failures(
        ticker: str,
        ranges: Iterable[tuple[date, date]],
        *,
        chunk_months: int,
        cache_used: bool,
    ) -> list[RequestFailure]:
        return [
            RequestFailure(
                ticker=ticker,
                start_date=start,
                end_date=end,
                attempts=0,
                chunk_months=chunk_months,
                error_type=TIME_BUDGET_EXCEEDED,
                message="security budget exhausted before range was attempted",
                cache_used=cache_used,
            )
            for start, end in ranges
        ]

    def _request_with_retries(
        self, ticker: str, start: date, end: date, *, chunk_months: int
    ) -> tuple[pd.DataFrame, bool]:
        last_error: Exception | None = None
        saw_timeout = False
        saw_connection_error = False
        for attempt in range(1, self.max_retries + 1):
            self._ensure_budget_available(ticker, start, end, chunk_months)
            attempt_started_at = float(self.monotonic_func())
            retry_after_seconds: float | None = None
            if attempt > 1:
                self.stats.retry_count += 1
            try:
                if self.request_limiter is None:
                    self._pace_request()
                request_slot = (
                    self.request_limiter.slot(sleep_func=self._sleep_with_budget)
                    if self.request_limiter is not None
                    else nullcontext()
                )
                with request_slot:
                    self._ensure_budget_available(ticker, start, end, chunk_months)
                    self._count_request_size(chunk_months)
                    self.stats.network_requests += 1
                    self._log(
                        f"[ISYATIRIM][{ticker}][{start.isoformat()}..{end.isoformat()}]"
                        f"[{chunk_months}M] request başladı "
                        f"attempt={attempt}/{self.max_retries} {self._timing_text()}"
                    )
                    response = self.session.get(
                        BASE_URL,
                        params={
                            "hisse": ticker,
                            "startdate": start.strftime("%d-%m-%Y"),
                            "enddate": end.strftime("%d-%m-%Y"),
                        },
                        timeout=(10, self.timeout_seconds),
                        verify=self.ssl_verify,
                    )
                status_code = int(getattr(response, "status_code", 200))
                if status_code in TRANSIENT_HTTP_STATUS_CODES:
                    if status_code == 429:
                        self.stats.http_429_count += 1
                    else:
                        self.stats.http_5xx_count += 1
                    error = requests.HTTPError(
                        f"HTTP {status_code} from İş Yatırım",
                        response=response,
                    )
                    retry_after_seconds = self._retry_after_seconds(response)
                    raise TransientProviderError(str(error)) from error
                response.raise_for_status()
                frame = self._parse_response(response, ticker, start, end)
                if frame.empty and self._active_budget is not None:
                    self._active_budget.exclude(
                        float(self.monotonic_func()) - attempt_started_at
                    )
                return frame, saw_timeout
            except requests.Timeout as error:
                self.stats.timeout_count += 1
                saw_timeout = True
                last_error = error
            except requests.ConnectionError as error:
                self.stats.connection_error_count += 1
                saw_connection_error = True
                last_error = error
            except TransientProviderError as error:
                last_error = error
            except IsYatirimSchemaError:
                raise
            except requests.RequestException as error:
                raise IsYatirimClientError(str(error)) from error

            if attempt < self.max_retries:
                if self._budget_exhausted():
                    raise IsYatirimTimeBudgetExceeded(
                        f"security budget exhausted before retry {attempt + 1}/{self.max_retries}"
                    )
                error_class = (
                    "timeout" if isinstance(last_error, requests.Timeout) else type(last_error).__name__
                )
                self._log(
                    f"[ISYATIRIM][{ticker}][{start.isoformat()}..{end.isoformat()}] "
                    f"{error_class}, retry {attempt + 1}/{self.max_retries} "
                    f"{self._timing_text()}"
                )
                backoff = min(
                    self.backoff_base_seconds * (2 ** (attempt - 1)),
                    self.backoff_cap_seconds,
                )
                if retry_after_seconds is not None:
                    backoff = max(backoff, retry_after_seconds)
                self._sleep_with_budget(backoff + self._jitter())
        assert last_error is not None
        raise _AttemptFailure(
            last_error,
            self.max_retries,
            saw_timeout,
            saw_timeout or saw_connection_error,
        )

    def _parse_response(
        self, response: Any, ticker: str, start: date, end: date
    ) -> pd.DataFrame:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise TransientProviderError(f"Invalid JSON response: {error}") from error
        if not isinstance(payload, dict):
            raise IsYatirimSchemaError("Response JSON must be an object")
        if "value" not in payload:
            raise TransientProviderError("Response JSON is missing the 'value' field")
        values = payload["value"]
        if not isinstance(values, list):
            raise IsYatirimSchemaError("Response 'value' field must be a list")
        if not values:
            empty = pd.DataFrame()
            empty.attrs["result"] = NO_DATA_IN_RANGE
            return empty
        frame = pd.DataFrame(values)
        missing = IDENTITY_COLUMNS.difference(frame.columns)
        if missing:
            raise IsYatirimSchemaError(
                f"Response rows are missing required columns: {sorted(missing)}"
            )
        try:
            frame["HGDG_TARIH"] = pd.to_datetime(
                frame["HGDG_TARIH"], errors="raise", dayfirst=True
            ).dt.normalize()
        except (TypeError, ValueError) as error:
            raise IsYatirimSchemaError(
                f"Response contains invalid HGDG_TARIH values: {error}"
            ) from error
        requested_ticker = frame["HGDG_HS_KODU"].astype(str).str.upper().eq(ticker)
        if not bool(requested_ticker.all()):
            raise IsYatirimSchemaError("Provider response contains an unexpected ticker")
        in_range = frame["HGDG_TARIH"].between(
            pd.Timestamp(start), pd.Timestamp(end), inclusive="both"
        )
        if not bool(in_range.any()):
            actual_start = frame["HGDG_TARIH"].min().date().isoformat()
            actual_end = frame["HGDG_TARIH"].max().date().isoformat()
            raise IsYatirimSchemaError(
                "Provider response is entirely outside the requested date range: "
                f"requested={start.isoformat()}..{end.isoformat()}; "
                f"actual={actual_start}..{actual_end}"
            )
        frame = frame.loc[in_range]
        return _merge_frames([frame], start, end)

    def _pace_request(self) -> None:
        if self.stats.network_requests:
            self._sleep_with_budget(self.request_delay_seconds + self._jitter())

    def _sleep_with_budget(self, seconds: float) -> None:
        delay = max(0.0, float(seconds))
        if self._active_budget is not None:
            delay = min(delay, self._active_budget.remaining_seconds)
        if delay > 0:
            self.sleep_func(delay)

    def _budget_exhausted(self) -> bool:
        return self._active_budget is not None and self._active_budget.exhausted

    def _ensure_budget_available(
        self,
        ticker: str,
        start: date,
        end: date,
        chunk_months: int,
    ) -> None:
        if self._budget_exhausted():
            raise IsYatirimTimeBudgetExceeded(
                f"{ticker} {start.isoformat()}..{end.isoformat()} {chunk_months}M "
                "request/retry was not started"
            )

    def _timing_text(self) -> str:
        if self._active_budget is None:
            return "elapsed_seconds=NA remaining_budget_seconds=NA"
        return (
            f"elapsed_seconds={self._active_budget.elapsed_seconds:.3f} "
            f"remaining_budget_seconds={self._active_budget.remaining_seconds:.3f}"
        )

    def _log(self, message: str) -> None:
        if self.progress_func is None:
            return
        context = self._progress_context
        suffix = ""
        if context is not None:
            suffix = (
                f" pass={context.collection_pass} security_id={context.security_id or 'NA'} "
                f"manifest_position={context.manifest_position}/{context.manifest_total}"
            )
        self.progress_func(message + suffix)

    def _jitter(self) -> float:
        value = float(self.random_func())
        if not math.isfinite(value):
            value = 0.0
        return min(max(value, 0.0), 1.0) * self.jitter_max_seconds

    def _count_request_size(self, chunk_months: int) -> None:
        if chunk_months >= 12:
            self.stats.yearly_requests += 1
        elif chunk_months >= 6:
            self.stats.six_month_requests += 1
        else:
            self.stats.three_month_requests += 1

    @staticmethod
    def _retry_after_seconds(response: Any) -> float | None:
        headers = getattr(response, "headers", {}) or {}
        raw = headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            try:
                parsed = datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S GMT").replace(
                    tzinfo=timezone.utc
                )
            except (TypeError, ValueError):
                return None
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())

    def _cache_paths(self, ticker: str, start: date, end: date) -> tuple[Path, Path]:
        stem = (
            f"{CACHE_SCHEMA_VERSION}_{ticker}_{start.isoformat()}_{end.isoformat()}"
        )
        return self.cache_dir / f"{stem}.csv", self.cache_dir / f"{stem}.json"

    def _write_cache(
        self, ticker: str, start: date, end: date, frame: pd.DataFrame
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data_path, metadata_path = self._cache_paths(ticker, start, end)
        data_temp: Path | None = None
        metadata_temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                suffix=".csv.tmp",
                dir=self.cache_dir,
                delete=False,
            ) as handle:
                data_temp = Path(handle.name)
                frame.to_csv(handle, index=False)
            digest = hashlib.sha256(data_temp.read_bytes()).hexdigest()
            metadata: dict[str, Any] = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
                "ticker": ticker,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "result": DATA_IN_RANGE,
                "schema_validation": {"status": "PASS"},
                "columns": list(frame.columns),
                "row_count": len(frame),
                "data_file": data_path.name,
                "sha256": digest,
            }
            metadata["checksum"] = self._metadata_checksum(metadata)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json.tmp",
                dir=self.cache_dir,
                delete=False,
            ) as handle:
                metadata_temp = Path(handle.name)
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
            os.replace(data_temp, data_path)
            data_temp = None
            os.replace(metadata_temp, metadata_path)
            metadata_temp = None
        finally:
            for path in (data_temp, metadata_temp):
                if path is not None and path.exists():
                    path.unlink()

    def _write_empty_cache(self, ticker: str, start: date, end: date) -> None:
        """Persist verified empty coverage without creating a training snapshot."""

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _, metadata_path = self._cache_paths(ticker, start, end)
        metadata: dict[str, Any] = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "result": NO_DATA_IN_RANGE,
            "schema_validation": {
                "status": "PASS",
                "http_status": 200,
                "json_object": True,
                "value_present": True,
                "value_is_list": True,
                "value_is_empty": True,
            },
        }
        metadata["checksum"] = self._metadata_checksum(metadata)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json.tmp",
                dir=self.cache_dir,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, metadata_path)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _load_cached_coverage(
        self, ticker: str, start: date, end: date
    ) -> tuple[list[pd.DataFrame], list[tuple[date, date]], bool]:
        if not self.cache_dir.exists():
            return [], [(start, end)], False
        entries: list[tuple[date, date, int, pd.DataFrame, str]] = []
        blocked_current_ranges: list[tuple[date, date]] = []
        versions = (CACHE_SCHEMA_VERSION, *LEGACY_CACHE_SCHEMA_VERSIONS)
        metadata_paths = sorted(
            {
                path
                for version in versions
                for path in self.cache_dir.glob(f"{version}_{ticker}_*.json")
            }
        )
        for metadata_path in metadata_paths:
            try:
                cache_start, cache_end, frame, result = self._read_cache_entry(
                    metadata_path
                )
            except Exception as error:
                self._record_cache_issue(metadata_path, error)
                if metadata_path.name.startswith(f"{CACHE_SCHEMA_VERSION}_"):
                    try:
                        invalid_metadata = json.loads(
                            metadata_path.read_text(encoding="utf-8")
                        )
                        if str(invalid_metadata.get("ticker", "")).upper() == ticker:
                            blocked_current_ranges.append(
                                (
                                    date.fromisoformat(
                                        str(invalid_metadata["start_date"])
                                    ),
                                    date.fromisoformat(str(invalid_metadata["end_date"])),
                                )
                            )
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        pass
                continue
            if cache_end < start or cache_start > end:
                continue
            version_priority = (
                0
                if metadata_path.name.startswith(f"{CACHE_SCHEMA_VERSION}_")
                else 1
            )
            entries.append(
                (cache_start, cache_end, version_priority, frame, result)
            )

        if not entries:
            return [], [(start, end)], False
        entries.sort(key=lambda item: (item[0], item[1], item[2]))
        frames: list[pd.DataFrame] = []
        gaps: list[tuple[date, date]] = []
        cursor = start
        used_cache = False
        for cache_start, cache_end, _, frame, result in entries:
            if any(
                blocked_start <= cache_end and blocked_end >= cache_start
                for blocked_start, blocked_end in blocked_current_ranges
            ):
                continue
            covered_start = max(start, cache_start)
            covered_end = min(end, cache_end)
            if covered_end < cursor:
                continue
            if covered_start > cursor:
                gaps.append((cursor, covered_start - timedelta(days=1)))
            if not frame.empty:
                frames.append(frame)
            self.stats.cache_hits += 1
            used_cache = True
            if result == NO_DATA_IN_RANGE:
                self.stats.empty_range_cache_hits += 1
            self._log(
                f"[ISYATIRIM][{ticker}][{covered_start.isoformat()}.."
                f"{covered_end.isoformat()}] cache hit {self._timing_text()}"
            )
            cursor = max(cursor, covered_end + timedelta(days=1))
            if cursor > end:
                break
        if cursor <= end:
            gaps.append((cursor, end))
        return frames, gaps, used_cache

    def _read_cache_entry(
        self, metadata_path: Path
    ) -> tuple[date, date, pd.DataFrame, str]:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        version = str(metadata.get("cache_schema_version", ""))
        if version not in {CACHE_SCHEMA_VERSION, *LEGACY_CACHE_SCHEMA_VERSIONS}:
            raise ValueError("cache schema version mismatch")
        required = {
            "ticker",
            "start_date",
            "end_date",
        }
        missing = required.difference(metadata)
        if missing:
            raise ValueError(f"cache metadata fields missing: {sorted(missing)}")
        if version == CACHE_SCHEMA_VERSION:
            required_v2 = {
                "fetch_timestamp",
                "result",
                "schema_validation",
                "checksum",
            }
            missing_v2 = required_v2.difference(metadata)
            if missing_v2:
                raise ValueError(
                    f"cache v2 metadata fields missing: {sorted(missing_v2)}"
                )
            if metadata["checksum"] != self._metadata_checksum(metadata):
                raise ValueError("cache metadata checksum mismatch")
            validation = metadata["schema_validation"]
            if not isinstance(validation, dict) or validation.get("status") != "PASS":
                raise ValueError("cache schema validation is not PASS")
        cache_start = date.fromisoformat(str(metadata["start_date"]))
        cache_end = date.fromisoformat(str(metadata["end_date"]))
        if cache_start > cache_end:
            raise ValueError("cache date range is reversed")
        result = str(metadata.get("result", DATA_IN_RANGE))
        if result == NO_DATA_IN_RANGE:
            return cache_start, cache_end, pd.DataFrame(), result
        if result != DATA_IN_RANGE:
            raise ValueError(f"unsupported cache result: {result}")
        data_required = {"columns", "row_count", "data_file", "sha256"}
        data_missing = data_required.difference(metadata)
        if data_missing:
            raise ValueError(f"cache data fields missing: {sorted(data_missing)}")
        data_path = metadata_path.parent / str(metadata["data_file"])
        if not data_path.is_file():
            raise FileNotFoundError(f"cache data file missing: {data_path.name}")
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        if digest != metadata["sha256"]:
            raise ValueError("cache data checksum mismatch")
        frame = pd.read_csv(data_path)
        if list(frame.columns) != metadata["columns"]:
            raise ValueError("cache column list mismatch")
        if len(frame) != int(metadata["row_count"]):
            raise ValueError("cache row count mismatch")
        if not IDENTITY_COLUMNS.issubset(frame.columns):
            raise ValueError("cache is missing identity columns")
        frame["HGDG_TARIH"] = pd.to_datetime(
            frame["HGDG_TARIH"], errors="raise"
        ).dt.normalize()
        tickers = frame["HGDG_HS_KODU"].astype(str).str.upper().unique().tolist()
        if tickers != [str(metadata["ticker"]).upper()]:
            raise ValueError("cache ticker identity mismatch")
        if not frame["HGDG_TARIH"].between(
            pd.Timestamp(cache_start), pd.Timestamp(cache_end), inclusive="both"
        ).all():
            raise ValueError("cache contains dates outside metadata coverage")
        return cache_start, cache_end, frame, result

    @staticmethod
    def _metadata_checksum(metadata: Mapping[str, Any]) -> str:
        payload = {key: value for key, value in metadata.items() if key != "checksum"}
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _record_cache_issue(self, path: Path, error: Exception) -> None:
        key = str(path.resolve())
        if key in self._cache_issue_paths:
            return
        self._cache_issue_paths.add(key)
        self.stats.cache_corruption_count += 1
        self.stats.cache_issues.append(
            CacheIssue(key, type(error).__name__, str(error))
        )


def fetch_isyatirim_history(
    ticker: str,
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    *,
    timeout_seconds: float = 60.0,
    max_retries: int = 5,
    minimum_chunk_months: int = 3,
    request_delay_seconds: float = 1.0,
    cache_dir: Path | str = Path(".cache/source_acceptance/isyatirim"),
    refresh_cache: bool = False,
    **client_kwargs: Any,
) -> pd.DataFrame:
    """Convenience wrapper around :class:`IsYatirimClient`."""
    client = IsYatirimClient(
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        minimum_chunk_months=minimum_chunk_months,
        request_delay_seconds=request_delay_seconds,
        cache_dir=cache_dir,
        refresh_cache=refresh_cache,
        **client_kwargs,
    )
    return client.fetch_history(ticker, start_date, end_date)
