#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 가 상품을 정확히 이해하도록 상품 데이터를 검사한다. 읽기 전용. Shopify 에 쓰지 않는다.

2026-10-25 사용자 지시로 만들었다. 세 가지를 한다.

  audit    상품명·설명·가격·옵션 일관성 검사 + AI 가 읽어야 할 사실(브랜드·제조사·성분·용량·원산지) 누락 검사
  draft    위 사실 중 '상품 데이터에 이미 있는 것' 만 모아 AI 검색용 Key facts 초안을 만든다
  traffic  AI 리퍼러(ChatGPT·Perplexity·Gemini 등) 세션과 장바구니·결제 전환을 상품별로 집계한다

지킨 것
  - 초안은 초안이다. 상품 본문을 바꾸지 않는다. 공개는 사람이 정한다 (GLOSSARY: 사업주 활성화).
  - 초안에는 상품 데이터에서 읽은 값만 넣는다. 없는 칸은 비워 두고 missing 에 적는다.
    효능·순위·인증 같은 주장은 만들지 않는다 (거짓말 데이터 금지).
  - 입력은 Admin GraphQL 상품 응답, ShopifyQL 응답 그대로다. --snapshot 으로 파일을 주면 네트워크를 안 쓴다.
  - AI 유입이 0 이면 0 이라고 적는다. 표본이 작으면 전환율 대신 건수만 본다.

판단 근거 (2026-10-25 ACTIVE 10개 실측)
  - 1+1 옵션 이름이 상품마다 다르다: "1+1 (2 pcs) - Save 13%", "Two-pack (2 bottles)", "2-Pack (Save 12%)", "1+1 (2 pcs)".
    AI 가 같은 구성을 다른 상품으로 읽지 않게 이름을 한 가지로 맞춰야 한다 -> option_label_inconsistent.
  - handle 이 "bonsup-..." 인데 브랜드는 BONCEPT. URL 과 이름이 다른 브랜드를 가리킨다 -> handle_brand_mismatch.
  - 원산지가 변형(countryCodeOfOrigin=KR)에는 있는데 본문에 없는 상품이 있다 -> origin_missing_in_text.
  - Dr.CPU+ 본문에 "have not yet been verified" 가 남아 있다. 고객이 보는 내부 검토 문구다 -> internal_review_wording.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "ai_listing"

# clean_desc 규칙(2026-10-25 설명 정리)에서 쓴 내부 검토 문구와 같은 목록이다.
INTERNAL = re.compile(r"pending|unverified|before publication|provisional|not yet been verified|"
                      r"safety approval|safety assessment|working translation|review required", re.I)
HANGUL = re.compile(r"[가-힣]")
VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G|oz|fl oz)\b")
SAVE = re.compile(r"Save\s+(\d+)%", re.I)
SAVE_PART = re.compile(r"\s*(?:-\s*Save\s+\d+%|\(Save\s+\d+%\))", re.I)
NO_INGREDIENTS = re.compile(r"see the product packaging for the full ingredient list", re.I)
MANUFACTURER = re.compile(r"Manufacturer[^:<]*:\s*(?:</strong>)?\s*([^<]+)", re.I)

AI_REFERRERS = ("chatgpt", "openai", "perplexity", "gemini", "bard", "copilot", "claude",
                "you.com", "phind", "meta.ai", "grok", "deepseek")

# 사업 규칙: 판매 구성은 단품과 1+1 둘뿐 (pricing_model.SELL_QTYS)
CANON_SINGLE = "Single (1 pc)"


