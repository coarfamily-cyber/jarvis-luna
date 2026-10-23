"""Pure local-work epoch contract; never a source-continuity reset.

This module validates content and transitions, NOT transport authenticity. Only
an authenticated GitHub runner adapter may supply `observed` to accept_retained.
It performs no network, execution, filesystem writes, environment trust, or
legacy ledger mutation. The first run is bootstrap_pending until retained bytes
are bound to a completed own-repository run; a local JSON is not a checkpoint.
"""
from __future__ import annotations
import hashlib
import json
import re

REPOSITORY = 'coarfamily-cyber/jarvis-luna'
REPOSITORY_ID = 1431541717
OWNER_ID = 280980688
WORKFLOW = '.github/workflows/owned-core-local.yml'
SCHEMA = 'jarvis-destination-local-epoch-v1'
PROFILE = 'saved_input_business_review_only'
INPUTS = ('data/product_master.json', 'data/pricing_model.json', 'data/listing_gate.json',
          'data/legal_full.json', 'data/mocra_readiness.json', 'data/shopify_shortlist.json')
HOLDS = {'legacy_continuity': 'unresolved_gap', 'source_requests': 'disabled',
         'ai_requests': 'disabled', 'shopify_writes': 'disabled',
         'legacy_claim_replay': 'disabled', 'legacy_budget_reset': 'disabled',
         'legacy_stop_clearance': 'disabled', 'full_core_recovery': False}

class Blocked(ValueError):
    pass


def need(value, reason):
    if not value:
        raise Blocked(reason)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 16*1024*1024, 'bounded_json_required')
    def pairs(items):
        out = {}
        for k, v in items:
            need(k not in out, 'duplicate_json_key')
            out[k] = v
        return out
    def reject(_):
        raise Blocked('nonfinite_json')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=reject)
    except (UnicodeError, ValueError, RecursionError) as e:
        raise Blocked('invalid_json') from e


def hashed(value, size=64):
    need(type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}', value), 'invalid_hash')


def positive(value):
    need(type(value) is int and value > 0, 'positive_integer_required')


def validate_policy(policy):
    need(type(policy) is dict and set(policy) == {'schema', 'repository', 'repository_id', 'owner_id',
        'workflow', 'profile', 'import_record_digest', 'legacy_inventory_digest',
        'legacy_unresolved_digest', 'source_final_tail_digest', 'code_contract_digest',
        'authorization_reference_digest', 'holds', 'genesis_workflow_id', 'genesis_run_number'}, 'policy_schema')
    need((policy['schema'], policy['repository'], policy['repository_id'], policy['owner_id'],
          policy['workflow'], policy['profile']) == (SCHEMA, REPOSITORY, REPOSITORY_ID, OWNER_ID,
          WORKFLOW, PROFILE), 'destination_profile_binding')
    need(type(policy['repository_id']) is int and type(policy['owner_id']) is int, 'numeric_identity')
    need(policy['holds'] == HOLDS, 'legacy_holds_must_remain')
    positive(policy['genesis_workflow_id'])
    need(type(policy['genesis_run_number']) is int and policy['genesis_run_number'] == 1, 'genesis_anchor_required')
    for k in policy:
        if k.endswith('_digest'):
            hashed(policy[k])
    return digest(policy)


def business_review(raw_inputs):
    """Compute real saved-input findings, not current market/freshness claims."""
    need(type(raw_inputs) is dict and set(raw_inputs) == set(INPUTS), 'exact_inputs_required')
    inputs, findings = {}, []
    for path in INPUTS:
        raw = raw_inputs[path]
        value = parse(raw)
        inputs[path] = sha(raw)
        # Preserve actual field shapes rather than interpreting a missing list as zero products.
        rows = value if type(value) is list else None
        if type(value) is dict:
            for name in ('products', 'items', 'rows', 'all_scored'):
                if type(value.get(name)) is list:
                    rows = value[name]
                    break
        row_count = len(rows) if rows is not None else None
        blocked = sum(1 for r in (rows or []) if type(r) is dict and
                      (r.get('blocked') is True or r.get('status') in ('blocked', 'hold', 'needs_review')))
        findings.append({'input': path, 'row_count': row_count,
                         'explicit_blocked_or_review_rows': blocked,
                         'row_schema_recognized': rows is not None})
    return {'profile': PROFILE, 'input_sha256': inputs, 'findings': findings,
            'freshness': 'not_established_by_saved_input_review',
            'external_effects_permitted': False, 'full_core_recovery': False}


