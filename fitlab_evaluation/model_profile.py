"""Source-backed model identity and planning-profile derivation.

Everything in this module is derived from artifacts that already exist on the
host: the GGUF header of the local model file, the Lemonade model registry and
an optional owner-supplied workload declaration. Nothing here loads a model,
starts a runtime or performs inference.

The central honesty rule: the F1/F2 requirements engine understands a dense
or MoE autoregressive decoder with standard full-attention KV cache. It does
not understand hybrid short-convolution architectures. When the sourced
metadata shows a hybrid architecture this module must not silently pretend the
standard KV formula applies. It emits a profile whose attention mechanism is
the truthful one, and the engine's own unsupported-attention rule then returns
``UNKNOWN`` instead of a wrong number.
"""

from pathlib import Path

from .artifacts import ArtifactError
from .gguf_meta import declared_weight_bits, summarize

MODEL = "LFM2.5-1.2B-Instruct-GGUF"
REPO = "LiquidAI/LFM2.5-1.2B-Instruct-GGUF"
CHECKPOINT = "LiquidAI/LFM2.5-1.2B-Instruct-GGUF:LFM2.5-1.2B-Instruct-Q4_K_M.gguf"
VERSION = "2026.42.1"
CPU_LLAMACPP = "llamacpp"
DEVICE_CPU = "cpu"
CTX_SIZE = 2048
LLAMACPP_ARGS = "--parallel 1 --threads 2 --threads-batch 2"

# F1 vocabulary. Hybrid short-convolution attention has no entry here, which
# is deliberate: the engine must fail closed rather than mis-apply a formula.
ARCHITECTURE_DENSE = "DENSE_DECODER"
ARCHITECTURE_MOE = "MOE_DECODER"
ARCHITECTURE_UNSUPPORTED = "UNSUPPORTED_HYBRID"
ATTENTION_STANDARD_FULL = "STANDARD_FULL"
ATTENTION_UNSUPPORTED = "SHORT_CONVOLUTION_HYBRID"

CONVOLUTION_BLOCK = "shortconv"
ATTENTION_BLOCK = "attn_q"


def _fail(code, detail=""):
    raise ArtifactError(code if not detail else f"{code}:{detail}")


def _registry_path():
    return Path.home() / ".cache/huggingface/hub" / f"models--{REPO.replace('/', '--')}" / ".lemonade_registry.json"


def read_registry():
    """Read the local Lemonade model registry; it is identity, not capability."""
    path = _registry_path()
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError("MODEL_REGISTRY_UNAVAILABLE") from exc
    if type(payload) is not dict:
        _fail("MODEL_REGISTRY_UNAVAILABLE")
    return payload


def locate_model_file():
    """Resolve the cached GGUF path for the registered snapshot revision."""
    registry = read_registry()
    processed = registry.get("processed_models")
    if type(processed) is not dict or MODEL not in processed:
        _fail("MODEL_NOT_REGISTERED")
    entry = processed[MODEL]
    if type(entry) is not dict:
        _fail("MODEL_REGISTRY_UNAVAILABLE")
    revision = entry.get("snapshot_id")
    if type(revision) is not str or not revision:
        _fail("MODEL_REVISION_UNAVAILABLE")
    root = Path.home() / ".cache/huggingface/hub" / f"models--{REPO.replace('/', '--')}" / "snapshots" / revision
    matches = sorted(root.glob("*.gguf"))
    if len(matches) != 1:
        _fail("MODEL_FILE_UNAVAILABLE")
    return matches[0], revision


def classify_blocks(tensors, block_count):
    """Split transformer blocks into convolution and attention blocks.

    Single pass over the observed tensor names: the work is bounded by the
    number of tensors actually present, never by block_count (a structurally
    valid GGUF may declare up to the excessive-count gate many blocks whose
    names match nothing; the former per-block scans cost block_count x names).
    Only canonical decimal forms "blk.<index>." classify (leading zeros,
    signs or unicode digits never matched the old "blk.<index>." prefixes and
    must not fire now), and indexes at or beyond the declared block_count are
    ignored exactly as range(block_count) excluded them.
    """
    convolution, attention = set(), set()
    canonical_width = len(str(block_count - 1)) if block_count > 0 else 0
    for name in {tensor["name"] for tensor in tensors}:
        if not name.startswith("blk."):
            continue
        tail = name[len("blk."):]
        dot = tail.find(".")
        if dot <= 0:
            continue
        digits = tail[:dot]
        # Only canonical ASCII decimal indexes classify. Superscript and
        # other unicode digit characters satisfy str.isdigit() but int()
        # rejects them; ASCII strings of thousands of digits exceed the
        # interpreter's default int-conversion limit and would abort
        # instead of being ignored (round-44 A-1). Both names were ignored
        # by the former prefix scan and must be ignored now.
        if not digits.isascii() or not digits.isdigit():
            continue
        if digits[0] == "0" and len(digits) > 1:
            continue
        # Bounded string comparison before any int conversion: a canonical
        # (no leading zeros) decimal with more digits than block_count - 1
        # necessarily indexes at or beyond block_count.
        if len(digits) > canonical_width:
            continue
        index = int(digits)
        if index >= block_count:
            continue
        if CONVOLUTION_BLOCK in name:
            convolution.add(index)
        if ATTENTION_BLOCK in name:
            attention.add(index)
    return sorted(convolution), sorted(attention)


