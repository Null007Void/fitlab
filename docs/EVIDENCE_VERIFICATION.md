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
python -m fitlab_evaluation.cli verify --trust evidence/session-001/trust.json --evaluation evidence/session-001/evaluation.json
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
That is an outstanding F5 acceptance requirement, recorded in
`SPRINT_STATUS.md`.

## Hash inventory

| Artifact | Digest |
|---|---|
| `fixtures/tasks-v2.json` | `99df7e161d97f23fac67ceefcf1e567080e1ecbe04047c8875c4898ffb651552` |
| Local model file (730,895,168 bytes) | `b1b3de114215d9507409a662a501a631095a479a419584e8a2ded6304b19b4f5` |
| Accepted baseline commit | `f2c0cf8e1221ea15db4aa87739b99ed5e30e7409` |
| Accepted baseline tree | `3ab84e6584ef6ae68926c03bc5f76279bb91e78f` |

The review package archive and its member digests are recorded in
`evidence/review4/REVIEW_PACKAGE.md`.
