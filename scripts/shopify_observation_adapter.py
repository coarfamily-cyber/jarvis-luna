"""Read-only GitHub verification + private LOCAL transactional candidate ledger.

No workflow/cron, Shopify API, remote state writer or task executor. A local DB
is durable only on a provisioned persistent private filesystem, not an ephemeral
Actions runner. Calling code must authorize that destination separately.
"""
import json
import os
from pathlib import Path
import sqlite3
import stat
from datetime import datetime,timezone
import shopify_observation_consumer as c

STEPS=('Offline observation and connection regression tests before credentials',
       'Read existing shop identity and observe catalog twice without writes',
       'Preserve only bounded observation metadata')
PATH='.github/workflows/owned-shopify-team-observation.yml'
OWNER_ID=280980688

class AdapterError(ValueError):pass

def require(ok,code):
    if not ok:raise AdapterError(code)

def production_reader():
    # Reuse reviewed fixed-origin GET and one allowlisted artifact redirect.
    # Existing reader does not forward GitHub authorization to blob storage.
    from owned_core_local import GithubReader
    return GithubReader(public_verification=False)

def verified_input(reader,run_id):
    require(type(run_id) is int and run_id>0,'run_id_invalid')
    repo=reader.json('');require(repo.get('id')==c.REPO_ID and repo.get('full_name')==c.REPO
                                and repo.get('owner',{}).get('id')==OWNER_ID,'repository_invalid')
    commit=reader.json('/git/commits/'+c.CODE_SHA);require(commit.get('sha')==c.CODE_SHA,'producer_commit_invalid')
    run_path=f'/actions/runs/{run_id}'
    run=reader.json(run_path)
    require(run.get('id')==run_id and run.get('workflow_id')==c.WORKFLOW_ID and run.get('path')==PATH
            and run.get('head_sha')==c.CODE_SHA and run.get('head_branch')=='main'
            and run.get('event')=='workflow_dispatch' and type(run.get('run_attempt')) is int and run['run_attempt']==1
            and run.get('status')=='completed' and run.get('conclusion')=='success','run_invalid')
    for key in ('repository','head_repository'):
        r=run.get(key,{})
        require(r.get('id')==c.REPO_ID and r.get('full_name')==c.REPO and r.get('owner',{}).get('id')==OWNER_ID,'run_repository_invalid')
    jobs=reader.json(run_path+'/jobs?filter=latest&per_page=100&page=1')
    require(jobs.get('total_count')==1 and len(jobs.get('jobs',[]))==1,'jobs_inventory_invalid')
    job=jobs['jobs'][0]
    require(job.get('name')=='observe' and job.get('run_id')==run_id and job.get('status')=='completed'
            and job.get('conclusion')=='success','job_invalid')
    steps=job.get('steps',[]);require(type(steps) is list,'steps_invalid')
    numbers=[]
    for name in STEPS:
        found=[s for s in steps if s.get('name')==name]
        require(len(found)==1 and found[0].get('status')=='completed' and found[0].get('conclusion')=='success'
                and type(found[0].get('number')) is int,'step_invalid')
        numbers.append(found[0]['number'])
    require(numbers==sorted(set(numbers)),'step_order_invalid')
    artifact_path=run_path+'/artifacts?per_page=100&page=1'
    listing=reader.json(artifact_path)
    require(listing.get('total_count')==1 and len(listing.get('artifacts',[]))==1,'artifact_inventory_invalid')
    a=listing['artifacts'][0];aid=a.get('id')
    require(type(aid) is int and aid>0 and type(a.get('size_in_bytes')) is int and 0<a['size_in_bytes']<=c.LIMIT
            and a.get('archive_download_url')==f'https://api.github.com/repos/{c.REPO}/actions/artifacts/{aid}/zip','artifact_metadata_invalid')
    raw=reader.archive(aid);require(type(raw) is bytes and len(raw)<=c.LIMIT and len(raw)==a['size_in_bytes']
                                   and a.get('digest')=='sha256:'+c.digest(raw),'artifact_digest_invalid')
    require(reader.json(run_path)==run and reader.json(artifact_path)==listing,'remote_observation_changed')
    wr=a.get('workflow_run',{})
    require(wr.get('repository_id')==c.REPO_ID and wr.get('head_repository_id')==c.REPO_ID
            and wr.get('head_branch')=='main','artifact_repository_invalid')
    meta=dict(repository=c.REPO,repository_id=c.REPO_ID,workflow_id=run['workflow_id'],head_sha=run['head_sha'],
         head_branch=run['head_branch'],event=run['event'],run_id=run_id,run_attempt=run['run_attempt'],status=run['status'],
         conclusion=run['conclusion'],completed_at=run['updated_at'],artifact_id=aid,artifact_name=a.get('name'),
         artifact_sha256=c.digest(raw),artifact_created_at=a.get('created_at'),artifact_expires_at=a.get('expires_at'),
         artifact_expired=a.get('expired'),artifact_run_id=wr.get('id'),artifact_head_sha=wr.get('head_sha'))
    return raw,meta

