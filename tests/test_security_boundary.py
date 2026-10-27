"""Adversarial regression tests for the product boundary.

These cover the attack classes named in the security review: malformed input,
duplicate keys, type coercion, path traversal, injection through revision
arguments, remote routing, evidence hash mismatch, result identity swapping,
contradictory configuration and failure-to-success promotion.

No test weakens an expected outcome to obtain a pass. The frozen F1/F2/F3
scientific contracts are not touched by this module.
"""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fitlab_evaluation.artifacts import ArtifactError, load_json, publish_bundle
from fitlab_evaluation.evidence import make_trust, trust_from_package_index, validate_trust, verify_record
from fitlab_evaluation.run import evaluate
from fitlab_evaluation.workflow import _is_local_reference, safe_runtime_config
from test_f4_integration import FakeClient, GOOD_MEMORY, ROOT


class RevisionArgumentTests(unittest.TestCase):
    """A revision name reaches a git subprocess and must stay inert."""

    def test_option_like_and_hostile_revisions_are_refused(self):
        for value in (
            "--all",
            "--help",
            "-q",
            "--upload-pack=evil",
            "HEAD --output=/tmp/x",
            "../../etc/passwd",
            "refs/heads/../../evil",
            "\x00bad",
            "a" * 300,
            "",
            "with space",
            "tab\tvalue",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ArtifactError) as caught:
                    make_trust(value)
                self.assertIn(caught.exception.code, ("INVALID_SOURCE", "SOURCE_UNAVAILABLE"))

    def test_valid_revisions_are_accepted(self):
        if not (ROOT / ".git").exists():
            self.skipTest("portable archive: no local Git object database")
        head = make_trust("HEAD")
        for value in ("HEAD", head["source_commit"]):
            with self.subTest(value=value):
                trust = make_trust(value)
                self.assertEqual(len(trust["source_commit"]), 40)

    def test_trust_validates_and_binds(self):
        if not (ROOT / ".git").exists():
            self.skipTest("portable archive: no local Git object database")
        trust = make_trust("HEAD")
        validate_trust(trust)
        self.assertEqual(trust["schema_version"], "fitlab-trust-v1")
        self.assertTrue(trust["source_sha256"])

    def test_external_snapshot_rejects_any_altered_bound_source(self):
        if not (ROOT / ".git").exists():
            self.skipTest("requires a Git trust source")
        trust = make_trust("HEAD")
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            for relative in trust["source_sha256"]:
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            altered = snapshot / "fitlab_evaluation" / "lemonade.py"
            altered.write_bytes(altered.read_bytes() + b"\n# altered\n")
            with patch("fitlab_evaluation.evidence.ROOT", snapshot):
                with self.assertRaisesRegex(ArtifactError, "SOURCE_SNAPSHOT_MISMATCH"):
                    validate_trust(trust)

    def test_externally_supplied_trust_cannot_carry_private_detail(self):
        # Round-51 A-1: in a non-Git installation the trust snapshot is
        # externally supplied and validate_trust accepted a boundary field
        # carrying private detail; export_report then published trust.json
        # verbatim. The whole trust document is now scanned before
        # validation accepts it: unsanitized trust is refused with a
        # stable error and NOTHING is published; sanitized trust
        # (including the frozen boundary) is unaffected. The scenario is
        # driven against a .git-less snapshot whose bytes verifiably match
        # the trust hashes - the exact non-Git execution environment.
        if not (ROOT / ".git").exists():
            self.skipTest("requires a Git trust source")
        from fitlab_evaluation import evidence as evidence_module
        from fitlab_evaluation.report_v3 import export_report
        trust = make_trust("HEAD")
        with tempfile.TemporaryDirectory() as snapshot_dir:
            snapshot = Path(snapshot_dir)
            # Snapshot bytes come from the COMMITTED source (git show),
            # not the possibly-dirty worktree: on a checkout with line-
            # ending translation the worktree bytes differ from the git
            # blob bytes, and a mid-edit tree would misbind the hashes.
            for relative in trust["source_sha256"]:
                raw = subprocess.run(
                    ["git", "show", f"HEAD:{relative}"],
                    cwd=ROOT, check=True,
                    stdout=subprocess.PIPE).stdout
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            with patch.object(evidence_module, "ROOT", snapshot):
                private_email = "researcher@fitlab.invalid"
                for boundary in (
                    f"Contact {private_email} for the private dataset.",
                    "Built on C:\\Users\\sampleuser\\machine before review.",
                ):
                    with self.subTest(boundary=boundary):
                        unsanitized = dict(trust)
                        unsanitized["boundary"] = boundary
                        with self.assertRaisesRegex(ArtifactError, "TRUST_NOT_SANITIZED"):
                            validate_trust(unsanitized)
                        with tempfile.TemporaryDirectory() as out:
                            with self.assertRaisesRegex(ArtifactError, "TRUST_NOT_SANITIZED"):
                                export_report(out, unsanitized)
                            self.assertEqual(list(Path(out).iterdir()), [])
                # A private source-path key is equally refused.
                path_key = "C:/Users/sampleuser/fitlab_evaluation/run.py"
                path_trust = dict(trust)
                path_trust["source_sha256"] = dict(trust["source_sha256"])
                path_trust["source_sha256"][path_key] = trust["source_sha256"]["fitlab_evaluation/run.py"]
                with self.assertRaisesRegex(ArtifactError, "TRUST_NOT_SANITIZED"):
                    validate_trust(path_trust)
        # The frozen trust (boundary included) still validates cleanly.
        validate_trust(make_trust("HEAD"))


