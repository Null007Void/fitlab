"""Pure deterministic requirements formulas for FitLab F1B."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .arithmetic import exact_add, exact_multiply
from .contracts import (
    ArchitectureKind,
    AttentionMechanism,
    CalculationResult,
    FormulaProvenance,
    HardwareResources,
    ModelArchitecture,
    Reason,
    ReasonCode,
    ResultStatus,
    Workload,
)
from .units import idealized_weight_payload_bytes
from .validation import MAX_BYTES, MAX_DIMENSION

WEIGHT_FORMULA = FormulaProvenance(
    "fitlab.weights.idealized_payload",
    "1.0.0",
    "P_total * bits_per_weight / 8",
)
KV_FORMULA = FormulaProvenance(
    "fitlab.kv.standard_full_cache",
    "1.0.0",
    "2 * L * H_kv * D_head * B_seq * S * bytes_per_KV_element",
)
FLOPS_FORMULA = FormulaProvenance(
    "fitlab.compute.dense_ar_decoder_heuristic",
    "1.0.0",
    "approximately 2 * active_parameters FLOP/generated_token",
)
COMPUTE_RATE_FORMULA = FormulaProvenance(
    "fitlab.compute.target_throughput",
    "1.0.0",
    "decoder_FLOP_per_token * target_tokens_per_second",
)
BANDWIDTH_FORMULA = FormulaProvenance(
    "fitlab.bandwidth.conditional_decode",
    "1.0.0",
    "declared_bytes_reloaded_per_token * target_tokens_per_second",
)
KNOWN_MEMORY_FORMULA = FormulaProvenance(
    "fitlab.memory.known_baseline",
    "1.0.0",
    "idealized_weight_payload + standard_full_kv_cache",
)
INDEPENDENT_CAPACITY_FORMULA = FormulaProvenance(
    "fitlab.memory.independent_physical_capacity",
    "1.0.0",
    "host_RAM + accelerator_dedicated_memory; unified_shared_memory is not added",
)

MAX_RESULT_INTEGER = MAX_BYTES * MAX_DIMENSION


def _unknown(name: str, code: ReasonCode, detail: str) -> CalculationResult:
    return CalculationResult.unknown(name, (Reason(code, detail),))


def calculate_ideal_weight_payload(
    model: ModelArchitecture,
    bits_per_weight: Decimal,
) -> CalculationResult:
    value = idealized_weight_payload_bytes(model.total_parameters, bits_per_weight)
    return CalculationResult.estimated(
        "idealized_weight_payload_bytes",
        value,
        "byte",
        WEIGHT_FORMULA,
        assumptions=(f"Exactly {bits_per_weight} idealized bits are assigned to every total parameter.",),
        limitations=(
            "not measured loaded RAM",
            "not GGUF file size",
            "excludes metadata, alignment, scales, runtime buffers, KV cache, and allocator overhead",
        ),
    )


def calculate_standard_kv_cache(
    model: ModelArchitecture,
    workload: Workload,
) -> CalculationResult:
    if model.architecture_kind is ArchitectureKind.UNKNOWN:
        return _unknown(
            "kv_cache_bytes",
            ReasonCode.UNSUPPORTED_ARCHITECTURE,
            "architecture support has not been verified",
        )
    if model.attention_mechanism is not AttentionMechanism.STANDARD_FULL:
        return _unknown(
            "kv_cache_bytes",
            ReasonCode.UNSUPPORTED_ATTENTION,
            f"standard full-cache formula is invalid for {model.attention_mechanism.value}",
        )
    required = {
        "layers": model.layers,
        "kv_heads": model.kv_heads,
        "head_dimension": model.head_dimension,
        "cached_tokens_per_sequence": workload.cached_tokens_per_sequence,
        "kv_bytes_per_element": workload.kv_bytes_per_element,
    }
    missing = tuple(name for name, value in required.items() if value is None)
    if missing:
        return _unknown(
            "kv_cache_bytes",
            ReasonCode.MISSING_METADATA,
            "missing: " + ",".join(missing),
        )
    value = (
        2
        * model.layers
        * model.kv_heads
        * model.head_dimension
        * workload.resident_sequences
        * workload.cached_tokens_per_sequence
        * workload.kv_bytes_per_element
    )
    if value > MAX_RESULT_INTEGER:
        return _unknown(
            "kv_cache_bytes",
            ReasonCode.ARITHMETIC_BOUND_EXCEEDED,
            "exact result exceeds the configured result bound",
        )
    return CalculationResult.calculated(
        "kv_cache_bytes",
        value,
        "byte",
        KV_FORMULA,
        assumptions=(
            "standard full-attention cache",
            "KV heads are used instead of query heads",
            "resident sequence concurrency is applied exactly once",
        ),
        limitations=(
            "excludes cache allocator overhead and paging metadata",
            "does not apply to sliding-window, MLA, paged, or offloaded cache architectures",
        ),
    )


def approximate_decoder_flops_per_token(model: ModelArchitecture) -> CalculationResult:
    if model.architecture_kind is ArchitectureKind.UNKNOWN:
        return _unknown(
            "decoder_flops_per_generated_token",
            ReasonCode.UNSUPPORTED_ARCHITECTURE,
            "architecture kind does not support the dense autoregressive decoder heuristic",
        )
    if model.architecture_kind is ArchitectureKind.MOE_DECODER:
        if model.active_parameters is None:
            return _unknown(
                "decoder_flops_per_generated_token",
                ReasonCode.MISSING_METADATA,
                "active_parameters is required for mixture-of-experts compute",
            )
        active = model.active_parameters
    else:
        active = model.active_parameters or model.total_parameters
    value = 2 * active
    return CalculationResult.estimated(
        "decoder_flops_per_generated_token",
        value,
        "FLOP/generated_token",
        FLOPS_FORMULA,
        assumptions=("active parameters represent per-token decoder activation",),
        limitations=(
            "simplified heuristic",
            "excludes prefill, full attention cost, embeddings, sampling, communication, and training",
            "does not predict achieved throughput",
        ),
    )


def calculate_target_compute_rate(
    flops_per_token: CalculationResult,
    workload: Workload,
) -> CalculationResult:
    if flops_per_token.status not in {ResultStatus.CALCULATED, ResultStatus.ESTIMATED}:
        return _unknown(
            "target_compute_flops_per_second",
            ReasonCode.DEPENDENCY_UNKNOWN,
            "decoder FLOPs per token is not numeric",
        )
    if (
        flops_per_token.name != "decoder_flops_per_generated_token"
        or flops_per_token.unit != "FLOP/generated_token"
        or flops_per_token.formula != FLOPS_FORMULA
    ):
        return _unknown(
            "target_compute_flops_per_second",
            ReasonCode.INCOMPATIBLE_DIMENSION,
            "input must be the versioned decoder FLOPs-per-generated-token result",
        )
    if workload.target_tokens_per_second is None:
        return _unknown(
            "target_compute_flops_per_second",
            ReasonCode.MISSING_METADATA,
            "target_tokens_per_second is required",
        )
    value = exact_multiply(flops_per_token.value, workload.target_tokens_per_second)
    return CalculationResult.estimated(
        "target_compute_flops_per_second",
        value,
        "FLOP/s",
        COMPUTE_RATE_FORMULA,
        assumptions=("target throughput is a declared requirement, not an observed achievement",),
        limitations=("inherits all decoder heuristic omissions", "does not predict achieved throughput"),
    )


def calculate_conditional_decode_bandwidth(workload: Workload) -> CalculationResult:
    if workload.declared_bytes_reloaded_per_token is None or workload.target_tokens_per_second is None:
        return _unknown(
            "conditional_decode_bandwidth_bytes_per_second",
            ReasonCode.MISSING_METADATA,
            "declared bytes reloaded per token and target throughput are required",
        )
    if workload.residency_assumption is None:
        return _unknown(
            "conditional_decode_bandwidth_bytes_per_second",
            ReasonCode.EXPLICIT_ASSUMPTION_REQUIRED,
            "an explicit residency/cache assumption is required",
        )
    value = exact_multiply(workload.declared_bytes_reloaded_per_token, workload.target_tokens_per_second)
    return CalculationResult.estimated(
        "conditional_decode_bandwidth_bytes_per_second",
        value,
        "byte/s",
        BANDWIDTH_FORMULA,
        assumptions=(workload.residency_assumption,),
        limitations=(
            "does not predict achieved throughput",
            "does not infer effective bandwidth from theoretical vendor bandwidth",
        ),
    )


def effective_bandwidth_observation(hardware: HardwareResources) -> CalculationResult:
    if hardware.effective_memory_bandwidth_bytes_per_second is None:
        return CalculationResult.unavailable(
            "effective_memory_bandwidth_bytes_per_second",
            (Reason(ReasonCode.EFFECTIVE_BANDWIDTH_UNKNOWN, "no effective bandwidth observation was supplied"),),
        )
    return CalculationResult.unavailable(
        "effective_memory_bandwidth_bytes_per_second",
        (
            Reason(
                ReasonCode.UNVERIFIED_PROVENANCE,
                "a supplied bandwidth value has no verified measurement source or definition",
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class RequirementsBundle:
    model_id: str
    idealized_weight_payload: CalculationResult
    kv_cache: CalculationResult
    known_memory_baseline: CalculationResult
    decoder_flops_per_token: CalculationResult
    target_compute_rate: CalculationResult
    conditional_decode_bandwidth: CalculationResult
    effective_bandwidth: CalculationResult
    independent_physical_capacity: CalculationResult
    runtime_overhead: CalculationResult
    whole_system_fit: CalculationResult


class RequirementsEngine:
    """Pure aggregation layer; it deliberately refuses physical-fit claims."""

    def evaluate(
        self,
        model: ModelArchitecture,
        workload: Workload,
        hardware: HardwareResources,
        *,
        weight_bits_per_parameter: Decimal,
    ) -> RequirementsBundle:
        weights = calculate_ideal_weight_payload(model, weight_bits_per_parameter)
        kv = calculate_standard_kv_cache(model, workload)
        if weights.status in {ResultStatus.CALCULATED, ResultStatus.ESTIMATED} and kv.status in {
            ResultStatus.CALCULATED,
            ResultStatus.ESTIMATED,
        }:
            known_memory = CalculationResult.estimated(
                "known_memory_baseline_bytes",
                exact_add(weights.value, kv.value),
                "byte",
                KNOWN_MEMORY_FORMULA,
                assumptions=("only idealized weights and supported standard KV cache are included",),
                limitations=("runtime overhead remains unknown", "not a whole-system fit result"),
            )
        else:
            known_memory = _unknown(
                "known_memory_baseline_bytes",
                ReasonCode.DEPENDENCY_UNKNOWN,
                "idealized weight payload or KV cache is unknown",
            )
        flops = approximate_decoder_flops_per_token(model)
        compute_rate = calculate_target_compute_rate(flops, workload)
        bandwidth = calculate_conditional_decode_bandwidth(workload)
        effective_bandwidth = effective_bandwidth_observation(hardware)
        capacity_value = hardware.independent_physical_capacity_bytes()
        if capacity_value is None:
            capacity = CalculationResult.unavailable(
                "independent_physical_capacity_bytes",
                (Reason(ReasonCode.MEASURED_HEADROOM_UNAVAILABLE, "no independent physical memory capacity was supplied"),),
            )
        else:
            capacity = CalculationResult.calculated(
                "independent_physical_capacity_bytes",
                capacity_value,
                "byte",
                INDEPENDENT_CAPACITY_FORMULA,
                assumptions=("unified shared memory is a subset of host RAM and is not added",),
                limitations=("capacity is not available headroom and does not establish model fit",),
            )
        runtime = _unknown(
            "runtime_overhead_bytes",
            ReasonCode.RUNTIME_OVERHEAD_UNKNOWN,
            "no measured or explicit runtime-overhead value exists in F1",
        )
        fit = _unknown(
            "whole_system_fit",
            ReasonCode.PHYSICAL_FEASIBILITY_NOT_MODELED,
            "F1 does not infer physical fit from idealized weights, KV cache, capacity, or bandwidth",
        )
        return RequirementsBundle(
            model_id=model.model_id,
            idealized_weight_payload=weights,
            kv_cache=kv,
            known_memory_baseline=known_memory,
            decoder_flops_per_token=flops,
            target_compute_rate=compute_rate,
            conditional_decode_bandwidth=bandwidth,
            effective_bandwidth=effective_bandwidth,
            independent_physical_capacity=capacity,
            runtime_overhead=runtime,
            whole_system_fit=fit,
        )
