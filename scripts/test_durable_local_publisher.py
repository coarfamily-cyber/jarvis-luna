import unittest
from unittest.mock import patch
import os
import durable_local_publisher as p
import durable_local_ledger as d
import destination_core_epoch as e
import test_destination_core_epoch as fixture
import test_durable_local_ledger as ledger_fixture
from test_owned_core_local import archive,make_run

class PublisherTests(unittest.TestCase):
    def setUp(self):
        f=fixture.EpochTests();f.setUp();self.policy=f.p;self.inputs=f.inputs
        l=ledger_fixture.DurableTests();l.setUp();self.anchor=l.anchor;self.state=l.state;self.cp=l.event['checkpoint']
        self.run=make_run(rid=101,number=4);self.run['head_sha']='d'*40
        self.run['created_at']='2026-10-24T00:00:00Z'
        names=['Set up job','Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
          'Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',*p.r.REQUIRED_STEPS,
          'Post Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',
          'Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1','Complete job']
        self.jobs=[dict(id=900,run_id=101,run_attempt=1,head_sha='d'*40,status='completed',conclusion='success',
            steps=[dict(name=n,status='completed',conclusion='success') for n in names])]
        self.zip=archive(e.canonical(self.cp))
        self.artifacts=[dict(id=901,name='owned-core-local-101-1',expired=False,size_in_bytes=len(self.zip),
            archive_download_url=p.r.API+'/actions/artifacts/901/zip',digest='sha256:'+e.sha(self.zip),
            workflow_run=dict(id=101,repository_id=e.REPOSITORY_ID,head_repository_id=e.REPOSITORY_ID,head_branch='main',head_sha='d'*40))]
    def check(self,state=None):
        return p.check_terminal_evidence(self.run,self.jobs,self.artifacts,self.zip,policy=self.policy,anchor=self.anchor,
                 state=state or self.state,expected_result=e.business_review(self.inputs))
    def configure_failure(self):
        self.run['conclusion']=self.jobs[0]['conclusion']='failure';self.artifacts=[];self.zip=None
        for index,conclusion in [(3,'failure'),(4,'skipped'),(5,'skipped')]:self.jobs[0]['steps'][index]['conclusion']=conclusion
    def test_terminal_success_receipt(self):
        event=self.check();self.assertEqual(event['kind'],'successful_checkpoint')
        state,changed=d.append(self.state,self.anchor,event,expected_commit='e'*40,active_contract='a'*64)
        self.assertTrue(changed);self.assertEqual(state['checkpoint'],self.cp)
    def test_unknown_write_outcome_exact_event_reread_idempotent(self):
        event=self.check();state,_=d.append(self.state,self.anchor,event,expected_commit='e'*40,active_contract='a'*64)
        observed=self.check(state=state);self.assertEqual(observed,event)
        _,changed=d.append(state,self.anchor,observed,expected_commit='9'*40,active_contract='a'*64)
        self.assertFalse(changed)
    def test_inprogress_upload_not_terminal_success(self):
        self.run['status']='in_progress'
        with self.assertRaises(e.Blocked):self.check()
    def test_failed_local_tombstone_preserves_checkpoint(self):
        self.configure_failure();event=self.check();self.assertIsNone(event['checkpoint'])
        state,_=d.append(self.state,self.anchor,event,expected_commit='e'*40,active_contract='a'*64)
        self.assertEqual(state['checkpoint'],self.state['checkpoint'])
        self.assertEqual(self.check(state=state),event)
    def test_ambiguous_failed_upload_blocks(self):
        self.configure_failure();self.jobs[0]['steps'][4]['conclusion']='failure'
        with self.assertRaises(e.Blocked):self.check()
    def test_artifact_digest_expiry_and_wrong_head_block(self):
        for field,value in [('digest','sha256:'+'0'*64),('expired',True),('size_in_bytes',1)]:
            old=self.artifacts[0][field];self.artifacts[0][field]=value
            with self.assertRaises(e.Blocked):self.check()
            self.artifacts[0][field]=old
    def test_extra_job_step_or_missing_job_blocks(self):
        self.jobs[0]['steps'].append(dict(name='unreviewed',status='completed',conclusion='success'))
        with self.assertRaises(e.Blocked):self.check()
        self.jobs=[]
        with self.assertRaises(e.Blocked):self.check()
    def test_public_schedule_allowed_pr_and_retry_denied(self):
        self.run['event']='schedule';self.check()
        for key,value in [('event','pull_request'),('run_attempt',2),('head_branch','attacker')]:
            old=self.run[key];self.run[key]=value
            with self.assertRaises(e.Blocked):self.check()
            self.run[key]=old
    def test_no_forged_terminal_receipt(self):
        with self.assertRaises(e.Blocked):p.TerminalReceipt(self.check(),e.digest(self.state),object())
    def test_same_event_changed_evidence_blocks(self):
        event=self.check();state,_=d.append(self.state,self.anchor,event,expected_commit='e'*40,active_contract='a'*64)
        self.jobs[0]['id']=901
        with self.assertRaises(e.Blocked):self.check(state=state)

    def initializer_environment(self):
        return {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':e.REPOSITORY,'GITHUB_REPOSITORY_ID':str(e.REPOSITORY_ID),
          'GITHUB_REPOSITORY_OWNER_ID':str(e.OWNER_ID),'GITHUB_EVENT_NAME':'workflow_dispatch',
          'GITHUB_WORKFLOW_REF':e.REPOSITORY+'/'+p.PUBLISHER_WORKFLOW+'@refs/heads/main','GITHUB_TOKEN':'fixture-token'}
    def test_initialize_exact_anchor_single_post_and_authentic_reread(self):
        rules=[{'type':x} for x in ('non_fast_forward','deletion','required_signatures')]
        ref={'ref':'refs/heads/jarvis-owned-state','object':{'type':'commit','sha':self.anchor['approved_head']}}
        observed=d.AuthenticatedState(self.state,'9'*40,d._STATE_SEAL)
        with patch.dict(os.environ,self.initializer_environment(),clear=True):
            reader=p.r.GithubReader()
            with patch.object(p.r,'verify_repository'),patch.object(reader,'json',side_effect=[ref,rules]),patch.object(p,'post_state',return_value='9'*40) as post,patch.object(d,'read_authenticated_state',return_value=observed):
                self.assertEqual(p.initialize(reader,anchor=self.anchor,writer_id=4242),observed)
                self.assertEqual(post.call_count,1)
                request=post.call_args.args[1]['variables']['input']
                self.assertEqual(request['expectedHeadOid'],self.anchor['approved_head'])
                self.assertEqual(request['fileChanges']['additions'][0]['path'],d.STATE_PATH)
    def test_initialize_cannot_reset_existing_or_wrong_head(self):
        with patch.dict(os.environ,self.initializer_environment(),clear=True):
            reader=p.r.GithubReader()
            ref={'ref':'refs/heads/jarvis-owned-state','object':{'type':'commit','sha':'8'*40}}
            with patch.object(p.r,'verify_repository'),patch.object(reader,'json',return_value=ref),patch.object(p,'post_state') as post,self.assertRaises(e.Blocked):
                p.initialize(reader,anchor=self.anchor,writer_id=4242)
            post.assert_not_called()
    def test_initialize_automatic_event_denied_before_read_or_write(self):
        env=self.initializer_environment();env['GITHUB_EVENT_NAME']='workflow_run'
        with patch.dict(os.environ,env,clear=True):
            reader=p.r.GithubReader()
            with patch.object(reader,'json') as read,patch.object(p,'post_state') as post,self.assertRaises(e.Blocked):
                p.initialize(reader,anchor=self.anchor,writer_id=4242)
            read.assert_not_called();post.assert_not_called()

if __name__=='__main__':unittest.main()
