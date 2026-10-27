"""Exact byte-unit arithmetic. No binary floating point is accepted."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .arithmetic import exact_divide
from .validation import MAX_BYTES, MAX_PARAMETERS, ValidationError, exact_decimal, exact_int

DECIMAL_GB_BYTES = Decimal(10**9)
BINARY_GIB_BYTES = Decimal(2**30)
SUPPORTED_WEIGHT_BITS = frozenset(
    {Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"), Decimal("6"), Decimal("8"), Decimal("16"), Decimal("32")}
)


def _exact_nonnegative_bytes(value: Any, field: str = "bytes") -> Decimal:
    if type(value) is int:
        exact_int(value, field, minimum=0, maximum=MAX_BYTES)
        return Decimal(value)
    if type(value) is Decimal:
        return exact_decimal(
            value,
            field,
            minimum=Decimal("0"),
            maximum=Decimal(MAX_BYTES),
            minimum_inclusive=True,
        )
    raise ValidationError("INVALID_TYPE", field, "expected exact int or decimal.Decimal")


def bytes_to_gb(value: int | Decimal) -> Decimal:
    return exact_divide(_exact_nonnegative_bytes(value), 1_000_000_000)


def bytes_to_gib(value: int | Decimal) -> Decimal:
    return exact_divide(_exact_nonnegative_bytes(value), 1 << 30)


def idealized_weight_payload_bytes(parameters: int, bits_per_weight: Decimal) -> Decimal:
    exact_int(parameters, "parameters", minimum=1, maximum=MAX_PARAMETERS)
    exact_decimal(bits_per_weight, "bits_per_weight", minimum=Decimal("0"), maximum=Decimal("64"))
    if bits_per_weight not in SUPPORTED_WEIGHT_BITS:
        raise ValidationError("UNSUPPORTED_PRECISION", "bits_per_weight", "precision is not in the supported explicit set")
    return exact_divide(parameters * int(bits_per_weight), 8)
