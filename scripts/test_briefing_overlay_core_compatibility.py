"""Real Git inventory and runtime-entry regressions with offline GitHub fixtures.

All API/signature responses below are TEST FIXTURES, not live authentication or
recovery evidence. No public commit, signed state, external POST, or rerun occurs.
"""
import base64
from copy import deepcopy
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import destination_core_epoch as e
import durable_local_runtime as runtime
import durable_local_publisher as publisher
import durable_local_ledger as ledger
import owned_core_local as core
from team_briefing_overlay import load_team_briefings, load_team_feeds
from test_owned_core_local import archive

ROOT = Path(__file__).resolve().parent.parent
BAD_HEAD = '2d9d92da0372de683c66c983a8ee8bec9f25620a'
APPROVED_HEAD = '7bb9b912d176b93cb7a5e2ac053ad67c09ba9255'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def blob(raw, kind='blob'):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


class CoreCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='briefing-core-fixture-')
        cls.root = Path(cls.tmp.name) / 'repo'
        # Local object sharing only; no network. Fixture commits stay under /tmp.
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ROOT), str(cls.root)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        git(cls.root, 'checkout', BAD_HEAD)
        cls.policy = e.parse((cls.root / core.CONFIG / 'policy.json').read_bytes())
        cls.record = core.provenance.parse_record((cls.root / core.CONFIG / 'import-record.json').read_bytes())
        try:
            core.validate_local_inputs(cls.root, cls.policy, cls.record)
        except e.Blocked as exc:
            cls.original_failure = str(exc)
        else:
            raise AssertionError('the actual historical inventory conflict was not reproduced')
        for path in ('data/manual/team_briefings.json', 'data/team_feeds.json'):
            shutil.copyfile(ROOT / path, cls.root / path)
        git(cls.root, 'add', 'data/manual/team_briefings.json', 'data/team_feeds.json')
        git(cls.root, '-c', 'user.name=Offline Test Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-m', 'TEST FIXTURE ONLY: restore imported data')
        cls.head = git(cls.root, 'rev-parse', 'HEAD').decode().strip()
        shutil.copytree(ROOT / 'review', cls.root / 'review')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def metadata(self, repository, suffix, deadline, cap):
        # Supply only the HTTPS metadata boundary; real tree/hash/import checks run.
        identity = core.provenance.LEGACY if repository == core.provenance.LEGACY[0] else core.provenance.DESTINATION
        if not suffix:
            return {'full_name': identity[0], 'id': identity[1], 'owner': {'id': identity[2]}, 'private': False}
        if suffix.startswith('/git/commits/'):
            commit = suffix.rsplit('/', 1)[-1]
            tail = e.parse((self.root / core.CONFIG / 'source-final-tail.json').read_bytes())
            tree = tail['tree'] if commit == tail['commit'] else git(self.root, 'rev-parse', commit+'^{tree}').decode().strip()
            return {'sha': commit, 'tree': {'sha': tree}}
        raise AssertionError('unexpected fixture request: '+suffix)

    def test_real_failure_and_contract_unchanged(self):
        self.assertEqual(self.original_failure, 'legacy_head_inventory_changed')
        self.assertEqual(publisher.contract_digest(self.root), self.policy['code_contract_digest'])
        self.assertEqual(publisher.contract_digest(self.root, BAD_HEAD), self.policy['code_contract_digest'])
        with patch.object(core.snapshot, '_get', side_effect=self.metadata):
            policy, config, record, inputs = runtime.load_context(self.root)
        self.assertEqual(policy, self.policy)
        self.assertEqual(set(inputs), set(e.INPUTS))
        self.assertFalse(e.business_review(inputs)['full_core_recovery'])

    def test_approved_content_and_obsidian_are_preserved(self):
        expected = json.loads(git(ROOT, 'show', APPROVED_HEAD+':data/manual/team_briefings.json'))
        self.assertEqual(load_team_briefings(ROOT), expected)
        feed = json.loads(git(ROOT, 'show', APPROVED_HEAD+':data/team_feeds.json'))
        self.assertEqual(load_team_feeds(ROOT), feed)
        changed = git(self.root, 'diff', '--name-only', BAD_HEAD, 'HEAD').decode().splitlines()
        self.assertEqual(set(changed), {'data/manual/team_briefings.json', 'data/team_feeds.json'})
        for path in ('obsidian/JARVIS_LUNA/.obsidian/graph.json',
                     'obsidian/JARVIS_LUNA/Briefings/JARVIS Graph Guide.md'):
            self.assertEqual(git(self.root, 'show', 'HEAD:'+path), git(ROOT, 'show', BAD_HEAD+':'+path))

    def test_unrelated_worktree_tampering_is_still_rejected(self):
        path = self.root / e.INPUTS[0]; before = path.read_bytes()
        try:
            path.write_bytes(before+b'\n')
            with self.assertRaisesRegex(e.Blocked, 'legacy_worktree_modified'):
                core.validate_local_inputs(self.root, self.policy, self.record)
        finally:
            path.write_bytes(before)

    def test_unrelated_committed_tampering_is_still_rejected(self):
        path = self.root / 'data/product_master.json'; before = path.read_bytes()
        try:
            path.write_bytes(before+b'\n'); git(self.root, 'add', 'data/product_master.json')
            tree = git(self.root, 'write-tree').decode().strip()
            env = {**os.environ, 'GIT_AUTHOR_NAME': 'Offline Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
                   'GIT_COMMITTER_NAME': 'Offline Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}
            commit = subprocess.check_output(['git','-C',str(self.root),'commit-tree',tree,'-p',self.head],
                                             input=b'TEST FIXTURE ONLY\n',env=env).decode().strip()
            git(self.root, 'update-ref', 'HEAD', commit)
            with self.assertRaisesRegex(e.Blocked, 'legacy_head_inventory_changed'):
                core.validate_local_inputs(self.root, self.policy, self.record)
        finally:
            git(self.root, 'update-ref', 'HEAD', self.head)
            git(self.root, 'reset', '--mixed', self.head)
            path.write_bytes(before)

    def test_extra_file_and_mode_tampering_remain_blocked(self):
        extra = self.root / 'data/unapproved-fixture.json'
        try:
            extra.write_text('{}')
            with self.assertRaisesRegex(e.Blocked, 'legacy_worktree_extra_or_missing'):
                core.validate_local_inputs(self.root, self.policy, self.record)
        finally:
            extra.unlink()
        path = self.root / 'data/team_feeds.json'; mode = path.stat().st_mode
        try:
            path.chmod(0o755)
            with self.assertRaisesRegex(e.Blocked, 'legacy_worktree_modified'):
                core.validate_local_inputs(self.root, self.policy, self.record)
        finally:
            path.chmod(mode)

    def runtime_fixture(self, stack):
        stack.enter_context(patch.object(core.snapshot, '_get', side_effect=self.metadata))
        policy, config, record, inputs = runtime.load_context(self.root)
        anchor = config['anchor']
        # Synthetic prior, deliberately not the live sequence-42 ledger.
        state = ledger.bootstrap(anchor)
        cp = e.parse(e.prepare_checkpoint(policy, inputs, run_id=1004, run_attempt=1,
                                         head_sha=BAD_HEAD, legacy_inventory_digest=policy['legacy_inventory_digest']))
        cp.update(sequence=2, predecessor=e.digest(anchor['checkpoint']))
        state.update(checkpoint=cp, code_contract_digest=policy['code_contract_digest'], event_count=1,
                     last_run_number=4, last_run_id=1004, last_created_at='2026-11-01T00:00:00Z',
                     last_event_digest='a'*64)
        ledger.validate_state(state, anchor)
        repo = {'id':e.REPOSITORY_ID,'full_name':e.REPOSITORY,'owner':{'id':e.OWNER_ID}}
        sealed = dict(id=1004,run_number=4,created_at=state['last_created_at'])
        run = dict(id=1005,run_number=5,run_attempt=1,workflow_id=policy['genesis_workflow_id'],
                   head_sha=self.head,path=e.WORKFLOW,head_branch='main',event='schedule',
                   repository=repo,head_repository=repo,status='in_progress',conclusion=None,
                   created_at='2026-11-01T01:00:00Z')
        transport = {'state':state,'head':'9'*40,'run':run,'archive':None}

        def request(reader, url, **kwargs):
            suffix = url.removeprefix(core.API)
            current = transport['state']; raw = e.canonical(current); oid = blob(raw)
            tree_bytes = b'100644 '+ledger.STATE_PATH.encode()+b'\0'+bytes.fromhex(oid)
            tree_oid = blob(tree_bytes, 'tree')
            if suffix == '': return e.canonical(repo)
            if suffix == '/git/ref/heads/jarvis-owned-state':
                return e.canonical({'ref':'refs/heads/jarvis-owned-state','object':{'type':'commit','sha':transport['head']}})
            if suffix == '/commits/'+transport['head']:
                return e.canonical({'sha':transport['head'],'author':{'login':'github-actions[bot]','id':config['writer_id']},
                    'committer':{'login':'web-flow','id':19864447},'parents':[{'sha':current['previous_commit']}],
                    'files':[{'filename':ledger.STATE_PATH,'status':'modified'}],
                    'commit':{'tree':{'sha':tree_oid},'verification':{'verified':True,'reason':'valid',
                    'signature':'-----BEGIN PGP SIGNATURE-----\nTEST FIXTURE NOT A REAL SIGNATURE',
                    'payload':'tree '+tree_oid+'\nparent '+current['previous_commit']+'\nfixture\n'}}})
            if suffix == '/git/trees/'+tree_oid:
                return e.canonical({'sha':tree_oid,'truncated':False,'tree':[{'path':ledger.STATE_PATH,'mode':'100644','type':'blob','sha':oid}]})
            if suffix == '/git/blobs/'+oid:
                return e.canonical({'sha':oid,'encoding':'base64','size':len(raw),'content':base64.b64encode(raw).decode()})
            if suffix.startswith('/compare/'):
                return e.canonical({'status':'ahead','merge_base_commit':{'sha':anchor['approved_head']},'total_commits':current['event_count']+1})
            if suffix.startswith('/rules/branches/'):
                return e.canonical([{'type':v} for v in ('non_fast_forward','deletion','required_signatures')])
            if suffix.startswith('/actions/workflows/'):
                rows = [sealed, transport['run']]
                return e.canonical({'total_count':len(rows),'workflow_runs':rows})
            if suffix == '/actions/runs/1005': return e.canonical(transport['run'])
            if '/1005/attempts/1/jobs?' in suffix:
                names = ['Set up job','Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
                         'Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',*core.REQUIRED_STEPS,
                         'Post Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',
                         'Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1','Complete job']
                success = transport['run']['conclusion']=='success'
                conclusions = ['success']*8 if success else ['success']*3+['failure','skipped','skipped','success','success']
                steps=[dict(name=n,status='completed',conclusion=c) for n,c in zip(names,conclusions)]
                job=dict(id=900,run_id=1005,run_attempt=1,head_sha=transport['run']['head_sha'],status='completed',
                         conclusion=transport['run']['conclusion'],steps=steps)
                return e.canonical({'total_count':1,'jobs':[job]})
            if '/1005/artifacts?' in suffix:
                data=transport['archive']; rows=[]
                if data is not None:
                    rows=[dict(id=901,name='owned-core-local-1005-1',expired=False,size_in_bytes=len(data),
                               archive_download_url=core.API+'/actions/artifacts/901/zip',digest='sha256:'+e.sha(data),
                               workflow_run=dict(id=1005,repository_id=e.REPOSITORY_ID,head_repository_id=e.REPOSITORY_ID,
                                                 head_branch='main',head_sha=transport['run']['head_sha']))]
                return e.canonical({'total_count':len(rows),'artifacts':rows})
            if suffix == '/actions/artifacts/901/zip': return transport['archive']
            raise AssertionError('unexpected offline transport request: '+suffix)

        def post(reader, request_data):
            value=request_data['variables']['input']
            self.assertEqual(value['expectedHeadOid'],transport['head'])
            self.assertEqual(value['branch']['branchName'],'jarvis-owned-state')
            self.assertEqual(set(value['fileChanges']),{'additions'})
            addition=value['fileChanges']['additions'];self.assertEqual(len(addition),1)
            self.assertEqual(addition[0]['path'],ledger.STATE_PATH)
            transport['state']=e.parse(base64.b64decode(addition[0]['contents']))
            transport['head']='8'*40
            return transport['head']
        stack.enter_context(patch.object(core.GithubReader,'_request',request))
        transport['post'] = stack.enter_context(patch.object(publisher,'post_state',side_effect=post))
        return transport

    def environment(self, publisher_mode=False):
        return {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':e.REPOSITORY,'GITHUB_REPOSITORY_ID':str(e.REPOSITORY_ID),
                'GITHUB_REPOSITORY_OWNER_ID':str(e.OWNER_ID),'GITHUB_SHA':self.head,'GITHUB_REF':'refs/heads/main',
                'GITHUB_WORKFLOW_REF':e.REPOSITORY+'/'+(publisher.PUBLISHER_WORKFLOW if publisher_mode else e.WORKFLOW)+'@refs/heads/main',
                'GITHUB_EVENT_NAME':'workflow_run' if publisher_mode else 'schedule',
                'GITHUB_TOKEN':'OFFLINE_TEST_TOKEN_NOT_A_CREDENTIAL','GITHUB_RUN_ID':'1005','GITHUB_RUN_ATTEMPT':'1'}

    def invoke(self, mode, output=None):
        args = ['durable_local_runtime.py', mode, '--root', str(self.root)]
        if output is not None:
            args.extend(['--output', str(output)])
        captured = io.StringIO()
        with patch.object(sys, 'argv', args), redirect_stdout(captured):
            result = runtime.main()
        self.assertEqual(result, 0, captured.getvalue())
        return json.loads(captured.getvalue())

    def test_full_producer_and_publisher_success_entry_paths_offline(self):
        with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='offline-checkpoint-fixture-') as output:
            transport=self.runtime_fixture(stack); before=deepcopy(transport['state'])
            with patch.dict(os.environ,self.environment(),clear=True):
                result=self.invoke('produce',Path(output)/'candidate')
            self.assertEqual(result['status'],'durable_candidate_retention_pending')
            self.assertFalse(result['full_core_recovery'])
            self.assertEqual(transport['state'],before);transport['post'].assert_not_called()
            raw=(Path(output)/'candidate/checkpoint.json').read_bytes()
            transport['archive']=archive(raw)
            transport['run'].update(status='completed',conclusion='success')
            with patch.dict(os.environ,self.environment(True),clear=True):
                result=self.invoke('publish')
            self.assertEqual(result['published_run_ids'],[1005])
            self.assertEqual(transport['post'].call_count,1)
            self.assertEqual(transport['state']['checkpoint']['sequence'],before['checkpoint']['sequence']+1)
            self.assertFalse(result['full_core_recovery'])

    def test_publisher_records_failed_old_head_without_rewriting_checkpoint(self):
        with ExitStack() as stack:
            transport=self.runtime_fixture(stack); before=deepcopy(transport['state']['checkpoint'])
            transport['run'].update(status='completed',conclusion='failure',head_sha=BAD_HEAD)
            with patch.dict(os.environ,self.environment(True),clear=True):
                result=self.invoke('publish')
            self.assertEqual(result['published_run_ids'],[1005])
            self.assertEqual(transport['state']['checkpoint'],before)
            self.assertEqual(transport['post'].call_count,1)


if __name__ == '__main__':
    unittest.main()
