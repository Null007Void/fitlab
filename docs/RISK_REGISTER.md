# Technical risk register

Ordered by severity. "Blocking" means the risk prevents a public release or
a competition submission.

## Blocking risks

### R1 — No source license

**Risk.** The repository has no `LICENSE` file. The code was authored under an
owner grant and repository access is not a redistribution grant. Publishing
without a license grant is not a valid open-source release.

**Impact.** The submission could not be lawfully distributed, and the
competition could treat the submission as unlicensed.

**Mitigation.** The owner chooses a license and adds the `LICENSE` file with
the correct copyright holder and year. `docs/RELEASE_READINESS.md` section 2.1
records the position.

**Owner action required.** Yes.

### R2 — Model license not established

**Risk.** The GGUF header declares a license name (`lfm1.0`) and a link
(`LICENSE`), but no license text exists in the local cache and none was
downloaded. A name is not a grant. The LFM license's actual terms,
attribution duties and any redistribution or use conditions are unknown.

**Impact.** Any statement about model license eligibility would be unfounded.
Bundling weights would be a licensing act with unknown terms.

**Mitigation.** Obtain the controlling license text and the model card from
the upstream source and record the conclusion. Do not bundle weights in a
source-only package, which is the recommended posture anyway. No license
eligibility claim has been made anywhere in this project.

**Owner action required.** Yes.

### R3 — Zero genuine F5 measurements

**Risk.** The defining scientific deliverable has no live observation. Every
measurement in every current report is null, and the capability verdict is
`NOT_EVALUATED`.

**Impact.** A submission without measured evidence cannot demonstrate the
central claim. The offline engineering is strong, but it is not the
measurement.

**Mitigation.** Execute the documented single-operation procedure in an
authorized safe window (`docs/F5_TURNKEY.md`), then independently corroborate
the execution origin.

**Owner action required.** Yes.

### R4 — Execution origin is declared, not authenticated

**Risk.** The `LOCAL_RUNTIME` label is a provenance declaration written by the
tool. A well-formed synthetic record could carry the same label. Hashes
detect change relative to a trusted checkpoint; they do not prove who ran
what.

**Impact.** Without independent corroboration, a measured claim could rest on
an unverified declaration. This is the difference between a demonstration and
a fabrication.

**Mitigation.** Independent live review of the runtime evidence. Until then the
report states the limit explicitly in its provenance limit, and the Passport
says so in its own words.

**Owner action required.** Yes, for acceptance.

### R5 — No public destination or explicit publication authorization

**Risk.** No repository, remote, visibility setting, package scope or
redaction list has been chosen or approved.

**Impact.** An unreviewed export could leak private detail or unrelated
material.

**Mitigation.** EXECUTED for this release: a fresh allowlisted export was
audited (privacy scan, provenance audit, stale-claim sweep), independently
reviewed, and published only after the explicit owner authorization.
The allowlist itself is the shipped tree; the accepted internal lane remains
private.

**Owner action required.** Owner authorization was obtained for this
publication; future re-publications need their own.

## High risks

### R6 — The shared engine does not model the target architecture

**Risk.** The local LFM2.5 model is a hybrid short-convolution architecture:
10 convolution blocks and 6 attention blocks. The F1/F2 engine models a
standard full-attention cache, so it correctly returns `UNKNOWN` for the
model's cache and memory baseline.

**Impact.** The headline "how much memory does this model need" number is
not available from the shared engine for the actual evaluated model. A
reviewer may see the `UNKNOWN` and read it as a gap in the tool rather than
as correct behaviour.

**Mitigation.** This is now handled explicitly and honestly. The engine
result is `UNKNOWN` with the reason `UNSUPPORTED_ATTENTION`. A disclosed
composite advisory scopes the standard formula to the 6 attention blocks and
adds the short-convolution state, labelling every component. The engine
result is not overridden.

**Residual risk.** The advisory is an estimate over declared inputs, not a
measurement. Extending the engine to model hybrid caches natively would be
the principled fix, and is a scope decision for the owner.

**Owner action required.** No, but worth a decision.

### R7 — Single-host, single-model validation surface

**Risk.** Everything was developed and reviewed on one Windows host with one
CPU model on one architecture.

