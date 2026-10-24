import copy
import json
from pathlib import Path
import tempfile
import unittest
import run_fx_readonly_observation as m
from test_fx_readonly_observation import raw,NOW
from fx_readonly_observation import parse_response,ObservationError

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'root';(self.root/'config').mkdir(parents=True)
        self.original=json.dumps({'fx':parse_response(raw(),NOW)['observation']})
        (self.root/'config/public-fx-observation.json').write_text(self.original)
        self.env={'GITHUB_SHA':'a'*40,'EXPECTED_SHA':'a'*40,'GITHUB_REPOSITORY':'coarfamily-cyber/jarvis-luna',
          'GITHUB_REPOSITORY_ID':'1431541717','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch',
          'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'123','GITHUB_WORKFLOW':'Owned FX read-only observation','RUNNER_TEMP':str(self.base)}
        self.calls=[]
    def observe(self,prev):
        self.calls.append(copy.deepcopy(prev));return parse_response(raw(),NOW)
    def test_result_in_runner_temp_only(self):
        result=m.execute(self.env,self.root,self.observe)
        self.assertEqual(len(self.calls),1);self.assertFalse(result['pricing_applied'])
        self.assertEqual(result['provenance']['code_sha'],'a'*40)
        self.assertEqual((self.root/'config/public-fx-observation.json').read_text(),self.original)
        self.assertEqual(list((self.base/'fx-readonly-observation-123-1').iterdir()),[self.base/'fx-readonly-observation-123-1/result.json'])
        self.assertEqual(json.loads((self.base/'fx-readonly-observation-123-1/result.json').read_text()),result)
    def test_all_identity_guards_before_network(self):
        for key in self.env:
            if key=='RUNNER_TEMP':continue
            with self.subTest(key=key),self.assertRaises(ObservationError):
                m.execute(dict(self.env,**{key:'wrong'}),self.root,self.observe)
        self.assertEqual(self.calls,[])
    def test_temp_requires_absolute_real_directory(self):
        link=self.base/'link';link.symlink_to(self.base,target_is_directory=True)
        for path in ('','relative',str(self.base/'missing'),str(link)):
            with self.assertRaises(ObservationError):m.execute(dict(self.env,RUNNER_TEMP=path),self.root,self.observe)
        self.assertEqual(self.calls,[])
    def test_existing_directory_blocks_replay_before_network(self):
        (self.base/'fx-readonly-observation-123-1').mkdir()
        with self.assertRaises(FileExistsError):m.execute(self.env,self.root,self.observe)
        self.assertEqual(self.calls,[])
    def test_provider_failure_no_false_receipt(self):
        def fail(previous):raise ObservationError('provider_unavailable')
        with self.assertRaises(ObservationError):m.execute(self.env,self.root,fail)
        self.assertFalse((self.base/'fx-readonly-observation-123-1/result.json').exists())
    def test_invalid_prior_file_before_network(self):
        (self.root/'config/public-fx-observation.json').write_text('{}')
        with self.assertRaises(KeyError):m.execute(self.env,self.root,self.observe)
        self.assertEqual(self.calls,[])
if __name__=='__main__':unittest.main()
