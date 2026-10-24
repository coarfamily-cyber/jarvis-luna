"""One fixed Organist team task: authenticated read/recheck, never product writes.

No-op means an already-corrected field was observed twice, not a new repair.
Matching reads are not atomic CAS. Local attempt files are not a cross-run ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
from datetime import datetime, timezone
import shopify_readonly_preflight as connection
import team_fix_protocol as protocol
from team_repair_rehearsal import RULE, LABEL, FRAGMENT, REPLACEMENT, clean_maker

PRODUCT_ID = 'gid://shopify/Product/9710072889601'
SKU = '1025282'
VARIANT_SKUS = {'gid://shopify/ProductVariant/50932438401281': 'DS-1025282-1',
                'gid://shopify/ProductVariant/50932438597889': 'DS-1025282-2'}
ISSUE = 'supplier-1025282-manufacturer_heading_fragment'
QUERY = '''query JarvisOrganistReadOnly {
 product(id:"gid://shopify/Product/9710072889601") {
  id title handle status descriptionHtml tags updatedAt vendor publishedAt totalInventory
  options { id name position values }
  variants(first:100) { nodes { id sku price compareAtPrice inventoryQuantity
   inventoryItem { id tracked } selectedOptions { name value } }
   pageInfo { hasNextPage endCursor } }
  media(first:100) { nodes { id alt mediaContentType status
   ... on MediaImage { image { url width height } } }
   pageInfo { hasNextPage endCursor } }
  resourcePublications(first:100, onlyPublished:false) {
   nodes { isPublished publishDate publication { id name } }
   pageInfo { hasNextPage endCursor } }
 }
}'''
QUERY_BODY = json.dumps({'query': QUERY}, separators=(',', ':')).encode()


class ProductReadTransport(connection.FixedTransport):
    # No constructor accepts a URL/query/method/target or operation budget.
    _operations = dict(connection.OPERATIONS, product_before=('POST', '/admin/api/2026-10/graphql.json'),
                       product_recheck=('POST', '/admin/api/2026-10/graphql.json'))
    _bodies = dict(connection.FixedTransport._bodies, product_before=QUERY_BODY, product_recheck=QUERY_BODY)
    _stages = dict(connection.STAGES, product_before='unknown', product_recheck='unknown')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, code):
    if not value:
        raise ValueError(code)


def task_and_source(root):
    """Capture current source bytes once; absence remains a hold, never approval."""
    docs, hashes = {}, {}
    for name in ('gosi.json', 'shopify_daily_registry.json'):
        raw = protocol.read_regular(Path(root) / 'data' / name, 8388608)
        def unique(items):
            out = {}
            for key, value in items:
                require(key not in out, 'source_duplicate_key')
                out[key] = value
            return out
        docs[name] = json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('source_nonfinite')))
        canonical(docs[name])  # Also reject overflow-created nonfinite floats.
        hashes[name] = digest(raw)
    registry = docs['shopify_daily_registry.json']
    require(isinstance(registry, dict) and isinstance(registry.get('items'), list), 'source_schema')
    entries = [r for r in registry['items'] if isinstance(r, dict) and str(r.get('pd_no')) == SKU]
    require(len(entries) == 1, 'source_target_missing_or_duplicate')
    notices = docs['gosi.json']
    require(isinstance(notices, dict) and isinstance(notices.get('items'), dict), 'source_schema')
    notice = notices['items'].get(SKU)
    source_hold = not (isinstance(notice, dict) and notice.get('maker') == FRAGMENT)
    # The approved target audit is handed to the existing team protocol, with no
    # receipt references or permission flags fabricated. Its pending state stays.
    task = protocol.project(root, [{'issue_id': ISSUE, 'rule': RULE}])['issues'][0]
    return task, hashes, source_hold or task['state'] != 'independently_verified'


def product(raw):
    doc = connection.decode(raw)
    require(not doc.get('errors') and isinstance(doc.get('data'), dict), 'product_read_error')
    p = doc['data'].get('product')
    required = {'id','title','handle','status','descriptionHtml','tags','updatedAt','vendor',
                'publishedAt','totalInventory','options','variants','media','resourcePublications'}
    require(isinstance(p, dict) and set(p) == required, 'product_projection_incomplete')
    require(p['id'] == PRODUCT_ID and p['status'] == 'DRAFT', 'product_identity_or_status')
    require(isinstance(p['descriptionHtml'], str) and isinstance(p['tags'], list) and
            all(isinstance(t, str) for t in p['tags']) and
            [t for t in p['tags'] if t.startswith('daiso-pd-')] == ['daiso-pd-' + SKU], 'product_sku_binding')
    for field in ('variants', 'media', 'resourcePublications'):
        c = p[field]
        require(isinstance(c, dict) and set(c) == {'nodes','pageInfo'} and
                isinstance(c['nodes'], list) and len(c['nodes']) <= 100 and
                isinstance(c['pageInfo'], dict) and set(c['pageInfo']) == {'hasNextPage','endCursor'} and
                c['pageInfo'].get('hasNextPage') is False,
                'product_projection_truncated')
    variants = p['variants']['nodes']
    require(len(variants) == len(VARIANT_SKUS) and all(isinstance(v, dict) for v in variants) and
            {v.get('id'):v.get('sku') for v in variants} == VARIANT_SKUS, 'variant_sku_mismatch')
    for v in variants:
        require(set(v) == {'id','sku','price','compareAtPrice','inventoryQuantity','inventoryItem','selectedOptions'} and
                isinstance(v['price'], str) and isinstance(v['inventoryItem'], dict) and
                set(v['inventoryItem']) == {'id','tracked'} and type(v['inventoryItem']['tracked']) is bool and
                type(v['inventoryQuantity']) is int and isinstance(v['selectedOptions'], list),
                'variant_projection_incomplete')
    require(isinstance(p['options'], list) and isinstance(p['updatedAt'], str) and
            isinstance(p['title'], str) and isinstance(p['handle'], str) and isinstance(p['vendor'], str) and
            type(p['totalInventory']) is int, 'product_projection_incomplete')
    require(len({v['id'] for v in variants}) == len(variants), 'duplicate_variant')
    for m in p['media']['nodes']:
        require(isinstance(m, dict) and {'id','alt','mediaContentType','status'} <= set(m), 'media_projection_incomplete')
        if m['mediaContentType'] == 'IMAGE':
            require(isinstance(m.get('image'), dict) and set(m['image']) == {'url','width','height'},
                    'image_projection_incomplete')
    for pub in p['resourcePublications']['nodes']:
        require(isinstance(pub, dict) and set(pub) == {'isPublished','publishDate','publication'} and
                type(pub['isPublished']) is bool and isinstance(pub['publication'], dict) and
                set(pub['publication']) == {'id','name'}, 'publication_projection_incomplete')
    return p


def evaluate(task, first, second, source_hold):
    require(isinstance(task, dict), 'unsupported_task_requires_review')
    require(task.get('issue_id') == ISSUE and task.get('rule') == RULE and task.get('team') == 'sourcing',
            'unsupported_task_requires_review')
    require(all(task.get(key) is False for key in protocol.AUTHORITY), 'task_cannot_grant_authority')
    require(canonical(first) == canonical(second), 'fresh_product_changed_requires_review')
    body = first['descriptionHtml']
    fields = list(re.finditer(re.escape(LABEL) + r'(?P<value>[^<]*)</(?:p|li)>', body))
    require(body.count(LABEL) == 1 and len(fields) == 1, 'manufacturer_field_ambiguous')
    value = fields[0].group('value').strip()
    result = {'rule': RULE, 'source_hold_retained': source_hold,
              'before_product_sha256': digest(canonical(first)),
              'recheck_product_sha256': digest(canonical(second)),
              'mutation_attempted': False, 'product_writes': 0, 'mode': 'fresh_read_only_dry_run',
              'comparison_scope': 'declared GraphQL projection only; not atomic CAS',
              'unresolved_holds': ['manufacturer_identity', 'volume_conflict', 'ingredient_identity_not_verified'],
              **protocol.AUTHORITY}
    if value == REPLACEMENT:
        result.update(state='verified_no_op', reason='already_corrected_pending_marker_observed_twice')
    elif value == FRAGMENT:
        # Reuse the published role-fragment rule; this creates no new maker fact.
        require(clean_maker(value) == '', 'published_fragment_rule_changed')
        field = fields[0]
        original = field.group('value')
        proposed_body = body[:field.start('value')] + original.replace(FRAGMENT, REPLACEMENT, 1) + body[field.end('value'):]
        proposed = dict(first, descriptionHtml=proposed_body)
        require([k for k in first if first[k] != proposed[k]] == ['descriptionHtml'], 'changed_field_scope')
        result.update(state='review_required', reason='deterministic_proposal_pending_source_and_independent_review',
                      proposal={'changed_fields':['descriptionHtml'],
                                'description_html_sha256':digest(proposed_body.encode()),
                                'product_sha256':digest(canonical(proposed)), 'executed':False})
    else:
        result.update(state='review_required', reason='unsupported_manufacturer_value')
    return result


def write_once(path, doc):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(canonical(doc)); stream.flush(); os.fsync(stream.fileno())


def execute(root, output, environ, *, transport=None):
    """Caller supplies a fresh private attempt directory; duplicate means no I/O."""
    output = Path(output)
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        return {'state':'blocked', 'reason':'attempt_exists_no_retry', 'product_writes':0, **protocol.AUTHORITY}
    write_once(output / 'attempt.json', {'schema_version':1, 'state':'started', 'product_id':PRODUCT_ID,
               'issue_id':ISSUE, 'mode':'fresh_read_only_dry_run', 'product_writes':0, **protocol.AUTHORITY})
    stage = 'execution_context'
    try:
        if transport is None:
            require(environ.get('GITHUB_ACTIONS') == 'true' and
                    environ.get('GITHUB_REPOSITORY') == 'coarfamily-cyber/jarvis-luna' and
                    environ.get('GITHUB_REF') == 'refs/heads/main' and
                    environ.get('GITHUB_RUN_ATTEMPT') == '1' and
                    re.fullmatch(r'[0-9a-f]{40}', environ.get('GITHUB_SHA', '')) is not None and
                    re.fullmatch(r'[1-9][0-9]*', environ.get('GITHUB_RUN_ID', '')) is not None,
                    'github_main_first_attempt_required')
        stage = 'source_binding'
        task, sources, hold = task_and_source(root)
        stage = 'connection_verification'
        transport = transport or ProductReadTransport()
        identity, token = connection._verified_session(environ, transport=transport)
        stage = 'product_before'
        before_raw = transport('product_before', token=token)
        before = product(before_raw)
        stage = 'product_recheck'
        after_raw = transport('product_recheck', token=token)
        after = product(after_raw)
        stage = 'team_evaluation'
        result = evaluate(task, before, after, hold)
        result.update(schema_version=1, product_id=PRODUCT_ID, issue_id=ISSUE,
                      source_sha256=sources, team_task_sha256=digest(canonical(task)),
                      task_origin='approved_single_target_post_correction_audit',
                      existing_handoff_state=task['state'],
                      before_response_sha256=digest(before_raw), recheck_response_sha256=digest(after_raw),
                      observed_at=datetime.now(timezone.utc).isoformat(),
                      connection_receipt_sha256=digest(canonical(identity)), live_writer_authorized=False)
    except Exception as error:
        # Only declared code enums are emitted; raw messages/cause/notes are ignored.
        allowed = {'github_main_first_attempt_required', 'source_schema', 'source_target_missing_or_duplicate', 'source_duplicate_key',
                   'source_nonfinite', 'product_read_error', 'product_projection_incomplete',
                   'product_identity_or_status', 'product_sku_binding', 'product_projection_truncated',
                   'variant_sku_mismatch', 'variant_projection_incomplete', 'duplicate_variant',
                   'media_projection_incomplete', 'image_projection_incomplete',
                   'publication_projection_incomplete', 'unsupported_task_requires_review',
                   'task_cannot_grant_authority', 'fresh_product_changed_requires_review',
                   'manufacturer_field_ambiguous', 'published_fragment_rule_changed', 'changed_field_scope'}
        reason = 'readonly_task_failed_review_required'
        if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in allowed:
            reason = error.args[0]
        elif type(error) is connection.PreflightError:
            reason = connection.PreflightError(getattr(error, 'code', None)).code
        result = {'schema_version':1, 'state':'blocked', 'reason':reason,
                  'stage':stage, 'product_writes':0, 'live_writer_authorized':False, **protocol.AUTHORITY}
    write_once(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    def deadline(*_): raise TimeoutError()
    signal.signal(signal.SIGALRM, deadline); signal.alarm(150)
    try:
        result = execute(args.root, args.output, os.environ)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get('state') == 'verified_no_op' else 1
    except Exception:
        print(json.dumps({'state':'blocked','reason':'local_attempt_or_deadline_failed','product_writes':0}))
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__': raise SystemExit(main())
