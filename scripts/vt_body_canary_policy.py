"""Inactive, offline-only policy for one reviewed VT Directions correction.

No token, transport, mutation, workflow or grant loader exists here. A future
trusted entrypoint must authenticate run/checkpoint evidence using the existing
reviewed_copy_transaction.GitHubCheckpoint, with REQUIRE_ORIGINAL_CHECKPOINT.
Caller-supplied metadata is a model, NOT authenticated execution authority.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re

PRODUCT = 'gid://shopify/Product/9538199421185'
SHOP = '82748997889'
HOST = 'rb3zh1-i1.myshopify.com'
PUBLICATION = 'gid://shopify/Publication/212187775233'
BEFORE = '8f25b9c7603b43d3d7e07522e245290c766cb041896e532da9f4fb15ba4596cd'
AFTER = 'baffeeb9427a680f24c3a318c9e99395d3984a2336059d465bd699edbf5732d8'
SOURCE = '0f464b5849e41af220b8257d1756309ae37fbb51b0e9bf2d836c2c978a06ff66'
OLD = '<h3>Directions</h3><p>Detailed directions remain pending verification against the actual product packaging. Refer to the supplied product label.</p>'
NEW = '<h3>Directions (supplier information)</h3><p>After using essence, take an appropriate amount of cream and spread it gently along the skin texture until absorbed.</p><p><small>Translated from the saved Daiso Mall item 1067498 product notice. Actual-package verification remains pending; follow the label supplied with your product.</small></p>'
REQUIRE_ORIGINAL_CHECKPOINT = True
VARIANTS = {'gid://shopify/ProductVariant/50658640527617': 'DS-1067498-1',
            'gid://shopify/ProductVariant/50658640560385': 'DS-1067498-2'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def operation_id():
    # Independent of ticket, dispatch, date and caller-selected labels.
    return digest(canonical([SHOP, PRODUCT, BEFORE, AFTER, SOURCE]))


def proposed_body(body, source_bytes):
    require(digest(source_bytes) == SOURCE, 'source_bytes_mismatch')
    require(isinstance(body, str), 'body_missing')
    if digest(body.encode()) == AFTER:
        return None  # Already correct: no deliberate rebreak and no mutation.
    require(digest(body.encode()) == BEFORE and body.count(OLD) == 1,
            'before_body_changed_requires_review')
    result = body.replace(OLD, NEW, 1)
    require(digest(result.encode()) == AFTER, 'exact_after_body_mismatch')
    return result


def protected(snapshot):
    require(isinstance(snapshot, dict) and snapshot.get('id') == PRODUCT
            and snapshot.get('status') == 'ACTIVE', 'target_or_status_mismatch')
    # Only updatedAt may legitimately change with description; everything else,
    # including title, ingredients elsewhere, prices and media, remains bound.
    require('descriptionHtml' in snapshot, 'body_missing')
    return {k: v for k, v in snapshot.items() if k not in ('descriptionHtml', 'updatedAt')}


def verify_readback(original, actual):
    require(canonical(protected(original)) == canonical(protected(actual)),
            'protected_projection_changed')
    require(isinstance(actual.get('descriptionHtml'), str) and
            digest(actual['descriptionHtml'].encode()) == AFTER, 'after_body_mismatch')
    return {'state': 'desired_projection_observed', 'unknown_write_resolved': False,
            'atomic_compare_and_swap': False, 'source_holds_retained': True}


@dataclass(frozen=True)
class ReviewedSlot:
    """Unissued model. Production must pin this in reviewed code, not JSON input."""
    workflow_id: int
    run_number: int
    code_sha: str
    approved_at: datetime
    expires_at: datetime
    original_projection_sha256: str
    checkpoint_id: int
    checkpoint_digest: str


def validate_slot(slot, run, checkpoint, original_journal, *, now):
    """Pure model validator, not a GitHub authentication boundary.

    Slot requires an existing pinned write-ahead checkpoint. Missing/expired/
    deleted original evidence never permits creating a replacement. Approval
    timing and numeric run slot remain unissued until explicit review.
    """
    require(type(slot) is ReviewedSlot, 'reviewed_slot_required')
    require(all(type(v) is int and v > 0 for v in
                (slot.workflow_id, slot.run_number, slot.checkpoint_id)), 'slot_identity_invalid')
    require(isinstance(slot.code_sha, str) and bool(re.fullmatch('[0-9a-f]{40}', slot.code_sha)), 'code_sha_invalid')
    require(all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
                for v in (slot.original_projection_sha256, slot.checkpoint_digest)), 'digest_invalid')
    require(all(isinstance(v, datetime) and v.tzinfo is not None and v.utcoffset() == timedelta(0)
                for v in (now, slot.approved_at, slot.expires_at)), 'utc_times_required')
    require(slot.approved_at <= now < slot.expires_at
            and timedelta(0) < slot.expires_at-slot.approved_at <= timedelta(hours=24), 'slot_expired_or_invalid')
    require(isinstance(run, dict) and run.get('repository_id') == 1431541717
            and run.get('workflow_id') == slot.workflow_id
            and type(run.get('run_number')) is int and run.get('run_number') == slot.run_number
            and type(run.get('run_attempt')) is int and run.get('run_attempt') == 1
            and run.get('head_sha') == slot.code_sha and run.get('head_branch') == 'main'
            and run.get('event') == 'workflow_dispatch' and run.get('status') == 'in_progress'
            and type(run.get('id')) is int and run['id'] > 0, 'exact_run_slot_required')
    require(isinstance(checkpoint, dict) and checkpoint.get('id') == slot.checkpoint_id
            and checkpoint.get('expired') is False
            and checkpoint.get('digest') == 'sha256:'+slot.checkpoint_digest
            and checkpoint.get('workflow_run') == {'id': run['id'], 'head_sha': slot.code_sha},
            'original_checkpoint_missing_or_changed')
    require(isinstance(original_journal, dict)
            and original_journal.get('operation_id') == operation_id()
            and original_journal.get('run_id') == str(run['id'])
            and original_journal.get('run_attempt') == '1'
            and original_journal.get('code_sha') == slot.code_sha
            and original_journal.get('before_projection_sha256') == slot.original_projection_sha256
            and original_journal.get('state') == 'prepared'
            and type(original_journal.get('write_attempts')) is int and original_journal.get('write_attempts') == 0, 'original_intent_required')
    return {'model_checks_passed': True, 'execution_authorized': False,
            'operation_id': operation_id(), 'max_mutations_proposed': 1}


def reconcile_unknown(original, actual):
    # Even matching desired bytes never clears an unknown-request STOP by itself.
    try:
        verify_readback(original, actual)
        observed = 'desired_projection_observed'
    except (ValueError, TypeError, KeyError):
        observed = 'review_required'
    return {'observed': observed, 'state': 'unknown_write_stop', 'retry_allowed': False}


def verify_target(snapshot, publications):
    """Validate saved declared projection, not claim a complete live snapshot."""
    protected(snapshot)
    variants = snapshot.get('variants')
    require(isinstance(variants, list) and len(variants) == 2 and
            all(isinstance(v, dict) for v in variants) and
            {v.get('id'): v.get('sku') for v in variants} == VARIANTS,
            'exact_variants_required')
    require(snapshot.get('totalVariants') == 2 and
            [t for t in snapshot.get('tags', []) if isinstance(t, str) and t.startswith('daiso-pd-')] == ['daiso-pd-1067498'], 'exact_supplier_required')
    require(isinstance(publications, dict) and publications.get('data', {}).get('shop') ==
            {'id': 'gid://shopify/Shop/'+SHOP, 'myshopifyDomain': HOST}, 'shop_binding_required')
    p = publications['data'].get('product', {})
    require(p.get('id') == PRODUCT, 'publication_target_required')
    for key in ('resourcePublications', 'unpublishedPublications'):
        c = p.get(key, {})
        require(isinstance(c.get('nodes'), list) and
                c.get('pageInfo', {}).get('hasNextPage') is False, 'complete_publications_required')
    published = p['resourcePublications']['nodes']
    require(len(published) == 1 and published[0].get('isPublished') is True
            and published[0].get('publication', {}).get('id') == PUBLICATION,
            'sole_copilot_publication_required')
    unpublished = p['unpublishedPublications']['nodes']
    require(len(unpublished) == 6 and all(isinstance(n, dict) and isinstance(n.get('id'), str) for n in unpublished)
            and len({n['id'] for n in unpublished}) == 6 and PUBLICATION not in {n['id'] for n in unpublished},
            'unpublished_channel_inventory_changed')
    return digest(canonical({'product': snapshot, 'publications': publications}))
