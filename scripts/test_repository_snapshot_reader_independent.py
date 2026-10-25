"""Independent offline negative transport tests; no live HTTP or trusted outputs."""
from email.message import Message
import io
import copy
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock
import repository_provenance as p
import repository_snapshot_reader as r

class Response:
    def __init__(self,body=b'{}',headers=(),status=200):
        self.body=io.BytesIO(body);self.status=status;self.headers=Message()
        for name,value in headers:self.headers[name]=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read1(self,n):return self.body.read(n)

class IndependentSnapshotReaderTests(unittest.TestCase):
    def setUp(self):
        # These fixtures test unauthenticated public transport, even on Actions.
        environment = patch.dict(r.os.environ, {'GITHUB_ACTIONS': 'false'})
        environment.start()
        self.addCleanup(environment.stop)

    def test_ci_identity_and_token_guards_precede_transport(self):
        identity = {'GITHUB_ACTIONS': 'true',
                    'GITHUB_REPOSITORY': p.DESTINATION[0],
                    'GITHUB_REPOSITORY_ID': str(p.DESTINATION[1]),
                    'GITHUB_REPOSITORY_OWNER_ID': str(p.DESTINATION[2])}
        cases = [({}, 'snapshot_runner_identity'),
                 (identity, 'snapshot_runner_token'),
                 ({**identity, 'GITHUB_TOKEN': 'bad token'}, 'snapshot_runner_token')]
        for values, reason in cases:
            with self.subTest(reason=reason), \
                 patch.dict(r.os.environ, {'GITHUB_ACTIONS': 'true', **values}, clear=True), \
                 patch.object(r.urllib.request, 'build_opener') as build:
                with self.assertRaisesRegex(p.ProvenanceError, '^' + reason + '$'):
                    r._get(p.DESTINATION[0], '', r.time.monotonic() + 10, 100)
                build.assert_not_called()

    def test_ci_bound_fixture_token_is_used_only_in_mocked_fixed_request(self):
        identity = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': p.DESTINATION[0],
                    'GITHUB_REPOSITORY_ID': str(p.DESTINATION[1]),
                    'GITHUB_REPOSITORY_OWNER_ID': str(p.DESTINATION[2]),
                    'GITHUB_TOKEN': 'synthetic-offline-fixture'}
        with patch.dict(r.os.environ, identity, clear=True):
            value, opener = self.get(Response())
        self.assertEqual(value, {})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-offline-fixture')
        self.assertEqual(request.full_url, 'https://api.github.com/repos/' + p.LEGACY[0])

    def get(self,response,cap=100,clock=0):
        opener=Mock();opener.open.return_value=response
        with patch.object(r.urllib.request,'build_opener',return_value=opener) as build,patch.object(r.time,'monotonic',return_value=clock):
            result=r._get(p.LEGACY[0],'',10,cap)
            build.assert_called_once()
            self.assertEqual(len(build.call_args.args),1)
            self.assertIsInstance(build.call_args.args[0],r._NoRedirect)
            self.assertEqual(build.call_args.kwargs,{})
        return result,opener
    def test_exact_framing_accepts_offline_fixture(self):
        value,_=self.get(Response(headers=[('Content-Length','2')]))
        self.assertEqual(value,{})
    def test_short_content_length_response_is_rejected(self):
        with self.assertRaises(p.ProvenanceError):self.get(Response(headers=[('Content-Length','3')]))
    def test_long_content_length_response_is_rejected(self):
        with self.assertRaises(p.ProvenanceError):self.get(Response(headers=[('Content-Length','1')]))
    def test_duplicate_length_is_rejected(self):
        with self.assertRaises(p.ProvenanceError):self.get(Response(headers=[('Content-Length','2'),('Content-Length','2')]))
    def test_length_with_transfer_encoding_is_rejected(self):
        with self.assertRaises(p.ProvenanceError):self.get(Response(headers=[('Content-Length','2'),('Transfer-Encoding','chunked')]))
    def test_nonidentity_content_encoding_rejected(self):
        with self.assertRaises(p.ProvenanceError):self.get(Response(headers=[('Content-Encoding','gzip')]))
    def test_declared_size_limit_before_read(self):
        response=Response(headers=[('Content-Length','101')]);response.read1=Mock(side_effect=AssertionError('read not allowed'))
        with self.assertRaises(p.ProvenanceError):self.get(response)
        response.read1.assert_not_called()
    def test_undeclared_body_cap_enforced(self):
        with self.assertRaises(p.ProvenanceError):self.get(Response(b' '*101))
    def test_non200_rejected(self):
        for status in (201,301,302,307,308,401,403,404):
            with self.subTest(status=status),self.assertRaises(p.ProvenanceError):self.get(Response(status=status))
    def test_expired_deadline_no_request(self):
        with patch.object(r.urllib.request,'build_opener',side_effect=AssertionError('no request')),patch.object(r.time,'monotonic',return_value=11):
            with self.assertRaises(p.ProvenanceError):r._get(p.LEGACY[0],'',10,100)
    def test_deadline_after_read_rejects_valid_json(self):
        opener=Mock();opener.open.return_value=Response()
        with patch.object(r.urllib.request,'build_opener',return_value=opener),patch.object(r.time,'monotonic',side_effect=[0,0,11]):
            with self.assertRaises(p.ProvenanceError):r._get(p.LEGACY[0],'',10,100)
    def test_request_has_no_auth_cookie_and_uses_fixed_endpoint(self):
        _,opener=self.get(Response())
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.github.com/repos/'+p.LEGACY[0])
        self.assertEqual(request.get_method(),'GET')
        self.assertFalse({'authorization','cookie','proxy-authorization'} & {k.lower() for k in request.headers})
        self.assertLessEqual(opener.open.call_args.kwargs['timeout'],20)
    def test_overflow_numbers_rejected(self):
        for raw in (b'{"x":1e999}',b'{"x":-1e999}',b'{"x":[1e999]}'):
            with self.subTest(raw=raw),self.assertRaises(p.ProvenanceError):r._json(raw)
    def test_wrong_repo_identity_stops_before_commit(self):
        metadata={'full_name':p.LEGACY[0],'id':p.DESTINATION[1],'owner':{'id':p.LEGACY[2]},'private':False}
        with patch.object(r,'_get',return_value=metadata) as get:
            with self.assertRaises(p.ProvenanceError):r.read_snapshot('source','a'*40)
            self.assertEqual(get.call_count,1)
    def test_private_repo_never_falls_back_to_credentials(self):
        metadata={'full_name':p.LEGACY[0],'id':p.LEGACY[1],'owner':{'id':p.LEGACY[2]},'private':True}
        with patch.object(r,'_get',return_value=metadata) as get:
            with self.assertRaises(p.ProvenanceError):r.read_snapshot('source','a'*40)
            self.assertEqual(get.call_count,1)
    def test_mismatched_commit_stops_before_tree(self):
        metadata={'full_name':p.LEGACY[0],'id':p.LEGACY[1],'owner':{'id':p.LEGACY[2]},'private':False}
        with patch.object(r,'_get',side_effect=[metadata,{'sha':'b'*40,'tree':{'sha':'c'*40}}]) as get:
            with self.assertRaises(p.ProvenanceError):r.read_snapshot('source','a'*40)
            self.assertEqual(get.call_count,2)

class IndependentGitTreeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        subprocess.run(['git','init','-q',self.temp.name],check=True)
    def git_tree(self,rows):
        raw=b''.join((mode+' '+kind+' '+oid+'\t'+name).encode()+b'\0' for name,mode,kind,oid in rows)
        return subprocess.check_output(['git','-C',self.temp.name,'mktree','-z','--missing'],input=raw).decode().strip()
    def fixture(self,protected_mode='100644',protected_kind='blob'):
        child=self.git_tree([('receipt',protected_mode,protected_kind,'a'*40)])
        nodes=[('é','100644','blob','b'*40),('data','040000','tree',child),
               ('data.txt','100644','blob','c'*40),('submodule','160000','commit','d'*40)]
        root=self.git_tree(nodes)
        rows=[{'path':name,'mode':mode,'type':kind,'sha':oid} for name,mode,kind,oid in nodes]
        rows.append({'path':'data/receipt','mode':protected_mode,'type':protected_kind,'sha':'a'*40})
        return {'sha':root,'truncated':False,'tree':rows},root
    def test_git_mktree_orders_unicode_directory_prefix_and_gitlink(self):
        value,root=self.fixture()
        self.assertEqual(r.verify_tree_payload(value,root),b'100644 blob '+b'a'*40+b'\tdata/receipt\0')
    def test_protected_gitlink_rejected_despite_real_git_hash(self):
        value,root=self.fixture('160000','commit')
        with self.assertRaises(p.ProvenanceError):r.verify_tree_payload(value,root)
    def test_missing_subtree_rows_rejected_against_real_git_hash(self):
        value,root=self.fixture();value['tree'].pop()
        with self.assertRaises(p.ProvenanceError):r.verify_tree_payload(value,root)
    def test_executable_mode_mutation_rejected_against_real_git_hash(self):
        value,root=self.fixture();value['tree'][-1]['mode']='100755'
        with self.assertRaises(p.ProvenanceError):r.verify_tree_payload(value,root)

