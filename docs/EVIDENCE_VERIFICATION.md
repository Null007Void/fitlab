# Evidence verification

Every FitLab claim is meant to be checkable by a third party. This document
describes how to verify each layer.

## Layer 1 — the source is what it claims to be

```powershell
python -m fitlab_evaluation.cli doctor
```

The `source` section reports the commit, the tree, the number of bound source
files and the task pack SHA-256. `LOCAL_GIT_VERIFIED` means the trust
snapshot was checked against the local Git object database.

Independently:

```powershell
git rev-parse HEAD
git rev-parse HEAD^{tree}
git status --short          # must be empty for a live run
```

The trust snapshot's `source_sha256` maps each production and fixture file
to a canonical SHA-256. To verify a single file:

```powershell
git show HEAD:fitlab_evaluation/grader.py | git hash-object --stdin
```

Compare against the value in `trust.json`.

## Layer 2 — the task pack is the frozen one

```powershell
Get-FileHash fixtures/tasks-v2.json -Algorithm SHA256
```

Expected: `99df7e161d97f23fac67ceefcf1e567080e1ecbe04047c8875c4898ffb651552`.
The same value appears in `fixtures/tasks-v2.sha256` and in the report's
`source.task_pack_sha256`.

The pack declares eight cases: `E1 E2 E3 D1 D2 D3 D4 D5`. The R2 core tier is
the first six; see `fixtures/task-tiers.json` for the split and the
denominators.

## Layer 3 — the report is byte-reproducible

```powershell
python -m fitlab_evaluation.cli trust --output-dir v1/source
python -m fitlab_evaluation.cli passport --trust v1/source/trust.json --output-dir v1/passport
python -m fitlab_evaluation.cli trust --output-dir v2/source
python -m fitlab_evaluation.cli passport --trust v2/source/trust.json --output-dir v2/passport

(Get-FileHash v1/passport/passport.html -Algorithm SHA256).Hash
(Get-FileHash v2/passport/passport.html -Algorithm SHA256).Hash
```

The two hashes must be identical. There is no timestamp, no random value and
no transient host reading in the report.

## Layer 4 — the bundle manifest binds every file

```powershell
Get-Content v1/passport/manifest.json
```

For each listed file, `Get-FileHash` must equal the recorded digest.

## Layer 5 — a live evaluation record replays

```powershell
python -m fitlab_evaluation.cli verify --trust evidence/phase-a/live-validation-001/trust.json --evaluation evidence/phase-a/live-validation-001/evaluation.json
```

The verifier does not trust the record. It independently:

- re-hashes the source and matches it against the trust snapshot
- re-hashes the task pack and matches it
- re-validates the runtime identity in every row
- **recomputes every grade** from the raw stored response using the frozen
  grader and compares it with the stored grade
- **recomputes the summary** and every per-case count
- checks the row order, the case identity, the repeat number and the
  sequence label against the frozen protocol
- checks that each row has a pre-request and a pre-inference memory sample
  that passed the resource gate
- checks that observed inter-request pauses are at least one second
- checks that elapsed time is consistent with the recorded wall-clock
  interval and the declared timeout
- checks that a completed run really has every planned row measured
- checks that a stopped run keeps its full denominator

A record that fails any of these is refused with a specific code. See
`docs/TROUBLESHOOTING.md`.

Note on the shipped LIVE-002 record: it is bound to the historical source
commit it ran against (recorded in its `trust.json` `source` fields). The
public repository deliberately carries a fresh commit history, so a
git-resolution of that historical hash is expected to fail here — that is
the fail-closed design, not a defect. Use `verify_campaign` (Layer 7) for
byte-level verification of the sealed historical campaign, and
`fitlab evaluate` produces fresh campaigns whose trust resolves against
your own checkout's HEAD.

## Layer 5b — the sealed campaign re-verifies from a fresh checkout

```console
python -c "from fitlab_evaluation.seal import verify_campaign; print(verify_campaign('evidence/phase-a/live-validation-001')['status'])"
```

`COMPLETED` means every sealed byte matched the recorded hashes: the file
inventory, the FINISHED-status gates, the passport component bindings and
the trust/evaluation cross-binding. This path needs no Git history and no
network, and is exercised by
`tests/test_windows_byte_stability.py` (produce → seal → commit → fresh
clone → re-verify).

## Layer 6 — the report cannot be edited into a claim

The export path always rebuilds the report from verified facts and compares
the result with the object it was given. A hand-edited report fails with
`REPORT_MISMATCH`. There is no code path that writes a measured value that
did not come from a verified local-runtime record.

## What verification does not establish

A passing verification establishes **internal consistency and integrity
relative to a trusted checkpoint**. It does not establish:

- that a real model executed, rather than a well-formed synthetic record
  carrying a `LOCAL_RUNTIME` label
- who produced the file, when, or on what machine
- statistical reliability of the model
- general capability beyond the eight known test cases
- that the model would behave the same way on different hardware

Execution-origin corroboration requires a human able to observe the runtime.
For the shipped campaign, the complete machine-observed session stream
(runtime launch metadata, per-request latency, memory samples, response
hashes) is preserved inside the sealed `evaluation.json`; the historical F5
acceptance trail is in the project's internal records.

## Hash inventory (shipped artifacts)

| Artifact | Digest |
|---|---|
| `fixtures/tasks-v2.json` | `99df7e161d97f23fac67ceefcf1e567080e1ecbe04047c8875c4898ffb651552` |
| LIVE-002 final-seal.json | see `evidence/phase-a/live-validation-001/final-seal.json` (hashes every campaign byte) |

The sealed campaign's `final-seal.json` is the authoritative hash inventory
for the recorded LIVE-002 qualification; every entry is re-checked by
`verify_campaign`.
