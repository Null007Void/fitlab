# FitLab
### Local AI Capability Passport

**What can this machine and model actually do?**

FitLab answers with evidence classes instead of vibes. It computes what a
workload needs, measures what a local model actually delivers, and publishes
both as a single offline **Capability Passport** — an HTML document that
tells the truth about what was measured and what remains unknown.

Python ≥ 3.12 (demonstrated on CPython 3.13). The runtime dependency set is
the Python standard library only — no account, no network, no GPU required
for planning; the evaluation path talks only to a local runtime you already
run. (Installing the optional `fitlab` console script from a clone uses the
standard editable-install build backend; see Installing below.)

## The user journey

```console
fitlab inspect      # prerequisites, hardware, source identity — no inference
fitlab evaluate     # the guarded local evaluation (inference happens here)
fitlab passport     # render the offline Capability Passport from the evidence
```

- `fitlab inspect` reports your host, the registered local model profile and
  source identity. Every value carries its evidence class; anything
  unknown is shown as `UNKNOWN`/`UNAVAILABLE`, never guessed.
- `fitlab evaluate` drives the accepted F5 workflow: frozen task pack,
  frozen deterministic grader, memory gates before every request, explicit
  one-shot protocol — **failed model outputs are recorded, never retried.**
  Without a prepared local runtime it refuses fast (BLOCKED), by design.
- `fitlab passport` renders the Passport (offline HTML + JSON + a verifiable
  trust bundle) from a campaign's sealed evidence.

Advanced surfaces stay available: `python -m fitlab_evaluation.cli
plan|trust|passport|verify|gate|doctor` and
`python -m fitlab_evaluation.workflow run|postprocess`.

## Evidence classes

Every number FitLab produces carries exactly one class:

| Class | Meaning |
|---|---|
| `MEASURED` | observed by a verified local-runtime run |
| `CALCULATED` | exact arithmetic under a declared formula and inputs |
| `ESTIMATED` | exact arithmetic applied to an idealization or heuristic |
| `DECLARED` | an owner-supplied planning assumption |
| `UNSUPPORTED` | the engine refuses to apply a formula here |
| `UNKNOWN` | the conclusion cannot be produced from supported assumptions |
| `UNAVAILABLE` | an observation is missing, or lacks provenance to classify |

An `UNKNOWN` is a real answer. FitLab prefers a blank you can see over a
plausible number you might plan around. Full register:
[docs/FORMULAS_AND_LIMITATIONS.md](docs/FORMULAS_AND_LIMITATIONS.md).

## What the numbers mean

- `CALCULATED` is exact arithmetic — **not** a hardware measurement.
- Idealized weights are not file size, not loaded RAM, not resident set size.
- Standard KV-cache arithmetic is refused for sliding-window, MLA, paged,
  offloaded and hybrid short-convolution attention.
- Architecture and attention default to `UNKNOWN`.
- Effective bandwidth without a verified source stays `UNAVAILABLE`.
- Unified shared memory is never counted as a second physical RAM pool.
- Physical fit is never inferred from idealized weights, cache and capacity.

## Recorded campaigns

### HISTORICAL CAMPAIGN — Lemonade 2026.42.1

- 69 local inference requests executed in an earlier campaign
- historical operating-envelope evidence
- lifecycle-transition details remained self-reported where documented
- preserved under the Phase A reports; superseded as qualification by
  LIVE-002 below

### FINAL LIVE-002 QUALIFICATION — Lemonade 2026.43.3

| Item | Value |
|---|---|
| Runtime | Lemonade 2026.43.3, llama.cpp backend, CPU |
| Model | LiquidAI LFM2.5-1.2B-Instruct GGUF, Q4_K_M quantization, context 2048 |
| Execution kind | `LOCAL_RUNTIME` (real inference, once per request) |
| Requests | 8/8 authorized protocol requests executed exactly once |
| Outcome | 6 pass / 2 retained model-output failures — **failures are not retried** |
| Status | `COMPLETED` / `LOCAL_RUNTIME` / `FINISHED` (sealed) |
| `complete_protocol` | `false` — the full F5 protocol specifies 3 repetitions per case; this run executed 1 repetition. **Bounded qualification, not a general reliability claim.** |

The two failures are honest model-output errors under the frozen grader
(a string where an integer was expected; an over-reported missing-field
list), retained verbatim in the sealed evidence.

