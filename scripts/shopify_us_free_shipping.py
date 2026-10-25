#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""미국행 결제 배송비를 $0 (Free Shipping) 으로 맞춘다.

사용자 결정 (2026-10-25)
  미국 고객에게 결제 화면에서 배송비를 따로 받지 않는다.

왜 무료인가 — 판단 근거
  scripts/pricing_model.py 가 판매가를 이미
      원가 + 우체국 배송비(주문당 최소 ₩9,000) + 관세 + 카드수수료 + 마진
  으로 잡는다. 그 ₩9,000 은 코드에 "고객 청구액이 아니라 원가 계산용"
  (shipping_floor_scope = one_us_outbound_order_not_per_unit_or_customer_charge)
  이라고 적혀 있다.

  그런데 2026-10-25 실측한 스토어 배송 설정은 미국이 "International" 존에
  묶여 결제 때 ₩9,000 고정을 또 받고 있었다. 배송비를 두 번 받은 것이다.
      실측: 일반 프로필 > International 존 (16개국, US 포함) > Standard ₩9000.0 KRW
  가격에 이미 든 배송비를 결제에서 다시 받지 않도록 미국만 분리해 $0 으로 둔다.
  다른 나라 존과 요금은 건드리지 않는다.

  처음엔 무게 구간별 결제 배송비(150g 이하 $7.99 ...)를 제안했다.
  pricing_model.py 를 읽고 이중 청구가 커진다는 것을 확인해 뒤집었다.

동작
  기본은 점검만 한다 (APPLY=0). 현재 상태, 해야 할 일, 결과를 출력한다.
  APPLY=1 일 때만 변경하고, 변경 뒤 다시 읽어 $0 인지 확인한다.
  이미 맞으면 아무것도 바꾸지 않는다 (몇 번 돌려도 같다).

필요 권한: read_shipping, write_shipping (APPLY=1 일 때)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from decimal import Decimal

TARGET_COUNTRY = "US"
US_ZONE_NAME = "United States"
METHOD_NAME = "Free Shipping"
METHOD_DESCRIPTION = "Korea Post from Seoul, tracked. Shipping is included in the item price."
CURRENCY = "USD"

TOK = None


# ---------------------------------------------------------------------------
# Shopify 통신 (shopify_markets_setup.py 와 같은 방식)
# ---------------------------------------------------------------------------
def token() -> str:
    t = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if t:
        return t
    store = os.environ["SHOPIFY_STORE"]
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["SHOPIFY_CLIENT_ID"],
        "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(
        f"https://{store}/admin/oauth/access_token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    scopes = set((d.get("scope") or "").split(","))
    print("token scopes:", ",".join(sorted(s for s in scopes if "shipping" in s)) or "(no shipping scope)")
    return d["access_token"]


