#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한국 화장품 판매처 5곳의 공개 랭킹을 읽어 JSON 하나로 저장한다.

수집 채널 현황의 "국내 판매처 랭킹" 채널 원천이다. 다이소 소싱 후보가 국내에서
지금 무엇과 경쟁하는지(브랜드·가격대·리뷰 수) 보는 용도다.

대상 (2026-10-25 사용자 지정)
  올리브영 · 아모레몰 · 클럽클리오 · 마녀공장 · 화해

지킨 것
  - robots.txt 를 매번 먼저 읽는다. 읽을 경로가 Disallow 면 수집하지 않는다.
  - robots.txt 를 못 읽으면(403, 봇 확인 페이지, 방화벽 차단 문구) 허용으로 치지 않는다.
    2026-10-25 실측: 마녀공장은 방화벽이 HTTP 200 에 "Request Blocked" HTML 을 돌려준다.
    파이썬 RobotFileParser 는 이걸 규칙 없는 파일로 읽어 "전부 허용" 이 된다.
    그래서 본문이 robots 형식인지 따로 검사한다. 조용히 통과하는 것이 가장 나쁘다.
  - 차단을 우회하지 않는다. 올리브영은 봇 확인(403) 이라 blocked 로 남긴다.
  - 읽기 전용. 랭킹 목록 페이지 하나씩만 연다. 로그인·장바구니·검색·API 경로는 안 연다.
  - 못 받은 곳은 items 0건과 사유를 남긴다. 빈 칸을 그럴듯하게 채우지 않는다.
  - 상품 링크를 화면에서 못 얻으면 지어내지 않고 랭킹 페이지 주소를 둔다 (화해).

판단 근거 (2026-10-25 실측)
  화해      /rankings 는 허용 (/hwahae-rank 만 Disallow). HTML 의 __NEXT_DATA__ 에 상위 20개가 글자로 있다.
            브라우저가 필요 없다. 상품 페이지 링크는 HTML 에 없다.
  아모레몰  /kr/ko/display/rank 는 허용. 목록은 스크립트가 그린다 -> 헤들리스 브라우저.
            카드 줄 순서: 순위 / 브랜드 / 상품명 / 정가 / 할인율 / 판매가 / 평점 / (리뷰수)
  클럽클리오 robots 전부 허용. 랭킹 = /shop/goodsList/035000000000000, 카드 = .product__inner.
            검색 레이어(.search_auto_layer) 안의 같은 카드 62개 중 12개는 랭킹이 아니라서 뺀다.
            카드 줄 순서: 순위 / 브랜드 / 상품명 / 판매가 / 정가 / 할인율 / 평점 (리뷰수)
  가격 두 개의 순서가 몰마다 다르다. 그래서 작은 값 = 판매가, 큰 값 = 정가 로 정한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kr_beauty_sellers.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
LIMIT = 20

SOURCES = [
    {"key": "oliveyoung", "name": "올리브영", "base": "https://www.oliveyoung.co.kr",
     "path": "/store/main/getBestList.do", "mode": "browser", "card": None},
    {"key": "amoremall", "name": "아모레몰", "base": "https://www.amoremall.com",
     "path": "/kr/ko/display/rank", "mode": "browser", "card": "amoremall"},
    {"key": "clubclio", "name": "클럽클리오", "base": "https://clubclio.co.kr",
     "path": "/shop/goodsList/035000000000000", "mode": "browser", "card": "clubclio"},
    {"key": "manyo", "name": "마녀공장", "base": "https://www.manyo.co.kr",
     "path": "/", "mode": "browser", "card": None},
    {"key": "hwahae", "name": "화해", "base": "https://www.hwahae.co.kr",
     "path": "/rankings", "mode": "next_data", "card": None},
]

# robots.txt 가 아니라 차단·확인 화면이 왔다는 표지. 실측 문구 그대로다.
BLOCK_MARKERS = ("request blocked", "web firewall", "접속 정보를 확인", "잠시만 기다려", "<html", "<!doctype")
ROBOTS_LINE = re.compile(r"^\s*(user-agent|disallow|allow|sitemap|crawl-delay|host)\s*:", re.I | re.M)

PRICE = re.compile(r"^([\d,]{3,})\s*원?$")
PCT = re.compile(r"^(\d{1,2})%$")
RATING = re.compile(r"^(\d\.\d)(?:\s*\(([\d,]+)\))?$")
REVIEWS = re.compile(r"^\(([\d,]+)\)$")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def robots_verdict(status, body, base, path):
    """(허용 여부, 사유). 못 읽었으면 허용하지 않는다."""
    if status != 200:
        return False, f"robots.txt HTTP {status} — 읽을 수 없어 수집하지 않음 (우회하지 않음)"
    low = body.lower()
    if any(m in low for m in BLOCK_MARKERS) or not ROBOTS_LINE.search(body):
        return False, "robots.txt 대신 차단·봇 확인 화면이 왔다 — 규칙을 확인할 수 없어 수집하지 않음"
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    if not rp.can_fetch("*", base + path):
        return False, f"robots.txt 가 {path} 를 허용하지 않음"
    return True, ""


def check_robots(src):
    try:
        status, body = http_get(src["base"] + "/robots.txt")
    except urllib.error.HTTPError as e:
        status, body = e.code, ""
    except Exception as e:  # noqa: BLE001
        return False, f"robots.txt 요청 실패: {type(e).__name__}"
    return robots_verdict(status, body, src["base"], src["path"])


