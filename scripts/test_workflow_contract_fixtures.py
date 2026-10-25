"""An archived contract pass cannot silently reenable a legacy workflow."""
from pathlib import Path
import tempfile
import unittest
from workflow_contract_fixtures import ROOT, QUARANTINE, archived_workflow

class ArchiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / QUARANTINE / 'latest-code-revalidation.yml'
        self.archive.parent.mkdir(parents=True); self.archive.write_bytes((ROOT / QUARANTINE / 'latest-code-revalidation.yml').read_bytes())
        self.active = self.root / '.github/workflows/latest-code-revalidation.yml'
        self.active.parent.mkdir(parents=True)

    def test_retains_all_thirty_archives_and_no_active_counterparts(self):
        names = {p.name for p in (ROOT / QUARANTINE).glob('*.yml')}
        self.assertEqual(len(names), 30)
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(archived_workflow(name), ROOT / QUARANTINE / name)

    def test_reads_exact_archive(self):
        self.assertEqual(archived_workflow('latest-code-revalidation.yml', root=self.root).read_bytes(), self.archive.read_bytes())

    def test_reactivation_fails_even_with_valid_archive(self):
        self.active.write_text('enabled')
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

    def test_missing_archive_fails_without_skip_or_fallback(self):
        self.archive.unlink()
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

    def test_traversal_and_non_yaml_rejected(self):
        for name in ('../example.yml', '/example.yml', 'example.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                archived_workflow(name, root=self.root)

    def test_symlink_archive_rejected(self):
        self.archive.unlink(); self.archive.symlink_to(self.root/'missing.yml')
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

    def test_dangling_active_symlink_rejected(self):
        self.active.symlink_to(self.root/'missing.yml')
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

    def test_changed_archive_bytes_fail(self):
        self.archive.write_text('different archived text')
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

    def test_unknown_archive_fails(self):
        (self.archive.parent / 'unreviewed.yml').write_text('fake')
        with self.assertRaises(AssertionError): archived_workflow('unreviewed.yml', root=self.root)

    def test_executable_archive_rejected(self):
        self.archive.chmod(0o755)
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

    def test_parent_symlink_escape_rejected(self):
        import shutil
        outside = self.root / 'outside'
        outside.mkdir()
        shutil.copyfile(self.archive, outside / self.archive.name)
        shutil.rmtree(self.archive.parent)
        self.archive.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(AssertionError): archived_workflow('latest-code-revalidation.yml', root=self.root)

if __name__ == '__main__': unittest.main()
