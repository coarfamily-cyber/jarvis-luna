"""Read-only review views outside the immutable imported data/ inventory.

These views are review assignments, never input or authority for Core/Publisher.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

BRIEFINGS = 'data/manual/team_briefings.json'
OVERLAY = 'review/manual/team_briefings.json'
FEEDS = 'data/team_feeds.json'
REVIEW_FEEDS = 'review/team_feeds.json'
BASE_BLOB = 'ef534d0995880b099d2215a70c545744b509444b'
PRESERVED_COMMIT = '7bb9b912d176b93cb7a5e2ac053ad67c09ba9255'
MAX_BYTES = 2 * 1024 * 1024


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('invalid review file')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate review JSON key')
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError('nonfinite review JSON')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=reject_constant)


def load_team_briefings(root):
    root = Path(root)
    path = root / OVERLAY
    if not (root / BRIEFINGS).exists() and not path.exists():
        return {'schema_version': 1, 'items': []}
    base = _read(root / BRIEFINGS)
    if not path.exists():
        return base
    overlay = _read(path)
    if (not isinstance(overlay, dict) or set(overlay) != {
            'schema_version', 'base_blob', 'preserved_from_commit', 'items'}
            or type(overlay['schema_version']) is not int or overlay['schema_version'] != 1 or overlay['base_blob'] != BASE_BLOB
            or overlay['preserved_from_commit'] != PRESERVED_COMMIT
            or not isinstance(overlay['items'], list)):
        raise ValueError('invalid briefing overlay')
    raw = (root / BRIEFINGS).read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != BASE_BLOB:
        raise ValueError('briefing overlay base changed')
    result = deepcopy(base)
    result['items'].extend(overlay['items'])
    ids = [item.get('id') for item in result['items'] if isinstance(item, dict)]
    if (len(ids) != len(result['items']) or any(not isinstance(i, str) or not i for i in ids)
            or len(ids) != len(set(ids))):
        raise ValueError('invalid or duplicate briefing overlay id')
    return result


def load_team_feeds(root):
    root = Path(root)
    if not (root / FEEDS).exists() and not (root / OVERLAY).exists():
        return {}
    base = _read(root / FEEDS)
    if not (root / OVERLAY).exists():
        return base
    # Import lazily: refresh reuses the existing pure briefing row helpers.
    from refresh_briefing_feeds_offline import refresh
    expected = refresh(base, load_team_briefings(root))
    materialized = _read(root / REVIEW_FEEDS)
    if materialized != expected:
        raise ValueError('review feed requires offline refresh')
    return materialized
