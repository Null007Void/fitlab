"""Build source-backed planning inputs for both FitLab journeys.

The two journeys share one requirements engine:

* ``workload_to_hardware`` - what does this workload need from a machine?
* ``hardware_to_workloads`` - what can this machine run?

The model side of every scenario is sourced from the local GGUF header and the
Lemonade registry, never from a placeholder. The workload side is an explicit
owner declaration: the F1/F2 contract treats target throughput, cache residency
and reload behaviour as declared requirements, never as measurements.

Hybrid short-convolution architectures are declared truthfully. The F1 engine
does not model their cache, so it returns ``UNKNOWN`` for the KV term instead
of a wrong number.
"""

from pathlib import Path

from .artifacts import ArtifactError
from .model_profile import (
    ATTENTION_STANDARD_FULL,
    ATTENTION_UNSUPPORTED,
    MODEL,
    derive_profile,
    locate_model_file,
)

# F1/F2 planner document schema (schema_version 1).
DOCUMENT_SCHEMA_VERSION = 1

# Owner-declared workload assumptions. These are labelled declarations, not
# observations, and are surfaced verbatim in the Capability Passport.
DEFAULT_WORKLOAD = {
    "resident_sequences": 1,
    "cached_tokens_per_sequence": 2048,
    "kv_bytes_per_element": 2,
    "target_tokens_per_second": "10",
    "declared_bytes_reloaded_per_token": 1170340608,
    "residency_assumption": (
        "Owner-declared planning assumption: one resident sequence, a 2048-token "
        "context window, f16 KV elements, and a conservative full-weight reload "
        "per generated token. These are declared requirements for planning, not "
        "measured behaviour."
    ),
}

DECLARATION_ORIGIN = "OWNER_DECLARED_PLANNING_ASSUMPTION"


def _fail(code, detail=""):
    raise ArtifactError(code if not detail else f"{code}:{detail}")


def _model_block(profile):
    """Map the sourced profile onto the frozen F1 model contract."""
    architecture_kind = profile["architecture_kind"]
    attention = profile["attention_mechanism"]
    if attention == ATTENTION_UNSUPPORTED:
        # F1 knows STANDARD_FULL only. Anything else must be declared as OTHER
        # so the engine's own unsupported-attention rule fails closed.
        attention = "OTHER"
    elif attention == ATTENTION_STANDARD_FULL:
        attention = "STANDARD_FULL"
    else:
        attention = "UNKNOWN"
    if architecture_kind == "UNSUPPORTED_HYBRID":
        # A hybrid decoder is still a dense decoder: every parameter is
        # active for every token. Only the cache model is unsupported.
        architecture_kind = "DENSE_DECODER"
    return {
        "model_id": MODEL,
        "total_parameters": profile["total_parameters"],
        "active_parameters": profile["total_parameters"],
        "layers": profile["block_count"],
        "query_heads": profile["head_count"],
        "kv_heads": profile["kv_heads"],
        "head_dimension": profile["head_dimension"],
        "architecture_kind": architecture_kind,
        "attention_mechanism": attention,
    }


def _workload_block(workload):
    result = {
        "resident_sequences": workload["resident_sequences"],
        "cached_tokens_per_sequence": workload["cached_tokens_per_sequence"],
        "kv_bytes_per_element": workload["kv_bytes_per_element"],
        "target_tokens_per_second": workload["target_tokens_per_second"],
        "declared_bytes_reloaded_per_token": workload["declared_bytes_reloaded_per_token"],
        "residency_assumption": workload["residency_assumption"],
    }
    return result


def _scenario(scenario_id, profile, workload, budget=None, overhead=None, basis=None):
    scenario = {
        "scenario_id": scenario_id,
        "model": _model_block(profile),
        "workload": _workload_block(workload),
        "weight_bits_per_parameter": profile["weight_bits_per_parameter"],
    }
    if overhead is not None:
        scenario["explicit_runtime_overhead_bytes"] = overhead
        scenario["runtime_overhead_basis"] = basis
    if budget is not None:
        scenario["planning_memory_budget_bytes"] = budget
    return scenario


