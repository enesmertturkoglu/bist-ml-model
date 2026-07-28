from __future__ import annotations

from dataclasses import replace
import json

import pandas as pd
import pytest

from src.config import MarketDataConfig
from src.data.active_universe import (
    ACTIVE_UNIVERSE_COLUMNS,
    ActiveUniverseError,
    OfficialSourceContent,
    build_active_universe,
    build_history_collection_manifest,
    parse_kap_companies_html,
    parse_kap_markets_html,
    save_active_universe_snapshot,
    save_official_source_snapshots,
    validate_active_universe_snapshot,
    validate_borsa_istanbul_cross_check,
)
from src.data.security_identity import MAPPING_COLUMNS, TickerMapping, generate_security_id
from src.data.snapshot_store import SnapshotRequest, SnapshotStore
from src.modeling.prediction_universe import (
    PredictionUniverseError,
    PredictionUniverseInputAssembler,
)


def _flight_html(data: object) -> str:
    component = ["$", "div", None, {"children": ["$", "component", None, {"data": data}]}]
    pushed = json.dumps([1, "15:" + json.dumps(component, ensure_ascii=False)], ensure_ascii=False)
    return f"<html><body><script>self.__next_f.push({pushed})</script></body></html>"


def _company_groups(*, ended: bool = False) -> list[dict[str, object]]:
    rows = [
        {
            "mkkMemberOid": "OID_AAA",
            "kapMemberTitle": "AAA SANAYİ A.Ş.",
            "stockCode": "AAA",
            "cityName": "İSTANBUL",
            "kapMemberType": "IGS",
        },
        {
            "mkkMemberOid": "OID_CLASS",
            "kapMemberTitle": "SINIFLI PAYLAR A.Ş.",
            "stockCode": "CLSA CLSB",
            "cityName": "ANKARA",
            "kapMemberType": "IGS",
        },
        {
            "mkkMemberOid": "OID_HALT",
            "kapMemberTitle": "GEÇİCİ KAPALI A.Ş.",
            "stockCode": "HALT",
            "cityName": "İZMİR",
            "kapMemberType": "IGS",
        },
        {
            "mkkMemberOid": "OID_END",
            "kapMemberTitle": "ÜYELİĞİ SONA EREN A.Ş.",
            "stockCode": "ENDED",
            "cityName": "BURSA",
            "kapMemberType": "IGS",
        },
    ]
    if ended:
        rows = [rows[-1]]
    return [{"code": "A", "content": rows}]


