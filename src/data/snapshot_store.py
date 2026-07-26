"""Immutable, checksummed, file-based market-data snapshot storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import numpy as np

from src.config import MarketDataConfig, SnapshotStatus


SNAPSHOT_SCHEMA_VERSION = "v1"
STORAGE_FORMAT = "canonical-jsonl-v1"
_SAFE_PATH_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class SnapshotError(RuntimeError):
    """Base exception for snapshot storage failures."""


class SnapshotNotFoundError(SnapshotError):
    """Raised when a snapshot ID is absent from the committed manifest."""


class SnapshotCorruptError(SnapshotError):
    """Raised when committed metadata and physical snapshot files disagree."""


@dataclass(frozen=True)
class SnapshotRequest:
    """Logical request identity and provenance for a snapshot write."""

    source: str
    dataset_type: str
    ticker_or_instrument: str
    request_start_date: date | str | pd.Timestamp
    request_end_date: date | str | pd.Timestamp
    request_parameters: Mapping[str, Any] = field(default_factory=dict)
    provider_library_version: str = "unknown"
    code_commit_sha: str = "unknown"
    layer: str = "raw"
    input_snapshot_ids: tuple[str, ...] = ()
    identity_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderRevision:
    """Difference summary between two complete provider snapshots."""

    revision_id: str
    logical_dataset_key: str
    previous_snapshot_id: str
    snapshot_id: str
    detected_at_utc: str
    changed_row_count: int
    added_dates: tuple[str, ...]
    removed_dates: tuple[str, ...]
    changed_columns: tuple[str, ...]
    changed_cell_count: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["added_dates"] = list(self.added_dates)
        result["removed_dates"] = list(self.removed_dates)
        result["changed_columns"] = list(self.changed_columns)
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderRevision":
        return cls(
            revision_id=str(value["revision_id"]),
            logical_dataset_key=str(value["logical_dataset_key"]),
            previous_snapshot_id=str(value["previous_snapshot_id"]),
            snapshot_id=str(value["snapshot_id"]),
            detected_at_utc=str(value["detected_at_utc"]),
            changed_row_count=int(value["changed_row_count"]),
            added_dates=tuple(map(str, value.get("added_dates", []))),
            removed_dates=tuple(map(str, value.get("removed_dates", []))),
            changed_columns=tuple(map(str, value.get("changed_columns", []))),
            changed_cell_count=int(value["changed_cell_count"]),
        )


@dataclass(frozen=True)
class SnapshotMetadata:
    """Committed metadata required to reproduce and audit a data snapshot."""

    snapshot_id: str
    source: str
    dataset_type: str
    ticker_or_instrument: str
    request_start_date: str
    request_end_date: str
    fetch_timestamp_utc: str
    row_count: int
    column_names: tuple[str, ...]
    column_types: Mapping[str, str]
    content_checksum: str
    schema_checksum: str
    file_path: str
    revision_number: int
    previous_snapshot_id: str | None
    request_parameters: Mapping[str, Any]
    config_checksum: str
    code_commit_sha: str
    provider_library_version: str
    snapshot_status: SnapshotStatus
    logical_dataset_key: str
    layer: str
    checksum_algorithm: str
    storage_format: str = STORAGE_FORMAT
    snapshot_schema_version: str = SNAPSHOT_SCHEMA_VERSION
    input_snapshot_ids: tuple[str, ...] = ()
    identity_columns: tuple[str, ...] = ()
    error_message: str | None = None
    revision: ProviderRevision | None = None

    @property
    def is_complete(self) -> bool:
        return self.snapshot_status is SnapshotStatus.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["column_names"] = list(self.column_names)
        result["column_types"] = dict(self.column_types)
        result["snapshot_status"] = self.snapshot_status.value
        result["input_snapshot_ids"] = list(self.input_snapshot_ids)
        result["identity_columns"] = list(self.identity_columns)
        result["request_parameters"] = _json_ready(self.request_parameters)
        result["revision"] = self.revision.to_dict() if self.revision else None
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotMetadata":
        revision_value = value.get("revision")
        return cls(
            snapshot_id=str(value["snapshot_id"]),
            source=str(value["source"]),
            dataset_type=str(value["dataset_type"]),
            ticker_or_instrument=str(value["ticker_or_instrument"]),
            request_start_date=str(value["request_start_date"]),
            request_end_date=str(value["request_end_date"]),
            fetch_timestamp_utc=str(value["fetch_timestamp_utc"]),
            row_count=int(value["row_count"]),
            column_names=tuple(map(str, value["column_names"])),
            column_types={
                str(key): str(item) for key, item in value["column_types"].items()
            },
            content_checksum=str(value["content_checksum"]),
            schema_checksum=str(value["schema_checksum"]),
            file_path=str(value["file_path"]),
            revision_number=int(value["revision_number"]),
            previous_snapshot_id=(
                str(value["previous_snapshot_id"])
                if value.get("previous_snapshot_id") is not None
                else None
            ),
            request_parameters=dict(value.get("request_parameters", {})),
            config_checksum=str(value["config_checksum"]),
            code_commit_sha=str(value["code_commit_sha"]),
            provider_library_version=str(value["provider_library_version"]),
            snapshot_status=SnapshotStatus(str(value["snapshot_status"])),
            logical_dataset_key=str(value["logical_dataset_key"]),
            layer=str(value["layer"]),
            checksum_algorithm=str(value["checksum_algorithm"]),
            storage_format=str(value.get("storage_format", STORAGE_FORMAT)),
            snapshot_schema_version=str(
                value.get("snapshot_schema_version", SNAPSHOT_SCHEMA_VERSION)
            ),
            input_snapshot_ids=tuple(map(str, value.get("input_snapshot_ids", []))),
            identity_columns=tuple(map(str, value.get("identity_columns", []))),
            error_message=(
                str(value["error_message"])
                if value.get("error_message") is not None
                else None
            ),
            revision=(
                ProviderRevision.from_dict(revision_value)
                if isinstance(revision_value, Mapping)
                else None
            ),
        )


@dataclass(frozen=True)
class SnapshotWriteResult:
    metadata: SnapshotMetadata
    created: bool

    @property
    def revision(self) -> ProviderRevision | None:
        return self.metadata.revision


@dataclass(frozen=True)
class CanonicalFrame:
    payload: bytes
    records: tuple[Mapping[str, Any], ...]
    column_names: tuple[str, ...]
    column_types: Mapping[str, str]
    content_checksum: str
    schema_checksum: str


def canonicalize_dataframe(
    frame: pd.DataFrame,
    *,
    checksum_algorithm: str = "sha256",
) -> CanonicalFrame:
    """Canonicalize column order, row order, dates, numbers and null values."""

    columns = tuple(sorted(map(str, frame.columns)))
    if len(columns) != len(frame.columns):
        raise SnapshotError("dataframe contains duplicate string column names")
    source_by_name = {str(column): column for column in frame.columns}
    temporal_kinds = {
        column: _temporal_kind(column, frame[source_by_name[column]])
        for column in columns
    }

    records: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False, name=None):
        raw_by_column = {
            str(column): value for column, value in zip(frame.columns, row, strict=True)
        }
        record = {
            column: _canonical_value(raw_by_column[column], temporal_kinds[column])
            for column in columns
        }
        records.append(record)
    records.sort(key=_canonical_json)

    column_types = {
        column: _canonical_column_type(
            [record[column] for record in records], temporal_kinds[column]
        )
        for column in columns
    }
    payload = b"".join(
        (_canonical_json(record) + "\n").encode("utf-8") for record in records
    )
    schema_payload = _canonical_json(
        {"column_names": list(columns), "column_types": column_types}
    ).encode("utf-8")
    return CanonicalFrame(
        payload=payload,
        records=tuple(records),
        column_names=columns,
        column_types=column_types,
        content_checksum=_digest(payload, checksum_algorithm),
        schema_checksum=_digest(schema_payload, checksum_algorithm),
    )


class SnapshotStore:
    """Persist immutable snapshots and provider revisions with atomic commits."""

    def __init__(self, config: MarketDataConfig | None = None) -> None:
        self.config = config or MarketDataConfig()
        hashlib.new(self.config.checksum_algorithm)

    def save_dataframe(
        self,
        frame: pd.DataFrame,
        request: SnapshotRequest,
        *,
        status: SnapshotStatus = SnapshotStatus.COMPLETE,
        error_message: str | None = None,
        fetch_timestamp_utc: datetime | None = None,
    ) -> SnapshotWriteResult:
        """Write one immutable snapshot or return the idempotent existing one."""

        if not isinstance(status, SnapshotStatus):
            status = SnapshotStatus(str(status))
        request_values = self._normalize_request(request)
        canonical = canonicalize_dataframe(
            frame, checksum_algorithm=self.config.checksum_algorithm
        )
        logical_key = self._logical_dataset_key(request_values)
        manifest = self.load_manifest()
        matching = [
            item for item in manifest if item.logical_dataset_key == logical_key
        ]
        previous = self._latest_valid_complete(matching)
        if (
            status is SnapshotStatus.COMPLETE
            and previous is not None
            and previous.content_checksum == canonical.content_checksum
            and previous.schema_checksum == canonical.schema_checksum
        ):
            return SnapshotWriteResult(previous, created=False)

        revision_number = max(
            (item.revision_number for item in matching), default=0
        ) + 1
        fingerprint = _digest(
            f"{canonical.content_checksum}:{canonical.schema_checksum}".encode("utf-8"),
            self.config.checksum_algorithm,
        )
        snapshot_id = (
            f"snap_{logical_key[:16]}_r{revision_number:04d}_{fingerprint[:12]}"
        )
        layer_root = self._layer_root(request_values["layer"])
        logical_directory = (
            layer_root
            / _safe_component(request_values["source"])
            / _safe_component(request_values["dataset_type"])
            / _safe_component(request_values["ticker_or_instrument"])
            / logical_key[:16]
        )
        final_directory = logical_directory / snapshot_id
        final_data_path = final_directory / "data.jsonl"
        relative_data_path = final_data_path.relative_to(self.config.data_root)
        timestamp = fetch_timestamp_utc or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp_text = timestamp.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

        revision = None
        if status is SnapshotStatus.COMPLETE and previous is not None:
            previous_records = self._read_records(previous)
            revision = _build_revision(
                logical_key=logical_key,
                previous=previous,
                snapshot_id=snapshot_id,
                detected_at_utc=timestamp_text,
                old_records=previous_records,
                new_records=canonical.records,
                old_columns=previous.column_names,
                new_columns=canonical.column_names,
                identity_columns=request_values["identity_columns"],
                checksum_algorithm=self.config.checksum_algorithm,
            )

        metadata = SnapshotMetadata(
            snapshot_id=snapshot_id,
            source=request_values["source"],
            dataset_type=request_values["dataset_type"],
            ticker_or_instrument=request_values["ticker_or_instrument"],
            request_start_date=request_values["request_start_date"],
            request_end_date=request_values["request_end_date"],
            fetch_timestamp_utc=timestamp_text,
            row_count=len(frame),
            column_names=canonical.column_names,
            column_types=canonical.column_types,
            content_checksum=canonical.content_checksum,
            schema_checksum=canonical.schema_checksum,
            file_path=relative_data_path.as_posix(),
            revision_number=revision_number,
            previous_snapshot_id=previous.snapshot_id if previous else None,
            request_parameters=request_values["request_parameters"],
            config_checksum=self.config.checksum(),
            code_commit_sha=request_values["code_commit_sha"],
            provider_library_version=request_values["provider_library_version"],
            snapshot_status=status,
            logical_dataset_key=logical_key,
            layer=request_values["layer"],
            checksum_algorithm=self.config.checksum_algorithm,
            input_snapshot_ids=request_values["input_snapshot_ids"],
            identity_columns=request_values["identity_columns"],
            error_message=error_message,
            revision=revision,
        )
        self._commit_snapshot(metadata, canonical.payload, manifest)
        return SnapshotWriteResult(metadata, created=True)

    def record_failed_attempt(
        self,
        request: SnapshotRequest,
        error: Exception | str,
        *,
        partial_data: pd.DataFrame | None = None,
    ) -> SnapshotWriteResult:
        """Record a failed or partial fetch without making it training-usable."""

        frame = partial_data if partial_data is not None else pd.DataFrame()
        status = SnapshotStatus.PARTIAL if not frame.empty else SnapshotStatus.FAILED
        return self.save_dataframe(
            frame,
            request,
            status=status,
            error_message=str(error),
        )

    def load_manifest(self, *, validate_files: bool = False) -> list[SnapshotMetadata]:
        values = _read_jsonl(self.config.snapshot_manifest_path)
        metadata = [SnapshotMetadata.from_dict(value) for value in values]
        if validate_files:
            for item in metadata:
                self.verify_snapshot(item)
        return metadata

    def load_revisions(self) -> list[ProviderRevision]:
        committed_snapshot_ids = {
            metadata.snapshot_id for metadata in self.load_manifest()
        }
        return [
            ProviderRevision.from_dict(value)
            for value in _read_jsonl(self.config.revision_log_path)
            if str(value.get("snapshot_id", "")) in committed_snapshot_ids
        ]

    def get_snapshot(self, snapshot_id: str) -> SnapshotMetadata:
        matches = [
            item for item in self.load_manifest() if item.snapshot_id == snapshot_id
        ]
        if len(matches) != 1:
            raise SnapshotNotFoundError(
                f"expected one committed snapshot for {snapshot_id}, found {len(matches)}"
            )
        return matches[0]

    def read_dataframe(
        self, snapshot: SnapshotMetadata | str, *, require_usable: bool = True
    ) -> pd.DataFrame:
        metadata = (
            self.get_snapshot(snapshot) if isinstance(snapshot, str) else snapshot
        )
        if require_usable and not metadata.is_complete:
            raise SnapshotError(
                f"snapshot {metadata.snapshot_id} is {metadata.snapshot_status.value}, not COMPLETE"
            )
        self.verify_snapshot(metadata)
        records = self._read_records(metadata)
        frame = pd.DataFrame(records, columns=metadata.column_names)
        sort_columns = [
            column for column in metadata.identity_columns if column in frame.columns
        ]
        if sort_columns and not frame.empty:
            frame = frame.sort_values(sort_columns).reset_index(drop=True)
        return frame

    def verify_snapshot(self, snapshot: SnapshotMetadata | str) -> None:
        """Recalculate identity, schema and content checksums from metadata/files."""

        metadata = (
            self.get_snapshot(snapshot) if isinstance(snapshot, str) else snapshot
        )
        path = self._physical_path(metadata.file_path)
        metadata_path = path.parent / "metadata.json"
        if not path.is_file() or not metadata_path.is_file():
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} is missing data or metadata"
            )
        physical_metadata = SnapshotMetadata.from_dict(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )
        if physical_metadata.to_dict() != metadata.to_dict():
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} physical metadata differs from manifest"
            )
        payload = path.read_bytes()
        if _digest(payload, metadata.checksum_algorithm) != metadata.content_checksum:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} content checksum mismatch"
            )
        schema_payload = _canonical_json(
            {
                "column_names": list(metadata.column_names),
                "column_types": dict(metadata.column_types),
            }
        ).encode("utf-8")
        if _digest(schema_payload, metadata.checksum_algorithm) != metadata.schema_checksum:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} schema checksum mismatch"
            )
        expected_logical_key = self._logical_dataset_key(
            {
                "source": metadata.source,
                "dataset_type": metadata.dataset_type,
                "ticker_or_instrument": metadata.ticker_or_instrument,
                "request_start_date": metadata.request_start_date,
                "request_end_date": metadata.request_end_date,
                "request_parameters": metadata.request_parameters,
                "layer": metadata.layer,
            }
        )
        if expected_logical_key != metadata.logical_dataset_key:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} logical dataset key mismatch"
            )
        expected_id = self._snapshot_id_for(metadata)
        if expected_id != metadata.snapshot_id:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} identity cannot be reproduced"
            )
        expected_file_path = self._expected_relative_path(metadata)
        if metadata.file_path != expected_file_path:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} file path does not match its identity"
            )
        records = _decode_jsonl(payload)
        if len(records) != metadata.row_count:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} row count mismatch"
            )
        if records and tuple(sorted(records[0])) != metadata.column_names:
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} columns differ from metadata"
            )

    def is_usable(self, snapshot: SnapshotMetadata | str) -> bool:
        metadata = (
            self.get_snapshot(snapshot) if isinstance(snapshot, str) else snapshot
        )
        if not metadata.is_complete:
            return False
        try:
            self.verify_snapshot(metadata)
        except SnapshotError:
            return False
        return True

    def _latest_valid_complete(
        self, snapshots: Iterable[SnapshotMetadata]
    ) -> SnapshotMetadata | None:
        ordered = sorted(snapshots, key=lambda item: item.revision_number, reverse=True)
        for item in ordered:
            if item.is_complete and self.is_usable(item):
                return item
        return None

    def _commit_snapshot(
        self,
        metadata: SnapshotMetadata,
        payload: bytes,
        current_manifest: Sequence[SnapshotMetadata],
    ) -> None:
        final_data_path = self._physical_path(metadata.file_path)
        final_directory = final_data_path.parent
        logical_directory = final_directory.parent
        logical_directory.mkdir(parents=True, exist_ok=True)
        if final_directory.exists():
            raise SnapshotError(f"immutable snapshot path already exists: {final_directory}")

        temporary_directory = Path(
            tempfile.mkdtemp(prefix=".snapshot-tmp-", dir=logical_directory)
        )
        directory_committed = False
        try:
            temporary_data = temporary_directory / "data.jsonl"
            temporary_metadata = temporary_directory / "metadata.json"
            _write_bytes_synced(temporary_data, payload)
            _write_bytes_synced(
                temporary_metadata,
                (
                    json.dumps(
                        metadata.to_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            self._replace_path(temporary_directory, final_directory)
            directory_committed = True

            new_manifest = [*current_manifest, metadata]
            self._write_revision_log(new_manifest)
            self._write_manifest(new_manifest)
        except Exception:
            if directory_committed and final_directory.exists():
                shutil.rmtree(final_directory)
            # The manifest is the commit boundary. If a manifest replace fails
            # after the derived revision log was written, restore that log from
            # the still-committed manifest so no orphan revision is advertised.
            try:
                self._write_revision_log(current_manifest)
            except Exception:
                pass
            raise
        finally:
            if temporary_directory.exists():
                shutil.rmtree(temporary_directory)

    def _write_manifest(self, values: Sequence[SnapshotMetadata]) -> None:
        _atomic_write_jsonl(
            self.config.snapshot_manifest_path,
            [value.to_dict() for value in values],
            self._replace_path,
        )

    def _write_revision_log(self, values: Sequence[SnapshotMetadata]) -> None:
        revisions = [
            value.revision.to_dict() for value in values if value.revision is not None
        ]
        _atomic_write_jsonl(
            self.config.revision_log_path,
            revisions,
            self._replace_path,
        )

    @staticmethod
    def _replace_path(source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def _read_records(self, metadata: SnapshotMetadata) -> tuple[Mapping[str, Any], ...]:
        path = self._physical_path(metadata.file_path)
        if not path.is_file():
            raise SnapshotCorruptError(
                f"snapshot {metadata.snapshot_id} data file does not exist"
            )
        return tuple(_decode_jsonl(path.read_bytes()))

    def _physical_path(self, relative_path: str) -> Path:
        root = self.config.data_root.resolve()
        candidate = (self.config.data_root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise SnapshotCorruptError("snapshot file path escapes data root") from error
        return candidate

    def _layer_root(self, layer: str) -> Path:
        if layer == "raw":
            return self.config.raw_data_root
        if layer == "derived":
            return self.config.derived_data_root
        raise ValueError("snapshot layer must be 'raw' or 'derived'")

    def _normalize_request(self, request: SnapshotRequest) -> dict[str, Any]:
        source = request.source.strip().lower()
        dataset_type = request.dataset_type.strip().lower()
        ticker = request.ticker_or_instrument.strip().upper()
        layer = request.layer.strip().lower()
        if not source or not dataset_type or not ticker:
            raise ValueError("source, dataset_type and ticker_or_instrument are required")
        self._layer_root(layer)
        start = _coerce_date(request.request_start_date)
        end = _coerce_date(request.request_end_date)
        if start > end:
            raise ValueError("request_start_date must be on or before request_end_date")
        return {
            "source": source,
            "dataset_type": dataset_type,
            "ticker_or_instrument": ticker,
            "request_start_date": start.isoformat(),
            "request_end_date": end.isoformat(),
            "request_parameters": _json_ready(dict(request.request_parameters)),
            "provider_library_version": request.provider_library_version or "unknown",
            "code_commit_sha": request.code_commit_sha or "unknown",
            "layer": layer,
            "input_snapshot_ids": tuple(map(str, request.input_snapshot_ids)),
            "identity_columns": tuple(map(str, request.identity_columns)),
        }

    def _logical_dataset_key(self, request_values: Mapping[str, Any]) -> str:
        payload = {
            key: request_values[key]
            for key in (
                "source",
                "dataset_type",
                "ticker_or_instrument",
                "request_start_date",
                "request_end_date",
                "request_parameters",
                "layer",
            )
        }
        return _digest(
            _canonical_json(payload).encode("utf-8"),
            self.config.checksum_algorithm,
        )

    def _snapshot_id_for(self, metadata: SnapshotMetadata) -> str:
        fingerprint = _digest(
            f"{metadata.content_checksum}:{metadata.schema_checksum}".encode("utf-8"),
            metadata.checksum_algorithm,
        )
        return (
            f"snap_{metadata.logical_dataset_key[:16]}_"
            f"r{metadata.revision_number:04d}_{fingerprint[:12]}"
        )

    def _expected_relative_path(self, metadata: SnapshotMetadata) -> str:
        path = (
            self._layer_root(metadata.layer)
            / _safe_component(metadata.source)
            / _safe_component(metadata.dataset_type)
            / _safe_component(metadata.ticker_or_instrument)
            / metadata.logical_dataset_key[:16]
            / metadata.snapshot_id
            / "data.jsonl"
        )
        return path.relative_to(self.config.data_root).as_posix()


def _build_revision(
    *,
    logical_key: str,
    previous: SnapshotMetadata,
    snapshot_id: str,
    detected_at_utc: str,
    old_records: Sequence[Mapping[str, Any]],
    new_records: Sequence[Mapping[str, Any]],
    old_columns: Sequence[str],
    new_columns: Sequence[str],
    identity_columns: Sequence[str],
    checksum_algorithm: str,
) -> ProviderRevision:
    columns = sorted(
        set().union(*(record.keys() for record in [*old_records, *new_records]))
    )
    keys = tuple(column for column in identity_columns if column in columns)
    if not keys:
        keys = tuple(_default_identity_columns(columns))

    old_map = _records_by_identity(old_records, keys)
    new_map = _records_by_identity(new_records, keys)
    old_keys = set(old_map)
    new_keys = set(new_map)
    changed_rows = 0
    changed_cells = 0
    changed_columns: set[str] = set(old_columns).symmetric_difference(new_columns)
    for key in sorted(old_keys & new_keys):
        old = old_map[key]
        new = new_map[key]
        row_changed = False
        for column in columns:
            if old.get(column) != new.get(column):
                row_changed = True
                changed_cells += 1
                changed_columns.add(column)
        changed_rows += int(row_changed)

    date_column = next(
        (column for column in keys if _temporal_name_kind(column) == "date"),
        next((column for column in columns if _temporal_name_kind(column) == "date"), None),
    )
    added_dates = _dates_for_keys(new_keys - old_keys, new_map, date_column)
    removed_dates = _dates_for_keys(old_keys - new_keys, old_map, date_column)
    revision_payload = {
        "logical_dataset_key": logical_key,
        "previous_snapshot_id": previous.snapshot_id,
        "snapshot_id": snapshot_id,
        "changed_row_count": changed_rows,
        "added_dates": added_dates,
        "removed_dates": removed_dates,
        "changed_columns": sorted(changed_columns),
        "changed_cell_count": changed_cells,
    }
    revision_id = "rev_" + _digest(
        _canonical_json(revision_payload).encode("utf-8"), checksum_algorithm
    )[:24]
    return ProviderRevision(
        revision_id=revision_id,
        logical_dataset_key=logical_key,
        previous_snapshot_id=previous.snapshot_id,
        snapshot_id=snapshot_id,
        detected_at_utc=detected_at_utc,
        changed_row_count=changed_rows,
        added_dates=tuple(added_dates),
        removed_dates=tuple(removed_dates),
        changed_columns=tuple(sorted(changed_columns)),
        changed_cell_count=changed_cells,
    )


def _records_by_identity(
    records: Sequence[Mapping[str, Any]], identity_columns: Sequence[str]
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if identity_columns:
            identity = _canonical_json([record.get(column) for column in identity_columns])
        else:
            identity = _canonical_json(record)
        if identity in result:
            # Preserve duplicates deterministically rather than silently overwriting.
            suffix = 2
            candidate = f"{identity}#{suffix}"
            while candidate in result:
                suffix += 1
                candidate = f"{identity}#{suffix}"
            identity = candidate
        result[identity] = record
    return result


def _dates_for_keys(
    keys: Iterable[str],
    records: Mapping[str, Mapping[str, Any]],
    date_column: str | None,
) -> list[str]:
    if date_column is None:
        return []
    return sorted(
        {
            str(records[key][date_column])
            for key in keys
            if records[key].get(date_column) is not None
        }
    )


def _default_identity_columns(columns: Sequence[str]) -> list[str]:
    ticker_candidates = [
        column
        for column in columns
        if column.lower() in {"ticker", "symbol", "instrument", "hgdg_hs_kodu"}
    ]
    date_candidates = [
        column for column in columns if _temporal_name_kind(column) == "date"
    ]
    return [*ticker_candidates[:1], *date_candidates[:1]]


def _temporal_kind(column: str, series: pd.Series) -> str | None:
    named = _temporal_name_kind(column)
    if named:
        return named
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    return None


def _temporal_name_kind(column: str) -> str | None:
    name = column.casefold()
    if "timestamp" in name or "datetime" in name:
        return "datetime"
    if name in {"date", "day", "tarih"} or name.endswith("_date") or "tarih" in name:
        return "date"
    return None


def _canonical_value(value: Any, temporal_kind: str | None) -> Any:
    if _is_null(value):
        return None
    if temporal_kind:
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError):
            parsed = pd.NaT
        if not pd.isna(parsed):
            if temporal_kind == "date":
                return parsed.date().isoformat()
            return parsed.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number == 0:
            return 0.0
        return number
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item, None)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, set):
        return sorted(
            (_canonical_value(item, None) for item in value), key=_canonical_json
        )
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, None) for item in value]
    return str(value)


def _canonical_column_type(values: Sequence[Any], temporal_kind: str | None) -> str:
    if temporal_kind:
        return temporal_kind
    types = {type(value) for value in values if value is not None}
    if not types:
        return "null"
    if types <= {bool}:
        return "boolean"
    if types <= {int}:
        return "integer"
    if types <= {int, float}:
        return "number"
    if types <= {str}:
        return "string"
    if types <= {dict}:
        return "object"
    if types <= {list}:
        return "array"
    return "mixed"


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict, str, bytes, bytearray)):
        return False
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def _coerce_date(value: date | str | pd.Timestamp) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _safe_component(value: str) -> str:
    result = _SAFE_PATH_COMPONENT.sub("_", value.strip())
    return result.strip("._") or "unknown"


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, set):
        return sorted((_json_ready(item) for item in value), key=_canonical_json)
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return _canonical_value(value, None)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, payload).hexdigest()


def _decode_jsonl(payload: bytes) -> list[Mapping[str, Any]]:
    text = payload.decode("utf-8")
    if not text:
        return []
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise SnapshotCorruptError(
                f"canonical JSONL line {line_number} is not an object"
            )
        records.append(value)
    return records


def _read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    return _decode_jsonl(path.read_bytes())


def _write_bytes_synced(path: Path, payload: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_jsonl(
    path: Path,
    values: Sequence[Mapping[str, Any]],
    replace_func: Any,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(
        (_canonical_json(value) + "\n").encode("utf-8") for value in values
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".jsonl.tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace_func(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
