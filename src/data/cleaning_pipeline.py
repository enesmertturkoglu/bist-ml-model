"""Verified-snapshot orchestration for D022/D023 cleaning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from src.config import MarketDataConfig
from src.data.cleaning import (
    NOMINAL_OHLC_COLUMNS,
    build_clean_eligibility_frame,
    extract_yfinance_auxiliary,
    mark_adjustment_factor_changes,
    normalize_isyatirim_history,
    summarize_cleaning,
)
from src.data.price_limits import PriceStepTable
from src.data.security_identity import (
    IDENTITY_COLUMNS,
    TickerMapping,
    deduplicate_security_history,
    enrich_security_identity,
)
from src.data.snapshot_store import (
    SnapshotMetadata,
    SnapshotRequest,
    SnapshotStore,
    SnapshotWriteResult,
)


class CleaningInputError(ValueError):
    """Raised when source snapshot provenance cannot be trusted."""


@dataclass(frozen=True)
class CleaningSnapshotSet:
    ticker: str
    isyatirim_raw_snapshot_id: str
    yfinance_raw_snapshot_id: str
    yfinance_nominal_snapshot_id: str

    @property
    def input_snapshot_ids(self) -> tuple[str, str, str]:
        return (
            self.isyatirim_raw_snapshot_id,
            self.yfinance_raw_snapshot_id,
            self.yfinance_nominal_snapshot_id,
        )


@dataclass(frozen=True)
class CleaningRunResult:
    snapshot: SnapshotWriteResult
    frame: pd.DataFrame
    summary: dict[str, Any]
    exception_examples: pd.DataFrame


@dataclass(frozen=True)
class _VerifiedInputs:
    definition: CleaningSnapshotSet
    isyatirim: SnapshotMetadata
    yfinance_raw: SnapshotMetadata
    yfinance_nominal: SnapshotMetadata

    @property
    def metadata(self) -> tuple[SnapshotMetadata, SnapshotMetadata, SnapshotMetadata]:
        return (self.isyatirim, self.yfinance_raw, self.yfinance_nominal)


class MarketDataCleaningPipeline:
    """Load only verified COMPLETE inputs and persist an auditable clean snapshot."""

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        code_commit_sha: str = "unknown",
    ) -> None:
        self.config = config or MarketDataConfig()
        self.snapshot_store = snapshot_store or SnapshotStore(self.config)
        self.code_commit_sha = code_commit_sha or "unknown"

    def run(
        self,
        snapshot_sets: Sequence[CleaningSnapshotSet],
        price_steps: PriceStepTable,
        *,
        exception_limit: int = 20,
        security_identity_snapshot_id: str | None = None,
        ticker_mapping: TickerMapping | None = None,
    ) -> CleaningRunResult:
        if not snapshot_sets:
            raise CleaningInputError("at least one cleaning snapshot set is required")
        verified = [self._verify_inputs(value) for value in snapshot_sets]
        identity_metadata = self._verify_identity_snapshot(
            security_identity_snapshot_id,
            verified,
            ticker_mapping,
        )
        self._validate_batch(
            verified,
            allow_mixed_periods=identity_metadata is not None,
        )
        identity_frame = (
            self.snapshot_store.read_dataframe(identity_metadata)
            if identity_metadata is not None
            else None
        )

        daily_frames: list[pd.DataFrame] = []
        calendar_dates: set[pd.Timestamp] = set()
        provenance: dict[str, tuple[list[str], list[str]]] = {}
        for inputs in verified:
            ticker = inputs.definition.ticker.strip().upper()
            is_raw = self.snapshot_store.read_dataframe(inputs.isyatirim)
            yf_raw = self.snapshot_store.read_dataframe(inputs.yfinance_raw)
            if identity_frame is None:
                nominal = self.snapshot_store.read_dataframe(inputs.yfinance_nominal)
            else:
                nominal = identity_frame.loc[
                    identity_frame["observed_ticker"].eq(ticker)
                ].copy()

            is_frame = normalize_isyatirim_history(is_raw, ticker)
            is_frame = mark_adjustment_factor_changes(
                is_frame,
                rtol=self.config.cleaning.adjustment_factor_relative_tolerance,
                atol=self.config.cleaning.adjustment_factor_absolute_tolerance,
            )
            calendar_dates.update(pd.to_datetime(is_frame["date"]).dt.normalize())
            auxiliary = extract_yfinance_auxiliary(yf_raw, ticker)
            nominal = self._prepare_nominal(nominal, ticker)
            daily = is_frame.merge(
                nominal,
                on=["ticker", "date"],
                how="outer",
                validate="one_to_one",
            ).merge(
                auxiliary,
                on=["ticker", "date"],
                how="outer",
                validate="one_to_one",
            )
            if ticker_mapping is not None:
                daily = enrich_security_identity(daily, ticker_mapping)
            daily_frames.append(daily)
            provenance[ticker] = (
                [item.snapshot_id for item in inputs.metadata],
                [item.content_checksum for item in inputs.metadata],
            )

        calendar = pd.DatetimeIndex(sorted(calendar_dates))
        daily_all = pd.concat(daily_frames, ignore_index=True, sort=False)
        if identity_metadata is not None:
            daily_all = deduplicate_security_history(daily_all)
        daily_all = daily_all[daily_all["date"].isin(calendar)].reset_index(drop=True)
        cleaned = build_clean_eligibility_frame(
            daily_all,
            calendar,
            price_steps,
            config=self.config.cleaning,
        )
        if cleaned.empty:
            raise CleaningInputError(
                "verified inputs do not contain a complete T+1..T+3 BIST-calendar window"
            )
        cleaned["input_snapshot_ids"] = cleaned["ticker"].map(
            lambda ticker: provenance[str(ticker)][0]
        )
        cleaned["input_snapshot_checksums"] = cleaned["ticker"].map(
            lambda ticker: provenance[str(ticker)][1]
        )
        cleaned["cleaning_config_checksum"] = self.config.cleaning.checksum(
            self.config.checksum_algorithm
        )
        cleaned["cleaning_code_commit_sha"] = self.code_commit_sha
        cleaned["cleaning_version"] = self.config.cleaning.cleaning_version
        self._guard_clean_schema(cleaned)

        all_metadata = [item for inputs in verified for item in inputs.metadata]
        if identity_metadata is not None:
            all_metadata.append(identity_metadata)
        input_ids = tuple(item.snapshot_id for item in all_metadata)
        input_checksums = tuple(item.content_checksum for item in all_metadata)
        input_checksum_by_id = {
            item.snapshot_id: item.content_checksum for item in all_metadata
        }
        tickers = sorted(value.definition.ticker.strip().upper() for value in verified)
        start = min(value.isyatirim.request_start_date for value in verified)
        end = max(value.isyatirim.request_end_date for value in verified)
        request_identity = (
            sorted(map(str, cleaned["security_id"].unique()))
            if "security_id" in cleaned
            else tickers
        )
        identity_parameters = {}
        if identity_metadata is not None:
            identity_parameters = {
                "security_identity_snapshot_id": identity_metadata.snapshot_id,
                "ticker_mapping_version": identity_metadata.request_parameters[
                    "ticker_mapping_version"
                ],
                "ticker_mapping_checksum": identity_metadata.request_parameters[
                    "ticker_mapping_checksum"
                ],
            }
        cleaning_config_checksum = self.config.cleaning.checksum(
            self.config.checksum_algorithm
        )
        price_step_table_checksum = price_steps.checksum(
            self.config.checksum_algorithm
        )
        request = SnapshotRequest(
            source="cleaning",
            dataset_type=self.config.cleaning.clean_dataset_type,
            ticker_or_instrument=(
                request_identity[0] if len(request_identity) == 1 else "BIST_BATCH"
            ),
            request_start_date=start,
            request_end_date=end,
            request_parameters={
                "cleaning_version": self.config.cleaning.cleaning_version,
                "cleaning_config_checksum": cleaning_config_checksum,
                "price_step_table_checksum": price_step_table_checksum,
                "tick_rule_set_ids": list(price_steps.rule_set_ids),
                "official_source_documents": list(
                    price_steps.official_source_documents
                ),
                "tickers": tickers,
                "input_snapshot_ids": list(input_ids),
                "input_snapshot_checksums": list(input_checksums),
                **identity_parameters,
            },
            provider_library_version="derived-cleaning-v2",
            code_commit_sha=self.code_commit_sha,
            layer="derived",
            input_snapshot_ids=input_ids,
            identity_columns=(
                ("security_id", "prediction_date")
                if identity_metadata is not None
                else ("ticker", "prediction_date")
            ),
            revision_context={
                "input_snapshot_ids": list(input_ids),
                "input_content_checksums": input_checksum_by_id,
                "cleaning_config_checksum": cleaning_config_checksum,
                "price_step_table_checksum": price_step_table_checksum,
                "code_commit_sha": self.code_commit_sha,
                **identity_parameters,
            },
        )
        written = self.snapshot_store.save_dataframe(cleaned, request)
        summary = summarize_cleaning(cleaned)
        exceptions = cleaned[
            cleaned["entry_eligible"].ne(True).fillna(True)
            | cleaned["requires_review"].fillna(False)
            | cleaned["cross_source_price_warning"].eq(True).fillna(False)
        ].head(max(0, exception_limit))
        return CleaningRunResult(
            snapshot=written,
            frame=cleaned,
            summary=summary,
            exception_examples=exceptions.reset_index(drop=True),
        )

    def _verify_inputs(self, value: CleaningSnapshotSet) -> _VerifiedInputs:
        ticker = value.ticker.strip().upper()
        if not ticker:
            raise CleaningInputError("snapshot-set ticker is required")
        metadata = [
            self.snapshot_store.get_snapshot(snapshot_id)
            for snapshot_id in value.input_snapshot_ids
        ]
        for item in metadata:
            if not self.snapshot_store.is_usable(item):
                raise CleaningInputError(
                    f"snapshot {item.snapshot_id} is not a verified COMPLETE snapshot"
                )
            if item.ticker_or_instrument != ticker:
                raise CleaningInputError(
                    f"snapshot {item.snapshot_id} ticker does not match {ticker}"
                )
        isyatirim, yfinance_raw, nominal = metadata
        expected = (
            (isyatirim, "isyatirim", "equity_history", "raw"),
            (yfinance_raw, "yfinance", "equity_history", "raw"),
            (nominal, "yfinance", "nominal_ohlc", "derived"),
        )
        for item, source, dataset_type, layer in expected:
            if (item.source, item.dataset_type, item.layer) != (
                source,
                dataset_type,
                layer,
            ):
                raise CleaningInputError(
                    f"snapshot {item.snapshot_id} is not {source}/{dataset_type}/{layer}"
                )
        periods = {
            (item.request_start_date, item.request_end_date) for item in metadata
        }
        if len(periods) != 1:
            raise CleaningInputError(f"source periods do not match for {ticker}")
        if nominal.input_snapshot_ids != (yfinance_raw.snapshot_id,):
            raise CleaningInputError(
                f"nominal snapshot {nominal.snapshot_id} does not exclusively reference "
                f"raw snapshot {yfinance_raw.snapshot_id}"
            )
        return _VerifiedInputs(value, isyatirim, yfinance_raw, nominal)

    def _verify_identity_snapshot(
        self,
        snapshot_id: str | None,
        values: Sequence[_VerifiedInputs],
        mapping: TickerMapping | None,
    ) -> SnapshotMetadata | None:
        if snapshot_id is None:
            if mapping is not None:
                raise CleaningInputError(
                    "ticker_mapping requires a security identity snapshot"
                )
            return None
        if mapping is None:
            raise CleaningInputError(
                "security identity snapshot requires ticker_mapping"
            )
        metadata = self.snapshot_store.get_snapshot(snapshot_id)
        if not self.snapshot_store.is_usable(metadata):
            raise CleaningInputError(
                f"security identity snapshot {snapshot_id} is not verified COMPLETE"
            )
        if (metadata.source, metadata.dataset_type, metadata.layer) != (
            "security_identity",
            "nominal_ohlc",
            "derived",
        ):
            raise CleaningInputError(
                f"snapshot {snapshot_id} is not security_identity/nominal_ohlc/derived"
            )
        nominal_ids = {
            value.yfinance_nominal.snapshot_id for value in values
        }
        if set(metadata.input_snapshot_ids) != nominal_ids:
            raise CleaningInputError(
                "security identity snapshot does not reference the supplied nominal snapshots"
            )
        parameters = metadata.request_parameters
        if parameters.get("ticker_mapping_version") != mapping.version or (
            parameters.get("ticker_mapping_checksum") != mapping.checksum
        ):
            raise CleaningInputError(
                "security identity snapshot mapping provenance does not match"
            )
        return metadata

    @staticmethod
    def _validate_batch(
        values: Sequence[_VerifiedInputs],
        *,
        allow_mixed_periods: bool = False,
    ) -> None:
        tickers = [value.definition.ticker.strip().upper() for value in values]
        if len(tickers) != len(set(tickers)):
            raise CleaningInputError("each ticker may appear only once in a cleaning batch")
        periods = {
            (value.isyatirim.request_start_date, value.isyatirim.request_end_date)
            for value in values
        }
        if len(periods) != 1 and not allow_mixed_periods:
            raise CleaningInputError("all cleaning snapshot sets must cover the same period")

    @staticmethod
    def _prepare_nominal(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
        required = {"ticker", "date", *NOMINAL_OHLC_COLUMNS}
        missing = required.difference(frame.columns)
        if missing:
            raise CleaningInputError(
                f"nominal snapshot fields missing for {ticker}: {sorted(missing)}"
            )
        identity_columns = [
            column for column in IDENTITY_COLUMNS if column in frame.columns
        ]
        result = frame[
            ["ticker", "date", *NOMINAL_OHLC_COLUMNS, *identity_columns]
        ].copy()
        result["ticker"] = result["ticker"].astype(str).str.upper()
        if not result["ticker"].eq(ticker).all():
            raise CleaningInputError(f"nominal snapshot contains another ticker for {ticker}")
        result["date"] = pd.to_datetime(result["date"]).dt.normalize()
        if result.duplicated(["ticker", "date"]).any():
            raise CleaningInputError(f"nominal snapshot has duplicate dates for {ticker}")
        return result

    @staticmethod
    def _guard_clean_schema(frame: pd.DataFrame) -> None:
        forbidden = {
            "label",
            "label_eligible",
            "target",
            "prediction",
            "yf_provider_open",
            "yf_provider_high",
            "yf_provider_low",
            "yf_provider_close",
            "yf_future_split_factor",
        }
        present = forbidden.intersection(frame.columns)
        if present:
            raise RuntimeError(
                f"clean snapshot contains forbidden label/provider fields: {sorted(present)}"
            )
