from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.config import MarketDataConfig
from src.data.collectors import MarketDataCollector
from src.data.cleaning_pipeline import CleaningSnapshotSet, MarketDataCleaningPipeline
from src.data.label_pipeline import LabelGenerationPipeline
from src.data.price_limits import PriceStepRule, PriceStepTable
from src.data.security_identity import (
    AUTO_NEW_TICKER,
    MAPPED_CURRENT_TICKER,
    MAPPED_HISTORICAL_TICKER,
    OUTSIDE_VALIDITY,
    TickerMapping,
    TickerMappingError,
    generate_security_id,
    merge_security_history,
    normalize_ticker,
    plan_active_ticker_collection,
    resolve_security_id,
    resolve_tickers_for_security,
    validate_ticker_mapping,
)
from src.data.security_identity_pipeline import SecurityIdentityPipeline
from src.data.snapshot_store import SnapshotRequest, SnapshotStore


MAPPING_COLUMNS = [
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
]
REFERENCE_MAPPING_PATH = (
    Path(__file__).resolve().parents[1]
    / "reference_data"
    / "bist_security_ticker_map_v1.csv"
)


def _mapping_rows() -> list[dict[str, object]]:
    source = {
        "mapping_status": "CONFIRMED",
        "official_source_name": "Borsa Istanbul",
        "official_source_reference": "TEST-DUYURU-1",
        "official_source_date": "2024-01-02",
        "official_source_url": "https://example.test/official/1",
        "notes": "Synthetic unit-test mapping; not reference data.",
    }
    return [
        {
            "security_id": "SEC_TEST001",
            "ticker": "ESKI",
            "valid_from": "2020-03-13",
            "valid_to": "2024-01-03",
            "is_current_ticker": False,
            **source,
        },
        {
            "security_id": "SEC_TEST001",
            "ticker": "YENI",
            "valid_from": "2024-01-04",
            "valid_to": "",
            "is_current_ticker": True,
            **source,
        },
    ]


def _mapping(*, version: str = "test_map_v1") -> TickerMapping:
    return TickerMapping.from_frame(
        pd.DataFrame(_mapping_rows(), columns=MAPPING_COLUMNS),
        version=version,
    )


def _empty_mapping() -> TickerMapping:
    return TickerMapping.from_frame(
        pd.DataFrame(columns=MAPPING_COLUMNS),
        version="empty_v1",
    )


def test_versioned_reference_mapping_schema_loads_without_invented_rows() -> None:
    mapping = TickerMapping.from_csv(REFERENCE_MAPPING_PATH)

    assert mapping.version == "bist_security_ticker_map_v1"
    assert mapping.frame.empty
    assert len(mapping.checksum) == 64


def test_current_and_historical_tickers_resolve_to_one_security() -> None:
    mapping = _mapping()

    historical = resolve_security_id(" eski.is ", "2024-01-03", mapping)
    current = resolve_security_id("yeni", "2024-01-04", mapping)

    assert historical.security_id == current.security_id == "SEC_TEST001"
    assert historical.mapping_status == MAPPED_HISTORICAL_TICKER
    assert current.mapping_status == MAPPED_CURRENT_TICKER
    assert historical.current_ticker == current.current_ticker == "YENI"
    assert historical.mapping_rule_id
    assert current.mapping_rule_id


def test_historical_ticker_outside_validity_is_not_an_effective_match() -> None:
    resolution = resolve_security_id("ESKI", "2024-01-04", _mapping())

    assert resolution.mapping_status == OUTSIDE_VALIDITY
    assert resolution.mapping_rule_id is None


def test_unmapped_ticker_gets_stable_non_blocking_automatic_identity() -> None:
    mapping = _empty_mapping()
    first = resolve_security_id(" thyao.is ", "2024-01-05", mapping)
    second = resolve_security_id("THYAO", "2025-05-06", mapping)

    assert first.security_id == second.security_id == "SEC_444a261b8b9b"
    assert first.mapping_status == second.mapping_status == AUTO_NEW_TICKER
    assert first.current_ticker == "THYAO"
    assert first.mapping_rule_id is None


