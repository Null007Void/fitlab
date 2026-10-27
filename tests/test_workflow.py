"""Offline orchestration tests: no model/runtime services are contacted."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
from fitlab_evaluation.artifacts import ArtifactError,stable_json
from fitlab_evaluation.workflow import execute,safe_runtime_config
from fitlab_evaluation.lemonade import LemonadeClient
from fitlab_evaluation.evidence import make_trust,trust_from_package_index
from test_f4_integration import GOOD_MEMORY,HEALTH,ROOT
from fitlab_evaluation.lemonade import MODEL

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.trust=make_trust('HEAD') if (ROOT/'.git').exists() else trust_from_package_index(ROOT)
    def execute(self,path,**kwargs):
        with patch('fitlab_evaluation.workflow.identity',return_value=self.trust['source_sha256']):
            return execute(path,self.trust,**kwargs)
    def test_low_resources_block_all_runtime_calls_and_preserve_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            config=Mock(side_effect=AssertionError('must not query runtime'))
            p=Path(td)/'session'
            result=self.execute(p,memory=lambda:{**GOOD_MEMORY,'memory_load_percent':97},config=config)
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['inference_requests'],0);config.assert_not_called()
            self.assertFalse((p/'evaluation.json').exists())
            self.assertEqual(json.loads((p/'session.json').read_text()),result)
            from fitlab_evaluation.artifacts import digest
            manifest=json.loads((p/'manifest.json').read_text())
            for name,sha in manifest['files'].items():self.assertEqual(digest((p/name).read_bytes()),sha)
            before=(p/'session.json').read_bytes()
            with self.assertRaises(ArtifactError):self.execute(p)
            self.assertEqual((p/'session.json').read_bytes(),before)
    def test_bad_config_blocks_before_client(self):
        for config in ({}, {'offline':True,'no_fetch_executables':False}, 'true', {'offline':float('nan')}, {'offline':set()}):
            with tempfile.TemporaryDirectory() as td,patch.object(LemonadeClient,'ready',side_effect=AssertionError('no runtime calls')):
                r=self.execute(Path(td)/'session',memory=lambda:GOOD_MEMORY,config=lambda:config)
                self.assertEqual(r['reason'],'RUNTIME_NOT_PROVEN_OFFLINE');self.assertEqual(r['inference_requests'],0)
    def test_dirty_source_refused_before_output(self):
        with tempfile.TemporaryDirectory() as td,patch('fitlab_evaluation.workflow.identity',return_value={}):
            with self.assertRaisesRegex(ArtifactError,'SOURCE_NOT_FROZEN'):execute(Path(td)/'new',self.trust)
            self.assertEqual(list(Path(td).iterdir()),[])
    def test_native_adapter_and_disabled_telemetry_required(self):
        for client,health in ((object(),HEALTH),(LemonadeClient(),HEALTH)):
            with tempfile.TemporaryDirectory() as td,patch.object(LemonadeClient,'ready',return_value=health),patch.object(LemonadeClient,'complete',side_effect=AssertionError('no inference')):
                r=self.execute(Path(td)/'session',memory=lambda:GOOD_MEMORY,config=lambda:{'offline':True,'no_fetch_executables':True},client=client)
                self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['inference_requests'],0)
    def test_keyboard_interrupt_before_inference(self):
        with tempfile.TemporaryDirectory() as td:
            def interrupted():raise KeyboardInterrupt()
            r=self.execute(Path(td)/'session',memory=interrupted)
            self.assertEqual(r['status'],'INTERRUPTED');self.assertEqual(r['inference_requests'],0)
    def test_config_read_is_bounded_strict_and_allowlisted(self):
        valid=b'{"offline":true,"no_fetch_executables":true,"secret":"must not persist"}'
        invalid=[b'{}',b'{"offline":true,"offline":true,"no_fetch_executables":true}',b'[]',b'\xff',b'{"offline":1,"no_fetch_executables":true}',b'['*1000+b']'*1000]
        for raw in [valid]+invalid:
            connection=Mock();connection.sock=None
            response=connection.getresponse.return_value;response.status=200;response.read.return_value=raw
            response.getheader.side_effect=lambda k,d=None: {'Content-Type':'application/json'}.get(k,d)
            with patch('fitlab_evaluation.workflow.http.client.HTTPConnection',return_value=connection):
                if raw is valid:self.assertEqual(safe_runtime_config(),{'offline':True,'no_fetch_executables':True})
                else:
                    with self.assertRaises(ArtifactError):safe_runtime_config()
            self.assertEqual(connection.request.call_args.args,('GET','/internal/config'))

    def test_unexpected_readiness_exception_is_durable_block(self):
        with tempfile.TemporaryDirectory() as td,patch.object(LemonadeClient,'ready',side_effect=RuntimeError('private fault detail')):
            p=Path(td)/'session'
            r=self.execute(p,memory=lambda:GOOD_MEMORY,config=lambda:{'offline':True,'no_fetch_executables':True})
            self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['inference_requests'],0)
            self.assertNotIn('private fault detail',(p/'session.json').read_text())

    def test_read_only_compatibility_snapshot_is_durable_before_inference(self):
        health=copy.deepcopy(HEALTH);health['telemetry']={'enabled':False}
        snapshot={'runtime_version':health['version'],'runtime_health':health,
                  'runtime_stats':{'live':{'active_requests':0}},
                  'system_stats':{'gpu_percent':None},
                  'model_discovery':{'status':'AVAILABLE_LISTED'},
                  'scope':'read-only loopback compatibility inspection; no pull or install'}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(LemonadeClient,'ready',return_value=health), \
             patch.object(LemonadeClient,'compatibility_snapshot',return_value=snapshot), \
             patch.object(LemonadeClient,'complete',side_effect=AssertionError('no inference')):
            p=Path(td)/'session'
            r=self.execute(p,memory=lambda:GOOD_MEMORY,
                           config=lambda:{'offline':True,'no_fetch_executables':True})
        self.assertEqual(r['status'],'STOPPED')
        self.assertEqual(r['runtime_compatibility'],snapshot)
        self.assertEqual(r['inference_requests'],1)
        self.assertIn('durable attempted rows',r['request_count_basis'])

    def test_plan_is_carried_into_the_record_and_validated(self):
        """A source-backed plan must reach the evaluation record."""
        plan=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        plan['scenarios'][0]['model']['model_id']=MODEL
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'session'
            with patch.object(LemonadeClient,'ready',return_value=HEALTH), \
                 patch.object(LemonadeClient,'complete',side_effect=AssertionError('no inference')):
                r=self.execute(p,memory=lambda:GOOD_MEMORY,
                              config=lambda:{'offline':True,'no_fetch_executables':True},
                              plan=plan)
            self.assertEqual(r['status'],'BLOCKED')
            self.assertEqual(r['inference_requests'],0)
        # The plan itself is accepted by the planner and names the model.
        from fitlab_foundation.planner_cli import run_document
        self.assertTrue(run_document(plan)['results'])
        self.assertEqual(plan['scenarios'][0]['model']['model_id'],MODEL)

    def test_plan_for_a_different_model_is_rejected_before_any_request(self):
        plan=json.loads((ROOT/'examples/f2_workload_to_hardware.json').read_text())
        plan['scenarios'][0]['model']['model_id']='some-other-model'
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'session'
            with patch.object(LemonadeClient,'ready',side_effect=AssertionError('no runtime calls')), \
                 patch.object(LemonadeClient,'complete',side_effect=AssertionError('no inference')):
                r=self.execute(p,memory=lambda:GOOD_MEMORY,
                              config=lambda:{'offline':True,'no_fetch_executables':True},
                              plan=plan)
            self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['inference_requests'],0)
