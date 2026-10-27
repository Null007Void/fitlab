# FITLAB-PHASEA-001 — Phase A closure report

> Publication context: this is a preserved historical engineering record of
> the Phase A evidence-chain work. References to internal review artifacts
> (evidence/review2, review3, review4) describe the project's private quality
> process; those directories are not part of this public repository. The live
> qualification superseding this phase's scope is the sealed LIVE-002 campaign
> in evidence/phase-a/live-validation-001/.

Offline, local-only closure of the FitLab F5 final-release evidence chain.
No inference was run. No Lemonade endpoint, provider, network service, Git
remote, publication or submission was contacted in any form.

Author: the engineering worker (PHASEA task context). Reviewer: independent integration reviewer.
This report is a builder-authored record of measurements; it is not an
acceptance verdict.

---

## 1. Identity and state

| Item | Value |
| --- | --- |
| Lane workspace | `<internal engineering workspace>` |
| Branch | `work/fitlab-f5-corrective-20261022` |
| Frozen candidate (start) | `08d6377f053d0ce8ac162ed329e2da02dc2a2cec` |
| Frozen candidate tree | `28576f859ec4c1024f32ac58249baf9d590b698f` |
| Lane start status | clean (`git status --porcelain` empty) |
| Origin remote | <private source origin>, read-only |
| Origin HEAD after work | `08d6377f053d0ce8ac162ed329e2da02dc2a2cec` (unchanged) |
| Interpreter | Python 3.13.2 (`py -3.13`), pytest 9.1.1 |

Source closure commits, in order:

| Commit | Tree | Content |
| --- | --- | --- |
| `e77af44d104844a4ba285641c3795e4cfcdf3f9b` | `2cf4997563b1c8909b341dd4e303ef494b49e07e` | `verify_campaign()`, owner class mapping, restored test, mapping tests |
| `a0233b8` | (child) | Correct campaign tree identity width (40 hex) |
| `060216c` | (child) | Compare campaign evaluation copies in canonical form |
| `2c2d775e03a7bc76402dcfb9fdb57be6154ad0e7` | `8f91f627dfcc142c07975d316e16e4e12d4ac22e` | Drop invalid raw-hash equality for the evaluation copy |
| `31992b957b49911cbdc58cd7e6e7532a43cabf53` | `1fb4f9476bf1b190ad50a0f2e4bc2f58ae4f375b` | Verification tools + preserved evidence |

The freeze commit is the direct child of `31992b9`: **its only change is this
report file**. `git log -1` / `git show -s --format='%H%n%T'` at review time
names that freeze commit and tree exactly.

Predecessor preservation (verified, not asserted):

- `git diff --diff-filter=D --name-only 08d6377..HEAD -- tests fitlab_evaluation fitlab_foundation` → 0 files deleted.
- `git diff 08d6377..HEAD -- tests | grep -E '^\+.*(skipTest|skipIf|skipUnless|expectedFailure)'` → 0 new skip markers.
- No accepted F1–F4 engineering was reopened, and no product behaviour outside
  the two named surfaces changed.

---

## 2. Block 1 — `verify_campaign()` (RED → GREEN, real defects found)

### 2.1 Restoring the stashed test file

The brief said the origin held the change in `stash@{0}`. **It did not**:
`git -C <origin> stash list` is empty. What survives is the stash's dangling
commit object, which Git still reports:

```
dangling commit 085cd7480553cf0edf90477fee2d163e5a2e2742
  parents 08d6377f053d0ce8ac162ed329e2da02dc2a2cec 8630dc949365dbdf0108442d5adac80c52d9ae61
  "WIP on work/fitlab-f5-corrective-20261022: 08d6377 Harden F5 campaign evidence sealing and verification"
  tests/test_f5_seal_security.py | 65 ++++++++++++++++++++++++++++++++++++++++++
```

