import copy
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from fitlab_evaluation.lemonade import (CHECKPOINT, MODEL, VERSION, MIN_AVAILABLE, MAX_BODY,
                                        IntegrationError, LemonadeClient, require_resources, build_request)
from fitlab_evaluation.run import evaluate
from fitlab_evaluation.grader import load_pack
ROOT=Path(__file__).resolve().parents[1]
GOOD_MEMORY={'total_physical_bytes':16*2**30,'available_physical_bytes':6*2**30,
             'memory_load_percent':60,'available_commit_bytes':8*2**30}
HEALTH={'status':'ok','version':VERSION,'all_models_loaded':[
    {'model_name':MODEL,'checkpoint':CHECKPOINT,'device':'cpu','recipe':'llamacpp','loaded':True,
     'backend_alive':True,'backend_health':'ready','is_busy':False,'is_streaming':False,
     'recipe_options':{'ctx_size':2048,'llamacpp_backend':'cpu',
                       'llamacpp_args':'--parallel 1 --threads 2 --threads-batch 2'}}]}

class FakeClient:
    """Explicit mock; emitted records belong only to tests, never live evidence."""
    timeout=1
    def __init__(self,fail_at=None):self.calls=0;self.fail_at=fail_at
    def ready(self):return copy.deepcopy(HEALTH)
    def complete(self,prompt):
        self.calls+=1
        if self.calls==self.fail_at: raise IntegrationError('simulated timeout')
        case=next(c for c in load_pack(ROOT/'fixtures/tasks-v2.json')[0]['cases'] if c['prompt']==prompt)
        content=case['expected'] if type(case['expected']) is str else json.dumps(case['expected'])
        return {'elapsed_seconds':0.01,'request':build_request(prompt),'response':{'model':MODEL,'choices':[
            {'message':{'role':'assistant','content':content},'finish_reason':'stop'}]}}

class IntegrationTests(unittest.TestCase):
    def plan(self,direction='workload_to_hardware'):
        plan=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        plan['direction']=direction
        plan['scenarios'][0]['model']['model_id']=MODEL
        return plan
    def test_resource_gate(self):
        require_resources(GOOD_MEMORY)
        for change in ({'available_physical_bytes':MIN_AVAILABLE-1},{'available_commit_bytes':0},
                       {'memory_load_percent':90},{'total_physical_bytes':0},{'available_physical_bytes':True}):
            with self.subTest(change=change),self.assertRaises(IntegrationError):
                require_resources({**GOOD_MEMORY,**change})
    def test_both_journeys_and_three_repeats_mock_only(self):
        for direction in ('workload_to_hardware','hardware_to_workloads'):
            client=FakeClient()
            result=evaluate(self.plan(direction),3,client=client,memory=lambda:GOOD_MEMORY,pause=lambda _:None)
            self.assertEqual(result['status'],'COMPLETED')
            self.assertEqual(result['summary']['measured_count'],24)
            self.assertEqual(result['summary']['passed_count'],24)
            self.assertEqual(result['planning_output']['direction'],direction)
    def test_low_memory_makes_zero_calls(self):
        client=FakeClient()
        result=evaluate(self.plan(),3,client=client,memory=lambda:{**GOOD_MEMORY,'available_physical_bytes':0})
        self.assertEqual(client.calls,0);self.assertEqual(result['status'],'STOPPED')
        self.assertIsNone(result['summary']['median_client_latency_seconds'])
        self.assertEqual(result['summary']['failed_or_unrun_count'],24)
    def test_failure_preserves_prior_rows_and_no_retry(self):
        client=FakeClient(fail_at=2)
        result=evaluate(self.plan(),3,client=client,memory=lambda:GOOD_MEMORY,pause=lambda _:None)
        self.assertEqual(client.calls,2);self.assertEqual(result['status'],'STOPPED')
        self.assertEqual(result['summary']['measured_count'],1)
        self.assertEqual(result['rows'][1]['status'],'FAILED')
    def test_later_memory_failure_stops(self):
        client=FakeClient(); samples=iter([GOOD_MEMORY,GOOD_MEMORY,{**GOOD_MEMORY,'memory_load_percent':95}])
        result=evaluate(self.plan(),3,client=client,memory=lambda:next(samples),pause=lambda _:None)
        self.assertEqual(client.calls,1);self.assertEqual(result['status'],'STOPPED')
        self.assertEqual(result['summary']['measured_count'],1)
    def test_wrong_model_plan_rejected(self):
        d=self.plan();d['scenarios'][0]['model']['model_id']='other'
        with self.assertRaises(ValueError):evaluate(d,1,client=FakeClient(),memory=lambda:GOOD_MEMORY)
    def test_health_checks(self):
        client=LemonadeClient()
        with patch.object(client,'request',return_value=HEALTH): self.assertEqual(client.ready(),HEALTH)
        for change in ({'device':'gpu'},{'checkpoint':'other'},{'is_busy':True},{'loaded':False},
                       {'recipe_options':{'ctx_size':2048,'llamacpp_backend':'cpu','llamacpp_args':''}}):
            health=copy.deepcopy(HEALTH);health['all_models_loaded'][0].update(change)
            with patch.object(client,'request',return_value=health),self.assertRaises(IntegrationError):client.ready()
        for health in ({}, {**HEALTH,'version':'other'},{**HEALTH,'all_models_loaded':[]}):
            with patch.object(client,'request',return_value=health),self.assertRaises(IntegrationError):client.ready()
    def test_completion_validation(self):
        client=LemonadeClient()
        good={'model':MODEL,'choices':[{'message':{'role':'assistant','content':'OK'},'finish_reason':'stop'}]}
        with patch.object(client,'request',return_value=good):self.assertEqual(client.complete('test')['response'],good)
        for bad in ({'model':'other'}, {'model':MODEL,'choices':[]}, {'model':MODEL,'choices':[{'message':{'content':None}}]}):
            with patch.object(client,'request',return_value=bad),self.assertRaises(IntegrationError):client.complete('test')

