import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shopify_readonly_preflight as c
import shopify_team_observation as o

NOW = datetime(2026,10,24,22,32,34,tzinfo=timezone.utc)
ENV = {'SHOPIFY_STORE':c.HOST, 'SHOPIFY_CLIENT_ID':'dummy_id',
       'SHOPIFY_CLIENT_SECRET':'dummy_secret', 'GITHUB_ACTIONS':'true',
       'GITHUB_REPOSITORY':o.REPO, 'GITHUB_REPOSITORY_ID':o.REPO_ID,
       'GITHUB_REF':'refs/heads/main', 'GITHUB_WORKFLOW':o.WORKFLOW,
       'GITHUB_EVENT_NAME':'workflow_dispatch', 'GITHUB_RUN_ATTEMPT':'1',
       'GITHUB_SHA':'a'*40, 'EXPECTED_SHA':'a'*40, 'GITHUB_RUN_ID':'12345'}


def row(i=1, status='ACTIVE', url=None):
    return {'id':f'gid://shopify/Product/{i}', 'status':status,
            'updatedAt':'2026-10-24T20:00:00Z', 'onlineStoreUrl':url}


def raw(rows=None, **page):
    return o.canonical({'data':{'products':{'nodes':rows if rows is not None else [row()],
                     'pageInfo':dict(hasNextPage=False,endCursor='cursor',**page)}}})


