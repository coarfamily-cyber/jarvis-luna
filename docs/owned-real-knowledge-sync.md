# Owned real-knowledge data synchronization v2

## Scope

`Owned real knowledge sync` is an explicitly reviewed, information-only lane in
`coarfamily-cyber/jarvis-luna` (repository 1431541717, owner 280980688).
The legacy `jarvis-real-knowledge.yml` remains quarantined byte-for-byte. Its broad
publisher can invoke operational and commerce generators and is not used here.

The new lane collects public OpenAlex paper metadata and Google News RSS through
bounded, credential-free HTTPS GETs. It preserves the historical main corpus and
accumulates records by URL. Main's saved corpus is a historical baseline, not a
claim that old captures are fresh. Five already-published baseline text fields
end in incomplete URL prefixes. Their explicitly reviewed prose tails remain
opaque text, without completion or fetching; actionable record/request/provenance
URLs and credential checks stay strict. It does not run model training, promote model
weights, regenerate Obsidian, rebuild the operational dashboard, register products,
modify Shopify, run advertisements, or grant business authority.

The main baseline is resolved only through the fixed nonrecursive Git-tree path
`data/knowledge/training_corpus.jsonl`. Every tree level must be complete and
match its expected SHA, path segment, object type and mode. A truncated whole-main
recursive listing is never accepted or needed. The dedicated data branch still
uses its complete recursive tree and strict data-only path allowlist.

## Isolation from concurrent main edits

Source code and policy changes are reviewed on a separate branch. Runtime output
is written only to the data-only `owned-real-knowledge` branch, never to `main`.
Each run records its actual source commit and GitHub run URL. This prevents a
knowledge job from overlaying an old repository or dashboard snapshot onto Codex's
newer main changes.

The data branch contains `latest.json`, cumulative `corpus.jsonl`, and immutable
`captures/<run_id>-1/real_sources.json` entries. Previous captures are retained;
normal fast-forward/CAS publication rejects a changed baseline. Ambiguous write
results are reconciled by reading the ref, never by blindly retrying POSTs.

`latest.json` is the integration point for a future live Knowledge UI. The existing
Pages dashboard is an intentionally preserved historical projection. This change
does not relabel its old counts as current or remove its operational blockers.
Codex can connect the new data source without changing the preserved snapshot.

## Cadence and evidence

The reviewed UTC schedule is `37 0,6,12,18 * * *`, corresponding to 09:37, 15:37,
21:37 and 03:37 Asia/Seoul. GitHub may delay scheduled runs. Manual dispatch requires
an exact reviewed main SHA. A successful manual run proves that execution only;
actual scheduled execution must be checked separately.

Capture time, article publication time and assembly time are separate. Fresh
receipts do not make inherited records fresh. URL additions, content changes and
clock-only evidence refreshes are counted separately. Partial evidence can be
retained, but the final completion gate fails on required partial/failed sources.
No model training or production recovery is inferred from a new timestamp.

## Cost and credential boundary

Only the public repository's standard Ubuntu runner is used. Public source GETs
have no paid API key. Collection receives no GitHub token, Google CSE secret,
YouTube secret, Gemini key or TypeSafe key. The ephemeral repository GitHub token
is explicitly passed only to the fixed baseline reader and data-branch publisher.
The pinned standard checkout uses repository authentication without persisting
credentials. Collection receives no GitHub token. No Actions artifacts are
uploaded, avoiding additional artifact-storage usage.

## Safety policy

The existing Core stage and all 30 quarantined workflows remain unchanged. The
separate `owned-real-knowledge-data-only-v2` policy pins this one new workflow and
keeps all unrelated workflows manual-only. Pages' literal workflow inventory is
updated, but its 36-file projection, site hash and `production_recovered=false`
assertions remain intact. Any change to reviewed helper bytes requires a matching
workflow checksum and workflow fingerprint review.
