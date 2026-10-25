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

# Observed 2026-10-24/25: supplier data has competing formulas/quantities/origin.
# Removal requires a separately reviewed actual-stock/source reconciliation.
OPEN_CONFLICTS = {
    '1067498': ('supplier_formula_actual_stock_unresolved',),
    '1025282': ('supplier_net_contents_conflict_unresolved',),
    # Dr.CPU: supplier package 60 ml versus archived catalogue 60 g.
    '1084687': ('supplier_net_contents_conflict_unresolved',),
    # Blistex: 4.25 g versus approximately 4.5 g; USA versus Korea.
    '1076498': ('supplier_net_contents_conflict_unresolved',
                'supplier_origin_conflict_unresolved'),
}
FORMULAS = re.compile(r'신형|구형|리뉴얼\s*(?:전|후)|(?:old|new)\s+formula', re.I)
ML = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*m[lL]\b', re.I)


def inspect(pd_no, name, notice):
    reasons, rows = [], []
    if notice.get('_supplier_disclosure_conflict') is True:
        reasons.append('supplier_disclosure_versions_conflict')
    if str(pd_no) in OPEN_CONFLICTS:
        reasons.extend(OPEN_CONFLICTS[str(pd_no)])
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
            'origin_hold': any('origin_conflict' in r for r in reasons),
            'retained_supplier_snapshot_sha256': notice.get('_retained_disclosure_sha256'),
            'human_approved': False, 'physical_label_verified': False,
            'publication_allowed': False}



# Exact disputed source quantities only. Never strip unrelated model numbers,
# percentages, bundle counts, ingredients, or the original product/source record.
_QUANTITY_COPY_PATTERNS = {
    '1084687': re.compile(r'(?<![\w.])60\s*(?:ml|millilit(?:er|re)s?|g|grams?)(?![\w])'
        r'(?:\s*\(\s*2\.0[23]\s*fl\.?\s*oz\s*\))?', re.I),
    '1076498': re.compile(r'(?<![\w.])4\.(?:25|5)\s*(?:g|grams?)(?![\w])'
        r'(?:\s*\(\s*0\.1[56]\s*oz\s*\))?', re.I),
}


def _hold_quantity_text_nodes(body, pattern):
    """Map rendered text back to original text-node spans; retain markup bytes."""
    from html import unescape
    parts = re.split(r"""(<(?:[^>"']|"[^"]*"|'[^']*')*>)""", body)
    visible, positions = [], []
    for index in range(0, len(parts), 2):
        raw = parts[index]
        for token in re.finditer(r'&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]+);|.', raw, re.S):
            decoded = unescape(token.group())
            visible.extend(decoded)
            positions.extend([(index, token.start(), token.end())] * len(decoded))
    matches = list(pattern.finditer(''.join(visible)))
    # Backwards edits leave earlier raw offsets stable, even across emphasis tags.
    for match in reversed(matches):
        spans = {}
        for index, start, end in positions[match.start():match.end()]:
            if index not in spans:
                spans[index] = [start, end]
            else:
                spans[index][0] = min(spans[index][0], start)
                spans[index][1] = max(spans[index][1], end)
        first = min(spans)
        for index, (start, end) in spans.items():
            replacement = 'net contents unverified' if index == first else ''
            parts[index] = parts[index][:start] + replacement + parts[index][end:]
    return ''.join(parts)


def hold_conflicting_quantity_copy(pd_no, selected_copy):
    """Limit customer-facing copy, not source identity or registration authority."""
    from copy import deepcopy
    out = deepcopy(selected_copy)
    pattern = _QUANTITY_COPY_PATTERNS.get(str(pd_no))
    if pattern is None or not isinstance(out, dict):
        return out
    title = out.get('title')
    if isinstance(title, str) and pattern.search(title):
        out['title'] = ' '.join(pattern.sub('', title).split()) + ' (net contents unverified)'
    body = out.get('description_html')
    if isinstance(body, str):
        out['description_html'] = _hold_quantity_text_nodes(body, pattern)
    return out


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
