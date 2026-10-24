"""Pure offline observation consumer. No network, persistence, enqueue or authority.

Metadata/state must arrive from an independently trusted verifier/store. Hashes
bind supplied bytes, not authenticity; this module cannot attest caller claims.
"""
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone

REPO='coarfamily-cyber/jarvis-luna'
REPO_ID=1431541717
WORKFLOW_ID=395488635
CODE_SHA='195bc216c2ee8f0ca42ae98ec4d3738370835639'
QUERY_SHA='8f9b35756566ed6d5fdc02120cf91c2b7b2bff7b6c8fc076b71968105c1f645f'
AUTHORITY={'publication_allowed':False,'shopify_write_allowed':False,
           'human_approved':False,'provider_retry_allowed':False}
STATUSES=('ACTIVE','ARCHIVED','DRAFT','UNLISTED')
TTL=timedelta(hours=8)
LIMIT=65536
HEX=re.compile(r'[0-9a-f]{64}')
SAFE=frozenset({'metadata_invalid','archive_invalid','receipt_invalid','clock_invalid',
               'receipt_stale','state_invalid','replay_conflict','out_of_order','state_capacity'})
class Invalid(ValueError):pass

def need(ok,reason):
    if not ok:raise Invalid(reason)

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(x).hexdigest()
def integer(x):return type(x) is int and x>=0

def stamp(x,reason='receipt_invalid'):
    need(type(x) is str and len(x)<=40,reason)
    try:v=datetime.fromisoformat(x.replace('Z','+00:00'))
    except ValueError:raise Invalid(reason) from None
    need(v.tzinfo is not None and v.utcoffset()==timedelta(0),reason)
    return v

def decode(raw):
    need(type(raw) is bytes and len(raw)<=LIMIT,'receipt_invalid')
    def pairs(items):
        d={}
        for k,v in items:
            need(k not in d,'receipt_invalid');d[k]=v
        return d
    try:
        x=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(Invalid('receipt_invalid')))
        canonical(x)
    except (ValueError,TypeError,UnicodeError):raise Invalid('receipt_invalid') from None
    need(type(x) is dict,'receipt_invalid');return x

def summary(s):
    keys={'product_count','status_counts','online_store_url_present_count','active_without_online_store_url_count',
          'orders','revenue','human_sessions','shipping_price','checkout_health','customer_market_availability',
          'source_or_label_readiness','team_observations'}
    need(type(s) is dict and set(s)==keys,'receipt_invalid')
    counts=s['status_counts'];need(type(counts) is dict and set(counts)==set(STATUSES),'receipt_invalid')
    need(all(integer(v) for v in counts.values()),'receipt_invalid')
    n=s['product_count'];u=s['online_store_url_present_count'];a=s['active_without_online_store_url_count']
    need(all(integer(v) for v in (n,u,a)) and n<=50 and sum(counts.values())==n and u<=n
         and a<=counts['ACTIVE'] and counts['ACTIVE']-a<=u and a<=n-u,'receipt_invalid')
    need(all(s[k] is None for k in ('orders','revenue','human_sessions','shipping_price')),'receipt_invalid')
    need(all(s[k]=='not_observed' for k in ('checkout_health','customer_market_availability','source_or_label_readiness')),'receipt_invalid')
    expected=[{'team':'listing','kind':'catalog_status_observation','meaning':'status inventory only; legal/source readiness not inspected'},
              {'team':'channels','kind':'online_store_url_observation','meaning':'missing URL may be intentional; no activation or publication instruction'}]
    need(s['team_observations']==expected,'receipt_invalid')
    return {'product_count':n,'status_counts':dict(counts),'online_store_url_present_count':u,
            'active_without_online_store_url_count':a}

