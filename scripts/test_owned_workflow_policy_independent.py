"""Independent actual-policy negative cases; temp fixtures never activate Actions."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import check_owned_workflow_policy as policy

ROOT=Path(__file__).resolve().parents[1]

class IndependentOwnedWorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in policy.EXPECTED:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,path)
    def test_fifo_cannot_disappear_from_inventory(self):
        os.mkfifo(self.root/'.github/workflows/unapproved.fifo')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_nested_workflow_not_ignored(self):
        path=self.root/'.github/workflows/nested/unapproved.yaml';path.parent.mkdir()
        path.write_text('on:\n  workflow_dispatch:\njobs: {}\n')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_disabled_file_bytes_are_still_immutable(self):
        path=self.root/'.github/workflows/auto-update.yml.disabled'
        path.write_bytes(path.read_bytes()+b'\n# mutation\n')
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_disabled_workflow_renamed_active_rejected(self):
        path=self.root/'.github/workflows/auto-update.yml.disabled'
        path.rename(path.with_suffix(''))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_active_workflow_mode_only_change_rejected(self):
        path=self.root/'.github/workflows/owned-repo-smoke.yml';path.chmod(0o755)
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_oversized_archive_rejected(self):
        path=self.root/'.github/workflows-quarantined/20261023/preflight.yml'
        path.write_bytes(b' ' * 262145)
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_active_directory_symlink_rejected(self):
        path=self.root/'.github/workflows';target=self.root/'.github/moved-workflows'
        path.rename(target);path.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_unreviewed_extra_smoke_schedule_rejected(self):
        path=self.root/'.github/workflows/owned-repo-smoke.yml'
        path.write_text(path.read_text().replace('  workflow_dispatch:',"  schedule:\n    - cron: '* * * * *'\n  workflow_dispatch:"))
        with self.assertRaises(ValueError):policy.verify(self.root)

if __name__=='__main__':unittest.main()
