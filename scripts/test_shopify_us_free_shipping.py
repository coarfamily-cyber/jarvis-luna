# -*- coding: utf-8 -*-
"""shopify_us_free_shipping.py 의 판단 로직 오프라인 검사.

픽스처는 coarfamily 스토어 기본 배송 프로필을 실제로 읽은 값이다 (2026-10-25).
존 이름·국가·요금·ID 는 읽은 그대로 쓴다.
"""
import unittest

import shopify_us_free_shipping as s

GROUP = "gid://shopify/DeliveryLocationGroup/115833274625"
PROFILE = "gid://shopify/DeliveryProfile/113212326145"

EUROPE = "AT BE BG CY CZ DK EE FI GR HR HU IE LT LU LV NL PL PT RO SE SI SK".split()
INTERNATIONAL_AFTER_US_SPLIT = "AE AU CA CH DE ES FR GB HK IL JP MY NO NZ SG".split()
REST_OF_WORLD = ("AM AR BH BO BR BZ CL CO CR DO EC EG GE GH GT GY HN ID IN IQ IS IT JM JO KE KW KZ "
                 "LB MA MT MX NG NI OM PA PE PH PY QA SA SV TH TR TT TW UA UY VE VN ZA").split()


def _zone(zid, name, countries, methods):
    return {"zone": {"id": zid, "name": name,
                     "countries": [{"code": {"countryCode": c, "restOfWorld": False}} for c in countries]},
            "methodDefinitions": {"nodes": methods}}


def _method(mid, rid, amount, currency, active=True, name="Standard"):
    return {"id": mid, "name": name, "active": active,
            "rateProvider": {"id": rid, "price": {"amount": amount, "currencyCode": currency}}}


def _profile(zones):
    return s.normalize({"id": PROFILE, "name": "일반 프로필", "default": True,
                        "profileLocationGroups": [{"locationGroup": {"id": GROUP},
                                                   "locationGroupZones": {"nodes": zones}}]})


EUROPE_ZONE = _zone("gid://shopify/DeliveryZone/465116299521", "Europe (EMS)", EUROPE,
                    [_method("gid://shopify/DeliveryMethodDefinition/905882403073",
                             "gid://shopify/DeliveryRateDefinition/836686086401", "27.17", "USD")])
ROW_ZONE = _zone("gid://shopify/DeliveryZone/465156538625", "Rest of World (highest rate)", REST_OF_WORLD,
                 [_method("gid://shopify/DeliveryMethodDefinition/905946497281",
                          "gid://shopify/DeliveryRateDefinition/836749885697", "27.17", "USD")])


def intl_zone(countries):
    return _zone("gid://shopify/DeliveryZone/457124512001", "International", countries,
                 [_method("gid://shopify/DeliveryMethodDefinition/852281983233",
                          "gid://shopify/DeliveryRateDefinition/783537012993", "9000.0", "KRW")])


US_ZONE = _zone("gid://shopify/DeliveryZone/466322227457", "United States", ["US"],
                [_method("gid://shopify/DeliveryMethodDefinition/912345235713",
                         "gid://shopify/DeliveryRateDefinition/843325964545", "0.0", "USD", name="Free Shipping")])

# 2026-10-25 10:0x 실측: US 가 International 에 묶여 ₩9000
BEFORE_ANY = _profile([EUROPE_ZONE, intl_zone(INTERNATIONAL_AFTER_US_SPLIT + ["US"]), ROW_ZONE])
# 2026-10-25 10:1x 실측: US 단독 존 $0 (1차 반영 직후)
AFTER_US_SPLIT = _profile([EUROPE_ZONE, intl_zone(INTERNATIONAL_AFTER_US_SPLIT), ROW_ZONE, US_ZONE])

KPACKET_IN_STORE = sorted(s.KPACKET_FREE_COUNTRIES)


class KPacketSetTest(unittest.TestCase):
    def test_eighteen_countries_without_cn_ru_kr(self):
        self.assertEqual(len(s.KPACKET_FREE_COUNTRIES), 18)
        for c in ("CN", "RU", "KR"):
            self.assertNotIn(c, s.KPACKET_FREE_COUNTRIES)

    def test_all_free_countries_are_sold_today(self):
        present = set(EUROPE + INTERNATIONAL_AFTER_US_SPLIT + REST_OF_WORLD + ["US"])
        self.assertTrue(s.KPACKET_FREE_COUNTRIES <= present)


