import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import run_technical_review_report as m
from test_technical_fix_review import fixture
class ReportTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.temp=self.root/'temp';self.temp.mkdir()
  for name,value in [(m.INPUT,{'teams':[{'id':t,'private':'SECRET-'+t} for t in m.TEAMS],'private':'TOKEN'}),(m.FIXTURE,fixture())]:
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
  self.env={'GITHUB_REPOSITORY':'coarfamily-cyber/jarvis-luna','GITHUB_REPOSITORY_ID':'1431541717','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1','GITHUB_WORKFLOW':m.NAME,'GITHUB_SHA':'a'*40,'EXPECTED_SHA':'a'*40,'GITHUB_RUN_ID':'1','RUNNER_TEMP':str(self.temp)}
 def test_sanitized_result_no_private_or_paths(self):
  with patch('socket.create_connection',side_effect=AssertionError('network')):d=m.execute(self.env,self.root)
  body=json.dumps(d)
  for forbidden in ['SECRET','TOKEN','scripts/','data/','summary','reported_result','routing_reason','/workspace/','repository']:self.assertNotIn(forbidden,body)
  self.assertFalse(d['team_delivery_verified']);self.assertFalse(d['team_execution_verified'])
  self.assertEqual(len(d['incidents']),4)
  self.assertTrue(all(r['acknowledgment'] is None for r in d['incidents']))
  p=self.temp/'technical-review-report-1-1/result.json';self.assertEqual(p.stat().st_mode&0o777,0o600)
 def test_exact_item_keys(self):
  d=m.report(self.root)
  for row in d['incidents']:self.assertEqual(set(row),{'error_code','code_state','code_commit','evidence_hashes','owner_role','proposed_review_roles','review_required','sent_at','acknowledgment','team_action_receipt'})
 def test_false_ack_rejected_before_artifact(self):
  d=fixture();d['incidents'][0]['acknowledgment']={'done':True};(self.root/m.FIXTURE).write_text(json.dumps(d))
  with self.assertRaises(ValueError):m.execute(self.env,self.root)
  self.assertEqual(list(self.temp.iterdir()),[])
 def test_wrong_execution_identity(self):
  for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_RUN_ATTEMPT','2'),('GITHUB_EVENT_NAME','schedule'),('GITHUB_REF','refs/heads/other'),('EXPECTED_SHA','b'*40),('GITHUB_WORKFLOW','other'),('GITHUB_RUN_ID','../x')]:
   e=dict(self.env);e[key]=value
   with self.assertRaises(ValueError):m.execute(e,self.root)
  self.assertEqual(list(self.temp.iterdir()),[])
 def test_no_overwrite(self):
  m.execute(self.env,self.root)
  with self.assertRaises(FileExistsError):m.execute(self.env,self.root)
 def test_saved_team_set_required(self):
  (self.root/m.INPUT).write_text('{"teams":[]}')
  with self.assertRaises(ValueError):m.execute(self.env,self.root)
 def test_symlink_inputs_rejected(self):
  p=self.root/m.INPUT;p.unlink();p.symlink_to(self.root/m.FIXTURE)
  with self.assertRaises(ValueError):m.execute(self.env,self.root)
if __name__=='__main__':unittest.main()
