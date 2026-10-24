"""Evidence-bound repair handoff for existing teams; never an execution authority.

Receipts are untrusted local observations. Matching bytes establish binding,
NOT truth, successful live execution, legal approval, or permission to retry.
No shell commands, writes, network calls or dynamic handlers are executed here.
"""
import hashlib
import json
import os
import stat
import re
from pathlib import Path

RULES = {
    'supplier_warning_review': ('listing', 'Source warnings exist: review translation/label binding; do not call this a proven live omission.'),
    'supplier_usage_review': ('listing', 'Source directions exist: review translation/label binding; do not call this a proven live omission.'),
    'supplier_warning_omission': ('listing', 'Preserve every source warning; retain age qualifiers and actual-label hold.'),
    'supplier_usage_omission': ('listing', 'Preserve source directions; do not invent directions or missing cautions.'),
    'source_color_omission': ('design', 'Use only readable source color/number; never infer obscured source fields.'),
    'manufacturer_heading_fragment': ('sourcing', 'Reject role-only fragments; trim only exact role prefix, never guess company.'),
    'volume_conflict': ('listing', 'Hold competing quantities; do not equate mass and volume or pick a title as proof.'),
    'formula_conflict': ('legal', 'Keep old/new formulas separate; actual stock must be independently reconciled.'),
    'promised_evidence': ('legal', 'Future verification and boolean approval are not completed source evidence.'),
}
AUTHORITY = {'publication_allowed': False, 'shopify_write_allowed': False,
             'human_approved': False, 'provider_retry_allowed': False}
HEX = re.compile(r'[0-9a-f]{64}')


