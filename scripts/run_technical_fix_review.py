"""Explicit local CLI: two fixed saved inputs -> one NEW local review file.

No remote reads, team delivery, workflow activation or execution authority.
"""
import argparse,hashlib,json,os,stat
from pathlib import Path
from technical_fix_review import attach_to_internal_snapshot,need
from team_router_moe import TEAMS
INPUT='data/dashboard_runtime.json'
FIXTURE='scripts/fixtures/technical_fix_review.json'
LIMIT=8*1024*1024

def read(root,name):
    path=root
    for part in Path(name).parts:
        path=path/part
        need(not path.is_symlink())
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        raw=stream.read(LIMIT+1)
    need(len(raw)<=LIMIT)
    def unique(pairs):
        out={}
        for k,v in pairs:
            need(k not in out);out[k]=v
        return out
    doc=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:need(False))
    return doc,raw

def run(root,output):
    root=Path(root).resolve(strict=True);need(root.is_dir())
    output=Path(output)
    need(output.is_absolute() and output.parent.resolve(strict=True).is_relative_to(root))
    need(not output.is_symlink() and not output.exists())
    runtime,raw=read(root,INPUT);doc,fixture_bytes=read(root,FIXTURE)
    need(isinstance(runtime,dict) and isinstance(runtime.get('teams'),list))
    teams=runtime['teams'];need(len(teams)==len(TEAMS))
    need(all(isinstance(r,dict) and isinstance(r.get('id'),str) for r in teams))
    need(set(r['id'] for r in teams)==set(TEAMS))
    snapshot={'teams':{r['id']:r for r in teams},'source_snapshot':{'path':INPUT,'sha256':hashlib.sha256(raw).hexdigest(),'freshness':'saved_snapshot_not_new_team_observation'},'fixture_sha256':hashlib.sha256(fixture_bytes).hexdigest(),'generated_by':'explicit_local_review_only_no_team_delivery'}
    result=attach_to_internal_snapshot(snapshot,doc)
    body=(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode();need(len(body)<=LIMIT)
    # Exclusive create: never replace an existing report or input.
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(body)
    return {'local_report_created':True,'team_delivery_verified':False,'execution_authority':'none','sha256':hashlib.sha256(body).hexdigest()}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try:result=run(a.root,a.output)
    except (ValueError,TypeError,OSError,RecursionError):print('{"status":"blocked_local_review"}');return 1
    print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
