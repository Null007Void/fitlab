"""Bounded, read-only GGUF metadata reader.

Reads only the header, key/value metadata block and tensor descriptors of a
GGUF file. Model weights are never read, never loaded and never executed.
This module performs no inference and starts no runtime.

Every read is length-bounded so a corrupt or hostile file cannot exhaust
memory. Failures raise :class:`ArtifactError` with a stable machine code.
"""

import struct
from pathlib import Path

from .artifacts import ArtifactError

MAGIC = b"GGUF"
MAX_FILE_BYTES = 64 * 1024 * 1024 * 1024
MAX_KV_PAIRS = 4096
MAX_TENSORS = 200000
MAX_STRING_BYTES = 1 << 20
MAX_ARRAY_ITEMS = 1 << 20
MAX_TENSOR_DIMS = 8
MAX_QUANTIZATION_NAME = 64

# Cumulative retained-residency budget for everything the parser builds
# (metadata strings, array items and tensor descriptors). Per-field limits
# alone permit hostile combinations - e.g. thousands of 1 MiB retained
# strings - whose aggregate allocation exhausts memory before any later
# gate runs (round-45 A-1). Every component is charged BEFORE it is
# allocated: strings from their declared byte length, scalar array items
# and descriptor dimensions at fixed footprints. 64 MiB is roughly three
# orders of magnitude above the largest metadata any planner-relevant
# model carries (vocab arrays are counted but discarded) and caps the
# former multi-gigabyte exposure.
MAX_METADATA_RESIDENCY_BYTES = 64 * 1024 * 1024
_SCALAR_ITEM_RESIDENCY_BYTES = 32
_DESCRIPTOR_DIMENSION_RESIDENCY_BYTES = 64

# GGUF value type identifiers.
UINT8, INT8, UINT16, INT16, UINT32, INT32, FLOAT32, BOOL, STRING, ARRAY, UINT64, INT64, FLOAT64 = range(13)

_SCALAR_FORMATS = {
    UINT8: ("<B", 1),
    INT8: ("<b", 1),
    UINT16: ("<H", 2),
    INT16: ("<h", 2),
    UINT32: ("<I", 4),
    INT32: ("<i", 4),
    FLOAT32: ("<f", 4),
    UINT64: ("<Q", 8),
    INT64: ("<q", 8),
    FLOAT64: ("<d", 8),
}

# GGML file/quantization identifiers used by the local model. Only the
# identifiers that can be named without guessing are listed; anything else
# is reported by numeric identifier and never translated.
FILE_TYPES = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    7: "Q8_0",
    8: "Q5_0",
    9: "Q5_1",
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    19: "IQ2_XXS",
    20: "IQ2_XS",
    21: "IQ3_XXS",
    22: "IQ1_S",
    23: "IQ4_NL",
    24: "IQ3_S",
    25: "IQ2_S",
    26: "IQ4_XS",
    27: "IQ1_M",
    28: "BF16",
    30: "TQ1_0",
    31: "TQ2_0",
}

# Idealized uniform weight widths the F1 requirements engine accepts.
SUPPORTED_IDEALIZED_BITS = ("1", "2", "3", "4", "5", "6", "8", "16", "32")

# Tensor-name fragments that identify mixture-of-experts parameter blocks.
_EXPERT_MARKERS = ("ffn_gate_exps", "ffn_down_exps", "ffn_up_exps", "expert")

# GGML tensor block layout: type id -> (elements per block, bytes per block).
# A descriptor is not structurally complete unless its declared payload fits.
_GGML_LAYOUTS = {
    0: (1, 4), 1: (1, 2), 2: (32, 18), 3: (32, 20),
    6: (32, 22), 7: (32, 24), 8: (32, 34), 9: (32, 40),
    10: (256, 84), 11: (256, 110), 12: (256, 144),
    13: (256, 176), 14: (256, 210), 15: (256, 292),
}


def _fail(code, detail=""):
    raise ArtifactError(code if not detail else f"{code}:{detail}")


