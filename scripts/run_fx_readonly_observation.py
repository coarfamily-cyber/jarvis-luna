"""Owned Actions manual, one fixed public GET; writes runner-temp receipt only."""
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
from fx_readonly_observation import observe, ObservationError

ROOT=Path(__file__).resolve().parents[1]

def execute(env, root=ROOT, observer=observe):
    sha=env.get('GITHUB_SHA','')
    if not (env.get('GITHUB_REPOSITORY')=='coarfamily-cyber/jarvis-luna'
            and env.get('GITHUB_REPOSITORY_ID')=='1431541717'
            and env.get('GITHUB_REF')=='refs/heads/main'
            and env.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and env.get('GITHUB_RUN_ATTEMPT')=='1'
            and env.get('GITHUB_WORKFLOW')=='Owned FX read-only observation'
            and re.fullmatch('[0-9a-f]{40}',sha)
            and env.get('EXPECTED_SHA')==sha
            and re.fullmatch('[1-9][0-9]{0,19}',env.get('GITHUB_RUN_ID',''))):
        raise ObservationError('execution_identity')
    temp=Path(env.get('RUNNER_TEMP',''))
    if not temp.is_absolute() or temp.is_symlink() or not temp.is_dir():
        raise ObservationError('runner_temp')
    directory=temp/('fx-readonly-observation-'+env['GITHUB_RUN_ID']+'-1')
    directory.mkdir(mode=0o700,exist_ok=False)
    # Input is read only. The original collection_status writer is never called.
    previous=json.loads((root/'config/public-fx-observation.json').read_text())['fx']
    provenance={'repository':env['GITHUB_REPOSITORY'],'repository_id':1431541717,
        'code_sha':sha,'run_id':int(env['GITHUB_RUN_ID']),'run_attempt':1,'trigger':'workflow_dispatch'}
    started=datetime.now(timezone.utc).isoformat()
    result=observer(previous)
    result.update(provenance=provenance,started_at=started)
    with (directory/'result.json').open('x') as f:
        json.dump(result,f,sort_keys=True,allow_nan=False);f.write('\n')
    return result

if __name__=='__main__':
    try:execute(os.environ)
    except Exception:
        # No provider body, secrets, or filesystem paths in failure output.
        print('FX observation blocked; no pricing or shipping updates',file=sys.stderr)
        raise SystemExit(1)
