"""One reviewed artifact's local custody binding; no discovery, API, or authority.

Pins originate in API/run/ZIP verification of run 40146249215, attempt 1.
Hash binding proves bytes only. Snapshot review is not engineering repair.
"""
import hashlib,json,os,stat,zipfile,io
from pathlib import Path
RUN_ID=40146249215
CODE_SHA='83055e0264b40123b635db814447dd3498637847'
ZIP_SHA='52f0a90810a2e5969ce64a75ae791d0bfcc1fc880ed67ae6ff6cebe84e1e31b1'
RESULT_SHA='fab6e4be6c7d462b8860f85753bfffbc9080197948d13b5e78fe11bb610dc717'
PATH='data/operations/technical-review-input/artifact.zip'
ROUTES={'vt-source-webp':'sourcing','fx-timestamp-schema':'pricing'}
PURPOSE='review_verified_technical_artifact_only'

def require(ok):
 if not ok:raise ValueError('technical_artifact_binding_invalid')

def read(root):
 p=Path(root)
 for part in Path(PATH).parts:
  p=p/part;require(not p.is_symlink())
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as f:
  require(stat.S_ISREG(os.fstat(f.fileno()).st_mode));raw=f.read(32769)
 require(len(raw)==1194 and hashlib.sha256(raw).hexdigest()==ZIP_SHA)
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  require(z.namelist()==['result.json']);info=z.getinfo('result.json');require(info.file_size==2546)
  body=z.read('result.json')
 require(hashlib.sha256(body).hexdigest()==RESULT_SHA)
 d=json.loads(body);require(d['producer_code_sha']==CODE_SHA and d['team_delivery_verified'] is False and d['team_execution_verified'] is False)
 return d

def evidence(root,action):
 p=action['payload'];code=p.get('technical_error_code');team=action['team']
 require(p.get('purpose')==PURPOSE and code in ROUTES and team==ROUTES[code]
   and p.get('technical_artifact_sha256')==ZIP_SHA and p.get('technical_run_id')==RUN_ID
   and isinstance(p.get('teams'),(list,tuple)) and list(p['teams'])==[team])
 doc=read(root);row=next(r for r in doc['incidents'] if r['error_code']==code)
 require(row['proposed_review_roles']==[team])
 return {'run_id':RUN_ID,'artifact_sha256':ZIP_SHA,'result_sha256':RESULT_SHA,
  'error_code':code,'review_role':team,'source_code_state':row['code_state'],
  'scope':'artifact_consumed_for_local_snapshot_review_only','engineering_fix_completed':False,
  'external_team_delivery_verified':False,'input_review_required':True}
