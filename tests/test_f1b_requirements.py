import json
import unittest
from decimal import Decimal

from fitlab_foundation.contracts import (
    ArchitectureKind,
    AttentionMechanism,
    HardwareResources,
    ModelArchitecture,
    ReasonCode,
    ResultStatus,
    Workload,
)
from fitlab_foundation.requirements import (
    BANDWIDTH_FORMULA,
    COMPUTE_RATE_FORMULA,
    FLOPS_FORMULA,
    KV_FORMULA,
    WEIGHT_FORMULA,
    RequirementsEngine,
    approximate_decoder_flops_per_token,
    calculate_conditional_decode_bandwidth,
    calculate_ideal_weight_payload,
    calculate_standard_kv_cache,
    calculate_target_compute_rate,
    effective_bandwidth_observation,
)
from fitlab_foundation.serialization import canonical_json
from fitlab_foundation.validation import ValidationError


class F1BFormulaTests(unittest.TestCase):
    def setUp(self):
        self.standard_model = ModelArchitecture(
            model_id="synthetic-standard",
            total_parameters=1_000,
            layers=2,
            query_heads=8,
            kv_heads=2,
            head_dimension=4,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        self.standard_workload = Workload(
            resident_sequences=1,
            cached_tokens_per_sequence=10,
            kv_bytes_per_element=2,
            target_tokens_per_second=Decimal("5"),
            declared_bytes_reloaded_per_token=500,
            residency_assumption="Synthetic fixture reloads the declared idealized weight payload once per generated token.",
        )

    def test_idealized_weight_payload_reference_fixture(self):
        result = calculate_ideal_weight_payload(self.standard_model, Decimal("4"))
        self.assertEqual(result.status, ResultStatus.ESTIMATED)
        self.assertEqual(result.value, Decimal("500"))
        self.assertEqual(result.formula.identifier, "fitlab.weights.idealized_payload")
        self.assertIn("not measured loaded RAM", result.limitations)

    def test_standard_kv_reference_fixture_is_640_bytes(self):
        result = calculate_standard_kv_cache(self.standard_model, self.standard_workload)
        self.assertEqual(result.status, ResultStatus.CALCULATED)
        self.assertEqual(result.value, 640)
        self.assertEqual(result.formula.identifier, "fitlab.kv.standard_full_cache")

    def test_doubling_resident_sequences_doubles_kv_once(self):
        one = calculate_standard_kv_cache(self.standard_model, self.standard_workload)
        two = calculate_standard_kv_cache(
            self.standard_model,
            Workload(resident_sequences=2, cached_tokens_per_sequence=10, kv_bytes_per_element=2),
        )
        self.assertEqual(two.value, one.value * 2)

    def test_gqa_uses_kv_heads_not_query_heads(self):
        result = calculate_standard_kv_cache(self.standard_model, self.standard_workload)
        wrong_query_head_value = 2 * 2 * 8 * 4 * 1 * 10 * 2
        self.assertEqual(result.value, 640)
        self.assertNotEqual(result.value, wrong_query_head_value)

    def test_missing_kv_metadata_returns_unknown(self):
        model = ModelArchitecture(
            model_id="missing",
            total_parameters=1000,
            layers=2,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        result = calculate_standard_kv_cache(model, self.standard_workload)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.MISSING_METADATA)
        self.assertIsNone(result.value)

    def test_unsupported_attention_mechanisms_never_return_numeric_kv(self):
        for attention in (
            AttentionMechanism.SLIDING_WINDOW,
            AttentionMechanism.MLA,
            AttentionMechanism.PAGED,
            AttentionMechanism.OFFLOADED,
            AttentionMechanism.OTHER,
        ):
            with self.subTest(attention=attention):
                model = ModelArchitecture(
                    model_id="unsupported",
                    total_parameters=1000,
                    layers=2,
                    query_heads=8,
                    kv_heads=2,
                    head_dimension=4,
                    architecture_kind=ArchitectureKind.DENSE_DECODER,
                    attention_mechanism=attention,
                )
                result = calculate_standard_kv_cache(model, self.standard_workload)
                self.assertEqual(result.status, ResultStatus.UNKNOWN)
                self.assertEqual(result.reasons[0].code, ReasonCode.UNSUPPORTED_ATTENTION)

    def test_invalid_cache_dimensions_fail_at_contract_boundary(self):
        with self.assertRaises(ValidationError):
            Workload(cached_tokens_per_sequence=0, kv_bytes_per_element=2)
        with self.assertRaises(ValidationError):
            Workload(cached_tokens_per_sequence=10, kv_bytes_per_element=3)

    def test_dense_compute_uses_total_parameters_when_active_not_declared(self):
        result = approximate_decoder_flops_per_token(self.standard_model)
        self.assertEqual(result.status, ResultStatus.ESTIMATED)
        self.assertEqual(result.value, 2000)
        self.assertIn("prefill", " ".join(result.limitations).lower())

    def test_moe_compute_uses_active_but_weights_use_total_parameters(self):
        model = ModelArchitecture(
            model_id="synthetic-moe",
            total_parameters=10_000,
            active_parameters=2_000,
            architecture_kind=ArchitectureKind.MOE_DECODER,
        )
        weight = calculate_ideal_weight_payload(model, Decimal("4"))
        compute = approximate_decoder_flops_per_token(model)
        self.assertEqual(weight.value, Decimal("5000"))
        self.assertEqual(compute.value, 4000)

    def test_moe_without_active_parameters_is_unknown(self):
        model = ModelArchitecture(
            model_id="synthetic-moe",
            total_parameters=10_000,
            architecture_kind=ArchitectureKind.MOE_DECODER,
        )
        result = approximate_decoder_flops_per_token(model)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.MISSING_METADATA)

    def test_unknown_architecture_compute_is_unknown(self):
        model = ModelArchitecture(
            model_id="synthetic-unknown",
            total_parameters=10_000,
            architecture_kind=ArchitectureKind.UNKNOWN,
        )
        result = approximate_decoder_flops_per_token(model)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.UNSUPPORTED_ARCHITECTURE)

    def test_target_compute_rate_multiplies_heuristic_by_target(self):
        flops = approximate_decoder_flops_per_token(self.standard_model)
        result = calculate_target_compute_rate(flops, self.standard_workload)
        self.assertEqual(result.status, ResultStatus.ESTIMATED)
        self.assertEqual(result.value, Decimal("10000"))
        self.assertEqual(result.unit, "FLOP/s")

    def test_target_compute_rate_rejects_byte_valued_weight_result(self):
        weight_bytes = calculate_ideal_weight_payload(
            self.standard_model, Decimal("4")
        )
        result = calculate_target_compute_rate(weight_bytes, self.standard_workload)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(
            result.reasons[0].code, ReasonCode.INCOMPATIBLE_DIMENSION
        )
        self.assertIsNone(result.value)

    def test_target_compute_rate_propagates_unknown(self):
        unknown_flops = approximate_decoder_flops_per_token(
            ModelArchitecture(
                model_id="moe",
                total_parameters=1000,
                architecture_kind=ArchitectureKind.MOE_DECODER,
            )
        )
        result = calculate_target_compute_rate(unknown_flops, self.standard_workload)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.DEPENDENCY_UNKNOWN)

    def test_missing_target_throughput_returns_unknown(self):
        result = calculate_target_compute_rate(
            approximate_decoder_flops_per_token(self.standard_model),
            Workload(),
        )
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.MISSING_METADATA)

    def test_conditional_bandwidth_requires_explicit_residency_assumption(self):
        workload = Workload(
            target_tokens_per_second=Decimal("5"),
            declared_bytes_reloaded_per_token=500,
        )
        result = calculate_conditional_decode_bandwidth(workload)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.EXPLICIT_ASSUMPTION_REQUIRED)

    def test_conditional_bandwidth_reference_calculation(self):
        result = calculate_conditional_decode_bandwidth(self.standard_workload)
        self.assertEqual(result.status, ResultStatus.ESTIMATED)
        self.assertEqual(result.value, Decimal("2500"))
        self.assertEqual(result.unit, "byte/s")
        self.assertIn("does not predict achieved throughput", result.limitations)

    def test_absent_effective_bandwidth_is_unavailable_not_guessed(self):
        result = effective_bandwidth_observation(HardwareResources(host_ram_bytes=16 * 2**30))
        self.assertEqual(result.status, ResultStatus.UNAVAILABLE)
        self.assertEqual(result.reasons[0].code, ReasonCode.EFFECTIVE_BANDWIDTH_UNKNOWN)

    def test_unverified_supplied_effective_bandwidth_is_unavailable(self):
        hardware = HardwareResources(
            host_ram_bytes=16 * 2**30,
            effective_memory_bandwidth_bytes_per_second=Decimal("100000000000"),
        )
        result = effective_bandwidth_observation(hardware)
        self.assertEqual(result.status, ResultStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertEqual(
            result.reasons[0].code, ReasonCode.UNVERIFIED_PROVENANCE
        )

    def test_formula_identifiers_and_versions_are_stable(self):
        for formula in (WEIGHT_FORMULA, KV_FORMULA, FLOPS_FORMULA, COMPUTE_RATE_FORMULA, BANDWIDTH_FORMULA):
            self.assertTrue(formula.identifier.startswith("fitlab."))
            self.assertEqual(formula.version, "1.0.0")


class F1BEngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.model = ModelArchitecture(
            model_id="synthetic-integration",
            total_parameters=1000,
            layers=2,
            query_heads=8,
            kv_heads=2,
            head_dimension=4,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        self.workload = Workload(
            resident_sequences=1,
            cached_tokens_per_sequence=10,
            kv_bytes_per_element=2,
            target_tokens_per_second=Decimal("5"),
            declared_bytes_reloaded_per_token=500,
            residency_assumption="Synthetic declared reload assumption.",
        )

    def test_engine_aggregates_supported_calculations_consistently(self):
        bundle = RequirementsEngine().evaluate(
            self.model,
            self.workload,
            HardwareResources(host_ram_bytes=16 * 2**30),
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.idealized_weight_payload.value, Decimal("500"))
        self.assertEqual(bundle.kv_cache.value, 640)
        self.assertEqual(bundle.known_memory_baseline.value, Decimal("1140"))
        self.assertEqual(bundle.decoder_flops_per_token.value, 2000)
        self.assertEqual(bundle.target_compute_rate.value, Decimal("10000"))
        self.assertEqual(bundle.conditional_decode_bandwidth.value, Decimal("2500"))

    def test_unknown_kv_propagates_to_combined_memory(self):
        incomplete = ModelArchitecture(model_id="incomplete", total_parameters=1000)
        bundle = RequirementsEngine().evaluate(
            incomplete,
            self.workload,
            HardwareResources(host_ram_bytes=16 * 2**30),
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.kv_cache.status, ResultStatus.UNKNOWN)
        self.assertEqual(bundle.known_memory_baseline.status, ResultStatus.UNKNOWN)
        self.assertEqual(bundle.known_memory_baseline.reasons[0].code, ReasonCode.DEPENDENCY_UNKNOWN)

    def test_engine_never_invents_runtime_overhead_or_physical_fit(self):
        bundle = RequirementsEngine().evaluate(
            self.model,
            self.workload,
            HardwareResources(
                host_ram_bytes=16 * 2**30,
                measured_available_host_bytes=8 * 2**30,
            ),
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.runtime_overhead.status, ResultStatus.UNKNOWN)
        self.assertEqual(bundle.runtime_overhead.reasons[0].code, ReasonCode.RUNTIME_OVERHEAD_UNKNOWN)
        self.assertEqual(bundle.whole_system_fit.status, ResultStatus.UNKNOWN)
        self.assertEqual(bundle.whole_system_fit.reasons[0].code, ReasonCode.PHYSICAL_FEASIBILITY_NOT_MODELED)

    def test_engine_does_not_double_count_unified_memory(self):
        hardware = HardwareResources(
            host_ram_bytes=16 * 2**30,
            measured_available_host_bytes=8 * 2**30,
            unified_shared_memory_bytes=8 * 2**30,
        )
        bundle = RequirementsEngine().evaluate(
            self.model,
            self.workload,
            hardware,
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.independent_physical_capacity.value, 16 * 2**30)

    def test_repeated_evaluation_serializes_byte_for_byte_identically(self):
        engine = RequirementsEngine()
        args = (self.model, self.workload, HardwareResources(host_ram_bytes=16 * 2**30))
        first = canonical_json(engine.evaluate(*args, weight_bits_per_parameter=Decimal("4")))
        second = canonical_json(engine.evaluate(*args, weight_bits_per_parameter=Decimal("4")))
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), json.loads(second))

    def test_engine_output_contains_no_achievable_throughput_claim(self):
        bundle = RequirementsEngine().evaluate(
            self.model,
            self.workload,
            HardwareResources(host_ram_bytes=16 * 2**30),
            weight_bits_per_parameter=Decimal("4"),
        )
        serialized = canonical_json(bundle).lower()
        self.assertNotIn("achievable_tokens", serialized)
        self.assertIn("physical_feasibility_not_modeled", serialized)

    def test_formula_outputs_are_reproducible_by_hand(self):
        bundle = RequirementsEngine().evaluate(
            self.model,
            self.workload,
            HardwareResources(host_ram_bytes=16 * 2**30),
            weight_bits_per_parameter=Decimal("4"),
        )
        hand_weight = Decimal(1000) * Decimal(4) / Decimal(8)
        hand_kv = 2 * 2 * 2 * 4 * 1 * 10 * 2
        hand_flops = 2 * 1000
        self.assertEqual(bundle.idealized_weight_payload.value, hand_weight)
        self.assertEqual(bundle.kv_cache.value, hand_kv)
        self.assertEqual(bundle.decoder_flops_per_token.value, hand_flops)


if __name__ == "__main__":
    unittest.main()
