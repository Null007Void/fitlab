import json
import unittest
from decimal import Decimal

from fitlab_foundation.contracts import (
    ArchitectureKind,
    AttentionMechanism,
    CalculationResult,
    FormulaProvenance,
    HardwareResources,
    ModelArchitecture,
    Reason,
    ReasonCode,
    ResultStatus,
    Workload,
)
from fitlab_foundation.requirements import RequirementsEngine, calculate_standard_kv_cache
from fitlab_foundation.serialization import canonical_json
from fitlab_foundation.units import bytes_to_gb, bytes_to_gib
from fitlab_foundation.validation import ValidationError


class AdversarialBoundaryTests(unittest.TestCase):
    def test_model_defaults_do_not_imply_supported_architecture(self):
        model = ModelArchitecture(
            model_id="unverified-defaults",
            total_parameters=1000,
            layers=2,
            query_heads=2,
            kv_heads=2,
            head_dimension=4,
        )
        workload = Workload(
            cached_tokens_per_sequence=10,
            kv_bytes_per_element=2,
        )
        bundle = RequirementsEngine().evaluate(
            model,
            workload,
            HardwareResources(),
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.kv_cache.status, ResultStatus.UNKNOWN)
        self.assertEqual(
            bundle.kv_cache.reasons[0].code,
            ReasonCode.UNSUPPORTED_ARCHITECTURE,
        )
        self.assertEqual(
            bundle.decoder_flops_per_token.status, ResultStatus.UNKNOWN
        )

    def test_unknown_architecture_cannot_produce_kv_with_standard_attention(self):
        model = ModelArchitecture(
            model_id="unknown-explicit-attention",
            total_parameters=1000,
            layers=2,
            query_heads=2,
            kv_heads=2,
            head_dimension=4,
            architecture_kind=ArchitectureKind.UNKNOWN,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        result = calculate_standard_kv_cache(
            model,
            Workload(cached_tokens_per_sequence=10, kv_bytes_per_element=2),
        )
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(
            result.reasons[0].code, ReasonCode.UNSUPPORTED_ARCHITECTURE
        )

    def test_required_total_parameters_cannot_be_none(self):
        with self.assertRaises(ValidationError):
            ModelArchitecture(model_id="bad", total_parameters=None)

    def test_reason_collection_must_be_immutable_tuple(self):
        with self.assertRaises(ValidationError):
            CalculationResult(
                name="bad",
                status=ResultStatus.UNKNOWN,
                reasons=[Reason(ReasonCode.MISSING_METADATA, "x")],
            )

    def test_decimal_digit_bomb_is_rejected(self):
        value = Decimal("0." + "1" * 101)
        with self.assertRaises(ValidationError) as ctx:
            Workload(target_tokens_per_second=value)
        self.assertEqual(ctx.exception.code, "DECIMAL_COMPLEXITY")

    def test_extreme_decimal_exponent_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            Workload(target_tokens_per_second=Decimal("1E-1000"))
        self.assertEqual(ctx.exception.code, "DECIMAL_COMPLEXITY")

    def test_large_bounded_kv_result_fails_closed_instead_of_claiming_number(self):
        model = ModelArchitecture(
            model_id="bounded-but-product-too-large",
            total_parameters=1000,
            layers=100_000,
            query_heads=1_000_000,
            kv_heads=1_000_000,
            head_dimension=10_000_000,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        workload = Workload(
            resident_sequences=1_000_000,
            cached_tokens_per_sequence=10_000_000,
            kv_bytes_per_element=8,
        )
        result = calculate_standard_kv_cache(model, workload)
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.reasons[0].code, ReasonCode.ARITHMETIC_BOUND_EXCEEDED)

    def test_negative_bytes_do_not_convert(self):
        with self.assertRaises(ValidationError):
            bytes_to_gb(-1)

    def test_serialization_rejects_binary_float(self):
        with self.assertRaises(ValidationError):
            canonical_json({"bad": 0.1})

    def test_serialization_rejects_non_string_mapping_keys(self):
        with self.assertRaises(ValidationError):
            canonical_json({1: "bad"})

    def test_canonical_mapping_order_is_stable(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))

    def test_query_heads_less_than_kv_heads_is_rejected(self):
        with self.assertRaises(ValidationError):
            ModelArchitecture(
                model_id="bad-gqa",
                total_parameters=1000,
                query_heads=2,
                kv_heads=4,
            )

    def test_unified_memory_without_host_is_not_presented_as_independent_capacity(self):
        h = HardwareResources(unified_shared_memory_bytes=8 * 2**30)
        self.assertIsNone(h.independent_physical_capacity_bytes())

    def test_engine_refuses_fit_even_when_known_baseline_is_below_available_memory(self):
        model = ModelArchitecture(
            model_id="tempting-fit",
            total_parameters=1000,
            layers=2,
            query_heads=2,
            kv_heads=2,
            head_dimension=4,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        workload = Workload(
            cached_tokens_per_sequence=10,
            kv_bytes_per_element=2,
            target_tokens_per_second=Decimal("1"),
            declared_bytes_reloaded_per_token=500,
            residency_assumption="synthetic",
        )
        bundle = RequirementsEngine().evaluate(
            model,
            workload,
            HardwareResources(host_ram_bytes=16 * 2**30, measured_available_host_bytes=15 * 2**30),
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.whole_system_fit.status, ResultStatus.UNKNOWN)
        self.assertNotIn("true", canonical_json(bundle.whole_system_fit).lower())

    def test_unsupported_attention_cannot_leak_numeric_value_through_engine(self):
        model = ModelArchitecture(
            model_id="mla",
            total_parameters=1000,
            layers=2,
            query_heads=2,
            kv_heads=2,
            head_dimension=4,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.MLA,
        )
        workload = Workload(cached_tokens_per_sequence=10, kv_bytes_per_element=2)
        bundle = RequirementsEngine().evaluate(
            model,
            workload,
            HardwareResources(),
            weight_bits_per_parameter=Decimal("4"),
        )
        self.assertEqual(bundle.kv_cache.status, ResultStatus.UNKNOWN)
        self.assertIsNone(bundle.kv_cache.value)
        self.assertEqual(bundle.known_memory_baseline.status, ResultStatus.UNKNOWN)

    def test_result_rejects_boolean_value(self):
        p = FormulaProvenance("fitlab.bad", "1.0.0", "x")
        with self.assertRaises(ValidationError):
            CalculationResult.calculated("bad", True, "byte", p)

    def test_result_rejects_mutable_assumption_collection(self):
        p = FormulaProvenance("fitlab.bad", "1.0.0", "x")
        with self.assertRaises(ValidationError):
            CalculationResult.calculated("bad", 1, "byte", p, assumptions=["mutable"])

    def test_required_resident_sequences_cannot_be_none(self):
        with self.assertRaises(ValidationError):
            Workload(resident_sequences=None)

    def test_decimal_arithmetic_is_independent_of_ambient_context(self):
        from decimal import Inexact, ROUND_CEILING, ROUND_FLOOR, Rounded, localcontext

        model = ModelArchitecture(
            model_id="context-independence",
            total_parameters=999_999_999_999_999,
            layers=2,
            query_heads=2,
            kv_heads=2,
            head_dimension=4,
            architecture_kind=ArchitectureKind.DENSE_DECODER,
            attention_mechanism=AttentionMechanism.STANDARD_FULL,
        )
        workload = Workload(
            cached_tokens_per_sequence=10,
            kv_bytes_per_element=2,
            target_tokens_per_second=Decimal("999999999.999999999999999999"),
            declared_bytes_reloaded_per_token=999_999_999_999_999_999_999,
            residency_assumption="synthetic context-independence fixture",
        )
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.rounding = ROUND_FLOOR
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            low_precision = canonical_json(
                RequirementsEngine().evaluate(
                    model, workload, HardwareResources(), weight_bits_per_parameter=Decimal("3")
                )
            )
        with localcontext() as ctx:
            ctx.prec = 60
            ctx.rounding = ROUND_CEILING
            high_precision = canonical_json(
                RequirementsEngine().evaluate(
                    model, workload, HardwareResources(), weight_bits_per_parameter=Decimal("3")
                )
            )
        self.assertEqual(low_precision, high_precision)

    def test_result_decimal_magnitude_is_bounded(self):
        p = FormulaProvenance("fitlab.bound", "1.0.0", "x")
        with self.assertRaises(ValidationError):
            CalculationResult.calculated("too-large", Decimal("1E+36"), "byte", p)

    def test_canonical_decimal_normalizes_equivalent_representations(self):
        self.assertEqual(canonical_json({"value": Decimal("1.0")}), canonical_json({"value": Decimal("1.00")}))

    def test_serialization_rejects_excessive_decimal_expansion(self):
        with self.assertRaises(ValidationError):
            canonical_json({"value": Decimal("1E+1000")})

    def test_smallest_gib_unit_result_is_canonically_serializable(self):
        self.assertEqual(
            canonical_json({"value": bytes_to_gib(1)}),
            '{"value":"0.000000000931322574615478515625"}',
        )

    def test_serialization_rejects_huge_integer(self):
        with self.assertRaises(ValidationError):
            canonical_json({"value": 10**5000})

    def test_serialization_rejects_cycle(self):
        cycle = []
        cycle.append(cycle)
        with self.assertRaises(ValidationError) as ctx:
            canonical_json(cycle)
        self.assertEqual(ctx.exception.code, "CYCLE_DETECTED")

    def test_serialization_rejects_excessive_depth(self):
        value = []
        for _ in range(66):
            value = [value]
        with self.assertRaises(ValidationError) as ctx:
            canonical_json(value)
        self.assertEqual(ctx.exception.code, "MAX_DEPTH_EXCEEDED")

    def test_serialization_rejects_oversized_collection(self):
        with self.assertRaises(ValidationError) as ctx:
            canonical_json(list(range(10_001)))
        self.assertEqual(ctx.exception.code, "MAX_ITEMS_EXCEEDED")

    def test_serialization_rejects_oversized_aggregate_utf8_output(self):
        payload = ["x" * 10_000 for _ in range(30)]
        with self.assertRaises(ValidationError) as ctx:
            canonical_json(payload)
        self.assertEqual(ctx.exception.code, "OUTPUT_TOO_LARGE")

    def test_serialization_rejects_unpaired_unicode_surrogate(self):
        with self.assertRaises(ValidationError) as ctx:
            canonical_json({"value": "\ud800"})
        self.assertEqual(ctx.exception.code, "INVALID_UNICODE")

    def test_contract_text_rejects_unpaired_unicode_surrogate(self):
        with self.assertRaises(ValidationError) as ctx:
            ModelArchitecture(model_id="\ud800", total_parameters=1)
        self.assertEqual(ctx.exception.code, "INVALID_UNICODE")

    def test_negative_decimal_result_uses_out_of_range_code(self):
        p = FormulaProvenance("fitlab.negative", "1.0.0", "x")
        with self.assertRaises(ValidationError) as ctx:
            CalculationResult.calculated("negative", Decimal("-1"), "byte", p)
        self.assertEqual(ctx.exception.code, "OUT_OF_RANGE")


if __name__ == "__main__":
    unittest.main()