class PlanFromUsSplitTest(unittest.TestCase):
    def setUp(self):
        self.acts = s.plan(AFTER_US_SPLIT)
        self.by_op = {}
        for a in self.acts:
            self.by_op.setdefault(a["op"], []).append(a)

    def test_not_compliant_yet(self):
        self.assertFalse(s.is_compliant(AFTER_US_SPLIT))

    def test_international_keeps_only_non_kpacket(self):
        intl = [a for a in self.by_op["remove_countries_from_zone"] if a["zone_name"] == "International"][0]
        self.assertEqual(intl["countries_after"], ["AE", "CH", "IL", "NO"])

    def test_rest_of_world_loses_only_kpacket(self):
        row = [a for a in self.by_op["remove_countries_from_zone"] if a["zone_name"].startswith("Rest")][0]
        self.assertEqual(sorted(row["removed"]), ["BR", "ID", "PH", "TH", "TW", "VN"])
        self.assertEqual(len(row["countries_after"]), len(REST_OF_WORLD) - 6)

    def test_europe_untouched(self):
        touched = {a.get("zone_name") for a in self.acts}
        self.assertNotIn("Europe (EMS)", touched)

    def test_us_zone_becomes_free_zone(self):
        z = self.by_op["set_free_zone_countries"][0]
        self.assertEqual(z["zone_id"], "gid://shopify/DeliveryZone/466322227457")
        self.assertEqual(z["countries"], KPACKET_IN_STORE)
        self.assertNotIn("deactivate_method", self.by_op)
        self.assertNotIn("add_free_method", self.by_op)
        self.assertNotIn("create_free_zone", self.by_op)

    def test_removals_listed_before_free_zone(self):
        ops = [a["op"] for a in self.acts]
        self.assertLess(max(i for i, o in enumerate(ops) if o == "remove_countries_from_zone"),
                        ops.index("set_free_zone_countries"))


class PlanOtherStatesTest(unittest.TestCase):
    def test_from_original_store_creates_free_zone(self):
        ops = [a["op"] for a in s.plan(BEFORE_ANY)]
        self.assertEqual(ops.count("remove_countries_from_zone"), 2)
        self.assertEqual(ops[-1], "create_free_zone")

    def test_target_state_is_noop(self):
        done = _profile([
            EUROPE_ZONE, intl_zone(["AE", "CH", "IL", "NO"]),
            _zone(ROW_ZONE["zone"]["id"], ROW_ZONE["zone"]["name"],
                  [c for c in REST_OF_WORLD if c not in s.KPACKET_FREE_COUNTRIES], ROW_ZONE["methodDefinitions"]["nodes"]),
            _zone(US_ZONE["zone"]["id"], s.FREE_ZONE_NAME, KPACKET_IN_STORE, US_ZONE["methodDefinitions"]["nodes"]),
        ])
        self.assertTrue(s.is_compliant(done))
        self.assertEqual(s.plan(done), [])

    def test_paid_rate_in_free_zone_is_turned_off(self):
        p = _profile([_zone("z", s.FREE_ZONE_NAME, KPACKET_IN_STORE, [_method("m", "r", "9000.0", "KRW")])])
        self.assertEqual([a["op"] for a in s.plan(p)], ["deactivate_method", "add_free_method"])

    def test_disabled_paid_rate_does_not_count(self):
        p = _profile([_zone("z", s.FREE_ZONE_NAME, KPACKET_IN_STORE, [
            _method("m1", "r1", "9000.0", "KRW", active=False),
            _method("m2", "r2", "0.00", "USD", name="Free Shipping")])])
        self.assertTrue(s.is_compliant(p))

    def test_country_not_sold_is_not_opened(self):
        p = _profile([_zone("z", "United States", ["US"], [_method("m", "r", "0.0", "USD", name="Free Shipping")])])
        acts = s.plan(p)
        self.assertEqual(acts[0]["countries"], ["US"]) if acts else self.assertTrue(s.is_compliant(p))

    def test_free_method_is_zero_usd(self):
        m = s.free_method_input()
        self.assertEqual(m["rateDefinition"]["price"], {"amount": "0.00", "currencyCode": "USD"})


if __name__ == "__main__":
    unittest.main()
