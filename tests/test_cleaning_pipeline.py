from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.config import MarketDataConfig, SnapshotStatus
from src.data.cleaning_pipeline import (
    CleaningInputError,
    CleaningSnapshotSet,
    MarketDataCleaningPipeline,
)
from src.data.price_limits import PriceStepRule, PriceStepTable
from src.data.snapshot_store import SnapshotRequest, SnapshotStore


DATES = pd.date_range("2024-01-01", periods=6, freq="D")


def _config(tmp_path: Path) -> MarketDataConfig:
    return replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )


def _request(
    source: str,
    dataset_type: str,
    *,
    layer: str,
    input_snapshot_ids: tuple[str, ...] = (),
) -> SnapshotRequest:
    return SnapshotRequest(
        source=source,
        dataset_type=dataset_type,
        ticker_or_instrument="AAA",
        request_start_date="2024-01-01",
        request_end_date="2024-01-06",
        request_parameters={"test": True},
        provider_library_version="test-1",
        code_commit_sha="a" * 40,
        layer=layer,
        input_snapshot_ids=input_snapshot_ids,
        identity_columns=(
            ("HGDG_HS_KODU", "HGDG_TARIH")
            if source == "isyatirim"
            else ("ticker", "date")
        ),
    )


def _is_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "HGDG_HS_KODU": ["AAA"] * len(DATES),
            "HGDG_TARIH": DATES,
            "HGDG_KAPANIS": [10.0] * len(DATES),
            "HGDG_AOF": [10.0] * len(DATES),
            "HGDG_MIN": [9.5] * len(DATES),
            "HGDG_MAX": [10.5] * len(DATES),
            "HGDG_HACIM": [1000.0] * len(DATES),
            "HG_KAPANIS": [10.0] * len(DATES),
            "HG_AOF": [10.0] * len(DATES),
            "HG_MIN": [9.5] * len(DATES),
            "HG_MAX": [10.5] * len(DATES),
            "HG_HACIM": [1000.0] * len(DATES),
        }
    )


def _yf_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA"] * len(DATES),
            "date": DATES,
            "Open": [10.0] * len(DATES),
            "High": [10.5] * len(DATES),
            "Low": [9.5] * len(DATES),
            "Close": [10.0] * len(DATES),
            "Adj Close": [10.0] * len(DATES),
            "Volume": [100.0] * len(DATES),
            "Dividends": [0.0] * len(DATES),
            "Stock Splits": [0.0] * len(DATES),
        }
    )


def _nominal() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA"] * len(DATES),
            "date": DATES,
            "yf_nominal_open": [10.0] * len(DATES),
            "yf_nominal_high": [10.5] * len(DATES),
            "yf_nominal_low": [9.5] * len(DATES),
            "yf_nominal_close": [10.0] * len(DATES),
            "yf_future_split_factor": [1.0] * len(DATES),
        }
    )


def _inputs(
    store: SnapshotStore,
    *,
    is_status: SnapshotStatus = SnapshotStatus.COMPLETE,
    correct_nominal_link: bool = True,
) -> CleaningSnapshotSet:
    is_snapshot = store.save_dataframe(
        _is_raw(),
        _request("isyatirim", "equity_history", layer="raw"),
        status=is_status,
    ).metadata
    yf_snapshot = store.save_dataframe(
        _yf_raw(),
        _request("yfinance", "equity_history", layer="raw"),
    ).metadata
    nominal_snapshot = store.save_dataframe(
        _nominal(),
        _request(
            "yfinance",
            "nominal_ohlc",
            layer="derived",
            input_snapshot_ids=(
                (yf_snapshot.snapshot_id,) if correct_nominal_link else ("wrong_raw_id",)
            ),
        ),
    ).metadata
    return CleaningSnapshotSet(
        "AAA",
        is_snapshot.snapshot_id,
        yf_snapshot.snapshot_id,
        nominal_snapshot.snapshot_id,
    )