class Fake:
    def __init__(self, before=None, after=None):
        self.calls=[]
        self.responses=[
            o.canonical({'access_token':'dummy_token','expires_in':3600}),
            o.canonical({'shop':{'id':c.SHOP_ID,'myshopify_domain':c.HOST}}),
            o.canonical({'data':{'currentAppInstallation':{'id':c.INSTALLATION_ID,'app':{'id':c.APP_ID}}}}),
            o.canonical({'access_scopes':[{'handle':s} for s in sorted(c.REQUIRED)]}),
            before if before is not None else raw(), after if after is not None else raw()]
    def __call__(self, operation, **kwargs):
        self.calls.append((operation,kwargs))
        val=self.responses[len(self.calls)-1]
        if isinstance(val,Exception): raise val
        return val


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output=Path(self.tmp.name)/'attempt'

    def execute(self, fake=None, env=None, clock=None):
        return o.execute(self.output, env or ENV, transport=fake or Fake(),clock=clock or (lambda:NOW))

    def test_exact_six_calls_observation_not_authority(self):
        fake=Fake(); result=self.execute(fake)
        self.assertEqual([v[0] for v in fake.calls], list(o.CatalogTransport._operations))
        self.assertEqual(result['state'],'observed')
        self.assertEqual(result['summary']['product_count'],1)
        self.assertFalse(result['live_writer_authorized'])
        for k in o.AUTHORITY:self.assertIs(result[k],False)
        self.assertEqual(result['product_writes'],0)
        self.assertIsNone(result['summary']['orders'])
        self.assertIsNone(result['summary']['revenue'])
        saved=(self.output/'result.json').read_text()
        for s in ('dummy_secret','dummy_token','dummy_id'):self.assertNotIn(s,saved)
        self.assertNotIn('scope_names',saved)
        self.assertNotIn('gid://shopify/Product/',saved)
        self.assertNotIn('updated_at',saved)
        self.assertNotIn('online_store_url_sha256',saved)
        self.assertNotIn('products',result)

    def test_duplicate_attempt_stops_before_network(self):
        self.execute(); fake=Fake(); r=self.execute(fake)
        self.assertEqual(fake.calls,[]);self.assertEqual(r['reason'],'attempt_exists_no_retry')

    def test_invalid_context_stops_before_network(self):
        for k,v in [('GITHUB_EVENT_NAME','schedule'),('GITHUB_RUN_ATTEMPT','2'),
                    ('GITHUB_REPOSITORY','coar0000-wq/jarvis-luna'),('GITHUB_REPOSITORY_ID','1'),
                    ('EXPECTED_SHA','b'*40),('GITHUB_REF','refs/heads/evil'),
                    ('GITHUB_WORKFLOW','arbitrary'),('GITHUB_RUN_ID','0')]:
            with self.subTest(k=k):
                fake=Fake()
                with self.assertRaises(o.ObservationError):self.execute(fake,dict(ENV,**{k:v}))
                self.assertEqual(fake.calls,[])

    def test_shop_app_installation_mismatch_blocks(self):
        for i,doc in [(1,{'shop':{'id':1,'myshopify_domain':c.HOST}}),
            (2,{'data':{'currentAppInstallation':{'id':'wrong','app':{'id':c.APP_ID}}}}),
            (2,{'data':{'currentAppInstallation':{'id':c.INSTALLATION_ID,'app':{'id':'wrong'}}}})]:
            with self.subTest(i=i,doc=doc),tempfile.TemporaryDirectory() as tmp:
                fake=Fake();fake.responses[i]=o.canonical(doc)
                r=o.execute(Path(tmp)/'run',ENV,transport=fake,clock=lambda:NOW)
                self.assertEqual(r['state'],'blocked');self.assertIsNone(r['summary'])
                self.assertEqual(len(fake.calls),i+1)

    def test_truncation_never_partial_count(self):
        doc=json.loads(raw());doc['data']['products']['pageInfo']['hasNextPage']=True
        fake=Fake(before=o.canonical(doc));r=self.execute(fake)
        self.assertEqual(r['reason'],'catalog_truncated');self.assertIsNone(r['summary'])
        self.assertEqual(len(fake.calls),5)

    def test_graphql_errors_do_not_leak(self):
        fake=Fake(before=o.canonical({'errors':[{'message':'dummy_secret'}],'data':None}))
        r=self.execute(fake);self.assertEqual(r['reason'],'catalog_graphql_error')
        self.assertNotIn('dummy_secret',json.dumps(r));self.assertNotIn('products',r)

    def test_missing_null_wrong_shape_not_zero(self):
        for value in ({'data':None},{'data':{'products':None}},
                      {'data':{'products':{'nodes':None,'pageInfo':{}}}}):
            with self.assertRaises(o.ObservationError):o.parse_catalog(o.canonical(value),now=NOW)

    def test_valid_empty_is_actual_zero(self):
        p=o.parse_catalog(raw([]),now=NOW)
        self.assertEqual(o.summarize(p,p)['product_count'],0)

    def test_unique_sorted_ids(self):
        for values in ([row(),row()], [row(2),row(1)]):
            with self.assertRaises(o.ObservationError):o.parse_catalog(raw(values),now=NOW)

    def test_over_capacity(self):
        with self.assertRaises(o.ObservationError):o.parse_catalog(raw([row(i+1) for i in range(51)]),now=NOW)

    def test_invalid_product_fields(self):
        for changes in ({'id':'gid://shopify/Customer/1'},{'status':'UNKNOWN'},
                        {'status':None},{'updatedAt':None},{'updatedAt':'bad'},
                        {'updatedAt':'2026-10-26T00:00:00Z'},
                        {'updatedAt':'2026-10-24T20:00:00'}, {'extra':'payload'}):
            with self.subTest(changes=changes),self.assertRaises(o.ObservationError):
                o.parse_catalog(raw([dict(row(),**changes)]),now=NOW)

    def test_all_statuses_preserved_including_unlisted(self):
        p=o.parse_catalog(raw([row(i+1,s) for i,s in enumerate(o.STATUSES)]),now=NOW)
        self.assertEqual(o.summarize(p,p)['status_counts'],{s:1 for s in o.STATUSES})

    def test_bad_urls_never_followed(self):
        for u in ('http://coarfamily.myshopify.com/products/x',
                  'https://evil.example/products/x',
                  'https://x:pw@coarfamily.myshopify.com/products/x',
                  'https://coarfamily.myshopify.com/products/x?token=bad',
                  'https://coarfamily.myshopify.com/products/x#bad',
                  'https://coarfamily.myshopify.com:123/products/x', 'javascript:foo', ''):
            with self.subTest(u=u),self.assertRaises(o.ObservationError):o.parse_catalog(raw([row(url=u)]),now=NOW)

    def test_url_redacted_hash_bound(self):
        url='https://coarfamily.myshopify.com/ko/products/test'
        fake=Fake(raw([row(url=url)]),raw([row(url=url)]));r=self.execute(fake)
        self.assertEqual(r['summary']['online_store_url_present_count'],1)
        self.assertNotIn(url,json.dumps(r))
        self.assertEqual(o.parse_catalog(raw([row(url=url)]),now=NOW)[0]['online_store_url_sha256'],o.sha(url.encode()))
        self.assertNotIn('products',r)

    def test_changed_status_or_url_blocks(self):
        for after in (row(status='DRAFT'),row(url='https://coarfamily.myshopify.com/products/x')):
            with tempfile.TemporaryDirectory() as tmp:
                r=o.execute(Path(tmp)/'a',ENV,transport=Fake(after=raw([after])),clock=lambda:NOW)
                self.assertEqual(r['reason'],'catalog_changed_between_reads');self.assertIsNone(r['summary'])

    def test_graphql_extension_cost_change_not_product_change(self):
        after=json.loads(raw());after['extensions']={'cost':{'restoreRate':1000.0}}
        self.assertEqual(self.execute(Fake(after=o.canonical(after)))['state'],'observed')

    def test_403_429_network_unknown_no_retry(self):
        for error in (c.PreflightError('http_forbidden'),c.PreflightError('http_rate_limited'),
                      RuntimeError('dummy_secret'),TimeoutError('dummy_token')):
            with tempfile.TemporaryDirectory() as tmp:
                fake=Fake();fake.responses[4]=error
                r=o.execute(Path(tmp)/'a',ENV,transport=fake,clock=lambda:NOW)
                self.assertEqual(len(fake.calls),5);self.assertEqual(r['state'],'blocked')
                self.assertIsNone(r['summary']);self.assertNotIn('dummy_',json.dumps(r))

    def test_clock_regression_and_duration(self):
        for end in (NOW-timedelta(seconds=1),NOW+timedelta(seconds=151)):
            values=iter([NOW,NOW,end])
            with tempfile.TemporaryDirectory() as tmp:
                r=o.execute(Path(tmp)/'a',ENV,transport=Fake(),clock=lambda:next(values))
                self.assertEqual(r['reason'],'observation_duration_invalid')

    def test_oversize_duplicate_nonfinite_json(self):
        for data in (b' '*(c.LIMIT+1),b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}'):
            with self.assertRaises(c.PreflightError):o.parse_catalog(data,now=NOW)

    def test_symlink_existing_output_no_request(self):
        self.output.symlink_to(Path(self.tmp.name),target_is_directory=True)
        fake=Fake();r=self.execute(fake)
        self.assertEqual(fake.calls,[]);self.assertEqual(r['reason'],'attempt_exists_no_retry')

    def test_transport_only_fixed_queries_no_mutations(self):
        self.assertEqual(len(o.CatalogTransport._operations),6)
        self.assertEqual(set(o.CatalogTransport._bodies),{'identity','catalog_before','catalog_recheck'})
        self.assertNotIn('mutation',o.QUERY.lower())
        self.assertEqual(o.CatalogTransport._bodies['catalog_before'],o.CatalogTransport._bodies['catalog_recheck'])
        tr=o.CatalogTransport();tr.next_operation=6
        with patch.object(c.socket,'getaddrinfo') as dns,self.assertRaises(c.PreflightError):
            tr('catalog_before',token='dummy_token')
        dns.assert_not_called()

    def test_error_message_whitelist(self):
        self.assertEqual(o.safe_reason(o.ObservationError('dummy_secret')),'readonly_observation_failed_redacted')
        self.assertEqual(o.safe_reason(o.ObservationError(['dummy_secret'])),'readonly_observation_failed_redacted')
        self.assertEqual(o.safe_reason(Exception('dummy_secret')),'readonly_observation_failed_redacted')


if __name__ == '__main__':unittest.main()
