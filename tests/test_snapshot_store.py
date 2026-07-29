from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import MarketDataConfig, SnapshotStatus
from src.data.snapshot_store import (
    SnapshotCorruptError,
    SnapshotError,
    SnapshotRequest,
    SnapshotStore,
    canonicalize_dataframe,
)


def _config(tmp_path: Path) -> MarketDataConfig:
    return replace(
        MarketDataConfig(),
        data_root=tmp_path / "data",
        operational_cache_root=tmp_path / "cache",
    )


def _request(
    *,
    source: str = "yfinance",
    ticker: str = "AAA",
    start: str = "2024-01-01",
    end: str = "2024-01-02",
    layer: str = "raw",
    dataset_type: str = "equity_history",
    revision_context: dict[str, str] | None = None,
) -> SnapshotRequest:
    return SnapshotRequest(
        source=source,
        dataset_type=dataset_type,
        ticker_or_instrument=ticker,
        request_start_date=start,
        request_end_date=end,
        request_parameters={"actions": True, "auto_adjust": False},
        provider_library_version="test-provider-1.0",
        code_commit_sha="a" * 40,
        layer=layer,
        identity_columns=("ticker", "date"),
        revision_context=revision_context or {},
    )


def _frame(close: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "close": [close, 11.0],
            "volume": [100, 200],
        }
    )


def test_same_canonical_data_is_idempotent(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))

    first = store.save_dataframe(_frame(), _request())
    second = store.save_dataframe(_frame().iloc[::-1], _request())

    assert first.created
    assert not second.created
    assert second.metadata.snapshot_id == first.metadata.snapshot_id
    assert len(store.load_manifest()) == 1
    assert store.load_revisions() == []


