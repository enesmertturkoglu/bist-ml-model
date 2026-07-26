"""Date-effective BIST price-step and upper-limit calculations for D021/D022.

No price-step tariff is embedded here. Callers must supply a table whose source
has been verified; an absent rule is an explicit review state, never a guessed
tick size.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Iterable

import pandas as pd


class PriceStepRuleError(ValueError):
    """Raised when a price-step table is invalid or ambiguous."""


def _decimal(value: Decimal | float | int | str) -> Decimal:
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise PriceStepRuleError(f"non-finite decimal value: {value!r}")
    return result


def _date(value: date | str | pd.Timestamp) -> date:
    return pd.Timestamp(value).date()


@dataclass(frozen=True)
class PriceStepRule:
    """One date-and-price interval from an externally verified tariff.

    Price bands are ``min_price <= price < max_price``. A missing
    ``effective_to`` or ``max_price`` means that interval has no upper bound.
    """

    effective_from: date | str | pd.Timestamp
    effective_to: date | str | pd.Timestamp | None
    min_price: Decimal | float | int | str
    max_price: Decimal | float | int | str | None
    price_step: Decimal | float | int | str

    def __post_init__(self) -> None:
        start = _date(self.effective_from)
        end = _date(self.effective_to) if self.effective_to is not None else None
        lower = _decimal(self.min_price)
        upper = _decimal(self.max_price) if self.max_price is not None else None
        step = _decimal(self.price_step)
        if end is not None and end < start:
            raise PriceStepRuleError("effective_to cannot precede effective_from")
        if lower < 0:
            raise PriceStepRuleError("min_price cannot be negative")
        if upper is not None and upper <= lower:
            raise PriceStepRuleError("max_price must be greater than min_price")
        if step <= 0:
            raise PriceStepRuleError("price_step must be positive")
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_to", end)
        object.__setattr__(self, "min_price", lower)
        object.__setattr__(self, "max_price", upper)
        object.__setattr__(self, "price_step", step)

    def matches(self, trade_date: date, price: Decimal) -> bool:
        in_date = self.effective_from <= trade_date and (
            self.effective_to is None or trade_date <= self.effective_to
        )
        in_price = self.min_price <= price and (
            self.max_price is None or price < self.max_price
        )
        return in_date and in_price

    def to_dict(self) -> dict[str, str | None]:
        return {
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "min_price": str(self.min_price),
            "max_price": str(self.max_price) if self.max_price is not None else None,
            "price_step": str(self.price_step),
        }


class PriceStepTable:
    """Resolve one unambiguous tick size for a date and nominal price."""

    def __init__(self, rules: Iterable[PriceStepRule] = ()) -> None:
        self.rules = tuple(rules)

    @classmethod
    def from_csv(cls, path: str | Path) -> "PriceStepTable":
        frame = pd.read_csv(path, dtype="string")
        required = {
            "effective_from",
            "effective_to",
            "min_price",
            "max_price",
            "price_step",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise PriceStepRuleError(
                f"price-step table fields missing: {sorted(missing)}"
            )
        rules = []
        for row in frame.to_dict(orient="records"):
            rules.append(
                PriceStepRule(
                    effective_from=str(row["effective_from"]),
                    effective_to=(
                        None if pd.isna(row["effective_to"]) else str(row["effective_to"])
                    ),
                    min_price=str(row["min_price"]),
                    max_price=(
                        None if pd.isna(row["max_price"]) else str(row["max_price"])
                    ),
                    price_step=str(row["price_step"]),
                )
            )
        return cls(rules)

    def resolve(
        self,
        trade_date: date | str | pd.Timestamp,
        nominal_price: Decimal | float | int | str,
    ) -> Decimal | None:
        resolved_date = _date(trade_date)
        price = _decimal(nominal_price)
        matches = [rule for rule in self.rules if rule.matches(resolved_date, price)]
        if len(matches) > 1:
            raise PriceStepRuleError(
                f"ambiguous price-step rules for {resolved_date.isoformat()} at {price}"
            )
        return matches[0].price_step if matches else None

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
    raw_upper_limit: float
    price_step: float
    estimated_upper_limit: float


def floor_to_price_step(
    price: Decimal | float | int | str,
    price_step: Decimal | float | int | str,
) -> Decimal:
    """Round inward/down to the greatest valid price-step multiple."""

    value = _decimal(price)
    step = _decimal(price_step)
    if value < 0 or step <= 0:
        raise ValueError("price must be non-negative and price_step positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def calculate_upper_limit(
    previous_close: float | int,
    trade_date: date | str | pd.Timestamp,
    price_steps: PriceStepTable,
    *,
    margin: float = 0.10,
) -> PriceLimitComputation | None:
    """Calculate the standard-share upper limit or return ``None`` without a rule."""

    raw_value = calculate_raw_upper_limit(previous_close, margin=margin)
    if raw_value is None:
        return None
    raw_limit = _decimal(raw_value)
    step = price_steps.resolve(trade_date, raw_limit)
    if step is None:
        return None
    estimated = floor_to_price_step(raw_limit, step)
    return PriceLimitComputation(
        raw_upper_limit=float(raw_limit),
        price_step=float(step),
        estimated_upper_limit=float(estimated),
    )


def calculate_raw_upper_limit(
    previous_close: float | int,
    *,
    margin: float = 0.10,
) -> float | None:
    """Calculate the unrounded standard margin even when no tick rule is available."""

    if not math.isfinite(float(previous_close)) or float(previous_close) <= 0:
        return None
    base = _decimal(previous_close)
    return float(base * (Decimal("1") + _decimal(margin)))


def prices_equal(
    left: float,
    right: float,
    *,
    relative_tolerance: float = 1e-12,
    absolute_tolerance: float = 1e-8,
) -> bool:
    """Compare prices with numerical-noise tolerance, never a full tick."""

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
