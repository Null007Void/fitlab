import copy
import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from fitlab_evaluation.grader import grade,load_pack
from fitlab_evaluation.lemonade import IntegrationError,LemonadeClient,require_resources,build_request,MODEL
from fitlab_evaluation.run import evaluate
from test_f4_integration import FakeClient,GOOD_MEMORY,HEALTH,ROOT

class ReviewCorrectionTests(unittest.TestCase):
    def plan(self):
        d=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text());d['scenarios'][0]['model']['model_id']=MODEL
        return d
    def test_falsy_grader_metadata_never_passes(self):
        pack,_=load_pack(ROOT/'fixtures/tasks-v2.json')
        variants={'tool_calls':[{},0,False,''], 'function_call':[{},0,False,'',[]], 'refusal':[0,False,[],{}]}
        for c in pack['cases']:
            content=c['expected'] if type(c['expected']) is str else json.dumps(c['expected'])
            for field,values in variants.items():
                for value in values:
                    with self.subTest(case=c['id'],field=field,value=value):
                        self.assertFalse(grade(c,content,**{field:value})['passed'])
    def test_malformed_results_stop_without_metadata_overwrite(self):
        correct=FakeClient().complete(load_pack(ROOT/'fixtures/tasks-v2.json')[0]['cases'][0]['prompt'])
        bad=[None,1,'string',[],{}, {'response':{}}, {**correct,'case_id':'forged'}, {**correct,'repeat':42}]
        bad += [{**correct,'elapsed_seconds':v} for v in (-1,True,float('nan'),float('inf'),'0.1')]
        d=copy.deepcopy(correct);d['response']['model']='wrong';bad.append(d)
        d=copy.deepcopy(correct);d['response']['choices'][0]['message']['tool_calls']={};bad.append(d)
        for value in bad:
            with self.subTest(value_type=type(value).__name__):
                client=FakeClient();client.complete=lambda p:copy.deepcopy(value)
                results=[]
                for _ in range(2):
                    r=evaluate(self.plan(),1,client=client,memory=lambda:GOOD_MEMORY,pause=lambda _:None)
                    self.assertEqual(r['status'],'STOPPED');self.assertEqual(r['summary']['measured_count'],0)
                    self.assertEqual(r['rows'][0]['case_id'],'E1');self.assertEqual(r['rows'][0]['repeat'],1)
                    self.assertEqual(r['rows'][0]['status'],'FAILED');results.append(r['stop_reason'])
                self.assertEqual(results[0],results[1])
    def test_invalid_memory_and_health_zero_completions(self):
        for value in (None,[],False,'text',{}):
            client=FakeClient();r=evaluate(self.plan(),1,client=client,memory=lambda:value)
            self.assertEqual(client.calls,0);self.assertEqual(r['status'],'STOPPED')
        for value in (None,[],False,'text',{}, {**HEALTH,'version':'wrong'}):
            client=FakeClient();client.ready=lambda:value
            r=evaluate(self.plan(),1,client=client,memory=lambda:GOOD_MEMORY)
            self.assertEqual(client.calls,0);self.assertEqual(r['status'],'STOPPED')
    def test_budget_and_resource_rechecked_after_health(self):
        client=FakeClient();samples=iter([GOOD_MEMORY,{**GOOD_MEMORY,'available_physical_bytes':0}])
        r=evaluate(self.plan(),1,client=client,memory=lambda:next(samples))
        self.assertEqual(client.calls,0);self.assertEqual(r['status'],'STOPPED')
        client=FakeClient()
        with patch('fitlab_evaluation.run.time.monotonic',side_effect=[0,0,600]):
            r=evaluate(self.plan(),1,client=client,memory=lambda:GOOD_MEMORY)
        self.assertEqual(client.calls,0);self.assertEqual(r['status'],'STOPPED')
    def test_invalid_budget_rejected(self):
        for v in (float('nan'),float('inf'),True,'600',0,601):
            with self.assertRaises(ValueError):evaluate(self.plan(),1,client=FakeClient(),memory=lambda:GOOD_MEMORY,budget_seconds=v)
    def test_argument_and_prompt_failures_normalized(self):
        client=LemonadeClient()
        for args in ([],{},1,'"'):
            health=copy.deepcopy(HEALTH);health['all_models_loaded'][0]['recipe_options']['llamacpp_args']=args
            with patch.object(client,'request',return_value=health),self.assertRaises(IntegrationError):client.ready()
        with self.assertRaises(IntegrationError):client.complete('\ud800')

class TaskOnlyTests(unittest.TestCase):
    def test_no_plan_is_explicitly_unavailable_and_counts_each_case(self):
        client=FakeClient()
        r=evaluate(None,3,client=client,memory=lambda:GOOD_MEMORY,pause=lambda _:None)
        self.assertEqual(r['status'],'COMPLETED');self.assertEqual(r['execution_kind'],'SYNTHETIC_TEST')
        self.assertIsNone(r['planning_input']);self.assertIsNone(r['planning_output'])
        self.assertEqual(r['planning_status'],'UNAVAILABLE');self.assertEqual(client.calls,24)
        self.assertEqual(len(r['summary']['by_case']),8)
        for counts in r['summary']['by_case'].values():
            self.assertEqual(counts['planned_count'],3);self.assertEqual(counts['passed_count'],3)
    def test_malformed_supplied_plan_rejects_before_client_calls(self):
        client=FakeClient()
        for document in ({},'text',[],False):
            with self.assertRaises(ValueError):evaluate(document,1,client=client,memory=lambda:GOOD_MEMORY)
        self.assertEqual(client.calls,0)
    def test_task_only_low_memory_zero_calls(self):
        client=FakeClient()
        r=evaluate(None,3,client=client,memory=lambda:{**GOOD_MEMORY,'available_physical_bytes':0})
        self.assertEqual(client.calls,0);self.assertEqual(r['status'],'STOPPED')
        self.assertEqual(r['summary']['measured_count'],0)
        self.assertTrue(all(v['median_client_latency_seconds'] is None for v in r['summary']['by_case'].values()))
