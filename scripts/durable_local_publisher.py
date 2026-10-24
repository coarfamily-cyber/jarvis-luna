"""Terminal-only publisher for reviewed internal state; never called by producer.

Deployment is not enabled by importing this module. A separately approved
workflow_run(completed) job needs contents:write and protected state-branch rules.
No PR-supplied code, arbitrary URL, arbitrary ref, token argument or retry loop.
"""
from __future__ import annotations
from dataclasses import dataclass,field
import http.client
import os
import urllib.error
import urllib.request
import destination_core_epoch as e
import owned_core_local as r
import durable_local_ledger as ledger

PUBLISHER_WORKFLOW='.github/workflows/owned-core-ledger-publisher.yml'
CODE_FILES=(*r.CODE_FILES,'scripts/durable_local_ledger.py','scripts/durable_local_publisher.py','scripts/durable_local_runtime.py',PUBLISHER_WORKFLOW)
_EVENT_SEAL=object()

def contract_digest(root,ref=None):
    entries=[]
    for path in CODE_FILES:
        if ref is None:
            raw=r.file_bytes(root,path);mode='100755' if (root/path).stat().st_mode&0o111 else '100644'
        else:
            header,name=r.git(root,'ls-tree','-z',ref,'--',path).rstrip(b'\0').split(b'\t',1)
            mode,kind,_=header.decode().split(' ')
            e.need(name.decode()==path and kind=='blob' and mode in ('100644','100755'),'durable_historical_code_file')
            raw=r.git(root,'show',ref+':'+path)
        entries.append({'path':path,'sha256':e.sha(raw),'mode':mode})
    return e.digest(entries)

def validate_producer(run,anchor):
    e.need(type(run)is dict,'durable_run_shape')
    for key in ('id','run_number','run_attempt'):e.positive(run.get(key))
    e.hashed(run.get('head_sha'),40)
    ledger.timestamp(run.get('created_at'))
    e.need(run.get('workflow_id')==anchor['workflow_id'] and run.get('path')==e.WORKFLOW and
           run.get('head_branch')=='main' and run.get('event') in ('workflow_dispatch','schedule') and run['run_attempt']==1,'durable_producer_scope')
    for key in ('repository','head_repository'):
        repo=run.get(key)
        e.need(type(repo)is dict and repo.get('id')==e.REPOSITORY_ID and repo.get('full_name')==e.REPOSITORY and
               repo.get('owner',{}).get('id')==e.OWNER_ID,'durable_producer_repository')

