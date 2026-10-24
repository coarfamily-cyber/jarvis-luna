"""Pure draft-only supplier disclosure checks; no translation or approval authority.

Raw supplier words are preserved, not promoted to physical-label facts. Known
unresolved identity conflicts are conservative holds, not inferred corrections.
"""
import hashlib
import json
import os
import stat
import re
from decimal import Decimal

# Observed 2026-10-24: current supplier data has competing formulas/quantities.
# Removal requires a separately reviewed actual-stock/source reconciliation.
OPEN_CONFLICTS = {'1067498': 'supplier_formula_actual_stock_unresolved',
                  '1025282': 'supplier_net_contents_conflict_unresolved'}
FORMULAS = re.compile(r'신형|구형|리뉴얼\s*(?:전|후)|(?:old|new)\s+formula', re.I)
ML = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*m[lL]\b', re.I)


def inspect(pd_no, name, notice):
    reasons, rows = [], []
    if notice.get('_supplier_disclosure_conflict') is True:
        reasons.append('supplier_disclosure_versions_conflict')
    if str(pd_no) in OPEN_CONFLICTS:
        reasons.append(OPEN_CONFLICTS[str(pd_no)])
    source = {key: notice.get(key, '') for key in
              ('usage', 'warnings', 'color', 'ingredients', 'volume', 'source_notice_text')}
    for key, heading in [('usage', 'Directions'), ('warnings', 'Warnings'), ('color', 'Color')]:
        raw = source[key]
        if isinstance(raw, str) and raw.strip():
            # Never replace the source with AI translation or mark human_approved.
            rows.append((heading + ' (supplier source text; unverified)', raw.strip()))
            reasons.append(key + '_source_requires_label_review')
        elif key != 'color':
            reasons.append(key + '_source_missing')
    text = '\n'.join(v for v in source.values() if isinstance(v, str))
    if FORMULAS.search(text):
        reasons.append('supplier_formula_variants_require_stock_reconciliation')
    title_ml = {Decimal(v) for v in ML.findall(str(name))}
    notice_ml = {Decimal(v) for v in ML.findall(str(source['volume']))}
    if title_ml and notice_ml and title_ml != notice_ml:
        reasons.append('supplier_title_notice_volume_conflict')
    return {'rows': rows, 'reasons': sorted(set(reasons)),
            'source_sha256': hashlib.sha256(json.dumps(source, ensure_ascii=False,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'formula_hold': any('formula' in r for r in reasons),
            'volume_hold': any('volume_conflict' in r or 'net_contents_conflict' in r for r in reasons),
            'retained_supplier_snapshot_sha256': notice.get('_retained_disclosure_sha256'),
            'human_approved': False, 'physical_label_verified': False,
            'publication_allowed': False}


def with_retained_supplier_text(root, pd_no, notice):
    """Reuse existing supplier transcription, never its approval/status claims.

    Exact product URL is required. Missing fields may be supplemented; conflicting
    source versions are retained as a hold, never silently substituted.
    """
    from pathlib import Path
    from copy import deepcopy
    if not isinstance(notice, dict):
        raise ValueError('notice_object_required')
    out = deepcopy(notice)
    out.pop('_retained_disclosure_sha256', None)
    path = Path(root) / 'data/manual/official_label_text.json'
    if path.is_symlink():
        return out
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return out
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            return out
        doc = json.loads(raw)
    except (OSError, ValueError):
        return out
    items = doc.get('items') if isinstance(doc, dict) else None
    row = items.get(str(pd_no)) if isinstance(items, dict) else None
    if not isinstance(row, dict):
        return out
    url = 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=' + str(pd_no)
    sources = row.get('sources')
    if not isinstance(sources, list) or not any(isinstance(s, dict) and s.get('url') == url for s in sources):
        return out
    for target, source in [('usage', 'directions_ko'), ('warnings', 'warnings_ko')]:
        value = row.get(source)
        if not isinstance(value, str) or not value.strip():
            continue
        if not out.get(target):
            out[target] = value
        elif out[target] != value:
            out['_supplier_disclosure_conflict'] = True
    out['_retained_disclosure_sha256'] = hashlib.sha256(raw).hexdigest()
    return out
