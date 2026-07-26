"""Versioned BIST equity tick-size and upper-limit calculations.

The tariff itself lives in a human-readable reference-data file. Monetary and
tick-size calculations use :class:`decimal.Decimal`; binary floating point is
used only when provider values enter or leave the calculation boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Iterable

import pandas as pd


REFERENCE_COLUMNS = {
    "rule_set_id",
    "instrument_type",
    "effective_from",
    "effective_to",
    "price_min_inclusive",
    "price_max_exclusive",
    "tick_size",
    "currency",
    "official_source_name",
    "official_document_number",
    "official_document_date",
    "official_effective_date",
    "official_source_url",
    "source_checksum",
    "notes",
}


class PriceStepRuleError(ValueError):
    """Raised when a tick-size reference table is invalid or ambiguous."""


def _decimal(value: Decimal | float | int | str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PriceStepRuleError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise PriceStepRuleError(f"non-finite decimal value: {value!r}")
    return result


def _date(value: date | str | pd.Timestamp) -> date:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise PriceStepRuleError(f"invalid date value: {value!r}") from exc
    if pd.isna(result):
        raise PriceStepRuleError(f"invalid date value: {value!r}")
    return result.date()


def _optional_text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


@dataclass(frozen=True)
class PriceStepRule:
    """One inclusive-lower/exclusive-upper interval from a tariff regime."""

    effective_from: date | str | pd.Timestamp
    effective_to: date | str | pd.Timestamp | None
    min_price: Decimal | float | int | str
    max_price: Decimal | float | int | str | None
    price_step: Decimal | float | int | str
    rule_set_id: str = "UNVERSIONED"
    instrument_type: str = "EQUITY"
    currency: str = "TRY"
    official_source_name: str = ""
    official_document_number: str = ""
    official_document_date: date | str | pd.Timestamp | None = None
    official_effective_date: date | str | pd.Timestamp | None = None
    official_source_url: str = ""
    source_checksum: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        start = _date(self.effective_from)
        end = _date(self.effective_to) if self.effective_to is not None else None
        lower = _decimal(self.min_price)
        upper = _decimal(self.max_price) if self.max_price is not None else None
        step = _decimal(self.price_step)
        instrument_type = self.instrument_type.strip().upper()
        currency = self.currency.strip().upper()
        rule_set_id = self.rule_set_id.strip()
        if end is not None and end < start:
            raise PriceStepRuleError("effective_to cannot precede effective_from")
        if lower < 0:
            raise PriceStepRuleError("min_price cannot be negative")
        if upper is not None and upper <= lower:
            raise PriceStepRuleError("max_price must be greater than min_price")
        if step <= 0:
            raise PriceStepRuleError("price_step must be positive")
        if not instrument_type:
            raise PriceStepRuleError("instrument_type is required")
        if not currency:
            raise PriceStepRuleError("currency is required")
        if not rule_set_id:
            raise PriceStepRuleError("rule_set_id is required")
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_to", end)
        object.__setattr__(self, "min_price", lower)
        object.__setattr__(self, "max_price", upper)
        object.__setattr__(self, "price_step", step)
        object.__setattr__(self, "rule_set_id", rule_set_id)
        object.__setattr__(self, "instrument_type", instrument_type)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self,
            "official_document_date",
            _date(self.official_document_date)
            if self.official_document_date is not None
            else None,
        )
        object.__setattr__(
            self,
            "official_effective_date",
            _date(self.official_effective_date)
            if self.official_effective_date is not None
            else None,
        )

    def matches(
        self, trade_date: date, price: Decimal, instrument_type: str
    ) -> bool:
        in_date = self.effective_from <= trade_date and (
            self.effective_to is None or trade_date <= self.effective_to
        )
        in_price = self.min_price <= price and (
            self.max_price is None or price < self.max_price
        )
        return (
            self.instrument_type == instrument_type.strip().upper()
            and in_date
            and in_price
        )

    @property
    def official_source_document(self) -> str:
        """Return compact, row-level official-document provenance."""

        parts = [self.official_source_name.strip(), self.official_document_number.strip()]
        text = " ".join(part for part in parts if part)
        if self.official_document_date is not None:
            text = f"{text} ({self.official_document_date.isoformat()})".strip()
        return text

    def to_dict(self) -> dict[str, str | None]:
        return {
            "rule_set_id": self.rule_set_id,
            "instrument_type": self.instrument_type,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "price_min_inclusive": str(self.min_price),
            "price_max_exclusive": str(self.max_price) if self.max_price is not None else None,
            "tick_size": str(self.price_step),
            "currency": self.currency,
            "official_source_name": self.official_source_name,
            "official_document_number": self.official_document_number,
            "official_document_date": (
                self.official_document_date.isoformat()
                if self.official_document_date
                else None
            ),
            "official_effective_date": (
                self.official_effective_date.isoformat()
                if self.official_effective_date
                else None
            ),
            "official_source_url": self.official_source_url,
            "source_checksum": self.source_checksum,
            "notes": self.notes,
        }


class PriceStepTable:
    """Resolve one unambiguous tick-size rule by date, instrument and price."""

    def __init__(self, rules: Iterable[PriceStepRule] = ()) -> None:
        self.rules = tuple(rules)

    @classmethod
    def from_csv(cls, path: str | Path) -> "PriceStepTable":
        frame = pd.read_csv(path, dtype="string")
        missing = REFERENCE_COLUMNS.difference(frame.columns)
        if missing:
            raise PriceStepRuleError(
                f"tick-size reference fields missing: {sorted(missing)}"
            )
        rules = []
        for row in frame.to_dict(orient="records"):
            rules.append(
                PriceStepRule(
                    effective_from=str(row["effective_from"]),
                    effective_to=(
                        None if pd.isna(row["effective_to"]) else str(row["effective_to"])
                    ),
                    min_price=str(row["price_min_inclusive"]),
                    max_price=(
                        None
                        if pd.isna(row["price_max_exclusive"])
                        else str(row["price_max_exclusive"])
                    ),
                    price_step=str(row["tick_size"]),
                    rule_set_id=_optional_text(row["rule_set_id"]),
                    instrument_type=_optional_text(row["instrument_type"]),
                    currency=_optional_text(row["currency"]),
                    official_source_name=_optional_text(row["official_source_name"]),
                    official_document_number=_optional_text(
                        row["official_document_number"]
                    ),
                    official_document_date=(
                        None
                        if pd.isna(row["official_document_date"])
                        else str(row["official_document_date"])
                    ),
                    official_effective_date=(
                        None
                        if pd.isna(row["official_effective_date"])
                        else str(row["official_effective_date"])
                    ),
                    official_source_url=_optional_text(row["official_source_url"]),
                    source_checksum=_optional_text(row["source_checksum"]),
                    notes=_optional_text(row["notes"]),
                )
            )
        table = cls(rules)
        table.validate_reference_data()
        return table

    def validate_reference_data(self) -> None:
        """Reject incomplete, overlapping, gapped or untraceable tariff data."""

        if not self.rules:
            raise PriceStepRuleError("tick-size reference table cannot be empty")
        regime_groups: dict[tuple[str, str, str], list[PriceStepRule]] = {}
        for rule in self.rules:
            key = (rule.instrument_type, rule.currency, rule.rule_set_id)
            regime_groups.setdefault(key, []).append(rule)
            if not all(
                (
                    rule.official_source_name,
                    rule.official_document_number,
                    rule.official_document_date,
                    rule.official_effective_date,
                    rule.official_source_url,
                    rule.source_checksum,
                )
            ):
                raise PriceStepRuleError(
                    f"official source metadata missing for rule set {rule.rule_set_id}"
                )
            checksum = rule.source_checksum.casefold()
            if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
                raise PriceStepRuleError(
                    f"source_checksum must be a SHA-256 hex digest for {rule.rule_set_id}"
                )

        regimes_by_instrument: dict[
            tuple[str, str], list[tuple[date, date | None, str]]
        ] = {}
        for (instrument_type, currency, rule_set_id), rules in regime_groups.items():
            dates = {(rule.effective_from, rule.effective_to) for rule in rules}
            if len(dates) != 1:
                raise PriceStepRuleError(
                    f"inconsistent effective dates in rule set {rule_set_id}"
                )
            metadata = {
                (
                    rule.official_source_name,
                    rule.official_document_number,
                    rule.official_document_date,
                    rule.official_effective_date,
                    rule.official_source_url,
                    rule.source_checksum.casefold(),
                )
                for rule in rules
            }
            if len(metadata) != 1:
                raise PriceStepRuleError(
                    f"inconsistent official metadata in rule set {rule_set_id}"
                )
            bands = sorted(rules, key=lambda rule: rule.min_price)
            if bands[0].min_price != Decimal("0.01"):
                raise PriceStepRuleError(
                    f"rule set {rule_set_id} must start at TRY 0.01"
                )
            for previous, current in zip(bands, bands[1:]):
                if previous.max_price is None or previous.max_price != current.min_price:
                    raise PriceStepRuleError(
                        f"price-band gap or overlap in rule set {rule_set_id}"
                    )
            if bands[-1].max_price is not None:
                raise PriceStepRuleError(
                    f"rule set {rule_set_id} must have an open-ended final band"
                )
            start, end = next(iter(dates))
            regimes_by_instrument.setdefault((instrument_type, currency), []).append(
                (start, end, rule_set_id)
            )

        for (instrument_type, currency), regimes in regimes_by_instrument.items():
            ordered = sorted(regimes, key=lambda regime: regime[0])
            for previous, current in zip(ordered, ordered[1:]):
                previous_end = previous[1]
                if previous_end is None or current[0] != previous_end + timedelta(days=1):
                    raise PriceStepRuleError(
                        "date-regime gap or overlap for "
                        f"{instrument_type}/{currency}: {previous[2]} -> {current[2]}"
                    )

    def resolve_rule(
        self,
        trade_date: date | str | pd.Timestamp,
        nominal_price: Decimal | float | int | str,
        *,
        instrument_type: str = "EQUITY",
    ) -> PriceStepRule | None:
        resolved_date = _date(trade_date)
        price = _decimal(nominal_price)
        resolved_instrument = instrument_type.strip().upper()
        matches = [
            rule
            for rule in self.rules
            if rule.matches(resolved_date, price, resolved_instrument)
        ]
        if len(matches) > 1:
            raise PriceStepRuleError(
                "ambiguous tick-size rules for "
                f"{resolved_instrument} on {resolved_date.isoformat()} at {price}"
            )
        return matches[0] if matches else None

    def resolve(
        self,
        trade_date: date | str | pd.Timestamp,
        nominal_price: Decimal | float | int | str,
        *,
        instrument_type: str = "EQUITY",
    ) -> Decimal | None:
        rule = self.resolve_rule(
            trade_date, nominal_price, instrument_type=instrument_type
        )
        return rule.price_step if rule else None

    @property
    def rule_set_ids(self) -> tuple[str, ...]:
        return tuple(sorted({rule.rule_set_id for rule in self.rules}))

    @property
    def official_source_documents(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    rule.official_source_document
                    for rule in self.rules
                    if rule.official_source_document
                }
            )
        )

    def checksum(self, algorithm: str = "sha256") -> str:
        payload = json.dumps(
            [rule.to_dict() for rule in self.rules],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.new(algorithm, payload).hexdigest()


@dataclass(frozen=True)
class PriceLimitComputation:
    raw_upper_limit: Decimal
    price_step: Decimal
    estimated_upper_limit: Decimal
    rule_set_id: str
    rule_effective_from: date
    rule_effective_to: date | None
    official_source_document: str

    @property
    def tick_size(self) -> Decimal:
        return self.price_step


def floor_to_price_step(
    price: Decimal | float | int | str,
    price_step: Decimal | float | int | str,
) -> Decimal:
    """Round inward/down to the greatest valid tick-size multiple."""

    value = _decimal(price)
    step = _decimal(price_step)
    if value < 0 or step <= 0:
        raise ValueError("price must be non-negative and price_step positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def calculate_upper_limit(
    previous_close: Decimal | float | int | str,
    trade_date: date | str | pd.Timestamp,
    price_steps: PriceStepTable,
    *,
    margin: Decimal | float | int | str = "0.10",
    instrument_type: str = "EQUITY",
) -> PriceLimitComputation | None:
    """Calculate a standard upper limit or return ``None`` without a rule."""

    raw_limit = calculate_raw_upper_limit(previous_close, margin=margin)
    if raw_limit is None:
        return None
    rule = price_steps.resolve_rule(
        trade_date, raw_limit, instrument_type=instrument_type
    )
    if rule is None:
        return None
    estimated = floor_to_price_step(raw_limit, rule.price_step)
    return PriceLimitComputation(
        raw_upper_limit=raw_limit,
        price_step=rule.price_step,
        estimated_upper_limit=estimated,
        rule_set_id=rule.rule_set_id,
        rule_effective_from=rule.effective_from,
        rule_effective_to=rule.effective_to,
        official_source_document=rule.official_source_document,
    )


def calculate_raw_upper_limit(
    previous_close: Decimal | float | int | str,
    *,
    margin: Decimal | float | int | str = "0.10",
) -> Decimal | None:
    """Calculate ``previous_close * (1 + margin)`` with exact decimals."""

    try:
        base = _decimal(previous_close)
        resolved_margin = _decimal(margin)
    except PriceStepRuleError:
        return None
    if base <= 0 or resolved_margin < 0:
        return None
    return base * (Decimal("1") + resolved_margin)


def prices_equal(
    left: float,
    right: float,
    *,
    relative_tolerance: float = 1e-12,
    absolute_tolerance: float = 1e-8,
) -> bool:
    """Compare provider/output prices with small config-level noise tolerance."""

    return math.isclose(
        float(left),
        float(right),
        rel_tol=relative_tolerance,
        abs_tol=absolute_tolerance,
    )


def is_above_price(
    value: float,
    reference: float,
    *,
    relative_tolerance: float = 1e-12,
    absolute_tolerance: float = 1e-8,
) -> bool:
    tolerance = max(
        absolute_tolerance,
        abs(float(reference)) * relative_tolerance,
    )
    return float(value) > float(reference) + tolerance