def read_regular(path, limit, *, consumed=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular_file_required')
        raw = stream.read(limit + 1)
    if consumed is not None:
        consumed(len(raw))
    if len(raw) > limit:
        raise ValueError('evidence_capacity')
    return raw


def checked_bytes(root, reference, *, consumed=None):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('invalid_reference')
    name, digest = reference['path'], reference['sha256']
    if not isinstance(name, str) or not name.startswith('data/team_fix_evidence/'):
        raise ValueError('evidence_namespace_required')
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts or not isinstance(digest, str) or not HEX.fullmatch(digest):
        raise ValueError('unsafe_reference')
    path = Path(root)
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('symlink_evidence')
    raw = read_regular(path, 1048576, consumed=consumed)
    if len(raw) > 1048576 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('evidence_bytes_mismatch')
    return raw


def checked_file(root, reference):
    return hashlib.sha256(checked_bytes(root, reference)).hexdigest()


def project(root, records):
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError('invalid_repair_receipts')
    output, seen = [], set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('invalid_repair_receipt')
        issue, rule = row.get('issue_id'), row.get('rule')
        if not isinstance(issue, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', issue) or issue in seen or not isinstance(rule, str) or rule not in RULES:
            raise ValueError('invalid_or_duplicate_issue')
        seen.add(issue)
        team, instruction = RULES[rule]
        state, reason, refs = 'review_required', 'missing_source_fix_tests_or_receipt', {}
        # Explicit truthy grants never become learned policy or override a hold.
        if any(row.get(key) is not None and row.get(key) is not False for key in AUTHORITY):
            reason = 'receipt_cannot_grant_authority'
        else:
            try:
                refs = {key: checked_file(root, row.get(key)) for key in
                        ('source', 'before', 'after', 'regression_log', 'readback')}
                if refs['before'] == refs['after'] or refs['after'] != refs['readback']:
                    raise ValueError('before_after_readback_mismatch')
                state, reason = 'evidence_bound_pending_independent_review', 'bytes_bound_not_live_success'
            except (OSError, ValueError):
                reason = 'source_fix_tests_or_receipt_unavailable_or_mismatched'
        output.append({'issue_id': issue, 'rule': rule, 'team': team, 'state': state,
                       'reason': reason, 'next_action': instruction,
                       'required_sequence': ['source', 'before', 'fix', 'regression_tests', 'readback', 'independent_review'],
                       'evidence_sha256': refs, **AUTHORITY})
    return {'schema_version': 1, 'meaning': 'team_repair_handoff_not_execution_or_permission',
            'issues': output, **AUTHORITY}


def discover(root):
    """Read existing registry/gosi outputs; create handoffs, not new facts or writes."""
    from supplier_notice_disclosures import inspect, with_retained_supplier_text
    from daiso.collect_gosi_alt import clean_maker
    root = Path(root)
    docs = []
    for name in ('shopify_daily_registry.json', 'gosi.json'):
        path = root / 'data' / name
        if not path.exists():
            return []
        if path.is_symlink():
            raise ValueError('symlink_source')
        raw = read_regular(path, 8388608)
        if len(raw) > 8388608:
            raise ValueError('source_capacity')
        docs.append(json.loads(raw))
    registry, notices = docs
    if not isinstance(registry, dict) or not isinstance(notices, dict):
        raise ValueError('source_schema')
    entries, items = registry.get('items'), notices.get('items')
    if not isinstance(entries, list) or not isinstance(items, dict):
        raise ValueError('source_schema')
    out = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('registry_entry_schema')
        pd = str(entry.get('pd_no', ''))
        if not re.fullmatch(r'[0-9]{1,12}', pd):
            continue
        notice = items.get(pd, {})
        if not isinstance(notice, dict):
            raise ValueError('notice_schema')
        checked = inspect(pd, entry.get('name_kr', ''), with_retained_supplier_text(root, pd, notice))
        rules = set()
        if 'warnings_source_missing' in checked['reasons']:rules.add('supplier_warning_omission')
        if 'warnings_source_requires_label_review' in checked['reasons']:rules.add('supplier_warning_review')
        if 'usage_source_missing' in checked['reasons']:rules.add('supplier_usage_omission')
        if 'usage_source_requires_label_review' in checked['reasons']:rules.add('supplier_usage_review')
        if checked['formula_hold']:rules.add('formula_conflict')
        if checked['volume_hold']:rules.add('volume_conflict')
        if notice.get('maker') and not clean_maker(notice['maker']):rules.add('manufacturer_heading_fragment')
        for rule in sorted(rules):
            issue = 'supplier-' + pd + '-' + rule
            out[issue] = {'issue_id':issue, 'rule':rule}
    return [out[key] for key in sorted(out)]


def _load_projection(root):
    path = Path(root) / 'data/team_fix_receipts.json'
    discovered = discover(root)
    if not path.exists():
        return project(root, discovered)
    if path.is_symlink():
        raise ValueError('symlink_receipts')
    raw = read_regular(path, 2097152)
    if len(raw) > 2097152:
        raise ValueError('repair_receipts_capacity')
    doc = json.loads(raw)
    if not isinstance(doc, dict) or set(doc) != {'schema_version', 'receipts'} or type(doc['schema_version']) is not int or doc['schema_version'] != 1:
        raise ValueError('repair_receipts_schema')
    receipts = doc['receipts']
    if not isinstance(receipts, list):
        raise ValueError('repair_receipts_schema')
    discovered_rules = {row['issue_id']: row['rule'] for row in discovered}
    for row in receipts:
        if isinstance(row, dict) and isinstance(row.get('issue_id'), str) and row['issue_id'] in discovered_rules:
            if row.get('rule') != discovered_rules[row['issue_id']]:
                raise ValueError('receipt_discovered_rule_mismatch')
    present = {row.get('issue_id') for row in receipts if isinstance(row, dict) and isinstance(row.get('issue_id'), str)}
    return project(root, receipts + [row for row in discovered if row['issue_id'] not in present])


MAX_OFFLINE_REPLAYS = 32
MAX_OFFLINE_REPLAY_BYTES = 8 * 1024 * 1024


def load_projection(root, *, offline_replays=None, now=None):
    """Existing handoff plus explicitly requested saved-input rehearsals only.

    Default callers are unchanged. Tasks/rules come from existing discovery and
    receipts, never caller-supplied permissions. Optional results do not update
    issue state, persisted receipts, runtime authority, or any external system.
    """
    doc = _load_projection(root)
    if offline_replays is None:
        return doc
    if not isinstance(offline_replays, list) or len(offline_replays) > MAX_OFFLINE_REPLAYS:
        raise ValueError('invalid_offline_replay_batch')
    seen = set()
    for request in offline_replays:
        if not isinstance(request, dict) or set(request) != {'issue_id', 'before', 'readback'}:
            raise ValueError('invalid_offline_replay_request')
        issue = request['issue_id']
        if not isinstance(issue, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', issue) or issue in seen:
            raise ValueError('invalid_or_duplicate_offline_issue')
        seen.add(issue)
    # Lazy import: consumer imports AUTHORITY; no cyclic import at module load.
    from team_repair_rehearsal import RULE, blocked, rehearse
    tasks = {row['issue_id']: row for row in doc['issues']}
    results, total_bytes = [], 0
    def consume(size):
        nonlocal total_bytes
        total_bytes += size
        if total_bytes > MAX_OFFLINE_REPLAY_BYTES:
            raise ValueError('offline_replay_aggregate_capacity')
    for request in offline_replays:
        issue = request['issue_id']
        task = tasks.get(issue)
        if task is None:
            result = blocked('unknown_issue_requires_review')
        elif task['rule'] != RULE or task['team'] != 'sourcing':
            # Unsupported jobs do not dereference caller-controlled files.
            result = blocked('unsupported_rule_requires_review')
        elif task.get('reason') == 'receipt_cannot_grant_authority':
            result = blocked('task_cannot_grant_authority')
        else:
            try:
                # Validate and consume precisely these captured bytes; never
                # hash one read then re-open a changed file for the consumer.
                before = checked_bytes(root, request['before'], consumed=consume)
                readback = checked_bytes(root, request['readback'], consumed=consume)
            except (OSError, ValueError, TypeError) as exc:
                if str(exc) == 'offline_replay_aggregate_capacity':
                    raise
                result = blocked('offline_evidence_unavailable_or_mismatched')
            else:
                result = rehearse(task, before, readback, now=now)
        results.append({'issue_id': issue, **result})
    return {**doc, 'offline_rehearsals': results}
