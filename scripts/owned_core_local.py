#!/usr/bin/env python3
"""Trusted own-GitHub-only runner for the distinct saved-input local epoch.

No provider request or source/legacy mutation. Every network request goes to
fixed GitHub API endpoints or a digest-bound GitHub artifact storage redirect.
The business computation itself is a pure function with no external execution.
"""
from __future__ import annotations
import argparse
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import destination_core_epoch as epoch
import repository_provenance as provenance
import repository_snapshot_reader as snapshot

API = 'https://api.github.com/repos/' + epoch.REPOSITORY
CONFIG = 'config/destination-core-local/'
CODE_FILES = ('scripts/destination_core_epoch.py', 'scripts/owned_core_local.py',
              'scripts/repository_provenance.py', 'scripts/repository_snapshot_reader.py',
              epoch.WORKFLOW)
REQUIRED_STEPS = ('Verify destination epoch and compute local review',
                  'Retain destination local checkpoint')
CAP = 8*1024*1024
MAX_PAGES = 10
MAX_ARCHIVE = 4*1024*1024
DEADLINE = 300

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GithubReader:
    """Production transport has no injectable URL, opener, token source or host."""
    def __init__(self, *, public_verification=False, artifact_directory=None):
        self.artifact_directory=artifact_directory
        epoch.need(artifact_directory is None or public_verification, 'local_artifacts_verification_only')
        self.deadline = time.monotonic()+DEADLINE
        token = os.environ.get('GITHUB_TOKEN', '')
        epoch.need((token or public_verification) and not any(c.isspace() for c in token), 'github_runner_token_required')
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirect())
        self.requests = 0

    def _body(self, response, cap):
        headers = response.headers
        sizes = headers.get_all('Content-Length') or []
        transfers = headers.get_all('Transfer-Encoding') or []
        encodings = headers.get_all('Content-Encoding') or []
        epoch.need(len(sizes)<=1 and len(transfers)<=1 and len(encodings)<=1 and
                   not (sizes and transfers), 'http_framing')
        epoch.need(not transfers or transfers[0].lower().strip()=='chunked', 'http_transfer_encoding')
        epoch.need(not encodings or encodings[0].lower().strip()=='identity', 'http_content_encoding')
        expected = None
        if sizes:
            epoch.need(sizes[0].isascii() and sizes[0].isdigit() and len(sizes[0])<=9, 'http_length')
            expected=int(sizes[0]);epoch.need(expected<=cap, 'http_size')
        chunks=[];size=0
        while True:
            epoch.need(time.monotonic()<self.deadline, 'github_deadline')
            chunk=response.read1(min(65536,cap+1-size))
            epoch.need(time.monotonic()<self.deadline, 'github_deadline')
            if not chunk:break
            chunks.append(chunk);size+=len(chunk);epoch.need(size<=cap,'http_size')
        epoch.need(expected is None or expected==size,'truncated_http_body')
        return b''.join(chunks)

    def _request(self, url, *, api=True, cap=CAP, redirect=False):
        remaining=self.deadline-time.monotonic()
        epoch.need(remaining>0 and self.requests<100,'github_request_bound')
        self.requests+=1
        headers={'User-Agent':'Jarvis-owned-local-epoch/1','Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28'}
        if api and self._token:headers['Authorization']='Bearer '+self._token
        request=urllib.request.Request(url,headers=headers)
        try:
            with self._opener.open(request,timeout=min(20,remaining)) as response:
                epoch.need(response.status==200,'github_http_status')
                return self._body(response,cap)
        except urllib.error.HTTPError as exc:
            if redirect and exc.code==302:
                locations=exc.headers.get_all('Location') or []
                epoch.need(len(locations)==1,'artifact_redirect_ambiguous')
                target=urllib.parse.urlsplit(locations[0])
                epoch.need(target.scheme=='https' and target.port in (None,443) and
                           target.username is None and target.password is None and not target.fragment and
                           re.fullmatch(r'productionresultssa[a-z0-9]*\.blob\.core\.windows\.net',target.hostname or ''),
                           'artifact_redirect_host')
                # NEVER forward GitHub authorization to blob storage.
                return self._request(locations[0],api=False,cap=cap,redirect=False)
            raise epoch.Blocked('github_http_unavailable') from None
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            raise epoch.Blocked('github_transport_unavailable') from None

    def json(self, suffix):
        epoch.need(type(suffix)is str and (suffix=='' or suffix.startswith('/')) and
                   not any(c in suffix for c in ('#','\\','\r','\n')) and '..' not in suffix,'github_endpoint')
        return epoch.parse(self._request(API+suffix))

    def archive(self, identity):
        epoch.positive(identity)
        if self.artifact_directory is not None:
            # Untrusted downloaded bytes: never treated as authenticated until
            # SHA256 matches fresh fixed-origin GitHub artifact metadata.
            return file_bytes(self.artifact_directory.resolve(),str(identity)+'.zip',cap=MAX_ARCHIVE)
        return self._request(API+f'/actions/artifacts/{identity}/zip',cap=MAX_ARCHIVE,redirect=True)


