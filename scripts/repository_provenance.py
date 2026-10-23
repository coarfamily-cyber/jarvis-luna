"""Offline, versioned historical-import parsing and immutable inventory checks.

No network, filesystem access, credential handling, authority issuance, workflow
activation or pending/STOP resolution. A successful report proves consistency
of caller-supplied bytes ONLY, never authenticated migration or current evidence.
Trusted callers must independently bind Git snapshots and approval before use.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re

SCHEMA = 'jarvis-historical-import-v1'
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TREE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 20000
LEGACY = ('coar0000-wq/jarvis-luna', 1334276889, 301755647)
DESTINATION = ('coarfamily-cyber/jarvis-luna', 1431541717, 280980688)
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')

class ProvenanceError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise ProvenanceError(reason)


def _hash(value, size=64):
    _require(type(value) is str and bool((HEX64 if size == 64 else HEX40).fullmatch(value)), 'invalid_hash')
    return value


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys), 'closed_schema_required')


def _path(value):
    _require(type(value) is str and 0 < len(value.encode('utf-8')) <= 4096, 'invalid_path')
    _require(not any(ord(c) < 32 or ord(c) == 127 for c in value)
             and '\\' not in value and not value.startswith('/')
             and all(p not in ('', '.', '..') for p in value.split('/')), 'unsafe_path')
    return value


def canonical(value):
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ProvenanceError('invalid_canonical_value') from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _json(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES, 'json_size_or_type')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ProvenanceError('nonfinite_json')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)
        _require(canonical(value) == raw, 'noncanonical_json')
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProvenanceError('invalid_json') from exc


@dataclass(frozen=True)
class Repository:
    full_name: str
    repository_id: int
    owner_id: int


def _repository(value, expected):
    _keys(value, ('full_name', 'repository_id', 'owner_id'))
    _require(type(value['repository_id']) is int and type(value['owner_id']) is int, 'integer_identity_required')
    actual = Repository(**value)
    _require(actual == Repository(*expected), 'repository_identity_mismatch')
    return actual


@dataclass(frozen=True)
class Snapshot:
    repository: Repository
    commit: str
    tree: str


def _snapshot(value, expected):
    _keys(value, ('repository', 'commit', 'tree'))
    return Snapshot(_repository(value['repository'], expected), _hash(value['commit'], 40), _hash(value['tree'], 40))


@dataclass(frozen=True, order=True)
class Entry:
    path: str
    blob: str
    mode: str


def _entries(values):
    _require(type(values) is list and len(values) <= MAX_ENTRIES, 'inventory_capacity')
    result = []
    for value in values:
        _keys(value, ('path', 'blob', 'mode'))
        _require(value['mode'] in ('100644', '100755'), 'regular_blob_required')
        result.append(Entry(_path(value['path']), _hash(value['blob'], 40), value['mode']))
    _require(len({e.path for e in result}) == len(result), 'duplicate_inventory_path')
    _require(result == sorted(result), 'sorted_inventory_required')
    return tuple(result)


def inventory_digest(entries):
    return digest([{'path': e.path, 'blob': e.blob, 'mode': e.mode} for e in entries])


def parse_tree(raw):
    """Parse complete `git ls-tree -r -z <exact tree> -- data/` bytes.

    Caller must authenticate tree binding and command completeness separately.
    This API does not infer trust from commit/tree strings or run subprocesses.
    """
    _require(type(raw) is bytes and len(raw) <= MAX_TREE_BYTES, 'tree_size_or_type')
    _require(not raw or raw.endswith(b'\0'), 'truncated_tree')
    records = []
    try:
        for item in raw.split(b'\0')[:-1]:
            header, path = item.split(b'\t', 1)
            mode, kind, blob = header.decode('ascii').split(' ')
            _require(kind == 'blob', 'regular_blob_required')
            records.append({'path': path.decode('utf-8'), 'blob': blob, 'mode': mode})
    except (ValueError, UnicodeError) as exc:
        raise ProvenanceError('invalid_git_tree') from exc
    return _entries(sorted(records, key=lambda entry: entry['path']))


@dataclass(frozen=True)
class ImportRecord:
    source: Snapshot
    destination: Snapshot
    entries: tuple[Entry, ...]
    additions: tuple[Entry, ...]
    predecessor_digest: str
    unresolved_digest: str
    old_contract_digest: str
    new_contract_digest: str
    transition_policy_digest: str
    authorization_reference_digest: str


def parse_record(raw):
    """Parse only historical import; destination-current has no accepting route."""
    value = _json(raw)
    keys = ('schema', 'purpose', 'protected_prefix', 'source', 'destination', 'inventory',
            'inventory_digest', 'approved_additions', 'predecessor_digest', 'unresolved_digest',
            'old_contract_digest', 'new_contract_digest', 'transition_policy_digest', 'authorization_reference_digest')
    _keys(value, keys)
    _require(value['schema'] == SCHEMA and value['purpose'] == 'historical_import_only', 'historical_import_only')
    # v1 intentionally protects ALL data; a payload cannot narrow safety scope.
    _require(value['protected_prefix'] == 'data/', 'full_data_scope_required')
    entries, additions = _entries(value['inventory']), _entries(value['approved_additions'])
    _require(bool(entries), 'empty_inventory')
    _require(all(e.path.startswith('data/') for e in entries), 'inventory_scope')
    _require(all(e.path.startswith('data/migration_provenance/') for e in additions), 'addition_scope')
    _require(not ({e.path for e in entries} & {e.path for e in additions}), 'addition_overwrites_history')
    _require(_hash(value['inventory_digest']) == inventory_digest(entries), 'inventory_digest_mismatch')
    hashes = {key: _hash(value[key]) for key in keys if key.endswith('_digest') and key != 'inventory_digest'}
    return ImportRecord(_snapshot(value['source'], LEGACY), _snapshot(value['destination'], DESTINATION),
                        entries, additions, **hashes)


@dataclass(frozen=True)
class PreservationReport:
    source_files: int
    additive_files: int
    inventory_digest: str
    scope: str = 'local_consistency_only'
    authenticated_migration: bool = False
    destination_current_evidence: bool = False
    production_recovered: bool = False


def validate_preservation(raw, source_tree_bytes, destination_tree_bytes, *,
                          expected_record_digest, source_snapshot, destination_snapshot):
    """Check exact pins and immutable content; caller pins must be independent.

    expected_record_digest must come from separately reviewed trusted policy,
    never be calculated from attacker input as a substitute for approval.
    This function itself cannot authenticate policy, repository or Git objects.
    """
    _hash(expected_record_digest)
    _require(type(raw) is bytes and len(raw) <= MAX_JSON_BYTES, 'json_size_or_type')
    _require(hashlib.sha256(raw).hexdigest() == expected_record_digest, 'record_pin_mismatch')
    record = parse_record(raw)
    _require(type(source_snapshot) is Snapshot and type(destination_snapshot) is Snapshot, 'snapshot_pin_type')
    _require(record.source == source_snapshot and record.destination == destination_snapshot, 'snapshot_pin_mismatch')
    source, destination = parse_tree(source_tree_bytes), parse_tree(destination_tree_bytes)
    _require(source == record.entries, 'source_inventory_mismatch')
    expected = tuple(sorted(record.entries + record.additions))
    _require(destination == expected, 'destination_inventory_mismatch')
    return PreservationReport(len(source), len(record.additions), inventory_digest(source))
