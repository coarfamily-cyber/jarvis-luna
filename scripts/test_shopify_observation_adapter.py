import copy
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
import shopify_observation_consumer as c
import shopify_observation_adapter as a
from test_shopify_observation_consumer import package,metadata,later,NOW

class Reader:
 def __init__(self,raw=None,m=None):
  self.raw=raw or package();m=m or metadata(self.raw);self.calls=[]
  repo={'id':c.REPO_ID,'full_name':c.REPO,'owner':{'id':a.OWNER_ID}}
  rid=m['run_id'];self.rid=rid
  run=dict(id=rid,workflow_id=c.WORKFLOW_ID,path=a.PATH,head_sha=c.CODE_SHA,head_branch='main',event='workflow_dispatch',run_attempt=1,status='completed',conclusion='success',repository=repo,head_repository=repo,updated_at=m['completed_at'])
  self.docs={'':repo,'/git/commits/'+c.CODE_SHA:{'sha':c.CODE_SHA},f'/actions/runs/{rid}':run,
   f'/actions/runs/{rid}/jobs?filter=latest&per_page=100&page=1':{'total_count':1,'jobs':[{'id':1,'name':'observe','run_id':rid,'status':'completed','conclusion':'success','steps':[{'name':n,'status':'completed','conclusion':'success','number':i+4} for i,n in enumerate(a.STEPS)]}]},
   f'/actions/runs/{rid}/artifacts?per_page=100&page=1':{'total_count':1,'artifacts':[dict(id=m['artifact_id'],name=m['artifact_name'],size_in_bytes=len(self.raw),digest='sha256:'+c.digest(self.raw),archive_download_url=f"https://api.github.com/repos/{c.REPO}/actions/artifacts/{m['artifact_id']}/zip",created_at=m['artifact_created_at'],expires_at=m['artifact_expires_at'],expired=False,workflow_run={'id':rid,'repository_id':c.REPO_ID,'head_repository_id':c.REPO_ID,'head_branch':'main','head_sha':c.CODE_SHA})]}}
 def json(self,path):self.calls.append(path);return copy.deepcopy(self.docs[path])
 def archive(self,aid):self.calls.append(('archive',aid));return self.raw
class AdapterTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)/'private';self.ledger=a.LocalLedger(self.directory);self.addCleanup(self.ledger.close)
 def ingest(self,reader=None,expected=None):
  reader=reader or Reader();return a.ingest(reader,reader.rid,self.ledger,now=NOW,expected_state_sha256=expected)
 def test_verified_eight_reads_baseline_durable_reopen(self):
  r=Reader();out=self.ingest(r);self.assertEqual(out['status'],'no_baseline');self.assertEqual(len(r.calls),8)
  other=a.LocalLedger(self.directory)
  try:self.assertEqual(other.snapshot(),out['next_state'])
  finally:other.close()
  self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM candidates').fetchone()[0],0)
 def test_duplicate_does_not_write_candidate_or_receipt(self):
  s=self.ingest()['next_state'];r=self.ingest(expected=s['state_sha256']);self.assertEqual(r['status'],'duplicate')
  self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM receipts').fetchone()[0],1)
 def test_delta_atomically_stored_as_review_only(self):
  s=self.ingest()['next_state'];raw,m=later(True);out=self.ingest(Reader(raw,m),s['state_sha256']);self.assertEqual(out['status'],'review_candidate')
  candidate=json.loads(self.ledger.db.execute('SELECT value FROM candidates').fetchone()[0]);self.assertFalse(candidate['shopify_write_allowed'])
  self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM receipts').fetchone()[0],2)
 def test_stale_cas_conflict_rolls_back(self):
  s=self.ingest()['next_state'];raw,m=later(True)
  with self.assertRaisesRegex(a.AdapterError,'cas_conflict'):self.ingest(Reader(raw,m),None)
  self.assertEqual(self.ledger.snapshot(),s)
 def test_two_connections_cas(self):
  second=a.LocalLedger(self.directory)
  try:
   self.ingest();r=Reader()
   with self.assertRaisesRegex(a.AdapterError,'cas_conflict'):a.ingest(r,r.rid,second,now=NOW)
  finally:second.close()
 def test_bad_digest_before_db_write(self):
  r=Reader();r.raw+=b'x'
  with self.assertRaises(a.AdapterError):self.ingest(r)
  self.assertIsNone(self.ledger.snapshot())
 def test_wrong_repo_or_commit(self):
  for path,key,val in [('', 'id',1),('/git/commits/'+c.CODE_SHA,'sha','a'*40)]:
   r=Reader();r.docs[path][key]=val
   with self.assertRaises(a.AdapterError):self.ingest(r)
 def test_failed_run_or_wrong_workflow(self):
  for k,v in [('workflow_id',1),('run_attempt',2),('head_sha','a'*40),('conclusion','failure'),('path','evil')]:
   r=Reader();r.docs[f'/actions/runs/{r.rid}'][k]=v
   with self.assertRaises(a.AdapterError):self.ingest(r)
 def test_missing_failed_reordered_steps(self):
  for mode in ('missing','failed','reordered'):
   r=Reader();steps=r.docs[f'/actions/runs/{r.rid}/jobs?filter=latest&per_page=100&page=1']['jobs'][0]['steps']
   if mode=='missing':steps.pop()
   elif mode=='failed':steps[0]['conclusion']='failure'
   else:steps[0]['number']=99
   with self.assertRaises(a.AdapterError):self.ingest(r)
 def test_extra_artifact_or_job(self):
  for suffix in ('jobs?filter=latest&per_page=100&page=1','artifacts?per_page=100&page=1'):
   r=Reader();r.docs[f'/actions/runs/{r.rid}/'+suffix]['total_count']=2
   with self.assertRaises(a.AdapterError):self.ingest(r)
 def test_unauthorized_archive_url(self):
  r=Reader();r.docs[f'/actions/runs/{r.rid}/artifacts?per_page=100&page=1']['artifacts'][0]['archive_download_url']='https://evil.invalid/'
  with self.assertRaises(a.AdapterError):self.ingest(r)
  self.assertFalse(any(type(x) is tuple for x in r.calls))
 def test_remote_changes_between_reads(self):
  r=Reader();original=r.json
  def changing(path):
   result=original(path)
   if path==f'/actions/runs/{r.rid}' and r.calls.count(path)>1:result['updated_at']='2026-10-24T23:02:00Z'
   return result
  r.json=changing
  with self.assertRaisesRegex(a.AdapterError,'remote_observation_changed'):self.ingest(r)
 def test_invalid_receipt_rolls_back(self):
  r=Reader();raw,m=later();m['artifact_expires_at']='2027-01-01T00:00:00Z';r=Reader(raw,m)
  with self.assertRaises(a.AdapterError):self.ingest(r)
  self.assertIsNone(self.ledger.snapshot())
 def test_candidate_write_failure_rolls_back_everything(self):
  state=self.ingest()['next_state']
  self.ledger.db.execute("CREATE TRIGGER deny_candidate BEFORE INSERT ON candidates BEGIN SELECT RAISE(ABORT,'test_fault'); END")
  raw,m=later(True)
  with self.assertRaises(Exception):self.ingest(Reader(raw,m),state['state_sha256'])
  self.assertEqual(self.ledger.snapshot(),state)
  self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM receipts').fetchone()[0],1)
 def test_orphaned_rows_block(self):
  self.ledger.db.execute("INSERT INTO receipts VALUES (1,'a','b','c')")
  with self.assertRaisesRegex(a.AdapterError,'orphaned'):self.ingest()
 def test_ledger_row_tamper_blocks(self):
  state=self.ingest()['next_state'];self.ledger.db.execute("UPDATE receipts SET artifact_digest='bad'")
  with self.assertRaisesRegex(a.AdapterError,'state_mismatch'):self.ingest(expected=state['state_sha256'])
 def test_directory_permissions_and_symlink(self):
  unsafe=Path(self.tmp.name)/'unsafe';unsafe.mkdir(mode=0o755)
  with self.assertRaises(a.AdapterError):a.LocalLedger(unsafe)
  link=Path(self.tmp.name)/'link';link.symlink_to(self.directory)
  with self.assertRaises(a.AdapterError):a.LocalLedger(link)
 def test_symlink_database(self):
  d=Path(self.tmp.name)/'another';d.mkdir(mode=0o700);(d/'shopify-observation.sqlite3').symlink_to(self.ledger.path)
  with self.assertRaises(a.AdapterError):a.LocalLedger(d)
if __name__=='__main__':unittest.main()
