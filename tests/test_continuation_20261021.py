"""Offline adversarial and regression checks for the 2026-10-21 continuation.

These tests cover defects found and corrected during the offline ship-preparation
continuation. They use no model, no runtime and no network. Every test is
bounded and deterministic.

Covered here:

* source binding must survive a CRLF working tree (the defect that made the
  F5 workflow refuse to start on a fresh Windows checkout);
* GGUF header parsing must be bounded, strict and must not read weights;
* the hybrid short-convolution architecture must be declared truthfully and
  must not produce a standard full-attention KV number;
* private detail must not survive into report-bound text;
* task tier classification must preserve the six core cases and must not
  weaken any frozen grading criterion;
* the Passport must not manufacture a measurement.
"""

import copy
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from fitlab_evaluation.artifacts import (
    ArtifactError,
    canonical_source_bytes,
    source_digest,
    stable_json,
)
from fitlab_evaluation.evidence import make_trust, validate_trust
from fitlab_evaluation.gguf_meta import read_metadata, summarize
from fitlab_evaluation.grader import load_pack
from fitlab_evaluation.model_profile import (
    ARCHITECTURE_UNSUPPORTED,
    ATTENTION_UNSUPPORTED,
    classify_blocks,
    derive_profile,
)
from fitlab_evaluation.plan_builder import build_plan, memory_advisory
from fitlab_evaluation.redact import contains_private_detail, redact_text, redact_value
from fitlab_evaluation.run import identity

ROOT = Path(__file__).resolve().parents[1]


class SourceBindingTests(unittest.TestCase):
    """The F5 workflow binds git blob bytes to working-tree bytes."""

    def setUp(self):
        # A source archive has no .git directory, so there is no object
        # database to bind against. The binding itself is verified in the
        # repository; here we verify the canonical-digest property, which
        # holds in both environments.
        self.has_git = (ROOT / ".git").exists()
        if not self.has_git:
            self.skipTest("portable archive: no local Git object database")

    def test_canonical_form_ignores_only_line_endings(self):
        self.assertEqual(canonical_source_bytes(b"a\r\nb\r\n"), b"a\nb\n")
        self.assertEqual(canonical_source_bytes(b"a\nb\n"), b"a\nb\n")
        # A real content change must still change the digest.
        self.assertNotEqual(source_digest(b"a\r\nb"), source_digest(b"a\r\nc"))
        # A lone CR is not a line ending this project normalises.
        self.assertEqual(canonical_source_bytes(b"a\rb"), b"a\rb")

    def test_worktree_identity_matches_git_trust_on_this_checkout(self):
        # A CRLF working tree must still satisfy the source binding.
        trust = make_trust("HEAD")
        validate_trust(trust)
        # Untracked files legitimately make the tree dirty; the workflow refuses
        # a dirty tree on purpose. Compare only the committed source set.
        committed = trust["source_sha256"]
        current = identity()
        for path, expected in committed.items():
            with self.subTest(path=path):
                self.assertIn(path, current)
                self.assertEqual(current[path], expected)

    def test_crlf_worktree_digest_equals_git_blob_digest(self):
        """The exact defect: a CRLF checkout must match its LF blob."""
        import subprocess

        path = "fitlab_evaluation/grader.py"
        blob = subprocess.check_output(["git", "show", "HEAD:" + path])
        worktree = (ROOT / path).read_bytes()
        self.assertEqual(source_digest(blob), source_digest(worktree))
        # And the two differ at the byte level whenever the worktree is CRLF,
        # which is precisely why the raw digests must not be compared.
        self.assertEqual(canonical_source_bytes(blob), canonical_source_bytes(worktree))

    def test_identity_uses_forward_slash_relative_paths(self):
        for path in identity():
            self.assertNotIn("\\", path)
            self.assertFalse(path.startswith("/"))
            self.assertNotIn("..", path.split("/"))