class RemoteRoutingTests(unittest.TestCase):
    """A local-only measurement must never be routed to a cloud endpoint."""

    def test_local_references_are_accepted(self):
        for value in (
            "127.0.0.1",
            "localhost",
            "http://127.0.0.1:13305",
            "http://localhost:8080/v1",
            "::1",
            "/usr/local/bin/server",
        ):
            with self.subTest(value=value):
                self.assertTrue(_is_local_reference(value))

    def test_remote_references_are_refused(self):
        for value in (
            "https://api.example.com",
            "http://api.openai.com/v1",
            "api.example.com",
            "evil",
            "https://192.168.1.44:13305",
            "wss://remote.example.com",
        ):
            with self.subTest(value=value):
                self.assertFalse(_is_local_reference(value))

    def test_config_with_remote_routing_is_refused(self):
        def read_config(body):
            connection = Mock()
            connection.sock = None
            response = connection.getresponse.return_value
            response.status = 200
            response.read.return_value = body
            response.getheader.side_effect = lambda k, d=None: {"Content-Type": "application/json"}.get(k, d)
            return connection

        bodies = [
            b'{"offline":true,"no_fetch_executables":true,"endpoint":"https://api.example.com"}',
            b'{"offline":true,"no_fetch_executables":true,"base_url":"https://api.example.com/v1"}',
            b'{"offline":true,"no_fetch_executables":true,"cloud":true}',
            b'{"offline":true,"no_fetch_executables":true,"telemetry":true}',
        ]
        for body in bodies:
            with self.subTest(body=body):
                connection = read_config(body)
                with patch(
                    "fitlab_evaluation.workflow.http.client.HTTPConnection",
                    return_value=connection,
                ):
                    with self.assertRaises(ArtifactError) as caught:
                        safe_runtime_config()
                self.assertIn(
                    caught.exception.code,
                    ("RUNTIME_REMOTE_ROUTING_REFUSED", "RUNTIME_NOT_PROVEN_OFFLINE"),
                )

    def test_local_config_is_still_accepted(self):
        connection = Mock()
        connection.sock = None
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = (
            b'{"offline":true,"no_fetch_executables":true,"host":"127.0.0.1","port":13305}'
        )
        response.getheader.side_effect = lambda k, d=None: {"Content-Type": "application/json"}.get(k, d)
        with patch(
            "fitlab_evaluation.workflow.http.client.HTTPConnection", return_value=connection
        ):
            self.assertEqual(
                safe_runtime_config(), {"offline": True, "no_fetch_executables": True}
            )


