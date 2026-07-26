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
import time
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
CACHE_SCHEMA_VERSION = "v1"
TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
IDENTITY_COLUMNS = {"HGDG_HS_KODU", "HGDG_TARIH"}

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
    cache_corruption_count: int = 0
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


@dataclass
class _AttemptFailure(Exception):
    error: Exception
    attempts: int
    saw_timeout: bool


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
    ) -> pd.DataFrame:
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        if start > end:
            raise ValueError("start_date must be on or before end_date")

        frames: list[pd.DataFrame] = []
        failures: list[RequestFailure] = []
        for annual_start, annual_end in split_date_range(start, end, 12):
            cached_frames: list[pd.DataFrame] = []
            gaps = [(annual_start, annual_end)]
            if not self.refresh_cache:
                cached_frames, gaps = self._load_cached_coverage(
                    ticker, annual_start, annual_end
                )
                frames.extend(cached_frames)
            cache_used = bool(cached_frames)
            for gap_start, gap_end in gaps:
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
                except IsYatirimFetchError as error:
                    failures.extend(error.failures)
                    if not error.partial_data.empty:
                        frames.append(error.partial_data)

        combined = _merge_frames(frames, start, end)
        if failures:
            raise IsYatirimFetchError(failures, partial_data=combined)
        return combined

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
            next_months = self._next_chunk_months(chunk_months)
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

            child_frames: list[pd.DataFrame] = []
            child_failures: list[RequestFailure] = []
            for child_start, child_end in split_date_range(start, end, next_months):
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
        self._write_cache(ticker, start, end, frame)
        return [frame]

    def _next_chunk_months(self, chunk_months: int) -> int | None:
        if chunk_months > 6 and self.minimum_chunk_months <= 6:
            return 6
        if chunk_months > 3 and self.minimum_chunk_months <= 3:
            return 3
        return None

    def _request_with_retries(
        self, ticker: str, start: date, end: date, *, chunk_months: int
    ) -> tuple[pd.DataFrame, bool]:
        last_error: Exception | None = None
        saw_timeout = False
        for attempt in range(1, self.max_retries + 1):
            retry_after_seconds: float | None = None
            if attempt > 1:
                self.stats.retry_count += 1
            self._pace_request()
            self._count_request_size(chunk_months)
            self.stats.network_requests += 1
            try:
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
                return frame, saw_timeout
            except requests.Timeout as error:
                self.stats.timeout_count += 1
                saw_timeout = True
                last_error = error
            except requests.ConnectionError as error:
                self.stats.connection_error_count += 1
                last_error = error
            except TransientProviderError as error:
                last_error = error
            except IsYatirimSchemaError:
                raise
            except requests.RequestException as error:
                raise IsYatirimClientError(str(error)) from error

            if attempt < self.max_retries:
                backoff = min(
                    self.backoff_base_seconds * (2 ** (attempt - 1)),
                    self.backoff_cap_seconds,
                )
                if retry_after_seconds is not None:
                    backoff = max(backoff, retry_after_seconds)
                self.sleep_func(backoff + self._jitter())
        assert last_error is not None
        raise _AttemptFailure(last_error, self.max_retries, saw_timeout)

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
            raise TransientProviderError("Provider returned an empty 'value' list")
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
        frame = frame[
            frame["HGDG_TARIH"].between(
                pd.Timestamp(start), pd.Timestamp(end), inclusive="both"
            )
        ]
        if frame.empty:
            raise TransientProviderError(
                "Provider response has no rows inside the requested date range"
            )
        requested_ticker = frame["HGDG_HS_KODU"].astype(str).str.upper().eq(ticker)
        if not bool(requested_ticker.all()):
            raise IsYatirimSchemaError("Provider response contains an unexpected ticker")
        return _merge_frames([frame], start, end)

    def _pace_request(self) -> None:
        if self.stats.network_requests:
            self.sleep_func(self.request_delay_seconds + self._jitter())

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
            metadata = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticker": ticker,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "columns": list(frame.columns),
                "row_count": len(frame),
                "data_file": data_path.name,
                "sha256": digest,
            }
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

    def _load_cached_coverage(
        self, ticker: str, start: date, end: date
    ) -> tuple[list[pd.DataFrame], list[tuple[date, date]]]:
        if not self.cache_dir.exists():
            return [], [(start, end)]
        entries: list[tuple[date, date, pd.DataFrame]] = []
        pattern = f"{CACHE_SCHEMA_VERSION}_{ticker}_*.json"
        for metadata_path in sorted(self.cache_dir.glob(pattern)):
            try:
                cache_start, cache_end, frame = self._read_cache_entry(metadata_path)
            except Exception as error:
                self._record_cache_issue(metadata_path, error)
                continue
            if cache_end < start or cache_start > end:
                continue
            entries.append((cache_start, cache_end, frame))

        if not entries:
            return [], [(start, end)]
        entries.sort(key=lambda item: (item[0], item[1]))
        frames: list[pd.DataFrame] = []
        gaps: list[tuple[date, date]] = []
        cursor = start
        for cache_start, cache_end, frame in entries:
            covered_start = max(start, cache_start)
            covered_end = min(end, cache_end)
            if covered_end < cursor:
                continue
            if covered_start > cursor:
                gaps.append((cursor, covered_start - timedelta(days=1)))
            frames.append(frame)
            self.stats.cache_hits += 1
            cursor = max(cursor, covered_end + timedelta(days=1))
            if cursor > end:
                break
        if cursor <= end:
            gaps.append((cursor, end))
        return frames, gaps

    def _read_cache_entry(
        self, metadata_path: Path
    ) -> tuple[date, date, pd.DataFrame]:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("cache schema version mismatch")
        required = {
            "ticker",
            "start_date",
            "end_date",
            "columns",
            "row_count",
            "data_file",
            "sha256",
        }
        missing = required.difference(metadata)
        if missing:
            raise ValueError(f"cache metadata fields missing: {sorted(missing)}")
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
        cache_start = date.fromisoformat(str(metadata["start_date"]))
        cache_end = date.fromisoformat(str(metadata["end_date"]))
        return cache_start, cache_end, frame

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
