# Lemonade FitLab F2 Engineering Checkpoint

**Status:** BLOCKED / NOT ACCEPTED — final independent review failed after two corrections
**Date:** 2026-10-19

## Delivered

- Bidirectional deterministic planning:
  - workload → minimum declared hardware requirements;
  - hardware planning budget → ranked workload compatibility.
- Strict schema-v1 offline JSON/CLI boundary.
- Exact Decimal/integer arithmetic with no float coercion.
- Explicit runtime-overhead value and provenance requirement.
- Deterministic ranking and canonical bounded JSON output.
- Structured preservation of unknown and unsupported cases.
- Synthetic example requests and captured outputs for both journeys.

## Semantics

A `COMPATIBLE` result means only that the supported, explicitly declared memory requirement is within the explicit planning budget. It is not a claim of runtime availability, achieved throughput, device placement, thermal stability, driver support, or full-system feasibility.

## Verification

- Full warning-strict suite: 96/96 PASS.
- F2-specific tests: 14/14 PASS.
- Python compilation: PASS.
- Two example CLI executions: PASS.
- Workload-to-hardware example: `COMPLETE`, 1,500 declared bytes.
- Hardware-to-workloads example: one `COMPATIBLE`, one `INCOMPATIBLE`, deterministically ranked.
- Independent review 1 (`deleg_a464744e`): FAIL; preserved in `evidence/F2_INDEPENDENT_REVIEW_1.json`.
- Correction 1 prevents incomplete compute/bandwidth requirements from receiving a top-level `COMPATIBLE` label and bounds input to 1 MiB with a 50-scenario evaluation ceiling and canonical error output.
- Independent review 2 (`deleg_5925bc9f`): FAIL; preserved in `evidence/F2_INDEPENDENT_REVIEW_2.json`.
- Correction 2 moves serialization into the controlled CLI boundary, rejects overlarge successful outputs canonically, and removes ambient-context-sensitive Decimal negation from headroom and ranking.
- Final independent review (`deleg_661c42c7`): FAIL; preserved in `evidence/F2_INDEPENDENT_REVIEW_3_FINAL.json`.
- Remaining blockers: serialization of an adversarial validation error can itself escape as a traceback; deeply nested JSON and oversized integer literals can escape parsing as `RecursionError` / `ValueError`.
- Two permitted corrective passes are exhausted. No third correction was attempted, and F3–F7 were not entered.

## Boundaries

- No network request.
- No Lemonade runtime or local model execution.
- No model download.
- No external publication.
- No F3 tuning or frozen evaluator.
- No F4–F8 implementation.

Independent source review is complete. F2 remains blocked and unaccepted; the exact residual defects are preserved in `evidence/F2_INDEPENDENT_REVIEW_3_FINAL.json`.
