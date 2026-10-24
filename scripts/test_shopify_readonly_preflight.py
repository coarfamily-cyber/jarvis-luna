import contextlib
import io
import json
import unittest
from unittest.mock import patch
import shopify_readonly_preflight as p

ENV = {'SHOPIFY_STORE': p.HOST, 'SHOPIFY_CLIENT_ID': 'dummy_id', 'SHOPIFY_CLIENT_SECRET': 'dummy_secret'}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = [
            {'access_token': 'dummy_token', 'expires_in': 86399},
            {'shop': {'id': p.SHOP_ID, 'myshopify_domain': p.CANONICAL_DOMAIN}},
            {'data': {'currentAppInstallation': {'id': p.INSTALLATION_ID, 'app': {'id': p.APP_ID}}}},
            {'access_scopes': [{'handle': n} for n in sorted(p.REQUIRED | {'write_themes'})]}]

    def request(self, op, **kwargs):
        self.calls.append((op, kwargs))
        return json.dumps(self.responses[len(self.calls)-1]).encode()

    def test_exact_operations_safe_receipt(self):
        result = p.run(ENV, transport=self.request)
        self.assertEqual([c[0] for c in self.calls], ['token', 'shop', 'identity', 'scopes'])
        self.assertEqual(result['excess_scope_names'], ['write_themes'])
        self.assertFalse(result['live_writer_authorized'])
        self.assertTrue(result['app_identity_independently_verified'])
        self.assertNotIn('dummy_', json.dumps(result))
        self.assertIn(b'grant_type=client_credentials', self.calls[0][1]['body'])
        self.assertNotIn(b'scope=', self.calls[0][1]['body'])

    def test_missing_and_wrong_host_before_network(self):
        for change in ({'SHOPIFY_CLIENT_SECRET': ''}, {'SHOPIFY_STORE': 'evil.myshopify.com'},
                       {'SHOPIFY_STORE': 'https://' + p.HOST}, {'SHOPIFY_ADMIN_TOKEN': 'dummy'}):
            with self.subTest(change=change), self.assertRaises(p.PreflightError):
                p.run(dict(ENV, **change), transport=self.request)
        self.assertEqual(self.calls, [])

    def test_wrong_shop_stops_before_scopes(self):
        self.responses[1]['shop']['id'] = 1
        with self.assertRaises(p.PreflightError): p.run(ENV, transport=self.request)
        self.assertEqual(len(self.calls), 2)

    def test_bool_id_rejected(self):
        self.responses[1]['shop']['id'] = True
        with self.assertRaises(p.PreflightError): p.run(ENV, transport=self.request)

    def test_wrong_app_stops_before_scopes(self):
        self.responses[2]['data']['currentAppInstallation']['app']['id'] = 'gid://shopify/App/1'
        with self.assertRaises(p.PreflightError): p.run(ENV, transport=self.request)
        self.assertEqual(len(self.calls), 3)

    def test_wrong_installation_and_graphql_errors_stop_before_scopes(self):
        for identity in (
            {'data':{'currentAppInstallation':{'id':'gid://shopify/AppInstallation/1','app':{'id':p.APP_ID}}}},
            {'data':{'currentAppInstallation':{'id':p.INSTALLATION_ID,'app':{'id':p.APP_ID}}},'errors':[{'message':'dummy_secret'}]},
            {'data':{'currentAppInstallation':None}}):
            self.calls.clear();self.responses[2]=identity
            with self.assertRaises(p.PreflightError) as caught:p.run(ENV,transport=self.request)
            self.assertEqual(len(self.calls),3)
            self.assertNotIn('dummy_secret',str(caught.exception))

    def test_transport_alias_does_not_substitute_canonical_shop_identity(self):
        self.assertEqual(p.HOST,p.CANONICAL_DOMAIN)
        self.assertNotEqual(p.PUBLIC_ALIAS,p.HOST)
        self.responses[1]['shop']['myshopify_domain']=p.PUBLIC_ALIAS
        with self.assertRaises(p.PreflightError):p.run(ENV,transport=self.request)
        self.assertEqual(len(self.calls),2)
        self.calls.clear();self.responses[1]['shop']['myshopify_domain']=p.CANONICAL_DOMAIN
        with self.assertRaises(p.PreflightError):p.run(dict(ENV,SHOPIFY_STORE=p.PUBLIC_ALIAS),transport=self.request)
        self.assertEqual(self.calls,[])

    def test_missing_scopes(self):
        self.responses[3]['access_scopes'] = []
        with self.assertRaises(p.PreflightError): p.run(ENV, transport=self.request)

    def test_unknown_scope_strings_not_logged(self):
        self.responses[3]['access_scopes'] = [{'handle': 'dummy_secret'}]
        with self.assertRaises(p.PreflightError): p.run(ENV, transport=self.request)

    def test_expiry_required(self):
        self.responses[0].pop('expires_in')
        with self.assertRaises(p.PreflightError): p.run(ENV, transport=self.request)
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_nonfinite_oversize_json(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b' '*(p.LIMIT+1)):
            with self.assertRaises(p.PreflightError): p.decode(raw)

    def test_transport_errors_redacted_no_retry(self):
        def fail(*args, **kw):
            self.calls.append(args)
            raise ValueError('dummy_secret dummy_token')
        with self.assertRaisesRegex(p.PreflightError, '^preflight_failed_redacted$'):
            p.run(ENV, transport=fail)
        self.assertEqual(len(self.calls), 1)

    def test_transport_rejects_unordered_calls_before_socket(self):
        with patch.object(p.socket, 'getaddrinfo', side_effect=AssertionError('network')) as dns:
            for op in ('shop', 'scopes', 'mutation', 'https://evil'):
                with self.assertRaises(p.PreflightError): p.FixedTransport()(op)
            dns.assert_not_called()

    def test_failed_attempt_consumed(self):
        t = p.FixedTransport()
        with patch.object(p.socket, 'getaddrinfo', side_effect=OSError('dummy_secret')) as dns:
            with self.assertRaises(p.PreflightError): t('token', body=b'x')
            with self.assertRaises(p.PreflightError): t('token', body=b'x')
            self.assertEqual(dns.call_count, 1)

    def test_cli_redacts_even_unexpected_exception(self):
        out = io.StringIO()
        with patch.object(p, 'run', side_effect=ValueError('dummy_secret')), contextlib.redirect_stdout(out):
            self.assertEqual(p.main(), 1)
        self.assertNotIn('dummy_secret', out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'], 'blocked')



class IndependentTransportTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        from contextlib import ExitStack
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.addresses = self.stack.enter_context(patch.object(p.socket, 'getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',443))]))
        self.sock = MagicMock()
        self.socket_factory = self.stack.enter_context(patch.object(p.socket, 'socket', return_value=self.sock))
        self.context = MagicMock(); self.context.wrap_socket.return_value = self.sock
        self.stack.enter_context(patch.object(p.ssl, 'create_default_context', return_value=self.context))
        self.connection = MagicMock(); self.response = MagicMock()
        self.connection.getresponse.return_value = self.response
        self.stack.enter_context(patch.object(p.http.client, 'HTTPSConnection', return_value=self.connection))
        self.response.status = 200
        self.response.getheaders.return_value = [('Content-Type','application/json'),('Content-Length','2')]
        self.response.read.return_value = b'{}'

    def call(self):
        return p.FixedTransport()('token', body=b'dummy_credentials')

    def test_fixed_method_path_tls_and_budget(self):
        t=p.FixedTransport()
        self.assertEqual(t('token',body=b'dummy_credentials'),b'{}')
        
        for operation in tuple(p.OPERATIONS)[1:]:t(operation,token='dummy_token')
        self.assertEqual([(c.args[0],c.args[1]) for c in self.connection.request.call_args_list],list(p.OPERATIONS.values()))
        self.context.wrap_socket.assert_called_with(self.sock,server_hostname=p.HOST)
        with self.assertRaises(p.PreflightError):t('token',body=b'retry')
        self.assertEqual(self.connection.request.call_count,len(p.OPERATIONS))

    def test_identity_query_is_fixed_and_caller_body_rejected(self):
        t=p.FixedTransport();t('token',body=b'dummy_credentials');t('shop',token='dummy_token')
        t('identity',token='dummy_token')
        call=self.connection.request.call_args
        self.assertEqual(call.kwargs['body'],p.IDENTITY_BODY)
        self.assertTrue(json.loads(call.kwargs['body'])['query'].startswith('query '))
        self.assertNotIn('mutation',json.loads(call.kwargs['body'])['query'])
        other=p.FixedTransport();other('token',body=b'dummy_credentials');other('shop',token='dummy_token')
        count=self.connection.request.call_count
        with self.assertRaises(p.PreflightError):other('identity',token='dummy_token',body=b'mutation arbitrary')
        self.assertEqual(self.connection.request.call_count,count)

    def test_redirect_does_not_follow_or_retry(self):
        self.response.status=302
        self.response.getheaders.return_value=[('Location','https://evil.invalid/secret')]
        with self.assertRaises(p.PreflightError) as caught:self.call()
        self.assertNotIn('evil',str(caught.exception))
        self.assertEqual(self.connection.request.call_count,1)

    def test_http_status_mapping_is_static_and_ignores_private_body(self):
        for status,code in ((301,'redirect_refused'),(401,'http_unauthorized'),(403,'http_forbidden'),(429,'http_rate_limited'),(503,'http_server_error'),(418,'http_error')):
            self.response.status=status
            self.response.read.return_value=b'PRIVATE_SECRET https://evil.invalid'
            self.response.read.reset_mock()
            with self.assertRaises(p.PreflightError) as caught:self.call()
            self.assertEqual(caught.exception.code,code)
            self.assertEqual(caught.exception.stage,'token_exchange')
            self.response.read.assert_not_called()

    def test_any_private_dns_answer_rejects_before_socket(self):
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','::1'):
            self.addresses.return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',(ip,443))]
            with self.assertRaises(p.PreflightError):self.call()
        self.socket_factory.assert_not_called()

    def test_duplicate_and_ambiguous_framing_rejected(self):
        for tail in ([('Content-Length','2'),('content-length','2')],
                     [('Content-Length','2'),('Transfer-Encoding','chunked')],
                     [('Content-Encoding','gzip')], [('Transfer-Encoding','gzip')],
                     [('Content-Length','٢')]):
            self.response.getheaders.return_value=[('Content-Type','application/json')]+tail
            with self.subTest(headers=tail),self.assertRaises(p.PreflightError):self.call()

    def test_truncated_oversize_and_wrong_content_type_rejected(self):
        for raw in (b'{',b'x'*(p.LIMIT+1)):
            self.response.read.return_value=raw
            with self.assertRaises(p.PreflightError):self.call()
        self.response.read.return_value=b'{}';self.response.getheaders.return_value=[('Content-Type','text/html')]
        with self.assertRaises(p.PreflightError):self.call()

    def test_uncertain_request_consumes_attempt_and_redacts_exception(self):
        t=p.FixedTransport();self.connection.getresponse.side_effect=RuntimeError('dummy_secret upstream')
        with self.assertRaises(p.PreflightError) as caught:t('token',body=b'dummy_credentials')
        self.assertNotIn('dummy_secret',str(caught.exception));self.assertTrue(caught.exception.__suppress_context__)
        with self.assertRaises(p.PreflightError):t('token',body=b'dummy_credentials')
        self.assertEqual(self.connection.request.call_count,1)

    def test_close_exception_never_escapes_raw(self):
        self.connection.close.side_effect=RuntimeError('dummy_secret cleanup')
        try:self.call()
        except Exception as exc:
            self.assertIsInstance(exc,p.PreflightError)
            self.assertNotIn('dummy_secret',str(exc))

    def test_float_overflow_metadata_rejected(self):
        for raw in (b'{"unused":1e999}',b'{"unused":NaN}',b'{"unused":Infinity}'):
            with self.assertRaises(p.PreflightError):p.decode(raw)