def build_plan(direction, workload=None, budget_bytes=None, overhead_bytes=None,
               overhead_basis=None, model_path=None, revision=None):
    """Build a planner document for one direction from sourced model identity."""
    if direction not in ("workload_to_hardware", "hardware_to_workloads"):
        _fail("UNSUPPORTED_DIRECTION")
    workload = dict(DEFAULT_WORKLOAD if workload is None else workload)
    for key in DEFAULT_WORKLOAD:
        if key not in workload:
            _fail("WORKLOAD_DECLARATION_INCOMPLETE", key)
    if model_path is None:
        model_path, detected_revision = locate_model_file()
        revision = revision or detected_revision
    profile = derive_profile(model_path, revision)
    if profile["weight_bits_per_parameter"] is None:
        _fail("MODEL_QUANTIZATION_UNSUPPORTED")
    if direction == "workload_to_hardware":
        scenarios = [
            _scenario(
                "lfm25-1.2b-instruct-real",
                profile,
                workload,
                overhead=overhead_bytes,
                basis=overhead_basis,
            )
        ]
    else:
        scenarios = [
            _scenario(
                "lfm25-1.2b-instruct-real",
                profile,
                workload,
                budget=budget_bytes,
                overhead=overhead_bytes,
                basis=overhead_basis,
            )
        ]
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "direction": direction,
        "scenarios": scenarios,
    }


def load_plan_document(path):
    """Read a planner document through the strict bounded F2 boundary."""
    from fitlab_foundation.planner_cli import _read_bounded_document, run_document

    document = _read_bounded_document(Path(path))
    run_document(document)
    return document


def provenance(profile, workload, budget_bytes=None):
    """Return the declaration provenance that accompanies a built plan."""
    return {
        "model_identity_source": profile["identity_source"],
        "model_identity": profile.get("model_identity", "UNVERIFIED"),
        "model_id": profile["model_id"],
        "checkpoint": profile["checkpoint"],
        "snapshot_revision": profile["snapshot_revision"],
        "runtime_version": profile["runtime_version"],
        "quantization": profile["quantization"],
        "weight_bits_per_parameter": profile["weight_bits_per_parameter"],
        "total_parameters": profile["total_parameters"],
        "architecture_family": profile["architecture_family"],
        "architecture_kind": profile["architecture_kind"],
        "attention_mechanism": profile["attention_mechanism"],
        "hybrid": profile["hybrid"],
        "convolution_block_count": profile["convolution_block_count"],
        "attention_block_count": profile["attention_block_count"],
        "shortconv_cache_length": profile["shortconv_cache_length"],
        "context_length": profile["context_length"],
        "vocab_size": profile["vocab_size"],
        "head_count": profile["head_count"],
        "kv_heads": profile["kv_heads"],
        "head_dimension": profile["head_dimension"],
        "workload_origin": DECLARATION_ORIGIN,
        "workload": dict(workload),
        "planning_memory_budget_bytes": budget_bytes,
        "declared_license_name": profile["declared_license_name"],
        "declared_license_link": profile["declared_license_link"],
        "license_note": (
            "The GGUF header declares a license name only. No license text was "
            "found locally and none is bundled; redistribution rights are not "
            "established by this field."
        ),
    }


# Bytes per element for the short-convolution state cache. llama.cpp keeps
# this state in f32.
CONV_STATE_BYTES_PER_ELEMENT = 4


