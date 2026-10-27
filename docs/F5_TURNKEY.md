# F5 live execution — one operation

**Status: EXECUTED in the sealed LIVE-002 qualification (Lemonade 2026.43.3,
8/8 authorized requests once: 6 pass / 2 retained model-output failures,
`COMPLETED`, `complete_protocol=false` because this turnkey protocol runs 1
repetition instead of the full 3). Its engine is the demonstrated live
integration. A new run of this wrapper starts a NEW session directory
(fresh evidence, never overwritten)
in this project. LIVE-002 executed this procedure once under the owner's
written authorization; any further full-protocol run (3 repetitions)
requires its own fresh authorization.**

This document is the complete procedure for one turnkey run. Its workflow
command is the single operation that executes inference; everything else is
preparation performed before it and verification performed after it.

## 1. The single operation

From PowerShell in a clean checkout of the repository root:

```powershell
$FitLabPython = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"

# 0. Confirm the machine is in a safe window. This performs no inference.
& $FitLabPython -m fitlab_evaluation.cli gate

# 1a. Optional but recommended: build the source-backed planning input.
#     This reads the model header only. It loads nothing and runs nothing.
& $FitLabPython -m fitlab_evaluation.cli plan workload_to_hardware `
    --overhead-bytes 268435456 `
    --overhead-basis "Owner-declared planning allowance for runtime buffers and allocator overhead; not a measurement." `
    --output-dir evidence/plan-001

# 1b. The one operation. Use a fresh output directory that does not exist yet.
& $FitLabPython -m fitlab_evaluation.workflow run `
    --output-dir evidence/session-001 `
    --repeats 3 `
    --plan evidence/plan-001/plan.json
```

The `gate` step must print `"resource_gate": "PASS"`. If it prints `FAIL`,
stop: the host does not have the memory headroom and the run would be
refused anyway. Do not free memory by stopping unrelated work.

The `--plan` argument is optional. With it, the record carries the planning
input and output, the report shows the planning journey alongside the
measured tasks, and the two are attributed separately. Without it, the run is
a **task-only** measurement: `planning_status` is `UNAVAILABLE`, the planning
input and output are null, and the report states that neither planning
journey was established. A task-only run is a valid measurement of task
outcomes; it is not a demonstration of hardware fit.

The run command performs the full protocol: 8 frozen tasks x 3 rounds = 24
planned scored observations, of which 18 are the R2 core observations.

## 2. Resource thresholds

These are mandatory and unchanged. The wrapper refuses before any runtime
query if they are not met.

| Gate | Requirement |
|---|---|
| Available physical memory | at least 4,811,437,114 bytes (4.481 GiB) |
| Available commit | at least 4,811,437,114 bytes (4.481 GiB) |
| Reported memory load | below 90 % |
| Calculated free physical fraction | above 10 % of total physical memory |

The 4.481 GiB floor is the original safety floor. It is not negotiable and
must not be lowered to make a run possible.

## 3. Model and backend identity

The wrapper verifies every one of these before the first completion and
refuses to proceed on any mismatch. It never repairs, reloads or substitutes.

| Field | Required value |
|---|---|
| Runtime version | tested with both `2026.42.1` (historical campaign) and
`2026.43.3` (LIVE-002 qualification); both accepted by the compat check |
| Model name | `LFM2.5-1.2B-Instruct-GGUF` |
| Checkpoint | `LiquidAI/LFM2.5-1.2B-Instruct-GGUF:LFM2.5-1.2B-Instruct-Q4_K_M.gguf` |
| Device | `cpu` |
| Backend | `llamacpp` |
| Context size | 2048 |
| Backend arguments | `--parallel 1 --threads 2 --threads-batch 2` |
| Loaded models | exactly one |
| Backend state | `loaded: true`, `backend_alive: true`, `backend_health: ready` |
| Busy / streaming | `is_busy: false`, `is_streaming: false` |
| Telemetry | explicitly disabled |
| Runtime config | `offline: true` and `no_fetch_executables: true` |

