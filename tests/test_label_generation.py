from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import MarketDataConfig, SnapshotStatus
from src.data.label_pipeline import LabelGenerationPipeline, LabelInputError
from src.data.labels import (
    LabelGenerationError,
    build_three_day_target_labels,
    calculate_target_price,
    ceil_to_price_step,
    summarize_labels,
)
from src.data.price_limits import PriceStepRule, PriceStepTable
from src.data.snapshot_store import SnapshotRequest, SnapshotStore


CALENDAR = pd.to_datetime(
    [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
        "2024-01-10",
    ]
)


def _steps(step: str = "0.10") -> PriceStepTable:
    return PriceStepTable(
        [PriceStepRule("2020-03-13", None, "0", None, step)]
    )


def _clean_frame(tickers: tuple[str, ...] = ("AAA",)) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        for prediction_date, entry_date in zip(CALENDAR[:-1], CALENDAR[1:], strict=True):
            rows.append(
                {
                    "ticker": ticker,
                    "prediction_date": prediction_date,
                    "entry_date": entry_date,
                    "yf_nominal_open": 100.0,
                    "yf_nominal_high": 104.0,
                    "yf_nominal_close": 101.0,
                    "ohlc_quality_flag": "VALID",
                    "volume_quality_flag": "POSITIVE_VOLUME_CONFIRMED",
                    "corporate_action_window_flag": False,
                    "entry_eligible": True,
                    "entry_exclusion_reason": pd.NA,
                    "entry_exclusion_reasons": [],
                    "requires_review": False,
                }
            )
    return pd.DataFrame(rows)


def _label_row(frame: pd.DataFrame, prediction_date: str = "2024-01-02") -> pd.Series:
    result = build_three_day_target_labels(frame, _steps())
    return result.loc[
        result["prediction_date"].eq(pd.Timestamp(prediction_date))
        & result["ticker"].eq("AAA")
    ].iloc[0]


def _set_horizon_value(
    frame: pd.DataFrame,
    horizon: int,
    column: str,
    value: object,
    *,
    ticker: str = "AAA",
) -> None:
    entry_date = CALENDAR[horizon]
    frame.loc[
        frame["ticker"].eq(ticker) & frame["entry_date"].eq(entry_date),
        column,
    ] = value


def test_exact_five_percent_target_is_positive() -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, 1, "yf_nominal_high", 105.0)

    row = _label_row(frame)

    assert row["label"] == 1
    assert bool(row["target_hit"])
    assert row["target_price"] == 105.0


def test_one_tick_below_target_is_negative() -> None:
    frame = _clean_frame()
    for horizon in (1, 2, 3):
        _set_horizon_value(frame, horizon, "yf_nominal_high", 104.9)

    row = _label_row(frame)

    assert row["label"] == 0
    assert not bool(row["target_hit"])


@pytest.mark.parametrize("hit_horizon", [1, 2, 3])
def test_target_can_be_hit_on_each_horizon_day(hit_horizon: int) -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, hit_horizon, "yf_nominal_high", 105.0)

    row = _label_row(frame)

    assert row["label"] == 1
    assert row["target_hit_horizon"] == hit_horizon
    assert row["target_hit_date"] == CALENDAR[hit_horizon]


def test_first_target_hit_day_wins() -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, 1, "yf_nominal_high", 106.0)
    _set_horizon_value(frame, 2, "yf_nominal_high", 107.0)

    row = _label_row(frame)

    assert row["target_hit_horizon"] == 1
    assert row["target_hit_date"] == CALENDAR[1]
    assert row["exit_date"] == CALENDAR[1]


def test_no_hit_exits_at_t3_close() -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, 3, "yf_nominal_close", 102.0)

    row = _label_row(frame)

    assert row["label"] == 0
    assert row["exit_date"] == CALENDAR[3]
    assert row["exit_price"] == 102.0
    assert row["exit_reason"] == "HORIZON_CLOSE"
    assert row["gross_return"] == pytest.approx(0.02)


def test_raw_target_is_rounded_up_not_down() -> None:
    frame = _clean_frame()
    frame.loc[frame["prediction_date"].eq(CALENDAR[0]), "yf_nominal_open"] = 100.01

    row = _label_row(frame)

    assert row["raw_target_price"] == pytest.approx(105.0105)
    assert row["target_tick_size"] == 0.10
    assert row["target_price"] == 105.10


def test_exact_tick_target_is_unchanged() -> None:
    calculation = calculate_target_price("100", "2024-01-03", _steps())

    assert calculation is not None
    assert calculation.raw_target_price == Decimal("105.00")
    assert calculation.target_price == Decimal("105.00")


def test_decimal_target_is_deterministic_for_binary_float_input() -> None:
    calculation = calculate_target_price(
        0.1 + 0.2,
        "2024-01-03",
        _steps("0.01"),
    )

    assert calculation is not None
    assert calculation.raw_target_price == Decimal("0.3150000000000000420")
    assert calculation.target_price == Decimal("0.32")
    assert ceil_to_price_step("1.0501", "0.01") == Decimal("1.06")


