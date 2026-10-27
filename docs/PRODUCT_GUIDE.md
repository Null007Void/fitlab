# Private offline product guide

Python 3.11+ and the standard library are sufficient. No installation, dependency download, account or credential step is required. Run modules from the repository root. Native Windows Python is the supported MSI execution route. Linux ext4 supports offline exports; WSL DrvFS can reject atomic no-overwrite publication and returns ATOMIC_PUBLICATION_UNSUPPORTED. Do not substitute a replacing rename.

## Deterministic Passport, with no model observations

Use new output directories; their parent must exist. From PowerShell in this checkout:

```powershell
$FitLabPython = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
& $FitLabPython -m fitlab_evaluation.product trust --commit HEAD --output-dir reports/source-snapshot
& $FitLabPython -m fitlab_evaluation.product passport --trust reports/source-snapshot/trust.json --output-dir reports/current-passport
```

Open `reports/current-passport/passport.html`. Its accompanying JSON contains the same claims; a SHA-256 manifest binds every exported file. No scripts, remote fonts, services or assets are used. Generation has no current-time or random fields: identical validated inputs and source-binding environment yield byte-identical reports.

Without a verified evaluation, measured fields are null and capability is NOT_EVALUATED. Synthetic harness records remain SYNTHETIC_ONLY. A declared LOCAL_RUNTIME record can yield measured values only after source/task matching, strict request/response validation, grade and summary recomputation, resource sequencing and timing checks. The declaration alone does not prove that a real model executed. Genuine F5 acceptance still requires independent corroboration of the native runtime evidence.

## Estimates and attribution

An optional `--plan examples/f2_workload_to_hardware.json` demonstrates declared arithmetic, not this real model's memory requirements. Both planning directions use the preserved F1/F2 engine. The example is a tiny synthetic model, visibly named alongside its scenario. Do not combine it with real-model evaluation. When an evaluation is supplied, all plan models must match it; an existing evaluation plan cannot be overwritten by a different plan.

Evidence classes are MEASURED, ESTIMATED, CALCULATED, UNSUPPORTED and UNKNOWN. Unsupported formulas and absent inputs remain null. CALCULATED means exact arithmetic under declarations; it is not hardware measurement. Every claim records its basis and limitations. Model peak RAM, TTFT and decode throughput remain unknown under this protocol.

## Reload, corruption and restart

```powershell
& $FitLabPython -m fitlab_evaluation.product verify --trust reports/source-snapshot/trust.json --evaluation evidence/session-001/evaluation.json
& $FitLabPython -m fitlab_evaluation.workflow postprocess --session-dir evidence/session-001 --output-dir reports/recovered-passport
```

Reload never performs inference. Missing, oversized, malformed UTF-8, duplicate-key, excessively nested, nonfinite, inconsistent, wrong-source or wrong-task evidence fails closed with a bounded error code and exit 2. A syntactically valid record is insufficient: replay checks semantics. Existing output directories are never replaced. All files of a report bundle become visible together; failure removes the temporary directory.

A stopped/interrupted record retains all planned trials in its denominator and never becomes a complete protocol. A durable RUNNING checkpoint can show earlier valid observations but remains incomplete. Started/failed rows are not measurements. A resource drop after a valid response preserves that response and ends the session. Missing post telemetry is accepted only for the last measured row in an explicitly STOPPED error record; it cannot establish protocol completion. Corrupt records are not repaired silently. Preserve originals for review.

A new live run uses a new session directory and run ID. There is no inference resume, retry, skipping failed cases or merging selected repeats into a success. `postprocess` resumes artifact generation only. If output failed after inference, inspect the durable evaluation before starting a new run so observed data are not discarded.

## Source and portability boundary

In a Git checkout, the supplied trust file must exactly match its existing commit, tree and code/task hashes. Required planner/grader replay code and frozen task bytes must also match the installed verifier. A dirty execution tree is refused by the live workflow.

For an offline source archive without `.git`, export a trust snapshot from the original verified checkout first. The report visibly labels this as EXTERNALLY_SUPPLIED_SNAPSHOT. Its commit/tree identifiers depend on that separately trusted snapshot; no local Git object exists to bind them. Full current-source equality is still required for live execution. Record verification never claims cryptographic origin authentication. Source binding may therefore differ between a checkout report and an archive report even with identical task data; each environment is deterministic internally.

## Schema and timing

`capability-passport-v2.schema.json` documents stable report fields. `evaluation-result-v2.schema.json` documents evaluation record shape. Runtime semantic validators are authoritative and stricter than JSON Schema. A schema-valid record may still fail replay.

Latency is bounded by the recorded request timeout and cumulative session budget. A row's client elapsed time cannot exceed its UTC wall interval by more than 0.05 seconds, an explicit tolerance for coarse Windows wall-clock resolution. Monotonic client timing is the measurement. The declared session must also fit prior latencies, prescribed one-second pauses and the producer's request-reservation margin. Declared LOCAL_RUNTIME rows require the observed pause within the same 0.05-second wall tolerance; fast synthetic harness fixtures remain unmeasured. Clock jumps or contradictory evidence may require manual investigation and cannot be silently relabeled valid.

Legacy fact-only Passport CLI export is disabled (LEGACY_FACTS_DISABLED): hand-edited totals cannot establish product provenance. Historical files remain historical artifacts.
