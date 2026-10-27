import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'examples/f2_workload_to_hardware.json').read_text())

class RecoveryTests(unittest.TestCase):
    def cli(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_bytes(payload)
            return subprocess.run([sys.executable, '-m', 'fitlab_foundation.planner_cli', '--input', str(path)], cwd=ROOT, capture_output=True, timeout=5)

    def assert_error(self, payload):
        a, b = self.cli(payload), self.cli(payload)
        self.assertEqual(a.returncode, 2, a.stderr[:1000])
        self.assertEqual(a.stderr, b'')
        self.assertEqual(a.stdout, b.stdout)
        self.assertLess(len(a.stdout), 2048)
        self.assertEqual(json.loads(a.stdout)['status'], 'ERROR')
        self.assertNotEqual(json.loads(a.stdout)['error']['code'], 'INPUT_IO_ERROR')

    def test_reported_enum_and_surrogate(self):
        for value in ('x'*20000, '\ud800', '\udfff'):
            with self.subTest(value_length=len(value)):
                d = copy.deepcopy(BASE)
                d['scenarios'][0]['model']['architecture_kind'] = value
                self.assert_error(json.dumps(d).encode())

    def test_huge_integer(self):
        self.assert_error(b'{"schema_version":'+b'9'*5000+b'}')

    def test_deep_json(self):
        self.assert_error(b'['*2000+b'0'+b']'*2000)

    def test_hostile_unknown_keys(self):
        for key in ('x'*20000, '\ud800'):
            d = copy.deepcopy(BASE); d[key] = 1
            self.assert_error(json.dumps(d).encode())

    def test_ambiguous_and_nonstandard_json(self):
        for payload in (b'{"schema_version":1,"schema_version":1}', b'NaN', b'Infinity', b'-Infinity', b'1e99999', b'1.5', b'\xff', b'['*33+b']'*33):
            with self.subTest(payload=payload[:80]): self.assert_error(payload)

    def test_strings_are_not_structural_nesting(self):
        d = copy.deepcopy(BASE)
        d['scenarios'][0]['runtime_overhead_basis'] = '[{'*100 + '\\"' + '}]'*100
        result = self.cli(json.dumps(d).encode())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_decimal_complexity(self):
        for val in ('9'*20000, '1e999999999999999999999', 'NaN', 'Infinity'):
            d=copy.deepcopy(BASE); d['scenarios'][0]['weight_bits_per_parameter']=val
            self.assert_error(json.dumps(d).encode())

if __name__ == '__main__': unittest.main()