class DiagnosticSafetyTests(unittest.TestCase):
    def cli(self, error):
        output=io.StringIO()
        with patch.object(p,'run',side_effect=error), contextlib.redirect_stdout(output):
            self.assertEqual(p.main(),1)
        text=output.getvalue()
        for secret in ('PRIVATE_SECRET','evil.invalid','Authorization','PRIVATE_BODY'):
            self.assertNotIn(secret,text)
        doc=json.loads(text)
        self.assertEqual(set(doc),{'status','error','stage','live_writer_authorized'})
        self.assertIn(doc['error'],p.SAFE_CODES);self.assertIn(doc['stage'],p.SAFE_STAGES)
        self.assertFalse(doc['live_writer_authorized'])
        return doc

    def test_cli_preserves_only_static_stage_and_error(self):
        result=self.cli(p.PreflightError('http_forbidden','token_exchange'))
        self.assertEqual(result['error'],'http_forbidden');self.assertEqual(result['stage'],'token_exchange')

    def test_nested_cause_notes_and_unknown_exception_are_redacted(self):
        error=RuntimeError('PRIVATE_SECRET https://evil.invalid Authorization PRIVATE_BODY')
        error.__cause__=ValueError('PRIVATE_SECRET');error.add_note('PRIVATE_BODY')
        result=self.cli(error)
        self.assertEqual(result['error'],'internal_error_redacted')
        safe=p.PreflightError('http_error','shop_identity')
        safe.__cause__=error;safe.add_note('PRIVATE_SECRET')
        self.assertEqual(self.cli(safe)['stage'],'shop_identity')

    def test_mutated_unknown_and_missing_attributes_fail_redacted(self):
        for mutation in ('unknown','missing_code','missing_stage','typed'):
            error=p.PreflightError('http_error','app_identity')
            if mutation=='unknown':error.code='PRIVATE_SECRET';error.stage='https://evil.invalid'
            elif mutation=='missing_code':del error.code
            elif mutation=='missing_stage':del error.stage
            else:error.code={'Authorization':'PRIVATE_SECRET'};error.stage=['PRIVATE_BODY']
            self.cli(error)

    def test_constructor_does_not_stringify_untrusted_fields(self):
        class Hostile:
            def __str__(self):raise AssertionError('untrusted stringify')
        result=self.cli(p.PreflightError(Hostile(),Hostile()))
        self.assertEqual(result['error'],'internal_error_redacted');self.assertEqual(result['stage'],'unknown')

    def test_finite_graphql_cost_metadata_accepted_not_authority(self):
        fixture=PreflightTests();fixture.setUp()
        fixture.responses[2]['extensions']={'cost':{'throttleStatus':{'restoreRate':50.0,'currentlyAvailable':999.5}}}
        result=p.run(ENV,transport=fixture.request)
        self.assertEqual(result['status'],'readonly_connection_verified')
        self.assertNotIn('extensions',result);self.assertFalse(result['live_writer_authorized'])
        self.assertEqual(p.decode(b'{"unused":1.5}')['unused'],1.5)

    def test_float_identity_and_expiry_still_rejected(self):
        for index,key,value in ((0,'expires_in',86399.0),(1,'id',float(p.SHOP_ID))):
            fixture=PreflightTests();fixture.setUp()
            if index==0:fixture.responses[index][key]=value
            else:fixture.responses[index]['shop'][key]=value
            with self.assertRaises(p.PreflightError):p.run(ENV,transport=fixture.request)
            self.assertEqual(len(fixture.calls),index+1)

    def test_each_operation_error_reports_stage_without_retry(self):
        for operation,stage in p.STAGES.items():
            fixture=PreflightTests();fixture.setUp();calls=[]
            def transport(op,**kwargs):
                calls.append(op)
                if op==operation:raise p.PreflightError('http_rate_limited','unknown')
                return fixture.request(op,**kwargs)
            with self.assertRaises(p.PreflightError) as caught:p.run(ENV,transport=transport)
            self.assertEqual(caught.exception.stage,stage)
            self.assertEqual(caught.exception.code,'http_rate_limited')
            self.assertEqual(calls,list(p.OPERATIONS)[:list(p.OPERATIONS).index(operation)+1])

if __name__ == '__main__': unittest.main()
