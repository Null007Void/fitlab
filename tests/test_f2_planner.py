import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from decimal import Decimal, localcontext
from io import StringIO
from pathlib import Path

from fitlab_foundation.contracts import (
    ArchitectureKind,
    AttentionMechanism,
    ModelArchitecture,
    Workload,
)
from fitlab_foundation.planner import (
    PlanningScenario,
    PlanningStatus,
    plan_hardware_to_workloads,
    plan_workload_to_hardware,
)
from fitlab_foundation.planner_cli import MAX_INPUT_BYTES, MAX_SCENARIOS, main, run_document
from fitlab_foundation.serialization import canonical_json
from fitlab_foundation.validation import ValidationError


class WorkloadToHardwarePlannerTests(unittest.TestCase):
    def test_supported_workload_produces_exact_minimum_declared_memory(self):
        scenario = PlanningScenario(
            scenario_id="dense-demo",
            model=ModelArchitecture(
                model_id="dense-demo",
                total_parameters=1_000,
                layers=2,
                query_heads=8,
                kv_heads=2,
                head_dimension=4,
                architecture_kind=ArchitectureKind.DENSE_DECODER,
                attention_mechanism=AttentionMechanism.STANDARD_FULL,
            ),
            workload=Workload(
                resident_sequences=1,
                cached_tokens_per_sequence=10,
                kv_bytes_per_element=2,
                target_tokens_per_second=Decimal("5"),
                declared_bytes_reloaded_per_token=500,
                residency_assumption="Synthetic exact planner fixture.",
            ),
            weight_bits_per_parameter=Decimal("4"),
            explicit_runtime_overhead_bytes=360,
            runtime_overhead_basis="Synthetic measured runtime allowance.",
        )

        result = plan_workload_to_hardware(scenario)

        self.assertEqual(result.status, PlanningStatus.COMPLETE)
        self.assertEqual(result.minimum_declared_memory_bytes, Decimal("1500"))
        self.assertEqual(result.target_compute_flops_per_second, Decimal("10000"))
        self.assertEqual(result.conditional_decode_bandwidth_bytes_per_second, Decimal("2500"))
        self.assertIn("does not predict achieved throughput", result.limitations)

    def test_unknown_architecture_preserves_unknown_instead_of_claiming_fit(self):
        scenario = PlanningScenario(
            scenario_id="unknown-model",
            model=ModelArchitecture(model_id="unknown", total_parameters=1_000),
            workload=Workload(target_tokens_per_second=Decimal("5")),
            weight_bits_per_parameter=Decimal("4"),
            explicit_runtime_overhead_bytes=100,
            runtime_overhead_basis="Synthetic allowance.",
        )
        result = plan_workload_to_hardware(scenario)
        self.assertEqual(result.status, PlanningStatus.UNKNOWN)
        self.assertIsNone(result.minimum_declared_memory_bytes)
        self.assertTrue(result.reasons)


class HardwareToWorkloadPlannerTests(unittest.TestCase):
    def scenario(self, scenario_id, budget, overhead=360):
        return PlanningScenario(
            scenario_id=scenario_id,
            model=ModelArchitecture(
                model_id=scenario_id,
                total_parameters=1_000,
                layers=2,
                query_heads=8,
                kv_heads=2,
                head_dimension=4,
                architecture_kind=ArchitectureKind.DENSE_DECODER,
                attention_mechanism=AttentionMechanism.STANDARD_FULL,
            ),
            workload=Workload(
                resident_sequences=1,
                cached_tokens_per_sequence=10,
                kv_bytes_per_element=2,
                target_tokens_per_second=Decimal("5"),
                declared_bytes_reloaded_per_token=500,
                residency_assumption="Synthetic exact planner fixture.",
            ),
            weight_bits_per_parameter=Decimal("4"),
            explicit_runtime_overhead_bytes=overhead,
            runtime_overhead_basis="Synthetic measured runtime allowance.",
            planning_memory_budget_bytes=budget,
        )

    def test_candidates_are_ranked_compatibly_by_exact_headroom(self):
        results = plan_hardware_to_workloads((
            self.scenario("tight", 1_500),
            self.scenario("roomy", 2_000),
            self.scenario("too-small", 1_499),
        ))
        self.assertEqual([result.scenario_id for result in results], ["roomy", "tight", "too-small"])
        self.assertEqual(results[0].status, PlanningStatus.COMPATIBLE)
        self.assertEqual(results[0].headroom_bytes, Decimal("500"))
        self.assertEqual(results[1].headroom_bytes, Decimal("0"))
        self.assertEqual(results[2].status, PlanningStatus.INCOMPATIBLE)
        self.assertEqual(results[2].headroom_bytes, Decimal("-1"))

    def test_incomplete_requirements_cannot_be_ranked_compatible(self):
        complete = self.scenario("complete", 2_000)
        incomplete = replace(
            self.scenario("missing-targets", 2_000),
            workload=Workload(
                resident_sequences=1,
                cached_tokens_per_sequence=10,
                kv_bytes_per_element=2,
            ),
        )
        results = plan_hardware_to_workloads((incomplete, complete))
        by_id = {result.scenario_id: result for result in results}
        self.assertEqual(by_id["complete"].status, PlanningStatus.COMPATIBLE)
        self.assertEqual(by_id["missing-targets"].status, PlanningStatus.UNKNOWN)
        self.assertEqual([result.scenario_id for result in results], ["complete", "missing-targets"])

    def test_large_fractional_headroom_is_independent_of_decimal_context(self):
        scenario = PlanningScenario(
            scenario_id="large-fractional",
            model=ModelArchitecture(
                model_id="large-fractional",
                total_parameters=999_999_999_999_999,
                layers=1,
                query_heads=1,
                kv_heads=1,
                head_dimension=1,
                architecture_kind=ArchitectureKind.DENSE_DECODER,
                attention_mechanism=AttentionMechanism.STANDARD_FULL,
            ),
            workload=Workload(
                resident_sequences=1,
                cached_tokens_per_sequence=1,
                kv_bytes_per_element=1,
                target_tokens_per_second=Decimal("1"),
                declared_bytes_reloaded_per_token=1,
                residency_assumption="Exact large fractional fixture.",
            ),
            weight_bits_per_parameter=Decimal("4"),
            explicit_runtime_overhead_bytes=0,
            runtime_overhead_basis="Zero-byte synthetic allowance.",
            planning_memory_budget_bytes=10**21,
        )
        with localcontext() as context:
            context.prec = 6
            result = plan_hardware_to_workloads((scenario,))[0]
        self.assertEqual(result.minimum_declared_memory_bytes, Decimal("500000000000001.5"))
        self.assertEqual(result.headroom_bytes, Decimal("999999499999999999998.5"))