Machine demonstrated: MSI Summit E13 AI Evo A1MTG — Intel Core Ultra 7 155H,
16 GB RAM, Windows 11 Home.

**Regression evidence for this release:** 272 tests passed + 303 subtests
(warning-strict run identical), including the byte-stability regression that
proves sealed evidence re-verifies `COMPLETED` from a fresh checkout.

The sealed campaign + rendered Passport live in
[`evidence/phase-a/live-validation-001/`](evidence/phase-a/live-validation-001/manifest.json).
Its integrity is independently checkable:

```console
python -c "from fitlab_evaluation.seal import verify_campaign; print(verify_campaign('evidence/phase-a/live-validation-001')['status'])"
```

> `COMPLETED` — no trust in the messenger required: the seal hashes every
> byte and re-binds the passport components. The campaign's `source` fields
> point at the exact source tree it ran against (a historical record; the
> public repository carries a fresh commit history).

## Planning without a runtime

The deterministic planner works offline with **zero inference**:

```console
python -m fitlab_evaluation.cli plan hardware_to_workloads --budget-bytes 17179869184 --output-dir my-plan
python -m fitlab_evaluation.cli plan workload_to_hardware --model-file path\to\model.gguf --output-dir my-plan
```

GGUF headers are parsed for real metadata — planner results are
`CALCULATED`/`DECLARED`/`UNKNOWN`, never presented as measurements.

## Evidence integrity

Campaigns are sealed: every file byte-hashed into `final-seal.json`, the
passport bundle component-bound, the trust snapshot bound to the exact
source tree (`SOURCE_NOT_FROZEN` otherwise). A fresh checkout of any sealed
campaign re-verifies byte-for-byte — including on Windows, where every
evidence writer now emits deterministic LF bytes
([tests/test_windows_byte_stability.py](tests/test_windows_byte_stability.py)
proves it through commit → fresh clone → `verify_campaign`).

Verification walkthrough: [docs/EVIDENCE_VERIFICATION.md](docs/EVIDENCE_VERIFICATION.md).

## Repository layout

```
fitlab_evaluation/   evaluation engine, CLI, workflow, seal, redaction
fitlab_foundation/   deterministic planner, contracts, arithmetic
examples/            runnable, offline examples
fixtures/            frozen task packs (v1 historical, v2 accepted)
docs/                architecture, evidence classes, reproduction, privacy
evidence/            sealed LIVE-002 campaign + per-phase records
tests/               272 tests / 303 subtests, stdlib unittest + pytest-compatible
```

## Prerequisites

- **Python ≥ 3.12** (3.13 demonstrated). 3.11 is known-incompatible
  (`pathlib.Path.is_junction` used by the seal integrity checks).
- No third-party Python packages — the product itself is stdlib-only.
- Test tooling: `pytest` is optional; the suite also runs with
  `python -m unittest discover -s tests`.
- For `fitlab evaluate`: a running local **Lemonade** runtime with the model
  already loaded and offline (`no_fetch_executables`) — FitLab never starts,
  stops, configures, loads or downloads anything.
- The local model is **not bundled**; the runtime manages its own cache.
- No container is required for this release.
- Source-binding expectations: `evaluate` requires a clean checkout (git
  trust binding); the sealed-evidence verifier has no git dependency.

## Documentation

- [Quick start](docs/QUICKSTART.md)
- [Product guide](docs/PRODUCT_GUIDE.md)
- [Install & reproduce](docs/INSTALL_AND_REPRODUCE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Formulas & limitations](docs/FORMULAS_AND_LIMITATIONS.md)
- [Evidence verification](docs/EVIDENCE_VERIFICATION.md)
- [Privacy](docs/PRIVACY.md)
- [Risk register](docs/RISK_REGISTER.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Sample passport

The shipped LIVE-002 Capability Passport (real recorded run; runtime cache
paths redacted to placeholders) is at
[`evidence/phase-a/live-validation-001/passport/passport.html`](evidence/phase-a/live-validation-001/passport/passport.html)
— a fully offline, self-contained HTML document.

## License

MIT for FitLab's original source — see [LICENSE](LICENSE) and
[NOTICE.md](NOTICE.md) for third-party/runtime/model provenance (all external,
none redistributed).