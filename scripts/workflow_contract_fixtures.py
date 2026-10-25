"""Paths for archived workflow CONTRACT tests, never execution/readiness evidence.

Historical workflow identities inside YAML/artifacts remain unchanged. Only the
on-disk fixture location changed in the 20261023 quarantine. Never fall back to
an active workflow or treat a missing archive as a skipped test.
"""
from pathlib import Path
import hashlib
from check_owned_workflow_policy import EXPECTED

ROOT = Path(__file__).resolve().parents[1]
QUARANTINE = Path('.github/workflows-quarantined/20261023')


def archived_workflow(name: str, *, root: Path = ROOT) -> Path:
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.yml'):
        raise ValueError('Expected a quarantined workflow basename')
    root = Path(root).resolve()
    active = root / '.github/workflows' / name
    if active.exists() or active.is_symlink():
        raise AssertionError(f'Archived contract unexpectedly active: {name}')
    relative = (QUARANTINE / name).as_posix()
    expected = EXPECTED.get(relative)
    if expected is None:
        raise AssertionError(f'Unreviewed archived workflow: {name}')
    archive = root / QUARANTINE / name
    if archive.is_symlink() or not archive.is_file():
        raise AssertionError(f'Archived workflow fixture missing or symlinked: {name}')
    if not archive.resolve().is_relative_to(root / QUARANTINE):
        raise AssertionError('Archived workflow fixture escaped quarantine')
    raw = archive.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != expected['blob'] or archive.stat().st_mode & 0o111:
        raise AssertionError(f'Archived fixture bytes or mode changed: {name}')
    return archive
