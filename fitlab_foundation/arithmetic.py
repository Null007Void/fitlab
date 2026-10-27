"""Ambient-context-independent exact decimal arithmetic.

All public numeric contracts reject floats. These helpers convert accepted integers
and Decimals to rational numbers, perform exact operations with Python integers,
and convert back only when the denominator has a finite base-10 representation.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from .validation import ValidationError


def _as_fraction(value: int | Decimal) -> Fraction:
    if type(value) is int:
        return Fraction(value, 1)
    if type(value) is not Decimal or not value.is_finite():
        raise ValidationError("INVALID_TYPE", "arithmetic.operand", "expected finite exact int or Decimal")
    sign, digits, exponent = value.as_tuple()
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    if sign:
        coefficient = -coefficient
    if exponent >= 0:
        return Fraction(coefficient * (10**exponent), 1)
    return Fraction(coefficient, 10 ** (-exponent))


def _finite_decimal(value: Fraction) -> Decimal:
    numerator = value.numerator
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValidationError("NON_TERMINATING_DECIMAL", "arithmetic.result", "result has no finite base-10 form")
    scale = max(twos, fives)
    coefficient = numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    sign = 1 if coefficient < 0 else 0
    digit_text = str(abs(coefficient))
    digits = tuple(int(char) for char in digit_text)
    return Decimal((sign, digits, -scale))


def exact_add(left: int | Decimal, right: int | Decimal) -> Decimal:
    return _finite_decimal(_as_fraction(left) + _as_fraction(right))


def exact_subtract(left: int | Decimal, right: int | Decimal) -> Decimal:
    return _finite_decimal(_as_fraction(left) - _as_fraction(right))


def exact_multiply(left: int | Decimal, right: int | Decimal) -> Decimal:
    return _finite_decimal(_as_fraction(left) * _as_fraction(right))


def exact_divide(numerator: int | Decimal, denominator: int | Decimal) -> Decimal:
    divisor = _as_fraction(denominator)
    if divisor == 0:
        raise ValidationError("DIVISION_BY_ZERO", "arithmetic.denominator", "denominator must not be zero")
    return _finite_decimal(_as_fraction(numerator) / divisor)
