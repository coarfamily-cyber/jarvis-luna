#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K-Packet 배송 국가의 결제 배송비를 $0 (Free Shipping) 으로 맞춘다.

파일 이름은 처음(미국 전용)대로 둔다. 워크플로
.github/workflows/owned-shopify-us-free-shipping.yml 가 이 경로를 부른다.

사용자 결정
  2026-10-25 10:10  미국 고객에게 결제 화면에서 배송비를 받지 않는다.
  2026-10-25 10:17  같은 기준을 우체국 K-Packet 이 가는 나라 전부에 적용한다.
                    K-Packet 이 안 가는 나라는 지금 유료 요금을 그대로 둔다.

왜 무료인가 — 판단 근거
  scripts/pricing_model.py 가 판매가를 이미
      원가 + 우체국 배송비(주문당 최소 ₩9,000) + 관세 + 카드수수료 + 마진
  으로 잡는다. 그 ₩9,000 은 코드에 "고객 청구액이 아니라 원가 계산용"
  (shipping_floor_scope = one_us_outbound_order_not_per_unit_or_customer_charge)
  이라고 적혀 있다. 결제에서 또 받으면 배송비를 두 번 받는다.

  2026-10-25 실측 스토어 배송 설정 (변경 전)
      International 존 (US 포함 16개국)          Standard ₩9000.0 KRW
      Europe (EMS) 존 (22개국)                   Standard $27.17
      Rest of World (highest rate) 존 (50개국)   Standard $27.17

왜 K-Packet 국가만인가 — 판단 근거
  가격에 넣은 배송비는 미국 기준이다. 미국은 K-Packet 에서 가장 비싸다.
      우체국 K-Packet 요금 (원, koreapost.go.kr/eng/subIndex/4410.do, 2026-10-25 조회)
                     100g    300g    500g
      미국          8,090  11,060  15,280
      캐나다        5,540   8,920  12,310   ← 미국 다음으로 비싼 나라
      그 외 17개국  4,160~5,510 (100g) · 8,140~12,230 (500g)
  그래서 K-Packet 나라는 미국 기준으로 잡은 가격 안에서 배송비가 충당된다.
  K-Packet 이 안 가는 나라는 항공소포·EMS 로 보내야 해서 0.5kg 에
  ₩13,500 이상이 든다 (우정사업본부 국제소포 요금표). 무료로 하면 손해가 날 수 있다.

  처음엔 무게 구간별 결제 배송비(150g 이하 $7.99 ...)를 제안했다.
  pricing_model.py 를 읽고 이중 청구가 커진다는 것을 확인해 뒤집었다.
  그다음 미국만 무료로 했다가, 위 요금표를 근거로 K-Packet 국가 전체로 넓혔다.

  K-Packet 요금표 20개국 중 중국(CN)·러시아(RU)는 뺐다.
  RU 는 shopify_markets_setup.py 의 SANCTIONED 에 있어 팔지 않는다.
  CN 은 현재 스토어 판매 지역(배송 존)에 없다. 없는 나라를 여기서 새로 열지 않는다.

동작
  기본은 점검만 한다 (APPLY=0). 현재 상태, 해야 할 일, 결과를 출력한다.
  APPLY=1 일 때만 변경하고, 변경 뒤 다시 읽어 확인한다.
  이미 맞으면 아무것도 바꾸지 않는다 (몇 번 돌려도 같다).
  K-Packet 이 아닌 나라의 존·요금은 건드리지 않는다.

필요 권한: read_shipping, write_shipping (APPLY=1 일 때)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from decimal import Decimal

# 우체국 K-Packet 요금표 국가 중 실제로 파는 나라 (CN·RU 제외, 위 주석 참고)
KPACKET_FREE_COUNTRIES = frozenset({
    "US", "CA", "GB", "FR", "DE", "ES", "AU", "NZ", "JP",
    "HK", "TW", "SG", "MY", "TH", "VN", "ID", "PH", "BR",
})
FREE_ZONE_NAME = "K-Packet Free Shipping"
METHOD_NAME = "Free Shipping"
METHOD_DESCRIPTION = "Korea Post K-Packet from Seoul, tracked. Shipping is included in the item price."
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