@pytest.mark.parametrize("ticker", ["thyao", "THYAO", " THYAO.IS "])
def test_normalization_variants_do_not_change_security_id(ticker: str) -> None:
    assert normalize_ticker(ticker) == "THYAO"
    assert generate_security_id(ticker) == "SEC_444a261b8b9b"


def test_explicit_mapping_overrides_automatic_identity() -> None:
    automatic = generate_security_id("YENI")
    mapped = resolve_security_id("YENI", "2024-01-04", _mapping())

    assert mapped.security_id == "SEC_TEST001"
    assert mapped.security_id != automatic


def test_collection_periods_are_inclusive_clipped_and_provider_ready() -> None:
    periods = resolve_tickers_for_security(
        "SEC_TEST001", "2024-01-01", "2024-01-06", _mapping()
    )

    assert [(value.ticker, value.start_date, value.end_date) for value in periods] == [
        ("ESKI", date(2024, 1, 1), date(2024, 1, 3)),
        ("YENI", date(2024, 1, 4), date(2024, 1, 6)),
    ]
    assert [value.yfinance_ticker for value in periods] == ["ESKI.IS", "YENI.IS"]


def test_active_ticker_collection_deduplicates_one_security_plan() -> None:
    periods = plan_active_ticker_collection(
        ["YENI", "yeni.is"], "2024-01-01", "2024-01-06", _mapping()
    )

    assert len(periods) == 2
    assert {value.ticker for value in periods} == {"ESKI", "YENI"}


def test_same_security_overlapping_inclusive_periods_are_rejected() -> None:
    rows = _mapping_rows()
    rows[0]["valid_to"] = "2024-01-04"

    with pytest.raises(TickerMappingError, match="same security_id overlap"):
        validate_ticker_mapping(pd.DataFrame(rows, columns=MAPPING_COLUMNS))


def test_same_ticker_cannot_map_to_two_securities_on_one_date() -> None:
    rows = _mapping_rows()
    duplicate = dict(rows[0])
    duplicate["security_id"] = "SEC_OTHER"
    duplicate["is_current_ticker"] = False
    rows[0]["is_current_ticker"] = False
    rows.append(duplicate)

    with pytest.raises(TickerMappingError, match="maps ambiguously"):
        validate_ticker_mapping(pd.DataFrame(rows, columns=MAPPING_COLUMNS))


def test_confirmed_mapping_requires_official_source_metadata() -> None:
    rows = _mapping_rows()
    rows[0]["official_source_url"] = ""

    with pytest.raises(TickerMappingError, match="official source"):
        validate_ticker_mapping(pd.DataFrame(rows, columns=MAPPING_COLUMNS))


def test_observed_ticker_is_preserved_and_current_ticker_is_added() -> None:
    source = pd.DataFrame(
        {"ticker": ["ESKI"], "date": ["2024-01-03"], "value": [1]}
    )
    result = merge_security_history(source, _mapping())

    assert result.loc[0, "ticker"] == "ESKI"
    assert result.loc[0, "observed_ticker"] == "ESKI"
    assert result.loc[0, "current_ticker"] == "YENI"


def test_mapped_old_and_new_periods_form_one_security_series() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["ESKI", "YENI"],
            "date": ["2024-01-03", "2024-01-04"],
            "value": [1, 2],
        }
    )
    result = merge_security_history(source, _mapping())

    assert result["security_id"].tolist() == ["SEC_TEST001", "SEC_TEST001"]
    assert result["observed_ticker"].tolist() == ["ESKI", "YENI"]


def test_unmapped_tickers_remain_separate_security_series() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "date": ["2024-01-03", "2024-01-03"],
        }
    )
    result = merge_security_history(source, _empty_mapping())

    assert result["security_id"].nunique() == 2
    assert result["ticker_mapping_status"].eq(AUTO_NEW_TICKER).all()


def test_mapping_update_can_merge_previously_separate_series() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["ESKI", "YENI"],
            "date": ["2024-01-03", "2024-01-04"],
        }
    )

    before = merge_security_history(source, _empty_mapping())
    after = merge_security_history(source, _mapping())

    assert before["security_id"].nunique() == 2
    assert after["security_id"].nunique() == 1


