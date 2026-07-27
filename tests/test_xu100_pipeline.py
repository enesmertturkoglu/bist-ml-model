from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.config import MarketDataConfig
from src.data.snapshot_store import SnapshotRequest, SnapshotStore
from src.data.xu100_client import TIMESTAMP_RESOLUTION_RULE, add_timestamp_candidates
from src.data.xu100_pipeline import (
    Xu100Pipeline,
    Xu100ValidationError,
    cross_check_end_fields,
    cross_check_yfinance,
    validate_xu100_history,
)


def _epoch_ms(value: str) -> int:
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


def _raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "index_code": ["XU100", "XU100", "XU100"],
            "source_timestamp_ms": [
                _epoch_ms("2024-01-01 21:00:00"),
                _epoch_ms("2024-01-02 21:00:00"),
                _epoch_ms("2024-01-07 21:00:00"),
            ],
            "source_value": [7400.0, 7500.0, 7600.0],
        }
    )


def _calendar() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-08"]),
            "session_index": [0, 1, 2],
        }
    )


def test_timestamp_candidates_are_timezone_aware_and_preserve_raw_fields() -> None:
    result = add_timestamp_candidates(_raw())

    assert list(result.columns[:3]) == [
        "index_code",
        "source_timestamp_ms",
        "source_value",
    ]
    assert result.loc[0, "utc_calendar_date"] == pd.Timestamp("2024-01-01")
    assert result.loc[0, "istanbul_calendar_date"] == pd.Timestamp("2024-01-02")
    assert result.loc[0, "legacy_plus_one_date"] == pd.Timestamp("2024-01-02")


def test_validated_xu100_uses_istanbul_calendar_date_without_filling() -> None:
    validated, report = validate_xu100_history(_raw(), _calendar())

    assert validated["prediction_date"].tolist() == list(_calendar()["session_date"])
    assert validated["validated_xu100_close"].tolist() == [7400.0, 7500.0, 7600.0]
    assert set(validated["timestamp_resolution_rule"]) == {TIMESTAMP_RESOLUTION_RULE}
    assert report.istanbul_match_ratio == 1.0
    assert report.istanbul_local_midnight_ratio == 1.0
    assert report.utc_match_ratio < report.istanbul_match_ratio


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("index_code", "XU030", "exactly XU100"),
        ("source_value", 0.0, "positive and finite"),
    ],
)
def test_invalid_identity_or_value_fails_closed(
    column: str, value: object, message: str
) -> None:
    raw = _raw()
    raw.loc[0, column] = value

    with pytest.raises(Xu100ValidationError, match=message):
        validate_xu100_history(raw, _calendar())


def test_duplicate_timestamp_fails_closed() -> None:
    raw = _raw()
    raw.loc[1, "source_timestamp_ms"] = raw.loc[0, "source_timestamp_ms"]

    with pytest.raises(Xu100ValidationError, match="duplicate XU100 source timestamp"):
        validate_xu100_history(raw, _calendar())


def test_calendar_mismatch_and_ambiguous_rule_fail_closed() -> None:
    calendar = pd.DataFrame(
        {
            "session_date": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-07",
                    "2024-01-08",
                ]
            )
        }
    )

    with pytest.raises(Xu100ValidationError, match="ambiguous"):
        validate_xu100_history(_raw(), calendar)


def test_missing_xu100_session_is_not_forward_filled() -> None:
    raw = _raw().iloc[[0, 2]].reset_index(drop=True)
    validated, _ = validate_xu100_history(raw, _calendar())

    assert pd.Timestamp("2024-01-03") not in set(validated["prediction_date"])
    assert len(validated) == 2


def test_pipeline_persists_raw_epoch_and_validated_benchmark_layers(
    tmp_path: Path,
) -> None:
    config = replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )
    store = SnapshotStore(config)
    calendar = store.save_dataframe(
        _calendar(),
        SnapshotRequest(
            source="isyatirim",
            dataset_type="global_bist_sessions",
            ticker_or_instrument="BIST",
            request_start_date="2024-01-02",
            request_end_date="2024-01-08",
            layer="derived",
            identity_columns=("session_date",),
        ),
    ).metadata

    class FakeClient:
        def fetch_history(self, *_args, **_kwargs) -> pd.DataFrame:
            return add_timestamp_candidates(_raw())

    result = Xu100Pipeline(
        config,
        snapshot_store=store,
        client=FakeClient(),  # type: ignore[arg-type]
        code_commit_sha="a" * 40,
    ).run(
        pd.Timestamp("2024-01-02").date(),
        pd.Timestamp("2024-01-08").date(),
        global_calendar_snapshot_id=calendar.snapshot_id,
    )
    saved_raw = store.read_dataframe(result.raw_snapshot)

    assert result.raw_snapshot.source == "isyatirim"
    assert result.raw_snapshot.dataset_type == "xu100_index_history"
    assert result.validated_snapshot.source == "benchmark"
    assert result.validated_snapshot.dataset_type == "validated_xu100_close"
    assert result.validated_snapshot.file_path.startswith(
        "derived/benchmark/validated_xu100_close/"
    )
    assert saved_raw.loc[0, "source_timestamp_ms"] == _raw().loc[0, "source_timestamp_ms"]


def test_end_and_yfinance_cross_checks_are_diagnostic_only() -> None:
    validated, _ = validate_xu100_history(_raw(), _calendar())
    stock_frames: list[pd.DataFrame] = []
    for number in range(20):
        stock_frames.append(
            pd.DataFrame(
                {
                    "HGDG_HS_KODU": f"T{number:03d}",
                    "HGDG_TARIH": _calendar()["session_date"],
                    "END_ENDEKS_KODU": "01",
                    "END_TARIH": _raw()["source_timestamp_ms"],
                    "END_SEANS": "2",
                    "END_DEGER": _raw()["source_value"],
                }
            )
        )
    end_report = cross_check_end_fields(stock_frames, validated)
    yfinance = pd.DataFrame(
        {"Close": [7400.01, 7500.01, 7600.01]}, index=_calendar()["session_date"]
    )
    yfinance.index.name = "Date"
    yf_report = cross_check_yfinance(yfinance, validated)

    assert end_report["security_count"] == 20
    assert end_report["same_day_value_equal_ratio"] == 1.0
    assert end_report["role"] == "diagnostic_only_no_fallback"
    assert yf_report["symbol"] == "XU100.IS"
    assert yf_report["overlap_days"] == 3
    assert yf_report["role"] == "diagnostic_only_no_fallback"
