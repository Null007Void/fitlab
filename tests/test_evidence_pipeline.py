import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fitlab_evaluation.artifacts import ArtifactError,load_json,publish_bundle,stable_json
from fitlab_evaluation.evidence import make_trust,trust_from_package_index,verify_record
from fitlab_evaluation.report import build_report,render_report,export_report
from fitlab_evaluation.run import evaluate
from test_f4_integration import FakeClient,GOOD_MEMORY,ROOT

class EvidencePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trust=make_trust('HEAD') if (ROOT/'.git').exists() else trust_from_package_index(ROOT)
        with patch('fitlab_evaluation.run.identity',return_value=cls.trust['source_sha256']):
            cls.record=evaluate(None,1,client=FakeClient(),memory=lambda:GOOD_MEMORY,pause=lambda _:None)
    def test_synthetic_never_becomes_measured(self):
        verified=verify_record(self.record,self.trust)
        self.assertFalse(verified['measurement_eligible'])
        p=build_report(self.trust,self.record)
        self.assertEqual(p['evaluation_state'],'SYNTHETIC_ONLY')
        self.assertEqual(p['capability_verdict'],'NOT_EVALUATED')
        self.assertTrue(all(c['value'] is None for c in p['claims']))
        self.assertEqual(render_report(p,self.trust,self.record),render_report(copy.deepcopy(p),self.trust,copy.deepcopy(self.record)))
    def test_empty_report_unknown_and_plan_estimates(self):
        plan=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        p=build_report(self.trust,plan=plan)
        self.assertIn('ESTIMATED',{c['evidence_class'] for c in p['claims']})
        self.assertIn('CALCULATED',{c['evidence_class'] for c in p['claims']})
        self.assertNotIn('MEASURED',{c['evidence_class'] for c in p['claims']})
    def test_wrong_source_grades_summary_identity_and_protocol_rejected(self):
        variants=[]
        for field,val in [('model','wrong'),('task_pack_sha256','0'*64),('run_id','bad'),('requested_repeats',True),('status','bad')]:
            r=copy.deepcopy(self.record);r[field]=val;variants.append(r)
        r=copy.deepcopy(self.record);r['summary']['passed_count']=0;variants.append(r)
        r=copy.deepcopy(self.record);r['rows'][0]['grade']['passed']=False;variants.append(r)
        r=copy.deepcopy(self.record);r['rows'][0]['repeat']=True;variants.append(r)
        r=copy.deepcopy(self.record);r['rows'].pop();variants.append(r)
        r=copy.deepcopy(self.record);r['protocol']['warmup_requests']=1;variants.append(r)
        r=copy.deepcopy(self.record);r['source_sha256']['extra.py']='0'*64;variants.append(r)
        for r in variants:
            with self.subTest(field=r.get('status')),self.assertRaises(ArtifactError):verify_record(r,self.trust)
    def test_partial_and_stop_denominator_preserved(self):
        with patch('fitlab_evaluation.run.identity',return_value=self.trust['source_sha256']):
            record=evaluate(None,3,client=FakeClient(fail_at=3),memory=lambda:GOOD_MEMORY,pause=lambda _:None)
        p=verify_record(record,self.trust)
        self.assertEqual(p['summary']['planned_count'],24)
        self.assertEqual(p['summary']['measured_count'],2)
        self.assertFalse(p['complete_protocol'])
    def test_corrupt_json_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.json'
            for raw in (b'{"x":1,"x":2}', b'\xff',b'['*100+b']'*100,b'{"x":NaN}'):
                path.write_bytes(raw)
                with self.assertRaises(ArtifactError):load_json(path)
    def test_bundle_atomicity_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)/'report'
            with patch('fitlab_evaluation.artifacts._rename_new',side_effect=OSError('fault')):
                with self.assertRaises(ArtifactError):export_report(dest,self.trust)
            self.assertFalse(dest.exists());self.assertEqual(list(Path(directory).iterdir()),[])
            export_report(dest,self.trust)
            before={p.name:p.read_bytes() for p in dest.iterdir()}
            with self.assertRaises(ArtifactError):export_report(dest,self.trust)
            self.assertEqual(before,{p.name:p.read_bytes() for p in dest.iterdir()})
    def test_html_and_forged_report(self):
        p=build_report(self.trust)
        p['claims'][0]['value']=100
        with self.assertRaises(ArtifactError):render_report(p,self.trust)
        plan=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        plan['scenarios'][0]['scenario_id']='<script>alert(1)</script>'
        p=build_report(self.trust,plan=plan)
        rendered=render_report(p,self.trust,plan=plan)
        self.assertNotIn('<script>',rendered)

    def test_replay_rejects_memory_and_time_contradictions(self):
        variants=[]
        r=copy.deepcopy(self.record);r['resource_samples'][0]['memory_load_percent']=97;variants.append(r)
        r=copy.deepcopy(self.record);r['resource_samples']=r['resource_samples'][:16];variants.append(r)
        r=copy.deepcopy(self.record);r['rows'][0]['started_at']='2099-01-01T00:00:00+00:00';variants.append(r)
        r=copy.deepcopy(self.record);r['rows'][1]['started_at']='2000-01-01T00:00:00+00:00';variants.append(r)
        for r in variants:
            with self.assertRaises(ArtifactError):verify_record(r,self.trust)
    def test_post_completion_resource_stop_remains_partial(self):
        for last in ({**GOOD_MEMORY,'memory_load_percent':97},None):
            samples=iter([GOOD_MEMORY,GOOD_MEMORY,last])
            with patch('fitlab_evaluation.run.identity',return_value=self.trust['source_sha256']):
                r=evaluate(None,3,client=FakeClient(),memory=lambda:next(samples),pause=lambda _:None)
            v=verify_record(r,self.trust)
            self.assertEqual(v['summary']['measured_count'],1)
            self.assertFalse(v['complete_protocol'])
    def test_model_estimate_attribution_and_no_override(self):
        plan=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        with self.assertRaises(ArtifactError):build_report(self.trust,self.record,plan)
        p=build_report(self.trust,plan=plan)
        text=render_report(p,self.trust,plan=plan)
        self.assertIn(plan['scenarios'][0]['model']['model_id'],text)
    def test_local_git_trust_binding(self):
        if not (ROOT/'.git').exists():self.skipTest('portable archive uses external snapshot')
        for key,val in [('source_commit','0'*40),('source_tree','0'*40)]:
            trust=copy.deepcopy(self.trust);trust[key]=val
            with self.assertRaises(ArtifactError):build_report(trust)

    def test_replay_rejects_latency_beyond_recorded_deadline(self):
        from fitlab_evaluation.evidence import summarize
        r=copy.deepcopy(self.record);r['rows'][0]['elapsed_seconds']=60
        pack=json.loads(self.trust['task_pack_text'])
        r['summary']=summarize(r['rows'],pack['cases'],1)
        with self.assertRaisesRegex(ArtifactError,'INCONSISTENT_TIMING'):verify_record(r,self.trust)

    def test_raw_responses_are_individually_hashed_and_bound(self):
        from fitlab_evaluation.artifacts import digest,stable_json
        for row in self.record['rows']:
            self.assertEqual(row['response_sha256'],
                             digest(stable_json(row['response']).encode('utf-8')))
        altered=copy.deepcopy(self.record)
        altered['rows'][0]['response']['choices'][0]['message']['content']='tampered'
        with self.assertRaisesRegex(ArtifactError,'RESPONSE_HASH_MISMATCH'):
            verify_record(altered,self.trust)

    def test_replay_rejects_impossible_budget_and_live_pause(self):
        r=copy.deepcopy(self.record);r['protocol']['session_budget_seconds']=1
        with self.assertRaisesRegex(ArtifactError,'IMPOSSIBLE_SESSION_BUDGET'):verify_record(r,self.trust)
        # A synthetic fast harness cannot become a plausible live record by a label edit.
        r=copy.deepcopy(self.record);r['execution_kind']='LOCAL_RUNTIME'
        with self.assertRaisesRegex(ArtifactError,'MISSING_INTER_REQUEST_PAUSE'):verify_record(r,self.trust)
