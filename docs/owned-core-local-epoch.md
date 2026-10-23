# Destination-local Core epoch: exact recovery path (2026-10-23)

## Verified root causes, not missing API keys

1. `scripts/continuity_reconciliation.py:2433 main(decide)` calls `validate_pending_decision`, then unconditionally emits `MODE = restricted_gap`. There is **no implemented normal-mode return**. Editing the historical code digest would still skip every Core normal runtime step.
2. `validate_pending_decision:2086` compares all current code/workflow bytes with old approved contract. Workflow quarantine/own migration changed it legitimately. Never overwrite the old decision's hash to make this pass.
3. Source `restore_source_safety.restore_latest:69` and `restore_operations_safety._latest:528` authenticate the original source repository and require an existing completed producer. Repointing constants to an empty destination yields `source_run_history_missing` / `run_history_missing`; imported Git history is not destination Actions history.
4. `run_jarvis_operations.run:535` executes only registry-enabled local reads/reports, but reuses old state/claims namespace. It has 2,007 historical claims. Do not reset these, replay old claims, set `JARVIS_OPERATIONS_CONTINUITY=verified` by hand, or treat local snapshot validation as authenticated restore.
5. Original restricted review publication explicitly cannot establish ordinary source/operations checkpoints. Pages never participates in these proofs.

## What this patch does and does not do

The Python module implements **offline content consistency and state-transition rules** for a NEW, distinct destination local-review lineage. It has no I/O, credential access or authority issuer. `business_review` performs actual pure computation on exact six existing saved-input artifacts, with their byte hashes and truthful unknown schema/freshness reporting. It is intentionally a narrow first live slice, not a substitute for the canonical commerce/operations runtime.

The producer accepts a policy pinned outside generated outputs (no self-referential commit digest), preserves immutable import inventory, original unresolved-gap digest, original unknown usage/STOP holds, and the separate source-final-tail digest. Source final tail `e686f86215c8002ce7da0aced8159f373ba89435` after import `1e6a9b361fd9f3d6b32c291a9bf7a54212bba120` must be authenticated and preserved/quarantined as historical evidence; it is not silently deemed imported.

The module's `accept_retained` MUST NOT receive user/workflow-input JSON as authenticated observation. It only checks bindings; authenticity must come from fixed-origin GitHub API adapter using run/job/artifact metadata plus digest-verified archive. A JSON that says `required_steps_successful=true` alone proves nothing. `prepare_checkpoint` returns candidate bytes, not verified evidence. No CLI, workflow, schedule or remote modifications are included.

## Minimum first two REAL executions

1. Authenticate source-import/destination snapshot + final source tail. Independently pin reviewed code transition, user migration authority reference, exact approved workflow bytes, and all inherited data blob/modes. Preserve original records and unresolved gaps. Policy digest is the destination epoch ID; never reuse it for changed policy/code.
2. Add manual-only `.github/workflows/owned-core-local.yml`, own repo IDs only, concurrency `owned-core-local`, cancel-in-progress=false, finite timeout. Default permissions contents:read; actions:read for restoration/authenticated metadata. No provider secrets, source requests, AI, Shopify, scheduled trigger, or inherited workflow execution. Do not claim a full normal Core run.
3. On FIRST run discover **all** destination producer run/attempt history with pagination, fixed workflow/path + approved head ancestry. Prove no earlier unaccounted producer. Existing smoke/Pages are explicitly non-producers, not invented safety checkpoints. Authenticate migration policy and frozen inputs. Pure computation may generate only `checkpoint.json` and review bytes under a temporary output directory. Include current own run/attempt/head. Guard original data before/after. Upload artifact `owned-core-local-RUN-ATTEMPT`; if interrupted/fails, no successful baseline exists. Preserve failed attempt evidence; do not blindly rerun bootstrap.
4. After job terminates, independently fetch completed run/attempt/jobs; require exact required step successes, correct approved head/workflow/own numeric IDs. Authenticate artifact ID/digest and download archive with safe member/size checks, hash archive then inner bytes. Only NOW establish genesis. Do not include the artifact ID/digest inside its own payload (circular).
5. SECOND manual run restores that artifact through the same verified path, validates policy + frozen legacy bytes, scans every intervening attempt (no missing, failed/in-progress unaccounted producer), computes again from exact current saved inputs, emits sequence 1 and predecessor SHA256. Upload, then verify terminal steps/retention independently. Correct stopping evidence: both completed runs have authenticated retained checkpoints and sequence1 references exact sequence0; historical continuity remains unresolved and external effects remain disabled.
6. Only after these two manual runs pass, propose enabling this **limited** local loop schedule. Keep original/full Core quarantined. Scheduled event support requires explicit schema change/review (the prototype currently accepts workflow_dispatch only).

