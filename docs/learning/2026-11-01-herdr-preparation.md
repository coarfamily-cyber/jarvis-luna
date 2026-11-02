# Herdr: inactive offline preparation

The [video](https://www.youtube.com/watch?v=zpf84UcXcXo) is “AI 코딩하시면 써보세요. 허더가 무료 앱으로 나왔습니다 [3분 완벽 정리]” by 민둥이 | 쉽게 배우는 AI (198 seconds). Metadata and description were verified; transcript retrieval was empty. This is **description verified and official documentation cross-checked**, not a full video/transcript review. Description chapters cover delegation/reporting (00:28), custom UI (01:06), a background core (01:46), and setup (02:36).

Sources: [Herdr](https://herdr.dev/), [Core](https://herdr.dev/core/), [protocol](https://github.com/herdrdev/herdr-core/blob/master/schema/README.md), [OpenRPC schema](https://github.com/herdrdev/herdr-core/blob/master/schema/hc.openrpc.json), [security](https://github.com/herdrdev/herdr-core/blob/master/docs/security.md). This is herdrdev's Herdr, not herder.sh or account failover. The app, core and TUI use Apache-2.0; AI providers may charge separately.

Programs report status through OSC 7501; Core does not infer it from terminal text. Closing the app can leave terminals running in a living Core. Machine reboot or a replacement shell does not establish automatic resumption of the original task. Core API clients have the OS account's command/file access; do not expose a raw API or create access.

## Pure snapshot adapter

`scripts/herdr_status_adapter.py` exports only `normalize_snapshot(payload, *, now_ms, expected_epoch)`. It is inactive and standalone: no file reads, CLI, subprocess, network, socket, installer, Core connection, credentials, agent execution or runtime wiring. Call it explicitly with UTF-8 JSON **bytes** (at most 65,536 bytes, at most 128 terminals). No dependencies beyond Python's standard library.

The caller must supply an explicit capture wrapper, not a conversion-time timestamp:

```json
{"captured_ms":1000,"source_epoch":"fixture-epoch","fresh_snapshot":true,"snapshot":{"terminals":[{"address":"t1","state":"live","reported":true,"status":{"state":"working"},"status_ms":900}],"hidden_finished":0,"machines":[]}}
```

`snapshot` projects the official `terminal.list` ListResult (`terminals`, `hidden_finished`, `machines`). This example includes only the fields consumed from Terminal, not a complete wire Terminal. `status` is a nullable Status object, distinct from Terminal's `state` (`live`/`finished`). The wrapper, clock and expected epoch are local capture provenance conventions, not invented Herdr wire fields or authentication. Capture time/epoch are caller assertions, not independently verified. Supply a fresh snapshot after reconnect, missed events or restart; event sequence numbers reset with the core and are not accepted here. Never reuse an old epoch to merge event streams.

Age is based on explicit capture time (maximum five minutes). Future/stale capture, epoch mismatch or missing fresh-snapshot assertion yields unknown observations. `status_ms` measures when the status changed, **not heartbeat freshness**; an old unchanged working report can remain working within a fresh capture. Missing status/report/time, unsupported words, loss/pending reasons or termination never become done. Malformed JSON, duplicate JSON keys or terminal addresses, oversized input, invalid types or impossible future field times fail closed with a fixed error that does not echo data. Missing required wrapper/ListResult fields fail closed. No report or missing lifecycle stays unknown; an empty list does not establish global health. Hidden finished counts and remote machines are not expanded.

Public output contains only ordinal rows with allowlisted reported states, lifecycle/reason, bounded numeric exit code and constant unverified flags. It never emits addresses, hostnames, labels, command lines, paths, terminal text, status messages, records or source epoch. An exit code is a program result, not independent verification. `done` never means tests passed, deployment, business approval or Core recovery. All corresponding verification flags remain false. No receipts are created.

## Team/feed scope

Knowledge reviews evidence/status semantics; institutions reviews capture/reconnect/loss semantics; design reviews unknown/report/exit presentation; legal reviews licensing/cost/access boundaries. These are generated review assignments, not acknowledgements or execution evidence.

After the inventory collision repair, approved additions live in `review/manual/team_briefings.json`; `scripts/team_briefing_overlay.py` combines them with the immutable imported manual base. The 25-briefing view and materialized `review/team_feeds.json` preserve the previously approved content exactly.

`scripts/refresh_briefing_feeds_offline.py` writes only `review/team_feeds.json` and uses only the existing pure `briefing_rows` and `team_feed_row` helpers, never the network-fetching full builder. It appends missing manual assignments, preserves every old row and all original global generation/source/aggregate metadata, and adds `briefing_refresh` provenance with a source digest and stored row counts. Existing aggregates still describe the last full build, not this scoped refresh. Repeating it on the same source is byte-idempotent. Existing consumers (`build_error_report.py`, `team_router_moe.py`) iterate arrays without a 60-row constraint; `generate_dashboard_runtime.py` reads the original summary. No schema maxItems constraint was found. The full builder's existing 60-row cap is unchanged, but its output is now an unconsumed `review/candidates/team_feeds.json`; it cannot overwrite imported data or the retained briefing-only view. No full builder/source collection is part of this repair.

No installation, paid service, credential creation/configuration, SSH, live connection, Shopify change, workflow change, manual rerun or explicit deployment is included. Current Core remains `saved_input_business_review_only`, `full_core_recovery=false`. Live adapter/agent operation and full Core recovery remain unverified and require separate authorization and setup.
