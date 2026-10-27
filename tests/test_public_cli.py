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
from fitlab_evaluation.artifacts import ArtifactError


def GOOD_MEMORY_FAKE():
    from test_f4_integration import GOOD_MEMORY
    return dict(GOOD_MEMORY)


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

    def test_doctor_display_fields_exclude_private_metadata(self):
        # Round-56 A-1: doctor/inspect copy metadata-derived display
        # fields (snapshot revision, general.architecture,
        # general.license.name) from operator-supplied strings into their
        # output; a private path or email in those fields rode the result
        # verbatim. Display fields are now redacted before publication.
        from unittest.mock import patch
        from fitlab_evaluation import cli as cli_module
        rogue_profile = {
            "model_id": "m", "checkpoint": "c",
            "architecture_family": "lfm2",
            "architecture_kind": "DENSE",
            "attention_mechanism": "STANDARD_FULL",
            "hybrid": False, "total_parameters": 1,
            "quantization": "Q4_K_M", "weight_bits_per_parameter": "4",
            "declared_license_name": "contact admin@corp.invalid or "
                                     "C:\\Users\\sampleuser\\license.txt",
        }

        class _Args:
            commit = "HEAD"

        with patch.object(cli_module, "make_trust",
                          side_effect=ArtifactError("SOURCE_UNAVAILABLE")), \
             patch("fitlab_evaluation.model_profile.profile_hardware",
                   lambda: {"t": 1}), \
             patch("fitlab_evaluation.model_profile.locate_model_file",
                   lambda: ("plain.gguf",
                            "snap C:/Users/sampleuser/revision")), \
             patch("fitlab_evaluation.model_profile.derive_profile",
                   lambda *a, **k: rogue_profile):
            record = cli_module._doctor(_Args())
        model = record["model"]
        serialized = json.dumps(model)
        self.assertNotIn("sampleuser", serialized)
        self.assertNotIn("admin@corp.invalid", serialized)
        self.assertNotIn("corp.invalid", serialized)
        # Structure survives redaction: identifiers are replaced, keys stay.
        self.assertIn("[redacted", model["declared_license_name"])
        self.assertIn("[redacted", model["snapshot_revision"])
        self.assertEqual(model["architecture_family"], "lfm2")

    def test_array_valued_license_metadata_is_never_published(self):
        # Round-57 A-1: an ARRAY<STRING> general.license.name would carry
        # nested private strings through _display unchanged (non-strings
        # passed through raw) and ride the doctor result verbatim.
        # derive_profile accepts the license field only as a bounded
        # string (non-strings collapse to None) and the _display boundary
        # sanitizes any structured container recursively.
        from unittest.mock import patch
        from fitlab_evaluation import cli as cli_module
        from fitlab_evaluation.model_profile import derive_profile
        array_profile = {
            "model_id": "m", "checkpoint": "c",
            "architecture_family": "lfm2",
            "architecture_kind": "DENSE",
            "attention_mechanism": "STANDARD_FULL",
            "hybrid": False, "total_parameters": 1,
            "quantization": "Q4_K_M", "weight_bits_per_parameter": "4",
            "declared_license_name": [
                "reach researcher@fitlab.invalid",
                "C:/Users/sampleuser/notes.txt",
            ],
        }

        class _Args:
            commit = "HEAD"

        with patch.object(cli_module, "make_trust",
                          side_effect=ArtifactError("SOURCE_UNAVAILABLE")), \
             patch("fitlab_evaluation.model_profile.profile_hardware",
                   lambda: {"t": 1}), \
             patch("fitlab_evaluation.model_profile.locate_model_file",
                   lambda: ("plain.gguf", "r1")), \
             patch("fitlab_evaluation.model_profile.derive_profile",
                   lambda *a, **k: array_profile):
            record = cli_module._doctor(_Args())
        serialized = json.dumps(record["model"])
        self.assertNotIn("researcher@fitlab.invalid", serialized)
        self.assertNotIn("sampleuser", serialized)
        self.assertIn("[redacted", serialized)
        # At the profiling layer the non-string license metadata
        # collapses to None before any publisher sees it.
        from fitlab_evaluation import model_profile as profile_module
        summarize = {
            "source": "GGUF_HEADER_METADATA", "file_bytes": 1,
            "gguf_version": 3,
            "metadata": {
                "lfm2.block_count": 4,
                "lfm2.embedding_length": 64,
                "lfm2.attention.head_count": 4,
                "general.license.name": [" hostile@fitlab.invalid "],
            },
            "tensors": [], "name": "LFM2.5-1.2B-Instruct-GGUF",
            "architecture": "lfm2", "file_type_id": 15,
            "quantization": "Q4_K_M", "quantization_known": True,
            "total_parameters": 0, "tensor_count": 0,
            "block_count": 4, "head_count": 4, "head_count_kv": None,
            "head_dimension": None, "embedding_length": 64,
            "context_length": None, "vocab_size": None,
            "expert_markers": [], "mixture_of_experts": False,
        }
        with patch.object(profile_module, "summarize", lambda p: summarize), \
             patch.object(profile_module, "locate_model_file",
                          lambda: ("plain.gguf", None)):
            profile = derive_profile("header-only.gguf", None)
        self.assertIsNone(profile["declared_license_name"])
        self.assertNotIn("hostile@fitlab.invalid", json.dumps(profile))

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

    def test_plan_publication_redacts_provenance_metadata(self):
        # Round-58 A-1: provenance embeds operator-supplied model metadata
        # (GGUF header strings, the registry revision); provenance.json was
        # published verbatim, so a private path or email in the license
        # name or revision string rode the shareable plan bundle. The
        # publication copy is now redacted through the distinct-identity
        # engine.
        import tempfile
        from unittest.mock import patch
        from pathlib import Path as _RealPath
        from fitlab_evaluation import cli as cli_module
        from fitlab_evaluation import plan_builder

        class _Args:
            direction = "workload_to_hardware"
            plan = None
            output_dir = None
            budget_bytes = None
            model_file = "plain.gguf"
            workload = None
            overhead_bytes = None
            overhead_basis = None

        def poisoned_provenance(profile, workload, budget_bytes=None):
            base = _original_provenance(profile, workload, budget_bytes)
            base["declared_license_name"] = (
                "contact admin@corp.invalid or C:\\Users\\sampleuser\\l.txt")
            base["snapshot_revision"] = "snap C:/Users/sampleuser/rev"
            return base

        _original_provenance = plan_builder.provenance

        def fake_build_plan(direction, workload=None, budget_bytes=None,
                            overhead_bytes=None, overhead_basis=None,
                            model_path=None, revision=None):
            return {"schema_version": "fitlab-plan-v2",
                    "direction": direction,
                    "scenarios": [{
                        "scenario_id": "s1",
                        "model": {"model_id": "LFM2.5-1.2B-Instruct-GGUF"},
                    }]}

        summary = {
            "source": "GGUF_HEADER_METADATA", "file_bytes": 1,
            "gguf_version": 3,
            "metadata": {
                "lfm2.block_count": 4,
                "lfm2.embedding_length": 64,
                "lfm2.attention.head_count": 4,
            },
            "tensors": [], "name": "LFM2.5-1.2B-Instruct-GGUF",
            "architecture": "lfm2", "file_type_id": 15,
            "quantization": "Q4_K_M", "quantization_known": True,
            "total_parameters": 0, "tensor_count": 0,
            "block_count": 4, "head_count": 4, "head_count_kv": None,
            "head_dimension": None, "embedding_length": 64,
            "context_length": None, "vocab_size": None,
            "expert_markers": [], "mixture_of_experts": False,
        }

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "plan-bundle"
            _Args.output_dir = Path(destination)
            with patch.object(plan_builder, "provenance",
                              poisoned_provenance), \
                 patch("fitlab_evaluation.model_profile.summarize",
                       lambda p: summary), \
                 patch("fitlab_evaluation.model_profile.locate_model_file",
                       lambda: (Path("plain.gguf"), None)), \
                 patch.object(plan_builder, "build_plan", fake_build_plan), \
                 patch.object(plan_builder, "memory_advisory",
                              lambda *a, **k: {
                                  "kind": "COMPOSITE_MEMORY_ADVISORY",
                                  "bytes": 0, "components": []}), \
                 patch("fitlab_foundation.planner_cli.run_document",
                       lambda document: None), \
                 patch.object(_RealPath, "is_file", lambda self: True):
                cli_module._publish_plan(_Args)
            body = (destination / "provenance.json").read_text("utf-8")
            self.assertNotIn("sampleuser", body)
            self.assertNotIn("admin@corp.invalid", body)
            self.assertNotIn("corp.invalid", body)
            self.assertIn("[redacted", body)
            plan_body = (destination / "plan.json").read_text("utf-8")
            self.assertNotIn("sampleuser", plan_body)
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
        # Scenario identities that redact to the same marker must not
        # collapse: replay re-validates the stored input with run_document,
        # which rejects duplicate scenario identities. An owner-supplied
        # literal marker-shaped id ("[redacted]#1") must survive unchanged
        # while generated tokens use a distinct namespaced shape
        # ("[redacted:k]") so a generated token can never collide with a
        # literal the owner actually shipped.
        import tempfile
        from unittest.mock import patch
        from fitlab_evaluation.run import evaluate
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.workflow import identity
        from test_f4_integration import FakeClient, GOOD_MEMORY

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        document_ids = ["[redacted]#1", "/data/private/a", "/data/private/b"]
        scenarios = []
        for sid in document_ids:
            scenario = json.loads(json.dumps(plan["scenarios"][0]))
            scenario["model"]["model_id"] = MODEL
            scenario["scenario_id"] = sid
            scenarios.append(scenario)
        document = {"direction": "workload_to_hardware",
                    "scenarios": scenarios,
                    "schema_version": plan.get("schema_version", 1)}
        trust = make_trust("HEAD")
        with patch("fitlab_evaluation.run.identity", return_value=trust["source_sha256"]):
            with tempfile.TemporaryDirectory() as tmp:
                record = evaluate(document, 1, client=FakeClient(),
                                  memory=lambda: dict(GOOD_MEMORY),
                                  pause=lambda _s: None, checkpoint=None)
        stored = record["planning_input"]
        ids = [s["scenario_id"] for s in stored["scenarios"]]
        self.assertEqual(len(ids), 3)
        # All three identities stay distinct after redaction.
        self.assertEqual(len(set(ids)), 3)
        # The unchanged literal marker-shaped id survives byte-exact.
        self.assertIn("[redacted]#1", ids)
        # Generated tokens are namespaced: never "#"-suffixed ordinals,
        # never equal to an owner-supplied literal.
        generated = [i for i in ids if i not in document_ids]
        self.assertEqual(len(generated), 2)
        for token in generated:
            self.assertTrue(token.startswith("[redacted:"), token)
            self.assertNotIn("#", token)
        # Replay: the sanitized input must still validate through the planner.
        from fitlab_foundation.planner_cli import run_document
        validated = run_document(stored)
        self.assertEqual(len(validated["results"]), 3)

    def test_private_detail_in_dictionary_keys_is_redacted(self):
        # Dictionary KEYS are owner-controlled content: an email or host
        # name used as a key must not survive into any publication component
        # (round-18 finding), and the publication scan must see keys too.
        from fitlab_evaluation.redact import redact_value, redact_structure, contains_private_detail
        payload = {
            "sampleuser@fitlab.invalid": "owner",
            "nested": {"host.redacted.invalid": {"deep": "value"}},
            "safe_key": "safe value",
        }
        result = redact_value(payload)
        joined = json.dumps(result)
        self.assertNotIn("sampleuser@fitlab.invalid", joined)
        self.assertNotIn("host.redacted.invalid", joined)
        self.assertFalse(contains_private_detail(joined))
        # Collapsing keys would lose data; distinct keys that redact to the
        # same marker are deterministically disambiguated.
        collapsing = {"/data/private/a": 1, "/data/private/b": 2}
        result2 = redact_value(collapsing)
        self.assertEqual(len(result2), 2)
        self.assertEqual(sorted(str(k) for k in result2),
                         ["[redacted]", "[redacted]:1"])
        # The redact_structure transform sees keys as well as values.
        seen = []
        redact_structure({"k": "v"}, lambda s: seen.append(s) or s)
        self.assertIn("k", seen)
        self.assertIn("v", seen)

    def test_generated_tokens_avoid_colliding_with_unchanged_literals(self):
        # An owner-supplied literal that ALREADY uses the generated-token
        # namespace ("[redacted:0]") must be pre-reserved: the allocator may
        # not hand the same token to a redacted id, or replay dies on a
        # duplicate identity.
        import tempfile
        from unittest.mock import patch
        from fitlab_evaluation.run import evaluate
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.workflow import identity
        from test_f4_integration import FakeClient, GOOD_MEMORY

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        document_ids = ["[redacted:0]", "/data/private/a"]
        scenarios = []
        for sid in document_ids:
            scenario = json.loads(json.dumps(plan["scenarios"][0]))
            scenario["model"]["model_id"] = MODEL
            scenario["scenario_id"] = sid
            scenarios.append(scenario)
        document = {"direction": "workload_to_hardware",
                    "scenarios": scenarios,
                    "schema_version": plan.get("schema_version", 1)}
        trust = make_trust("HEAD")
        with patch("fitlab_evaluation.run.identity", return_value=trust["source_sha256"]):
            with tempfile.TemporaryDirectory() as tmp:
                record = evaluate(document, 1, client=FakeClient(),
                                  memory=lambda: dict(GOOD_MEMORY),
                                  pause=lambda _s: None, checkpoint=None)
        stored = record["planning_input"]
        ids = [s["scenario_id"] for s in stored["scenarios"]]
        self.assertEqual(len(set(ids)), 2, ids)
        # The namespace-shaped literal survives byte-exact.
        self.assertIn("[redacted:0]", ids)
        # The redacted id received a DIFFERENT generated token.
        generated = [i for i in ids if i not in document_ids]
        self.assertEqual(len(generated), 1)
        self.assertNotEqual(generated[0], "[redacted:0]")
        # Replay still validates through the planner.
        from fitlab_foundation.planner_cli import run_document
        validated = run_document(stored)
        self.assertEqual(len(validated["results"]), 2)

    def test_standalone_plan_identities_survive_report_export(self):
        # A standalone plan exported to a passport bundle must keep distinct
        # scenario identities distinct (the exported planning input must
        # still replay), and its sanitized copy must match the report's own
        # planning input.
        import tempfile
        import copy as copy_module
        from fitlab_evaluation.report_v3 import export_report
        from fitlab_evaluation.evidence import make_trust

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        ids = ["/data/private/a", "/data/private/b"]
        scenarios = []
        for sid in ids:
            scenario = json.loads(json.dumps(plan["scenarios"][0]))
            scenario["scenario_id"] = sid
            scenarios.append(scenario)
        private_plan = {"direction": "workload_to_hardware",
                        "scenarios": scenarios,
                        "schema_version": plan.get("schema_version", 1)}
        trust = make_trust("HEAD")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "passport"
            export_report(out, trust, None, private_plan)
            body = (out / "planning-input.json").read_text("utf-8")
            self.assertNotIn("/data/private", body)
            stored = json.loads(body)
            stored_ids = [s["scenario_id"] for s in stored["scenarios"]]
            self.assertEqual(len(set(stored_ids)), 2, stored_ids)
            for token in stored_ids:
                self.assertTrue(token.startswith("[redacted:"), token)
            from fitlab_foundation.planner_cli import run_document
            validated = run_document(stored)
            self.assertEqual(len(validated["results"]), 2)
            # The report's embedded planning results carry the same
            # sanitized identities as the stored input.
            passport = json.loads((out / "passport.json").read_text("utf-8"))
            result_ids = sorted(r["scenario_id"] for r in passport["planning"]["results"])
            self.assertEqual(result_ids, sorted(stored_ids))

    def test_unsanitized_imported_record_is_refused_at_publication(self):
        # A record that verifies cryptographically but predates a redaction
        # rule must FAIL the export instead of reaching the shareable bundle
        # in raw form (publication-time privacy boundary).
        import tempfile
        import copy as copy_module
        from unittest.mock import patch
        from fitlab_evaluation.report_v3 import export_report
        from fitlab_evaluation.evidence import make_trust
        from fitlab_evaluation.artifacts import ArtifactError
        from fitlab_evaluation import run as run_module
        from fitlab_evaluation.run import evaluate
        from test_f4_integration import FakeClient, GOOD_MEMORY

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        plan["scenarios"][0]["model"]["model_id"] = MODEL
        plan["scenarios"][0]["workload"]["residency_assumption"] = (
            "legacy weights at /data/legacy/model.bin")
        trust = make_trust("HEAD")
        with patch("fitlab_evaluation.run.identity",
                   return_value=trust["source_sha256"]):
            record = evaluate(copy_module.deepcopy(plan), 1,
                              client=FakeClient(),
                              memory=lambda: dict(GOOD_MEMORY),
                              pause=lambda _s: None, checkpoint=None)
        # Simulate an imported record from an earlier sanitizer era: inject
        # a private marker into the stored planning input.
        record["planning_input"]["scenarios"][0]["workload"][
            "residency_assumption"] = "legacy weights at /data/legacy/model.bin"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "passport"
            with self.assertRaises(ArtifactError) as caught:
                export_report(out, trust, record=record)
            self.assertIn("EVALUATION_RECORD_NOT_SANITIZED",
                          str(caught.exception))
            self.assertFalse(out.exists())
        # The JSON-escaping evasion must not work either: a non-ASCII email
        # is scanned in its DECODED form, not its json.dumps escape form.
        record["planning_input"]["scenarios"][0]["workload"][
            "residency_assumption"] = "contact sampleuser@éxample.org now"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "passport"
            with self.assertRaises(ArtifactError):
                export_report(out, trust, record=record)
            self.assertFalse(out.exists())

    def test_host_identity_companion_is_redacted(self):
        # The host-identity companion satisfies the same privacy contract
        # as the rendered report.
        import tempfile
        from fitlab_evaluation.report_v3 import export_report
        from fitlab_evaluation.evidence import make_trust
        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        trust = make_trust("HEAD")
        host = {"operator_email": "owner@host.invalid",
                "work_dir": "C:\\Users\\sampleuser\\private"}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "passport"
            export_report(out, trust, None, plan, host=host)
            body = (out / "host-identity.json").read_text("utf-8")
            self.assertNotIn("owner@host.invalid", body)
            self.assertNotIn("sampleuser", body)
            self.assertIn("[redacted]", body)

    def test_planning_rederivation_failure_propagates(self):
        # The stored planning output must come from a verified re-derivation
        # against the stored input. A failing re-derivation must FAIL the
        # run; silently falling back to an unverifiable stored copy is
        # forbidden.
        import tempfile
        from unittest.mock import patch
        import fitlab_evaluation.run as run_module
        from fitlab_evaluation.run import evaluate
        from fitlab_evaluation.evidence import make_trust
        from test_f4_integration import FakeClient, GOOD_MEMORY

        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        plan["scenarios"][0]["model"]["model_id"] = MODEL
        real = run_module.run_document
        calls = {"n": 0}

        def flaky_rederivation(document):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("synthetic re-derivation failure")
            return real(document)

        with patch.object(run_module, "run_document", side_effect=flaky_rederivation):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    evaluate(plan, 1, client=FakeClient(),
                             memory=lambda: dict(GOOD_MEMORY),
                             pause=lambda _s: None, checkpoint=None)
        self.assertEqual(calls["n"], 2)


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
            # Planning inputs pass through the collision-safe allocator, so
            # generated markers carry the namespaced shape.
            self.assertIn("[redacted:", body)

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

    def test_task_only_run_guards_every_readiness_check(self):
        # Round-25 A-2: the task-only entry previously verified the offline
        # contract once and then created an unguarded client — a posture
        # change after the initial probe would not stop inference. The entry
        # must now wrap the adapter so every readiness check re-validates
        # BOTH the offline contract and the disabled-telemetry state, exactly
        # like workflow.execute's guarded_ready. A posture change mid-run
        # must produce a STOPPED record with zero additional inference.
        import tempfile
        import copy
        from unittest.mock import patch
        from fitlab_evaluation import run as run_mod
        from fitlab_evaluation import workflow as wf_mod
        from fitlab_evaluation.lemonade import validate_health, LemonadeClient
        from test_f4_integration import FakeClient, HEALTH
        plan = json.loads((ROOT / "examples" /
                           "f2_workload_to_hardware.json").read_text("utf-8"))
        from fitlab_evaluation.lemonade import MODEL
        plan["direction"] = "workload_to_hardware"
        plan["scenarios"][0]["model"]["model_id"] = MODEL
        offline = {"offline": True, "no_fetch_executables": True}
        telemetry_calls = {"n": 0}

        def telemetry_state(*_a, **_k):
            telemetry_calls["n"] += 1
            # First check (initial probe): valid health, telemetry explicitly
            # disabled.
            if telemetry_calls["n"] == 1:
                health = copy.deepcopy(HEALTH)
                health["telemetry"] = {"enabled": False}
                return validate_health(health)
            # Later checks (guarded re-checks inside evaluate): telemetry
            # has been re-enabled mid-run — the guard must stop the run. The
            # guard reads the raw dict, so no health validation here; the
            # shape still looks like a health response with telemetry on.
            health = copy.deepcopy(HEALTH)
            health["telemetry"] = {"enabled": True}
            return health

        calls = {"n": 0}

        def posture_change():
            calls["n"] += 1
            # First call (initial probe): contract proven offline.
            if calls["n"] == 1:
                return dict(offline)
            # Later calls (guarded re-checks inside evaluate): posture flip.
            return {"offline": False, "no_fetch_executables": True}

        # The entry constructs its own client; it must be a REAL
        # LemonadeClient (evaluate's LOCAL_RUNTIME type gate), so patch the
        # class with a counting subclass whose ready() replays the scripted
        # telemetry posture instead of touching a real runtime.
        class GuardedLemonade(LemonadeClient):
            def __init__(self):
                super().__init__()
                self.readies = 0

            def ready(self):
                self.readies += 1
                return telemetry_state()

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "campaign.json"
            with patch.object(wf_mod, "safe_runtime_config",
                              side_effect=posture_change), \
                 patch.object(run_mod, "windows_memory",
                              return_value=GOOD_MEMORY_FAKE()), \
                 patch.object(run_mod, "LemonadeClient", GuardedLemonade), \
                 patch.object(sys, "argv",
                              ["run.py", "--output", str(out), "--repeats", "1"]):
                code = run_mod.main()
            self.assertEqual(code, 2)
            record = json.loads(out.read_text("utf-8"))
            # The guarded readiness check must have stopped the run before
            # any row reached MEASURED, and the record is not COMPLETED.
            self.assertNotEqual(record.get("status"), "COMPLETED")
            measured = [r for r in record.get("rows", [])
                        if r.get("status") == "MEASURED"]
            self.assertEqual(len(measured), 0, measured)
            # The guard actually re-checked the contract after the probe:
            # safe_runtime_config was consulted at least twice (initial
            # probe + guarded re-check inside evaluate) before the run
            # stopped, and the stop reason records the guarded refusal.
            self.assertGreaterEqual(calls["n"], 2, calls)
            self.assertEqual(record.get("stop_reason"),
                             "runtime offline state changed")


def out_debug(code, text):
    return f"exit={code} out={text[:400]}"


if __name__ == "__main__":
    unittest.main()