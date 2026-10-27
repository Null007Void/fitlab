"""Unified offline FitLab command line.

One entry point for the whole offline product surface:

    plan       build a source-backed planning document for either journey
    trust      export a source trust snapshot
    passport   render the Capability Passport from verified evidence
    verify     replay an evaluation record against a trust snapshot
    gate       report the native resource preflight and F5 readiness
    doctor     report the offline environment and source identity

Every command is bounded, deterministic and offline. ``plan`` reads the local
model's GGUF header; it never loads a model and never performs inference.

Inference entry points (two, both guarded, each under the same frozen task
pack, grader and resource gates):
  * ``python -m fitlab_evaluation.workflow run`` — the full orchestrated
    campaign runner (ready-only runtime contract, sealed evidence).
  * ``python -m fitlab_evaluation.run`` — the task-only evaluation loop with
    the same frozen grader and gates (used by tests and harnesses); records
    are validated by the same verifier.

Neither entry issues a request unless a prepared, offline, already-running
local runtime answers; without one they fail fast. Never retry failed model
outputs.

Errors are machine-readable JSON on stderr with exit status 2. Successful
commands print a single JSON object on stdout.
"""

import argparse
import json
import sys
from pathlib import Path

from .artifacts import ArtifactError, BoundedParser, load_json, publish_bundle, stable_json
from .evidence import make_trust, validate_trust, verify_record
from .report_v3 import export_report

# The two planning journeys share one requirements engine.
DIRECTIONS = ("workload_to_hardware", "hardware_to_workloads")


def _plan(arguments):
    """Build a source-backed planning document for one journey."""
    from .plan_builder import build_plan, memory_advisory, provenance
    from .model_profile import derive_profile, locate_model_file

    model_path = None
    revision = None
    if arguments.model_file is not None:
        model_path = Path(arguments.model_file)
        if not model_path.is_file():
            raise ArtifactError("MODEL_FILE_UNAVAILABLE")
    else:
        model_path, revision = locate_model_file()

    workload = None
    if arguments.workload is not None:
        workload, _ = load_json(arguments.workload)
        if type(workload) is not dict:
            raise ArtifactError("WORKLOAD_DECLARATION_INVALID")

    document = build_plan(
        arguments.direction,
        workload=workload,
        budget_bytes=arguments.budget_bytes,
        overhead_bytes=arguments.overhead_bytes,
        overhead_basis=arguments.overhead_basis,
        model_path=model_path,
        revision=revision,
    )
    profile = derive_profile(model_path, revision)
    advisory = memory_advisory(profile, workload or _default_workload(), arguments.overhead_bytes)
    return {
        "document": document,
        "provenance": provenance(profile, workload or _default_workload(), arguments.budget_bytes),
        "advisory": advisory,
    }


def _default_workload():
    from .plan_builder import DEFAULT_WORKLOAD

    return dict(DEFAULT_WORKLOAD)


def _read_plan_bundle(path):
    """Read a plan document, optionally with its advisory and provenance.

    Accepts either a plan bundle directory produced by ``plan`` or a bare
    planning document. A bare document carries no advisory or provenance and
    the report will show honest unknown states for those fields.
    """
    directory = Path(path)
    if directory.is_dir():
        plan, _ = load_json(directory / "plan.json")
        advisory = None
        provenance = None
        if (directory / "advisory.json").exists():
            advisory, _ = load_json(directory / "advisory.json")
        if (directory / "provenance.json").exists():
            provenance, _ = load_json(directory / "provenance.json")
        return plan, advisory, provenance
    plan, _ = load_json(directory)
    return plan, None, None


def _host_identity():
    """Stable host facts for the report. Never transient memory readings."""
    from .model_profile import host_identity

    return host_identity()


def _publish_plan(arguments):
    """Write a planning document and its provenance as an atomic bundle."""
    from fitlab_foundation.planner_cli import run_document

    built = _plan(arguments)
    document = built["document"]
    # The document must survive the strict F2 boundary before it is published.
    run_document(document)
    files = {
        "plan.json": stable_json(document),
        "provenance.json": stable_json(built["provenance"]),
        "advisory.json": stable_json(built["advisory"]),
    }
    manifest = publish_bundle(arguments.output_dir, files)
    return {
        "status": "WRITTEN",
        "artifact_kind": "plan",
        "direction": arguments.direction,
        "output_dir": str(arguments.output_dir),
        "files": sorted(files),
        "manifest_files": len(manifest["files"]),
    }


def _gate(arguments):
    """Native resource preflight and F5 readiness. Read-only; no runtime."""
    from .lemonade import (
        IntegrationError,
        MIN_AVAILABLE,
        MODEL,
        VERSION,
        TARGET_VERSION,
        SUPPORTED_VERSIONS,
        require_resources,
        windows_memory,
    )

    memory = windows_memory()
    available = memory["available_physical_bytes"]
    record = {
        "status": "OK",
        "artifact_kind": "gate",
        "model": MODEL,
        "runtime_version_required": VERSION,
        "runtime_version_retained": VERSION,
        "runtime_version_target": TARGET_VERSION,
        "runtime_versions_supported": sorted(SUPPORTED_VERSIONS),
        "required_available_bytes": MIN_AVAILABLE,
        "required_available_gib": round(MIN_AVAILABLE / (1 << 30), 3),
        "memory": memory,
        "inference_requests": 0,
        "server_start_attempted": False,
        "model_load_attempted": False,
        "ready": False,
    }
    try:
        require_resources(memory)
        record["resource_gate"] = "PASS"
        record["ready"] = True
    except IntegrationError as exc:
        record["resource_gate"] = "FAIL"
        record["reason"] = str(exc)
        record["ready"] = False
    record["host_note"] = (
        "Resource availability is a host observation, not a model measurement. "
        "A PASS result permits an owner-authorized F5 run; it does not perform one."
    )
    if arguments.output_dir is not None:
        publish_bundle(arguments.output_dir, {"gate.json": stable_json(record)})
        record["output_dir"] = str(arguments.output_dir)
    return record


