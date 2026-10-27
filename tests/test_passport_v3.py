"""Capability Passport v3 safety and honesty tests.

The Passport is the competition-facing artifact. These tests assert the
properties that must never regress:

* a synthetic harness record can never appear as a measurement;
* a forged report dictionary cannot add a measurement;
* a missing measurement is unavailable, never zero and never a pass;
* the core R2 denominator is fixed and supplemental cases cannot satisfy it;
* the rendered document is self-contained and leaks no private detail.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fitlab_evaluation.artifacts import ArtifactError
from fitlab_evaluation.evidence import make_trust, trust_from_package_index, verify_record
from fitlab_evaluation.report_v3 import build_report, render_report, export_report
from fitlab_evaluation.run import evaluate
from test_f4_integration import FakeClient, GOOD_MEMORY, ROOT


class PassportV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trust = make_trust("HEAD") if (ROOT / ".git").exists() else trust_from_package_index(ROOT)

    def synthetic_record(self, repeats=1):
        with patch("fitlab_evaluation.run.identity", return_value=self.trust["source_sha256"]):
            return evaluate(
                None, repeats, client=FakeClient(), memory=lambda: GOOD_MEMORY, pause=lambda _: None
            )

    def test_synthetic_record_never_becomes_measured(self):
        record = self.synthetic_record()
        report = build_report(self.trust, record)
        self.assertEqual(report["evaluation_state"], "SYNTHETIC_ONLY")
        self.assertEqual(report["capability_verdict"], "NOT_EVALUATED")
        self.assertFalse(report["complete_protocol"])
        self.assertEqual(
            [claim for claim in report["claims"] if claim["evidence_class"] == "MEASURED"], []
        )
        for task in report["tasks"]:
            self.assertEqual(task["evidence_class"], "UNKNOWN")
            self.assertIsNone(task["observed"])
            self.assertIsNone(task["passed"])

    def test_no_evidence_report_is_all_unknown(self):
        report = build_report(self.trust)
        self.assertEqual(report["evaluation_state"], "NO_EVIDENCE")
        self.assertEqual(report["capability_verdict"], "NOT_EVALUATED")
        for claim in report["claims"]:
            self.assertNotEqual(claim["evidence_class"], "MEASURED")
        for task in report["tasks"]:
            self.assertEqual(task["evidence_class"], "UNKNOWN")

    def test_forged_report_cannot_add_a_measurement(self):
        report = build_report(self.trust)
        report["claims"][0]["value"] = 100
        report["claims"][0]["evidence_class"] = "MEASURED"
        with self.assertRaisesRegex(ArtifactError, "REPORT_MISMATCH"):
            render_report(report, self.trust)

    def test_forged_task_outcome_cannot_add_a_measurement(self):
        report = build_report(self.trust)
        report["tasks"][0]["observed"] = 3
        report["tasks"][0]["passed"] = 3
        report["tasks"][0]["evidence_class"] = "MEASURED"
        with self.assertRaises(ArtifactError):
            render_report(report, self.trust)

    def test_tiers_separate_core_from_supplemental(self):
        report = build_report(self.trust)
        tiers = {task["id"]: task["tier"] for task in report["tasks"]}
        self.assertEqual(
            [k for k, v in tiers.items() if v == "core"], ["E1", "E2", "E3", "D1", "D2", "D3"]
        )
        self.assertEqual([k for k, v in tiers.items() if v == "supplemental"], ["D4", "D5"])
        self.assertEqual(report["task_tiers"]["denominator_policy"]["core_denominator"], 18)

    def test_task_tiers_are_bound_to_frozen_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "task-tiers.json"
            altered.write_text('{"schema_version":"fitlab-task-tiers-v1","tiers":{}}', encoding="utf-8")
            with patch("fitlab_evaluation.report_v3.TASK_TIERS_PATH", altered):
                with self.assertRaisesRegex(ArtifactError, "TASK_TIERS_SOURCE_MISMATCH"):
                    build_report(self.trust)

    def test_rendering_is_deterministic(self):
        report = build_report(self.trust)
        first = render_report(report, self.trust)
        second = render_report(copy.deepcopy(report), self.trust)
        self.assertEqual(first, second)

    def test_rendered_document_is_self_contained(self):
        html = render_report(build_report(self.trust), self.trust)
        for forbidden in ("<script", "src=", "href=", "cdn", "googleapis", "http://", "https://"):
            self.assertNotIn(forbidden, html.lower(), f"external reference {forbidden}")
        # Inline style only, and a restrictive content security policy.
        self.assertIn("default-src 'none'", html)
        self.assertIn("script-src 'none'", html)

    def test_rendered_document_escapes_untrusted_text(self):
        report = build_report(self.trust)
        report["limitations"] = ["<script>alert(1)</script>"]
        # The report must be rebuilt from validated facts, so a mutated
        # dictionary cannot reach the renderer at all.
        with self.assertRaises(ArtifactError):
            render_report(report, self.trust)

    def test_export_bundle_is_complete_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "passport"
            export_report(destination, self.trust)
            names = {path.name for path in destination.iterdir()}
            self.assertIn("passport.html", names)
            self.assertIn("passport.json", names)
            self.assertIn("trust.json", names)
            self.assertIn("manifest.json", names)
            before = {path.name: path.read_bytes() for path in destination.iterdir()}
            with self.assertRaises(ArtifactError):
                export_report(destination, self.trust)
            after = {path.name: path.read_bytes() for path in destination.iterdir()}
            self.assertEqual(before, after)

    def test_manifest_binds_every_exported_file(self):
        from fitlab_evaluation.artifacts import digest

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "passport"
            export_report(destination, self.trust)
            manifest = json.loads((destination / "manifest.json").read_text())
            for name, expected in manifest["files"].items():
                self.assertEqual(digest((destination / name).read_bytes()), expected)

    def test_advisory_and_provenance_are_carried_without_measurement(self):
        advisory = {
            "kind": "COMPOSITE_MEMORY_ADVISORY",
            "bytes": 1000,
            "components": [
                {
                    "component": "idealized_weight_payload_bytes",
                    "bytes": 1000,
                    "evidence": "ESTIMATED",
                    "basis": "test",
                    "limitation": "test",
                }
            ],
            "engine_result": "UNKNOWN",
            "engine_reason": "test",
            "limitations": ["test"],
        }
        provenance = {"model_id": "LFM2.5-1.2B-Instruct-GGUF", "hybrid": True}
        host = {"total_physical_bytes": 16 * (1 << 30), "cpu_brand": "Test CPU"}
        report = build_report(self.trust, None, None, advisory, provenance, host)
        self.assertEqual(report["memory_advisory"], advisory)
        self.assertEqual(report["planning_provenance"], provenance)
        self.assertEqual(report["host"], host)
        self.assertEqual(report["capability_verdict"], "NOT_EVALUATED")
        html = render_report(report, self.trust, None, None, advisory, provenance, host)
        self.assertIn("LFM2.5-1.2B-Instruct-GGUF", html)
        self.assertIn("Test CPU", html)
        self.assertIn("Memory advisory", html)

    def test_private_detail_is_redacted_from_rendered_output(self):
        provenance = {
            "model_id": "LFM2.5-1.2B-Instruct-GGUF",
            "residency_assumption": "loaded from C:\\Users\\Overh\\model.gguf by owner@example.com",
        }
        host = {"cpu_brand": "Intel(R) Core(TM) Ultra 7 155H"}
        report = build_report(self.trust, None, None, None, provenance, host)
        serialized = json.dumps(report)
        self.assertNotIn("Overh", serialized)
        self.assertNotIn("owner@example.com", serialized)
        self.assertNotIn("C:\\\\Users", serialized)
        html = render_report(report, self.trust, None, None, None, provenance, host)
        self.assertNotIn("Overh", html)
        self.assertNotIn("C:\\Users", html)
        # The product identity must survive redaction.
        self.assertIn("LFM2.5-1.2B-Instruct-GGUF", html)


if __name__ == "__main__":
    unittest.main()
