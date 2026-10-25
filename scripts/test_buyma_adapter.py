"""Offline boundary regressions. Synthetic fixtures; forbid all socket access."""
import base64
import copy
from datetime import date
import hmac
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import buyma_adapter as b

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/buyma_offline.json"
TODAY = date(2026, 10, 25)
NOW = "2026-10-25T00:00:00+00:00"
SECRET = b"synthetic-fixture-secret-not-a-credential"


class BuymaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.network = patch("socket.socket", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.adapter = b.BuymaAdapter(self.temp.name, environment="sandbox", seller_id=10000000)
        self.action = self.prepare()

    def prepare(self, product=None, listing=None, now=NOW):
        return b.prepare_action(product or self.fixtures["product"],
                                self.fixtures["listing"] if listing is None else listing,
                                environment="sandbox", seller_id=10000000, now=now)

    def send(self, fixture=None):
        return self.adapter.rehearse(self.action, fixture or b.FixtureResponse(201, self.fixtures["accepted"]), today=TODAY)

    def headers(self, raw, event="product/create"):
        return {"X-Buyma-Event": event, "X-Buyma-Api-Version": "v1",
                "X-Buyma-Hmac-Sha256": base64.b64encode(hmac.digest(SECRET, raw, "sha256")).decode()}

    def webhook(self, key="created", event="product/create", body=None, received_at="2026-10-25T00:10:00Z"):
        raw = json.dumps(body if body is not None else self.fixtures[key], ensure_ascii=False).encode()
        return self.adapter.webhook(raw, self.headers(raw, event), application_secret=SECRET,
                                    received_at=received_at)

    def test_p2_later_public_update_does_not_move_original_registration_to_new_day(self):
        self.send()
        first = self.webhook()
        later = dict(self.fixtures["created"], updated_at="2026-10-26T09:01:00+09:00")
        result = self.webhook(body=later, event="product/update", received_at="2026-10-26T00:10:00Z")
        plan = self.daily([result], now="2026-10-26T00:10:00Z")
        self.assertEqual(plan["simulated_success_count"], 0)
        self.assertEqual(plan["reason"], "japan_cost_inputs_missing")
        self.assertIsNotNone(first.get("registration_publication"))
        self.assertEqual(result["registration_publication"], first["registration_publication"])
        self.assertEqual(result["remote_updated_at"], later["updated_at"])

    def test_p2_soldout_after_publication_is_current_status_not_pending_registration(self):
        self.send()
        first = self.webhook()
        later = dict(self.fixtures["created"], status="soldout", updated_at="2026-10-26T09:01:00+09:00")
        result = self.webhook(body=later, event="product/update", received_at="2026-10-26T00:10:00Z")
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(result["remote_status"], "soldout")
        self.assertEqual(result["registration_publication"], first["registration_publication"])
        plan = self.daily([result], now="2026-10-26T00:10:00Z")
        self.assertEqual(plan["simulated_success_count"], 0)
        self.assertEqual(plan["reason"], "japan_cost_inputs_missing")

    def test_p2_same_signed_snapshot_with_only_event_header_changed_is_duplicate(self):
        self.send()
        raw = json.dumps(self.fixtures["created"]).encode()
        headers = self.headers(raw)
        self.adapter.webhook(raw, headers, application_secret=SECRET, received_at="2026-10-25T00:10:00Z")
        before = self.ledger()
        headers["X-Buyma-Event"] = "product/update"  # exact same bytes and signature
        result = self.adapter.webhook(raw, headers, application_secret=SECRET, received_at="2026-10-25T00:10:00Z")
        self.assertEqual(result.get("result"), "duplicate")
        self.assertEqual(self.ledger(), before)

    def test_p2_id_conflict_immediately_persists_reconciliation_and_original_mapping(self):
        self.send()
        first = self.webhook()
        conflict = dict(self.fixtures["created"], id=987654, updated_at="2026-10-25T09:05:00+09:00")
        try:
            self.webhook(body=conflict)
        except ValueError:
            pass  # Inspect persisted state immediately, even for the pre-fix exception path.
        stored = self.ledger()["actions"][self.action["reference_number"]]
        self.assertEqual(stored["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(stored["buyma_product_id"], 123456)
        self.assertTrue(stored["confirmation_blocked"])
        self.assertFalse(stored["simulated_publication_confirmed"])
        self.assertEqual(stored["registration_publication"], first["registration_publication"])
        evidence = self.ledger()["receipts"][-1]["evidence"]
        self.assertEqual(evidence["reason"], "buyma_id_mapping_conflict")
        self.assertEqual(evidence["existing_buyma_product_id"], 123456)
        self.assertEqual(evidence["incoming_buyma_product_id"], 987654)
        self.assertEqual(evidence["incoming_updated_at"], conflict["updated_at"])
        count = len(self.ledger()["receipts"])
        self.assertEqual(self.send()["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(len(self.ledger()["receipts"]), count)

    def test_snapshot_dedup_still_processes_new_snapshot_and_distinct_failure_semantics(self):
        self.send()
        first = self.webhook()
        later = dict(self.fixtures["created"], comments="changed snapshot", updated_at="2026-10-25T09:03:00+09:00")
        count = len(self.ledger()["receipts"])
        changed = self.webhook(body=later, event="product/update")
        self.assertEqual(len(self.ledger()["receipts"]), count + 1)
        self.assertEqual(changed["remote_updated_at"], later["updated_at"])
        self.assertEqual(changed["registration_publication"], first["registration_publication"])
        before = self.ledger()
        with self.assertRaisesRegex(ValueError, "invalid_failure_event"):
            self.webhook(body=later, event="product/fail_to_create")
        self.assertEqual(self.ledger(), before)
        failed = dict(self.fixtures["failed"], failed_at="2026-10-25T09:04:00+09:00")
        result = self.webhook(body=failed, event="product/fail_to_create")
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(result["registration_publication"], first["registration_publication"])
        self.assertTrue(result["confirmation_blocked"])

    def test_first_publication_history_tampering_and_old_ledger_schema_fail_closed(self):
        self.send()
        self.webhook()
        original = self.ledger()
        path = Path(self.temp.name) / b.RehearsalStore.filename
        changed = copy.deepcopy(original)
        changed["actions"][self.action["reference_number"]]["registration_publication"]["published_at"] = "2026-10-26T00:00:00Z"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ledger_publication_receipt_mismatch"):
            self.send()
        changed = copy.deepcopy(original)
        changed["schema_version"] = 1
        path.write_text(json.dumps(changed), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "ledger_scope_mismatch"):
            self.send()
        self.assertEqual(path.read_bytes(), before)

    def test_forged_action_flags_or_credential_fields_are_rejected_without_persistence(self):
        for extra in ({"publication_confirmed": True}, {"business_clearance": True},
                      {"headers": {"Authorization": "sensitive-sentinel"}},
                      {"access_token": "sensitive-sentinel"}, {"action_id": "buyma:publish:other"}):
            with self.subTest(extra=list(extra)), self.assertRaises(ValueError):
                self.adapter.rehearse({**self.action, **extra}, b.FixtureResponse(), today=TODAY)
        self.assertFalse((Path(self.temp.name) / b.RehearsalStore.filename).exists())

    def test_unknown_listing_keys_are_not_echoed_or_saved_as_payload(self):
        with self.assertRaisesRegex(ValueError, "unsupported_listing_fields"):
            self.prepare(listing={**self.fixtures["listing"], "client_secret": "sensitive-sentinel"})

    def test_signed_duplicate_json_keys_are_rejected_before_state_change(self):
        self.send()
        raw = json.dumps(self.fixtures["created"]).encode().replace(b'"status": "public"', b'"status": "draft", "status": "public"')
        before = self.ledger()
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            self.adapter.webhook(raw, self.headers(raw), application_secret=SECRET,
                                 received_at="2026-10-25T00:10:00Z")
        self.assertEqual(self.ledger(), before)

    def test_future_event_and_failure_before_request_cannot_confirm_or_reject(self):
        self.send()
        with self.assertRaises(ValueError):
            self.webhook(body=dict(self.fixtures["created"], updated_at="2030-01-01T00:00:00Z"))
        with self.assertRaises(ValueError):
            self.webhook(event="product/fail_to_create", body=dict(self.fixtures["failed"], failed_at="2026-10-24T00:00:00Z"))
        self.assertEqual(self.send()["state"], "ACCEPTED")

    def test_contradiction_after_rejection_is_sticky_and_never_auto_confirms(self):
        self.send()
        self.webhook("failed", "product/fail_to_create")
        self.assertEqual(self.webhook()["state"], "RECONCILIATION_REQUIRED")
        newer = dict(self.fixtures["created"], updated_at="2026-10-25T09:05:00+09:00")
        result = self.webhook(body=newer, event="product/update")
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(result["simulated_publication_confirmed"])

    def test_existing_product_before_attempt_cannot_be_claimed_as_new_creation(self):
        self.send()
        with self.assertRaisesRegex(ValueError, "creation_precedes_current_attempt"):
            self.webhook(body=dict(self.fixtures["created"], created_at="2026-10-24T00:00:00Z"))

    def test_timestamp_error_does_not_echo_sensitive_input(self):
        with self.assertRaises(ValueError) as caught:
            b.timestamp("sensitive-sentinel")
        self.assertNotIn("sensitive-sentinel", str(caught.exception))
        listing = {**self.fixtures["listing"], "available_until": "sensitive-sentinel"}
        self.assertNotIn("sensitive-sentinel", str(self.prepare(listing=listing)["payload_validation_errors"]))

    def test_signature_algorithm_against_independent_rfc4231_vector(self):
        # RFC 4231 case 1: independently specified digest, not our signing helper.
        raw = b"Hi There"
        digest = bytes.fromhex("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7")
        headers = {"X-Buyma-Hmac-Sha256": base64.b64encode(digest).decode(),
                   "X-Buyma-Event": "product/create", "X-Buyma-Api-Version": "v1"}
        with self.assertRaisesRegex(ValueError, "invalid_webhook_json"):
            self.adapter.webhook(raw, headers, application_secret=b"\x0b" * 20, received_at=NOW)
        headers["X-Buyma-Hmac-Sha256"] = digest.hex()
        with self.assertRaisesRegex(ValueError, "invalid_webhook_signature"):
            self.adapter.webhook(raw, headers, application_secret=b"\x0b" * 20, received_at=NOW)

    def test_empty_or_forged_completed_store_cannot_reset_or_claim_publication(self):
        self.send()
        original = self.ledger()
        path = Path(self.temp.name) / b.RehearsalStore.filename
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ledger_unexpected_empty"):
            self.send()
        for field in ("publication_confirmed", "simulated_publication_confirmed", "business_clearance"):
            changed = copy.deepcopy(original)
            changed["actions"][self.action["reference_number"]][field] = True
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ledger_false_publication_claim"):
                self.send()

    def test_local_private_and_authenticated_image_urls_are_rejected(self):
        for url in ("http://localhost/x", "http://127.0.0.1/x", "https://10.0.0.1/x",
                    "https://[::1]/x", "https://x.local/x", "https://u:secret@example.org/x"):
            payload = copy.deepcopy(self.action["immutablePayload"])
            payload["product"]["images"][0]["path"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                b.validate_payload(payload, today=TODAY)

    def test_large_and_nonfinite_json_webhooks_are_rejected(self):
        raw = b" " * (2 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "webhook_body_too_large"):
            self.adapter.webhook(raw, {}, application_secret=SECRET)
        raw = json.dumps(self.fixtures["created"]).encode().replace(b'"id": 123456', b'"id": NaN')
        with self.assertRaisesRegex(ValueError, "nonfinite_json_number"):
            self.adapter.webhook(raw, self.headers(raw), application_secret=SECRET)

    def daily(self, attempts=(), now="2026-10-25T00:10:00Z", verifier=None, actions=None):
        actions = [self.action] if actions is None else actions
        inputs = None
        if callable(verifier):
            inputs = {}
            for action in actions:
                facts = copy.deepcopy(verifier(action))
                self.bind_cost_evidence(action, facts)
                inputs[action["canonical_product_id"]] = facts
        return b.plan_daily_candidate(actions, list(attempts), now=now, cost_inputs=inputs,
                                     evidence_verifier=(lambda *args: True) if inputs is not None else None)

    def economics(self, action):
        # Synthetic facts, not an override of the actual calculation.
        facts = copy.deepcopy(self.fixtures["costs"])
        facts.update(target=action["target"], canonical_product_id=action["canonical_product_id"], payload_hash=action["payload_hash"])
        facts["offer"]["unit_price_jpy"] = str(action["immutablePayload"]["product"]["price"])
        facts["supplier"]["source_hash"] = b.digest(action["source"])
        facts["market"]["max_customer_total_jpy"] = "100000"
        return facts

    def cost_fixture(self, *, price=5000):
        action = copy.deepcopy(self.action)
        action["immutablePayload"]["product"]["price"] = price
        action["payload_hash"] = b.digest(action["immutablePayload"])
        facts = copy.deepcopy(self.fixtures["costs"])
        facts.update(target=action["target"], canonical_product_id=action["canonical_product_id"], payload_hash=action["payload_hash"])
        facts["offer"]["unit_price_jpy"] = str(price)
        facts["supplier"]["source_hash"] = b.digest(action["source"])
        return action, facts

    def bind_cost_evidence(self, action, facts):
        facts["evidence"] = {key: b.digest({"target": action["target"], "canonical_product_id": action["canonical_product_id"],
            "payload_hash": action["payload_hash"], "section": key, "facts": facts.get(key),
            "input_set_hash": b.digest({k: v for k, v in facts.items() if k != "evidence"})})
            for key in ("offer", "purchase", "shipping", "packaging", "fee", "fx", "supplier", "legal", "strategy", "market")}

    def cost_check(self, action, facts, *, verifier=lambda *args: True, bind=True):
        if bind:
            self.bind_cost_evidence(action, facts)
        return b.evaluate_japan_costs(action, facts, now="2026-10-25T00:10:00Z", evidence_verifier=verifier)

    def test_costs_recalculate_percentage_fixed_fee_fx_and_minimum_jpy_price(self):
        action, facts = self.cost_fixture()
        result = self.cost_check(action, facts)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["order_gross_jpy"], "5000")
        self.assertEqual(result["variable_fee_jpy"], "350")
        self.assertEqual(result["fixed_fee_jpy"], "100")
        self.assertEqual(result["net_profit_krw"], "3950")  # (5000-350-100)*9 - (10000+26000+1000)
        self.assertEqual(result["minimum_unit_price_jpy"], 4888)
        self.assertFalse(result["publication_confirmed"])

    def test_costs_exact_3000_margin_boundary_is_recalculated(self):
        for price, expected, eligible in ((4887, "2996", False), (4888, "3005", True)):
            action, facts = self.cost_fixture(price=price)
            result = self.cost_check(action, facts)
            self.assertEqual(result["net_profit_krw"], expected)
            self.assertEqual(result["profitability_valid"], eligible)
            self.assertEqual(result["eligible"], eligible)
        action, facts = self.cost_fixture(price=4888)
        facts["packaging"]["cost_krw"] = "1005"
        self.assertEqual(self.cost_check(action, facts)["net_profit_krw"], "3000")
        self.assertTrue(self.cost_check(action, facts)["eligible"])
        facts["packaging"]["cost_krw"] = "1005.01"
        self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_jpy_price_ceil_and_explicit_fee_rounding(self):
        action, facts = self.cost_fixture()
        facts["offer"]["unit_price_jpy"] = "4999.01"
        self.assertEqual(self.cost_check(action, facts)["unit_price_jpy"], 5000)
        action, facts = self.cost_fixture(price=5001)
        for rounding, fee, profit in (("CEILING", "351", "3950"), ("HALF_UP", "350", "3959"), ("FLOOR", "350", "3959")):
            facts["fee"]["rounding"] = rounding
            result = self.cost_check(action, facts)
            self.assertEqual(result["variable_fee_jpy"], fee)
            self.assertEqual(result["net_profit_krw"], profit)
        facts["fee"].pop("rounding")
        self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["fee"]["rate"] = "0.0701"  # 350.5 JPY: verify the half-up tie explicitly.
        for rounding, expected in (("HALF_UP", "351"), ("FLOOR", "350")):
            facts["fee"]["rounding"] = rounding
            self.assertEqual(self.cost_check(action, facts)["variable_fee_jpy"], expected)

    def test_costs_shipping_and_packaging_are_charged_once_for_bundle_order(self):
        action, facts = self.cost_fixture()
        facts["offer"]["listing_quantity"] = 2
        facts["purchase"]["total_units"] = 4
        facts["shipping"]["packed_actual_weight_g"] = "450"
        facts["market"]["max_customer_total_jpy"] = "11000"
        result = self.cost_check(action, facts)
        self.assertEqual(result["purchase_total_krw"], "20000")
        self.assertEqual(result["shipping_total_krw"], "26000")
        self.assertEqual(result["packaging_total_krw"], "1000")
        self.assertEqual(result["net_profit_krw"], "35800")
        self.assertEqual(result["fixed_fee_jpy"], "100")

    def test_costs_customer_shipping_is_in_explicit_fee_basis(self):
        action, facts = self.cost_fixture()
        facts["offer"]["customer_shipping_jpy"] = "100"
        result = self.cost_check(action, facts)
        self.assertEqual(result["order_gross_jpy"], "5100")
        self.assertEqual(result["variable_fee_jpy"], "357")
        self.assertEqual(result["net_profit_krw"], "4787")

    def test_costs_require_final_shipping_and_kpacket_contract(self):
        for mutation in (lambda f: f["shipping"].update(includes_all_surcharges=False),
                         lambda f: f["shipping"].update(service="K-Packet", contract_confirmed=False),
                         lambda f: f["shipping"].update(transport_surcharge_krw=None),
                         lambda f: f["shipping"].update(final_quote_krw=None),
                         lambda f: f["shipping"].update(final_quote_krw="25000"),
                         lambda f: f["shipping"].update(scope="unit"),
                         lambda f: f["shipping"].update(shipment_count=2)):
            action, facts = self.cost_fixture()
            mutation(facts)
            self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["shipping"].update(service="K-Packet", contract_confirmed=True)
        self.assertTrue(self.cost_check(action, facts)["eligible"])

    def test_costs_use_packed_volume_and_next_tariff_bracket(self):
        action, facts = self.cost_fixture()
        facts["shipping"].update(box_cm={"length": "30", "width": "20", "height": "10"}, billed_weight_g="1000")
        result = self.cost_check(action, facts)
        self.assertEqual(result["chargeable_weight_g"], "1000")
        self.assertEqual(result["billed_weight_g"], "1000")
        facts["shipping"]["billed_weight_g"] = "500"
        self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["shipping"].update(packed_actual_weight_g="501", billed_weight_g="750")
        self.assertTrue(self.cost_check(action, facts)["eligible"])
        facts["shipping"]["billed_weight_g"] = "500"
        self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_net_weight_cannot_substitute_for_packed_weight_or_dimensions(self):
        for mutation in (lambda f: f["shipping"].pop("packed_actual_weight_g"),
                         lambda f: f["shipping"].update(packed_actual_weight_g="100"),
                         lambda f: f["shipping"].pop("box_cm"),
                         lambda f: f["shipping"]["box_cm"].update(length=None)):
            action, facts = self.cost_fixture()
            mutation(facts)
            self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_quote_fee_and_fx_dates_must_cover_calculation_time(self):
        for section in ("shipping", "fee", "fx"):
            for field, value in (("observed_at", "2026-10-26T00:00:00Z"), ("valid_until", "2026-10-24T00:00:00Z"),
                                 ("observed_at", None)):
                action, facts = self.cost_fixture()
                facts[section][field] = value
                self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["fee"]["effective_at"] = "2026-11-01T00:00:00Z"
        self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_wrong_currency_direction_nan_negative_and_missing_values_fail_closed(self):
        changes = [("fx", "direction", "JPY_PER_KRW"), ("fx", "rate", "0"), ("fx", "rate", "NaN"),
                   ("purchase", "currency", "JPY"), ("shipping", "currency", "USD"), ("fee", "currency", "KRW"),
                   ("fee", "rate", "7"), ("fee", "fixed_jpy", "0.5"), ("packaging", "cost_krw", "-1")]
        for section, field, value in changes:
            action, facts = self.cost_fixture()
            facts[section][field] = value
            self.assertFalse(self.cost_check(action, facts)["eligible"])
        for value in (None, "NaN", "Infinity", -1, True, float("nan")):
            action, facts = self.cost_fixture()
            facts["purchase"]["unit_cost_krw"] = value
            if type(value) is float:
                # Non-JSON/non-finite evidence is rejected during binding too.
                with self.assertRaises(ValueError):
                    self.bind_cost_evidence(action, facts)
                facts["evidence"] = {}
                self.assertFalse(b.evaluate_japan_costs(action, facts, now=NOW)["eligible"])
            else:
                self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_editable_verified_flags_cannot_replace_bound_evidence(self):
        action, facts = self.cost_fixture()
        self.assertFalse(self.cost_check(action, facts, verifier=None)["eligible"])
        self.assertFalse(self.cost_check(action, facts, verifier=lambda *args: False)["eligible"])
        facts["evidence"]["fx"] = "a" * 64
        facts["verified"] = True
        self.assertFalse(self.cost_check(action, facts, bind=False)["eligible"])
        for malformed in (None, [], "unknown"):
            facts["evidence"] = malformed
            self.assertFalse(self.cost_check(action, facts, bind=False)["eligible"])

    def test_costs_market_missing_or_out_of_strategy_range_stays_incomplete(self):
        for mutation in (lambda f: f.pop("market"), lambda f: f["market"].update(max_customer_total_jpy="4999")):
            action, facts = self.cost_fixture()
            mutation(facts)
            result = self.cost_check(action, facts)
            self.assertTrue(result["profitability_valid"])
            self.assertEqual(result["market_status"], "incomplete")
            self.assertFalse(result["eligible"])

    def test_costs_are_bound_to_payload_target_product_and_supplier(self):
        for key, value in (("payload_hash", "a" * 64), ("canonical_product_id", "CP000068"), ("target", {})):
            action, facts = self.cost_fixture()
            facts[key] = value
            self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["supplier"]["source_hash"] = "a" * 64
        self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_daily_candidate_uses_actual_cost_recalculation_and_preserves_nonexecution(self):
        action, facts = self.cost_fixture()
        self.bind_cost_evidence(action, facts)
        plan = b.plan_daily_candidate([action], [], now="2026-10-25T00:10:00Z",
                                     cost_inputs={"CP000067": facts}, evidence_verifier=lambda *args: True)
        self.assertEqual(plan["candidate"]["canonical_product_id"], "CP000067")
        self.assertFalse(plan["execution_enabled"])
        self.assertFalse(plan["publication_confirmed"])
        for inputs in ({}, {"CP000067": facts}):
            blocked = b.plan_daily_candidate([action], [], now="2026-10-25T00:10:00Z", cost_inputs=inputs)
            self.assertIsNone(blocked["candidate"])
            self.assertTrue(blocked["candidate_checks"][0]["blockers"])
        facts["shipping"]["transport_surcharge_krw"] = None
        self.bind_cost_evidence(action, facts)
        blocked = b.plan_daily_candidate([action], [], now="2026-10-25T00:10:00Z",
                                        cost_inputs={"CP000067": facts}, evidence_verifier=lambda *args: True)
        self.assertIsNone(blocked["candidate"])

    def test_costs_evidence_cannot_be_mixed_from_different_order_compositions(self):
        action, facts = self.cost_fixture()
        self.bind_cost_evidence(action, facts)
        prior = copy.deepcopy(facts["evidence"])
        facts["purchase"]["total_units"] = 1
        self.bind_cost_evidence(action, facts)
        facts["evidence"]["shipping"] = prior["shipping"]
        self.assertFalse(self.cost_check(action, facts, bind=False)["eligible"])

    def test_costs_verifier_exceptions_do_not_echo_values_and_stale_source_is_not_relabelled_fresh(self):
        def failed(*args):
            raise ValueError("sensitive-sentinel")
        action, facts = self.cost_fixture()
        result = self.cost_check(action, facts, verifier=failed)
        self.assertFalse(result["eligible"])
        self.assertNotIn("sensitive-sentinel", str(result))
        action["source"]["collected_at"] = "2026-09-01T00:00:00Z"
        facts["supplier"]["source_hash"] = b.digest(action["source"])
        self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_wrong_action_hash_and_extreme_decimal_are_blocked(self):
        action, facts = self.cost_fixture()
        action["immutablePayload"]["product"]["price"] = 5001
        self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["fx"]["rate"] = "1e-999999999"
        self.assertFalse(self.cost_check(action, facts)["eligible"])

    def test_costs_composition_must_match_and_bulk_profit_cannot_clear_single_listing(self):
        action, facts = self.cost_fixture()
        facts["purchase"]["total_units"] = 1
        self.assertFalse(self.cost_check(action, facts)["eligible"])
        action, facts = self.cost_fixture()
        facts["offer"]["listing_quantity"] = 2
        facts["purchase"]["total_units"] = 4
        facts["shipping"]["packed_actual_weight_g"] = "450"
        facts["market"]["max_customer_total_jpy"] = "11000"
        result = self.cost_check(action, facts)
        self.assertTrue(result["profitability_valid"])
        self.assertFalse(result["eligible"])
        self.assertIn("listing_candidate_requires_single_listing_order", result["blockers"])

    def test_daily_default_blocks_and_kst_midnight_is_explicit(self):
        plan = self.daily(now="2026-10-25T15:00:00Z")
        self.assertEqual(plan["kst_date"], "2026-10-26")
        self.assertEqual(plan["reason"], "japan_cost_inputs_missing")
        self.assertIsNone(plan["candidate"])
        self.assertFalse(plan["execution_enabled"])
        self.assertFalse(plan["schedule_enabled"])

    def test_daily_selects_at_most_one_candidate_only_with_japan_specific_evidence_and_margin(self):
        product = dict(self.fixtures["product"], canonical_product_id="CP000068", pd_no="1041809")
        second = self.prepare(product=product)
        result = self.daily(verifier=self.economics, actions=[self.action, second])
        self.assertEqual(result["candidate"]["canonical_product_id"], "CP000067")
        self.assertEqual(result["actual_success_count"], 0)
        self.assertFalse(result["publication_confirmed"])
        low_margin = self.economics(self.action)
        low_margin["purchase"]["unit_cost_krw"] = "78713"
        for bad in (low_margin, {**self.economics(self.action), "shipping": None},
                    {"approved": True, "net_profit_krw": 9000}):
            self.assertIsNone(self.daily(verifier=lambda _: bad)["candidate"])

    def test_daily_accepted_unknown_and_review_states_reserve_slot_without_counting_success(self):
        row = self.send()
        for state in ("SENDING", "ACCEPTED", "RECONCILIATION_REQUIRED", "CREATED_NOT_PUBLIC"):
            plan = self.daily([dict(row, state=state)], verifier=self.economics)
            self.assertEqual(plan["reason"], "unresolved_prior_attempt_reserves_slot")
            self.assertEqual(plan["actual_success_count"], 0)
            self.assertEqual(plan["simulated_success_count"], 0)

    def test_daily_unresolved_prior_day_also_blocks_rollover(self):
        row = self.send(b.FixtureResponse(timeout=True))
        plan = self.daily([row], now="2026-10-25T15:00:00Z", verifier=self.economics)
        self.assertEqual(plan["reason"], "unresolved_prior_attempt_reserves_slot")
        self.assertIsNone(plan["candidate"])

    def test_daily_publication_consumes_one_slot_only_as_simulation(self):
        self.send()
        row = self.webhook()
        plan = self.daily([row], verifier=self.economics)
        self.assertEqual(plan["reason"], "daily_slot_already_used")
        self.assertEqual(plan["simulated_success_count"], 1)
        self.assertEqual(plan["actual_success_count"], 0)
        plan = self.daily([row], now="2026-10-25T15:00:00Z", verifier=self.economics)
        self.assertIsNone(plan["candidate"])  # Same product is never auto-resubmitted.

    def test_daily_rejection_allows_other_product_but_never_same_product_retry(self):
        row = self.send(b.FixtureResponse(422, self.fixtures["rejected"]))
        product = dict(self.fixtures["product"], canonical_product_id="CP000068", pd_no="1041809")
        second = self.prepare(product=product)
        plan = self.daily([row], verifier=self.economics, actions=[self.action, second])
        self.assertEqual(plan["candidate"]["canonical_product_id"], "CP000068")

    def test_daily_delayed_publication_consumes_completion_day_and_async_rejection_releases_reservation(self):
        self.send()
        rejected = self.webhook("failed", "product/fail_to_create")
        product = dict(self.fixtures["product"], canonical_product_id="CP000068", pd_no="1041809")
        second = self.prepare(product=product)
        plan = self.daily([rejected], verifier=self.economics, actions=[second])
        self.assertEqual(plan["candidate"]["canonical_product_id"], "CP000068")
        delayed = dict(rejected, state="PUBLISHED", simulated_publication_confirmed=True,
                       confirmation_blocked=False, buyma_product_id=123456,
                       registration_publication={"buyma_product_id": 123456, "published_at": "2026-10-25T15:01:00Z", "event_digest": "a" * 64},
                       remote_updated_at="2026-10-25T15:01:00Z")
        plan = self.daily([delayed], now="2026-10-25T15:02:00Z", verifier=self.economics, actions=[second])
        self.assertEqual(plan["kst_date"], "2026-10-26")
        self.assertEqual(plan["reason"], "daily_slot_already_used")
        self.assertEqual(plan["simulated_success_count"], 1)

    def test_daily_unknown_costs_or_base_tariff_alone_do_not_become_final_quote_or_zero(self):
        for key in ("shipping", "fee", "fx", "packaging"):
            for unknown in (None, 0, "", "unknown"):
                proof = {**self.economics(self.action), key: unknown}
                self.assertIsNone(self.daily(verifier=lambda _: proof)["candidate"])
        for base_tariff in (4550, 6930, 9340, 14090, 26000, 28500):
            proof = {**self.economics(self.action), "shipping": base_tariff}
            self.assertIsNone(self.daily(verifier=lambda _: proof)["candidate"])

    def ledger(self):
        return json.loads((Path(self.temp.name) / b.RehearsalStore.filename).read_text(encoding="utf-8"))

    def test_preparation_retains_existing_identity_source_and_holds(self):
        a = self.action
        self.assertEqual(a["reference_number"], "jarvis-CP000067")
        self.assertEqual(a["immutablePayload"]["product"]["images"][0]["path"], self.fixtures["product"]["image_url"])
        self.assertEqual(a["source"], self.fixtures["product"]["source"])
        self.assertIn("verified_market_price_missing", a["blockers"])
        self.assertIn("japan_shipping_cost_unverified", a["blockers"])
        self.assertIn("buyma_fee_revision_unverified", a["blockers"])
        self.assertFalse(a["execution_enabled"])
        self.assertFalse(a["business_clearance"])
        self.assertFalse(a["publication_confirmed"])
        product = copy.deepcopy(self.fixtures["product"])
        product.update(name_ko="different name", price_krw=999999)
        self.assertEqual(self.prepare(product)["reference_number"], a["reference_number"])

    def test_missing_buyma_facts_are_not_fabricated_from_korean_fields(self):
        a = self.prepare(listing={})
        self.assertEqual(a["state"], "BLOCKED")
        self.assertNotIn("price", a["immutablePayload"]["product"])
        self.assertNotIn("name", a["immutablePayload"]["product"])
        self.assertNotIn("variants", a["immutablePayload"]["product"])
        with self.assertRaises(ValueError):
            self.adapter.rehearse(a, b.FixtureResponse(201, self.fixtures["accepted"]), today=TODAY)

    def test_actual_master_including_alphanumeric_source_ids_can_be_planned_without_fabrication(self):
        master = json.loads((FIXTURES.parents[2] / "data/product_master.json").read_text(encoding="utf-8"))
        refs = set()
        for product in master["products"]:
            self.assertEqual(master["pd_no_to_cp"][product["pd_no"]], product["canonical_product_id"])
            action = self.prepare(product=product, listing={})
            self.assertNotIn(action["reference_number"], refs)
            refs.add(action["reference_number"])
            self.assertEqual(action["state"], "BLOCKED")
            self.assertIn("buyma_payload_invalid_or_incomplete", action["blockers"])
            self.assertNotIn("price", action["immutablePayload"]["product"])

    def test_cli_builds_plan_only_and_rejects_duplicate_or_unregistered_identities(self):
        product = self.fixtures["product"]
        master = {"products": [product], "pd_no_to_cp": {product["pd_no"]: product["canonical_product_id"]}}
        root = Path(self.temp.name)
        master_path, listings_path = root / "master.json", root / "listings.json"
        listings_path.write_text("{}", encoding="utf-8")
        argv = ["buyma_adapter.py", "--master", str(master_path), "--listings", str(listings_path),
                "--environment", "sandbox", "--seller-id", "10000000", "--now", NOW]
        master_path.write_text(json.dumps(master), encoding="utf-8")
        with patch("sys.argv", argv), redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(b.main(), 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["mode"], "local_plan_only")
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(result["actions"][0]["state"], "BLOCKED")
        for invalid in ({**master, "products": [product, product]}, {**master, "pd_no_to_cp": {}}):
            master_path.write_text(json.dumps(invalid), encoding="utf-8")
            with patch("sys.argv", argv), self.assertRaises(ValueError):
                b.main()

    def test_old_missing_future_supplier_observations_remain_blocked(self):
        for captured in (None, "2026-09-01T00:00:00Z", "2026-10-26T00:00:00Z"):
            product = copy.deepcopy(self.fixtures["product"])
            product["source"]["collected_at"] = captured
            self.assertTrue(any(x.startswith("supplier_observation") for x in self.prepare(product)["blockers"]))

    def test_official_auth_header_and_endpoint_are_descriptors_only(self):
        self.assertEqual(self.action["url"], "https://sandbox.personal-shopper-api.buyma.com/api/v1/products.json")
        self.assertEqual(self.action["required_token_header"], "X-Buyma-Personal-Shopper-Api-Access-Token")
        self.assertNotIn("headers", self.action)
        with self.assertRaisesRegex(ValueError, "fixture_response_only"):
            self.adapter.rehearse(self.action, lambda: None, today=TODAY)

    def test_acceptance_is_not_publication_and_survives_restart(self):
        result = self.send()
        self.assertEqual(result["state"], "ACCEPTED")
        self.assertEqual(result["request_uid"], "offline-request-1")
        self.assertIsNone(result["buyma_product_id"])
        self.assertFalse(result["simulated_publication_confirmed"])
        self.assertFalse(result["publication_confirmed"])
        restarted = b.BuymaAdapter(self.temp.name, environment="sandbox", seller_id=10000000)
        self.assertEqual(restarted.rehearse(self.action, b.FixtureResponse(timeout=True), today=TODAY), result)
        self.assertEqual(len(self.ledger()["receipts"]), 2)

    def test_create_webhook_maps_id_and_marks_only_simulated_publication(self):
        self.send()
        result = self.webhook()
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(result["buyma_product_id"], 123456)
        self.assertTrue(result["simulated_publication_confirmed"])
        self.assertFalse(result["publication_confirmed"])
        self.assertEqual(result["mode"], "fixture_only")

    def test_duplicate_webhook_is_idempotent_including_json_whitespace(self):
        self.send()
        self.webhook()
        before = self.ledger()
        raw = json.dumps(self.fixtures["created"], sort_keys=True, indent=2).encode()
        self.assertEqual(self.adapter.webhook(raw, self.headers(raw), application_secret=SECRET)["result"], "duplicate")
        self.assertEqual(self.ledger(), before)

    def test_in_review_and_later_update_are_distinct_from_public(self):
        self.send()
        review = dict(self.fixtures["created"], status="in_review")
        self.assertEqual(self.webhook(body=review)["state"], "CREATED_NOT_PUBLIC")
        later = dict(self.fixtures["created"], updated_at="2026-10-25T09:02:00+09:00")
        self.assertEqual(self.webhook(body=later, event="product/update")["state"], "PUBLISHED")

    def test_rejection_and_async_rejection(self):
        self.assertEqual(self.send(b.FixtureResponse(422, self.fixtures["rejected"]))["state"], "REJECTED")
        with tempfile.TemporaryDirectory() as other:
            self.adapter = b.BuymaAdapter(other, environment="sandbox", seller_id=10000000)
            self.send()
            result = self.webhook("failed", "product/fail_to_create")
            self.assertEqual(result["state"], "REJECTED")
            self.assertFalse(result["publication_confirmed"])

    def test_timeout_5xx_duplicate_response_and_malformed_201_require_reconciliation(self):
        cases = (b.FixtureResponse(timeout=True), b.FixtureResponse(500, {}),
                 b.FixtureResponse(201, {}), b.FixtureResponse(201, {"request_uid": "x", "request_received_at": "bad"}),
                 b.FixtureResponse(409, {"errors": "duplicate reference"}), b.FixtureResponse(200, {}))
        for fixture in cases:
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as root:
                adapter = b.BuymaAdapter(root, environment="sandbox", seller_id=10000000)
                result = adapter.rehearse(self.action, fixture, today=TODAY)
                self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
                self.assertEqual(adapter.rehearse(self.action, b.FixtureResponse(201, self.fixtures["accepted"]), today=TODAY), result)

    def test_429_saves_official_reset_header_and_does_not_retry(self):
        result = self.send(b.FixtureResponse(429, "rate limited", {"X-Rate-Limit-Reset": "1792886400"}))
        self.assertEqual(result["state"], "RATE_LIMITED")
        self.assertEqual(self.ledger()["receipts"][-1]["evidence"]["rate_limit_reset"], "1792886400")
        self.assertEqual(self.send()["state"], "RATE_LIMITED")

    def test_unknown_timeout_can_be_resolved_by_signed_creation_without_resending(self):
        self.send(b.FixtureResponse(timeout=True))
        self.assertEqual(self.webhook()["state"], "PUBLISHED")
        self.assertEqual(len(self.ledger()["receipts"]), 3)

    def test_changed_payload_and_identity_cannot_bypass_existing_reference(self):
        self.send()
        changed = copy.deepcopy(self.action)
        changed["immutablePayload"]["product"]["price"] += 1
        changed["payload_hash"] = b.digest(changed["immutablePayload"])
        with self.assertRaisesRegex(ValueError, "reconciliation"):
            self.adapter.rehearse(changed, b.FixtureResponse(), today=TODAY)
        changed = copy.deepcopy(self.action)
        changed["pd_no"] = "99999"
        with self.assertRaisesRegex(ValueError, "reconciliation"):
            self.adapter.rehearse(changed, b.FixtureResponse(), today=TODAY)

    def test_invalid_missing_tampered_signatures_never_mutate_ledger(self):
        self.send()
        raw = json.dumps(self.fixtures["created"]).encode()
        before = self.ledger()
        for signature in (None, "bad", "é", "00" * 32):
            headers = self.headers(raw)
            headers["X-Buyma-Hmac-Sha256"] = signature
            with self.assertRaisesRegex(ValueError, "invalid_webhook_signature"):
                self.adapter.webhook(raw, headers, application_secret=SECRET)
        with self.assertRaisesRegex(ValueError, "invalid_webhook_signature"):
            self.adapter.webhook(raw + b" ", self.headers(raw), application_secret=SECRET)
        self.assertEqual(self.ledger(), before)

    def test_wrong_seller_unknown_reference_and_unsigned_event_spoof_are_rejected(self):
        self.send()
        before = self.ledger()
        cases = [(dict(self.fixtures["created"], seller_id=999), "product/create"),
                 (dict(self.fixtures["created"], reference_number="unknown"), "product/create"),
                 (self.fixtures["failed"], "product/create"),
                 (self.fixtures["created"], "product/fail_to_create")]
        for body, event in cases:
            with self.assertRaises(ValueError):
                self.webhook(body=body, event=event)
        self.assertEqual(self.ledger(), before)

    def test_unknown_failure_uid_does_not_guess_product_mapping(self):
        self.send(b.FixtureResponse(timeout=True))
        with self.assertRaisesRegex(ValueError, "unknown_failure_request"):
            self.webhook("failed", "product/fail_to_create")

    def test_conflicting_id_and_stale_event_do_not_report_publication(self):
        self.send()
        self.webhook()
        conflict = self.webhook(body=dict(self.fixtures["created"], id=987654, updated_at="2026-10-25T09:05:00+09:00"))
        self.assertEqual(conflict["state"], "RECONCILIATION_REQUIRED")
        self.assertTrue(conflict["confirmation_blocked"])
        self.assertFalse(conflict["simulated_publication_confirmed"])
        stale = dict(self.fixtures["created"], status="in_review")
        result = self.webhook(body=stale)
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(result["simulated_publication_confirmed"])
        self.assertEqual(result["buyma_product_id"], 123456)

    def test_store_scope_lock_corruption_and_crash_do_not_replay(self):
        self.send()
        other = b.BuymaAdapter(self.temp.name, environment="production", seller_id=10000000)
        with self.assertRaisesRegex(ValueError, "action_scope_invalid"):
            other.rehearse(self.action, b.FixtureResponse(), today=TODAY)
        with self.adapter.store.transaction():
            with self.assertRaises(FileExistsError):
                self.send()
        path = Path(self.temp.name) / b.RehearsalStore.filename
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.send()

    def test_crash_after_sending_claim_is_durable_and_never_replayed(self):
        import jarvis_execution as execution
        original = execution._atomic
        calls = []
        class Crash(BaseException):
            pass
        def crash_on_second_save(root, relative, value):
            calls.append(relative)
            if len(calls) == 2:
                raise Crash()
            return original(root, relative, value)
        with patch.object(execution, "_atomic", crash_on_second_save):
            with self.assertRaises(Crash):
                self.send()
        self.assertEqual(self.send()["state"], "SENDING")
        self.assertEqual(len(self.ledger()["receipts"]), 1)

    def test_corrupt_receipt_or_action_state_fails_closed(self):
        self.send()
        original = self.ledger()
        path = Path(self.temp.name) / b.RehearsalStore.filename
        for kind in ("receipt", "state"):
            doc = copy.deepcopy(original)
            if kind == "receipt":
                doc["receipts"][0]["state"] = "PUBLISHED"
            else:
                doc["actions"][self.action["reference_number"]]["state"] = "PUBLISHED"
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ledger_"):
                self.send()

    def test_id_and_request_uid_cannot_map_to_multiple_products(self):
        self.send()
        self.webhook()
        product = copy.deepcopy(self.fixtures["product"])
        product.update(canonical_product_id="CP000068", pd_no="1041809")
        action = self.prepare(product=product)
        result = self.adapter.rehearse(action, b.FixtureResponse(201, self.fixtures["accepted"]), today=TODAY)
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        conflict = self.webhook(body=dict(self.fixtures["created"], reference_number="jarvis-CP000068"))
        self.assertEqual(conflict["state"], "RECONCILIATION_REQUIRED")
        self.assertTrue(conflict["confirmation_blocked"])
        self.assertEqual(self.ledger()["receipts"][-1]["evidence"]["reason"], "buyma_id_already_mapped")

    def test_old_signed_webhook_cannot_confirm_current_attempt(self):
        self.send()
        body = dict(self.fixtures["created"], created_at="2026-10-24T09:01:01+09:00",
                    updated_at="2026-10-24T09:01:02+09:00")
        with self.assertRaisesRegex(ValueError, "precedes_current_attempt"):
            self.webhook(body=body)
        self.assertEqual(self.send()["state"], "ACCEPTED")

    def test_payload_structural_regressions(self):
        mutations = [
            lambda p: p.pop("price"), lambda p: p.update(price=True), lambda p: p.update(price=0),
            lambda p: p.update(id=123), lambda p: p.update(control="delete"),
            lambda p: p.update(comments="<b>html</b>"), lambda p: p.update(comments="a" * 3001),
            lambda p: p.update(available_until="2027/12/31"), lambda p: p.update(available_until="2026/10/24"),
            lambda p: p.update(images=[]), lambda p: p.update(shipping_methods=[]),
            lambda p: p["images"][0].update(path="file:///private"),
            lambda p: p.update(brand_id=203, brand_name="unmanaged"),
            lambda p: p["variants"][0].update(stocks=-1),
            lambda p: p["variants"][0].update(stock_type="purchase_for_order"),
            lambda p: p["options"].append({"type": "size", "value": "M", "position": 2, "master_id": 2}),
            lambda p: p["variants"].append(copy.deepcopy(p["variants"][0])),
        ]
        for mutate in mutations:
            payload = copy.deepcopy(self.action["immutablePayload"])
            mutate(payload["product"])
            with self.subTest(payload=payload), self.assertRaises((ValueError, TypeError)):
                b.validate_payload(payload, today=TODAY)


if __name__ == "__main__":
    unittest.main()
