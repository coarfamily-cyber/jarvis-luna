"""Bounded provider observation; never writes pricing inputs or publishes a site.

The existing fx_provenance validator is reused. A receipt is evidence of one
provider response, not independently authenticated FX truth or a pricing grant.
"""
import hashlib
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.request
import fx_provenance

ENDPOINT = fx_provenance.ENDPOINTS['ExchangeRate-API']
MAX_BYTES = 64000
MAX_SOURCE_AGE_SECONDS = 4 * 86400

class ObservationError(ValueError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ObservationError('redirect_forbidden')

def _pairs(pairs):
    out = {}
    for key, val in pairs:
        if key in out: raise ObservationError('duplicate_json_key')
        out[key] = val
    return out

def _clock(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ObservationError('aware_clock_required')
    return value.astimezone(timezone.utc)

def parse_response(raw, observed_at, previous=None):
    now = _clock(observed_at)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ObservationError('response_size')
    try:
        doc = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ObservationError('nonfinite_json')))
        if not isinstance(doc, dict) or doc.get('result') != 'success' or doc.get('base_code') != 'USD':
            raise ObservationError('provider_identity')
        if doc.get('provider') != 'https://www.exchangerate-api.com':
            raise ObservationError('provider_identity')
        unix = doc['time_last_update_unix']
        if type(unix) is not int: raise ObservationError('source_timestamp')
        stamp = datetime.fromtimestamp(unix, timezone.utc)
        text = doc['time_last_update_utc']
        if type(text) is not str or not 1 <= len(text) <= 64:
            raise ObservationError('source_timestamp')
        rendered = parsedate_to_datetime(text)
        if rendered.tzinfo is None or rendered.astimezone(timezone.utc) != stamp:
            raise ObservationError('source_timestamp_mismatch')
        age = (now-stamp).total_seconds()
        if age < 0 or age > MAX_SOURCE_AGE_SECONDS: raise ObservationError('source_stale_or_future')
        rate = doc['rates']['KRW']
        obs = {'ok': True, 'usd_to_krw': rate, 'as_of': stamp.date().isoformat(),
               'fetched_at': now.isoformat(), 'source':'ExchangeRate-API','api_url':ENDPOINT}
        result = fx_provenance.assess_fx(obs, now=now)
        if not result['valid'] or not result['fresh']: raise ObservationError('invalid_fx')
        if previous is not None:
            prior = fx_provenance.assess_fx(previous, now=now)
            if not prior['valid']: raise ObservationError('invalid_previous')
            selection = fx_provenance.select_fx(previous, obs, now=now)
            if selection['selection'] != 'incoming': raise ObservationError('source_regression')
    except ObservationError: raise
    except (ValueError, KeyError, TypeError, OverflowError, UnicodeError, RecursionError):
        raise ObservationError('invalid_provider_response') from None
    return {'schema_version':1,'kind':'fx_readonly_observation',
            'status':'observed','request_limit':1,'response_sha256':hashlib.sha256(raw).hexdigest(),
            'source_updated_at':stamp.isoformat(), 'source_age_seconds':age,
            'observation':result['observation'], 'pricing_applied':False,
            'product_writes':0,'shipping_writes':0,'fee_assumption':None,
            'shipping_planning_floor_krw_per_order':9000,
            'purpose':'observation_only_not_pricing_input'}

def observe(previous=None, *, now=None, opener=None):
    # No user-controlled URL, redirects, credentials, retries, or repository paths.
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(ENDPOINT, headers={'User-Agent':'JarvisFXObservation/1.0','Accept':'application/json'})
    try:
        with client.open(req, timeout=20) as response:
            if response.status != 200 or response.geturl() != ENDPOINT:
                raise ObservationError('http_or_url')
            if response.headers.get_content_type() != 'application/json':
                raise ObservationError('content_type')
            if response.headers.get('Content-Encoding', 'identity') != 'identity':
                raise ObservationError('encoding')
            raw = response.read(MAX_BYTES+1)
    except ObservationError: raise
    except Exception:
        # Never include third-party response/error body in the artifact/log.
        raise ObservationError('provider_unavailable') from None
    return parse_response(raw, now or datetime.now(timezone.utc), previous)