def _doctor(arguments):
    """Report the offline environment, source identity and model identity."""
    from .model_profile import derive_profile, locate_model_file, profile_hardware

    record = {
        "status": "OK",
        "artifact_kind": "doctor",
        "inference_requests": 0,
        "server_start_attempted": False,
        "model_load_attempted": False,
    }
    try:
        trust = make_trust(arguments.commit)
        validate_trust(trust)
        record["source"] = {
            "commit": trust["source_commit"],
            "tree": trust["source_tree"],
            "source_files": len(trust["source_sha256"]),
            "task_pack_sha256": trust["task_pack_sha256"],
            "binding": "LOCAL_GIT_VERIFIED",
        }
    except ArtifactError as exc:
        record["source"] = {"available": False, "reason": exc.code}
    record["host"] = profile_hardware()
    try:
        model_path, revision = locate_model_file()
        profile = derive_profile(model_path, revision)
        record["model"] = {
            "model_id": profile["model_id"],
            "checkpoint": profile["checkpoint"],
            "snapshot_revision": revision,
            "architecture_family": profile["architecture_family"],
            "architecture_kind": profile["architecture_kind"],
            "attention_mechanism": profile["attention_mechanism"],
            "hybrid": profile["hybrid"],
            "total_parameters": profile["total_parameters"],
            "quantization": profile["quantization"],
            "weight_bits_per_parameter": profile["weight_bits_per_parameter"],
            "declared_license_name": profile["declared_license_name"],
        }
    except ArtifactError as exc:
        record["model"] = {"available": False, "reason": exc.code}
    return record


def main(argv=None):
    parser = BoundedParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Build a source-backed planning document")
    plan.add_argument("direction", choices=DIRECTIONS)
    plan.add_argument("--model-file", type=Path, help="Explicit GGUF path; default is the registered local model")
    plan.add_argument("--workload", type=Path, help="Owner workload declaration JSON")
    plan.add_argument("--budget-bytes", type=int, help="Planning memory budget (hardware_to_workloads)")
    plan.add_argument("--overhead-bytes", type=int, help="Declared runtime overhead allowance")
    plan.add_argument("--overhead-basis", help="Provenance statement for the overhead allowance")
    plan.add_argument("--output-dir", type=Path, required=True)

    trust = sub.add_parser("trust", help="Export a source trust snapshot")
    trust.add_argument("--commit", default="HEAD")
    trust.add_argument("--output-dir", type=Path, required=True)

    report = sub.add_parser("passport", help="Render the Capability Passport")
    report.add_argument("--trust", type=Path, required=True)
    report.add_argument("--evaluation", type=Path)
    report.add_argument("--plan", type=Path)
    report.add_argument("--output-dir", type=Path, required=True)

    check = sub.add_parser("verify", help="Replay an evaluation record")
    check.add_argument("--trust", type=Path, required=True)
    check.add_argument("--evaluation", type=Path, required=True)

    gate = sub.add_parser("gate", help="Native resource preflight and F5 readiness")
    gate.add_argument("--output-dir", type=Path)

    doctor = sub.add_parser("doctor", help="Report environment, source and model identity")
    doctor.add_argument("--commit", default="HEAD")

    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "plan":
            result = _publish_plan(arguments)
        elif arguments.command == "trust":
            publish_bundle(arguments.output_dir, {"trust.json": stable_json(make_trust(arguments.commit))})
            result = {"status": "WRITTEN", "artifact_kind": "trust"}
        elif arguments.command == "verify":
            trust, _ = load_json(arguments.trust)
            record, _ = load_json(arguments.evaluation)
            verified = verify_record(record, trust)
            result = {
                "status": "VERIFIED",
                "run_status": verified["status"],
                "measurement_eligible": verified["measurement_eligible"],
                "complete_protocol": verified["complete_protocol"],
                "measured_count": verified["summary"]["measured_count"],
                "planned_count": verified["summary"]["planned_count"],
            }
        elif arguments.command == "passport":
            trust, _ = load_json(arguments.trust)
            record = None if arguments.evaluation is None else load_json(arguments.evaluation)[0]
            plan = None
            advisory = None
            provenance = None
            if arguments.plan is not None:
                plan, advisory, provenance = _read_plan_bundle(arguments.plan)
            host = _host_identity()
            export_report(
                arguments.output_dir, trust, record, plan, advisory, provenance, host
            )
            result = {"status": "WRITTEN", "artifact_kind": "passport"}
        elif arguments.command == "gate":
            result = _gate(arguments)
        elif arguments.command == "doctor":
            result = _doctor(arguments)
        else:  # pragma: no cover - argparse rejects unknown commands
            raise ArtifactError("INVALID_ARGUMENTS")
        print(stable_json(result), end="")
        return 0
    except ArtifactError as exc:
        code = exc.code
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError):
        code = "INVALID_INPUT"
    except OSError:
        code = "IO_ERROR"
    print(stable_json({"status": "ERROR", "code": code}), end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