class LocalTransportTests(unittest.TestCase):
    """Real HTTP on an ephemeral local test port; no model/runtime contacted."""
    def setUp(self):
        self.status=200;self.body=b'{"status":"ok"}';self.delay=0;self.count=0
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                owner.count+=1
                if owner.delay:
                    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                    try:
                        for _ in range(30):self.wfile.write(b' ');self.wfile.flush();time.sleep(owner.delay)
                    except (OSError,ConnectionError):pass
                    return
                self.send_response(owner.status);self.send_header('Content-Type','application/json');self.end_headers()
                try:self.wfile.write(owner.body)
                except (OSError,ConnectionError):pass
        self.server=HTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.client=LemonadeClient(port=self.server.server_port,timeout=0.2)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_real_local_http(self):self.assertEqual(self.client.request('GET','/api/v1/health'),{'status':'ok'})
    def test_redirect_no_retry(self):
        self.status=302
        with self.assertRaises(IntegrationError):self.client.request('GET','/api/v1/health')
        self.assertEqual(self.count,1)
    def test_large_response(self):
        self.body=b'x'*(MAX_BODY+1)
        with self.assertRaises(IntegrationError):self.client.request('GET','/api/v1/health')
    def test_malformed_response(self):
        for raw in (b'{"x":1,"x":2}',b'[]',b'\xff'):
            self.body=raw
            with self.assertRaises(IntegrationError):self.client.request('GET','/api/v1/health')
    def test_slow_trickle_total_deadline(self):
        self.delay=0.05;started=time.monotonic()
        with self.assertRaises(IntegrationError):self.client.request('GET','/api/v1/health')
        self.assertLess(time.monotonic()-started,1)

if __name__=='__main__':unittest.main()

class CheckpointTests(unittest.TestCase):
    def test_each_completed_row_is_checkpointed(self):
        d=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        d['scenarios'][0]['model']['model_id']=MODEL
        snapshots=[]
        result=evaluate(d,1,client=FakeClient(fail_at=3),memory=lambda:GOOD_MEMORY,
                        pause=lambda _:None,checkpoint=lambda r:snapshots.append(copy.deepcopy(r)))
        self.assertEqual(snapshots[0]['status'],'RUNNING')
        self.assertEqual(snapshots[-1]['status'],'STOPPED')
        self.assertTrue(any(len(r['rows'])==2 and r['rows'][-1]['status']=='MEASURED' for r in snapshots))
        self.assertEqual(result['summary']['measured_count'],2)
