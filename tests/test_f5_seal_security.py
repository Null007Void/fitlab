"""Adversarial tests for the final campaign seal."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fitlab_evaluation.artifacts import ArtifactError
from fitlab_evaluation.workflow import _write_final_seal


class SealSecurityTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("bootstrap.json", "trust.json", "manifest.json"):
            (self.root / name).write_text(
                "{}", encoding="utf-8"
            )
        (self.root / "session.json").write_text(
            '{"status":"BLOCKED"}', encoding="utf-8"
        )
        _write_final_seal(self.root, {"status": "BLOCKED"})

    def tearDown(self):
        self.temp.cleanup()

    def verify(self):
        from fitlab_evaluation.seal import verify_final_seal
        return verify_final_seal(self.root)

    def test_valid_seal_verifies(self):
        result = self.verify()
        self.assertEqual(result["status"], "BLOCKED")

    def test_modified_session_is_rejected(self):
        (self.root / "session.json").write_text(
            '{"status":"FINISHED"}', encoding="utf-8"
        )
        with self.assertRaises(ArtifactError):
            self.verify()

    def test_unsealed_extra_file_is_rejected(self):
        (self.root / "unrecorded.json").write_text(
            '{"result":"unverified"}', encoding="utf-8"
        )
        with self.assertRaises(ArtifactError):
            self.verify()

    def test_oversized_file_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in (
                "bootstrap.json", "trust.json",
                "manifest.json", "session.json"
            ):
                (root / name).write_text(
                    '{"status":"BLOCKED"}', encoding="utf-8"
                )

            large = root / "oversized.bin"
            with large.open("wb") as handle:
                handle.truncate(8 * 1024 * 1024 + 1)

            original = Path.read_bytes

            def guarded_read(path):
                if path.name == "oversized.bin":
                    raise AssertionError(
                        "Oversized file was read into memory"
                    )
                return original(path)

            with patch.object(Path, "read_bytes", guarded_read):
                with self.assertRaisesRegex(
                    ArtifactError, "SEAL_FILE_TOO_LARGE"
                ):
                    _write_final_seal(
                        root, {"status": "BLOCKED"}
                    )


    def test_finished_without_evaluation_is_rejected(self):
        (self.root / "final-seal.json").unlink()
        (self.root / "session.json").write_text(
            '{"status":"FINISHED"}', encoding="utf-8"
        )
        with self.assertRaises(ArtifactError):
            _write_final_seal(self.root, {"status": "FINISHED"})
        self.assertFalse(
            (self.root / "final-seal.json").exists()
        )

    def test_finished_without_passport_is_rejected(self):
        (self.root / "final-seal.json").unlink()
        (self.root / "session.json").write_text(
            '{"status":"FINISHED"}', encoding="utf-8"
        )
        (self.root / "evaluation.json").write_text(
            '{"status":"COMPLETED"}', encoding="utf-8"
        )
        with self.assertRaises(ArtifactError):
            _write_final_seal(self.root, {"status": "FINISHED"})
        self.assertFalse(
            (self.root / "final-seal.json").exists()
        )


    def _prepare_finished(self):
        import hashlib
        (self.root / "final-seal.json").unlink()
        (self.root / "session.json").write_text(
            '{"status":"FINISHED","evaluation_status":"COMPLETED"}',
            encoding="utf-8",
        )
        (self.root / "evaluation.json").write_text(
            '{"status":"COMPLETED"}', encoding="utf-8"
        )

        passport = self.root / "passport"
        passport.mkdir()
        report = passport / "report.json"
        report.write_text('{"verified":true}', encoding="utf-8")
        digest = hashlib.sha256(report.read_bytes()).hexdigest()
        (passport / "manifest.json").write_text(
            json.dumps({
                "schema_version": "fitlab-bundle-v1",
                "files": {"report.json": digest},
            }),
            encoding="utf-8",
        )

    def test_completed_campaign_verifies(self):
        self._prepare_finished()
        _write_final_seal(self.root, {"status": "FINISHED"})
        seal = self.verify()
        self.assertEqual(seal["status"], "FINISHED")
        self.assertIn("evaluation.json", seal["files"])
        self.assertIn("passport/report.json", seal["files"])

    def test_completed_passport_tamper_is_rejected(self):
        self._prepare_finished()
        _write_final_seal(self.root, {"status": "FINISHED"})
        (self.root / "passport/report.json").write_text(
            '{"verified":false}', encoding="utf-8"
        )
        with self.assertRaises(ArtifactError):
            self.verify()

    def test_stopped_session_without_passport_verifies(self):
        (self.root / "final-seal.json").unlink()
        (self.root / "session.json").write_text(
            '{"status":"STOPPED"}', encoding="utf-8"
        )
        _write_final_seal(self.root, {"status": "STOPPED"})
        self.assertEqual(self.verify()["status"], "STOPPED")

    def test_malformed_seal_status_fails_closed(self):
        seal_path = self.root / "final-seal.json"
        seal = json.loads(seal_path.read_text("utf-8"))
        seal["status"] = []
        seal_path.write_text(json.dumps(seal), encoding="utf-8")
        with self.assertRaises(ArtifactError):
            self.verify()



    def test_real_passport_exporter_seal(self):
        """Real V3 export, synthetic evaluation, no model contacted."""
        from fitlab_evaluation.artifacts import publish_bundle, stable_json
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.report_v3 import export_report
        from fitlab_evaluation.run import evaluate
        from test_f4_integration import FakeClient, GOOD_MEMORY

        trust = make_trust("HEAD")
        record = evaluate(
            None, 1,
            client=FakeClient(),
            memory=lambda: GOOD_MEMORY,
            pause=lambda _: None,
        )
        self.assertEqual(record["status"], "COMPLETED")
        self.assertEqual(record["execution_kind"], "SYNTHETIC_TEST")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "campaign"
            publish_bundle(root, {
                "trust.json": stable_json(trust),
                "bootstrap.json": stable_json({
                    "schema_version": "fitlab-session-v1",
                    "status": "PREPARING",
                    "inference_requests": 0,
                }),
            })

            (root / "evaluation.json").write_text(
                stable_json(record), encoding="utf-8"
            )
            session = {
                "schema_version": "fitlab-session-v1",
                "status": "FINISHED",
                "evaluation_status": "COMPLETED",
                "inference_requests": len(record["rows"]),
            }
            (root / "session.json").write_text(
                stable_json(session), encoding="utf-8"
            )

            export_report(root / "passport", trust, record)
            _write_final_seal(root, session)

            from fitlab_evaluation.seal import verify_final_seal
            seal = verify_final_seal(root)
            self.assertEqual(seal["status"], "FINISHED")

            from fitlab_evaluation.seal import verify_campaign
            verified = verify_campaign(root)
            self.assertEqual(verified["status"], "COMPLETED")
            self.assertEqual(
                verified["execution_kind"], "SYNTHETIC_TEST"
            )

            html = root / "passport" / "passport.html"
            self.assertTrue(html.is_file())
            html.write_bytes(html.read_bytes() + b"altered")

            with self.assertRaises(ArtifactError):
                verify_final_seal(root)


if __name__ == "__main__":
    unittest.main()