class IndependentLocalProofTests(unittest.TestCase):
    setUp=IndependentGitTreeTests.setUp
    git_tree=IndependentGitTreeTests.git_tree
    fixture=IndependentGitTreeTests.fixture
    def metadata(self,root):
        return [{'full_name':p.LEGACY[0],'id':p.LEGACY[1],'owner':{'id':p.LEGACY[2]},'private':False},
                {'sha':'a'*40,'tree':{'sha':root}}]
    def read_proof(self,proof,root):
        with patch.object(r,'_get',side_effect=self.metadata(root)) as get:
            result=r.read_snapshot('source','a'*40,local_tree_proof=proof)
            self.assertEqual(get.call_count,2)
            self.assertEqual(get.call_args_list[1].args[1],'/git/commits/'+'a'*40)
            return result
    def test_local_data_proof_uses_two_fixed_reads(self):
        value,root=self.fixture()
        result=self.read_proof(json.dumps(value).encode(),root)
        self.assertEqual(result.snapshot.tree,root)
        self.assertEqual(result.data_tree_bytes,b'100644 blob '+b'a'*40+b'\tdata/receipt\0')
    def test_modified_leaf_wrong_root_truncated_and_missing_subtree_fail(self):
        value,root=self.fixture()
        variants=[]
        changed=copy.deepcopy(value);changed['tree'][-1]['sha']='f'*40;variants.append(changed)
        changed=copy.deepcopy(value);changed['sha']='f'*40;variants.append(changed)
        changed=copy.deepcopy(value);changed['truncated']=True;variants.append(changed)
        changed=copy.deepcopy(value);changed['tree'].pop();variants.append(changed)
        for proof in variants:
            with self.subTest(proof=proof),self.assertRaises(p.ProvenanceError):
                self.read_proof(json.dumps(proof).encode(),root)
    def test_proof_type_empty_and_size_caps(self):
        for proof in ({},b'',b' '*(r.LOCAL_PROOF_CAP+1)):
            with self.subTest(kind=type(proof),size=len(proof)),patch.object(r,'_get',side_effect=AssertionError('invalid proof must not spend GETs')) as get:
                with self.assertRaises(p.ProvenanceError):
                    r.read_snapshot('source','a'*40,local_tree_proof=proof)
                get.assert_not_called()
    def test_self_consistent_different_tree_cannot_override_https_anchor(self):
        value,root=self.fixture();different,_=self.fixture('100755','blob')
        with self.assertRaises(p.ProvenanceError):self.read_proof(json.dumps(different).encode(),root)
    def test_valid_local_proof_never_bypasses_repository_identity(self):
        value,root=self.fixture();metadata=self.metadata(root);metadata[0]['id']=p.DESTINATION[1]
        with patch.object(r,'_get',side_effect=metadata) as get:
            with self.assertRaises(p.ProvenanceError):
                r.read_snapshot('source','a'*40,local_tree_proof=json.dumps(value).encode())
            self.assertEqual(get.call_count,1)

if __name__=='__main__':unittest.main()
