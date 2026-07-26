"""Deterministic, date-effective BIST equity security identity resolution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd


MAPPING_COLUMNS = (
    "security_id",
    "ticker",
    "valid_from",
    "valid_to",
    "is_current_ticker",
    "mapping_status",
    "official_source_name",
    "official_source_reference",
    "official_source_date",
    "official_source_url",
    "notes",
)
IDENTITY_COLUMNS = (
    "security_id",
    "observed_ticker",
    "current_ticker",
    "ticker_mapping_status",
    "ticker_mapping_rule_id",
    "ticker_mapping_version",
    "ticker_mapping_checksum",
)
MAPPED_CURRENT_TICKER = "MAPPED_CURRENT_TICKER"
MAPPED_HISTORICAL_TICKER = "MAPPED_HISTORICAL_TICKER"
AUTO_NEW_TICKER = "AUTO_NEW_TICKER"
OUTSIDE_VALIDITY = "OUTSIDE_VALIDITY"


class TickerMappingError(ValueError):
    """Raised when a mapping cannot be interpreted without ambiguity."""


@dataclass(frozen=True)
class SecurityIdentityResolution:
    security_id: str
    observed_ticker: str
    current_ticker: str
    mapping_status: str
    mapping_rule_id: str | None


@dataclass(frozen=True)
class SecurityTickerPeriod:
    security_id: str
    ticker: str
    start_date: date
    end_date: date
    mapping_status: str
    mapping_rule_id: str | None

    @property
    def yfinance_ticker(self) -> str:
        return f"{self.ticker}.IS"


@dataclass(frozen=True)
class TickerMapping:
    frame: pd.DataFrame
    version: str
    checksum: str

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        *,
        checksum_algorithm: str = "sha256",
    ) -> "TickerMapping":
        source = Path(path)
        frame = pd.read_csv(source, dtype="string", keep_default_na=False)
        normalized = _normalize_mapping_frame(frame)
        validate_ticker_mapping(normalized)
        return cls(
            frame=normalized,
            version=source.stem,
            checksum=_mapping_checksum(normalized, checksum_algorithm),
        )

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        *,
        version: str = "in_memory_v1",
        checksum_algorithm: str = "sha256",
    ) -> "TickerMapping":
        normalized = _normalize_mapping_frame(frame)
        validate_ticker_mapping(normalized)
        return cls(
            frame=normalized,
            version=version,
            checksum=_mapping_checksum(normalized, checksum_algorithm),
        )


def normalize_ticker(ticker: Any) -> str:
    """Return the provider-neutral uppercase ticker used by identity rules."""

    if ticker is None or pd.isna(ticker):
        raise TickerMappingError("ticker is required")
    normalized = str(ticker).strip().upper()
    if normalized.endswith(".IS"):
        normalized = normalized[:-3]
    normalized = normalized.strip()
    if not normalized:
        raise TickerMappingError("ticker is required")
    return normalized


def generate_security_id(ticker: Any) -> str:
    """Generate a stable identity without relying on process-randomized hash()."""

    normalized = normalize_ticker(ticker)
    digest = hashlib.sha256(f"BIST:EQUITY:{normalized}".encode("utf-8")).hexdigest()
    return f"SEC_{digest[:12]}"


def resolve_security_id(
    ticker: Any,
    trade_date: date | str | pd.Timestamp,
    mapping: TickerMapping | pd.DataFrame,
) -> SecurityIdentityResolution:
    """Resolve one observed ticker on an inclusive mapping date."""

    table = _coerce_mapping(mapping)
    observed = normalize_ticker(ticker)
    day = _coerce_date(trade_date, field="trade_date")
    candidates = table.frame.loc[table.frame["ticker"].eq(observed)]
    if candidates.empty:
        return SecurityIdentityResolution(
            generate_security_id(observed),
            observed,
            observed,
            AUTO_NEW_TICKER,
            None,
        )

    effective = candidates.loc[
        candidates["valid_from"].le(day)
        & candidates["valid_to"].map(lambda value: value is None or value >= day)
    ]
    if effective.empty:
        security_ids = sorted(map(str, candidates["security_id"].unique()))
        security_id = security_ids[0]
        return SecurityIdentityResolution(
            security_id,
            observed,
            _current_ticker(table.frame, security_id),
            OUTSIDE_VALIDITY,
            None,
        )
    if len(effective) != 1:
        raise TickerMappingError(
            f"ticker {observed} resolves to multiple rules on {day.isoformat()}"
        )
    rule = effective.iloc[0]
    security_id = str(rule["security_id"])
    is_current = bool(rule["is_current_ticker"])
    return SecurityIdentityResolution(
        security_id,
        observed,
        _current_ticker(table.frame, security_id),
        MAPPED_CURRENT_TICKER if is_current else MAPPED_HISTORICAL_TICKER,
        str(rule["mapping_rule_id"]),
    )


def resolve_tickers_for_security(
    security_id: str,
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    mapping: TickerMapping | pd.DataFrame,
) -> tuple[SecurityTickerPeriod, ...]:
    """Return mapped provider tickers clipped to the requested inclusive period."""

    table = _coerce_mapping(mapping)
    start = _coerce_date(start_date, field="start_date")
    end = _coerce_date(end_date, field="end_date")
    if start > end:
        raise TickerMappingError("start_date must be on or before end_date")
    rows = table.frame.loc[table.frame["security_id"].eq(str(security_id).strip())]
    periods: list[SecurityTickerPeriod] = []
    for rule in rows.sort_values(["valid_from", "ticker"]).to_dict(orient="records"):
        clipped_start = max(start, rule["valid_from"])
        clipped_end = min(end, rule["valid_to"] or end)
        if clipped_start > clipped_end:
            continue
        periods.append(
            SecurityTickerPeriod(
                security_id=str(rule["security_id"]),
                ticker=str(rule["ticker"]),
                start_date=clipped_start,
                end_date=clipped_end,
                mapping_status=(
                    MAPPED_CURRENT_TICKER
                    if bool(rule["is_current_ticker"])
                    else MAPPED_HISTORICAL_TICKER
                ),
                mapping_rule_id=str(rule["mapping_rule_id"]),
            )
        )
    return tuple(periods)


def plan_ticker_collection(
    ticker: Any,
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    mapping: TickerMapping | pd.DataFrame,
) -> tuple[SecurityTickerPeriod, ...]:
    """Plan only official mapped intervals, or one non-blocking automatic ticker."""

    table = _coerce_mapping(mapping)
    observed = normalize_ticker(ticker)
    start = _coerce_date(start_date, field="start_date")
    end = _coerce_date(end_date, field="end_date")
    if start > end:
        raise TickerMappingError("start_date must be on or before end_date")
    known = table.frame.loc[table.frame["ticker"].eq(observed)]
    if known.empty:
        return (
            SecurityTickerPeriod(
                generate_security_id(observed),
                observed,
                start,
                end,
                AUTO_NEW_TICKER,
                None,
            ),
        )
    security_ids = sorted(map(str, known["security_id"].unique()))
    if len(security_ids) != 1:
        raise TickerMappingError(
            f"ticker {observed} belongs to multiple securities across mapping history"
        )
    return resolve_tickers_for_security(security_ids[0], start, end, table)


def plan_active_ticker_collection(
    tickers: Iterable[Any],
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    mapping: TickerMapping | pd.DataFrame,
) -> tuple[SecurityTickerPeriod, ...]:
    """Deduplicate provider requests when active tickers resolve to one security."""

    planned: dict[tuple[str, str, date, date], SecurityTickerPeriod] = {}
    for ticker in tickers:
        for period in plan_ticker_collection(ticker, start_date, end_date, mapping):
            key = (
                period.security_id,
                period.ticker,
                period.start_date,
                period.end_date,
            )
            planned[key] = period
    return tuple(planned[key] for key in sorted(planned))


def enrich_security_identity(
    frame: pd.DataFrame,
    mapping: TickerMapping | pd.DataFrame,
    *,
    ticker_column: str = "ticker",
    date_column: str = "date",
) -> pd.DataFrame:
    """Attach auditable identity fields without changing observed provider tickers."""

    table = _coerce_mapping(mapping)
    missing = {ticker_column, date_column}.difference(frame.columns)
    if missing:
        raise TickerMappingError(f"identity input fields missing: {sorted(missing)}")
    result = frame.copy()
    resolutions = [
        resolve_security_id(ticker, day, table)
        for ticker, day in zip(
            result[ticker_column], result[date_column], strict=True
        )
    ]
    result[ticker_column] = [value.observed_ticker for value in resolutions]
    result["security_id"] = [value.security_id for value in resolutions]
    result["observed_ticker"] = [value.observed_ticker for value in resolutions]
    result["current_ticker"] = [value.current_ticker for value in resolutions]
    result["ticker_mapping_status"] = [value.mapping_status for value in resolutions]
    result["ticker_mapping_rule_id"] = [value.mapping_rule_id for value in resolutions]
    result["ticker_mapping_version"] = table.version
    result["ticker_mapping_checksum"] = table.checksum
    return result


def merge_security_history(
    frame: pd.DataFrame,
    mapping: TickerMapping | pd.DataFrame,
    *,
    ticker_column: str = "ticker",
    date_column: str = "date",
) -> pd.DataFrame:
    """Create one deterministic security/date series and reject out-of-period rows."""

    enriched = enrich_security_identity(
        frame,
        mapping,
        ticker_column=ticker_column,
        date_column=date_column,
    )
    return deduplicate_security_history(enriched, date_column=date_column)


def deduplicate_security_history(
    enriched: pd.DataFrame,
    *,
    date_column: str = "date",
) -> pd.DataFrame:
    """Prefer explicit date-effective rows for duplicate security/date records."""

    required = {
        "security_id",
        "observed_ticker",
        "ticker_mapping_status",
        date_column,
    }
    missing = required.difference(enriched.columns)
    if missing:
        raise TickerMappingError(f"enriched identity fields missing: {sorted(missing)}")
    result = enriched.loc[
        enriched["ticker_mapping_status"].ne(OUTSIDE_VALIDITY)
    ].copy()
    result[date_column] = pd.to_datetime(result[date_column]).dt.normalize()
    priority = {
        MAPPED_CURRENT_TICKER: 0,
        MAPPED_HISTORICAL_TICKER: 0,
        AUTO_NEW_TICKER: 1,
    }
    result["_identity_priority"] = result["ticker_mapping_status"].map(priority).fillna(9)
    result["_identity_row_hash"] = [
        hashlib.sha256(_canonical_record(row).encode("utf-8")).hexdigest()
        for row in result.to_dict(orient="records")
    ]
    result = result.sort_values(
        ["security_id", date_column, "_identity_priority", "_identity_row_hash"]
    ).drop_duplicates(["security_id", date_column], keep="first")
    return result.drop(
        columns=["_identity_priority", "_identity_row_hash"]
    ).sort_values(["security_id", date_column]).reset_index(drop=True)


def validate_ticker_mapping(mapping: TickerMapping | pd.DataFrame) -> None:
    """Reject incomplete, overlapping or date-ambiguous explicit mappings."""

    frame = mapping.frame if isinstance(mapping, TickerMapping) else _normalize_mapping_frame(mapping)
    if frame.empty:
        return
    for row in frame.to_dict(orient="records"):
        if not str(row["security_id"]).strip():
            raise TickerMappingError("security_id is required")
        if row["valid_to"] is not None and row["valid_to"] < row["valid_from"]:
            raise TickerMappingError("valid_to must be on or after valid_from")
        if str(row["mapping_status"]).strip().upper() == "CONFIRMED":
            required_source = (
                "official_source_name",
                "official_source_reference",
                "official_source_date",
                "official_source_url",
            )
            if any(not str(row[field]).strip() for field in required_source):
                raise TickerMappingError(
                    "CONFIRMED mappings require complete official source metadata"
                )

    current_counts = frame.loc[frame["is_current_ticker"]].groupby("security_id").size()
    if current_counts.gt(1).any():
        raise TickerMappingError("a security may have at most one current ticker")

    _reject_overlaps(
        frame,
        group_columns=("security_id",),
        message="ticker periods under the same security_id overlap",
    )
    _reject_overlaps(
        frame,
        group_columns=("ticker",),
        message="one ticker maps ambiguously on the same date",
        only_different_security=True,
    )


def _coerce_mapping(mapping: TickerMapping | pd.DataFrame) -> TickerMapping:
    if isinstance(mapping, TickerMapping):
        return mapping
    if isinstance(mapping, pd.DataFrame):
        return TickerMapping.from_frame(mapping)
    raise TypeError("mapping must be a TickerMapping or pandas DataFrame")


def _normalize_mapping_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(MAPPING_COLUMNS).difference(map(str, frame.columns))
    if missing:
        raise TickerMappingError(f"mapping fields missing: {sorted(missing)}")
    result = frame.loc[:, MAPPING_COLUMNS].copy()
    if result.empty:
        result["is_current_ticker"] = pd.Series(dtype=bool)
        result["mapping_rule_id"] = pd.Series(dtype="string")
        return result
    for column in MAPPING_COLUMNS:
        result[column] = result[column].map(
            lambda value: "" if value is None or pd.isna(value) else str(value).strip()
        )
    result["security_id"] = result["security_id"].str.upper()
    result["ticker"] = result["ticker"].map(normalize_ticker)
    result["valid_from"] = result["valid_from"].map(
        lambda value: _coerce_date(value, field="valid_from")
    )
    result["valid_to"] = result["valid_to"].map(
        lambda value: None if value == "" else _coerce_date(value, field="valid_to")
    )
    result["official_source_date"] = result["official_source_date"].map(
        lambda value: "" if value == "" else _coerce_date(value, field="official_source_date").isoformat()
    )
    result["is_current_ticker"] = result["is_current_ticker"].map(_coerce_bool)
    result["mapping_status"] = result["mapping_status"].str.upper()
    result["mapping_rule_id"] = [
        _mapping_rule_id(row) for row in result.to_dict(orient="records")
    ]
    return result.sort_values(
        ["security_id", "valid_from", "ticker"]
    ).reset_index(drop=True)


def _mapping_checksum(frame: pd.DataFrame, algorithm: str) -> str:
    hashlib.new(algorithm)
    rows = [
        {
            column: _canonical_scalar(row[column])
            for column in MAPPING_COLUMNS
        }
        for row in frame.to_dict(orient="records")
    ]
    payload = json.dumps(
        {"columns": list(MAPPING_COLUMNS), "rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.new(algorithm, payload).hexdigest()


def _mapping_rule_id(row: Mapping[str, Any]) -> str:
    payload = {
        column: _canonical_scalar(row[column])
        for column in MAPPING_COLUMNS
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"MAP_{digest[:16]}"


def _current_ticker(frame: pd.DataFrame, security_id: str) -> str:
    rows = frame.loc[frame["security_id"].eq(security_id)]
    current = rows.loc[rows["is_current_ticker"]]
    if not current.empty:
        return str(current.iloc[0]["ticker"])
    ordered = rows.sort_values(["valid_from", "ticker"])
    return str(ordered.iloc[-1]["ticker"])


def _reject_overlaps(
    frame: pd.DataFrame,
    *,
    group_columns: Sequence[str],
    message: str,
    only_different_security: bool = False,
) -> None:
    grouper: str | list[str]
    grouper = group_columns[0] if len(group_columns) == 1 else list(group_columns)
    for _, group in frame.groupby(grouper, sort=False):
        rows = group.sort_values(["valid_from", "valid_to"], na_position="last").to_dict(
            orient="records"
        )
        for index, left in enumerate(rows):
            left_end = left["valid_to"] or date.max
            for right in rows[index + 1 :]:
                if right["valid_from"] > left_end:
                    break
                if only_different_security and (
                    left["security_id"] == right["security_id"]
                ):
                    continue
                right_end = right["valid_to"] or date.max
                if left["valid_from"] <= right_end and right["valid_from"] <= left_end:
                    raise TickerMappingError(message)


def _coerce_date(value: Any, *, field: str) -> date:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise TickerMappingError(f"invalid {field}: {value!r}") from exc
    if pd.isna(timestamp):
        raise TickerMappingError(f"invalid {field}: {value!r}")
    return timestamp.date()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise TickerMappingError(f"invalid is_current_ticker: {value!r}")


def _canonical_record(row: Mapping[str, Any]) -> str:
    return json.dumps(
        {str(key): _canonical_scalar(value) for key, value in row.items()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_scalar(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if hasattr(value, "item"):
        return value.item()
    return value
