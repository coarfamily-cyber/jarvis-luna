import base64,copy,hashlib,unittest
import durable_local_ledger as d
import destination_core_epoch as e
import test_destination_core_epoch as fixture

def git_hash(kind,raw):return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

class DurableTests(unittest.TestCase):
    def setUp(self):
        f=fixture.EpochTests();f.setUp();self.cp=f.cp
        self.anchor=dict(schema=d.SCHEMA,repository_id=e.REPOSITORY_ID,owner_id=e.OWNER_ID,workflow_id=777,
            through_run_number=3,through_created_at='2026-10-23T23:09:59Z',checkpoint=self.cp,evidence_root='1'*64,code_contract_digest='a'*64,approved_head='c'*40)
        self.state=d.bootstrap(self.anchor)
        cp=copy.deepcopy(self.cp);cp.update(sequence=1,predecessor=e.digest(self.cp),run_id=101,head_sha='d'*40)
        self.event=dict(run_id=101,run_number=4,run_attempt=1,head_sha='d'*40,workflow_id=777,
            kind='successful_checkpoint',checkpoint=cp,evidence_digest='2'*64,code_contract_digest='a'*64,created_at='2026-10-24T00:00:00Z')
    def append(self,event=None,state=None,**kw):
        return d.append(state or self.state,self.anchor,event or self.event,expected_commit='e'*40,active_contract='a'*64,**kw)
    def test_bootstrap_requires_exact_existing_checkpoint(self):
        d.validate_state(self.state,self.anchor)
        self.state['history_root']='0'*64
        with self.assertRaises(e.Blocked):d.validate_state(self.state,self.anchor)
    def test_success_compaction_preserves_counter_chain(self):
        state,changed=self.append();self.assertTrue(changed)
        self.assertEqual(state['last_run_number'],4);self.assertEqual(state['checkpoint']['predecessor'],e.digest(self.cp))
        self.assertEqual(state['anchor_digest'],e.digest(self.anchor));self.assertEqual(state['holds'],e.HOLDS)
    def test_duplicate_response_loss_is_idempotent(self):
        state,_=self.append();again,changed=self.append(state=state)
        self.assertFalse(changed);self.assertEqual(state,again)
    def test_duplicate_conflict_rejected(self):
        state,_=self.append();self.event['evidence_digest']='3'*64
        with self.assertRaises(e.Blocked):self.append(state=state)
    def test_no_gap_retry_replay_or_wrong_workflow(self):
        for k,v in [('run_number',5),('run_number',2),('run_attempt',2),('workflow_id',778)]:
            event=copy.deepcopy(self.event);event[k]=v
            with self.assertRaises(e.Blocked):self.append(event)
    def test_failure_tombstone_does_not_replace_checkpoint(self):
        event=dict(self.event,kind='failed_local_no_retention',checkpoint=None)
        state,_=self.append(event);self.assertEqual(state['checkpoint'],self.cp)
        self.assertEqual(state['last_run_number'],4);self.assertNotEqual(state['history_root'],self.state['history_root'])
    def test_failure_cannot_claim_checkpoint(self):
        event=dict(self.event,kind='failed_local_no_retention')
        with self.assertRaises(e.Blocked):self.append(event)
    def test_contract_change_requires_bound_review(self):
        self.event['code_contract_digest']='f'*64
        with self.assertRaises(e.Blocked):d.append(self.state,self.anchor,self.event,expected_commit='e'*40,active_contract='f'*64)
        approval=dict(from_contract='a'*64,to_contract='f'*64,previous_state_digest=e.digest(self.state),review_reference='9'*64)
        state,_=d.append(self.state,self.anchor,self.event,expected_commit='e'*40,active_contract='f'*64,approved_transition=approval)
        self.assertEqual(state['code_contract_digest'],'f'*64)
        approval['previous_state_digest']='8'*64
        with self.assertRaises(e.Blocked):d.append(self.state,self.anchor,self.event,expected_commit='e'*40,active_contract='f'*64,approved_transition=approval)
    def test_no_legacy_hold_or_inventory_reset(self):
        for key in ('legacy_inventory_digest','legacy_unresolved_digest','source_final_tail_digest'):
            event=copy.deepcopy(self.event);event['checkpoint'][key]='f'*64
            with self.assertRaises(e.Blocked):self.append(event)
    def test_no_private_raw_product_rows(self):
        event=copy.deepcopy(self.event);event['checkpoint']['result']['products']=[{'secret':'value'}]
        with self.assertRaises(e.Blocked):self.append(event)
    def test_impossible_counts_or_unknown_shape_rejected(self):
        for change in ({'row_count':0,'explicit_blocked_or_review_rows':999},{'row_schema_recognized':False,'row_count':0}):
            event=copy.deepcopy(self.event);result=event['checkpoint']['result'];result['findings'][0].update(change)
            event['checkpoint']['result_digest']=e.digest(result)
            with self.assertRaises(e.Blocked):self.append(event)
    def test_graphql_exact_path_expected_head_no_delete(self):
        state,_=self.append();request=d.graphql_commit_request(expected_commit='e'*40,state=state,anchor=self.anchor)
        value=request['variables']['input'];self.assertEqual(value['expectedHeadOid'],'e'*40)
        self.assertEqual(value['branch']['branchName'],'jarvis-owned-state')
        self.assertEqual(set(value['fileChanges']),{'additions'})
        self.assertEqual(value['fileChanges']['additions'][0]['path'],d.STATE_PATH)
    def test_graphql_rejects_private_extra_state(self):
        state,_=self.append();state['raw']={'customer':'secret'}
        with self.assertRaises(e.Blocked):d.graphql_commit_request(expected_commit='e'*40,state=state,anchor=self.anchor)
    def test_compaction_size_constant_over_many_events(self):
        state=self.state
        for n in range(4,1004):
            event=dict(self.event,run_id=1000+n,run_number=n,kind='failed_local_no_retention',checkpoint=None)
            state,_=d.append(state,self.anchor,event,expected_commit='e'*40,active_contract='a'*64)
        self.assertLess(len(d.bounded(state)),len(d.bounded(self.state))+100)
        self.assertEqual(state['event_count'],1000)
    def signed_fixture(self):
        state,_=self.append();raw=e.canonical(state);blobsha=git_hash('blob',raw)
        treebytes=b'100644 '+d.STATE_PATH.encode()+b'\0'+bytes.fromhex(blobsha);treehash=git_hash('tree',treebytes)
        tree={'sha':treehash,'truncated':False,'tree':[{'path':d.STATE_PATH,'mode':'100644','type':'blob','sha':blobsha}]}
        blob={'sha':blobsha,'encoding':'base64','size':len(raw),'content':base64.b64encode(raw).decode()}
        identity={'login':'github-actions[bot]','id':4242}
        meta={'sha':'9'*40,'author':identity,'committer':{'login':'web-flow','id':19864447},'parents':[{'sha':'e'*40}],
              'files':[{'filename':d.STATE_PATH,'status':'modified'}],
              'commit':{'tree':{'sha':treehash},'verification':{'verified':True,'reason':'valid',
                'signature':'-----BEGIN PGP SIGNATURE-----\nFIXTURE_NOT_REAL',
                'payload':'tree '+treehash+'\nparent '+'e'*40+'\nauthor fixture\ncommitter fixture\n\nfixture'}}}
        return meta,tree,blob
    def check(self,values):return d.check_signed_snapshot(*values,head='9'*40,anchor=self.anchor,writer_id=4242)
    def test_offline_signed_shape_not_authentication(self):
        state=self.check(self.signed_fixture());self.assertEqual(state['last_run_number'],4)
        with self.assertRaises(e.Blocked):d.AuthenticatedState(state,'9'*40,object())
        with self.assertRaises(e.Blocked):d.read_authenticated_state(object(),anchor=self.anchor,writer_id=4242)
    def test_wrong_writer_or_unsigned_rejected(self):
        for field,value in [('verified',False),('reason','bad_email'),('signature','arbitrary')]:
            v=self.signed_fixture();v[0]['commit']['verification'][field]=value
            with self.assertRaises(e.Blocked):self.check(v)
        v=self.signed_fixture();v[0]['committer']={'login':'attacker','id':4242}
        with self.assertRaises(e.Blocked):self.check(v)
    def test_extra_code_file_merge_or_replaced_blob_rejected(self):
        v=self.signed_fixture();v[0]['files'].append({'filename':'scripts/runtime.py','status':'modified'})
        with self.assertRaises(e.Blocked):self.check(v)
        v=self.signed_fixture();v[0]['parents'].append({'sha':'8'*40})
        with self.assertRaises(e.Blocked):self.check(v)
        v=self.signed_fixture();v[2]['content']=base64.b64encode(b'{}').decode()
        with self.assertRaises(e.Blocked):self.check(v)
    def test_tree_omission_or_symlink_rejected(self):
        for field,value in [('truncated',True),('tree',[])]:
            v=self.signed_fixture();v[1][field]=value
            with self.assertRaises(e.Blocked):self.check(v)
    def test_anchor_ancestry_rejects_orphan_rollback_extra_commit(self):
        state,_=self.append();good={'status':'ahead','merge_base_commit':{'sha':'c'*40},'total_commits':2}
        d.check_anchor_ancestry(good,state,self.anchor)
        for key,value in [('status','diverged'),('merge_base_commit',{'sha':'b'*40}),('total_commits',1),('total_commits',3)]:
            wrong=dict(good);wrong[key]=value
            with self.assertRaises(e.Blocked):d.check_anchor_ancestry(wrong,state,self.anchor)
    def test_missing_live_append_protection_rejected(self):
        rules=[{'type':t} for t in ('non_fast_forward','deletion','required_signatures')]
        d.check_append_rules(rules)
        for n in range(len(rules)):
            with self.assertRaises(e.Blocked):d.check_append_rules(rules[:n]+rules[n+1:])

if __name__=='__main__':unittest.main()