def listing(reader, path, key):
    """Complete bounded pagination; caller repeats producer discovery for stability."""
    result=[];total=None
    for page in range(1,MAX_PAGES+1):
        separator='&' if '?' in path else '?'
        value=reader.json(path+separator+f'per_page=100&page={page}')
        epoch.need(type(value)is dict and type(value.get('total_count'))is int and
                   0<=value['total_count']<=MAX_PAGES*100 and type(value.get(key))is list,'listing_shape')
        if total is None:total=value['total_count']
        epoch.need(value['total_count']==total,'listing_changed')
        rows=value[key]
        epoch.need(len(rows)<=100 and len(result)+len(rows)<=total,'listing_count')
        result.extend(rows)
        if len(result)==total:
            epoch.need(all(type(r)is dict and type(r.get('id'))is int for r in result),'listing_identity')
            epoch.need(len({r['id'] for r in result})==len(result),'duplicate_listing_identity')
            return result
        epoch.need(len(rows)==100,'listing_incomplete')
    raise epoch.Blocked('listing_page_bound')


def verify_repository(reader):
    value=reader.json('')
    epoch.need(type(value)is dict and value.get('full_name')==epoch.REPOSITORY and
               value.get('id')==epoch.REPOSITORY_ID and type(value.get('owner'))is dict and
               value['owner'].get('id')==epoch.OWNER_ID,'wrong_destination_repository')


def validate_run(run, *, terminal=False):
    epoch.need(type(run)is dict,'run_shape')
    for k in ('id','run_attempt','run_number'):epoch.positive(run.get(k))
    epoch.hashed(run.get('head_sha'),40)
    epoch.need(run.get('path')==epoch.WORKFLOW and run.get('head_branch')=='main' and
               run.get('event')=='workflow_dispatch','producer_scope')
    for k in ('repository','head_repository'):
        repo=run.get(k)
        epoch.need(type(repo)is dict and repo.get('id')==epoch.REPOSITORY_ID and
                   repo.get('full_name')==epoch.REPOSITORY and type(repo.get('owner'))is dict and
                   repo['owner'].get('id')==epoch.OWNER_ID,'run_repository_binding')
    if terminal:epoch.need(run.get('status')=='completed' and run.get('conclusion')=='success','producer_not_successful')
    epoch.need(run['run_attempt']==1,'rerun_requires_explicit_reconciliation')


def read_checkpoint_archive(raw):
    epoch.need(type(raw)is bytes and 0<len(raw)<=MAX_ARCHIVE,'archive_size')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            members=z.infolist()
            epoch.need(len(members)==1 and members[0].filename=='checkpoint.json','archive_members')
            member=members[0];mode=member.external_attr>>16
            epoch.need(not member.is_dir() and stat.S_IFMT(mode) in (0,stat.S_IFREG) and
                       not member.flag_bits&1 and member.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and
                       0<member.file_size<=MAX_ARCHIVE and
                       member.compress_size<=MAX_ARCHIVE,'archive_entry')
            result=z.read(member)
            epoch.need(len(result)==member.file_size,'archive_truncated')
            return result
    except (zipfile.BadZipFile,RuntimeError,OSError,ValueError):
        raise epoch.Blocked('invalid_checkpoint_archive') from None