def _market_groups(*, duplicate: bool = False) -> list[dict[str, object]]:
    equities = [
        {
            "stockCode": "AAA",
            "title": "AAA SANAYİ A.Ş.",
            "types": "IGS",
            "mkkMemberOid": "OID_AAA",
            "fundOid": None,
        },
        {
            "stockCode": "CLSA",
            "title": "SINIFLI PAYLAR A.Ş. A GRUBU",
            "types": "IGS",
            "mkkMemberOid": "OID_CLASS",
            "fundOid": None,
        },
        {
            "stockCode": "CLSB",
            "title": "SINIFLI PAYLAR A.Ş. B GRUBU",
            "types": "IGS",
            "mkkMemberOid": "OID_CLASS",
            "fundOid": None,
        },
        {
            "stockCode": "HALT",
            "title": "GEÇİCİ KAPALI A.Ş.",
            "types": "IGS,TEMPORARILY_HALTED",
            "mkkMemberOid": "OID_HALT",
            "fundOid": None,
        },
        {
            "stockCode": "ENDED",
            "title": "ÜYELİĞİ SONA EREN A.Ş.",
            "types": "IGS",
            "mkkMemberOid": "OID_END",
            "fundOid": None,
        },
        {
            "stockCode": "ETF1",
            "title": "ÖRNEK BORSA YATIRIM FONU",
            "types": "FON",
            "mkkMemberOid": None,
            "fundOid": "FUND_1",
        },
        {
            "stockCode": "FUND1",
            "title": "ÖRNEK YATIRIM FONU",
            "types": "FON",
            "mkkMemberOid": None,
            "fundOid": "FUND_2",
        },
        {
            "stockCode": "WAR1",
            "title": "ÖRNEK VARANT",
            "types": "VARANT",
            "mkkMemberOid": None,
            "fundOid": None,
        },
        {
            "stockCode": "CERT1",
            "title": "ÖRNEK ALTIN SERTİFİKASI",
            "types": "SERTİFİKA",
            "mkkMemberOid": None,
            "fundOid": None,
        },
        {
            "stockCode": "RGT1",
            "title": "ÖRNEK RÜÇHAN KUPONU",
            "types": "RÜÇHAN",
            "mkkMemberOid": None,
            "fundOid": None,
        },
    ]
    if duplicate:
        equities.append(dict(equities[0]))
    return [
        {
            "title": "PAY PİYASASI",
            "contents": [
                {
                    "financialMarketOid": "FM_PAY",
                    "financialMarketName": "PAY PİYASASI",
                    "marketOid": "M_YILDIZ",
                    "marketName": "YILDIZ PAZAR",
                    "marketDetailContentList": equities,
                },
                {
                    "financialMarketOid": "FM_PAY",
                    "financialMarketName": "PAY PİYASASI",
                    "marketOid": "M_STRUCTURED",
                    "marketName": "YAPILANDIRILMIŞ ÜRÜNLER VE FON PAZARI",
                    "marketDetailContentList": [dict(equities[0])],
                },
            ],
        }
    ]


def _frames(*, duplicate: bool = False):
    companies = parse_kap_companies_html(_flight_html(_company_groups()))
    markets = parse_kap_markets_html(_flight_html(_market_groups(duplicate=duplicate)))
    ended = parse_kap_companies_html(_flight_html(_company_groups(ended=True)))
    return companies, markets, ended


def _build(*, duplicate: bool = False):
    companies, markets, ended = _frames(duplicate=duplicate)
    return build_active_universe(
        as_of_date="2026-07-29",
        kap_companies=companies,
        kap_markets=markets,
        ended_members=ended,
    )


def _empty_mapping() -> TickerMapping:
    return TickerMapping.from_frame(pd.DataFrame(columns=MAPPING_COLUMNS), version="empty_v1")


def _config(tmp_path) -> MarketDataConfig:
    return replace(MarketDataConfig(), data_root=tmp_path / "data")


def test_official_react_flight_fixtures_build_deterministic_universe() -> None:
    first = _build()
    second = _build()

    pd.testing.assert_frame_equal(first.universe, second.universe)
    assert first.summary == second.summary
    assert first.universe["current_ticker"].tolist() == ["AAA", "CLSA", "CLSB", "HALT"]
    assert set(first.universe.columns) == set(ACTIVE_UNIVERSE_COLUMNS)


def test_duplicate_included_ticker_fails_closed() -> None:
    with pytest.raises(ActiveUniverseError, match="duplicate included ticker"):
        _build(duplicate=True)


def test_one_security_id_cannot_bind_two_active_tickers(monkeypatch) -> None:
    monkeypatch.setattr("src.data.active_universe.generate_security_id", lambda ticker: "SEC_ONE")

    with pytest.raises(ActiveUniverseError, match="security_id"):
        _build()


def test_non_equity_instruments_are_excluded_with_reasons() -> None:
    build = _build()
    reasons = dict(
        build.audit.loc[
            build.audit["candidate_ticker"].isin(
                ["ETF1", "FUND1", "WAR1", "CERT1", "RGT1"]
            ),
            ["candidate_ticker", "exclusion_reason"],
        ].itertuples(index=False, name=None)
    )

    assert reasons == {
        "ETF1": "ETF",
        "FUND1": "FUND",
        "WAR1": "WARRANT",
        "CERT1": "CERTIFICATE",
        "RGT1": "RIGHTS_COUPON",
    }


