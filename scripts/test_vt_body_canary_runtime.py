from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import vt_body_canary_policy as p
import vt_body_canary_runtime as r


def sample():
    return dict(id=p.PRODUCT,title='VT',handle='vt',status='ACTIVE',descriptionHtml=p.OLD,
        tags=['daiso-pd-1067498','draft-review-required'],updatedAt='2026-10-24T11:00:00Z',vendor='VT',
        publishedAt=None,totalInventory=0,options=[],
        variants={'nodes':[dict(id=k,sku=v,price='1.00',compareAtPrice=None,inventoryQuantity=0,
            inventoryItem={'id':'inventory-'+k,'tracked':False},selectedOptions=[]) for k,v in p.VARIANTS.items()],
            'pageInfo':{'hasNextPage':False,'endCursor':None}},
        media={'nodes':[],'pageInfo':{'hasNextPage':False,'endCursor':None}},
        resourcePublications={'nodes':[{'isPublished':i==0,'publishDate':None,'publication':{
            'id':p.PUBLICATION if i==0 else 'gid://shopify/Publication/'+str(i),'name':'channel'}} for i in range(7)],
            'pageInfo':{'hasNextPage':False,'endCursor':None}})


class RuntimeTests(unittest.TestCase):
    def test_projection_and_changes_rejected(self):
        s=sample()
        self.assertEqual(r.projection(json.dumps({'data':{'product':s}}).encode()),s)
        for field in ('variants','media','resourcePublications'):
            bad=deepcopy(s);bad[field]['pageInfo']['hasNextPage']=True
            with self.subTest(field=field),self.assertRaises(Exception):
                r.projection(json.dumps({'data':{'product':bad}}).encode())
        for change in ('status','id','tags'):
            bad=deepcopy(s);bad[change]='bad'
            with self.subTest(change=change),self.assertRaises(Exception):
                r.projection(json.dumps({'data':{'product':bad}}).encode())

    def test_only_hash_bound_mutation_body_can_be_armed(self):
        t=r.CanaryTransport('apply')
        with self.assertRaises(Exception):t.arm_exact_body('unreviewed')
        self.assertNotIn('mutation',t._bodies)

    def test_transport_other_operations_and_credentials_are_not_sent(self):
        t=r.CanaryTransport('apply')
        with self.assertRaises(Exception):t('mutation',token='CANARY_SECRET')
        with self.assertRaises(Exception):t('arbitrary',token='CANARY_SECRET')

    def test_inactive_candidate_fails_before_network(self):
        with patch.object(r,'CANDIDATE_EXECUTION_ENABLED',False), \
             patch.object(r,'CanaryTransport',side_effect=AssertionError('network')):
            self.assertEqual(r.main(['prepare','--output','unused']),1)

    def test_source_stop_precedes_network(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir()
            (root/'data/gosi.json').write_text(json.dumps({'provider_stops':[{'provider':'daiso'}]}))
            calls=[]
            with self.assertRaises(Exception):r.fetch_source(root,root,request=lambda *a,**k:calls.append(1))
            self.assertEqual(calls,[])

    def test_source_http_redirect_bad_type_size_hash_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir()
            (root/'data/gosi.json').write_text('{"provider_stops":[]}')
            for status,headers,data in [(302,{},b''),(403,{},b''),(200,{'content-type':'text/html'},b'x'),
                                       (200,{'content-type':'image/jpeg'},b'x'*1064638)]:
                calls=[]
                def request(url,**kwargs):
                    calls.append((url,kwargs));return status,headers,data
                with self.subTest(status=status),self.assertRaises(Exception):r.fetch_source(root,root,request=request)
                self.assertEqual(calls,[(r.SOURCE_URL,{'hosts':{'cdn.daisomall.co.kr'}})])
                self.assertFalse((root/'source.bin').exists())

    def test_hash_only_plan_and_real_engine_write_unknown_no_retry(self):
        source=b'synthetic-source';before=p.OLD;after=p.NEW
        digest=lambda s:hashlib.sha256(s.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as d, patch.object(p,'SOURCE',hashlib.sha256(source).hexdigest()), \
             patch.object(p,'BEFORE',digest(before)),patch.object(p,'AFTER',digest(after)), \
             patch.object(r.Policy,'fetch_sources',return_value=source), \
             patch.object(r,'APPROVED_VISIBLE_PROJECTION',r.sha(r.visible_projection(sample()))):
            model=r.Policy();snap=sample();now=datetime(2026,10,24,12,30,tzinfo=timezone.utc)
            scope={'pd_no':'1067498','product_id':p.PRODUCT,'canonical_shop':p.HOST}
            plan=model.build_plan(scope,d,snap,now=now)
            raw=json.dumps(plan)
            self.assertNotIn('<h3>',raw);self.assertNotIn('descriptionHtml"',raw)
            journal=r.tx.make_journal(model,plan,repository='coarfamily-cyber/jarvis-luna',run_id='99',run_attempt='1',code_sha='a'*40,workflow_path=r.WORKFLOW)
            path=Path(d)/'journal.json';r.gallery.atomic_json(path,journal)
            class Client:
                writes=0
                def read_snapshot(self,product):return deepcopy(snap)
                def update_once(self,product,changes):
                    self.writes+=1
                    raise RuntimeError('SECRET_BODY_TOKEN')
            class Checkpoint:
                def verify(self,*args):return True
            client=Client()
            result=r.tx.execute(model,plan,root=d,expected_plan_digest=plan['plan_digest'],client=client,
                                journal_path=path,checkpoint=Checkpoint(),apply=True,now=now)
            self.assertEqual(result['state'],'write_unknown');self.assertEqual(client.writes,1)
            self.assertNotIn('SECRET_BODY_TOKEN',json.dumps(result))
            saved=r.gallery.read_json(path);self.assertEqual(saved['write_attempts'],1)
            self.assertEqual(saved['state'],'write_unknown')

    def test_final_fresh_drift_stops_before_mutation(self):
        source=b'synthetic-source'
        digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as d, patch.object(p,'SOURCE',hashlib.sha256(source).hexdigest()), \
             patch.object(p,'BEFORE',digest(p.OLD)),patch.object(p,'AFTER',digest(p.NEW)), \
             patch.object(r.Policy,'fetch_sources',return_value=source), \
             patch.object(r,'APPROVED_VISIBLE_PROJECTION',r.sha(r.visible_projection(sample()))):
            model=r.Policy();snap=sample();now=datetime(2026,10,24,12,30,tzinfo=timezone.utc)
            scope={'pd_no':'1067498','product_id':p.PRODUCT,'canonical_shop':p.HOST}
            plan=model.build_plan(scope,d,snap,now=now)
            journal=r.tx.make_journal(model,plan,repository='coarfamily-cyber/jarvis-luna',
                run_id='99',run_attempt='1',code_sha='a'*40,workflow_path=r.WORKFLOW)
            path=Path(d)/'journal.json';r.gallery.atomic_json(path,journal)
            class Client:
                reads=0
                writes=0
                def read_snapshot(self,product):
                    self.reads+=1;out=deepcopy(snap)
                    if self.reads==2:out['variants']['nodes'][0]['price']='9.00'
                    return out
                def update_once(self,*args):self.writes+=1
            class Checkpoint:
                def verify(self,*args):return True
            client=Client()
            with self.assertRaises(Exception):
                r.tx.execute(model,plan,root=d,expected_plan_digest=plan['plan_digest'],client=client,
                    journal_path=path,checkpoint=Checkpoint(),apply=True,now=now)
            self.assertEqual(client.writes,0)
            self.assertEqual(r.gallery.read_json(path)['write_attempts'],0)

    def test_protected_projection_keeps_prices_and_publications(self):
        snap=sample();baseline=r.hashes(snap)
        for key in ('variants','media','resourcePublications','tags','title','status'):
            changed=deepcopy(snap);changed[key]=[] if key!='status' else 'DRAFT'
            with self.subTest(key=key):
                try: actual=r.hashes(changed)
                except Exception:continue
                self.assertNotEqual(actual['protected_sha256'],baseline['protected_sha256'])


if __name__=='__main__':unittest.main()