def _sold_free_countries(profile: dict, free: frozenset) -> list[str]:
    """무료 대상 중 지금 스토어 배송 존에 실제로 있는 나라.

    배송 존에 없는 나라는 판매 지역이 아니다. 여기서 새로 열지 않는다.
    """
    present = {c for g in profile["groups"] for z in g["zones"] for c in z["countries"]}
    return sorted(present & free)


def _target_zone(group: dict, free: frozenset) -> dict | None:
    """무료 존으로 쓸 존. 나라가 전부 무료 대상인 존 중 첫 번째."""
    for z in group["zones"]:
        if z["countries"] and set(z["countries"]) <= free:
            return z
    return None


def plan(profile: dict, free: frozenset = KPACKET_FREE_COUNTRIES) -> list[dict]:
    """해야 할 일 목록. 이미 맞으면 빈 목록.

    규칙 (첫 위치그룹 기준)
      1. 무료 대상 나라와 다른 나라가 섞인 존에서 무료 대상 나라를 뺀다.
         그 존의 나머지 나라와 요금은 그대로 둔다.
      2. 나라가 전부 무료 대상인 존이 있으면 그것을 무료 존으로 쓴다.
         나라 목록을 무료 대상 전체로 맞추고, 유료 방법은 끄고, $0 방법이 없으면 단다.
         그런 존이 둘 이상이면 첫 번째로 모으고 나머지는 지운다.
      3. 그런 존이 없으면 무료 존을 새로 만든다.
    """
    if not profile["groups"]:
        return []
    g = profile["groups"][0]
    targets = _sold_free_countries(profile, free)
    if not targets:
        return []
    target_set = set(targets)
    actions: list[dict] = []

    tz = _target_zone(g, free)
    for z in g["zones"]:
        if tz is not None and z["id"] == tz["id"]:
            continue
        hit = [c for c in z["countries"] if c in target_set]
        if not hit:
            continue
        rest = [c for c in z["countries"] if c not in target_set]
        if rest:
            actions.append({"op": "remove_countries_from_zone", "group_id": g["id"],
                            "zone_id": z["id"], "zone_name": z["name"],
                            "removed": hit, "countries_after": rest})
        else:
            actions.append({"op": "delete_zone", "group_id": g["id"],
                            "zone_id": z["id"], "zone_name": z["name"], "removed": hit})

    if tz is None:
        actions.append({"op": "create_free_zone", "group_id": g["id"], "countries": targets})
        return actions

    if sorted(tz["countries"]) != targets or tz["name"] != FREE_ZONE_NAME:
        actions.append({"op": "set_free_zone_countries", "group_id": g["id"], "zone_id": tz["id"],
                        "zone_name": tz["name"], "countries": targets})
    for m in tz["methods"]:
        if m["active"] and not _is_free(m):
            actions.append({"op": "deactivate_method", "group_id": g["id"], "zone_id": tz["id"],
                            "method_id": m["id"], "method_name": m["name"],
                            "was": f'{m["amount"]} {m["currency"]}'})
    if not any(_is_free(m) for m in tz["methods"]):
        actions.append({"op": "add_free_method", "group_id": g["id"], "zone_id": tz["id"]})
    return actions


def is_compliant(profile: dict, free: frozenset = KPACKET_FREE_COUNTRIES) -> bool:
    """무료 대상 나라가 전부 한 존에만 있고, 그 존의 활성 방법이 전부 $0 이면 참."""
    targets = set(_sold_free_countries(profile, free))
    if not targets:
        return True
    for g in profile["groups"]:
        for z in g["zones"]:
            hit = targets & set(z["countries"])
            if not hit:
                continue
            active = [m for m in z["methods"] if m["active"]]
            if set(z["countries"]) != targets or not active or not all(_is_free(m) for m in active):
                return False
    return True


def free_method_input() -> dict:
    return {"name": METHOD_NAME, "description": METHOD_DESCRIPTION, "active": True,
            "rateDefinition": {"price": {"amount": "0.00", "currencyCode": CURRENCY}}}


def _countries_input(codes: list[str]) -> list[dict]:
    return [{"code": c, "includeAllProvinces": True} for c in codes]