def authenticate_checkpoint(reader, policy, run, predecessor, *, root, expected_result):
    validate_run(run,terminal=True)
    verify_historical_code(root, policy, run['head_sha'])
    rid,attempt=run['id'],run['run_attempt']
    jobs=listing(reader,f'/actions/runs/{rid}/attempts/{attempt}/jobs','jobs')
    epoch.need(len(jobs)==1,'unexpected_job_inventory')
    job=jobs[0]
    epoch.need(job.get('run_id')==rid and job.get('run_attempt')==attempt and
               job.get('head_sha')==run['head_sha'] and job.get('status')=='completed' and
               job.get('conclusion')=='success','producer_job_binding')
    steps=job.get('steps');epoch.need(type(steps)is list,'step_inventory')
    for name in REQUIRED_STEPS:
        found=[s for s in steps if type(s)is dict and s.get('name')==name]
        epoch.need(len(found)==1 and found[0].get('status')=='completed' and
                   found[0].get('conclusion')=='success','required_step_not_successful')
    artifacts=listing(reader,f'/actions/runs/{rid}/artifacts','artifacts')
    epoch.need(len(artifacts)==1,'unexpected_artifact_inventory')
    a=artifacts[0];wr=a.get('workflow_run')
    epoch.need(type(wr)is dict and wr.get('id')==rid and wr.get('repository_id')==epoch.REPOSITORY_ID and
               wr.get('head_repository_id')==epoch.REPOSITORY_ID and wr.get('head_sha')==run['head_sha'] and
               wr.get('head_branch')=='main','artifact_run_binding')
    epoch.need(a.get('name')==f'owned-core-local-{rid}-{attempt}' and a.get('expired')is False and
               a.get('archive_download_url')==API+f"/actions/artifacts/{a['id']}/zip" and
               type(a.get('size_in_bytes'))is int and 0<a['size_in_bytes']<=MAX_ARCHIVE,'artifact_metadata')
    raw=reader.archive(a['id']);archive_sha=epoch.sha(raw)
    epoch.need(a.get('digest')=='sha256:'+archive_sha,'artifact_digest')
    cp_raw=read_checkpoint_archive(raw)
    observed=dict(repository=epoch.REPOSITORY,repository_id=epoch.REPOSITORY_ID,owner_id=epoch.OWNER_ID,
        run_id=rid,run_attempt=attempt,head_sha=run['head_sha'],workflow=epoch.WORKFLOW,
        event=run['event'],branch='main',status='completed',conclusion='success',artifact_id=a['id'],
        artifact_name=a['name'],artifact_digest=a['digest'],artifact_expired=False,
        required_steps_successful=True,complete_attempt_inventory=True,unreconciled_producer_attempts=[],
        predecessor_checkpoint_digest=epoch.digest(predecessor) if predecessor else None)
    cp=epoch.accept_retained(cp_raw,policy,observed=observed,expected_run_id=rid,
                             expected_attempt=attempt,verified_archive_sha256=archive_sha)
    epoch.need(cp['sequence']==(predecessor['sequence']+1 if predecessor else 0),'checkpoint_sequence_gap')
    epoch.need(cp['result']==expected_result,'retained_computation_mismatch')
    return cp, {'epoch':epoch.digest(policy),'workflow_id':policy['genesis_workflow_id'],
                'run_id':rid,'run_attempt':attempt,'head_sha':run['head_sha'],
                'checkpoint_digest':epoch.digest(cp),'artifact_id':a['id'],'artifact_digest':a['digest']}


def git(root,*args,cap=32*1024*1024):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,timeout=60,check=False)
    epoch.need(result.returncode==0 and len(result.stdout)<=cap,'git_snapshot_unavailable')
    return result.stdout


def file_bytes(root,path,cap=16*1024*1024):
    candidate=root/path
    epoch.need(not candidate.is_symlink() and candidate.is_file(),'regular_file_required')
    for parent in candidate.parents:
        if parent==root:break
        epoch.need(not parent.is_symlink(),'symlink_parent')
    info=candidate.stat();epoch.need(info.st_nlink==1 and 0<info.st_size<=cap,'file_size_or_hardlink')
    raw=candidate.read_bytes();epoch.need(len(raw)==info.st_size,'file_changed')
    return raw


def code_digest(root, ref=None):
    entries=[]
    for path in CODE_FILES:
        if ref is None:
            raw=file_bytes(root,path);mode='100755' if (root/path).stat().st_mode&0o111 else '100644'
        else:
            entry=git(root,'ls-tree','-z',ref,'--',path)
            header, observed_path=entry.rstrip(b'\0').split(b'\t',1)
            mode,kind,_=header.decode().split(' ')
            epoch.need(observed_path.decode()==path and kind=='blob' and mode in ('100644','100755'),'historical_code_blob')
            raw=git(root,'show',ref+':'+path)
        entries.append({'path':path,'sha256':epoch.sha(raw),'mode':mode})
    return epoch.digest(entries)


