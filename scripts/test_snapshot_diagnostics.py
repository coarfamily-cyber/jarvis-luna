import unittest
from unittest.mock import Mock, patch
import repository_snapshot_reader as r
import repository_provenance as p

class Diagnostics(unittest.TestCase):
    def invoke(self, failure, suffix=''):
        opener=Mock(); opener.open.side_effect=failure
        with patch.object(r.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(p.ProvenanceError) as caught:
                r._get(p.DESTINATION[0],suffix,r.time.monotonic()+10,1024)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn('SECRET',str(caught.exception))
        return str(caught.exception)
    def test_http_status_stage_only(self):
        for suffix,stage in [('', 'repository'),('/git/commits/'+'a'*40,'commit'),('/git/trees/'+'b'*40+'?recursive=1','tree')]:
            err=r.urllib.error.HTTPError('SECRET_URL',403,'SECRET_BODY',{'SECRET':'SECRET'},None)
            self.assertEqual(self.invoke(err,suffix),f'snapshot_{stage}_http_403')
    def test_bad_status_does_not_echo(self):
        err=r.urllib.error.HTTPError('SECRET_URL','SECRET','SECRET_BODY',{},None)
        self.assertEqual(self.invoke(err),'snapshot_repository_http_0')
    def test_symbolic_validation_preserved(self):
        self.assertEqual(self.invoke(p.ProvenanceError('unsupported_content_encoding')),'unsupported_content_encoding')
    def test_generic_transport_redacted(self):
        for error in [r.urllib.error.URLError('SECRET'),r.http.client.BadStatusLine('SECRET'),ValueError('SECRET')]:
            self.assertEqual(self.invoke(error),'snapshot_read_unavailable')
    def test_runner_token_only_fixed_origin_no_redirect(self):
        import os
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':p.DESTINATION[0],
             'GITHUB_REPOSITORY_ID':str(p.DESTINATION[1]),'GITHUB_REPOSITORY_OWNER_ID':str(p.DESTINATION[2]),
             'GITHUB_TOKEN':'SECRET_TOKEN'}
        opener=Mock();opener.open.side_effect=r.urllib.error.HTTPError('SECRET_URL',302,'SECRET',{},None)
        with patch.dict(os.environ,env,clear=True),patch.object(r.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(p.ProvenanceError):r._get(p.LEGACY[0],'',r.time.monotonic()+10,1024)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,r.API+p.LEGACY[0]);self.assertEqual(request.get_header('Authorization'),'Bearer SECRET_TOKEN')
        self.assertIsNone(r._NoRedirect().redirect_request(request,None,302,'SECRET',{},'https://evil.example'))
    def test_anonymous_process_ignores_token(self):
        import os
        opener=Mock();opener.open.side_effect=ValueError('SECRET')
        with patch.dict(os.environ,{'GITHUB_TOKEN':'SECRET_TOKEN'},clear=True),patch.object(r.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(p.ProvenanceError):r._get(p.DESTINATION[0],'',r.time.monotonic()+10,1024)
        self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))
    def test_wrong_runner_or_endpoint_stops_before_transport(self):
        import os
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'wrong'},clear=True),patch.object(r.urllib.request,'build_opener',side_effect=AssertionError('network')):
            with self.assertRaises(p.ProvenanceError):r._get(p.DESTINATION[0],'',r.time.monotonic()+10,1024)
        with patch.object(r.urllib.request,'build_opener',side_effect=AssertionError('network')):
            for repo,suffix in [('evil/repo',''),(p.DESTINATION[0],'/../../secrets')]:
                with self.assertRaises(p.ProvenanceError):r._get(repo,suffix,r.time.monotonic()+10,1024)

if __name__=='__main__':unittest.main()
