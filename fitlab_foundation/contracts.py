"""Typed, immutable contracts for deterministic FitLab requirements calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from .validation import (
    MAX_BYTES,
    MAX_DIMENSION,
    MAX_PARAMETERS,
    MAX_SEQUENCES,
    ValidationError,
    exact_enum,
    exact_int,
    nonempty_text,
    optional_exact_decimal,
    optional_exact_int,
)


class ResultStatus(Enum):
    CALCULATED = "CALCULATED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class ReasonCode(Enum):
    MISSING_METADATA = "MISSING_METADATA"
    UNSUPPORTED_ARCHITECTURE = "UNSUPPORTED_ARCHITECTURE"
    UNSUPPORTED_ATTENTION = "UNSUPPORTED_ATTENTION"
    EXPLICIT_ASSUMPTION_REQUIRED = "EXPLICIT_ASSUMPTION_REQUIRED"
    EFFECTIVE_BANDWIDTH_UNKNOWN = "EFFECTIVE_BANDWIDTH_UNKNOWN"
    RUNTIME_OVERHEAD_UNKNOWN = "RUNTIME_OVERHEAD_UNKNOWN"
    MEASURED_HEADROOM_UNAVAILABLE = "MEASURED_HEADROOM_UNAVAILABLE"
    PHYSICAL_FEASIBILITY_NOT_MODELED = "PHYSICAL_FEASIBILITY_NOT_MODELED"
    DEPENDENCY_UNKNOWN = "DEPENDENCY_UNKNOWN"
    ARITHMETIC_BOUND_EXCEEDED = "ARITHMETIC_BOUND_EXCEEDED"
    INCOMPATIBLE_DIMENSION = "INCOMPATIBLE_DIMENSION"
    UNVERIFIED_PROVENANCE = "UNVERIFIED_PROVENANCE"


class ArchitectureKind(Enum):
    DENSE_DECODER = "DENSE_DECODER"
    MOE_DECODER = "MOE_DECODER"
    UNKNOWN = "UNKNOWN"


class AttentionMechanism(Enum):
    UNKNOWN = "UNKNOWN"
    STANDARD_FULL = "STANDARD_FULL"
    SLIDING_WINDOW = "SLIDING_WINDOW"
    MLA = "MLA"
    PAGED = "PAGED"
    OFFLOADED = "OFFLOADED"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class Reason:
    code: ReasonCode
    detail: str

    def __post_init__(self) -> None:
        exact_enum(self.code, ReasonCode, "reason.code")
        nonempty_text(self.detail, "reason.detail")


@dataclass(frozen=True, slots=True)
class FormulaProvenance:
    identifier: str
    version: str
    expression: str

    def __post_init__(self) -> None:
        nonempty_text(self.identifier, "formula.identifier", maximum_length=200)
        nonempty_text(self.version, "formula.version", maximum_length=50)
        nonempty_text(self.expression, "formula.expression")


@dataclass(frozen=True, slots=True)
class ModelArchitecture:
    model_id: str
    total_parameters: int
    active_parameters: int | None = None
    layers: int | None = None
    query_heads: int | None = None
    kv_heads: int | None = None
    head_dimension: int | None = None
    architecture_kind: ArchitectureKind = ArchitectureKind.UNKNOWN
    attention_mechanism: AttentionMechanism = AttentionMechanism.UNKNOWN

    def __post_init__(self) -> None:
        nonempty_text(self.model_id, "model_id", maximum_length=300)
        exact_int(self.total_parameters, "total_parameters", minimum=1, maximum=MAX_PARAMETERS)
        optional_exact_int(self.active_parameters, "active_parameters", minimum=1, maximum=MAX_PARAMETERS)
        optional_exact_int(self.layers, "layers", minimum=1, maximum=100_000)
        optional_exact_int(self.query_heads, "query_heads", minimum=1, maximum=1_000_000)
        optional_exact_int(self.kv_heads, "kv_heads", minimum=1, maximum=1_000_000)
        optional_exact_int(self.head_dimension, "head_dimension", minimum=1, maximum=MAX_DIMENSION)
        exact_enum(self.architecture_kind, ArchitectureKind, "architecture_kind")
        exact_enum(self.attention_mechanism, AttentionMechanism, "attention_mechanism")
        if self.active_parameters is not None and self.active_parameters > self.total_parameters:
            raise ValidationError("INCONSISTENT", "active_parameters", "must not exceed total_parameters")
        if self.query_heads is not None and self.kv_heads is not None and self.kv_heads > self.query_heads:
            raise ValidationError("INCONSISTENT", "kv_heads", "must not exceed query_heads")


@dataclass(frozen=True, slots=True)
class Workload:
    resident_sequences: int = 1
    cached_tokens_per_sequence: int | None = None
    kv_bytes_per_element: int | None = None
    target_tokens_per_second: Decimal | None = None
    declared_bytes_reloaded_per_token: int | None = None
    residency_assumption: str | None = None

    def __post_init__(self) -> None:
        exact_int(self.resident_sequences, "resident_sequences", minimum=1, maximum=MAX_SEQUENCES)
        optional_exact_int(self.cached_tokens_per_sequence, "cached_tokens_per_sequence", minimum=1, maximum=MAX_DIMENSION)
        optional_exact_int(self.kv_bytes_per_element, "kv_bytes_per_element", minimum=1, maximum=8)
        if self.kv_bytes_per_element is not None and self.kv_bytes_per_element not in {1, 2, 4, 8}:
            raise ValidationError("UNSUPPORTED_PRECISION", "kv_bytes_per_element", "supported values are 1, 2, 4, 8")
        optional_exact_decimal(self.target_tokens_per_second, "target_tokens_per_second")
        optional_exact_int(
            self.declared_bytes_reloaded_per_token,
            "declared_bytes_reloaded_per_token",
            minimum=1,
            maximum=MAX_BYTES,
        )
        if self.residency_assumption is not None:
            nonempty_text(self.residency_assumption, "residency_assumption")


@dataclass(frozen=True, slots=True)
class HardwareResources:
    host_ram_bytes: int | None = None
    measured_available_host_bytes: int | None = None
    accelerator_dedicated_bytes: int | None = None
    unified_shared_memory_bytes: int | None = None
    effective_memory_bandwidth_bytes_per_second: Decimal | None = None

    def __post_init__(self) -> None:
        optional_exact_int(self.host_ram_bytes, "host_ram_bytes", minimum=1, maximum=MAX_BYTES)
        optional_exact_int(self.measured_available_host_bytes, "measured_available_host_bytes", minimum=0, maximum=MAX_BYTES)
        optional_exact_int(self.accelerator_dedicated_bytes, "accelerator_dedicated_bytes", minimum=0, maximum=MAX_BYTES)
        optional_exact_int(self.unified_shared_memory_bytes, "unified_shared_memory_bytes", minimum=1, maximum=MAX_BYTES)
        optional_exact_decimal(
            self.effective_memory_bandwidth_bytes_per_second,
            "effective_memory_bandwidth_bytes_per_second",
            maximum=Decimal(MAX_BYTES),
        )
        if (
            self.host_ram_bytes is not None
            and self.measured_available_host_bytes is not None
            and self.measured_available_host_bytes > self.host_ram_bytes
        ):
            raise ValidationError("INCONSISTENT", "measured_available_host_bytes", "must not exceed host RAM")
        if (
            self.host_ram_bytes is not None
            and self.unified_shared_memory_bytes is not None
            and self.unified_shared_memory_bytes > self.host_ram_bytes
        ):
            raise ValidationError("INCONSISTENT", "unified_shared_memory_bytes", "shared memory must be a subset of host RAM")

    def independent_physical_capacity_bytes(self) -> int | None:
        """Return only independent pools; unified shared memory is never added twice."""
        if self.host_ram_bytes is None and self.accelerator_dedicated_bytes is None:
            return None
        return (self.host_ram_bytes or 0) + (self.accelerator_dedicated_bytes or 0)


@dataclass(frozen=True, slots=True)
class CalculationResult:
    name: str
    status: ResultStatus
    value: int | Decimal | None = None
    unit: str | None = None
    formula: FormulaProvenance | None = None
    reasons: tuple[Reason, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        nonempty_text(self.name, "result.name")
        exact_enum(self.status, ResultStatus, "result.status")
        if self.value is not None:
            if type(self.value) is int:
                if self.value < 0 or self.value > MAX_BYTES * MAX_DIMENSION:
                    raise ValidationError("OUT_OF_RANGE", "result.value", "integer result out of bounds")
            elif type(self.value) is Decimal:
                decimal_tuple = self.value.as_tuple()
                if not self.value.is_finite():
                    raise ValidationError("NON_FINITE", "result.value", "result decimal must be finite")
                if self.value < 0:
                    raise ValidationError("OUT_OF_RANGE", "result.value", "result decimal must be nonnegative")
                if (
                    len(decimal_tuple.digits) > 100
                    or decimal_tuple.exponent < -18
                    or decimal_tuple.exponent > 35
                    or self.value > Decimal("1E+35")
                ):
                    raise ValidationError("OUT_OF_RANGE", "result.value", "decimal result exceeds complexity or magnitude bounds")
            else:
                raise ValidationError("INVALID_TYPE", "result.value", "expected exact int or Decimal")
        if type(self.reasons) is not tuple:
            raise ValidationError("INVALID_TYPE", "result.reasons", "expected tuple")
        for reason in self.reasons:
            if type(reason) is not Reason:
                raise ValidationError("INVALID_TYPE", "result.reasons", "expected Reason values")
        for field_name, values in (("assumptions", self.assumptions), ("limitations", self.limitations)):
            if type(values) is not tuple:
                raise ValidationError("INVALID_TYPE", f"result.{field_name}", "expected tuple")
            for value in values:
                nonempty_text(value, f"result.{field_name}")
        if self.status in {ResultStatus.CALCULATED, ResultStatus.ESTIMATED}:
            if self.value is None or self.unit is None or self.formula is None:
                raise ValidationError("INCOMPLETE_RESULT", "result", "numeric result requires value, unit, and formula")
            nonempty_text(self.unit, "result.unit")
            if type(self.formula) is not FormulaProvenance:
                raise ValidationError("INVALID_TYPE", "result.formula", "expected FormulaProvenance")
        else:
            if self.value is not None or self.unit is not None or self.formula is not None:
                raise ValidationError("INCONSISTENT", "result", "unknown/unavailable result must not contain a numeric claim")
            if not self.reasons:
                raise ValidationError("INCOMPLETE_RESULT", "result.reasons", "unknown/unavailable result requires a reason")

    @classmethod
    def calculated(
        cls,
        name: str,
        value: int | Decimal,
        unit: str,
        formula: FormulaProvenance,
        *,
        assumptions: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> "CalculationResult":
        return cls(name, ResultStatus.CALCULATED, value, unit, formula, (), assumptions, limitations)

    @classmethod
    def estimated(
        cls,
        name: str,
        value: int | Decimal,
        unit: str,
        formula: FormulaProvenance,
        *,
        assumptions: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> "CalculationResult":
        return cls(name, ResultStatus.ESTIMATED, value, unit, formula, (), assumptions, limitations)

    @classmethod
    def unknown(cls, name: str, reasons: tuple[Reason, ...]) -> "CalculationResult":
        return cls(name=name, status=ResultStatus.UNKNOWN, reasons=reasons)

    @classmethod
    def unavailable(cls, name: str, reasons: tuple[Reason, ...]) -> "CalculationResult":
        return cls(name=name, status=ResultStatus.UNAVAILABLE, reasons=reasons)
