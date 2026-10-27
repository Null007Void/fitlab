"""Deterministic bidirectional planning built on the accepted F1 engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .arithmetic import exact_add, exact_subtract
from .contracts import HardwareResources, ModelArchitecture, ResultStatus, Workload
from .requirements import RequirementsBundle, RequirementsEngine
from .validation import MAX_BYTES, ValidationError, exact_int, nonempty_text


class PlanningStatus(Enum):
    COMPLETE = "COMPLETE"
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PlanningScenario:
    scenario_id: str
    model: ModelArchitecture
    workload: Workload
    weight_bits_per_parameter: Decimal
    explicit_runtime_overhead_bytes: int | None = None
    runtime_overhead_basis: str | None = None
    planning_memory_budget_bytes: int | None = None

    def __post_init__(self) -> None:
        nonempty_text(self.scenario_id, "scenario_id", maximum_length=200)
        if type(self.model) is not ModelArchitecture:
            raise ValidationError("INVALID_TYPE", "model", "expected ModelArchitecture")
        if type(self.workload) is not Workload:
            raise ValidationError("INVALID_TYPE", "workload", "expected Workload")
        if type(self.weight_bits_per_parameter) is not Decimal:
            raise ValidationError("INVALID_TYPE", "weight_bits_per_parameter", "expected Decimal")
        if not self.weight_bits_per_parameter.is_finite() or self.weight_bits_per_parameter <= 0:
            raise ValidationError("OUT_OF_RANGE", "weight_bits_per_parameter", "must be finite and positive")
        if self.explicit_runtime_overhead_bytes is not None:
            exact_int(
                self.explicit_runtime_overhead_bytes,
                "explicit_runtime_overhead_bytes",
                minimum=0,
                maximum=MAX_BYTES,
            )
        if self.runtime_overhead_basis is not None:
            nonempty_text(self.runtime_overhead_basis, "runtime_overhead_basis")
        if (self.explicit_runtime_overhead_bytes is None) != (self.runtime_overhead_basis is None):
            raise ValidationError(
                "INCONSISTENT",
                "runtime_overhead",
                "bytes and basis must be supplied together",
            )
        if self.planning_memory_budget_bytes is not None:
            exact_int(
                self.planning_memory_budget_bytes,
                "planning_memory_budget_bytes",
                minimum=0,
                maximum=MAX_BYTES,
            )


@dataclass(frozen=True, slots=True)
class WorkloadToHardwarePlan:
    scenario_id: str
    status: PlanningStatus
    minimum_declared_memory_bytes: Decimal | None
    target_compute_flops_per_second: Decimal | None
    conditional_decode_bandwidth_bytes_per_second: Decimal | None
    requirements: RequirementsBundle
    reasons: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HardwareToWorkloadPlan:
    scenario_id: str
    status: PlanningStatus
    minimum_declared_memory_bytes: Decimal | None
    planning_memory_budget_bytes: int | None
    headroom_bytes: Decimal | None
    workload_plan: WorkloadToHardwarePlan
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]


_LIMITATIONS = (
    "declared memory is idealized weights plus supported KV cache plus an explicit runtime allowance",
    "does not predict achieved throughput",
    "does not establish device compatibility, placement, thermals, or runtime availability",
)


def _numeric(result) -> Decimal | None:
    if result.status not in {ResultStatus.CALCULATED, ResultStatus.ESTIMATED}:
        return None
    return Decimal(result.value) if type(result.value) is int else result.value


def plan_workload_to_hardware(scenario: PlanningScenario) -> WorkloadToHardwarePlan:
    requirements = RequirementsEngine().evaluate(
        scenario.model,
        scenario.workload,
        HardwareResources(),
        weight_bits_per_parameter=scenario.weight_bits_per_parameter,
    )
    reasons: list[str] = []
    known_memory = _numeric(requirements.known_memory_baseline)
    if known_memory is None:
        reasons.append("known memory baseline is unavailable for this architecture or workload")
    if scenario.explicit_runtime_overhead_bytes is None:
        reasons.append("explicit runtime overhead and provenance are required")
    minimum = None
    if known_memory is not None and scenario.explicit_runtime_overhead_bytes is not None:
        minimum = exact_add(known_memory, scenario.explicit_runtime_overhead_bytes)
    compute = _numeric(requirements.target_compute_rate)
    bandwidth = _numeric(requirements.conditional_decode_bandwidth)
    if compute is None:
        reasons.append("target compute requirement is unknown")
    if bandwidth is None:
        reasons.append("conditional decode bandwidth requirement is unknown")
    status = PlanningStatus.COMPLETE if not reasons else PlanningStatus.UNKNOWN
    assumptions = ()
    if scenario.runtime_overhead_basis is not None:
        assumptions = (scenario.runtime_overhead_basis,)
    return WorkloadToHardwarePlan(
        scenario_id=scenario.scenario_id,
        status=status,
        minimum_declared_memory_bytes=minimum,
        target_compute_flops_per_second=compute,
        conditional_decode_bandwidth_bytes_per_second=bandwidth,
        requirements=requirements,
        reasons=tuple(reasons),
        assumptions=assumptions,
        limitations=_LIMITATIONS,
    )


def plan_hardware_to_workloads(
    scenarios: tuple[PlanningScenario, ...],
) -> tuple[HardwareToWorkloadPlan, ...]:
    """Rank candidates against each scenario's explicit planning memory budget."""
    if type(scenarios) is not tuple:
        raise ValidationError("INVALID_TYPE", "scenarios", "expected tuple")
    identifiers = [scenario.scenario_id for scenario in scenarios]
    if len(set(identifiers)) != len(identifiers):
        raise ValidationError("DUPLICATE_IDENTITY", "scenario_id", "scenario IDs must be unique")

    results: list[HardwareToWorkloadPlan] = []
    for scenario in scenarios:
        workload_plan = plan_workload_to_hardware(scenario)
        reasons = list(workload_plan.reasons)
        minimum = workload_plan.minimum_declared_memory_bytes
        budget = scenario.planning_memory_budget_bytes
        headroom = None
        if workload_plan.status is not PlanningStatus.COMPLETE:
            status = PlanningStatus.UNKNOWN
        elif budget is None:
            reasons.append("an explicit planning memory budget is required")
            status = PlanningStatus.UNKNOWN
        elif minimum is None:
            status = PlanningStatus.UNKNOWN
        else:
            headroom = exact_subtract(budget, minimum)
            status = PlanningStatus.COMPATIBLE if headroom >= 0 else PlanningStatus.INCOMPATIBLE
            if status is PlanningStatus.INCOMPATIBLE:
                reasons.append("minimum declared memory exceeds the planning budget")
        results.append(
            HardwareToWorkloadPlan(
                scenario_id=scenario.scenario_id,
                status=status,
                minimum_declared_memory_bytes=minimum,
                planning_memory_budget_bytes=budget,
                headroom_bytes=headroom,
                workload_plan=workload_plan,
                reasons=tuple(reasons),
                limitations=_LIMITATIONS,
            )
        )

    status_rank = {
        PlanningStatus.COMPATIBLE: 0,
        PlanningStatus.UNKNOWN: 1,
        PlanningStatus.INCOMPATIBLE: 2,
    }
    ordered = sorted(results, key=lambda result: result.scenario_id)
    ordered.sort(
        key=lambda result: result.headroom_bytes if result.headroom_bytes is not None else Decimal(0),
        reverse=True,
    )
    ordered.sort(key=lambda result: status_rank[result.status])
    return tuple(ordered)
