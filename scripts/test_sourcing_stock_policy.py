"""Pure offline source-stock policy tests: no API requests or product writes."""
import json
from unittest.mock import MagicMock, patch
import unittest
import daiso_daily_beauty_to_shopify as daily


class SourcingStockTests(unittest.TestCase):
    def product(self, **values):
        return dict({'pdNo': '9001', 'pdNm':'Fixture serum', 'pdPrc':'3000',
                     'pdImgUrl':'/fixture.jpg','exhYn':'Y'}, **values)

    def test_unknown_is_research_eligible_but_never_stock_available(self):
        for quantity in (None, '', 'oops', True, False, [], {}, -1, '-1', 1.5):
            with self.subTest(quantity=quantity):
                p = self.product(soldOutYn='N', onlStckQy=quantity)
                self.assertEqual(daily.online_stock_state(p), 'unknown')
                self.assertTrue(daily.sellable(p))
                self.assertEqual(daily.online_stock_draft_reasons(p),
                                 ['supplier_stock_not_gating_sourcing_assumption_draft_only'])
        self.assertTrue(daily.sellable(self.product()))

    def test_explicit_zero_and_soldout_preserved_but_not_sourcing_blockers(self):
        for quantity in (0, '0', '000'):
            p=self.product(soldOutYn='N',onlStckQy=quantity)
            self.assertEqual(daily.online_stock_state(p),'unavailable')
            self.assertTrue(daily.sellable(p))
        self.assertTrue(daily.sellable(self.product(soldOutYn='Y',onlStckQy=10)))

    def test_positive_quantity_needs_explicit_not_soldout_for_available_label(self):
        for quantity in (1, '1', ' 10 '):
            p=self.product(soldOutYn='N',onlStckQy=quantity)
            self.assertEqual(daily.online_stock_state(p),'available')
            self.assertTrue(daily.sellable(p))
            self.assertEqual(daily.online_stock_draft_reasons(p),[])
        self.assertEqual(daily.online_stock_state(self.product(onlStckQy=10)), 'unknown')

    def test_oversized_quantity_text_does_not_crash_or_rewrite_source(self):
        for quantity, expected in (("9" * 5000, "available"), ("0" * 5000, "unavailable"),
                                   ("9" * 5000 + "x", "unknown")):
            p = self.product(soldOutYn="N", onlStckQy=quantity)
            self.assertEqual(daily.online_stock_state(p), expected)
            self.assertTrue(daily.sellable(p))
            self.assertEqual(p["onlStckQy"], quantity)

    def test_other_selection_guards_unchanged(self):
        for values in ({'pdPrc':'0'}, {'pdPrc':'oops'}, {'exhYn':'N'}, {'pdImgUrl':''}):
            self.assertFalse(daily.sellable(self.product(**values)))

    def lookup(self, detail):
        hit=self.product(soldOutYn='N',ONL_STCK_QY=10)
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(hit).encode()
        with patch.object(daily.urllib.request,'urlopen',return_value=response), \
             patch.object(daily,'daiso_post',return_value={'data':detail}):
            return daily.daiso_lookup('9001')

    def test_detail_explicit_zero_never_falls_back_to_positive_search(self):
        p=self.lookup({'pdPrc':3000,'stckQy':0})
        self.assertEqual(p['onlStckQy'],0)
        self.assertTrue(p['_current_detail_available'])
        self.assertTrue(daily.sellable(p))

    def test_detail_unknown_preserved_and_not_disguised_as_zero(self):
        p=self.lookup({'pdPrc':3000,'stckQy':None})
        self.assertIsNone(p['onlStckQy'])
        self.assertTrue(p['_current_detail_available'])
        self.assertTrue(daily.sellable(p))
        self.assertTrue(daily.online_stock_draft_reasons(p))

    def test_detail_price_and_exhibition_still_required(self):
        for detail in ({},{'pdPrc':0},{'pdPrc':3000,'exhYn':'N'}):
            self.assertFalse(self.lookup(detail)['_current_detail_available'])

    def test_score_does_not_gate_on_online_stock_or_mutate_it(self):
        from daiso import score_shopify_demand as scorer
        matches = [{'matched_tokens':['centella','serum'],'similarity':0.8}]
        args = ('시카 수분 세럼', '스킨케어', 99, matches)
        self.assertEqual(scorer.qualify_s(*args,sold_out=True),
                         scorer.qualify_s(*args,sold_out=False))

    def test_runtime_draft_guard_is_wired(self):
        import inspect
        source=inspect.getsource(daily.main)
        self.assertIn('reasons.extend(online_stock_draft_reasons(p))',source)
        self.assertIn('product_accuracy.HOLD_REASON',source)


if __name__=='__main__':
    unittest.main()
