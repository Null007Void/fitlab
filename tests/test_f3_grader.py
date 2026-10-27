import copy
import json
import tempfile
import unittest
from pathlib import Path
from fitlab_evaluation.grader import grade, load_pack
PACK = Path(__file__).resolve().parents[1]/'fixtures/tasks-v2.json'

class GraderTests(unittest.TestCase):
    def setUp(self): self.cases = load_pack(PACK)[0]['cases']

    def test_all_frozen_answers_and_wrong_answers(self):
        for case in self.cases:
            expected=case['expected']
            answer=expected if type(expected) is str else json.dumps(expected)
            with self.subTest(case=case['id']):
                self.assertTrue(grade(case,answer)['passed'])
                for wrong in ('', '{}', 'I passed', answer+' extra', '{"passed":true,"score":1}', None):
                    self.assertFalse(grade(case,wrong)['passed'])
                for overrides in ({'tool_calls':[{'name':'delete_all_files'}]}, {'function_call':{'name':'x'}}, {'finish_reason':'length'}, {'refusal':'refused'}):
                    self.assertFalse(grade(case,answer,**overrides)['passed'])

    def test_json_schema_strictness(self):
        case=self.cases[0]
        for answer in ('{"device":"Orchid-13","ram_gb":16.0,"os":"Windows 11"}', '{"device":"Orchid-13","ram_gb":16,"ram_gb":16,"os":"Windows 11"}', '```json\n'+json.dumps(case['expected'])+'\n```', json.dumps({**case['expected'],'invented':'x'})):
            self.assertFalse(grade(case,answer)['passed'])
        case={'id':'bool-trap','expected':{'value':1}}
        self.assertFalse(grade(case,'{"value":true}')['passed'])

    def test_malformed_and_resource_bounds(self):
        for content in ('\ud800','x'*65537, '['*2000+']'*2000, '{"v":NaN}', '{"v":'+ '9'*5000+'}'):
            self.assertFalse(grade(self.cases[0],content)['passed'])

    def test_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'tasks.json'; p.write_bytes(PACK.read_bytes()+b' ')
            p.with_suffix('.sha256').write_text(PACK.with_suffix('.sha256').read_text())
            with self.assertRaises(ValueError): load_pack(p)

if __name__ == '__main__': unittest.main()
