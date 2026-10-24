"""Pure bounded ledger protocol; NOT an authentication or publication API.

The caller must independently authenticate completed producer runs and the
GitHub-verified signed writer commit before using these deterministic checks.
Git author strings, hashes, or serialized verified flags do not grant authority.
The explicitly approved repository writers/admins are trusted; a GitHub signature
does not identify an exact workflow. No network, credentials, or mutations here.
"""
from __future__ import annotations
import copy
import hashlib
import datetime
import base64
from dataclasses import dataclass,field
import destination_core_epoch as e

SCHEMA='jarvis-owned-durable-ledger-v1'
STATE_PATH='.jarvis-owned-state.json'
MAX_BYTES=128*1024
EVENT_FIELDS={'run_id','run_number','run_attempt','head_sha','workflow_id','kind','checkpoint','evidence_digest','code_contract_digest','created_at'}
STATE_FIELDS={'schema','anchor_digest','previous_commit','last_run_number','last_run_id','last_created_at','event_count','history_root','checkpoint','last_event_digest','code_contract_digest','holds','privacy'}
PRIVACY='public_existing_input_hashes_counts_and_run_metadata_only'
_STATE_SEAL=object()

def bounded(value):
    raw=e.canonical(value)
    e.need(len(raw)<=MAX_BYTES,'durable_state_size')
    return raw

def timestamp(value):
    e.need(type(value)is str and len(value)==20 and value.endswith('Z'),'durable_timestamp')
    try:parsed=datetime.datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ')
    except ValueError:raise e.Blocked('durable_timestamp') from None
    e.need(parsed.strftime('%Y-%m-%dT%H:%M:%SZ')==value,'durable_timestamp')

def validate_summary(cp):
    # Existing epoch checkpoint has a strict allowlist, including six input
    # hashes/count findings. It never contains product rows, URLs or secrets.
    fields={'schema','epoch','sequence','predecessor','run_id','run_attempt','head_sha','holds','result','result_digest',
            'legacy_inventory_digest','legacy_unresolved_digest','source_final_tail_digest'}
    e.need(type(cp)is dict and set(cp)==fields,'durable_checkpoint_schema')
    e.hashed(cp['epoch']);e.hashed(cp['head_sha'],40)
    e.need(cp['schema']==e.SCHEMA,'durable_checkpoint_version')
    for key in ('legacy_inventory_digest','legacy_unresolved_digest','source_final_tail_digest'):e.hashed(cp[key])
    e.positive(cp['run_id']);e.need(cp['run_attempt']==1 and type(cp['run_attempt'])is int,'durable_no_retry')
    e.need(type(cp['sequence'])is int and cp['sequence']>=0,'durable_sequence')
    if cp['predecessor'] is not None:e.hashed(cp['predecessor'])
    e.need((cp['sequence']==0)==(cp['predecessor'] is None),'durable_predecessor')
    e.need(cp['holds']==e.HOLDS,'durable_holds')
    result=cp['result']
    e.need(type(result)is dict and set(result)=={'profile','freshness','external_effects_permitted','full_core_recovery','input_sha256','findings'},'durable_result_schema')
    e.need(result['profile']==e.PROFILE and result['freshness']=='not_established_by_saved_input_review' and result['external_effects_permitted']is False and result['full_core_recovery']is False,'durable_result_scope')
    e.need(type(result['input_sha256'])is dict and set(result['input_sha256'])==set(e.INPUTS),'durable_input_scope')
    for value in result['input_sha256'].values():e.hashed(value)
    findings=result['findings'];e.need(type(findings)is list and len(findings)==len(e.INPUTS),'durable_findings')
    e.need([f.get('input') for f in findings if type(f)is dict]==list(e.INPUTS),'durable_findings_order')
    for f in findings:
        e.need(set(f)=={'input','row_count','row_schema_recognized','explicit_blocked_or_review_rows'},'durable_findings_schema')
        e.need(type(f['row_schema_recognized'])is bool,'durable_findings_type')
        for key in ('row_count','explicit_blocked_or_review_rows'):
            value=f[key]
            e.need((key=='row_count' and value is None) or type(value)is int and value>=0,'durable_findings_count')
        if f['row_schema_recognized']:
            e.need(type(f['row_count'])is int and f['explicit_blocked_or_review_rows']<=f['row_count'],'durable_findings_semantics')
        else:e.need(f['row_count'] is None and f['explicit_blocked_or_review_rows']==0,'durable_unknown_findings')
    e.need(cp['result_digest']==e.digest(result),'durable_result_digest')
    bounded(cp)

