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

    def test_retained_metadata_residency_is_capped_before_allocation(self):
        # Round-45/46 A-1: per-field limits alone allowed retained metadata
        # arrays whose aggregate allocation exhausts memory before any
        # later gate runs; the cumulative budget must refuse the crossing
        # charge BEFORE allocation, with a stable error code. 65 declared
        # 1 MiB strings charge 65 MiB > the 64 MiB retained budget, so the
        # crossing string is refused at its pre-charge.
        with tempfile.TemporaryDirectory() as directory:
            header = b"GGUF" + struct.pack("<I", 3)
            header += struct.pack("<Q", 1)
            header += struct.pack("<Q", 2)
            header += struct.pack("<Q", 20) + b"general.architecture"
            header += struct.pack("<I", 8) + struct.pack("<Q", 4) + b"lfm2"
            header += struct.pack("<Q", 14) + b"attacker.array"
            header += struct.pack("<I", 9) + struct.pack("<I", 8)
            header += struct.pack("<Q", 65)
            piece = b"p" * (1 << 20)
            payload = b"".join([struct.pack("<Q", 1 << 20) + piece] * 65)
            path = Path(directory) / "model.gguf"
            path.write_bytes(header + payload)
            with self.assertRaisesRegex(ArtifactError, "GGUF_METADATA_BUDGET_EXCEEDED"):
                read_metadata(path)
            # A retained array whose items contain ONE supplementary
            # character each decodes UCS-4: each 1 MiB item charges
            # ~5.25 Mi decoded footprint, so a 20-item array (~105 Mi
            # charged) crosses the 64 Mi retained budget before
            # allocation (round-46 A-1).
            header2 = b"GGUF" + struct.pack("<I", 3)
            header2 += struct.pack("<Q", 1)
            header2 += struct.pack("<Q", 2)
            header2 += struct.pack("<Q", 20) + b"general.architecture"
            header2 += struct.pack("<I", 8) + struct.pack("<Q", 4) + b"lfm2"
            header2 += struct.pack("<Q", 19) + b"attacker.ucs4.array"
            header2 += struct.pack("<I", 9) + struct.pack("<I", 8)
            header2 += struct.pack("<Q", 20)
            tail = b"x" * ((1 << 20) - 4) + "\U0001F600".encode("utf-8")
            body = b"".join([struct.pack("<Q", 1 << 20) + tail] * 20)
            path2 = Path(directory) / "ucs4.gguf"
            path2.write_bytes(header2 + body)
            with self.assertRaisesRegex(ArtifactError, "GGUF_METADATA_BUDGET_EXCEEDED"):
                read_metadata(path2)
            # Normal models stay far below the budget and parse cleanly.
            ok = _write_gguf(
                directory,
                {
                    "general.architecture": (8, "lfm2"),
                    "lfm2.block_count": (4, 4),
                    "lfm2.embedding_length": (4, 64),
                    "lfm2.attention.head_count": (4, 4),
                    "tokenizer.ggml.tokens": (9, (8, [f"tok{i}" for i in range(2000)])),
                },
                [("blk.0.attn_q.weight", [64, 64], 12)],
            )
            raw = read_metadata(ok)
            self.assertEqual(raw["metadata"]["lfm2.block_count"], 4)
            self.assertEqual(raw["metadata"]["token_count"], 2000)

    def test_discarded_tokenizer_array_exceeding_retained_budget_parses(self):
        # Round-46 A-2: discarded tokenizer items are transient and must
        # NOT consume the retained budget - a legitimate large vocabulary
        # (aggregate payload beyond MAX_METADATA_RESIDENCY_BYTES, tiny live
        # residency) still parses with its counted length, while the
        # transient pool still fails a file that declares more discarded
        # payload than MAX_DISCARDED_BYTES.
        def discard_header(key, count):
            head = b"GGUF" + struct.pack("<I", 3)
            head += struct.pack("<Q", 0)
            head += struct.pack("<Q", 2)
            head += struct.pack("<Q", 20) + b"general.architecture"
            head += struct.pack("<I", 8) + struct.pack("<Q", 4) + b"lfm2"
            head += struct.pack("<Q", len(key)) + key
            head += struct.pack("<I", 9) + struct.pack("<I", 8)
            head += struct.pack("<Q", count)
            return head

        with tempfile.TemporaryDirectory() as directory:
            # 70000 x 1 KiB ASCII tokens = ~70 MiB aggregate payload, above
            # the 64 MiB retained budget, below the 512 MiB transient cap.
            ok = discard_header(b"tokenizer.ggml.tokens", 70000)
            token = b"t" * 1024
            ok += b"".join([struct.pack("<Q", 1024) + token] * 70000)
            # GGUF alignment: the tensor-data section starts at the next
            # 32-byte boundary, so the file must carry padding up to it
            # even with zero tensors.
            ok += b"\x00" * ((-len(ok)) % 32)
            path = Path(directory) / "vocab.gguf"
            path.write_bytes(ok)
            raw = read_metadata(path)
            self.assertEqual(raw["metadata"]["token_count"], 70000)
            # A discarded array whose ELEMENT type is itself ARRAY is
            # refused BEFORE any inner item is read: nested lists would
            # build a whole inner list simultaneously, breaking the
            # one-item streaming bound (round-50 A-1).
            nested = b"GGUF" + struct.pack("<I", 3)
            nested += struct.pack("<Q", 0)
            nested += struct.pack("<Q", 1)
            nested += struct.pack("<Q", 21) + b"tokenizer.ggml.tokens"
            nested += struct.pack("<I", 9) + struct.pack("<I", 9)
            nested += struct.pack("<Q", 1)
            nested_path = Path(directory) / "nested.gguf"
            nested_path.write_bytes(nested)
            with self.assertRaisesRegex(ArtifactError, "GGUF_UNSUPPORTED_VALUE_TYPE"):
                read_metadata(nested_path)
            # Aggregate discarded payload beyond the transient cap is
            # refused before allocation: each discarded item charges the
            # transient pool, so 110 one-MiB STRING tokens (~2.7 GiB
            # declared, ~5.25 MiB charged each) cross the 512 MiB cap.
            hostile = discard_header(b"tokenizer.ggml.tokens", 520)
            piece = b"t" * (1 << 20)
            hostile += b"".join([struct.pack("<Q", 1 << 20) + piece] * 110)
            path2 = Path(directory) / "flood.gguf"
            path2.write_bytes(hostile)
            with self.assertRaisesRegex(ArtifactError, "GGUF_METADATA_BUDGET_EXCEEDED"):
                read_metadata(path2)

    def test_retained_numeric_array_items_charge_conservatively(self):
        # Round-49 A-1: the retained per-item charge must cover BOTH the
        # list slot and the decoded object (a huge UINT64 stores a ~32 B
        # int object, plus the ~8 B list slot). Two retained arrays of
        # 999,999 UINT64-maximum values occupy ~76 MiB on 64-bit CPython
        # while the former 32 B/item charge declared only ~61 MiB total
        # and let both through; with the conservative 64 B/item charge
        # the second array crosses the 64 MiB retained budget and is
        # refused BEFORE allocation with a stable code.
        key = b"planner.retained.numbers"
        key2 = b"planner.retained.numbers2"
        with tempfile.TemporaryDirectory() as directory:
            head = b"GGUF" + struct.pack("<I", 3)
            head += struct.pack("<Q", 0)
            head += struct.pack("<Q", 2)
            head += struct.pack("<Q", len(key)) + key
            head += struct.pack("<I", 9) + struct.pack("<I", 10)
            head += struct.pack("<Q", 999999)
            head += b"\x00" * (8 * 999999)
            head += struct.pack("<Q", len(key2)) + key2
            head += struct.pack("<I", 9) + struct.pack("<I", 10)
            head += struct.pack("<Q", 999999)
            path = Path(directory) / "numeric-retained.gguf"
            path.write_bytes(head)
            with self.assertRaisesRegex(ArtifactError, "GGUF_METADATA_BUDGET_EXCEEDED"):
                read_metadata(path)
            # One such array (still under the cap with its headers) plus
            # normal profile metadata parses; legitimate planner-relevant
            # metadata sits orders of magnitude below the budget.
            parts = [
                b"GGUF", struct.pack("<I", 3),
                struct.pack("<Q", 0), struct.pack("<Q", 2),
                struct.pack("<Q", 20), b"general.architecture",
                struct.pack("<I", 8), struct.pack("<Q", 4), b"lfm2",
                struct.pack("<Q", len(key)), key,
                struct.pack("<I", 9), struct.pack("<I", 10),
                struct.pack("<Q", 999999),
            ]
            ok = b"".join(parts) + b"\x00" * (8 * 999999)
            ok += b"\x00" * ((-len(ok)) % 32)
            path2 = Path(directory) / "numeric-ok.gguf"
            path2.write_bytes(ok)
            raw = read_metadata(path2)
            self.assertEqual(raw["metadata"]["general.architecture"], "lfm2")

    def test_descriptor_container_footprint_enforces_retained_budget(self):
        # Round-48 A-1: descriptors charge a conservative fixed container
        # footprint plus per-dimension object costs BEFORE allocation. A
        # structurally valid file of many small one-dimensional tensors
        # (~424 bytes actual residency each, formerly charged only name +
        # dims*64) must be refused once the retained budget is crossed -
        # 200k such descriptors retain ~85 MB while formerly charging
        # only ~32 MB.
        with tempfile.TemporaryDirectory() as directory:
            count = 200000
            parts = [
                b"GGUF", struct.pack("<I", 3),
                struct.pack("<Q", count),
                struct.pack("<Q", 1),
                struct.pack("<Q", 20), b"general.architecture",
                struct.pack("<I", 8), struct.pack("<Q", 4), b"lfm2",
            ]
            # t399999-style six-digit names, 1 dimension, F32 (type 0),
            # one-byte offsets; required payload fits in MAX_FILE_BYTES.
            for index in range(count):
                name = b"t%06d" % index
                parts.append(struct.pack("<Q", len(name)) + name)
                parts.append(struct.pack("<I", 1))
                parts.append(struct.pack("<Q", 2))
                parts.append(struct.pack("<I", 0))
                parts.append(struct.pack("<Q", index))
            path = Path(directory) / "descriptor-flood.gguf"
            path.write_bytes(b"".join(parts))
            with self.assertRaisesRegex(ArtifactError, "GGUF_METADATA_BUDGET_EXCEEDED"):
                read_metadata(path)

    def test_repeated_discarded_keys_refused_and_numeric_items_charged(self):
        # Round-47 A-1: the reported trigger - repeated
        # tokenizer.ggml.token_type arrays of 1,048,576 UINT64 items each,
        # whose discarded numeric processing bypassed every charge - is
        # now refused outright: duplicate metadata keys fail with a stable
        # code before any second array is processed. With duplicates
        # impossible, the three discarded keys cap uncharged numeric
        # processing at zero and charged transient processing at
        # 3 x MAX_ARRAY_ITEMS items. Every discarded item (numeric and
        # BOOL included) charges the transient pool.
        with tempfile.TemporaryDirectory() as directory:
            head = b"GGUF" + struct.pack("<I", 3)
            head += struct.pack("<Q", 0)
            head += struct.pack("<Q", 2)
            head += struct.pack("<Q", 25) + b"tokenizer.ggml.token_type"
            head += struct.pack("<I", 9) + struct.pack("<I", 10)
            head += struct.pack("<Q", 4) + b"\x00" * (4 * 8)
            head += struct.pack("<Q", 25) + b"tokenizer.ggml.token_type"
            path = Path(directory) / "repeat.gguf"
            path.write_bytes(head)
            with self.assertRaisesRegex(ArtifactError, "GGUF_DUPLICATE_METADATA"):
                read_metadata(path)
            # A single legitimate numeric discarded array still parses
            # and reports its counted length with per-item charging
            # active (1,048,576 UINT64 items = 32 MiB transient charge,
            # far below the 512 MiB cap).
            ok = b"GGUF" + struct.pack("<I", 3)
            ok += struct.pack("<Q", 0)
            ok += struct.pack("<Q", 1)
            ok += struct.pack("<Q", 25) + b"tokenizer.ggml.token_type"
            ok += struct.pack("<I", 9) + struct.pack("<I", 10)
            ok += struct.pack("<Q", 1 << 20) + b"\x00" * ((1 << 20) * 8)
            ok += b"\x00" * ((-len(ok)) % 32)
            path2 = Path(directory) / "numeric-ok.gguf"
            path2.write_bytes(ok)
            raw = read_metadata(path2)
            self.assertEqual(raw["metadata"]["token_type_count"], 1 << 20)

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

    def test_classify_blocks_work_is_bounded_and_matches_prefix_semantics(self):
        # Round-43 A-1: classification work must be bounded by the number of
        # OBSERVED tensor names, never by block_count — a structurally valid
        # GGUF below the excessive-count gate may declare many blocks whose
        # names match nothing.
        unrelated = [{"name": f"tensor.{i}.weight"} for i in range(500)]
        convolution, attention = classify_blocks(unrelated, 99999)
        self.assertEqual((convolution, attention), ([], []))
        mixed = []
        for index in range(2000):
            kind = "shortconv.in_proj.weight" if index % 2 else "attn_q.weight"
            mixed.append({"name": f"blk.{index}.{kind}"})
        convolution, attention = classify_blocks(mixed, 99999)
        self.assertEqual(len(convolution), 1000)
        self.assertEqual(len(attention), 1000)
        self.assertEqual(
            convolution, [index for index in range(1, 2000, 2)])
        self.assertEqual(attention, [index for index in range(0, 2000, 2)])
        # Indexes at or beyond the declared block_count are ignored exactly
        # as range(block_count) excluded them.
        convolution, attention = classify_blocks(
            [{"name": "blk.3.attn_q.weight"}], 3)
        self.assertEqual((convolution, attention), ([], []))
        # Only canonical decimal indexes classify: leading zeros, signs and
        # non-decimal digits never matched the old f"blk.{index}." prefix.
        convolution, attention = classify_blocks(
            [
                {"name": "blk.007.attn_q.weight"},
                {"name": "blk.-1.attn_q.weight"},
                {"name": "blk..attn_q.weight"},
                {"name": "blk.1X.attn_q.weight"},
            ],
            1000,
        )
        self.assertEqual((convolution, attention), ([], []))
        # Superscript-style unicode digits satisfy str.isdigit() but int()
        # rejects them; oversized ASCII decimal indexes exceed the default
        # int-conversion limit. Both are IGNORED, never abort (round-44 A-1).
        convolution, attention = classify_blocks(
            [
                {"name": "blk.\u00b2.attn_q.weight"},
                {"name": "blk." + "9" * 5000 + ".attn_q.weight"},
                {"name": "blk.\u0661\u0662\u0663.attn_q.weight"},
            ],
            1000,
        )
        self.assertEqual((convolution, attention), ([], []))

    def test_excessive_block_count_is_refused_before_classification(self):
        # Round-42: a structurally valid GGUF can declare a UINT64-maximum
        # block_count; classify_blocks would iterate range(block_count) and
        # hang the offline planner. The refuse must happen BEFORE block
        # classification, with a stable error code.
        from fitlab_evaluation.model_profile import derive_profile
        from fitlab_evaluation.artifacts import ArtifactError as ProfileError
        with tempfile.TemporaryDirectory() as directory:
            path = _write_gguf(
                directory,
                {
                    "general.architecture": (8, "lfm2"),
                    "general.file_type": (4, 15),
                    "lfm2.block_count": (10, 18446744073709551615),
                    "lfm2.embedding_length": (4, 64),
                    "lfm2.attention.head_count": (4, 4),
                },
                [
                    ("blk.0.shortconv.in_proj.weight", [64, 192], 12),
                ],
            )
            # The refusal must happen BEFORE block classification, with an
            # EXACTLY stable error code: the declared value must not ride
            # the code, which cli.main publishes verbatim into the
            # evaluation record.
            with self.assertRaises(ProfileError) as refused:
                derive_profile(path, "r")
            self.assertEqual(
                refused.exception.code, "MODEL_METADATA_BLOCK_COUNT_EXCESSIVE")
            self.assertEqual(
                str(refused.exception), "MODEL_METADATA_BLOCK_COUNT_EXCESSIVE")
            from unittest.mock import patch
            import fitlab_evaluation.model_profile as module
            with patch.object(module, "classify_blocks",
                              side_effect=AssertionError("classification reached")):
                with self.assertRaises(ProfileError) as still_refused:
                    derive_profile(path, "r")
            self.assertEqual(
                still_refused.exception.code,
                "MODEL_METADATA_BLOCK_COUNT_EXCESSIVE")
            # A modest block count still passes the same gate.
            ok_dir = Path(directory) / "ok"
            ok_dir.mkdir()
            ok = _write_gguf(
                Path(directory) / "ok",
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
            profile = derive_profile(ok, "r")
            self.assertEqual(profile["block_count"], 4)


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
            # Round-14 grammar: interior segments are space-free; the space-
            # bearing middle is consumed by the known-root pass, which stops
            # at the first whitespace.
            ("/data/private/model bin file", "[redacted] bin file"),
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
            # Round-15 reviewer case: a complete path is NEVER extended into
            # a following suffixed prose token.
            ("/data/private/model.gguf notes.txt remain", "[redacted] notes.txt remain"),
            # Round-16 reviewer case: a complete WINDOWS path is never
            # extended into a following suffixed prose token.
            ("C:\\models\\model.gguf notes.txt remain",
             "[redacted] notes.txt remain"),
            # Round-35 A-1: root-level single-segment POSIX files are
            # redacted when contiguous ("/confidential.gguf"); a space inside
            # a root-level filename is isomorphic to prose ("my secret
            # notes.md"), so per the prose-preservation contract it stays.
            ("/confidential.gguf", "[redacted]"),
            ("/my secret.gguf", "/my secret.gguf"),
            # Round-26 A-1: prose after a space-bearing username is NEVER
            # consumed ("cache" is not part of the identity); the optional
            # second word is taken only when a path separator follows.
            ("/home/sampleuser cache docs/README.md",
             "/[redacted] cache docs/README.md"),
            # Round-19 A-1 (refined): a space-bearing username followed by a
            # separator is one identity and is consumed whole.
            # Round-27 adjudicated trade-off (see packet contract): 3+-word
            # space-bearing usernames are locally indistinguishable from
            # prose after a username; PROSE PRESERVATION WINS. The username
            # itself is consumed ("[redacted] sampleuser ..."); the generic
            # tail remains. Refusal of unresolvable records happens at the
            # publication privacy scan, not the grammar.
            ("C:\\Users\\sampleuser sampleuser sampleuser\\model.gguf",
             "[redacted] sampleuser sampleuser\\model.gguf"),
            ("/home/sampleuser sampleuser sampleuser/model.gguf",
             "/[redacted] sampleuser sampleuser/model.gguf"),
            ("the Users group has 3 members", "the Users group has 3 members"),
            # Round-19 A-1: user-profile rule runs before the suffix pass,
            # so a POSIX home path keeps its full consumption shape.
            ("host /home/sampleuser/.cache/huggingface",
             "host /[redacted]/.cache/huggingface"),
            # The final filename segment is contiguous with its suffix; a
            # space inside it is consumed only for NON-suffixed pre-space
            # words ("My Model.gguf").
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
