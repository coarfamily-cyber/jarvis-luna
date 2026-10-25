import base64,copy,json,pathlib,tempfile,unittest
from unittest.mock import patch
import secretary_technical_review as c, technical_review_binding as b
import jarvis_operations as core,jarvis_execution as ex,run_jarvis_operations as runner
# Exact sanitized public artifact ZIP, API digest independently verified; no private source.
PROOF=base64.b64decode('UEsDBBQACAAIAHoCWV0AAAAAAAAAAAAAAAALAAAAcmVzdWx0Lmpzb27NVtuO3DYMfe9XDPw8A+hC3fZXisCgSGrHjceeyvLsLoL8e2HP7iZoEKC3IH0TqMMjUoek9KmTZ6G1DfPU49rOcx3aS/dw6KZ5ku546OS5SZ1w7C9rww22dA8HdTx0ZXhua5V+OaNxfnORHECjxcTeQNQhKVMk2Bg0aO0FYgAgA4ZS8S4WkuQ4SopWI2kj+3HDRAPL1LZTfv3UIX2c5qdR+PEiU+seDtM6jsdDRzNLT/PlMmzGzmKI3qtQUAuwDaIsRcXOUXEebQ7acogWuzfXpWGTzfPO0YT3XGuda78Btq0rPspyeprrxzLOT6dhusnU5vqyI29blCT9GZez7MF2OasUtWNtPHsWYzxTML4UjUXn6KwvYJ1LmMARkwqaU8paxYIhKU8bLzvGAjpla7WyJjJgDg7Eg4hBVuCBbE7ZG5cjQQTIOqEu1ltvULD7cDx089Mkta/zuKexTrgsw+N0T/Fa5+u8CPdVboM87ag9/M3xzSa/r0MV7h4Ora5yPHSLTK3Hr+6/CV56pL1sqpAM17fNz8fDX5ctQeIsxQcJpJANARNb1iTGisteGR0glL8l262dlnmtJKcnydfviRUMIpWMloWkRAQyGqwkKU6Vor22DJEIXTBBm6ygQGAbSCkEF2EPKaVSElqlADbpTSYNQpC1jwEDJ1AlMIAz2VGCjdJIROOsTlopS/9crG7PcJgeu58i24/otvJ8asNFloaX62mhs1zwe9qRCjl60VGbnKzhAsSZ2SfIhYtPvkRvJXhO0QcIUlRyKehsjLbkQtx4/4tmNS5kjxFI+4LJeGeLZadU5CxQnGdnN0cJJiVtwJYMKDk4jYl8MfFf6H+tw8+S/2vju7DjTDj2hBMPvJm+kZfmKie5XNvL6bc5ny7SkLF9V2ILxUQBY0VbdgkshhTA6pxzgpANu+AdFCJdIirPxFpbQHLJOys6bLwKsBDkkkRFFPQQOIAoFqZErHxWzhitOYumYkUMKAPZozFOAxm1cVhnEnDyKaQIsXjlTfQlaU6QchKtnLE+FyWJks5k2WvyirLxSnHM/4d5/GF/Va9r60uV5TzJsvF3C96E+2XC63KeWz9P40v3jvzyppfIFkoR0soHk0xEUAFjiUY5sViCQgkuBWMlg4BxpVD2QYuNCUHp1xx5JbkXw8a9EUernBNlPGRQ2tjsreMcNQAEZgspehsi7EpWKVL3Eml1XfYZdK+VfppbP0wsV5m2X8O23879XPv9Ql5vYtk5vp2de7pLG9p6/9ccD90F60dp22oclvYKemu2zSqPON7p8twG2p1YNj33aXfGaZJxt7710t4MjxWv570Y7qOtv0ldhnnqHg56MzZs6y7LBacVx/dqkOtcW09V8HVo7nmxjMNN6svGMpRhr4yC4yJvgC9/uj8jPv/yB1BLBwgqY7nvIgQAAPIJAABQSwECLQMUAAgACAB6AlldKmO57yIEAADyCQAACwAAAAAAAAAAACAAgIEAAAAAcmVzdWx0Lmpzb25QSwUGAAAAAAEAAQA5AAAAWwQAAAAA')
class SecretaryReviewTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=pathlib.Path(self.t.name)
  for p,d in [('data/operations/state.json',core.empty_state()),(ex.ExecutionStore.filename,{'claims':{}}),('data/product_team.json',{}),('data/pricing_model.json',{})]:
   q=self.root/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(json.dumps(d))
  q=self.root/b.PATH;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(PROOF)
 def test_secretary_lifecycle_duplicate_and_old_goal(self):
  s=runner.read(self.root,runner.STATE);old=core.create_task(s,goal='old goal',team='listing');runner.atomic(self.root,runner.STATE,s)
  with patch('socket.create_connection',side_effect=AssertionError('network')):
   first=c.run(self.root);second=c.run(self.root)
  self.assertEqual(first['task_states'],['COMPLETED','COMPLETED']);self.assertEqual(first['new_claims'],2);self.assertEqual(second['new_claims'],0)
  self.assertEqual(first['handoff_status'],'ACCEPTED');self.assertFalse(first['engineering_fix_completed'])
  s=runner.read(self.root,runner.STATE);self.assertEqual(s['tasks'][old['task_id']],old);runner.validate_state(self.root,s)
 def test_wrong_actor(self):
  with self.assertRaises(ValueError):c.run(self.root,actor='pricing')
 def test_missing_checkpoint_no_reset(self):
  (self.root/runner.STATE).unlink()
  with self.assertRaises(ValueError):c.run(self.root)
  self.assertFalse((self.root/runner.STATE).exists())
 def test_artifact_tamper_and_out_of_order(self):
  q=self.root/b.PATH;raw=q.read_bytes();q.write_bytes(raw+b'x')
  with self.assertRaises(ValueError):c.run(self.root)
  q.write_bytes(raw)
  a={'team':'sourcing','payload':c.payload('vt-source-webp')};a['payload']['technical_run_id']=b.RUN_ID-1
  with self.assertRaises(ValueError):b.evidence(self.root,a)
 def test_wrong_role_and_unsupported_code(self):
  a={'team':'pricing','payload':c.payload('vt-source-webp')}
  with self.assertRaises(ValueError):b.evidence(self.root,a)
  a['payload']['technical_error_code']='core-empty-job-metadata'
  with self.assertRaises(ValueError):b.evidence(self.root,a)
 def test_handoff_replay_and_receipt_tamper(self):
  r=c.run(self.root);s=runner.read(self.root,runner.STATE);h=next(iter(s['handoffs']))
  with self.assertRaises(ValueError):core.accept_handoff(s,h,actor='secretary')
  task=s['tasks'][r['task_ids'][0]];receipt=s['receipts'][task['receipt_id']];p=self.root/receipt['outputs'][0]['path'];d=json.loads(p.read_text());d['technical_review_evidence']['engineering_fix_completed']=True;p.write_text(json.dumps(d))
  self.assertFalse(ex.validate_receipt(self.root,receipt))
  with self.assertRaises(ValueError):c.run(self.root)
 def test_interrupted_task_no_replay(self):
  s=runner.read(self.root,runner.STATE);t=core.create_task(s,goal=c.GOAL,team='sourcing',kind='snapshot_report',payload=c.payload('vt-source-webp'),evidence={'artifact_sha256':b.ZIP_SHA,'scope':'local_technical_snapshot_review_not_repair'})
  core.transition(s,t['task_id'],'ROUTED');runner.atomic(self.root,runner.STATE,s)
  with self.assertRaises(ValueError):c.run(self.root)
  self.assertEqual(len(runner.read(self.root,ex.ExecutionStore.filename)['claims']),0)
if __name__=='__main__':unittest.main()