**Impact.** Platform-specific defects may survive. The atomic-publication
path on WSL is known to fail explicitly rather than silently, which is the
correct behaviour, but the Linux ext4 path has not been exercised here.

**Mitigation.** `docs/INSTALL_AND_REPRODUCE.md` states the supported platform
matrix honestly, including the WSL limitation.

**Owner action required.** No.

### R8 — The safe-window resource floor blocks measurement on a busy machine

**Risk.** The 4.481 GiB floor is frequently not met on a shared workstation.
Measurement opportunities are rare and must be planned.

**Impact.** Schedule risk for the F5 window.

**Mitigation.** `cli gate` reports readiness without performing any
inference, so the owner can check cheaply and repeatedly. The floor is
deliberately not lowered.

**Owner action required.** No.

## Medium risks

### R9 — Declared workload assumptions drive the planning numbers

**Risk.** The target throughput, the reload-per-token assumption, the
residency assumption and the runtime overhead allowance are owner
declarations, not observations. The planning numbers are only as good as
those declarations.

**Impact.** A reader could mistake a declared planning input for a measured
one.

**Mitigation.** Every such value is labelled `DECLARED` or `ESTIMATED`, the
workload origin is recorded as `OWNER_DECLARED_PLANNING_ASSUMPTION`, and the
report states that the numbers do not establish real hardware fit.

**Owner action required.** No.

### R10 — Test tasks are known, not held out

**Risk.** The eight frozen cases are transparent toy tests. A model could in
principle be tuned against them.

**Impact.** The task results are not a general capability measurement, and
the report says so.

**Mitigation.** The limitation is stated in the protocol, the report and the
README. The core/supplemental split makes the denominator explicit.

**Owner action required.** No.

### R11 — Cache state and cold-start behaviour are unknown

**Risk.** The first request runs on an already-loaded model whose prefix
cache state is unknown. No cold-load cost is measured, and repeated prompts
may hit backend prefix caches.

**Impact.** Latency numbers are not comparable across configurations and no
cold-start figure exists.

**Mitigation.** The first observation is explicitly labelled
`first_observed_request` with the cache state declared unknown, warmup
requests are zero, and cold-load performance is listed as unavailable.

**Owner action required.** No.

### R12 — No third-party security audit

**Risk.** The security properties are asserted by the project's own review
process and its own tests.

**Impact.** An unknown class of defect may remain.

**Mitigation.** The boundary is small, dependency-free and adversarially
tested. A third-party audit before publication would strengthen the
submission's claim.

**Owner action required.** No, but a reasonable ask before public release.

## Low risks

### R13 — The model file is large and the header reader is new code

**Risk.** The GGUF reader is newly written and handles only the version 3
layout it was written against.

**Impact.** A malformed or unusual model file could be misparsed.

**Mitigation.** Every read is length-bounded, the magic and version are
checked, and unparseable files fail with a specific code rather than a
crash. The reader was exercised against the actual 730,895,168-byte local
model file and against synthetic malformed files.

**Owner action required.** No.

### R14 — The evidence tree is growing

**Risk.** The `evidence/` directory accumulates review transcripts, generated
reports and oversized probe inputs (three 1 MiB files exist).

**Impact.** Repository bulk and the risk of an oversized file entering a
public export.

**Mitigation.** `evidence/` is private by default and excluded from the
proposed package scope. The release inventory classifies every tracked file.

**Owner action required.** No.

## Risk summary

| ID | Risk | Severity | Owner action |
|---|---|---|---|
| R1 | No source license | Blocking | Yes |
| R2 | Model license not established | Blocking | Yes |
| R3 | Zero genuine F5 measurements | Blocking | Yes |
| R4 | Execution origin unauthenticated | Blocking | Yes, for acceptance |
| R5 | No destination or publication authorization | Blocking | Yes |
| R6 | Engine does not model the hybrid architecture | High | Decision |
| R7 | Single-host validation | High | No |
| R8 | Resource floor blocks measurement | High | No |
| R9 | Declared workload assumptions | Medium | No |
| R10 | Known, not held-out tasks | Medium | No |
| R11 | Cache state and cold start unknown | Medium | No |
| R12 | No third-party security audit | Medium | No |
| R13 | New GGUF reader | Low | No |
| R14 | Growing evidence tree | Low | No |
