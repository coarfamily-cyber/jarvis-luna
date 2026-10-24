"""Independent offline negatives; synthetic snapshots cannot grant live authority."""
import copy
import hashlib
import json
import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import team_repair_rehearsal as replay

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode()


class TeamRepairRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(issue_id='supplier-1025282-manufacturer_heading_fragment',
                         rule='manufacturer_heading_fragment', team='sourcing',
                         **{key: False for key in replay.AUTHORITY})
        self.before = {'kind': 'saved_shopify_product_readback',
                       'recorded_at': '2026-10-24T01:00:00Z',
                       'product': {'id': 'gid://shopify/Product/9710072889601',
                                   'status': 'DRAFT', 'tags': ['daiso-pd-1025282'],
                                   'title': 'Organist 200 ml', 'totalInventory': 1,
                                   'variants': [{'id': 'variant-fixture', 'price': '12.00'}],
                                   'descriptionHtml': '<p>' + replay.LABEL + replay.FRAGMENT + '</p><p>190 ml (200g)</p>'}}
        self.after = copy.deepcopy(self.before)
        self.after['recorded_at'] = '2026-10-24T02:00:00Z'
        self.after['product']['descriptionHtml'] = self.before['product']['descriptionHtml'].replace(replay.FRAGMENT, replay.REPLACEMENT)

    def run_case(self, before=None, after=None, task=None, **kw):
        return replay.rehearse(self.task if task is None else task,
                              encode(self.before if before is None else before),
                              encode(self.after if after is None else after), now=kw.get('now', NOW))

    def assert_blocked(self, result):
        self.assertEqual(result['state'], 'review_required')
        self.assertFalse(result['live_execution']); self.assertFalse(result['fresh_readback'])
        self.assertTrue(result['independent_review_required'])
        for key in replay.AUTHORITY: self.assertIs(result[key], False)
        self.assertNotIn('proposed_description_html', result)

    def test_success_deterministic_bound_readonly_and_no_authority(self):
        originals = copy.deepcopy((self.task, self.before, self.after))
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network')), patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
            result = self.run_case()
        self.assertEqual(result['state'], 'offline_replay_verified')
        self.assertEqual(result, self.run_case())
        self.assertEqual((self.task, self.before, self.after), originals)
        self.assertEqual(result['binding']['before_snapshot_sha256'], hashlib.sha256(encode(self.before)).hexdigest())
        self.assertEqual(result['binding']['saved_readback_sha256'], hashlib.sha256(encode(self.after)).hexdigest())
        self.assertEqual(result['binding']['allowed_fields'], ['descriptionHtml'])
        self.assertIn('190 ml (200g)', result['proposed_description_html'])
        self.assertTrue(result['unresolved_holds_unchanged'])
        for key in (*replay.AUTHORITY, 'live_execution', 'fresh_readback'): self.assertIs(result[key], False)

    def test_unsupported_formula_and_volume_rules(self):
        for rule in ('formula_conflict', 'volume_conflict', 'supplier_warning_review'):
            self.assert_blocked(replay.rehearse(dict(self.task, rule=rule), b'invalid', b'invalid', now=NOW))

    def test_no_truthy_or_missing_task_authority(self):
        for key in replay.AUTHORITY:
            for value in (True, 0, 1, None, 'false'):
                self.assert_blocked(self.run_case(task=dict(self.task, **{key: value})))
            task = dict(self.task); del task[key]
            self.assert_blocked(self.run_case(task=task))

    def test_issue_team_and_sku_binding(self):
        for changes in ({'team': 'legal'}, {'issue_id': 'supplier-1067498-manufacturer_heading_fragment'}, {'issue_id': []}):
            self.assert_blocked(self.run_case(task=dict(self.task, **changes)))
        before = copy.deepcopy(self.before); before['product']['tags'] = 'daiso-pd-1025282'
        self.assert_blocked(self.run_case(before=before))
        for tags in (['daiso-pd-1025282', 'daiso-pd-1067498'],
                     ['daiso-pd-1025282', 'daiso-pd-1025282']):
            before = copy.deepcopy(self.before); before['product']['tags'] = tags
            after = copy.deepcopy(self.after); after['product']['tags'] = tags
            self.assert_blocked(self.run_case(before=before, after=after))

    def test_readback_identity_and_protected_field_changes(self):
        for key, value in [('id', 'gid://shopify/Product/2'), ('status', 'ACTIVE'), ('title', 'Changed'), ('totalInventory', 2), ('tags', []), ('variants', [])]:
            after = copy.deepcopy(self.after); after['product'][key] = value
            self.assert_blocked(self.run_case(after=after))
        after = copy.deepcopy(self.after); after['product']['unexpected'] = 'extra'
        self.assert_blocked(self.run_case(after=after))

    def test_python_equal_but_json_different_protected_values_rejected(self):
        for value in (True, 1.0):
            after = copy.deepcopy(self.after); after['product']['totalInventory'] = value
            self.assert_blocked(self.run_case(after=after))

    def test_missing_ambiguous_changed_and_already_fixed_fragment(self):
        for body in ('', self.before['product']['descriptionHtml'] * 2, self.after['product']['descriptionHtml'], '<p>및 판매원</p>'):
            before = copy.deepcopy(self.before); before['product']['descriptionHtml'] = body
            self.assert_blocked(self.run_case(before=before))

    def test_role_fragment_prefix_of_real_text_not_eligible(self):
        before = copy.deepcopy(self.before)
        before['product']['descriptionHtml'] = '<p>' + replay.LABEL + replay.FRAGMENT + ' Example Company</p>'
        after = copy.deepcopy(self.after)
        after['product']['descriptionHtml'] = before['product']['descriptionHtml'].replace(replay.FRAGMENT, replay.REPLACEMENT)
        self.assert_blocked(self.run_case(before=before, after=after))

    def test_clock_future_naive_missing_and_readback_regression(self):
        for value in ('2027-01-01T00:00:00Z', '2026-10-24T01:00:00', None, '', '2026-10-23T23:00:00Z'):
            after = copy.deepcopy(self.after); after['recorded_at'] = value
            self.assert_blocked(self.run_case(after=after))
        self.assert_blocked(self.run_case(now=datetime(2026, 10, 24)))

    def test_exact_envelope_shape_and_kind(self):
        for changes in ({'kind': 'live_verified'}, {'unexpected': True}, {'product': []}):
            self.assert_blocked(self.run_case(before=dict(self.before, **changes)))

    def test_strict_bytes_json_duplicate_and_nonfinite(self):
        good = encode(self.before)
        for raw in (None, '', b'', b'\xff', b'{', b'[]', b'{}', b'x' * (replay.MAX_BYTES + 1), good.replace(b'"totalInventory": 1', b'"totalInventory": 1, "totalInventory": 2'), good.replace(b'"totalInventory": 1', b'"totalInventory": NaN'), good.replace(b'"totalInventory": 1', b'"totalInventory": 1e999')):
            self.assert_blocked(replay.rehearse(self.task, raw, encode(self.after), now=NOW))

    def test_replay_key_changes_with_saved_envelope_bytes(self):
        initial = self.run_case()
        after = copy.deepcopy(self.after); after['recorded_at'] = '2026-10-24T03:00:00Z'
        later = self.run_case(after=after)
        self.assertEqual(later['state'], 'offline_replay_verified')
        self.assertNotEqual(initial['replay_key'], later['replay_key'])

    def test_malformed_reasons_never_echo_snapshot_contents(self):
        raw = b'{"private_marker":"SECRET_FIXTURE", "product":'
        result = replay.rehearse(self.task, raw, encode(self.after), now=NOW)
        self.assert_blocked(result)
        self.assertNotIn('SECRET_FIXTURE', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