def validate_checkpoint(cp, policy):
    epoch = validate_policy(policy)
    need(type(cp) is dict and set(cp) == {'schema', 'epoch', 'sequence', 'predecessor', 'run_id',
        'run_attempt', 'head_sha', 'legacy_inventory_digest', 'legacy_unresolved_digest',
        'source_final_tail_digest', 'holds', 'result', 'result_digest'}, 'checkpoint_schema')
    need(cp['schema'] == SCHEMA and cp['epoch'] == epoch, 'epoch_mismatch')
    need(type(cp['sequence']) is int and cp['sequence'] >= 0, 'sequence_invalid')
    need((cp['sequence'] == 0) == (cp['predecessor'] is None), 'genesis_only_at_zero')
    if cp['predecessor'] is not None:
        hashed(cp['predecessor'])
    positive(cp['run_id']); positive(cp['run_attempt']); hashed(cp['head_sha'], 40)
    for k in ('legacy_inventory_digest', 'legacy_unresolved_digest', 'source_final_tail_digest', 'holds'):
        need(cp[k] == policy[k], 'historical_binding_changed')
    result = cp['result']
    need(type(result) is dict and result.get('profile') == PROFILE and
         result.get('external_effects_permitted') is False and result.get('full_core_recovery') is False,
         'local_result_scope_changed')
    need(set(result) == {'profile', 'input_sha256', 'findings', 'freshness',
                         'external_effects_permitted', 'full_core_recovery'}, 'result_schema')
    need(type(result['input_sha256']) is dict and set(result['input_sha256']) == set(INPUTS), 'result_input_scope')
    for value in result['input_sha256'].values():
        hashed(value)
    need(result['freshness'] == 'not_established_by_saved_input_review', 'freshness_overclaim')
    need(type(result['findings']) is list and len(result['findings']) == len(INPUTS), 'findings_schema')
    for path, finding in zip(INPUTS, result['findings']):
        need(type(finding) is dict and set(finding) == {'input', 'row_count',
             'explicit_blocked_or_review_rows', 'row_schema_recognized'} and finding['input'] == path, 'finding_input_binding')
        count, blocked = finding['row_count'], finding['explicit_blocked_or_review_rows']
        need(type(blocked) is int and blocked >= 0 and type(finding['row_schema_recognized']) is bool, 'finding_count_type')
        need((count is None and finding['row_schema_recognized'] is False and blocked == 0) or
             (type(count) is int and count >= blocked and finding['row_schema_recognized'] is True), 'finding_count_bound')
    need(cp['result_digest'] == digest(result), 'result_digest_mismatch')
    return digest(cp)


def prepare_checkpoint(policy, raw_inputs, *, run_id, run_attempt, head_sha, legacy_inventory_digest,
                       prior=None):
    """Return candidate bytes only. Caller must independently authenticate prior."""
    epoch = validate_policy(policy)
    need(legacy_inventory_digest == policy['legacy_inventory_digest'], 'legacy_inventory_changed')
    result = business_review(raw_inputs)
    predecessor, sequence = None, 0
    if prior is not None:
        predecessor = validate_checkpoint(prior, policy)
        need(prior['run_id'] != run_id, 'same_run_retry_requires_reconciliation')
        sequence = prior['sequence'] + 1
    cp = {'schema': SCHEMA, 'epoch': epoch, 'sequence': sequence, 'predecessor': predecessor,
          'run_id': run_id, 'run_attempt': run_attempt, 'head_sha': head_sha,
          'legacy_inventory_digest': policy['legacy_inventory_digest'],
          'legacy_unresolved_digest': policy['legacy_unresolved_digest'],
          'source_final_tail_digest': policy['source_final_tail_digest'],
          'holds': dict(HOLDS), 'result': result, 'result_digest': digest(result)}
    validate_checkpoint(cp, policy)
    return canonical(cp)


def accept_retained(raw_checkpoint, policy, *, observed, expected_run_id, expected_attempt,
                    verified_archive_sha256):
    """Validate binding of a previously authenticated/downloaded artifact.

    `observed` MUST originate from authenticated fixed-origin complete GitHub
    run/job/artifact discovery. This function cannot authenticate arbitrary dicts.
    Archive SHA is separate from inner JSON SHA: avoids self-referential metadata.
    """
    cp = parse(raw_checkpoint)
    need(canonical(cp) == raw_checkpoint, 'canonical_checkpoint_required')
    validate_checkpoint(cp, policy)
    need(type(observed) is dict and set(observed) == {'repository', 'repository_id', 'owner_id',
        'run_id', 'run_attempt', 'head_sha', 'workflow', 'event', 'branch', 'status', 'conclusion',
        'artifact_id', 'artifact_name', 'artifact_digest', 'artifact_expired',
        'required_steps_successful', 'complete_attempt_inventory', 'unreconciled_producer_attempts',
        'predecessor_checkpoint_digest'},
        'authenticated_observation_schema')
    need((observed['repository'], observed['repository_id'], observed['owner_id']) ==
         (REPOSITORY, REPOSITORY_ID, OWNER_ID), 'wrong_repository')
    need(observed['run_id'] == cp['run_id'] == expected_run_id and
         observed['run_attempt'] == cp['run_attempt'] == expected_attempt, 'run_attempt_mismatch')
    positive(observed['artifact_id']); positive(observed['run_id']); positive(observed['run_attempt'])
    positive(expected_run_id); positive(expected_attempt); hashed(verified_archive_sha256)
    need(observed['predecessor_checkpoint_digest'] == cp['predecessor'], 'predecessor_not_authenticated')
    need(observed['head_sha'] == cp['head_sha'] and observed['workflow'] == WORKFLOW and
         observed['branch'] == 'main' and observed['event'] == 'workflow_dispatch', 'run_code_binding')
    need(observed['status'] == 'completed' and observed['conclusion'] == 'success' and
         observed['required_steps_successful'] is True, 'run_not_successfully_retained')
    need(observed['artifact_name'] == f"owned-core-local-{expected_run_id}-{expected_attempt}" and
         observed['artifact_digest'] == 'sha256:'+verified_archive_sha256 and
         observed['artifact_expired'] is False, 'artifact_binding')
    need(observed['complete_attempt_inventory'] is True and
         observed['unreconciled_producer_attempts'] == [], 'producer_gap_unreconciled')
    return cp
