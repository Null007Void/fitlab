"""Windows sealed-evidence byte-stability regression.

Reproduces the LIVE-002 finding (§11 of live-validation-report.md): product
writers used Windows text mode, so sealed JSON files were stored CRLF on
disk; the repository's ``* text=auto eol=lf`` rule normalized them to LF at
commit time and a fresh checkout could no longer reproduce the recorded
seal hashes (SEAL_HASH_MISMATCH from an otherwise correct tree).

The fix: every evidence writer emits '\n' byte-exactly (newline='' on all
text-mode writes). The discriminating test builds a miniature clone of the
product (real source files), runs a real SYNTHETIC campaign through the
real exporter and seal writer inside it, commits the campaign under plain
repository attributes (no -text carve-out), materializes a fresh clone,
and requires verify_campaign to PASS against the checked-out bytes.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def _run_python(work, code, env=None):
    """Run a python snippet with cwd=work; the product is importable there."""
    import os
    environment = dict(os.environ if env is None else env)
    environment.setdefault("PYTHONPATH", str(work))
    return subprocess.run(
        [sys.executable, "-c", code], cwd=str(work), env=environment,
        capture_output=True, text=True, timeout=300,
    )


DRIVER = r'''
import json, sys
from pathlib import Path
from fitlab_evaluation.artifacts import publish_bundle, stable_json
from fitlab_evaluation.evidence import make_trust
from fitlab_evaluation.report_v3 import export_report
from fitlab_evaluation.run import evaluate
from fitlab_evaluation.workflow import _write_final_seal
sys.path.insert(0, "tests")
from test_f4_integration import FakeClient, GOOD_MEMORY

campaign = Path("evidence/phase-a/synthetic-checkout-001")
campaign.parent.mkdir(parents=True, exist_ok=True)
trust = make_trust("HEAD")
record = evaluate(None, 1, client=FakeClient(),
                  memory=lambda: dict(GOOD_MEMORY), pause=lambda _: None)
assert record["status"] == "COMPLETED", record["status"]
assert record["execution_kind"] == "SYNTHETIC_TEST"
# Product order: the campaign bundle is published first (creating the
# campaign directory), then the passport bundle inside it — this mirrors
# workflow.execute() and report_v3.export_report() in the real path.
publish_bundle(campaign, {
    "trust.json": stable_json(trust),
    "bootstrap.json": stable_json({"schema_version": "fitlab-session-v1",
                                   "status": "PREPARING",
                                   "inference_requests": 0}),
    "evaluation.json": stable_json(record),
    "session.json": stable_json({"schema_version": "fitlab-session-v1",
                                 "status": "FINISHED",
                                 "evaluation_status": "COMPLETED",
                                 "inference_requests": len(record["rows"])}),
})
export_report(campaign / "passport", trust, record)
session = json.loads((campaign / "session.json").read_text("utf-8"))
_write_final_seal(campaign, session)
print("CAMPAIGN-OK")
'''


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True).stdout.strip()


class WriterByteStability(unittest.TestCase):
    """Unit level: the corrected writers never emit CRLF on Windows."""

    def test_checkpoint_and_manifest_write_lf_bytes(self):
        import sys
        from fitlab_evaluation.workflow import _checkpoint
        from fitlab_evaluation.artifacts import publish_bundle
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evaluation.json"
            _checkpoint(target, {"schema_version": "fitlab-evaluation-v2",
                                 "probe": 1})
            self.assertNotIn(b"\r\n", target.read_bytes())
            bundle = Path(tmp) / "bundle"
            publish_bundle(bundle, {"component.txt": "alpha\nbeta\n"})
            self.assertNotIn(b"\r\n", (bundle / "manifest.json").read_bytes())


class SealedEvidenceCheckoutStability(unittest.TestCase):
    """End to end: produce, seal, commit, fresh clone, verify_campaign."""

    def test_synthetic_campaign_survives_commit_and_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "repo"
            work.mkdir()
            # Miniature product clone: real source bytes, plain attributes.
            (work / ".gitattributes").write_bytes(
                (ROOT / ".gitattributes").read_bytes())
            for item in ("fitlab_evaluation", "fitlab_foundation", "fixtures",
                         "tests/test_f4_integration.py", "tests/trust-d794.json"):
                src = ROOT / item
                dst = work / item
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc"))
                else:
                    shutil.copy2(src, dst)
            _git("init", "-q", cwd=work)
            _git("config", "user.email", "fixture@fitlab.invalid", cwd=work)
            _git("config", "user.name", "Byte Stability Fixture", cwd=work)
            _git("config", "core.autocrlf", "true", cwd=work)
            # Commit the product FIRST so make_trust("HEAD") resolves and the
            # campaign commit carries only the evidence (matching LIVE-002,
            # where the campaign commit added evidence to a frozen source).
            _git("add", "-A", cwd=work)
            _git("commit", "-q", "-m", "product source", cwd=work)
            source_commit = _git("rev-parse", "HEAD", cwd=work)

            produced = _run_python(work, DRIVER)
            self.assertIn("CAMPAIGN-OK", produced.stdout,
                          msg=produced.stdout + produced.stderr)
            campaign = work / "evidence" / "phase-a" / "synthetic-checkout-001"
            self.assertEqual(
                campaign / "trust.json" and
                json.loads((campaign / "trust.json").read_text("utf-8"))[
                    "source_commit"],
                source_commit)

            # Produced bytes must already be LF-exact (the actual fix).
            for name in ("evaluation.json", "session.json", "manifest.json"):
                self.assertNotIn(b"\r\n", (campaign / name).read_bytes(),
                                 f"{name} was written with CRLF")

            # Commit the campaign under PLAIN repository attributes (no
            # -text carve-out anywhere).
            _git("add", "-A", cwd=work)
            _git("commit", "-q", "-m", "sealed synthetic campaign", cwd=work)

            # Fresh clone of that commit. Verification runs in an ISOLATED
            # subprocess: the checked-out product is imported only there, so
            # no module from the checkout can leak into this test session
            # (a same-interpreter import left ROOT bound to the checkout and
            # poisoned later tests).
            checkout = Path(tmp) / "checkout"
            _git("clone", "-q", str(work), str(checkout), cwd=tmp)
            verifier = (
                "import sys\n"
                "from fitlab_evaluation.seal import verify_campaign\n"
                "result = verify_campaign(r'%s')\n"
                "assert result['status'] == 'COMPLETED', result['status']\n"
                "assert result['execution_kind'] == 'SYNTHETIC_TEST'\n"
                "assert result['source']['commit'] == '%s'\n"
                "print('CHECKOUT-VERIFY-OK')\n"
            ) % (checkout / "evidence" / "phase-a" / "synthetic-checkout-001",
                 source_commit)
            verified = _run_python(checkout, verifier)
            self.assertIn("CHECKOUT-VERIFY-OK", verified.stdout,
                          msg=verified.stdout + verified.stderr)


class AcceptedLIVE002EvidenceStillVerifies(unittest.TestCase):
    """The fix must not degrade the accepted historical evidence path: the
    LIVE-002 directory keeps its byte-preserving attribute and its seal."""

    def test_live002_directory_attribute_rule_present(self):
        attributes = (ROOT / "evidence" / ".gitattributes").read_text("utf-8")
        self.assertIn("phase-a/live-validation-001/** -text", attributes)

    def test_shipped_sealed_campaign_verifies(self):
        # The shipped LIVE-002 qualification re-verifies byte-for-byte.
        from fitlab_evaluation.seal import verify_campaign
        result = verify_campaign(
            ROOT / "evidence" / "phase-a" / "live-validation-001")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["execution_kind"], "LOCAL_RUNTIME")


if __name__ == "__main__":
    unittest.main()