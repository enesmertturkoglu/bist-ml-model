"""Prediction-universe construction using only T and earlier information."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.active_universe import validate_active_universe_snapshot
from src.data.security_identity import normalize_ticker
from src.data.snapshot_store import SnapshotMetadata, SnapshotStore
from src.features.catalog import BASELINE_V1_FEATURES, catalog_file_checksum
from src.features.pipeline import validate_feature_snapshot


PREDICTION_EXCLUSION_REASONS: tuple[str, ...] = (
    "NOT_IN_MASTER_UNIVERSE",
    "NO_T_OBSERVATION",
    "INVALID_T_OHLC",
    "NO_TRADE_ON_T",
    "MISSING_TRADE_EVIDENCE",
    "INSUFFICIENT_HISTORY",
    "MISSING_FEATURE_ROW",
    "MISSING_XU100_SESSION",
    "DUPLICATE_FEATURE_ROW",
)

FORBIDDEN_UNIVERSE_FIELDS = {
    "entry_eligible",
    "entry_exclusion_reason",
    "limit_open",
    "is_limit_open",
    "corporate_action_window_flag",
    "target_hit",
    "label",
    "exit_price",
    "entry_price",
    "target_price",
    "horizon_t2_date",
    "horizon_t3_date",
    "yf_future_split_factor",
}

OBSERVATION_COLUMNS: tuple[str, ...] = (
    "security_id",
    "observed_ticker",
    "prediction_date",
    "yf_nominal_open",
    "yf_nominal_high",
    "yf_nominal_low",
    "yf_nominal_close",
    "is_tl_volume",
    "yf_share_volume",
)


class PredictionUniverseError(ValueError):
    """Raised when prediction eligibility cannot be determined safely."""


@dataclass(frozen=True)
class PredictionUniverseAssembly:
    universe: pd.DataFrame
    observations: pd.DataFrame
    features: pd.DataFrame
    calendar: pd.DataFrame
    xu100: pd.DataFrame
    metadata: tuple[SnapshotMetadata, ...]


def _normalize_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    required = {"session_date", "session_index"}
    missing = required.difference(calendar.columns)
    if missing:
        raise PredictionUniverseError(
            f"global calendar fields missing: {sorted(missing)}"
        )
    result = calendar.loc[:, ["session_date", "session_index"]].copy()
    result["session_date"] = pd.to_datetime(result["session_date"], errors="raise").dt.normalize()
    result["session_index"] = pd.to_numeric(result["session_index"], errors="raise")
    if result["session_date"].duplicated().any():
        raise PredictionUniverseError("global calendar contains duplicate sessions")
    result = result.sort_values("session_date").reset_index(drop=True)
    if not result["session_date"].is_monotonic_increasing:
        raise PredictionUniverseError("global calendar must be increasing")
    if result["session_index"].tolist() != list(range(len(result))):
        raise PredictionUniverseError("global calendar session_index must be contiguous")
    return result


def _normalize_master(
    master_universe: pd.DataFrame | Iterable[str],
    sessions: pd.DataFrame,
) -> pd.DataFrame:
    if isinstance(master_universe, pd.DataFrame):
        if "security_id" not in master_universe.columns:
            raise PredictionUniverseError("master universe has no security_id")
        if "prediction_date" in master_universe.columns:
            result = master_universe.loc[:, ["security_id", "prediction_date"]].copy()
            result["prediction_date"] = pd.to_datetime(
                result["prediction_date"], errors="raise"
            ).dt.normalize()
        else:
            securities = master_universe.loc[:, ["security_id"]].copy()
            result = securities.assign(_join=1).merge(
                sessions.loc[:, ["session_date"]]
                .rename(columns={"session_date": "prediction_date"})
                .assign(_join=1),
                on="_join",
                how="inner",
            ).drop(columns="_join")
    else:
        securities = pd.DataFrame({"security_id": list(master_universe)})
        result = securities.assign(_join=1).merge(
            sessions.loc[:, ["session_date"]]
            .rename(columns={"session_date": "prediction_date"})
            .assign(_join=1),
            on="_join",
            how="inner",
        ).drop(columns="_join")
    if result.empty or result["security_id"].isna().any():
        raise PredictionUniverseError("master universe must contain security IDs")
    result["security_id"] = result["security_id"].astype(str)
    if result.duplicated(["security_id", "prediction_date"]).any():
        raise PredictionUniverseError("master universe contains duplicate date key")
    valid_sessions = set(sessions["session_date"])
    if not result["prediction_date"].isin(valid_sessions).all():
        raise PredictionUniverseError("master universe date falls outside global calendar")
    return result.sort_values(["prediction_date", "security_id"]).reset_index(drop=True)


def _guard_no_future_fields(frame: pd.DataFrame) -> None:
    normalized = {str(column).strip().lower() for column in frame.columns}
    present = sorted(normalized.intersection(FORBIDDEN_UNIVERSE_FIELDS))
    future_fragments = sorted(
        column
        for column in normalized
        if column.startswith("t_plus_") or column.startswith("t1_")
    )
    if present or future_fragments:
        raise PredictionUniverseError(
            f"prediction universe input contains future/outcome fields: {present + future_fragments}"
        )


def _valid_positive(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.notna() & np.isfinite(numeric) & numeric.gt(0)


def _valid_ohlc(frame: pd.DataFrame) -> pd.Series:
    columns = [
        "yf_nominal_open",
        "yf_nominal_high",
        "yf_nominal_low",
        "yf_nominal_close",
    ]
    numeric = frame.loc[:, columns].apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype="float64")
    finite_positive = pd.DataFrame(
        np.isfinite(values) & (values > 0),
        index=numeric.index,
        columns=columns,
    ).all(axis=1)
    return (
        finite_positive
        & numeric["yf_nominal_high"].ge(numeric[["yf_nominal_open", "yf_nominal_close"]].max(axis=1))
        & numeric["yf_nominal_low"].le(numeric[["yf_nominal_open", "yf_nominal_close"]].min(axis=1))
        & numeric["yf_nominal_high"].ge(numeric["yf_nominal_low"])
    )


def _validate_feature_schema(features: pd.DataFrame) -> pd.DataFrame:
    expected = ["security_id", "prediction_date", *BASELINE_V1_FEATURES]
    if set(features.columns) != set(expected) or len(features.columns) != len(expected):
        raise PredictionUniverseError("feature schema does not exactly match baseline_v1")
    result = features.loc[:, expected].copy()
    result["security_id"] = result["security_id"].astype(str)
    result["prediction_date"] = pd.to_datetime(
        result["prediction_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["security_id", "prediction_date"]).any():
        raise PredictionUniverseError(
            "DUPLICATE_FEATURE_ROW: duplicate security_id + prediction_date"
        )
    return result


def build_prediction_universe(
    master_universe: pd.DataFrame | Iterable[str],
    observations: pd.DataFrame,
    features: pd.DataFrame,
    calendar: pd.DataFrame,
    xu100: pd.DataFrame,
    *,
    minimum_history_sessions: int = 21,
) -> pd.DataFrame:
    """Return deterministic historical eligibility without consulting T+1 outcomes."""

    if minimum_history_sessions < 1:
        raise PredictionUniverseError("minimum_history_sessions must be positive")
    sessions = _normalize_calendar(calendar)
    master = _normalize_master(master_universe, sessions)
    _guard_no_future_fields(observations)
    missing_observation = set(OBSERVATION_COLUMNS).difference(observations.columns)
    if missing_observation:
        raise PredictionUniverseError(
            f"prediction observation fields missing: {sorted(missing_observation)}"
        )
    observed = observations.loc[:, OBSERVATION_COLUMNS].copy()
    observed["security_id"] = observed["security_id"].astype(str)
    observed["prediction_date"] = pd.to_datetime(
        observed["prediction_date"], errors="raise"
    ).dt.normalize()
    if observed.duplicated(["security_id", "prediction_date"]).any():
        raise PredictionUniverseError("duplicate T observation key")
    feature_frame = _validate_feature_schema(features)

    if not {"prediction_date", "validated_xu100_close"}.issubset(xu100.columns):
        raise PredictionUniverseError("XU100 fields missing")
    benchmark = xu100.loc[:, ["prediction_date", "validated_xu100_close"]].copy()
    benchmark["prediction_date"] = pd.to_datetime(
        benchmark["prediction_date"], errors="raise"
    ).dt.normalize()
    if benchmark["prediction_date"].duplicated().any():
        raise PredictionUniverseError("duplicate XU100 session")
    benchmark["_has_xu100"] = _valid_positive(benchmark["validated_xu100_close"])

    extra_keys = pd.concat(
        [
            observed.loc[:, ["security_id", "prediction_date"]],
            feature_frame.loc[:, ["security_id", "prediction_date"]],
        ],
        ignore_index=True,
    ).drop_duplicates()
    keys = pd.concat([master, extra_keys], ignore_index=True).drop_duplicates()
    keys = keys.sort_values(["prediction_date", "security_id"]).reset_index(drop=True)
    keys = keys.merge(
        master.assign(_in_master=True),
        on=["security_id", "prediction_date"],
        how="left",
        validate="one_to_one",
    )
    keys["_in_master"] = keys["_in_master"].eq(True)

    observed["_has_observation"] = True
    panel = keys.merge(
        observed,
        on=["security_id", "prediction_date"],
        how="left",
        validate="one_to_one",
    )
    feature_keys = feature_frame.loc[:, ["security_id", "prediction_date"]].assign(
        _has_feature=True
    )
    panel = panel.merge(
        feature_keys,
        on=["security_id", "prediction_date"],
        how="left",
        validate="one_to_one",
    )
    panel = panel.merge(
        sessions.rename(columns={"session_date": "prediction_date"}),
        on="prediction_date",
        how="left",
        validate="many_to_one",
    )
    panel = panel.merge(
        benchmark.loc[:, ["prediction_date", "_has_xu100"]],
        on="prediction_date",
        how="left",
        validate="many_to_one",
    )

    on_calendar = observed.merge(
        sessions.rename(columns={"session_date": "prediction_date"}),
        on="prediction_date",
        how="inner",
        validate="many_to_one",
    )
    first_index = on_calendar.groupby("security_id")["session_index"].min()
    panel["_first_session_index"] = panel["security_id"].map(first_index)
    panel["available_history_sessions"] = (
        panel["session_index"] - panel["_first_session_index"] + 1
    ).astype("Int64")

    has_observation = panel["_has_observation"].eq(True)
    valid_ohlc = _valid_ohlc(panel)
    tl_numeric = pd.to_numeric(panel["is_tl_volume"], errors="coerce")
    share_numeric = pd.to_numeric(panel["yf_share_volume"], errors="coerce")
    tl_available = tl_numeric.notna() & np.isfinite(tl_numeric) & tl_numeric.ge(0)
    share_available = share_numeric.notna() & np.isfinite(share_numeric) & share_numeric.ge(0)
    positive_trade = (tl_available & tl_numeric.gt(0)) | (
        share_available & share_numeric.gt(0)
    )
    conclusive_no_trade = tl_available & share_available & ~positive_trade
    sufficient_history = panel["available_history_sessions"].ge(
        minimum_history_sessions
    ).fillna(False)
    has_feature = panel["_has_feature"].eq(True)
    has_xu100 = panel["_has_xu100"].eq(True)

    reasons = pd.Series(pd.NA, index=panel.index, dtype="string")
    conditions: Sequence[tuple[pd.Series, str]] = (
        (~panel["_in_master"], "NOT_IN_MASTER_UNIVERSE"),
        (~has_observation, "NO_T_OBSERVATION"),
        (has_observation & ~valid_ohlc, "INVALID_T_OHLC"),
        (has_observation & valid_ohlc & conclusive_no_trade, "NO_TRADE_ON_T"),
        (
            has_observation & valid_ohlc & ~positive_trade & ~conclusive_no_trade,
            "MISSING_TRADE_EVIDENCE",
        ),
        (has_observation & valid_ohlc & positive_trade & ~sufficient_history, "INSUFFICIENT_HISTORY"),
        (
            has_observation & valid_ohlc & positive_trade & sufficient_history & ~has_feature,
            "MISSING_FEATURE_ROW",
        ),
        (
            has_observation
            & valid_ohlc
            & positive_trade
            & sufficient_history
            & has_feature
            & ~has_xu100,
            "MISSING_XU100_SESSION",
        ),
    )
    for condition, code in conditions:
        reasons = reasons.mask(reasons.isna() & condition.fillna(False), code)

    panel["prediction_exclusion_reason"] = reasons
    panel["prediction_eligible"] = reasons.isna()
    output = panel.loc[
        :,
        [
            "security_id",
            "observed_ticker",
            "prediction_date",
            "prediction_eligible",
            "prediction_exclusion_reason",
            "available_history_sessions",
        ],
    ].copy()
    output["prediction_eligible"] = output["prediction_eligible"].astype(bool)
    return output.sort_values(["prediction_date", "security_id"]).reset_index(drop=True)


class PredictionUniverseInputAssembler:
    """Verify snapshot integrity and reconstruct only T-known eligibility inputs."""

    def __init__(
        self,
        snapshot_store: SnapshotStore,
        *,
        catalog_path: str | Path = Path("FEATURE_CATALOG.md"),
    ) -> None:
        self.snapshot_store = snapshot_store
        self.catalog_path = Path(catalog_path)

    def assemble(
        self,
        *,
        yfinance_raw_snapshot_ids: Sequence[str],
        isyatirim_raw_snapshot_ids: Sequence[str],
        identity_snapshot_id: str,
        active_universe_snapshot_id: str,
        feature_snapshot_id: str,
        xu100_snapshot_id: str,
        calendar_snapshot_id: str,
        minimum_history_sessions: int = 21,
    ) -> PredictionUniverseAssembly:
        if not str(active_universe_snapshot_id).strip():
            raise PredictionUniverseError("active_universe_snapshot_id is required")
        active_meta = validate_active_universe_snapshot(
            self.snapshot_store, active_universe_snapshot_id
        )
        if not yfinance_raw_snapshot_ids or not isyatirim_raw_snapshot_ids:
            raise PredictionUniverseError("raw yFinance and İş Yatırım snapshots are required")
        yf_meta = [
            self._verify(value, ("yfinance", "equity_history", "raw"))
            for value in yfinance_raw_snapshot_ids
        ]
        is_meta = [
            self._verify(value, ("isyatirim", "equity_history", "raw"))
            for value in isyatirim_raw_snapshot_ids
        ]
        identity_meta = self._verify(
            identity_snapshot_id, ("security_identity", "nominal_ohlc", "derived")
        )
        feature_meta = validate_feature_snapshot(
            self.snapshot_store,
            feature_snapshot_id,
            expected_catalog_checksum=catalog_file_checksum(self.catalog_path),
        )
        xu_meta = self._verify(
            xu100_snapshot_id, ("benchmark", "validated_xu100_close", "derived")
        )
        calendar_meta = self._verify(
            calendar_snapshot_id, ("isyatirim", "global_bist_sessions", "derived")
        )
        supplied_feature_inputs = [
            *yf_meta,
            *is_meta,
            identity_meta,
            xu_meta,
            calendar_meta,
        ]
        supplied_ids = [item.snapshot_id for item in supplied_feature_inputs]
        if len(supplied_ids) != len(set(supplied_ids)) or set(supplied_ids) != set(
            feature_meta.input_snapshot_ids
        ):
            raise PredictionUniverseError(
                "prediction-universe snapshots do not exactly match feature lineage"
            )
        yfinance_volume = pd.concat(
            [self._project_yfinance(item) for item in yf_meta], ignore_index=True
        )
        identity = self._project_identity(identity_meta)
        observations = yfinance_volume.merge(
            identity,
            on=["observed_ticker", "prediction_date"],
            how="left",
            validate="one_to_one",
        )
        if observations["security_id"].isna().any():
            raise PredictionUniverseError(
                "identity snapshot has no date-effective security_id/nominal OHLC"
            )
        isyatirim = pd.concat(
            [self._project_isyatirim(item) for item in is_meta], ignore_index=True
        )
        if isyatirim.duplicated(["observed_ticker", "prediction_date"]).any():
            raise PredictionUniverseError("duplicate İş Yatırım T observation")
        observations = observations.merge(
            isyatirim,
            on=["observed_ticker", "prediction_date"],
            how="left",
            validate="one_to_one",
        ).loc[:, OBSERVATION_COLUMNS]
        features = _validate_feature_schema(
            self.snapshot_store.read_dataframe(feature_meta).loc[
                :, ["security_id", "prediction_date", *BASELINE_V1_FEATURES]
            ]
        )
        calendar = _normalize_calendar(
            self.snapshot_store.read_dataframe(calendar_meta).loc[
                :, ["session_date", "session_index"]
            ]
        )
        xu100 = self.snapshot_store.read_dataframe(xu_meta).loc[
            :, ["prediction_date", "validated_xu100_close"]
        ].copy()
        xu100["prediction_date"] = pd.to_datetime(
            xu100["prediction_date"], errors="raise"
        ).dt.normalize()
        master_frame = self.snapshot_store.read_dataframe(active_meta)
        master = master_frame.loc[:, ["security_id"]].drop_duplicates()
        if master["security_id"].duplicated().any():
            raise PredictionUniverseError("active universe contains duplicate security_id")
        universe = build_prediction_universe(
            master,
            observations,
            features,
            calendar,
            xu100,
            minimum_history_sessions=minimum_history_sessions,
        )
        return PredictionUniverseAssembly(
            universe,
            observations.sort_values(["security_id", "prediction_date"]).reset_index(drop=True),
            features,
            calendar,
            xu100,
            tuple([*supplied_feature_inputs, feature_meta, active_meta]),
        )

    def _verify(
        self, snapshot_id: str, expected: tuple[str, str, str]
    ) -> SnapshotMetadata:
        metadata = self.snapshot_store.get_snapshot(snapshot_id)
        if not self.snapshot_store.is_usable(metadata):
            raise PredictionUniverseError(f"snapshot is not verified COMPLETE: {snapshot_id}")
        actual = (metadata.source, metadata.dataset_type, metadata.layer)
        if actual != expected:
            raise PredictionUniverseError(
                f"snapshot {snapshot_id} has type {actual}, expected {expected}"
            )
        return metadata

    def _project_yfinance(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = ["ticker", "date", "Volume"]
        missing = set(required).difference(frame.columns)
        if missing:
            raise PredictionUniverseError(f"yFinance fields missing: {sorted(missing)}")
        result = frame.loc[:, required].rename(
            columns={
                "ticker": "observed_ticker",
                "date": "prediction_date",
                "Volume": "yf_share_volume",
            }
        )
        result["observed_ticker"] = result["observed_ticker"].map(normalize_ticker)
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        if result.duplicated(["observed_ticker", "prediction_date"]).any():
            raise PredictionUniverseError("duplicate yFinance T observation")
        return result

    def _project_identity(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = [
            "security_id",
            "observed_ticker",
            "date",
            "yf_nominal_open",
            "yf_nominal_high",
            "yf_nominal_low",
            "yf_nominal_close",
        ]
        missing = set(required).difference(frame.columns)
        if missing:
            raise PredictionUniverseError(f"identity fields missing: {sorted(missing)}")
        result = frame.loc[:, required].rename(columns={"date": "prediction_date"})
        result["observed_ticker"] = result["observed_ticker"].map(normalize_ticker)
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        if result.duplicated(["observed_ticker", "prediction_date"]).any():
            raise PredictionUniverseError("duplicate identity T observation")
        return result

    def _project_isyatirim(self, metadata: SnapshotMetadata) -> pd.DataFrame:
        frame = self.snapshot_store.read_dataframe(metadata)
        required = ["HGDG_HS_KODU", "HGDG_TARIH", "HGDG_HACIM"]
        missing = set(required).difference(frame.columns)
        if missing:
            raise PredictionUniverseError(f"İş Yatırım fields missing: {sorted(missing)}")
        result = frame.loc[:, required].rename(
            columns={
                "HGDG_HS_KODU": "observed_ticker",
                "HGDG_TARIH": "prediction_date",
                "HGDG_HACIM": "is_tl_volume",
            }
        )
        result["observed_ticker"] = result["observed_ticker"].map(normalize_ticker)
        result["prediction_date"] = pd.to_datetime(result["prediction_date"]).dt.normalize()
        return result
