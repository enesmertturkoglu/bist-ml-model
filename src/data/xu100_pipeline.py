"""Validated XU100 snapshot collection and calendar-date resolution."""

from __future__ import annotations

import importlib.metadata
from dataclasses import asdict, dataclass
from datetime import date
from typing import Mapping

import pandas as pd

from src.config import MarketDataConfig
from src.data.collectors import current_code_commit_sha
from src.data.snapshot_store import SnapshotMetadata, SnapshotRequest, SnapshotStore
from src.data.xu100_client import (
    TIMESTAMP_RESOLUTION_RULE,
    XU100_ENDPOINT,
    XU100_INDEX_CODE,
    Xu100Client,
    add_timestamp_candidates,
    values_are_positive_finite,
)


class Xu100ValidationError(RuntimeError):
    """Raised when XU100 identity, dates or values cannot be accepted safely."""


@dataclass(frozen=True)
class TimestampValidationReport:
    row_count: int
    calendar_session_count: int
    utc_match_count: int
    istanbul_match_count: int
    legacy_plus_one_match_count: int
    utc_match_ratio: float
    istanbul_match_ratio: float
    legacy_plus_one_match_ratio: float
    istanbul_local_midnight_ratio: float
    legacy_equals_istanbul_ratio: float
    accepted_rule: str


@dataclass(frozen=True)
class Xu100RunResult:
    raw_snapshot: SnapshotMetadata
    validated_snapshot: SnapshotMetadata
    validation_report: TimestampValidationReport