def validate_anchor(anchor):
    e.need(type(anchor)is dict and set(anchor)=={'schema','repository_id','owner_id','workflow_id','through_run_number','through_created_at','checkpoint','evidence_root','code_contract_digest','approved_head'},'durable_anchor_schema')
    e.need(anchor['schema']==SCHEMA and anchor['repository_id']==e.REPOSITORY_ID and anchor['owner_id']==e.OWNER_ID,'durable_anchor_identity')
    e.positive(anchor['workflow_id']);e.positive(anchor['through_run_number'])
    timestamp(anchor['through_created_at'])
    e.hashed(anchor['evidence_root']);e.hashed(anchor['code_contract_digest']);e.hashed(anchor['approved_head'],40)
    validate_summary(anchor['checkpoint']);bounded(anchor)

def bootstrap(anchor):
    """Construct only from a separately reviewed/pinned anchor, not a fresh start."""
    validate_anchor(anchor)
    return {'schema':SCHEMA,'anchor_digest':e.digest(anchor),'previous_commit':anchor['approved_head'],
            'last_run_number':anchor['through_run_number'],'last_run_id':anchor['checkpoint']['run_id'],
            'last_created_at':anchor['through_created_at'],
            'event_count':0,'history_root':anchor['evidence_root'],'checkpoint':copy.deepcopy(anchor['checkpoint']),
            'last_event_digest':None,'code_contract_digest':anchor['code_contract_digest'],
            'holds':copy.deepcopy(e.HOLDS),'privacy':PRIVACY}

def validate_state(state,anchor):
    validate_anchor(anchor)
    e.need(type(state)is dict and set(state)==STATE_FIELDS,'durable_state_schema')
    e.need(state['schema']==SCHEMA and state['anchor_digest']==e.digest(anchor),'durable_anchor_binding')
    e.hashed(state['previous_commit'],40);e.hashed(state['history_root']);e.hashed(state['code_contract_digest'])
    e.positive(state['last_run_id'])
    timestamp(state['last_created_at']);e.need(state['last_created_at']>=anchor['through_created_at'],'durable_timestamp_order')
    e.need(type(state['event_count'])is int and state['event_count']>=0 and
           state['last_run_number']==anchor['through_run_number']+state['event_count'],'durable_counter')
    e.need(type(state['last_run_number'])is int,'durable_counter_type')
    e.need(state['holds']==e.HOLDS and state['privacy']==PRIVACY,'durable_privacy_or_holds')
    validate_summary(state['checkpoint'])
    for key in ('legacy_inventory_digest','legacy_unresolved_digest','source_final_tail_digest'):
        e.need(state['checkpoint'][key]==anchor['checkpoint'][key],'durable_legacy_binding_changed')
    if state['event_count']==0:e.need(state==bootstrap(anchor),'durable_bootstrap_exact')
    else:e.hashed(state['last_event_digest'])
    bounded(state)

def validate_event(event):
    e.need(type(event)is dict and set(event)==EVENT_FIELDS,'durable_event_schema')
    for key in ('run_id','run_number','workflow_id'):e.positive(event[key])
    timestamp(event['created_at'])
    e.need(type(event['run_attempt'])is int and event['run_attempt']==1,'durable_attempt_requires_review')
    e.hashed(event['head_sha'],40);e.hashed(event['evidence_digest']);e.hashed(event['code_contract_digest'])
    e.need(event['kind'] in ('successful_checkpoint','failed_local_no_retention'),'durable_event_kind')
    if event['kind']=='successful_checkpoint':
        validate_summary(event['checkpoint'])
        e.need(all(event[k]==event['checkpoint'][k] for k in ('run_id','run_attempt','head_sha')),'durable_event_checkpoint_binding')
    else:e.need(event['checkpoint'] is None,'durable_failure_not_checkpoint')
    bounded(event)

