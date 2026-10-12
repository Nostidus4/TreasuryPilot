"""Strict, float-free representation and conversion helpers for money."""

from __future__ import annotations

import re
from typing import Any

from pydantic_core import CoreSchema, core_schema

_DECIMAL_AMOUNT = re.compile(r"^(?P<whole>[0-9]+)(?:\.(?P<fraction>[0-9]+))?$")
_INTEGER_AMOUNT = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MAX_ASSET_DECIMALS = 255


def _validate_decimals(decimals: int) -> int:
    if isinstance(decimals, bool) or not isinstance(decimals, int):
        raise TypeError("decimals must be an integer")
    if not 0 <= decimals <= _MAX_ASSET_DECIMALS:
        raise ValueError(f"decimals must be between 0 and {_MAX_ASSET_DECIMALS}")
    return decimals


class BaseUnits(int):
    """A non-negative integer amount in an asset's smallest denomination.

    Construction is deliberately strict: callers cannot pass strings, booleans,
    decimals, or floats and rely on implicit coercion. Use :meth:`parse` at a
    text boundary instead.
    """

    __slots__ = ()

    def __new__(cls, value: int) -> BaseUnits:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("BaseUnits requires an integer; implicit conversion is forbidden")
        if value < 0:
            raise ValueError("BaseUnits cannot be negative")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, value: str, decimals: int) -> BaseUnits:
        """Parse a non-negative decimal asset amount into integer base units."""

        return parse_base_units(value, decimals)

    def format(self, decimals: int, *, trim_trailing_zeros: bool = False) -> str:
        """Format this amount without loss at the asset's declared precision."""

        return format_base_units(self, decimals, trim_trailing_zeros=trim_trailing_zeros)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Any,
    ) -> CoreSchema:
        def from_integer(value: int) -> BaseUnits:
            return cls(value)

        def from_json_string(value: str) -> BaseUnits:
            if _INTEGER_AMOUNT.fullmatch(value) is None:
                raise ValueError(
                    "BaseUnits JSON value must be a canonical non-negative integer string"
                )
            return cls(int(value))

        python_schema = core_schema.chain_schema(
            [
                core_schema.int_schema(strict=True),
                core_schema.no_info_plain_validator_function(from_integer),
            ]
        )
        json_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(strict=True),
                core_schema.no_info_plain_validator_function(from_json_string),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=json_schema,
            python_schema=python_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: str(int(value)),
                info_arg=False,
                return_schema=core_schema.str_schema(),
                when_used="json",
            ),
        )


def parse_base_units(value: str, decimals: int) -> BaseUnits:
    """Convert decimal text to base units exactly.

    Scientific notation, signs, whitespace and precision beyond ``decimals``
    are rejected so an amount is never silently rounded.
    """

    scale = _validate_decimals(decimals)
    if not isinstance(value, str):
        raise TypeError("amount must be a string")

    match = _DECIMAL_AMOUNT.fullmatch(value)
    if match is None:
        raise ValueError("amount must be non-negative decimal text")

    fraction = match.group("fraction") or ""
    if len(fraction) > scale:
        raise ValueError(f"amount has more than {scale} decimal places")

    whole = int(match.group("whole"))
    padded_fraction = fraction.ljust(scale, "0")
    fraction_units = int(padded_fraction) if padded_fraction else 0
    return BaseUnits(whole * (10**scale) + fraction_units)


def format_base_units(
    value: BaseUnits,
    decimals: int,
    *,
    trim_trailing_zeros: bool = False,
) -> str:
    """Convert base units to exact decimal text without using a float."""

    scale = _validate_decimals(decimals)
    if not isinstance(value, BaseUnits):
        raise TypeError("value must be BaseUnits")

    if scale == 0:
        return str(int(value))

    divisor = 10**scale
    whole, fraction = divmod(int(value), divisor)
    fraction_text = f"{fraction:0{scale}d}"
    if trim_trailing_zeros:
        fraction_text = fraction_text.rstrip("0")
        if not fraction_text:
            return str(whole)
    return f"{whole}.{fraction_text}"