def check_terminal_evidence(run,jobs,artifacts,archive,*,policy,anchor,state,expected_result):
    """Pure terminal checks. Never authenticates a caller's JSON by itself."""
    ledger.validate_state(state,anchor);validate_producer(run,anchor)
    e.need(run.get('status')=='completed' and run.get('conclusion') in ('success','failure'),'durable_terminal_required')
    already=run['run_number']==state['last_run_number'] and run['id']==state['last_run_id']
    e.need(already or run['run_number']==state['last_run_number']+1,'durable_terminal_order')
    e.need(type(jobs)is list and len(jobs)==1,'durable_job_inventory')
    job=jobs[0]
    e.need(job.get('run_id')==run['id'] and job.get('run_attempt')==1 and job.get('head_sha')==run['head_sha'] and
           job.get('status')=='completed' and job.get('conclusion')==run['conclusion'],'durable_job_binding')
    steps=job.get('steps');e.need(type(steps)is list,'durable_steps')
    names=['Set up job','Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
      'Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',*r.REQUIRED_STEPS,
      'Post Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',
      'Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1','Complete job']
    e.need(len(steps)==len(names) and [s.get('name') for s in steps if type(s)is dict]==names,'durable_exact_job_steps')
    if run['conclusion']=='success':expected=['success']*8
    else:expected=['success']*3+['failure','skipped','skipped','success','success']
    e.need(all(s.get('status')=='completed' and s.get('conclusion')==v for s,v in zip(steps,expected)),'durable_step_results')
    e.need(type(artifacts)is list,'durable_artifact_inventory')
    cp=None;artifact_receipt=None
    if run['conclusion']=='success':
        e.need(len(artifacts)==1 and type(archive)is bytes,'durable_single_artifact_required')
        a=artifacts[0];wr=a.get('workflow_run',{});e.positive(a.get('id'))
        e.need(wr.get('id')==run['id'] and wr.get('repository_id')==e.REPOSITORY_ID and wr.get('head_repository_id')==e.REPOSITORY_ID and
               wr.get('head_sha')==run['head_sha'] and wr.get('head_branch')=='main','durable_artifact_run')
        e.need(a.get('name')==f"owned-core-local-{run['id']}-1" and a.get('expired')is False and
               a.get('archive_download_url')==r.API+f"/actions/artifacts/{a['id']}/zip" and
               a.get('digest')=='sha256:'+e.sha(archive) and type(a.get('size_in_bytes'))is int and
               a['size_in_bytes']==len(archive),'durable_artifact_digest')
        raw=r.read_checkpoint_archive(archive);cp=e.parse(raw)
        e.need(e.canonical(cp)==raw,'durable_canonical_checkpoint');e.validate_checkpoint(cp,policy);ledger.validate_summary(cp)
        e.need(cp['run_id']==run['id'] and cp['run_attempt']==1 and cp['head_sha']==run['head_sha'] and
               cp['result']==expected_result,'durable_candidate_binding')
        if already:e.need(cp==state['checkpoint'],'durable_existing_checkpoint_changed')
        else:e.need(cp['sequence']==state['checkpoint']['sequence']+1 and
                    cp['predecessor']==e.digest(state['checkpoint']),'durable_candidate_chain')
        artifact_receipt={'id':a['id'],'digest':a['digest'],'checkpoint_digest':e.digest(cp)}
    else:e.need(artifacts==[] and archive is None,'durable_failure_retention_ambiguous')
    evidence={'run_id':run['id'],'run_number':run['run_number'],'run_attempt':1,'head_sha':run['head_sha'],
              'workflow_id':run['workflow_id'],'conclusion':run['conclusion'],'job_id':job['id'],
              'steps':[{'name':s['name'],'status':s['status'],'conclusion':s['conclusion']} for s in steps],
              'artifact':artifact_receipt}
    event={'run_id':run['id'],'run_number':run['run_number'],'run_attempt':1,'head_sha':run['head_sha'],'workflow_id':run['workflow_id'],
           'kind':'successful_checkpoint' if cp else 'failed_local_no_retention','checkpoint':cp,
           'evidence_digest':e.digest(evidence),'code_contract_digest':policy['code_contract_digest'],'created_at':run['created_at']}
    ledger.validate_event(event)
    if already:e.need(e.digest(event)==state['last_event_digest'],'durable_existing_event_changed')
    return event

@dataclass(frozen=True)
class TerminalReceipt:
    event:dict
    previous_state_digest:str
    _seal:object=field(repr=False,compare=False)
    def __post_init__(self):e.need(self._seal is _EVENT_SEAL,'durable_terminal_reader_required')

def read_terminal_receipt(reader,*,root,policy,anchor,previous,run_id,inputs):
    e.need(type(reader)is r.GithubReader and type(previous)is ledger.AuthenticatedState,'durable_fixed_reader_required')
    e.positive(run_id);r.verify_repository(reader)
    run=reader.json('/actions/runs/'+str(run_id));validate_producer(run,anchor)
    r.git(root,'merge-base','--is-ancestor',run['head_sha'],'HEAD')
    e.need(contract_digest(root,run['head_sha'])==policy['code_contract_digest'],'durable_producer_code_contract')
    e.need(r.git(root,'show',run['head_sha']+':'+r.CONFIG+'policy.json')==e.canonical(policy),'durable_producer_policy')
    jobs=r.listing(reader,f'/actions/runs/{run_id}/attempts/1/jobs','jobs')
    artifacts=r.listing(reader,f'/actions/runs/{run_id}/artifacts','artifacts')
    archive=reader.archive(artifacts[0]['id']) if run.get('conclusion')=='success' and len(artifacts)==1 else None
    event=check_terminal_evidence(run,jobs,artifacts,archive,policy=policy,anchor=anchor,state=previous.state,expected_result=e.business_review(inputs))
    e.need(reader.json('/actions/runs/'+str(run_id))==run,'durable_producer_changed')
    return TerminalReceipt(event,e.digest(previous.state),_EVENT_SEAL)