def append(state,anchor,event,*,expected_commit,active_contract,approved_transition=None):
    """Pure CAS proposal. Caller must authenticate receipt BEFORE this call.

    Successful response loss is reconciled by exact last-event digest. Old events
    are not re-applied. Missing run numbers remain blockers, never compacted away.
    """
    validate_state(state,anchor);validate_event(event);e.hashed(expected_commit,40);e.hashed(active_contract)
    e.need(event['workflow_id']==anchor['workflow_id'],'durable_workflow_changed')
    e.need(event['code_contract_digest']==active_contract,'durable_event_contract')
    if event['run_number']==state['last_run_number']:
        e.need(event['run_id']==state['last_run_id'] and e.digest(event)==state['last_event_digest'],'durable_duplicate_conflict')
        return copy.deepcopy(state),False
    e.need(event['run_number']==state['last_run_number']+1,'durable_run_gap_or_replay')
    e.need(event['run_id']!=state['last_run_id'],'durable_run_id_reuse')
    e.need(event['created_at']>=state['last_created_at'],'durable_event_timestamp_order')
    if active_contract!=state['code_contract_digest']:
        e.need(type(approved_transition)is dict and set(approved_transition)=={'from_contract','to_contract','previous_state_digest','review_reference'} and
               approved_transition['from_contract']==state['code_contract_digest'] and approved_transition['to_contract']==active_contract and
               approved_transition['previous_state_digest']==e.digest(state),'durable_reviewed_rotation_required')
        e.hashed(approved_transition['review_reference'])
    next_state=copy.deepcopy(state)
    if event['kind']=='successful_checkpoint':
        cp=event['checkpoint'];prior=state['checkpoint']
        e.need(cp['sequence']==prior['sequence']+1 and cp['predecessor']==e.digest(prior),'durable_checkpoint_chain')
        next_state['checkpoint']=copy.deepcopy(cp)
    next_state.update(previous_commit=expected_commit,last_run_number=event['run_number'],last_run_id=event['run_id'],last_created_at=event['created_at'],
        event_count=state['event_count']+1,history_root=e.digest({'prior':state['history_root'],'event':e.digest(event)}),
        last_event_digest=e.digest(event),code_contract_digest=active_contract)
    validate_state(next_state,anchor)
    return next_state,True

def graphql_commit_request(*,expected_commit,state,anchor,repository=e.REPOSITORY):
    """Build, but never send, the one-path CAS signed-commit mutation.

    Its caller must bind state to authenticated terminal evidence and current
    signed branch head. Only the dedicated publisher is granted contents:write.
    """
    import base64
    validate_state(state,anchor)
    e.need(repository==e.REPOSITORY,'durable_repository_scope');e.hashed(expected_commit,40)
    e.need(state.get('previous_commit')==expected_commit,'durable_expected_head_binding')
    raw=bounded(state)
    return {'query':'mutation($input:CreateCommitOnBranchInput!){createCommitOnBranch(input:$input){commit{oid}}}',
            'variables':{'input':{'branch':{'repositoryNameWithOwner':e.REPOSITORY,'branchName':'jarvis-owned-state'},
              'expectedHeadOid':expected_commit,'message':{'headline':'owned local checkpoint '+str(state['last_run_number'])},
              'fileChanges':{'additions':[{'path':STATE_PATH,'contents':base64.b64encode(raw).decode('ascii')}]}}}}

def check_signed_snapshot(metadata,tree,blob,*,head,anchor,writer_id):
    """Pure verification of data from fixed-origin authenticated GitHub reads.

    Does not itself authenticate HTTP origin or mint an authenticated state.
    GitHub's signature verification is trusted, not a supplied JSON boolean.
    """
    e.hashed(head,40);e.positive(writer_id)
    e.need(type(metadata)is dict and metadata.get('sha')==head,'durable_commit_binding')
    author,committer=metadata.get('author'),metadata.get('committer')
    e.need(type(author)is dict and author.get('login')=='github-actions[bot]' and author.get('id')==writer_id,'durable_writer_identity')
    e.need(type(committer)is dict and committer.get('login')=='web-flow' and committer.get('id')==19864447,'durable_github_committer_identity')
    commit=metadata.get('commit');e.need(type(commit)is dict,'durable_commit_schema')
    verification=commit.get('verification')
    e.need(type(verification)is dict and verification.get('verified')is True and verification.get('reason')=='valid' and
           type(verification.get('signature'))is str and verification['signature'].startswith('-----BEGIN PGP SIGNATURE-----\n') and
           type(verification.get('payload'))is str,'durable_signature_required')
    parents=metadata.get('parents');e.need(type(parents)is list and len(parents)==1,'durable_single_parent')
    parent=parents[0].get('sha');e.hashed(parent,40)
    root=commit.get('tree',{}).get('sha');e.hashed(root,40)
    payload=verification['payload']
    e.need(payload.startswith('tree '+root+'\nparent '+parent+'\n') and payload.count('\nparent ')==1,'durable_signed_payload_binding')
    files=metadata.get('files')
    e.need(type(files)is list and len(files)==1 and files[0].get('filename')==STATE_PATH and
           files[0].get('status') in ('added','modified') and not files[0].get('previous_filename'),'durable_one_path_change')
    e.need(type(tree)is dict and tree.get('sha')==root and tree.get('truncated')is False and type(tree.get('tree'))is list,'durable_tree_binding')
    rows=tree['tree'];e.need(len(rows)<=2000,'durable_tree_capacity')
    names=set();entries=[];selected=[]
    for row in rows:
        e.need(type(row)is dict and set(row).issuperset({'path','mode','type','sha'}),'durable_tree_entry')
        name=row['path'];e.need(type(name)is str and name and '/' not in name and '\0' not in name and name not in names,'durable_tree_name');names.add(name)
        mode,kind=row['mode'],row['type'];e.hashed(row['sha'],40)
        e.need({'040000':'tree','100644':'blob','100755':'blob','120000':'blob','160000':'commit'}.get(mode)==kind,'durable_tree_mode')
        entries.append((name,mode,kind,row['sha']))
        if name==STATE_PATH:selected.append(row)
    content=b''.join((mode.lstrip('0')+' ').encode()+name.encode()+b'\0'+bytes.fromhex(sha)
        for name,mode,kind,sha in sorted(entries,key=lambda x:(x[0]+('/' if x[2]=='tree' else '')).encode()))
    e.need(hashlib.sha1(b'tree '+str(len(content)).encode()+b'\0'+content).hexdigest()==root,'durable_tree_hash')
    e.need(len(selected)==1 and selected[0]['mode']=='100644' and selected[0]['type']=='blob','durable_regular_state_file')
    e.need(type(blob)is dict and blob.get('sha')==selected[0]['sha'] and blob.get('encoding')=='base64' and type(blob.get('size'))is int and 0<blob['size']<=MAX_BYTES,'durable_blob_binding')
    try:raw=base64.b64decode(''.join(blob['content'].splitlines()),validate=True)
    except (KeyError,ValueError,TypeError):raise e.Blocked('durable_blob_encoding') from None
    e.need(len(raw)==blob['size'] and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==blob['sha'],'durable_blob_hash')
    state=e.parse(raw);e.need(e.canonical(state)==raw,'durable_state_canonical');validate_state(state,anchor)
    e.need(state['previous_commit']==parent,'durable_state_parent_binding')
    return state

