"""BUYMA Personal Shopper API preparation and offline lifecycle rehearsal.

No HTTP client, credential loading, OAuth flow or live dispatcher is installed.
Only FixtureResponse can cross the rehearsal boundary. Core execution authority
is unchanged. See docs/operations/buyma-adapter.md for the connection checklist.
"""
from __future__ import annotations

import argparse
import base64
import copy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
import hmac
import ipaddress
import itertools
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from jarvis_execution import ExecutionStore, canonical, digest

ENDPOINTS = {
    "production": "https://personal-shopper-api.buyma.com/api/v1/products.json",
    "sandbox": "https://sandbox.personal-shopper-api.buyma.com/api/v1/products.json",
}
TOKEN_HEADER = "X-Buyma-Personal-Shopper-Api-Access-Token"
REQUIRED = {"control", "reference_number", "name", "comments", "brand_id",
            "category_id", "price", "available_until", "buying_area_id",
            "shipping_area_id", "images", "shipping_methods", "options", "variants"}
OPTIONAL = {"brand_name", "model_id", "theme_id", "season_id", "regular_price",
            "reference_price", "buying_shop_name", "buyer_notes", "duty", "tags",
            "style_numbers", "size_unit", "colorsize_comments", "order_quantity", "shop_urls"}
BUSINESS_HOLDS = ["buyma_connection_unverified", "buyma_fee_revision_unverified",
                  "japan_shipping_cost_unverified", "japan_market_price_unverified",
                  "buyma_legal_and_publication_clearance_unverified"]


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def integer(value, minimum=1):
    return type(value) is int and value >= minimum


