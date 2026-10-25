"""Moving-clock receipts and durable crash boundaries; local fixtures only."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import jarvis_execution as ex

class ReceiptClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        p=self.root/'data/legal_team.json';p.parent.mkdir();p.write_text('{}')
        self.task={'id':'clock-proof','team':'legal','kind':'snapshot_report','payload':{}}
        self.tick=datetime(2026,10,25,tzinfo=timezone.utc)
        self.real_time=ex._time
    def clock(self,value=None):
        if value is not None:return self.real_time(value)
        self.tick+=timedelta(seconds=1)
        return self.tick
    def run_store(self,task=None):
        with patch.object(ex,'_time',self.clock):
            return ex.execute(self.root,task or self.task,ex.ExecutionStore(self.root))
    def test_moving_clock_snapshot_hash_and_durable_duplicate(self):
        r=self.run_store()
        self.assertEqual(r['status'],'VERIFIED')
        self.assertNotEqual(r['started_at'],r['ended_at'])
        self.assertEqual(r['evidence_hash'],ex.digest(r['outputs']))
        self.assertTrue(ex.validate_receipt(self.root,r))
        raw=(self.root/ex.ExecutionStore.filename).read_bytes()
        with patch.object(ex,'_snapshot',side_effect=AssertionError('redispatch')):
            self.assertEqual(self.run_store(),r)
        self.assertEqual((self.root/ex.ExecutionStore.filename).read_bytes(),raw)
    def test_moving_clock_read_snapshot_hash(self):
        r=self.run_store({**self.task,'kind':'read_snapshot'})
        self.assertEqual(r['status'],'VERIFIED')
        self.assertEqual(r['evidence_hash'],ex.digest(r['outputs']))
        self.assertTrue(ex.validate_receipt(self.root,r))
    def test_crash_after_report_replace_prevents_replay(self):
        class Crash(BaseException):pass
        original=ex._atomic
        def write_then_crash(root,path,value):
            result=original(root,path,value)
            if path!=ex.ExecutionStore.filename:raise Crash()
            return result
        with patch.object(ex,'_atomic',write_then_crash):
            with self.assertRaises(Crash):self.run_store()
        ledger=json.loads((self.root/ex.ExecutionStore.filename).read_text())
        self.assertEqual(ledger['claims']['clock-proof']['status'],'CLAIMED')
        report_files=list((self.root/'data/operations/reports').glob('[!.]*.json'))
        self.assertEqual(len(report_files),1);raw=report_files[0].read_bytes()
        with patch.object(ex,'_snapshot',side_effect=AssertionError('redispatch')):
            self.assertEqual(self.run_store()['status'],'RECONCILIATION_REQUIRED')
        self.assertEqual(report_files[0].read_bytes(),raw)
    def test_crash_after_receipt_replace_reloads_exact_receipt(self):
        class Crash(BaseException):pass
        original=ex._atomic
        def write_then_crash(root,path,value):
            result=original(root,path,value)
            if path==ex.ExecutionStore.filename and value['claims']['clock-proof']['status']=='VERIFIED':raise Crash()
            return result
        with patch.object(ex,'_atomic',write_then_crash):
            with self.assertRaises(Crash):self.run_store()
        ledger=json.loads((self.root/ex.ExecutionStore.filename).read_text());r=ledger['claims']['clock-proof']['receipt']
        self.assertEqual(r['evidence_hash'],ex.digest(r['outputs']))
        with patch.object(ex,'_snapshot',side_effect=AssertionError('redispatch')):
            self.assertEqual(self.run_store(),r)
if __name__=='__main__':unittest.main()
