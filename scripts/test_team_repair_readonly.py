"""Offline independent target-bound reader tests; no Shopify requests or credentials."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import team_repair_readonly as r

ENV={'SHOPIFY_STORE':r.connection.HOST,'SHOPIFY_CLIENT_ID':'dummy_id','SHOPIFY_CLIENT_SECRET':'PRIVATE_SECRET'}


def encoded(doc):return json.dumps(doc,ensure_ascii=False).encode()


def projection():
    return {'id':r.PRODUCT_ID,'title':'Organist 200 ml','handle':'fixture-organist','status':'DRAFT',
            'descriptionHtml':'<p>'+r.LABEL+r.REPLACEMENT+'</p><p>190 ml (200g)</p>',
            'tags':['daiso-pd-1025282'],'updatedAt':'2026-10-24T04:45:34Z','vendor':'fixture',
            'publishedAt':None,'totalInventory':2,
            'options':[{'id':'gid://shopify/ProductOption/1','name':'Pack','position':1,'values':['Single','Double']}],
            'variants':{'nodes':[
                {'id':'gid://shopify/ProductVariant/50932438401281','sku':'DS-1025282-1','price':'12.00','compareAtPrice':None,
                 'inventoryQuantity':1,'inventoryItem':{'id':'gid://shopify/InventoryItem/1','tracked':True},'selectedOptions':[{'name':'Pack','value':'Single'}]},
                {'id':'gid://shopify/ProductVariant/50932438597889','sku':'DS-1025282-2','price':'22.00','compareAtPrice':None,
                 'inventoryQuantity':1,'inventoryItem':{'id':'gid://shopify/InventoryItem/2','tracked':True},'selectedOptions':[{'name':'Pack','value':'Double'}]}],
                'pageInfo':{'hasNextPage':False,'endCursor':None}},
            'media':{'nodes':[],'pageInfo':{'hasNextPage':False,'endCursor':None}},
            'resourcePublications':{'nodes':[],'pageInfo':{'hasNextPage':False,'endCursor':None}}}


class ReadonlyTeamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'root';(self.root/'data').mkdir(parents=True)
        (self.root/'data/gosi.json').write_bytes(encoded({'items':{r.SKU:{'maker':r.FRAGMENT,'volume':'190 ml (200g)'}}}))
        (self.root/'data/shopify_daily_registry.json').write_bytes(encoded({'items':[{'pd_no':r.SKU,'name_kr':'Organist 200 ml'}]}))
        self.output=Path(self.temp.name)/'attempt'
        self.before=projection();self.after=copy.deepcopy(self.before);self.calls=[]
        self.failure=None
    def transport(self,operation,**kwargs):
        self.calls.append((operation,kwargs))
        if operation==self.failure:raise RuntimeError('PRIVATE_SECRET PRIVATE_BODY https://evil.invalid')
        c=r.connection
        docs={'token':{'access_token':'PRIVATE_TOKEN','expires_in':86399},
              'shop':{'shop':{'id':c.SHOP_ID,'myshopify_domain':c.CANONICAL_DOMAIN}},
              'identity':{'data':{'currentAppInstallation':{'id':c.INSTALLATION_ID,'app':{'id':c.APP_ID}}}},
              'scopes':{'access_scopes':[{'handle':x} for x in sorted(c.REQUIRED)]},
              'product_before':{'data':{'product':self.before}},
              'product_recheck':{'data':{'product':self.after}}}
        return encoded(docs[operation])
    def execute(self):return r.execute(self.root,self.output,ENV,transport=self.transport)
    def assert_safe(self,result):
        for key in r.protocol.AUTHORITY:self.assertIs(result[key],False)
        self.assertEqual(result['product_writes'],0)
        text=encoded(result)
        for marker in (b'PRIVATE_SECRET',b'PRIVATE_TOKEN',b'PRIVATE_BODY',b'evil.invalid'):
            self.assertNotIn(marker,text)
    def test_real_transport_requires_github_main_before_auth(self):
        with patch.object(r, 'ProductReadTransport', side_effect=AssertionError('no auth')) as factory:
            result = r.execute(self.root, self.output, ENV)
        self.assertEqual(result['reason'], 'github_main_first_attempt_required')
        self.assertEqual(result['stage'], 'execution_context')
        factory.assert_not_called()

    def test_production_context_rejections_all_stop_before_auth(self):
        valid=dict(ENV,GITHUB_ACTIONS='true',GITHUB_REPOSITORY='coarfamily-cyber/jarvis-luna',
                   GITHUB_REF='refs/heads/main',GITHUB_RUN_ATTEMPT='1',GITHUB_SHA='a'*40,GITHUB_RUN_ID='123')
        changes=[{'GITHUB_ACTIONS':'false'},{'GITHUB_REPOSITORY':'other/repo'},
                 {'GITHUB_REF':'refs/pull/1/merge'},{'GITHUB_RUN_ATTEMPT':'2'},
                 {'GITHUB_SHA':'a'*39},{'GITHUB_SHA':'PRIVATE_SECRET'},
                 {'GITHUB_RUN_ID':'0'},{'GITHUB_RUN_ID':'-1'}]
        for i,change in enumerate(changes):
            with self.subTest(change=change),patch.object(r.connection,'_verified_session',side_effect=AssertionError('must not authenticate')) as session:
                result=r.execute(self.root,Path(self.temp.name)/('bad-context-'+str(i)),dict(valid,**change))
                self.assertEqual(result['state'],'blocked')
                self.assertEqual(result['reason'],'github_main_first_attempt_required')
                self.assert_safe(result);session.assert_not_called()

    def test_already_corrected_exact_target_noop(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.execute();self.assertEqual(result['state'],'verified_no_op');self.assert_safe(result)
        self.assertNotIn('proposal',result)
        self.assertIn('volume_conflict',result['unresolved_holds'])
        self.assertEqual([x[0] for x in self.calls],['token','shop','identity','scopes','product_before','product_recheck'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(result,json.loads((self.output/'result.json').read_bytes()))
        self.assertEqual((self.output/'result.json').stat().st_mode & 0o777,0o600)
    def test_fragment_only_review_required_never_write(self):
        self.before['descriptionHtml']=self.before['descriptionHtml'].replace(r.REPLACEMENT,r.FRAGMENT)
        self.after=copy.deepcopy(self.before)
        result=self.execute();self.assertEqual(result['state'],'review_required');self.assert_safe(result)
        self.assertFalse(result['proposal']['executed'])
        self.assertEqual(result['proposal']['changed_fields'],['descriptionHtml'])
        proposed=self.before['descriptionHtml'].replace(r.FRAGMENT,r.REPLACEMENT)
        self.assertEqual(result['proposal']['description_html_sha256'],r.digest(proposed.encode()))
        self.assertNotEqual(result['proposal']['product_sha256'],result['recheck_product_sha256'])
        self.assertIn('volume_conflict',result['unresolved_holds'])
    def test_unknown_manufacturer_and_missing_source_hold(self):
        self.before['descriptionHtml']=self.before['descriptionHtml'].replace(r.REPLACEMENT,'Unknown actual company')
        self.after=copy.deepcopy(self.before)
        (self.root/'data/gosi.json').write_bytes(encoded({'items':{}}))
        result=self.execute();self.assertEqual(result['state'],'review_required');self.assertTrue(result['source_hold_retained']);self.assert_safe(result)
    def test_duplicate_attempt_no_requests_or_overwrite(self):
        first=self.execute();saved=(self.output/'result.json').read_bytes();self.calls.clear()
        second=self.execute();self.assertEqual(second['reason'],'attempt_exists_no_retry')
        self.assertEqual(self.calls,[]);self.assertEqual((self.output/'result.json').read_bytes(),saved);self.assert_safe(first)
    def test_unknown_network_attempt_stays_blocked_duplicate_not_retried(self):
        self.failure='product_recheck';result=self.execute()
        self.assertEqual(result['state'],'blocked');self.assert_safe(result)
        self.assertEqual(len(self.calls),6)
        self.calls.clear();self.failure=None
        self.assertEqual(self.execute()['reason'],'attempt_exists_no_retry');self.assertEqual(self.calls,[])
    def test_readback_drift_typed_and_protected_field(self):
        for field,value in [('descriptionHtml','changed'),('title','changed'),('totalInventory',True),('updatedAt','2026-10-24T05:00:00Z')]:
            with self.subTest(field=field):
                second=copy.deepcopy(self.before);second[field]=value
                task,_,hold=r.task_and_source(self.root)
                with self.assertRaises(ValueError):r.evaluate(task,self.before,second,hold)
    def test_unsupported_or_authority_task_blocked(self):
        task,_,hold=r.task_and_source(self.root)
        for change in ({'issue_id':'supplier-1067498-formula_conflict'},{'rule':'formula_conflict'}, {'team':'legal'},{'human_approved':True}):
            with self.assertRaises(ValueError):r.evaluate(dict(task,**change),self.before,self.after,hold)
    def test_product_identity_variant_pair_and_sku_ambiguity(self):
        for change in ('id','status','tags','variant_id','variant_sku','duplicate_variant'):
            doc=copy.deepcopy(self.before)
            if change=='id':doc['id']='gid://shopify/Product/1'
            elif change=='status':doc['status']='ACTIVE'
            elif change=='tags':doc['tags'].append('daiso-pd-1067498')
            elif change=='variant_id':doc['variants']['nodes'][0]['id']='gid://shopify/ProductVariant/1'
            elif change=='variant_sku':doc['variants']['nodes'][0]['sku']='DS-1067498-1'
            else:doc['variants']['nodes'].append(copy.deepcopy(doc['variants']['nodes'][0]))
            with self.subTest(change=change),self.assertRaises(ValueError):r.product(encoded({'data':{'product':doc}}))
    def test_truncated_graphql_error_and_missing_fields_rejected(self):
        for field in ('variants','media','resourcePublications'):
            doc=copy.deepcopy(self.before);doc[field]['pageInfo']['hasNextPage']=True
            with self.assertRaises(ValueError):r.product(encoded({'data':{'product':doc}}))
        with self.assertRaises(ValueError):r.product(encoded({'data':{'product':self.before},'errors':[{'message':'PRIVATE_BODY'}]}))
        doc=copy.deepcopy(self.before);del doc['descriptionHtml']
        with self.assertRaises(ValueError):r.product(encoded({'data':{'product':doc}}))
    def test_ambiguous_manufacturer_never_noop(self):
        task,_,hold=r.task_and_source(self.root)
        for body in ('no field',self.before['descriptionHtml']*2):
            doc=copy.deepcopy(self.before);doc['descriptionHtml']=body
            with self.assertRaises(ValueError):r.evaluate(task,doc,copy.deepcopy(doc),hold)
    def test_source_hashes_bound_and_duplicate_registry_blocks_before_token(self):
        task,hashes,_=r.task_and_source(self.root)
        self.assertEqual(set(hashes),{'gosi.json','shopify_daily_registry.json'})
        self.assertEqual(task['issue_id'],r.ISSUE)
        (self.root/'data/shopify_daily_registry.json').write_bytes(encoded({'items':[{'pd_no':r.SKU},{'pd_no':r.SKU}]}))
        result=self.execute();self.assertEqual(result['state'],'blocked');self.assertEqual(self.calls,[]);self.assert_safe(result)
    def test_source_duplicate_and_nonfinite_json_any_size_blocks(self):
        path=self.root/'data/gosi.json'
        for padding in (0,70000):
            for tail in ('"items":{}','"bad":1e999'):
                path.write_text('{"items":{"1025282":{"maker":"및 판매원"}},"padding":"'+'x'*padding+'",'+tail+'}')
                with self.assertRaises((ValueError,r.connection.PreflightError)):r.task_and_source(self.root)

    def test_fixed_product_transport_cannot_take_arbitrary_query_or_extra_attempt(self):
        from contextlib import ExitStack
        from unittest.mock import MagicMock
        c=r.connection
        with ExitStack() as stack:
            stack.enter_context(patch.object(c.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]))
            sock=MagicMock();stack.enter_context(patch.object(c.socket,'socket',return_value=sock))
            tls=MagicMock();tls.wrap_socket.return_value=sock
            stack.enter_context(patch.object(c.ssl,'create_default_context',return_value=tls))
            conn=MagicMock();response=MagicMock();conn.getresponse.return_value=response
            response.status=200;response.getheaders.return_value=[('Content-Type','application/json'),('Content-Length','2')];response.read.return_value=b'{}'
            stack.enter_context(patch.object(c.http.client,'HTTPSConnection',return_value=conn))
            transport=r.ProductReadTransport()
            for op in transport._operations:
                transport(op,**({'body':b'dummy_credentials'} if op=='token' else {'token':'PRIVATE_TOKEN'}))
            calls=conn.request.call_args_list
            self.assertEqual(len(calls),6)
            for call in calls[-2:]:
                self.assertEqual(call.kwargs['body'],r.QUERY_BODY)
                self.assertEqual(call.args,('POST','/admin/api/2026-10/graphql.json'))
            with self.assertRaises(c.PreflightError):transport('product_before',token='PRIVATE_TOKEN')
            other=r.ProductReadTransport()
            for op in tuple(other._operations)[:4]:other(op,**({'body':b'dummy'} if op=='token' else {'token':'PRIVATE_TOKEN'}))
            count=conn.request.call_count
            with self.assertRaises(c.PreflightError):other('product_before',token='PRIVATE_TOKEN',body=b'mutation arbitrary')
            self.assertEqual(conn.request.call_count,count)

    def test_initial_attempt_persist_failure_prevents_requests(self):
        with patch.object(r,'write_once',side_effect=OSError('private local error')):
            with self.assertRaises(OSError):self.execute()
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
