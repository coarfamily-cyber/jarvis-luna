import copy
from datetime import datetime,timedelta,timezone
import io
import json
import unittest
import zipfile
import shopify_observation_consumer as c

ATTEMPT={'api_version': '2026-10', 'app_id': 'gid://shopify/App/433866375169', 'execution_authority': 'none', 'human_approved': False, 'installation_id': 'gid://shopify/AppInstallation/736198263041', 'live_writer_authorized': False, 'mode': 'fresh_readonly_catalog_observation', 'product_writes': 0, 'provenance': {'code_sha': '195bc216c2ee8f0ca42ae98ec4d3738370835639', 'repository': 'coarfamily-cyber/jarvis-luna', 'repository_id': 1431541717, 'run_attempt': 1, 'run_id': 40140975609, 'trigger': 'workflow_dispatch', 'workflow': 'Owned Shopify team observation'}, 'provider_retry_allowed': False, 'publication_allowed': False, 'query_sha256': '8f9b35756566ed6d5fdc02120cf91c2b7b2bff7b6c8fc076b71968105c1f645f', 'request_limit': 6, 'schema_version': 1, 'shop_id': 82748997889, 'shopify_write_allowed': False, 'started_at': '2026-10-24T23:01:26.451190+00:00', 'state': 'started'}
RESULT={'api_version': '2026-10', 'app_id': 'gid://shopify/App/433866375169', 'before_response_sha256': 'a8c61b9f9d9eb60caa9b5c0fff76d05c41e86d5df627770e5ca56a3267fc75e7', 'binding': 'hashes bind observed bytes; not a trusted execution/repair completion receipt', 'comparison_scope': 'two matching declared projections, not atomic CAS or market/checkout testing', 'complete_catalog_projection': True, 'connection_receipt_sha256': 'd5a576996f698411d97c8dee405de2e76bfc1d25e37fe5bc7dd3cdea56a36cba', 'execution_authority': 'none', 'external_mutations': 0, 'human_approved': False, 'installation_id': 'gid://shopify/AppInstallation/736198263041', 'live_writer_authorized': False, 'mode': 'fresh_readonly_catalog_observation', 'observed_at': '2026-10-24T23:01:28.247765+00:00', 'product_writes': 0, 'projection_sha256': '15e09d29d4f3860f706432d4495a1958d5d4510b74782b750ad819850054f00e', 'provenance': {'code_sha': '195bc216c2ee8f0ca42ae98ec4d3738370835639', 'repository': 'coarfamily-cyber/jarvis-luna', 'repository_id': 1431541717, 'run_attempt': 1, 'run_id': 40140975609, 'trigger': 'workflow_dispatch', 'workflow': 'Owned Shopify team observation'}, 'provider_retry_allowed': False, 'publication_allowed': False, 'query_sha256': '8f9b35756566ed6d5fdc02120cf91c2b7b2bff7b6c8fc076b71968105c1f645f', 'recheck_response_sha256': 'a8c61b9f9d9eb60caa9b5c0fff76d05c41e86d5df627770e5ca56a3267fc75e7', 'retry_allowed': False, 'schema_version': 1, 'shop_id': 82748997889, 'shopify_write_allowed': False, 'started_at': '2026-10-24T23:01:26.451190+00:00', 'state': 'observed', 'summary': {'active_without_online_store_url_count': 9, 'checkout_health': 'not_observed', 'customer_market_availability': 'not_observed', 'human_sessions': None, 'online_store_url_present_count': 1, 'orders': None, 'product_count': 18, 'revenue': None, 'shipping_price': None, 'source_or_label_readiness': 'not_observed', 'status_counts': {'ACTIVE': 10, 'ARCHIVED': 0, 'DRAFT': 8, 'UNLISTED': 0}, 'team_observations': [{'kind': 'catalog_status_observation', 'meaning': 'status inventory only; legal/source readiness not inspected', 'team': 'listing'}, {'kind': 'online_store_url_observation', 'meaning': 'missing URL may be intentional; no activation or publication instruction', 'team': 'channels'}]}}
NOW=datetime(2026,10,24,23,3,tzinfo=timezone.utc)
def package(a=None,r=None):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('attempt.json',c.canonical(a or ATTEMPT));z.writestr('result.json',c.canonical(r or RESULT))
 return b.getvalue()