def _steps() -> PriceStepTable:
    return PriceStepTable(
        [PriceStepRule("2020-01-01", None, "0", None, "0.01")]
    )


def test_pipeline_writes_verified_derived_clean_snapshot(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)

    result = MarketDataCleaningPipeline(
        config,
        snapshot_store=store,
        code_commit_sha="b" * 40,
    ).run([inputs], _steps())

    assert result.snapshot.created
    assert result.snapshot.metadata.source == "cleaning"
    assert result.snapshot.metadata.layer == "derived"
    assert result.snapshot.metadata.input_snapshot_ids == inputs.input_snapshot_ids
    assert store.is_usable(result.snapshot.metadata)
    assert result.summary["entry_eligible_true"] == 3


def test_pipeline_records_input_ids_checksums_and_cleaning_identity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)

    result = MarketDataCleaningPipeline(
        config,
        snapshot_store=store,
        code_commit_sha="c" * 40,
    ).run([inputs], _steps())
    row = result.frame.iloc[0]

    assert row["input_snapshot_ids"] == list(inputs.input_snapshot_ids)
    assert len(row["input_snapshot_checksums"]) == 3
    assert row["cleaning_config_checksum"] == config.cleaning.checksum()
    assert row["cleaning_code_commit_sha"] == "c" * 40


def test_pipeline_rejects_non_complete_input(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store, is_status=SnapshotStatus.PARTIAL)

    with pytest.raises(CleaningInputError, match="verified COMPLETE"):
        MarketDataCleaningPipeline(config, snapshot_store=store).run([inputs], _steps())


def test_pipeline_rejects_nominal_snapshot_with_wrong_raw_link(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store, correct_nominal_link=False)

    with pytest.raises(CleaningInputError, match="does not exclusively reference"):
        MarketDataCleaningPipeline(config, snapshot_store=store).run([inputs], _steps())


def test_pipeline_rejects_checksum_corruption(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)
    metadata = store.get_snapshot(inputs.yfinance_raw_snapshot_id)
    data_path = config.data_root / metadata.file_path
    data_path.write_bytes(data_path.read_bytes() + b"corrupt")

    with pytest.raises(CleaningInputError, match="verified COMPLETE"):
        MarketDataCleaningPipeline(config, snapshot_store=store).run([inputs], _steps())


def test_same_inputs_and_rules_are_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)
    pipeline = MarketDataCleaningPipeline(config, snapshot_store=store)

    first = pipeline.run([inputs], _steps())
    second = pipeline.run([inputs], _steps())

    assert first.snapshot.metadata.snapshot_id == second.snapshot.metadata.snapshot_id
    assert not second.snapshot.created


def test_cleaning_does_not_modify_source_snapshot_bytes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)
    before = {
        snapshot_id: (config.data_root / store.get_snapshot(snapshot_id).file_path).read_bytes()
        for snapshot_id in inputs.input_snapshot_ids
    }

    MarketDataCleaningPipeline(config, snapshot_store=store).run([inputs], _steps())

    after = {
        snapshot_id: (config.data_root / store.get_snapshot(snapshot_id).file_path).read_bytes()
        for snapshot_id in inputs.input_snapshot_ids
    }
    assert after == before


def test_empty_verified_price_table_creates_review_rows_without_guessing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)

    result = MarketDataCleaningPipeline(config, snapshot_store=store).run(
        [inputs], PriceStepTable()
    )

    assert result.frame["entry_eligible"].isna().all()
    assert result.frame["entry_exclusion_reason"].eq("PRICE_STEP_UNAVAILABLE").all()


def test_clean_snapshot_excludes_label_provider_and_future_split_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    inputs = _inputs(store)

    result = MarketDataCleaningPipeline(config, snapshot_store=store).run(
        [inputs], _steps()
    )

    assert {
        "label",
        "target",
        "prediction",
        "yf_provider_open",
        "yf_future_split_factor",
    }.isdisjoint(result.frame.columns)