def verified_receipt(archive,meta,now):
    need(type(now) is datetime and now.tzinfo is not None and now.utcoffset()==timedelta(0),'clock_invalid')
    keys={'repository','repository_id','workflow_id','head_sha','head_branch','event','run_id','run_attempt',
          'status','conclusion','completed_at','artifact_id','artifact_name','artifact_sha256','artifact_created_at',
          'artifact_expires_at','artifact_expired','artifact_run_id','artifact_head_sha'}
    need(type(meta) is dict and set(meta)==keys,'metadata_invalid')
    need(meta['repository']==REPO and meta['repository_id']==REPO_ID and meta['workflow_id']==WORKFLOW_ID
         and meta['head_sha']==CODE_SHA and meta['artifact_head_sha']==CODE_SHA and meta['head_branch']=='main'
         and meta['event']=='workflow_dispatch' and type(meta['run_attempt']) is int and meta['run_attempt']==1
         and meta['status']=='completed' and meta['conclusion']=='success' and meta['artifact_expired'] is False,'metadata_invalid')
    need(all(integer(meta[k]) and meta[k]>0 for k in ('run_id','artifact_id','artifact_run_id'))
         and meta['artifact_run_id']==meta['run_id'],'metadata_invalid')
    need(meta['artifact_name']==f"shopify-team-observation-{meta['run_id']}-1",'metadata_invalid')
    created=stamp(meta['artifact_created_at'],'metadata_invalid');expires=stamp(meta['artifact_expires_at'],'metadata_invalid')
    done=stamp(meta['completed_at'],'metadata_invalid')
    need(abs((expires-created)-timedelta(days=30))<=timedelta(seconds=5)
         and created<=done<=now and now<expires,'metadata_invalid')
    need(type(archive) is bytes and len(archive)<=LIMIT and meta['artifact_sha256']==digest(archive),'archive_invalid')
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            infos=z.infolist()
            need(sorted(i.filename for i in infos)==['attempt.json','result.json'] and
                 all(not i.is_dir() and i.file_size<=LIMIT and not i.flag_bits&1
                     and (i.external_attr>>16)&0o170000 !=0o120000 for i in infos)
                 and sum(i.file_size for i in infos)<=LIMIT,'archive_invalid')
            ar=z.read('attempt.json');rr=z.read('result.json')
    except (zipfile.BadZipFile,RuntimeError,OSError):raise Invalid('archive_invalid') from None
    a=decode(ar);r=decode(rr)
    base={'api_version','app_id','execution_authority','installation_id','live_writer_authorized','mode','product_writes',
          'provenance','query_sha256','schema_version','shop_id','started_at',*AUTHORITY}
    need(set(a)==base|{'state','request_limit'} and set(r)==base|{'before_response_sha256','binding','comparison_scope',
         'complete_catalog_projection','connection_receipt_sha256','external_mutations','observed_at','projection_sha256',
         'recheck_response_sha256','retry_allowed','state','summary'},'receipt_invalid')
    need(all(a[k]==r[k] for k in base),'receipt_invalid')
    need(a['state']=='started' and a['request_limit']==6 and type(a['request_limit']) is int
         and r['state']=='observed' and r['complete_catalog_projection'] is True,'receipt_invalid')
    need(r['api_version']=='2026-10' and r['app_id']=='gid://shopify/App/433866375169'
         and r['installation_id']=='gid://shopify/AppInstallation/736198263041' and r['shop_id']==82748997889
         and r['mode']=='fresh_readonly_catalog_observation' and r['execution_authority']=='none'
         and r['live_writer_authorized'] is False and all(r[k] is False for k in AUTHORITY)
         and type(r['product_writes']) is int and r['product_writes']==0 and type(r['external_mutations']) is int
         and r['external_mutations']==0 and r['retry_allowed'] is False and type(r['schema_version']) is int
         and r['schema_version']==1 and r['query_sha256']==QUERY_SHA,'receipt_invalid')
    provenance={'code_sha':CODE_SHA,'repository':REPO,'repository_id':REPO_ID,'run_attempt':1,
                'run_id':meta['run_id'],'trigger':'workflow_dispatch','workflow':'Owned Shopify team observation'}
    need(canonical(r['provenance'])==canonical(provenance),'receipt_invalid')
    need(r['binding']=='hashes bind observed bytes; not a trusted execution/repair completion receipt'
         and r['comparison_scope']=='two matching declared projections, not atomic CAS or market/checkout testing','receipt_invalid')
    need(all(type(r[k]) is str and HEX.fullmatch(r[k]) for k in ('before_response_sha256','recheck_response_sha256',
         'projection_sha256','connection_receipt_sha256')),'receipt_invalid')
    start=stamp(r['started_at']);observed=stamp(r['observed_at'])
    need(start<=observed<=created<=done and observed-start<=timedelta(seconds=150),'receipt_invalid')
    need(now-observed<=TTL,'receipt_stale')
    return {'run_id':meta['run_id'],'artifact_id':meta['artifact_id'],'artifact_sha256':digest(archive),
            'attempt_sha256':digest(ar),'result_sha256':digest(rr),'observed_at':r['observed_at'],
            'projection_sha256':r['projection_sha256'],'aggregate':summary(r['summary'])}

