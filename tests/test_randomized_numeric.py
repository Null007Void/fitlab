import random
import unittest
from decimal import Decimal

from fitlab_foundation.contracts import (
    ArchitectureKind,
    AttentionMechanism,
    ModelArchitecture,
    ResultStatus,
    Workload,
)
from fitlab_foundation.requirements import (
    calculate_ideal_weight_payload,
    calculate_standard_kv_cache,
)


class DeterministicRandomizedNumericTests(unittest.TestCase):
    def test_1500_seeded_weight_and_kv_fixtures_match_exact_arithmetic(self):
        rng = random.Random(20261019)
        supported_bits = (1, 2, 3, 4, 5, 6, 8, 16, 32)

        for fixture_id in range(750):
            parameters = rng.randint(1, 10**12)
            bits = rng.choice(supported_bits)
            model = ModelArchitecture(
                model_id=f"weight-{fixture_id}",
                total_parameters=parameters,
            )
            result = calculate_ideal_weight_payload(model, Decimal(bits))
            self.assertEqual(result.status, ResultStatus.ESTIMATED)
            self.assertEqual(
                result.value,
                Decimal(parameters) * Decimal(bits) / Decimal(8),
            )

        for fixture_id in range(750):
            layers = rng.randint(1, 256)
            query_heads = rng.randint(1, 256)
            kv_heads = rng.randint(1, query_heads)
            head_dimension = rng.randint(1, 512)
            resident_sequences = rng.randint(1, 32)
            cached_tokens = rng.randint(1, 32_768)
            bytes_per_element = rng.choice((1, 2, 4, 8))
            model = ModelArchitecture(
                model_id=f"kv-{fixture_id}",
                total_parameters=rng.randint(1, 10**12),
                layers=layers,
                query_heads=query_heads,
                kv_heads=kv_heads,
                head_dimension=head_dimension,
                architecture_kind=ArchitectureKind.DENSE_DECODER,
                attention_mechanism=AttentionMechanism.STANDARD_FULL,
            )
            workload = Workload(
                resident_sequences=resident_sequences,
                cached_tokens_per_sequence=cached_tokens,
                kv_bytes_per_element=bytes_per_element,
            )
            result = calculate_standard_kv_cache(model, workload)
            self.assertEqual(result.status, ResultStatus.CALCULATED)
            self.assertEqual(
                result.value,
                2
                * layers
                * kv_heads
                * head_dimension
                * resident_sequences
                * cached_tokens
                * bytes_per_element,
            )


if __name__ == "__main__":
    unittest.main()
