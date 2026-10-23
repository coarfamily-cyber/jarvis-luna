import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import destination_core_epoch as e
import owned_core_local as r
import test_destination_core_epoch as fixture


def make_run(rid=100,number=1,status='completed'):
    repo={'id':e.REPOSITORY_ID,'full_name':e.REPOSITORY,'owner':{'id':e.OWNER_ID}}
    return dict(id=rid,run_attempt=1,run_number=number,workflow_id=777,head_sha='b'*40,path=e.WORKFLOW,
                head_branch='main',event='workflow_dispatch',repository=repo,head_repository=repo,
                status=status,conclusion='success' if status=='completed' else None)


def archive(raw,name='checkpoint.json',mode=0o100644):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        info=zipfile.ZipInfo(name);info.external_attr=mode<<16;z.writestr(info,raw)
    return out.getvalue()


class FakeReader:
    def __init__(self,raw,run=None):
        self.raw=archive(raw);self.run=run or make_run()
        rid=self.run['id']
        self.repo=dict(self.run['repository'])
        self.jobs=[dict(id=500,run_id=rid,run_attempt=1,head_sha='b'*40,status='completed',conclusion='success',
            steps=[dict(name=n,status='completed',conclusion='success') for n in r.REQUIRED_STEPS])]
        self.artifacts=[dict(id=600,name=f'owned-core-local-{rid}-1',expired=False,
            archive_download_url=r.API+'/actions/artifacts/600/zip',size_in_bytes=len(self.raw),
            digest='sha256:'+e.sha(self.raw),workflow_run=dict(id=rid,repository_id=e.REPOSITORY_ID,
            head_repository_id=e.REPOSITORY_ID,head_sha='b'*40,head_branch='main'))]
        self.runs=[self.run]
    def json(self,path):
        if path=='':return self.repo
        if '/jobs?' in path:return {'total_count':len(self.jobs),'jobs':copy.deepcopy(self.jobs)}
        if '/artifacts?' in path:return {'total_count':len(self.artifacts),'artifacts':copy.deepcopy(self.artifacts)}
        if '/runs?' in path:return {'total_count':len(self.runs),'workflow_runs':copy.deepcopy(self.runs)}
        raise AssertionError(path)
    def archive(self,aid):
        assert aid==600
        return self.raw


