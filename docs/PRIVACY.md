# Privacy and security

## What this project collects

Nothing. There is no telemetry, no analytics, no crash reporting, no usage
counter and no network call in any offline command. The Passport is a
self-contained HTML file with no script, no remote font, no image and no
external reference of any kind.

## What is written to disk

Only what you explicitly ask for, and only into the output directory you
name. Every output directory is created atomically and is never overwritten;
an existing path is refused rather than replaced.

| Command | Files written |
|---|---|
| `plan` | `plan.json`, `provenance.json`, `advisory.json`, `manifest.json` |
| `trust` | `trust.json`, `manifest.json` |
| `passport` | `passport.json`, `passport.html`, `trust.json`, plus any supplied evaluation, planning, advisory, provenance and host identity, plus `manifest.json` |
| `gate` | `gate.json`, `manifest.json` (only with `--output-dir`) |
| `doctor` | nothing; it prints to stdout |

## What is read

| Source | What is read | Why |
|---|---|---|
| The local Git object database | commit, tree and per-file hashes of the source | bind the report to an exact source state |
| The local model file | **only** the GGUF header, the key/value metadata block and the tensor descriptors | establish model identity, quantization and geometry |
| The Lemonade model registry | the model id, checkpoint and snapshot revision | corroborate the model identity |
| Host counters | total physical memory, CPU brand, logical processor count | describe the assessed hardware |
| Host counters, live only | available memory, memory load, available commit | enforce the resource floor before any inference |

**Model weights are never read by any offline command.** The GGUF reader
stops after the tensor descriptors and never touches the tensor data region.
No offline command loads a model, starts a server or performs inference.

## Private detail in generated documents

Owner-supplied prose (scenario labels, residency assumptions, runtime
overhead bases) is redacted before it reaches a report. Redaction removes:

- Windows drive-letter and UNC paths
- POSIX home and system paths
- user profile segments such as `Users/<name>`
- e-mail addresses
- IPv4 addresses, with or without a port
- MAC addresses

Scientific and product identifiers are deliberately preserved, because they
carry the report's meaning: formula identifiers such as
`fitlab.kv.standard_full_cache`, model and checkpoint names, quantization
names and backend names are not redacted.

The rendered Passport was checked against a private-detail scan and against a
390-pixel viewport for layout overflow.

## Host-specific data that is deliberately excluded

A report must be byte-reproducible, so transient observations are excluded
from it. The following are **not** in a Passport:

- available physical memory
- memory load percentage
- available commit size
- timestamps
- random values
- process identifiers
- user names and machine names

Available memory and load appear only in a live session record and in the
`gate` output, where they are the point of the measurement.

## The source binding and what it does not prove

The report binds to a source commit, a source tree and a set of per-file
hashes, and it records a `LOCAL_GIT_VERIFIED` or
`EXTERNALLY_SUPPLIED_SNAPSHOT` binding.

These hashes detect **change relative to a trusted checkpoint**. They do not
authenticate who produced a file, when, or on what machine. A hash is not a
signature. The report says so in its own provenance limit.

## Security properties of the measurement path

| Property | Implementation |
|---|---|
| Loopback only | the adapter connects to `127.0.0.1` on a fixed port; no proxy, no discovery, no redirect following |
| No silent retry | a transport failure is a failure, not a retry |
| Bounded responses | response bodies are capped at 256 KiB and the read is refused beyond that |
| Bounded requests | a request body above 16 KiB is refused |
| Bounded time | every request has an aggregate deadline enforced by a timer, not only by a socket timeout |
| Strict JSON | duplicate keys, non-finite numbers and non-standard constants are rejected |
| Exact types | `true` is not `1`; no Boolean-as-integer coercion |
| No shell | subprocess calls pass an argument list, never a shell string |
| No path escape | output bundle names cannot contain a separator or a parent reference |
| No overwrite | existing output paths are refused, not replaced |
| No remote routing | a runtime configuration that points at a cloud endpoint is refused |
| Telemetry off | enabled telemetry is refused |
| Dirty tree refused | a live run refuses to start when the source does not match the frozen snapshot |

## Reporting a vulnerability

This is a private pre-release project. Report a suspected issue to the owner
through the existing private channel. Do not open a public issue for a
security finding in a project that has not been published.

## Not yet done

- No third-party security audit has been performed.
- The F1/F2/F3 scientific contracts have independent review from the
  project's own review process, not from an external auditor.
- The measurement path has not yet been exercised against a live runtime, so
  the live-only defences are verified by synthetic tests rather than by
  observation.
