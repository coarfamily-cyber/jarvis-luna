"""Existing checkpoint-engine adversaries; synthetic transports, no VT authority.

These test the existing adapter seam, NOT an implemented VT writer or consumed
run-slot store. Imported legacy fixture uses temporary synthetic source files.
"""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import apply_reviewed_draft_copy as draft
import reviewed_copy_transaction as transaction
import test_apply_reviewed_draft_copy as fixtures


class StrictFixturePolicy(draft._DraftPolicy):
    REQUIRE_ORIGINAL_CHECKPOINT = True


class CheckpointAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CopyExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # The old writer is quarantined. Recreate its hash input ONLY in a
        # temporary historical fixture; never activate a repository workflow.
        source = self.fixture.production_source_root
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = ['scripts/apply_reviewed_draft_copy.py',
                 'scripts/plan_draft_product_copy.py',
                 'scripts/reviewed_copy_transaction.py',
                 'scripts/apply_reviewed_product_gallery.py',
                 'scripts/plan_active_product_gallery.py', 'scripts/gallery_review.py',
                 'data/manual/draft_copy/verified_fields.json', draft.WORKFLOW]
        for relative in paths:
            original = source / relative
            if relative == draft.WORKFLOW:
                original = source / '.github/workflows-quarantined/20261023' / Path(relative).name
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        module_path = patch.object(draft, '__file__', str(root / 'scripts/apply_reviewed_draft_copy.py'))
        module_path.start()
        self.addCleanup(module_path.stop)

    def backend(self, **kwargs):
        plan, journal, old = self.fixture.backend(**kwargs)
        backend = transaction.GitHubCheckpoint(
            'SYNTHETIC-SECRET', old.artifact_id, old.expected_digest,
            policy=StrictFixturePolicy(), request=old.request)
        return plan, journal, backend

    def test_strict_original_checkpoint_authenticates_raw_bytes(self):
        plan, journal, backend = self.backend()
        self.assertTrue(backend.verify(plan, journal))
        restored, restored_journal = backend.restore(
            self.fixture.context['repository'], expected_plan_digest=plan['plan_digest'],
            expected_shop=self.fixture.scope['canonical_shop'],
            expected_product=self.fixture.scope['product_id'])
        self.assertEqual(restored, plan)
        self.assertEqual(restored_journal, journal)
        self.assertEqual(self.fixture.client.writes, 0)

    def test_equal_count_history_metadata_drift_is_rejected(self):
        plan, journal, backend = self.backend()
        request = backend.request
        scans = 0
        def changed(url, **kwargs):
            nonlocal scans
            status, headers, raw = request(url, **kwargs)
            if '/actions/artifacts?' in url:
                scans += 1
                if scans == 2:
                    listing = draft.strict_json(raw)
                    listing['artifacts'][0]['digest'] = 'sha256:' + 'e'*64
                    raw = draft.json_bytes(listing)
            return status, headers, raw
        backend.request = changed
        with self.assertRaisesRegex(draft.Hold, 'checkpoint_scan_drift'):
            backend.verify(plan, journal)

    def test_deleted_original_never_restores_from_missing_history(self):
        plan, _, backend = self.backend(list_change=lambda x: x.update(total_count=0, artifacts=[]))
        with self.assertRaisesRegex(draft.Hold, 'restore_history_expired_or_missing'):
            backend.restore(self.fixture.context['repository'], expected_plan_digest=plan['plan_digest'],
                expected_shop=self.fixture.scope['canonical_shop'], expected_product=self.fixture.scope['product_id'])

    def test_expired_prior_intent_blocks_fresh_checkpoint(self):
        def prior(listing):
            original = deepcopy(listing['artifacts'][0])
            original.update(id=89, expired=True)
            listing.update(total_count=2, artifacts=[original, *listing['artifacts']])
        plan, journal, backend = self.backend(list_change=prior)
        with self.assertRaises(draft.PriorCheckpoint):
            backend.verify(plan, journal)
        with self.assertRaisesRegex(draft.Hold, 'restore_history_expired_or_missing'):
            backend.restore(self.fixture.context['repository'], expected_plan_digest=plan['plan_digest'],
                expected_shop=self.fixture.scope['canonical_shop'], expected_product=self.fixture.scope['product_id'])

    def test_zip_traversal_absolute_duplicate_and_extra_members_rejected(self):
        for names in [('plan.json', '../journal.json'), ('/plan.json', 'journal.json'),
                      ('plan.json', 'journal.json', 'plan.json'),
                      ('plan.json', 'journal.json', 'source/private.json')]:
            with self.subTest(names=names):
                plan, journal, backend = self.backend()
                out = io.BytesIO()
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(out, 'w') as archive:
                        for name in names:
                            archive.writestr(name, draft.json_bytes(plan if 'plan' in name else journal))
                raw = out.getvalue()
                backend.expected_digest = hashlib.sha256(raw).hexdigest()
                backend.request = lambda *a, **k: (200, {}, raw)
                with self.assertRaisesRegex(draft.Hold, 'checkpoint_zip_invalid'):
                    backend.download(self.fixture.context['repository'])

    def test_signed_object_download_strips_github_token(self):
        plan, journal, backend = self.backend()
        request = backend.request
        signed = 'https://synthetic.blob.core.windows.net/checkpoint.zip?sig=SYNTHETIC'
        calls = []
        def redirected(url, **kwargs):
            calls.append((url, kwargs))
            if url == signed:
                self.assertNotIn('Authorization', kwargs.get('headers', {}))
                self.assertNotIn('SYNTHETIC-SECRET', repr(kwargs))
                return request('https://api.github.com/repos/synthetic/repo/actions/artifacts/90/zip')
            if url.endswith('/zip'):
                return 302, {'location': signed}, b''
            return request(url, **kwargs)
        backend.request = redirected
        self.assertTrue(backend.verify(plan, journal))
        self.assertEqual(calls[-1][0], signed)

    def test_foreign_download_host_rejected_without_followup(self):
        _, _, backend = self.backend()
        calls = []
        def request(url, **kwargs):
            calls.append(url)
            return 302, {'location': 'https://attacker.invalid/private'}, b''
        backend.request = request
        with self.assertRaisesRegex(draft.Hold, 'checkpoint_download_host_invalid'):
            backend.download(self.fixture.context['repository'])
        self.assertEqual(len(calls), 1)

    def test_completed_or_rerun_cannot_verify_write_checkpoint(self):
        for change in ({'run_attempt': 2}, {'status': 'completed'}, {'head_sha': 'b'*40}):
            with self.subTest(change=change):
                plan, journal, backend = self.backend(run_change=lambda r: r.update(change))
                with self.assertRaisesRegex(draft.Hold, 'checkpoint_workflow_mismatch'):
                    backend.verify(plan, journal)
                self.assertEqual(self.fixture.client.writes, 0)


