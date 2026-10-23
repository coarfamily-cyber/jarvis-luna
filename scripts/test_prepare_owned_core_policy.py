from pathlib import Path
import tempfile
import unittest
import destination_core_epoch as e
import owned_core_local as runner
import prepare_owned_core_policy as prep

class PreparationTests(unittest.TestCase):
    def test_real_reviewed_record_fixture_policy(self):
        base=Path(__file__).resolve().parents[1]/'reviewed-inputs'
        record=(base/'historical-import-record-v1.json').read_bytes()
        history=(base/'historical-import-policy-v1.json').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            # Unit fixture ID777 is NOT a deployable real GitHub workflow identity.
            for path in runner.CODE_FILES:
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'fixture\n')
            policy=prep.prepare(root,record,history,777)
            self.assertEqual(policy['import_record_digest'],prep.RECORD_PIN)
            self.assertEqual(policy['legacy_inventory_digest'],'3529977fd31c95381cf87c85664b368bd6a7c5a53b50247a4dc0a903fd2d4c1f')
            self.assertEqual(policy['holds'],e.HOLDS)
            with self.assertRaises(e.Blocked):prep.prepare(root,record,history,777)
    def test_record_pin_not_self_authorized(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(e.Blocked):prep.prepare(Path(folder),b'{}',b'{}',777)
    def test_workflow_id_required(self):
        with self.assertRaises(e.Blocked):prep.prepare(Path('/tmp'),b'',b'',True)

if __name__=='__main__':unittest.main()
