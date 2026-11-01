"""Fixture-only Herdr projection tests: no external tools or Core."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest

import herdr_status_adapter as adapter


def fixture():
    return {'captured_ms': 400000, 'source_epoch': 'epoch-one', 'fresh_snapshot': True,
            'snapshot': {'terminals': [{'address': 'private-host/t1', 'state': 'live',
                                       'reported': True, 'status': {'state': 'working'},
                                       'created_ms': 1, 'status_ms': 2}],
                         'hidden_finished': 0, 'machines': []}}


class HerdrSnapshotTests(unittest.TestCase):
    def normalize(self, doc, **kwargs):
        return adapter.normalize_snapshot(json.dumps(doc).encode(),
                                          now_ms=kwargs.get('now_ms', 400001),
                                          expected_epoch=kwargs.get('epoch', 'epoch-one'))

    def test_every_reported_word_and_no_success_authority(self):
        for state in adapter.STATES:
            doc = fixture(); doc['snapshot']['terminals'][0]['status']['state'] = state
            row = self.normalize(doc)['terminals'][0]
            self.assertEqual(row['reported_state'], state)
            for flag in ('execution_verified', 'business_approval', 'tests_passed',
                         'deployment_verified', 'full_core_recovery'):
                self.assertIs(row[flag], False)
            self.assertEqual(row['verification_status'], 'unverified_program_report')

    def test_old_status_change_is_not_stale_capture(self):
        self.assertEqual(self.normalize(fixture())['terminals'][0]['reported_state'], 'working')

    def test_capture_staleness_future_epoch_and_reconnect(self):
        for update, kwargs in [({}, {'now_ms': 700001}), ({}, {'now_ms': 399999}),
                               ({}, {'epoch': 'epoch-two'}), ({'fresh_snapshot': False}, {}),
                               ({'fresh_snapshot': None}, {})]:
            doc = fixture(); doc.update(update)
            result = self.normalize(doc, **kwargs)
            self.assertEqual(result['snapshot_status'], 'unknown')
            self.assertEqual(result['terminals'][0]['reported_state'], 'unknown')
            self.assertEqual(result['terminals'][0]['termination'], 'unknown')

    def test_missing_unknown_and_loss_states(self):
        for updates in ({'reported': False}, {'status': None}, {'status': {'state': 'future'}},
                        {'status_ms': None}, {'state': None}, {'reason': 'holder_lost'},
                        {'reason': 'spawn_pending'}, {'reason': 'unsupported'},
                        {'signal': 9}, {'exit_code': 0}, {'finished_ms': 100}):
            doc = fixture(); doc['snapshot']['terminals'][0].update(updates)
            self.assertEqual(self.normalize(doc)['terminals'][0]['reported_state'], 'unknown')
        doc = fixture(); del doc['snapshot']['terminals'][0]['status']
        self.assertEqual(self.normalize(doc)['terminals'][0]['reported_state'], 'unknown')

    def test_termination_is_independent_of_done_and_zero_exit(self):
        doc = fixture(); doc['snapshot']['terminals'][0].update(
            state='finished', status=None, finished_ms=300000, reason='exited', exit_code=0)
        row = self.normalize(doc)['terminals'][0]
        self.assertEqual((row['termination'], row['termination_reason'], row['exit_code']),
                         ('finished', 'exited', 0))
        self.assertEqual(row['reported_state'], 'unknown')
        self.assertFalse(row['tests_passed'])

    def test_redaction_and_no_mutation(self):
        doc = fixture(); terminal = doc['snapshot']['terminals'][0]
        for key in ('argv', 'cwd', 'title', 'labels', 'foreground', 'records'):
            terminal[key] = 'PRIVATE_SECRET_COMMAND_PATH'
        terminal['status'].update(msg='PRIVATE_MESSAGE', title='PRIVATE_TITLE', app='PRIVATE_APP')
        doc['snapshot']['machines'] = [{'name': 'PRIVATE_HOST'}]
        before = deepcopy(doc)
        result = json.dumps(self.normalize(doc))
        for marker in ('PRIVATE', 'private-host', 'epoch-one', 't1'):
            self.assertNotIn(marker, result)
        self.assertEqual(doc, before)

    def test_invalid_and_oversized_input(self):
        for payload in (b'', b'[]', b'{', b'\xff', b'{"a":1,"a":2}', b'{"a":NaN}',
                        b' ' * (adapter.MAX_BYTES + 1), 'not bytes'):
            with self.assertRaises(ValueError):
                adapter.normalize_snapshot(payload, now_ms=1, expected_epoch='e')
        for path, value in [('captured_ms', True), ('captured_ms', None), ('source_epoch', None),
                            ('snapshot', None)]:
            doc = fixture(); doc[path] = value
            with self.assertRaises(ValueError): self.normalize(doc)
        for updates in ({'status': 'done'}, {'reported': 1}, {'exit_code': True},
                        {'exit_code': 2**31}, {'signal': -(2**31)-1}, {'status_ms': 400001},
                        {'finished_ms': -1}, {'created_ms': 400001}, {'address': ''}):
            doc = fixture(); doc['snapshot']['terminals'][0].update(updates)
            with self.assertRaises(ValueError): self.normalize(doc)
        for value in (None, -1, True):
            doc = fixture(); doc['snapshot']['hidden_finished'] = value
            with self.assertRaises(ValueError): self.normalize(doc)
        for count in (2, adapter.MAX_TERMINALS + 1):
            doc = fixture(); doc['snapshot']['terminals'] *= count
            with self.assertRaises(ValueError): self.normalize(doc)

    def test_empty_list_is_not_health_evidence(self):
        doc = fixture(); doc['snapshot']['terminals'] = []
        result = self.normalize(doc)
        self.assertEqual(result['terminals'], [])
        self.assertFalse(result['full_core_recovery'])

    def test_imports_have_no_execution_capability(self):
        tree = ast.parse(Path(adapter.__file__).read_text())
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                   for alias in node.names]
        self.assertEqual(imports, ['json'])
        self.assertFalse(any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree)))


if __name__ == '__main__':
    unittest.main()
