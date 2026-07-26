from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from src.data.price_limits import (
    REFERENCE_COLUMNS,
    PriceStepRule,
    PriceStepRuleError,
    PriceStepTable,
    calculate_raw_upper_limit,
    calculate_upper_limit,
    floor_to_price_step,
)


REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "reference_data"
    / "bist_equity_tick_sizes_v1.csv"
)
SOURCE_CHECKSUM = "cb0a1e0091d799186e9ae67b7badc8483f2166d9b66ed03c7bd55e205a0702d3"


@pytest.fixture(scope="module")
def table() -> PriceStepTable:
    return PriceStepTable.from_csv(REFERENCE_PATH)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("19.999", "0.01"),
        ("20", "0.02"),
        ("49.999", "0.02"),
        ("50", "0.05"),
        ("99.999", "0.05"),
        ("100", "0.10"),
        ("249.999", "0.10"),
        ("250", "0.25"),
        ("499.999", "0.25"),
        ("500", "0.50"),
        ("999.999", "0.50"),
        ("1000", "1.00"),
        ("2499.999", "1.00"),
        ("2500", "2.50"),
    ],
)
def test_current_regime_boundaries(
    table: PriceStepTable, price: str, expected: str
) -> None:
    assert table.resolve("2024-01-02", price) == Decimal(expected)


@pytest.mark.parametrize(
    ("trade_date", "price", "expected"),
    [
        ("2020-03-13", "250", "0.10"),
        ("2023-11-05", "250", "0.10"),
        ("2023-11-05", "2500", "0.10"),
        ("2023-11-06", "250", "0.25"),
        ("2023-11-06", "2500", "2.50"),
    ],
)
def test_date_effective_regime_switch(
    table: PriceStepTable, trade_date: str, price: str, expected: str
) -> None:
    assert table.resolve(trade_date, price) == Decimal(expected)


def test_before_scoped_model_period_is_unavailable(table: PriceStepTable) -> None:
    assert table.resolve("2020-03-12", "10") is None


@pytest.mark.parametrize("instrument_type", ["FUND", "WARRANT", ""])
def test_non_equity_or_unknown_instrument_is_unavailable(
    table: PriceStepTable, instrument_type: str
) -> None:
    assert (
        table.resolve("2024-01-02", "10", instrument_type=instrument_type) is None
    )


def test_reference_file_has_required_provenance_and_version_fields() -> None:
    frame = pd.read_csv(REFERENCE_PATH, dtype="string")

    assert REFERENCE_COLUMNS.issubset(frame.columns)
    assert len(frame) == 12
    assert set(frame["rule_set_id"]) == {
        "BIST_EQUITY_PRE_20231106_V1",
        "BIST_EQUITY_FROM_20231106_V1",
    }
    assert set(frame["instrument_type"]) == {"EQUITY"}
    assert set(frame["currency"]) == {"TRY"}
    assert set(frame["official_document_number"]) == {
        "E-18454353-100.04.02-19412"
    }
    assert set(frame["official_document_date"]) == {"2023-08-28"}
    assert set(frame["official_effective_date"]) == {"2023-11-06"}
    assert set(frame["source_checksum"]) == {SOURCE_CHECKSUM}


def test_reference_has_no_price_or_date_gaps_or_overlaps(
    table: PriceStepTable,
) -> None:
    table.validate_reference_data()


@pytest.mark.parametrize("second_min", ["19", "21"])
def test_validation_rejects_price_overlap_or_gap(second_min: str) -> None:
    rules = [
        _verified_rule("ONE", "2024-01-01", None, "0.01", "20", "0.01"),
        _verified_rule("ONE", "2024-01-01", None, second_min, None, "0.02"),
    ]

    with pytest.raises(PriceStepRuleError, match="gap or overlap"):
        PriceStepTable(rules).validate_reference_data()


def test_validation_rejects_date_gap() -> None:
    rules = [
        _verified_rule("ONE", "2024-01-01", "2024-01-10", "0.01", None, "0.01"),
        _verified_rule("TWO", "2024-01-12", None, "0.01", None, "0.02"),
    ]

    with pytest.raises(PriceStepRuleError, match="date-regime gap or overlap"):
        PriceStepTable(rules).validate_reference_data()


def test_resolution_is_deterministic(table: PriceStepTable) -> None:
    first = table.resolve_rule("2024-01-02", "500")
    second = table.resolve_rule("2024-01-02", Decimal("500.000"))

    assert first == second
    assert first is not None
    assert first.rule_set_id == "BIST_EQUITY_FROM_20231106_V1"


def test_raw_upper_limit_is_exact_decimal() -> None:
    assert calculate_raw_upper_limit("1.133") == Decimal("1.24630")


def test_binary_float_input_is_converted_deterministically(
    table: PriceStepTable,
) -> None:
    result = calculate_upper_limit(0.1 + 0.2, "2024-01-02", table)

    assert result is not None
    assert result.raw_upper_limit == Decimal("0.330000000000000044")
    assert result.estimated_upper_limit == Decimal("0.33")


def test_exact_tick_multiple_is_not_changed(table: PriceStepTable) -> None:
    result = calculate_upper_limit("100", "2024-01-02", table)

    assert result is not None
    assert result.raw_upper_limit == Decimal("110.00")
    assert result.estimated_upper_limit == Decimal("110.00")


def test_decimal_flooring_uses_resolved_high_price_tick(
    table: PriceStepTable,
) -> None:
    result = calculate_upper_limit("239.1999969482422", "2024-01-08", table)

    assert result is not None
    assert result.raw_upper_limit == Decimal("263.119996643066420")
    assert result.tick_size == Decimal("0.25")
    assert result.estimated_upper_limit == Decimal("263.00")


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        ("19.999", "0.01", "19.99"),
        ("49.999", "0.02", "49.98"),
        ("99.999", "0.05", "99.95"),
        ("499.999", "0.25", "499.75"),
        ("999.999", "0.50", "999.50"),
        ("2499.999", "1.00", "2499.00"),
        ("2501.24", "2.50", "2500.00"),
    ],
)
def test_flooring_across_tick_sizes(value: str, step: str, expected: str) -> None:
    assert floor_to_price_step(value, step) == Decimal(expected)


def test_date_switch_changes_rule_metadata(table: PriceStepTable) -> None:
    old = calculate_upper_limit("227.28", "2023-11-05", table)
    new = calculate_upper_limit("227.28", "2023-11-06", table)

    assert old is not None and new is not None
    assert old.raw_upper_limit == new.raw_upper_limit == Decimal("250.0080")
    assert old.tick_size == Decimal("0.10")
    assert new.tick_size == Decimal("0.25")
    assert old.rule_set_id != new.rule_set_id


def test_non_equity_calculation_does_not_use_equity_tariff(
    table: PriceStepTable,
) -> None:
    assert (
        calculate_upper_limit(
            "100", "2024-01-02", table, instrument_type="FUND"
        )
        is None
    )


def _verified_rule(
    rule_set_id: str,
    effective_from: str,
    effective_to: str | None,
    min_price: str,
    max_price: str | None,
    step: str,
) -> PriceStepRule:
    return PriceStepRule(
        effective_from,
        effective_to,
        min_price,
        max_price,
        step,
        rule_set_id=rule_set_id,
        official_source_name="Borsa İstanbul",
        official_document_number="TEST",
        official_document_date="2023-08-28",
        official_effective_date="2023-11-06",
        official_source_url="https://example.test/source.pdf",
        source_checksum="a" * 64,
    )
