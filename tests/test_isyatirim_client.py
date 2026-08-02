from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import requests

from src.data.isyatirim_client import (
    CACHE_SCHEMA_VERSION,
    TIME_BUDGET_EXCEEDED,
    IsYatirimClient,
    IsYatirimBudgetFetchError,
    IsYatirimFetchError,
    split_date_range,
)


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class QueueSession:
    def __init__(self, outcomes: Iterable[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.outcomes:
            raise AssertionError("Unexpected network request")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


class AdvancingQueueSession(QueueSession):
    def __init__(
        self, outcomes: Iterable[object], clock: FakeClock, advance_seconds: float
    ) -> None:
        super().__init__(outcomes)
        self.clock = clock
        self.advance_seconds = advance_seconds

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.clock.advance(self.advance_seconds)
        return super().get(url, **kwargs)


def _row(day: str, *, close: float = 10.0) -> dict[str, object]:
    return {
        "HGDG_HS_KODU": "THYAO",
        "HGDG_TARIH": day,
        "HGDG_KAPANIS": close,
        "HG_KAPANIS": close,
    }


def _response(*days: str) -> FakeResponse:
    return FakeResponse({"value": [_row(day) for day in days]})


def _client(
    tmp_path: Path,
    outcomes: Iterable[object],
    *,
    max_retries: int = 1,
    sleep_calls: list[float] | None = None,
    random_value: float = 0.0,
    **kwargs: Any,
) -> tuple[IsYatirimClient, QueueSession]:
    session = QueueSession(outcomes)
    recorded_sleeps = sleep_calls if sleep_calls is not None else []
    client = IsYatirimClient(
        session=session,
        cache_dir=tmp_path,
        max_retries=max_retries,
        request_delay_seconds=kwargs.pop("request_delay_seconds", 0.0),
        sleep_func=kwargs.pop("sleep_func", recorded_sleeps.append),
        random_func=lambda: random_value,
        ssl_verify=True,
        **kwargs,
    )
    return client, session


def test_first_yearly_request_succeeds(tmp_path: Path) -> None:
    client, session = _client(tmp_path, [_response("01-01-2024")])

    result = client.fetch_history("THYAO", date(2024, 1, 1), date(2024, 12, 31))

    assert len(result) == 1
    assert len(session.calls) == 1
    assert client.stats.yearly_requests == 1
    assert client.stats.successful_network_chunks == 1


def test_timeout_retries_then_succeeds(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [requests.Timeout("slow"), _response("01-01-2024")],
        max_retries=2,
    )

    result = client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 1
    assert len(session.calls) == 2
    assert client.stats.timeout_count == 1
    assert client.stats.retry_count == 1
    assert client.stats.timeout_recovered_chunks == 1


def test_yearly_failure_splits_into_two_six_month_chunks(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [
            requests.Timeout("year"),
            _response("30-06-2024"),
            _response("01-07-2024"),
        ],
    )

    result = client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 2
    assert len(session.calls) == 3
    assert client.stats.split_to_six_month_count == 1
    assert client.stats.six_month_requests == 2


def test_six_month_failure_splits_into_three_month_chunks(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [
            requests.Timeout("year"),
            requests.Timeout("half"),
            _response("31-03-2024"),
            _response("01-04-2024"),
            _response("01-07-2024"),
        ],
    )

    result = client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 3
    assert client.stats.split_to_six_month_count == 1
    assert client.stats.split_to_three_month_count == 1
    assert client.stats.three_month_requests == 2


def test_minimum_chunk_failure_is_explicit(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [requests.Timeout("slow") for _ in range(7)],
    )

    with pytest.raises(IsYatirimFetchError) as captured:
        client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(session.calls) == 7
    assert len(captured.value.failures) == 4
    assert {failure.chunk_months for failure in captured.value.failures} == {3}
    assert client.stats.failed_chunks == 4


def test_successful_child_is_cached_when_sibling_fails(tmp_path: Path) -> None:
    client, _ = _client(
        tmp_path,
        [
            requests.Timeout("year"),
            _response("30-06-2024"),
            requests.Timeout("half"),
            requests.Timeout("quarter-3"),
            requests.Timeout("quarter-4"),
        ],
    )

    with pytest.raises(IsYatirimFetchError) as captured:
        client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(captured.value.partial_data) == 1
    assert list(tmp_path.glob("*.csv"))
    metadata = [path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json")]
    assert any('"end_date": "2024-06-30"' in value for value in metadata)


def test_cache_hit_avoids_network_request(tmp_path: Path) -> None:
    first, _ = _client(tmp_path, [_response("01-01-2024")])
    first.fetch_history("THYAO", "2024-01-01", "2024-12-31")
    second, session = _client(tmp_path, [])

    result = second.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 1
    assert not session.calls
    assert second.stats.cache_hits == 1


def test_cache_downloads_only_missing_date_range(tmp_path: Path) -> None:
    first, _ = _client(tmp_path, [_response("30-06-2024")])
    first.fetch_history("THYAO", "2024-01-01", "2024-06-30")
    second, session = _client(tmp_path, [_response("01-07-2024")])

    result = second.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 2
    assert len(session.calls) == 1
    assert session.calls[0]["params"]["startdate"] == "01-07-2024"
    assert second.stats.cache_hits == 1


def test_corrupt_cache_is_reported_and_redownloaded(tmp_path: Path) -> None:
    first, _ = _client(tmp_path, [_response("01-01-2024")])
    first.fetch_history("THYAO", "2024-01-01", "2024-12-31")
    data_path = next(tmp_path.glob("*.csv"))
    data_path.write_text("corrupt", encoding="utf-8")
    second, session = _client(tmp_path, [_response("01-01-2024")])

    result = second.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 1
    assert len(session.calls) == 1
    assert second.stats.cache_corruption_count == 1
    assert second.stats.cache_issues


def test_date_chunks_have_no_gap_or_duplicate_boundary() -> None:
    chunks = split_date_range(date(2023, 8, 31), date(2024, 8, 31), 6)

    assert chunks[0][0] == date(2023, 8, 31)
    assert chunks[-1][1] == date(2024, 8, 31)
    for previous, current in zip(chunks, chunks[1:]):
        assert previous[1] + timedelta(days=1) == current[0]


def test_duplicate_ticker_date_rows_are_removed(tmp_path: Path) -> None:
    duplicate = FakeResponse(
        {"value": [_row("01-01-2024", close=9), _row("01-01-2024", close=10)]}
    )
    client, _ = _client(tmp_path, [duplicate])

    result = client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(result) == 1
    assert result.loc[0, "HG_KAPANIS"] == 10


def test_http_429_uses_retry_after(tmp_path: Path) -> None:
    sleeps: list[float] = []
    client, session = _client(
        tmp_path,
        [
            FakeResponse({}, status_code=429, headers={"Retry-After": "7"}),
            _response("01-01-2024"),
        ],
        max_retries=2,
        sleep_calls=sleeps,
    )

    client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(session.calls) == 2
    assert client.stats.http_429_count == 1
    assert 7.0 in sleeps


def test_http_5xx_is_retried(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [FakeResponse({}, status_code=503), _response("01-01-2024")],
        max_retries=2,
    )

    client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(session.calls) == 2
    assert client.stats.http_5xx_count == 1


def test_permanent_schema_error_is_not_retried(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [FakeResponse({"value": [{"unexpected": 1}]})],
        max_retries=5,
    )

    with pytest.raises(IsYatirimFetchError) as captured:
        client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(session.calls) == 1
    assert captured.value.failures[0].error_type == "IsYatirimSchemaError"


def test_sleep_and_jitter_are_injected_without_real_wait(tmp_path: Path) -> None:
    sleeps: list[float] = []
    client, _ = _client(
        tmp_path,
        [requests.Timeout("slow"), _response("01-01-2024")],
        max_retries=2,
        sleep_calls=sleeps,
        random_value=0.5,
        request_delay_seconds=2.0,
    )

    client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert sleeps == [1.25, 2.25]


def test_timeout_is_forwarded_to_http_client(tmp_path: Path) -> None:
    client, session = _client(
        tmp_path,
        [_response("01-01-2024")],
        timeout_seconds=42,
    )

    client.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert session.calls[0]["timeout"] == (10, 42.0)


def test_refresh_cache_bypasses_existing_entry(tmp_path: Path) -> None:
    first, _ = _client(tmp_path, [_response("01-01-2024")])
    first.fetch_history("THYAO", "2024-01-01", "2024-12-31")
    session = QueueSession([_response("02-01-2024")])
    refreshed = IsYatirimClient(
        session=session,
        cache_dir=tmp_path,
        max_retries=1,
        request_delay_seconds=0,
        refresh_cache=True,
        sleep_func=lambda _: None,
        random_func=lambda: 0.0,
    )

    result = refreshed.fetch_history("THYAO", "2024-01-01", "2024-12-31")

    assert len(session.calls) == 1
    assert result.loc[0, "HGDG_TARIH"] == pd.Timestamp("2024-01-02")
    assert CACHE_SCHEMA_VERSION in next(tmp_path.glob("*.json")).name


def test_security_budget_covers_the_recursive_12_6_3_month_chain(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    session = AdvancingQueueSession(
        [
            requests.Timeout("year"),
            _response("30-06-2024"),
        ],
        clock,
        advance_seconds=2.0,
    )
    client = IsYatirimClient(
        session=session,
        cache_dir=tmp_path,
        max_retries=1,
        request_delay_seconds=0,
        sleep_func=clock.sleep,
        random_func=lambda: 0.0,
        monotonic_func=clock.monotonic,
        ssl_verify=True,
    )

    with pytest.raises(IsYatirimBudgetFetchError) as captured:
        client.fetch_history(
            "THYAO",
            "2024-01-01",
            "2024-12-31",
            security_budget_seconds=4,
            security_started_at=0,
        )

    assert len(session.calls) == 2
    assert captured.value.failures[0].error_type == TIME_BUDGET_EXCEEDED
    assert captured.value.failures[0].start_date == date(2024, 7, 1)
    assert len(captured.value.partial_data) == 1
    assert client.stats.time_budget_exceeded_count == 1
    assert list(tmp_path.glob("*.csv"))


def test_budget_expiry_prevents_a_new_retry(tmp_path: Path) -> None:
    clock = FakeClock()
    session = AdvancingQueueSession(
        [requests.Timeout("slow")], clock, advance_seconds=1.0
    )
    client = IsYatirimClient(
        session=session,
        cache_dir=tmp_path,
        max_retries=5,
        request_delay_seconds=0,
        sleep_func=clock.sleep,
        random_func=lambda: 0.0,
        monotonic_func=clock.monotonic,
        ssl_verify=True,
    )

    with pytest.raises(IsYatirimBudgetFetchError) as captured:
        client.fetch_history(
            "THYAO",
            "2024-01-01",
            "2024-12-31",
            security_budget_seconds=1,
            security_started_at=0,
        )

    assert len(session.calls) == 1
    assert client.stats.retry_count == 0
    assert captured.value.failures[0].error_type == TIME_BUDGET_EXCEEDED


def test_budget_failure_reports_later_unattempted_ranges(tmp_path: Path) -> None:
    clock = FakeClock()
    session = AdvancingQueueSession(
        [requests.Timeout("slow")], clock, advance_seconds=1.0
    )
    client = IsYatirimClient(
        session=session,
        cache_dir=tmp_path,
        max_retries=5,
        request_delay_seconds=0,
        sleep_func=clock.sleep,
        random_func=lambda: 0.0,
        monotonic_func=clock.monotonic,
        ssl_verify=True,
    )

    with pytest.raises(IsYatirimBudgetFetchError) as captured:
        client.fetch_history(
            "THYAO",
            "2024-01-01",
            "2025-12-31",
            security_budget_seconds=1,
            security_started_at=0,
        )

    assert len(session.calls) == 1
    assert [
        (item.start_date, item.end_date, item.error_type, item.attempts)
        for item in captured.value.failures
    ] == [
        (date(2024, 1, 1), date(2024, 12, 31), TIME_BUDGET_EXCEEDED, 0),
        (date(2025, 1, 1), date(2025, 12, 31), TIME_BUDGET_EXCEEDED, 0),
    ]


def test_retry_after_budget_failure_requests_only_the_uncached_range(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    first_session = AdvancingQueueSession(
        [requests.Timeout("year"), _response("30-06-2024")],
        clock,
        advance_seconds=2.0,
    )
    first = IsYatirimClient(
        session=first_session,
        cache_dir=tmp_path,
        max_retries=1,
        request_delay_seconds=0,
        sleep_func=clock.sleep,
        random_func=lambda: 0.0,
        monotonic_func=clock.monotonic,
        ssl_verify=True,
    )
    with pytest.raises(IsYatirimBudgetFetchError):
        first.fetch_history(
            "THYAO",
            "2024-01-01",
            "2024-12-31",
            security_budget_seconds=4,
            security_started_at=0,
        )

    second_session = QueueSession([_response("01-07-2024")])
    second = IsYatirimClient(
        session=second_session,
        cache_dir=tmp_path,
        max_retries=1,
        request_delay_seconds=0,
        sleep_func=lambda _: None,
        random_func=lambda: 0.0,
        ssl_verify=True,
    )
    result = second.fetch_history(
        "THYAO",
        "2024-01-01",
        "2024-12-31",
        security_budget_seconds=30,
    )

    assert len(result) == 2
    assert len(second_session.calls) == 1
    assert second_session.calls[0]["params"]["startdate"] == "01-07-2024"
    assert second.stats.cache_hits == 1
