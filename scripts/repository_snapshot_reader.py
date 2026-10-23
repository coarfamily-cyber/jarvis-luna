"""Bounded public GitHub snapshot authentication, for trusted-process use only.

No GitHub credentials, explicit environment reads, redirects, retries, provider access or mutation.
Standard library HTTPS transport may use the trusted runtime's configured proxy;
proxy settings/credentials are never inspected, logged or persisted by this code.
Production entrypoint never accepts a transport or a serialized 'trusted' flag.
Pure tree verification is available for OFFLINE tests but cannot mint a receipt.
Python object sealing is not a sandbox: execute only reviewed trusted code in a
separate process/runner, never together with PR code or an injectable transport.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
import repository_provenance as p

API = 'https://api.github.com/repos/'
TREE_CAP = 16 * 1024 * 1024
LOCAL_PROOF_CAP = 32 * 1024 * 1024
META_CAP = 1024 * 1024
MAX_OBJECTS = 100000
DEADLINE_SECONDS = 90
MAX_RECEIPT_AGE = 120
_SEAL = object()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            p._require(key not in out, 'duplicate_remote_json_key')
            out[key] = value
        return out
    def constant(_):
        raise p.ProvenanceError('nonfinite_remote_json')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant, parse_float=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise p.ProvenanceError('invalid_remote_json') from exc


def _get(repository, suffix, deadline, cap):
    # repository and suffix originate only in read_snapshot's fixed construction.
    remaining = deadline - time.monotonic()
    p._require(remaining > 0, 'snapshot_deadline')
    request = urllib.request.Request(API + repository + suffix, headers={
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'Jarvis-public-historical-snapshot/1'})
    # Use ordinary platform HTTPS egress; never inspect proxy configuration.
    # The trusted runtime owns this environment and TLS trust store. No GitHub
    # Authorization header is added and redirects remain forbidden.
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=min(20, remaining)) as response:
            p._require(response.status == 200, 'snapshot_http_status')
            lengths = response.headers.get_all('Content-Length') or []
            transfers = response.headers.get_all('Transfer-Encoding') or []
            encodings = response.headers.get_all('Content-Encoding') or []
            p._require(len(lengths) <= 1 and len(transfers) <= 1 and len(encodings) <= 1,
                       'ambiguous_http_framing')
            p._require(not (lengths and transfers), 'ambiguous_http_framing')
            p._require(not transfers or transfers[0].lower().strip() == 'chunked', 'unsupported_transfer_encoding')
            p._require(not encodings or encodings[0].lower().strip() == 'identity', 'unsupported_content_encoding')
            declared = lengths[0] if lengths else None
            if declared is not None:
                p._require(declared.isascii() and declared.isdigit() and len(declared) <= 9
                           and int(declared) <= cap, 'snapshot_size')
            chunks, total = [], 0
            while True:
                p._require(time.monotonic() <= deadline, 'snapshot_deadline')
                # read1 returns after one underlying read, avoiding read(n)'s
                # unbounded aggregate trickle wait. Socket timeout is <=20s;
                # a blocked read may end that much after the deadline, but
                # no result is accepted after the deadline.
                chunk = response.read1(min(65536, cap + 1 - total))
                p._require(time.monotonic() <= deadline, 'snapshot_deadline')
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                p._require(total <= cap, 'snapshot_size')
            p._require(declared is None or total == int(declared), 'truncated_http_body')
            return _json(b''.join(chunks))
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
        # Never include HTTP bodies, URLs or proxy credentials in error chains.
        raise p.ProvenanceError('snapshot_read_unavailable') from None


def verify_tree_payload(payload, expected_tree):
    """Recompute every supplied Git tree; reject omissions/truncation/extra paths.

    Git blob bytes are NOT downloaded. This proves a complete content-addressed
    tree inventory, not semantic correctness or authenticity of each blob's data.
    Returns data/-scoped ls-tree bytes, never an authenticated evidence object.
    """
    p._hash(expected_tree, 40)
    p._require(type(payload) is dict and payload.get('sha') == expected_tree
               and payload.get('truncated') is False, 'tree_binding_or_truncation')
    rows = payload.get('tree')
    p._require(type(rows) is list and len(rows) <= MAX_OBJECTS, 'tree_object_capacity')
    entries = {}
    allowed = {'040000':'tree','100644':'blob','100755':'blob','120000':'blob','160000':'commit'}
    for row in rows:
        p._require(type(row) is dict, 'tree_entry_type')
        path = p._path(row.get('path'))
        p._require(len(path.split('/')) <= 64, 'tree_depth_limit')
        mode, kind = row.get('mode'), row.get('type')
        p._require(type(mode) is str and mode in allowed and allowed[mode] == kind, 'git_mode_type')
        sha = p._hash(row.get('sha'), 40)
        p._require(path not in entries, 'duplicate_tree_path')
        entries[path] = (mode, kind, sha)
    directories = {'': expected_tree}
    directories.update({path: value[2] for path, value in entries.items() if value[1] == 'tree'})
    children = {path: [] for path in directories}
    for path, value in entries.items():
        parent, _, name = path.rpartition('/')
        p._require(parent in directories, 'missing_parent_tree')
        children[parent].append((name, *value))
    for path, expected in directories.items():
        nodes = sorted(children[path], key=lambda x: (x[0] + ('/' if x[2] == 'tree' else '')).encode('utf-8'))
        content = b''.join((mode.lstrip('0') + ' ').encode('ascii') + name.encode('utf-8') + b'\0' + bytes.fromhex(sha)
                           for name, mode, kind, sha in nodes)
        actual = hashlib.sha1(b'tree ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest()
        p._require(actual == expected, 'git_tree_hash_mismatch')
    p._require('data' in directories, 'complete_data_tree_required')
    data = []
    for path, (mode, kind, sha) in sorted(entries.items()):
        if path.startswith('data/') and kind != 'tree':
            p._require(kind == 'blob' and mode in ('100644','100755'), 'nonregular_protected_data')
            data.append((mode+' blob '+sha+'\t'+path).encode('utf-8')+b'\0')
    raw = b''.join(data)
    p.parse_tree(raw)  # enforce the smaller protected-inventory cap and uniqueness
    return raw


@dataclass(frozen=True)
class AuthenticatedSnapshot:
    snapshot: p.Snapshot
    data_tree_bytes: bytes
    observed_monotonic: float
    _token: object = field(repr=False, compare=False)

    def __post_init__(self):
        p._require(self._token is _SEAL, 'trusted_reader_construction_required')


def read_snapshot(role, commit, *, local_tree_proof=None):
    """At most 3 bounded public GETs; no mutable ref or test transport.

    Commit->tree association is HTTPS-authenticated GitHub metadata, NOT a
    rehashed raw Git commit. Only complete tree objects are rehashed here.
    """
    p._require(role in ('source','destination'), 'snapshot_role')
    p._hash(commit, 40)
    if local_tree_proof is not None:
        p._require(type(local_tree_proof) is bytes and 0 < len(local_tree_proof) <= LOCAL_PROOF_CAP,
                   'local_tree_proof_size_or_type')
    expected = p.LEGACY if role == 'source' else p.DESTINATION
    repository = expected[0]
    deadline = time.monotonic() + DEADLINE_SECONDS
    metadata = _get(repository, '', deadline, META_CAP)
    p._require(type(metadata) is dict and type(metadata.get('owner')) is dict, 'repository_metadata')
    identity = {'full_name':metadata.get('full_name'), 'repository_id':metadata.get('id'), 'owner_id':metadata['owner'].get('id')}
    repo = p._repository(identity, expected)
    p._require(metadata.get('private') is False, 'public_snapshot_only')
    value = _get(repository, '/git/commits/'+commit, deadline, META_CAP)
    p._require(type(value) is dict and value.get('sha') == commit and type(value.get('tree')) is dict, 'commit_binding')
    tree = p._hash(value['tree'].get('sha'), 40)
    if local_tree_proof is None:
        payload = _get(repository, '/git/trees/'+tree+'?recursive=1', deadline, TREE_CAP)
    else:
        # This is untrusted DATA, not a transport or authentication flag.
        # Every tree must hash to the root authenticated above. It lets a
        # complete local Git proof avoid GitHub's recursive-response truncation.
        payload = _json(local_tree_proof)
    raw = verify_tree_payload(payload, tree)
    p._require(time.monotonic() <= deadline, 'snapshot_deadline')
    return AuthenticatedSnapshot(p.Snapshot(repo, commit, tree), raw, time.monotonic(), _SEAL)


def validate_authenticated_import(raw, source, destination, *, expected_record_digest):
    """Snapshot-authenticated preservation ONLY; NOT authenticated user approval.

    expected_record_digest remains independently reviewed parent-policy input.
    No function in this module issues approval, clears STOP, or enables a writer.
    """
    for evidence in (source, destination):
        p._require(type(evidence) is AuthenticatedSnapshot and evidence._token is _SEAL, 'authenticated_snapshot_required')
        age = time.monotonic() - evidence.observed_monotonic
        p._require(0 <= age <= MAX_RECEIPT_AGE, 'snapshot_receipt_expired')
    p._require(source.snapshot.repository == p.Repository(*p.LEGACY)
               and destination.snapshot.repository == p.Repository(*p.DESTINATION), 'snapshot_role_mismatch')
    return p.validate_preservation(raw, source.data_tree_bytes, destination.data_tree_bytes,
        expected_record_digest=expected_record_digest, source_snapshot=source.snapshot, destination_snapshot=destination.snapshot)
