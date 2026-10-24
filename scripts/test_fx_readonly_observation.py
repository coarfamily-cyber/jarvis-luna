import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone, timedelta
from email.message import Message
from unittest.mock import patch
import fx_readonly_observation as m
NOW=datetime(2026,10,24,23,17,tzinfo=timezone.utc)
STAMP=datetime(2026,10,24,0,2,31,tzinfo=timezone.utc)
def doc(): return {'result':'success','provider':'https://www.exchangerate-api.com','base_code':'USD','time_last_update_unix':int(STAMP.timestamp()),'time_last_update_utc':'Sat, 24 Oct 2026 00:02:31 +0000','rates':{'KRW':1324.702169}}
def raw(d=None): return json.dumps(doc() if d is None else d).encode()
class Response:
    status=200
    def __init__(self, body):
        self.body=body; self.headers=Message(); self.headers['Content-Type']='application/json'
    def geturl(self): return m.ENDPOINT
    def read(self,n): return self.body[:n]
    def __enter__(self):return self
    def __exit__(self,*args):pass
class Client:
    def __init__(self,response): self.response=response;self.calls=[]
    def open(self,req,timeout):self.calls.append((req,timeout));return self.response
class TestFX(unittest.TestCase):
    def test_success(self):
        r=m.parse_response(raw(),NOW);self.assertEqual(r['observation']['usd_to_krw'],1324.702169)
        self.assertEqual(r['response_sha256'],hashlib.sha256(raw()).hexdigest())
        self.assertFalse(r['pricing_applied']);self.assertEqual(r['product_writes'],0)
        self.assertEqual(r['shipping_planning_floor_krw_per_order'],9000);self.assertIsNone(r['fee_assumption'])
    def test_invalid_rates(self):
        for val in [True,None,'1324',float('nan'),float('inf'),0,400,3001]:
            d=doc();d['rates']['KRW']=val
            with self.subTest(val=val),self.assertRaises(m.ObservationError):m.parse_response(raw(d),NOW)
    def test_identity(self):
        for key,val in [('base_code','KRW'),('result','error'),('provider','https://evil.test')]:
            d=doc();d[key]=val
            with self.subTest(key=key),self.assertRaises(m.ObservationError):m.parse_response(raw(d),NOW)
    def test_timestamp(self):
        for key,val in [('time_last_update_unix',True),('time_last_update_utc','Sat, 24 Oct 2026 00:02:32 +0000'),('time_last_update_utc','2026-10-24')]:
            d=doc();d[key]=val
            with self.subTest(key=key),self.assertRaises(m.ObservationError):m.parse_response(raw(d),NOW)
    def test_malformed_timestamp_type_and_length(self):
        for value in (1, 1e100, None, [], {}, True, '', 'x'*65):
            d=doc();d['time_last_update_utc']=value
            with self.subTest(value=value),self.assertRaises(m.ObservationError):m.parse_response(raw(d),NOW)
    def test_deep_json_is_static_error(self):
        body=b'{"unused":'+b'['*10000+b'0'+b']'*10000+b'}'
        with self.assertRaisesRegex(m.ObservationError,'invalid_provider_response'):m.parse_response(body,NOW)
    def test_proxy_disabled(self):
        c=Client(Response(raw()))
        with patch.object(m.urllib.request,'build_opener',return_value=c) as build:
            m.observe(now=NOW)
        handlers=build.call_args.args
        self.assertIsInstance(handlers[0],m.urllib.request.ProxyHandler)
        self.assertEqual(handlers[0].proxies,{})
        self.assertIsInstance(handlers[1],m.NoRedirect)
    def test_stale_future_naive(self):
        for now in [STAMP-timedelta(seconds=1),STAMP+timedelta(days=4,seconds=1),NOW.replace(tzinfo=None)]:
            with self.subTest(now=now),self.assertRaises(m.ObservationError):m.parse_response(raw(),now)
    def test_duplicates(self):
        with self.assertRaises(m.ObservationError):m.parse_response(b'{"result":"success","result":"success"}',NOW)
    def test_bad_bodies(self):
        for body in [b'',b'x'*64001,b'[]',b'null',b'\xff',b'<html>error']:
            with self.subTest(body=body[:10]),self.assertRaises(m.ObservationError):m.parse_response(body,NOW)
    def test_previous_unchanged(self):
        prev=m.parse_response(raw(),NOW-timedelta(hours=1))['observation'];before=copy.deepcopy(prev)
        self.assertEqual(m.parse_response(raw(),NOW,prev)['status'],'observed');self.assertEqual(prev,before)
    def test_invalid_previous(self):
        with self.assertRaises(m.ObservationError):m.parse_response(raw(),NOW,{'ok':False})
    def test_no_source_date_regression(self):
        prev=m.parse_response(raw(),NOW)['observation'];prev['as_of']='2026-10-25';prev['fetched_at']='2026-10-25T01:00:00+00:00'
        with self.assertRaises(m.ObservationError):m.parse_response(raw(),NOW+timedelta(days=1),prev)
    def test_one_get_no_credentials(self):
        c=Client(Response(raw()));r=m.observe(now=NOW,opener=c)
        self.assertEqual(len(c.calls),1);req,timeout=c.calls[0]
        self.assertEqual(req.full_url,m.ENDPOINT);self.assertEqual(req.get_method(),'GET');self.assertIsNone(req.data)
        self.assertNotIn('Authorization',req.headers);self.assertEqual(timeout,20);self.assertEqual(r['request_limit'],1)
    def test_reject_http_url_type_encoding(self):
        for attr in ['status','url','type','encoding']:
            r=Response(raw())
            if attr=='status':r.status=429
            if attr=='url':r.geturl=lambda:'https://evil.test'
            if attr=='type':r.headers.replace_header('Content-Type','text/html')
            if attr=='encoding':r.headers['Content-Encoding']='gzip'
            with self.subTest(attr=attr),self.assertRaises(m.ObservationError):m.observe(now=NOW,opener=Client(r))
    def test_error_redaction_no_retry(self):
        class Broken:
            calls=0
            def open(self,*a,**kw):self.calls+=1;raise RuntimeError('sensitive_provider_body')
        c=Broken()
        with self.assertRaisesRegex(m.ObservationError,'^provider_unavailable$'):m.observe(now=NOW,opener=c)
        self.assertEqual(c.calls,1)
    def test_redirect_denied(self):
        with self.assertRaises(m.ObservationError):m.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test')
if __name__=='__main__':unittest.main()