@dataclass(frozen=True)
class AuthenticatedState:
    state:dict
    commit:str
    _seal:object=field(repr=False,compare=False)
    def __post_init__(self):e.need(self._seal is _STATE_SEAL,'durable_authenticated_reader_required')

def read_authenticated_state(reader,*,anchor,writer_id):
    """Fixed-origin reader; no caller-supplied verified flag or transport.

    Trusted-process API, not a Python sandbox. Public fixtures can exercise the
    pure checks above but cannot mint this production reader's receipt.
    """
    import owned_core_local as r
    e.need(type(reader)is r.GithubReader,'durable_fixed_reader_required')
    r.verify_repository(reader)
    ref=reader.json('/git/ref/heads/jarvis-owned-state')
    e.need(ref.get('ref')=='refs/heads/jarvis-owned-state' and ref.get('object',{}).get('type')=='commit','durable_branch_binding')
    head=ref['object']['sha'];e.hashed(head,40)
    metadata=reader.json('/commits/'+head)
    root=metadata.get('commit',{}).get('tree',{}).get('sha');e.hashed(root,40)
    tree=reader.json('/git/trees/'+root)
    rows=[row for row in tree.get('tree',[]) if type(row)is dict and row.get('path')==STATE_PATH]
    e.need(len(rows)==1,'durable_state_missing');oid=rows[0].get('sha');e.hashed(oid,40)
    blob=reader.json('/git/blobs/'+oid)
    state=check_signed_snapshot(metadata,tree,blob,head=head,anchor=anchor,writer_id=writer_id)
    # Existing generic reader correctly forbids '..'. This dedicated route is
    # constructed only from validated 40-hex immutable commit IDs.
    e.hashed(anchor['approved_head'],40)
    comparison=e.parse(reader._request(r.API+'/compare/'+anchor['approved_head']+'...'+head+'?per_page=1&page=1'))
    check_anchor_ancestry(comparison,state,anchor)
    rules=reader.json('/rules/branches/jarvis-owned-state?per_page=100&page=1')
    check_append_rules(rules)
    e.need(reader.json('/git/ref/heads/jarvis-owned-state')==ref,'durable_branch_changed')
    return AuthenticatedState(state,head,_STATE_SEAL)

def check_anchor_ancestry(comparison,state,anchor):
    e.need(type(comparison)is dict and comparison.get('status')=='ahead' and
           comparison.get('merge_base_commit',{}).get('sha')==anchor['approved_head'] and
           comparison.get('total_commits')==state['event_count']+1 and
           type(comparison.get('total_commits'))is int,'durable_anchor_ancestry')

def check_append_rules(rules):
    # Live enforced rules, not a protected:true flag or repository file assertion.
    # Repository writers/admins and the reviewed workflow allowlist are the
    # explicit trust boundary. No bypass actor or exact-workflow claim is made.
    e.need(type(rules)is list and 0<len(rules)<100,'durable_rules_inventory')
    kinds={rule.get('type') for rule in rules if type(rule)is dict}
    e.need({'non_fast_forward','deletion','required_signatures'}<=kinds,'durable_append_protection_missing')