class RuntimeClientEngineTests(unittest.TestCase):
    def exercise(self, timeout=False):
        import json
        from datetime import datetime, timezone
        import vt_body_canary_runtime as runtime
        import vt_body_canary_policy as policy
        from test_vt_body_canary_runtime import sample
        source = b'synthetic-reviewed-source'
        snapshot = sample()
        calls = []
        class Transport:
            def arm_exact_body(self, body):
                self.armed = body
            def __call__(self, operation, **kwargs):
                calls.append(operation)
                if operation == 'mutation':
                    if timeout:
                        raise TimeoutError('SYNTHETIC-SECRET-BODY')
                    snapshot['descriptionHtml'] = self.armed
                    snapshot['updatedAt'] = '2026-10-24T12:00:01Z'
                    return json.dumps({'data': {'productUpdate': {
                        'product': {'id': policy.PRODUCT}, 'userErrors': []}}}).encode()
                return json.dumps({'data': {'product': snapshot}}).encode()
        class Checkpoint:
            def verify(self, *args):
                calls.append('checkpoint')
                return True
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(policy, 'SOURCE', hashlib.sha256(source).hexdigest()), \
                patch.object(policy, 'BEFORE', hashlib.sha256(policy.OLD.encode()).hexdigest()), \
                patch.object(policy, 'AFTER', hashlib.sha256(policy.NEW.encode()).hexdigest()), \
                patch.object(runtime.Policy, 'fetch_sources', return_value=source), \
                patch.object(runtime, 'APPROVED_VISIBLE_PROJECTION', runtime.sha(runtime.visible_projection(snapshot))), \
                patch.object(runtime, 'live_window'):
            model = runtime.Policy()
            plan = model.build_plan({'pd_no': '1067498', 'product_id': policy.PRODUCT,
                                     'canonical_shop': policy.HOST}, directory, snapshot,
                                    now=datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
            journal = transaction.make_journal(model, plan, repository='coarfamily-cyber/jarvis-luna',
                run_id='99', run_attempt='1', code_sha='a'*40, workflow_path=runtime.WORKFLOW)
            path = Path(directory) / 'journal.json'
            draft.atomic_json(path, journal)
            client = runtime.Client(Transport(), 'SYNTHETIC-TOKEN', 'apply')
            result = transaction.execute(model, plan, root=directory,
                expected_plan_digest=plan['plan_digest'], client=client,
                journal_path=path, checkpoint=Checkpoint(), apply=True)
            saved = draft.read_json(path)
            self.assertNotIn('SYNTHETIC', json.dumps(result))
            self.assertEqual(saved['write_attempts'], 1)
            return result, saved, calls

    def test_real_client_and_engine_success_order_and_body_only_readback(self):
        result, saved, calls = self.exercise()
        self.assertEqual(calls, ['before', 'checkpoint', 'last', 'mutation', 'after'])
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['writes'], 1)
        self.assertEqual(saved['state'], 'verified')

    def test_real_client_unknown_does_not_automatically_read_or_retry(self):
        result, saved, calls = self.exercise(timeout=True)
        self.assertEqual(calls, ['before', 'checkpoint', 'last', 'mutation'])
        self.assertEqual(result['state'], 'write_unknown')
        self.assertEqual(saved['state'], 'write_unknown')
        self.assertFalse(result['automatic_retry_allowed'])


if __name__ == '__main__':
    unittest.main()
