# F5 measurement protocol v1 — ready, not executed

This protocol is frozen before new model inference. It defines a small known-task engineering evaluation, not a held-out benchmark or statistical reliability claim. Prior feasibility observations are historical and are not new F5 measurements.

## Entry gates

1. Exact reviewed source commit, task-pack v2 SHA-256, grader SHA-256 and protocol identity are recorded. F2/F3/F4 review scope and genuine-runtime limitations remain visible.
2. Existing Windows Lemonade 2026.42.1 and cached `LFM2.5-1.2B-Instruct-GGUF` Q4_K_M are used; no upgrades, downloads, provider changes or GPU execution.
3. Read-only preflight passes: at least 4.481 GiB available physical memory and available commit, reported memory load below 90%, and calculated free physical fraction above 10%. No unrelated process may be killed or reconfigured.
4. Use only an already-running idle CPU instance with verified live offline/no-fetch flags and disabled telemetry. Startup/loading is not automated or endorsed by this checkpoint; see F5_TURNKEY.md. Do not unload or reconfigure another workload. Exact loaded settings are CPU, 2048 context, parallel 1, threads 2, batch threads 2.
5. Adapter confirms exact runtime/model/checkpoint/backend/config and idle state. Both resource and remaining-budget checks run again after health and immediately before each inference request.
6. Planning input must use sourced model metadata and workload assumptions for the real model. The inherited tiny synthetic model examples must never be renamed and presented as real metadata. Unknown/hybrid architecture remains UNKNOWN. For task-only measurements, omit --plan: planning input/output remain null with planning_status UNAVAILABLE. Such a run establishes neither planning journey nor hardware fit; missing metadata must not block honest task-only measurement.

## Repetition and warmup

- Default: eight tasks × three rounds = 24 planned scored observations, sequential in frozen case order. One- or two-round runs are allowed as explicitly labeled partial engineering probes, not fulfillment of the three-repeat target.
- Task tiers: the R2 approved baseline requires **six core tasks with at least three measured repetitions each, giving 18 core observations**. The six core cases are E1, E2, E3, D1, D2 and D3, preserved unchanged from the frozen six-case feasibility oracle. The two additional invalid-argument negatives, D4 and D5, are **supplemental**: they extend negative coverage but are not required for baseline fulfilment and never count toward the core denominator. `fixtures/task-tiers.json` records the split, the denominators and the grading-identity statement. This classification is proposed, not owner-approved, and it changes no pass rule: one frozen grader applies one oracle to every case in both tiers.
- The core denominator is fixed at 18. A stopped or interrupted run keeps it. Supplemental observations never satisfy it, and a partial run never shrinks it.
- Warmup requests: **zero**. There are no hidden, discarded or unrecorded calibration completions. This avoids additional resource use and selection bias.
- First request is labeled `first_observed_request` on an already-loaded model. It is not a cold model-load measurement. Subsequent requests are labeled `subsequent_request`.
- Cache state is unknown. Repeated prompts may use backend prefix caches. All repeats and server-reported usage/timing metadata are retained; no speed comparison across unlike cache/backend configurations.
- Temperature 0.1, max output tokens 128, nonstreaming, thinking disabled where supported; no seed guarantee. Expected nondeterminism is reported, not hidden by retries.
- At most one request in flight, one-second pause after completed rows, 30-second per-request deadline, 600-second session budget. Reserve time for both health and inference; recheck after health.

## What is measured

- Correctness: deterministic frozen oracle, exact content/schema/type comparison, malformed and tool-call rejection. Report per-case pass counts with denominator three, the core-tier count with denominator 18 and the all-task count with denominator 24. Keep incorrect responses.
- Timing: client end-to-end nonstreaming elapsed seconds for every valid completion. It includes HTTP/prompt/decode overhead. Median across valid completions is descriptive only. Keep individual values; no unsupported p95 claim from three samples.
- Memory: native Windows physical availability, total physical memory, reported load and available commit snapshots before health, immediately before inference and after each successful completion. These are whole-host observations, **not process peak RAM, incremental model memory, or continuous telemetry**.
- Runtime: health/config per row, including model/checkpoint/backend/context/thread identity. Full raw request and response remain private evidence.
- TTFT, decode-only tokens/second, peak process RAM, energy, sustained throughput, cold-start cost and reliability confidence are **UNAVAILABLE**. Do not derive them from client elapsed time or software tests.

## Failure policy

No retries, automatic model switches or prompt edits. Resource failure, deadline exhaustion, malformed adapter data, identity mismatch or transport exception stops further requests. Earlier valid observations remain; the denominator retains failed/unrun cases. A correct envelope with an incorrect answer is a measured failure, not a transport failure, and does not itself stop later tasks.

A resource drop after a completion preserves that completed observation and stops the session. Malformed adapter output becomes FAILED and never MEASURED. Interrupted/STARTED rows are incomplete. Atomic checkpoints retain the last complete JSON file on interruption; final status must be checked before aggregation. New evidence files use exclusive creation and are never overwritten by another run.

`SYNTHETIC_TEST` records belong only to harness tests. `LOCAL_RUNTIME` is explicitly selected by the real CLI and requires the concrete Lemonade adapter. This label is a provenance declaration, not cryptographic proof; independent review must inspect authentic runtime evidence. No synthetic record may become an F5 observation or Passport measurement.

## Result schema and reproducibility

`docs/evaluation-result-v2.schema.json` describes normal run records. Each record includes a unique run ID, UTC timestamps, source hashes, task-pack hash, execution kind, protocol, planning input/output, runtime/config, ordered rows, raw replies, grades, memory snapshots, limitations and summary. Invalid input before execution produces a separate `INVALID_INPUT` envelope with zero inference requests.

Archive the exact source commit/tree, clean state, manifest, task pack, protocol and raw result. Verify hashes before reproduction. Recompute grades from raw content with the frozen grader and reconcile every case/repeat identity and summary. Hashes detect changes relative to a trusted checkpoint; they do not authenticate a self-edited record.

A genuine smoke run establishes F4 only for the observed configuration. F5 starts with real recorded observations and completes only after the full declared repetition policy, integrity checks and resource evidence are satisfied. Keep F6 placeholder values null until measurement import has its own reviewed provenance/validation path.
