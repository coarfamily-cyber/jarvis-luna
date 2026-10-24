"""Actual-checkout quarantine assertions, separate from legacy fixture tests."""
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import check_owned_workflow_policy as policy

ROOT=Path(__file__).resolve().parents[1]

class OwnedWorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for relative in policy.EXPECTED:
            dest=self.root/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/relative,dest)
    def test_actual_checkout(self):
        result=policy.verify(ROOT)
        self.assertEqual(result['active_schedules'], 0 if policy.STAGE == policy.MANUAL_STAGE else 1)
        self.assertEqual(len(result['active_manual_workflows']), 3 if policy.STAGE == policy.MANUAL_STAGE else 2)
        self.assertEqual(result['archived_workflows'],30)
        self.assertFalse(result['production_recovered'])
    def test_exact_v3_active_set(self):
        result=policy.verify(ROOT)
        self.assertEqual(result['stage'],policy.STAGE)
        self.assertEqual(result['active_workflows'],[
            '.github/workflows/owned-core-ledger-publisher.yml',
            '.github/workflows/owned-core-local.yml',
            '.github/workflows/owned-pages-once.yml',
            '.github/workflows/owned-repo-smoke.yml'])
    def test_new_core_bytes_mutation_rejected(self):
        path=self.root/'.github/workflows/owned-core-local.yml'
        path.write_bytes(path.read_bytes()+b'\n# changed\n')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_core_schedule_rejected(self):
        path=self.root/'.github/workflows/owned-core-local.yml'
        path.write_text(path.read_text().replace('  workflow_dispatch:', "  schedule:\n    - cron: '* * * * *'\n  workflow_dispatch:"))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_core_missing_rejected(self):
        (self.root/'.github/workflows/owned-core-local.yml').unlink()
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_publisher_push_event_rejected(self):
        path=self.root/'.github/workflows/owned-core-ledger-publisher.yml'
        path.write_text(path.read_text().replace('  workflow_run:', '  push:\n  workflow_run:'))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_publisher_root_write_permission_rejected(self):
        path=self.root/'.github/workflows/owned-core-ledger-publisher.yml'
        path.write_text(path.read_text().replace('permissions: {}', 'permissions:\n  contents: write'))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_publisher_extra_choice_rejected(self):
        path=self.root/'.github/workflows/owned-core-ledger-publisher.yml'
        path.write_text(path.read_text().replace('[publish, initialize]', '[publish, initialize, reset]'))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_producer_faster_schedule_rejected(self):
        path=self.root/'.github/workflows/owned-core-local.yml'
        path.write_text(path.read_text().replace("  schedule:\n    - cron: '17 * * * *'\n", '').replace('  workflow_dispatch:', "  workflow_dispatch:\n  schedule:\n    - cron: '* * * * *'"))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def producer_profile(self, hourly):
        path=self.root/'.github/workflows/owned-core-local.yml'
        text=path.read_text().replace("  schedule:\n    - cron: '17 * * * *'\n", '')
        if hourly:
            text=text.replace('  workflow_dispatch:\n', "  workflow_dispatch:\n  schedule:\n    - cron: '17 * * * *'\n")
        path.write_text(text)
    def test_named_manual_profile(self):
        self.producer_profile(False)
        with patch.object(policy, 'STAGE', policy.MANUAL_STAGE):
            self.assertEqual(policy.verify(self.root)['active_schedules'],0)
    def test_named_hourly_profile(self):
        self.producer_profile(True)
        with patch.object(policy, 'STAGE', policy.HOURLY_STAGE):
            self.assertEqual(policy.verify(self.root)['active_schedules'],1)
    def test_manual_stage_rejects_hourly_bytes(self):
        self.producer_profile(True)
        with patch.object(policy, 'STAGE', policy.MANUAL_STAGE):
            with self.assertRaises(ValueError):policy.verify(self.root)
    def test_hourly_stage_rejects_manual_bytes(self):
        self.producer_profile(False)
        with patch.object(policy, 'STAGE', policy.HOURLY_STAGE):
            with self.assertRaises(ValueError):policy.verify(self.root)
    def test_unknown_profile_rejected(self):
        with patch.object(policy, 'STAGE', 'unapproved'):
            with self.assertRaises(ValueError):policy.verify(self.root)
    def test_unchanged_fixture(self):
        self.assertEqual(policy.verify(self.root)['stage'],policy.STAGE)
    def test_legacy_activation_rejected(self):
        src=self.root/'.github/workflows-quarantined/20261023/JARVIS-Core-Automation.yml'
        shutil.copy2(src,self.root/'.github/workflows/JARVIS-Core-Automation.yml')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_manual_workflow_mutation_rejected(self):
        path=self.root/'.github/workflows/owned-pages-once.yml';path.write_bytes(path.read_bytes()+b'\n# changed\n')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_deleted_archive_rejected(self):
        (self.root/'.github/workflows-quarantined/20261023/JARVIS-Core-Automation.yml').unlink()
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_archive_mode_change_rejected(self):
        (self.root/'.github/workflows-quarantined/20261023/JARVIS-Core-Automation.yml').chmod(0o755)
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_archive_symlink_rejected(self):
        path=self.root/'.github/workflows-quarantined/20261023/JARVIS-Core-Automation.yml';path.unlink();path.symlink_to(ROOT/'.github/workflows-quarantined/20261023/JARVIS-Core-Automation.yml')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_extra_inactive_workflow_rejected(self):
        (self.root/'.github/workflows-quarantined/20261023/unapproved.yml').write_text('name: unexpected')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_disguised_extra_file_rejected(self):
        (self.root/'.github/workflows/extra.txt').write_text('not expected')
        with self.assertRaises(ValueError):policy.verify(self.root)

if __name__=='__main__':unittest.main(verbosity=2)