def num(s):
    return int(s.replace(",", "")) if s else None


def parse_card(lines):
    """카드의 줄 목록 -> 상품 한 건. 순위·브랜드·이름이 없으면 None (상품 카드가 아님)."""
    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    if len(lines) < 4 or not lines[0].isdigit():
        return None
    rank, brand, name = int(lines[0]), lines[1], lines[2]
    prices, pct, rating, reviews = [], None, None, None
    for ln in lines[3:]:
        if m := PRICE.match(ln):
            prices.append(num(m.group(1)))
        elif m := PCT.match(ln):
            pct = int(m.group(1))
        elif m := RATING.match(ln):
            rating = float(m.group(1))
            reviews = num(m.group(2)) if m.group(2) else reviews
        elif m := REVIEWS.match(ln):
            reviews = num(m.group(1))
    if not prices:
        return None
    return {"rank": rank, "brand": brand, "name": name,
            "price_krw": min(prices), "list_price_krw": max(prices) if len(prices) > 1 else None,
            "discount_pct": pct, "rating": rating, "reviews": reviews}


def parse_hwahae(html, page_url):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("__NEXT_DATA__ 없음")
    rp = json.loads(m.group(1))["props"]["pageProps"]["rankingProducts"]
    meta = (rp.get("data") or {}).get("meta") or {}
    items = []
    for i, d in enumerate((rp.get("data") or {}).get("details") or [], 1):
        p, b = d.get("product") or {}, d.get("brand") or {}
        if not p.get("name"):
            continue
        items.append({"rank": i, "brand": b.get("name") or "", "name": p["name"],
                      "price_krw": p.get("price"), "list_price_krw": None, "discount_pct": None,
                      "rating": p.get("review_rating"), "reviews": p.get("review_count"),
                      "package": p.get("package_info") or None, "url": page_url})
    return items, meta.get("last_updated_at")


JS_CARDS = {
    "amoremall": """() => {
      const seen = new Set(); const out = [];
      for (const a of document.querySelectorAll('a[href*="/product/detail?onlineProdSn="]')) {
        const li = a.closest('li'); if (!li) continue;
        const sn = (a.getAttribute('href').match(/onlineProdSn=(\\d+)/) || [])[1];
        if (!sn || seen.has(sn)) continue; seen.add(sn);
        out.push({lines: li.innerText.split('\\n'), url: '/kr/ko/product/detail?onlineProdSn=' + sn});
      }
      return out; }""",
    "clubclio": """() => [...document.querySelectorAll('.product__inner')]
      .filter(e => !e.closest('.search_auto_layer'))
      .map(e => { const a = e.querySelector('a[href*="/shop/goodsView/"]') || e.closest('a[href*="/shop/goodsView/"]');
                  return {lines: e.innerText.split('\\n'), url: a ? a.getAttribute('href') : null}; })""",
}


def collect_browser(page, src):
    url = src["base"] + src["path"]
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    if not src["card"]:
        raise ValueError("카드 규칙 없음")
    items, seen = [], set()
    for raw in page.evaluate(JS_CARDS[src["card"]]):
        it = parse_card(raw["lines"])
        if not it or it["rank"] in seen:
            continue
        seen.add(it["rank"])
        it["url"] = src["base"] + raw["url"] if raw.get("url") else url
        items.append(it)
    items.sort(key=lambda x: x["rank"])
    return items[:LIMIT]


def run():
    out = {"schema_version": 1, "collected_at": now_iso(), "limit_per_source": LIMIT, "sources": []}
    allowed = {}
    for src in SOURCES:
        ok, why = check_robots(src)
        allowed[src["key"]] = (ok, why)
    need_browser = any(allowed[s["key"]][0] and s["mode"] == "browser" for s in SOURCES)
    pw = browser = page = None
    if need_browser:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(user_agent=UA, locale="ko-KR", viewport={"width": 1280, "height": 900}).new_page()
    try:
        for src in SOURCES:
            ok, why = allowed[src["key"]]
            row = {"key": src["key"], "name": src["name"], "site_url": src["base"],
                   "source_url": src["base"] + src["path"], "robots_checked": True,
                   "collected_at": now_iso(), "source_updated_at": None, "items": []}
            if not ok:
                row.update(status="blocked", reason=why)
            else:
                try:
                    if src["mode"] == "next_data":
                        _, html = http_get(row["source_url"])
                        row["items"], row["source_updated_at"] = parse_hwahae(html, row["source_url"])
                    else:
                        row["items"] = collect_browser(page, src)
                    row.update(status="ok" if row["items"] else "empty",
                               reason="" if row["items"] else "랭킹 카드가 한 개도 읽히지 않음")
                except Exception as e:  # noqa: BLE001
                    row.update(status="failed", reason=f"{type(e).__name__}: {str(e)[:160]}")
                    row["items"] = []
            row["count"] = len(row["items"])
            out["sources"].append(row)
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()
    out["ok_sources"] = sum(1 for s in out["sources"] if s["status"] == "ok")
    out["total_items"] = sum(s["count"] for s in out["sources"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    data = run()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for s in data["sources"]:
        print(f'{s["key"]:<11} {s["status"]:<8} {s["count"]:>3}  {s.get("reason", "")}')
    print(f'ok {data["ok_sources"]}/{len(data["sources"])} · items {data["total_items"]}')
    return 0 if data["ok_sources"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
