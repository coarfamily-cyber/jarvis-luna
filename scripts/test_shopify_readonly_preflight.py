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
        for raw in (b'{"unused":1e999}',b'{"unused":1.5}'):
            with self.assertRaises(p.PreflightError):p.decode(raw)

if __name__ == '__main__': unittest.main()
