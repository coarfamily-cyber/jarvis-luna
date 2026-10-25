"""Exact durable-local-v3 plus reviewed knowledge-data-v1 policy; no execution or mutation.

Legacy assertions use separate temporary fixture views, never this active view.
Updating active workflow bytes requires an explicit reviewed policy version.
"""
from pathlib import Path
import argparse
import hashlib
import json
import yaml

MANUAL_STAGE = 'owned-repository-durable-manual-verification-v3'
HOURLY_STAGE = 'owned-repository-durable-local-v3'
# This source constant is reviewed per deployment; no CLI/environment override.
STAGE = HOURLY_STAGE
# Separately reviewed information-only lane; existing core authority is unchanged.
KNOWLEDGE_STAGE = 'owned-real-knowledge-data-only-v1'
KNOWLEDGE_WORKFLOW = '.github/workflows/owned-real-knowledge-sync.yml'
KNOWLEDGE_GUARD = "github.repository == 'coarfamily-cyber/jarvis-luna' && github.repository_id == '1431541717' && github.repository_owner_id == '280980688' && github.ref == 'refs/heads/main' && github.run_attempt == 1 && (github.event_name == 'schedule' || inputs.expected_sha == github.sha)"
PRODUCER_PATH = '.github/workflows/owned-core-local.yml'
PRODUCER_BLOBS = {MANUAL_STAGE: '4154e610c3a93ab626c72452a48df6449ad959d3',
                  HOURLY_STAGE: 'b1cacb160c3c80ebe21dda50a046b31e00810cd4'}
