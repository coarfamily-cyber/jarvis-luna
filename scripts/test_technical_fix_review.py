import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
import technical_fix_review as m
from team_fix_protocol import RULES
ROOT=Path(__file__).resolve().parents[1]
def fixture():return json.loads((ROOT/'scripts/fixtures/technical_fix_review.json').read_text())
class TechnicalFixTests(unittest.TestCase):
 def test_actual_four_remain_review(self):
  d=m.project(fixture()); self.assertEqual(len(d['incidents']),4)
  self.assertTrue(all(r['owner_role']=='unassigned' and r['acknowledgment'] is None for r in d['incidents']))
 def test_existing_product_tasks_unchanged_and_input_pure(self):
  s={'teams':{'sourcing':{'repair_tasks':[{'id':'existing'}]},'pricing':{},'design':{}},'repair_handoff':{'original':True}}
  before=copy.deepcopy(s); d=fixture(); db=copy.deepcopy(d)
  with patch('socket.create_connection',side_effect=AssertionError('network')),patch('builtins.open',side_effect=AssertionError('file I/O')):
   out=m.attach_to_internal_snapshot(s,d)
  self.assertEqual(s,before);self.assertEqual(d,db);self.assertEqual(out['repair_handoff'],s['repair_handoff'])
  self.assertEqual(out['teams']['sourcing']['repair_tasks'],s['teams']['sourcing']['repair_tasks'])
  self.assertEqual(len(out['teams']['pricing']['technical_review_candidates']),1)
  self.assertEqual(len(out['teams']['design']['technical_review_candidates']),0)
  self.assertEqual(len(RULES),9)
 def test_no_overwrite_or_second_attach(self):
  out=m.attach_to_internal_snapshot({'teams':{}},fixture())
  with self.assertRaises(ValueError):m.attach_to_internal_snapshot(out,fixture())
 def test_claims_rejected(self):
  for k,v in [('owner_role','pricing'),('sent_at','now'),('acknowledgment',{}),('team_action_receipt',{}),('team_status','completed'),('manual_review_required',False),('execution_authority','write'),('proposed_routing',['devops'])]:
   with self.subTest(k=k):
    d=fixture();d['incidents'][0][k]=v
    with self.assertRaises(ValueError):m.project(d)
 def test_duplicate_and_unknown(self):
  for v in ['fx-timestamp-schema','invented']:
   d=fixture();d['incidents'][0]['incident_id']=v
   with self.assertRaises(ValueError):m.project(d)
 def test_candidate_cannot_claim_commit(self):
  d=fixture();d['incidents'][3]['source']['commit']='a'*40
  with self.assertRaises(ValueError):m.project(d)
 def test_references_bound_not_claimed_verified(self):
  d=fixture();d['incidents'][0]['evidence'][0]['sha256']='bad'
  with self.assertRaises(ValueError):m.project(d)
 def test_capacity_and_extra_authority(self):
  for mutate in [lambda d:d.update(authority=True),lambda d:d['incidents'][0].update(summary='x'*501),lambda d:d['incidents'][0]['source'].update(code_paths=['../x'])]:
   d=fixture();mutate(d)
   with self.assertRaises(ValueError):m.project(d)
 def test_actual_public_projection_drops_private_reviews(self):
  from build_public_site import project,SCHEMAS
  private=m.attach_to_internal_snapshot({'teams':{}},fixture())
  public=project(private,SCHEMAS['data/dashboard_runtime.json'])
  self.assertNotIn('technical_review_handoff',public)
  self.assertNotIn('technical_manual_review',json.dumps(public))
if __name__=='__main__':unittest.main()
