# -*- coding: utf-8 -*-
"""shopify_us_free_shipping.py 의 판단 로직 오프라인 검사.

픽스처는 2026-10-25 coarfamily 스토어 기본 배송 프로필을 실제로 읽은 값이다.
존·국가·요금은 그대로 두고, 국가 목록만 판단에 필요한 만큼 줄였다.
"""
import unittest

import shopify_us_free_shipping as s


def _zone(zid, name, countries, methods):
    return {"zone": {"id": zid, "name": name,
                     "countries": [{"code": {"countryCode": c, "restOfWorld": False}} for c in countries]},
            "methodDefinitions": {"nodes": methods}}


def _method(mid, rid, amount, currency, active=True, name="Standard"):
    return {"id": mid, "name": name, "active": active,
            "rateProvider": {"id": rid, "price": {"amount": amount, "currencyCode": currency}}}


GROUP = "gid://shopify/DeliveryLocationGroup/115833274625"

# 2026-10-25 실측: US 가 International 존에 묶여 ₩9000 고정
OBSERVED_2026_10_25 = {
    "id": "gid://shopify/DeliveryProfile/113212326145", "name": "일반 프로필", "default": True,
    "profileLocationGroups": [{
        "locationGroup": {"id": GROUP},
        "locationGroupZones": {"nodes": [
            _zone("gid://shopify/DeliveryZone/465116299521", "Europe (EMS)", ["AT", "BE", "NL"],
                  [_method("gid://shopify/DeliveryMethodDefinition/905882403073",
                           "gid://shopify/DeliveryRateDefinition/836686086401", "27.17", "USD")]),
            _zone("gid://shopify/DeliveryZone/457124512001", "International", ["AE", "AU", "CA", "GB", "US"],
                  [_method("gid://shopify/DeliveryMethodDefinition/852281983233",
                           "gid://shopify/DeliveryRateDefinition/783537012993", "9000.0", "KRW")]),
        ]},
    }],
}


def profile(zones):
    return s.normalize({"id": "p", "name": "x", "default": True, "profileLocationGroups": [
        {"locationGroup": {"id": GROUP}, "locationGroupZones": {"nodes": zones}}]})


class PlanTest(unittest.TestCase):
    def test_observed_store_is_double_charging(self):
        p = s.normalize(OBSERVED_2026_10_25)
        self.assertFalse(s.is_compliant(p))
        acts = s.plan(p)
        self.assertEqual([a["op"] for a in acts], ["remove_country_from_zone", "create_free_zone"])
        self.assertEqual(acts[0]["countries_after"], ["AE", "AU", "CA", "GB"])
        self.assertNotIn("US", acts[0]["countries_after"])

    def test_other_zones_untouched(self):
        acts = s.plan(s.normalize(OBSERVED_2026_10_25))
        touched = {a.get("zone_id") for a in acts}
        self.assertNotIn("gid://shopify/DeliveryZone/465116299521", touched)

    def test_already_free_is_noop(self):
        p = profile([_zone("z", "United States", ["US"], [_method("m", "r", "0.0", "USD", name="Free Shipping")])])
        self.assertTrue(s.is_compliant(p))
        self.assertEqual(s.plan(p), [])

    def test_us_only_zone_with_paid_rate(self):
        p = profile([_zone("z", "United States", ["US"], [_method("m", "r", "9000.0", "KRW")])])
        ops = [a["op"] for a in s.plan(p)]
        self.assertEqual(ops, ["deactivate_method", "add_free_method"])

    def test_paid_rate_disabled_does_not_count(self):
        p = profile([_zone("z", "United States", ["US"], [
            _method("m1", "r1", "9000.0", "KRW", active=False),
            _method("m2", "r2", "0.00", "USD", name="Free Shipping")])])
        self.assertTrue(s.is_compliant(p))
        self.assertEqual(s.plan(p), [])

    def test_us_missing_creates_zone(self):
        p = profile([_zone("z", "Europe", ["NL"], [_method("m", "r", "27.17", "USD")])])
        self.assertEqual([a["op"] for a in s.plan(p)], ["create_free_zone"])

    def test_free_method_is_zero_usd(self):
        m = s.free_method_input()
        self.assertEqual(m["rateDefinition"]["price"], {"amount": "0.00", "currencyCode": "USD"})
        self.assertTrue(m["active"])


if __name__ == "__main__":
    unittest.main()
