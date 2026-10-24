"""One-rule offline consumer of team repair tasks; never a live writer.

Source/readback envelopes are untrusted saved observations. recorded_at is the
saved receipt record clock, not a claim of a fresh provider observation. A successful replay
proves byte-bound transformation only, not provider authenticity, fresh readback,
permission, legal clearance, or successful autonomous execution.
No network, credentials, filesystem writes, or workflow activation.
"""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from team_fix_protocol import AUTHORITY
from daiso.collect_gosi_alt import clean_maker

RULE = 'manufacturer_heading_fragment'
FRAGMENT = '및 판매원'
LABEL = '<strong>Manufacturer / Distributor (Korea):</strong> '
REPLACEMENT = 'Source verification pending'
MAX_BYTES = 1048576


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def need(value, reason):
    if not value:
        raise ValueError(reason)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def snapshot(raw, now):
    need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, 'snapshot_capacity_or_type')
    try:
        doc = json.loads(raw, object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('snapshot_json') from exc
    need(isinstance(doc, dict) and set(doc) == {'kind', 'recorded_at', 'product'}, 'snapshot_schema')
    need(doc['kind'] == 'saved_shopify_product_readback', 'not_saved_observation')
    need(isinstance(doc['recorded_at'], str), 'observation_clock')
    try:
        observed = datetime.fromisoformat(doc['recorded_at'].replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('observation_clock') from exc
    need(observed.tzinfo is not None and observed <= now, 'future_or_naive_observation')
    product = doc['product']
    need(isinstance(product, dict), 'product_schema')
    need(isinstance(product.get('id'), str) and
         re.fullmatch(r'gid://shopify/Product/[1-9][0-9]*', product['id']), 'product_identity')
    need(product.get('status') == 'DRAFT', 'draft_snapshot_required')
    need(isinstance(product.get('descriptionHtml'), str) and
         len(product['descriptionHtml'].encode()) <= MAX_BYTES, 'description_required')
    return doc, observed


def blocked(reason):
    return {'schema_version': 1, 'state': 'review_required', 'reason': reason,
            'mode': 'offline_saved_input_replay', 'live_execution': False,
            'fresh_readback': False, 'independent_review_required': True,
            **AUTHORITY}


def rehearse(task, before_snapshot_bytes, saved_readback_bytes, *, now=None):
    """Consume one task using strict saved envelopes; never consume permissions.

    Unsupported rules fail closed. Source/readback assertions supplied by callers
    do not cross a trusted boundary; output is permanently an offline result.
    """
    now = datetime.now(timezone.utc) if now is None else now
    try:
        need(isinstance(now, datetime) and now.tzinfo is not None, 'invalid_evaluation_clock')
        need(isinstance(task, dict), 'task_schema')
        need(task.get('rule') == RULE and task.get('team') == 'sourcing', 'unsupported_rule_requires_review')
        need(all(task.get(key) is False for key in AUTHORITY), 'task_cannot_grant_authority')
        issue = task.get('issue_id')
        need(isinstance(issue, str) and re.fullmatch(r'supplier-[0-9]{1,12}-manufacturer_heading_fragment', issue), 'issue_identity')
        before_doc, before_at = snapshot(before_snapshot_bytes, now)
        after_doc, after_at = snapshot(saved_readback_bytes, now)
        before, observed_after = before_doc['product'], after_doc['product']
        need(before['id'] == observed_after['id'], 'readback_product_mismatch')
        need(after_at >= before_at, 'readback_clock_regression')
        pd_no = issue.split('-')[1]
        # A product-id string in a task is not enough: source snapshot SKU tag
        # must bind the task to this exact product without trusting guessed IDs.
        need(isinstance(before.get('tags'), list) and
             all(isinstance(tag, str) for tag in before['tags']) and
             [tag for tag in before['tags'] if tag.startswith('daiso-pd-')] == ['daiso-pd-' + pd_no], 'task_snapshot_sku_mismatch')
        body = before['descriptionHtml']
        matches = list(re.finditer(re.escape(LABEL) + r'(?P<value>[^<]*)</(?:p|li)>', body))
        need(body.count(LABEL) == 1 and len(matches) == 1, 'ambiguous_missing_or_already_corrected_fragment')
        field = matches[0]
        value = field.group('value')
        need(value.strip() == FRAGMENT, 'ambiguous_missing_or_already_corrected_fragment')
        need(clean_maker(value) == '', 'published_fragment_rule_changed')
        proposed = copy.deepcopy(before)
        proposed['descriptionHtml'] = (body[:field.start('value')] +
                                       value.replace(FRAGMENT, REPLACEMENT, 1) +
                                       body[field.end('value'):])
        need(canonical(proposed) == canonical(observed_after), 'saved_readback_or_other_fields_mismatch')
        need([key for key in before if before[key] != proposed[key]] == ['descriptionHtml'], 'changed_field_scope')
        binding = {'issue_id': issue, 'product_id': before['id'], 'rule': RULE,
                   'before_snapshot_sha256': digest(before_snapshot_bytes),
                   'saved_readback_sha256': digest(saved_readback_bytes),
                   'before_product_sha256': digest(canonical(before)),
                   'proposed_product_sha256': digest(canonical(proposed)),
                   'allowed_fields': ['descriptionHtml']}
        return {'schema_version': 1, 'state': 'offline_replay_verified',
                'reason': 'exact_saved_readback_matches_deterministic_proposal',
                'mode': 'offline_saved_input_replay', 'binding': binding,
                'replay_key': digest(canonical(binding)),
                'proposed_description_html': proposed['descriptionHtml'],
                'live_execution': False, 'fresh_readback': False,
                'independent_review_required': True,
                'unresolved_holds_unchanged': True, **AUTHORITY}
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        # Fixed validation codes only; never return raw product/source values.
        allowed = {'snapshot_capacity_or_type', 'duplicate_json_key', 'nonfinite_json',
                   'snapshot_json', 'snapshot_schema', 'not_saved_observation',
                   'observation_clock', 'future_or_naive_observation', 'product_schema',
                   'product_identity', 'draft_snapshot_required', 'description_required',
                   'invalid_evaluation_clock', 'task_schema', 'unsupported_rule_requires_review',
                   'task_cannot_grant_authority', 'issue_identity', 'readback_product_mismatch',
                   'readback_clock_regression', 'task_snapshot_sku_mismatch',
                   'published_fragment_rule_changed', 'ambiguous_missing_or_already_corrected_fragment',
                   'saved_readback_or_other_fields_mismatch', 'changed_field_scope'}
        reason = str(exc) if str(exc) in allowed else 'invalid_offline_input'
        return blocked(reason)