def gql(q: str, v: dict | None = None) -> dict:
    global TOK
    TOK = TOK or token()
    store = os.environ["SHOPIFY_STORE"]
    api = os.environ.get("SHOPIFY_API_VERSION", "2025-10")
    req = urllib.request.Request(
        f"https://{store}/admin/api/{api}/graphql.json",
        data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": TOK}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    if d.get("errors"):
        raise RuntimeError(json.dumps(d["errors"], ensure_ascii=False)[:600])
    return d["data"]


PROFILE_Q = """{deliveryProfiles(first:10){nodes{id name default
  profileLocationGroups{locationGroup{id}
    locationGroupZones(first:50){nodes{
      zone{id name countries{code{countryCode restOfWorld}}}
      methodDefinitions(first:20){nodes{id name active
        rateProvider{... on DeliveryRateDefinition{id price{amount currencyCode}}}}}}}}}}}"""


def read_default_profile() -> dict:
    nodes = gql(PROFILE_Q)["deliveryProfiles"]["nodes"]
    for p in nodes:
        if p.get("default"):
            return normalize(p)
    raise RuntimeError("기본 배송 프로필을 찾지 못했다")


# ---------------------------------------------------------------------------
# 순수 로직 (네트워크 없음, 테스트 대상)
# ---------------------------------------------------------------------------
def normalize(p: dict) -> dict:
    """API 응답을 판단에 필요한 최소 구조로 바꾼다."""
    groups = []
    for g in p.get("profileLocationGroups") or []:
        zones = []
        for z in ((g.get("locationGroupZones") or {}).get("nodes") or []):
            zone = z.get("zone") or {}
            methods = []
            for m in ((z.get("methodDefinitions") or {}).get("nodes") or []):
                rp = m.get("rateProvider") or {}
                price = rp.get("price") or {}
                methods.append({
                    "id": m.get("id"), "name": m.get("name"), "active": bool(m.get("active")),
                    "rate_id": rp.get("id"),
                    "amount": price.get("amount"), "currency": price.get("currencyCode"),
                })
            zones.append({
                "id": zone.get("id"), "name": zone.get("name"),
                "countries": [c["code"]["countryCode"] for c in zone.get("countries") or []
                              if (c.get("code") or {}).get("countryCode")],
                "methods": methods,
            })
        groups.append({"id": (g.get("locationGroup") or {}).get("id"), "zones": zones})
    return {"id": p.get("id"), "name": p.get("name"), "groups": groups}


def _is_free(m: dict) -> bool:
    try:
        return m["active"] and m.get("rate_id") is not None and Decimal(str(m["amount"])) == 0
    except Exception:
        return False


def plan(profile: dict, country: str = TARGET_COUNTRY) -> list[dict]:
    """해야 할 일 목록. 이미 맞으면 빈 목록.

    규칙
      1. 미국이 다른 나라와 한 존에 묶여 있으면 그 존에서 미국을 빼고,
         미국만 있는 새 존을 만들어 $0 방법을 단다.
      2. 미국 단독 존이 있는데 유료 방법이 켜져 있으면 끈다.
         $0 방법이 없으면 만든다.
      3. 미국이 어느 존에도 없으면 새 존을 만든다.
    """
    actions: list[dict] = []
    found = False
    for g in profile["groups"]:
        for z in g["zones"]:
            if country not in z["countries"]:
                continue
            found = True
            if len(z["countries"]) > 1:
                actions.append({"op": "remove_country_from_zone", "group_id": g["id"],
                                "zone_id": z["id"], "zone_name": z["name"],
                                "countries_after": [c for c in z["countries"] if c != country]})
                actions.append({"op": "create_free_zone", "group_id": g["id"], "country": country})
            else:
                free = [m for m in z["methods"] if _is_free(m)]
                paid = [m for m in z["methods"] if m["active"] and not _is_free(m)]
                for m in paid:
                    actions.append({"op": "deactivate_method", "group_id": g["id"], "zone_id": z["id"],
                                    "method_id": m["id"], "method_name": m["name"],
                                    "was": f'{m["amount"]} {m["currency"]}'})
                if not free:
                    actions.append({"op": "add_free_method", "group_id": g["id"], "zone_id": z["id"]})
    if not found:
        group_id = profile["groups"][0]["id"] if profile["groups"] else None
        actions.append({"op": "create_free_zone", "group_id": group_id, "country": country})
    return actions


def is_compliant(profile: dict, country: str = TARGET_COUNTRY) -> bool:
    """미국 단독 존에 활성 방법이 있고 전부 $0 이면 참."""
    for g in profile["groups"]:
        for z in g["zones"]:
            if country in z["countries"]:
                active = [m for m in z["methods"] if m["active"]]
                return len(z["countries"]) == 1 and bool(active) and all(_is_free(m) for m in active)
    return False


def free_method_input() -> dict:
    return {"name": METHOD_NAME, "description": METHOD_DESCRIPTION, "active": True,
            "rateDefinition": {"price": {"amount": "0.00", "currencyCode": CURRENCY}}}


# ---------------------------------------------------------------------------
# 변경
# ---------------------------------------------------------------------------
UPDATE_M = """mutation($id:ID!,$profile:DeliveryProfileInput!){
  deliveryProfileUpdate(id:$id,profile:$profile){profile{id} userErrors{field message}}}"""


def _update(profile_id: str, profile_input: dict) -> None:
    d = gql(UPDATE_M, {"id": profile_id, "profile": profile_input})["deliveryProfileUpdate"]
    if d["userErrors"]:
        raise RuntimeError(json.dumps(d["userErrors"], ensure_ascii=False))


def apply(profile: dict, actions: list[dict]) -> None:
    # 한 나라는 한 위치그룹 안에서 두 존에 동시에 있을 수 없다.
    # 그래서 "빼기" 를 먼저 끝낸 뒤 "만들기" 를 따로 보낸다.
    for a in actions:
        if a["op"] == "remove_country_from_zone":
            _update(profile["id"], {"locationGroupsToUpdate": [{"id": a["group_id"], "zonesToUpdate": [{
                "id": a["zone_id"],
                "countries": [{"code": c, "includeAllProvinces": True} for c in a["countries_after"]],
            }]}]})
            print(f'  완료: {a["zone_name"]} 존에서 {TARGET_COUNTRY} 제외')
    for a in actions:
        if a["op"] == "create_free_zone":
            _update(profile["id"], {"locationGroupsToUpdate": [{"id": a["group_id"], "zonesToCreate": [{
                "name": US_ZONE_NAME,
                "countries": [{"code": a["country"], "includeAllProvinces": True}],
                "methodDefinitionsToCreate": [free_method_input()],
            }]}]})
            print(f'  완료: {US_ZONE_NAME} 존 생성, {METHOD_NAME} $0')
        elif a["op"] == "deactivate_method":
            _update(profile["id"], {"locationGroupsToUpdate": [{"id": a["group_id"], "zonesToUpdate": [{
                "id": a["zone_id"], "methodDefinitionsToUpdate": [{"id": a["method_id"], "active": False}],
            }]}]})
            print(f'  완료: 유료 방법 {a["method_name"]} ({a["was"]}) 비활성')
        elif a["op"] == "add_free_method":
            _update(profile["id"], {"locationGroupsToUpdate": [{"id": a["group_id"], "zonesToUpdate": [{
                "id": a["zone_id"], "methodDefinitionsToCreate": [free_method_input()],
            }]}]})
            print(f'  완료: {METHOD_NAME} $0 추가')


def describe(profile: dict) -> None:
    for g in profile["groups"]:
        for z in g["zones"]:
            if TARGET_COUNTRY in z["countries"]:
                rates = ", ".join(f'{m["name"]}={m["amount"]} {m["currency"]}{"" if m["active"] else "(off)"}'
                                  for m in z["methods"]) or "방법 없음"
                print(f'  {TARGET_COUNTRY} 존: {z["name"]} ({len(z["countries"])}개국) · {rates}')
                return
    print(f"  {TARGET_COUNTRY} 가 어느 배송 존에도 없다")


def main() -> int:
    do_apply = os.environ.get("APPLY", "0").strip().lower() in {"1", "true", "yes"}
    profile = read_default_profile()
    print(f'프로필: {profile["name"]}')
    print("현재:")
    describe(profile)

    actions = plan(profile)
    if not actions:
        print("결과: 이미 미국 결제 배송비 $0. 바꿀 것 없음.")
        return 0

    print("해야 할 일:")
    for a in actions:
        print("  -", json.dumps({k: v for k, v in a.items() if not k.endswith("_id")}, ensure_ascii=False))

    if not do_apply:
        print("결과: 점검만 했다 (APPLY=0). 변경 없음.")
        return 0

    apply(profile, actions)
    after = read_default_profile()
    print("변경 후:")
    describe(after)
    if not is_compliant(after):
        print("결과: 실패. 다시 읽은 값이 $0 이 아니다.")
        return 1
    print("결과: 성공. 미국 결제 배송비 $0 확인.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
