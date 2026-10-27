# Architecture

## Design goals

The F1 foundation is a small deterministic calculation core. It favors explicit immutable data, pure functions, exact arithmetic, structured uncertainty, and audit-friendly formula provenance over framework machinery.

## Data flow

1. Callers construct `ModelArchitecture`, `Workload`, and `HardwareResources` contracts.
2. Contract construction rejects incompatible types, Boolean-as-integer coercion, invalid precision, non-finite Decimal values, inconsistent fields, and inputs above configured bounds.
3. Pure formula functions produce immutable `CalculationResult` records.
4. `RequirementsEngine.evaluate` composes those records without converting unknown dependencies into optimistic numbers.
5. `canonical_json` recursively serializes dataclasses, enums, integers, and Decimals into deterministic JSON, stopping if aggregate UTF-8 output would exceed 262,144 bytes.

## Module boundaries

### `arithmetic`

Converts bounded integer and Decimal operands to exact rational values, performs arithmetic with Python integers, and constructs finite base-10 Decimal results without consulting the mutable ambient Decimal context.

### `validation`

Centralizes machine-readable validation errors and conservative limits. Decimal inputs are exact `Decimal` objects only, with at most 100 digits and exponent range `-18..18`; floats and numeric strings are never coerced.

### `contracts`

Frozen, slotted dataclasses define model metadata, workload declarations, hardware observations, formula provenance, machine-readable reasons, and result states. Architecture and attention are unknown by default; callers must affirm supported kinds before architecture-dependent numeric formulas run. Invariants are enforced at construction so calculation functions receive validated values.

### `units`

Performs byte, decimal-GB, binary-GiB, and idealized weight-payload arithmetic without binary floating point or rounding.

### `requirements`

Contains versioned formulas and one aggregation engine. Supported arithmetic returns a number plus formula, assumptions, and limitations. Unsupported or missing cases return structured `UNKNOWN`/`UNAVAILABLE` values.

### `serialization`

Converts approved value types into canonical JSON using sorted keys and compact separators. Decimal values remain strings, avoiding accidental float conversion. Incremental encoding enforces a 262,144-byte aggregate UTF-8 limit before the complete oversized output is materialized.

## Dependency direction

`validation <- arithmetic <- units <- requirements`

`validation <- contracts <- requirements`

`validation <- units <- requirements`

`contracts <- serialization`

The modules have no network, filesystem, process, environment, clock, random, model-runtime, or mutable-global dependencies. Given equal contract values, output is byte-for-byte stable.

## Safety boundaries

- Exact type checks reject Python's `bool` subtype where an integer is expected.
- Operand magnitudes, serialized depth, collection sizes, text, expanded numeric representations, and aggregate serialized UTF-8 output are explicitly bounded; formulas do not allocate memory proportional to the represented numeric value.
- Target compute accepts only the versioned decoder-FLOPs/generated-token result; byte-valued or semantically unrelated results fail closed as `UNKNOWN`.
- Externally supplied effective bandwidth without source/definition provenance remains `UNAVAILABLE` and carries no numeric claim.
- Inputs and result integers are bounded; oversized exact results fail closed as `UNKNOWN` with `ARITHMETIC_BOUND_EXCEEDED`.
- Shared unified memory is descriptive only and excluded from independent-pool addition.
- Known memory baseline includes only idealized weights and a supported KV baseline.
- Runtime overhead and whole-system fit are never fabricated.

## Future extension seam

F2 may consume `RequirementsBundle` values and reasons to construct bidirectional planning journeys. It should not duplicate formulas. New formulas require new identifiers/versions, test-first implementation, and explicit propagation rules. F4 may adapt this pure engine behind a Lemonade-facing boundary without placing runtime or network behavior inside F1.
