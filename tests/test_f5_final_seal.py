"""F5 final campaign evidence seal regressions."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fitlab_evaluation.workflow import execute
from fitlab_evaluation.evidence import make_trust


class FinalSealTests(unittest.TestCase):

    def test_blocked_session_has_integrity_seal(self):
        trust = make_trust("HEAD")
        low_memory = {
            "total_physical_bytes": 16 * 2**30,
            "available_physical_bytes": 0,
            "available_commit_bytes": 8 * 2**30,
            "memory_load_percent": 97,
        }

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "session"

            with patch(
                "fitlab_evaluation.workflow.identity",
                return_value=trust["source_sha256"],
            ):
                result = execute(
                    destination,
                    trust,
                    memory=lambda: low_memory,
                )

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["inference_requests"], 0)

            seal_path = destination / "final-seal.json"
            self.assertTrue(
                seal_path.is_file(),
                "Terminal session must have a final evidence seal",
            )

            seal = json.loads(seal_path.read_text("utf-8"))
            self.assertEqual(
                seal["schema_version"],
                "fitlab-final-seal-v1",
            )
            self.assertEqual(seal["status"], "BLOCKED")

            expected_files = {
                "bootstrap.json",
                "trust.json",
                "manifest.json",
                "session.json",
            }
            self.assertEqual(set(seal["files"]), expected_files)

            for name, expected_hash in seal["files"].items():
                actual = hashlib.sha256(
                    (destination / name).read_bytes()
                ).hexdigest()
                self.assertEqual(actual, expected_hash)

            self.assertFalse(
                (destination / "evaluation.json").exists()
            )


if __name__ == "__main__":
    unittest.main()