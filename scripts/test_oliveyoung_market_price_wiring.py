#!/usr/bin/env python3
"""Synthetic offline producer/consumer tests; no source receipt is collected."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_channels as sync
import collect_oliveyoung_us as producer
import current_s_eligibility as consumer

NOW = datetime(2026, 10, 25, 3, 48, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


class OliveYoungMarketPriceWiring(unittest.TestCase):
    def document(self, price=19.95, currency='USD'):
        item = {'product_id': 'UA_SYNTHETIC', 'product_name': 'Vitamin C Capsule Cream',
                'brand_name': 'Synthetic fixture', 'price': {'currency': currency,
                'sale': {'min': {'amount': price}}}}
        with patch.object(producer, 'walk_products', return_value=[item]):
            rows = producer.parse('[]')
        return {'source': 'us.oliveyoung.com/best-sellers.data',
                'collected_at': STAMP, 'products': rows}

    def evaluate(self, document, trust='verified'):
        before = deepcopy(document)
        with patch.object(sync, 'load_json', return_value=document):
            rows, stamp, _ = sync.from_oliveyoung_us()
        self.assertEqual(document, before)
        dashboard = {'global_channels': {'oliveyoung_us': rows},
                     'global_channels_status': {'oliveyoung_us': {
                         'status': 'ok', 'trust': trust, 'collected_at': stamp}}}
        return rows, consumer.market_universe(dashboard, NOW)

    def test_collector_price_reaches_fresh_market_universe(self):
        document = self.document()
        rows, (_, prices, evidence, _) = self.evaluate(document)
        self.assertEqual(prices, [{'name': 'vitamin c capsule cream', 'price': 19.95}])
        self.assertEqual(rows[0]['badge'], '$19.95')
        self.assertEqual(rows[0]['url'], document['products'][0]['url'])
        self.assertEqual(evidence[0]['collected_at'], STAMP)

    def test_timestamp_stale_missing_future_not_upgraded(self):
        for stamp in ('2026-09-01T00:00:00+00:00', '', '2026-10-26T00:00:00+00:00'):
            with self.subTest(stamp=stamp):
                document = self.document(); document['collected_at'] = stamp
                _, (_, prices, evidence, _) = self.evaluate(document)
                self.assertEqual((prices, evidence), ([], []))

    def test_invalid_price_not_substituted_from_badge(self):
        for price in (None, True, False, 0, -1, float('nan'), float('inf')):
            with self.subTest(price=price):
                document = self.document(price)
                # NaN cannot be compared with itself; retain same value object.
                rows, (_, prices, _, _) = self.evaluate(document)
                self.assertIsNone(rows[0]['price_usd'])
                self.assertEqual(rows[0]['badge'], '')
                self.assertEqual(prices, [])

    def test_explicit_non_usd_or_unknown_currency_not_usd_price(self):
        for currency in ('KRW', 'EUR', '', None):
            with self.subTest(currency=currency):
                document = self.document()
                document['products'][0]['currency'] = currency
                rows, (_, prices, _, _) = self.evaluate(document)
                self.assertIsNone(rows[0]['price_usd'])
                self.assertEqual(rows[0]['badge'], '')
                self.assertEqual(prices, [])

    def test_ai_extracted_not_upgraded(self):
        _, (_, prices, evidence, _) = self.evaluate(self.document(), trust='ai_extracted')
        self.assertEqual((prices, evidence), ([], []))

    def test_curated_input_not_promoted(self):
        document = self.document(); document['source'] = 'curated mirror'
        rows, (_, prices, evidence, _) = self.evaluate(document)
        self.assertEqual((rows, prices, evidence), ([], [], []))


if __name__ == '__main__':
    unittest.main()