def text_of(desc_html):
    t = re.sub(r"<[^>]+>", " ", desc_html or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def volumes(s):
    return {(float(n), u.lower().replace("fl oz", "oz")) for n, u in VOLUME.findall(s or "")}


def variants(p):
    v = p.get("variants") or {}
    return v.get("nodes", v) if isinstance(v, dict) else v


def media(p):
    m = p.get("media") or {}
    return m.get("nodes", m) if isinstance(m, dict) else m


def money(x):
    return float(x) if x not in (None, "") else None


def check(p):
    """상품 하나 -> 발견 목록. 각 발견은 code, level(error/warn/info), detail."""
    out = []

    def add(code, level, detail):
        out.append({"code": code, "level": level, "detail": detail})

    title, vendor, handle = p.get("title") or "", (p.get("vendor") or "").strip(), p.get("handle") or ""
    desc = text_of(p.get("descriptionHtml"))
    vs = variants(p)

    # 1) 이름·URL·브랜드 일관성
    if not vendor:
        add("brand_missing", "error", "vendor(브랜드)가 비어 있다")
    elif not title.lower().startswith(vendor.lower()):
        add("title_brand_mismatch", "warn", f"상품명이 브랜드 '{vendor}' 로 시작하지 않는다")
    first = re.split(r"[^a-z0-9]+", vendor.lower())[0] if vendor else ""
    if first and not handle.startswith(first):
        add("handle_brand_mismatch", "warn", f"URL handle '{handle}' 이 브랜드 '{vendor}' 와 다르다")

    # 2) 용량: 상품명에 적은 용량이 본문에도 있어야 한다
    tv = volumes(title)
    if not tv:
        add("net_contents_missing_in_title", "warn", "상품명에 용량(ml/g)이 없다")
    elif not tv & volumes(desc):
        add("net_contents_title_desc_mismatch", "error", f"상품명 용량 {sorted(tv)} 이 본문에 없다")

    # 3) 가격·옵션
    single = next((v for v in vs if (v.get("title") or "").startswith("Single")), None)
    bundles = [v for v in vs if v is not single]
    if not single:
        add("single_variant_missing", "error", "단품 옵션이 없다")
    if len(vs) != 2:
        add("variant_count", "warn", f"옵션 {len(vs)}개 (기준: 단품 + 1+1)")
    for b in bundles:
        sp, bp, cap = money(single and single.get("price")), money(b.get("price")), money(b.get("compareAtPrice"))
        if sp and bp and bp >= 2 * sp:
            add("bundle_not_cheaper", "error", f"1+1 ${bp} 가 단품 2개 ${2 * sp:.2f} 보다 싸지 않다")
        if sp and cap is not None and abs(cap - 2 * sp) > 0.011:
            add("compare_at_not_two_singles", "error", f"1+1 비교가 ${cap} ≠ 단품×2 ${2 * sp:.2f}")
        m = SAVE.search(b.get("title") or "")
        if m and sp and bp:
            real = int((1 - bp / (2 * sp)) * 100)
            if int(m.group(1)) != real:
                add("save_label_wrong", "error", f"옵션 'Save {m.group(1)}%' 실제 {real}%")
        if m and cap is None:
            add("save_label_without_compare_at", "warn", "옵션에 Save % 가 있는데 비교가가 없다")
        sw = ((single or {}).get("inventoryItem") or {}).get("measurement", {}).get("weight", {}).get("value")
        bw = (b.get("inventoryItem") or {}).get("measurement", {}).get("weight", {}).get("value")
        if sw and bw and abs(bw - 2 * sw) > 0.5:
            add("bundle_weight", "warn", f"1+1 무게 {bw} ≠ 단품×2 {2 * sw}")

    # 4) AI 가 읽어야 할 사실
    inv = [(v.get("inventoryItem") or {}) for v in vs]
    origin = {i.get("countryCodeOfOrigin") for i in inv} - {None}
    if not origin:
        add("origin_missing", "error", "변형에 원산지(countryCodeOfOrigin)가 없다")
    elif not re.search(r"country of (origin|manufacture)", desc, re.I):
        add("origin_missing_in_text", "warn", f"원산지 {sorted(origin)} 가 데이터에는 있는데 본문에 없다")
    if not any(i.get("harmonizedSystemCode") for i in inv):
        add("hs_code_missing", "warn", "HS 코드가 없다")
    if not MANUFACTURER.search(p.get("descriptionHtml") or ""):
        add("manufacturer_missing", "warn", "본문에 제조사 표기가 없다")
    if NO_INGREDIENTS.search(desc) or not re.search(r"ingredients", desc, re.I):
        add("ingredients_missing", "warn", "전성분이 본문에 없다 (포장 참조로 대체)")
    if not re.search(r"how to use|directions", desc, re.I):
        add("directions_missing", "warn", "사용법이 없다")
    if not p.get("productType"):
        add("product_type_missing", "warn", "productType 이 비어 있다")
    seo = p.get("seo") or {}
    if not seo.get("description"):
        add("seo_description_missing", "warn", "SEO 설명이 없다")
    if not seo.get("title"):
        add("seo_title_default", "info", "SEO 제목이 비어 있어 상품명이 그대로 쓰인다")
    alts = [m.get("alt") for m in media(p)]
    if not alts:
        add("no_images", "error", "이미지가 없다")
    elif any(not a for a in alts):
        add("image_alt_missing", "warn", f"대체 텍스트 없는 이미지 {sum(1 for a in alts if not a)}장")

    # 5) 고객에게 보이면 안 되는 것
    for label, s in (("title", title), ("본문", desc), ("SEO", seo.get("description") or "")):
        if HANGUL.search(s):
            add("hangul_in_customer_text", "error", f"{label}에 한글이 남아 있다")
        if m := INTERNAL.search(s):
            add("internal_review_wording", "error", f"{label}에 내부 검토 문구 '{m.group(0)}'")
    if p.get("status") == "ACTIVE" and any(t.startswith("draft-") for t in p.get("tags") or []):
        add("active_with_draft_tags", "info", "판매중인데 draft-* 태그가 남아 있다 (고객에게는 안 보임)")
    return out


def facts(p):
    """상품 데이터에 이미 있는 사실만 모은다. 못 찾은 것은 missing."""
    desc_html = p.get("descriptionHtml") or ""
    desc = text_of(desc_html)
    vs = variants(p)
    f, missing = {}, []

    def put(k, v):
        (f.__setitem__(k, v) if v else missing.append(k))

    put("brand", (p.get("vendor") or "").strip())
    put("product_type", p.get("productType"))
    tv = sorted(volumes(p.get("title")))
    put("net_contents", f"{tv[0][0]:g} {tv[0][1]}" if tv else None)
    origin = sorted({(v.get("inventoryItem") or {}).get("countryCodeOfOrigin") for v in vs} - {None})
    put("country_of_origin", {"KR": "South Korea"}.get(origin[0], origin[0]) if origin else None)
    m = MANUFACTURER.search(desc_html)
    put("manufacturer", html.unescape(m.group(1)).strip() if m else None)
    ing = re.search(r"Ingredients(?: \(INCI\))?:?\s*(.+?)(?: Ingredients may vary| Product details| Manufacturer|$)", desc)
    ing_txt = ing.group(1).strip() if ing and not NO_INGREDIENTS.search(ing.group(1)) else ""
    put("key_ingredients", ", ".join([x.strip() for x in ing_txt.split(",")][:6]) if ing_txt else None)
    d = re.search(r"(?:How to use|Directions(?: \([^)]*\))?)\s*:?\s*(.+?)(?: Always follow| Cautions| Frequently| Ingredients|$)", desc)
    put("how_to_use", d.group(1).strip() if d else None)
    opts = [{"option": v.get("title"), "price_usd": money(v.get("price"))} for v in vs]
    put("pack_options", opts if opts else None)
    return f, missing


def draft_html(p, f):
    """Key facts 초안. 값이 있는 줄만 쓴다. 상품에 반영하지 않는다."""
    rows = [("Brand", f.get("brand")), ("Product type", f.get("product_type")),
            ("Net contents", f.get("net_contents")), ("Country of origin", f.get("country_of_origin")),
            ("Manufacturer", f.get("manufacturer")), ("Key ingredients (first listed)", f.get("key_ingredients")),
            ("How to use", f.get("how_to_use"))]
    li = "".join(f"<li><strong>{html.escape(k)}:</strong> {html.escape(str(v))}</li>" for k, v in rows if v)
    packs = f.get("pack_options") or []
    if packs:
        li += "<li><strong>Options:</strong> " + "; ".join(
            f"{html.escape(o['option'])} ${o['price_usd']:.2f}" for o in packs if o["price_usd"] is not None) + "</li>"
    return f"<h3>Key facts</h3><ul>{li}</ul>"


def audit(products):
    # 1+1 옵션 이름은 상품 하나가 아니라 카탈로그 전체의 문제라서 상품별이 아니라 여기서 한 번만 센다.
    # (처음엔 상품마다 붙였더니 10개 전부에 같은 경고가 떠서 진짜 문제가 묻혔다.)
    labels = {SAVE_PART.sub("", v.get("title") or "").strip() for p in products
              for v in variants(p) if not (v.get("title") or "").startswith("Single")}
    rows = []
    for p in products:
        fs = check(p)
        f, missing = facts(p)
        rows.append({"handle": p.get("handle"), "title": p.get("title"), "status": p.get("status"),
                     "errors": sum(1 for x in fs if x["level"] == "error"),
                     "warnings": sum(1 for x in fs if x["level"] == "warn"),
                     "findings": fs, "facts": f, "facts_missing": missing,
                     "ai_readiness_pct": round(100 * len(f) / (len(f) + len(missing))),
                     "key_facts_draft_html": draft_html(p, f)})
    codes = {}
    for r in rows:
        for x in r["findings"]:
            codes[x["code"]] = codes.get(x["code"], 0) + 1
    catalog = []
    if len(labels) > 1:
        catalog.append({"code": "option_label_inconsistent", "level": "warn",
                        "detail": f"1+1 옵션 이름이 {len(labels)}가지: {sorted(labels)}"})
    return {"products": len(rows), "bundle_option_labels": sorted(labels), "catalog_findings": catalog,
            "errors": sum(r["errors"] for r in rows), "warnings": sum(r["warnings"] for r in rows),
            "finding_counts": dict(sorted(codes.items(), key=lambda kv: -kv[1])),
            "avg_ai_readiness_pct": round(sum(r["ai_readiness_pct"] for r in rows) / len(rows)) if rows else None,
            "items": rows}


def product_handle(path):
    m = re.match(r"^(?:/[a-z]{2}(?:-[a-z]{2})?)?/products/([^/?#]+)", path or "")
    return m.group(1) if m else None


def is_ai(name):
    n = (name or "").lower()
    return any(k in n for k in AI_REFERRERS)


def traffic(shopifyql):
    """ShopifyQL 결과(referrer_name, landing_page_path, sessions, carts, checkouts) -> 상품별 AI/기타 집계."""
    cols = [c["name"] for c in shopifyql.get("columns", [])]
    need = {"referrer_name", "landing_page_path", "sessions", "sessions_with_cart_additions", "sessions_that_completed_checkout"}
    if not need <= set(cols):
        raise ValueError(f"ShopifyQL 열이 부족하다: {sorted(need - set(cols))}")
    agg, total = {}, {"ai": [0, 0, 0], "other": [0, 0, 0]}
    ai_names = set()
    for row in shopifyql.get("rows", []):
        r = dict(zip(cols, row))
        kind = "ai" if is_ai(r["referrer_name"]) else "other"
        if kind == "ai":
            ai_names.add(r["referrer_name"])
        nums = [int(r["sessions"]), int(r["sessions_with_cart_additions"]), int(r["sessions_that_completed_checkout"])]
        total[kind] = [a + b for a, b in zip(total[kind], nums)]
        h = product_handle(r["landing_page_path"])
        if h:
            slot = agg.setdefault(h, {"ai": [0, 0, 0], "other": [0, 0, 0]})
            slot[kind] = [a + b for a, b in zip(slot[kind], nums)]

    def shape(t):
        s, c, k = t
        # 세션 30 미만이면 전환율은 의미가 약하다. 값은 주되 표본 크기를 같이 둔다.
        return {"sessions": s, "cart_sessions": c, "checkout_sessions": k,
                "cart_rate_pct": round(100 * c / s, 1) if s else None,
                "checkout_rate_pct": round(100 * k / s, 1) if s else None, "small_sample": s < 30}

    return {"rows_read": len(shopifyql.get("rows", [])), "ai_referrer_names_seen": sorted(ai_names),
            "ai_patterns": list(AI_REFERRERS), "totals": {k: shape(v) for k, v in total.items()},
            "by_product": {h: {k: shape(v) for k, v in d.items()}
                           for h, d in sorted(agg.items(), key=lambda kv: -(kv[1]["ai"][0] + kv[1]["other"][0]))}}


TRAFFIC_QL = ("FROM sessions SHOW sessions, sessions_with_cart_additions, sessions_that_completed_checkout "
              "GROUP BY referrer_name, landing_page_path SINCE -90d UNTIL today ORDER BY sessions DESC LIMIT 1000")
PRODUCTS_GQL = """query($after:String){ products(first:50, after:$after, query:"status:active"){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle title vendor productType tags status descriptionHtml seo{title description}
    media(first:10){nodes{alt mediaContentType}} options{name values}
    variants(first:10){nodes{title price compareAtPrice sku
      inventoryItem{countryCodeOfOrigin harmonizedSystemCode measurement{weight{value unit}}}}} } } }"""


def live_products():
    """읽기 전용 조회. 인증은 기존 AEO 검사기의 흐름을 그대로 쓴다 (범위를 넓히지 않는다)."""
    import urllib.request  # noqa: PLC0415
    import apply_shopify_aeo_and_obsidian as aeo  # noqa: PLC0415
    token = aeo.resolve_token()
    if not token:
        raise RuntimeError("Shopify 인증 정보가 없다 (SHOPIFY_CLIENT_ID/SECRET 또는 SHOPIFY_ADMIN_TOKEN)")
    # aeo.shopify_request 는 GET 만 허용한다. GraphQL 은 POST 라서 여기서 보내되,
    # 보낼 수 있는 것은 위에 고정한 읽기 질의(PRODUCTS_GQL) 하나뿐이다. mutation 은 보낼 길이 없다.
    assert PRODUCTS_GQL.lstrip().startswith("query")
    url = f"https://{aeo.STORE_DOMAIN}/admin/api/{aeo.API_VERSION}/graphql.json"
    out, after = [], None
    while True:
        body = json.dumps({"query": PRODUCTS_GQL, "variables": {"after": after}}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "X-Shopify-Access-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        if r.get("errors"):
            raise RuntimeError(f"GraphQL 오류: {str(r['errors'])[:200]}")
        page = r["data"]["products"]
        out += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("audit", "traffic"))
    ap.add_argument("--snapshot", help="audit: products 응답 JSON / traffic: ShopifyQL 응답 JSON")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if a.cmd == "audit":
        if a.snapshot:
            raw = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
            products = raw.get("data", raw).get("products", raw)
            products = products.get("nodes", products) if isinstance(products, dict) else products
            src = f"snapshot:{Path(a.snapshot).name}"
        else:
            products, src = live_products(), "live:admin-graphql"
        result = dict(audit(products), generated_at=now, source=src, writes_to_shopify=False)
        print(f'products {result["products"]} · errors {result["errors"]} · warnings {result["warnings"]} '
              f'· AI 준비도 평균 {result["avg_ai_readiness_pct"]}%')
        for c in result["catalog_findings"]:
            print(f'  카탈로그 {c["code"]}: {c["detail"]}')
        for code, n in result["finding_counts"].items():
            print(f"  {n:>3}  {code}")
    else:
        if not a.snapshot:
            raise SystemExit("traffic 은 ShopifyQL 응답 JSON 이 필요하다 (--snapshot). 질의문:\n" + TRAFFIC_QL)
        raw = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
        result = dict(traffic(raw), generated_at=now, query=raw.get("query", TRAFFIC_QL),
                      source=f"snapshot:{Path(a.snapshot).name}")
        t = result["totals"]
        print(f'AI 유입 세션 {t["ai"]["sessions"]} · 기타 {t["other"]["sessions"]} · 상품 페이지 {len(result["by_product"])}개')
    out = Path(a.out) if a.out else OUT_DIR / f"{a.cmd}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