def test_find_usable_snapshot_returns_only_verified_complete(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(_config(tmp_path))
    request = _request()
    complete = store.save_dataframe(_frame(), request).metadata
    store.record_failed_attempt(request, "later provider failure")

    found = store.find_usable_snapshot(request)

    assert found is not None
    assert found.snapshot_id == complete.snapshot_id


def test_find_usable_snapshot_ignores_corrupt_complete(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    request = _request()
    complete = store.save_dataframe(_frame(), request).metadata
    (store.config.data_root / complete.file_path).write_bytes(b"corrupt")

    assert store.find_usable_snapshot(request) is None


def test_one_changed_cell_creates_revision_and_diff(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    first = store.save_dataframe(_frame(), _request()).metadata

    changed = _frame()
    changed.loc[0, "close"] = 10.5
    second = store.save_dataframe(changed, _request()).metadata

    assert second.revision_number == 2
    assert second.previous_snapshot_id == first.snapshot_id
    assert second.revision is not None
    assert second.revision.changed_row_count == 1
    assert second.revision.changed_cell_count == 1
    assert second.revision.changed_columns == ("close",)


def test_new_date_creates_revision_and_reports_added_date(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    request = _request(end="2024-01-03")
    original = _frame()
    store.save_dataframe(original, request)
    added = pd.concat(
        [
            original,
            pd.DataFrame(
                {
                    "ticker": ["AAA"],
                    "date": [pd.Timestamp("2024-01-03")],
                    "close": [12.0],
                    "volume": [300],
                }
            ),
        ],
        ignore_index=True,
    )

    revised = store.save_dataframe(added, request).metadata

    assert revised.revision is not None
    assert revised.revision.added_dates == ("2024-01-03",)
    assert revised.revision.removed_dates == ()


def test_schema_only_change_reports_changed_column(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    store.save_dataframe(_frame(), _request())

    revised = store.save_dataframe(_frame().assign(note=None), _request()).metadata

    assert revised.revision is not None
    assert revised.revision.changed_columns == ("note",)
    assert revised.revision.changed_cell_count == 0


def test_old_snapshot_file_is_preserved_after_revision(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    first = store.save_dataframe(_frame(), _request()).metadata
    first_bytes = (store.config.data_root / first.file_path).read_bytes()

    store.save_dataframe(_frame(close=99.0), _request())

    assert (store.config.data_root / first.file_path).read_bytes() == first_bytes
    assert store.read_dataframe(first).loc[0, "close"] == 10


def test_checksum_is_deterministic_across_row_and_column_order() -> None:
    frame = _frame()
    reordered = frame[["volume", "close", "date", "ticker"]].iloc[::-1]

    first = canonicalize_dataframe(frame)
    second = canonicalize_dataframe(reordered)

    assert first.content_checksum == second.content_checksum
    assert first.schema_checksum == second.schema_checksum
    assert first.payload == second.payload


def test_column_order_does_not_create_false_revision(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    first = store.save_dataframe(_frame(), _request())
    reordered = _frame()[["volume", "date", "ticker", "close"]]

    second = store.save_dataframe(reordered, _request())

    assert first.metadata.snapshot_id == second.metadata.snapshot_id
    assert not second.created


def test_date_and_null_representations_are_canonical(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    first_frame = pd.DataFrame(
        {"ticker": ["AAA"], "date": [pd.Timestamp("2024-01-01")], "value": [np.nan]}
    )
    second_frame = pd.DataFrame(
        {"value": [None], "date": [date(2024, 1, 1)], "ticker": ["AAA"]}
    )

    first = store.save_dataframe(first_frame, _request(end="2024-01-01"))
    second = store.save_dataframe(second_frame, _request(end="2024-01-01"))

    assert first.metadata.content_checksum == second.metadata.content_checksum
    assert not second.created


def test_temporary_or_partial_file_is_not_a_valid_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    result = store.save_dataframe(_frame(), _request()).metadata
    temporary = store.config.raw_data_root / ".snapshot-tmp-uncommitted"
    temporary.mkdir(parents=True)
    (temporary / "data.jsonl").write_text('{"not":"committed"}\n', encoding="utf-8")

    manifest = store.load_manifest(validate_files=True)

    assert [item.snapshot_id for item in manifest] == [result.snapshot_id]


def test_atomic_manifest_failure_preserves_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SnapshotStore(_config(tmp_path))
    first = store.save_dataframe(_frame(), _request()).metadata
    real_replace = os.replace

    def fail_manifest_replace(source: Path, destination: Path) -> None:
        if Path(destination) == store.config.snapshot_manifest_path:
            raise OSError("simulated manifest replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(store, "_replace_path", fail_manifest_replace)

    with pytest.raises(OSError, match="simulated"):
        store.save_dataframe(_frame(close=99.0), _request())

    assert [item.snapshot_id for item in store.load_manifest()] == [first.snapshot_id]
    assert store.is_usable(first)
    assert store.load_revisions() == []


def test_yfinance_and_isyatirim_sources_are_isolated(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))

    yf = store.save_dataframe(_frame(), _request(source="yfinance")).metadata
    isy = store.save_dataframe(_frame(), _request(source="isyatirim")).metadata

    assert yf.logical_dataset_key != isy.logical_dataset_key
    assert yf.file_path.startswith("raw/yfinance/")
    assert isy.file_path.startswith("raw/isyatirim/")


def test_tickers_are_isolated(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))

    aaa = store.save_dataframe(_frame(), _request(ticker="AAA")).metadata
    bbb_frame = _frame().assign(ticker="BBB")
    bbb = store.save_dataframe(bbb_frame, _request(ticker="BBB")).metadata

    assert aaa.logical_dataset_key != bbb.logical_dataset_key
    assert "/AAA/" in aaa.file_path
    assert "/BBB/" in bbb.file_path


def test_request_date_ranges_are_isolated(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))

    first = store.save_dataframe(_frame(), _request()).metadata
    second = store.save_dataframe(
        _frame(), _request(start="2023-01-01", end="2024-01-02")
    ).metadata

    assert first.logical_dataset_key != second.logical_dataset_key
    assert first.revision_number == second.revision_number == 1


def test_manifest_and_physical_file_consistency_is_verified(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    snapshot = store.save_dataframe(_frame(), _request()).metadata
    store.load_manifest(validate_files=True)

    path = store.config.data_root / snapshot.file_path
    path.write_bytes(path.read_bytes() + b"corrupt")

    with pytest.raises(SnapshotCorruptError, match="checksum mismatch"):
        store.load_manifest(validate_files=True)
    assert not store.is_usable(snapshot)


def test_revision_chain_links_each_complete_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    first = store.save_dataframe(_frame(close=10.0), _request()).metadata
    second = store.save_dataframe(_frame(close=20.0), _request()).metadata
    third = store.save_dataframe(_frame(close=30.0), _request()).metadata

    assert [first.revision_number, second.revision_number, third.revision_number] == [1, 2, 3]
    assert second.previous_snapshot_id == first.snapshot_id
    assert third.previous_snapshot_id == second.snapshot_id
    assert [item.snapshot_id for item in store.load_revisions()] == [
        second.snapshot_id,
        third.snapshot_id,
    ]


@pytest.mark.parametrize(
    "status",
    [SnapshotStatus.FAILED, SnapshotStatus.PARTIAL, SnapshotStatus.CORRUPT],
)
def test_non_complete_snapshot_is_not_usable(
    tmp_path: Path, status: SnapshotStatus
) -> None:
    store = SnapshotStore(_config(tmp_path))
    snapshot = store.save_dataframe(_frame(), _request(), status=status).metadata

    assert not store.is_usable(snapshot)
    with pytest.raises(SnapshotError, match="not COMPLETE"):
        store.read_dataframe(snapshot)


def test_snapshot_identity_and_checksums_can_be_reverified(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    snapshot = store.save_dataframe(_frame(), _request()).metadata
    canonical = canonicalize_dataframe(_frame())

    store.verify_snapshot(snapshot.snapshot_id)

    assert snapshot.content_checksum == canonical.content_checksum
    assert snapshot.schema_checksum == canonical.schema_checksum
    assert snapshot.snapshot_id.startswith(
        f"snap_{snapshot.logical_dataset_key[:16]}_r0001_"
    )
    assert snapshot.config_checksum == store.config.checksum()


def test_required_metadata_fields_are_recorded(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    metadata = store.save_dataframe(_frame(), _request()).metadata.to_dict()
    required = {
        "snapshot_id",
        "source",
        "dataset_type",
        "ticker_or_instrument",
        "request_start_date",
        "request_end_date",
        "fetch_timestamp_utc",
        "row_count",
        "column_names",
        "column_types",
        "content_checksum",
        "schema_checksum",
        "file_path",
        "revision_number",
        "previous_snapshot_id",
        "request_parameters",
        "config_checksum",
        "code_commit_sha",
        "provider_library_version",
        "snapshot_status",
    }

    assert required.issubset(metadata)


def test_revision_context_is_idempotent_when_content_and_context_match(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(_config(tmp_path))
    request = _request(revision_context={"calendar_checksum": "calendar-a"})

    first = store.save_dataframe(_frame(), request)
    second = store.save_dataframe(_frame(), request)

    assert first.created
    assert not second.created
    assert second.metadata.snapshot_id == first.metadata.snapshot_id
    assert first.metadata.revision_context_checksum is not None
    store.verify_snapshot(first.metadata)


def test_revision_context_change_creates_revision_even_when_content_matches(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(_config(tmp_path))
    first = store.save_dataframe(
        _frame(), _request(revision_context={"calendar_checksum": "calendar-a"})
    ).metadata
    second = store.save_dataframe(
        _frame(), _request(revision_context={"calendar_checksum": "calendar-b"})
    ).metadata

    assert second.snapshot_id != first.snapshot_id
    assert second.logical_dataset_key == first.logical_dataset_key
    assert second.revision_number == 2
    assert second.previous_snapshot_id == first.snapshot_id
    assert second.content_checksum == first.content_checksum
    assert second.revision_context_checksum != first.revision_context_checksum


def test_windows_permission_error_during_atomic_replace_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = 0
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_text("payload", encoding="utf-8")
    real_replace = os.replace

    def flaky_replace(left: Path, right: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporary Windows file lock")
        real_replace(left, right)

    monkeypatch.setattr("src.data.snapshot_store.os.replace", flaky_replace)
    monkeypatch.setattr("src.data.snapshot_store.time.sleep", lambda _: None)

    SnapshotStore._replace_path(source, destination)

    assert attempts == 3
    assert destination.read_text(encoding="utf-8") == "payload"


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")
def test_windows_snapshot_directory_keeps_acl_inheritance(tmp_path: Path) -> None:
    store = SnapshotStore(_config(tmp_path))
    metadata = store.save_dataframe(_frame(), _request()).metadata
    snapshot_directory = (store.config.data_root / metadata.file_path).parent
    environment = os.environ.copy()
    environment["SNAPSHOT_ACL_TEST_PATH"] = str(snapshot_directory)

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-Acl -LiteralPath $env:SNAPSHOT_ACL_TEST_PATH).AreAccessRulesProtected",
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert completed.stdout.strip() == "False"


def test_numeric_provider_epoch_fields_are_preserved_as_raw_integers(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(_config(tmp_path))
    frame = pd.DataFrame(
        {
            "index_code": ["XU100"],
            "source_timestamp_ms": [1704142800000],
            "END_TARIH": [1704142800000],
            "source_value": [7624.29],
        }
    )
    snapshot = store.save_dataframe(frame, _request(dataset_type="index_history"))
    loaded = store.read_dataframe(snapshot.metadata)

    assert loaded.loc[0, "source_timestamp_ms"] == 1704142800000
    assert loaded.loc[0, "END_TARIH"] == 1704142800000
    assert snapshot.metadata.column_types["source_timestamp_ms"] == "integer"
    assert snapshot.metadata.column_types["END_TARIH"] == "integer"
