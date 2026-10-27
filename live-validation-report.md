# LIVE-002 — authorized 8-request FitLab campaign (fitlab-f5-v1)

Campaign directory: `evidence/phase-a/live-validation-001`
Task: FITLAB-PHASEA-002 (executed once under the owner's written campaign authorization)
Report authored: 2026-10-26

## 1. Verdict summary

| Item | Value |
|---|---|
| Workflow command | `py -3.13 -m fitlab_evaluation.workflow run --output-dir evidence/phase-a/live-validation-001 --repeats 1` |
| Times executed | 1 (single authorized run; no rerun) |
| Process exit code | 0 |
| Session status | `FINISHED` |
| Evaluation status | `COMPLETED` |
| Execution kind | `LOCAL_RUNTIME` |
| Planned attempts | 8 |
| Durable attempted rows (`inference_requests`) | 8 |
| Measured rows (`measured_count`) | 8 |
| Rows passed / failed | 6 passed / 2 failed (E1, E2 — `value_or_type_mismatch`) |
| Run id | `deff26ab-d2db-4c77-b575-3dd92494b154` |
| Session window (UTC) | 2026-10-26T18:06:11.516441+00:00 → 2026-10-26T18:06:29.319398+00:00 |
| Protocol | `fitlab-f5-v1` (repeats 1, concurrency 1, 0 warmup, 30 s/request, 600 s budget, 1 s pause) |
| Task pack SHA-256 | `99df7e161d97f23fac67ceefcf1e567080e1ecbe04047c8875c4898ffb651552` |
| Seal verification | `COMPLETED` / `LOCAL_RUNTIME`, seal `FINISHED`, source `c3d72d7…` / tree `88c6bfe…` |

The two failing cases are **measured model-output failures**, not transport or
harness failures: both rows completed with HTTP-level success, `finish_reason`
`stop`, and a grade of `value_or_type_mismatch` under the frozen exact-equality
oracle. They are retained, not retried, per the protocol failure policy.

## 2. Source, campaign identity and scope

- Source HEAD at start and after the run: `c3d72d72d93e35ea6963c3f3fdaa34c39a7e3ca5`
  (tree `88c6bfef5183548e39447f82e5dd3b3786a4e89e`), working tree clean
  before the run. (The branch name is an internal engineering label and is
  not part of this release.)
- Protocol: `fitlab-f5-v1`; order "round-major, frozen case order"; first row is
  labelled `first_observed_request` on an already-loaded model
  (`cold_load_measured: false`, cache state unknown); no warmup requests.
- Frozen case ids, in executed order: `E1`, `E2`, `E3`, `D1`, `D2`, `D3`,
  `D4`, `D5` (fixtures/tasks-v2.json; its recorded SHA-256
  `99df7e16…b651552` matches the `task_pack_sha256` inside evaluation.json).
- Planning: `planning_status: UNAVAILABLE` (task-only run, no `--plan`), so
  planning input/output are null. No planning journey or hardware-fit claim is
  made here.

## 3. Model and runtime identity (observed from the run record)

| Field | Value |
|---|---|
| Runtime | Lemonade `2026.43.3` (`lemonade version 2026.43.3` from preflight) |
| Endpoint | `127.0.0.1:13305` (server), backend `http://127.0.0.1:8001/v1` |
| Model | `LFM2.5-1.2B-Instruct-GGUF` |
| Checkpoint | `LiquidAI/LFM2.5-1.2B-Instruct-GGUF:LFM2.5-1.2B-Instruct-Q4_K_M.gguf` |
| Backend / device | `llamacpp` / `cpu` |
| Context size | 2048 |
| `llamacpp_args` | `--parallel 1 --threads 2 --threads-batch 2` |
| Runtime config flags | `offline: true`, `no_fetch_executables: true`, telemetry `enabled: false` |
| Model discovery | `AVAILABLE_LISTED` (no pull, no install attempted) |
| Loaded model file | revision `8ed288026e23958ad9dfa92d53ed773a8eee7125`, 730,895,168 bytes |
| Preflight catalog SHA-256 | `2b3cb7011c67a73863cdb44462fb0a091a94e5aa2c97d2dc1ee1ac991f04a009` |
| Inference device verified | `false` (runtime reports `device: cpu`; GPU attribution unverified — no GPU used) |

No server start/stop, no configuration change, no model load/unload/download,
and no request beyond the 8 authorized ones was performed. The only runtime
interaction was the workflow's own read-only config/health reads and the 8
authorized completions.

## 4. Per-request rows (verbatim from `evaluation.json`)

All eight rows have `status: MEASURED`, `repeat: 1`, and distinct
`response_sha256` values (8 distinct digests).

| # | case | repeat | label | status | elapsed_seconds | response_sha256 | grade.passed | grade.reason |
|---|------|--------|-------|--------|-----------------|-----------------|--------------|--------------|
| 1 | E1 | 1 | first_observed_request | MEASURED | 1.8090167000000292 | `3590eda2eac8ad0182aba9e9a6b80106fc376a62dfd2f4e82abc830b8e4b6f5d` | false | value_or_type_mismatch |
| 2 | E2 | 1 | subsequent_request | MEASURED | 1.7857237000000623 | `f59558cf2c68d21789bcbcabdd6a20558345339d6dde194f135d7c9b97260317` | false | value_or_type_mismatch |
| 3 | E3 | 1 | subsequent_request | MEASURED | 0.5088886000000912 | `bd5e44ceb970bbc0a83fb2c67450500aa4494a37bd6841ca1667db21b6e84144` | true | exact_match |
| 4 | D1 | 1 | subsequent_request | MEASURED | 2.0054651000000376 | `6ba30817cdf356635de8424007bccc3f0ebc23984fe837001f94e5308f5b6a9b` | true | exact_match |
| 5 | D2 | 1 | subsequent_request | MEASURED | 0.9561075999999957 | `0959b8cc5197f50dc4e503f3dfcb43d200ca068b774ff734dd85aae859983d8b` | true | exact_match |
| 6 | D3 | 1 | subsequent_request | MEASURED | 0.6994478999999956 | `08800cb85d2c078f506ec359f57b15b3a85304275e82a4584546dbf7e93dc7fb` | true | exact_match |
| 7 | D4 | 1 | subsequent_request | MEASURED | 0.8833035000000109 | `6d046cee60b9767c18befa0540cb430b4edcb2b8380ccc4289605d3d2ab9ca01` | true | exact_match |
| 8 | D5 | 1 | subsequent_request | MEASURED | 0.8213362999999845 | `e8c59196f2f55313c44dd25843fa0a99296db5fe6b7986cdabde301ec6b0b407` | true | exact_match |

Summary block as produced by the product: `planned_count` 8, `measured_count` 8,
`passed_count` 6, `failed_or_unrun_count` 2, median client latency
0.9197055500000033 s. Per-case medians: E1 1.8090, E2 1.7857, E3 0.5089,
D1 2.0055, D2 0.9561, D3 0.6994, D4 0.8833, D5 0.8213 seconds.

### Observed failure detail (retained, not retried)

- **E1** (`fictional_structured_data_extraction`, expects `ram_gb` as a JSON
  integer 16). Model output:
  `{"device": "Orchid-13", "ram_gb": "16", "os": "Windows 11"}` — a string,
  not an integer, so exact equality fails. 32 completion tokens, `stop`.
- **E2** (`missing_field_recognition`, expects `missing: ["ram_gb"]`). Model
  output:
  `{"status": "MISSING", "missing": ["device", "ram_gb", "os"]}` — it
  over-reported absent fields (`device` and `os` are present in the prompt).
  28 completion tokens, `stop`.

Both are toy-task answer errors under a frozen deterministic oracle. Under the
protocol, a correct envelope with an incorrect answer is a measured failure and
does not stop later tasks; all 8 rows were therefore attempted.

## 5. Memory evidence

24 native Windows memory snapshots were recorded by the run
(`resource_samples`), taken before health, immediately before inference and
after each completion. Available physical bytes ranged 5,701,672,960 →
5,720,793,088 (minimum ≈ 5.31 GiB), always above the 4,481,437,114-byte gate.
Session preflight sample: total 16,665,960,448 B, available 5,713,485,824 B,
memory load 65 %, available commit 25,881,812,992 B.

These are whole-host observations — not process peak RAM, incremental model
memory, or continuous telemetry.

## 6. Seal / campaign verification (`fitlab_evaluation.seal.verify_campaign`)

> Publication note: the seal hashes shown below are the ORIGINAL campaign
> receipts, quoted verbatim from the run. The public edition redacted three
> runtime path fields from evaluation.json/session.json and rebuilt the seal
> accordingly; the authoritative in-repo receipt is
> `evidence/phase-a/live-validation-public-verification.json`, and
> `verify_campaign('evidence/phase-a/live-validation-001')` re-derives
> `COMPLETED` from the carried bytes.

Invoked from a standalone script against `evidence/phase-a/live-validation-001`;
full returned dict preserved at
`evidence/phase-a/live-validation-public-verification.json`:

```json
{
  "execution_kind": "LOCAL_RUNTIME",
  "passport": {
    "components": {
      "evaluation.json": "fc0bddbde22b930cd46ee0af9707826cfc0e9e026a19f8c4635df56ba65f78d4",
      "passport.html": "1fe041619cb718f1d985f4662cad581311408624261fc76646c93a2eb1cc36bc",
      "passport.json": "0a3248d9319d5ea091c2211bd8c2a4fcdd879c7d91ce67dbe5c866cb6b0ebff4",
      "trust.json": "2b10421d02e54690209fc2a85b69c0184245b915b644d415e26923f5277858dc"
    },
    "manifest_sha256": "23bdcfb198ec98ad6a5d749e0b6f577a0ed54fc321bf03dd94759b50f270c30e"
  },
  "schema_version": "fitlab-campaign-verification-v1",
  "seal": {
    "files": {
      "bootstrap.json": "4bbf48dbb481ff0332cf181672d512548ad90ebff3cd7a248f4272183f840362",
      "evaluation.json": "dc7e04f862f33cac6c3555c07f62219c9b9b019b8311c586084c3f1cffe43926",
      "manifest.json": "c2fe576ef1220b08a9c53089be57aafed12cd98e219e32fdf8d09ad899507424",
      "passport/evaluation.json": "fc0bddbde22b930cd46ee0af9707826cfc0e9e026a19f8c4635df56ba65f78d4",
      "passport/manifest.json": "23bdcfb198ec98ad6a5d749e0b6f577a0ed54fc321bf03dd94759b50f270c30e",
      "passport/passport.html": "1fe041619cb718f1d985f4662cad581311408624261fc76646c93a2eb1cc36bc",
      "passport/passport.json": "0a3248d9319d5ea091c2211bd8c2a4fcdd879c7d91ce67dbe5c866cb6b0ebff4",
      "passport/trust.json": "2b10421d02e54690209fc2a85b69c0184245b915b644d415e26923f5277858dc",
      "session.json": "615c1f7990d6392e04e347639e6051a4f3da820185d8a3bf7cf01f1dc2a9f8a2",
      "trust.json": "2b10421d02e54690209fc2a85b69c0184245b915b644d415e26923f5277858dc"
    },
    "schema_version": "fitlab-final-seal-v1",
    "status": "FINISHED"
  },
  "source": {
    "commit": "c3d72d72d93e35ea6963c3f3fdaa34c39a7e3ca5",
    "tree": "88c6bfef5183548e39447f82e5dd3b3786a4e89e"
  },
  "status": "COMPLETED"
}
```

The campaign therefore binds to the frozen source commit `c3d72d72…`
(tree `88c6bfef…`), the seal is `FINISHED`, the evaluation is `COMPLETED` with
`LOCAL_RUNTIME`, and the passport component hashes are the sealed ones (the
passport's `trust.json` and `evaluation.json` copies hash to their sealed
values).

**Byte-identity caveat (see §11).** `verify_campaign` hashes working-tree bytes.
The product wrote four of these files with Windows CRLF (`evaluation.json`,
`session.json`, `manifest.json`, `passport/manifest.json`), and the repository's
root `* text=auto eol=lf` rule rewrote those bytes to LF at commit time in the
first commit attempt, so a fresh checkout reported `SEAL_HASH_MISMATCH`. The
finding, its additive containment and the residual product defect are recorded
in §11. With the containment in place, a fresh detached checkout of the final
commit re-verifies `COMPLETED`.

## 7. Preflight snapshot

`py -3.13 scripts/preflight.py` (read-only; no server start, no model load, no
inference) → `evidence/phase-a/live-validation-preflight.json`, exit 0:

| Field | Value |
|---|---|
| timestamp | 2026-10-26T18:07:34.303411+00:00 |
| installed_version | `lemonade version 2026.43.3` |
| model | `LFM2.5-1.2B-Instruct-GGUF` |
| required_available_bytes | 4,811,437,114 |
| catalog_sha256 | `2b3cb7011c67a73863cdb44462fb0a091a94e5aa2c97d2dc1ee1ac991f04a009` |
| catalog_entry | `LiquidAI/LFM2.5-1.2B-Instruct-GGUF:LFM2.5-1.2B-Instruct-Q4_K_M.gguf`, recipe `llamacpp`, size 0.731 |
| cached_models | revision `8ed288026e23958ad9dfa92d53ed773a8eee7125`, `LFM2.5-1.2B-Instruct-Q4_K_M.gguf`, 730,895,168 B |
| memory | total 16,665,960,448 B, available 5,705,691,136 B, load 65 %, available commit 25,842,700,288 B |
| resource_gate | `PASS` |
| inference_requests | 0 |
| server_start_attempted / model_load_attempted | false / false |

## 8. Regression suite

Environment: Python 3.13.2 (`py -3.13`), pytest 9.1.1.
Log: `evidence/phase-a/live-validation-regression.txt`.

| Command | Result |
|---|---|
| `pytest tests/ -q` | `248 passed, 275 subtests passed` — 0 failures, 0 errors |
| `pytest -q -W error` | `248 passed, 275 subtests passed` — 0 failures, 0 errors, 0 warnings |

Both counts match the expected 248 for this repository, and both runs exit 0.
The suite is deterministic and contacts no model or external service
(documented in docs/INSTALL_AND_REPRODUCE.md:36-39).

### Note on the test environment (recorded honestly)

The product has no lockfile and no third-party dependencies (stdlib-only;
see docs/INSTALL_AND_REPRODUCE.md). No lockfile was invented, no network
install was attempted, and no existing file was modified. A `py -3.13 -m
venv` environment was created outside the repository (`--system-site-packages`,
so the already-installed pytest 9.1.1 is visible), and both suites were run
with that interpreter. This preserves the intent (isolated Python 3.13
interpreter, no downloads) without fabricating a lock step the product does
not have.

## 9. Evidence class and limits

- **Measured evidence class: MEASURED** for all eight live rows. Each row is a
  real `LOCAL_RUNTIME` completion against the already-loaded CPU model, with
  raw request and raw response retained verbatim in `evaluation.json`, plus a
  per-row `response_sha256` and client end-to-end `elapsed_seconds`.
- **Scope: toy tasks only.** The eight frozen cases are small synthetic
  structured-extraction and negative cases. This run is not a held-out
  benchmark, not a statistical reliability claim, and not evidence of general
  model capability.
- **Pass rate is descriptive:** 6/8 exact-match passes at one repetition.
  No confidence interval, no p95, no reliability claim is derivable from one
  repeat per case.
- **UNAVAILABLE and not claimed:** TTFT, decode-only tokens/second, peak
  process RAM, incremental model RAM, energy, sustained throughput, cold-start
  cost, GPU/NPU attribution (runtime reports CPU, attribution unverified).
  Client `elapsed_seconds` includes HTTP, prompt and decode overhead and is not
  a throughput measurement.
- Cache state is unknown; repeated prompts may use backend prefix caches. No
  cross-configuration speed comparison is made.
- The `LOCAL_RUNTIME` label is a provenance declaration by the real CLI, not
  cryptographic proof; the raw replies and runtime identity above are what an
  independent reviewer should inspect.
- This report is builder-authored engineering evidence. Acceptance is decided
  by the operator and an independent reviewer, not by this document.

## 10. Artifacts

Campaign directory (sealed, 10 files + `final-seal.json`):
`bootstrap.json`, `trust.json`, `manifest.json`, `session.json`,
`evaluation.json`, `passport/{evaluation.json,manifest.json,passport.html,passport.json,trust.json}`,
`final-seal.json`.

Additional evidence committed with this report:
`evidence/phase-a/live-validation-preflight.json`,
`evidence/phase-a/live-validation-public-verification.json`,
`evidence/phase-a/live-validation-regression.txt`,
`evidence/.gitattributes` (new, additive: byte-preservation for this sealed
campaign directory only — see §11).

Session-stream evidence: the complete ordered stream — every raw request, every
raw response, per-row `elapsed_seconds`, `response_sha256`, grade, runtime
identity and 24 memory snapshots — is preserved verbatim inside
`evidence/phase-a/live-validation-001/evaluation.json` (sealed and committed
above), with the summary rows transcribed in §4. No file was written outside
this campaign's working directory.

## 11. Reproducibility finding: sealed bytes vs. Git line-ending normalisation

This is a real finding discovered by verifying the committed artifact from a
fresh checkout, not from the directory where it was produced.

### Observation

`git worktree add --detach <temp> HEAD` of the first commit produced a clean
checkout in which `verify_campaign('evidence/phase-a/live-validation-001')`
raised `ArtifactError: SEAL_HASH_MISMATCH` (from `verify_final_seal`), even
though the tree was otherwise correct. Byte audit against the seal:

| File | run-time bytes == seal | checkout bytes == seal | seal bytes are CRLF |
|---|---|---|---|
| `bootstrap.json` | true | true | no |
| `evaluation.json` | true | **false** | yes |
| `manifest.json` | true | **false** | yes |
| `session.json` | true | **false** | yes |
| `passport/manifest.json` | true | **false** | yes |
| `passport/evaluation.json`, `passport/passport.html`, `passport/passport.json`, `passport/trust.json`, `trust.json` | true | true | no |

Exactly 4 of 10 sealed files differed, and in each case the checkout content
equalled the LF-normalised run-time content.

### Root cause

The product writes evidence through paths that apply Windows text-mode newline
translation, so those files are stored CRLF on disk, and `seal.inventory()`
correctly hashes those exact bytes:

- `workflow.py::_checkpoint` uses `tempfile.NamedTemporaryFile(mode='w', encoding='utf-8')` — produces `evaluation.json` and `session.json` CRLF on Windows;
- `artifacts.py::publish_bundle` writes `manifest.json` with `Path.write_text(...)` — CRLF on Windows;
- `report_v3.export_report` writes `passport/manifest.json` the same way.

The repository root `.gitattributes` declares `* text=auto eol=lf`, whose
purpose is to keep the *source* binding reproducible (`make_trust()` hashes Git
blobs, `run.identity()` hashes working-tree bytes). Applied to byte-hashed
evidence it has the opposite effect: the commit stores LF blobs while the seal
records CRLF digests, so no fresh checkout can reproduce the seal. This is the
first sealed campaign committed to this repository (`git log --all --
'*final-seal.json'` shows only this commit), so the defect had no precedent to
expose it earlier.

### Containment applied here (additive only)

`evidence/.gitattributes` (new file) marks this campaign directory
`-text`, so Git stores and restores the produced bytes verbatim on every
platform. The pattern is deliberately narrow
(`phase-a/live-validation-001/** -text`): the 52 other tracked evidence files
that are CRLF-on-disk with LF blobs stay under the root rule and remain clean.
No product file, test, or existing evidence file was modified, and the sealed
directory gained no new member.

Verified after containment: staged blobs carry the same CRLF byte counts the
seal hashes (1552, 138, 7, 9 CRLF sequences for the four files), `git status`
is clean, and a second fresh detached checkout re-runs
`verify_campaign` → `COMPLETED`.

### Residual defect — HISTORICAL STATUS: fixed in this release candidate

At the time of this campaign, the writer defect was real and uncorrected;
this section records that finding verbatim in its original scope. The
publication candidate that carries this report CORRECTS it at the writers
(`newline=""` on every evidence write path) with the required discriminating
regression — write a campaign, commit it under plain repository attributes,
check out fresh, require `verify_campaign` to pass — see
`tests/test_windows_byte_stability.py`. A `-text` attribute is no longer
necessary for newly produced sealed campaigns (it is retained for this
historical directory's byte preservation).

