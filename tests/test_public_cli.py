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


def out_debug(code, text):
    return f"exit={code} out={text[:400]}"


if __name__ == "__main__":
    unittest.main()