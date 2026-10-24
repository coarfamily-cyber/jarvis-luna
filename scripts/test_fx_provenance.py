"""Offline synthetic observations; no provider requests or financial assertions."""
import copy
import unittest
from datetime import datetime, timezone
from fx_provenance import assess_fx, select_fx, dashboard_fx, ENDPOINTS

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def observation(**changes):
    return dict({'usd_to_krw': 1400.5, 'as_of': '2026-10-24',
                 'source': 'ExchangeRate-API', 'api_url': ENDPOINTS['ExchangeRate-API'],
                 'fetched_at': '2026-10-24T01:00:00+00:00', 'ok': True}, **changes)


class FxProvenanceTests(unittest.TestCase):
    def test_valid_and_no_mutation(self):
        row = observation(); before = copy.deepcopy(row)
        result = assess_fx(row, NOW)
        self.assertTrue(result['valid']); self.assertTrue(result['fresh'])
        self.assertEqual(row, before)
        self.assertEqual(result['observation']['fetched_at'], row['fetched_at'])

    def test_invalid_numeric_types_and_values(self):
        for rate in (True, False, '1400', None, [], {}, float('nan'), float('inf'), -1, 0, 499, 3001, 10**500):
            with self.subTest(rate=repr(rate)):
                self.assertFalse(assess_fx(observation(usd_to_krw=rate), NOW)['valid'])
        for rate in (500, 3000, 1400.5):
            self.assertTrue(assess_fx(observation(usd_to_krw=rate), NOW)['valid'])

    def test_strict_success_bool(self):
        for value in (1, 'true', False, None):
            self.assertFalse(assess_fx(observation(ok=value), NOW)['valid'])

    def test_missing_impossible_future_and_trailing_dates(self):
        for value in ('', None, '2026-02-30', '2026-10-25', '2026-10-24garbage', '2026-10-24T00:00:00Z', '2026-1-2', True):
            self.assertFalse(assess_fx(observation(as_of=value), NOW)['valid'], repr(value))

    def test_observed_time_must_exist_aware_not_future(self):
        for value in ('', None, '2026-10-24', '2026-10-24T01:00:00', '2026-10-24T12:00:01Z', 'garbage'):
            self.assertFalse(assess_fx(observation(fetched_at=value), NOW)['valid'])
        self.assertTrue(assess_fx(observation(fetched_at='2026-10-24T10:00:00+09:00'), NOW)['valid'])

    def test_source_cannot_postdate_observation(self):
        self.assertFalse(assess_fx(observation(fetched_at='2026-10-23T23:00:00Z'), NOW)['valid'])

    def test_endpoint_binding_both_source_styles(self):
        for label, endpoint in ENDPOINTS.items():
            self.assertTrue(assess_fx(observation(source=label, api_url=endpoint), NOW)['valid'])
            self.assertTrue(assess_fx(observation(source=endpoint, api_url=endpoint), NOW)['valid'])
        for value in ('https://example.invalid', ENDPOINTS['ExchangeRate-API'] + '?spoof', {}, None):
            self.assertFalse(assess_fx(observation(source=value), NOW)['valid'])
        self.assertFalse(assess_fx(observation(api_url=ENDPOINTS['Frankfurter API']), NOW)['valid'])

    def test_stale_is_valid_not_fresh(self):
        old = observation(as_of='2026-10-01', fetched_at='2026-10-01T12:00:00Z')
        result = assess_fx(old, NOW)
        self.assertTrue(result['valid']); self.assertFalse(result['fresh'])
        self.assertEqual(result['state'], 'stale')
        self.assertTrue(dashboard_fx(old, NOW)['stale'])

    def test_failure_and_older_preserve_cache_timestamp(self):
        old = observation()
        for incoming in ({}, None, observation(as_of='2026-10-23'), observation(as_of='2099-01-01')):
            result = select_fx(old, incoming, NOW)
            self.assertEqual(result['selection'], 'previous')
            self.assertEqual(result['state'], 'cached')
            self.assertEqual(result['observation']['fetched_at'], old['fetched_at'])

    def test_stale_previous_retained_not_rejuvenated(self):
        old = observation(as_of='2026-10-01', fetched_at='2026-10-01T12:00:00Z')
        result = select_fx(old, {}, NOW)
        self.assertEqual(result['state'], 'stale')
        self.assertEqual(result['observation']['fetched_at'], old['fetched_at'])

    def test_invalid_previous_cannot_defeat_valid_incoming(self):
        result = select_fx(observation(as_of='2099-01-01'), observation(), NOW)
        self.assertEqual(result['selection'], 'incoming')
        self.assertTrue(result['fresh'])
        self.assertEqual(select_fx({}, {}, NOW)['selection'], 'none')

    def test_equal_date_no_observation_clock_regression(self):
        result = select_fx(observation(fetched_at='2026-10-24T02:00:00Z'), observation(), NOW)
        self.assertEqual(result['selection'], 'previous')

    def test_newer_valid_source_selected(self):
        result = select_fx(observation(as_of='2026-10-23'), observation(), NOW)
        self.assertEqual(result['selection'], 'incoming')

    def test_dashboard_exact_projection_invalid_removed(self):
        view = dashboard_fx(observation(), NOW)
        self.assertEqual(view['rate'], 1400.5)
        self.assertEqual(view['as_of'], '2026-10-24')
        self.assertEqual(view['source'], 'ExchangeRate-API')
        self.assertNotIn('updated_at', view)
        self.assertEqual(dashboard_fx(observation(usd_to_krw=True), NOW), {})

    def test_retained_fresh_display_and_ages_do_not_refresh_clock(self):
        old = observation(as_of='2026-10-23', fetched_at='2026-10-23T12:00:00Z',
                          selection='previous', last_attempt_ok=False)
        card = dashboard_fx(old, NOW)
        self.assertEqual(card['state'], 'cached')
        self.assertFalse(card['stale'])
        self.assertEqual(card['source_age_days'], 1)
        self.assertEqual(card['observation_age_days'], 1)
        self.assertEqual(card['fetched_at'], old['fetched_at'])
        self.assertEqual(dashboard_fx(dict(old, as_of='2026-10-01',
                         fetched_at='2026-10-01T12:00:00Z'), NOW)['state'], 'stale')
        self.assertIsNone(assess_fx({}, NOW)['source_age_days'])

    def test_clock_and_policy_invalid_fail_explicitly(self):
        with self.assertRaises(ValueError): assess_fx(observation(), datetime(2026, 10, 24))
        for value in (-1, True, float('inf'), '4'):
            with self.assertRaises(ValueError): assess_fx(observation(), NOW, value)


if __name__ == '__main__':
    unittest.main()