class _Reader:
    """Sequential, length-bounded reader over a file handle."""

    def __init__(self, handle, limit, residency_budget):
        self._handle = handle
        self._limit = limit
        self._offset = 0
        self._residency_budget = residency_budget
        self._residency = 0

    @property
    def offset(self):
        return self._offset

    def charge(self, amount):
        """Charge declared parse residency BEFORE the allocation happens.

        A charge that crosses the budget fails with a stable code, so a
        hostile declaration can never drive the parser into unbounded
        allocation or a MemoryError at process scale.
        """
        if self._residency + amount > self._residency_budget:
            _fail("GGUF_METADATA_BUDGET_EXCEEDED")
        self._residency += amount

    def read(self, count):
        if count < 0 or self._offset + count > self._limit:
            _fail("GGUF_TRUNCATED")
        data = self._handle.read(count)
        if len(data) != count:
            _fail("GGUF_TRUNCATED")
        self._offset += count
        return data

    def unpack(self, fmt, size):
        return struct.unpack(fmt, self.read(size))[0]

    def scalar(self, value_type):
        if value_type == BOOL:
            raw = self.read(1)
            if raw[0] > 1:
                _fail("GGUF_INVALID_BOOL")
            return bool(raw[0])
        if value_type == STRING:
            return self.string()
        if value_type == ARRAY:
            return self.array()
        entry = _SCALAR_FORMATS.get(value_type)
        if entry is None:
            _fail("GGUF_UNSUPPORTED_VALUE_TYPE")
        fmt, size = entry
        return self.unpack(fmt, size)

    def string(self):
        length = self.unpack("<Q", 8)
        if length > MAX_STRING_BYTES:
            _fail("GGUF_STRING_TOO_LARGE")
        # Charge the declared payload BEFORE reading or decoding it.
        self.charge(length)
        raw = self.read(length)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactError("GGUF_INVALID_UTF8") from exc

    def array(self):
        element_type = self.unpack("<I", 4)
        count = self.unpack("<Q", 8)
        if count > MAX_ARRAY_ITEMS:
            _fail("GGUF_ARRAY_TOO_LARGE")
        if element_type == ARRAY:
            _fail("GGUF_UNSUPPORTED_VALUE_TYPE")
        # Charge the declared item footprint BEFORE building the list.
        self.charge(count * _SCALAR_ITEM_RESIDENCY_BYTES)
        return [self.scalar(element_type) for _ in range(count)]


# Metadata keys whose array value is large, deterministic and not needed for
# planning. They are counted but not retained, so a 200k-token vocabulary
# costs no resident memory.
_DISCARDED_ARRAY_KEYS = {
    "tokenizer.ggml.tokens": "token_count",
    "tokenizer.ggml.token_type": "token_type_count",
    "tokenizer.ggml.merges": "merge_count",
}


def _read_metadata(reader):
    pairs = {}
    count = reader.unpack("<Q", 8)
    if count > MAX_KV_PAIRS:
        _fail("GGUF_TOO_MANY_METADATA")
    for _ in range(count):
        key = reader.string()
        value_type = reader.unpack("<I", 4)
        if key in _DISCARDED_ARRAY_KEYS and value_type == ARRAY:
            element_type = reader.unpack("<I", 4)
            length = reader.unpack("<Q", 8)
            if length > MAX_ARRAY_ITEMS:
                _fail("GGUF_ARRAY_TOO_LARGE")
            for _ in range(length):
                reader.scalar(element_type)
            pairs[_DISCARDED_ARRAY_KEYS[key]] = length
            continue
        pairs[key] = reader.scalar(value_type)
    return pairs


def _read_tensor_descriptors(reader, tensor_count):
    if tensor_count > MAX_TENSORS:
        _fail("GGUF_TOO_MANY_TENSORS")
    tensors = []
    for _ in range(tensor_count):
        # GGUF tensor info order: name, dimension count, dimensions, type, offset.
        name = reader.string()
        dimensions = reader.unpack("<I", 4)
        if dimensions > MAX_TENSOR_DIMS:
            _fail("GGUF_TOO_MANY_DIMENSIONS")
        # Charge the descriptor's retained footprint (shape ints + dict)
        # BEFORE unpacking the dimensions.
        reader.charge(dimensions * _DESCRIPTOR_DIMENSION_RESIDENCY_BYTES)
        shape = [reader.unpack("<Q", 8) for _ in range(dimensions)]
        quantized_type = reader.unpack("<I", 4)
        offset = reader.unpack("<Q", 8)
        elements = 1
        for dimension in shape:
            elements *= dimension
        tensors.append(
            {
                "name": name,
                "shape": shape,
                "elements": elements,
                "ggml_type": quantized_type,
                "data_offset": offset,
            }
        )
    return tensors


