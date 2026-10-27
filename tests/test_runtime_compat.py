import copy
import unittest
from argparse import Namespace
from unittest.mock import patch

from fitlab_evaluation.cli import _gate
from fitlab_evaluation.lemonade import (
    CHECKPOINT,
    MODEL,
    IntegrationError,
    LemonadeClient,
    validate_health,
    validate_runtime_stats,
    validate_system_stats,
    classify_model_discovery,
)


BASE_HEALTH = {
    "status": "ok",
    "version": "2026.42.1",
    "all_models_loaded": [
        {
            "model_name": MODEL,
            "checkpoint": CHECKPOINT,
            "device": "cpu",
            "recipe": "llamacpp",
            "loaded": True,
            "backend_alive": True,
            "backend_health": "ready",
            "is_busy": False,
            "is_streaming": False,
            "recipe_options": {
                "ctx_size": 2048,
                "llamacpp_backend": "cpu",
                "llamacpp_args": "--parallel 1 --threads 2 --threads-batch 2",
            },
        }
    ],
}


class RuntimeCompatibilityTests(unittest.TestCase):
    def test_health_accepts_only_preserved_and_target_versions(self):
        for version in ("2026.42.1", "2026.43.3"):
            with self.subTest(version=version):
                health = copy.deepcopy(BASE_HEALTH)
                health["version"] = version
                self.assertEqual(validate_health(health)["version"], version)
        health = copy.deepcopy(BASE_HEALTH)
        health["version"] = "2026.44.0"
        with self.assertRaisesRegex(IntegrationError, "version mismatch"):
            validate_health(health)

    def test_stats_separate_live_estimate_from_completed_decode(self):
        normalized = validate_runtime_stats(
            {
                "time_to_first_token": 0.25,
                "tokens_per_second": 31.5,
                "input_tokens": 40,
                "output_tokens": 12,
                "live": {
                    "active_requests": 1,
                    "estimated_tokens_per_second": 27.25,
                },
            }
        )
        self.assertEqual(normalized["live"]["active_requests"], 1)
        self.assertEqual(normalized["live"]["estimated_tokens_per_second"], 27.25)
        self.assertEqual(normalized["completed"]["decode_tokens_per_second"], 31.5)
        self.assertIsNone(normalized["completed"]["prefill_tokens_per_second"])
        self.assertEqual(normalized["live"]["measurement_kind"], "best_effort_stream_estimate")
        self.assertEqual(normalized["completed"]["decode_measurement_kind"], "completed_request_stat")

    def test_stats_missing_optional_fields_remain_unknown(self):
        normalized = validate_runtime_stats({})
        self.assertIsNone(normalized["live"]["active_requests"])
        self.assertIsNone(normalized["live"]["estimated_tokens_per_second"])
        self.assertIsNone(normalized["completed"]["decode_tokens_per_second"])
        self.assertIsNone(normalized["completed"]["prefill_tokens_per_second"])

    def test_stats_reject_malformed_live_values(self):
        for live in (
            {"active_requests": True, "estimated_tokens_per_second": 1.0},
            {"active_requests": -1, "estimated_tokens_per_second": 1.0},
            {"active_requests": 1, "estimated_tokens_per_second": float("nan")},
            {"active_requests": 1, "estimated_tokens_per_second": -0.1},
        ):
            with self.subTest(live=live), self.assertRaises(IntegrationError):
                validate_runtime_stats({"live": live})

    def test_system_stats_preserve_primary_gpu_identity_and_memory_kind(self):
        normalized = validate_system_stats(
            {
                "cpu_percent": 11.0,
                "memory_gb": 7.5,
                "gpu_percent": 25.0,
                "vram_gb": 3.0,
                "npu_percent": None,
                "primary_gpu_id": "amd:pci:00.0",
                "gpus": [
                    {
                        "id": "amd:pci:00.0",
                        "vendor": "amd",
                        "name": "AMD Radeon",
                        "memory_type": "shared",
                        "gpu_percent": 25.0,
                        "memory_total_gb": 120.0,
                        "memory_used_gb": 3.0,
                    }
                ],
            }
        )
        self.assertEqual(normalized["primary_gpu_id"], "amd:pci:00.0")
        self.assertEqual(normalized["primary_gpu"]["memory_type"], "shared")
        self.assertEqual(normalized["primary_gpu"]["memory_used_gb"], 3.0)
        self.assertFalse(normalized["inference_device_verified"])

    def test_system_stats_keep_unavailable_telemetry_unknown(self):
        normalized = validate_system_stats(
            {"cpu_percent": None, "memory_gb": 6.0, "gpu_percent": None,
             "vram_gb": None, "npu_percent": None}
        )
        self.assertIsNone(normalized["gpu_percent"])
        self.assertIsNone(normalized["vram_gb"])
        self.assertIsNone(normalized["primary_gpu"])
        self.assertEqual(normalized["device_attribution"], "unverified")

    def test_system_stats_reject_inconsistent_primary_or_memory(self):
        bad_primary = {
            "memory_gb": 1.0,
            "primary_gpu_id": "missing",
            "gpus": [{"id": "gpu0", "vendor": "intel", "name": "Intel GPU",
                      "memory_type": "unknown", "gpu_percent": None,
                      "memory_total_gb": None, "memory_used_gb": None}],
        }
        with self.assertRaises(IntegrationError):
            validate_system_stats(bad_primary)
        bad_memory = copy.deepcopy(bad_primary)
        bad_memory["primary_gpu_id"] = "gpu0"
        bad_memory["gpus"][0]["memory_total_gb"] = 2.0
        bad_memory["gpus"][0]["memory_used_gb"] = 3.0
        with self.assertRaises(IntegrationError):
            validate_system_stats(bad_memory)

    def test_model_discovery_distinguishes_hidden_from_unsupported(self):
        listed = classify_model_discovery({"data": [{"id": MODEL}]})
        self.assertEqual(listed["status"], "AVAILABLE_LISTED")
        hidden = classify_model_discovery({"data": []})
        self.assertEqual(hidden["status"], "NOT_LISTED")
        self.assertFalse(hidden["install_attempted"])
        unsupported = classify_model_discovery(
            {"data": []},
            error={"error": {"type": "model_not_supported",
                              "code": "model_not_supported",
                              "requested_model": MODEL}},
        )
        self.assertEqual(unsupported["status"], "UNSUPPORTED")
        self.assertFalse(unsupported["install_attempted"])

    def test_model_discovery_rejects_malformed_catalog(self):
        for payload in ({}, {"data": {}}, {"data": [MODEL]},
                        {"data": [{"id": True}]}, {"data": [{"id": MODEL}, {"id": MODEL}]}):
            with self.subTest(payload=payload), self.assertRaises(IntegrationError):
                classify_model_discovery(payload)

    def test_client_compatibility_snapshot_uses_read_only_loopback_endpoints(self):
        client = LemonadeClient()
        stats = {"tokens_per_second": 20.0, "live": {
            "active_requests": 0, "estimated_tokens_per_second": 0.0}}
        system = {"memory_gb": 8.0, "gpu_percent": None, "vram_gb": None,
                  "cpu_percent": None, "npu_percent": None}
        catalog = {"data": [{"id": MODEL}]}
        with patch.object(client, "request", side_effect=[BASE_HEALTH, stats, system, catalog]) as request:
            snapshot = client.compatibility_snapshot()
        self.assertEqual(snapshot["runtime_version"], "2026.42.1")
        self.assertEqual(snapshot["model_discovery"]["status"], "AVAILABLE_LISTED")
        self.assertEqual(
            [call.args[:2] for call in request.call_args_list],
            [("GET", "/api/v1/health"), ("GET", "/api/v1/stats"),
             ("GET", "/api/v1/system-stats"),
             ("GET", "/api/v1/models?show_all=true")],
        )

    def test_gate_reports_preserved_and_target_runtime_versions(self):
        memory = {"total_physical_bytes": 16 * 2**30,
                  "available_physical_bytes": 6 * 2**30,
                  "memory_load_percent": 60,
                  "available_commit_bytes": 8 * 2**30}
        with patch("fitlab_evaluation.lemonade.windows_memory", return_value=memory):
            gate = _gate(Namespace(output_dir=None))
        self.assertEqual(gate["runtime_version_retained"], "2026.42.1")
        self.assertEqual(gate["runtime_version_target"], "2026.43.3")
        self.assertEqual(gate["runtime_versions_supported"], ["2026.42.1", "2026.43.3"])


if __name__ == "__main__":
    unittest.main()