def memory_advisory(profile, workload, runtime_overhead_bytes=None):
    """Compose a disclosed, sourced memory estimate for a hybrid model.

    The frozen F1/F2 engine deliberately refuses to model a hybrid
    short-convolution architecture, so its own ``known_memory_baseline`` stays
    ``UNKNOWN`` for this model. This advisory does not change that result. It
    computes the same quantities the engine would, but scopes the standard
    full-attention formula to the attention blocks that actually use it, adds
    the short-convolution state that the engine cannot express, and labels
    every component.

    The result is an estimate over declared inputs. It is not a measurement,
    not loaded RAM, and not proof of fit.
    """
    from fitlab_foundation.planner_cli import run_document
    from fitlab_foundation.serialization import to_primitive

    attention_layers = profile["attention_block_count"]
    convolution_layers = profile["convolution_block_count"]

    components = []
    total = 0

    weight_bytes = profile["total_parameters"] * int(profile["weight_bits_per_parameter"]) // 8
    components.append(
        {
            "component": "idealized_weight_payload_bytes",
            "bytes": weight_bytes,
            "evidence": "ESTIMATED",
            "basis": "P_total x bits_per_weight / 8, identical to fitlab.weights.idealized_payload v1.0.0",
            "limitation": (
                "Not GGUF file size, not loaded RAM. Excludes quantization "
                "scales, tensor alignment, tokenizer and runtime buffers."
            ),
        }
    )
    total += weight_bytes

    attention_kv_bytes = None
    if attention_layers and profile["kv_heads"] and profile["head_dimension"]:
        scoped = {
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "direction": "workload_to_hardware",
            "scenarios": [
                {
                    "scenario_id": "attention-scoped-kv",
                    "model": {
                        "model_id": MODEL,
                        "total_parameters": profile["total_parameters"],
                        "layers": attention_layers,
                        "query_heads": profile["head_count"],
                        "kv_heads": profile["kv_heads"],
                        "head_dimension": profile["head_dimension"],
                        "architecture_kind": "DENSE_DECODER",
                        "attention_mechanism": "STANDARD_FULL",
                    },
                    "workload": _workload_block(workload),
                    "weight_bits_per_parameter": profile["weight_bits_per_parameter"],
                }
            ],
        }
        result = to_primitive(run_document(scoped))["results"][0]
        kv = result["requirements"]["kv_cache"]
        if kv["status"] in ("CALCULATED", "ESTIMATED"):
            attention_kv_bytes = int(kv["value"])
            components.append(
                {
                    "component": "attention_kv_cache_bytes",
                    "bytes": attention_kv_bytes,
                    "evidence": "CALCULATED",
                    "basis": (
                        "fitlab.kv.standard_full_cache v1.0.0 scoped to the "
                        f"{attention_layers} attention blocks "
                        f"(H_kv={profile['kv_heads']}, D_head={profile['head_dimension']})"
                    ),
                    "limitation": (
                        "Scoped to attention blocks only; excludes short-convolution "
                        "state, allocator overhead and paging metadata."
                    ),
                }
            )
            total += attention_kv_bytes

    conv_state_bytes = None
    if convolution_layers and profile["shortconv_cache_length"] and profile["embedding_length"]:
        conv_state_bytes = (
            convolution_layers
            * int(profile["shortconv_cache_length"])
            * int(profile["embedding_length"])
            * CONV_STATE_BYTES_PER_ELEMENT
        )
        components.append(
            {
                "component": "shortconv_state_bytes",
                "bytes": conv_state_bytes,
                "evidence": "ESTIMATED",
                "basis": (
                    f"{convolution_layers} convolution blocks x l_cache="
                    f"{profile['shortconv_cache_length']} x d_model="
                    f"{profile['embedding_length']} x 4 bytes (f32 state)"
                ),
                "limitation": (
                    "Sourced from GGUF metadata; not measured. Assumes one "
                    "resident sequence and f32 state storage."
                ),
            }
        )
        total += conv_state_bytes

    if runtime_overhead_bytes is not None:
        components.append(
            {
                "component": "declared_runtime_overhead_bytes",
                "bytes": int(runtime_overhead_bytes),
                "evidence": "DECLARED",
                "basis": "Owner-declared planning allowance for runtime buffers and allocator overhead",
                "limitation": "A declared allowance, not a measurement.",
            }
        )
        total += int(runtime_overhead_bytes)

    return {
        "kind": "COMPOSITE_MEMORY_ADVISORY",
        "bytes": total,
        "components": components,
        "engine_result": "UNKNOWN",
        "engine_reason": (
            "The frozen F1/F2 engine returns UNKNOWN for this model's memory "
            "baseline because it does not model hybrid short-convolution "
            "attention. That engine result is unchanged by this advisory."
        ),
        "limitations": [
            "An estimate over declared inputs, not a measurement.",
            "Not loaded RAM, not resident set size, not proof of physical fit.",
            "Runtime overhead is declared by the owner, not observed.",
            "Cache allocator overhead, paging and alignment are excluded.",
        ],
    }