class PlannerDocumentTests(unittest.TestCase):
    def document(self):
        return {
            "schema_version": 1,
            "direction": "workload_to_hardware",
            "scenarios": [{
                "scenario_id": "document-demo",
                "model": {
                    "model_id": "document-demo",
                    "total_parameters": 1000,
                    "layers": 2,
                    "query_heads": 8,
                    "kv_heads": 2,
                    "head_dimension": 4,
                    "architecture_kind": "DENSE_DECODER",
                    "attention_mechanism": "STANDARD_FULL",
                },
                "workload": {
                    "resident_sequences": 1,
                    "cached_tokens_per_sequence": 10,
                    "kv_bytes_per_element": 2,
                    "target_tokens_per_second": "5",
                    "declared_bytes_reloaded_per_token": 500,
                    "residency_assumption": "Synthetic exact document fixture.",
                },
                "weight_bits_per_parameter": "4",
                "explicit_runtime_overhead_bytes": 360,
                "runtime_overhead_basis": "Synthetic measured runtime allowance.",
            }],
        }

    def test_document_output_is_canonical_and_repeatable(self):
        first = canonical_json(run_document(self.document()))
        second = canonical_json(run_document(json.loads(json.dumps(self.document()))))
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["results"][0]["minimum_declared_memory_bytes"], "1500")
        self.assertEqual(parsed["results"][0]["status"], "COMPLETE")

    def test_float_input_is_rejected_instead_of_rounded(self):
        document = self.document()
        document["scenarios"][0]["weight_bits_per_parameter"] = 4.0
        with self.assertRaises(ValidationError):
            run_document(document)

    def test_non_string_direction_is_controlled_validation_error(self):
        document = self.document()
        document["direction"] = []
        with self.assertRaises(ValidationError):
            run_document(document)

    def test_duplicate_scenario_identity_is_rejected(self):
        document = self.document()
        document["scenarios"].append(json.loads(json.dumps(document["scenarios"][0])))
        with self.assertRaises(ValidationError):
            run_document(document)

    def test_missing_hardware_budget_remains_unknown(self):
        document = self.document()
        document["direction"] = "hardware_to_workloads"
        output = run_document(document)
        self.assertEqual(output["results"][0].status, PlanningStatus.UNKNOWN)
        self.assertIsNone(output["results"][0].headroom_bytes)

    def test_scenario_count_is_rejected_before_scenario_parsing(self):
        document = self.document()
        document["scenarios"] = [{}] * (MAX_SCENARIOS + 1)
        with self.assertRaises(ValidationError):
            run_document(document)

    def test_invalid_json_cli_returns_controlled_canonical_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text("{bad", encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["--input", str(path)])
        self.assertEqual(exit_code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "ERROR")
        self.assertEqual(payload["error"]["code"], "INVALID_JSON")

    def test_oversized_cli_input_is_rejected_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.json"
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["--input", str(path)])
        self.assertEqual(exit_code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["error"]["code"], "INPUT_TOO_LARGE")

    def test_valid_but_overlarge_output_returns_canonical_error(self):
        document = self.document()
        document["direction"] = "hardware_to_workloads"
        scenarios = []
        for index in range(MAX_SCENARIOS):
            scenario = json.loads(json.dumps(document["scenarios"][0]))
            scenario["scenario_id"] = f"large-output-{index:03d}"
            scenario["model"]["model_id"] = scenario["scenario_id"]
            scenario["runtime_overhead_basis"] = "x" * 4096
            scenario["planning_memory_budget_bytes"] = 2000
            scenarios.append(scenario)
        document["scenarios"] = scenarios
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large-output.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertLessEqual(path.stat().st_size, MAX_INPUT_BYTES)
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["--input", str(path)])
        self.assertEqual(exit_code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "ERROR")
        self.assertEqual(payload["error"]["code"], "OUTPUT_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
