"""Independent İş Yatırım XU100 history client and timestamp diagnostics."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Protocol

import pandas as pd
import requests

from src.data.isyatirim_client import DEFAULT_SSL_VERIFY


XU100_INDEX_CODE = "XU100"
XU100_ENDPOINT = (
    "https://www.isyatirim.com.tr/_Layouts/15/"
    "IsYatirim.Website/Common/ChartData.aspx/IndexHistoricalAll"
)
TIMESTAMP_RESOLUTION_RULE = "utc_epoch_ms_to_europe_istanbul_calendar_date_v1"


class HttpGetter(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


class Xu100ClientError(RuntimeError):
    """Base XU100 provider error."""


class Xu100SchemaError(Xu100ClientError):
    """Raised when the independent endpoint response is not the expected schema."""


@dataclass(frozen=True)
class Xu100FetchStats:
    attempts: int
    retry_count: int


class Xu100Client:
    """Fetch XU100 without using stock-response END_* fields or yFinance."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        max_retries: int = 5,
        retry_backoff_seconds: float = 1.0,
        session: HttpGetter | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        ssl_verify: bool = DEFAULT_SSL_VERIFY,
    ) -> None:
        if timeout_seconds <= 0 or max_retries < 1 or retry_backoff_seconds < 0:
            raise ValueError("invalid XU100 request configuration")
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self.session = session or requests.Session()
        self.sleep_func = sleep_func
        self.ssl_verify = ssl_verify
        self.last_stats = Xu100FetchStats(attempts=0, retry_count=0)

    def fetch_history(
        self,
        start_date: date | str | pd.Timestamp,
        end_date: date | str | pd.Timestamp,
        *,
        index_code: str = XU100_INDEX_CODE,
    ) -> pd.DataFrame:
        """Fetch raw timestamp/value pairs and explicit diagnostic date candidates."""

        code = str(index_code).strip().upper()
        if code != XU100_INDEX_CODE:
            raise ValueError("only exact index code XU100 is accepted")
        start = pd.Timestamp(start_date).date()
        end = pd.Timestamp(end_date).date()
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        params = {
            "period": 1440,
            "from": start.strftime("%Y%m%d") + "000000",
            "to": end.strftime("%Y%m%d") + "235959",
            "endeks": code,
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    XU100_ENDPOINT,
                    params=params,
                    timeout=(10, self.timeout_seconds),
                    verify=self.ssl_verify,
                )
                response.raise_for_status()
                frame = self._parse_response(response, code)
                self.last_stats = Xu100FetchStats(attempt, attempt - 1)
                return add_timestamp_candidates(frame)
            except Xu100SchemaError:
                raise
            except requests.RequestException as error:
                last_error = error
                if attempt < self.max_retries:
                    self.sleep_func(self.retry_backoff_seconds * (2 ** (attempt - 1)))
        self.last_stats = Xu100FetchStats(self.max_retries, self.max_retries - 1)
        raise Xu100ClientError(str(last_error)) from last_error

    @staticmethod
    def _parse_response(response: Any, index_code: str) -> pd.DataFrame:
        try:
            payload = response.json()
        except Exception as error:
            raise Xu100SchemaError("XU100 response is not valid JSON") from error
        raw = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw, list) or not raw:
            raise Xu100SchemaError("XU100 response has no non-empty data list")
        if any(not isinstance(row, (list, tuple)) or len(row) != 2 for row in raw):
            raise Xu100SchemaError("XU100 data rows must be [timestamp_ms, value]")
        frame = pd.DataFrame(raw, columns=["source_timestamp_ms", "source_value"])
        frame.insert(0, "index_code", index_code)
        try:
            frame["source_timestamp_ms"] = pd.to_numeric(
                frame["source_timestamp_ms"], errors="raise"
            ).astype("int64")
            frame["source_value"] = pd.to_numeric(
                frame["source_value"], errors="raise"
            ).astype("float64")
        except (TypeError, ValueError) as error:
            raise Xu100SchemaError("XU100 timestamp/value fields must be numeric") from error
        return frame


def add_timestamp_candidates(raw: pd.DataFrame) -> pd.DataFrame:
    """Interpret epoch milliseconds as UTC before deriving calendar candidates."""

    required = {"index_code", "source_timestamp_ms", "source_value"}
    missing = required.difference(raw.columns)
    if missing:
        raise Xu100SchemaError(f"XU100 fields missing: {sorted(missing)}")
    result = raw.loc[:, ["index_code", "source_timestamp_ms", "source_value"]].copy()
    utc = pd.to_datetime(result["source_timestamp_ms"], unit="ms", utc=True, errors="raise")
    istanbul = utc.dt.tz_convert("Europe/Istanbul")
    result["utc_calendar_date"] = utc.dt.tz_localize(None).dt.normalize()
    result["istanbul_calendar_date"] = istanbul.dt.tz_localize(None).dt.normalize()
    result["legacy_plus_one_date"] = result["utc_calendar_date"] + pd.Timedelta(days=1)
    return result


def values_are_positive_finite(values: pd.Series) -> bool:
    numeric = pd.to_numeric(values, errors="coerce")
    return bool(numeric.map(math.isfinite).all() and numeric.gt(0).all())