The new blob is `bef74c9` (8,351 bytes). It was written into the lane with
`git cat-file blob bef74c9` — byte-exact, not retyped. The origin worktree
already carries exactly that blob (mtime `2026-10-25 20:46:18`, before this
session's lane clone at `20:55:58`), so the controller applied it there; the
origin was not modified by this work.

Proof of exact restoration: `git hash-object tests/test_f5_seal_security.py`
→ `bef74c9213c3a3c7b93bbeaa3f3416aa1d1a8d78`, and the committed blob at the
final source commit is the same value. `git diff --stat` shows exactly
`65 insertions(+)`, matching the stash. The test was never edited afterwards.

### 2.2 RED

`py -3.13 -m pytest tests/test_f5_seal_security.py::SealSecurityTests::test_real_passport_exporter_seal -q`

```
E   ImportError: cannot import name 'verify_campaign' from 'fitlab_evaluation.seal'
tests\test_f5_seal_security.py:218: ImportError
1 failed in 6.04s
```

Evidence: `evidence/phase-a/red-verify-campaign.txt`
(committed blob sha256 `f86ee8b8ac0db80199ab52cc006147b5bb4279b8d51599e9588cb57f895f82be`).

### 2.3 Implementation

`fitlab_evaluation/seal.py` gains, additively:

- `CAMPAIGN_SCHEMA = "fitlab-campaign-verification-v1"`, `EXECUTION_KINDS`,
  and a `COMMIT` pattern for 40-hex identity (`HASH` stays the 64-hex content
  pattern);
- `_campaign_source(root)` — strict echo of `source_commit` / `source_tree`;
- `verify_campaign(root)` — calls `verify_final_seal(root)` first and reuses it
  for the tamper-evident inventory, the FINISHED preconditions and the passport
  component hash binding. It then adds only campaign-level composition:

1. the seal must be `FINISHED` (a stopped/blocked directory raises
   `CAMPAIGN_NOT_FINISHED`; it is never upgraded);
2. `evaluation.json` must be a dict with `status == "COMPLETED"` and a known
   `execution_kind` (`LOCAL_RUNTIME` or `SYNTHETIC_TEST`), else
   `CAMPAIGN_INVALID_EVALUATION`;
3. `trust.json` must be a `fitlab-trust-v1` record with 40-hex commit and tree,
   else `CAMPAIGN_INVALID_TRUST`;
4. the passport's own `trust.json` component must hash to the sealed
   `trust.json` bytes, else `CAMPAIGN_TRUST_BINDING_MISMATCH`;
5. the passport's own `evaluation.json` must exist and carry the same
   evaluation content, else `CAMPAIGN_EVALUATION_BINDING_MISMATCH`.

It returns `status`, `execution_kind`, the verified `seal`, the passport
component map plus `manifest_sha256`, and the source identity echo. Every
deviation raises `ArtifactError`; no new evidence is invented and no sealed
check is re-implemented.

### 2.4 Two real defects the restored test caught

Both were genuine implementation errors, fixed as separate commits so the
failure sequence stays visible:

| Failure | Cause | Correction |
| --- | --- | --- |
| `CAMPAIGN_INVALID_TRUST` on every real campaign | a tree id is 40 hex, but the check reused the 64-hex content `HASH` | `COMMIT` pattern (`a0233b8`) |
| `CAMPAIGN_EVALUATION_BINDING_MISMATCH` on a correct campaign | the campaign checkpoint writes `evaluation.json` in text mode while the passport bundle publishes binary, so the two sealed raw hashes legitimately differ on Windows | presence plus canonical (line-ending-independent) content equality via `source_digest` (`060216c`, `2c2d775`) |

A third observation, recorded because it constrains every future run: the
restored test derives `trust` from HEAD and compares it with the worktree
identity, so it fails with `SOURCE_MISMATCH` while any file under
`fitlab_evaluation/`, `fitlab_foundation/` or `fixtures/` is uncommitted. GREEN
therefore *requires* a committed source tree; that is the product's
`SOURCE_NOT_FROZEN` invariant, not a test defect.

### 2.5 GREEN

```
py -3.13 -m pytest tests/test_f5_seal_security.py::SealSecurityTests::test_real_passport_exporter_seal -q
1 passed in 3.99s
```

Evidence: `evidence/phase-a/green-verify-campaign.txt`
(committed blob sha256 `b593564d2c8d90853ea395e8794be535f02c70b58dbaaa3d1f773164b49ad468`).

`verify_campaign()` on a synthetic finished campaign (fixture built by
`scripts/phase_a_synthetic_campaign.py` through the real exporter, the real
final-seal writer and a `SYNTHETIC_TEST` record; no socket opened):

| Field | Value |
| --- | --- |
| `status` | `COMPLETED` |
| `execution_kind` | `SYNTHETIC_TEST` |
| `seal.status` | `FINISHED` (10 sealed files) |
| `passport.manifest_sha256` | `e7e42081d4b824efa93fc68e10c4363387c4815aa8d680339cc72802cdd7598d` |
| `passport` components | `evaluation.json f303308d…`, `passport.html c9522aa4…`, `passport.json 61fe59b9…`, `trust.json e72d4d58…` |
| `source` echo | `2c2d775e03a7bc76402dcfb9fdb57be6154ad0e7` / `8f91f627dfcc142c07975d316e16e4e12d4ac22e` |
| Report `evidence_class` | `SYNTHETIC TEST EVIDENCE` |
| `capability_verdict` | `NOT_EVALUATED`; every claim/task label `UNKNOWN` |

Evidence: `evidence/phase-a/synthetic-campaign-verification.json`
(committed blob sha256 `b81d1cab42155de73dd3f80c2c2043c7d7d24f2f3c6222e03dbbd6fa766703d1`).
This fixture is synthetic evidence and is never described as measured.

---

## 3. Block 2 — full regression

Command, at source-complete commit `31992b9` with a clean working tree:

```
py -3.13 -m pytest tests/ -q
248 passed, 275 subtests passed in 41.18s
```

- failures: **0**
- skips: **0**
- errors: **0**
- collected: 248 (239 before the additive mapping tests were added; `--collect-only`
  at the restored-test-only state reported exactly `239 tests collected`, matching
  the owner's expectation)
- the 9 added tests are the evidence-class mapping suite; no existing test was
  modified, and the restored test runs unmodified.

Evidence: `evidence/phase-a/regression-full.txt`
(committed blob sha256 `1a9f1030e0ead1c970061ba22b4f9009e3f837cc341cea535929f7ca45a24390`
for the recorded run).

---

## 4. Block 3 — historical 69-request campaign binding (read-only)

Everything in this block was read, never written. The origin/event directories
are outside the lane and were opened read-only.

### 4.1 Byte integrity of the handoff index

`scripts/verify_handoff_index.py`, run against
`…/Event Coordination/fitlab-f5-multicampaign-retry-20261022/HANDOFF_INDEX.json`
with the two archive members supplied explicitly:

| Result | Value |
| --- | --- |
| index schema | `fitlab-private-handoff-v2`, mission `FITLAB-F5-MULTICAMPAIGN-RETRY-20261022` |
| members declared | 72 |
| members verified | **72** |
| members failed | **0** |
| bytes verified | 1,737,433 |
| verdict | `PASS` |

External members, verified by the same byte/hash rule:

| Member | Bytes | SHA-256 |
| --- | --- | --- |
| `history/fitlab-f5-multicampaign-blocked-20261022.zip` | 168,990 | `25aa85811bd187d9d06024a276fbd14609c76b1f90c3ae57a5999eab721075ad` |
| `source/fitlab-f5-readiness-7cfc6d11e385.zip` | 168,298 | `aba1c99ad7898c708050bd3c80719416b659dc20866652c6ce6f948e7e041377` |

Evidence: `evidence/phase-a/historical-handoff-verification.json`
(committed blob sha256 `32883d7de57bdf31ae6671e5713dceb82916cc469b2908d129326bbf6dae354b`).

### 4.2 Delivery archive (self-binding)

| Item | Value |
| --- | --- |
| Delivery zip | `…/fitlab-f5-multicampaign-retry-package/fitlab-f5-multicampaign-retry-20261022.zip` |
| SHA-256 | `4f89f471ef5bb1cf354ed8052dce25174f83a33f890a3799bfe3b6d7d05cab4b` (matches the owner's stated value) |
| Bytes / members | 545,526 / 73 unique (72 indexed payload members + the index) |
| CRC check | `PASS` (per `DELIVERY_RECORD.json`) |
| `HANDOFF_INDEX.json` sha256 | `517a2418a73c7e8424e60545ba717fb3513a0feb3d99fae8bf6833093582d99c`, identical on disk and inside the delivery archive |

The index's own members are otherwise bound by that index; the index itself is
bound by the outer archive SHA-256 recorded in `DELIVERY_RECORD.json`.

### 4.3 Request math

`24 + 24 + 9 + 9 + 3 = 69` (campaign A 24, B 24, C 9, D 9, E 3), matching the
index field `inference_requests: 69` and `DELIVERY_RECORD.requests.total`.

### 4.4 Campaign source identity and the genuine passport

| Item | Value |
| --- | --- |
| Campaign source commit | `7cfc6d11e385014d13a8ca0afffd3e763ed3d735` |
| Campaign source tree | `3596387cfbbe30f42613ebff1d68ebfb504ac7fa` |
| Passport | `passport-workload-to-hardware`, schema `fitlab-capability-passport-v3` |
| Passport run | `execution_kind LOCAL_RUNTIME`, `status COMPLETED`, `requested_repeats 3` |
| Rows | 24 rows, all `MEASURED`; 8 unique cases × 3 repeats |
| Grades | 18 passed of 24 planned; median client latency 0.960628100001486 s |
| Capability verdict | `OBSERVED_TOY_TASKS_ONLY` |
| Passport's own trust | `source_commit 7cfc6d1…`, `source_tree 3596387…` |

**Evidence class: `HISTORICAL MEASURED EVIDENCE`.** It was measured at
`7cfc6d1`, by code at `7cfc6d1`. It is **not** a product of the frozen
candidate `08d6377` and is never labelled as one anywhere in this closure.

---

## 5. Block 4 — passport evidence-class audit

Change surface: `fitlab_evaluation/report_v3.py` only, plus tests. The stored
machine class is untouched; a new `evidence_label` is derived at presentation
time, and a `evidence_class_vocabulary` block publishes the mapping.

Mapping (presentation layer, additive):

| Machine class | Owner label |
| --- | --- |
| `MEASURED` | `MEASURED` (unchanged); `SYNTHETIC TEST EVIDENCE` when the record's `execution_kind` is `SYNTHETIC_TEST`; `HISTORICAL MEASURED EVIDENCE` only with an explicit historical binding |
| `ESTIMATED`, `CALCULATED`, `DECLARED` | `ANALYTICAL ESTIMATE` |
| `UNSUPPORTED` | `UNKNOWN` (no value exists; the reason stays in `limitation`) |
| `UNKNOWN` | `UNKNOWN` (unchanged) |

Ordering is deliberate: a synthetic record can never be presented as measured,
even when a historical binding is also supplied (tested). The historical
binding is an explicit, validated record — campaign id, request count, 40-hex
commit and tree, 64-hex delivery digest, note — and any missing, extra or
malformed field raises `INVALID_HISTORICAL_BINDING`. It never measures
anything in the current report: `capability_verdict` stays `NOT_EVALUATED` and
claims stay `UNKNOWN`.

Rendered output uses the labels in the verdict line, the metric cards, the
feasibility table, the task ledger and a new "Earlier measured campaign bound
to this report" section; the legend lists exactly the five owner classes. A
forged `evidence_label` is rejected because `render_report()` rebuilds the
report and compares (`REPORT_MISMATCH`).

### 5.1 Per-field audit — historical genuine passport (`fitlab-capability-passport-v3`)

| Field | Machine class | Owner label |
| --- | --- | --- |
| claim `tasks` | `MEASURED` | `MEASURED` |
| claim `core_tasks` | `MEASURED` | `MEASURED` |
| claim `latency` | `MEASURED` | `MEASURED` |
| claim `peak_ram` | `UNKNOWN` | `UNKNOWN` |
| claim `ttft` | `UNKNOWN` | `UNKNOWN` |
| claim `decode` | `UNKNOWN` | `UNKNOWN` |
| `plan:…:conditional_decode_bandwidth` | `ESTIMATED` | `ANALYTICAL ESTIMATE` |
| `plan:…:decoder_flops_per_token` | `ESTIMATED` | `ANALYTICAL ESTIMATE` |
| `plan:…:idealized_weight_payload` | `ESTIMATED` | `ANALYTICAL ESTIMATE` |
| `plan:…:target_compute_rate` | `ESTIMATED` | `ANALYTICAL ESTIMATE` |
| `plan:…:effective_bandwidth` | `UNKNOWN` | `UNKNOWN` |
| `plan:…:independent_physical_capacity` | `UNKNOWN` | `UNKNOWN` |
| `plan:…:known_memory_baseline` | `UNKNOWN` | `UNKNOWN` |
| `plan:…:kv_cache` | `UNSUPPORTED` | `UNKNOWN` |
| `plan:…:runtime_overhead` | `UNKNOWN` | `UNKNOWN` |
| `plan:…:whole_system_fit` | `UNKNOWN` | `UNKNOWN` |
| tasks `E1`, `E2`, `E3`, `D1`, `D2`, `D3`, `D4`, `D5` | `MEASURED` (each) | `MEASURED` |

Totals: 11 `MEASURED`, 4 `ANALYTICAL ESTIMATE`, 9 `UNKNOWN`; 24 fields; zero
labels outside the owner vocabulary. Those fields are `MEASURED` **at
`7cfc6d1`**, so in the owner's vocabulary the whole artifact is
`HISTORICAL MEASURED EVIDENCE` (the per-field table shows the field class; the
historical qualifier is a property of the artifact's provenance, not a licence
to relabel a value).

### 5.2 Per-field audit — `reports/capability-passport-v2/passport.json`

Schema `fitlab-capability-passport-v2`, `evaluation_state NO_EVIDENCE`,
`capability_verdict NOT_EVALUATED`: 13 fields (claims `tasks`, `latency`,
`peak_ram`, `ttft`, `decode`; tasks `E1`–`D5`), **all** `UNKNOWN` → `UNKNOWN`.
This committed artifact predates the current generator: it has no
`core_tasks` claim, no `evidence_label` field and no `evidence_class` field.
It is left byte-unchanged; the labels above are what the current mapping layer
*would* render, not a rewrite of the stored artifact.

Evidence: `evidence/phase-a/passport-class-audit.json`
(committed blob sha256 `e04aadbfc15bf894a64bbf0658b92c3632d9ca4183f27093f9e6faabdc29bb5f`).
The `"stored_label_field_present": false` entries in that file are the honest
statement that both audited artifacts were generated before this change.

### 5.3 Mapping tests

`tests/test_passport_evidence_classes.py` (9 tests, 14 subtests): the mapping
matrix; evaluation-label derivation; planning estimates labelled
`ANALYTICAL ESTIMATE` with raw `ESTIMATED`/`CALCULATED` preserved; a synthetic
run labelled `SYNTHETIC TEST EVIDENCE` with every field `UNKNOWN`; the explicit
historical binding labelled `HISTORICAL MEASURED EVIDENCE` without measuring
this build; rejection of incomplete/forged bindings; rejection of a forged
label; the published vocabulary; and export carrying the binding.

---

## 6. Inference-sufficiency determination — **NO**

### 6.1 Finding

The frozen candidate `08d6377` does **not** contain sufficient genuine
end-to-end V3 evidence. There is no V3 passport produced by the final build.

Measured evidence for that conclusion (all from the lane's own committed
candidate content, not from prose):

| Check | Observation |
| --- | --- |
| Every `passport.json` in the candidate (33 files) | `capability_verdict`: 33 × `NOT_EVALUATED`; **0** × `OBSERVED_TOY_TASKS_ONLY` |
| Schema spread | 30 × `fitlab-capability-passport-v2`, 1 × `fitlab-capability-passport-v3` (`NO_EVIDENCE`), 2 × `fitlab-passport-v1` |
| Every `evaluation.json` in the candidate (14 files) | all `execution_kind = SYNTHETIC_TEST`; none `COMPLETED` + `LOCAL_RUNTIME` |
| Only `LOCAL_RUNTIME` record present (`evidence/review2/native-resource-gated-run.json`) | `STOPPED`, 0 rows, 24 planned, measured 0 — resource-gated, no inference |
| `evidence/review3/native-session-001` | `BLOCKED`, `inference_requests: 0`, memory load 96% |
| `evidence/review4/passport-preview` | V3 passport, `evaluation_state NO_EVIDENCE` |

The 69-request campaign evidence is real measured evidence, but it belongs to
`7cfc6d1` (`HISTORICAL MEASURED EVIDENCE`). The offline passport previews are
synthetic. Neither substitutes for one genuine `LOCAL_RUNTIME` V3 passport
generated by `08d6377`.

Therefore the mission **stops here**, per the owner's instruction. No Lemonade
request was made; no runtime was started, loaded, configured or contacted.

Evidence: `evidence/phase-a/lane-passport-census.json`
(committed blob sha256 `51c4866b63d313240f31b5f2c7c1846aa206bae8a4ccd3e6957c52ceb0c84126`)
and `evidence/phase-a/lane-evaluation-census.json`
(committed blob sha256 `90e35eef398263c216a18f7c44cd3ef8704916e303c3185efe9961856e0e29df`).

### 6.2 The exact missing proof

One genuine workflow through the final build:

1. `fitlab_evaluation.workflow.execute()` reaches `record.status == "COMPLETED"`
   with `execution_kind == "LOCAL_RUNTIME"` for the frozen model;
2. the real V3 exporter writes `passport.json` with
   `evaluation_state COMPLETED` and `capability_verdict OBSERVED_TOY_TASKS_ONLY`;
3. `final-seal.json` is written with `status FINISHED` over that inventory;
4. `verify_campaign()` returns `status COMPLETED`, `execution_kind
   LOCAL_RUNTIME`, a `FINISHED` seal and a matching passport component map.

Nothing in the candidate currently produces items 1–4 together. Items 3–4 are
now implemented and proven on a synthetic fixture only.

### 6.3 Minimum validation plan (owner-authorized window only)

Owner-authorised, offline, ready-only. Preconditions, all fail-closed in the
product: Lemonade running locally with `LFM2.5-1.2B-Instruct-GGUF` already
loaded (`CHECKPOINT LiquidAI/LFM2.5-1.2B-Instruct-GGUF:LFM2.5-1.2B-Instruct-Q4_K_M.gguf`,
runtime `2026.42.1`); `/internal/config` returning `offline: true`,
`no_fetch_executables: true`, telemetry disabled and no non-local routing field;
free physical/commit memory ≥ 4,811,437,114 bytes; no model load, unload, pull
or configuration change.

**Minimum run that can yield `COMPLETED` — 8 requests.** The frozen protocol
`fitlab-f5-v1` is round-major over 8 frozen cases at `--repeats 1`; a 3–5
request run cannot satisfy the protocol and can only end `STOPPED`, which
`verify_campaign()` correctly refuses (`CAMPAIGN_NOT_FINISHED`). There is no
smaller COMPLETED unit without changing frozen protocol semantics, which this
task must not do.

```
py -3.13 -m fitlab_evaluation.workflow run \
  --output-dir evidence/phase-a/live-validation-001 \
  --repeats 1
```

What is measured: 8 real chat completions, one per frozen case, with per-row
`elapsed_seconds`, `response_sha256`, strict grades, and memory samples before
health, before each inference and after completion; `session.inference_requests`
counts durable attempted rows.

How it is sealed: `execute()` writes `session.json`, exports the passport from
the verified record, then writes `final-seal.json` and re-verifies it; the run
is accepted only if `verify_campaign(<dir>)` returns `COMPLETED` /
`LOCAL_RUNTIME` / seal `FINISHED`, and `py -3.13 -m pytest tests/ -q` stays
green afterwards.

Optional transport smoke, **not sufficient for admission** (3–5 requests): a
deliberately stopped session that proves connectivity and fail-closed sealing.
It produces `status STOPPED`, seal `STOPPED`, and `verify_campaign()` must
raise `CAMPAIGN_NOT_FINISHED` — that is the expected, honest result, not a
passport.

For a fully protocol-complete passport (`complete_protocol: True`), the run
needs `--repeats 3`, i.e. 24 requests; that is the owner's call, not this
lane's.

Cost/risk: 8 local CPU requests at ~1 s median latency, one session, no
external spend. Stop before the owner-stated promotion deadline.

---

## 7. Remaining work to submission-ready

1. Owner authorises and runs the 8-request (or 24-request) local validation
   above; the engineering worker then binds the resulting campaign with `verify_campaign()` and
   records its seal/passport hashes as `MEASURED`.
2. Independent reviewer confirms: the restored test is byte-identical to the
   stash blob, `verify_campaign()` adds no duplicate sealed check, and the
   mapping layer changes no stored class or value.
3. Decide whether the submission Passport should bind the 69-request campaign
   as `HISTORICAL MEASURED EVIDENCE` alongside the new live run; the mechanism
   exists (`historical=` binding) but no submission artifact was regenerated
   here.
4. Regenerate the committed judge-facing passport (`reports/capability-passport-v2/`)
   only through the current generator, so its stored labels and `core_tasks`
   fields match the audited code — deliberately not done here.
5. Owner-side only: publication/submission, and the portfolio session-stream
   capture (`evidence_requirements`). This worker is barred from private
   portfolio records, so that record must be produced by the orchestrator.

---

## 8. Evidence index (commit `31992b9`, blob-normalized SHA-256)

Raw working-copy hashes differ from these only by Git's LF normalization of
CRLF text; the values below are `git show 31992b9:<path> | sha256sum`.

| Path | SHA-256 |
| --- | --- |
| `evidence/phase-a/red-verify-campaign.txt` | `f86ee8b8ac0db80199ab52cc006147b5bb4279b8d51599e9588cb57f895f82be` |
| `evidence/phase-a/green-verify-campaign.txt` | `b593564d2c8d90853ea395e8794be535f02c70b58dbaaa3d1f773164b49ad468` |
| `evidence/phase-a/regression-full.txt` | `1a9f1030e0ead1c970061ba22b4f9009e3f837cc341cea535929f7ca45a24390` |
| `evidence/phase-a/synthetic-campaign-verification.json` | `b81d1cab42155de73dd3f80c2c2043c7d7d24f2f3c6222e03dbbd6fa766703d1` |
| `evidence/phase-a/historical-handoff-verification.json` | `32883d7de57bdf31ae6671e5713dceb82916cc469b2908d129326bbf6dae354b` |
| `evidence/phase-a/passport-class-audit.json` | `e04aadbfc15bf894a64bbf0658b92c3632d9ca4183f27093f9e6faabdc29bb5f` |
| `evidence/phase-a/lane-passport-census.json` | `51c4866b63d313240f31b5f2c7c1846aa206bae8a4ccd3e6957c52ceb0c84126` |
| `evidence/phase-a/lane-evaluation-census.json` | `90e35eef398263c216a18f7c44cd3ef8704916e303c3185efe9961856e0e29df` |
| `scripts/verify_handoff_index.py` | `1f179db70cb636aa2ac1936a0857c9d40f3adcdf8d0d76da09f91038f2fd2351` |
| `scripts/audit_evidence_classes.py` | `1e10dea6e29a6a1e26b2a45ed3d06096abac7c9599a51c7ed803f120a727d5db` |
| `scripts/phase_a_synthetic_campaign.py` | `859a51b645019ced48454f0ce265154e7c4116df2380c2d38871d6c79e5e1109` |
| `scripts/summarize_evaluation.py` | `98ad0869d484575faeff81f6e99bc7afce9ce7368ca136e8d88592da6b40df6d` |

---

## 9. Boundaries observed

- No inference, no Lemonade runtime call, no network, no credential, no AMD
  account action, no publication, no submission, no Git remote, no paid service.
- The 69-request campaign was not rerun; it was byte-verified read-only.
- The origin clone was not modified: its HEAD is still `08d6377` and the one
  modified file there (`tests/test_f5_seal_security.py`, blob `bef74c9`) predates
  this session by nine minutes.
- Accepted F1–F4 engineering was not reopened; the change surface is
  `seal.verify_campaign()` (additive), the `report_v3` presentation mapping
  (additive), and tests.
- This report does not claim acceptance. An independent reviewer decides.