SOURCE_SNAPSHOT = '1e6a9b361fd9f3d6b32c291a9bf7a54212bba120'
TARGET_BASE = '6ad0711c4c9ba1531ac885a3bdb2f340da5c8121'
# Reviewed manual-only fresh catalog observation; no new schedule or writer.
# Existing owner-authorized manual shipping lane; registration is not execution approval.
EXPECTED = {KNOWLEDGE_WORKFLOW: {'blob': '4c15f104549314acced44cd8f92f9282eacf4930', 'mode': '100644'}, '.github/workflows/owned-shopify-us-free-shipping.yml': {'blob': '635d1c38d25d8395af84e04a7c33d5c371009a1b', 'mode': '100644'},
 '.github/workflows/owned-technical-review-report.yml': {'blob': '19392daff1cf47e61b32940a988027316bae1d30', 'mode': '100644'},
 '.github/workflows/owned-fx-readonly-observation.yml': {'blob': '5f8c73fe7f8e0a77a47d944521ea617ef773a37d', 'mode': '100644'},
 '.github/workflows/owned-shopify-team-observation.yml': {'blob': '7375fe80e2d48d5d4b059da51b7cb7bb79176c47', 'mode': '100644'},
 '.github/workflows/owned-shopify-readonly-preflight.yml': {'blob': 'fab975b4c3613713b242d3e48691fcc04b70f418', 'mode': '100644'},
 '.github/workflows/owned-core-ledger-publisher.yml': {'blob': '61e8b5dc58b8266d2bc6933a333c014b5564eb76', 'mode': '100644'},
 '.github/workflows/owned-core-local.yml': {'blob': 'e710850a60881dc705bd7e8b1467a780dfa42df6', 'mode': '100644'},
 '.github/workflows-quarantined/20261023/JARVIS-Core-Automation.yml': {'blob': '88281a6d915ae2defe085c21ca6a1d1a5b090655',
                                                                       'mode': '100644'},
 '.github/workflows-quarantined/20261023/JARVIS-Deep-Analysis.yml': {'blob': '55dbc1b99a4555329bac0ccc48264de3cfc616a5',
                                                                     'mode': '100644'},
 '.github/workflows-quarantined/20261023/daiso-candidate-recovery.yml': {'blob': 'dd462c349df8358d03049f781a432b46a3a11b54',
                                                                         'mode': '100644'},
 '.github/workflows-quarantined/20261023/daiso-daily-beauty-shopify.yml': {'blob': '8c71932040182c9b37c0ce57e528f20d686980c0',
                                                                           'mode': '100644'},
 '.github/workflows-quarantined/20261023/daiso-discovery.yml': {'blob': 'd367011879b060debf371ecd361b8178319eb55a',
                                                                'mode': '100644'},
 '.github/workflows-quarantined/20261023/daiso-real-collection.yml': {'blob': 'd13a0f49f9025d0d6f3afc7607a509ac69464fe7',
                                                                      'mode': '100644'},
 '.github/workflows-quarantined/20261023/dependency-profiles.yml': {'blob': 'd214551df6c90331d47d2c1124f748443be71647',
                                                                    'mode': '100644'},
 '.github/workflows-quarantined/20261023/fx-refresh.yml': {'blob': '5ddc62254f02626c706c730815a3b58530fed79e',
                                                           'mode': '100644'},
 '.github/workflows-quarantined/20261023/gemini-web-collect.yml': {'blob': 'dda9388abc915f3da102c7734d508e79ad24c822',
                                                                   'mode': '100644'},
 '.github/workflows-quarantined/20261023/gosi-alt.yml': {'blob': 'e5a74772f9d72a55cad883f6b7e521a7e06dc677',
                                                         'mode': '100644'},
 '.github/workflows-quarantined/20261023/gosi-vision.yml': {'blob': 'ac191e962fe369b5f706d0da81ac275cf62b72c4',
                                                            'mode': '100644'},
 '.github/workflows-quarantined/20261023/image-ocr-tests.yml': {'blob': '46677d0d8cf364b7497d767d22b22912a1ccfd2b',
                                                                'mode': '100644'},
 '.github/workflows-quarantined/20261023/inci-dictionary.yml': {'blob': 'b479e87a1f3b988e08d0012eff518733f844ed43',
                                                                'mode': '100644'},
 '.github/workflows-quarantined/20261023/jarvis-real-knowledge.yml': {'blob': 'de6912bd8d7bf64e2d341db2d4f86d35e329965a',
                                                                      'mode': '100644'},
 '.github/workflows-quarantined/20261023/jarvis-watchdog.yml': {'blob': '79a99cda73d07999f74fca314501dc7620355a9a',
                                                                'mode': '100644'},
 '.github/workflows-quarantined/20261023/latest-code-revalidation.yml': {'blob': '60e0c0366c7249fa427020c3e89edb4b801fe662',
                                                                         'mode': '100644'},
 '.github/workflows-quarantined/20261023/obsidian_sync.yml': {'blob': '645cdf59b9b1a3ec99279ba26f8e61b35ac6970c',
                                                              'mode': '100644'},
 '.github/workflows-quarantined/20261023/pages-verified.yml': {'blob': '522e28106bcc51b6c443469a252ecf6d551b305a',
                                                               'mode': '100644'},
 '.github/workflows-quarantined/20261023/preflight.yml': {'blob': 'a662091a17acbedc4ee244a02bc965f0fe5562c4',
                                                          'mode': '100644'},
 '.github/workflows-quarantined/20261023/root-collectors.yml': {'blob': '6743d2db2ec507c170e493bef9da49f6f2937b2a',
                                                                'mode': '100644'},
 '.github/workflows-quarantined/20261023/serpapi-market.yml': {'blob': 'e547794eadecdaf9a05b8e1ddddcb3b3764c6bf3',
                                                               'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-aeo-apply.yml': {'blob': '6043be12829d626b5696536ff8414951db37a2e0',
                                                                  'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-listing-copy.yml': {'blob': '1322b5435f48d7266c7643bc1b9a17ccc8ac762c',
                                                                     'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-manual-draft-repair.yml': {'blob': '00b47d33c7de298530d9453527c898b6db2e85b5',
                                                                            'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-markets-setup.yml': {'blob': '96f0eceefa1179816495c05ad6919ddf4bad9c71',
                                                                      'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-media-alt.yml': {'blob': '940e661e93f971a9b9427c4c300e27fee13c601e',
                                                                  'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-reviewed-active-copy.yml': {'blob': 'd05504841a17732e908813d79036703195bb0203',
                                                                             'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-reviewed-draft-copy.yml': {'blob': '6f2b0894fa949a7d535254dcdd3fc4f48ec0ffe0',
                                                                            'mode': '100644'},
 '.github/workflows-quarantined/20261023/shopify-reviewed-gallery.yml': {'blob': '03b20302247e727c416b6e839ffb38633f4b1dfb',
                                                                         'mode': '100644'},
 '.github/workflows-quarantined/20261023/us-retail-collect.yml': {'blob': 'a9052790ff6bb2465ecb4074ce4bd6f907b39bda',
                                                                  'mode': '100644'},
 '.github/workflows/auto-update.yml.disabled': {'blob': 'e229f196d2b833332ea1f7a314d2273a6394ee2b',
                                                'mode': '100644'},
 '.github/workflows/jarvis-auto-evolution.yml.disabled': {'blob': '77c256bad60636070cdf070b8250f32fc21ec2c3',
                                                          'mode': '100644'},
 '.github/workflows/jarvis-deploy.yml.disabled': {'blob': 'aa666ed1b06f6a4fc2818fa86afb216ef777aa05',
                                                  'mode': '100644'},
 '.github/workflows/jarvis-luna-deploy.yml.disabled': {'blob': 'e942a724624a290d873fe75d0d3dbfa2c3f55100',
                                                       'mode': '100644'},
 '.github/workflows/jarvis_automation.yml.disabled': {'blob': '90a56935921c91f9fdb1c6ff87789152aa6f25c9',
                                                      'mode': '100644'},
 '.github/workflows/jarvis_final_automation.yml.disabled': {'blob': '700203653f9819d5cf44b4eb729dd6e228184555',
                                                            'mode': '100644'},
 '.github/workflows/jarvis_health_monitor.yml.disabled': {'blob': '59366602b6a0c7ff1339e23fff28b5f1cd9b00ba',
                                                          'mode': '100644'},
 '.github/workflows/jarvis_test_simple.yml.disabled': {'blob': '0be7fa769f1d544626e5b3ea54b9f62978f4e0cd',
                                                       'mode': '100644'},
 '.github/workflows/jekyll-gh-pages.yml.disabled': {'blob': '67be9b00bb678d6dcb059ad708b2130499bca1e9',
                                                    'mode': '100644'},
 # Reviewed owner-audit home-card Pages bytes v2; all execution policies remain unchanged.
 '.github/workflows/owned-pages-once.yml': {'blob': 'ae6e5b783ed921aa451fb4810646e70c0a72ffcf',
                                            'mode': '100644'},
 '.github/workflows/owned-repo-smoke.yml': {'blob': '7a5b93b3b97af5b6b3a3a32293db6b232d9a142d',
                                            'mode': '100644'},
 '.github/workflows/phase26_complete_automation.yml.disabled': {'blob': '541ef487568a9763cbfe8cd42b966717e109ce38',
                                                                'mode': '100644'},
 '.github/workflows/strategy_report_20260821_072037.pptx': {'blob': 'cd6cbc85c2104ce335700e1dc2d9b21adbcac9af',
                                                            'mode': '100644'},
 '.github/workflows/update-tasks.yml.disabled': {'blob': 'c9d4e7693ed62203685304983991333c951fcb8e',
                                                 'mode': '100644'},
 '.github/workflows/weekly-strategy-report.yml.disabled': {'blob': '70298444c2e70050143420103203704020a62edc',
                                                           'mode': '100644'}}


def verify(root):
    if KNOWLEDGE_STAGE != 'owned-real-knowledge-data-only-v1':
        raise ValueError('unknown_knowledge_policy_stage')
    if STAGE not in PRODUCER_BLOBS:
        raise ValueError('unknown_workflow_policy_stage')
    expected = dict(EXPECTED)
    expected[PRODUCER_PATH] = {'blob': PRODUCER_BLOBS[STAGE], 'mode': '100644'}
    root = Path(root)
    active = root / '.github/workflows'
    archived = root / '.github/workflows-quarantined/20261023'
    for path in (root / '.github', active, root / '.github/workflows-quarantined', archived):
        if path.is_symlink() or not path.is_dir():
            raise ValueError('workflow_directory_unsafe')
    actual = {}
    active_docs = []
    manual_docs = []
    schedules = 0
    for directory in (active, archived):
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                raise ValueError('workflow_symlink')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('nonregular_workflow_entry')
            with path.open('rb') as stream:
                raw = stream.read(262145)
            if len(raw) > 262144:
                raise ValueError('workflow_size')
            rel = path.relative_to(root).as_posix()
            actual[rel] = {'blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                           'mode': '100755' if path.stat().st_mode & 0o100 else '100644'}
            if directory == active and path.suffix in ('.yml', '.yaml'):
                doc = yaml.safe_load(raw)
                event = doc.get('on', doc.get(True)) if isinstance(doc, dict) else None
                if path.name == 'owned-core-local.yml':
                    producer_events = {'workflow_dispatch': None}
                    if STAGE == HOURLY_STAGE:
                        producer_events['schedule'] = [{'cron': '17 */1 * * *'}]
                    if event != producer_events:
                        raise ValueError('exact_hourly_producer_events_required')
                    if doc.get('permissions') != {'contents': 'read', 'actions': 'read'}:
                        raise ValueError('producer_readonly_required')
                    if STAGE == HOURLY_STAGE:
                        schedules += 1
                    else:
                        manual_docs.append(rel)
                elif path.name == 'owned-real-knowledge-sync.yml':
                    knowledge_events = {
                        'workflow_dispatch': {'inputs': {'expected_sha': {
                            'description': 'Exact reviewed main commit', 'required': True, 'type': 'string'}}},
                        'schedule': [{'cron': '37 0,6,12,18 * * *'}]}
                    jobs = doc.get('jobs', {})
                    job = jobs.get('sync', {})
                    if (event != knowledge_events or doc.get('permissions') != {} or
                            set(jobs) != {'sync'} or job.get('permissions') != {'contents': 'write', 'actions': 'read'} or
                            job.get('if') != KNOWLEDGE_GUARD or job.get('runs-on') != 'ubuntu-latest' or
                            job.get('timeout-minutes') != 15 or 'environment' in job or
                            doc.get('concurrency') != {'group': 'owned-real-knowledge-sync', 'cancel-in-progress': False}):
                        raise ValueError('exact_knowledge_data_only_policy_required')
                    steps = job.get('steps', [])
                    names = ['Install only hash-pinned policy validation dependency',
                             'Verify reviewed knowledge-only helper',
                             'Offline knowledge and workflow boundary tests',
                             'Prepare fixed knowledge-state baseline',
                             'Collect credential-free public knowledge',
                             'Publish only fixed data branch',
                             'Propagate partial collection failure']
                    if (len(steps) != 9 or [s.get('name') for s in steps[2:]] != names or
                            steps[0].get('uses') != 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1' or
                            steps[0].get('with', {}).get('persist-credentials') is not False or
                            steps[0].get('with', {}).get('ref') != '${{ github.sha }}' or
                            steps[1].get('uses') != 'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97'):
                        raise ValueError('knowledge_exact_steps_required')
                    out = '"$RUNNER_TEMP/owned-real-knowledge-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"'
                    commands = {
                        'Prepare fixed knowledge-state baseline': 'python -I -B scripts/owned_real_knowledge_sync.py prepare --root "$GITHUB_WORKSPACE" --out ' + out,
                        'Collect credential-free public knowledge': 'timeout --signal=TERM --kill-after=5s 180s python -I -B scripts/owned_real_knowledge_sync.py collect --root "$GITHUB_WORKSPACE" --out ' + out,
                        'Publish only fixed data branch': 'python -I -B scripts/owned_real_knowledge_sync.py publish --root "$GITHUB_WORKSPACE" --out ' + out,
                        'Propagate partial collection failure': 'python -I -B scripts/owned_real_knowledge_sync.py assert-complete --out ' + out}
                    for step in steps:
                        if step.get('continue-on-error') or step.get('if'):
                            raise ValueError('knowledge_failure_must_propagate')
                        if step.get('name') in commands and step.get('run') != commands[step['name']]:
                            raise ValueError('knowledge_fixed_command_required')
                        token = (step.get('env') or {}).get('GITHUB_TOKEN')
                        privileged = step.get('name') in ('Prepare fixed knowledge-state baseline', 'Publish only fixed data branch')
                        if (privileged and token != '${{ github.token }}') or (not privileged and token not in (None, '')):
                            raise ValueError('knowledge_credential_isolation_required')
                    text = raw.decode('utf-8')
                    if 'secrets.' in text or './.github/actions/publish' in text or any(x in text for x in (
                            'publish_transaction.py', 'generate_dashboard_runtime.py', 'run_jarvis_operations.py',
                            'run_jarvis_agents.py', 'train_real_knowledge.py', 'tune_real_knowledge_moe.py')):
                        raise ValueError('knowledge_broad_execution_forbidden')
                    schedules += 1
                elif path.name == 'owned-core-ledger-publisher.yml':
                    expected_events = {
                        'workflow_run': {'workflows': ['Owned Core local saved-input epoch'],
                                         'types': ['completed'], 'branches': ['main']},
                        'workflow_dispatch': {'inputs': {'operation': {
                            'description': 'Reviewed one-time initialization or bounded terminal recovery',
                            'required': True, 'default': 'publish', 'type': 'choice',
                            'options': ['publish', 'initialize']}}}}
                    if event != expected_events:
                        raise ValueError('exact_terminal_publisher_events_required')
                    jobs = doc.get('jobs', {})
                    if (doc.get('permissions') != {} or set(jobs) != {'publish'} or
                            jobs['publish'].get('permissions') != {'contents': 'write', 'actions': 'read'}):
                        raise ValueError('writer_job_only_permissions_required')
                elif path.name == 'owned-shopify-us-free-shipping.yml':
                    # Preserve the exact pre-existing manual check/apply surface.
                    # Do not turn this inventory repair into broader writer authority.
                    expected_inputs = {
                        'expected_sha': {'description': 'Exact reviewed main commit', 'required': True, 'type': 'string'},
                        'mode': {'description': 'check reads only; apply changes only when K-Packet checkout shipping is not $0',
                                 'required': True, 'default': 'check', 'type': 'choice', 'options': ['check', 'apply']}}
                    jobs = doc.get('jobs', {})
                    job = jobs.get('us_free_shipping', {})
                    if (event != {'workflow_dispatch': {'inputs': expected_inputs}} or
                            doc.get('permissions') != {'contents': 'read'} or
                            set(jobs) != {'us_free_shipping'} or 'permissions' in job or
                            job.get('environment') != 'jarvis-shopify-writer' or
                            job.get('if') != "github.repository == 'coarfamily-cyber/jarvis-luna' && github.ref == 'refs/heads/main' && inputs.expected_sha == github.sha" or
                            job.get('timeout-minutes') != 5 or
                            doc.get('concurrency') != {'group': 'owned-shopify-us-free-shipping', 'cancel-in-progress': False}):
                        raise ValueError('exact_existing_shipping_manual_policy_required')
                    manual_docs.append(rel)
                elif path.name == 'owned-shopify-readonly-preflight.yml':
                    expected_inputs = {
                        'expected_sha': {'description': 'Exact reviewed main commit', 'required': True, 'type': 'string'},
                        'mode': {'description': 'Connection, Organist read-only, reviewed VT canary, or source-only diagnostic',
                                 'required': True, 'default': 'connection', 'type': 'choice',
                                 'options': ['connection', 'organist_dry_run', 'vt_usage_canary', 'source_diagnostic']}}
                    if (event != {'workflow_dispatch': {'inputs': expected_inputs}} or
                            doc.get('permissions') != {'contents': 'read'} or
                            set(doc.get('jobs', {})) != {'preflight', 'vt_usage_canary', 'source_diagnostic'} or
                            doc['jobs']['preflight'].get('environment') != 'jarvis-shopify-writer' or
                            doc['jobs']['vt_usage_canary'].get('environment') != 'jarvis-shopify-writer' or
                            doc['jobs']['vt_usage_canary'].get('permissions') != {'contents': 'read', 'actions': 'read'} or
                            'environment' in doc['jobs']['source_diagnostic'] or
                            doc['jobs']['source_diagnostic'].get('permissions') != {'contents': 'read'}):
                        raise ValueError('readonly_preflight_policy_required')
                    manual_docs.append(rel)
                else:
                    if not isinstance(event, dict) or set(event) != {'workflow_dispatch'}:
                        raise ValueError('manual_only_active_workflow_required')
                    manual_docs.append(rel)
                active_docs.append(rel)
    if actual != expected:
        raise ValueError('workflow_inventory_changed')
    return {'stage': STAGE, 'knowledge_stage': KNOWLEDGE_STAGE, 'scope': 'actual_checkout_quarantine_policy',
            'active_workflows': sorted(active_docs),
            'active_manual_workflows': sorted(manual_docs), 'archived_workflows': 30,
            'active_schedules': schedules, 'production_recovered': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    print(json.dumps(verify(args.root), sort_keys=True))
