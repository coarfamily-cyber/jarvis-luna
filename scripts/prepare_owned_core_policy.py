#!/usr/bin/env python3
"""Local deployment preparation only; no remote writes, runs or authority minting.

Requires an actual already-created workflow ID from authenticated GitHub metadata.
The reviewed deployment changes code/config only; all inherited data is frozen.
"""
import argparse
from pathlib import Path
import destination_core_epoch as e
import repository_provenance as p
import owned_core_local as runner

RECORD_PIN='b609974aa560537a6183447eef29c9072e3dbc0ac8eabe03ce6986eb73c02f01'
HISTORICAL_POLICY_PIN='cfe83cdcf173efe10e4460472ae846e923262c868230398737ee3c993320161a'


def prepare(root,record_raw,historical_policy_raw,workflow_id):
    e.positive(workflow_id)
    e.need(e.sha(record_raw)==RECORD_PIN and e.sha(historical_policy_raw)==HISTORICAL_POLICY_PIN,'parent_reviewed_import_pins_required')
    record=p.parse_record(record_raw);history=e.parse(historical_policy_raw)
    tail={k:history['source_final_tail'][k] for k in ('commit','tree','status')}
    tail_raw=e.canonical(tail)
    policy=dict(schema=e.SCHEMA,repository=e.REPOSITORY,repository_id=e.REPOSITORY_ID,owner_id=e.OWNER_ID,
        workflow=e.WORKFLOW,profile=e.PROFILE,import_record_digest=RECORD_PIN,
        legacy_inventory_digest=p.inventory_digest(record.entries),legacy_unresolved_digest=record.unresolved_digest,
        source_final_tail_digest=e.sha(tail_raw),code_contract_digest=runner.code_digest(root),
        authorization_reference_digest=record.authorization_reference_digest,holds=dict(e.HOLDS),
        genesis_workflow_id=workflow_id,genesis_run_number=1)
    e.validate_policy(policy)
    out=root/runner.CONFIG;out.mkdir(parents=True,exist_ok=True)
    for name,raw in {'policy.json':e.canonical(policy),'import-record.json':record_raw,'source-final-tail.json':tail_raw}.items():
        path=out/name
        e.need(not path.exists(),'existing_policy_refuses_overwrite')
        path.write_bytes(raw)
    return policy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--record',type=Path,required=True)
    parser.add_argument('--historical-policy',type=Path,required=True)
    parser.add_argument('--workflow-id',type=int,required=True)
    args=parser.parse_args()
    result=prepare(args.root.resolve(),args.record.read_bytes(),args.historical_policy.read_bytes(),args.workflow_id)
    print(e.canonical({'prepared_epoch':e.digest(result),'workflow_id':args.workflow_id,
                       'authority':'reviewed_local_preparation_only_not_activated'}).decode(),end='')
if __name__=='__main__':main()
