"""Independent adversarial checks; synthetic pins are not migration authority."""
import copy
import hashlib
import unittest
from dataclasses import asdict
import repository_provenance as p

class IndependentProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.source = p.Snapshot(p.Repository(*p.LEGACY), 'a'*40, 'b'*40)
        self.destination = p.Snapshot(p.Repository(*p.DESTINATION), 'c'*40, 'd'*40)
        self.entry = {'path':'data/history.json','blob':'e'*40,'mode':'100644'}
        self.value = {'schema':p.SCHEMA,'purpose':'historical_import_only','protected_prefix':'data/',
            'source':asdict(self.source),'destination':asdict(self.destination),'inventory':[self.entry],
            'inventory_digest':p.inventory_digest(p._entries([self.entry])), 'approved_additions':[]}
        for k in ('predecessor_digest','unresolved_digest','old_contract_digest','new_contract_digest',
                  'transition_policy_digest','authorization_reference_digest'):
            self.value[k]='f'*64
    def tree(self, entries):
        return b''.join((e['mode']+' blob '+e['blob']+'\t'+e['path']).encode()+b'\0' for e in entries)
    def validate(self, value=None, source=None, destination=None, **pins):
        raw=p.canonical(self.value if value is None else value)
        args={'expected_record_digest':hashlib.sha256(raw).hexdigest(),
              'source_snapshot':self.source,'destination_snapshot':self.destination}
        args.update(pins)
        return p.validate_preservation(raw,self.tree([self.entry]) if source is None else source,
                                      self.tree([self.entry]) if destination is None else destination,**args)
    def test_valid_fixture_never_grants_authority(self):
        report=self.validate()
        self.assertEqual(report.scope,'local_consistency_only')
        self.assertFalse(report.authenticated_migration or report.destination_current_evidence or report.production_recovered)
    def test_independent_record_pin_rejects_even_self_consistent_change(self):
        with self.assertRaises(p.ProvenanceError): self.validate(expected_record_digest='0'*64)
    def test_snapshot_pin_not_taken_from_record(self):
        other=p.Snapshot(self.source.repository,'0'*40,self.source.tree)
        with self.assertRaises(p.ProvenanceError): self.validate(source_snapshot=other)
    def test_repository_axes_not_relabelled(self):
        for side in ('source','destination'):
            for key in ('full_name','repository_id','owner_id'):
                value=copy.deepcopy(self.value)
                value[side]['repository'][key]='attacker/repo' if key=='full_name' else 1
                with self.subTest(side=side,key=key),self.assertRaises(p.ProvenanceError): self.validate(value)
    def test_boolean_repository_id_rejected(self):
        value=copy.deepcopy(self.value);value['source']['repository']['repository_id']=True
        with self.assertRaises(p.ProvenanceError): self.validate(value)
    def test_current_evidence_purpose_rejected(self):
        value=copy.deepcopy(self.value);value['purpose']='destination_current'
        with self.assertRaises(p.ProvenanceError): self.validate(value)
    def test_scope_cannot_be_narrowed(self):
        value=copy.deepcopy(self.value);value['protected_prefix']='data/history/'
        with self.assertRaises(p.ProvenanceError): self.validate(value)
    def test_unknown_authority_flag_rejected(self):
        value=copy.deepcopy(self.value);value['approved']=True
        with self.assertRaises(p.ProvenanceError): self.validate(value)
    def test_approved_addition_binds_blob_and_mode_not_just_path(self):
        addition={'path':'data/migration_provenance/fixture.json','blob':'1'*40,'mode':'100644'}
        value=copy.deepcopy(self.value);value['approved_additions']=[addition]
        for key, replacement in [('blob','2'*40),('mode','100755')]:
            changed=dict(addition,**{key:replacement})
            with self.subTest(key=key),self.assertRaises(p.ProvenanceError):
                self.validate(value,destination=self.tree([self.entry,changed]))
    def test_declared_addition_must_be_present(self):
        value=copy.deepcopy(self.value)
        value['approved_additions']=[{'path':'data/migration_provenance/x','blob':'1'*40,'mode':'100644'}]
        with self.assertRaises(p.ProvenanceError): self.validate(value)
    def test_undeclared_extra_and_source_omission_rejected(self):
        extra={'path':'data/new.json','blob':'1'*40,'mode':'100644'}
        for source,dest in [(b'',self.tree([self.entry])),(self.tree([self.entry]),self.tree([self.entry,extra]))]:
            with self.subTest(source=source,dest=dest),self.assertRaises(p.ProvenanceError):
                self.validate(source=source,destination=dest)
    def test_duplicate_tree_entries_rejected(self):
        with self.assertRaises(p.ProvenanceError): self.validate(source=self.tree([self.entry,self.entry]))
    def test_unsafe_paths_and_special_modes_rejected(self):
        for path in ('data/../escape','/data/x','data//x','data/./x','data/x\\y','data/x\ny'):
            with self.subTest(path=path),self.assertRaises(p.ProvenanceError):
                p.parse_tree(self.tree([dict(self.entry,path=path)]))
        for mode in ('120000','160000','040000','100664'):
            with self.subTest(mode=mode),self.assertRaises(p.ProvenanceError):
                p.parse_tree(self.tree([dict(self.entry,mode=mode)]))
    def test_truncated_invalid_utf8_and_wrong_kind_rejected(self):
        tree=self.tree([self.entry])
        for raw in (tree[:-1],tree.replace(b'data/history',b'data/\xff'),tree.replace(b' blob ',b' commit ')):
            with self.subTest(raw=raw),self.assertRaises(p.ProvenanceError): p.parse_tree(raw)
    def test_noncanonical_duplicate_and_nonfinite_json_rejected(self):
        raw=p.canonical(self.value)
        for bad in (b' '+raw,raw.replace(b'{',b'{"purpose":"x",',1),b'{"x":NaN}\n',b'{"x":1e999}\n'):
            with self.subTest(bad=bad),self.assertRaises(p.ProvenanceError): p.parse_record(bad)
    def test_limits_reject_before_acceptance(self):
        for raw in (b'x'*(p.MAX_JSON_BYTES+1),b''):
            with self.subTest(size=len(raw)),self.assertRaises(p.ProvenanceError): p.parse_record(raw)
        with self.assertRaises(p.ProvenanceError): p.parse_tree(b'x'*(p.MAX_TREE_BYTES+1))

if __name__=='__main__': unittest.main()
