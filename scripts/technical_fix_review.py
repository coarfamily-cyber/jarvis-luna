"""Inactive, pure technical-review projection; no writes, dispatch or team receipts.

Only an explicit caller may attach to a copied internal team-improvement snapshot.
No existing producer, public schema, product RULES or workflow calls this module.
Hashes bind references, not truth. All records remain manual-review/unassigned.
"""
import copy
import json
import re
from team_router_moe import TEAMS

HEX = re.compile(r'[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
IDS = {'pages-workflow-inventory','vt-source-webp','fx-timestamp-schema','core-empty-job-metadata'}
REQUIRED = {'incident_id','summary','source','evidence','test_state','owner_role','proposed_routing','routing_reason','manual_review_required','sent_at','acknowledgment','team_action_receipt','team_status','execution_authority'}


def need(ok):
    if not ok: raise ValueError('technical_review_invalid')


def project(doc):
    need(isinstance(doc,dict) and set(doc)=={'schema_version','incidents'})
    need(type(doc['schema_version']) is int and doc['schema_version']==1)
    rows=doc['incidents']; need(isinstance(rows,list) and len(rows)<=32)
    need(len(json.dumps(doc,ensure_ascii=False,allow_nan=False).encode())<=131072)
    output=[]; seen=set()
    for r in rows:
        need(isinstance(r,dict) and set(r)==REQUIRED)
        id=r['incident_id']; need(isinstance(id,str) and id in IDS and id not in seen); seen.add(id)
        need(r['owner_role']=='unassigned' and r['manual_review_required'] is True)
        need(r['execution_authority']=='none' and r['team_status']=='not_verified')
        need(all(r[k] is None for k in ('sent_at','acknowledgment','team_action_receipt')))
        routing=r['proposed_routing']; need(isinstance(routing,list) and len(routing)<=len(TEAMS))
        need(all(isinstance(t,str) and t in TEAMS for t in routing)); need(len(set(routing))==len(routing))
        for field in ('summary','routing_reason'):
            need(isinstance(r[field],str) and 0<len(r[field])<=500)
        source=r['source']; need(isinstance(source,dict) and set(source)=={'repository','code_state','commit','code_paths'})
        need(source['repository']=='coarfamily-cyber/jarvis-luna')
        need(source['code_state'] in ('committed','local_candidate'))
        commit=source['commit']; need(commit is None if source['code_state']=='local_candidate' else isinstance(commit,str) and bool(SHA.fullmatch(commit)))
        paths=source['code_paths']; need(isinstance(paths,list) and 1<=len(paths)<=16)
        need(all(isinstance(p,str) and len(p)<=200 and not p.startswith('/') and '..' not in p.split('/') and p.startswith(('scripts/','.github/workflows/')) for p in paths))
        evidence=r['evidence']; need(isinstance(evidence,list) and 1<=len(evidence)<=16)
        for e in evidence:
            need(isinstance(e,dict) and set(e)=={'path','sha256','meaning'})
            need(isinstance(e['path'],str) and 0<len(e['path'])<=256 and not e['path'].startswith('/') and '..' not in e['path'].split('/'))
            need(isinstance(e['sha256'],str) and bool(HEX.fullmatch(e['sha256'])))
            need(e['meaning']=='local_captured_bytes_not_team_receipt')
        t=r['test_state']; need(isinstance(t,dict) and set(t)=={'reported_result','executed_by_this_document','scope'})
        need(t['executed_by_this_document'] is False and t['scope']=='local evidence inspection only')
        need(isinstance(t['reported_result'],str) and 0<len(t['reported_result'])<=500)
        output.append(copy.deepcopy(r))
    return {'schema_version':1,'meaning':'technical_manual_review_not_team_receipt','execution_authority':'none','automatic_ingestion_verified':False,'incidents':output}


def attach_to_internal_snapshot(snapshot, doc):
    """Explicit offline hook only; returns new dict, preserves product repair_tasks."""
    need(isinstance(snapshot,dict) and isinstance(snapshot.get('teams'),dict))
    need('technical_review_handoff' not in snapshot)
    need(all(isinstance(t,dict) and 'technical_review_candidates' not in t for t in snapshot['teams'].values()))
    projection=project(doc)
    result=copy.deepcopy(snapshot)
    result['technical_review_handoff']=projection
    for team, card in result['teams'].items():
        card['technical_review_candidates']=[copy.deepcopy(r) for r in projection['incidents'] if team in r['proposed_routing']]
    return result
