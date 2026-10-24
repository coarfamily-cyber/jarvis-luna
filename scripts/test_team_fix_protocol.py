"""Synthetic local receipt fixtures: neither Shopify calls nor live success proof."""
import copy
from datetime import datetime, timezone
from unittest.mock import patch
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import team_fix_protocol as protocol

class TeamFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data/team_fix_evidence').mkdir(parents=True)
    def ref(self,name,data):
        path='data/team_fix_evidence/'+name
        (self.root/path).write_bytes(data)
        return {'path':path,'sha256':hashlib.sha256(data).hexdigest()}
    def record(self):
        return {'issue_id':'med-warning','rule':'supplier_warning_omission',
            'source':self.ref('source',b'supplier warning'), 'before':self.ref('before',b'old'),
            'after':self.ref('after',b'new'), 'regression_log':self.ref('tests',b'synthetic test log'),
            'readback':self.ref('readback',b'new')}
    def test_handoff_keeps_independent_review_and_no_authority(self):
        issue=protocol.project(self.root,[self.record()])['issues'][0]
        self.assertEqual(issue['state'],'evidence_bound_pending_independent_review')
        self.assertEqual(issue['team'],'listing')
        self.assertFalse(issue['publication_allowed']);self.assertFalse(issue['human_approved'])
    def test_missing_any_required_step_remains_open(self):
        for key in ('source','before','after','regression_log','readback'):
            row=self.record();del row[key]
            self.assertEqual(protocol.project(self.root,[row])['issues'][0]['state'],'review_required')
    def test_changed_test_bytes_cannot_reuse_receipt(self):
        row=self.record();(self.root/row['regression_log']['path']).write_bytes(b'changed')
        self.assertEqual(protocol.project(self.root,[row])['issues'][0]['state'],'review_required')
    def test_readback_drift_rejected(self):
        row=self.record();row['readback']=self.ref('drift',b'drift')
        self.assertEqual(protocol.project(self.root,[row])['issues'][0]['state'],'review_required')
    def test_false_human_approval_never_learned(self):
        for value in (True,'true',1):
            row=self.record();row['human_approved']=value
            issue=protocol.project(self.root,[row])['issues'][0]
            self.assertEqual(issue['reason'],'receipt_cannot_grant_authority')
    def test_traversal_and_symlink_rejected(self):
        row=self.record();row['source']['path']='data/team_fix_evidence/../outside'
        self.assertEqual(protocol.project(self.root,[row])['issues'][0]['state'],'review_required')
        row=self.record();p=self.root/row['source']['path'];p.unlink();p.symlink_to(self.root/'data/team_fix_evidence/after')
        self.assertEqual(protocol.project(self.root,[row])['issues'][0]['state'],'review_required')
    def test_fifo_does_not_block(self):
        row=self.record();p=self.root/row['source']['path'];p.unlink();os.mkfifo(p)
        self.assertEqual(protocol.project(self.root,[row])['issues'][0]['state'],'review_required')
    def test_malformed_rule_fails_typed(self):
        for rule in ([], {}, None):
            row=self.record();row['rule']=rule
            with self.assertRaises(ValueError):protocol.project(self.root,[row])
    def test_unknown_rule_duplicate_ids_fail_closed(self):
        row=self.record()
        with self.assertRaises(ValueError):protocol.project(self.root,[row,row])
        row['rule']='auto_publish'
        with self.assertRaises(ValueError):protocol.project(self.root,[row])
    def test_load_absent_is_empty_not_success(self):
        self.assertEqual(protocol.load_projection(self.root)['issues'],[])
    def test_file_load_connected(self):
        path=self.root/'data/team_fix_receipts.json'
        path.write_text(json.dumps({'schema_version':1,'receipts':[self.record()]}))
        self.assertEqual(len(protocol.load_projection(self.root)['issues']),1)
    def test_existing_registry_and_gosi_generate_team_actions(self):
        (self.root/'data/shopify_daily_registry.json').write_text(json.dumps({'items':[
            {'pd_no':'1025282','name_kr':'Body Wash 200 ml'}]}))
        (self.root/'data/gosi.json').write_text(json.dumps({'items':{'1025282':
            {'maker':'및 판매원','volume':'190 ml (200g)'}}}))
        result=protocol.load_projection(self.root)
        self.assertIn('manufacturer_heading_fragment',{r['rule'] for r in result['issues']})
        self.assertIn('volume_conflict',{r['rule'] for r in result['issues']})
        self.assertTrue(all(r['state']=='review_required' for r in result['issues']))
    def test_receipt_cannot_relabel_discovered_formula_issue(self):
        (self.root/'data/shopify_daily_registry.json').write_text(json.dumps({'items':[{'pd_no':'1067498'}]}))
        (self.root/'data/gosi.json').write_text(json.dumps({'items':{}}))
        row=self.record();row['issue_id']='supplier-1067498-formula_conflict';row['rule']='source_color_omission'
        (self.root/'data/team_fix_receipts.json').write_text(json.dumps({'schema_version':1,'receipts':[row]}))
        with self.assertRaises(ValueError):protocol.load_projection(self.root)
    def test_nonfinite_or_boolean_schema_not_accepted(self):
        # Version is an integer schema, not boolean authority.
        path=self.root/'data/team_fix_receipts.json'
        path.write_text('{"schema_version":2,"receipts":[]}')
        with self.assertRaises(ValueError):protocol.load_projection(self.root)

class OfflineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'data/team_fix_evidence').mkdir(parents=True)
        self.original_read = protocol.read_regular
        self.now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
        self.issue = 'supplier-1025282-manufacturer_heading_fragment'
        (self.root/'data/shopify_daily_registry.json').write_text(json.dumps({'items':[{'pd_no':'1025282','name_kr':'Organist 200 ml'},{'pd_no':'1067498'}]}))
        (self.root/'data/gosi.json').write_text(json.dumps({'items':{'1025282':{'maker':'및 판매원','volume':'190 ml (200g)'}}}))
        self.before = {'kind':'saved_shopify_product_readback','recorded_at':'2026-10-24T01:00:00Z',
            'product':{'id':'gid://shopify/Product/9710072889601','status':'DRAFT','tags':['daiso-pd-1025282'],
                       'title':'Organist 200 ml','inventory':1,'descriptionHtml':'<p><strong>Manufacturer / Distributor (Korea):</strong> 및 판매원</p><p>190 ml (200g)</p>'}}
        self.after = copy.deepcopy(self.before)
        self.after['product']['descriptionHtml'] = self.after['product']['descriptionHtml'].replace('및 판매원','Source verification pending')
        self.job = {'issue_id':self.issue,'before':self.ref('before',self.before),'readback':self.ref('after',self.after)}
    def ref(self, name, doc):
        raw=json.dumps(doc,ensure_ascii=False).encode();name='data/team_fix_evidence/'+name
        (self.root/name).write_bytes(raw)
        return {'path':name,'sha256':hashlib.sha256(raw).hexdigest()}
    def run_jobs(self, jobs):
        return protocol.load_projection(self.root,offline_replays=jobs,now=self.now)
    def assert_no_authority(self, result):
        for key in protocol.AUTHORITY:self.assertIs(result[key],False)
        self.assertFalse(result['live_execution']);self.assertFalse(result['fresh_readback'])
    def forbid_optional_read(self, path, limit, **kwargs):
        if Path(path).parent == self.root/'data/team_fix_evidence':
            raise AssertionError('optional evidence read')
        return self.original_read(path,limit,**kwargs)
    def test_default_is_unchanged_and_does_not_read_optional_evidence(self):
        with patch.object(protocol,'read_regular',side_effect=self.forbid_optional_read):
            baseline=protocol.load_projection(self.root)
            explicit=protocol.load_projection(self.root,offline_replays=None,now=self.now)
        self.assertEqual(baseline,explicit)
        self.assertNotIn('offline_rehearsals',baseline)
    def test_success_separate_results_preserves_holds_and_files(self):
        baseline=protocol.load_projection(self.root)
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.run_jobs([self.job]);after={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual({k:v for k,v in result.items() if k!='offline_rehearsals'},baseline)
        replay=result['offline_rehearsals'][0]
        self.assertEqual(replay['issue_id'],self.issue)
        self.assertEqual(replay['state'],'offline_replay_verified');self.assert_no_authority(replay)
        self.assertTrue(all(row['state']=='review_required' for row in result['issues']))
        self.assertIn('formula_conflict',{row['rule'] for row in result['issues']})
        self.assertIn('volume_conflict',{row['rule'] for row in result['issues']})
    def test_unknown_and_unsupported_never_read_refs(self):
        for issue in ('not-discovered','supplier-1067498-formula_conflict','supplier-1025282-volume_conflict'):
            with patch.object(protocol,'read_regular',side_effect=self.forbid_optional_read):
                result=self.run_jobs([dict(self.job,issue_id=issue)])['offline_rehearsals'][0]
            self.assertEqual(result['state'],'review_required');self.assert_no_authority(result)
    def test_grant_blocked_projected_task_never_reads_refs(self):
        row={'issue_id':self.issue,'rule':'manufacturer_heading_fragment','human_approved':True}
        (self.root/'data/team_fix_receipts.json').write_text(json.dumps({'schema_version':1,'receipts':[row]}))
        with patch.object(protocol,'read_regular',side_effect=self.forbid_optional_read):
            result=self.run_jobs([self.job])['offline_rehearsals'][0]
        self.assertEqual(result['state'],'review_required');self.assert_no_authority(result)
    def test_closed_request_schema_duplicate_and_capacity(self):
        for jobs in ({},[None],[dict(self.job,task={})],[{'issue_id':self.issue}],[dict(self.job,issue_id=[])],[self.job,self.job],[dict(self.job,issue_id='unknown-'+str(i)) for i in range(33)]):
            with self.subTest(jobs=str(jobs)[:80]),self.assertRaises(ValueError):self.run_jobs(jobs)
    def test_hash_and_path_mismatch_blocked(self):
        for ref in ({'path':self.job['before']['path'],'sha256':'0'*64},
                    {'path':'data/team_fix_evidence/../outside','sha256':'0'*64},
                    {'path':'/etc/passwd','sha256':'0'*64}):
            result=self.run_jobs([dict(self.job,before=ref)])['offline_rehearsals'][0]
            self.assertEqual(result['reason'],'offline_evidence_unavailable_or_mismatched');self.assert_no_authority(result)
    def test_fifo_and_symlink_do_not_read(self):
        path=self.root/self.job['before']['path'];path.unlink();os.mkfifo(path)
        result=self.run_jobs([self.job])['offline_rehearsals'][0]
        self.assertEqual(result['reason'],'offline_evidence_unavailable_or_mismatched')
        path.unlink();path.symlink_to(self.root/self.job['readback']['path'])
        self.assertEqual(self.run_jobs([self.job])['offline_rehearsals'][0]['reason'],'offline_evidence_unavailable_or_mismatched')
    def test_hash_verified_bytes_are_read_only_once(self):
        real=protocol.read_regular;counts={}
        def read(path,limit,**kwargs):
            key=str(path);counts[key]=counts.get(key,0)+1
            return real(path,limit,**kwargs)
        with patch.object(protocol,'read_regular',side_effect=read):result=self.run_jobs([self.job])
        self.assertEqual(result['offline_rehearsals'][0]['state'],'offline_replay_verified')
        for key in ('before','readback'):self.assertEqual(counts[str(self.root/self.job[key]['path'])],1)
    def test_valid_hash_cannot_hide_protected_field_or_future_drift(self):
        for change in ('protected','future'):
            after=copy.deepcopy(self.after)
            if change=='protected':after['product']['inventory']=True
            else:after['recorded_at']='2099-01-01T00:00:00Z'
            result=self.run_jobs([dict(self.job,readback=self.ref('tampered',after))])['offline_rehearsals'][0]
            self.assertEqual(result['state'],'review_required');self.assert_no_authority(result)
    def test_aggregate_verified_payload_cap(self):
        size=sum(len((self.root/self.job[key]['path']).read_bytes()) for key in ('before','readback'))
        with patch.object(protocol,'MAX_OFFLINE_REPLAY_BYTES',size-1):
            with self.assertRaisesRegex(ValueError,'aggregate_capacity'):self.run_jobs([self.job])
        with patch.object(protocol,'MAX_OFFLINE_REPLAY_BYTES',size):
            self.assertEqual(self.run_jobs([self.job])['offline_rehearsals'][0]['state'],'offline_replay_verified')
    def test_failed_hash_reads_still_charge_aggregate_budget(self):
        size=len((self.root/self.job['before']['path']).read_bytes())
        bad=dict(self.job,before=dict(self.job['before'],sha256='0'*64))
        with patch.object(protocol,'MAX_OFFLINE_REPLAY_BYTES',size-1):
            with self.assertRaisesRegex(ValueError,'aggregate_capacity'):self.run_jobs([bad])
        with patch.object(protocol,'MAX_OFFLINE_REPLAY_BYTES',size):
            self.assertEqual(self.run_jobs([bad])['offline_rehearsals'][0]['reason'],'offline_evidence_unavailable_or_mismatched')
    def test_oversize_reads_still_charge_aggregate_budget(self):
        raw=b'x'*1048577;path=self.root/self.job['before']['path'];path.write_bytes(raw)
        bad=dict(self.job,before=dict(self.job['before'],sha256=hashlib.sha256(raw).hexdigest()))
        with patch.object(protocol,'MAX_OFFLINE_REPLAY_BYTES',1048576):
            with self.assertRaisesRegex(ValueError,'aggregate_capacity'):self.run_jobs([bad])
    def test_empty_optional_batch_explicit_no_results(self):
        self.assertEqual(self.run_jobs([])['offline_rehearsals'],[])

if __name__=='__main__':unittest.main()
