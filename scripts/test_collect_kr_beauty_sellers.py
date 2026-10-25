#!/usr/bin/env python3
"""collect_kr_beauty_sellers 오프라인 테스트. 네트워크를 쓰지 않는다.

카드 줄과 robots 응답은 2026-10-25 실측 화면에서 그대로 옮겼다.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_kr_beauty_sellers as k  # noqa: E402

AMORE = ["1", "라네즈", "립 슬리핑 마스크 EX 20g", "22,000원", "28%", "15,840원", "4.9", "(17,118)", "사은품", "좋아요"]
CLIO = ["1", "클리오", "[밀착커버] 킬커버 파운웨어 쿠션 기획세트 [본품+리필] [증정] 전용퍼프 2P",
        "27,000", "36,000", "25%", "4.9 (572)", "BEST", "NEW"]
MANYO_WAF = ("Request Blocked(Web Firewall)<br><br><br><Li> Time : 2026-10-25 14:12:47 </Li>"
             "<Li> Host : manyo.co.kr </Li><Li> Url : /robots.txt </Li>")
AMORE_ROBOTS = "User-agent: *\nAllow: /\nDisallow: /kr/ko/api/\nDisallow: /kr/ko/display/search\n"
HWAHAE_ROBOTS = "User-agent: *\nAllow: /\n\nUser-agent: *\nDisallow: /api/\nDisallow: /hwahae-rank\n"


class Card(unittest.TestCase):
    def test_amoremall_order_list_then_sale(self):
        it = k.parse_card(AMORE)
        self.assertEqual((it["rank"], it["brand"], it["price_krw"], it["list_price_krw"]), (1, "라네즈", 15840, 22000))
        self.assertEqual((it["discount_pct"], it["rating"], it["reviews"]), (28, 4.9, 17118))

    def test_clubclio_order_sale_then_list_and_inline_reviews(self):
        it = k.parse_card(CLIO)
        self.assertEqual((it["price_krw"], it["list_price_krw"], it["discount_pct"]), (27000, 36000, 25))
        self.assertEqual((it["rating"], it["reviews"]), (4.9, 572))

    def test_non_product_card_is_dropped(self):
        self.assertIsNone(k.parse_card(["상품 정보", "23,500", "39,000"]))
        self.assertIsNone(k.parse_card(["1", "브랜드", "이름", "좋아요"]))  # 가격 없음

    def test_single_price_has_no_list_price(self):
        it = k.parse_card(["2", "B", "N", "9,900원", "4.8", "(2,040)"])
        self.assertEqual((it["price_krw"], it["list_price_krw"]), (9900, None))


class Robots(unittest.TestCase):
    def test_firewall_200_is_not_allow(self):
        ok, why = k.robots_verdict(200, MANYO_WAF, "https://www.manyo.co.kr", "/")
        self.assertFalse(ok)
        self.assertIn("차단", why)

    def test_403_is_not_allow(self):
        self.assertFalse(k.robots_verdict(403, "", "https://www.oliveyoung.co.kr", "/x")[0])

    def test_allowed_and_disallowed_paths(self):
        self.assertTrue(k.robots_verdict(200, AMORE_ROBOTS, "https://www.amoremall.com", "/kr/ko/display/rank")[0])
        self.assertFalse(k.robots_verdict(200, AMORE_ROBOTS, "https://www.amoremall.com", "/kr/ko/display/search")[0])
        self.assertTrue(k.robots_verdict(200, HWAHAE_ROBOTS, "https://www.hwahae.co.kr", "/rankings")[0])
        self.assertFalse(k.robots_verdict(200, HWAHAE_ROBOTS, "https://www.hwahae.co.kr", "/hwahae-rank")[0])


class Hwahae(unittest.TestCase):
    def test_next_data(self):
        payload = {"props": {"pageProps": {"rankingProducts": {"data": {
            "meta": {"last_updated_at": "2026-10-25T05:00:00"},
            "details": [{"brand": {"name": "몽디에스"}, "product": {"name": "엉덩이 클렌저", "price": 39000,
                         "review_rating": 4.83, "review_count": 326, "package_info": "300ml"}}]}}}}}
        html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload, ensure_ascii=False) + "</script>"
        items, updated = k.parse_hwahae(html, "https://www.hwahae.co.kr/rankings")
        self.assertEqual(updated, "2026-10-25T05:00:00")
        self.assertEqual(items[0]["name"], "엉덩이 클렌저")
        self.assertEqual(items[0]["url"], "https://www.hwahae.co.kr/rankings")  # 링크를 지어내지 않는다
        self.assertIsNone(items[0]["list_price_krw"])

    def test_missing_next_data_fails_loudly(self):
        with self.assertRaises(ValueError):
            k.parse_hwahae("<html></html>", "u")


if __name__ == "__main__":
    unittest.main()