def read_metadata(path):
    """Return header metadata and tensor descriptors without reading weights."""
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ArtifactError("GGUF_UNAVAILABLE") from exc
    if size <= 0 or size > MAX_FILE_BYTES:
        _fail("GGUF_UNUSABLE_SIZE")
    try:
        with source.open("rb") as handle:
            reader = _Reader(handle, size, MAX_METADATA_RESIDENCY_BYTES)
            if reader.read(4) != MAGIC:
                _fail("GGUF_BAD_MAGIC")
            version = reader.unpack("<I", 4)
            if version not in (2, 3):
                _fail("GGUF_UNSUPPORTED_VERSION")
            tensor_count = reader.unpack("<Q", 8)
            metadata = _read_metadata(reader)
            tensors = _read_tensor_descriptors(reader, tensor_count)
            alignment = metadata.get("general.alignment", 32)
            if type(alignment) is not int or not 1 <= alignment <= 4096 or alignment & (alignment - 1):
                _fail("GGUF_INVALID_ALIGNMENT")
            data_start = (reader.offset + alignment - 1) // alignment * alignment
            if any(tensor["data_offset"] >= size for tensor in tensors):
                _fail("GGUF_TENSOR_OFFSET_OUT_OF_RANGE")
            if data_start > size:
                _fail("GGUF_TRUNCATED_TENSOR_DATA")
            for tensor in tensors:
                layout = _GGML_LAYOUTS.get(tensor["ggml_type"])
                if layout is None:
                    _fail("GGUF_UNSUPPORTED_TENSOR_TYPE")
                block_elements, block_bytes = layout
                required = ((tensor["elements"] + block_elements - 1) // block_elements) * block_bytes
                if data_start + tensor["data_offset"] + required > size:
                    _fail("GGUF_TRUNCATED_TENSOR_DATA")
    except ArtifactError:
        raise
    except (OSError, struct.error, MemoryError) as exc:
        raise ArtifactError("GGUF_PARSE_FAILED") from exc
    return {"file_bytes": size, "version": version, "metadata": metadata, "tensors": tensors}


def _first(metadata, *names):
    for name in names:
        if name in metadata:
            return metadata[name]
    return None


def _as_int(value):
    if type(value) is bool or type(value) is not int:
        return None
    return value


def summarize(path):
    """Derive exact, sourced model facts from a GGUF file's own metadata."""
    raw = read_metadata(path)
    metadata = raw["metadata"]
    tensors = raw["tensors"]
    total_parameters = sum(tensor["elements"] for tensor in tensors)
    file_type = _as_int(_first(metadata, "general.file_type"))
    architecture = _first(metadata, "general.architecture")
    attention_layers = _as_int(_first(metadata, "block_count"))
    head_count = _as_int(_first(metadata, "attention.head_count"))
    head_count_kv = _as_int(_first(metadata, "attention.head_count_kv"))
    embedding_length = _as_int(_first(metadata, "embedding_length"))
    context_length = _as_int(_first(metadata, "context_length"))
    expert_markers = sorted(
        {
            marker
            for marker in _EXPERT_MARKERS
            for tensor in tensors
            if marker in tensor["name"]
        }
    )
    head_dimension = None
    if head_count and embedding_length and embedding_length % head_count == 0:
        head_dimension = embedding_length // head_count
    quantization_name = FILE_TYPES.get(file_type) if file_type is not None else None
    return {
        "source": "GGUF_HEADER_METADATA",
        "file_bytes": raw["file_bytes"],
        "gguf_version": raw["version"],
        "metadata": metadata,
        "tensors": tensors,
        "name": _first(metadata, "general.name"),
        "architecture": architecture if type(architecture) is str else None,
        "file_type_id": file_type,
        "quantization": quantization_name,
        "quantization_known": quantization_name is not None,
        "total_parameters": total_parameters,
        "tensor_count": len(tensors),
        "block_count": attention_layers,
        "head_count": head_count,
        "head_count_kv": head_count_kv,
        "head_dimension": head_dimension,
        "embedding_length": embedding_length,
        "context_length": context_length,
        "vocab_size": _as_int(_first(metadata, "tokenizer.ggml.tokens.length", "vocab_size")),
        "expert_markers": expert_markers,
        "mixture_of_experts": bool(expert_markers),
    }


def declared_weight_bits(summary):
    """Idealized uniform weight width implied by a named quantization.

    The F1 requirements engine only accepts a small explicit set of uniform
    bit widths. A named K-quantization is reported at its base weight width
    because K-quantization stores 4-bit block weights plus block scales; the
    engine's idealized-payload formula deliberately excludes that scale
    overhead and says so in its own limitations.
    """
    quantization = summary.get("quantization")
    if type(quantization) is not str:
        return None
    base = {
        "Q2_K": "2",
        "Q3_K_S": "3",
        "Q3_K_M": "3",
        "Q3_K_L": "3",
        "Q4_0": "4",
        "Q4_1": "4",
        "Q4_K_S": "4",
        "Q4_K_M": "4",
        "Q5_0": "5",
        "Q5_1": "5",
        "Q5_K_S": "5",
        "Q5_K_M": "5",
        "Q6_K": "6",
        "Q8_0": "8",
        "F16": "16",
        "F32": "32",
        "BF16": "16",
    }.get(quantization)
    if base is None or base not in SUPPORTED_IDEALIZED_BITS:
        return None
    return base
