from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import MarketDataConfig
from src.data.snapshot_store import SnapshotRequest, SnapshotStore


@dataclass(frozen=True)
class SyntheticFeatureBundle:
    store: SnapshotStore
    config: MarketDataConfig
    yfinance_ids: tuple[str, ...]
    isyatirim_ids: tuple[str, ...]
    identity_id: str
    xu100_id: str
    calendar_id: str


def make_bundle(
    tmp_path: Path,
    *,
    store: SnapshotStore | None = None,
    action_value: float = 0.0,
) -> SyntheticFeatureBundle:
    config = (
        store.config
        if store is not None
        else replace(
            MarketDataConfig(),
            data_root=tmp_path / "data",
            operational_cache_root=tmp_path / "cache",
        )
    )
    store = store or SnapshotStore(config)
    dates = pd.bdate_range("2024-01-02", periods=30)
    y_rows: list[dict[str, object]] = []
    is_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    for security_number in range(20):
        ticker = f"T{security_number:03d}"
        security_id = f"SEC_{security_number:03d}"
        for day_number, day in enumerate(dates):
            close = 100.0 + day_number + security_number * 0.25
            y_rows.append(
                {
                    "ticker": ticker,
                    "date": day,
                    "Open": close - 0.4,
                    "High": close + 1.0,
                    "Low": close - 1.0,
                    "Close": close,
                    "Adj Close": close * 0.95,
                    "Volume": 10_000 + day_number,
                    "Dividends": action_value if day_number == 5 else 0.0,
                    "Stock Splits": 0.0,
                }
            )
            is_rows.append(
                {
                    "HGDG_HS_KODU": ticker,
                    "HGDG_TARIH": day,
                    "HGDG_HACIM": 1_000_000.0
                    + day_number * 10_000.0
                    + security_number * 1_000.0,
                }
            )
            identity_rows.append(
                {
                    "security_id": security_id,
                    "observed_ticker": ticker,
                    "date": day,
                    "yf_nominal_open": close,
                    "yf_nominal_high": close,
                    "yf_nominal_low": close,
                    "yf_nominal_close": close,
                }
            )
    start, end = dates.min().date(), dates.max().date()
    y_frame = pd.DataFrame(y_rows)
    y_request = SnapshotRequest(
        source="yfinance",
        dataset_type="equity_history",
        ticker_or_instrument="BIST_BATCH",
        request_start_date=start,
        request_end_date=end,
        request_parameters={"auto_adjust": False, "actions": True},
        layer="raw",
        identity_columns=("ticker", "date"),
    )
    y_id = store.save_dataframe(y_frame, y_request).metadata.snapshot_id
    is_id = store.save_dataframe(
        pd.DataFrame(is_rows),
        SnapshotRequest(
            source="isyatirim",
            dataset_type="equity_history",
            ticker_or_instrument="BIST_BATCH",
            request_start_date=start,
            request_end_date=end,
            layer="raw",
            identity_columns=("HGDG_HS_KODU", "HGDG_TARIH"),
        ),
    ).metadata.snapshot_id
    identity_id = store.save_dataframe(
        pd.DataFrame(identity_rows),
        SnapshotRequest(
            source="security_identity",
            dataset_type="nominal_ohlc",
            ticker_or_instrument="BIST_BATCH",
            request_start_date=start,
            request_end_date=end,
            request_parameters={
                "ticker_mapping_version": "test-map-v1",
                "ticker_mapping_checksum": "test-map-checksum",
            },
            layer="derived",
            identity_columns=("security_id", "date"),
        ),
    ).metadata.snapshot_id
    calendar = pd.DataFrame(
        {"session_date": dates, "session_index": np.arange(len(dates), dtype="int64")}
    )
    calendar_id = store.save_dataframe(
        calendar,
        SnapshotRequest(
            source="isyatirim",
            dataset_type="global_bist_sessions",
            ticker_or_instrument="BIST",
            request_start_date=start,
            request_end_date=end,
            layer="derived",
            identity_columns=("session_date",),
        ),
    ).metadata.snapshot_id
    xu100 = pd.DataFrame(
        {
            "prediction_date": dates,
            "validated_xu100_close": 7_000.0 + np.arange(len(dates)) * 5.0,
            "validation_status": "PASS",
        }
    )
    xu100_id = store.save_dataframe(
        xu100,
        SnapshotRequest(
            source="benchmark",
            dataset_type="validated_xu100_close",
            ticker_or_instrument="XU100",
            request_start_date=start,
            request_end_date=end,
            layer="derived",
            input_snapshot_ids=(calendar_id,),
            identity_columns=("prediction_date",),
        ),
    ).metadata.snapshot_id
    return SyntheticFeatureBundle(
        store,
        config,
        (y_id,),
        (is_id,),
        identity_id,
        xu100_id,
        calendar_id,
    )