def test_out_of_period_provider_row_cannot_duplicate_effective_mapping_row() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["ESKI", "YENI"],
            "date": ["2024-01-03", "2024-01-03"],
            "value": [10, 999],
        }
    )
    result = merge_security_history(source, _mapping())

    assert len(result) == 1
    assert result.loc[0, "observed_ticker"] == "ESKI"
    assert result.loc[0, "value"] == 10


def test_short_history_new_listing_is_accepted() -> None:
    source = pd.DataFrame(
        {"ticker": ["YENIHALKAARZ"], "date": ["2026-07-24"], "value": [1]}
    )
    result = merge_security_history(source, _empty_mapping())

    assert len(result) == 1
    assert result.loc[0, "ticker_mapping_status"] == AUTO_NEW_TICKER


def _config(tmp_path: Path) -> MarketDataConfig:
    return replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )


def _save_nominal(
    store: SnapshotStore,
    ticker: str,
    dates: list[str],
) -> str:
    raw = store.save_dataframe(
        pd.DataFrame(
            {
                "ticker": [ticker] * len(dates),
                "date": dates,
                "Open": [10.0] * len(dates),
            }
        ),
        SnapshotRequest(
            source="yfinance",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=min(dates),
            request_end_date=max(dates),
            request_parameters={"test": True},
            layer="raw",
            identity_columns=("ticker", "date"),
        ),
    ).metadata
    nominal = store.save_dataframe(
        pd.DataFrame(
            {
                "ticker": [ticker] * len(dates),
                "date": dates,
                "yf_nominal_open": [10.0] * len(dates),
                "yf_nominal_high": [10.5] * len(dates),
                "yf_nominal_low": [9.5] * len(dates),
                "yf_nominal_close": [10.0] * len(dates),
            }
        ),
        SnapshotRequest(
            source="yfinance",
            dataset_type="nominal_ohlc",
            ticker_or_instrument=ticker,
            request_start_date=min(dates),
            request_end_date=max(dates),
            request_parameters={"test": True},
            layer="derived",
            input_snapshot_ids=(raw.snapshot_id,),
            identity_columns=("ticker", "date"),
        ),
    ).metadata
    return nominal.snapshot_id


def _save_isyatirim(
    store: SnapshotStore,
    ticker: str,
    dates: list[str],
) -> str:
    count = len(dates)
    frame = pd.DataFrame(
        {
            "HGDG_HS_KODU": [ticker] * count,
            "HGDG_TARIH": dates,
            "HGDG_KAPANIS": [10.0] * count,
            "HGDG_AOF": [10.0] * count,
            "HGDG_MIN": [9.5] * count,
            "HGDG_MAX": [10.5] * count,
            "HGDG_HACIM": [1000.0] * count,
            "HG_KAPANIS": [10.0] * count,
            "HG_AOF": [10.0] * count,
            "HG_MIN": [9.5] * count,
            "HG_MAX": [10.5] * count,
            "HG_HACIM": [1000.0] * count,
        }
    )
    return store.save_dataframe(
        frame,
        SnapshotRequest(
            source="isyatirim",
            dataset_type="equity_history",
            ticker_or_instrument=ticker,
            request_start_date=min(dates),
            request_end_date=max(dates),
            request_parameters={"test": True},
            layer="raw",
            identity_columns=("HGDG_HS_KODU", "HGDG_TARIH"),
        ),
    ).metadata.snapshot_id


