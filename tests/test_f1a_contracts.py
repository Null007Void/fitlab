import json
import math
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
from fitlab_foundation.serialization import canonical_json
from fitlab_foundation.units import bytes_to_gb, bytes_to_gib, idealized_weight_payload_bytes
from fitlab_foundation.validation import ValidationError


class F1AContractTests(unittest.TestCase):
    def test_reference_weight_fixture_is_exact(self):
        self.assertEqual(idealized_weight_payload_bytes(1000, Decimal("4")), Decimal("500"))

    def test_binary_gib_reference_fixture_is_exact(self):
        self.assertEqual(bytes_to_gib(2**30), Decimal("1"))

    def test_decimal_gb_reference_fixture_is_exact(self):
        self.assertEqual(bytes_to_gb(10**9), Decimal("1"))
        self.assertNotEqual(bytes_to_gib(10**9), Decimal("1"))

    def test_fractional_idealized_payload_is_preserved_without_rounding(self):
        self.assertEqual(idealized_weight_payload_bytes(1, Decimal("3")), Decimal("0.375"))

    def test_boolean_is_not_accepted_as_integer(self):
        with self.assertRaises(ValidationError) as ctx:
            ModelArchitecture(model_id="synthetic", total_parameters=True)
        self.assertEqual(ctx.exception.code, "INVALID_TYPE")

    def test_float_is_not_accepted_for_exact_numeric_field(self):
        with self.assertRaises(ValidationError):
            idealized_weight_payload_bytes(1000, 4.0)

    def test_numeric_string_is_not_coerced(self):
        with self.assertRaises(ValidationError):
            ModelArchitecture(model_id="synthetic", total_parameters="1000")

    def test_non_finite_decimal_is_rejected(self):
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Workload(target_tokens_per_second=value)

    def test_negative_and_zero_positive_fields_are_rejected(self):
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ModelArchitecture(model_id="synthetic", total_parameters=value)

    def test_excessive_parameter_count_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            ModelArchitecture(model_id="synthetic", total_parameters=10**15 + 1)
        self.assertEqual(ctx.exception.code, "OUT_OF_RANGE")

    def test_unsupported_weight_precision_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            idealized_weight_payload_bytes(1000, Decimal("7"))
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_PRECISION")

    def test_model_rejects_active_parameters_above_total(self):
        with self.assertRaises(ValidationError):
            ModelArchitecture(
                model_id="synthetic-moe",
                total_parameters=100,
                active_parameters=101,
                architecture_kind=ArchitectureKind.MOE_DECODER,
            )

    def test_formula_provenance_is_versioned_and_nonempty(self):
        p = FormulaProvenance("fitlab.example", "1.0.0", "x + y")
        self.assertEqual(p.version, "1.0.0")
        with self.assertRaises(ValidationError):
            FormulaProvenance("", "1.0.0", "x")

    def test_unknown_result_has_no_numeric_value_and_machine_reason(self):
        result = CalculationResult.unknown(
            name="kv_cache_bytes",
            reasons=(Reason(ReasonCode.MISSING_METADATA, "layers"),),
        )
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertIsNone(result.value)
        self.assertEqual(result.reasons[0].code, ReasonCode.MISSING_METADATA)

    def test_calculated_result_requires_formula_value_and_unit(self):
        p = FormulaProvenance("fitlab.test", "1.0.0", "x")
        result = CalculationResult.calculated("x", 4, "byte", p)
        self.assertEqual(result.status, ResultStatus.CALCULATED)
        with self.assertRaises(ValidationError):
            CalculationResult(name="bad", status=ResultStatus.CALCULATED)

    def test_unknown_result_rejects_fake_value(self):
        with self.assertRaises(ValidationError):
            CalculationResult(
                name="bad",
                status=ResultStatus.UNKNOWN,
                value=1,
                unit="byte",
                reasons=(Reason(ReasonCode.MISSING_METADATA, "x"),),
            )

    def test_all_four_statuses_are_distinct(self):
        self.assertEqual(
            {s.value for s in ResultStatus},
            {"CALCULATED", "ESTIMATED", "UNKNOWN", "UNAVAILABLE"},
        )

    def test_unified_memory_is_not_added_to_host_ram(self):
        h = HardwareResources(
            host_ram_bytes=16 * 2**30,
            unified_shared_memory_bytes=8 * 2**30,
            accelerator_dedicated_bytes=0,
        )
        self.assertEqual(h.independent_physical_capacity_bytes(), 16 * 2**30)

    def test_hardware_contract_does_not_invent_measured_available_memory(self):
        h = HardwareResources(host_ram_bytes=16 * 2**30)
        self.assertIsNone(h.measured_available_host_bytes)

    def test_canonical_json_is_stable_and_decimal_is_string(self):
        p = FormulaProvenance("fitlab.test", "1.0.0", "x")
        result = CalculationResult.estimated("x", Decimal("0.375"), "byte", p)
        first = canonical_json(result)
        second = canonical_json(result)
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["value"], "0.375")
        self.assertEqual(first, json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False))

    def test_incompatible_enum_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            ModelArchitecture(
                model_id="synthetic",
                total_parameters=1000,
                architecture_kind="dense",
            )

    def test_workload_bounds_prevent_resource_exhaustion(self):
        with self.assertRaises(ValidationError):
            Workload(resident_sequences=1_000_001)
        with self.assertRaises(ValidationError):
            Workload(cached_tokens_per_sequence=10_000_001)

    def test_empty_model_identifier_is_rejected(self):
        with self.assertRaises(ValidationError):
            ModelArchitecture(model_id=" ", total_parameters=1000)


if __name__ == "__main__":
    unittest.main()