Remote routing and enabled telemetry are refused outright.

## 4. Owner preparation prerequisites

The wrapper is **ready-only**. It never starts a server, loads or unloads a
model, changes configuration, or downloads anything. The owner must prepare
a compliant runtime beforehand.

1. **The runtime must already be running and idle** with the exact model
   loaded, on CPU, with the exact settings above.
2. **The runtime must already be in offline mode** with `offline: true` and
   `no_fetch_executables: true`, and telemetry disabled.
3. **Do not use the previously documented load command.** Installed
   documentation shows `/v1/load` can install a missing model and defaults to
   merging stored backend arguments. That command is withdrawn as a safe
   turnkey instruction. Cache existence and `--no-discovery` do not prove
   offline operation.
4. **Do not change shared configuration**, disable the resource floor, kill
   other workloads, or run a download to obtain measurements.
5. **Do not unload or reconfigure the pre-existing model afterwards.** The
   wrapper does not own the server and never terminates it.

## 5. Measurement protocol

Protocol identifier `fitlab-f5-v1`.

| Property | Value |
|---|---|
| Warmup requests | zero — there are no hidden or discarded calibration completions |
| Order | round-major, frozen case order |
| Concurrency | one request in flight |
| Pause between rows | 1 second |
| Request timeout | 30 seconds |
| Session budget | 600 seconds |
| Temperature / max tokens | 0.1 / 128, nonstreaming, thinking disabled |
| First observation label | `first_observed_request` — already-loaded model, cache state unknown |
| Cold load measured | no |

The eight frozen cases are `E1 E2 E3 D1 D2 D3 D4 D5`. Six are the R2 core
cases and two are supplemental; the core denominator is 18 and supplemental
observations never satisfy it. See `fixtures/task-tiers.json`.

## 6. What the run produces

```
evidence/session-001/
  trust.json        immutable source snapshot (commit, tree, per-file hashes)
  bootstrap.json    initial reservation, zero inference requests
  manifest.json     SHA-256 of the immutable payloads
  session.json      mutable wrapper status, preflight, allowlisted config, request count
  evaluation.json   per-row atomic checkpoints and the final strict record
  passport/         deterministically recomputed HTML/JSON report and manifest
```

`session.json` records the attempted request count. A durable `STARTED` row
may not have reached the server; if the evidence cannot be reloaded the count
stays null rather than being reported as zero.

## 7. After the run

Verify the evidence. This performs no inference:

```powershell
& $FitLabPython -m fitlab_evaluation.cli verify --trust evidence/session-001/trust.json --evaluation evidence/session-001/evaluation.json
```

Expected on a complete run: `status` `COMPLETED`, `measurement_eligible`
`true`, `complete_protocol` `true`, `measured_count` 24, `planned_count` 24.

If the report export failed after inference, reproduce the Passport without
new requests:

```powershell
& $FitLabPython -m fitlab_evaluation.workflow postprocess --session-dir evidence/session-001 --output-dir reports/session-001-recovered
```

If no evaluation file exists, generate a no-evidence Passport:

```powershell
& $FitLabPython -m fitlab_evaluation.cli passport --trust evidence/session-001/trust.json --output-dir reports/session-001-unmeasured
```

## 8. Failure semantics

- A `BLOCKED` session exits 2. It is not a measured failure and not a
  success. No evaluation file is fabricated.
- A `STOPPED` or `INTERRUPTED` run keeps every unrun and failed case in the
  denominator. It never becomes a complete protocol.
- No automatic retry, inference resume, model switch, prompt edit or repeat
  merging exists. A new measurement is a new session in a new directory.
- Existing output paths are refused. Nothing is overwritten.
- Corrupt evidence is not repaired. Preserve the original for review.

## 9. What still requires a human

A green offline run, a schema-valid report or a self-declared `LOCAL_RUNTIME`
label does not authenticate execution. Independent corroboration of the
execution origin, by someone able to observe the runtime, is still required
before F5 is accepted and before any public claim is made.
