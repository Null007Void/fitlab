"""Public CLI packaging/behavior tests: the commands must actually work.

Covers the shipped entry points an external user will type:
    fitlab inspect / fitlab evaluate / fitlab passport
via the console-script mapping (public_cli:main), the module entry
(python -m fitlab_evaluation.public_cli), and the legacy advanced surfaces.
No model, server or network is contacted: evaluate is proven to reach the
guarded workflow and fail fast through its own resource/runtime gates with
zero inference requests, using synthetic fixtures only.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fitlab_evaluation.public_cli import main as public_main
from fitlab_evaluation.report_v3 import export_report
from fitlab_evaluation.model_profile import derive_profile


def _run(*argv):
    """Drive the console entry in-process; return (returncode, stdout_json)."""
    import io
    from unittest.mock import patch
    out = io.StringIO()
    with patch("sys.stdout", out):
        code = public_main(list(argv))
    return code, out.getvalue()


class PublicCliSurface(unittest.TestCase):
    def test_inspect_reports_environment_without_inference(self):
        code, text = _run("inspect")
        self.assertEqual(code, 0, out_debug(code, text))
        record = json.loads(text)
        self.assertEqual(record["status"], "OK")
        self.assertEqual(record["artifact_kind"], "doctor")
        self.assertEqual(record["inference_requests"], 0)
        self.assertFalse(record["model_load_attempted"])
        # Evidence-class discipline: unavailable values are honest, never guessed.
        self.assertIn("host", record)

    def test_module_entry_points_exist(self):
        from fitlab_evaluation import public_cli, cli, workflow
        from fitlab_evaluation import seal as seal_module
        for module in (public_cli, cli, workflow):
            self.assertTrue(hasattr(module, "main"))
        # seal's public surface is verify_campaign (library, not CLI).
        self.assertTrue(callable(seal_module.verify_campaign))
        # Advanced surfaces stay importable exactly as documented.
        from fitlab_evaluation.cli import main as advanced_cli
        from fitlab_evaluation.workflow import main as advanced_workflow
        self.assertTrue(callable(advanced_cli))
        self.assertTrue(callable(advanced_workflow))

    def test_evaluate_fails_fast_through_guarded_gates(self):
        # Deterministic, host-independent injection: the runtime adapter's
        # readiness probe is made to refuse, and the adapter's completion is
        # assertion-armed — an inference attempt fails the test. So this
        # regression can never reach the model on any machine (with or
        # without a prepared runtime), and the public evaluate entry must
        # produce durable sealed BLOCKED evidence with zero requests.
        # Read-only loopback interactions that the guard chain performs
        # before readiness (memory sampling, the local offline-config GET)
        # stay engine-real by design; the failure injected here is only the
        # runtime adapter gate, deterministically.
        import tempfile
        from unittest.mock import patch
        from fitlab_evaluation import workflow as wf
        from fitlab_evaluation.lemonade import IntegrationError
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "campaign"
            with patch.object(wf.LemonadeClient, "ready",
                              side_effect=IntegrationError(
                                  "runtime offline state changed")), \
                 patch.object(wf.LemonadeClient, "complete",
                              side_effect=AssertionError(
                                  "inference attempted")) as complete:
                code, text = _run("evaluate", "--output-dir", str(output),
                                  "--repeats", "1")
                complete.assert_not_called()
            self.assertEqual(code, 2, out_debug(code, text))
            session = json.loads((output / "session.json").read_text("utf-8"))
            self.assertEqual(session["status"], "BLOCKED")
            self.assertIsInstance(session.get("reason"), str)
            self.assertTrue(session["reason"])
            self.assertEqual(session["inference_requests"], 0)
            seal = json.loads((output / "final-seal.json").read_text("utf-8"))
            self.assertEqual(seal["status"], "BLOCKED")

    def test_evaluate_passes_plan_through(self):
        # A planning document naming a different model must be refused before
        # any runtime contact (guards hold under the public entry too):
        # the workflow exits 2 with a machine-readable error and writes
        # no campaign output in the target directory.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({
                "schema_version": "fitlab-plan-v2",
                "scenarios": [{"model": {"model_id": "not-the-model"}}],
            }), encoding="utf-8")
            out = Path(tmp) / "out"
            code, text = _run("evaluate", "--output-dir", str(out),
                              "--repeats", "1", "--plan", str(plan))
            self.assertEqual(code, 2, out_debug(code, text))
            self.assertFalse(out.exists())

    def test_passport_public_entry_renders_and_is_deterministic(self):
        # The public passport entry, driven exactly as an installed user
        # would drive it (fresh trust from THIS checkout's HEAD), must
        # render the passport and produce byte-identical output on a second
        # render — no times, no host readings, no randomness.
        import io, tempfile
        from unittest.mock import patch
        from fitlab_evaluation import public_cli
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.artifacts import stable_json
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            trust = make_trust("HEAD")
            (source / "trust.json").write_text(stable_json(trust), encoding="utf-8")
            hashes = []
            out = None
            for i in range(2):
                # The bundle destination must NOT pre-exist (atomic
                # no-overwrite publication); only its parent must exist.
                out = Path(tmp) / ("passport" if out is None else "passport-2")
                code, text = _run(
                    "passport", "--trust", str(source / "trust.json"),
                    "--output-dir", str(out))
                self.assertEqual(code, 0, out_debug(code, text))
                record = json.loads(text)
                self.assertEqual(record["status"], "WRITTEN")
                self.assertEqual(record["artifact_kind"], "passport")
                self.assertTrue((out / "passport.html").exists())
                self.assertTrue((out / "passport.json").exists())
                hashes.append((out / "passport.html").read_bytes())
            self.assertEqual(hashes[0], hashes[1])
            # Rendered HTML must stay free of private detail by construction.
            self.assertNotIn(b"C:\\Users\\", hashes[0])

    def test_install_layout_contract(self):
        # The supported install is the editable checkout: the engine binds
        # fixtures and source roots relative to the package's parent
        # directory. This test pins that contract so a future packaging
        # change cannot silently break evaluate/trust.
        import os
        self.assertTrue((ROOT / "fixtures" / "tasks-v2.json").exists())
        self.assertTrue((ROOT / "fitlab_evaluation" / "run.py").exists())
        self.assertTrue((ROOT / "pyproject.toml").exists())
        entry = "fitlab = \"fitlab_evaluation.public_cli:main\""
        self.assertIn(entry, (ROOT / "pyproject.toml").read_text("utf-8"))

    def test_console_script_module_invocation(self):
        # The documented module invocation must expose the three public
        # commands with working argparse mapping (help surfaces them; the
        # subcommands dispatch through the same handlers the tests above
        # exercise).
        r = subprocess.run(
            [sys.executable, "-m", "fitlab_evaluation.public_cli", "--help"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("inspect", r.stdout)
        self.assertIn("evaluate", r.stdout)
        self.assertIn("passport", r.stdout)
        r2 = subprocess.run(
            [sys.executable, "-m", "fitlab_evaluation.cli", "--help"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("passport", r2.stdout)





class PlanningDeclarationRedactionTests(unittest.TestCase):
    """Owner declarations must be private-by-construction in every stored copy."""

    def test_planning_declarations_redacted_in_stored_record_and_bundle(self):
        import tempfile
        import copy
        from unittest.mock import patch
        from fitlab_evaluation.run import evaluate
        from fitlab_evaluation.report_v3 import export_report
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.artifacts import stable_json
        from fitlab_evaluation.workflow import identity
        from test_f4_integration import FakeClient, GOOD_MEMORY

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        plan["scenarios"][0]["model"]["model_id"] = MODEL
        plan["scenarios"][0]["workload"]["residency_assumption"] = (
            "weights cached at /data/private/model.gguf for fd00::1234")
        trust = make_trust("HEAD")
        with patch("fitlab_evaluation.run.identity", return_value=trust["source_sha256"]):
            with tempfile.TemporaryDirectory() as tmp:
                record = evaluate(plan, 1, client=FakeClient(), memory=lambda: dict(GOOD_MEMORY),
                                  pause=lambda _s: None, checkpoint=None)
                joined = stable_json(record)
                self.assertNotIn("/data/private", joined)
                self.assertNotIn("fd00::1234", joined)

                out = Path(tmp) / "passport"
                export_report(out, trust, record=record)
                pub = (out / "evaluation.json").read_text("utf-8")
                self.assertNotIn("/data/private", pub)
                self.assertNotIn("fd00::1234", pub)

    def test_distinct_private_scenario_ids_stay_distinct_after_redaction(self):
        # Two scenarios whose identities redact to the same marker must not
        # collapse: replay re-validates the stored input with run_document,
        # which rejects duplicate scenario identities.
        import tempfile
        from unittest.mock import patch
        from fitlab_evaluation.run import evaluate
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.workflow import identity
        from test_f4_integration import FakeClient, GOOD_MEMORY

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        first = json.loads(json.dumps(plan))
        first["direction"] = "workload_to_hardware"
        first["scenarios"][0]["model"]["model_id"] = MODEL
        first["scenarios"][0]["scenario_id"] = "/data/private/alpha"
        second = json.loads(json.dumps(plan))
        second["direction"] = "workload_to_hardware"
        second["scenarios"][0]["model"]["model_id"] = MODEL
        second["scenarios"][0]["scenario_id"] = "/data/private/beta"
        document = {"direction": "workload_to_hardware",
                    "scenarios": [first["scenarios"][0], second["scenarios"][0]],
                    "schema_version": plan.get("schema_version", 1)}
        trust = make_trust("HEAD")
        with patch("fitlab_evaluation.run.identity", return_value=trust["source_sha256"]):
            with tempfile.TemporaryDirectory() as tmp:
                record = evaluate(document, 1, client=FakeClient(),
                                  memory=lambda: dict(GOOD_MEMORY),
                                  pause=lambda _s: None, checkpoint=None)
        stored = record["planning_input"]
        ids = sorted(s["scenario_id"] for s in stored["scenarios"])
        self.assertNotIn("/data/private", ids[0] + ids[1])
        self.assertNotEqual(ids[0], ids[1])
        # Replay: the sanitized input must still validate through the planner.
        from fitlab_foundation.planner_cli import run_document
        validated = run_document(stored)
        self.assertEqual(len(validated["results"]), 2)


class AHardeningTests(unittest.TestCase):
    """Round-6 part-A findings: companion redaction, advisory label binding,
    explicit-GGUF identity validation, task-only offline guard."""

    def test_companion_publication_is_redacted(self):
        # An owner declaration carrying a local path must never leak into the
        # published companion artifacts.
        import tempfile
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.artifacts import stable_json
        from fitlab_evaluation.report_v3 import export_report
        from fitlab_evaluation.model_profile import derive_profile
        trust = make_trust("HEAD")
        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        plan["scenarios"][0]["workload"]["residency_assumption"] = (
            "loaded from C:\\Users\\sampleuser\\model.gguf during the run")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "passport"
            export_report(out, trust, None, plan)
            body = (out / "planning-input.json").read_text("utf-8")
            self.assertNotIn("sampleuser", body)
            self.assertIn("[redacted]", body)

    def test_advisory_with_measurement_label_is_refused(self):
        import tempfile
        from fitlab_evaluation.cli import _validate_advisory
        from fitlab_evaluation.artifacts import ArtifactError
        with self.assertRaises(ArtifactError):
            _validate_advisory({"components": [
                {"component": "weights", "evidence": "MEASURED",
                 "bytes": 1, "limitation": ""}]})
        _validate_advisory({"components": [
            {"component": "weights", "evidence": "CALCULATED",
             "bytes": 1, "limitation": ""}]})

    def test_explicit_foreign_gguf_is_refused(self):
        # derive_profile refuses a GGUF whose header names a different model:
        # fixed-contract identity cannot be attributed to foreign metadata.
        import tempfile
        # A minimal well-formed GGUF v3 header whose general.name names a
        # different model than the frozen contract.
        gguf_head = (
            b"GGUF"
            + (3).to_bytes(4, "little")      # version
            + (0).to_bytes(8, "little")      # tensor count
            + (1).to_bytes(8, "little")      # kv count
            + (12).to_bytes(8, "little") + b"general.name"
            + (8).to_bytes(4, "little")      # value type: string
            + (23).to_bytes(8, "little") + b"Totally Different Model"
        )
        # Pad to the default 32-byte data alignment so the (empty) tensor
        # section start lies inside the file.
        GGUF_HEAD = gguf_head + b"\x00" * ((-len(gguf_head)) % 32)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "other-model-Q4_K_M.gguf"
            path.write_bytes(GGUF_HEAD)
            with self.assertRaises(Exception) as caught:
                derive_profile(path, None)
            self.assertIn("MODEL_IDENTITY_MISMATCH", str(caught.exception))

    def test_task_only_run_refuses_unproven_offline_config(self):
        # run.main (task-only LOCAL_RUNTIME path) must refuse before creating
        # any evidence path when the runtime-config gate cannot see the
        # offline contract. Simulate by pointing the guard at a failing port.
        import tempfile
        import subprocess
        from unittest.mock import patch
        from fitlab_evaluation import run as run_mod
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "campaign.json"
            from fitlab_evaluation import workflow as wf_mod
            argv = ["run-task-only", "--output", str(out), "--repeats", "1"]
            with patch.object(wf_mod, "safe_runtime_config",
                              side_effect=ConnectionRefusedError("refused")), \
                 patch.object(sys, "argv", ["run.py"] + argv[1:]):
                with self.assertRaises((ConnectionRefusedError, OSError)):
                    run_mod.main()
            # The guard sits BEFORE evidence reservation: nothing was created.
            self.assertFalse(out.exists())


def out_debug(code, text):
    return f"exit={code} out={text[:400]}"


if __name__ == "__main__":
    unittest.main()