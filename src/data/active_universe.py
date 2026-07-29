"""Official-source active BIST equity universe and collection planning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import unicodedata
from urllib.parse import urlparse

import pandas as pd
import requests

from src.config import MarketDataConfig
from src.data.security_identity import (
    AUTO_NEW_TICKER,
    MAPPING_COLUMNS,
    TickerMapping,
    generate_security_id,
    normalize_ticker,
    plan_ticker_collection,
)
from src.data.snapshot_store import (
    SnapshotMetadata,
    SnapshotRequest,
    SnapshotStore,
    SnapshotWriteResult,
)


UNIVERSE_VERSION = "bist_active_universe_v1"
PARSER_VERSION = "active-bist-universe-v1"
KAP_BIST_COMPANIES_URL = "https://www.kap.org.tr/tr/bist-sirketler"
KAP_MARKETS_URL = "https://www.kap.org.tr/tr/Pazarlar"
KAP_ENDED_MEMBERS_URL = "https://www.kap.org.tr/tr/sirketler/KSE"
BORSA_ISTANBUL_TRADED_COMPANIES_URL = (
    "https://www.borsaistanbul.com/sirketler/islem-goren-sirketler"
)

ACTIVE_UNIVERSE_COLUMNS: tuple[str, ...] = (
    "universe_version",
    "as_of_date",
    "security_id",
    "current_ticker",
    "company_name",
    "market_group",
    "market_name",
    "instrument_type",
    "is_active",
    "include_in_v1",
    "official_source_name",
    "official_source_reference",
    "official_source_date",
    "official_source_url",
    "source_record_checksum",
    "notes",
)
AUDIT_EXTRA_COLUMNS: tuple[str, ...] = (
    "candidate_ticker",
    "exclusion_reason",
    "source_market",
    "source_instrument_type",
    "cross_check_status",
)
REVIEW_COLUMNS: tuple[str, ...] = (
    "current_ticker",
    "candidate_historical_ticker",
    "candidate_reason",
    "possible_transition_date",
    "evidence_status",
    "official_source_name",
    "official_source_reference",
    "official_source_url",
    "review_status",
    "notes",
)
COLLECTION_MANIFEST_COLUMNS: tuple[str, ...] = (
    "security_id",
    "current_ticker",
    "provider_ticker",
    "period_start",
    "period_end",
    "mapping_status",
    "mapping_rule_id",
    "isyatirim_symbol",
    "yfinance_symbol",
    "collection_status",
    "notes",
)

_NON_EQUITY_MARKETS = {
    "YAPILANDIRILMIŞ ÜRÜNLER VE FON PAZARI",
    "EMTİA PAZARI",
}
_INSTRUMENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ETF", ("BORSA YATIRIM FONU",)),
    ("FUND", ("YATIRIM FONU", "EMEKLİLİK FONU", "FON SEPETİ")),
    ("WARRANT", ("VARANT",)),
    ("CERTIFICATE", ("SERTİFİKA",)),
    ("RIGHTS_COUPON", ("RÜÇHAN", "YENİ PAY ALMA HAKKI")),
    ("DEBT_INSTRUMENT", ("TAHVİL", "BONO", "BORÇLANMA ARACI")),
    ("LEASE_CERTIFICATE", ("KİRA SERTİFİK",)),
)


class ActiveUniverseError(RuntimeError):
    """Raised when official inputs cannot produce a complete, auditable universe."""


@dataclass(frozen=True)
class OfficialSourceContent:
    source_name: str
    source_url: str
    retrieved_at_utc: str
    as_of_date: str
    raw_content: str
    raw_content_checksum: str
    parser_version: str = PARSER_VERSION
    code_commit_sha: str = "unknown"

    @classmethod
    def from_text(
        cls,
        *,
        source_name: str,
        source_url: str,
        as_of_date: date | str | pd.Timestamp,
        raw_content: str,
        retrieved_at_utc: str | None = None,
        code_commit_sha: str = "unknown",
    ) -> "OfficialSourceContent":
        day = pd.Timestamp(as_of_date).date().isoformat()
        timestamp = retrieved_at_utc or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        return cls(
            source_name=source_name,
            source_url=source_url,
            retrieved_at_utc=timestamp,
            as_of_date=day,
            raw_content=raw_content,
            raw_content_checksum=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
            code_commit_sha=code_commit_sha or "unknown",
        )


@dataclass(frozen=True)
class ActiveUniverseBuild:
    universe: pd.DataFrame
    audit: pd.DataFrame
    summary: Mapping[str, Any]
    mapping_review: pd.DataFrame


@dataclass(frozen=True)
class ActiveUniverseSnapshotBuild:
    build: ActiveUniverseBuild
    source_snapshots: tuple[SnapshotWriteResult, ...]
    active_snapshot: SnapshotWriteResult
    active_universe_file_checksum: str
    mapping_checksum: str


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._in_script = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self.scripts.append("".join(self._parts))
            self._in_script = False
            self._parts = []


class _TextAndLinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.hrefs: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.text.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def fetch_official_sources(
    as_of_date: date | str | pd.Timestamp,
    *,
    timeout_seconds: float = 45.0,
    code_commit_sha: str = "unknown",
    session: requests.Session | None = None,
) -> tuple[OfficialSourceContent, ...]:
    """Fetch all binding pages fail-closed; partial official input is never returned."""

    urls = (
        ("KAP_BIST_COMPANIES", KAP_BIST_COMPANIES_URL),
        ("KAP_MARKETS", KAP_MARKETS_URL),
        ("KAP_ENDED_MEMBERS", KAP_ENDED_MEMBERS_URL),
        ("BORSA_ISTANBUL_TRADED_COMPANIES", BORSA_ISTANBUL_TRADED_COMPANIES_URL),
    )
    client = session or requests.Session()
    headers = {"User-Agent": "bist-ml-model/active-universe-v1"}
    retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results: list[OfficialSourceContent] = []
    try:
        for source_name, url in urls:
            response = client.get(url, timeout=timeout_seconds, headers=headers)
            response.raise_for_status()
            if not response.content:
                raise ActiveUniverseError(f"official source returned empty content: {url}")
            response.encoding = response.encoding or "utf-8"
            results.append(
                OfficialSourceContent.from_text(
                    source_name=source_name,
                    source_url=url,
                    as_of_date=as_of_date,
                    raw_content=response.text,
                    retrieved_at_utc=retrieved,
                    code_commit_sha=code_commit_sha,
                )
            )
    except Exception as exc:
        raise ActiveUniverseError(f"official source acceptance failed: {exc}") from exc
    return tuple(results)


def parse_kap_companies_html(raw_content: str) -> pd.DataFrame:
    groups = _find_data_payload(
        raw_content,
        lambda value: _is_sequence_of_dicts(value, required={"code", "content"}),
        label="KAP BIST companies",
    )
    rows: list[dict[str, Any]] = []
    for group in groups:
        for item in group.get("content", []):
            if not isinstance(item, Mapping):
                continue
            rows.append(
                {
                    "mkk_member_oid": _text(item.get("mkkMemberOid")),
                    "company_name": _text(item.get("kapMemberTitle")),
                    "stock_code": _text(item.get("stockCode")),
                    "city_name": _text(item.get("cityName")),
                    "kap_member_type": _text(item.get("kapMemberType")),
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty or frame["mkk_member_oid"].eq("").any() or frame["company_name"].eq("").any():
        raise ActiveUniverseError("KAP BIST companies payload is empty or incomplete")
    return frame.drop_duplicates().sort_values(
        ["stock_code", "company_name", "mkk_member_oid"]
    ).reset_index(drop=True)


def parse_kap_markets_html(raw_content: str) -> pd.DataFrame:
    groups = _find_data_payload(
        raw_content,
        lambda value: _is_sequence_of_dicts(value, required={"title", "contents"})
        and any(
            isinstance(item, Mapping) and item.get("title") == "PAY PİYASASI"
            for item in value
        ),
        label="KAP markets",
    )
    rows: list[dict[str, Any]] = []
    for market_group in groups:
        group_name = _text(market_group.get("title"))
        for market in market_group.get("contents", []):
            if not isinstance(market, Mapping):
                continue
            for item in market.get("marketDetailContentList", []):
                if not isinstance(item, Mapping):
                    continue
                rows.append(
                    {
                        "market_group": group_name,
                        "financial_market_oid": _text(market.get("financialMarketOid")),
                        "market_name": _text(market.get("marketName")),
                        "market_oid": _text(market.get("marketOid")),
                        "candidate_ticker": _optional_ticker(item.get("stockCode")),
                        "company_name": _text(item.get("title")),
                        "types": _text(item.get("types")),
                        "mkk_member_oid": _text(item.get("mkkMemberOid")),
                        "fund_oid": _text(item.get("fundOid")),
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty or not frame["market_group"].eq("PAY PİYASASI").any():
        raise ActiveUniverseError("KAP markets payload has no Pay Piyasası records")
    return frame.sort_values(
        ["market_group", "market_name", "candidate_ticker", "company_name"]
    ).reset_index(drop=True)


def validate_borsa_istanbul_cross_check(raw_content: str) -> None:
    parser = _TextAndLinkCollector()
    parser.feed(raw_content)
    visible = _search_text(" ".join(parser.text))
    if "islem goren sirketler" not in visible or "pay piyasasinda" not in visible:
        raise ActiveUniverseError("Borsa İstanbul cross-check page lacks Pay Piyasası statement")
    if not any(urlparse(value).netloc.lower().endswith("kap.org.tr") for value in parser.hrefs):
        raise ActiveUniverseError("Borsa İstanbul cross-check page has no KAP company reference")


def build_active_universe(
    *,
    as_of_date: date | str | pd.Timestamp,
    kap_companies: pd.DataFrame,
    kap_markets: pd.DataFrame,
    ended_members: pd.DataFrame,
) -> ActiveUniverseBuild:
    """Create the deterministic included universe and full candidate audit."""

    day = pd.Timestamp(as_of_date).date().isoformat()
    active_oids = set(kap_companies["mkk_member_oid"].astype(str))
    active_codes = {
        normalize_ticker(code)
        for value in kap_companies["stock_code"].astype(str)
        for code in value.split()
        if code.strip()
    }
    ended_oids = set(ended_members["mkk_member_oid"].astype(str)).difference({""})
    audit_rows: list[dict[str, Any]] = []
    for source_row in kap_markets.to_dict(orient="records"):
        ticker = str(source_row["candidate_ticker"])
        instrument_type = _classify_instrument(source_row)
        reason = _exclusion_reason(
            source_row,
            ticker=ticker,
            instrument_type=instrument_type,
            active_oids=active_oids,
            active_codes=active_codes,
            ended_oids=ended_oids,
        )
        include = reason == ""
        reference = ":".join(
            filter(
                None,
                (
                    "KAP_MARKET",
                    str(source_row["financial_market_oid"]),
                    str(source_row["market_oid"]),
                    str(source_row["mkk_member_oid"]),
                    ticker,
                ),
            )
        )
        record_checksum = _record_checksum(source_row)
        audit_rows.append(
            {
                "universe_version": UNIVERSE_VERSION,
                "as_of_date": day,
                "security_id": generate_security_id(ticker) if include else "",
                "current_ticker": ticker if include else "",
                "company_name": str(source_row["company_name"]),
                "market_group": str(source_row["market_group"]),
                "market_name": str(source_row["market_name"]),
                "instrument_type": instrument_type,
                "is_active": bool(include),
                "include_in_v1": bool(include),
                "official_source_name": "KAP_MARKETS",
                "official_source_reference": reference,
                "official_source_date": day,
                "official_source_url": KAP_MARKETS_URL,
                "source_record_checksum": record_checksum,
                "notes": "Exact as-of source observation; no liquidity filter applied.",
                "candidate_ticker": ticker,
                "exclusion_reason": reason,
                "source_market": str(source_row["market_name"]),
                "source_instrument_type": instrument_type,
                "cross_check_status": "PASS_BORSA_ISTANBUL_KAP_REFERENCE",
            }
        )
    audit = pd.DataFrame(audit_rows, columns=[*ACTIVE_UNIVERSE_COLUMNS, *AUDIT_EXTRA_COLUMNS])
    included = audit.loc[audit["include_in_v1"]].copy()
    _validate_included(included)
    universe = included.loc[:, ACTIVE_UNIVERSE_COLUMNS].sort_values(
        ["current_ticker", "security_id"]
    ).reset_index(drop=True)
    audit = audit.sort_values(
        ["include_in_v1", "candidate_ticker", "market_group", "market_name"],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)
    summary = _universe_summary(audit, universe, day)
    review = _mapping_review(universe)
    return ActiveUniverseBuild(universe, audit, summary, review)


def save_official_source_snapshots(
    sources: Sequence[OfficialSourceContent],
    snapshot_store: SnapshotStore,
) -> tuple[SnapshotWriteResult, ...]:
    results: list[SnapshotWriteResult] = []
    for source in sources:
        instrument = source.source_name
        request = SnapshotRequest(
            source="official_reference",
            dataset_type="active_universe_source_html",
            ticker_or_instrument=instrument,
            request_start_date=source.as_of_date,
            request_end_date=source.as_of_date,
            request_parameters={
                "source_name": source.source_name,
                "source_url": source.source_url,
                "as_of_date": source.as_of_date,
                "parser_version": source.parser_version,
            },
            provider_library_version=requests.__version__,
            code_commit_sha=source.code_commit_sha,
            layer="raw",
            identity_columns=("source_name", "as_of_date"),
        )
        frame = pd.DataFrame(
            [
                {
                    "source_name": source.source_name,
                    "source_url": source.source_url,
                    "as_of_date": source.as_of_date,
                    "raw_content": source.raw_content,
                    "raw_content_checksum": source.raw_content_checksum,
                    "parser_version": source.parser_version,
                    "code_commit_sha": source.code_commit_sha,
                }
            ]
        )
        timestamp = pd.Timestamp(source.retrieved_at_utc).to_pydatetime()
        results.append(
            snapshot_store.save_dataframe(frame, request, fetch_timestamp_utc=timestamp)
        )
    return tuple(results)


def save_active_universe_snapshot(
    universe: pd.DataFrame,
    *,
    as_of_date: date | str | pd.Timestamp,
    source_metadata: Sequence[SnapshotMetadata],
    active_universe_file_checksum: str,
    mapping: TickerMapping,
    excluded_candidate_count: int,
    snapshot_store: SnapshotStore,
    code_commit_sha: str = "unknown",
) -> SnapshotWriteResult:
    day = pd.Timestamp(as_of_date).date().isoformat()
    input_ids = tuple(item.snapshot_id for item in source_metadata)
    input_checksums = {
        item.snapshot_id: item.content_checksum for item in source_metadata
    }
    context = {
        "input_snapshot_ids": list(input_ids),
        "input_content_checksums": input_checksums,
        "active_universe_file_checksum": active_universe_file_checksum,
        "ticker_mapping_version": mapping.version,
        "ticker_mapping_checksum": mapping.checksum,
        "as_of_date": day,
        "parser_version": PARSER_VERSION,
        "code_commit_sha": code_commit_sha or "unknown",
        "included_security_count": int(len(universe)),
        "excluded_candidate_count": int(excluded_candidate_count),
    }
    request = SnapshotRequest(
        source="universe",
        dataset_type="active_bist_equities",
        ticker_or_instrument="BIST_ACTIVE_EQUITIES",
        request_start_date=day,
        request_end_date=day,
        request_parameters={"universe_version": UNIVERSE_VERSION, "as_of_date": day},
        code_commit_sha=code_commit_sha,
        layer="derived",
        input_snapshot_ids=input_ids,
        identity_columns=("security_id",),
        revision_context=context,
    )
    snapshot_columns = (
        "security_id",
        "current_ticker",
        "company_name",
        "market_group",
        "market_name",
        "instrument_type",
        "universe_version",
        "as_of_date",
    )
    return snapshot_store.save_dataframe(universe.loc[:, snapshot_columns], request)


def validate_active_universe_snapshot(
    snapshot_store: SnapshotStore, snapshot_id: str
) -> SnapshotMetadata:
    metadata = snapshot_store.get_snapshot(snapshot_id)
    if not snapshot_store.is_usable(metadata):
        raise ActiveUniverseError(f"active universe snapshot is not verified COMPLETE: {snapshot_id}")
    if (metadata.source, metadata.dataset_type, metadata.layer) != (
        "universe",
        "active_bist_equities",
        "derived",
    ):
        raise ActiveUniverseError("snapshot is not universe/active_bist_equities/derived")
    frame = snapshot_store.read_dataframe(metadata)
    required = {
        "security_id",
        "current_ticker",
        "company_name",
        "market_group",
        "market_name",
        "instrument_type",
        "universe_version",
        "as_of_date",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ActiveUniverseError(f"active universe fields missing: {sorted(missing)}")
    if frame.empty or frame["security_id"].astype(str).str.strip().eq("").any():
        raise ActiveUniverseError("active universe has no usable security IDs")
    if frame["security_id"].duplicated().any():
        raise ActiveUniverseError("active universe contains duplicate security_id")
    if frame["current_ticker"].duplicated().any():
        raise ActiveUniverseError("active universe contains duplicate current_ticker")
    required_context = {
        "input_snapshot_ids",
        "input_content_checksums",
        "active_universe_file_checksum",
        "ticker_mapping_version",
        "ticker_mapping_checksum",
        "as_of_date",
        "parser_version",
        "code_commit_sha",
        "included_security_count",
        "excluded_candidate_count",
    }
    missing_context = required_context.difference(metadata.revision_context)
    if missing_context:
        raise ActiveUniverseError(
            f"active universe provenance missing: {sorted(missing_context)}"
        )
    if int(metadata.revision_context["included_security_count"]) != len(frame):
        raise ActiveUniverseError("active universe included count does not match data")
    return metadata


def build_history_collection_manifest(
    active_universe: pd.DataFrame,
    mapping: TickerMapping,
    *,
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
) -> pd.DataFrame:
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    if start > end:
        raise ActiveUniverseError("start_date must be on or before end_date")
    required = {"security_id", "current_ticker"}
    missing = required.difference(active_universe.columns)
    if missing:
        raise ActiveUniverseError(f"active universe fields missing: {sorted(missing)}")
    if active_universe["security_id"].duplicated().any():
        raise ActiveUniverseError("active universe security_id must be unique")
    rows: list[dict[str, Any]] = []
    for security in active_universe.loc[:, ["security_id", "current_ticker"]].sort_values(
        ["security_id", "current_ticker"]
    ).to_dict(orient="records"):
        current = normalize_ticker(security["current_ticker"])
        periods = plan_ticker_collection(current, start, end, mapping)
        for period in periods:
            rows.append(
                {
                    "security_id": str(security["security_id"]),
                    "current_ticker": current,
                    "provider_ticker": period.ticker,
                    "period_start": period.start_date.isoformat(),
                    "period_end": period.end_date.isoformat(),
                    "mapping_status": period.mapping_status,
                    "mapping_rule_id": period.mapping_rule_id or "",
                    "isyatirim_symbol": period.ticker,
                    "yfinance_symbol": period.yfinance_ticker,
                    "collection_status": "PLANNED",
                    "notes": (
                        "First trading date will be resolved during market-data collection."
                        if period.mapping_status == AUTO_NEW_TICKER
                        else "Official date-effective ticker mapping interval."
                    ),
                }
            )
    return pd.DataFrame(rows, columns=COLLECTION_MANIFEST_COLUMNS).sort_values(
        ["security_id", "period_start", "provider_ticker"]
    ).reset_index(drop=True)


def write_csv_deterministic(frame: pd.DataFrame, path: str | Path) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.to_csv(index=False, lineterminator="\n")
    destination.write_text(payload, encoding="utf-8", newline="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_manifest_frame(
    sources: Sequence[OfficialSourceContent],
    snapshots: Sequence[SnapshotWriteResult],
) -> pd.DataFrame:
    if len(sources) != len(snapshots):
        raise ActiveUniverseError("source/snapshot cardinality mismatch")
    return pd.DataFrame(
        [
            {
                "source_name": source.source_name,
                "source_url": source.source_url,
                "retrieved_at_utc": source.retrieved_at_utc,
                "as_of_date": source.as_of_date,
                "raw_content_checksum": source.raw_content_checksum,
                "parser_version": source.parser_version,
                "code_commit_sha": source.code_commit_sha,
                "snapshot_id": snapshot.metadata.snapshot_id,
                "snapshot_content_checksum": snapshot.metadata.content_checksum,
                "created": snapshot.created,
            }
            for source, snapshot in zip(sources, snapshots, strict=True)
        ]
    )


def empty_mapping(path: str | Path) -> TickerMapping:
    source = Path(path)
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        write_csv_deterministic(pd.DataFrame(columns=MAPPING_COLUMNS), source)
    return TickerMapping.from_csv(source)


def _find_data_payload(raw_content: str, predicate: Any, *, label: str) -> Any:
    collector = _ScriptCollector()
    collector.feed(raw_content)
    matches: list[Any] = []
    pattern = re.compile(r"self\.__next_f\.push\((.*)\)\s*$", flags=re.DOTALL)
    for script in collector.scripts:
        match = pattern.search(script.strip())
        if not match:
            continue
        try:
            push_value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(push_value, list) or len(push_value) < 2 or not isinstance(
            push_value[1], str
        ):
            continue
        chunk = push_value[1]
        if ":" not in chunk:
            continue
        try:
            component = json.loads(chunk.split(":", 1)[1].strip())
        except json.JSONDecodeError:
            continue
        for value in _walk_values(component):
            if predicate(value):
                matches.append(value)
    if len(matches) != 1:
        raise ActiveUniverseError(
            f"{label} parser expected one embedded data payload, found {len(matches)}"
        )
    return matches[0]


def _walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _is_sequence_of_dicts(value: Any, *, required: set[str]) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, Mapping) for item in value)
        and all(required.issubset(item) for item in value)
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _search_text(value: str) -> str:
    folded = value.replace("ı", "i").replace("İ", "I").lower()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", folded)
        if not unicodedata.combining(character)
    )


def _optional_ticker(value: Any) -> str:
    text = _text(value)
    return normalize_ticker(text) if text else ""


def _classify_instrument(row: Mapping[str, Any]) -> str:
    title = str(row.get("company_name", "")).upper()
    if str(row.get("fund_oid", "")).strip():
        for instrument_type, patterns in _INSTRUMENT_PATTERNS:
            if any(pattern in title for pattern in patterns):
                return instrument_type
        return "FUND"
    for instrument_type, patterns in _INSTRUMENT_PATTERNS:
        if any(pattern in title for pattern in patterns):
            return instrument_type
    return "EQUITY"


def _exclusion_reason(
    row: Mapping[str, Any],
    *,
    ticker: str,
    instrument_type: str,
    active_oids: set[str],
    active_codes: set[str],
    ended_oids: set[str],
) -> str:
    oid = str(row.get("mkk_member_oid", ""))
    if oid and oid in ended_oids:
        return "KAP_MEMBERSHIP_ENDED"
    if str(row.get("market_group", "")) != "PAY PİYASASI":
        return "NOT_PAY_MARKET"
    if str(row.get("market_name", "")) in _NON_EQUITY_MARKETS:
        return "NON_EQUITY_MARKET"
    if instrument_type != "EQUITY":
        return instrument_type
    if not ticker:
        return "MISSING_TICKER"
    if oid not in active_oids and ticker not in active_codes:
        return "NOT_ACTIVE_KAP_BIST_COMPANY"
    return ""


def _record_checksum(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {str(key): value for key, value in row.items()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_included(included: pd.DataFrame) -> None:
    if included.empty:
        raise ActiveUniverseError("active BIST equity universe is empty")
    if included["current_ticker"].duplicated().any():
        values = sorted(
            included.loc[
                included["current_ticker"].duplicated(keep=False), "current_ticker"
            ].unique()
        )
        raise ActiveUniverseError(f"duplicate included ticker: {values}")
    if included["security_id"].duplicated().any():
        raise ActiveUniverseError("one security_id cannot bind multiple active tickers")
    required_source = (
        "official_source_name",
        "official_source_reference",
        "official_source_date",
        "official_source_url",
        "source_record_checksum",
    )
    if included.loc[:, required_source].astype(str).apply(lambda col: col.str.strip().eq("")).any().any():
        raise ActiveUniverseError("included row lacks official source provenance")


def _universe_summary(
    audit: pd.DataFrame, universe: pd.DataFrame, as_of_date: str
) -> dict[str, Any]:
    excluded = audit.loc[~audit["include_in_v1"]]
    return {
        "universe_version": UNIVERSE_VERSION,
        "as_of_date": as_of_date,
        "candidate_count": int(len(audit)),
        "included_security_count": int(len(universe)),
        "excluded_count": int(len(excluded)),
        "counts_by_market": {
            str(key): int(value)
            for key, value in universe.groupby("market_name").size().sort_index().items()
        },
        "counts_by_instrument_type": {
            str(key): int(value)
            for key, value in audit.groupby("source_instrument_type").size().sort_index().items()
        },
        "counts_by_exclusion_reason": {
            str(key): int(value)
            for key, value in excluded.groupby("exclusion_reason").size().sort_index().items()
        },
        "duplicate_ticker_count": int(universe["current_ticker"].duplicated().sum()),
        "duplicate_security_id_count": int(universe["security_id"].duplicated().sum()),
        "missing_official_source_count": int(
            universe["official_source_reference"].astype(str).str.strip().eq("").sum()
        ),
        "cross_check_mismatch_count": int(
            audit["cross_check_status"].ne("PASS_BORSA_ISTANBUL_KAP_REFERENCE").sum()
        ),
    }


def _mapping_review(universe: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "current_ticker": row.current_ticker,
            "candidate_historical_ticker": "",
            "candidate_reason": "No official historical ticker transition was present in V1 inputs.",
            "possible_transition_date": "",
            "evidence_status": "NO_OFFICIAL_TRANSITION_EVIDENCE",
            "official_source_name": "KAP_MARKETS",
            "official_source_reference": row.official_source_reference,
            "official_source_url": row.official_source_url,
            "review_status": "NO_HISTORICAL_TICKER_FOUND",
            "notes": "Collection continues under the current ticker; no alias was inferred.",
        }
        for row in universe.itertuples(index=False)
    ]
    return pd.DataFrame(rows, columns=REVIEW_COLUMNS).sort_values("current_ticker").reset_index(
        drop=True
    )
