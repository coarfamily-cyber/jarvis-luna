"""Synthetic local receipt fixtures: neither Shopify calls nor live success proof."""
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

if __name__=='__main__':unittest.main()