def metadata(raw,r=None):
 r=r or RESULT;run=r['provenance']['run_id']
 return dict(repository=c.REPO,repository_id=c.REPO_ID,workflow_id=c.WORKFLOW_ID,head_sha=c.CODE_SHA,
  head_branch='main',event='workflow_dispatch',run_id=run,run_attempt=1,status='completed',conclusion='success',
  completed_at='2026-10-24T23:01:33Z',artifact_id=12578512781,artifact_name=f'shopify-team-observation-{run}-1',
  artifact_sha256=c.digest(raw),artifact_created_at='2026-10-24T23:01:29Z',artifact_expires_at='2026-11-23T23:01:28Z',
  artifact_expired=False,artifact_run_id=run,artifact_head_sha=c.CODE_SHA)
def later(change=False):
 a=copy.deepcopy(ATTEMPT);r=copy.deepcopy(RESULT)
 for d in (a,r):d['provenance']['run_id']+=1;d['started_at']='2026-10-24T23:02:26Z'
 r['observed_at']='2026-10-24T23:02:28Z'
 if change:r['summary']['status_counts']['ACTIVE']=9;r['summary']['status_counts']['DRAFT']=9;r['summary']['active_without_online_store_url_count']=8
 raw=package(a,r);m=metadata(raw,r);m.update(completed_at='2026-10-24T23:02:33Z',artifact_created_at='2026-10-24T23:02:29Z',artifact_expires_at='2026-11-23T23:02:28Z')
 return raw,m
