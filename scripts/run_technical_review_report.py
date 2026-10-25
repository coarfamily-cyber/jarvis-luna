"""Manual runner: saved inputs only -> strictly allowlisted review artifact.

Never sends to teams or writes repository/Shopify/state. Artifact is not an ACK.
"""
import hashlib,json,os,re,sys
from pathlib import Path
from run_technical_fix_review import read,INPUT,FIXTURE,need
from technical_fix_review import project
from team_router_moe import TEAMS
ROOT=Path(__file__).resolve().parents[1]
NAME='Owned technical review report'

def report(root):
    runtime,raw=read(root,INPUT);doc,fixture_bytes=read(root,FIXTURE)
    need(isinstance(runtime,dict) and isinstance(runtime.get('teams'),list))
    teams=runtime['teams'];need(len(teams)==len(TEAMS))
    need(all(isinstance(t,dict) and isinstance(t.get('id'),str) for t in teams))
    need(set(t['id'] for t in teams)==set(TEAMS))
    projection=project(doc)
    incidents=[]
    for r in projection['incidents']:
        incidents.append({'error_code':r['incident_id'],'code_state':r['source']['code_state'],
          'code_commit':r['source']['commit'],'evidence_hashes':[e['sha256'] for e in r['evidence']],
          'owner_role':'unassigned','proposed_review_roles':r['proposed_routing'],
          'review_required':True,'sent_at':None,'acknowledgment':None,'team_action_receipt':None})
    return {'schema_version':1,'status':'manual_review_report_created',
      'input_sha256':hashlib.sha256(raw).hexdigest(),'fixture_sha256':hashlib.sha256(fixture_bytes).hexdigest(),
      'input_freshness':'saved_snapshot_only','reference_trust':'hashes_not_independent_truth_or_team_receipts',
      'roles':list(TEAMS),'incidents':incidents,'team_delivery_verified':False,
      'team_execution_verified':False,'execution_authority':'none','external_mutations':0}

def execute(env,root=ROOT):
    sha=env.get('GITHUB_SHA','')
    need(env.get('GITHUB_REPOSITORY')=='coarfamily-cyber/jarvis-luna' and env.get('GITHUB_REPOSITORY_ID')=='1431541717'
      and env.get('GITHUB_REF')=='refs/heads/main' and env.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
      and env.get('GITHUB_RUN_ATTEMPT')=='1' and env.get('GITHUB_WORKFLOW')==NAME
      and isinstance(sha,str) and bool(re.fullmatch('[0-9a-f]{40}',sha)) and env.get('EXPECTED_SHA')==sha
      and bool(re.fullmatch('[1-9][0-9]{0,19}',env.get('GITHUB_RUN_ID',''))))
    temp=Path(env.get('RUNNER_TEMP',''));need(temp.is_absolute() and not temp.is_symlink() and temp.is_dir())
    result=report(Path(root));result['producer_code_sha']=sha
    body=(json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode();need(len(body)<=32768)
    directory=temp/('technical-review-report-'+env['GITHUB_RUN_ID']+'-1')
    directory.mkdir(mode=0o700,exist_ok=False)
    fd=os.open(directory/'result.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(body)
    return result
if __name__=='__main__':
    try:execute(os.environ)
    except Exception:
        print('technical_review_report_blocked',file=sys.stderr);raise SystemExit(1)
