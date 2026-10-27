"""Synthetic supported example; values are not measurements of a real model or device."""

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
    model_id="synthetic-dense-gqa",
    total_parameters=1_000,
    layers=2,
    query_heads=4,
    kv_heads=2,
    head_dimension=4,
    architecture_kind=ArchitectureKind.DENSE_DECODER,
    attention_mechanism=AttentionMechanism.STANDARD_FULL,
)
workload = Workload(
    resident_sequences=1,
    cached_tokens_per_sequence=10,
    kv_bytes_per_element=2,
    target_tokens_per_second=Decimal("5"),
    declared_bytes_reloaded_per_token=500,
    residency_assumption="synthetic example assumes 500 bytes reloaded for each decoded token",
)
hardware = HardwareResources()

bundle = RequirementsEngine().evaluate(
    model,
    workload,
    hardware,
    weight_bits_per_parameter=Decimal("4"),
)
print(canonical_json(bundle))