def timestamp(value):
    need(isinstance(value, str), "timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise ValueError("invalid_timestamp") from None
    need(parsed.tzinfo is not None, "timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: need(False, "nonfinite_json_number"))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise ValueError("invalid_webhook_json") from None


def reference_number(product):
    """Use the existing never-reassigned CP, not title, price or array position."""
    cp = product.get("canonical_product_id")
    need(isinstance(cp, str) and re.fullmatch(r"CP\d{6}", cp), "canonical_product_id_required")
    # Product Master also retains B2026... source identifiers; do not invent a
    # numeric-only identity contract or silently coerce/reassign those products.
    need(isinstance(product.get("pd_no"), str) and re.fullmatch(r"[A-Za-z0-9]+", product["pd_no"]),
         "pd_no_required")
    return "jarvis-" + cp


def validate_payload(payload, *, today):
    """Conservative local subset; BUYMA still performs asynchronous validation.

    Master-ID existence, public image accessibility and category-specific rules
    require separately supplied evidence; structural validity is not clearance.
    """
    need(type(payload) is dict and set(payload) == {"product"}, "product_envelope_required")
    p = payload["product"]
    need(type(p) is dict, "product_object_required")
    need(REQUIRED <= set(p), "required_product_fields_missing:" + ",".join(sorted(REQUIRED - set(p))))
    need(set(p) <= REQUIRED | OPTIONAL, "unknown_or_readonly_field")
    canonical(payload)  # reject NaN and non-JSON data
    need(p["control"] == "publish", "create_publish_only")
    for key in ("reference_number", "name", "comments"):
        need(isinstance(p[key], str) and p[key].strip(), key + "_required")
    # Conservative UTF-8 byte bound also handles emoji; no silent truncation.
    need(len(p["comments"].encode("utf-8")) <= 3000 and not re.search(r"<[^>]+>", p["comments"]),
         "comments_plain_text_limit")
    for key in ("category_id", "price"):
        need(integer(p[key]), key + "_positive_integer")
    need(integer(p["brand_id"], 0), "brand_id_nonnegative_integer")
    if p.get("brand_name"):
        need(p["brand_id"] == 0, "brand_name_requires_zero_brand_id")
    for key in ("buying_area_id", "shipping_area_id"):
        need((isinstance(p[key], str) and p[key].isdigit() and int(p[key]) > 0)
             or integer(p[key]), key + "_required")
    try:
        expiry = datetime.strptime(p["available_until"], "%Y/%m/%d").date()
    except (ValueError, TypeError):
        raise ValueError("invalid_available_until") from None
    need(today <= expiry <= today + timedelta(days=90), "available_until_outside_90_days_jst")
    if "duty" in p:
        need(p["duty"] in {"none", "included", "refundable"}, "invalid_duty")
    images = p["images"]
    need(type(images) is list and 1 <= len(images) <= 20, "images_1_to_20_required")
    positions = set()
    for image in images:
        need(type(image) is dict and set(image) == {"path", "position"}, "invalid_image")
        url = urlsplit(image["path"])
        need(url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password,
             "public_image_url_required")
        host = url.hostname.lower().rstrip(".")
        need(host != "localhost" and not host.endswith((".localhost", ".local", ".internal")),
             "public_image_url_required")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None  # DNS accessibility still requires separate evidence.
        need(address is None or address.is_global, "public_image_url_required")
        need(integer(image["position"]) and image["position"] not in positions, "image_position_unique")
        positions.add(image["position"])
    methods = p["shipping_methods"]
    need(type(methods) is list and methods, "shipping_methods_required")
    ids = []
    for method in methods:
        need(type(method) is dict and set(method) == {"shipping_method_id"}
             and integer(method["shipping_method_id"]), "invalid_shipping_method")
        ids.append(method["shipping_method_id"])
    need(len(ids) == len(set(ids)), "duplicate_shipping_method")
    options = p["options"]
    need(type(options) is list and options, "options_required")
    values = {"color": set(), "size": set()}
    positions = set()
    for option in options:
        need(type(option) is dict and {"type", "value", "master_id", "position"} <= set(option)
             and set(option) <= {"type", "value", "master_id", "position", "details"}, "invalid_option")
        kind, value = option["type"], option["value"]
        need(kind in values and isinstance(value, str) and value.strip(), "invalid_option_value")
        need(value not in values[kind], "duplicate_option")
        need(integer(option["master_id"], 0) and integer(option["position"]), "invalid_option_id_position")
        need((kind, option["position"]) not in positions, "duplicate_option_position")
        positions.add((kind, option["position"]))
        values[kind].add(value)
    need(all(values.values()), "color_and_size_required")
    expected = set(itertools.product(values["color"], values["size"]))
    variants = p["variants"]
    need(type(variants) is list and variants, "variants_required")
    actual = set()
    for variant in variants:
        need(type(variant) is dict and {"options", "stock_type"} <= set(variant)
             and set(variant) <= {"options", "stock_type", "stocks"}, "invalid_variant")
        opts = variant["options"]
        need(type(opts) is list and len(opts) == 2, "variant_color_size_required")
        need(all(type(o) is dict and set(o) == {"type", "value"} for o in opts), "invalid_variant_option")
        need({o["type"] for o in opts} == {"color", "size"}, "variant_color_size_required")
        pair = {o["type"]: o["value"] for o in opts}
        key = (pair["color"], pair["size"])
        need(key in expected and key not in actual, "unknown_or_duplicate_variant")
        actual.add(key)
        stock = variant["stock_type"]
        need(stock in {"stock_in_hand", "purchase_for_order", "out_of_stock"}, "invalid_stock_type")
        if stock == "stock_in_hand":
            need(integer(variant.get("stocks")), "physical_stock_required")
        elif stock == "out_of_stock":
            need(variant.get("stocks") in (None, 0), "out_of_stock_quantity")
        else:
            need(variant.get("stocks") is None or integer(variant["stocks"], 0), "invalid_purchase_stock")
            need(integer(p.get("order_quantity")), "order_quantity_required")
    need(actual == expected, "all_variant_combinations_required")
    return copy.deepcopy(payload)


def prepare_action(product, listing, *, environment, seller_id, now):
    """Existing Product Master + explicit BUYMA facts. Never derive JPY from KRW.

    Missing Japanese copy, IDs, stock, price or shipping remain missing. This
    local plan cannot clear business/connection holds, even with editable flags.
    """
    need(environment in ENDPOINTS and integer(seller_id), "explicit_target_required")
    reference = reference_number(product)
    p = copy.deepcopy(listing)
    need(type(p) is dict and "reference_number" not in p and "control" not in p, "listing_identity_owned_by_adapter")
    need(set(p) <= (REQUIRED | OPTIONAL) - {"reference_number", "control"}, "unsupported_listing_fields")
    p.update(reference_number=reference, control="publish")
    # The image is an observed existing field, not generated product information.
    if "images" not in p and product.get("image_url"):
        p["images"] = [{"path": product["image_url"], "position": 1}]
    errors, validation_errors = [], []
    try:
        validate_payload({"product": p}, today=timestamp(now).astimezone(timezone(timedelta(hours=9))).date())
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        errors.append("buyma_payload_invalid_or_incomplete")
        validation_errors.append(str(exc))
    source = copy.deepcopy(product.get("source") or {})
    try:
        age = (timestamp(now) - timestamp(source.get("collected_at"))).total_seconds()
        if not 0 <= age <= 86400:
            errors.append("supplier_observation_stale_or_future")
    except (ValueError, TypeError):
        errors.append("supplier_observation_timestamp_missing")
    blockers = list(dict.fromkeys(errors + list((product.get("listing") or {}).get("blocked_by") or []) + BUSINESS_HOLDS))
    payload = {"product": p}
    return {"schema_version": 1, "action_id": "buyma:publish:" + product["canonical_product_id"],
            "canonical_product_id": product["canonical_product_id"], "pd_no": product["pd_no"],
            "reference_number": reference, "target": {"environment": environment, "seller_id": seller_id},
            "method": "POST", "url": ENDPOINTS[environment], "required_token_header": TOKEN_HEADER,
            "immutablePayload": payload, "payload_hash": digest(payload), "source": source,
            "prepared_at": now, "payload_validation_errors": validation_errors,
            "state": "BLOCKED" if errors else "LOCAL_VALIDATED", "blockers": blockers,
            "execution_enabled": False, "business_clearance": False, "publication_confirmed": False}


class RehearsalStore(ExecutionStore):
    """Reuse existing exclusive lock/fsync/atomic store without touching Core."""
    filename = "data/operations/reports/.buyma-rehearsal.json"
    lockname = "data/operations/reports/.buyma-rehearsal.lock"


@dataclass(frozen=True)
class FixtureResponse:
    status: int | None = None
    body: object = None
    headers: dict | None = None
    timeout: bool = False


def evaluate_japan_costs(action, inputs, *, now, evidence_verifier=None):
    """Pure Decimal recalculation for one explicit order composition.

    No rate tables/default costs/fetches. Hashes bind facts but do not authenticate
    them: evidence_verifier is trusted code, not an input approved/verified flag.
    A local eligible result never grants execution or publication authority.
    """
    result = {"eligible": False, "profitability_valid": False, "market_status": "incomplete",
              "execution_enabled": False, "publication_confirmed": False, "blockers": []}
    def amount(value, label, *, positive=False):
        need(type(value) in (str, int) and len(str(value)) <= 64, label + "_invalid_number")
        try:
            n = Decimal(value)
        except InvalidOperation:
            raise ValueError(label + "_invalid_number") from None
        need(n.is_finite() and n >= 0 and n <= Decimal("1e15") and (not positive or n > 0),
             label + "_invalid_number")
        return n
    def window(section, label):
        need(timestamp(section["observed_at"]) <= clock <= timestamp(section["valid_until"]),
             label + "_outside_validity")
        if "effective_at" in section:
            need(timestamp(section["effective_at"]) <= clock, label + "_not_effective")
    def verified(key):
        section = inputs.get(key)
        binding = {"target": action["target"], "canonical_product_id": action["canonical_product_id"],
                   "payload_hash": action["payload_hash"], "section": key, "facts": section,
                   "input_set_hash": digest({k: v for k, v in inputs.items() if k != "evidence"})}
        ref = inputs.get("evidence", {}).get(key)
        need(type(section) is dict and ref == digest(binding), key + "_evidence_missing_or_mismatched")
        need(callable(evidence_verifier), "trusted_cost_evidence_verifier_missing")
        try:
            authenticated = evidence_verifier(key, copy.deepcopy(binding), ref)
        except Exception:
            raise ValueError(key + "_evidence_verifier_failed") from None
        need(authenticated is True, key + "_evidence_unverified")
        return section
    try:
        clock = timestamp(now)
        need(action["payload_hash"] == digest(action["immutablePayload"]), "cost_action_payload_hash_invalid")
        validate_payload(action["immutablePayload"], today=clock.astimezone(timezone(timedelta(hours=9))).date())
        need(type(inputs) is dict and type(inputs.get("schema_version")) is int
             and inputs["schema_version"] == 1, "japan_cost_inputs_missing")
        need(type(inputs.get("evidence")) is dict, "cost_evidence_map_required")
        need(inputs.get("target") == action["target"] and inputs.get("canonical_product_id") == action["canonical_product_id"]
             and inputs.get("payload_hash") == action["payload_hash"], "cost_action_binding_mismatch")
        with localcontext() as context:
            context.prec = 64
            offer, purchase, shipping, packaging, fee, fx, supplier, legal, strategy = (
                verified(k) for k in ("offer", "purchase", "shipping", "packaging", "fee", "fx", "supplier", "legal", "strategy"))
            for label, section in (("offer", offer), ("purchase", purchase), ("shipping", shipping),
                                   ("packaging", packaging), ("fee", fee), ("fx", fx),
                                   ("supplier", supplier), ("legal", legal), ("strategy", strategy)):
                window(section, label)
            need(supplier["source_hash"] == digest(action["source"]), "supplier_action_source_mismatch")
            observed_source = timestamp(action["source"]["collected_at"])
            need(timestamp(supplier["observed_at"]) == observed_source
                 and 0 <= (clock - observed_source).total_seconds() <= 86400,
                 "supplier_observation_not_current")
            need(offer["currency"] == fee["currency"] == "JPY" and
                 purchase["currency"] == shipping["currency"] == packaging["currency"] == "KRW", "cost_currency_mismatch")
            need(fx["direction"] == "KRW_PER_JPY", "fx_direction_must_be_krw_per_jpy")
            rate = amount(fx["rate"], "fx_rate", positive=True)
            unit_jpy = amount(offer["unit_price_jpy"], "unit_price", positive=True).to_integral_value(rounding=ROUND_CEILING)
            need(unit_jpy == action["immutablePayload"]["product"]["price"], "rounded_price_payload_mismatch")
            q = offer["listing_quantity"]
            need(integer(q) and q <= 1000000 and integer(purchase["total_units"])
                 and purchase["total_units"] <= 1000000, "order_quantity_invalid")
            need(integer(purchase["units_per_listing"]) and purchase["total_units"] == purchase["units_per_listing"] * q,
                 "purchase_order_composition_mismatch")
            need(shipping["destination"] == "JP" and shipping["shipment_count"] == 1
                 and type(shipping["shipment_count"]) is int, "one_explicit_order_shipment_required")
            need(shipping["service"] in {"EMS", "K-Packet"}, "shipping_service_unverified")
            need(shipping["service"] != "K-Packet" or shipping.get("contract_confirmed") is True, "kpacket_contract_unverified")
            need(shipping["includes_all_surcharges"] is True and shipping["scope"] == packaging["scope"] == "order",
                 "final_order_shipping_quote_required")
            net_g = amount(shipping["product_net_weight_g"], "net_weight", positive=True)
            actual_g = amount(shipping["packed_actual_weight_g"], "packed_weight", positive=True)
            need(actual_g >= net_g * purchase["total_units"], "packed_weight_below_total_net_weight")
            box = shipping["box_cm"]
            volume_g = amount(box["length"], "length", positive=True) * amount(box["width"], "width", positive=True) * amount(box["height"], "height", positive=True) / Decimal(6)
            chargeable_g = max(actual_g, volume_g)
            brackets = [amount(x, "tariff_bracket", positive=True) for x in shipping["tariff_brackets_g"]]
            need(brackets and brackets == sorted(set(brackets)), "tariff_brackets_invalid")
            next_bracket = next((x for x in brackets if x >= chargeable_g), None)
            need(next_bracket is not None and amount(shipping["billed_weight_g"], "billed_weight", positive=True) == next_bracket,
                 "shipping_next_weight_bracket_required")
            base = amount(shipping["base_krw"], "base_shipping", positive=True)
            surcharge = amount(shipping["transport_surcharge_krw"], "transport_surcharge")
            extra = amount(shipping["other_shipping_krw"], "other_shipping")
            final_shipping = amount(shipping["final_quote_krw"], "final_shipping", positive=True)
            need(final_shipping == base + surcharge + extra, "final_shipping_sum_mismatch")
            purchase_total = amount(purchase["unit_cost_krw"], "purchase_unit_cost", positive=True) * purchase["total_units"]
            packing = amount(packaging["cost_krw"], "packing_cost")
            cost = purchase_total + final_shipping + packing  # shipment/packing ONCE per order, not per purchased unit
            need(fee["basis"] == "order_gross_jpy" and fee["fixed_scope"] == "order", "fee_basis_unverified")
            need("effective_at" in fee, "fee_effective_date_required")
            percent = amount(fee["rate"], "fee_rate")
            need(percent < 1, "fee_rate_must_be_fraction_below_one")
            fixed = amount(fee["fixed_jpy"], "fixed_fee")
            need(fixed == fixed.to_integral_value(), "fixed_fee_integer_jpy_required")
            modes = {"CEILING": ROUND_CEILING, "HALF_UP": ROUND_HALF_UP, "FLOOR": ROUND_FLOOR}
            need(fee["rounding"] in modes, "fee_rounding_unverified")
            customer_shipping = amount(offer["customer_shipping_jpy"], "customer_shipping")
            need(customer_shipping == customer_shipping.to_integral_value(), "customer_shipping_integer_jpy_required")
            def calculate(price):
                gross = price * q + customer_shipping
                variable = (gross * percent).to_integral_value(rounding=modes[fee["rounding"]])
                return gross, variable, (gross - variable - fixed) * rate - cost
            gross, variable, profit = calculate(unit_jpy)
            # Conservative upper bound includes at most one JPY fee-rounding loss;
            # binary search finds the exact minimum whole-JPY unit price.
            upper = (((cost + Decimal(3000)) / rate + fixed + 1) / (1 - percent) - customer_shipping) / q
            high, low = max(1, int(upper.to_integral_value(rounding=ROUND_CEILING))), 0
            need(high <= 10**15, "minimum_price_out_of_supported_range")
            while low < high:
                middle = (low + high) // 2
                if calculate(Decimal(middle))[2] >= 3000:
                    high = middle
                else:
                    low = middle + 1
            result.update(cost_calculation_valid=True, profitability_valid=profit >= 3000,
                          unit_price_jpy=int(unit_jpy), order_gross_jpy=str(gross),
                          variable_fee_jpy=str(variable), fixed_fee_jpy=str(fixed), purchase_total_krw=str(purchase_total),
                          shipping_total_krw=str(final_shipping), packaging_total_krw=str(packing),
                          chargeable_weight_g=str(chargeable_g), billed_weight_g=str(next_bracket),
                          net_profit_krw=str(profit), minimum_profit_krw=3000, minimum_unit_price_jpy=max(1, low))
            if profit < 3000:
                result["blockers"].append("minimum_3000krw_profit_not_met")
            # A buyer may buy one listing. Bulk-order profit cannot clear the
            # public listing; a bundle is represented by units_per_listing > 1.
            if q != 1:
                result["blockers"].append("listing_candidate_requires_single_listing_order")
            # A tariff/margin result never substitutes for observed market/strategy evidence.
            try:
                market = verified("market")
                window(market, "market")
                need(market["currency"] == "JPY" and strategy["comparison_basis"] == "order_customer_total_jpy", "market_comparison_basis_invalid")
                ceiling = amount(market["max_customer_total_jpy"], "market_ceiling", positive=True)
                need(gross <= ceiling, "market_strategy_price_limit_exceeded")
                result["market_status"] = "verified_within_strategy_limit"
            except (ValueError, KeyError, TypeError):
                result["blockers"].append("market_competitiveness_incomplete")
            result["eligible"] = not result["blockers"]
            proof_refs = inputs["evidence"]
            result.update(japan_shipping=proof_refs["shipping"], buyma_fee=proof_refs["fee"],
                          japan_market_price=proof_refs.get("market"), sales_strategy=proof_refs["strategy"],
                          fresh_supplier=proof_refs["supplier"], buyma_legal_publication=proof_refs["legal"],
                          krw_jpy_fx=proof_refs["fx"], packing_cost=proof_refs["packaging"])
    except (ValueError, KeyError, TypeError, DecimalException, OverflowError) as exc:
        reason = str(exc) if type(exc) is ValueError and str(exc).replace("_", "").isalnum() else "cost_input_missing_or_invalid"
        result["blockers"].append(reason)
    return result


def plan_daily_candidate(actions, attempts, *, now, cost_inputs=None, evidence_verifier=None):
    """Pure proposal for the daily-one requirement; NOT wired to a dispatcher.

    Japan-specific economics/strategy must be recalculated here; a callback may
    authenticate evidence but cannot replace the calculation with approved flags.
    Missing facts/authentication cannot choose a product.
    Pending outcomes from ANY day reserve capacity; a rollover must not permit
    a second product while yesterday's asynchronous creation remains unknown.
    Fixture publication never contributes to actual confirmed success.
    """
    clock = timestamp(now)
    if cost_inputs is not None:
        need(type(cost_inputs) is dict, "cost_inputs_must_be_keyed_by_cp")
    kst = timezone(timedelta(hours=9))
    day = clock.astimezone(kst).date().isoformat()
    result = {"mode": "daily_candidate_only", "kst_date": day, "daily_limit": 1,
              "execution_enabled": False, "schedule_enabled": False,
              "publication_confirmed": False, "actual_success_count": 0,
              "simulated_success_count": 0, "candidate": None, "reason": None, "candidate_checks": []}
    pending = {"SENDING", "ACCEPTED", "RECONCILIATION_REQUIRED", "CREATED_NOT_PUBLIC"}
    known_states = pending | {"PUBLISHED", "REJECTED", "RATE_LIMITED"}
    need(type(actions) is list and type(attempts) is list, "daily_input_schema_invalid")
    prior_products, occupied, unresolved = set(), False, False
    for attempt in attempts:
        need(type(attempt) is dict and attempt.get("mode") == "fixture_only"
             and attempt.get("state") in known_states and attempt.get("publication_confirmed") is False,
             "daily_attempt_invalid")
        reference_number(attempt)
        prior_products.add(attempt["canonical_product_id"])
        attempted = timestamp(attempt.get("attempted_at") or attempt.get("prepared_at"))
        need(attempted <= clock, "daily_attempt_in_future")
        unresolved |= attempt["state"] in pending
        publication = attempt.get("registration_publication")
        if attempt["state"] == "PUBLISHED":
            need(attempt.get("simulated_publication_confirmed") is True and type(publication) is dict,
                 "daily_publication_evidence_missing")
        if publication is not None:
            need(type(publication) is dict and integer(publication.get("buyma_product_id"))
                 and publication["buyma_product_id"] == attempt.get("buyma_product_id"), "daily_publication_mapping_invalid")
            completed = timestamp(publication.get("published_at"))
            need(attempted <= completed <= clock, "daily_publication_clock_invalid")
            completed_today = completed.astimezone(kst).date().isoformat() == day
            attempted_today = attempted.astimezone(kst).date().isoformat() == day
            occupied |= completed_today or attempted_today
            result["simulated_success_count"] += int(completed_today)
    if unresolved:
        result["reason"] = "unresolved_prior_attempt_reserves_slot"
    elif occupied:
        result["reason"] = "daily_slot_already_used"
    elif cost_inputs is None:
        result["reason"] = "japan_cost_inputs_missing"
    else:
        for action in actions:
            if action.get("canonical_product_id") in prior_products:
                continue  # Never auto-resubmit the same product, even next day.
            need(action.get("execution_enabled") is False and action.get("publication_confirmed") is False,
                 "daily_action_scope_invalid")
            if action.get("payload_validation_errors") or any(
                    str(reason).startswith("supplier_observation_") for reason in action.get("blockers", [])):
                continue
            proof = evaluate_japan_costs(action, cost_inputs.get(action["canonical_product_id"]),
                                         now=now, evidence_verifier=evidence_verifier)
            result["candidate_checks"].append({"canonical_product_id": action["canonical_product_id"],
                "blockers": list(proof["blockers"]), "profitability_valid": proof["profitability_valid"],
                "market_status": proof["market_status"]})
            if not isinstance(proof, dict) or proof.get("eligible") is not True:
                continue
            profit = proof.get("net_profit_krw")
            try:
                amount = Decimal(str(profit)) if type(profit) in (str, int, float) else Decimal("NaN")
            except InvalidOperation:
                continue
            if not amount.is_finite() or amount < 3000:
                continue
            required = ("japan_shipping", "buyma_fee", "japan_market_price", "sales_strategy",
                        "fresh_supplier", "buyma_legal_publication", "krw_jpy_fx", "packing_cost")
            if not all(isinstance(proof.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", proof[key]) for key in required):
                continue
            result.update(candidate={"action_id": action["action_id"],
                          "canonical_product_id": action["canonical_product_id"],
                          "reference_number": reference_number(action), "payload_hash": action["payload_hash"],
                          "target": copy.deepcopy(action["target"]),
                          "eligibility_evidence_hash": digest(proof)}, reason="review_candidate_only")
            break
        if result["reason"] is None:
            result["reason"] = "no_verified_japan_candidate"
    return result


class BuymaAdapter:
    """Persistent fixture-only adapter. No live transport can be configured."""
    def __init__(self, root, *, environment, seller_id):
        need(environment in ENDPOINTS and integer(seller_id), "explicit_target_required")
        self.target = {"environment": environment, "seller_id": seller_id}
        self.store = RehearsalStore(root)

    def _ledger(self, document):
        if not document:
            need(not (self.store.root / self.store.filename).exists(), "ledger_unexpected_empty")
            document.update(schema_version=2, mode="fixture_only", target=self.target,
                            actions={}, events=[], receipts=[])
        need(document.get("schema_version") == 2 and document.get("mode") == "fixture_only"
             and document.get("target") == self.target, "ledger_scope_mismatch")
        need(type(document.get("actions")) is dict and type(document.get("events")) is list
             and type(document.get("receipts")) is list, "ledger_invalid")
        for reference, row in document["actions"].items():
            need(reference == row["reference_number"] and row["payload_hash"] == digest(row["immutablePayload"]),
                 "ledger_action_invalid")
            need(row.get("publication_confirmed") is False and row.get("business_clearance") is False
                 and row.get("execution_enabled") is False and row.get("mode") == "fixture_only"
                 and row.get("target") == self.target
                 and row.get("simulated_publication_confirmed") is (row.get("state") == "PUBLISHED"),
                 "ledger_false_publication_claim")
            publication = row.get("registration_publication")
            need(row.get("state") != "PUBLISHED" or type(publication) is dict, "ledger_publication_history_missing")
            if publication is not None:
                need(type(publication) is dict and set(publication) == {"buyma_product_id", "published_at", "event_digest"}
                     and integer(publication["buyma_product_id"]) and publication["buyma_product_id"] == row.get("buyma_product_id"),
                     "ledger_publication_mapping_invalid")
                need(timestamp(publication["published_at"]) >= timestamp(row["attempted_at"]), "ledger_publication_clock_invalid")
        previous = None
        latest, publications = {}, {}
        for receipt in document["receipts"]:
            need(receipt.get("previous") == previous and receipt.get("receipt_hash") ==
                 digest({k: v for k, v in receipt.items() if k != "receipt_hash"}), "ledger_receipt_invalid")
            previous = receipt["receipt_hash"]
            reference = receipt["reference_number"]
            publication = receipt.get("registration_publication")
            if reference in publications:
                need(publication == publications[reference], "ledger_publication_history_changed")
            if publication is not None:
                publications.setdefault(reference, publication)
            latest[receipt["reference_number"]] = receipt
        for reference, row in document["actions"].items():
            need(reference in latest and latest[reference]["state"] == row["state"]
                 and latest[reference]["payload_hash"] == row["payload_hash"], "ledger_state_receipt_mismatch")
            need(latest[reference].get("registration_publication") == row.get("registration_publication"),
                 "ledger_publication_receipt_mismatch")
        return document

    def _receipt(self, doc, row, state, *, evidence=None):
        row["state"] = state
        row["simulated_publication_confirmed"] = state == "PUBLISHED"
        receipt = {"mode": "fixture_only", "target": self.target, "action_id": row["action_id"],
                   "reference_number": row["reference_number"], "payload_hash": row["payload_hash"],
                   "state": state, "publication_confirmed": False,
                   "registration_publication": copy.deepcopy(row.get("registration_publication")),
                   "previous": doc["receipts"][-1]["receipt_hash"] if doc["receipts"] else None,
                   "evidence": evidence or {}}
        receipt["receipt_hash"] = digest(receipt)
        doc["receipts"].append(receipt)

    def rehearse(self, action, fixture, *, today):
        need(type(fixture) is FixtureResponse, "fixture_response_only_live_transport_disabled")
        fields = {"schema_version", "action_id", "canonical_product_id", "pd_no", "reference_number",
                  "target", "method", "url", "required_token_header", "immutablePayload", "payload_hash",
                  "source", "prepared_at", "payload_validation_errors", "state", "blockers",
                  "execution_enabled", "business_clearance", "publication_confirmed"}
        need(type(action) is dict and set(action) == fields, "unexpected_action_fields")
        need(action.get("execution_enabled") is False and action.get("target") == self.target
             and action.get("business_clearance") is False and action.get("publication_confirmed") is False,
             "action_scope_invalid")
        payload = validate_payload(action["immutablePayload"], today=today)
        reference = payload["product"]["reference_number"]
        need(reference == reference_number(action) and action["reference_number"] == reference
             and action["payload_hash"] == digest(payload)
             and action["action_id"] == "buyma:publish:" + action["canonical_product_id"]
             and action["required_token_header"] == TOKEN_HEADER, "action_binding_invalid")
        need(action["url"] == ENDPOINTS[self.target["environment"]] and action["method"] == "POST", "endpoint_invalid")
        with self.store.transaction() as (document, save):
            doc = self._ledger(document)
            prior = doc["actions"].get(reference)
            # Includes rejected/rate-limited attempts: a retry needs reconciliation,
            # never a new identity or automatic replay of POST (also updates items).
            if prior:
                need(prior["payload_hash"] == action["payload_hash"] and prior["pd_no"] == action["pd_no"],
                     "existing_reference_requires_reconciliation")
                return copy.deepcopy(prior)
            row = copy.deepcopy(action)
            row.update(mode="fixture_only", attempted_at=action["prepared_at"], buyma_product_id=None, request_uid=None,
                       simulated_publication_confirmed=False, confirmation_blocked=False, registration_publication=None)
            doc["actions"][reference] = row
            self._receipt(doc, row, "SENDING")
            save(doc)  # Crash after this point must not cause another create.
            status, body = fixture.status, fixture.body
            state = "RECONCILIATION_REQUIRED"
            evidence = {"fixture_http_status": status}
            if fixture.timeout:
                evidence["reason"] = "timeout_outcome_unknown"
            elif status == 201 and type(body) is dict and isinstance(body.get("request_uid"), str) and body["request_uid"]:
                try:
                    need(timestamp(body.get("request_received_at")) >= timestamp(action["prepared_at"]),
                         "acceptance_precedes_preparation")
                    need(not any(r.get("request_uid") == body["request_uid"] for r in doc["actions"].values()), "request_uid_reused")
                    row.update(request_uid=body["request_uid"], request_received_at=body["request_received_at"])
                    state = "ACCEPTED"
                except ValueError:
                    evidence["reason"] = "invalid_acceptance_receipt"
            elif status == 422 and type(body) is dict and body.get("errors"):
                state = "REJECTED"
                evidence["error_digest"] = digest(body["errors"])
            elif status == 429:
                state = "RATE_LIMITED"
                headers = {k.lower(): v for k, v in (fixture.headers or {}).items()}
                evidence["rate_limit_reset"] = headers.get("x-rate-limit-reset")
            self._receipt(doc, row, state, evidence=evidence)
            save(doc)
            return copy.deepcopy(row)

    def webhook(self, raw, headers, *, application_secret, received_at=None):
        """Verify exact bytes before JSON; application secret is an explicit capability.

        Caller supplies only a synthetic secret in this rehearsal. No listener is
        started. Event name isn't signed by BUYMA, so validate its body shape too.
        """
        need(type(raw) is bytes and type(application_secret) is bytes and application_secret,
             "raw_bytes_and_application_secret_required")
        need(len(raw) <= 2 * 1024 * 1024, "webhook_body_too_large")
        headers = {k.lower(): v for k, v in headers.items()}
        signature = headers.get("x-buyma-hmac-sha256")
        expected = base64.b64encode(hmac.digest(application_secret, raw, "sha256")).decode("ascii")
        need(isinstance(signature, str) and signature.isascii() and hmac.compare_digest(expected, signature),
             "invalid_webhook_signature")
        need(headers.get("x-buyma-api-version") == "v1", "unsupported_webhook_version")
        event = headers.get("x-buyma-event")
        need(event in {"product/create", "product/update", "product/fail_to_create"}, "unsupported_webhook_event")
        body = strict_json(raw)
        received = timestamp(received_at or datetime.now(timezone.utc).isoformat())
        need(type(body) is dict and type(body.get("seller_id")) is int
             and body["seller_id"] == self.target["seller_id"], "webhook_seller_mismatch")
        # BUYMA signs body bytes, not X-Buyma-Event. create/update share the
        # authenticated product-snapshot semantics; failure has a distinct body.
        kind = "product_create_failure" if event == "product/fail_to_create" else "product_snapshot"
        event_id = digest({"kind": kind, "body": body})
        with self.store.transaction() as (document, save):
            doc = self._ledger(document)
            if event_id in doc["events"]:
                return {"result": "duplicate", "mode": "fixture_only", "publication_confirmed": False}
            if event == "product/fail_to_create":
                need(isinstance(body.get("request_uid"), str) and body.get("errors")
                     and "status" not in body and "reference_number" not in body, "invalid_failure_event")
                matches = [r for r in doc["actions"].values() if r.get("request_uid") == body["request_uid"]]
                need(len(matches) == 1, "unknown_failure_request_reconciliation_required")
                row = matches[0]
                failed = timestamp(body.get("failed_at"))
                need(timestamp(row.get("request_received_at") or row["prepared_at"]) <= failed <= received,
                     "invalid_failure_clock")
                state = "REJECTED" if row["state"] == "ACCEPTED" else "RECONCILIATION_REQUIRED"
                row["confirmation_blocked"] = True
            else:
                need("errors" not in body and integer(body.get("id")) and body.get("status") in
                     {"public", "soldout", "draft", "buyer_suspended", "admin_suspended", "in_review",
                      "not_approved", "buyer_deleted", "admin_deleted"}, "invalid_creation_event")
                row = doc["actions"].get(body.get("reference_number"))
                need(row is not None, "unknown_reference_reconciliation_required")
                updated = timestamp(body.get("updated_at"))
                need(updated >= timestamp(body.get("created_at")), "invalid_product_clock")
                need(updated <= received, "future_product_clock")
                need(updated >= timestamp(row.get("request_received_at") or row["prepared_at"]),
                     "webhook_precedes_current_attempt")
                existing = row.get("buyma_product_id")
                conflict = ("buyma_id_mapping_conflict" if existing not in (None, body["id"]) else
                            "buyma_id_already_mapped" if any(r is not row and r.get("buyma_product_id") == body["id"]
                                                           for r in doc["actions"].values()) else None)
                if conflict:
                    # Preserve original mapping and first-publication evidence.
                    # A verified contradiction must survive a process restart.
                    row["confirmation_blocked"] = True
                    doc["events"].append(event_id)
                    self._receipt(doc, row, "RECONCILIATION_REQUIRED", evidence={"reason": conflict,
                        "event_digest": event_id, "existing_buyma_product_id": existing,
                        "incoming_buyma_product_id": body["id"], "incoming_updated_at": body["updated_at"]})
                    save(doc)
                    return copy.deepcopy(row)
                if existing is None:
                    need(timestamp(body["created_at"]) >= timestamp(row.get("request_received_at") or row["prepared_at"]),
                         "creation_precedes_current_attempt")
                if row.get("confirmation_blocked"):
                    state = "RECONCILIATION_REQUIRED"
                elif row.get("remote_updated_at") and updated <= timestamp(row["remote_updated_at"]):
                    row["confirmation_blocked"] = True
                    state = "RECONCILIATION_REQUIRED"
                elif row["state"] not in {"ACCEPTED", "SENDING", "RECONCILIATION_REQUIRED", "CREATED_NOT_PUBLIC", "PUBLISHED"}:
                    row["confirmation_blocked"] = True
                    state = "RECONCILIATION_REQUIRED"
                else:
                    row.update(buyma_product_id=body["id"], remote_status=body["status"],
                               remote_updated_at=body["updated_at"])
                    if body["status"] == "public" and row["registration_publication"] is None:
                        row["registration_publication"] = {"buyma_product_id": body["id"],
                            "published_at": body["updated_at"], "event_digest": event_id}
                    # Lifecycle completion is historical. Later soldout/suspended
                    # snapshots update remote_status but never undo registration.
                    state = "PUBLISHED" if row["registration_publication"] is not None else "CREATED_NOT_PUBLIC"
                row["simulated_publication_confirmed"] = state == "PUBLISHED"
            doc["events"].append(event_id)
            self._receipt(doc, row, state, evidence={"event_digest": event_id})
            save(doc)
            return copy.deepcopy(row)


def main():
    parser = argparse.ArgumentParser(description="Prepare a local BUYMA plan; never sends requests")
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--listings", type=Path, required=True, help="Explicit reviewed BUYMA fields keyed by CP; no secrets")
    parser.add_argument("--environment", choices=ENDPOINTS, required=True)
    parser.add_argument("--seller-id", type=int, required=True, help="Explicit target, not an account verification")
    parser.add_argument("--now", required=True)
    args = parser.parse_args()
    master = json.loads(args.master.read_text(encoding="utf-8-sig"))
    listings = json.loads(args.listings.read_text(encoding="utf-8-sig"))
    rows = master["products"]
    need(type(rows) is list and type(listings) is dict, "input_schema_invalid")
    refs, pd_nos = set(), set()
    actions = []
    for product in rows:
        ref = reference_number(product)
        need(ref not in refs and product["pd_no"] not in pd_nos, "duplicate_master_identity")
        need(master.get("pd_no_to_cp", {}).get(product["pd_no"]) == product["canonical_product_id"], "master_registry_mismatch")
        refs.add(ref)
        pd_nos.add(product["pd_no"])
        actions.append(prepare_action(product, listings.get(product["canonical_product_id"], {}),
                       environment=args.environment, seller_id=args.seller_id, now=args.now))
    need(set(listings) <= {p["canonical_product_id"] for p in rows}, "unknown_listing_identity")
    print(canonical({"schema_version": 1, "mode": "local_plan_only", "execution_enabled": False,
                     "publication_confirmed": False, "actions": actions}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
