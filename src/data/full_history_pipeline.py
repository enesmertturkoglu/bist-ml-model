"""Resumable full-history orchestration for the frozen active BIST universe."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.config import MarketDataConfig, SnapshotStatus
from src.data.active_universe import (
    COLLECTION_MANIFEST_COLUMNS,
    UNIVERSE_VERSION,
    build_history_collection_manifest,
    validate_active_universe_snapshot,
)
from src.data.calendar_pipeline import GlobalCalendarPipeline
from src.data.cleaning import summarize_cleaning
from src.data.cleaning_pipeline import CleaningSnapshotSet, MarketDataCleaningPipeline
from src.data.collectors import MarketDataCollector, SourceCollectionResult
from src.data.label_pipeline import LabelGenerationPipeline
from src.data.labels import summarize_labels
from src.data.price_limits import PriceStepTable
from src.data.security_identity import TickerMapping, normalize_ticker
from src.data.security_identity_pipeline import SecurityIdentityPipeline
from src.data.snapshot_store import SnapshotMetadata, SnapshotStore
from src.data.xu100_pipeline import Xu100Pipeline
from src.features.catalog import BASELINE_V1_FEATURES
from src.features.pipeline import BaselineFeaturePipeline
from src.modeling.dataset import TrainingDataset, build_training_dataset
from src.modeling.prediction_universe import (
    PredictionUniverseAssembly,
    PredictionUniverseInputAssembler,
)


DEFAULT_ACTIVE_UNIVERSE_SNAPSHOT_ID = (
    "snap_fb0011eaecf3b4b7_r0002_112665b37839"
)
DEFAULT_AS_OF_DATE = date(2026, 7, 29)
DEFAULT_COLLECTION_START_DATE = date(2020, 3, 13)
DEFAULT_COLLECTION_END_DATE = date(2026, 7, 29)
DEFAULT_MASTER_SECURITY_COUNT = 621
DEFAULT_REPORT_ROOT = Path("reports/full_history")

COLLECTION_STATUS_COLUMNS: tuple[str, ...] = (
    "security_id",
    "current_ticker",
    "provider_tickers_queried",
    "requested_start_date",
    "requested_end_date",
    "isyatirim_status",
    "yfinance_status",
    "raw_snapshot_ids",
    "nominal_snapshot_id",
    "identity_snapshot_id",
    "clean_snapshot_id",
    "label_snapshot_id",
    "first_observed_date",
    "last_observed_date",
    "observed_session_count",
    "missing_session_count",
    "longest_internal_gap_sessions",
    "collection_complete",
    "failure_stage",
    "failure_class",
    "failure_reason",
    "mapping_review_required",
)

MAPPING_REVIEW_COLUMNS: tuple[str, ...] = (
    "security_id",
    "current_ticker",
    "issue_type",
    "first_observed_date",
    "last_observed_date",
    "gap_dates",
    "gap_session_count",
    "longest_internal_gap_sessions",
    "provider_evidence",
    "possible_historical_ticker",
    "official_evidence_status",
    "recommended_action",
)

PREDICTION_DAILY_COLUMNS: tuple[str, ...] = (
    "prediction_date",
    "master_universe_count",
    "observed_security_count",
    "feature_row_count",
    "prediction_eligible_count",
    "prediction_excluded_count",
)


class FullHistoryError(RuntimeError):
    """Raised when preflight or a fail-closed derived contract is violated."""


@dataclass(frozen=True)
class FullHistoryContext:
    active_universe_snapshot_id: str = DEFAULT_ACTIVE_UNIVERSE_SNAPSHOT_ID
    universe_version: str = UNIVERSE_VERSION
    active_universe_as_of_date: date = DEFAULT_AS_OF_DATE
    master_security_count: int = DEFAULT_MASTER_SECURITY_COUNT
    collection_start_date: date = DEFAULT_COLLECTION_START_DATE
    model_period_start_date: date = DEFAULT_COLLECTION_START_DATE
    collection_end_date: date = DEFAULT_COLLECTION_END_DATE

    def __post_init__(self) -> None:
        if self.collection_start_date < self.model_period_start_date:
            raise FullHistoryError(
                "collection cannot begin before the binding model-period start"
            )
        if self.collection_start_date > self.collection_end_date:
            raise FullHistoryError("collection_start_date must not follow collection_end_date")
        if self.master_security_count < 1:
            raise FullHistoryError("master_security_count must be positive")


@dataclass(frozen=True)
class FullHistoryPaths:
    manifest: Path = Path("reports/universe/full_history_collection_manifest_v1.csv")
    mapping: Path = Path("reference_data/bist_security_ticker_map_v1.csv")
    active_universe_csv: Path = Path("reference_data/bist_active_universe_v1.csv")
    price_steps: Path = Path("reference_data/bist_equity_tick_sizes_v1.csv")
    feature_catalog: Path = Path("FEATURE_CATALOG.md")
    report_root: Path = DEFAULT_REPORT_ROOT


@dataclass(frozen=True)
class FullHistoryPreflight:
    active_metadata: SnapshotMetadata
    universe: pd.DataFrame
    manifest: pd.DataFrame
    mapping: TickerMapping
    active_universe_file_checksum: str
    manifest_file_checksum: str
    mapping_file_checksum: str


@dataclass(frozen=True)
class ManifestOutcome:
    row_number: int
    security_id: str
    current_ticker: str
    provider_ticker: str
    period_start: str
    period_end: str
    isyatirim_status: str
    yfinance_status: str
    isyatirim_raw_snapshot_id: str
    yfinance_raw_snapshot_id: str
    nominal_snapshot_id: str
    isyatirim_dates: tuple[str, ...] = ()
    yfinance_dates: tuple[str, ...] = ()
    failure_stage: str = ""
    failure_class: str = ""
    failure_reason: str = ""

    @property
    def complete(self) -> bool:
        return (
            self.isyatirim_status == SnapshotStatus.COMPLETE.value
            and self.yfinance_status == SnapshotStatus.COMPLETE.value
            and bool(self.nominal_snapshot_id)
        )


@dataclass(frozen=True)
class DerivedArtifacts:
    identity: SnapshotMetadata
    clean: SnapshotMetadata
    label: SnapshotMetadata
    calendar: SnapshotMetadata
    xu100_raw: SnapshotMetadata
    xu100_validated: SnapshotMetadata
    feature: SnapshotMetadata
    identity_frame: pd.DataFrame
    clean_frame: pd.DataFrame
    label_frame: pd.DataFrame
    calendar_frame: pd.DataFrame
    xu100_frame: pd.DataFrame
    feature_frame: pd.DataFrame
    feature_quality: pd.DataFrame
    prediction: PredictionUniverseAssembly
    training: TrainingDataset

    @property
    def snapshot_metadata(self) -> tuple[SnapshotMetadata, ...]:
        return (
            self.identity,
            self.clean,
            self.label,
            self.calendar,
            self.xu100_raw,
            self.xu100_validated,
            self.feature,
        )


@dataclass(frozen=True)
class FullHistoryRunResult:
    run_status: str
    preflight: FullHistoryPreflight
    outcomes: tuple[ManifestOutcome, ...]
    status: pd.DataFrame
    summary: Mapping[str, Any]
    used_security_ids: tuple[str, ...]
    excluded_security_ids: tuple[str, ...]
    derived: DerivedArtifacts | None
    reports: Mapping[str, Path] = field(default_factory=dict)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize_error(value: object, *, maximum_length: int = 1000) -> str:
    """Remove common credential shapes before an exception reaches a report."""

    text = "" if value is None else str(value)
    patterns = (
        r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)",
        r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)([^\s,;&]+)",
        r"(?i)([?&](?:api[_-]?key|token|password|secret)=)([^&\s]+)",
    )
    for pattern in patterns:
        text = re.sub(pattern, r"\1[REDACTED]", text)
    return text[:maximum_length]


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace one report while preserving the previous checkpoint."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
    )


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write_text(
        path,
        frame.to_csv(index=False, lineterminator="\n", na_rep=""),
    )


class FullHistoryPipeline:
    """Validate, collect and derive the frozen-universe historical data chain."""

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        *,
        context: FullHistoryContext | None = None,
        paths: FullHistoryPaths | None = None,
        snapshot_store: SnapshotStore | None = None,
        collector: MarketDataCollector | None = None,
        code_commit_sha: str | None = None,
    ) -> None:
        self.config = config or MarketDataConfig()
        self.context = context or FullHistoryContext()
        self.paths = paths or FullHistoryPaths()
        self.snapshot_store = snapshot_store or SnapshotStore(self.config)
        self.collector = collector
        self.code_commit_sha = code_commit_sha

    def preflight(self) -> FullHistoryPreflight:
        """Fail before provider construction when frozen inputs are inconsistent."""

        required_files = (
            self.paths.active_universe_csv,
            self.paths.manifest,
            self.paths.mapping,
            self.paths.price_steps,
            self.paths.feature_catalog,
        )
        missing_files = [str(path) for path in required_files if not path.is_file()]
        if missing_files:
            raise FullHistoryError(f"preflight files missing: {missing_files}")

        metadata = validate_active_universe_snapshot(
            self.snapshot_store, self.context.active_universe_snapshot_id
        )
        universe = self.snapshot_store.read_dataframe(metadata)
        expected_identity = ("universe", "active_bist_equities", "derived")
        if (metadata.source, metadata.dataset_type, metadata.layer) != expected_identity:
            raise FullHistoryError("active universe snapshot type mismatch")
        parameters = metadata.request_parameters
        if parameters.get("universe_version") != self.context.universe_version:
            raise FullHistoryError("active universe version mismatch")
        expected_as_of = self.context.active_universe_as_of_date.isoformat()
        if parameters.get("as_of_date") != expected_as_of:
            raise FullHistoryError("active universe as-of mismatch")
        if len(universe) != self.context.master_security_count:
            raise FullHistoryError("active universe security count mismatch")
        if universe["security_id"].nunique() != self.context.master_security_count:
            raise FullHistoryError("active universe security_id uniqueness mismatch")
        if universe["current_ticker"].nunique() != self.context.master_security_count:
            raise FullHistoryError("active universe current_ticker uniqueness mismatch")
        if set(universe["universe_version"].astype(str)) != {self.context.universe_version}:
            raise FullHistoryError("active universe row version mismatch")
        if set(universe["as_of_date"].astype(str)) != {expected_as_of}:
            raise FullHistoryError("active universe row as-of mismatch")

        active_csv = pd.read_csv(self.paths.active_universe_csv)
        snapshot_columns = [
            "security_id",
            "current_ticker",
            "company_name",
            "market_group",
            "market_name",
            "instrument_type",
            "universe_version",
            "as_of_date",
        ]
        missing_active_columns = set(snapshot_columns).difference(active_csv.columns)
        if missing_active_columns:
            raise FullHistoryError(
                f"active universe CSV fields missing: {sorted(missing_active_columns)}"
            )
        try:
            pd.testing.assert_frame_equal(
                active_csv.loc[:, snapshot_columns]
                .astype(str)
                .sort_values("security_id")
                .reset_index(drop=True),
                universe.loc[:, snapshot_columns]
                .astype(str)
                .sort_values("security_id")
                .reset_index(drop=True),
                check_dtype=False,
            )
        except AssertionError as exc:
            raise FullHistoryError(
                "active universe CSV rows differ from the verified snapshot"
            ) from exc
        active_checksum = hashlib.sha256(
            active_csv.to_csv(index=False, lineterminator="\n").encode("utf-8")
        ).hexdigest()
        expected_file_checksum = str(
            metadata.revision_context.get("active_universe_file_checksum", "")
        )
        if active_checksum != expected_file_checksum:
            raise FullHistoryError("active universe CSV checksum mismatch")

        mapping = TickerMapping.from_csv(
            self.paths.mapping, checksum_algorithm=self.config.checksum_algorithm
        )
        if mapping.version != str(
            metadata.revision_context.get("ticker_mapping_version", "")
        ):
            raise FullHistoryError("ticker mapping version mismatch")
        if mapping.checksum != str(
            metadata.revision_context.get("ticker_mapping_checksum", "")
        ):
            raise FullHistoryError("ticker mapping checksum mismatch")

        manifest = pd.read_csv(self.paths.manifest, dtype=str, keep_default_na=False)
        if list(manifest.columns) != list(COLLECTION_MANIFEST_COLUMNS):
            raise FullHistoryError("collection manifest schema mismatch")
        expected_manifest = build_history_collection_manifest(
            universe,
            mapping,
            start_date=self.context.collection_start_date,
            end_date=self.context.collection_end_date,
        ).astype(str)
        actual_manifest = manifest.astype(str)
        try:
            pd.testing.assert_frame_equal(
                actual_manifest.reset_index(drop=True),
                expected_manifest.reset_index(drop=True),
                check_dtype=False,
            )
        except AssertionError as exc:
            raise FullHistoryError(
                "collection manifest differs from the frozen universe/mapping periods"
            ) from exc
        if set(manifest["security_id"]) != set(universe["security_id"].astype(str)):
            raise FullHistoryError("collection manifest security set mismatch")
        if manifest[["security_id", "provider_ticker", "period_start", "period_end"]].duplicated().any():
            raise FullHistoryError("duplicate provider period in collection manifest")
        self._validate_manifest_periods(manifest)
        return FullHistoryPreflight(
            active_metadata=metadata,
            universe=universe.sort_values("security_id").reset_index(drop=True),
            manifest=manifest.reset_index(drop=True),
            mapping=mapping,
            active_universe_file_checksum=active_checksum,
            manifest_file_checksum=sha256_file(self.paths.manifest),
            mapping_file_checksum=sha256_file(self.paths.mapping),
        )

    def _validate_manifest_periods(self, manifest: pd.DataFrame) -> None:
        lower = pd.Timestamp(self.context.collection_start_date)
        upper = pd.Timestamp(self.context.collection_end_date)
        values = manifest.copy()
        values["period_start_ts"] = pd.to_datetime(values["period_start"], errors="raise")
        values["period_end_ts"] = pd.to_datetime(values["period_end"], errors="raise")
        if values["period_start_ts"].lt(lower).any() or values["period_end_ts"].gt(upper).any():
            raise FullHistoryError("manifest period falls outside the binding collection range")
        if values["period_start_ts"].gt(values["period_end_ts"]).any():
            raise FullHistoryError("manifest provider period start follows its end")
        for security_id, group in values.groupby("security_id", sort=True):
            ordered = group.sort_values(
                ["period_start_ts", "period_end_ts", "provider_ticker"]
            )
            previous_end: pd.Timestamp | None = None
            for row in ordered.itertuples(index=False):
                if previous_end is not None and row.period_start_ts <= previous_end:
                    raise FullHistoryError(
                        f"overlapping provider periods for security {security_id}"
                    )
                previous_end = row.period_end_ts

    def collect_manifest(
        self,
        preflight: FullHistoryPreflight,
        *,
        refresh: bool = False,
        run_started_at_utc: str | None = None,
    ) -> tuple[tuple[ManifestOutcome, ...], pd.DataFrame, Mapping[str, Any]]:
        """Collect each manifest row sequentially and checkpoint after every row."""

        collector = self.collector or MarketDataCollector(
            self.config,
            snapshot_store=self.snapshot_store,
            ticker_mapping=preflight.mapping,
            code_commit_sha=self.code_commit_sha,
        )
        started = run_started_at_utc or _utc_now()
        outcomes: list[ManifestOutcome] = []
        for row_number, row in preflight.manifest.iterrows():
            start = date.fromisoformat(str(row["period_start"]))
            end = date.fromisoformat(str(row["period_end"]))
            try:
                result = collector.collect_ticker(
                    str(row["provider_ticker"]), start, end, refresh=refresh
                )
                outcome = self._manifest_outcome(row_number, row, result.source_results)
            except Exception as exc:
                outcome = ManifestOutcome(
                    row_number=row_number,
                    security_id=str(row["security_id"]),
                    current_ticker=str(row["current_ticker"]),
                    provider_ticker=str(row["provider_ticker"]),
                    period_start=start.isoformat(),
                    period_end=end.isoformat(),
                    isyatirim_status="FAILED",
                    yfinance_status="FAILED",
                    isyatirim_raw_snapshot_id="",
                    yfinance_raw_snapshot_id="",
                    nominal_snapshot_id="",
                    failure_stage="COLLECTION_ORCHESTRATION",
                    failure_class=type(exc).__name__,
                    failure_reason=sanitize_error(exc),
                )
            outcomes.append(outcome)
            status = build_collection_status(preflight, outcomes)
            summary = build_collection_summary(status)
            provenance = self._run_provenance(
                preflight,
                status,
                summary,
                run_status="COLLECTING",
                run_started_at_utc=started,
                used_security_ids=(),
                excluded_security_ids=(),
                snapshots=(),
            )
            self._write_collection_checkpoint(status, summary, provenance)
        final_status = build_collection_status(preflight, outcomes)
        final_summary = build_collection_summary(final_status)
        return tuple(outcomes), final_status, final_summary

    def _manifest_outcome(
        self,
        row_number: int,
        row: pd.Series,
        results: Sequence[SourceCollectionResult],
    ) -> ManifestOutcome:
        by_source = {item.source: item for item in results}
        isyatirim = by_source["isyatirim"]
        yfinance = by_source["yfinance"]
        nominal = yfinance.derived_snapshots[0] if yfinance.derived_snapshots else None
        failures = [item for item in (isyatirim, yfinance) if item.failure_reason]
        last_failure = failures[-1] if failures else None
        return ManifestOutcome(
            row_number=row_number,
            security_id=str(row["security_id"]),
            current_ticker=str(row["current_ticker"]),
            provider_ticker=str(row["provider_ticker"]),
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            isyatirim_status=isyatirim.raw_snapshot.snapshot_status.value,
            yfinance_status=(
                SnapshotStatus.COMPLETE.value
                if yfinance.complete
                else yfinance.raw_snapshot.snapshot_status.value
            ),
            isyatirim_raw_snapshot_id=isyatirim.raw_snapshot.snapshot_id,
            yfinance_raw_snapshot_id=yfinance.raw_snapshot.snapshot_id,
            nominal_snapshot_id=(
                nominal.snapshot_id
                if nominal is not None and self.snapshot_store.is_usable(nominal)
                else ""
            ),
            isyatirim_dates=self._observed_dates(isyatirim.raw_snapshot, "HGDG_TARIH"),
            yfinance_dates=self._observed_dates(yfinance.raw_snapshot, "date"),
            failure_stage=(last_failure.source.upper() if last_failure else ""),
            failure_class=(last_failure.failure_class or "" if last_failure else ""),
            failure_reason=(
                sanitize_error(last_failure.failure_reason) if last_failure else ""
            ),
        )

    def _observed_dates(
        self, metadata: SnapshotMetadata, column: str
    ) -> tuple[str, ...]:
        if not self.snapshot_store.is_usable(metadata):
            return ()
        frame = self.snapshot_store.read_dataframe(metadata)
        if column not in frame.columns:
            return ()
        dates = pd.to_datetime(frame[column], errors="coerce").dropna().dt.normalize()
        return tuple(sorted({value.date().isoformat() for value in dates}))

    def _write_collection_checkpoint(
        self,
        status: pd.DataFrame,
        summary: Mapping[str, Any],
        provenance: Mapping[str, Any],
    ) -> None:
        root = self.paths.report_root
        atomic_write_csv(root / "collection_status.csv", status)
        atomic_write_json(root / "collection_summary.json", summary)
        atomic_write_json(root / "run_provenance.json", provenance)

    def _run_provenance(
        self,
        preflight: FullHistoryPreflight,
        status: pd.DataFrame,
        summary: Mapping[str, Any],
        *,
        run_status: str,
        run_started_at_utc: str,
        used_security_ids: Sequence[str],
        excluded_security_ids: Sequence[str],
        snapshots: Sequence[SnapshotMetadata],
    ) -> dict[str, Any]:
        return {
            "run_status": run_status,
            "run_started_at_utc": run_started_at_utc,
            "last_checkpoint_at_utc": _utc_now(),
            "active_universe_snapshot_id": preflight.active_metadata.snapshot_id,
            "active_universe_snapshot_checksum": preflight.active_metadata.content_checksum,
            "active_universe_file_checksum": preflight.active_universe_file_checksum,
            "universe_version": self.context.universe_version,
            "active_universe_as_of_date": self.context.active_universe_as_of_date.isoformat(),
            "master_security_count": self.context.master_security_count,
            "collection_start_date": self.context.collection_start_date.isoformat(),
            "model_period_start_date": self.context.model_period_start_date.isoformat(),
            "collection_end_date": self.context.collection_end_date.isoformat(),
            "manifest_path": self.paths.manifest.as_posix(),
            "manifest_file_checksum": preflight.manifest_file_checksum,
            "mapping_path": self.paths.mapping.as_posix(),
            "mapping_version": preflight.mapping.version,
            "mapping_checksum": preflight.mapping.checksum,
            "mapping_file_checksum": preflight.mapping_file_checksum,
            "collection_summary": dict(summary),
            "used_security_ids": sorted(map(str, used_security_ids)),
            "excluded_security_ids": sorted(map(str, excluded_security_ids)),
            "snapshot_lineage": {
                item.dataset_type: {
                    "snapshot_id": item.snapshot_id,
                    "content_checksum": item.content_checksum,
                    "source": item.source,
                    "layer": item.layer,
                }
                for item in snapshots
            },
            "experiment_ready": bool(
                run_status == "COMPLETE"
                and len(used_security_ids) == self.context.master_security_count
            ),
            "lightgbm_training_run": False,
            "experiment_log_created": False,
            "status_row_count": int(len(status)),
        }

    def run_derived(
        self,
        preflight: FullHistoryPreflight,
        outcomes: Sequence[ManifestOutcome],
        used_security_ids: Sequence[str],
        *,
        refresh: bool = False,
    ) -> DerivedArtifacts:
        """Call the existing derived pipelines for the explicit complete set."""

        used = set(map(str, used_security_ids))
        selected = [item for item in outcomes if item.security_id in used]
        if not selected or not all(item.complete for item in selected):
            raise FullHistoryError("derived inputs are not an explicit complete security set")
        nominal_ids = [item.nominal_snapshot_id for item in selected]
        isyatirim_ids = [item.isyatirim_raw_snapshot_id for item in selected]
        yfinance_ids = [item.yfinance_raw_snapshot_id for item in selected]
        if any(len(values) != len(set(values)) for values in (nominal_ids, isyatirim_ids, yfinance_ids)):
            raise FullHistoryError("duplicate raw/nominal snapshot ID in derived inputs")

        identity_result = SecurityIdentityPipeline(
            self.config,
            snapshot_store=self.snapshot_store,
            code_commit_sha=self.code_commit_sha or "unknown",
        ).run(nominal_ids, preflight.mapping)
        identity = identity_result.frame
        if identity.duplicated(["security_id", "date"]).any():
            raise FullHistoryError("duplicate security_id + date in identity output")
        identity_set = set(identity["security_id"].astype(str))
        if identity_set != used:
            raise FullHistoryError(
                "identity output security scope differs from the declared complete set"
            )

        definitions = [
            CleaningSnapshotSet(
                ticker=item.provider_ticker,
                isyatirim_raw_snapshot_id=item.isyatirim_raw_snapshot_id,
                yfinance_raw_snapshot_id=item.yfinance_raw_snapshot_id,
                yfinance_nominal_snapshot_id=item.nominal_snapshot_id,
            )
            for item in selected
        ]
        price_steps = PriceStepTable.from_csv(self.paths.price_steps)
        cleaning_result = MarketDataCleaningPipeline(
            self.config,
            snapshot_store=self.snapshot_store,
            code_commit_sha=self.code_commit_sha or "unknown",
        ).run(
            definitions,
            price_steps,
            security_identity_snapshot_id=identity_result.snapshot.metadata.snapshot_id,
            ticker_mapping=preflight.mapping,
        )
        clean = cleaning_result.frame
        if clean.duplicated(["security_id", "prediction_date"]).any():
            raise FullHistoryError("duplicate security_id + date in clean output")

        label_result = LabelGenerationPipeline(
            self.config,
            snapshot_store=self.snapshot_store,
            code_commit_sha=self.code_commit_sha or "unknown",
        ).run(cleaning_result.snapshot.metadata.snapshot_id, price_steps)
        labels = label_result.frame
        if labels.duplicated(["security_id", "prediction_date"]).any():
            raise FullHistoryError("duplicate security_id + date in label output")

        calendar_result = GlobalCalendarPipeline(
            self.snapshot_store, code_commit_sha=self.code_commit_sha
        ).run(isyatirim_ids)
        calendar = self.snapshot_store.read_dataframe(calendar_result.snapshot)
        xu100_result = Xu100Pipeline(
            self.config,
            snapshot_store=self.snapshot_store,
            code_commit_sha=self.code_commit_sha,
        ).run(
            self.context.collection_start_date,
            self.context.collection_end_date,
            global_calendar_snapshot_id=calendar_result.snapshot.snapshot_id,
            refresh=refresh,
        )
        xu100 = self.snapshot_store.read_dataframe(xu100_result.validated_snapshot)

        feature_result = BaselineFeaturePipeline(
            self.config,
            snapshot_store=self.snapshot_store,
            code_commit_sha=self.code_commit_sha,
            catalog_path=self.paths.feature_catalog,
        ).run(
            yfinance_raw_snapshot_ids=yfinance_ids,
            isyatirim_raw_snapshot_ids=isyatirim_ids,
            identity_snapshot_id=identity_result.snapshot.metadata.snapshot_id,
            xu100_snapshot_id=xu100_result.validated_snapshot.snapshot_id,
            calendar_snapshot_id=calendar_result.snapshot.snapshot_id,
        )
        features = feature_result.frame
        if list(features.columns) != [
            "security_id",
            "prediction_date",
            *BASELINE_V1_FEATURES,
        ]:
            raise FullHistoryError("feature output is not exact ordered baseline_v1")
        if features.duplicated(["security_id", "prediction_date"]).any():
            raise FullHistoryError("duplicate feature key")

        prediction = PredictionUniverseInputAssembler(
            self.snapshot_store, catalog_path=self.paths.feature_catalog
        ).assemble(
            yfinance_raw_snapshot_ids=yfinance_ids,
            isyatirim_raw_snapshot_ids=isyatirim_ids,
            identity_snapshot_id=identity_result.snapshot.metadata.snapshot_id,
            active_universe_snapshot_id=preflight.active_metadata.snapshot_id,
            feature_snapshot_id=feature_result.snapshot.snapshot_id,
            xu100_snapshot_id=xu100_result.validated_snapshot.snapshot_id,
            calendar_snapshot_id=calendar_result.snapshot.snapshot_id,
            minimum_history_sessions=self.config.training.minimum_feature_history_sessions,
        )
        training = build_training_dataset(
            prediction.universe,
            prediction.features,
            labels,
            prediction.calendar,
            as_of_date=self.context.collection_end_date,
            feature_snapshot_id=feature_result.snapshot.snapshot_id,
            label_snapshot_id=label_result.snapshot.metadata.snapshot_id,
        )
        return DerivedArtifacts(
            identity=identity_result.snapshot.metadata,
            clean=cleaning_result.snapshot.metadata,
            label=label_result.snapshot.metadata,
            calendar=calendar_result.snapshot,
            xu100_raw=xu100_result.raw_snapshot,
            xu100_validated=xu100_result.validated_snapshot,
            feature=feature_result.snapshot,
            identity_frame=identity,
            clean_frame=clean,
            label_frame=labels,
            calendar_frame=calendar,
            xu100_frame=xu100,
            feature_frame=features,
            feature_quality=feature_result.quality_summary,
            prediction=prediction,
            training=training,
        )

    def run(
        self,
        *,
        refresh: bool = False,
        run_started_at_utc: str | None = None,
    ) -> FullHistoryRunResult:
        """Execute preflight, resumable collection, derived reports and feasibility."""

        started = run_started_at_utc or _utc_now()
        preflight = self.preflight()
        outcomes, status, summary = self.collect_manifest(
            preflight,
            refresh=refresh,
            run_started_at_utc=started,
        )
        complete_ids = tuple(
            sorted(
                status.loc[status["collection_complete"].eq(True), "security_id"].astype(str)
            )
        )
        master_ids = set(preflight.universe["security_id"].astype(str))
        excluded_ids = tuple(sorted(master_ids.difference(complete_ids)))
        derived: DerivedArtifacts | None = None
        derived_error: Exception | None = None
        if complete_ids:
            try:
                derived = self.run_derived(
                    preflight, outcomes, complete_ids, refresh=refresh
                )
            except Exception as exc:
                derived_error = exc

        if derived is not None:
            status = enrich_collection_status(status, outcomes, derived)
            run_status = (
                "COMPLETE"
                if len(complete_ids) == self.context.master_security_count
                else "PARTIAL"
            )
            reports = self._write_derived_reports(preflight, outcomes, status, derived)
        else:
            run_status = "PARTIAL" if complete_ids else "FAILED"
            if derived_error is not None:
                status = status.copy()
                affected = status["security_id"].isin(complete_ids)
                status.loc[affected, "failure_stage"] = "DERIVED_CHAIN"
                status.loc[affected, "failure_class"] = type(derived_error).__name__
                status.loc[affected, "failure_reason"] = sanitize_error(derived_error)
                status.loc[affected, "mapping_review_required"] = True
            reports = self._write_partial_reports(preflight, outcomes, status)

        summary = build_collection_summary(status)
        provenance = self._run_provenance(
            preflight,
            status,
            summary,
            run_status=run_status,
            run_started_at_utc=started,
            used_security_ids=complete_ids,
            excluded_security_ids=excluded_ids,
            snapshots=derived.snapshot_metadata if derived is not None else (),
        )
        if derived_error is not None:
            provenance["derived_failure"] = {
                "failure_class": type(derived_error).__name__,
                "failure_reason": sanitize_error(derived_error),
            }
        self._write_collection_checkpoint(status, summary, provenance)
        return FullHistoryRunResult(
            run_status=run_status,
            preflight=preflight,
            outcomes=tuple(outcomes),
            status=status,
            summary=summary,
            used_security_ids=complete_ids,
            excluded_security_ids=excluded_ids,
            derived=derived,
            reports=reports,
        )

    def _write_derived_reports(
        self,
        preflight: FullHistoryPreflight,
        outcomes: Sequence[ManifestOutcome],
        status: pd.DataFrame,
        derived: DerivedArtifacts,
    ) -> dict[str, Path]:
        root = self.paths.report_root
        mapping_review = build_mapping_review(status, outcomes, derived.calendar_frame)
        quality_summary, quality_by_security, class_distribution = build_quality_reports(
            preflight, status, derived
        )
        prediction_daily, prediction_exclusions = build_prediction_reports(
            derived.prediction
        )
        paths = {
            "ticker_mapping_review": root / "ticker_mapping_review.csv",
            "data_quality_summary": root / "data_quality_summary.json",
            "data_quality_by_security": root / "data_quality_by_security.csv",
            "feature_quality": root / "feature_quality.csv",
            "class_distribution": root / "class_distribution.json",
            "prediction_universe_daily": root / "prediction_universe_daily.csv",
            "prediction_universe_exclusions": root / "prediction_universe_exclusions.csv",
        }
        atomic_write_csv(paths["ticker_mapping_review"], mapping_review)
        atomic_write_json(paths["data_quality_summary"], quality_summary)
        atomic_write_csv(paths["data_quality_by_security"], quality_by_security)
        atomic_write_csv(paths["feature_quality"], derived.feature_quality)
        atomic_write_json(paths["class_distribution"], class_distribution)
        atomic_write_csv(paths["prediction_universe_daily"], prediction_daily)
        atomic_write_csv(paths["prediction_universe_exclusions"], prediction_exclusions)

        from src.modeling.fold_feasibility import write_fold_feasibility_reports

        feasibility_paths = write_fold_feasibility_reports(
            derived.training.panel,
            derived.calendar_frame,
            report_root=root,
            as_of_date=self.context.collection_end_date,
            config=self.config.training,
        )
        paths.update(feasibility_paths)
        return paths

    def _write_partial_reports(
        self,
        preflight: FullHistoryPreflight,
        outcomes: Sequence[ManifestOutcome],
        status: pd.DataFrame,
    ) -> dict[str, Path]:
        root = self.paths.report_root
        mapping_path = root / "ticker_mapping_review.csv"
        quality_summary_path = root / "data_quality_summary.json"
        quality_by_security_path = root / "data_quality_by_security.csv"
        feature_quality_path = root / "feature_quality.csv"
        class_distribution_path = root / "class_distribution.json"
        prediction_daily_path = root / "prediction_universe_daily.csv"
        prediction_exclusions_path = root / "prediction_universe_exclusions.csv"
        atomic_write_csv(mapping_path, build_mapping_review(status, outcomes, None))
        atomic_write_json(
            quality_summary_path,
            {
                "run_status": "PARTIAL",
                "derived_chain_available": False,
                "master_security_count": self.context.master_security_count,
                "complete_security_count": int(status["collection_complete"].sum()),
            },
        )
        atomic_write_csv(
            quality_by_security_path,
            status.loc[
                :,
                [
                    "security_id",
                    "current_ticker",
                    "observed_session_count",
                    "missing_session_count",
                    "longest_internal_gap_sessions",
                    "collection_complete",
                ],
            ],
        )
        atomic_write_csv(
            feature_quality_path,
            pd.DataFrame(columns=["feature_name", "status", "reason"]),
        )
        atomic_write_json(
            class_distribution_path,
            {"positive_label_count": 0, "negative_label_count": 0, "na_label_count": 0},
        )
        atomic_write_csv(
            prediction_daily_path, pd.DataFrame(columns=PREDICTION_DAILY_COLUMNS)
        )
        atomic_write_csv(
            prediction_exclusions_path,
            pd.DataFrame(columns=["prediction_date", "exclusion_reason", "count"]),
        )
        return {
            "ticker_mapping_review": mapping_path,
            "data_quality_summary": quality_summary_path,
            "data_quality_by_security": quality_by_security_path,
            "feature_quality": feature_quality_path,
            "class_distribution": class_distribution_path,
            "prediction_universe_daily": prediction_daily_path,
            "prediction_universe_exclusions": prediction_exclusions_path,
        }


def build_collection_status(
    preflight: FullHistoryPreflight,
    outcomes: Sequence[ManifestOutcome],
) -> pd.DataFrame:
    """Aggregate deterministic per-manifest outcomes to one row per master security."""

    outcome_by_security: dict[str, list[ManifestOutcome]] = {}
    for item in outcomes:
        outcome_by_security.setdefault(item.security_id, []).append(item)
    manifest_by_security = {
        str(key): group.sort_values(["period_start", "provider_ticker"])
        for key, group in preflight.manifest.groupby("security_id", sort=True)
    }
    current_by_security = preflight.universe.set_index("security_id")["current_ticker"]
    rows: list[dict[str, Any]] = []
    for security_id in sorted(map(str, preflight.universe["security_id"])):
        planned = manifest_by_security[security_id]
        completed = sorted(
            outcome_by_security.get(security_id, []), key=lambda item: item.row_number
        )
        is_status = _aggregate_provider_status(
            [item.isyatirim_status for item in completed], len(planned)
        )
        yf_status = _aggregate_provider_status(
            [item.yfinance_status for item in completed], len(planned)
        )
        dates = sorted(
            {
                value
                for item in completed
                for value in (*item.isyatirim_dates, *item.yfinance_dates)
            }
        )
        raw_ids = sorted(
            {
                value
                for item in completed
                for value in (
                    item.isyatirim_raw_snapshot_id,
                    item.yfinance_raw_snapshot_id,
                )
                if value
            }
        )
        nominal_ids = sorted(
            {item.nominal_snapshot_id for item in completed if item.nominal_snapshot_id}
        )
        failures = [item for item in completed if item.failure_reason]
        failure = failures[-1] if failures else None
        is_complete = len(completed) == len(planned) and all(
            item.complete for item in completed
        )
        provider_mismatch = any(
            set(item.isyatirim_dates) != set(item.yfinance_dates)
            for item in completed
            if item.isyatirim_dates or item.yfinance_dates
        )
        rows.append(
            {
                "security_id": security_id,
                "current_ticker": str(current_by_security.loc[security_id]),
                "provider_tickers_queried": "|".join(
                    item.provider_ticker for item in completed
                ),
                "requested_start_date": str(planned["period_start"].min()),
                "requested_end_date": str(planned["period_end"].max()),
                "isyatirim_status": is_status,
                "yfinance_status": yf_status,
                "raw_snapshot_ids": "|".join(raw_ids),
                "nominal_snapshot_id": "|".join(nominal_ids),
                "identity_snapshot_id": "",
                "clean_snapshot_id": "",
                "label_snapshot_id": "",
                "first_observed_date": dates[0] if dates else "",
                "last_observed_date": dates[-1] if dates else "",
                "observed_session_count": len(dates),
                "missing_session_count": pd.NA,
                "longest_internal_gap_sessions": pd.NA,
                "collection_complete": bool(is_complete),
                "failure_stage": failure.failure_stage if failure else "",
                "failure_class": failure.failure_class if failure else "",
                "failure_reason": failure.failure_reason if failure else "",
                "mapping_review_required": bool(failure or provider_mismatch),
            }
        )
    return pd.DataFrame(rows, columns=COLLECTION_STATUS_COLUMNS)


def build_collection_summary(status: pd.DataFrame) -> dict[str, Any]:
    attempted = ~(
        status["isyatirim_status"].eq("PENDING")
        & status["yfinance_status"].eq("PENDING")
    )
    complete = status["collection_complete"].eq(True)
    no_history = (
        attempted
        & ~complete
        & pd.to_numeric(status["observed_session_count"], errors="coerce").fillna(0).eq(0)
        & status["failure_reason"].astype(str).str.contains(
            r"(?i)(?:no rows|no history|not found|delisted|symbol)", regex=True
        )
    )
    any_success = status["isyatirim_status"].eq("COMPLETE") | status[
        "yfinance_status"
    ].eq("COMPLETE")
    partial = attempted & ~complete & ~no_history & any_success
    failed = attempted & ~complete & ~no_history & ~partial
    denominator = max(int(attempted.sum()), 1)
    return {
        "master_security_count": int(len(status)),
        "collection_attempted_count": int(attempted.sum()),
        "complete_security_count": int(complete.sum()),
        "partial_security_count": int(partial.sum()),
        "failed_security_count": int(failed.sum()),
        "no_history_security_count": int(no_history.sum()),
        "isyatirim_success_rate": float(
            (status.loc[attempted, "isyatirim_status"].eq("COMPLETE").sum()) / denominator
        ),
        "yfinance_success_rate": float(
            (status.loc[attempted, "yfinance_status"].eq("COMPLETE").sum()) / denominator
        ),
        "identity_success_rate": float(
            status.loc[attempted, "identity_snapshot_id"].astype(str).ne("").sum()
            / denominator
        ),
        "clean_success_rate": float(
            status.loc[attempted, "clean_snapshot_id"].astype(str).ne("").sum()
            / denominator
        ),
        "label_success_rate": float(
            status.loc[attempted, "label_snapshot_id"].astype(str).ne("").sum()
            / denominator
        ),
    }


def enrich_collection_status(
    status: pd.DataFrame,
    outcomes: Sequence[ManifestOutcome],
    derived: DerivedArtifacts,
) -> pd.DataFrame:
    result = status.copy()
    calendar_dates = tuple(
        pd.to_datetime(derived.calendar_frame["session_date"], errors="raise")
        .dt.normalize()
        .sort_values()
    )
    by_security: dict[str, set[pd.Timestamp]] = {}
    for item in outcomes:
        if not item.complete:
            continue
        by_security.setdefault(item.security_id, set()).update(
            pd.Timestamp(value).normalize() for value in item.yfinance_dates
        )
    used = set(derived.identity_frame["security_id"].astype(str))
    for index, row in result.iterrows():
        security_id = str(row["security_id"])
        observed = by_security.get(security_id, set())
        if observed:
            result.at[index, "first_observed_date"] = min(observed).date().isoformat()
            result.at[index, "last_observed_date"] = max(observed).date().isoformat()
        result.at[index, "observed_session_count"] = len(observed)
        result.at[index, "missing_session_count"] = len(
            set(calendar_dates).difference(observed)
        )
        _, longest = _internal_gap_dates(observed, calendar_dates)
        result.at[index, "longest_internal_gap_sessions"] = longest
        if security_id in used:
            result.at[index, "identity_snapshot_id"] = derived.identity.snapshot_id
            result.at[index, "clean_snapshot_id"] = derived.clean.snapshot_id
            result.at[index, "label_snapshot_id"] = derived.label.snapshot_id
        late = bool(observed and min(observed) > min(calendar_dates))
        early = bool(observed and max(observed) < max(calendar_dates))
        result.at[index, "mapping_review_required"] = bool(
            row["mapping_review_required"] or late or early or longest > 0
        )
    return result.loc[:, COLLECTION_STATUS_COLUMNS]


def build_mapping_review(
    status: pd.DataFrame,
    outcomes: Sequence[ManifestOutcome],
    calendar: pd.DataFrame | None,
) -> pd.DataFrame:
    calendar_dates: tuple[pd.Timestamp, ...] = ()
    if calendar is not None and not calendar.empty:
        calendar_dates = tuple(
            pd.to_datetime(calendar["session_date"], errors="raise")
            .dt.normalize()
            .sort_values()
        )
    outcomes_by_security: dict[str, list[ManifestOutcome]] = {}
    for item in outcomes:
        outcomes_by_security.setdefault(item.security_id, []).append(item)
    rows: list[dict[str, Any]] = []
    for record in status.sort_values("security_id").to_dict(orient="records"):
        security_id = str(record["security_id"])
        items = outcomes_by_security.get(security_id, [])
        is_dates = {
            pd.Timestamp(value).normalize() for item in items for value in item.isyatirim_dates
        }
        yf_dates = {
            pd.Timestamp(value).normalize() for item in items for value in item.yfinance_dates
        }
        observed = is_dates | yf_dates
        evidence = json.dumps(
            {
                "isyatirim_first": _date_text(min(is_dates) if is_dates else None),
                "isyatirim_last": _date_text(max(is_dates) if is_dates else None),
                "isyatirim_sessions": len(is_dates),
                "yfinance_first": _date_text(min(yf_dates) if yf_dates else None),
                "yfinance_last": _date_text(max(yf_dates) if yf_dates else None),
                "yfinance_sessions": len(yf_dates),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        def add(issue: str, gaps: Iterable[pd.Timestamp] = ()) -> None:
            gap_values = tuple(gaps)
            rows.append(
                {
                    "security_id": security_id,
                    "current_ticker": record["current_ticker"],
                    "issue_type": issue,
                    "first_observed_date": record["first_observed_date"],
                    "last_observed_date": record["last_observed_date"],
                    "gap_dates": "|".join(_date_text(value) for value in gap_values),
                    "gap_session_count": len(gap_values),
                    "longest_internal_gap_sessions": (
                        record["longest_internal_gap_sessions"]
                        if issue == "INTERNAL_SESSION_GAP"
                        else 0
                    ),
                    "provider_evidence": evidence,
                    "possible_historical_ticker": "",
                    "official_evidence_status": "OFFICIAL_EVIDENCE_REQUIRED",
                    "recommended_action": (
                        "Review official KAP/Borsa İstanbul ticker-transition evidence; "
                        "do not infer or apply an alias automatically."
                    ),
                }
            )

        if not observed and items:
            add("NO_HISTORY_BOTH_PROVIDERS")
        if calendar_dates and observed:
            if min(observed) > min(calendar_dates):
                add("LATE_SERIES_START")
            if max(observed) < max(calendar_dates):
                add("EARLY_SERIES_END")
            gap_dates, _ = _internal_gap_dates(yf_dates or observed, calendar_dates)
            if gap_dates:
                add("INTERNAL_SESSION_GAP", gap_dates)
        if is_dates != yf_dates and (is_dates or yf_dates):
            add("PROVIDER_DATE_COVERAGE_MISMATCH")
        messages = " ".join(item.failure_reason for item in items)
        if re.search(r"(?i)(not found|delisted|redirect|symbol)", messages):
            add("PROVIDER_SYMBOL_OR_REDIRECT")
        if any(
            issue in {row["issue_type"] for row in rows if row["security_id"] == security_id}
            for issue in ("LATE_SERIES_START", "EARLY_SERIES_END", "INTERNAL_SESSION_GAP")
        ):
            add("POSSIBLE_OLD_OR_NEW_TICKER_SIGNAL")
    return pd.DataFrame(rows, columns=MAPPING_REVIEW_COLUMNS).sort_values(
        ["issue_type", "longest_internal_gap_sessions", "security_id", "gap_dates"],
        ascending=[True, False, True, True],
        ignore_index=True,
    )


def build_quality_reports(
    preflight: FullHistoryPreflight,
    status: pd.DataFrame,
    derived: DerivedArtifacts,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    identity = derived.identity_frame.copy()
    identity["date"] = pd.to_datetime(identity["date"], errors="raise").dt.normalize()
    clean = derived.clean_frame.copy()
    labels = derived.label_frame.copy()
    features = derived.feature_frame.copy()
    observations = derived.prediction.observations.copy()
    calendar = derived.calendar_frame.copy()

    nominal_columns = [
        "yf_nominal_open",
        "yf_nominal_high",
        "yf_nominal_low",
        "yf_nominal_close",
    ]
    nominal = identity.loc[:, nominal_columns].apply(pd.to_numeric, errors="coerce")
    invalid_ohlc = (
        nominal.isna().any(axis=1)
        | ~np.isfinite(nominal.to_numpy(dtype="float64")).all(axis=1)
        | nominal.le(0).any(axis=1)
        | nominal["yf_nominal_high"].lt(
            nominal[["yf_nominal_open", "yf_nominal_close"]].max(axis=1)
        )
        | nominal["yf_nominal_low"].gt(
            nominal[["yf_nominal_open", "yf_nominal_close"]].min(axis=1)
        )
        | nominal["yf_nominal_high"].lt(nominal["yf_nominal_low"])
    )
    both_volume_missing_or_zero = (
        pd.to_numeric(observations["is_tl_volume"], errors="coerce").fillna(0).le(0)
        & pd.to_numeric(observations["yf_share_volume"], errors="coerce").fillna(0).le(0)
    )
    feature_numeric = features.loc[:, BASELINE_V1_FEATURES].apply(
        pd.to_numeric, errors="coerce"
    )
    duplicate_identity = int(identity.duplicated(["security_id", "date"]).sum())
    duplicate_ticker_date = int(identity.duplicated(["observed_ticker", "date"]).sum())
    duplicate_features = int(features.duplicated(["security_id", "prediction_date"]).sum())
    if duplicate_identity or duplicate_features:
        raise FullHistoryError("duplicate identity or feature key in quality reporting")

    security_rows: list[dict[str, Any]] = []
    total_sessions = max(len(calendar), 1)
    clean_security = clean.groupby("security_id", sort=True) if "security_id" in clean else None
    label_security = labels.groupby("security_id", sort=True) if "security_id" in labels else None
    observation_security = observations.groupby("security_id", sort=True)
    identity_security = identity.groupby("security_id", sort=True)
    status_index = status.set_index("security_id")
    for security_id in sorted(map(str, preflight.universe["security_id"])):
        identity_part = (
            identity_security.get_group(security_id)
            if security_id in identity_security.groups
            else identity.iloc[0:0]
        )
        observation_part = (
            observation_security.get_group(security_id)
            if security_id in observation_security.groups
            else observations.iloc[0:0]
        )
        clean_part = (
            clean_security.get_group(security_id)
            if clean_security is not None and security_id in clean_security.groups
            else clean.iloc[0:0]
        )
        label_part = (
            label_security.get_group(security_id)
            if label_security is not None and security_id in label_security.groups
            else labels.iloc[0:0]
        )
        identity_indices = identity_part.index
        observation_indices = observation_part.index
        security_rows.append(
            {
                "security_id": security_id,
                "current_ticker": status_index.loc[security_id, "current_ticker"],
                "observed_session_count": int(len(identity_part)),
                "observed_session_ratio": float(len(identity_part) / total_sessions),
                "missing_session_count": status_index.loc[security_id, "missing_session_count"],
                "longest_internal_gap_sessions": status_index.loc[
                    security_id, "longest_internal_gap_sessions"
                ],
                "invalid_or_missing_ohlc_count": int(invalid_ohlc.loc[identity_indices].sum()),
                "non_positive_price_count": int(nominal.loc[identity_indices].le(0).any(axis=1).sum()),
                "both_volumes_missing_or_zero_count": int(
                    both_volume_missing_or_zero.loc[observation_indices].sum()
                ),
                "cross_source_warning_count": int(
                    clean_part.get("cross_source_price_warning", pd.Series(dtype=bool))
                    .eq(True)
                    .sum()
                ),
                "entry_eligible_count": int(
                    clean_part.get("entry_eligible", pd.Series(dtype=bool)).eq(True).sum()
                ),
                "requires_review_count": int(
                    clean_part.get("requires_review", pd.Series(dtype=bool)).eq(True).sum()
                ),
                "positive_label_count": int(label_part.get("label", pd.Series(dtype=float)).eq(1).sum()),
                "negative_label_count": int(label_part.get("label", pd.Series(dtype=float)).eq(0).sum()),
                "na_label_count": int(label_part.get("label_status", pd.Series(dtype=str)).ne("LABELED").sum()),
                "collection_complete": bool(status_index.loc[security_id, "collection_complete"]),
            }
        )
    by_security = pd.DataFrame(security_rows).sort_values("security_id").reset_index(drop=True)
    label_summary = summarize_labels(labels)
    clean_summary = summarize_cleaning(clean)
    labeled = labels.loc[labels["label_status"].eq("LABELED"), "label"]
    class_distribution = {
        "positive_label_count": int(labeled.eq(1).sum()),
        "negative_label_count": int(labeled.eq(0).sum()),
        "na_label_count": int(labels["label_status"].ne("LABELED").sum()),
        "positive_class_rate": (
            float(labeled.eq(1).mean()) if len(labeled) else None
        ),
        "label_status_distribution": {
            str(key): int(value)
            for key, value in labels["label_status"].astype(str).value_counts().sort_index().items()
        },
    }
    cross_features = [name for name in BASELINE_V1_FEATURES if name.startswith("cs_")]
    cross_dates = features.groupby("prediction_date")[cross_features].apply(
        lambda frame: bool(frame.notna().any().all())
    )
    valid_daily = feature_numeric.notna().all(axis=1).groupby(
        features["prediction_date"]
    ).sum()
    calendar_dates = set(pd.to_datetime(calendar["session_date"]).dt.normalize())
    xu_dates = set(pd.to_datetime(derived.xu100_frame["prediction_date"]).dt.normalize())
    quality_summary = {
        "master_security_count": int(len(preflight.universe)),
        "derived_security_count": int(identity["security_id"].nunique()),
        "master_securities_without_data": sorted(
            set(preflight.universe["security_id"].astype(str)).difference(
                identity["security_id"].astype(str)
            )
        ),
        "duplicate_security_date_count": duplicate_identity,
        "duplicate_ticker_date_count": duplicate_ticker_date,
        "mapping_status_distribution": {
            str(key): int(value)
            for key, value in identity["ticker_mapping_status"]
            .astype(str)
            .value_counts()
            .sort_index()
            .items()
        },
        "global_calendar_session_count": int(len(calendar)),
        "invalid_or_missing_ohlc_count": int(invalid_ohlc.sum()),
        "non_positive_price_row_count": int(nominal.le(0).any(axis=1).sum()),
        "both_volumes_missing_or_zero_count": int(both_volume_missing_or_zero.sum()),
        "nominal_transformation_issue_count": int(invalid_ohlc.sum()),
        "cleaning_summary": clean_summary,
        "label_summary": label_summary,
        "feature_count": len(BASELINE_V1_FEATURES),
        "feature_names": list(BASELINE_V1_FEATURES),
        "duplicate_feature_key_count": duplicate_features,
        "infinite_feature_value_count": int(
            np.isinf(feature_numeric.to_numpy(dtype="float64")).sum()
        ),
        "feature_nan_count": int(feature_numeric.isna().sum().sum()),
        "cross_sectional_rank_date_count": int(cross_dates.sum()),
        "daily_valid_feature_value_count": {
            "min": int(valid_daily.min()) if len(valid_daily) else 0,
            "median": float(valid_daily.median()) if len(valid_daily) else 0.0,
            "max": int(valid_daily.max()) if len(valid_daily) else 0,
        },
        "xu100_calendar_match_ratio": float(
            len(calendar_dates.intersection(xu_dates)) / max(len(calendar_dates), 1)
        ),
    }
    return quality_summary, by_security, class_distribution


def build_prediction_reports(
    prediction: PredictionUniverseAssembly,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    universe = prediction.universe.copy()
    observations = prediction.observations.copy()
    features = prediction.features.copy()
    observed_counts = observations.groupby("prediction_date")["security_id"].nunique()
    feature_counts = features.groupby("prediction_date")["security_id"].nunique()
    daily = universe.groupby("prediction_date", sort=True).agg(
        master_universe_count=("security_id", "nunique"),
        prediction_eligible_count=("prediction_eligible", "sum"),
    )
    daily["observed_security_count"] = daily.index.map(observed_counts).fillna(0).astype(int)
    daily["feature_row_count"] = daily.index.map(feature_counts).fillna(0).astype(int)
    daily["prediction_excluded_count"] = (
        daily["master_universe_count"] - daily["prediction_eligible_count"]
    )
    daily = daily.reset_index().loc[:, PREDICTION_DAILY_COLUMNS]
    daily["prediction_date"] = pd.to_datetime(daily["prediction_date"]).dt.date.astype(str)

    reasons = [
        "INSUFFICIENT_HISTORY",
        "NO_T_OBSERVATION",
        "INVALID_T_OHLC",
        "NO_TRADE_ON_T",
        "MISSING_TRADE_EVIDENCE",
        "MISSING_FEATURE_ROW",
        "MISSING_XU100_SESSION",
    ]
    exclusions = (
        universe.loc[universe["prediction_exclusion_reason"].isin(reasons)]
        .groupby(["prediction_date", "prediction_exclusion_reason"], sort=True)
        .size()
        .rename("count")
        .reset_index()
        .rename(columns={"prediction_exclusion_reason": "exclusion_reason"})
    )
    complete_index = pd.MultiIndex.from_product(
        [sorted(universe["prediction_date"].unique()), reasons],
        names=["prediction_date", "exclusion_reason"],
    )
    exclusions = (
        exclusions.set_index(["prediction_date", "exclusion_reason"])
        .reindex(complete_index, fill_value=0)
        .reset_index()
    )
    exclusions["prediction_date"] = pd.to_datetime(
        exclusions["prediction_date"]
    ).dt.date.astype(str)
    return daily, exclusions


def _aggregate_provider_status(values: Sequence[str], expected_count: int) -> str:
    if not values:
        return "PENDING"
    if len(values) == expected_count and all(value == "COMPLETE" for value in values):
        return "COMPLETE"
    if any(value == "COMPLETE" for value in values):
        return "PARTIAL"
    if any(value == "PARTIAL" for value in values):
        return "PARTIAL"
    return "FAILED"


def _internal_gap_dates(
    observed: set[pd.Timestamp], calendar_dates: Sequence[pd.Timestamp]
) -> tuple[tuple[pd.Timestamp, ...], int]:
    if not observed or not calendar_dates:
        return (), 0
    lower, upper = min(observed), max(observed)
    internal = [value for value in calendar_dates if lower <= value <= upper]
    missing = tuple(value for value in internal if value not in observed)
    longest = 0
    current = 0
    missing_set = set(missing)
    for value in internal:
        if value in missing_set:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return missing, longest


def _date_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if value is pd.NA:
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
