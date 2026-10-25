"""Actual-checkout quarantine assertions, separate from legacy fixture tests."""
import ast
import hashlib
import yaml
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
        self.assertEqual(result['active_schedules'], 2 if policy.STAGE == policy.MANUAL_STAGE else 3)
        self.assertEqual(len(result['active_manual_workflows']), 7 if policy.STAGE == policy.MANUAL_STAGE else 6)
        self.assertEqual(result['archived_workflows'],30)
        self.assertFalse(result['production_recovered'])
    def test_smoke_daily_stage_and_exact_readonly_execution(self):
        result = policy.verify(ROOT)
        self.assertEqual(result['smoke_stage'], 'owned-repository-offline-smoke-daily-v1')
        self.assertNotIn('.github/workflows/owned-repo-smoke.yml', result['active_manual_workflows'])
        text = (ROOT / '.github/workflows/owned-repo-smoke.yml').read_text()
        doc = yaml.safe_load(text)
        self.assertEqual(doc.get('on', doc.get(True)), {
            'workflow_dispatch': None, 'schedule': [{'cron': '53 3 * * *'}]})
        self.assertEqual(doc['permissions'], {'contents': 'read'})
        self.assertEqual(set(doc['jobs']), {'offline-smoke'})
        job = doc['jobs']['offline-smoke']
        self.assertEqual(job['timeout-minutes'], 10)
        self.assertEqual(job['if'], "github.repository == 'coarfamily-cyber/jarvis-luna' && github.ref == 'refs/heads/main'")
        self.assertNotIn('environment', job)
        self.assertFalse(job['steps'][0]['with']['persist-credentials'])
        self.assertIn('--require-hashes --only-binary=:all:', job['steps'][2]['run'])
        self.assertIn('socket.create_connection = deny', job['steps'][4]['run'])
        self.assertEqual(job['steps'][4]['run'].count("'test_"), 9)
        for forbidden in ('secrets.', 'contents: write', 'actions: write', 'upload-artifact',
                          'run_jarvis_operations.py', 'run_jarvis_agents.py'):
            self.assertNotIn(forbidden, text)

    def test_smoke_exact_semantics_even_if_mutated_bytes_registered(self):
        path = self.root / '.github/workflows/owned-repo-smoke.yml'
        original = path.read_text()
        for old, new in [("53 3 * * *", "53 * * * *"),
                         ('  workflow_dispatch:', '  push:\n  workflow_dispatch:'),
                         ('contents: read', 'contents: write')]:
            with self.subTest(mutation=old):
                path.write_text(original.replace(old, new), encoding='utf-8', newline='\n')
                raw = path.read_bytes()
                reviewed = dict(policy.EXPECTED)
                reviewed['.github/workflows/owned-repo-smoke.yml'] = {
                    'blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                    'mode': '100644'}
                with patch.object(policy, 'EXPECTED', reviewed):
                    with self.assertRaisesRegex(ValueError, 'exact_daily_offline_smoke_policy_required'):
                        policy.verify(self.root)
        path.write_text(original, encoding='utf-8', newline='\n')

    def test_exact_v3_active_set(self):
        result=policy.verify(ROOT)
        self.assertEqual(result['stage'],policy.STAGE)
        self.assertEqual(result['active_workflows'],[
            '.github/workflows/owned-core-ledger-publisher.yml',
            '.github/workflows/owned-core-local.yml',
            '.github/workflows/owned-fx-readonly-observation.yml',
            '.github/workflows/owned-pages-once.yml',
            '.github/workflows/owned-real-knowledge-sync.yml',
            '.github/workflows/owned-repo-smoke.yml',
            '.github/workflows/owned-shopify-readonly-preflight.yml',
            '.github/workflows/owned-shopify-team-observation.yml',
            '.github/workflows/owned-shopify-us-free-shipping.yml', '.github/workflows/owned-technical-review-report.yml'])
    def test_existing_shipping_lane_preserved_exactly(self):
        path = ROOT / '.github/workflows/owned-shopify-us-free-shipping.yml'
        import hashlib
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                         '635d1c38d25d8395af84e04a7c33d5c371009a1b')
        doc = yaml.safe_load(raw)
        self.assertEqual(set(doc.get('on', doc.get(True))), {'workflow_dispatch'})
        self.assertEqual(doc['permissions'], {'contents': 'read'})
        steps = doc['jobs']['us_free_shipping']['steps']
        self.assertEqual(steps[0]['with']['persist-credentials'], False)
        self.assertEqual(steps[0]['with']['ref'], '${{ github.sha }}')
        self.assertNotIn('secrets.', str(steps[2]))
        self.assertEqual(steps[3]['env']['APPLY'], "${{ inputs.mode == 'apply' && '1' || '0' }}")
        self.assertEqual(steps[3]['run'], 'python -B scripts/shopify_us_free_shipping.py')

    def test_existing_shipping_mutations_rejected(self):
        path = self.root / '.github/workflows/owned-shopify-us-free-shipping.yml'
        original = path.read_text(encoding='utf-8')
        for old, new in [('default: check', 'default: apply'),
                         ('contents: read', 'contents: write'),
                         ('inputs.expected_sha == github.sha', 'true'),
                         ('options: [check, apply]', 'options: [check, apply, all]'),
                         ("inputs.mode == 'apply' && '1' || '0'", "'1'"),
                         ('timeout-minutes: 5', 'timeout-minutes: 60')]:
            with self.subTest(mutation=old):
                path.write_text(original.replace(old, new), encoding='utf-8', newline='\n')
                with self.assertRaises(ValueError):
                    policy.verify(self.root)
        path.write_text(original, encoding='utf-8', newline='\n')

    def test_pages_exact_inventory_matches_policy(self):
        # Keep Pages literal allowlist and exact fingerprint policy synchronized.
        doc = yaml.safe_load((ROOT / '.github/workflows/owned-pages-once.yml').read_text())
        step = next(s for s in doc['jobs']['public-build']['steps']
                    if s.get('name', '').startswith('Build only reviewed'))
        code = step['run'].split("python -B - <<'PY'\n", 1)[1].split('\nPY', 1)[0]
        comparisons = [n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Compare)
                       and isinstance(n.left, ast.Name) and n.left.id == 'active']
        self.assertEqual(len(comparisons), 1)
        check = comparisons[0]
        self.assertEqual(len(check.ops), 1)
        self.assertIsInstance(check.ops[0], ast.Eq)
        exact = ast.literal_eval(check.comparators[0])
        expected = sorted(Path(p).name for p in policy.EXPECTED
                          if p.startswith('.github/workflows/') and p.endswith(('.yml', '.yaml')))
        self.assertEqual(exact, expected)

    def test_technical_report_lane_exact_readonly(self):
        text=(ROOT/'.github/workflows/owned-technical-review-report.yml').read_text()
        doc=yaml.safe_load(text)
        self.assertEqual(set(doc.get('on',doc.get(True))),{'workflow_dispatch'})
        self.assertEqual(doc['permissions'],{'contents':'read'})
        self.assertEqual(set(doc['jobs']),{'report'})
        job=doc['jobs']['report'];self.assertNotIn('environment',job)
        for forbidden in ('secrets.', 'contents: write', 'actions: write', 'schedule:', 'workflow_run:'):
            self.assertNotIn(forbidden,text)
        self.assertEqual(job['timeout-minutes'],4)
        for guard in ("github.repository_id == '1431541717'", "github.ref == 'refs/heads/main'",'inputs.expected_sha == github.sha','github.run_attempt == 1'):
            self.assertIn(guard,job['if'])
        steps=job['steps'];self.assertEqual(steps[0]['with']['persist-credentials'],False)
        self.assertEqual(steps[0]['with']['ref'],'${{ github.sha }}')
        self.assertIn('test_run_technical_review_report',steps[2]['run'])
        self.assertEqual(steps[3]['run'],'timeout --signal=TERM --kill-after=5s 45s python -B scripts/run_technical_review_report.py')
        upload=steps[4];self.assertEqual(upload['with']['retention-days'],30)
        self.assertEqual(upload['with']['overwrite'],False)
        self.assertEqual(upload['with']['path'],'${{ runner.temp }}/technical-review-report-${{ github.run_id }}-${{ github.run_attempt }}/result.json')
        self.assertEqual(upload['uses'],'actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9')
    def test_technical_report_workflow_changes_rejected(self):
        path=self.root/'.github/workflows/owned-technical-review-report.yml';original=path.read_text()
        for mutation in (original.replace('contents: read','contents: write'), original.replace('retention-days: 30','retention-days: 90'),original+'\n# unreviewed\n'):
            path.write_text(mutation)
            with self.assertRaises(ValueError):policy.verify(self.root)
        path.write_text(original)

    def test_fx_lane_is_manual_bounded_credential_free(self):
        text=(ROOT/'.github/workflows/owned-fx-readonly-observation.yml').read_text()
        doc=yaml.safe_load(text)
        self.assertEqual(set(doc.get('on',doc.get(True))),{'workflow_dispatch'})
        self.assertEqual(doc['permissions'],{'contents':'read'})
        self.assertEqual(set(doc['jobs']),{'observe'})
        job=doc['jobs']['observe'];self.assertNotIn('environment',job)
        self.assertNotIn('secrets.',text);self.assertNotIn('contents: write',text)
        self.assertEqual(job['timeout-minutes'],4)
        for guard in ("github.repository_id == '1431541717'", "github.ref == 'refs/heads/main'",'inputs.expected_sha == github.sha','github.run_attempt == 1'):
            self.assertIn(guard,job['if'])
        steps=job['steps'];self.assertEqual(steps[0]['with']['persist-credentials'],False)
        self.assertEqual(steps[0]['with']['ref'],'${{ github.sha }}')
        self.assertIn('test_run_fx_readonly_observation',steps[2]['run'])
        self.assertEqual(steps[3]['run'],'timeout --signal=TERM --kill-after=5s 45s python -B scripts/run_fx_readonly_observation.py')
        upload=steps[4];self.assertEqual(upload['with']['retention-days'],30)
        self.assertEqual(upload['with']['overwrite'],False)
        self.assertTrue(upload['with']['path'].endswith('/result.json'))
        self.assertEqual(upload['uses'],'actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9')
    def test_fx_lane_changes_rejected(self):
        path=self.root/'.github/workflows/owned-fx-readonly-observation.yml';original=path.read_text()
        for changed in (original.replace('contents: read','contents: write'),
                        original.replace('timeout-minutes: 4','timeout-minutes: 40'),
                        original.replace('retention-days: 30','retention-days: 90'),
                        original.replace('run_attempt == 1','run_attempt >= 1')):
            path.write_text(changed)
            with self.assertRaises(ValueError):policy.verify(self.root)
        path.write_text(original)

    def test_connection_default_and_no_unreviewed_choice(self):
        path=self.root/'.github/workflows/owned-shopify-readonly-preflight.yml'
        original=path.read_text()
        for altered in (original.replace('default: connection','default: organist_dry_run'),
                        original.replace('[connection, organist_dry_run, vt_usage_canary, source_diagnostic]', '[connection, organist_dry_run, vt_usage_canary, source_diagnostic, execute]')):
            path.write_text(altered)
            with self.assertRaises(ValueError): policy.verify(self.root)

    def test_canary_missing_slot_or_write_permissions_rejected(self):
        path=self.root/'.github/workflows/owned-shopify-readonly-preflight.yml'
        original=path.read_text()
        for altered in (original.replace('github.run_number == 8 && ', ''),
                        original.replace('actions: read', 'actions: write'),
                        original.replace('overwrite: false', 'overwrite: true')):
            path.write_text(altered)
            with self.assertRaises(ValueError): policy.verify(self.root)

    def test_source_diagnostic_has_no_shopify_environment_or_writer_slot(self):
        path=self.root/'.github/workflows/owned-shopify-readonly-preflight.yml'
        original=path.read_text()
        for altered in (original.replace('  source_diagnostic:\n', '  source_diagnostic:\n    environment: jarvis-shopify-writer\n'),
                        original.replace('github.run_number == 7', 'github.run_number == 5'),
                        original.replace('"$RUNNER_TEMP/vt-source-diagnostic"','"$RUNNER_TEMP/vt-usage-canary"')):
            path.write_text(altered)
            with self.assertRaises(ValueError):policy.verify(self.root)

    def test_preflight_write_scope_rejected(self):
        path=self.root/'.github/workflows/owned-shopify-readonly-preflight.yml'
        path.write_text(path.read_text().replace('contents: read', 'contents: write'))
        with self.assertRaises(ValueError): policy.verify(self.root)

    def test_preflight_schedule_rejected(self):
        path=self.root/'.github/workflows/owned-shopify-readonly-preflight.yml'
        path.write_text(path.read_text().replace('  workflow_dispatch:', "  schedule:\n    - cron: '* * * * *'\n  workflow_dispatch:"))
        with self.assertRaises(ValueError): policy.verify(self.root)

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
        path.write_text(path.read_text().replace("  schedule:\n    - cron: '17 */1 * * *'\n", '').replace('  workflow_dispatch:', "  workflow_dispatch:\n  schedule:\n    - cron: '* * * * *'"))
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_knowledge_scope_is_separate_and_no_production_recovery(self):
        result = policy.verify(ROOT)
        self.assertEqual(result['knowledge_stage'], 'owned-real-knowledge-data-only-v2')
        self.assertFalse(result['production_recovered'])
        self.assertEqual(result['archived_workflows'], 30)
        doc = yaml.safe_load((ROOT / policy.KNOWLEDGE_WORKFLOW).read_text())
        helper = (ROOT / 'scripts/owned_real_knowledge_sync.py').read_bytes().replace(b'\r\n', b'\n')
        checksum_step = next(s for s in doc['jobs']['sync']['steps'] if s.get('name') == 'Verify reviewed knowledge-only helper')
        self.assertIn(hashlib.sha256(helper).hexdigest(), checksum_step['run'])
        self.assertNotIn('actions/upload-artifact', str(doc))
        self.assertNotIn('secrets.', str(doc))

    def test_knowledge_lane_mutations_rejected_even_with_changed_fingerprint(self):
        path = self.root / policy.KNOWLEDGE_WORKFLOW
        original = path.read_bytes()
        mutations = [
            (b'37 0,6,12,18 * * *', b'* * * * *'),
            (b"github.ref == 'refs/heads/main'", b'true'),
            (b'inputs.expected_sha == github.sha', b'true'),
            (b'contents: write', b'contents: read'),
            (b'cancel-in-progress: false', b'cancel-in-progress: true'),
            (b'owned_real_knowledge_sync.py publish', b'publish_transaction.py publish'),
            (b'github.token', b'secrets.PUBLISH_TOKEN'),
            (b'timeout-minutes: 15', b'timeout-minutes: 60')]
        try:
            for old, new in mutations:
                with self.subTest(mutation=old):
                    changed = original.replace(old, new)
                    self.assertNotEqual(changed, original)
                    path.write_bytes(changed)
                    with patch.dict(policy.EXPECTED, {policy.KNOWLEDGE_WORKFLOW: {
                            'blob': hashlib.sha1(b'blob '+str(len(changed)).encode()+b'\0'+changed).hexdigest(), 'mode': '100644'}}):
                        with self.assertRaises(ValueError):
                            policy.verify(self.root)
        finally:
            path.write_bytes(original)

    def test_unknown_knowledge_stage_rejected(self):
        with patch.object(policy, 'KNOWLEDGE_STAGE', 'unreviewed'):
            with self.assertRaises(ValueError):
                policy.verify(self.root)

    def producer_profile(self, hourly):
        path=self.root/'.github/workflows/owned-core-local.yml'
        text=path.read_text(encoding='utf-8').replace("  schedule:\n    - cron: '17 */1 * * *'\n", '')
        if hourly:
            text=text.replace('  workflow_dispatch:\n', "  workflow_dispatch:\n  schedule:\n    - cron: '17 */1 * * *'\n")
        path.write_text(text, encoding='utf-8', newline='\n')
    def test_named_manual_profile(self):
        self.producer_profile(False)
        with patch.object(policy, 'STAGE', policy.MANUAL_STAGE):
            self.assertEqual(policy.verify(self.root)['active_schedules'],2)
    def test_named_hourly_profile(self):
        self.producer_profile(True)
        with patch.object(policy, 'STAGE', policy.HOURLY_STAGE):
            self.assertEqual(policy.verify(self.root)['active_schedules'],3)
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
    def test_pages_root_write_permission_rejected(self):
        path=self.root/'.github/workflows/owned-pages-once.yml'
        original=path.read_text()
        changed=original.replace('permissions: {}', 'permissions:\n  contents: write', 1)
        self.assertNotEqual(original,changed)
        path.write_text(changed)
        with self.assertRaises(ValueError):policy.verify(self.root)
    def test_pages_automatic_events_rejected(self):
        path=self.root/'.github/workflows/owned-pages-once.yml'
        original=path.read_text()
        for event in ('  push:\n', "  schedule:\n    - cron: '* * * * *'\n"):
            with self.subTest(event=event):
                changed=original.replace('  workflow_dispatch:', event+'  workflow_dispatch:', 1)
                self.assertNotEqual(original,changed)
                path.write_text(changed)
                with self.assertRaises(ValueError):policy.verify(self.root)
        path.write_text(original)

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