def test_separate_share_classes_remain_separate_securities() -> None:
    classes = _build().universe.query("current_ticker in ['CLSA', 'CLSB']")

    assert classes["security_id"].nunique() == 2
    assert set(classes["security_id"]) == {
        generate_security_id("CLSA"),
        generate_security_id("CLSB"),
    }


def test_temporary_non_trading_marker_does_not_remove_master_member() -> None:
    assert "HALT" in set(_build().universe["current_ticker"])


def test_ended_kap_member_is_excluded() -> None:
    ended = _build().audit.query("candidate_ticker == 'ENDED'").iloc[0]

    assert not ended["include_in_v1"]
    assert ended["exclusion_reason"] == "KAP_MEMBERSHIP_ENDED"


def test_every_included_row_has_official_source_provenance() -> None:
    universe = _build().universe
    fields = [
        "official_source_name",
        "official_source_reference",
        "official_source_date",
        "official_source_url",
        "source_record_checksum",
    ]

    assert not universe[fields].astype(str).apply(lambda col: col.str.strip().eq("")).any().any()


def test_unverified_historical_alias_is_review_only_and_not_mapping() -> None:
    build = _build()

    assert build.mapping_review["review_status"].eq(
        "NO_HISTORICAL_TICKER_FOUND"
    ).all()
    assert build.mapping_review["candidate_historical_ticker"].eq("").all()
    assert _empty_mapping().frame.empty


def test_borsa_istanbul_cross_check_requires_pay_market_and_kap_link() -> None:
    validate_borsa_istanbul_cross_check(
        '<h1>İşlem Gören Şirketler</h1><p>Pay Piyasasında işlem görür.</p>'
        '<a href="https://www.kap.org.tr/tr/bist-sirketler">KAP</a>'
    )

    with pytest.raises(ActiveUniverseError):
        validate_borsa_istanbul_cross_check("<p>Eksik kaynak</p>")


def test_source_and_derived_snapshots_are_idempotent_and_checksum_sensitive(tmp_path) -> None:
    store = SnapshotStore(_config(tmp_path))
    sources = (
        OfficialSourceContent.from_text(
            source_name="KAP_MARKETS",
            source_url="https://www.kap.org.tr/tr/Pazarlar",
            as_of_date="2026-07-29",
            raw_content="same-content",
            retrieved_at_utc="2026-07-29T10:00:00Z",
            code_commit_sha="a" * 40,
        ),
    )
    first_source = save_official_source_snapshots(sources, store)
    second_source = save_official_source_snapshots(sources, store)
    universe = _build().universe
    mapping = _empty_mapping()
    first = save_active_universe_snapshot(
        universe,
        as_of_date="2026-07-29",
        source_metadata=[first_source[0].metadata],
        active_universe_file_checksum="u" * 64,
        mapping=mapping,
        excluded_candidate_count=5,
        snapshot_store=store,
        code_commit_sha="a" * 40,
    )
    second = save_active_universe_snapshot(
        universe,
        as_of_date="2026-07-29",
        source_metadata=[second_source[0].metadata],
        active_universe_file_checksum="u" * 64,
        mapping=mapping,
        excluded_candidate_count=5,
        snapshot_store=store,
        code_commit_sha="a" * 40,
    )
    changed_source = save_official_source_snapshots(
        (
            OfficialSourceContent.from_text(
                source_name="KAP_MARKETS",
                source_url="https://www.kap.org.tr/tr/Pazarlar",
                as_of_date="2026-07-29",
                raw_content="changed-content",
                retrieved_at_utc="2026-07-29T11:00:00Z",
                code_commit_sha="a" * 40,
            ),
        ),
        store,
    )
    changed = save_active_universe_snapshot(
        universe,
        as_of_date="2026-07-29",
        source_metadata=[changed_source[0].metadata],
        active_universe_file_checksum="u" * 64,
        mapping=mapping,
        excluded_candidate_count=5,
        snapshot_store=store,
        code_commit_sha="a" * 40,
    )

    assert first_source[0].created
    assert not second_source[0].created
    assert first.metadata.snapshot_id == second.metadata.snapshot_id
    assert not second.created
    assert changed_source[0].metadata.revision_number == 2
    assert changed.metadata.snapshot_id != first.metadata.snapshot_id
    assert changed.metadata.revision_number == 2
    validate_active_universe_snapshot(store, changed.metadata.snapshot_id)