## Route beyond this limited slice (not covered by prototype)

The real offline commerce chain is `run_commerce_pipeline.commands()` from `config/publish_policy.json`; the actual operations dispatcher enables only L1 read_snapshot and L2 snapshot_report. To regain these rather than just review counts:
- Review exact commerce command list and dependency closure for network/side effects.
- Run full actual chain in a disposable root with inherited state read-only and derivative output namespace distinct. For process-based chain use OS network isolation (e.g. reviewed pinned container with network:none, no credentials, read-only base, cap-drop ALL), not merely deleting token variables or Python monkeypatching.
- Existing operations has hardcoded `data/operations/*` and nested modules (`jarvis_execution`, storage, watch, feedback, audit, recovery, brain_plane). Introduce explicit destination epoch storage/root and IDs across these modules; migrate historical tables only as immutable read-only references. Do NOT just change a global filename, empty_state(), or copy old current tasks into a new active epoch.
- New current operations may use saved data and compute local reports without claiming historical source freshness. New claims must be bound to destination repo/epoch and real run/attempt, with durable-before-dispatch and immutable verified output receipts; all external action kinds stay disabled. Exact input snapshots and protected historical root remain pinned.
- Authenticate/checkpoint resulting destination state separately, restore on second run, and report `destination_local_operations_verified=true`, never `production_recovered=true` for unresolved old source lineage.
- Reenable sources only with known authorization and valid unconsumed source scope/budget. Changing repository does not reset old STOP/budget or account for missing provider spend.

## Engineering work vs genuine outside blocker

Engineering: implement fixed-origin run/job/artifact discovery with pagination + archive limits/redirect safety; integrate snapshot adapter and separate source-tail binding; trusted workflow/code pin; safe output writer; two-stage retention verification; failure/supersession recovery; full actual offline operations namespace refactor. These do not require asking user to repeat broad approval.

Outside/permission state: own Actions are currently disabled and current authenticated CLI token was revoked; activating exact new workflow + actual remote code write requires existing authorized connector/browser route or permission step, owned by parent. The user already requested own-repository corrections/execution; do not misstate missing business API keys as blocker. Historical unobserved provider effects cannot be reconstructed by engineering or broad approval; source-specific authoritative reconciliation is needed before clearing those holds. New paid/provider/Shopify scope is excluded, not inferred from migration approval.

## Tests / actual local evidence

`cd scripts && python -m unittest -v test_destination_core_epoch`: 16 tests pass (plus parameterized negative cases). They cover first/second links, all hold invariants, repo/run/attempt/branch/event/head/artifact tampering, final tail requirement, no same-run bootstrap retry, missing inputs, duplicate keys/nonfinite JSON, unknown schema, immutable input/state preservation. Fixtures are NOT actual Actions evidence.

`actual-local-input-review.json` came from existing candidate input bytes, not fabricated products: product_master 356 rows, listing_gate 6; unknown other row shapes honestly remain null. This report does NOT claim market freshness, publication readiness, successful source collection, or full Core recovery.

