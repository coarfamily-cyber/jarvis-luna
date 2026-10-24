"""Pure local FX consistency checks, not authenticated retrieval or trading authority.

Retained observations never receive a new observation timestamp. Freshness is
separate from validity so a genuine historical observation is not fabricated away.
"""
import math
import re
from datetime import date, datetime, timezone

ENDPOINTS = {
    'Frankfurter API': 'https://api.frankfurter.app/latest?from=USD&to=KRW',
    'ExchangeRate-API': 'https://open.er-api.com/v6/latest/USD',
    'exchangerate-api': 'https://api.exchangerate-api.com/v4/latest/USD',
}


def _clock(now):
    value = datetime.now(timezone.utc) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('aware_clock_required')
    return value.astimezone(timezone.utc)


def assess_fx(fx, now=None, max_age_days=4):
    """Validate a cache-shaped observation; missing metadata never becomes today."""
    clock = _clock(now)
    if type(max_age_days) not in (int, float) or not math.isfinite(max_age_days) or max_age_days < 0:
        raise ValueError('invalid_age_policy')
    reasons = []
    if not isinstance(fx, dict):
        fx = {}
    rate = fx.get('usd_to_krw')
    if type(rate) not in (int, float) or not 500 <= rate <= 3000 or not math.isfinite(rate):
        reasons.append('rate_invalid')
    if fx.get('ok') is not True:
        reasons.append('observation_not_successful')
    raw_day = fx.get('as_of')
    day = None
    try:
        if not isinstance(raw_day, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', raw_day):
            raise ValueError
        day = date.fromisoformat(raw_day)
        if day > clock.date():
            reasons.append('source_date_future')
    except ValueError:
        reasons.append('source_date_invalid')
    raw_time = fx.get('fetched_at')
    observed = None
    try:
        if not isinstance(raw_time, str):
            raise ValueError
        observed = datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError
        observed = observed.astimezone(timezone.utc)
        if observed > clock:
            reasons.append('observation_future')
        if day is not None and day > observed.date():
            reasons.append('source_after_observation')
    except (ValueError, OverflowError):
        reasons.append('observation_time_invalid')
    source = fx.get('source')
    endpoint = ENDPOINTS.get(source) if isinstance(source, str) else None
    if endpoint is None and isinstance(source, str) and source in ENDPOINTS.values():
        endpoint = source
    if endpoint is None or ('api_url' in fx and fx['api_url'] != endpoint):
        reasons.append('source_endpoint_invalid')
    if reasons:
        return {'valid': False, 'fresh': False, 'state': 'invalid', 'reasons': reasons, 'observation': None,
                'source_age_days': None, 'observation_age_days': None}
    source_age = (clock.date() - day).days
    observation_age = (clock - observed).total_seconds() / 86400
    fresh = source_age <= max_age_days and observation_age <= max_age_days
    canonical = {'usd_to_krw': rate, 'krw_to_usd': round(1 / rate, 8),
                 'as_of': raw_day, 'source': source, 'api_url': endpoint,
                 'fetched_at': raw_time, 'ok': True}
    return {'valid': True, 'fresh': fresh, 'state': 'fresh' if fresh else 'stale',
            'reasons': [] if fresh else ['observation_stale'], 'observation': canonical,
            'source_age_days': source_age, 'observation_age_days': observation_age}


def select_fx(prev, incoming, now=None):
    """Choose monotonic source dates; invalid attempts cannot refresh cached time."""
    clock = _clock(now)
    old, new = assess_fx(prev, clock), assess_fx(incoming, clock)
    selection = 'none'
    chosen = new
    if new['valid']:
        selection = 'incoming'
    if old['valid'] and (not new['valid'] or
            new['observation']['as_of'] < old['observation']['as_of']):
        chosen, selection = old, 'previous'
    # At equal source dates do not move the actual observation clock backwards.
    elif old['valid'] and new['valid'] and new['observation']['as_of'] == old['observation']['as_of']:
        def timestamp(result):
            return datetime.fromisoformat(result['observation']['fetched_at'].replace('Z', '+00:00'))
        if timestamp(new) < timestamp(old):
            chosen, selection = old, 'previous'
    result = dict(chosen, selection=selection)
    if selection == 'previous' and result['fresh']:
        result['state'] = 'cached'
    return result


def dashboard_fx(fx, now=None):
    """Project only validated cache facts; an invalid observation has no rate card."""
    result = assess_fx(fx, now)
    if not result['valid']:
        return {}
    row = result['observation']
    state = result['state']
    if result['fresh'] and (fx.get('selection') == 'previous' or fx.get('last_attempt_ok') is False):
        state = 'cached'
    return {'rate': row['usd_to_krw'], 'as_of': row['as_of'],
            'source': row['source'], 'api_url': row['api_url'],
            'fetched_at': row['fetched_at'], 'stale': not result['fresh'],
            'state': state, 'source_age_days': result['source_age_days'],
            'observation_age_days': result['observation_age_days']}
