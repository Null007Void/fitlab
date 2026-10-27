"""Synthetic unsupported example showing explicit UNKNOWN propagation."""

from decimal import Decimal

from fitlab_foundation.contracts import (
    ArchitectureKind,
    AttentionMechanism,
    HardwareResources,
    ModelArchitecture,
    Workload,
)
from fitlab_foundation.requirements import RequirementsEngine
from fitlab_foundation.serialization import canonical_json

model = ModelArchitecture(
    model_id="synthetic-mla-model",
    total_parameters=10_000,
    layers=2,
    query_heads=4,
    kv_heads=2,
    head_dimension=8,
    architecture_kind=ArchitectureKind.DENSE_DECODER,
    attention_mechanism=AttentionMechanism.MLA,
)
workload = Workload(cached_tokens_per_sequence=10, kv_bytes_per_element=2)

bundle = RequirementsEngine().evaluate(
    model,
    workload,
    HardwareResources(unified_shared_memory_bytes=8 * 2**30),
    weight_bits_per_parameter=Decimal("4"),
)
print(canonical_json(bundle))