def state_body(state):return {k:v for k,v in state.items() if k!='state_sha256'}
def consume(archive,metadata,prior,*,now):
    """Returns proposals only. Caller must atomically persist verified state separately."""
    common={'schema_version':1,'authority':'none','candidate':None,'next_state':None,**AUTHORITY,
            'trust':'caller_verified_metadata_and_state_required; hashes_do_not_attest_truth'}
    try:
        current=verified_receipt(archive,metadata,now)
        if prior is None:seen=[];last=None;previous_hash=None
        else:
            need(type(prior) is dict and set(prior)=={'schema_version','seen','last','previous_state_sha256','state_sha256'}
                 and type(prior['schema_version']) is int and prior['schema_version']==1 and prior['state_sha256']==digest(canonical(state_body(prior))),'state_invalid')
            seen=prior['seen'];last=prior['last'];previous_hash=prior['state_sha256']
            need(type(seen) is list and 1<=len(seen)<=256 and type(last) is dict,'state_invalid')
            need(all(type(e) is dict and set(e)=={'run_id','artifact_sha256'} and integer(e['run_id'])
                     and e['run_id']>0 and type(e['artifact_sha256']) is str and HEX.fullmatch(e['artifact_sha256']) for e in seen),'state_invalid')
            need(len({e['run_id'] for e in seen})==len(seen) and set(last)==set(current)
                 and seen[-1]=={'run_id':last['run_id'],'artifact_sha256':last['artifact_sha256']},'state_invalid')
            # Prior state stores only the bounded validated aggregate, not arbitrary text.
            ag=last['aggregate'];need(type(ag) is dict and set(ag)==set(current['aggregate']),'state_invalid')
            need(prior['previous_state_sha256'] is None or (type(prior['previous_state_sha256']) is str and HEX.fullmatch(prior['previous_state_sha256'])), 'state_invalid')
            need(integer(last['run_id']) and last['run_id']>0 and stamp(last['observed_at'],'state_invalid')<=now,'state_invalid')
            need([e['run_id'] for e in seen]==sorted(e['run_id'] for e in seen),'state_invalid')
            for k in ('artifact_sha256','attempt_sha256','result_sha256','projection_sha256'):
                need(type(last[k]) is str and HEX.fullmatch(last[k]),'state_invalid')
            need(integer(last['artifact_id']) and last['artifact_id']>0,'state_invalid')
            validate_s=dict(ag,orders=None,revenue=None,human_sessions=None,shipping_price=None,
                            checkout_health='not_observed',customer_market_availability='not_observed',source_or_label_readiness='not_observed',
                            team_observations=[{'team':'listing','kind':'catalog_status_observation','meaning':'status inventory only; legal/source readiness not inspected'}, {'team':'channels','kind':'online_store_url_observation','meaning':'missing URL may be intentional; no activation or publication instruction'}])
            summary(validate_s)
            matches=[e for e in seen if e['run_id']==current['run_id']]
            if matches:
                need(matches[0]['artifact_sha256']==current['artifact_sha256'],'replay_conflict')
                return dict(common,status='duplicate',reason='already_consumed_no_action')
            need(stamp(current['observed_at'])>stamp(last['observed_at'],'state_invalid')
                 and current['run_id']>last['run_id'],'out_of_order')
            need(len(seen)<256,'state_capacity')
        new={'schema_version':1,'seen':seen+[{'run_id':current['run_id'],'artifact_sha256':current['artifact_sha256']}],
             'last':current,'previous_state_sha256':previous_hash}
        new['state_sha256']=digest(canonical(new))
        status='no_baseline' if last is None else ('unchanged' if last['aggregate']==current['aggregate'] else 'review_candidate')
        candidate=None
        if status=='review_candidate':
            candidate={'kind':'catalog_aggregate_change_review','teams':['listing','channels'],'cause':'unknown',
                       'before':last['aggregate'],'after':current['aggregate'],
                       'before_result_sha256':last['result_sha256'],'after_result_sha256':current['result_sha256'],
                       'meaning':'review aggregate change only; no individual product action or publication instruction',**AUTHORITY}
        return dict(common,status=status,reason='first_observation_baseline_only' if last is None else 'validated_comparison',
                    candidate=candidate,next_state=new)
    except Exception as error:
        reason=error.args[0] if type(error) is Invalid and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in SAFE else 'receipt_invalid'
        return dict(common,status='blocked',reason=reason)
