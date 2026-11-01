"""Inactive, pure offline projection of an explicitly captured Herdr snapshot.

No CLI, file access, network, subprocesses, or live Core integration.
See docs/learning/2026-11-01-herdr-preparation.md for the input contract.
"""
import json

MAX_BYTES = 65536
MAX_TERMINALS = 128
MAX_AGE_MS = 300000
STATES = frozenset(('idle', 'working', 'done', 'blocked', 'error'))
REASONS = frozenset(('exited', 'killed', 'server_stop', 'host_shutdown',
                     'signaled', 'holder_lost', 'stopped_by_restart', 'spawn_pending'))


def _integer(value, minimum=0, maximum=2**64 - 1):
    return type(value) is int and minimum <= value <= maximum


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def normalize_snapshot(payload, *, now_ms, expected_epoch):
    """Return a redacted observation, never execution/approval evidence.

    Caller supplies UTF-8 JSON bytes, an explicit clock, and the expected capture
    epoch. Epoch is capture provenance, not a Herdr API field or authentication.
    Any malformed input raises a fixed ValueError without echoing input.
    """
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise ValueError('invalid snapshot size or encoding')
    if not _integer(now_ms) or not isinstance(expected_epoch, str) or not 1 <= len(expected_epoch) <= 128:
        raise ValueError('invalid capture context')
    try:
        doc = json.loads(payload.decode('utf-8'), object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(doc, dict):
            raise ValueError()
        captured = doc.get('captured_ms')
        epoch = doc.get('source_epoch')
        if not _integer(captured) or not isinstance(epoch, str) or not 1 <= len(epoch) <= 128:
            raise ValueError()
        snapshot = doc.get('snapshot')
        if not isinstance(snapshot, dict):
            raise ValueError()
        terminals = snapshot.get('terminals')
        if (not isinstance(terminals, list) or len(terminals) > MAX_TERMINALS
                or not _integer(snapshot.get('hidden_finished'))
                or not isinstance(snapshot.get('machines'), list)):
            raise ValueError()
        fresh = (epoch == expected_epoch and doc.get('fresh_snapshot') is True
                 and 0 <= now_ms - captured <= MAX_AGE_MS)
        rows, seen = [], set()
        for terminal in terminals:
            if not isinstance(terminal, dict):
                raise ValueError()
            address = terminal.get('address')
            if not isinstance(address, str) or not 1 <= len(address) <= 256 or address in seen:
                raise ValueError()
            seen.add(address)
            for key in ('created_ms', 'status_ms', 'finished_ms'):
                value = terminal.get(key)
                if value is not None and (not _integer(value) or value > captured):
                    raise ValueError()
            for key in ('exit_code', 'signal'):
                value = terminal.get(key)
                if value is not None and not _integer(value, -(2**31), 2**31 - 1):
                    raise ValueError()
            reported = terminal.get('reported', False)
            if type(reported) is not bool:
                raise ValueError()
            status = terminal.get('status')
            if status is not None and not isinstance(status, dict):
                raise ValueError()
            lifecycle = terminal.get('state')
            lifecycle = lifecycle if lifecycle in ('live', 'finished') else 'unknown'
            reason = terminal.get('reason')
            reason = reason if isinstance(reason, str) and reason in REASONS else 'unknown'
            word = status.get('state') if isinstance(status, dict) else None
            word = word if isinstance(word, str) and word in STATES else 'unknown'
            # A lost kept record can remain live without its original program.
            # status_ms measures a change, not a heartbeat: age it only by capture.
            if (not fresh or not reported or lifecycle != 'live'
                    or terminal.get('reason') is not None or terminal.get('exit_code') is not None
                    or terminal.get('signal') is not None or terminal.get('finished_ms') is not None
                    or terminal.get('status_ms') is None):
                word = 'unknown'
            rows.append({'reported_state': word,
                         'termination': lifecycle if fresh else 'unknown',
                         'termination_reason': reason if fresh else 'unknown',
                         'exit_code': terminal.get('exit_code') if fresh else None,
                         'verification_status': 'unverified_program_report',
                         'execution_verified': False, 'business_approval': False,
                         'tests_passed': False, 'deployment_verified': False,
                         'full_core_recovery': False})
        return {'mode': 'inactive_offline_only',
                'snapshot_status': 'fresh_capture_unverified' if fresh else 'unknown',
                'terminals': rows, 'full_core_recovery': False}
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise ValueError('invalid snapshot') from None
