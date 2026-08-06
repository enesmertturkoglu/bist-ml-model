"""Strict projection and joining of verified feature-source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from src.data.security_identity import normalize_ticker
from src.data.snapshot_store import SnapshotMetadata, SnapshotStore


FEATURE_INPUT_COLUMNS: tuple[str, ...] = (
    "security_id",
    "prediction_date",
    "yf_provider_open",
    "yf_provider_high",
    "yf_provider_low",
    "yf_provider_close",
    "is_tl_volume",
    "validated_xu100_close",
)

FORBIDDEN_EXACT_FIELDS = {
    "entry_date",
    "entry_eligible",
    "entry_exclusion_reason",
    "entry_exclusion_reasons",
    "requires_review",
    "estimated_upper_limit",
    "raw_upper_limit",
    "tick_size",
    "price_step",
    "price_step_resolution_status",
    "is_limit_open",
    "limit_open",
    "corporate_action_window_flag",
    "corporate_action_window_dates",
    "target_price",
    "raw_target_price",
    "target_hit",
    "target_hit_date",
    "label",
    "exit_price",
    "label_status",
    "yf_future_split_factor",
    "yf_stock_splits",
    "yf_dividends",
    "yf_provider_adjusted_close",
    "yf_nominal_open",
    "yf_nominal_high",
    "yf_nominal_low",
    "yf_nominal_close",
    "ticker_mapping_status",
    "ticker_mapping_rule_id",
    "ticker_mapping_version",
    "ticker_mapping_checksum",
    "current_ticker",
}
FORBIDDEN_FIELD_FRAGMENTS = (
    "future_",
    "t_plus_1",
    "t1_",
    "snapshot_id",
    "checksum",
    "revision",
)


class FeatureInputError(RuntimeError):
    """Raised when feature inputs are incomplete, unverifiable or leakage-prone."""


@dataclass(frozen=True)
class FeatureInputAssembly:
    frame: pd.DataFrame
    benchmark: pd.DataFrame
    calendar: pd.DataFrame
    excluded_non_session_rows: pd.DataFrame
    metadata: tuple[SnapshotMetadata, ...]
    mapping_version: str
    mapping_checksum: str


def validate_feature_input_schema(
    frame: pd.DataFrame, *, allow_identifiers: bool = True
) -> None:
    """Fail closed if a projected feature-input schema includes a forbidden field."""

    identifiers = {"security_id", "prediction_date"} if allow_identifiers else set()
    forbidden: list[str] = []
    for column in map(str, frame.columns):
        normalized = column.strip().lower()
        if normalized in identifiers:
            continue
        if normalized in FORBIDDEN_EXACT_FIELDS or any(
            fragment in normalized for fragment in FORBIDDEN_FIELD_FRAGMENTS
        ):
            forbidden.append(column)
    if forbidden:
        raise FeatureInputError(f"forbidden feature input fields: {sorted(forbidden)}")


class FeatureInputAssembler:
    """Read only verified COMPLETE snapshots and emit the eight allowed fields."""

    def __init__(self, snapshot_store: SnapshotStore) -> None:
        self.snapshot_store = snapshot_store

    def assemble(
        self,
        *,
        yfinance_raw_snapshot_ids: Sequence[str],
        isyatirim_raw_snapshot_ids: Sequence[str],
        identity_snapshot_id: str,
        xu100_snapshot_id: str,
        calendar_snapshot_id: str,
    ) -> FeatureInputAssembly:
        if not yfinance_raw_snapshot_ids or not isyatirim_raw_snapshot_ids:
            raise FeatureInputError("both yFinance and İş Yatırım raw snapshots are required")
        yf_meta = self._verify_many(
            yfinance_raw_snapshot_ids, ("yfinance", "equity_history", "raw")
        )
        is_meta = self._verify_many(
            isyatirim_raw_snapshot_ids, ("isyatirim", "equity_history", "raw")
        )
        identity_meta = self._verify_one(
            identity_snapshot_id, ("security_identity", "nominal_ohlc", "derived")
        )
        xu_meta = self._verify_one(
            xu100_snapshot_id, ("benchmark", "validated_xu100_close", "derived")
        )
        calendar_meta = self._verify_one(
            calendar_snapshot_id, ("isyatirim", "global_bist_sessions", "derived")
        )

        calendar = self._project_calendar(calendar_meta)
        if calendar.empty:
            raise FeatureInputError("global calendar cannot be empty")
        yf = pd.concat([self._project_yfinance(item) for item in yf_meta], ignore_index=True)
        calendar_dates = set(calendar["session_date"])
        outside = ~yf["prediction_date"].isin(calendar_dates)
        calendar_start = calendar["session_date"].min()
        calendar_end = calendar["session_date"].max()
        outside_bounds = outside & ~yf["prediction_date"].between(
            calendar_start, calendar_end, inclusive="both"
        )
        if outside_bounds.any():
            dates = sorted(
                yf.loc[outside_bounds, "prediction_date"]
                .dt.date.astype(str)
                .unique()
                .tolist()
            )
            raise FeatureInputError(
                "provider row falls outside verified global calendar bounds: "
                f"{dates}"
            )
        excluded_non_session_rows = yf.loc[
            outside, ["observed_ticker", "prediction_date"]
        ].copy()
        excluded_non_session_rows["exclusion_reason"] = (
            "YFINANCE_NON_SESSION_WITHIN_VERIFIED_CALENDAR_BOUNDS"
        )
        excluded_non_session_rows = excluded_non_session_rows.sort_values(
            ["prediction_date", "observed_ticker"]
        ).reset_index(drop=True)
        yf = yf.loc[~outside].reset_index(drop=True)
        if yf.empty:
            raise FeatureInputError("no yFinance rows remain on verified global sessions")
        identity = self._project_identity(identity_meta)
        assembled = yf.merge(
            identity,
            left_on=["observed_ticker", "prediction_date"],
            right_on=["observed_ticker", "prediction_date"],
            how="left",
            validate="one_to_one",
        )
        if assembled["security_id"].isna().any():
            missing = assembled.loc[assembled["security_id"].isna(), "observed_ticker"].unique()
            raise FeatureInputError(
                f"identity snapshot has no date-effective security_id for: {sorted(map(str, missing))}"
            )
        volume = pd.concat(
            [self._project_isyatirim(item) for item in is_meta], ignore_index=True
        )
        if volume.duplicated(["observed_ticker", "prediction_date"]).any():
            raise FeatureInputError("duplicate İş Yatırım ticker/date volume rows")
        assembled = assembled.merge(
            volume,
            on=["observed_ticker", "prediction_date"],
            how="left",
            validate="one_to_one",
        )
        benchmark = self._project_xu100(xu_meta)
        assembled = assembled.merge(
            benchmark, on="prediction_date", how="left", validate="many_to_one"
        )
        result = assembled.loc[:, FEATURE_INPUT_COLUMNS].copy()
        if result.duplicated(["security_id", "prediction_date"]).any():
            raise FeatureInputError("duplicate security_id + prediction_date feature input")
        validate_feature_input_schema(result)
        parameters = identity_meta.request_parameters
        mapping_version = str(parameters.get("ticker_mapping_version", "unknown"))
        mapping_checksum = str(parameters.get("ticker_mapping_checksum", "unknown"))
        return FeatureInputAssembly(
            frame=result.sort_values(["security_id", "prediction_date"]).reset_index(
                drop=True
            ),
            benchmark=benchmark,
            calendar=calendar,
            excluded_non_session_rows=excluded_non_session_rows,
            metadata=tuple([*yf_meta, *is_meta, identity_meta, xu_meta, calendar_meta]),
            mapping_version=mapping_version,
            mapping_checksum=mapping_checksum,
        )

    def _verify_many(
        self, snapshot_ids: Sequence[str], expected: tuple[str, str, str]
    ) -> list[SnapshotMetadata]:
        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise FeatureInputError("snapshot IDs must be unique within each source")
        return [self._verify_one(value, expected) for value in snapshot_ids]

    def _verify_one(
        self, snapshot_id: str, expected: tuple[str, str, str]
    ) -> SnapshotMetadata:
        metadata = self.snapshot_store.get_snapshot(snapshot_id)
        if not self.snapshot_store.is_usable(metadata):
            raise FeatureInputError(f"snapshot is not verified COMPLETE: {snapshot_id}")
        actual = (metadata.source, metadata.dataset_type, metadata.layer)
        if actual != expected:
            raise FeatureInputError(
                f"snapshot {snapshot_id} has type {actual}, expected {expected}"
            )
        return metadata

    def _project_yfinance(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = {"ticker", "date", "Open", "High", "Low", "Close"}
        self._require(frame, required, metadata.snapshot_id)
        result = frame.loc[:, ["ticker", "date", "Open", "High", "Low", "Close"]].rename(
            columns={
                "ticker": "observed_ticker",
                "date": "prediction_date",
                "Open": "yf_provider_open",
                "High": "yf_provider_high",
                "Low": "yf_provider_low",
                "Close": "yf_provider_close",
            }
        )
        result["observed_ticker"] = result["observed_ticker"].map(normalize_ticker)
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        return result

    def _project_identity(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = {"security_id", "observed_ticker", "date"}
        self._require(frame, required, metadata.snapshot_id)
        result = frame.loc[:, ["security_id", "observed_ticker", "date"]].rename(
            columns={"date": "prediction_date"}
        )
        result["observed_ticker"] = result["observed_ticker"].map(normalize_ticker)
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        if result.duplicated(["observed_ticker", "prediction_date"]).any():
            raise FeatureInputError("identity snapshot has duplicate ticker/date rows")
        return result

    def _project_isyatirim(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = {"HGDG_HS_KODU", "HGDG_TARIH", "HGDG_HACIM"}
        self._require(frame, required, metadata.snapshot_id)
        result = frame.loc[:, list(required)].rename(
            columns={
                "HGDG_HS_KODU": "observed_ticker",
                "HGDG_TARIH": "prediction_date",
                "HGDG_HACIM": "is_tl_volume",
            }
        )
        result["observed_ticker"] = result["observed_ticker"].map(normalize_ticker)
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        return result

    def _project_xu100(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = {"prediction_date", "validated_xu100_close"}
        self._require(frame, required, metadata.snapshot_id)
        result = frame.loc[:, ["prediction_date", "validated_xu100_close"]].copy()
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        if result["prediction_date"].duplicated().any():
            raise FeatureInputError("validated XU100 snapshot has duplicate dates")
        return result

    def _project_calendar(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        self._require(frame, {"session_date", "session_index"}, metadata.snapshot_id)
        result = frame.loc[:, ["session_date", "session_index"]].copy()
        result["session_date"] = pd.to_datetime(result["session_date"]).dt.normalize()
        if result["session_date"].duplicated().any() or not result["session_date"].is_monotonic_increasing:
            raise FeatureInputError("global calendar must be unique and increasing")
        return result

    @staticmethod
    def _require(frame: pd.DataFrame, required: Iterable[str], snapshot_id: str) -> None:
        missing = set(required).difference(frame.columns)
        if missing:
            raise FeatureInputError(f"snapshot {snapshot_id} fields missing: {sorted(missing)}")
