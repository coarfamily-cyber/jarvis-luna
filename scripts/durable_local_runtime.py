"""Saved-input-only producer and terminal publisher entry points.

No workflow is activated by this module. Durable branch initialization, writer
identity and append-only rules require a separately reviewed deployment.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import time
import urllib.parse
import destination_core_epoch as e
import owned_core_local as r
import durable_local_ledger as d
import durable_local_publisher as p

CONFIG=r.CONFIG+'durable-policy.json'

def validate_configuration(config,policy):
    e.need(type(config)is dict and set(config)=={'anchor','anchor_policy','predecessor_policy','writer_id','approved_transition'},'durable_configuration_schema')
    d.validate_anchor(config['anchor']);e.positive(config['writer_id'])
    for prior in (config['anchor_policy'],config['predecessor_policy']):
        e.validate_policy(prior)
        e.need(all(prior[k]==policy[k] for k in prior if k!='code_contract_digest'),'durable_policy_authority_changed')
    e.validate_checkpoint(config['anchor']['checkpoint'],config['anchor_policy'])
    e.need(config['anchor']['code_contract_digest']==config['anchor_policy']['code_contract_digest'] and
           config['anchor']['workflow_id']==policy['genesis_workflow_id'],'durable_anchor_policy')
    transition=config['approved_transition']
    e.need(type(transition)is dict and set(transition)=={'from_contract','to_contract','previous_state_digest','review_reference'},'durable_reviewed_transition')
    e.need(transition['from_contract']==config['predecessor_policy']['code_contract_digest'] and
           transition['to_contract']==policy['code_contract_digest'],'durable_transition_contract')
    for value in transition.values():e.hashed(value)

def load_context(root):
    policy=e.parse(r.file_bytes(root,r.CONFIG+'policy.json'));e.validate_policy(policy)
    e.need(p.contract_digest(root)==policy['code_contract_digest'],'durable_current_code_contract')
    config=e.parse(r.file_bytes(root,CONFIG));validate_configuration(config,policy)
    # Reviewed main configuration must be the actual checked-out Git bytes.
    for path in (CONFIG,r.CONFIG+'policy.json'):
        e.need(r.git(root,'show','HEAD:'+path)==r.file_bytes(root,path),'durable_uncommitted_configuration')
    record_raw=r.file_bytes(root,r.CONFIG+'import-record.json');record=r.provenance.parse_record(record_raw)
    e.need(record.unresolved_digest==policy['legacy_unresolved_digest'] and
           record.authorization_reference_digest==policy['authorization_reference_digest'],'migration_binding')
    source=r.snapshot.read_snapshot('source',record.source.commit,local_tree_proof=r.tree_proof(root,record.source.commit))
    destination=r.snapshot.read_snapshot('destination',record.destination.commit,local_tree_proof=r.tree_proof(root,record.destination.commit))
    r.snapshot.validate_authenticated_import(record_raw,source,destination,expected_record_digest=policy['import_record_digest'])
    tail_raw=r.file_bytes(root,r.CONFIG+'source-final-tail.json');e.need(e.sha(tail_raw)==policy['source_final_tail_digest'],'source_tail_pin')
    tail=e.parse(tail_raw)
    e.need(type(tail)is dict and set(tail)=={'commit','tree','status'} and tail['status']=='historical_tail_quarantined_not_current_authority','source_tail_schema')
    e.hashed(tail['commit'],40);e.hashed(tail['tree'],40)
    metadata=r.snapshot._get(r.provenance.LEGACY[0],'/git/commits/'+tail['commit'],time.monotonic()+30,r.snapshot.META_CAP)
    e.need(metadata.get('sha')==tail['commit'] and metadata.get('tree',{}).get('sha')==tail['tree'],'source_final_tail_binding')
    return policy,config,record,r.validate_local_inputs(root,policy,record)

def validate_prior(previous,config,policy):
    d.validate_state(previous,config['anchor'])
    cp=previous['checkpoint']
    if cp['epoch']==e.digest(policy):e.validate_checkpoint(cp,policy)
    elif cp['epoch']==e.digest(config['predecessor_policy']):e.validate_checkpoint(cp,config['predecessor_policy'])
    else:raise e.Blocked('durable_prior_epoch_unreviewed')
    if previous['code_contract_digest']!=policy['code_contract_digest']:
        transition=config['approved_transition']
        e.need(transition['from_contract']==previous['code_contract_digest'] and
               transition['previous_state_digest']==e.digest(previous),'durable_transition_state_changed')
    return cp

def prepare_candidate(policy,config,previous,inputs,run):
    """Pure candidate construction; caller authenticates state and current run."""
    prior=validate_prior(previous,config,policy);p.validate_producer(run,config['anchor'])
    e.need(run['run_number']==previous['last_run_number']+1 and run['id']!=previous['last_run_id'],'durable_candidate_run_gap')
    # Do not rewrite the old checkpoint to pretend it used the new code epoch.
    cp=e.parse(e.prepare_checkpoint(policy,inputs,run_id=run['id'],run_attempt=1,head_sha=run['head_sha'],
        legacy_inventory_digest=policy['legacy_inventory_digest']))
    cp['sequence']=prior['sequence']+1;cp['predecessor']=e.digest(prior)
    e.validate_checkpoint(cp,policy);d.validate_summary(cp)
    return e.canonical(cp)

def pending_runs(reader,anchor,state):
    """Inclusive timestamp cursor, anchored last run, contiguous run numbers.

    This authenticates the accepted chain and new tail, not the absence of all
    historical reruns. An old rerun cannot append or replace a sealed event.
    """
    d.validate_state(state,anchor)
    cutoff=urllib.parse.quote('>='+state['last_created_at'],safe='')
    path='/actions/workflows/'+str(anchor['workflow_id'])+'/runs?created='+cutoff
    rows=r.listing(reader,path,'workflow_runs')
    sealed=[row for row in rows if row.get('run_number')==state['last_run_number']]
    e.need(len(sealed)==1 and sealed[0].get('id')==state['last_run_id'] and
           sealed[0].get('created_at')==state['last_created_at'],'durable_tail_anchor_missing')
    pending=sorted([row for row in rows if type(row.get('run_number'))is int and row['run_number']>state['last_run_number']],key=lambda row:row['run_number'])
    for row in pending:p.validate_producer(row,anchor)
    e.need([row['run_number'] for row in pending]==list(range(state['last_run_number']+1,state['last_run_number']+len(pending)+1)),'durable_tail_run_gap')
    return pending

def runner_scope(root,publisher=False):
    e.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')==e.REPOSITORY and
           os.environ.get('GITHUB_REPOSITORY_ID')==str(e.REPOSITORY_ID) and os.environ.get('GITHUB_REPOSITORY_OWNER_ID')==str(e.OWNER_ID),'durable_runner_scope')
    head=r.git(root,'rev-parse','HEAD').decode().strip();e.hashed(head,40)
    e.need(head==os.environ.get('GITHUB_SHA') and os.environ.get('GITHUB_REF')=='refs/heads/main','durable_checkout_scope')
    target=p.PUBLISHER_WORKFLOW if publisher else e.WORKFLOW
    e.need(os.environ.get('GITHUB_WORKFLOW_REF')==e.REPOSITORY+'/'+target+'@refs/heads/main','durable_workflow_scope')
    e.need(os.environ.get('GITHUB_EVENT_NAME') in (('workflow_run','workflow_dispatch') if publisher else ('schedule','workflow_dispatch')),'durable_event_scope')
    return head

def produce(root,output):
    root=root.resolve();head=runner_scope(root)
    policy,config,record,inputs=load_context(root);reader=r.GithubReader()
    previous=d.read_authenticated_state(reader,anchor=config['anchor'],writer_id=config['writer_id'])
    validate_prior(previous.state,config,policy)
    rows=pending_runs(reader,config['anchor'],previous.state)
    rid=int(os.environ['GITHUB_RUN_ID']);e.need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','durable_retry_requires_reconciliation')
    e.need(rows and rows[0]['id']==rid and rows[0]['head_sha']==head and rows[0].get('status')=='in_progress','durable_prior_terminal_publication_pending')
    # Later queued runs do not authorize skipping an unsealed earlier run.
    e.need(all(row.get('status') in ('queued','waiting','pending','requested') for row in rows[1:]),'durable_concurrent_producer')
    raw=prepare_candidate(policy,config,previous.state,inputs,rows[0])
    e.need(pending_runs(reader,config['anchor'],previous.state)==rows,'durable_producer_tail_changed')
    observed=d.read_authenticated_state(reader,anchor=config['anchor'],writer_id=config['writer_id'])
    e.need(observed.commit==previous.commit and observed.state==previous.state,'durable_state_changed_during_compute')
    r.validate_local_inputs(root,policy,record)
    output=output.resolve();e.need(not output.is_relative_to(root),'output_must_be_outside_repository')
    output.mkdir(parents=True,exist_ok=False)
    with (output/'checkpoint.json').open('xb') as stream:stream.write(raw)
    return {'status':'durable_candidate_retention_pending','run_id':rid,'sequence':e.parse(raw)['sequence'],'full_core_recovery':False}

def drain(root):
    root=root.resolve();runner_scope(root,publisher=True)
    policy,config,record,inputs=load_context(root);reader=r.GithubReader()
    previous=d.read_authenticated_state(reader,anchor=config['anchor'],writer_id=config['writer_id'])
    processed=[]
    # Bounded batches heal out-of-order workflow_run delivery without skipping.
    # A later producer completion triggers another drain; manual intervention is
    # required only for an ambiguous failure, missing run or oversized backlog.
    for _ in range(3):
        validate_prior(previous.state,config,policy)
        rows=pending_runs(reader,config['anchor'],previous.state)
        if not rows or rows[0].get('status')!='completed':break
        receipt=p.read_terminal_receipt(reader,root=root,policy=policy,anchor=config['anchor'],previous=previous,run_id=rows[0]['id'],inputs=inputs)
        previous=p.publish(reader,previous=previous,receipt=receipt,anchor=config['anchor'],policy=policy,
                           writer_id=config['writer_id'],approved_transition=config['approved_transition'])
        processed.append(rows[0]['id'])
    return {'status':'durable_terminal_batch_verified','published_run_ids':processed,'last_run_number':previous.state['last_run_number'],'full_core_recovery':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('produce','publish','initialize'))
    parser.add_argument('--root',required=True,type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        e.need(args.mode!='produce' or args.output is not None,'durable_output_required')
        if args.mode=='initialize':
            root=args.root.resolve();runner_scope(root,publisher=True)
            policy,config,record,inputs=load_context(root)
            observed=p.initialize(r.GithubReader(),anchor=config['anchor'],writer_id=config['writer_id'])
            result={'status':'durable_bootstrap_verified','commit':observed.commit,'full_core_recovery':False}
        else:result=produce(args.root,args.output) if args.mode=='produce' else drain(args.root)
        print(e.canonical(result).decode());return 0
    except (e.Blocked,r.provenance.ProvenanceError) as exc:
        # Only library symbolic errors, never arbitrary transport bodies/tokens.
        print(e.canonical({'status':'blocked','reason':str(exc),'full_core_recovery':False}).decode());return 1
    except (OSError,KeyError,TypeError,ValueError):
        print('{"status":"blocked","reason":"durable_runtime_invalid_context","full_core_recovery":false}');return 1

if __name__=='__main__':raise SystemExit(main())
