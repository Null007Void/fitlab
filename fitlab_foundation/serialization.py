"""Bounded canonical JSON serialization for immutable FitLab contracts."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from .validation import ValidationError

MAX_DEPTH = 64
MAX_CONTAINER_ITEMS = 10_000
MAX_TOTAL_NODES = 100_000
MAX_TEXT_CHARACTERS = 10_000
MAX_INTEGER_MAGNITUDE = 10**35
MAX_DECIMAL_DIGITS = 100
MAX_DECIMAL_TEXT_CHARACTERS = 256
MAX_DECIMAL_MAGNITUDE = Decimal("1E+35")
MAX_SERIALIZED_BYTES = 256 * 1024


def _validated_text(value: str, field: str = "serialization") -> str:
    if len(value) > MAX_TEXT_CHARACTERS:
        raise ValidationError("TEXT_TOO_LONG", field, f"maximum {MAX_TEXT_CHARACTERS} characters")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("INVALID_UNICODE", field, "text must encode as strict UTF-8") from exc
    return value


def _canonical_decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValidationError("NON_FINITE", "serialization", "non-finite Decimal is forbidden")
    sign, digits, exponent = value.as_tuple()
    if not any(digits):
        return "0"
    if len(digits) > MAX_DECIMAL_DIGITS or value.copy_abs() > MAX_DECIMAL_MAGNITUDE:
        raise ValidationError("OUT_OF_RANGE", "serialization", "Decimal exceeds canonical serialization bounds")
    if exponent >= 0:
        expanded_length = len(digits) + exponent
    else:
        point = len(digits) + exponent
        expanded_length = len(digits) + 1 if point > 0 else 2 + (-point) + len(digits)
    if sign:
        expanded_length += 1
    if expanded_length > MAX_DECIMAL_TEXT_CHARACTERS:
        raise ValidationError("OUT_OF_RANGE", "serialization", "Decimal expansion exceeds canonical text bound")

    digit_text = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        text = digit_text + ("0" * exponent)
    else:
        point = len(digit_text) + exponent
        if point <= 0:
            text = "0." + ("0" * (-point)) + digit_text
        else:
            text = digit_text[:point] + "." + digit_text[point:]
        text = text.rstrip("0").rstrip(".")
    return ("-" if sign else "") + text


def _to_primitive(value: Any, *, depth: int, active: set[int], nodes: list[int]) -> Any:
    if depth > MAX_DEPTH:
        raise ValidationError("MAX_DEPTH_EXCEEDED", "serialization", f"maximum depth is {MAX_DEPTH}")
    nodes[0] += 1
    if nodes[0] > MAX_TOTAL_NODES:
        raise ValidationError("MAX_ITEMS_EXCEEDED", "serialization", f"maximum total nodes is {MAX_TOTAL_NODES}")

    if isinstance(value, Enum):
        return _to_primitive(value.value, depth=depth + 1, active=active, nodes=nodes)
    if type(value) is Decimal:
        return _canonical_decimal_text(value)
    if type(value) is str:
        return _validated_text(value)
    if type(value) is bool or value is None:
        return value
    if type(value) is int:
        if value < -MAX_INTEGER_MAGNITUDE or value > MAX_INTEGER_MAGNITUDE:
            raise ValidationError("OUT_OF_RANGE", "serialization", "integer exceeds canonical serialization bound")
        return value

    is_dc = is_dataclass(value) and not isinstance(value, type)
    is_sequence = type(value) in {tuple, list}
    is_mapping = type(value) is dict
    if is_dc or is_sequence or is_mapping:
        identity = id(value)
        if identity in active:
            raise ValidationError("CYCLE_DETECTED", "serialization", "cyclic object graph is forbidden")
        active.add(identity)
        try:
            if is_dc:
                dataclass_fields = fields(value)
                if len(dataclass_fields) > MAX_CONTAINER_ITEMS:
                    raise ValidationError("MAX_ITEMS_EXCEEDED", "serialization", "dataclass has too many fields")
                return {
                    field.name: _to_primitive(
                        getattr(value, field.name), depth=depth + 1, active=active, nodes=nodes
                    )
                    for field in dataclass_fields
                }
            if is_sequence:
                if len(value) > MAX_CONTAINER_ITEMS:
                    raise ValidationError("MAX_ITEMS_EXCEEDED", "serialization", "sequence has too many items")
                return [
                    _to_primitive(item, depth=depth + 1, active=active, nodes=nodes)
                    for item in value
                ]
            if len(value) > MAX_CONTAINER_ITEMS:
                raise ValidationError("MAX_ITEMS_EXCEEDED", "serialization", "mapping has too many items")
            if not all(type(key) is str for key in value):
                raise ValidationError("INVALID_TYPE", "serialization", "JSON object keys must be strings")
            validated_keys = [_validated_text(key, "serialization.key") for key in value]
            return {
                key: _to_primitive(value[key], depth=depth + 1, active=active, nodes=nodes)
                for key in sorted(validated_keys)
            }
        finally:
            active.remove(identity)

    raise ValidationError("UNSUPPORTED_TYPE", "serialization", f"cannot serialize {type(value).__name__}")


def to_primitive(value: Any) -> Any:
    return _to_primitive(value, depth=0, active=set(), nodes=[0])


def canonical_json(value: Any) -> str:
    try:
        encoder = json.JSONEncoder(
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        chunks: list[str] = []
        encoded_bytes = 0
        for chunk in encoder.iterencode(to_primitive(value)):
            encoded_bytes += len(chunk.encode("utf-8", errors="strict"))
            if encoded_bytes > MAX_SERIALIZED_BYTES:
                raise ValidationError(
                    "OUTPUT_TOO_LARGE",
                    "serialization",
                    f"maximum canonical UTF-8 output is {MAX_SERIALIZED_BYTES} bytes",
                )
            chunks.append(chunk)
        return "".join(chunks)
    except ValidationError:
        raise
    except (RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise ValidationError("SERIALIZATION_FAILED", "serialization", "bounded canonical JSON conversion failed") from exc
