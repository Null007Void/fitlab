# Installation and reproduction

## Requirements

| Item | Requirement |
|---|---|
| Python | 3.12 or newer (`pathlib.Path.is_junction` is required). Tested on CPython 3.13 on Windows 11; Python 3.11 is known-incompatible. |
| Dependencies | none. Standard library only. |
| Network | not required for any offline command. |
| GPU | not used. CPU only. |
| Disk | about 2 MB for the source tree. |
| Model file | optional. Only needed for real-model planning, not for the tests. |

There is no `pip install` step, no build step and no lockfile, because there
are no third-party packages. Clone the repository and run from its root.

## Supported platforms

| Platform | Status | Notes |
|---|---|---|
| Windows 11 (x64) | Supported, primary | Native Windows Python is the MSI execution route. Resource measurement uses `GlobalMemoryStatusEx`. |
| Linux (ext4) | Supported | Atomic no-overwrite publication uses `renameat2` with `RENAME_NOREPLACE`. |
| WSL | Partial | A DrvFS mount rejects the required non-replacing rename and the export fails explicitly with `ATOMIC_PUBLICATION_UNSUPPORTED`. Do not substitute a replacing rename. |
| macOS | Unverified | The native memory reader is Windows-specific. The `gate` command requires Windows. |

## Reproducing the offline results

```powershell
python -W error -m unittest discover -s tests -v
```

Expected result: `OK` with the current test count recorded in
`SPRINT_STATUS.md`. Warnings are treated as errors, so a deprecation in any
dependency would fail the run rather than pass quietly.

The suite is deterministic: it uses fixed seeds for the randomized numeric
fixtures and synthetic replies for the evaluation harness. It contacts no
model and no external service. The only sockets it opens are ephemeral
loopback listeners for transport tests.

## Reproducing a Capability Passport

```powershell
python -m fitlab_evaluation.cli trust --output-dir out/source
python -m fitlab_evaluation.cli passport --trust out/source/trust.json --output-dir out/passport
```

The output is byte-for-byte deterministic for identical inputs and the same
source-binding environment. There are no timestamps, no random values and no
host-specific transient values in the report. `out/passport/manifest.json`
records a SHA-256 for every exported file.

Compare two runs to confirm determinism:

```powershell
(Get-FileHash out/passport/passport.html -Algorithm SHA256).Hash
```

## Reproducing the source binding

```powershell
python -m fitlab_evaluation.cli doctor
```

The `source` section reports the commit, tree, number of bound source files
and the task pack SHA-256. A `LOCAL_GIT_VERIFIED` binding means the trust
snapshot was checked against the local Git object database. An
`EXTERNALLY_SUPPLIED_SNAPSHOT` binding means the tree has no `.git` directory
and the snapshot came from elsewhere; in that case commit and tree
identifiers describe the separately trusted snapshot, and the report says so.

The source binding compares canonical (line-ending independent) digests of
the git blobs and the working tree, so a checkout with different line endings
still verifies, while a genuine content change does not.

## Verifying a source archive without Git

Export a trust snapshot from the original verified checkout first:

```powershell
python -m fitlab_evaluation.cli trust --output-dir out/source
```

Copy `out/source/trust.json` into the archive and use it with
`--trust`. The report will visibly bind to `EXTERNALLY_SUPPLIED_SNAPSHOT`.

## Verifying the model identity

```powershell
python -m fitlab_evaluation.cli doctor
```

The `model` section is derived from the local GGUF file's own header and the
Lemonade model registry. Only the header, the key/value metadata block and
the tensor descriptors are read. No weight data is read, no model is loaded
and no inference is performed.

To check the model file's integrity independently:

```powershell
Get-FileHash "<path-to-gguf>" -Algorithm SHA256
```

Model files are operator-provided; this repository ships no model and no
model digests (weights are external, see `NOTICE.md`).

## Environment variables

None are required. The tool reads no environment variable for configuration
and no credential is needed for any offline command.
