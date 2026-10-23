import copy
import unittest
import destination_core_epoch as m

class EpochTests(unittest.TestCase):
    def setUp(self):
        self.p = dict(schema=m.SCHEMA,repository=m.REPOSITORY,repository_id=m.REPOSITORY_ID,
            owner_id=m.OWNER_ID,workflow=m.WORKFLOW,profile=m.PROFILE,holds=dict(m.HOLDS),
            genesis_workflow_id=777,genesis_run_number=1,
            **{k:'a'*64 for k in ('import_record_digest','legacy_inventory_digest',
                'legacy_unresolved_digest','source_final_tail_digest','code_contract_digest','authorization_reference_digest')})
        self.inputs = {p:b'{"products":[{"status":"blocked"},{"id":2}]}\n' for p in m.INPUTS}
        self.args = dict(run_id=100,run_attempt=1,head_sha='b'*40,legacy_inventory_digest='a'*64)
        self.raw = m.prepare_checkpoint(self.p,self.inputs,**self.args)
        self.cp = m.parse(self.raw)
        self.obs = dict(repository=m.REPOSITORY,repository_id=m.REPOSITORY_ID,owner_id=m.OWNER_ID,
          run_id=100,run_attempt=1,head_sha='b'*40,workflow=m.WORKFLOW,event='workflow_dispatch',branch='main',
          status='completed',conclusion='success',artifact_id=200,artifact_name='owned-core-local-100-1',
          artifact_digest='sha256:'+'c'*64,artifact_expired=False,required_steps_successful=True,
          complete_attempt_inventory=True,unreconciled_producer_attempts=[],predecessor_checkpoint_digest=None)
    def accept(self, raw=None):
        return m.accept_retained(raw or self.raw,self.p,observed=self.obs,expected_run_id=100,
                                 expected_attempt=1,verified_archive_sha256='c'*64)
    def test_genesis_pending_and_accept(self):
        self.assertEqual(self.cp['sequence'],0)
        self.assertIsNone(self.cp['predecessor'])
        self.assertEqual(self.accept(),self.cp)
    def test_second_chains_exact_first(self):
        first=self.accept()
        args=dict(self.args,run_id=101)
        second=m.parse(m.prepare_checkpoint(self.p,self.inputs,prior=first,**args))
        self.assertEqual(second['sequence'],1)
        self.assertEqual(second['predecessor'],m.digest(first))
        self.assertEqual(second['holds'],m.HOLDS)
    def test_real_input_findings(self):
        r=self.cp['result']['findings'][0]
        self.assertEqual((r['row_count'],r['explicit_blocked_or_review_rows']),(2,1))
    def test_unknown_shape_not_fake_zero_products(self):
        inputs=dict(self.inputs);inputs[m.INPUTS[0]]=b'{"unknown":1}'
        self.assertIsNone(m.business_review(inputs)['findings'][0]['row_count'])
    def test_mutation_of_any_hold_blocked(self):
        for k in m.HOLDS:
            with self.subTest(k=k),self.assertRaises(m.Blocked):
                p=copy.deepcopy(self.p);p['holds'][k]=True;m.validate_policy(p)
    def test_source_tail_mandatory(self):
        p=dict(self.p);p.pop('source_final_tail_digest')
        with self.assertRaises(m.Blocked):m.validate_policy(p)
    def test_inventory_unchanged(self):
        with self.assertRaises(m.Blocked):m.prepare_checkpoint(self.p,self.inputs,**dict(self.args,legacy_inventory_digest='d'*64))
    def test_same_run_retry_not_restart(self):
        with self.assertRaises(m.Blocked):m.prepare_checkpoint(self.p,self.inputs,prior=self.cp,**dict(self.args,run_attempt=2))
    def test_run_and_artifact_failures(self):
        cases={'repository':'coar0000-wq/jarvis-luna','repository_id':1334276889,'owner_id':301755647,
          'run_id':101,'run_attempt':2,'head_sha':'c'*40,'workflow':'.github/workflows/evil.yml',
          'event':'pull_request','branch':'other','status':'in_progress','conclusion':'failure',
          'artifact_name':'wrong','artifact_digest':'sha256:'+'d'*64,'artifact_expired':True,
          'required_steps_successful':False,'complete_attempt_inventory':False,
          'unreconciled_producer_attempts':['99:1'],'artifact_id':True,'predecessor_checkpoint_digest':'d'*64}
        for k,v in cases.items():
            with self.subTest(k=k),self.assertRaises(m.Blocked):
                old=self.obs;self.obs=dict(old,**{k:v})
                try:self.accept()
                finally:self.obs=old
    def test_checkpoint_tamper(self):
        for k,v in {'sequence':-1,'epoch':'d'*64,'predecessor':'a'*64,'result_digest':'d'*64,
                    'legacy_unresolved_digest':'d'*64}.items():
            with self.subTest(k=k),self.assertRaises(m.Blocked):
                self.accept(m.canonical(dict(self.cp,**{k:v})))
    def test_bool_attempt_rejected(self):
        self.obs['run_attempt']=True
        with self.assertRaises(m.Blocked):self.accept()
    def test_forged_findings_rejected(self):
        cp=copy.deepcopy(self.cp);cp['result']['findings'][0]['row_count']=-1
        cp['result_digest']=m.digest(cp['result'])
        with self.assertRaises(m.Blocked):self.accept(m.canonical(cp))
    def test_duplicate_json_rejected(self):
        with self.assertRaises(m.Blocked):m.parse(b'{"a":1,"a":2}')
    def test_nonfinite_rejected(self):
        with self.assertRaises(m.Blocked):m.parse(b'{"a":NaN}')
    def test_missing_input_not_replaced(self):
        inputs=dict(self.inputs);inputs.pop(m.INPUTS[0])
        with self.assertRaises(m.Blocked):m.business_review(inputs)
    def test_no_input_or_legacy_mutation(self):
        before=copy.deepcopy((self.p,self.inputs,self.cp))
        m.prepare_checkpoint(self.p,self.inputs,prior=self.cp,**dict(self.args,run_id=101))
        self.assertEqual(before,(self.p,self.inputs,self.cp))

if __name__ == '__main__':unittest.main()