def _write_gguf(directory, metadata, tensors, version=3, include_tensor_data=True):
    """Build a minimal but structurally valid GGUF file for parser tests."""

    def encode_string(text):
        raw = text.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    def encode_value(value_type, value):
        if value_type == 8:  # STRING
            return encode_string(value)
        if value_type == 9:  # ARRAY
            element_type, items = value
            out = struct.pack("<I", element_type) + struct.pack("<Q", len(items))
            for item in items:
                out += encode_value(element_type, item)
            return out
        if value_type == 4:  # UINT32
            return struct.pack("<I", value)
        if value_type == 10:  # UINT64
            return struct.pack("<Q", value)
        if value_type == 6:  # FLOAT32
            return struct.pack("<f", value)
        if value_type == 7:  # BOOL
            return struct.pack("<B", 1 if value else 0)
        raise AssertionError("unsupported test value type")

    out = b"GGUF" + struct.pack("<I", version)
    out += struct.pack("<Q", len(tensors))
    out += struct.pack("<Q", len(metadata))
    for key, (value_type, value) in metadata.items():
        out += encode_string(key) + struct.pack("<I", value_type) + encode_value(value_type, value)
    for name, shape, ggml_type in tensors:
        out += encode_string(name)
        out += struct.pack("<I", len(shape))
        for dimension in shape:
            out += struct.pack("<Q", dimension)
        out += struct.pack("<I", ggml_type)
        out += struct.pack("<Q", 0)
    if tensors and include_tensor_data:
        out += b"\x00" * ((32 - len(out) % 32) % 32)
        _, shape, ggml_type = tensors[0]
        elements = 1
        for dimension in shape:
            elements *= dimension
        block, size = {0: (1, 4), 12: (256, 144)}[ggml_type]
        out += b"\x00" * (((elements + block - 1) // block) * size)
    path = Path(directory) / "model.gguf"
    path.write_bytes(out)
    return path


class GgufParserTests(unittest.TestCase):
    """The reader must be strict, bounded and must never read weights."""

    def test_rejects_non_gguf_and_truncated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.gguf"
            for payload in (b"NOPE" + b"\x00" * 32, b"GGUF", b"", b"\xff" * 64):
                bad.write_bytes(payload)
                with self.assertRaises(ArtifactError):
                    read_metadata(bad)

    def test_rejects_unsupported_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(directory, {}, [], version=1)
            with self.assertRaisesRegex(ArtifactError, "GGUF_UNSUPPORTED_VERSION"):
                read_metadata(path)

    def test_reads_metadata_and_tensors_without_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(
                directory,
                {
                    "general.architecture": (8, "lfm2"),
                    "general.file_type": (4, 15),
                    "lfm2.block_count": (4, 4),
                    "lfm2.embedding_length": (4, 64),
                    "lfm2.attention.head_count": (4, 4),
                },
                [("blk.0.attn_q.weight", [64, 64], 12)],
            )
            raw = read_metadata(path)
            self.assertEqual(raw["metadata"]["lfm2.block_count"], 4)
            self.assertEqual(raw["tensors"][0]["elements"], 64 * 64)
            self.assertEqual(raw["tensors"][0]["name"], "blk.0.attn_q.weight")
            summary = summarize(path)
            self.assertEqual(summary["quantization"], "Q4_K_M")
            self.assertEqual(summary["architecture"], "lfm2")

    def test_rejects_tensor_offset_beyond_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(directory, {}, [("weight", [8], 0)], include_tensor_data=False)
            payload = bytearray(path.read_bytes())
            payload[-8:] = struct.pack("<Q", 1 << 40)
            path.write_bytes(payload)
            with self.assertRaisesRegex(ArtifactError, "GGUF_TENSOR_OFFSET_OUT_OF_RANGE"):
                read_metadata(path)

    def test_rejects_missing_tensor_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(directory, {}, [("weight", [8], 0)], include_tensor_data=False)
            with self.assertRaisesRegex(ArtifactError, "GGUF_TRUNCATED_TENSOR_DATA"):
                read_metadata(path)

    def test_oversized_declarations_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            # A string length far beyond any real metadata value.
            path = Path(directory) / "huge.gguf"
            path.write_bytes(
                b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 1)
                + struct.pack("<Q", 1) + b"k" + struct.pack("<I", 8)
                + struct.pack("<Q", 1 << 40)
            )
            with self.assertRaises(ArtifactError):
                read_metadata(path)

    def test_missing_file_is_a_stable_error(self):
        with self.assertRaisesRegex(ArtifactError, "GGUF_UNAVAILABLE"):
            read_metadata(Path("no-such-model.gguf"))


class HybridArchitectureTests(unittest.TestCase):
    """A hybrid short-convolution model must be declared truthfully."""

    def test_classify_blocks_separates_convolution_and_attention(self):
        tensors = [
            {"name": "blk.0.shortconv.in_proj.weight"},
            {"name": "blk.1.shortconv.in_proj.weight"},
            {"name": "blk.2.attn_q.weight"},
            {"name": "blk.3.attn_q.weight"},
        ]
        convolution, attention = classify_blocks(tensors, 4)
        self.assertEqual(convolution, [0, 1])
        self.assertEqual(attention, [2, 3])

    def test_hybrid_profile_is_unsupported_not_silently_dense(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(
                directory,
                {
                    "general.architecture": (8, "lfm2"),
                    "general.file_type": (4, 15),
                    "lfm2.block_count": (4, 4),
                    "lfm2.embedding_length": (4, 64),
                    "lfm2.attention.head_count": (4, 4),
                    "lfm2.attention.head_count_kv": (9, (4, [0, 0, 2, 0])),
                    "lfm2.shortconv.l_cache": (4, 3),
                },
                [
                    ("blk.0.shortconv.in_proj.weight", [64, 192], 12),
                    ("blk.1.shortconv.in_proj.weight", [64, 192], 12),
                    ("blk.2.attn_q.weight", [64, 64], 12),
                    ("blk.3.attn_q.weight", [64, 64], 12),
                ],
            )
            profile = derive_profile(path, "revision-under-test")
            self.assertTrue(profile["hybrid"])
            self.assertEqual(profile["architecture_kind"], ARCHITECTURE_UNSUPPORTED)
            self.assertEqual(profile["attention_mechanism"], ATTENTION_UNSUPPORTED)
            self.assertEqual(profile["convolution_block_count"], 2)
            self.assertEqual(profile["attention_block_count"], 2)
            self.assertEqual(profile["kv_heads"], 2)

    def test_hybrid_plan_must_not_yield_a_kv_number(self):
        """The engine must return UNKNOWN, not a wrong cache size."""
        from fitlab_foundation.planner_cli import run_document
        from fitlab_foundation.serialization import to_primitive

        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(
                directory,
                {
                    "general.architecture": (8, "lfm2"),
                    "general.file_type": (4, 15),
                    "lfm2.block_count": (4, 4),
                    "lfm2.embedding_length": (4, 64),
                    "lfm2.attention.head_count": (4, 4),
                    "lfm2.attention.head_count_kv": (9, (4, [0, 0, 2, 0])),
                    "lfm2.shortconv.l_cache": (4, 3),
                },
                [
                    ("blk.0.shortconv.in_proj.weight", [64, 192], 12),
                    ("blk.1.shortconv.in_proj.weight", [64, 192], 12),
                    ("blk.2.attn_q.weight", [64, 64], 12),
                    ("blk.3.attn_q.weight", [64, 64], 12),
                ],
            )
            document = build_plan("workload_to_hardware", model_path=path, revision="r")
            result = to_primitive(run_document(document))["results"][0]
            requirements = result["requirements"]
            self.assertEqual(requirements["kv_cache"]["status"], "UNKNOWN")
            self.assertEqual(requirements["known_memory_baseline"]["status"], "UNKNOWN")
            # The weight payload is still a valid declared estimate.
            self.assertEqual(requirements["idealized_weight_payload"]["status"], "ESTIMATED")

    def test_advisory_labels_every_component_and_keeps_engine_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(
                directory,
                {
                    "general.architecture": (8, "lfm2"),
                    "general.file_type": (4, 15),
                    "lfm2.block_count": (4, 4),
                    "lfm2.embedding_length": (4, 64),
                    "lfm2.attention.head_count": (4, 4),
                    "lfm2.attention.head_count_kv": (9, (4, [0, 0, 2, 0])),
                    "lfm2.shortconv.l_cache": (4, 3),
                },
                [
                    ("blk.0.shortconv.in_proj.weight", [64, 192], 12),
                    ("blk.1.shortconv.in_proj.weight", [64, 192], 12),
                    ("blk.2.attn_q.weight", [64, 64], 12),
                    ("blk.3.attn_q.weight", [64, 64], 12),
                ],
            )
            profile = derive_profile(path, "r")
            advisory = memory_advisory(profile, build_plan.__globals__["DEFAULT_WORKLOAD"])
            self.assertEqual(advisory["engine_result"], "UNKNOWN")
            names = {component["component"] for component in advisory["components"]}
            self.assertIn("idealized_weight_payload_bytes", names)
            self.assertIn("shortconv_state_bytes", names)
            for component in advisory["components"]:
                self.assertIn(component["evidence"], ("ESTIMATED", "CALCULATED", "DECLARED"))
                self.assertTrue(component["basis"])
                self.assertTrue(component["limitation"])
            # The total must equal the sum of its disclosed components.
            self.assertEqual(
                advisory["bytes"], sum(c["bytes"] for c in advisory["components"])
            )


class RedactionTests(unittest.TestCase):
    """Private detail must not survive into a shareable report."""

    def test_removes_paths_users_emails_and_network_detail(self):
        cases = [
            "Model at C:\\Users\\sampleuser\\models\\LFM.gguf",
            "Path C:/Users/sampleuser/AppData/Local/lemonade",
            "host /home/sampleuser/.cache/huggingface",
            "mail researcher@fitlab.invalid",
            "server 192.168.1.44:13305 running",
            "mac 00:1A:2B:3C:4D:5E",
            "\\\\FILESRV\\share\\model.gguf",
            "Users/sampleuser/Documents",
        ]
        for value in cases:
            with self.subTest(value=value):
                result = redact_text(value)
                self.assertNotIn("sampleuser", result)
                self.assertFalse(contains_private_detail(result))

    def test_redacts_paths_with_spaces_and_reserved_internal_hostnames(self):
        value = "loaded from C:\\Users\\sampleuser\\Redacted Project\\model.gguf on host.redacted.invalid"
        result = redact_text(value)
        # sampleuser must never leak in any form; the suffix-anchored path
        # grammar is space-free by design, so the space-bearing directory is
        # covered by the Windows user-profile rule and the drive rule.
        self.assertNotIn("sampleuser", result)
        self.assertNotIn("Redacted Project", result)
        self.assertNotIn("host.redacted.invalid", result)
        self.assertFalse(contains_private_detail(result))

    def test_posix_two_pass_grammar_discriminating_cases(self):
        # Regression for the round-10 correction: the suffix-anchored lazy
        # grammar runs first (space-bearing paths consumed whole), then the
        # known-root grammar with a proper root word boundary. Both prior
        # failure shapes must be impossible: prose after a path must survive
        # AND bare slash-prefixed words ("/optional") must survive.
        cases = [
            # (input, exact expected output)
            ("/data/private/alpha", "[redacted]"),
            ("/data/private/model bin file", "[redacted] bin file"),
            ("see /etc/config for details", "see [redacted] for details"),
            ("path /srv/deploy tool", "path [redacted] tool"),
            ("/opt/cache/model.gguf with notes", "[redacted] with notes"),
            # Round-14 DECLARED TRADE-OFF: interior segments are space-free,
            # so a space-bearing interior segment under a known root is cut
            # at the whitespace by the conservative known-root pass. The tail
            # fragment ("Drive/model.gguf") is a generic directory/file name,
            # not a private identifier; the alternative (space-joined
            # interior runs) provably consumes prose ("cache then consult
            # docs/README.md") and was rejected three review rounds running.
            # Usernames and hosts stay fully covered by their own rules.
            ("/Volumes/Backup Drive/model.gguf", "[redacted] Drive/model.gguf"),
            # Prose must never be eaten after a space-bearing path.
            ("/data/private/model bin file and more prose", "[redacted] bin file and more prose"),
            # Round-14 grammar: interior segments are space-free; the space-
            # bearing middle is consumed by the known-root pass, which stops
            # at the first whitespace.
            ("/Volumes/Drive/models and files/model.gguf kept prose",
             "[redacted] and files/model.gguf kept prose"),
            # Overmatch guards: slash-prefixed prose must survive.
            ("/optional feature flag remains enabled",
             "/optional feature flag remains enabled"),
            ("/option for verbose output", "/option for verbose output"),
            ("/etcetera and /ethanol stay prose", "/etcetera and /ethanol stay prose"),
            # Round-11 reviewer cases: a distant filename in prose must never
            # extend a path match across the sentence.
            ("/tmp/cache contains results described in README.md",
             "[redacted] contains results described in README.md"),
            ("/optional means consult README.md",
             "/optional means consult README.md"),
            # Round-12 reviewer cases: a distant slash-anchored filename
            # ("docs/README.md") must not be consumed through a space-joined
            # interior run either.
            ("/data/private/model.gguf then consult docs/README.md",
             "[redacted] then consult docs/README.md"),
            ("/optional mode consult docs/README.md",
             "/optional mode consult docs/README.md"),
            ("/data/private/cache docs/README.md", "[redacted] docs/README.md"),
            ("/data/private/My Model.gguf", "[redacted]"),
            # Round-13 reviewer case: even an extensionless path must not
            # span trailing prose to reach a distant slash-tail.
            ("/data/private/cache then consult docs/README.md",
             "[redacted] then consult docs/README.md"),
            # Round-14 grammar: interior segments are space-free; space-
            # bearing SEGMENTS under known roots are consumed whole by the
            # suffix pass's single-space tail only, otherwise by the
            # conservative known-root pass (which stops at whitespace).
            ("/data/private/model bin file", "[redacted] bin file"),
            ("/data/private/my model.gguf", "[redacted]"),
            # Drive-path prefix redacts conservatively; prose after it
            # survives (the old grammar consumed the whole sentence).
            ("C:\\tmp folder holds notes about readme.md",
             "[redacted] folder holds notes about readme.md"),
            # The original-frozen space-bearing Windows path: "Redacted
            # Project" is covered by the Windows user-profile rule plus the
            # drive rule; the private content never leaks.
            # Round-14 DECLARED TRADE-OFF (see /Volumes/Backup Drive case):
            # "Redacted Project" is space-bearing; the user-profile rule
            # removes the identity ("sampleuser"), the drive rule removes
            # the root, and the generic tail ("Project\model.gguf") remains.
            ("loaded from C:\\Users\\sampleuser\\Redacted Project\\model.gguf today",
             "loaded from [redacted] Project\\model.gguf today"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                result = redact_text(value)
                self.assertEqual(result, expected)
                self.assertFalse(contains_private_detail(result))

    def test_preserves_scientific_and_product_identifiers(self):
        for value in (
            "formula fitlab.kv.standard_full_cache v1.0.0",
            "model LFM2.5-1.2B-Instruct-GGUF quantized Q4_K_M",
            "llamacpp backend with gguf weights",
            "checkpoint LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
        ):
            with self.subTest(value=value):
                result = redact_text(value)
                self.assertEqual(result, value)
                self.assertFalse(contains_private_detail(result))

    def test_redacts_nested_structures(self):
        payload = {
            "label": "host at C:\\Users\\sampleuser\\x",
            "items": ["mail x@y.invalid", {"deep": "/home/sampleuser/y"}],
            "number": 7,
            "flag": True,
            "none": None,
        }
        result = redact_value(payload)
        self.assertNotIn("sampleuser", json.dumps(result))
        self.assertNotIn("x@y.invalid", json.dumps(result))
        self.assertEqual(result["number"], 7)
        self.assertIs(result["flag"], True)
        self.assertIsNone(result["none"])

    def test_non_string_values_pass_through_unchanged(self):
        self.assertEqual(redact_text(5), 5)
        self.assertIsNone(redact_text(None))


class TaskTierTests(unittest.TestCase):
    """The six core cases must be preserved and classified, never dropped."""

    def setUp(self):
        self.tiers = json.loads((ROOT / "fixtures/task-tiers.json").read_text())
        self.pack, _ = load_pack(ROOT / "fixtures/tasks-v2.json")

    def test_tier_files_cover_every_case_exactly_once(self):
        core = self.tiers["tiers"]["core"]["case_ids"]
        supplemental = self.tiers["tiers"]["supplemental"]["case_ids"]
        self.assertEqual(sorted(core + supplemental), sorted(c["id"] for c in self.pack["cases"]))
        self.assertEqual(len(core) + len(supplemental), len(self.pack["cases"]))
        self.assertEqual(len(set(core) & set(supplemental)), 0)

    def test_core_is_six_cases_with_eighteen_required_observations(self):
        core = self.tiers["tiers"]["core"]
        self.assertEqual(len(core["case_ids"]), 6)
        self.assertEqual(core["required_observations"], 18)
        self.assertEqual(self.tiers["denominator_policy"]["core_denominator"], 18)
        self.assertEqual(self.tiers["denominator_policy"]["total_planned_denominator"], 24)

    def test_core_cases_are_the_unchanged_feasibility_six(self):
        self.assertEqual(
            self.tiers["tiers"]["core"]["case_ids"], ["E1", "E2", "E3", "D1", "D2", "D3"]
        )

    def test_grading_criteria_are_identical_across_tiers(self):
        self.assertTrue(self.tiers["grading"]["identical_across_tiers"])
        # The classified pack must still carry the frozen pass rules.
        for case in self.pack["cases"]:
            self.assertTrue(case["pass_rule"])
            self.assertIn("expected", case)

    def test_tier_classification_grants_no_approval(self):
        self.assertIn("PROPOSED_CLASSIFICATION", self.tiers["provenance"]["approval_status"])


if __name__ == "__main__":
    unittest.main()
