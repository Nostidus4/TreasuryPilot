from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from treasurypilot_core.money import BaseUnits, format_base_units, parse_base_units


@pytest.mark.parametrize("invalid", [1.0, 0.0, True, "1", None])
def test_base_units_rejects_implicit_conversion(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        BaseUnits(invalid)  # type: ignore[arg-type]


def test_base_units_rejects_negative_integer() -> None:
    with pytest.raises(ValueError, match="negative"):
        BaseUnits(-1)


@pytest.mark.parametrize(
    ("text", "decimals", "expected"),
    [
        ("0.000001", 6, BaseUnits(1)),
        ("123456789012.654321", 6, BaseUnits(123_456_789_012_654_321)),
        ("0.000000000000000001", 18, BaseUnits(1)),
        (
            "123456789012345678.123456789012345678",
            18,
            BaseUnits(123_456_789_012_345_678_123_456_789_012_345_678),
        ),
    ],
)
def test_parse_and_format_round_trip_exactly(text: str, decimals: int, expected: BaseUnits) -> None:
    amount = parse_base_units(text, decimals)

    assert amount == expected
    assert format_base_units(amount, decimals) == text
    assert BaseUnits.parse(text, decimals).format(decimals) == text


@pytest.mark.parametrize(
    "text",
    ["-1", "+1", " 1", "1 ", "1e6", ".1", "1.", "1,000", "NaN", "Infinity"],
)
def test_parse_rejects_non_plain_or_negative_decimal_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_base_units(text, 6)


def test_parse_rejects_precision_that_would_require_rounding() -> None:
    with pytest.raises(ValueError, match="more than 6"):
        parse_base_units("1.0000001", 6)


@pytest.mark.parametrize("decimals", [-1, 256, True, 1.5])
def test_invalid_asset_decimals_are_rejected(decimals: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_base_units("1", decimals)  # type: ignore[arg-type]


def test_format_can_trim_display_only_zeroes_without_losing_value() -> None:
    amount = BaseUnits(1_230_000)

    assert format_base_units(amount, 6) == "1.230000"
    assert format_base_units(amount, 6, trim_trailing_zeros=True) == "1.23"
    assert format_base_units(BaseUnits(1_000_000), 6, trim_trailing_zeros=True) == "1"


def test_pydantic_serializes_base_units_as_a_decimal_string() -> None:
    adapter = TypeAdapter(BaseUnits)

    assert adapter.dump_json(BaseUnits(123)) == b'"123"'
    assert adapter.validate_json(b'"123"') == BaseUnits(123)


@pytest.mark.parametrize("payload", [b"1.5", b"1", b'"01"', b'"-1"'])
def test_pydantic_json_rejects_noncanonical_amounts(payload: bytes) -> None:
    adapter = TypeAdapter(BaseUnits)

    with pytest.raises(ValidationError):
        adapter.validate_json(payload)
