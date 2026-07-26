"""Pure three-BIST-day target-label rules for D011-D014 and D020-D026."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Mapping, Sequence

import pandas as pd

from src.config import LabelConfig
from src.data.price_limits import PriceStepTable


REQUIRED_CLEAN_LABEL_COLUMNS = {
    "ticker",
    "prediction_date",
    "entry_date",
    "yf_nominal_open",
    "yf_nominal_high",
    "yf_nominal_close",
    "ohlc_quality_flag",
    "volume_quality_flag",
    "corporate_action_window_flag",
    "entry_eligible",
    "entry_exclusion_reason",
    "entry_exclusion_reasons",
    "requires_review",
}
IDENTITY_AUDIT_COLUMNS = (
    "security_id",
    "observed_ticker",
    "current_ticker",
    "ticker_mapping_status",
    "ticker_mapping_rule_id",
    "ticker_mapping_version",
    "ticker_mapping_checksum",
)


class LabelGenerationError(ValueError):
    """Raised when clean input cannot produce an auditable label frame."""


@dataclass(frozen=True)
class TargetPriceComputation:
    """Exact Decimal components of one executable target-price calculation."""

    raw_target_price: Decimal
    target_tick_size: Decimal
    target_price: Decimal


def _decimal(value: Decimal | float | int | str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LabelGenerationError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise LabelGenerationError(f"non-finite decimal value: {value!r}")
    return result


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        result = _decimal(value)
    except LabelGenerationError:
        return None
    return result if result > 0 else None


def ceil_to_price_step(
    price: Decimal | float | int | str,
    price_step: Decimal | float | int | str,
) -> Decimal:
    """Round outward/up to the smallest valid tick-size multiple."""

    value = _decimal(price)
    step = _decimal(price_step)
    if value < 0 or step <= 0:
        raise LabelGenerationError("price must be non-negative and price_step positive")
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def calculate_target_price(
    entry_price: Decimal | float | int | str,
    entry_date: date | str | pd.Timestamp,
    price_steps: PriceStepTable,
    *,
    target_return: Decimal | float | int | str = "0.05",
    instrument_type: str = "EQUITY",
) -> TargetPriceComputation | None:
    """Resolve and round the D011 target using the entry-date tariff."""

    entry = _positive_decimal(entry_price)
    if entry is None:
        return None
    target_rate = _decimal(target_return)
    if target_rate < 0:
        raise LabelGenerationError("target_return cannot be negative")
    raw_target = entry * (Decimal("1") + target_rate)
    step = price_steps.resolve(
        entry_date,
        raw_target,
        instrument_type=instrument_type,
    )
    if step is None:
        return None
    return TargetPriceComputation(
        raw_target_price=raw_target,
        target_tick_size=step,
        target_price=ceil_to_price_step(raw_target, step),
    )


def _reason_list(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("entry_exclusion_reasons")
    if isinstance(raw, (list, tuple)):
        reasons = [str(value) for value in raw if value is not None and not pd.isna(value)]
    else:
        reasons = []
    primary = row.get("entry_exclusion_reason")
    if primary is not None and not pd.isna(primary) and str(primary) not in reasons:
        reasons.insert(0, str(primary))
    if _is_true(row.get("corporate_action_window_flag", False)) and (
        "CORPORATE_ACTION_WINDOW" not in reasons
    ):
        reasons.append("CORPORATE_ACTION_WINDOW")
    return reasons


def _is_true(value: Any) -> bool:
    return value is not None and not pd.isna(value) and bool(value)


def _global_next_dates(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    pairs = frame[["prediction_date", "entry_date"]].dropna().drop_duplicates()
    conflicts = pairs.groupby("prediction_date")["entry_date"].nunique()
    if conflicts.gt(1).any():
        dates = [value.isoformat() for value in conflicts[conflicts.gt(1)].index]
        raise LabelGenerationError(
            f"clean snapshot has conflicting global BIST next dates: {dates}"
        )
    unique = pairs.drop_duplicates("prediction_date")
    return dict(zip(unique["prediction_date"], unique["entry_date"], strict=True))


def _base_output(
    row: Mapping[str, Any],
    next_dates: Mapping[pd.Timestamp, pd.Timestamp],
) -> dict[str, Any]:
    entry_date = row["entry_date"]
    t2_date = next_dates.get(entry_date)
    t3_date = next_dates.get(t2_date) if t2_date is not None else None
    output = {
        "ticker": str(row["ticker"]),
        "prediction_date": row["prediction_date"],
        "entry_date": entry_date,
        "horizon_t2_date": t2_date,
        "horizon_t3_date": t3_date,
        "entry_price": None,
        "raw_target_price": None,
        "target_tick_size": None,
        "target_price": None,
        "target_hit": pd.NA,
        "target_hit_date": None,
        "target_hit_horizon": pd.NA,
        "label": pd.NA,
        "label_status": "NA",
        "label_exclusion_reason": pd.NA,
        "label_exclusion_reasons": [],
        "exit_date": None,
        "exit_price": None,
        "exit_reason": pd.NA,
        "gross_return": None,
    }
    for column in IDENTITY_AUDIT_COLUMNS:
        if column in row:
            output[column] = row[column]
    return output


def _exclude(output: dict[str, Any], reasons: Sequence[str]) -> None:
    ordered = list(dict.fromkeys(map(str, reasons)))
    output["label_exclusion_reasons"] = ordered
    output["label_exclusion_reason"] = ordered[0] if ordered else "UNKNOWN"


def build_three_day_target_labels(
    clean_frame: pd.DataFrame,
    price_steps: PriceStepTable,
    *,
    config: LabelConfig | None = None,
) -> pd.DataFrame:
    """Build label outcomes without reading raw/provider snapshots.

    The global BIST calendar relation is carried by the clean snapshot's
    ``prediction_date -> entry_date`` pairs. Missing T+2/T+3 links remain NA;
    ticker rows are never shifted to a later date to fill a gap.
    """

    settings = config or LabelConfig()
    if settings.horizon_days != 3:
        raise LabelGenerationError("the binding label horizon must be three BIST days")
    missing = REQUIRED_CLEAN_LABEL_COLUMNS.difference(clean_frame.columns)
    if missing:
        raise LabelGenerationError(
            f"clean label input fields missing: {sorted(missing)}"
        )
    if clean_frame.empty:
        raise LabelGenerationError("clean label input cannot be empty")

    frame = clean_frame.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    entity_column = "security_id" if "security_id" in frame.columns else "ticker"
    if entity_column == "security_id" and frame["security_id"].isna().any():
        raise LabelGenerationError("clean snapshot contains a missing security_id")
    for column in ("prediction_date", "entry_date"):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    if frame.duplicated([entity_column, "prediction_date"]).any():
        raise LabelGenerationError(
            f"clean snapshot has duplicate {entity_column}/prediction_date rows"
        )
    if frame.duplicated([entity_column, "entry_date"]).any():
        raise LabelGenerationError(
            f"clean snapshot has duplicate {entity_column}/entry_date rows"
        )

    next_dates = _global_next_dates(frame)
    by_entry = frame.set_index([entity_column, "entry_date"], drop=False)
    outputs: list[dict[str, Any]] = []
    ordered = frame.sort_values([entity_column, "prediction_date"])
    for source in ordered.to_dict(orient="records"):
        output = _base_output(source, next_dates)
        outputs.append(output)

        source_reasons = _reason_list(source)
        if source_reasons:
            _exclude(output, source_reasons)
            continue
        if _is_true(source.get("requires_review")):
            _exclude(output, ["REQUIRES_REVIEW"])
            continue
        if not _is_true(source.get("entry_eligible")):
            _exclude(output, ["ENTRY_NOT_ELIGIBLE"])
            continue

        entry = _positive_decimal(source.get("yf_nominal_open"))
        if entry is None:
            _exclude(output, ["NO_OPEN"])
            continue
        output["entry_price"] = float(entry)
        target = calculate_target_price(
            entry,
            source["entry_date"],
            price_steps,
            target_return=settings.target_return,
            instrument_type=settings.instrument_type,
        )
        if target is None:
            _exclude(output, ["TARGET_TICK_SIZE_UNAVAILABLE"])
            continue
        output["raw_target_price"] = float(target.raw_target_price)
        output["target_tick_size"] = float(target.target_tick_size)
        output["target_price"] = float(target.target_price)

        horizon_dates = [
            source["entry_date"],
            output["horizon_t2_date"],
            output["horizon_t3_date"],
        ]
        if any(value is None or pd.isna(value) for value in horizon_dates):
            _exclude(output, ["INCOMPLETE_HORIZON"])
            continue

        horizon_rows: list[Mapping[str, Any]] = []
        missing_horizon_row = False
        for horizon_date in horizon_dates:
            key = (source[entity_column], horizon_date)
            if key not in by_entry.index:
                missing_horizon_row = True
                break
            horizon_rows.append(by_entry.loc[key].to_dict())
        if missing_horizon_row:
            _exclude(output, ["MISSING_HORIZON_ROW"])
            continue

        highs: list[Decimal] = []
        invalid_reason: str | None = None
        for horizon_row in horizon_rows:
            if str(horizon_row.get("volume_quality_flag", "")) == "NO_TRADE":
                invalid_reason = "HORIZON_NO_TRADE"
                break
            high = _positive_decimal(horizon_row.get("yf_nominal_high"))
            if str(horizon_row.get("ohlc_quality_flag", "")) != "VALID" or high is None:
                invalid_reason = "INVALID_HORIZON_PRICE"
                break
            highs.append(high)
        if invalid_reason:
            _exclude(output, [invalid_reason])
            continue

        first_hit_index = next(
            (
                index
                for index, high in enumerate(highs, start=1)
                if high >= target.target_price
            ),
            None,
        )
        if first_hit_index is not None:
            exit_price = target.target_price
            exit_date = horizon_dates[first_hit_index - 1]
            output.update(
                {
                    "target_hit": True,
                    "target_hit_date": exit_date,
                    "target_hit_horizon": first_hit_index,
                    "label": 1,
                    "label_status": "LABELED",
                    "exit_date": exit_date,
                    "exit_price": float(exit_price),
                    "exit_reason": "TARGET_HIT",
                    "gross_return": float(exit_price / entry - Decimal("1")),
                }
            )
            continue

        t3_close = _positive_decimal(horizon_rows[2].get("yf_nominal_close"))
        if t3_close is None:
            _exclude(output, ["MISSING_T3_CLOSE"])
            continue
        output.update(
            {
                "target_hit": False,
                "label": 0,
                "label_status": "LABELED",
                "exit_date": horizon_dates[2],
                "exit_price": float(t3_close),
                "exit_reason": "HORIZON_CLOSE",
                "gross_return": float(t3_close / entry - Decimal("1")),
            }
        )

    result = pd.DataFrame(outputs)
    result["label"] = pd.Series(result["label"], dtype="Int64")
    result["target_hit"] = pd.Series(result["target_hit"], dtype="boolean")
    result["target_hit_horizon"] = pd.Series(
        result["target_hit_horizon"], dtype="Int64"
    )
    for column in (
        "label_status",
        "label_exclusion_reason",
        "exit_reason",
    ):
        result[column] = result[column].astype("string")
    return result.sort_values([entity_column, "prediction_date"]).reset_index(drop=True)


def summarize_labels(frame: pd.DataFrame) -> dict[str, Any]:
    """Return deterministic label distribution and NA-reason counts."""

    na_reasons = (
        frame.loc[frame["label_status"].eq("NA"), "label_exclusion_reason"]
        .dropna()
        .astype(str)
        .value_counts()
        .sort_index()
    )
    return {
        "row_count": int(len(frame)),
        "label_positive": int(frame["label"].eq(1).sum()),
        "label_negative": int(frame["label"].eq(0).sum()),
        "label_na": int(frame["label"].isna().sum()),
        "target_hit_t1": int(frame["target_hit_horizon"].eq(1).sum()),
        "target_hit_t2": int(frame["target_hit_horizon"].eq(2).sum()),
        "target_hit_t3": int(frame["target_hit_horizon"].eq(3).sum()),
        "na_reasons": {str(key): int(value) for key, value in na_reasons.items()},
    }