def cross_check_end_fields(
    stock_frames: list[pd.DataFrame], validated: pd.DataFrame
) -> dict[str, object]:
    """Diagnose END_* consistency without ever promoting it to main benchmark source."""

    if len(stock_frames) < 20:
        raise Xu100ValidationError("END_* cross-check requires at least 20 securities")
    required = {
        "HGDG_HS_KODU",
        "HGDG_TARIH",
        "END_ENDEKS_KODU",
        "END_TARIH",
        "END_SEANS",
        "END_DEGER",
    }
    projected: list[pd.DataFrame] = []
    for frame in stock_frames:
        missing = required.difference(frame.columns)
        if missing:
            raise Xu100ValidationError(f"END_* cross-check fields missing: {sorted(missing)}")
        projected.append(frame.loc[:, list(required)].copy())
    combined = pd.concat(projected, ignore_index=True)
    if combined["HGDG_HS_KODU"].astype(str).nunique() < 20:
        raise Xu100ValidationError("END_* cross-check requires 20 distinct securities")
    stock_date = pd.to_datetime(combined["HGDG_TARIH"], errors="raise").dt.normalize()
    end_date = (
        pd.to_datetime(
            pd.to_numeric(combined["END_TARIH"], errors="raise"), unit="ms", utc=True
        )
        .dt.tz_convert("Europe/Istanbul")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    combined["_prediction_date"] = stock_date
    combined["_end_date"] = end_date
    combined["_end_value"] = pd.to_numeric(combined["END_DEGER"], errors="coerce")
    independent = validated.loc[:, ["prediction_date", "validated_xu100_close"]].copy()
    independent["prediction_date"] = pd.to_datetime(independent["prediction_date"]).dt.normalize()
    daily_end = combined.groupby("_prediction_date", as_index=False)["_end_value"].median()
    comparison = daily_end.merge(
        independent,
        left_on="_prediction_date",
        right_on="prediction_date",
        how="inner",
    )
    absolute_difference = (
        comparison["_end_value"] - comparison["validated_xu100_close"]
    ).abs()
    return {
        "security_count": int(combined["HGDG_HS_KODU"].astype(str).nunique()),
        "end_index_code_distribution": {
            str(key): int(value)
            for key, value in combined["END_ENDEKS_KODU"].astype(str).value_counts().items()
        },
        "end_session_distribution": {
            str(key): int(value)
            for key, value in combined["END_SEANS"].astype(str).value_counts().items()
        },
        "literal_xu100_code_ratio": float(
            combined["END_ENDEKS_KODU"].astype(str).eq(XU100_INDEX_CODE).mean()
        ),
        "end_date_stock_date_match_ratio": float(stock_date.eq(end_date).mean()),
        "same_day_value_equal_ratio": float(
            combined.groupby("_prediction_date")["_end_value"].nunique(dropna=False).le(1).mean()
        ),
        "same_day_session_equal_ratio": float(
            combined.groupby("_prediction_date")["END_SEANS"].nunique(dropna=False).le(1).mean()
        ),
        "independent_overlap_days": int(len(comparison)),
        "independent_absolute_difference_median": float(absolute_difference.median()),
        "independent_absolute_difference_max": float(absolute_difference.max()),
        "role": "diagnostic_only_no_fallback",
    }


def cross_check_yfinance(
    yfinance_frame: pd.DataFrame, validated: pd.DataFrame
) -> dict[str, object]:
    """Compare XU100.IS closes diagnostically; never substitute missing main-source rows."""

    source = yfinance_frame.copy()
    if isinstance(source.index, pd.DatetimeIndex):
        source = source.reset_index()
    date_candidates = [name for name in ("Date", "date", "Datetime", "index") if name in source]
    close_candidates = [name for name in ("Close", "close") if name in source]
    if not date_candidates or not close_candidates:
        raise Xu100ValidationError("yFinance XU100.IS cross-check needs Date and Close")
    cross = source.loc[:, [date_candidates[0], close_candidates[0]]].rename(
        columns={date_candidates[0]: "prediction_date", close_candidates[0]: "yf_close"}
    )
    dates = pd.to_datetime(cross["prediction_date"], errors="raise")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    cross["prediction_date"] = dates.dt.normalize()
    cross["yf_close"] = pd.to_numeric(cross["yf_close"], errors="coerce")
    independent = validated.loc[:, ["prediction_date", "validated_xu100_close"]].copy()
    independent["prediction_date"] = pd.to_datetime(independent["prediction_date"]).dt.normalize()
    comparison = independent.merge(cross, on="prediction_date", how="inner")
    absolute = (comparison["validated_xu100_close"] - comparison["yf_close"]).abs()
    relative = absolute / comparison["validated_xu100_close"]
    return {
        "symbol": "XU100.IS",
        "overlap_days": int(len(comparison)),
        "missing_in_yfinance_days": int(
            len(set(independent["prediction_date"]) - set(cross["prediction_date"]))
        ),
        "missing_in_independent_days": int(
            len(set(cross["prediction_date"]) - set(independent["prediction_date"]))
        ),
        "absolute_difference_median": float(absolute.median()),
        "absolute_difference_max": float(absolute.max()),
        "relative_difference_median": float(relative.median()),
        "relative_difference_max": float(relative.max()),
        "role": "diagnostic_only_no_fallback",
    }


def validate_xu100_history(
    raw: pd.DataFrame, global_calendar: pd.DataFrame
) -> tuple[pd.DataFrame, TimestampValidationReport]:
    """Resolve XU100 dates only when timezone-aware evidence is unambiguous."""

    candidates = add_timestamp_candidates(raw)
    if set(candidates["index_code"].astype(str)) != {XU100_INDEX_CODE}:
        raise Xu100ValidationError("independent endpoint index code is not exactly XU100")
    if not values_are_positive_finite(candidates["source_value"]):
        raise Xu100ValidationError("XU100 values must be positive and finite")
    if candidates["source_timestamp_ms"].duplicated().any():
        raise Xu100ValidationError("duplicate XU100 source timestamp")
    if "session_date" not in global_calendar.columns:
        raise Xu100ValidationError("global calendar is missing session_date")
    calendar_dates = set(pd.to_datetime(global_calendar["session_date"], errors="raise").dt.normalize())
    if not calendar_dates:
        raise Xu100ValidationError("global calendar is empty")

    counts: dict[str, int] = {}
    for column in ("utc_calendar_date", "istanbul_calendar_date", "legacy_plus_one_date"):
        counts[column] = int(candidates[column].isin(calendar_dates).sum())
    row_count = len(candidates)
    utc = pd.to_datetime(candidates["source_timestamp_ms"], unit="ms", utc=True)
    local = utc.dt.tz_convert("Europe/Istanbul")
    local_midnight = local.dt.hour.eq(0) & local.dt.minute.eq(0) & local.dt.second.eq(0)
    istanbul_count = counts["istanbul_calendar_date"]
    if istanbul_count != row_count:
        raise Xu100ValidationError("not every resolved Istanbul date is a global BIST session")
    if counts["utc_calendar_date"] >= istanbul_count:
        raise Xu100ValidationError("timestamp resolution is ambiguous against the global calendar")
    if not bool(local_midnight.all()):
        raise Xu100ValidationError("epoch timestamps do not resolve to Istanbul local midnight")
    if candidates["istanbul_calendar_date"].duplicated().any():
        raise Xu100ValidationError("duplicate XU100 prediction_date")

    validated = candidates.rename(
        columns={
            "istanbul_calendar_date": "prediction_date",
            "source_value": "validated_xu100_close",
        }
    ).copy()
    validated["timestamp_resolution_rule"] = TIMESTAMP_RESOLUTION_RULE
    validated["validation_status"] = "PASS"
    validated = validated.loc[
        :,
        [
            "prediction_date",
            "validated_xu100_close",
            "index_code",
            "source_timestamp_ms",
            "utc_calendar_date",
            "legacy_plus_one_date",
            "timestamp_resolution_rule",
            "validation_status",
        ],
    ].sort_values("prediction_date").reset_index(drop=True)
    report = TimestampValidationReport(
        row_count=row_count,
        calendar_session_count=len(calendar_dates),
        utc_match_count=counts["utc_calendar_date"],
        istanbul_match_count=istanbul_count,
        legacy_plus_one_match_count=counts["legacy_plus_one_date"],
        utc_match_ratio=counts["utc_calendar_date"] / row_count,
        istanbul_match_ratio=istanbul_count / row_count,
        legacy_plus_one_match_ratio=counts["legacy_plus_one_date"] / row_count,
        istanbul_local_midnight_ratio=float(local_midnight.mean()),
        legacy_equals_istanbul_ratio=float(
            candidates["legacy_plus_one_date"].eq(candidates["istanbul_calendar_date"]).mean()
        ),
        accepted_rule=TIMESTAMP_RESOLUTION_RULE,
    )
    return validated, report


class Xu100Pipeline:
    """Collect the independent series then validate it against a global calendar snapshot."""

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        client: Xu100Client | None = None,
        code_commit_sha: str | None = None,
    ) -> None:
        self.config = config or MarketDataConfig()
        self.snapshot_store = snapshot_store or SnapshotStore(self.config)
        request_config = self.config.isyatirim
        self.client = client or Xu100Client(
            timeout_seconds=request_config.timeout_seconds,
            max_retries=request_config.max_retries,
            retry_backoff_seconds=request_config.retry_backoff_seconds,
        )
        self.code_commit_sha = code_commit_sha or current_code_commit_sha()
        try:
            self.provider_version = importlib.metadata.version("isyatirimhisse")
        except importlib.metadata.PackageNotFoundError:
            self.provider_version = "unknown"

    def run(
        self,
        start_date: date,
        end_date: date,
        *,
        global_calendar_snapshot_id: str,
        refresh: bool = False,
    ) -> Xu100RunResult:
        calendar_meta = self.snapshot_store.get_snapshot(global_calendar_snapshot_id)
        if not self.snapshot_store.is_usable(calendar_meta):
            raise Xu100ValidationError("global calendar snapshot is not COMPLETE and verified")
        if calendar_meta.dataset_type != "global_bist_sessions":
            raise Xu100ValidationError("snapshot is not a global BIST calendar")
        calendar = self.snapshot_store.read_dataframe(calendar_meta)
        raw_request = SnapshotRequest(
            source="isyatirim",
            dataset_type="xu100_index_history",
            ticker_or_instrument=XU100_INDEX_CODE,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={"endpoint": XU100_ENDPOINT, "period_minutes": 1440},
            provider_library_version=self.provider_version,
            code_commit_sha=self.code_commit_sha,
            layer="raw",
            identity_columns=("index_code", "source_timestamp_ms"),
        )
        raw_existing = (
            None
            if refresh
            else self.snapshot_store.find_usable_snapshot(raw_request)
        )
        if raw_existing is None:
            raw = self.client.fetch_history(start_date, end_date)
            raw_written = self.snapshot_store.save_dataframe(raw, raw_request)
            raw_metadata = raw_written.metadata
        else:
            raw_metadata = raw_existing
            raw = self.snapshot_store.read_dataframe(raw_metadata)
        validated, report = validate_xu100_history(raw, calendar)
        context: Mapping[str, object] = {
            "input_snapshot_ids": [raw_metadata.snapshot_id, calendar_meta.snapshot_id],
            "input_content_checksums": {
                raw_metadata.snapshot_id: raw_metadata.content_checksum,
                calendar_meta.snapshot_id: calendar_meta.content_checksum,
            },
            "global_calendar_checksum": calendar_meta.content_checksum,
            "timestamp_resolution_rule": TIMESTAMP_RESOLUTION_RULE,
            "validation_report": asdict(report),
            "code_commit_sha": self.code_commit_sha,
        }
        validated_request = SnapshotRequest(
            source="benchmark",
            dataset_type="validated_xu100_close",
            ticker_or_instrument=XU100_INDEX_CODE,
            request_start_date=start_date,
            request_end_date=end_date,
            request_parameters={"validation_method": "global_calendar_and_local_midnight_v1"},
            provider_library_version=self.provider_version,
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=(raw_metadata.snapshot_id, calendar_meta.snapshot_id),
            identity_columns=("prediction_date",),
            revision_context=context,
        )
        validated_written = self.snapshot_store.save_dataframe(validated, validated_request)
        return Xu100RunResult(raw_metadata, validated_written.metadata, report)