class RunnerTests(unittest.TestCase):
    def setUp(self):
        base=fixture.EpochTests();base.setUp()
        self.policy,self.inputs,self.raw,self.cp=base.p,base.inputs,base.raw,base.cp
        self.reader=FakeReader(self.raw)
        self.code_patch=patch.object(r,'verify_historical_code')
        self.code_patch.start();self.addCleanup(self.code_patch.stop)
    def authenticate(self,run=None,predecessor=None):
        return r.authenticate_checkpoint(self.reader,self.policy,run or make_run(),predecessor,
            root=Path('/fixture'),expected_result=e.business_review(self.inputs))[0]
    def test_local_archive_verification_only(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GITHUB_TOKEN':''}):
            reader=r.GithubReader(public_verification=True,artifact_directory=Path(tmp))
            (Path(tmp)/'600.zip').write_bytes(self.reader.raw)
            self.assertEqual(reader.archive(600),self.reader.raw)
            with self.assertRaises(e.Blocked):r.GithubReader(artifact_directory=Path(tmp))
    def test_missing_runner_token_not_bypassed(self):
        with patch.dict(os.environ,{'GITHUB_TOKEN':''}),self.assertRaises(e.Blocked):r.GithubReader()
    def test_authenticated_artifact_bindings(self):
        self.assertEqual(self.authenticate(),self.cp)
    def test_all_required_steps(self):
        self.reader.jobs[0]['steps'][1]['conclusion']='failure'
        with self.assertRaises(e.Blocked):self.authenticate()
    def test_wrong_artifact_repo(self):
        self.reader.artifacts[0]['workflow_run']['repository_id']=1334276889
        with self.assertRaises(e.Blocked):self.authenticate()
    def test_wrong_archive_digest(self):
        self.reader.raw+=b'x'
        with self.assertRaises(e.Blocked):self.authenticate()
    def test_ambiguous_artifacts(self):
        self.reader.artifacts.append(dict(self.reader.artifacts[0],id=601))
        with self.assertRaises(e.Blocked):self.authenticate()
    def test_unexpected_second_job(self):
        self.reader.jobs.append(dict(self.reader.jobs[0],id=501))
        with self.assertRaises(e.Blocked):self.authenticate()
    def test_wrong_attempt_rejected(self):
        run=make_run();run['run_attempt']=2
        with self.assertRaises(e.Blocked):self.authenticate(run)
    def test_failed_producer_not_baseline(self):
        run=make_run();run['conclusion']='failure'
        with self.assertRaises(e.Blocked):self.authenticate(run)
    def test_wrong_predecessor(self):
        with self.assertRaises(e.Blocked):self.authenticate(predecessor=self.cp)
    def test_archive_member_scope(self):
        for name in ('../checkpoint.json','/checkpoint.json','folder/checkpoint.json','other.json'):
            with self.subTest(name=name),self.assertRaises(e.Blocked):r.read_checkpoint_archive(archive(self.raw,name))
    def test_archive_symlink(self):
        with self.assertRaises(e.Blocked):r.read_checkpoint_archive(archive(self.raw,mode=0o120777))
    def test_archive_duplicate(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('checkpoint.json',self.raw);z.writestr('other.json',self.raw)
        with self.assertRaises(e.Blocked):r.read_checkpoint_archive(out.getvalue())
    def test_partial_page(self):
        class Broken:
            def json(self,_):return {'total_count':2,'jobs':[{'id':1}]}
        with self.assertRaises(e.Blocked):r.listing(Broken(),'/jobs','jobs')
    def test_duplicate_page_ids(self):
        class Broken:
            def json(self,_):return {'total_count':2,'jobs':[{'id':1},{'id':1}]}
        with self.assertRaises(e.Blocked):r.listing(Broken(),'/jobs','jobs')
    def test_pagination_complete(self):
        class Pages:
            def json(self,path):
                rows=[{'id':i} for i in (range(100) if path.endswith('&page=1') else range(100,101))]
                return {'total_count':101,'jobs':rows}
        self.assertEqual(len(r.listing(Pages(),'/jobs','jobs')),101)
    def test_missing_first_run_cannot_reset(self):
        self.reader.runs=[make_run(100,42,'in_progress')]
        with self.assertRaises(e.Blocked):r.run_inventory(self.reader,self.policy)
    def test_deleted_middle_run_rejected(self):
        self.reader.runs=[make_run(100,1),make_run(102,3,'in_progress')]
        with self.assertRaises(e.Blocked):r.run_inventory(self.reader,self.policy)
    def test_recreated_workflow_rejected(self):
        self.reader.runs[0]['workflow_id']=778
        with self.assertRaises(e.Blocked):r.run_inventory(self.reader,self.policy)
    def test_forged_result_recomputed(self):
        cp=copy.deepcopy(self.cp);cp['result']['findings'][0]['row_count']=999999
        cp['result_digest']=e.digest(cp['result'])
        self.reader=FakeReader(e.canonical(cp))
        with self.assertRaises(e.Blocked):self.authenticate()
    def test_run_repo_and_owner(self):
        run=make_run();run['head_repository']=copy.deepcopy(run['head_repository'])
        run['head_repository']['owner']['id']=123
        with self.assertRaises(e.Blocked):r.validate_run(run)
    def test_live_genesis_algorithm_candidate_only(self):
        self.reader.runs=[make_run(status='in_progress')]
        env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY=e.REPOSITORY,GITHUB_REPOSITORY_ID=str(e.REPOSITORY_ID),
                 GITHUB_REPOSITORY_OWNER_ID=str(e.OWNER_ID),GITHUB_RUN_ID='100',GITHUB_RUN_ATTEMPT='1',GITHUB_SHA='b'*40)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();out=Path(tmp)/'out'
            config=root/r.CONFIG;config.mkdir(parents=True)
            seal=dict(epoch=e.digest(self.policy),workflow_id=777,run_id=100,run_attempt=1,head_sha='b'*40,
                checkpoint_digest=e.digest(self.cp),artifact_id=600,artifact_digest='sha256:'+e.sha(self.reader.raw))
            (config/'genesis-seal.json').write_bytes(e.canonical(seal))
            with patch.object(r,'load_context',return_value=(self.policy,object(),self.inputs)),\
                 patch.object(r,'validate_local_inputs',return_value=self.inputs),\
                 patch.object(r,'GithubReader',return_value=self.reader),\
                 patch.object(r,'git',return_value=('b'*40+'\n').encode()),patch.dict(os.environ,env):
                result=r.run(root,out)
            self.assertEqual(result['status'],'checkpoint_candidate_retention_pending')
            self.assertEqual(e.parse((out/'checkpoint.json').read_bytes())['sequence'],0)
    def test_terminal_genesis_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(r,'load_context',return_value=(self.policy,object(),self.inputs)),\
                 patch.object(r,'validate_local_inputs',return_value=self.inputs),\
                 patch.object(r,'GithubReader',return_value=self.reader):
                result=r.run(Path(tmp),None,verify_run=100)
            self.assertEqual(result['status'],'authenticated_destination_local_checkpoint')
            self.assertEqual(result['sequence'],0)
            self.assertFalse(result['full_core_recovery'])
    def test_followup_restores_real_fixture_bytes(self):
        self.reader.runs=[make_run(),make_run(101,2,'in_progress')]
        env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY=e.REPOSITORY,GITHUB_REPOSITORY_ID=str(e.REPOSITORY_ID),
                 GITHUB_REPOSITORY_OWNER_ID=str(e.OWNER_ID),GITHUB_RUN_ID='101',GITHUB_RUN_ATTEMPT='1',GITHUB_SHA='b'*40)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();out=Path(tmp)/'out'
            config=root/r.CONFIG;config.mkdir(parents=True)
            seal=dict(epoch=e.digest(self.policy),workflow_id=777,run_id=100,run_attempt=1,head_sha='b'*40,
                checkpoint_digest=e.digest(self.cp),artifact_id=600,artifact_digest='sha256:'+e.sha(self.reader.raw))
            (config/'genesis-seal.json').write_bytes(e.canonical(seal))
            with patch.object(r,'load_context',return_value=(self.policy,object(),self.inputs)),\
                 patch.object(r,'validate_local_inputs',return_value=self.inputs),\
                 patch.object(r,'GithubReader',return_value=self.reader),\
                 patch.object(r,'git',return_value=('b'*40+'\n').encode()),patch.dict(os.environ,env):
                result=r.run(root,out)
            cp=e.parse((out/'checkpoint.json').read_bytes())
            self.assertEqual(result['sequence'],1)
            self.assertEqual(cp['predecessor'],e.digest(self.cp))
            self.assertEqual(cp['holds'],e.HOLDS)

if __name__=='__main__':unittest.main()