def publish(reader,*,previous,receipt,anchor,policy,writer_id,approved_transition=None):
    """One terminal CAS publication, with unknown outcomes reconciled by reread.

    Never retry POST automatically. The next invocation must first authenticate
    the current branch; exact last-event digest is idempotent, conflicts block.
    """
    e.need(type(reader)is r.GithubReader and type(previous)is ledger.AuthenticatedState and type(receipt)is TerminalReceipt,'durable_trusted_receipts_required')
    e.need(receipt.previous_state_digest==e.digest(previous.state),'durable_receipt_state_changed')
    e.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')==e.REPOSITORY and
           os.environ.get('GITHUB_REPOSITORY_ID')==str(e.REPOSITORY_ID) and os.environ.get('GITHUB_REPOSITORY_OWNER_ID')==str(e.OWNER_ID) and
           os.environ.get('GITHUB_EVENT_NAME') in ('workflow_run','workflow_dispatch') and
           os.environ.get('GITHUB_WORKFLOW_REF')==e.REPOSITORY+'/'+PUBLISHER_WORKFLOW+'@refs/heads/main','durable_publisher_scope')
    state,changed=ledger.append(previous.state,anchor,receipt.event,expected_commit=previous.commit,
                                active_contract=policy['code_contract_digest'],approved_transition=approved_transition)
    if not changed:return previous
    request_data=ledger.graphql_commit_request(expected_commit=previous.commit,state=state,anchor=anchor)
    head=post_state(reader,request_data)
    observed=ledger.read_authenticated_state(reader,anchor=anchor,writer_id=writer_id)
    e.need(observed.commit==head and observed.state==state,'durable_published_state_mismatch')
    return observed


def post_state(reader,request_data):
    """Private fixed-origin one-shot write. Callers validate scope and CAS body."""
    token=os.environ.get('GITHUB_TOKEN','');e.need(token and token.isascii() and all(33<=ord(c)<=126 for c in token),'durable_publisher_token')
    request=urllib.request.Request('https://api.github.com/graphql',data=e.canonical(request_data),method='POST',
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':'Jarvis-owned-durable-publisher/1'})
    try:
        with urllib.request.build_opener(r.NoRedirect()).open(request,timeout=30) as response:
            e.need(response.status==200,'durable_publication_unconfirmed')
            body=reader._body(response,65536);result=e.parse(body)
            e.need(type(result)is dict and not result.get('errors'),'durable_publication_unconfirmed')
            head=result.get('data',{}).get('createCommitOnBranch',{}).get('commit',{}).get('oid');e.hashed(head,40)
    except (OSError,urllib.error.URLError,http.client.HTTPException,ValueError):
        raise e.Blocked('durable_publication_outcome_unconfirmed_reread_before_retry') from None
    return head


def initialize(reader,*,anchor,writer_id):
    """One-time reviewed bootstrap. Existing state can never be reset here."""
    e.need(type(reader)is r.GithubReader,'durable_fixed_reader_required')
    e.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')==e.REPOSITORY and
           os.environ.get('GITHUB_REPOSITORY_ID')==str(e.REPOSITORY_ID) and os.environ.get('GITHUB_REPOSITORY_OWNER_ID')==str(e.OWNER_ID) and
           os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and
           os.environ.get('GITHUB_WORKFLOW_REF')==e.REPOSITORY+'/'+PUBLISHER_WORKFLOW+'@refs/heads/main','durable_initializer_scope')
    r.verify_repository(reader);ledger.validate_anchor(anchor)
    ref=reader.json('/git/ref/heads/jarvis-owned-state')
    e.need(ref.get('ref')=='refs/heads/jarvis-owned-state' and ref.get('object',{}).get('type')=='commit' and
           ref['object'].get('sha')==anchor['approved_head'],'durable_bootstrap_already_used_or_wrong_head')
    ledger.check_append_rules(reader.json('/rules/branches/jarvis-owned-state?per_page=100&page=1'))
    state=ledger.bootstrap(anchor)
    # This routine never creates/deletes a branch or alters protection settings.
    # Reviewed operator first creates the branch at the exact approved anchor.
    head=post_state(reader,ledger.graphql_commit_request(expected_commit=anchor['approved_head'],state=state,anchor=anchor))
    observed=ledger.read_authenticated_state(reader,anchor=anchor,writer_id=writer_id)
    e.need(observed.commit==head and observed.state==state,'durable_bootstrap_verification_failed')
    return observed