def test_identity_pipeline_records_mapping_checksum_and_is_idempotent(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    nominal_id = _save_nominal(store, "THYAO", ["2024-01-03"])
    mapping = _empty_mapping()
    pipeline = SecurityIdentityPipeline(
        config, snapshot_store=store, code_commit_sha="a" * 40
    )

    first = pipeline.run([nominal_id], mapping)
    second = pipeline.run([nominal_id], mapping)

    assert first.snapshot.metadata.request_parameters[
        "ticker_mapping_checksum"
    ] == mapping.checksum
    assert first.snapshot.metadata.revision_context["code_commit_sha"] == "a" * 40
    assert first.snapshot.metadata.revision_context[
        "input_content_checksums"
    ] == {
        nominal_id: store.get_snapshot(nominal_id).content_checksum,
    }
    assert first.frame.loc[0, "security_id"] == "SEC_444a261b8b9b"
    assert first.snapshot.metadata.snapshot_id == second.snapshot.metadata.snapshot_id
    assert not second.snapshot.created


def test_identity_code_change_creates_new_revision_with_same_content(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    nominal_id = _save_nominal(store, "THYAO", ["2024-01-03"])
    mapping = _empty_mapping()

    first = SecurityIdentityPipeline(
        config, snapshot_store=store, code_commit_sha="a" * 40
    ).run([nominal_id], mapping)
    second = SecurityIdentityPipeline(
        config, snapshot_store=store, code_commit_sha="b" * 40
    ).run([nominal_id], mapping)

    assert second.snapshot.created
    assert second.snapshot.metadata.snapshot_id != first.snapshot.metadata.snapshot_id
    assert second.snapshot.metadata.revision_number == 2
    assert (
        second.snapshot.metadata.content_checksum
        == first.snapshot.metadata.content_checksum
    )
    assert second.snapshot.metadata.revision_context["code_commit_sha"] == "b" * 40


def test_mapping_change_creates_new_snapshot_and_preserves_old_snapshot(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    old_id = _save_nominal(store, "ESKI", ["2024-01-03"])
    new_id = _save_nominal(store, "YENI", ["2024-01-04"])
    pipeline = SecurityIdentityPipeline(config, snapshot_store=store)
    first = pipeline.run([old_id, new_id], _empty_mapping())
    second = pipeline.run([old_id, new_id], _mapping(version="test_map_v2"))

    assert first.snapshot.metadata.snapshot_id != second.snapshot.metadata.snapshot_id
    assert second.snapshot.created
    assert store.is_usable(first.snapshot.metadata)
    assert store.is_usable(second.snapshot.metadata)
    assert first.frame["security_id"].nunique() == 2
    assert second.frame["security_id"].nunique() == 1


def test_identity_series_flows_through_cleaning_and_labels(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    old_dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    new_dates = ["2024-01-04", "2024-01-05", "2024-01-06"]
    old_nominal = _save_nominal(store, "ESKI", old_dates)
    new_nominal = _save_nominal(store, "YENI", new_dates)
    old_yf_raw = store.get_snapshot(old_nominal).input_snapshot_ids[0]
    new_yf_raw = store.get_snapshot(new_nominal).input_snapshot_ids[0]
    old_is_raw = _save_isyatirim(store, "ESKI", old_dates)
    new_is_raw = _save_isyatirim(store, "YENI", new_dates)
    mapping = _mapping()
    identity = SecurityIdentityPipeline(
        config, snapshot_store=store, code_commit_sha="b" * 40
    ).run([old_nominal, new_nominal], mapping)
    steps = PriceStepTable(
        [PriceStepRule("2020-03-13", None, "0", None, "0.01")]
    )

    clean = MarketDataCleaningPipeline(
        config, snapshot_store=store, code_commit_sha="c" * 40
    ).run(
        [
            CleaningSnapshotSet("ESKI", old_is_raw, old_yf_raw, old_nominal),
            CleaningSnapshotSet("YENI", new_is_raw, new_yf_raw, new_nominal),
        ],
        steps,
        security_identity_snapshot_id=identity.snapshot.metadata.snapshot_id,
        ticker_mapping=mapping,
    )
    labels = LabelGenerationPipeline(
        config, snapshot_store=store, code_commit_sha="d" * 40
    ).run(clean.snapshot.metadata.snapshot_id, steps)

    assert clean.frame["security_id"].nunique() == 1
    assert clean.frame["security_id"].eq("SEC_TEST001").all()
    assert set(clean.frame["observed_ticker"].dropna()) == {"ESKI", "YENI"}
    assert clean.frame["current_ticker"].eq("YENI").all()
    expected_row_inputs = {
        "ESKI": [old_is_raw, old_yf_raw, old_nominal],
        "YENI": [new_is_raw, new_yf_raw, new_nominal],
    }
    expected_row_checksums = {
        ticker: [store.get_snapshot(snapshot_id).content_checksum for snapshot_id in ids]
        for ticker, ids in expected_row_inputs.items()
    }
    for row in clean.frame.itertuples(index=False):
        assert row.input_snapshot_ids == expected_row_inputs[row.ticker]
        assert row.input_snapshot_checksums == expected_row_checksums[row.ticker]
        assert len(row.input_snapshot_ids) == 3
        assert len(row.input_snapshot_checksums) == 3
    assert clean.snapshot.metadata.input_snapshot_ids == (
        old_is_raw,
        old_yf_raw,
        old_nominal,
        new_is_raw,
        new_yf_raw,
        new_nominal,
        identity.snapshot.metadata.snapshot_id,
    )
    assert clean.snapshot.metadata.identity_columns == (
        "security_id",
        "prediction_date",
    )
    assert labels.frame["security_id"].eq("SEC_TEST001").all()
    assert labels.snapshot.metadata.identity_columns == (
        "security_id",
        "prediction_date",
    )
    assert labels.snapshot.metadata.request_parameters[
        "ticker_mapping_checksum"
    ] == mapping.checksum


class _DynamicIsYatirim:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date, date]] = []

    def fetch_history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        return pd.DataFrame(
            {
                "HGDG_HS_KODU": [ticker],
                "HGDG_TARIH": [start],
                "HGDG_KAPANIS": [10.0],
                "HGDG_AOF": [10.0],
                "HGDG_MIN": [9.0],
                "HGDG_MAX": [11.0],
                "HGDG_HACIM": [1000.0],
                "HG_KAPANIS": [10.0],
                "HG_AOF": [10.0],
                "HG_MIN": [9.0],
                "HG_MAX": [11.0],
                "HG_HACIM": [1000.0],
                "END_ENDEKS_KODU": ["XU100"],
                "END_TARIH": [1],
                "END_SEANS": [2],
                "END_DEGER": [1.0],
                "PD": [1.0],
                "PD_USD": [1.0],
                "HAO_PD": [1.0],
                "HAO_PD_USD": [1.0],
            }
        )


def test_collector_queries_each_mapped_ticker_only_in_its_valid_period(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    is_client = _DynamicIsYatirim()
    yf_calls: list[tuple[str, date, date]] = []

    def fetch_yfinance(
        ticker: str, start: date, end: date, _: float
    ) -> pd.DataFrame:
        yf_calls.append((ticker, start, end))
        return pd.DataFrame(
            {
                "Open": [10.0],
                "High": [11.0],
                "Low": [9.0],
                "Close": [10.0],
                "Adj Close": [10.0],
                "Volume": [100.0],
                "Dividends": [0.0],
                "Stock Splits": [0.0],
            },
            index=pd.DatetimeIndex([pd.Timestamp(start)], name="Date"),
        )

    result = MarketDataCollector(
        config,
        isyatirim_client=is_client,
        yfinance_fetcher=fetch_yfinance,
        ticker_mapping=_mapping(),
        sleep_func=lambda _: None,
    ).collect_many(["YENI"], date(2024, 1, 1), date(2024, 1, 6))

    expected = [
        ("ESKI", date(2024, 1, 1), date(2024, 1, 3)),
        ("YENI", date(2024, 1, 4), date(2024, 1, 6)),
    ]
    assert is_client.calls == expected
    assert yf_calls == expected
    assert len(result) == 2
    assert all(value.complete for value in result)


def test_unmapped_collector_request_is_direct_and_non_blocking(tmp_path: Path) -> None:
    periods = plan_active_ticker_collection(
        ["YENIHALKAARZ"],
        date(2026, 7, 20),
        date(2026, 7, 24),
        _empty_mapping(),
    )

    assert len(periods) == 1
    assert periods[0].ticker == "YENIHALKAARZ"
    assert periods[0].mapping_status == AUTO_NEW_TICKER
