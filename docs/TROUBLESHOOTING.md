# Troubleshooting

Every command prints a single JSON object on success and a single JSON object
with a `code` on failure, and exits 2 on failure. The code is stable and
machine-readable.

## Reading an error

```powershell
python -m fitlab_evaluation.cli passport --trust missing.json --output-dir out
```

```json
{"status": "ERROR", "code": "INPUT_UNAVAILABLE"}
```

## Error codes

| Code | Meaning | What to do |
|---|---|---|
| `INPUT_UNAVAILABLE` | a required input file could not be read | check the path and that the file exists |
| `INPUT_TOO_LARGE` | an input exceeds 16 MiB | the input is not a FitLab artifact |
| `INVALID_JSON` | malformed, duplicate-key, non-UTF-8 or too deeply nested JSON | the file is corrupt; do not repair it, obtain a clean copy |
| `INVALID_INPUT` | the input parsed but is semantically invalid | check the field against the schema |
| `OUTPUT_EXISTS` | the output directory already exists | use a new directory; outputs are never overwritten |
| `OUTPUT_PARENT_UNAVAILABLE` | the parent of the output directory does not exist | create the parent first |
| `ATOMIC_PUBLICATION_UNSUPPORTED` | the filesystem cannot publish a directory atomically | a WSL DrvFS mount does this; use a native Windows or ext4 path |
| `OUTPUT_TOO_LARGE` | a generated file exceeds the artifact bound | report as a defect |
| `SOURCE_UNAVAILABLE` | the Git object database could not be read | check the repository state |
| `INVALID_SOURCE` | the requested revision is not a plain, valid revision name | use `HEAD`, a branch name or a commit id |
| `SOURCE_COMMIT_MISMATCH` | the trust snapshot does not match the local commit | the trust file came from a different checkout; export a fresh one |
| `SOURCE_NOT_FROZEN` | the working tree does not match the frozen source | commit or remove the local changes; a live run requires a clean tree |
| `TASK_HASH_MISMATCH` | the task pack bytes do not match the trust snapshot | the fixtures were modified; restore them |
| `UNSUPPORTED_TASK_PACK` | the task pack is not the accepted frozen pack | restore `fixtures/tasks-v2.json` |
| `INVALID_TRUST` | the trust snapshot is malformed | export a fresh one with `cli trust` |
| `INCOMPLETE_SOURCE_IDENTITY` | the trust snapshot omits required source files | export a fresh one |
| `UNSUPPORTED_REPLAY_VERSION` | the local replay code differs from the reviewed version | check out the reviewed commit |
| `INVALID_EVALUATION` | the evaluation record is malformed | preserve the original and report it |
| `INVALID_ROW` / `ROW_IDENTITY_MISMATCH` | a row is malformed or out of order | the record is corrupt |
| `GRADE_MISMATCH` | a stored grade differs from the recomputed grade | the record was altered; do not trust it |
| `SUMMARY_MISMATCH` | the stored summary differs from the recomputed summary | the record was altered |
| `FALSE_COMPLETION` | a run claims completion it did not achieve | the record was altered |
| `MISSING_RESOURCE_EVIDENCE` | required memory samples are absent | the record is incomplete |
| `REPORT_MISMATCH` | a report dictionary was not produced by the builder | do not hand-edit a report; regenerate it |
| `RUNTIME_CONFIG_UNAVAILABLE` | the runtime config route could not be read | the runtime is not running, or is not the expected instance |
| `RUNTIME_NOT_PROVEN_OFFLINE` | the runtime is not in offline/no-fetch mode | prepare the runtime; do not proceed |
| `RUNTIME_REMOTE_ROUTING_REFUSED` | the runtime is configured to route to a cloud endpoint | this is a local-only project; fix the routing |
| `RUNTIME_TELEMETRY_NOT_DISABLED` | telemetry is enabled | disable it before measuring |
| `MODEL_REGISTRY_UNAVAILABLE` | the Lemonade model registry could not be read | the model is not registered locally |
| `MODEL_FILE_UNAVAILABLE` | the model file could not be located | check the local cache |
| `GGUF_*` | the model file is not a valid GGUF, or its header is malformed | the file is corrupt or unsupported |
| `MODEL_QUANTIZATION_UNSUPPORTED` | the model's quantization has no idealized weight width | the engine only accepts an explicit set of uniform bit widths |

## The resource gate refuses

```json
{"resource_gate": "FAIL", "reason": "resource gate failed: requires 4.481 GiB available physical and commit, load below 90%"}
```

This is the expected and correct behaviour on a busy machine. The floor is
4.481 GiB available physical memory **and** 4.481 GiB available commit, with
load below 90 %.

Do not lower the floor. Do not kill unrelated processes to create headroom.
Wait for a quieter window and run `cli gate` again.

## A fresh clone refuses to run

If a fresh Windows checkout reports `SOURCE_NOT_FROZEN` or every source file
appears modified, check that `.gitattributes` is present. It declares LF line
endings for text files, which keeps the checkout byte-identical to the stored
blobs. Without it, a CRLF checkout and an LF blob disagree.

The source binding also digests the canonical line-ending-independent form on
both sides, so the binding is correct either way. If it still fails, the
working tree really does differ from the frozen commit.

## The report is refused as "not verified"

`REPORT_MISMATCH` means the report object was not produced by the report
builder. This is the intended behaviour for a hand-edited report: the
export path always rebuilds from verified facts, so an edited report cannot
add a measurement.

## Planning shows UNKNOWN for the cache

Expected for a hybrid short-convolution architecture such as
`LFM2.5-1.2B-Instruct-GGUF`. The shared engine models a standard
full-attention cache and correctly refuses to apply that formula to a
different mechanism. The disclosed composite advisory in `advisory.json`
breaks the estimate down into labelled components. The engine result stays
`UNKNOWN` and is not overridden.

## The tests fail on a warning

The suite runs with `-W error` so that a deprecation cannot pass quietly.
If a test fails on a warning, check the Python version against the supported
range in `docs/INSTALL_AND_REPRODUCE.md`.