def derive_profile(model_path, revision=None):
    """Derive a source-backed planning profile from a GGUF header."""
    summary = summarize(model_path)
    metadata = summary["metadata"]
    architecture = summary.get("architecture")
    prefix = f"{architecture}." if architecture else ""

    # An operator-supplied GGUF must actually be the frozen contract model:
    # attributing arbitrary header metadata to the fixed checkpoint identity
    # would forge provenance. Accept header names that carry the model
    # token (case-insensitive); refuse anything explicitly different.
    declared_name = summary.get("name")
    core = MODEL.split("/")[-1].replace(".gguf", "").split(":")[0]
    if type(declared_name) is str and declared_name and \
            core.lower() not in declared_name.lower():
        # A header that NAMES a different model must never receive the frozen
        # contract identity — that would forge provenance. The supplied
        # name is operator data and NEVER rides the code: cli.main
        # publishes exc.code verbatim into stderr JSON and the doctor's
        # model.reason, so an arbitrary GGUF name could otherwise inject
        # unredacted content into error output (round-53 A-1).
        _fail("MODEL_IDENTITY_MISMATCH")

    def meta(name):
        return metadata.get(prefix + name)

    block_count = meta("block_count")
    head_count = meta("attention.head_count")
    head_count_kv = meta("attention.head_count_kv")
    embedding_length = meta("embedding_length")
    feed_forward_length = meta("feed_forward_length")
    shortconv_cache = meta("shortconv.l_cache")
    context_length = meta("context_length")
    vocab_size = meta("vocab_size")

    if type(block_count) is not int or block_count <= 0:
        _fail("MODEL_METADATA_INCOMPLETE", "block_count")
    # A structurally valid GGUF can declare a UINT64-maximum block_count;
    # classify_blocks iterates range(block_count), so an unchecked value
    # hangs the offline planner before any later layer limit could apply
    # (round-42 A-1). Bound it here, before classification, with a stable
    # error code. The declared value MUST NOT ride the code: cli.main
    # publishes exc.code verbatim into the evaluation record, so the code
    # alone is the stable contract and the exact value is deliberately
    # dropped.
    if block_count > 100000:
        _fail("MODEL_METADATA_BLOCK_COUNT_EXCESSIVE")
    if type(embedding_length) is not int or embedding_length <= 0:
        _fail("MODEL_METADATA_INCOMPLETE", "embedding_length")
    if type(head_count) is not int or head_count <= 0:
        _fail("MODEL_METADATA_INCOMPLETE", "attention.head_count")

    convolution_blocks, attention_blocks = classify_blocks(
        summary["tensors"], block_count
    )
    hybrid = bool(convolution_blocks) and bool(attention_blocks)
    mixture_of_experts = bool(summary.get("mixture_of_experts"))

    if mixture_of_experts:
        architecture_kind = ARCHITECTURE_MOE
    elif hybrid:
        architecture_kind = ARCHITECTURE_UNSUPPORTED
    else:
        architecture_kind = ARCHITECTURE_DENSE

    if hybrid:
        attention_mechanism = ATTENTION_UNSUPPORTED
    else:
        attention_mechanism = ATTENTION_STANDARD_FULL

    # KV head count may be a per-layer array; the engine takes one declared
    # value, so the maximum is used and the variation is disclosed.
    kv_heads = None
    kv_head_distribution = None
    if type(head_count_kv) is list:
        values = [value for value in head_count_kv if type(value) is int]
        if values:
            kv_heads = max(values)
            kv_head_distribution = {
                "per_layer": list(head_count_kv),
                "distinct": sorted(set(values)),
            }
    elif type(head_count_kv) is int:
        kv_heads = head_count_kv
    elif type(head_count) is int:
        kv_heads = head_count

    head_dimension = None
    if type(head_count) is int and head_count > 0 and embedding_length % head_count == 0:
        head_dimension = embedding_length // head_count

    weight_bits = declared_weight_bits(summary)

    # Operator-supplied display metadata must be a string or absent: an
    # ARRAY<STRING> license field would otherwise carry nested private
    # strings through every publisher (round-57 A-1). The declared name is
    # already type-checked at the mismatch gate above; these fields have
    # no structural role and are accepted only in their declared shape.
    def _declared_text(name):
        value = metadata.get(name)
        if value is None:
            return None
        if type(value) is not str or not value or len(value) > 512:
            return None
        return value

    return {
        "model_id": MODEL,
        "repo_id": REPO,
        "checkpoint": CHECKPOINT,
        "snapshot_revision": revision,
        "runtime_version": VERSION,
        "device": DEVICE_CPU,
        "backend": CPU_LLAMACPP,
        "context_size": CTX_SIZE,
        "llamacpp_args": LLAMACPP_ARGS,
        "identity_source": "LOCAL_GGUF_HEADER_AND_LEMONADE_REGISTRY",
        "model_identity": ("VERIFIED_LOCAL_HEADER"
                           if type(declared_name) is str and declared_name
                           and core.lower() in declared_name.lower()
                           else "UNVERIFIED"),
        "file_bytes": summary["file_bytes"],
        "gguf_version": summary["gguf_version"],
        "declared_name": summary.get("name"),
        "architecture_family": architecture,
        "architecture_kind": architecture_kind,
        "attention_mechanism": attention_mechanism,
        "hybrid": hybrid,
        "convolution_block_count": len(convolution_blocks),
        "attention_block_count": len(attention_blocks),
        "block_count": block_count,
        "head_count": head_count,
        "kv_heads": kv_heads,
        "kv_head_distribution": kv_head_distribution,
        "head_dimension": head_dimension,
        "embedding_length": embedding_length,
        "feed_forward_length": feed_forward_length,
        "shortconv_cache_length": shortconv_cache,
        "context_length": context_length,
        "vocab_size": vocab_size,
        "total_parameters": summary["total_parameters"],
        "tensor_count": summary["tensor_count"],
        "quantization": summary.get("quantization"),
        "quantization_known": summary.get("quantization_known"),
        "weight_bits_per_parameter": weight_bits,
        "declared_license_name": _declared_text("general.license.name"),
        "declared_license_link": _declared_text("general.license.link"),
        "size_label": _declared_text("general.size_label"),
    }


