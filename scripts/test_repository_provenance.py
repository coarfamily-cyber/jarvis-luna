"""Offline synthetic schema tests; hashes/commits are not live approval evidence."""
import copy
import hashlib
import unittest
import repository_provenance as p


def fixture():
    def snapshot(identity, commit, tree):
        return {'repository': dict(zip(('full_name','repository_id','owner_id'),identity)), 'commit':commit*40,'tree':tree*40}
    inventory=[{'path':'data/receipt.json','blob':'a'*40,'mode':'100644'},
               {'path':'data/stops.json','blob':'b'*40,'mode':'100755'}]
    return dict(schema=p.SCHEMA,purpose='historical_import_only',protected_prefix='data/',
                source=snapshot(p.LEGACY,'c','d'),destination=snapshot(p.DESTINATION,'e','f'),
                inventory=inventory,inventory_digest=p.digest(inventory),approved_additions=[],
                **{key:'a'*64 for key in ('predecessor_digest','unresolved_digest','old_contract_digest',
                   'new_contract_digest','transition_policy_digest','authorization_reference_digest')})


def tree(entries):
    return b''.join((e['mode']+' blob '+e['blob']+'\t'+e['path']).encode()+b'\0' for e in entries)

class RepositoryProvenanceTests(unittest.TestCase):
    def setUp(self): self.value=fixture()
    def parse(self): return p.parse_record(p.canonical(self.value))
    def validate(self, source=None, destination=None, raw=None, **kwargs):
        raw=p.canonical(self.value) if raw is None else raw
        record=self.parse()
        return p.validate_preservation(raw,tree(self.value['inventory']) if source is None else source,
            tree(self.value['inventory']+self.value['approved_additions']) if destination is None else destination,
            expected_record_digest=kwargs.get('expected_record_digest',hashlib.sha256(raw).hexdigest()),
            source_snapshot=kwargs.get('source_snapshot',record.source),
            destination_snapshot=kwargs.get('destination_snapshot',record.destination))
    def test_valid_import_is_not_authority(self):
        result=self.validate()
        self.assertEqual(result.source_files,2)
        self.assertEqual(result.scope,'local_consistency_only')
        self.assertFalse(result.authenticated_migration or result.destination_current_evidence or result.production_recovered)
    def test_exact_approved_addition(self):
        self.value['approved_additions']=[{'path':'data/migration_provenance/evidence.json','blob':'c'*40,'mode':'100644'}]
        self.assertEqual(self.validate().additive_files,1)
    def test_source_identity_axes(self):
        for field,value in [('full_name',p.DESTINATION[0]),('repository_id',p.DESTINATION[1]),('owner_id',p.DESTINATION[2]),('repository_id',True)]:
            with self.subTest(field=field,value=value):
                self.value=fixture();self.value['source']['repository'][field]=value
                with self.assertRaises(p.ProvenanceError): self.parse()
    def test_destination_identity_axes(self):
        for field,value in [('full_name',p.LEGACY[0]),('repository_id',p.LEGACY[1]),('owner_id',p.LEGACY[2])]:
            with self.subTest(field=field):
                self.value=fixture();self.value['destination']['repository'][field]=value
                with self.assertRaises(p.ProvenanceError): self.parse()
    def test_current_evidence_purpose_rejected(self):
        self.value['purpose']='destination_current'
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_unknown_schema_rejected(self):
        self.value['schema']='jarvis-historical-import-v2'
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_extra_field_rejected(self):
        self.value['approved']=True
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_missing_field_rejected(self):
        del self.value['unresolved_digest']
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_narrowed_scope_rejected(self):
        self.value['protected_prefix']='data/safe_subset/'
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_inventory_scope_rejected(self):
        self.value['inventory'][0]['path']='scripts/test.py'
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_addition_outside_migration_rejected(self):
        self.value['approved_additions']=[{'path':'data/new_receipt.json','blob':'c'*40,'mode':'100644'}]
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_unapproved_addition_rejected(self):
        destination=tree(self.value['inventory'])+b'100644 blob '+b'a'*40+b'\tdata/extra.json\0'
        with self.assertRaises(p.ProvenanceError): self.validate(destination=destination)
    def test_missing_history_rejected(self):
        with self.assertRaises(p.ProvenanceError): self.validate(destination=tree(self.value['inventory'][:1]))
    def test_content_mutation_rejected(self):
        values=copy.deepcopy(self.value['inventory']);values[0]['blob']='f'*40
        with self.assertRaises(p.ProvenanceError): self.validate(destination=tree(values))
    def test_mode_mutation_rejected(self):
        values=copy.deepcopy(self.value['inventory']);values[0]['mode']='100755'
        with self.assertRaises(p.ProvenanceError): self.validate(destination=tree(values))
    def test_source_inventory_must_match(self):
        with self.assertRaises(p.ProvenanceError): self.validate(source=b'')
    def test_record_digest_pin(self):
        with self.assertRaises(p.ProvenanceError): self.validate(expected_record_digest='f'*64)
    def test_snapshot_pin(self):
        record=self.parse()
        with self.assertRaises(p.ProvenanceError): self.validate(source_snapshot=record.destination)
    def test_inventory_digest(self):
        self.value['inventory_digest']='f'*64
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_duplicate_inventory(self):
        self.value['inventory'].append(self.value['inventory'][0])
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_unsorted_inventory(self):
        self.value['inventory'].reverse()
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_empty_inventory(self):
        self.value['inventory']=[]
        with self.assertRaises(p.ProvenanceError): self.parse()
    def test_unsafe_paths(self):
        for path in ('/data/a','data/../a','data//a','data/./a','data/\\a','data/a\n','data/a\x00'):
            with self.subTest(path=path):
                self.value=fixture();self.value['inventory'][0]['path']=path
                with self.assertRaises(p.ProvenanceError): self.parse()
    def test_invalid_modes(self):
        for mode in ('120000','160000','040000','100600',100644):
            with self.subTest(mode=mode):
                self.value=fixture();self.value['inventory'][0]['mode']=mode
                with self.assertRaises(p.ProvenanceError): self.parse()
    def test_hash_types(self):
        for invalid in ('A'*64,'a'*63,True,None,1,[]):
            with self.subTest(invalid=invalid):
                self.value=fixture();self.value['unresolved_digest']=invalid
                with self.assertRaises(p.ProvenanceError): self.parse()
    def test_duplicate_json_key(self):
        with self.assertRaises(p.ProvenanceError): p.parse_record(b'{"schema":1,"schema":2}\n')
    def test_noncanonical_json(self):
        with self.assertRaises(p.ProvenanceError): p.parse_record(p.canonical(self.value).strip())
    def test_nonfinite_json(self):
        with self.assertRaises(p.ProvenanceError): p.parse_record(b'{"schema":NaN}\n')
    def test_json_limits(self):
        for raw in ('not bytes', b'', b' '* (p.MAX_JSON_BYTES+1), b'\xff'):
            with self.assertRaises(p.ProvenanceError): p.parse_record(raw)
    def test_tree_truncation(self):
        with self.assertRaises(p.ProvenanceError): p.parse_tree(tree(self.value['inventory'])[:-1])
    def test_tree_types_and_capacity(self):
        for raw in ('bad',b' '* (p.MAX_TREE_BYTES+1)):
            with self.assertRaises(p.ProvenanceError): p.parse_tree(raw)
    def test_tree_duplicate(self):
        raw=tree(self.value['inventory'])
        with self.assertRaises(p.ProvenanceError): p.parse_tree(raw+raw)
    def test_tree_nonblob(self):
        with self.assertRaises(p.ProvenanceError): p.parse_tree(b'160000 commit '+b'a'*40+b'\tdata/a\0')
    def test_frozen_result(self):
        with self.assertRaises(AttributeError): self.parse().source.commit='x'

if __name__=='__main__': unittest.main(verbosity=2)
