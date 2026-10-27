import copy
import unittest
from fitlab_evaluation.passport import build_passport,render,canonical

FACTS={'schema_version':'fitlab-passport-facts-v1','project':'Lemonade FitLab','source_commit':'a'*40,
       'stages':[{'id':f'F{i}','status':'REVIEW_PENDING','detail':'No capability claim.'} for i in range(1,9)],
       'evidence':['Offline engineering tests only.'],'limitations':['No F5 measurements.']}

class PassportTests(unittest.TestCase):
    def test_deterministic_and_unmeasured(self):
        a=build_passport(FACTS);b=build_passport(copy.deepcopy(FACTS))
        self.assertEqual(canonical(a),canonical(b));self.assertEqual(render(a),render(b))
        self.assertIsNone(a['observations'])
        self.assertTrue(all(v is None for v in a['measurement_placeholders'].values()))
        self.assertIn('Capability not yet evaluated',render(a))
    def test_html_escapes_untrusted_text(self):
        facts=copy.deepcopy(FACTS);facts['evidence']=['<script>alert("x")</script>']
        output=render(build_passport(facts))
        self.assertNotIn('<script>',output);self.assertIn('&lt;script&gt;',output)
        self.assertNotIn('src=',output);self.assertNotIn('href=',output)
    def test_forged_measurements_rejected(self):
        p=build_passport(FACTS);p['measurement_placeholders']['task_pass_rate']=1
        with self.assertRaises(ValueError):render(p)
        p=build_passport(FACTS);p['observations']=[{'passed':True}]
        with self.assertRaises(ValueError):render(p)
    def test_invalid_facts_rejected(self):
        for key,value in (('source_commit','fake'),('stages',[]),('evidence',['\ud800']),('observations',[])):
            facts=copy.deepcopy(FACTS);facts[key]=value
            with self.assertRaises((ValueError,UnicodeError)):build_passport(facts)
