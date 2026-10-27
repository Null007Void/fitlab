# Lemonade FitLab — F1-C1 Corrective Engineering Acceptance Report

**Date:** 2026-10-19  
**Engineering verdict:** PASS — corrective candidate complete.  
**Independent adversarial re-review:** PASS (`deleg_a8e8242f`).  
**Owner acceptance:** Not inferred; remains Tyrell's decision.  
**Next-stage authority:** F2–F8 remain NOT AUTHORIZED.

## Scope and source identity

This corrective pass started from clean local Git commit `2b3aa25ca2b9dd37c24ad39aacb798d434cff83a` in the private repository `C:/Users/Overh/Lemonade-FitLab-Private/fitlab-r2-foundation` with no remotes.

The immutable original 36-member acceptance ZIP was re-identified at 54,634 bytes and SHA-256 `45b78fbeed15559c831bb3f264103c2844fe733cefa2a03d56e3047846d0359f`; its path safety passed. Its source/package manifests were previously verified and the archive was not modified.

The controlling F1-C1 review and exact R2 scope/matrix text were supplied directly by Tyrell after the initial attachment proved to be that original 36-member archive. The separately described 12,477-byte five-member corrective-docs ZIP did not materialize as a local file in this session, so its expected SHA-256 `9660ddbff5696ecd52e4ff7c431b4d7d6068dc8408b25c978254facc24c15a47` could not honestly be recomputed. The supplied controlling text is preserved in `evidence/F1_C1_CONTROLLING_INDEPENDENT_REVIEW.md`; canonical T01–T09 wording and traceability are preserved in `evidence/R2_F1_T01_T09_TRACEABILITY.md`.

## Red-phase reproduction

Before production corrections, five targeted tests reproduced all four executable defect classes:

- Byte-valued idealized-weight output was accepted as target compute (`ESTIMATED` instead of `UNKNOWN`).
- Caller-supplied effective bandwidth was classified `CALCULATED` instead of `UNAVAILABLE`.
- Model defaults silently produced architecture-dependent KV and compute results.
- Explicit `UNKNOWN` architecture plus standard attention still produced numeric KV.
- Aggregate JSON exceeding the intended output budget serialized successfully.

Command result: 5 tests run, 5 expected failures.

## F1-R01 — Dimensional correctness

Corrected `calculate_target_compute_rate` to require all of:

- name `decoder_flops_per_generated_token`;
- unit `FLOP/generated_token`;
- exact versioned `FLOPS_FORMULA` provenance.

A wrong name, unit, formula identifier, version, expression, or byte-valued result now returns structured `UNKNOWN / INCOMPATIBLE_DIMENSION` with no numeric value. A valid 2,000 FLOP/generated-token input at 5 tokens/s remains `ESTIMATED 10,000 FLOP/s`.

## F1-R02 — Architecture verification

- `ModelArchitecture.architecture_kind` now defaults to `UNKNOWN`.
- `ModelArchitecture.attention_mechanism` now defaults to new enum value `UNKNOWN`.
- Standard KV refuses numeric output when architecture support is unverified, even if standard attention is explicitly supplied.
- Supported synthetic fixtures now explicitly declare `DENSE_DECODER` and `STANDARD_FULL`.
- Explicit known-standard arithmetic remains exactly 640 bytes for the R2 hand fixture.
- Unsupported attention and unknown architecture continue to propagate structured `UNKNOWN`.

## F1-R03 — Measurement provenance

An externally supplied effective-bandwidth number has no source/definition fields in the current F1 contract. It therefore now returns `UNAVAILABLE / UNVERIFIED_PROVENANCE`, with no numeric claim. It is neither `CALCULATED` nor `MEASURED`.

This deliberately conservative behavior preserves the existing input contract while preventing false provenance. A later telemetry-facing contract requires separately authorized work and explicit source/definition identity.

## F1-R04 — Serialization safety

- Added an explicit 262,144-byte aggregate UTF-8 output ceiling.
- Canonical JSON now uses incremental `JSONEncoder.iterencode` processing.
- Byte count is checked per chunk before complete oversized JSON is materialized.
- Exactly-at-limit ASCII and multibyte UTF-8 outputs pass.
- One-byte-over-limit output deterministically raises `ValidationError` code `OUTPUT_TOO_LARGE`.
- Valid canonical output remains byte-for-byte deterministic.

## F1-R05 — Canonical R2 traceability

Added `evidence/R2_F1_T01_T09_TRACEABILITY.md`, preserving the approved identifiers and wording:

- T01 validation
- T02 1,000-parameter 4-bit weight payload
- T03 byte/GB/GiB units
- T04 standard KV
- T05 GQA KV heads
- T06 unsupported attention
- T07 MoE active versus total parameters
- T08 conditional throughput/capacity
- T09 unified memory

Each entry maps the exact contract/falsification probe and required observation to current source and tests. The earlier package-only reconstructed reconciliation remains preserved as historical evidence rather than rewritten.

## Verification

Final local verification:

- Warning-strict suite: **82/82 PASS**, zero failures/errors/skips.
- Deterministic randomized verification: **1,500 fixtures** in `tests/test_randomized_numeric.py` — 750 idealized-weight and 750 standard-KV cases checked against independent exact arithmetic.
- Compilation: PASS for production source, tests, and examples.
- Synthetic basic and unsupported-architecture/attention examples: PASS; emitted JSON parsed successfully.
- Production dependencies: Python standard library only; no dependency added.

Independent adversarial re-review:

- Verdict: **PASS — no material blockers**.
- Rechecked formula identity bypasses, architecture/attention combinations, bandwidth provenance, ASCII and multibyte aggregate byte boundaries, exact-limit and over-limit behavior, valid-output determinism, complete suite, compilation, and T01–T09 traceability.
- Reviewer modified no candidate files and used no network.

## Modified authored paths

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/FORMULAS_AND_LIMITATIONS.md`
- `examples/basic_usage.py`
- `examples/unknown_architecture.py`
- `fitlab_foundation/contracts.py`
- `fitlab_foundation/requirements.py`
- `fitlab_foundation/serialization.py`
- `tests/test_adversarial.py`
- `tests/test_f1b_requirements.py`
- `tests/test_randomized_numeric.py`
- New F1-C1 evidence, report, and manifest files under `evidence/` and repository root

Original source/evidence remains recoverable byte-for-byte at Git commit `2b3aa25ca2b9dd37c24ad39aacb798d434cff83a` and in the immutable original acceptance ZIP.

## Remaining limitations

- This is deterministic F1 engineering evidence, not automatic owner acceptance.
- No real hardware measurement provenance contract was added; unverified bandwidth correctly remains unavailable.
- Architecture support is caller-declared; F1 does not independently inspect model files or runtime metadata.
- The 262,144-byte serializer limit is an explicit F1 safety policy, not a later Passport/report schema limit.
- The separately described five-member corrective-docs ZIP was not physically available for hash/manifest verification; its full controlling text was supplied directly and used.
- F2 planning, Lemonade runtime activity, model downloads, live inference, report/passport work, publication, and submission remain outside scope.

## Boundary confirmation

No Lemonade runtime was started. No model was downloaded. No external network request, paid service, new dependency, public repository action, F2–F8 engineering, or unrelated portfolio mutation occurred.