## Implemented runner update / deployment ordering

`owned_core_local.py` and `.github/workflows/owned-core-local.yml` now implement the bounded run/attempt/jobs/artifact transport and manual first/following-run path. Reviewer independently tested authentication tampering, historical Git code/policy mismatch, deleted-run genesis reset, and token stripping on blob redirects. Pure unit/integration fixtures do not represent successful real executions.

- Workflow ID is **not guessed**. Commit code/workflow while Actions remain disabled, read its actual GitHub workflow ID and verify no prior runs, then run `prepare_owned_core_policy.py --root <reviewed own worktree> --record <approved record> --historical-policy <approved policy> --workflow-id <actual ID>`. It refuses arbitrary import pins and refuses overwriting policy. Do not deploy test ID777.
- The approved historical record SHA is `b609974aa560537a6183447eef29c9072e3dbc0ac8eabe03ce6986eb73c02f01`; historical policy SHA is `cfe83cdcf173efe10e4460472ae846e923262c868230398737ee3c993320161a`. Neither grants provider/source/STOP authority.
- Existing exact-two-workflow policy must be deliberately revised to permit exactly the new third manual workflow after independent review; never bypass its check. Do not restore any quarantined workflow.
- `--verify-run FIRST_ID` returns a `genesis_seal` ONLY after authenticated successful completed run, steps, exact code/policy Git objects, recomputed result, and digest-verified artifact. Commit that exact object to `config/destination-core-local/genesis-seal.json` before second run. It is a reference to actual verified evidence, not a replacement ledger. No full Core success flag is written.
- Workflow copies exactly the four reviewed modules to a fresh runner-temp directory and invokes Python isolated mode. Repo/PYTHONPATH modules cannot shadow stdlib or widen the module dependency closure. No inherited scripts are executed.
- Every run proves a contiguous workflow `run_number` sequence starting1, pinned numeric workflow ID, exact same code/policy contract in historical producers, and the same genesis seal. Deleting failed/expired runs cannot silently restart the epoch.

### Finite proof, not a durable recurring service

This exact implementation is for **two manual proof runs**, not indefinite production automation. All prior checkpoints must remain available. Artifacts expire after30days; fixed100HTTP-request and10-page budgets impose a maximum about25 total runs for small histories (artifact downloads usually consume API302+blob GET). A missing, failed, deleted, expired, changed-code or unaccounted attempt blocks. Do not schedule this implementation indefinitely or call it permanently restored.

### Bounded resilience work before scheduling

Do not answer a later failed run by deleting it, resetting epoch sequence, loosening runtime guards, or blindly rerunning the same run. A future explicit reconciliation transition can preserve a failed attempt as a tombstone, but is NOT accepted by this current verifier:
1. Authenticate complete fixed workflow/run/attempt/jobs/steps + artifact inventory, exact approved local-only code bytes and ancestry. Distinguish no-job cancellation from failure before local computation, failure during computation, and retention/post-upload failure.
2. If no output artifact exists, approved code has no repository/external business writes, and no concurrent unaccounted producer exists, record that precise bounded failure disposition (not historic source/no-spend claims). Preserve run/head/attempt/job identities and evidence digests; sequence never resets.
3. If an uploaded checkpoint exists but run failed, authenticate and retain it as **uncommitted candidate evidence**, never automatically promote success. Any state ambiguity stays blocked.
4. Store append-only failure dispositions plus successful checkpoint references in durable reviewed repository history before artifact expiry; independently verify chain and all immutable members. Resume only under an explicit tested state transition. Rotating code contracts needs a migration edge binding predecessor checkpoint, code diff, unchanged legacy evidence and same capability ceiling—not automatic fresh genesis.
5. Test each failure phase, request budget, retention expiration, checkpoint rollback, duplicate-run retry and post-upload crash before enabling a schedule. These are implementation gaps for recurring production, not a demand for new user business permissions.