class LocalLedger:
    """Atomic private SQLite; no shared Core state and no remote persistence."""
    def __init__(self,directory):
        directory=Path(directory)
        require(not directory.is_symlink(),'ledger_symlink')
        directory.mkdir(mode=0o700,parents=False,exist_ok=True)
        st=directory.stat();require(st.st_uid==os.getuid() and not st.st_mode&0o077,'ledger_directory_not_private')
        self.path=directory/'shopify-observation.sqlite3'
        try:
            fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
        except FileExistsError:pass
        st=self.path.lstat();require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid()
                                    and not st.st_mode&0o077,'ledger_file_unsafe')
        self.db=sqlite3.connect(self.path,timeout=2,isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);'
          'CREATE TABLE IF NOT EXISTS receipts (run_id INTEGER PRIMARY KEY, artifact_digest TEXT NOT NULL, result_digest TEXT NOT NULL, state_digest TEXT NOT NULL);'
          'CREATE TABLE IF NOT EXISTS candidates (run_id INTEGER PRIMARY KEY, value TEXT NOT NULL);')
    def close(self):self.db.close()
    def snapshot(self):
        row=self.db.execute('SELECT value FROM state WHERE id=1').fetchone()
        return c.decode(row[0].encode()) if row else None
    def apply(self,raw,meta,*,now,expected_state_sha256=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous=self.snapshot()
            rows=self.db.execute('SELECT run_id,artifact_digest,result_digest,state_digest FROM receipts ORDER BY run_id').fetchall()
            if previous is None:
                require(not rows and self.db.execute('SELECT count(*) FROM candidates').fetchone()[0]==0,'ledger_orphaned_rows')
            else:
                require([{'run_id':x[0],'artifact_sha256':x[1]} for x in rows]==previous.get('seen'),'ledger_state_mismatch')
                require(rows and rows[-1][2]==previous.get('last',{}).get('result_sha256') and rows[-1][3]==previous.get('state_sha256'),'ledger_state_mismatch')
            actual=previous['state_sha256'] if previous else None
            require(actual==expected_state_sha256,'ledger_cas_conflict')
            result=c.consume(raw,meta,previous,now=now)
            require(result['status']!='blocked','consumer_'+result.get('reason','blocked'))
            new=result['next_state']
            if new is not None:
                last=new['last']
                self.db.execute('INSERT INTO receipts VALUES (?,?,?,?)',(last['run_id'],last['artifact_sha256'],last['result_sha256'],new['state_sha256']))
                self.db.execute('INSERT OR REPLACE INTO state VALUES (1,?)',(c.canonical(new).decode(),))
                if result['candidate'] is not None:
                    self.db.execute('INSERT INTO candidates VALUES (?,?)',(last['run_id'],c.canonical(result['candidate']).decode()))
            self.db.execute('COMMIT')
            return result
        except Exception:
            self.db.execute('ROLLBACK');raise

def ingest(reader,run_id,ledger,*,now,expected_state_sha256=None):
    raw,meta=verified_input(reader,run_id)
    # Validating pure consumer first ensures invalid input cannot initialize state.
    return ledger.apply(raw,meta,now=now,expected_state_sha256=expected_state_sha256)