@pytest.mark.parametrize(
    "reason",
    [
        "CORPORATE_ACTION_WINDOW",
        "LIMIT_OPEN",
        "NO_OPEN",
        "NO_TRADE",
        "INVALID_OHLC",
        "NO_PREVIOUS_CLOSE",
        "SPECIAL_MARGIN_OR_CORPORATE_ACTION",
        "PRICE_STEP_UNAVAILABLE",
    ],
)
def test_entry_exclusion_reasons_remain_na(reason: str) -> None:
    frame = _clean_frame()
    frame.loc[0, "entry_eligible"] = False
    frame.at[0, "entry_exclusion_reason"] = reason
    frame.at[0, "entry_exclusion_reasons"] = [reason]
    if reason == "CORPORATE_ACTION_WINDOW":
        frame.loc[0, "corporate_action_window_flag"] = True

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_status"] == "NA"
    assert row["label_exclusion_reason"] == reason
    assert reason in row["label_exclusion_reasons"]


def test_ineligible_entry_without_reason_is_na() -> None:
    frame = _clean_frame()
    frame.loc[0, "entry_eligible"] = False

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "ENTRY_NOT_ELIGIBLE"


def test_requires_review_is_na_not_negative() -> None:
    frame = _clean_frame()
    frame.loc[0, "requires_review"] = True

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "REQUIRES_REVIEW"


def test_missing_t1_open_is_na_even_if_eligibility_is_inconsistent() -> None:
    frame = _clean_frame()
    frame.loc[0, "yf_nominal_open"] = np.nan

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "NO_OPEN"


@pytest.mark.parametrize("horizon", [1, 2, 3])
def test_missing_or_invalid_horizon_high_is_na(horizon: int) -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, horizon, "yf_nominal_high", np.nan)
    _set_horizon_value(frame, horizon, "ohlc_quality_flag", "INVALID_OHLC")

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "INVALID_HORIZON_PRICE"


def test_no_trade_horizon_day_is_na() -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, 2, "volume_quality_flag", "NO_TRADE")

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "HORIZON_NO_TRADE"


def test_missing_t3_close_without_hit_is_na() -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, 3, "yf_nominal_close", np.nan)

    row = _label_row(frame)

    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "MISSING_T3_CLOSE"


def test_global_bist_calendar_does_not_shift_for_missing_ticker_day() -> None:
    frame = _clean_frame(("AAA", "BBB"))
    frame = frame.loc[
        ~(frame["ticker"].eq("AAA") & frame["entry_date"].eq(CALENDAR[2]))
    ].reset_index(drop=True)
    row = _label_row(frame)

    assert row["horizon_t2_date"] == CALENDAR[2]
    assert row["horizon_t3_date"] == CALENDAR[3]
    assert pd.isna(row["label"])
    assert row["label_exclusion_reason"] == "MISSING_HORIZON_ROW"


def test_t4_high_does_not_affect_label() -> None:
    frame = _clean_frame()
    _set_horizon_value(frame, 4, "yf_nominal_high", 200.0)

    row = _label_row(frame)

    assert row["label"] == 0
    assert not bool(row["target_hit"])


def test_label_contains_no_commission_or_slippage() -> None:
    row = _label_row(_clean_frame())

    assert row["gross_return"] == pytest.approx(0.01)
    assert {"commission", "slippage", "net_return"}.isdisjoint(row.index)


def test_incomplete_global_horizon_is_explicit_na() -> None:
    result = build_three_day_target_labels(_clean_frame(), _steps())
    last = result.iloc[-1]

    assert pd.isna(last["label"])
    assert last["label_exclusion_reason"] == "INCOMPLETE_HORIZON"


def test_same_clean_input_and_config_are_deterministic() -> None:
    frame = _clean_frame()

    first = build_three_day_target_labels(frame, _steps())
    second = build_three_day_target_labels(frame, _steps())

    pd.testing.assert_frame_equal(first, second)


def test_summary_reports_label_distribution_and_na_reasons() -> None:
    summary = summarize_labels(
        build_three_day_target_labels(_clean_frame(), _steps())
    )

    assert summary["row_count"] == 6
    assert summary["label_negative"] == 4
    assert summary["label_na"] == 2
    assert summary["na_reasons"] == {"INCOMPLETE_HORIZON": 2}


def test_conflicting_global_calendar_is_rejected() -> None:
    frame = _clean_frame(("AAA", "BBB"))
    frame.loc[
        frame["ticker"].eq("BBB") & frame["prediction_date"].eq(CALENDAR[0]),
        "entry_date",
    ] = pd.Timestamp("2024-01-11")

    with pytest.raises(LabelGenerationError, match="conflicting global BIST"):
        build_three_day_target_labels(frame, _steps())


def test_missing_clean_field_is_rejected() -> None:
    with pytest.raises(LabelGenerationError, match="fields missing"):
        build_three_day_target_labels(
            _clean_frame().drop(columns="entry_eligible"), _steps()
        )


def _config(tmp_path: Path) -> MarketDataConfig:
    return replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )


def _save_clean_snapshot(
    store: SnapshotStore,
    config: MarketDataConfig,
    *,
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    source: str = "cleaning",
    frame: pd.DataFrame | None = None,
) -> str:
    source_frame = frame if frame is not None else _clean_frame()
    request = SnapshotRequest(
        source=source,
        dataset_type=config.cleaning.clean_dataset_type,
        ticker_or_instrument="AAA",
        request_start_date=pd.to_datetime(source_frame["prediction_date"]).min(),
        request_end_date=pd.to_datetime(source_frame["entry_date"]).max(),
        request_parameters={"cleaning_version": "test"},
        provider_library_version="test-cleaning-v1",
        code_commit_sha="a" * 40,
        layer="derived",
        input_snapshot_ids=("raw-a", "raw-b", "nominal-c"),
        identity_columns=("ticker", "prediction_date"),
    )
    return store.save_dataframe(
        source_frame,
        request,
        status=status,
    ).metadata.snapshot_id


def test_pipeline_writes_immutable_label_snapshot_with_provenance(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    clean_id = _save_clean_snapshot(store, config)

    result = LabelGenerationPipeline(
        config,
        snapshot_store=store,
        code_commit_sha="b" * 40,
    ).run(clean_id, _steps())
    row = result.frame.iloc[0]
    metadata = result.snapshot.metadata

    assert result.snapshot.created
    assert metadata.source == "labels"
    assert metadata.dataset_type == config.label.label_dataset_type
    assert metadata.layer == "derived"
    assert metadata.input_snapshot_ids == (clean_id,)
    assert store.is_usable(metadata)
    assert row["input_clean_snapshot_id"] == clean_id
    assert row["input_clean_snapshot_checksum"] == store.get_snapshot(
        clean_id
    ).content_checksum
    assert row["label_config_checksum"] == config.label.checksum()
    assert row["label_code_commit_sha"] == "b" * 40
    assert metadata.request_parameters["input_clean_snapshot_id"] == clean_id


def test_pipeline_rejects_non_complete_clean_snapshot(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    clean_id = _save_clean_snapshot(store, config, status=SnapshotStatus.PARTIAL)

    with pytest.raises(LabelInputError, match="verified COMPLETE"):
        LabelGenerationPipeline(config, snapshot_store=store).run(clean_id, _steps())


def test_pipeline_rejects_non_clean_snapshot_type(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    snapshot_id = _save_clean_snapshot(store, config, source="other")

    with pytest.raises(LabelInputError, match="is not cleaning"):
        LabelGenerationPipeline(config, snapshot_store=store).run(
            snapshot_id, _steps()
        )


def test_pipeline_rejects_checksum_corruption(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    clean_id = _save_clean_snapshot(store, config)
    metadata = store.get_snapshot(clean_id)
    data_path = config.data_root / metadata.file_path
    data_path.write_bytes(data_path.read_bytes() + b"corrupt")

    with pytest.raises(LabelInputError, match="verified COMPLETE"):
        LabelGenerationPipeline(config, snapshot_store=store).run(clean_id, _steps())


def test_pipeline_excludes_rows_before_d020_model_start(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    frame = _clean_frame()
    pre_model = frame.iloc[[0]].copy()
    pre_model["prediction_date"] = pd.Timestamp("2020-03-12")
    pre_model["entry_date"] = pd.Timestamp("2020-03-13")
    clean_id = _save_clean_snapshot(
        store,
        config,
        frame=pd.concat([pre_model, frame], ignore_index=True),
    )

    result = LabelGenerationPipeline(config, snapshot_store=store).run(
        clean_id, _steps()
    )

    assert result.frame["prediction_date"].ge(
        pd.Timestamp(config.model_start_date)
    ).all()


def test_same_label_input_and_config_are_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    clean_id = _save_clean_snapshot(store, config)
    pipeline = LabelGenerationPipeline(
        config,
        snapshot_store=store,
        code_commit_sha="c" * 40,
    )

    first = pipeline.run(clean_id, _steps())
    second = pipeline.run(clean_id, _steps())

    assert first.snapshot.metadata.snapshot_id == second.snapshot.metadata.snapshot_id
    assert not second.snapshot.created


def test_label_pipeline_does_not_modify_clean_snapshot_bytes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    clean_id = _save_clean_snapshot(store, config)
    metadata = store.get_snapshot(clean_id)
    data_path = config.data_root / metadata.file_path
    before = data_path.read_bytes()

    LabelGenerationPipeline(config, snapshot_store=store).run(clean_id, _steps())

    assert data_path.read_bytes() == before


def test_label_snapshot_contains_no_feature_model_or_provider_fields(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = SnapshotStore(config)
    clean_id = _save_clean_snapshot(store, config)

    result = LabelGenerationPipeline(config, snapshot_store=store).run(
        clean_id, _steps()
    )

    assert {
        "feature",
        "prediction",
        "model_version",
        "yf_provider_open",
        "yf_future_split_factor",
    }.isdisjoint(result.frame.columns)