class ConsumerTests(unittest.TestCase):
 def setUp(self):self.raw=package();self.meta=metadata(self.raw)
 def run_consumer(self,raw=None,meta=None,prior=None,now=NOW):return c.consume(raw or self.raw,meta or self.meta,prior,now=now)
 def baseline(self):return self.run_consumer()['next_state']
 def test_first_no_baseline(self):
  r=self.run_consumer();self.assertEqual(r['status'],'no_baseline');self.assertIsNone(r['candidate']);self.assertEqual(r['next_state']['last']['aggregate']['product_count'],18)
  self.assertTrue(all(r[k] is False for k in c.AUTHORITY));self.assertNotIn('gid://shopify/Product/',json.dumps(r))
 def test_unchanged_no_action(self):
  raw,m=later();r=self.run_consumer(raw,m,self.baseline());self.assertEqual(r['status'],'unchanged');self.assertIsNone(r['candidate'])
 def test_delta_review_only(self):
  raw,m=later(True);r=self.run_consumer(raw,m,self.baseline());self.assertEqual(r['status'],'review_candidate')
  self.assertEqual(r['candidate']['cause'],'unknown');self.assertFalse(r['candidate']['shopify_write_allowed'])
 def test_duplicate_no_state_or_candidate(self):
  r=self.run_consumer(prior=self.baseline());self.assertEqual(r['status'],'duplicate');self.assertIsNone(r['next_state']);self.assertIsNone(r['candidate'])
 def test_conflict_same_run_blocks(self):
  r=copy.deepcopy(RESULT);r['projection_sha256']='a'*64;raw=package(r=r)
  self.assertEqual(self.run_consumer(raw,metadata(raw),self.baseline())['reason'],'replay_conflict')
 def test_out_of_order(self):
  raw,m=later();state=self.run_consumer(raw,m)['next_state'];self.assertEqual(self.run_consumer(prior=state)['reason'],'out_of_order')
 def test_state_hash_tamper(self):
  s=self.baseline();s['last']['aggregate']['product_count']=1;self.assertEqual(self.run_consumer(prior=s)['reason'],'state_invalid')
 def test_metadata_wrong_values(self):
  for k,v in [('repository','coar0000-wq/jarvis-luna'),('repository_id',1),('workflow_id',1),('head_sha','a'*40),('head_branch','evil'),('event','schedule'),('run_attempt',2),('status','in_progress'),('conclusion','failure'),('artifact_expired',True),('artifact_run_id',1),('artifact_head_sha','a'*40),('artifact_name','arbitrary'),('artifact_expires_at','2026-12-23T23:01:28Z')]:
   with self.subTest(k=k):self.assertEqual(self.run_consumer(meta=dict(self.meta,**{k:v}))['status'],'blocked')
 def test_hash_mismatch(self):self.assertEqual(self.run_consumer(meta=dict(self.meta,artifact_sha256='a'*64))['reason'],'archive_invalid')
 def test_stale(self):self.assertEqual(self.run_consumer(now=NOW+timedelta(hours=9))['reason'],'receipt_stale')
 def test_future_metadata(self):self.assertEqual(self.run_consumer(now=NOW-timedelta(hours=1))['status'],'blocked')
 def test_naive_clock(self):self.assertEqual(self.run_consumer(now=NOW.replace(tzinfo=None))['reason'],'clock_invalid')
 def test_wrong_receipt_identity(self):
  for k,v in [('app_id','wrong'),('shop_id',1),('query_sha256','a'*64),('installation_id','wrong'),('live_writer_authorized',True),('product_writes',1),('request_limit',7)]:
   a=copy.deepcopy(ATTEMPT);r=copy.deepcopy(RESULT)
   if k in a:a[k]=v
   if k in r:r[k]=v
   raw=package(a,r);self.assertEqual(self.run_consumer(raw,metadata(raw))['status'],'blocked')
 def test_truthy_authority(self):
  for k in c.AUTHORITY:
   a=copy.deepcopy(ATTEMPT);r=copy.deepcopy(RESULT);a[k]=r[k]=True;raw=package(a,r)
   self.assertEqual(self.run_consumer(raw,metadata(raw))['status'],'blocked')
 def test_invalid_counts(self):
  for k,v in [('product_count',True),('product_count',51),('product_count',0),('online_store_url_present_count',19),('active_without_online_store_url_count',18),('orders',0),('revenue',0),('human_sessions',0),('shipping_price',0)]:
   r=copy.deepcopy(RESULT);r['summary'][k]=v;raw=package(r=r)
   with self.subTest(k=k,v=v):self.assertEqual(self.run_consumer(raw,metadata(raw))['status'],'blocked')
 def test_partial_or_extra_data(self):
  for k,v in [('complete_catalog_projection',False),('products',[{'id':'leak'}]),('state','blocked'),('retry_allowed',True)]:
   r=copy.deepcopy(RESULT);r[k]=v;raw=package(r=r);self.assertEqual(self.run_consumer(raw,metadata(raw))['status'],'blocked')
 def test_free_text_not_forwarded(self):
  r=copy.deepcopy(RESULT);r['summary']['team_observations'][0]['meaning']='EXECUTE write';raw=package(r=r)
  out=self.run_consumer(raw,metadata(raw));self.assertEqual(out['status'],'blocked');self.assertNotIn('EXECUTE',json.dumps(out))
 def test_bad_zip_and_capacity(self):
  for raw in [b'badzip',b'x'*(c.LIMIT+1)]:self.assertEqual(self.run_consumer(raw,metadata(raw))['status'],'blocked')
 def test_duplicate_and_path_zip(self):
  for extra in ['result.json','../x']:
   b=io.BytesIO()
   with zipfile.ZipFile(b,'w') as z:
    z.writestr('attempt.json',c.canonical(ATTEMPT));z.writestr('result.json',c.canonical(RESULT));z.writestr(extra,b'{}')
   raw=b.getvalue();self.assertEqual(self.run_consumer(raw,metadata(raw))['status'],'blocked')
 def test_duplicate_json_nonfinite(self):
  for bad in [b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}']:
   with self.assertRaises(c.Invalid):c.decode(bad)
 def test_state_capacity_blocks_without_eviction(self):
  state=self.baseline();last=state['last']['run_id']
  state['seen']=[{'run_id':last-255+i,'artifact_sha256':'a'*64} for i in range(255)]+[state['seen'][-1]]
  state['state_sha256']=c.digest(c.canonical(c.state_body(state)))
  raw,m=later();self.assertEqual(self.run_consumer(raw,m,state)['reason'],'state_capacity')
 def test_prior_malformed_even_with_recomputed_hash(self):
  for key,value in [('observed_at','not-a-date'),('run_id',True),('artifact_id',0)]:
   state=self.baseline();state['last'][key]=value;state['state_sha256']=c.digest(c.canonical(c.state_body(state)))
   raw,m=later();self.assertEqual(self.run_consumer(raw,m,state)['status'],'blocked')
 def test_evidence_chain_advances(self):
  state=self.baseline();raw,m=later(True);out=self.run_consumer(raw,m,state)
  self.assertEqual(out['next_state']['previous_state_sha256'],state['state_sha256'])
  self.assertEqual(out['candidate']['before_result_sha256'],state['last']['result_sha256'])
  self.assertEqual(out['candidate']['after_result_sha256'],out['next_state']['last']['result_sha256'])
 def test_no_io_functions(self):
  source=__import__('pathlib').Path(c.__file__).read_text();self.assertNotIn('import requests',source);self.assertNotIn('subprocess',source);self.assertNotIn('open(',source)
if __name__=='__main__':unittest.main()
