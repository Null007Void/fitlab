# FitLab F2 — Bidirectional Deterministic Planner

## Contract

F2 adds two offline planning directions on top of the independently accepted F1 requirements engine:

1. `workload_to_hardware`: calculates the minimum **declared planning memory** and target compute/bandwidth requirements for each workload.
2. `hardware_to_workloads`: compares those declared memory requirements with an explicit planning budget and ranks compatible, unknown, then incompatible scenarios deterministically.

Invoke either direction with:

```text
python -m fitlab_foundation.planner_cli --input examples/f2_workload_to_hardware.json
python -m fitlab_foundation.planner_cli --input examples/f2_hardware_to_workloads.json
```

The command emits one bounded canonical JSON document. Decimal inputs must be strings. Binary floats, unknown fields, duplicate identities, unsupported schema versions, invalid enums, malformed numeric values, input files above 1,048,576 bytes, and requests above 50 scenarios are rejected rather than coerced. Validation failures return canonical JSON with exit code `2`; they do not emit Python tracebacks.

## Exact arithmetic

For supported standard-full-attention scenarios:

```text
minimum_declared_memory = idealized_weight_payload + standard_KV_cache + explicit_runtime_overhead
headroom = explicit_planning_memory_budget - minimum_declared_memory
```

The F1 formula identities and limitations remain intact. No intermediate binary floating-point arithmetic is used.

## Interpretation

- `COMPLETE`: workload requirements were calculable from supported metadata and explicit runtime-overhead provenance.
- `COMPATIBLE`: minimum declared memory is within the explicit planning memory budget.
- `INCOMPATIBLE`: minimum declared memory exceeds the explicit planning memory budget.
- `UNKNOWN`: required architecture metadata, runtime allowance, target requirement, or budget is absent or unsupported.

`COMPATIBLE` is deliberately narrower than “will run.” It does not establish runtime availability, model-format compatibility, placement across memory domains, thermals, driver support, achieved throughput, or whole-system stability.

## Required honesty boundary

The runtime overhead is never guessed. A caller must provide both exact bytes and a nonempty basis. The hardware direction compares against a caller-declared planning budget; it does not silently derive that budget from marketing capacity or double-count unified memory.

Target compute and conditional bandwidth are requirements, not performance predictions. Unsupported architecture or attention metadata stays `UNKNOWN` and cannot be ranked as compatible.

## Scope

F2 is standard-library-only and performs no network requests, hardware probing, shopping recommendation, model download, or Lemonade inference. F3 frozen evaluation and F4 real Lemonade integration remain separate gates.
