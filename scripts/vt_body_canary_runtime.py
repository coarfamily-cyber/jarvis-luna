"""Inactive bounded VT canary adapter. Hash-only immutable checkpoint content.

Uses the existing transaction engine without exporting raw product/source bytes.
This bundle has a single approved opt-in run slot. Real execution requires
an independently reviewed fixed run slot, source policy and workflow integration.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import reviewed_copy_transaction as tx
import apply_reviewed_product_gallery as gallery
import shopify_readonly_preflight as auth
import team_repair_readonly as readonly
import team_fix_protocol as protocol
import vt_body_canary_policy as policy

WORKFLOW = '.github/workflows/owned-shopify-readonly-preflight.yml'
PREFIX = 'vt-usage-intent-'
QUERY = readonly.QUERY.replace('JarvisOrganistReadOnly', 'JarvisVTCanaryRead').replace(readonly.PRODUCT_ID, policy.PRODUCT)
QUERY_BODY = json.dumps({'query': QUERY}, separators=(',', ':')).encode()
MUTATION = 'mutation JarvisVTUsageOnly($product:ProductUpdateInput!){productUpdate(product:$product){product{id} userErrors{field}}}'
APPROVED_AT = '2026-10-24T12:08:51+00:00'
EXPIRES_AT = '2026-10-25T12:08:51+00:00'
WORKFLOW_ID = 395025557
EXPECTED_RUN_NUMBER = 5
# Exact operational bundle approved 2026-10-24T12:08:51Z; one fixed run only.
CANDIDATE_EXECUTION_ENABLED = True
APPROVED_VISIBLE_PROJECTION = 'dc3dcdb66b3f26be462a4099933383b9f8bef40452f8304fc7e3686116bd856b'


def require(ok, reason):
    if not ok:
        raise gallery.Hold(reason)


def sha(value):
    return hashlib.sha256(gallery.json_bytes(value)).hexdigest()


def live_window(now):
    require(datetime.fromisoformat(APPROVED_AT) <= now < datetime.fromisoformat(EXPIRES_AT),
            'approved_window_expired_or_future')


def projection(raw):
    data = auth.decode(raw)
    require(not data.get('errors') and isinstance(data.get('data'), dict), 'product_response_invalid')
    p = data['data'].get('product')
    required = {'id','title','handle','status','descriptionHtml','tags','updatedAt','vendor',
                'publishedAt','totalInventory','options','variants','media','resourcePublications'}
    require(isinstance(p, dict) and set(p) == required, 'projection_incomplete')
    require(p['id'] == policy.PRODUCT and p['status'] == 'ACTIVE', 'target_status_changed')
    require(isinstance(p['descriptionHtml'], str) and isinstance(p['tags'], list)
            and all(isinstance(t,str) for t in p['tags']) and
            [t for t in p['tags'] if t.startswith('daiso-pd-')] == ['daiso-pd-1067498'], 'supplier_binding_changed')
    for name in ('variants','media','resourcePublications'):
        c = p[name]
        require(isinstance(c,dict) and set(c) == {'nodes','pageInfo'} and isinstance(c['nodes'],list)
                and isinstance(c['pageInfo'],dict) and set(c['pageInfo']) == {'hasNextPage','endCursor'}
                and c['pageInfo']['hasNextPage'] is False and len(c['nodes']) <= 100,
                'projection_truncated')
    variants=p['variants']['nodes']
    require(len(variants)==2 and all(isinstance(v,dict) for v in variants) and
            {v.get('id'):v.get('sku') for v in variants} == policy.VARIANTS,'variants_changed')
    for v in variants:
        require(set(v)=={'id','sku','price','compareAtPrice','inventoryQuantity','inventoryItem','selectedOptions'}
                and isinstance(v['price'],str) and isinstance(v['inventoryItem'],dict)
                and set(v['inventoryItem'])=={'id','tracked'} and type(v['inventoryItem']['tracked']) is bool
                and type(v['inventoryQuantity']) is int and isinstance(v['selectedOptions'],list), 'variant_incomplete')
    pubs=p['resourcePublications']['nodes']
    require(all(isinstance(v,dict) and set(v)=={'isPublished','publishDate','publication'}
                and type(v['isPublished']) is bool and isinstance(v['publication'],dict)
                and set(v['publication'])=={'id','name'} for v in pubs), 'publication_incomplete')
    require(len(pubs)==7 and len({v['publication']['id'] for v in pubs})==7 and
            [v['publication']['id'] for v in pubs if v['isPublished']] == [policy.PUBLICATION], 'publication_changed')
    for m in p['media']['nodes']:
        require(isinstance(m,dict) and {'id','alt','mediaContentType','status'} <= set(m), 'media_incomplete')
        if m['mediaContentType']=='IMAGE':
            require(isinstance(m.get('image'),dict) and set(m['image'])=={'url','width','height'},'image_incomplete')
    policy.canonical(p)
    return p


def visible_projection(p):
    result={k:p[k] for k in ('id','title','vendor','status','tags','totalInventory')}
    result['variants']=[{k:v[k] for k in ('id','sku','price','inventoryQuantity')} for v in p['variants']['nodes']]
    result['images']=[{'id':m['id'],'alt':m['alt'],'url':m['image']['url']} for m in p['media']['nodes']]
    result['publications']=sorted([{'id':n['publication']['id'],'isPublished':n['isPublished']}
        for n in p['resourcePublications']['nodes']],key=lambda v:v['id'])
    return result


def hashes(snapshot):
    return {'full_sha256':sha(snapshot), 'protected_sha256':sha(policy.protected(snapshot)),
            'body_sha256':policy.digest(snapshot['descriptionHtml'].encode())}


class CanaryTransport(auth.FixedTransport):
    """Fixed bounded ordering; body bytes populated only after exact hash checks."""
    def __init__(self, phase):
        require(phase in ('prepare','apply'), 'phase_invalid')
        super().__init__()
        names = ['initial'] if phase=='prepare' else ['before','last','mutation','after']
        self._operations=dict(auth.OPERATIONS, **{n:('POST','/admin/api/2026-10/graphql.json') for n in names})
        self._bodies=dict(auth.FixedTransport._bodies, **{n:QUERY_BODY for n in names if n!='mutation'})
        self._stages=dict(auth.STAGES, **{n:'unknown' for n in names})

    def arm_exact_body(self, body):
        require(isinstance(body,str) and policy.digest(body.encode())==policy.AFTER, 'mutation_body_not_exact')
        require('mutation' not in self._bodies, 'mutation_already_armed')
        self._bodies['mutation']=json.dumps({'query':MUTATION,'variables':{'product':{
            'id':policy.PRODUCT,'descriptionHtml':body}}},separators=(',',':')).encode()


class Client:
    def __init__(self, transport, token, phase):
        self.transport,self.token=transport,token
        self.reads=iter(['initial'] if phase=='prepare' else ['before','last','after'])
        self.last=None
        self.attempted=False

    def read_snapshot(self, product_id):
        require(product_id==policy.PRODUCT,'target_not_allowed')
        self.last=projection(self.transport(next(self.reads),token=self.token))
        return self.last

    def update_once(self, product_id, changes):
        require(not self.attempted and product_id==policy.PRODUCT and
                changes=={'descriptionHtml_sha256':policy.AFTER}, 'mutation_scope_invalid')
        live_window(datetime.now(timezone.utc))
        require(self.last is not None and policy.digest(self.last['descriptionHtml'].encode())==policy.BEFORE,
                'last_body_changed')
        body=self.last['descriptionHtml'].replace(policy.OLD,policy.NEW,1)
        self.transport.arm_exact_body(body)
        self.attempted=True
        doc=auth.decode(self.transport('mutation',token=self.token))
        result=doc.get('data',{}).get('productUpdate')
        require(not doc.get('errors') and isinstance(result,dict) and result.get('userErrors')==[]
                and result.get('product',{}).get('id')==policy.PRODUCT,'mutation_response_unverified')


class Policy:
    WORKFLOW=WORKFLOW
    PREFIX=PREFIX
    REQUIRE_ORIGINAL_CHECKPOINT=True

    def fetch_sources(self, pd_no, root, *, fetch=None):
        require(pd_no=='1067498','source_target_invalid')
        path=Path(root)/'source.bin'
        raw=protocol.read_regular(path,1064638)
        require(len(raw)==1064638 and policy.digest(raw)==policy.SOURCE,'source_hash_mismatch')
        return raw

    def build_plan(self, scope, root, snapshot, *, now):
        live_window(now)
        require(scope=={'pd_no':'1067498','product_id':policy.PRODUCT,'canonical_shop':policy.HOST},'scope_mismatch')
        source=self.fetch_sources('1067498',root)
        desired=policy.proposed_body(snapshot['descriptionHtml'],source)
        require(desired is not None,'already_corrected_no_write')
        require(sha(visible_projection(snapshot))==APPROVED_VISIBLE_PROJECTION,'approved_visible_projection_changed')
        before=hashes(snapshot)
        result={'schema_version':1,'operation_id':policy.operation_id(),'scope':scope,'before':before,
                'copy_plan':{'changes':{'descriptionHtml_sha256':policy.AFTER},'before':before},
                'source_sha256':policy.SOURCE}
        result['plan_digest']=sha(result)
        return result

    def validate_plan_digest(self, plan, expected):
        require(isinstance(plan,dict) and plan.get('plan_digest')==expected and
                expected==sha({k:v for k,v in plan.items() if k!='plan_digest'}), 'plan_digest_mismatch')
        require(plan.get('operation_id')==policy.operation_id() and plan.get('source_sha256')==policy.SOURCE
                and plan.get('copy_plan',{}).get('changes')=={'descriptionHtml_sha256':policy.AFTER},'plan_scope_invalid')

    def verify_readback(self, copy_plan, snapshot):
        current=hashes(snapshot)
        require(current['protected_sha256']==copy_plan['before']['protected_sha256']
                and current['body_sha256']==policy.AFTER,'readback_mismatch')

    def result(self, state, plan, **extra):
        return {'state':state,'operation_id':plan['operation_id'],'source_holds_retained':True,
                'atomic_cas':False,'automatic_retry_allowed':False,**extra}


class Checkpoint(tx.GitHubCheckpoint):
    def verify(self, plan, journal):
        require(type(journal.get('run_attempt')) is str and journal['run_attempt']=='1','rerun_forbidden')
        run=self.api('/repos/coarfamily-cyber/jarvis-luna/actions/runs/'+journal['run_id'])
        require(run.get('workflow_id')==WORKFLOW_ID and type(run.get('run_number')) is int and
                run['run_number']==EXPECTED_RUN_NUMBER and type(run.get('run_attempt')) is int and
                run['run_attempt']==1 and run.get('head_branch')=='main','single_run_slot_required')
        live_window(datetime.now(timezone.utc))
        return super().verify(plan,journal)

SOURCE_URL = 'https://cdn.daisomall.co.kr/file/PD/20260402/res5cz2HFrWTvzYSMj4r1067498_01_03res5cz2HFrWTvzYSMj4r.jpg/dims/resize/850/quality/100'


def source_guard(root):
    doc=gallery.read_json(Path(root)/'data/gosi.json')
    rows=doc.get('provider_stops')
    require(isinstance(rows,list),'provider_stop_state_missing')
    for row in rows:
        require(isinstance(row,dict) and isinstance(row.get('provider'),str),'provider_stop_state_invalid')
        # Current stop list controls: never silently expire a current entry.
        provider=row['provider'].lower()
        require(provider not in ('daiso','daisomall','cdn.daisomall.co.kr')
                and row.get('host')!='cdn.daisomall.co.kr' and row.get('url')!=SOURCE_URL,
                'source_provider_stop_active')


def fetch_source(root, output, *, request=gallery.https_request):
    source_guard(root)
    status,headers,raw=request(SOURCE_URL,hosts={'cdn.daisomall.co.kr'})
    require(status==200,'source_http_or_redirect_stop')
    require(headers.get('content-type','').split(';')[0].lower()=='image/jpeg'
            and isinstance(raw,bytes) and len(raw)==1064638 and policy.digest(raw)==policy.SOURCE,
            'source_bytes_mismatch')
    # Ephemeral private runner file; explicitly excluded from every artifact.
    with (Path(output)/'source.bin').open('xb') as stream:
        stream.write(raw)


def context(environ):
    require(CANDIDATE_EXECUTION_ENABLED,'candidate_not_activated')
    require(environ.get('GITHUB_REPOSITORY')=='coarfamily-cyber/jarvis-luna'
            and environ.get('GITHUB_REPOSITORY_ID')=='1431541717'
            and environ.get('GITHUB_REF')=='refs/heads/main'
            and environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and environ.get('GITHUB_RUN_ATTEMPT')=='1'
            and environ.get('GITHUB_RUN_NUMBER')==str(EXPECTED_RUN_NUMBER),'fixed_run_context_required')
    require(gallery.SHA1.fullmatch(environ.get('GITHUB_SHA','')) is not None
            and environ.get('EXPECTED_SHA')==environ['GITHUB_SHA']
            and environ.get('GITHUB_RUN_ID','').isdigit(),'expected_commit_required')
    live_window(datetime.now(timezone.utc))
    return {k:environ[k] for k in ('GITHUB_RUN_ID','GITHUB_SHA')}


def authenticate_run(environ, checkpoint):
    ctx=context(environ)
    run=checkpoint.api('/repos/coarfamily-cyber/jarvis-luna/actions/runs/'+ctx['GITHUB_RUN_ID'])
    require(run.get('workflow_id')==WORKFLOW_ID and type(run.get('run_number')) is int
            and run['run_number']==EXPECTED_RUN_NUMBER and type(run.get('run_attempt')) is int
            and run['run_attempt']==1 and str(run.get('id'))==ctx['GITHUB_RUN_ID']
            and run.get('head_sha')==ctx['GITHUB_SHA'] and run.get('head_branch')=='main'
            and run.get('event')=='workflow_dispatch' and run.get('status')=='in_progress'
            and run.get('path')==WORKFLOW,'authenticated_run_slot_required')
    return ctx


def main(argv=None):
    import argparse
    import os
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=('prepare','apply'))
    parser.add_argument('--output',required=True)
    parser.add_argument('--root',default='.')
    args=parser.parse_args(argv)
    stage='context'
    try:
        env=os.environ
        context(env)
        cp=Checkpoint(env.get('GITHUB_TOKEN'),env.get('CHECKPOINT_ID','1'),
                      env.get('CHECKPOINT_DIGEST','0'*64),policy=Policy())
        ctx=authenticate_run(env,cp)
        output=Path(args.output)
        if args.phase=='prepare':
            output.mkdir(mode=0o700,parents=False,exist_ok=False)
            stage='source'
            fetch_source(args.root,output)
        else:
            require(output.is_dir() and not output.is_symlink(),'original_local_intent_missing')
            require(env.get('CHECKPOINT_ID','').isdigit() and env.get('CHECKPOINT_DIGEST'),
                    'original_remote_intent_missing')
        if args.phase=='apply':
            existing=gallery.read_json(output/'journal.json')
            require(existing.get('state')=='prepared' and type(existing.get('write_attempts')) is int
                    and existing['write_attempts']==0,'consumed_or_uncertain_slot_stop')
        stage='identity'
        transport=CanaryTransport(args.phase)
        _,token=auth._verified_session(env,transport=transport)
        client=Client(transport,token,args.phase)
        model=Policy()
        if args.phase=='prepare':
            stage='prepare'
            current=client.read_snapshot(policy.PRODUCT)
            if policy.digest(current['descriptionHtml'].encode())==policy.AFTER:
                gallery.atomic_json(output/'result.json',{'state':'already_corrected_no_op','writes':0})
                return 2  # Stop before upload/apply; never rebreak the product.
            scope={'pd_no':'1067498','product_id':policy.PRODUCT,'canonical_shop':policy.HOST}
            plan=model.build_plan(scope,output,current,now=datetime.now(timezone.utc))
            journal=tx.make_journal(model,plan,repository='coarfamily-cyber/jarvis-luna',
                run_id=ctx['GITHUB_RUN_ID'],run_attempt='1',code_sha=ctx['GITHUB_SHA'],workflow_path=WORKFLOW)
            gallery.atomic_json(output/'plan.json',plan)
            gallery.atomic_json(output/'journal.json',journal)
            # Immutable original staged separately from mutable attempt journal.
            (output/'checkpoint').mkdir()
            gallery.atomic_json(output/'checkpoint/plan.json',plan)
            gallery.atomic_json(output/'checkpoint/journal.json',journal)
            if env.get('GITHUB_OUTPUT'):
                with open(env['GITHUB_OUTPUT'],'a') as stream:
                    stream.write('operation_id='+policy.operation_id()+'\n')
            print(json.dumps({'state':'prepared_hash_only_intent','operation_id':policy.operation_id(),'writes':0}))
            return 0
        stage='apply'
        plan=gallery.read_json(output/'plan.json')
        result=tx.execute(model,plan,root=output,expected_plan_digest=plan['plan_digest'],client=client,
                          journal_path=output/'journal.json',checkpoint=cp,apply=True)
        gallery.atomic_json(output/'result.json',result)
        print(json.dumps(result))
        return 0 if result['state']=='verified' and result.get('writes')==1 else 1
    except Exception:
        # Never dump exception text, HTTP response, body, headers or credentials.
        print(json.dumps({'state':'blocked_or_uncertain','stage':stage,'retry_allowed':False}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
