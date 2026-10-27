"""Strict validation helpers for FitLab's deterministic contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

MAX_PARAMETERS = 10**15
MAX_DIMENSION = 10**7
MAX_SEQUENCES = 10**6
MAX_BYTES = 10**21
MAX_RATE = Decimal("1000000000")


class ValidationError(ValueError):
    """Machine-readable validation failure without numeric coercion."""

    def __init__(self, code: str, field: str, message: str) -> None:
        self.code = code
        self.field = field
        self.message = message
        super().__init__(f"{code}:{field}:{message}")


def exact_int(value: Any, field: str, *, minimum: int = 1, maximum: int = MAX_DIMENSION) -> int:
    if type(value) is not int:
        raise ValidationError("INVALID_TYPE", field, "expected an exact integer")
    if value < minimum or value > maximum:
        raise ValidationError("OUT_OF_RANGE", field, f"expected {minimum}..{maximum}")
    return value


def optional_exact_int(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = MAX_DIMENSION,
) -> int | None:
    if value is None:
        return None
    return exact_int(value, field, minimum=minimum, maximum=maximum)


def exact_decimal(
    value: Any,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal = MAX_RATE,
    minimum_inclusive: bool = False,
) -> Decimal:
    if type(value) is not Decimal:
        raise ValidationError("INVALID_TYPE", field, "expected decimal.Decimal")
    if not value.is_finite():
        raise ValidationError("NON_FINITE", field, "NaN and Infinity are forbidden")
    decimal_tuple = value.as_tuple()
    if len(decimal_tuple.digits) > 100 or decimal_tuple.exponent < -18 or decimal_tuple.exponent > 18:
        raise ValidationError("DECIMAL_COMPLEXITY", field, "maximum 100 digits and exponent range -18..18")
    too_small = value < minimum if minimum_inclusive else value <= minimum
    if too_small or value > maximum:
        relation = ">=" if minimum_inclusive else ">"
        raise ValidationError("OUT_OF_RANGE", field, f"expected {relation} {minimum} and <= {maximum}")
    return value


def optional_exact_decimal(
    value: Any,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal = MAX_RATE,
    minimum_inclusive: bool = False,
) -> Decimal | None:
    if value is None:
        return None
    return exact_decimal(
        value,
        field,
        minimum=minimum,
        maximum=maximum,
        minimum_inclusive=minimum_inclusive,
    )


def nonempty_text(value: Any, field: str, *, maximum_length: int = 4096) -> str:
    if type(value) is not str:
        raise ValidationError("INVALID_TYPE", field, "expected string")
    if not value.strip():
        raise ValidationError("EMPTY", field, "must not be blank")
    if len(value) > maximum_length:
        raise ValidationError("OUT_OF_RANGE", field, f"maximum length is {maximum_length}")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("INVALID_UNICODE", field, "must encode as strict UTF-8") from exc
    return value


def exact_enum(value: Any, enum_type: type, field: str):
    if type(value) is not enum_type:
        raise ValidationError("INVALID_TYPE", field, f"expected {enum_type.__name__}")
    return value
