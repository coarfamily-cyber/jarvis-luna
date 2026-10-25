#!/usr/bin/env python3
"""shopify_ai_listing_audit 오프라인 테스트. 상품 값은 2026-10-25 ACTIVE 상품에서 줄여 옮겼다."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shopify_ai_listing_audit as a  # noqa: E402


def variant(title, price, cap=None, w=80):
    return {"title": title, "price": price, "compareAtPrice": cap,
            "inventoryItem": {"countryCodeOfOrigin": "KR", "harmonizedSystemCode": "330499",
                              "measurement": {"weight": {"value": w, "unit": "GRAMS"}}}}


def product(**kw):
    p = {"handle": "boncept-retinol-500-iu-serum-30-ml", "title": "BONCEPT Retinol 500 IU Serum 30 ml",
         "vendor": "BONCEPT", "productType": "Skincare", "status": "ACTIVE", "tags": [],
         "descriptionHtml": ("<p>BONCEPT Retinol 500 IU Serum in a 30 ml bottle.</p><h3>Directions</h3><p>Apply at the serum step.</p>"
                             "<h3>Ingredients</h3><p>Water, Butylene Glycol, Retinol</p>"
                             "<p><strong>Manufacturer / distributor:</strong> Megacos Co., Ltd.</p>"
                             "<p><strong>Country of origin:</strong> Korea</p>"),
         "seo": {"title": "t", "description": "d"}, "media": {"nodes": [{"alt": "photo"}]},
         "variants": {"nodes": [variant("Single (1 pc)", "16.99"), variant("1+1 (2 pcs) - Save 17%", "27.99", "33.98", 160)]}}
    p.update(kw)
    return p


def codes(p):
    return {f["code"] for f in a.check(p)}


class Consistency(unittest.TestCase):
    def test_clean_product_has_no_errors_or_warnings(self):
        self.assertEqual({f["code"] for f in a.check(product()) if f["level"] != "info"}, set())

    def test_compare_at_must_equal_two_singles(self):
        # 실측: BONCEPT 단품 $16.99, 1+1 비교가 $31.98 (단품×2 = $33.98)
        p = product(variants={"nodes": [variant("Single (1 pc)", "16.99"), variant("Two-pack (2 bottles)", "27.99", "31.98", 160)]})
        self.assertIn("compare_at_not_two_singles", codes(p))

    def test_save_label_must_match_price(self):
        p = product(variants={"nodes": [variant("Single (1 pc)", "16.99"), variant("1+1 (2 pcs) - Save 30%", "27.99", "33.98", 160)]})
        self.assertIn("save_label_wrong", codes(p))

    def test_bundle_not_cheaper(self):
        p = product(variants={"nodes": [variant("Single (1 pc)", "10.00"), variant("1+1 (2 pcs)", "20.00", None, 160)]})
        self.assertIn("bundle_not_cheaper", codes(p))

    def test_handle_brand_mismatch(self):
        self.assertIn("handle_brand_mismatch", codes(product(handle="bonsup-retinol-500-iu-serum-30-ml")))

    def test_title_volume_missing_from_body(self):
        p = product(descriptionHtml=product()["descriptionHtml"].replace("30 ml", "50 ml"))
        self.assertIn("net_contents_title_desc_mismatch", codes(p))

    def test_internal_wording_and_hangul(self):
        p = product(descriptionHtml=product()["descriptionHtml"] + "<p>have not yet been verified 확인중</p>")
        self.assertTrue({"internal_review_wording", "hangul_in_customer_text"} <= codes(p))

    def test_origin_in_data_but_not_text(self):
        p = product(descriptionHtml=product()["descriptionHtml"].replace("Country of origin", "Made"))
        self.assertIn("origin_missing_in_text", codes(p))


class Facts(unittest.TestCase):
    def test_only_existing_facts(self):
        p = product(descriptionHtml="<p>X 30 ml</p><h3>Ingredients</h3><p>Please see the product packaging for the full ingredient list.</p>")
        f, missing = a.facts(p)
        self.assertNotIn("key_ingredients", f)
        self.assertIn("key_ingredients", missing)
        self.assertIn("manufacturer", missing)
        html = a.draft_html(p, f)
        self.assertNotIn("Ingredients", html)
        self.assertIn("South Korea", html)

    def test_catalog_label_inconsistency_reported_once(self):
        p2 = product(handle="boncept-x", variants={"nodes": [variant("Single (1 pc)", "16.99"), variant("2-Pack (Save 17%)", "27.99", "33.98", 160)]})
        r = a.audit([product(), p2])
        self.assertEqual(r["bundle_option_labels"], ["1+1 (2 pcs)", "2-Pack"])
        self.assertEqual([c["code"] for c in r["catalog_findings"]], ["option_label_inconsistent"])
        self.assertFalse(any(f["code"] == "option_label_inconsistent" for i in r["items"] for f in i["findings"]))


class Traffic(unittest.TestCase):
    COLS = [{"name": n} for n in ("referrer_name", "landing_page_path", "sessions",
                                  "sessions_with_cart_additions", "sessions_that_completed_checkout")]

    def test_ai_split_and_locale_paths(self):
        rows = [["", "/products/vt-pdrn-radiance-cream-50-ml", "14", "3", "0"],
                ["ChatGPT", "/en/products/vt-pdrn-radiance-cream-50-ml", "2", "1", "1"],
                ["", "/", "236", "0", "0"]]
        r = a.traffic({"columns": self.COLS, "rows": rows})
        pr = r["by_product"]["vt-pdrn-radiance-cream-50-ml"]
        self.assertEqual((pr["ai"]["sessions"], pr["ai"]["checkout_sessions"]), (2, 1))
        self.assertEqual(pr["other"]["cart_rate_pct"], 21.4)
        self.assertTrue(pr["ai"]["small_sample"])
        self.assertEqual(r["totals"]["other"]["sessions"], 250)
        self.assertEqual(r["ai_referrer_names_seen"], ["ChatGPT"])

    def test_zero_ai_is_zero_not_missing(self):
        r = a.traffic({"columns": self.COLS, "rows": [["", "/", "5", "0", "0"]]})
        self.assertEqual(r["totals"]["ai"]["sessions"], 0)
        self.assertIsNone(r["totals"]["ai"]["cart_rate_pct"])

    def test_missing_columns_fail_loudly(self):
        with self.assertRaises(ValueError):
            a.traffic({"columns": [{"name": "sessions"}], "rows": []})


if __name__ == "__main__":
    unittest.main()