def verify_historical_code(root,policy,head):
    epoch.hashed(head,40)
    git(root,'merge-base','--is-ancestor',head,'HEAD')
    epoch.need(code_digest(root,head)==policy['code_contract_digest'],'historical_code_contract_changed')
    epoch.need(git(root,'show',head+':'+CONFIG+'policy.json')==epoch.canonical(policy),'historical_policy_changed')


def tree_proof(root,commit):
    rows=[]
    for item in git(root,'ls-tree','-r','-t','-z',commit).split(b'\0'):
        if not item:continue
        header,path=item.split(b'\t',1);mode,kind,oid=header.decode().split(' ')
        rows.append({'path':path.decode(),'mode':mode,'type':kind,'sha':oid})
    tree=git(root,'rev-parse',commit+'^{tree}').decode().strip()
    return epoch.canonical({'sha':tree,'truncated':False,'tree':rows})


def validate_local_inputs(root,policy,record):
    entries=record.entries+record.additions
    actual=provenance.parse_tree(git(root,'ls-tree','-r','-z','HEAD','--','data/'))
    epoch.need(tuple(sorted(entries))==actual,'legacy_head_inventory_changed')
    files={p.relative_to(root).as_posix() for p in (root/'data').rglob('*') if p.is_file() or p.is_symlink()}
    epoch.need(files=={e.path for e in entries},'legacy_worktree_extra_or_missing')
    for entry in entries:
        raw=file_bytes(root,entry.path,cap=64*1024*1024)
        blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        mode='100755' if (root/entry.path).stat().st_mode&0o111 else '100644'
        epoch.need(blob==entry.blob and mode==entry.mode,'legacy_worktree_modified')
    epoch.need(provenance.inventory_digest(record.entries)==policy['legacy_inventory_digest'],'legacy_inventory_policy')
    return {path:file_bytes(root,path) for path in epoch.INPUTS}


def load_context(root):
    policy=epoch.parse(file_bytes(root,CONFIG+'policy.json'));epoch.validate_policy(policy)
    epoch.need(code_digest(root)==policy['code_contract_digest'],'destination_code_contract_changed')
    record_raw=file_bytes(root,CONFIG+'import-record.json');record=provenance.parse_record(record_raw)
    epoch.need(record.unresolved_digest==policy['legacy_unresolved_digest'] and
               record.authorization_reference_digest==policy['authorization_reference_digest'],'migration_binding')
    source=snapshot.read_snapshot('source',record.source.commit,local_tree_proof=tree_proof(root,record.source.commit))
    destination=snapshot.read_snapshot('destination',record.destination.commit,
                                       local_tree_proof=tree_proof(root,record.destination.commit))
    snapshot.validate_authenticated_import(record_raw,source,destination,expected_record_digest=policy['import_record_digest'])
    tail_raw=file_bytes(root,CONFIG+'source-final-tail.json')
    epoch.need(epoch.sha(tail_raw)==policy['source_final_tail_digest'],'source_tail_pin')
    tail=epoch.parse(tail_raw)
    epoch.need(type(tail)is dict and set(tail)=={'commit','tree','status'} and
               tail['status']=='historical_tail_quarantined_not_current_authority','source_tail_schema')
    epoch.hashed(tail['commit'],40);epoch.hashed(tail['tree'],40)
    # Source-final tree identity is independently HTTPS-authenticated. It is NOT
    # included in the imported current inventory or used as execution authority.
    metadata=snapshot._get(provenance.LEGACY[0],'/git/commits/'+tail['commit'],time.monotonic()+30,snapshot.META_CAP)
    epoch.need(type(metadata)is dict and metadata.get('sha')==tail['commit'] and
               type(metadata.get('tree'))is dict and metadata['tree'].get('sha')==tail['tree'],'source_final_tail_binding')
    return policy,record,validate_local_inputs(root,policy,record)


def run_inventory(reader,policy):
    rows=listing(reader,'/actions/workflows/'+Path(epoch.WORKFLOW).name+'/runs','workflow_runs')
    for run in rows:
        validate_run(run)
        epoch.need(run.get('workflow_id')==policy['genesis_workflow_id'],'workflow_identity_changed')
    epoch.need(len({r['run_number'] for r in rows})==len(rows),'duplicate_run_number')
    rows=sorted(rows,key=lambda r:r['run_number'])
    epoch.need([row['run_number'] for row in rows]==list(range(1,len(rows)+1)),'producer_run_number_gap')
    return rows