# ---------------------------------------------------------------------------
# 변경
# ---------------------------------------------------------------------------
UPDATE_M = """mutation($id:ID!,$profile:DeliveryProfileInput!){
  deliveryProfileUpdate(id:$id,profile:$profile){profile{id} userErrors{field message}}}"""


def _update(profile_id: str, profile_input: dict) -> None:
    d = gql(UPDATE_M, {"id": profile_id, "profile": profile_input})["deliveryProfileUpdate"]
    if d["userErrors"]:
        raise RuntimeError(json.dumps(d["userErrors"], ensure_ascii=False))


def _zone_update(profile_id: str, group_id: str, zone: dict) -> None:
    _update(profile_id, {"locationGroupsToUpdate": [{"id": group_id, "zonesToUpdate": [zone]}]})


def apply(profile: dict, actions: list[dict]) -> None:
    # 한 나라는 한 위치그룹 안에서 두 존에 동시에 있을 수 없다.
    # 그래서 다른 존에서 "빼기·지우기" 를 먼저 끝낸 뒤 무료 존을 맞춘다.
    pid = profile["id"]
    for a in actions:
        if a["op"] == "remove_countries_from_zone":
            _zone_update(pid, a["group_id"], {"id": a["zone_id"], "countries": _countries_input(a["countries_after"])})
            print(f'  완료: {a["zone_name"]} 존에서 {",".join(a["removed"])} 제외')
        elif a["op"] == "delete_zone":
            _update(pid, {"zonesToDelete": [a["zone_id"]]})
            print(f'  완료: {a["zone_name"]} 존 삭제 ({",".join(a["removed"])} 는 무료 존으로 이동)')
    for a in actions:
        if a["op"] == "create_free_zone":
            _update(pid, {"locationGroupsToUpdate": [{"id": a["group_id"], "zonesToCreate": [{
                "name": FREE_ZONE_NAME, "countries": _countries_input(a["countries"]),
                "methodDefinitionsToCreate": [free_method_input()],
            }]}]})
            print(f'  완료: {FREE_ZONE_NAME} 존 생성 ({len(a["countries"])}개국), {METHOD_NAME} $0')
        elif a["op"] == "set_free_zone_countries":
            _zone_update(pid, a["group_id"], {"id": a["zone_id"], "name": FREE_ZONE_NAME,
                                              "countries": _countries_input(a["countries"])})
            print(f'  완료: {a["zone_name"]} → {FREE_ZONE_NAME} ({len(a["countries"])}개국)')
        elif a["op"] == "deactivate_method":
            _zone_update(pid, a["group_id"], {"id": a["zone_id"], "methodDefinitionsToUpdate": [
                {"id": a["method_id"], "active": False}]})
            print(f'  완료: 유료 방법 {a["method_name"]} ({a["was"]}) 비활성')
        elif a["op"] == "add_free_method":
            _zone_update(pid, a["group_id"], {"id": a["zone_id"], "methodDefinitionsToCreate": [free_method_input()]})
            print(f'  완료: {METHOD_NAME} $0 추가')


def describe(profile: dict) -> None:
    for g in profile["groups"]:
        for z in g["zones"]:
            rates = ", ".join(f'{m["name"]}={m["amount"]} {m["currency"]}{"" if m["active"] else "(off)"}'
                              for m in z["methods"]) or "방법 없음"
            mark = "무료대상" if set(z["countries"]) & KPACKET_FREE_COUNTRIES else "유지"
            print(f'  [{mark}] {z["name"]} ({len(z["countries"])}개국) · {rates}')


def main() -> int:
    do_apply = os.environ.get("APPLY", "0").strip().lower() in {"1", "true", "yes"}
    profile = read_default_profile()
    print(f'프로필: {profile["name"]}')
    print("현재:")
    describe(profile)

    actions = plan(profile)
    if not actions:
        print("결과: 이미 K-Packet 국가 결제 배송비 $0. 바꿀 것 없음.")
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
        print("결과: 실패. 다시 읽은 값이 기준과 다르다.")
        return 1
    print("결과: 성공. K-Packet 국가 결제 배송비 $0 확인.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
