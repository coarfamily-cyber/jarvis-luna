import copy
from pathlib import Path
import unittest
import os
import tempfile
from unittest.mock import patch
import destination_core_epoch as e
import owned_core_local as r
from test_owned_core_local import make_run
from test_owned_core_local import FakeReader
import test_destination_core_epoch as fixture

class FailurePrefix(unittest.TestCase):
    def setUp(self):
        f=fixture.EpochTests();f.setUp();self.policy=copy.deepcopy(f.p)
        self.policy['code_contract_digest']='c'*64
        self.run=make_run();self.run['conclusion']='failure'
        self.policy['failed_prefix_transition']={'prior_policy':f.p,'classification':'initial_local_preflight_failed_no_retention',
            'run':{'id':100,'run_number':1,'run_attempt':1,'head_sha':'b'*40,'job_id':500}}
        names=['Set up job','Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
          'Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',*r.REQUIRED_STEPS,
          'Post Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',
          'Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1','Complete job']
        self.jobs=[dict(id=500,run_id=100,run_attempt=1,head_sha='b'*40,status='completed',conclusion='failure',
          steps=[dict(name=n,status='completed',conclusion=c) for n,c in zip(names,['success']*3+['failure','skipped','skipped','success','success'])])]
        self.artifacts=[]
    def json(self,path):
        if '/jobs?' in path:return {'total_count':len(self.jobs),'jobs':copy.deepcopy(self.jobs)}
        if '/artifacts?' in path:return {'total_count':len(self.artifacts),'artifacts':copy.deepcopy(self.artifacts)}
        raise AssertionError(path)
    def call(self):
        e.validate_policy(self.policy)
        with patch.object(r,'verify_historical_code') as history:
            result=r.authenticate_failed_prefix(self,self.policy,self.run,root=Path('/fixture'))
            history.assert_called_once_with(Path('/fixture'),self.policy['failed_prefix_transition']['prior_policy'],'b'*40)
        return result
    def test_exact_failed_prefix_preserved(self):
        result=self.call();self.assertEqual(result['run_id'],100);self.assertEqual(result['artifact_count'],0)
        self.assertEqual(result['legacy_effects'],'not_determined_or_cleared')
    def test_transition_cannot_change_authority(self):
        for key,value in [('legacy_unresolved_digest','d'*64),('authorization_reference_digest','d'*64),('genesis_workflow_id',888)]:
            old=self.policy[key];self.policy[key]=value
            with self.assertRaises(e.Blocked):self.call()
            self.policy[key]=old
    def test_not_reset_or_nested_transition(self):
        self.policy['failed_prefix_transition']['run']['run_number']=2
        with self.assertRaises(e.Blocked):self.call()
    def test_no_artifact_or_success_claim(self):
        self.artifacts=[{'id':1}]
        with self.assertRaises(e.Blocked):self.call()
        self.artifacts=[];self.run['conclusion']='success'
        with self.assertRaises(e.Blocked):self.call()
    def test_retain_or_extra_step_blocks(self):
        self.jobs[0]['steps'][4]['conclusion']='success'
        with self.assertRaises(e.Blocked):self.call()
        self.jobs[0]['steps'][4]['conclusion']='skipped';self.jobs[0]['steps'].append(dict(name='extra'))
        with self.assertRaises(e.Blocked):self.call()
    def test_missing_or_retried_or_changed_job_blocks(self):
        self.jobs[0]['run_attempt']=2
        with self.assertRaises(e.Blocked):self.call()
        self.jobs=[]
        with self.assertRaises(e.Blocked):self.call()
    def test_second_run_prepares_genesis_preserving_failed_first(self):
        f=fixture.EpochTests();f.setUp()
        current=make_run(rid=101,number=2,status='in_progress')
        failed=self
        class Reader:
            def json(self,path):
                if path=='':return current['repository']
                if '/runs?' in path:return {'total_count':2,'workflow_runs':[current,failed.run]}
                return failed.json(path)
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':e.REPOSITORY,'GITHUB_REPOSITORY_ID':str(e.REPOSITORY_ID),
             'GITHUB_REPOSITORY_OWNER_ID':str(e.OWNER_ID),'GITHUB_RUN_ID':'101','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'b'*40}
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,env),patch.object(r,'load_context',return_value=(self.policy,None,f.inputs)),patch.object(r,'GithubReader',return_value=Reader()),patch.object(r,'validate_local_inputs'),patch.object(r,'verify_historical_code'),patch.object(r,'git',return_value=b'b'*40+b'\n'):
            out=Path(temp)/'checkpoint'
            result=r.run(Path('/fixture'),out)
            cp=e.parse((out/'checkpoint.json').read_bytes())
            self.assertEqual(result['sequence'],0);self.assertEqual(cp['run_id'],101)
            self.assertEqual(cp['epoch'],e.digest(self.policy));self.assertIn('failed_prefix_transition',self.policy)
    def test_deleted_first_still_blocks_with_transition(self):
        current=make_run(rid=101,number=2,status='in_progress')
        reader=FakeReader(b'{}',current)
        with self.assertRaises(e.Blocked):r.run_inventory(reader,self.policy)

if __name__=='__main__':unittest.main()
