"""Owner five-class evidence vocabulary: a presentation layer, never a relabel.

The machine-readable evidence classes stay frozen facts. These tests assert
that the judge-facing labels use only the owner's five words, that a synthetic
or historical record is never presented as this build's measurement, and that a
forged label cannot survive re-rendering.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fitlab_evaluation.artifacts import ArtifactError
from fitlab_evaluation.evidence import make_trust, trust_from_package_index
from fitlab_evaluation.report_v3 import (
    ANALYTICAL_ESTIMATE,
    HISTORICAL_MEASURED_EVIDENCE,
    OWNER_EVIDENCE_CLASSES,
    SYNTHETIC_TEST_EVIDENCE,
    build_report,
    evaluation_label,
    evidence_label,
    export_report,
    render_report,
)
from fitlab_evaluation.run import evaluate
from test_f4_integration import FakeClient, GOOD_MEMORY, ROOT

HISTORICAL = {
    "campaign_id": "fitlab-f5-multicampaign-retry-20261022",
    "request_count": 69,
    "source_commit": "7cfc6d11e385014d13a8ca0afffd3e763ed3d735",
    "source_tree": "3596387cfbbe30f42613ebff1d68ebfb504ac7fa",
    "delivery_sha256": "4f89f471ef5bb1cf354ed8052dce25174f83a33f890a3799bfe3b6d7d05cab4b",
    "note": "Measured by the campaign commit, not by this build.",
}


class EvidenceClassMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trust = make_trust("HEAD") if (ROOT / ".git").exists() else trust_from_package_index(ROOT)

    def synthetic_record(self):
        with patch("fitlab_evaluation.run.identity", return_value=self.trust["source_sha256"]):
            return evaluate(
                None, 1, client=FakeClient(), memory=lambda: GOOD_MEMORY, pause=lambda _: None
            )

    def test_mapping_matrix_uses_only_the_owner_vocabulary(self):
        self.assertEqual(evidence_label("MEASURED"), "MEASURED")
        self.assertEqual(evidence_label("UNKNOWN"), "UNKNOWN")
        for kind in ("ESTIMATED", "CALCULATED", "DECLARED"):
            self.assertEqual(evidence_label(kind), ANALYTICAL_ESTIMATE)
        self.assertEqual(evidence_label("UNSUPPORTED"), "UNKNOWN")
        self.assertEqual(
            evidence_label("MEASURED", execution_kind="SYNTHETIC_TEST"),
            SYNTHETIC_TEST_EVIDENCE,
        )
        self.assertEqual(
            evidence_label("MEASURED", historical=True), HISTORICAL_MEASURED_EVIDENCE
        )
        # A harness record can never be presented as measured, even when a
        # historical binding is supplied alongside it.
        self.assertEqual(
            evidence_label("MEASURED", execution_kind="SYNTHETIC_TEST", historical=True),
            SYNTHETIC_TEST_EVIDENCE,
        )
        produced = {
            evidence_label("MEASURED"),
            evidence_label("MEASURED", execution_kind="SYNTHETIC_TEST"),
            evidence_label("MEASURED", historical=True),
            evidence_label("ESTIMATED"),
            evidence_label("UNKNOWN"),
        }
        self.assertEqual(produced, set(OWNER_EVIDENCE_CLASSES))
        for kind in ("MEASURED", "UNKNOWN", "ESTIMATED", "CALCULATED", "DECLARED", "UNSUPPORTED"):
            self.assertIn(evidence_label(kind), OWNER_EVIDENCE_CLASSES)
        with self.assertRaisesRegex(ArtifactError, "INVALID_EVIDENCE_CLASS"):
            evidence_label("NOT_A_CLASS")

    def test_evaluation_label_follows_the_execution_kind(self):
        self.assertEqual(evaluation_label(None), "UNKNOWN")
        self.assertEqual(
            evaluation_label({"execution_kind": "SYNTHETIC_TEST", "measurement_eligible": False}),
            SYNTHETIC_TEST_EVIDENCE,
        )
        self.assertEqual(
            evaluation_label({"execution_kind": "LOCAL_RUNTIME", "measurement_eligible": True}),
            "MEASURED",
        )
        self.assertEqual(
            evaluation_label({"execution_kind": "LOCAL_RUNTIME", "measurement_eligible": False}),
            "UNKNOWN",
        )

    def test_planning_estimates_render_as_analytical_estimate(self):
        plan = json.loads((ROOT / "examples/f2_workload_to_hardware.json").read_text("utf-8"))
        report = build_report(self.trust, plan=plan)
        raw = {claim["evidence_class"] for claim in report["claims"]}
        self.assertIn("ESTIMATED", raw)
        self.assertIn("CALCULATED", raw)
        labels = {claim["evidence_label"] for claim in report["claims"]}
        self.assertIn(ANALYTICAL_ESTIMATE, labels)
        self.assertNotIn("MEASURED", labels)
        self.assertEqual(report["evidence_class"], "UNKNOWN")
        html = render_report(report, self.trust, plan=plan)
        self.assertIn(ANALYTICAL_ESTIMATE, html)

    def test_synthetic_run_is_synthetic_test_evidence_never_measured(self):
        record = self.synthetic_record()
        report = build_report(self.trust, record)
        self.assertEqual(report["evaluation_state"], "SYNTHETIC_ONLY")
        self.assertEqual(report["capability_verdict"], "NOT_EVALUATED")
        self.assertEqual(report["evidence_class"], SYNTHETIC_TEST_EVIDENCE)
        # The raw classes are untouched: this run measured nothing.
        self.assertEqual({claim["evidence_class"] for claim in report["claims"]}, {"UNKNOWN"})
        self.assertEqual({task["evidence_class"] for task in report["tasks"]}, {"UNKNOWN"})
        self.assertNotIn("MEASURED", {claim["evidence_label"] for claim in report["claims"]})
        self.assertNotIn("MEASURED", {task["evidence_label"] for task in report["tasks"]})
        html = render_report(report, self.trust, record)
        self.assertIn(SYNTHETIC_TEST_EVIDENCE, html)

    def test_historical_binding_is_explicit_and_labelled(self):
        # Round-28 A-2: shape-valid history alone is a DECLARATION, not
        # HISTORICAL MEASURED EVIDENCE; the measured class requires
        # corroborating verified LOCAL_RUNTIME evidence bound to the same
        # source identity.
        report = build_report(self.trust, historical=HISTORICAL)
        bound = report["historical_campaign"]
        self.assertEqual(bound["request_count"], 69)
        self.assertEqual(bound["source_commit"], HISTORICAL["source_commit"])
        self.assertEqual(bound["source_tree"], HISTORICAL["source_tree"])
        self.assertEqual(bound["evidence_class"], "DECLARED")
        self.assertFalse(bound["evidence_corroborated"])
        # Binding earlier evidence never measures anything in this report.
        self.assertEqual(report["capability_verdict"], "NOT_EVALUATED")
        self.assertNotIn("MEASURED", {claim["evidence_label"] for claim in report["claims"]})
        html = render_report(report, self.trust, historical=HISTORICAL)
        self.assertIn(HISTORICAL["source_commit"], html)
        self.assertIn("69", html)

    def test_historical_measured_promotion_requires_corroboration(self):
        # Round-30/31/32 A-1 chain: promotion requires a measurement-eligible
        # verified LOCAL_RUNTIME record, verify_campaign-verified shipped
        # bytes, and campaign identity bound through the verification record.
        # The synthetic HISTORICAL fixture names a commit that is NOT this
        # checkout's, so without shipped-corroboration it stays DECLARED.
        record = self.synthetic_record()
        report = build_report(self.trust, record, historical=HISTORICAL)
        # Synthetic record: not LOCAL_RUNTIME/measurement-eligible, so no
        # promotion.
        self.assertFalse(report["historical_campaign"]["evidence_corroborated"])
        self.assertEqual(
            report["historical_campaign"]["evidence_class"], "DECLARED")
        self.assertEqual(
            report["evidence_class"], SYNTHETIC_TEST_EVIDENCE)

    def test_declared_campaign_id_mismatch_keeps_declared(self):
        # Round-32: an invented campaign_id must NOT receive measured
        # corroboration even when other fields look plausible. The shipped
        # verification record has no free-text campaign identity, so any
        # campaign_id that cannot be bound to the shipped verified campaign
        # stays DECLARED — including a fabricated id.
        from fitlab_evaluation.report_v3 import EXPORT_EVIDENCE
        record_path = EXPORT_EVIDENCE / "phase-a/live-validation-public-verification.json"
        if not record_path.exists():
            self.skipTest("verification record not shipped in this checkout")
        impostor = dict(HISTORICAL)
        impostor["campaign_id"] = "invented-campaign-20261022"
        impostor["source_commit"] = self.trust["source_commit"]
        impostor["source_tree"] = self.trust["source_tree"]
        report = build_report(self.trust, historical=impostor)
        self.assertFalse(
            report["historical_campaign"]["evidence_corroborated"])
        self.assertEqual(
            report["historical_campaign"]["evidence_class"], "DECLARED")

    def test_incomplete_or_forged_historical_binding_is_rejected(self):
        variants = []
        for key in HISTORICAL:
            incomplete = dict(HISTORICAL)
            incomplete.pop(key)
            variants.append(incomplete)
        for field, value in (
            ("request_count", 0),
            ("request_count", True),
            ("source_commit", "0" * 39),
            ("source_commit", "Z" * 40),
            ("delivery_sha256", "0" * 63),
            ("campaign_id", ""),
            ("note", ""),
        ):
            forged = dict(HISTORICAL)
            forged[field] = value
            variants.append(forged)
        extra = dict(HISTORICAL)
        extra["claimed_label"] = "MEASURED"
        variants.append(extra)
        for binding in variants:
            with self.subTest(binding=binding), self.assertRaisesRegex(
                ArtifactError, "INVALID_HISTORICAL_BINDING"
            ):
                build_report(self.trust, historical=binding)

    def test_root_level_posix_file_redacted_and_scanned(self):
        # Round-36: unknown-root contiguous files ("/custom/model.gguf") are
        # redacted; the scanner includes the root-level rule.
        from fitlab_evaluation.redact import (
            contains_private_detail, redact_text)
        self.assertEqual(redact_text("/custom/model.gguf"), "[redacted]")
        self.assertTrue(contains_private_detail("/custom/model.gguf"))
        self.assertTrue(contains_private_detail("/confidential.gguf"))

    def test_publication_scanner_sees_user_profile_patterns(self):
        # Round-34 A-1: contains_private_detail must include the dedicated
        # user-profile patterns, otherwise a single-backslash
        # "\Users\name\..." fragment slips into the published record.
        from fitlab_evaluation.redact import contains_private_detail
        probe = "resumed from " + chr(92) + "Users" + chr(92) + "sampleuser" + chr(92) + "model.gguf"
        self.assertTrue(contains_private_detail(probe))
        probe2 = "host /home/sampleuser/artifacts"
        self.assertTrue(contains_private_detail(probe2))
        # Plain prose without private shapes is not a finding.
        self.assertFalse(contains_private_detail(
            "resumed from the checkpoint directory after the outage"))

    def test_forged_label_cannot_upgrade_a_report(self):
        forged = build_report(self.trust)
        forged["claims"][0]["evidence_label"] = "MEASURED"
        forged["evidence_class"] = "MEASURED"
        with self.assertRaisesRegex(ArtifactError, "REPORT_MISMATCH"):
            render_report(forged, self.trust)

    def test_vocabulary_is_published_and_machine_classes_are_preserved(self):
        report = build_report(self.trust)
        self.assertEqual(
            tuple(report["evidence_class_vocabulary"]["owner"]), OWNER_EVIDENCE_CLASSES
        )
        self.assertIn("ESTIMATED", report["evidence_class_vocabulary"]["machine"])
        for claim in report["claims"]:
            self.assertEqual(
                claim["evidence_label"], evidence_label(claim["evidence_class"])
            )
            self.assertIn(claim["evidence_label"], OWNER_EVIDENCE_CLASSES)

    def test_export_records_the_binding_without_measuring_this_build(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "passport"
            export_report(destination, self.trust, historical=HISTORICAL)
            payload = json.loads((destination / "passport.json").read_text("utf-8"))
            self.assertEqual(payload["historical_campaign"]["request_count"], 69)
            # Round-28 A-2: without a corroborating verified record, the
            # binding is a declaration, not measured evidence.
            self.assertEqual(
                payload["historical_campaign"]["evidence_class"], "DECLARED")
            self.assertFalse(
                payload["historical_campaign"]["evidence_corroborated"])
            self.assertEqual(payload["evaluation_state"], "NO_EVIDENCE")
            html = (destination / "passport.html").read_text("utf-8")
            self.assertIn(HISTORICAL["delivery_sha256"], html)


if __name__ == "__main__":
    unittest.main()
