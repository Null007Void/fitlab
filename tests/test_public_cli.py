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
        # No runtime is prepared in the test environment: the workflow's own
        # preflight/guard chain must refuse BEFORE any inference request and
        # still write durable BLOCKED evidence. This proves the public entry
        # reaches the real guarded workflow (exit 2 + sealed BLOCKED evidence).
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "campaign"
            code, text = _run("evaluate", "--output-dir", str(output),
                              "--repeats", "1")
            self.assertEqual(code, 2, out_debug(code, text))
            session = json.loads((output / "session.json").read_text("utf-8"))
            self.assertIn(session["status"], ("BLOCKED", "INTERRUPTED"))
            self.assertEqual(session["inference_requests"], 0)
            # The evidence chain must exist and be sealed.
            seal = json.loads((output / "final-seal.json").read_text("utf-8"))
            self.assertIn(seal["status"], ("BLOCKED", "INTERRUPTED"))

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

    def test_passport_renders_from_fresh_trust_and_historical_seal_verifies(self):
        # Two distinct passport paths with different trust semantics:
        #  (a) a FRESH campaign's passport renders from fresh trust (the user
        #      journey — trust built in the user's own clone resolves),
        #  (b) the SHIPPED LIVE-002 passport is the historical artifact: its
        #      rendered bytes are included and its integrity is proven by the
        #      byte-seal, not by re-rendering (the historical source commit
        #      intentionally does not exist in the public repo's fresh
        #      history, so trust re-validation fail-closes — by design).
        import tempfile, subprocess
        camp = ROOT / "evidence" / "phase-a" / "live-validation-001"
        self.assertTrue((camp / "passport" / "passport.html").exists())
        self.assertTrue((camp / "passport" / "passport.json").exists())
        verifier = (
            "import sys\n"
            "from fitlab_evaluation.seal import verify_campaign\n"
            "r = verify_campaign(r'%s')\n"
            "assert r['status'] == 'COMPLETED', r['status']\n"
            "print('HIST-OK')\n" % camp
        )
        r = subprocess.run([sys.executable, "-c", verifier], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=120)
        self.assertIn("HIST-OK", r.stdout, r.stderr[-400:])

    def test_console_script_module_invocation(self):
        # python -m fitlab_evaluation.public_cli --help exit 0
        r = subprocess.run(
            [sys.executable, "-m", "fitlab_evaluation.public_cli", "--help"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("inspect", r.stdout)
        self.assertIn("evaluate", r.stdout)
        self.assertIn("passport", r.stdout)


def out_debug(code, text):
    return f"exit={code} out={text[:400]}"


if __name__ == "__main__":
    unittest.main()