def profile_hardware():
    """Read the host's physical memory and CPU identity, without a runtime."""
    profile = {"source": "NATIVE_HOST_QUERY", "accelerator": "NONE_DECLARED"}
    try:
        from .lemonade import windows_memory

        profile["memory"] = windows_memory()
    except Exception as exc:  # pragma: no cover - platform dependent
        profile["memory"] = None
        profile["memory_error"] = type(exc).__name__
    try:
        import platform

        profile["machine"] = platform.machine()
        profile["processor"] = platform.processor()
    except Exception:  # pragma: no cover - platform dependent
        pass
    return profile


def host_identity():
    """Return only stable host facts.

    The Capability Passport must be byte-reproducible: identical inputs must
    yield identical output. Available memory, memory load and commit size are
    transient observations and are therefore excluded here; they belong to a
    live session record, not to a reproducible report. Total physical memory,
    CPU brand and logical processor count are stable for the life of a host.
    """
    identity = {
        "source": "NATIVE_HOST_QUERY",
        "accelerator": "NONE_DECLARED",
        "total_physical_bytes": None,
        "cpu_brand": None,
        "logical_processors": None,
        "machine": None,
    }
    try:
        from .lemonade import windows_memory

        identity["total_physical_bytes"] = windows_memory()["total_physical_bytes"]
    except Exception:  # pragma: no cover - platform dependent
        pass
    try:
        import os

        identity["logical_processors"] = os.cpu_count()
    except Exception:  # pragma: no cover - platform dependent
        pass
    try:
        import platform

        identity["machine"] = platform.machine()
    except Exception:  # pragma: no cover - platform dependent
        pass
    import os as _os

    if _os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                identity["cpu_brand"] = str(name).strip()
        except Exception:  # pragma: no cover - platform dependent
            pass
    return identity