class EvidencePromotionTests(unittest.TestCase):
    """A stopped, partial or failed run must never become a success."""

    @classmethod
    def setUpClass(cls):
        cls.trust = make_trust("HEAD") if (ROOT / ".git").exists() else trust_from_package_index(ROOT)

    def record(self, repeats=3, fail_at=None):
        with patch("fitlab_evaluation.run.identity", return_value=self.trust["source_sha256"]):
            return evaluate(
                None,
                repeats,
                client=FakeClient(fail_at=fail_at),
                memory=lambda: GOOD_MEMORY,
                pause=lambda _: None,
            )

    def test_partial_run_cannot_be_promoted_to_completed(self):
        record = self.record(3, fail_at=3)
        self.assertEqual(record["status"], "STOPPED")
        forged = copy.deepcopy(record)
        forged["status"] = "COMPLETED"
        with self.assertRaises(ArtifactError):
            verify_record(forged, self.trust)

    def test_forged_grade_is_recomputed(self):
        record = self.record(1)
        forged = copy.deepcopy(record)
        forged["rows"][0]["grade"] = dict(forged["rows"][0]["grade"], passed=False)
        with self.assertRaisesRegex(ArtifactError, "GRADE_MISMATCH"):
            verify_record(forged, self.trust)

    def test_forged_response_is_regraded(self):
        record = self.record(1)
        forged = copy.deepcopy(record)
        forged["rows"][0]["response"]["choices"][0]["message"]["content"] = "WRONG-ANSWER"
        with self.assertRaisesRegex(ArtifactError, "RESPONSE_HASH_MISMATCH"):
            verify_record(forged, self.trust)

    def test_forged_summary_is_rejected(self):
        record = self.record(1)
        forged = copy.deepcopy(record)
        forged["summary"] = dict(forged["summary"], passed_count=0)
        with self.assertRaisesRegex(ArtifactError, "SUMMARY_MISMATCH"):
            verify_record(forged, self.trust)

    def test_swapped_row_identity_is_rejected(self):
        record = self.record(1)
        forged = copy.deepcopy(record)
        forged["rows"][0]["case_id"] = "D5"
        with self.assertRaises(ArtifactError):
            verify_record(forged, self.trust)

    def test_evidence_hash_mismatch_is_rejected(self):
        record = self.record(1)
        forged = copy.deepcopy(record)
        forged["task_pack_sha256"] = "0" * 64
        with self.assertRaisesRegex(ArtifactError, "TASK_HASH_MISMATCH"):
            verify_record(forged, self.trust)

    def test_trust_with_foreign_source_is_rejected(self):
        if not (ROOT / ".git").exists():
            # Without a local Git object database there is nothing to compare
            # the commit against. That is a documented, deliberate boundary:
            # an archive binds to an externally supplied snapshot and the
            # report says so. The archive environment is checked by the
            # task-pack and replay-version checks instead.
            self.skipTest("portable archive: no local Git object database")
        trust = copy.deepcopy(self.trust)
        trust["source_commit"] = "0" * 40
        with self.assertRaises(ArtifactError):
            validate_trust(trust)

    def test_trust_with_altered_task_pack_is_rejected(self):
        trust = copy.deepcopy(self.trust)
        trust["task_pack_text"] = trust["task_pack_text"].replace("E1", "EX")
        with self.assertRaises(ArtifactError):
            validate_trust(trust)


class MalformedInputTests(unittest.TestCase):
    """Malformed, oversized, duplicated and non-UTF-8 input fails closed."""

    def test_malformed_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for payload in (
                b'{"x":1,"x":2}',
                b"\xff",
                b"[" * 200 + b"]" * 200,
                b'{"x":NaN}',
                b'{"x":Infinity}',
                b'{"x":1e999}',
                b"",
                b'{"x":1,',
            ):
                with self.subTest(payload=payload[:16]):
                    path.write_bytes(payload)
                    with self.assertRaises(ArtifactError):
                        load_json(path)

    def test_oversized_input_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.json"
            path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ArtifactError, "INPUT_TOO_LARGE"):
                load_json(path)

    def test_bundle_names_cannot_escape_the_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../escape.json", "a/b.json", "/abs.json", ".", ".."):
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ArtifactError, "INVALID_BUNDLE"):
                        publish_bundle(Path(directory) / "out", {name: "x"})

    def test_bundle_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out"
            publish_bundle(destination, {"a.json": "1"})
            before = {path.name: path.read_bytes() for path in destination.iterdir()}
            with self.assertRaises(ArtifactError):
                publish_bundle(destination, {"a.json": "2"})
            after = {path.name: path.read_bytes() for path in destination.iterdir()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
