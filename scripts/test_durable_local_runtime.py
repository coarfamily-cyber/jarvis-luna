import copy,unittest
from unittest.mock import patch
import destination_core_epoch as e
import durable_local_ledger as d
import durable_local_runtime as m
import test_destination_core_epoch as fixture
import test_durable_local_ledger as lf
from test_owned_core_local import make_run

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        f=fixture.EpochTests();f.setUp();self.inputs=f.inputs;self.old=f.p
        l=lf.DurableTests();l.setUp();self.anchor=l.anchor;self.state=l.state
        self.policy=copy.deepcopy(self.old);self.policy['code_contract_digest']='f'*64
        self.config=dict(anchor=self.anchor,anchor_policy=self.old,predecessor_policy=self.old,writer_id=4242,
          approved_transition=dict(from_contract='a'*64,to_contract='f'*64,previous_state_digest=e.digest(self.state),review_reference='9'*64))
        self.run=make_run(rid=101,number=4);self.run['created_at']='2026-10-24T00:00:00Z'
        self.sealed=make_run(rid=self.state['last_run_id'],number=3);self.sealed['created_at']=self.state['last_created_at']
    def test_expired_old_artifact_not_required_for_durable_candidate(self):
        # Pure helper takes authenticated durable state, never an archive or URL.
        m.validate_configuration(self.config,self.policy)
        raw=m.prepare_candidate(self.policy,self.config,self.state,self.inputs,self.run)
        cp=e.parse(raw);self.assertEqual(cp['predecessor'],e.digest(self.state['checkpoint']))
        self.assertEqual(cp['epoch'],e.digest(self.policy));self.assertEqual(cp['sequence'],1)
        self.assertNotEqual(cp['epoch'],self.state['checkpoint']['epoch'])
    def test_rotation_preserves_old_bytes_and_unresolved_holds(self):
        before=e.canonical(self.state);cp=e.parse(m.prepare_candidate(self.policy,self.config,self.state,self.inputs,self.run))
        self.assertEqual(before,e.canonical(self.state));self.assertEqual(cp['holds'],e.HOLDS)
        self.assertEqual(cp['legacy_unresolved_digest'],self.state['checkpoint']['legacy_unresolved_digest'])
    def test_unreviewed_rotation_or_wrong_state_blocks(self):
        self.config['approved_transition']['previous_state_digest']='0'*64
        with self.assertRaises(e.Blocked):m.prepare_candidate(self.policy,self.config,self.state,self.inputs,self.run)
    def test_unknown_prior_epoch_blocks(self):
        self.state['checkpoint']['epoch']='0'*64
        with self.assertRaises(e.Blocked):m.prepare_candidate(self.policy,self.config,self.state,self.inputs,self.run)
    def test_scope_expansion_in_policy_blocks(self):
        self.policy['authorization_reference_digest']='0'*64
        with self.assertRaises(e.Blocked):m.validate_configuration(self.config,self.policy)
    def test_tail_inclusive_same_second_oldest_first(self):
        self.run['created_at']=self.sealed['created_at']
        with patch.object(m.r,'listing',return_value=[self.run,self.sealed]) as listing:
            rows=m.pending_runs(object(),self.anchor,self.state)
            self.assertEqual(rows,[self.run]);self.assertIn('created=%3E%3D',listing.call_args.args[1])
    def test_tail_deleted_anchor_or_gap_blocks(self):
        for rows in ([self.run],[self.sealed,dict(self.run,run_number=5)]):
            with patch.object(m.r,'listing',return_value=rows),self.assertRaises(e.Blocked):m.pending_runs(object(),self.anchor,self.state)
    def test_tail_duplicate_number_or_current_retry_blocks(self):
        for rows in ([self.sealed,self.run,dict(self.run,id=202)],[self.sealed,dict(self.run,run_attempt=2)]):
            with patch.object(m.r,'listing',return_value=rows),self.assertRaises(e.Blocked):m.pending_runs(object(),self.anchor,self.state)
    def test_late_historical_retry_not_used_as_new_state(self):
        old=dict(self.sealed,run_attempt=2)
        with patch.object(m.r,'listing',return_value=[old,self.run]):
            self.assertEqual(m.pending_runs(object(),self.anchor,self.state),[self.run])
        # Deliberately no claim that the old rerun was absent; only new accepted events are processed.
    def test_failed_event_rotation_then_success_keeps_predecessor_epoch_valid(self):
        event=dict(run_id=101,run_number=4,run_attempt=1,head_sha=self.run['head_sha'],workflow_id=777,
          kind='failed_local_no_retention',checkpoint=None,evidence_digest='2'*64,code_contract_digest='f'*64,created_at=self.run['created_at'])
        state,_=d.append(self.state,self.anchor,event,expected_commit='e'*40,active_contract='f'*64,approved_transition=self.config['approved_transition'])
        cp=e.parse(m.prepare_candidate(self.policy,self.config,state,self.inputs,dict(self.run,id=102,run_number=5)))
        self.assertEqual(cp['predecessor'],e.digest(self.state['checkpoint']));self.assertEqual(cp['sequence'],1)

if __name__=='__main__':unittest.main()