def run(root,output,*,verify_run=None,artifact_directory=None):
    root=root.resolve();policy,record,inputs=load_context(root)
    reader=GithubReader(public_verification=verify_run is not None,artifact_directory=artifact_directory);verify_repository(reader)
    rows=run_inventory(reader,policy)
    if verify_run is None:
        epoch.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')==epoch.REPOSITORY and
                   os.environ.get('GITHUB_REPOSITORY_ID')==str(epoch.REPOSITORY_ID) and
                   os.environ.get('GITHUB_REPOSITORY_OWNER_ID')==str(epoch.OWNER_ID),'trusted_runner_required')
        rid=int(os.environ['GITHUB_RUN_ID']);attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])
        head=git(root,'rev-parse','HEAD').decode().strip()
        epoch.need(head==os.environ.get('GITHUB_SHA'),'checkout_head_mismatch')
    else:
        rid=verify_run;attempt=1;head=None
    current=[r for r in rows if r['id']==rid]
    epoch.need(len(current)==1,'current_run_missing')
    current=current[0]
    epoch.need(current['run_attempt']==attempt and (head is None or current['head_sha']==head),'current_run_mismatch')
    if verify_run is None:epoch.need(current.get('status')=='in_progress','current_run_not_running')
    predecessor=None; genesis_seal=None
    expected_result=epoch.business_review(inputs)
    for row in rows:
        if row['run_number']>current['run_number']:
            epoch.need(row.get('status') in ('queued','waiting','pending','requested'),'concurrent_producer')
            jobs=listing(reader,f"/actions/runs/{row['id']}/attempts/1/jobs",'jobs')
            epoch.need(jobs==[],'queued_run_started')
            continue
        if row['id']==rid and verify_run is None:continue
        predecessor, receipt=authenticate_checkpoint(reader,policy,row,predecessor,root=root,expected_result=expected_result)
        if row['run_number']==1:genesis_seal=receipt
    epoch.need(run_inventory(reader,policy)==rows,'producer_inventory_changed')
    validate_local_inputs(root,policy,record)
    if current['run_number']>1:
        committed_seal=epoch.parse(file_bytes(root,CONFIG+'genesis-seal.json'))
        epoch.need(genesis_seal is not None and committed_seal==genesis_seal,'committed_genesis_seal_required')
    if verify_run is not None:
        epoch.need(predecessor is not None and predecessor['run_id']==rid,'verification_target_mismatch')
        return {'status':'authenticated_destination_local_checkpoint','run_id':rid,
                'sequence':predecessor['sequence'],'checkpoint_digest':epoch.digest(predecessor),
                'full_core_recovery':False,'legacy_continuity':'unresolved_gap','genesis_seal':genesis_seal,
                'retention_scope':'bounded_30_day_artifact_chain_not_permanent_history'}
    raw=epoch.prepare_checkpoint(policy,inputs,run_id=rid,run_attempt=attempt,head_sha=head,
         legacy_inventory_digest=policy['legacy_inventory_digest'],prior=predecessor)
    output=output.resolve()
    epoch.need(not output.is_relative_to(root),'output_must_be_outside_repository')
    output.mkdir(parents=True,exist_ok=False)
    with (output/'checkpoint.json').open('xb') as stream:stream.write(raw)
    return {'status':'checkpoint_candidate_retention_pending','run_id':rid,
            'sequence':epoch.parse(raw)['sequence'],'full_core_recovery':False,'legacy_continuity':'unresolved_gap'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--verify-run',type=int)
    parser.add_argument('--artifact-dir',type=Path,help='Verify-only downloaded ZIPs named by actual artifact ID; fresh GitHub digest binding still mandatory')
    args=parser.parse_args()
    try:
        epoch.need(args.output is not None or args.verify_run is not None,'output_required')
        epoch.need(args.artifact_dir is None or args.verify_run is not None,'downloaded_artifacts_verify_only')
        value=run(args.root,args.output,verify_run=args.verify_run,artifact_directory=args.artifact_dir)
        print(json.dumps(value,sort_keys=True));return 0
    except (epoch.Blocked,provenance.ProvenanceError,OSError,KeyError,ValueError,subprocess.TimeoutExpired) as error:
        # Only known symbolic errors, never server bodies, tokens, URLs or input payloads.
        reason=str(error) if isinstance(error,(epoch.Blocked,provenance.ProvenanceError)) else type(error).__name__
        print(json.dumps({'status':'blocked','reason':reason,'full_core_recovery':False}));return 1

if __name__=='__main__':raise SystemExit(main())
