"""Synthetic offline tree proofs, never authenticated production receipts."""
import copy
import hashlib
import inspect
import subprocess
import unittest
from unittest.mock import patch
import repository_provenance as p
import repository_snapshot_reader as r


def make_tree(rows):
    content=b''.join((mode.lstrip('0')+' ').encode()+name.encode()+b'\0'+bytes.fromhex(sha)
                     for name,mode,kind,sha in sorted(rows,key=lambda x:(x[0]+('/' if x[2]=='tree' else '')).encode()))
    return hashlib.sha1(b'tree '+str(len(content)).encode()+b'\0'+content).hexdigest(),content


def fixture():
    child,body=make_tree([('receipt','100644','blob','a'*40)])
    root,rootbody=make_tree([('data','040000','tree',child),('data.txt','100644','blob','b'*40)])
    value={'sha':root,'truncated':False,'tree':[
        {'path':'data','mode':'040000','type':'tree','sha':child},
        {'path':'data/receipt','mode':'100644','type':'blob','sha':'a'*40},
        {'path':'data.txt','mode':'100644','type':'blob','sha':'b'*40}]}
    return value,root,body,rootbody

class SnapshotReaderTests(unittest.TestCase):
    def setUp(self): self.value,self.root,self.body,self.rootbody=fixture()
    def verify(self): return r.verify_tree_payload(self.value,self.root)
    def test_valid_tree_proves_only_inventory(self):
        self.assertEqual(self.verify(),b'100644 blob '+b'a'*40+b'\tdata/receipt\0')
    def test_git_independent_hash_ordering(self):
        actual=subprocess.check_output(['git','hash-object','-t','tree','--stdin'],input=self.rootbody).decode().strip()
        self.assertEqual(self.root,actual)
    def test_tree_mutation(self):
        self.value['tree'][1]['sha']='b'*40
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_truncated_true_or_missing(self):
        for invalid in (True,None,0):
            self.value['truncated']=invalid
            with self.assertRaises(p.ProvenanceError):self.verify()
    def test_missing_leaf(self):
        self.value['tree'].pop(1)
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_extra_leaf(self):
        self.value['tree'].append({'path':'extra','mode':'100644','type':'blob','sha':'c'*40})
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_duplicate_path(self):
        self.value['tree'].append(copy.deepcopy(self.value['tree'][0]))
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_missing_parent(self):
        self.value['tree'][1]['path']='missing/receipt'
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_file_directory_collision(self):
        self.value['tree'][1]['path']='data.txt/receipt'
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_mode_type_mismatch(self):
        self.value['tree'][1]['type']='tree'
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_protected_symlink_is_rejected_even_with_valid_hash(self):
        sha,_=make_tree([('receipt','120000','blob','a'*40)])
        root,_=make_tree([('data','040000','tree',sha),('data.txt','100644','blob','b'*40)])
        self.value['tree'][0]['sha']=sha;self.value['tree'][1]['mode']='120000'
        self.value['sha']=self.root=root
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_nondata_symlink_has_correct_git_semantics(self):
        self.value['tree'][2]['mode']='120000'
        root,_=make_tree([('data','040000','tree',self.value['tree'][0]['sha']),('data.txt','120000','blob','b'*40)])
        self.value['sha']=self.root=root
        self.assertTrue(self.verify())
    def test_excessive_depth(self):
        self.value['tree'][1]['path']='x/'*65+'leaf'
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_wrong_root(self):
        self.value['sha']='f'*40
        with self.assertRaises(p.ProvenanceError):self.verify()
    def test_arbitrary_mapping_not_authenticated(self):
        with self.assertRaises(p.ProvenanceError):r.validate_authenticated_import(b'',{}, {}, expected_record_digest='a'*64)
    def test_direct_snapshot_construction_rejected(self):
        with self.assertRaises(p.ProvenanceError):r.AuthenticatedSnapshot(None,b'',0,object())
    def test_no_transport_injection_parameter(self):
        self.assertEqual(list(inspect.signature(r.read_snapshot).parameters),['role','commit','local_tree_proof'])
    def test_bad_role_or_branch_stops_before_network(self):
        with patch.object(r,'_get',side_effect=AssertionError('network must not run')):
            for role,commit in [('attacker','a'*40),('source','main'),('destination','A'*40)]:
                with self.assertRaises(p.ProvenanceError):r.read_snapshot(role,commit)
    def test_http_framing_exception_is_redacted_and_blocked(self):
        from unittest.mock import Mock
        opener=Mock()
        opener.open.side_effect=r.http.client.IncompleteRead(b'untrusted-body-fragment')
        # Exercise public HTTP framing, independent of the surrounding CI credentials.
        with patch.dict(r.os.environ, {'GITHUB_ACTIONS': 'false'}), \
             patch.object(r.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(p.ProvenanceError) as caught:
                r._get(p.DESTINATION[0],'',r.time.monotonic()+10,1024)
        self.assertEqual(str(caught.exception),'snapshot_read_unavailable')
        self.assertTrue(caught.exception.__suppress_context__)
    def test_remote_duplicate_and_nonfinite_json(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'\xff'):
            with self.assertRaises(p.ProvenanceError):r._json(raw)

if __name__=='__main__':unittest.main(verbosity=2)
