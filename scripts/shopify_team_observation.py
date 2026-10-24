"""Bounded shop catalog observation, never a repair or publication authority.

Six fixed requests: existing verified session plus two identical catalog reads.
No queries from tasks/content, no retries, no customer/order data. A matching
read is an observation, not atomic CAS, a verified repair, or a permission grant.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import signal
from urllib.parse import urlsplit

import shopify_readonly_preflight as connection
from team_fix_protocol import AUTHORITY

QUERY = '''query JarvisReadonlyCatalogObservation {
 products(first:50, sortKey:ID) {
  nodes { id status updatedAt onlineStoreUrl }
  pageInfo { hasNextPage endCursor }
 }
}'''
QUERY_BODY = json.dumps({'query': QUERY}, separators=(',', ':')).encode()
STATUSES = ('ACTIVE', 'ARCHIVED', 'DRAFT', 'UNLISTED')
REPO = 'coarfamily-cyber/jarvis-luna'
REPO_ID = '1431541717'
WORKFLOW = 'Owned Shopify team observation'
SAFE_ERRORS = frozenset({
    'execution_context_invalid', 'catalog_graphql_error', 'catalog_shape_invalid',
    'catalog_truncated', 'catalog_duplicate_id', 'catalog_id_order_invalid',
    'product_shape_invalid', 'product_identity_invalid', 'product_status_invalid',
    'product_time_invalid', 'product_time_future', 'product_url_invalid',
    'catalog_changed_between_reads', 'clock_invalid', 'observation_duration_invalid',
    'total_deadline_exceeded', 'readonly_observation_failed_redacted',
})


class ObservationError(ValueError):
    pass


def need(value, code):
    if not value:
        raise ObservationError(code)


def canonical(doc):
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc(value):
    need(isinstance(value, datetime) and value.tzinfo is not None
         and value.utcoffset() == timedelta(0), 'clock_invalid')
    return value


def stamp(value):
    need(type(value) is str and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value),
        'product_time_invalid')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ObservationError('product_time_invalid') from None


class CatalogTransport(connection.FixedTransport):
    _operations = dict(connection.OPERATIONS,
        catalog_before=('POST', '/admin/api/2026-10/graphql.json'),
        catalog_recheck=('POST', '/admin/api/2026-10/graphql.json'))
    _bodies = dict(connection.FixedTransport._bodies,
                  catalog_before=QUERY_BODY, catalog_recheck=QUERY_BODY)
    _stages = dict(connection.STAGES, catalog_before='unknown', catalog_recheck='unknown')


def parse_catalog(raw, *, now):
    now = utc(now)
    doc = connection.decode(raw)
    need(not doc.get('errors'), 'catalog_graphql_error')
    need(isinstance(doc.get('data'), dict) and set(doc['data']) == {'products'},
         'catalog_shape_invalid')
    c = doc['data']['products']
    need(isinstance(c, dict) and set(c) == {'nodes', 'pageInfo'}
         and isinstance(c['nodes'], list) and len(c['nodes']) <= 50,
         'catalog_shape_invalid')
    page = c['pageInfo']
    need(isinstance(page, dict) and set(page) == {'hasNextPage', 'endCursor'}
         and type(page['hasNextPage']) is bool
         and (page['endCursor'] is None or type(page['endCursor']) is str
              and 1 <= len(page['endCursor']) <= 4096), 'catalog_shape_invalid')
    # No follow-up pagination or hidden partial total. A larger shop is a new scope.
    need(page['hasNextPage'] is False, 'catalog_truncated')
    result, ids = [], []
    for p in c['nodes']:
        need(isinstance(p, dict) and set(p) == {'id','status','updatedAt','onlineStoreUrl'},
             'product_shape_invalid')
        need(type(p['id']) is str and re.fullmatch(r'gid://shopify/Product/[1-9][0-9]{0,29}', p['id']),
             'product_identity_invalid')
        need(type(p['status']) is str and p['status'] in STATUSES, 'product_status_invalid')
        updated = stamp(p['updatedAt'])
        need(updated <= now + timedelta(minutes=5), 'product_time_future')
        u = p['onlineStoreUrl']
        if u is not None:
            need(type(u) is str and 1 <= len(u) <= 2048 and not any(ord(c) < 33 for c in u),
                 'product_url_invalid')
            try:
                parts = urlsplit(u)
                allowed = (parts.scheme == 'https' and parts.hostname in
                           {connection.HOST, connection.PUBLIC_ALIAS}
                           and parts.port in (None,443) and not parts.username and not parts.password
                           and not parts.query and not parts.fragment and '/products/' in parts.path)
            except ValueError:
                allowed = False
            need(allowed, 'product_url_invalid')
        ids.append(int(p['id'].rsplit('/', 1)[1]))
        # No URLs, titles, HTML, credentials or merchant free text in the receipt.
        result.append({'product_id': p['id'], 'status': p['status'],
                       'updated_at': p['updatedAt'], 'online_store_url_present': u is not None,
                       'online_store_url_sha256': sha(u.encode()) if u is not None else None})
    need(len(ids) == len(set(ids)), 'catalog_duplicate_id')
    need(ids == sorted(ids), 'catalog_id_order_invalid')
    return result


def summarize(first, second):
    need(canonical(first) == canonical(second), 'catalog_changed_between_reads')
    counts = {s: sum(p['status'] == s for p in second) for s in STATUSES}
    online = sum(p['online_store_url_present'] for p in second)
    # These are observations for team review, not errors, tasks completed, or write plans.
    return {'product_count': len(second), 'status_counts': counts,
            'online_store_url_present_count': online,
            'active_without_online_store_url_count': sum(
                p['status'] == 'ACTIVE' and not p['online_store_url_present'] for p in second),
            'team_observations': [
                {'team': 'listing', 'kind': 'catalog_status_observation',
                 'meaning': 'status inventory only; legal/source readiness not inspected'},
                {'team': 'channels', 'kind': 'online_store_url_observation',
                 'meaning': 'missing URL may be intentional; no activation or publication instruction'},
            ],
            'orders': None, 'revenue': None, 'human_sessions': None,
            'checkout_health': 'not_observed', 'shipping_price': None,
            'customer_market_availability': 'not_observed',
            'source_or_label_readiness': 'not_observed'}


def context(environ):
    need(environ.get('GITHUB_ACTIONS') == 'true'
         and environ.get('GITHUB_REPOSITORY') == REPO
         and environ.get('GITHUB_REPOSITORY_ID') == REPO_ID
         and environ.get('GITHUB_REF') == 'refs/heads/main'
         and environ.get('GITHUB_WORKFLOW') == WORKFLOW
         and environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
         and environ.get('GITHUB_RUN_ATTEMPT') == '1'
         and re.fullmatch(r'[0-9a-f]{40}', environ.get('GITHUB_SHA', '')) is not None
         and environ.get('EXPECTED_SHA') == environ.get('GITHUB_SHA')
         and re.fullmatch(r'[1-9][0-9]*', environ.get('GITHUB_RUN_ID', '')) is not None,
         'execution_context_invalid')
    return {'repository': REPO, 'repository_id': int(REPO_ID),
            'run_id': int(environ['GITHUB_RUN_ID']), 'run_attempt': 1,
            'code_sha': environ['GITHUB_SHA'], 'workflow': WORKFLOW,
            'trigger': 'workflow_dispatch'}


def write_once(path, doc):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(canonical(doc)); stream.flush(); os.fsync(stream.fileno())


def safe_reason(error):
    if type(error) is connection.PreflightError:
        return connection.PreflightError(getattr(error, 'code', None)).code
    if type(error) is ObservationError and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in SAFE_ERRORS:
        return error.args[0]
    return 'readonly_observation_failed_redacted'


def execute(output, environ, *, transport=None, clock=None):
    """Fresh private directory, one attempt. Not a cross-run durable deduplication ledger."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = utc(clock())
    provenance = context(environ)  # Always checked, including injected transport tests.
    output = Path(output)
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        return {'state':'blocked', 'reason':'attempt_exists_no_retry', 'summary':None,
                'product_writes':0, 'live_writer_authorized':False, **AUTHORITY}
    base = {'schema_version': 1, 'mode': 'fresh_readonly_catalog_observation',
            'shop_id': connection.SHOP_ID, 'app_id': connection.APP_ID,
            'installation_id': connection.INSTALLATION_ID, 'api_version': connection.API_VERSION,
            'started_at': started.isoformat(), 'provenance': provenance,
            'query_sha256': sha(QUERY_BODY), 'product_writes': 0,
            'live_writer_authorized': False, 'execution_authority': 'none', **AUTHORITY}
    write_once(output / 'attempt.json', dict(base, state='started', request_limit=6))
    stage = 'connection'
    try:
        transport = transport or CatalogTransport()
        identity, token = connection._verified_session(environ, transport=transport)
        stage = 'catalog_before'
        first_raw = transport('catalog_before', token=token)
        first = parse_catalog(first_raw, now=utc(clock()))
        stage = 'catalog_recheck'
        second_raw = transport('catalog_recheck', token=token)
        ended = utc(clock())
        second = parse_catalog(second_raw, now=ended)
        need(timedelta(0) <= ended-started <= timedelta(seconds=150), 'observation_duration_invalid')
        stage = 'team_observation'
        summary = summarize(first, second)
        result = dict(base, state='observed', observed_at=ended.isoformat(),
            complete_catalog_projection=True, summary=summary,
            before_response_sha256=sha(first_raw), recheck_response_sha256=sha(second_raw),
            projection_sha256=sha(canonical(second)),
            connection_receipt_sha256=sha(canonical(identity)),
            binding='hashes bind observed bytes; not a trusted execution/repair completion receipt',
            comparison_scope='two matching declared projections, not atomic CAS or market/checkout testing',
            external_mutations=0, retry_allowed=False)
    except Exception as error:
        result = dict(base, state='blocked', stage=stage, reason=safe_reason(error),
                      summary=None, complete_catalog_projection=False,
                      retry_allowed=False)
    write_once(output / 'result.json', result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    def deadline(*_):
        raise ObservationError('total_deadline_exceeded')
    signal.signal(signal.SIGALRM, deadline); signal.alarm(150)
    try:
        result = execute(args.output, os.environ)
        # Only finite metadata; product rows never leave process memory.
        print(json.dumps({'state':result['state'], 'reason':result.get('reason'),
                          'product_writes':0, 'live_writer_authorized':False}))
        return 0 if result['state'] == 'observed' else 1
    except Exception as error:
        print(json.dumps({'state':'blocked', 'reason':safe_reason(error),
                          'product_writes':0, 'live_writer_authorized':False}))
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