def test_collection_manifest_splits_confirmed_mapping_intervals() -> None:
    security_id = generate_security_id("NEW")
    source = {
        "mapping_status": "CONFIRMED",
        "official_source_name": "KAP",
        "official_source_reference": "OFFICIAL-1",
        "official_source_date": "2024-01-02",
        "official_source_url": "https://www.kap.org.tr/tr/Bildirim/1",
        "notes": "Verified transition.",
    }
    mapping = TickerMapping.from_frame(
        pd.DataFrame(
            [
                {
                    "security_id": security_id,
                    "ticker": "OLD",
                    "valid_from": "2020-03-13",
                    "valid_to": "2024-01-03",
                    "is_current_ticker": False,
                    **source,
                },
                {
                    "security_id": security_id,
                    "ticker": "NEW",
                    "valid_from": "2024-01-04",
                    "valid_to": "",
                    "is_current_ticker": True,
                    **source,
                },
            ],
            columns=MAPPING_COLUMNS,
        )
    )
    universe = pd.DataFrame({"security_id": [security_id], "current_ticker": ["NEW"]})
    manifest = build_history_collection_manifest(
        universe, mapping, start_date="2020-03-13", end_date="2026-07-29"
    )

    assert manifest["provider_ticker"].tolist() == ["OLD", "NEW"]
    assert manifest["period_start"].tolist() == ["2020-03-13", "2024-01-04"]
    assert manifest["period_end"].tolist() == ["2024-01-03", "2026-07-29"]
    assert manifest["yfinance_symbol"].tolist() == ["OLD.IS", "NEW.IS"]


def test_production_assembler_requires_explicit_active_universe_snapshot(tmp_path) -> None:
    assembler = PredictionUniverseInputAssembler(SnapshotStore(_config(tmp_path)))

    with pytest.raises(PredictionUniverseError, match="active_universe_snapshot_id"):
        assembler.assemble(
            yfinance_raw_snapshot_ids=[],
            isyatirim_raw_snapshot_ids=[],
            identity_snapshot_id="identity",
            active_universe_snapshot_id="",
            feature_snapshot_id="feature",
            xu100_snapshot_id="xu100",
            calendar_snapshot_id="calendar",
        )


def test_identity_snapshot_cannot_be_used_as_master_universe(tmp_path) -> None:
    store = SnapshotStore(_config(tmp_path))
    identity = store.save_dataframe(
        pd.DataFrame({"security_id": ["SEC_A"], "date": ["2026-07-29"]}),
        SnapshotRequest(
            source="security_identity",
            dataset_type="nominal_ohlc",
            ticker_or_instrument="ALL_SECURITIES",
            request_start_date="2026-07-29",
            request_end_date="2026-07-29",
            layer="derived",
        ),
    )
    assembler = PredictionUniverseInputAssembler(store)

    with pytest.raises(ActiveUniverseError, match="not universe"):
        assembler.assemble(
            yfinance_raw_snapshot_ids=["raw-yf"],
            isyatirim_raw_snapshot_ids=["raw-is"],
            identity_snapshot_id=identity.metadata.snapshot_id,
            active_universe_snapshot_id=identity.metadata.snapshot_id,
            feature_snapshot_id="feature",
            xu100_snapshot_id="xu100",
            calendar_snapshot_id="calendar",
        )
