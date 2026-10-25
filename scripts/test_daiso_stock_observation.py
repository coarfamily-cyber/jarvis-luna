"""Offline stock evidence regression; no source requests or Shopify writes."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from daiso import collect_daiso as collector
sys.path.insert(0, str(Path(__file__).parent / 'daiso'))
from daiso import recheck_stock as recheck

URL = 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1068721'
META = ('<meta property="og:title" content="시카 수분 세럼">'
        '<meta property="product:price:amount" content="5000">')


class StockEvidenceTests(unittest.TestCase):
    def test_missing_html_and_generic_shell_are_not_products(self):
        for html in ('', '<script>loadProduct()</script>',
                     '<meta property="og:title" content="다이소몰">'):
            with self.subTest(html=html):
                self.assertIsNone(collector.parse_product('1068721', URL, html))

    def test_metadata_without_stock_is_unknown_not_available(self):
        for body in ('', '<script>loadProduct()</script>', '로그인이 필요합니다',
                     '일시적인 오류가 발생했습니다', '장바구니 구매하기'):
            with self.subTest(body=body):
                row = collector.parse_product('1068721', URL, META + body)
                self.assertFalse(row['sold_out'])
                self.assertEqual(row['stock_note'], '판매 상태 확인 필요')
                self.assertIsNone(row['stock_checked_at'])
                self.assertEqual(row['price_krw'], 5000)
                self.assertTrue(row['collected_at'])  # metadata capture, not stock proof

    def test_observed_soldout_retained(self):
        row = collector.parse_product('1068721', URL, META + '품절')
        self.assertTrue(row['sold_out'])
        self.assertEqual(row['stock_note'], '품절 표시 있음')
        self.assertIsNone(row['stock_checked_at'])

    def test_search_price_is_not_stock_check(self):
        row = collector.merge_search_fallback(None, {'pd_no': '1068721', 'price_krw': 5000})
        self.assertEqual(row['stock_note'], '판매 상태 확인 필요')
        self.assertIsNone(row['stock_checked_at'])

    def run_recheck(self, status, html, sold_out=True):
        with tempfile.TemporaryDirectory() as tmp:
            products, report = Path(tmp)/'products.json', Path(tmp)/'report.json'
            old = {'pd_no':'1068721', 'sold_out': sold_out, 'stock_note':'품절 표시 있음',
                   'stock_checked_at':'2026-09-01T00:00:00+00:00', 'price_krw':5000}
            products.write_text(json.dumps({'products':[old]}))
            output = io.StringIO()
            with patch.object(recheck, 'PRODUCTS', products), patch.object(recheck, 'REPORT', report), \
                 patch.object(recheck, 'pick', return_value=['1068721']), \
                 patch.object(recheck, 'fetch', return_value=(status, html)) as fetch, \
                 patch.object(sys, 'argv', ['recheck_stock']), contextlib.redirect_stdout(output):
                self.assertEqual(recheck.main(), 0)
                fetch.assert_called_once()
            return old, json.loads(products.read_text())['products'][0], output.getvalue()

    def test_http_failure_does_not_refresh_old_observation(self):
        for status in (403, 429, 500):
            with self.subTest(status=status):
                old, new, output = self.run_recheck(status, META)
                self.assertEqual(new, old)
                self.assertNotIn('판매 중', output)

    def test_parse_failure_does_not_refresh_old_observation(self):
        old, new, _ = self.run_recheck(200, '<html></html>')
        self.assertEqual(new, old)

    def test_unknown_does_not_clear_prior_shortage_or_claim_stock_check(self):
        _, new, output = self.run_recheck(200, META)
        self.assertTrue(new['sold_out'])
        self.assertIsNone(new['stock_checked_at'])
        self.assertEqual(new['stock_note'], '판매 상태 확인 필요')
        self.assertNotIn('판매 중', output)

    def test_soldout_recheck_retains_hint_without_claiming_stock_verification(self):
        _, new, _ = self.run_recheck(200, META + '품절', sold_out=False)
        self.assertTrue(new['sold_out'])
        self.assertIsNone(new['stock_checked_at'])


if __name__ == '__main__':
    unittest.main()
