"""Offline integration fixtures: no provider/Shopify calls or real data writes."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import fetch_fx_rate as fetch
import pricing_model as pricing
import generate_dashboard_runtime as dashboard
import sync_channels as sync

NOW=datetime.now(timezone.utc)
def observation(days=0,rate=1326.14):
    at=NOW-timedelta(days=days)
    return {'ok':True,'usd_to_krw':rate,'as_of':at.date().isoformat(),
            'source':'ExchangeRate-API','api_url':'https://open.er-api.com/v6/latest/USD',
            'fetched_at':at.isoformat()}

class ShippingFloorTests(unittest.TestCase):
    def test_floor_once_per_order_1_2_5_and_not_weight_or_product_cost(self):
        p={'pd_no':'fixture','name':'Cream 30 ml','price_krw':5000}
        with patch.object(pricing,'ship_krw',return_value=8000),patch.object(pricing,'MEASURED',{}),patch.object(pricing,'GOSI_VOL',{}):
            rows=[pricing.analyze(p,1000,n,{'p25':20,'median':25}) for n in (1,2,5)]
        for n,row in zip((1,2,5),rows):
            self.assertEqual(row['shipping_order_krw'],9000)
            self.assertEqual(row['shipping_order_usd'],9)
            self.assertEqual(row['shipping_unit_usd'],round(9/n,2))
            self.assertEqual(row['unit_cost_usd'],5)
            self.assertEqual(row['shipping_weight_estimate_krw'],8000)
            self.assertFalse(row['full_profit_verified'])
            self.assertFalse(row['shipping_quote_verified'])
        self.assertEqual(len({row['weight_g_est'] for row in rows}),1)
    def test_carrier_estimate_above_floor_not_reduced(self):
        with patch.object(pricing,'ship_krw',return_value=12000):
            row=pricing.analyze({'name':'Cream','price_krw':5000},1000,2,{'p25':20,'median':25})
        self.assertEqual(row['shipping_order_krw'],12000)
    def test_invalid_order_or_fx_fail_closed(self):
        for n in (0,-1,True,1.5):
            with self.assertRaises(ValueError):pricing.analyze({},1000,n,{})
        for rate in (True,0,float('nan'),float('inf')):
            with self.assertRaises(ValueError):pricing.analyze({},rate,1,{})

class FxIntegrationTests(unittest.TestCase):
    def test_provider_date_never_filled_with_today(self):
        data={'base':'USD','rates':{'KRW':1326.14}}
        with patch.object(fetch,'get',return_value=(200,json.dumps(data))):
            result=fetch.fetch_fx()
        self.assertFalse(result['ok']);self.assertIsNone(result['as_of'])
    def test_unknown_currency_and_nonfinite_rate_rejected(self):
        for changes in ({'base':'EUR'},{'base':None},{'rates':{'KRW':True}},{'rates':{'KRW':float('inf')}}):
            data={'base':'USD','rates':{'KRW':1326.14},'date':NOW.date().isoformat()};data.update(changes)
            with patch.object(fetch,'get',return_value=(200,json.dumps(data))):result=fetch.fetch_fx()
            self.assertFalse(result['ok'])
    def test_impossible_date_and_trailing_text_not_accepted(self):
        for value in ('2026-02-30','2026-10-24 garbage','Sat, 24 Oct 2026 00:00:00 +0000 trailing','',None,True):self.assertEqual(fetch.as_date(value),'')
        self.assertEqual(fetch.as_date('Sat, 24 Oct 2026 00:00:00 +0000'),'2026-10-24')
        self.assertEqual(fetch.as_date('Sat, 24 Oct 2026 00:00:00 +0900'),'2026-10-23')
    def test_failed_fetch_preserves_valid_cache_without_new_fetched_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json';old=observation(1);path.write_text(json.dumps({'fx':old,'other':'keep'}))
            with patch.object(fetch,'STATUS',path),patch.object(fetch,'fetch_fx',return_value={'ok':False,'usd_to_krw':None}):
                self.assertEqual(fetch.main(),1)
            saved=json.loads(path.read_text());self.assertEqual(saved['other'],'keep')
            self.assertEqual(saved['fx']['fetched_at'],old['fetched_at'])
            self.assertEqual(saved['fx']['freshness_state'],'cached')
            self.assertFalse(saved['fx']['last_attempt_ok'])
    def test_duplicate_writer_cannot_move_date_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'daiso_real').mkdir();path=root/'daiso_real/collection_status.json'
            old=observation(0);path.write_text(json.dumps({'fx':old}))
            response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            response.read.return_value=json.dumps({'base_code':'USD','rates':{'KRW':1200},'date':observation(2)['as_of']}).encode()
            with patch.object(sync,'DATA',root),patch.object(sync.urllib.request,'urlopen',return_value=response):result=sync.fetch_and_update_fx_status()
            self.assertEqual(result['as_of'],old['as_of']);self.assertEqual(result['fetched_at'],old['fetched_at'])
            self.assertEqual(result['usd_to_krw'],old['usd_to_krw'])
    def test_dashboard_reads_canonical_not_older_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data/daiso_real').mkdir(parents=True)
            (root/'data/dashboard_runtime.json').write_text(json.dumps({'exchange_rate':{'rate':1347.39,'as_of':'2026-10-03'}}))
            path=root/'data/daiso_real/collection_status.json';path.write_text(json.dumps({'fx':observation(1)}))
            result=dashboard.load_canonical_fx_card(root,NOW)
            self.assertEqual(result['rate'],1326.14);self.assertFalse(result['stale'])
            path.write_text(json.dumps({'fx':observation(10)}));result=dashboard.load_canonical_fx_card(root,NOW)
            self.assertEqual(result['rate'],1326.14);self.assertEqual(result['state'],'stale')
            path.write_text(json.dumps({'fx':{'ok':True,'usd_to_krw':1326.14}}))
            self.assertEqual(dashboard.load_canonical_fx_card(root,NOW)['state'],'invalid')

if __name__=='__main__':unittest.main()
