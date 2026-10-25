"""Offline contract tests. Run: python -B -m unittest discover -s scripts -p test_owned_real_knowledge_sync.py -v"""
import ast
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import owned_real_knowledge_sync as sync


def environment():
    return {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": sync.REPO,
            "GITHUB_REPOSITORY_ID": sync.REPO_ID, "GITHUB_REPOSITORY_OWNER_ID": sync.OWNER_ID,
            "GITHUB_REF": "refs/heads/main", "GITHUB_REF_TYPE": "branch",
            "GITHUB_WORKFLOW_REF": sync.REPO + "/" + sync.WORKFLOW + "@refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_API_URL": "https://api.github.com", "GITHUB_EVENT_NAME": "schedule",
            "GITHUB_SHA": "a" * 40, "GITHUB_WORKFLOW_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}


class Response(io.BytesIO):
    def __init__(self, data=b"{}", url="https://api.openalex.org/works", status=200):
        super().__init__(data)
        self.url = url
        self.status = status

    def geturl(self):
        return self.url


class FakeAPI:
    """In-memory Git objects and ref updates, including accepted-but-lost responses."""
    def __init__(self, seed, existing=False):
        self.seed = seed
        self.baseline = seed
        self.current = "b" * 40 if existing else None
        self.initial = self.current
        self.calls = []
        self.mode = "normal"
        self.verified = 0
        self.previous = {"corpus.jsonl": "c" * 40, "latest.json": "d" * 40,
                         "captures/100-1/real_sources.json": "e" * 40} if existing else {}

    def verify(self):
        self.verified += 1

    def head(self):
        if self.mode == "unknown" and any(p.startswith("/git/refs") for _, p, _ in self.calls):
            raise TimeoutError("offline simulated unknown")
        return self.current

    def tree(self, commit):
        if commit == "a" * 40:
            return {"truncated": False, "tree": [{"path": "data/knowledge/training_corpus.jsonl", "type": "blob", "mode": "100644", "sha": "2" * 40}]}
        return {"truncated": False, "tree": [{"path": k, "sha": v, "type": "blob", "mode": "100644"} for k, v in self.previous.items()]}

    def blob(self, blob_sha, cap):
        return self.baseline if blob_sha == "2" * 40 else self.seed

    def call(self, method, suffix, body=None):
        self.calls.append((method, suffix, body))
        if suffix == "/git/blobs":
            return {"sha": sync.digest(base64.b64decode(body["content"]))[:40]}
        if suffix == "/git/trees":
            return {"sha": "f" * 40}
        if suffix == "/git/commits":
            return {"sha": "1" * 40}
        if suffix.startswith("/git/refs"):
            if self.mode == "rejected":
                raise TimeoutError("not accepted")
            self.current = body["sha"]
            if self.mode in ("lost_response", "unknown"):
                raise TimeoutError("response lost")
            return {"object": {"sha": self.current}}
        raise AssertionError((method, suffix))


class FakeCollectors:
    def __init__(self, reason=False, fail_google=False, stale=False):
        self.reason = reason
        self.fail_google = fail_google
        self.stale = stale
        self.called = []

    def result(self, name, count):
        self.called.append(name)
        if name == "google" and self.fail_google:
            raise ValueError("simulated parser error")
        items, captures = [], []
        host = "api.openalex.org" if name == "arxiv" else "news.google.com"
        for n in range(count):
            url = "https://" + host + "/works?q=" + str(n) + "&mailto="
            self.fetch(url)
            at = "2000-01-01T00:00:00+00:00" if self.stale else sync.now()
            provenance = {"kind": "response_parse", "response_received": True,
                          "parse_succeeded": True, "collected_at": at, "response_url": url,
                          "parser": "json" if name == "arxiv" else "rss_xml"}
            captures.append(provenance)
            items.append({"title": name + str(n), "url": "https://example.org/" + name + str(n),
                          "published": "2020-01-01", "collected_at": at,
                          "evidence_type": "external_capture", "provenance": provenance})
        return {"status": "ok", "reason": "one query failed" if self.reason else "", "items": items,
                "provenance": {"captures": captures}}

    def collect_arxiv(self):
        return self.result("arxiv", 2)

    def collect_google(self):
        return self.result("google", 3)


def transport():
    return sync.SourceTransport(adapter=lambda req, timeout: Response(b"{\"results\":[]}", req.full_url))


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.block_network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("real network forbidden"))
        self.block_network.start()
        self.addCleanup(self.block_network.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.env = environment()
        self.old = [{"url": "https://example.org/undated", "title": "undated"},
                    {"url": "https://example.org/historical", "title": "historical", "collected_at": "2019-01-01T00:00:00Z", "published": "2018-02-01"}]
        self.seed = b"".join(sync.encode(r) for r in self.old)

    def prepared(self, existing=False):
        api = FakeAPI(self.seed, existing)
        sync.prepare(self.out, self.out, api=api, env=self.env)
        return api

    def collected(self, module=None, existing=False):
        api = self.prepared(existing)
        result = sync.collect(self.out, self.out, module=module or FakeCollectors(), transport_factory=transport, env=self.env)
        return api, result

    def test_actions_guards(self):
        self.assertEqual(sync.context(self.env)["run_attempt"], 1)
        for key, bad in (("GITHUB_REF", "refs/heads/evil"), ("GITHUB_REPOSITORY", "other/repo"),
                         ("GITHUB_REPOSITORY_ID", "1"), ("GITHUB_REPOSITORY_OWNER_ID", "1"),
                         ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_EVENT_NAME", "pull_request"),
                         ("GITHUB_WORKFLOW_SHA", "b" * 40), ("GITHUB_WORKFLOW_REF", "evil"),
                         ("GITHUB_API_URL", "https://evil.example")):
            with self.subTest(key=key), self.assertRaises(sync.SyncError):
                sync.context({**self.env, key: bad})

    def test_actual_api_identity(self):
        good = {"id": int(sync.REPO_ID), "full_name": sync.REPO, "owner": {"id": int(sync.OWNER_ID)}}
        def client(doc):
            return sync.GitHubAPI(token="offline-not-real", adapter=lambda req, timeout: Response(sync.encode(doc), req.full_url))
        client(good).verify()
        for bad in ({**good, "id": 1}, {**good, "owner": {"id": 1}}, {**good, "full_name": "evil/repo"}):
            with self.assertRaises(sync.SyncError):
                client(bad).verify()

    def test_transport_allowlist_credentials_and_mailto(self):
        seen = []
        def adapter(req, timeout):
            seen.append(req)
            return Response(b"hello", req.full_url)
        tr = sync.SourceTransport(adapter)
        tr.fetch("https://api.openalex.org/works?mailto=private%40example.org&q=AI")
        self.assertNotIn("mailto", seen[0].full_url)
        self.assertFalse(any(k.lower() == "authorization" for k in seen[0].headers))
        receipt = tr.receipts[0]
        self.assertEqual(receipt["sha256"], sync.digest(b"hello"))
        self.assertEqual(receipt["bytes"], 5)
        sync.instant(receipt["received_at"])
        for url in ("http://api.openalex.org/works", "https://evil.example/", "https://api.openalex.org.evil.example/", "https://user:pass@api.openalex.org/", "https://api.openalex.org/?token=secret", "https://api.openalex.org:444/"):
            with self.subTest(url=url), self.assertRaises(sync.SyncError):
                tr.fetch(url)

    def test_redirect_and_body_rejection(self):
        with self.assertRaises(sync.SyncError):
            sync.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example/")
        tr = sync.SourceTransport(lambda req, timeout: Response(b"x", "https://evil.example/"))
        with self.assertRaises(sync.SyncError):
            tr.fetch("https://news.google.com/rss")
        with patch.object(sync, "BODY_CAP", 4):
            tr = sync.SourceTransport(lambda req, timeout: Response(b"12345", req.full_url))
            with self.assertRaises(sync.SyncError):
                tr.fetch("https://news.google.com/rss")

    def test_api_redirect_rejected(self):
        api = sync.GitHubAPI(token="offline-not-real", adapter=lambda req, timeout: Response(b"{}", "https://evil.example"))
        with self.assertRaises(sync.SyncError):
            api.verify()
        with self.assertRaises(sync.SyncError):
            api.call("GET", "/../../evil")

    def test_malformed_duplicate_private_seed_fail_closed(self):
        for seed in (b"not-json\n", b"[]\n", self.seed + sync.encode(self.old[0]), b"\n",
                     sync.encode({"url": "file:///private"}), sync.encode({"url": "https://127.0.0.1/a"}),
                     sync.encode({"url": "https://example.org/a", "text": "https://localhost/private"})):
            with self.subTest(seed=seed), self.assertRaises((sync.SyncError, ValueError)):
                sync.parse_corpus(seed)

    def test_preserve_undated_and_historical_rows(self):
        _, result = self.collected()
        self.assertEqual(result["status"], "complete")
        records = sync.parse_corpus((self.out / "corpus.jsonl").read_bytes())
        for old in self.old:
            self.assertEqual(records[old["url"]], old)
        self.assertEqual(result["counters"]["new_urls"], 5)
        self.assertEqual(len(result["captured_at"]), 5)
        self.assertFalse(result["production_recovered"])
        self.assertFalse(result["commercial_execution"])
        self.assertFalse(result["model_training_performed"])
        self.assertNotIn("mailto", (self.out / "real_sources.json").read_text())
        for row in records.values():
            if row["url"].startswith("https://example.org/arxiv"):
                self.assertEqual(row["published"], "2020-01-01")
                self.assertIn("response_received_at", row["provenance"])
                self.assertEqual(row["record_id"], sync.digest(row["url"].encode()))

    def test_live_capture_outside_attempt_rejected(self):
        _, result = self.collected(FakeCollectors(stale=True))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"], 2)
        self.assertEqual(result["captured_at"], [])

    def test_genuine_receipt_required(self):
        row = {"url": "https://example.org/x", "collected_at": sync.now(), "evidence_type": "external_capture",
               "provenance": {"kind": "response_parse", "response_received": True, "parse_succeeded": True,
                              "response_url": "https://api.openalex.org/works", "parser": "json"}}
        row["provenance"]["collected_at"] = row["collected_at"]
        with self.assertRaises(sync.SyncError):
            sync.normalize_live(row, [], "2000-01-01T00:00:00Z", "2099-01-01T00:00:00Z")

    def test_dedup_content_and_clock_counters_history(self):
        a = {"url": "https://example.org/a", "title": "same", "collected_at": "2020-01-01T00:00:00Z"}
        b = {**a, "collected_at": "2021-01-01T00:00:00Z"}
        merged, counts = sync.merge_records({a["url"]: a}, [b, b])
        self.assertEqual(counts["new_urls"], 0)
        self.assertEqual(counts["content_changes"], 0)
        self.assertEqual(counts["evidence_refreshes"], 1)
        self.assertEqual(counts["duplicate_live_urls"], 1)
        self.assertNotIn("history", merged[a["url"]])
        self.assertEqual(merged[a["url"]]["observations"]["first"]["collected_at"], a["collected_at"])
        self.assertEqual(merged[a["url"]]["observations"]["latest"]["collected_at"], b["collected_at"])
        self.assertEqual(merged[a["url"]]["observations"]["count"], 2)
        self.assertEqual(merged[a["url"]]["collected_at"], a["collected_at"])
        replayed, repeated = sync.merge_records(merged, [b])
        self.assertEqual(repeated["evidence_refreshes"], 0)
        self.assertEqual(replayed, merged)
        c = {**b, "title": "changed", "collected_at": "2022-01-01T00:00:00Z"}
        merged2, counts = sync.merge_records(merged, [c])
        self.assertEqual(counts["content_changes"], 1)
        self.assertEqual(len(merged2[a["url"]]["history"]), 1)
        self.assertEqual(sync.content(merged2[a["url"]]["history"][0]), sync.content(a))
        self.assertNotIn("history", merged2[a["url"]]["history"][0])

    def test_no_deletion_and_cap(self):
        merged, _ = sync.merge_records(sync.parse_corpus(self.seed), [])
        self.assertEqual(len(merged), 2)
        with patch.object(sync, "CORPUS_CAP", 2), self.assertRaises(sync.SyncError):
            sync.corpus_bytes(merged)
        self.collected()
        (self.out / "corpus.jsonl").write_bytes(b"")
        with self.assertRaises(sync.SyncError):
            sync.publication_files(self.out, sync.context(self.env))

    def test_tree_allowlist_and_modes(self):
        for name, mode, kind in (("scripts/run.py", "100644", "blob"), ("corpus.jsonl", "100755", "blob"),
                                 ("latest.json", "120000", "blob"), ("x", "160000", "commit"),
                                 ("captures/12-2/real_sources.json", "100644", "blob")):
            with self.subTest(name=name), self.assertRaises(sync.SyncError):
                sync.tree_files({"truncated": False, "tree": [{"path": name, "mode": mode, "type": kind, "sha": "a" * 40}]})
        with self.assertRaises(sync.SyncError):
            sync.tree_files({"truncated": True, "tree": []})

    def test_orphan_publication_and_exact_replay(self):
        api, _ = self.collected()
        result = sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(result["status"], "published")
        commit = [body for _, path, body in api.calls if path == "/git/commits"][0]
        self.assertEqual(commit["parents"], [])
        tree = [body for _, path, body in api.calls if path == "/git/trees"][0]
        self.assertNotIn("base_tree", tree)
        self.assertTrue(all(sync.allowed_path(row["path"]) for row in tree["tree"]))
        before = len(api.calls)
        sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(len(api.calls), before)
        self.assertEqual(sync.assert_complete(self.out)["status"], "complete")

    def test_existing_branch_parents_old_captures_retained(self):
        api, _ = self.collected(existing=True)
        sync.publish(self.out, self.out, api=api, env=self.env)
        commit = [body for _, path, body in api.calls if path == "/git/commits"][0]
        self.assertEqual(commit["parents"], ["b" * 40])
        tree = [body for _, path, body in api.calls if path == "/git/trees"][0]
        self.assertIn("captures/100-1/real_sources.json", [row["path"] for row in tree["tree"]])
        update = [body for _, path, body in api.calls if path.startswith("/git/refs/heads/")][0]
        self.assertIs(update["force"], False)

    def test_cas_conflict_no_writes(self):
        api, _ = self.collected()
        api.current = "9" * 40
        with self.assertRaises(sync.SyncError):
            sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(api.calls, [])

    def test_lost_response_reconciles_no_retry(self):
        api, _ = self.collected()
        api.mode = "lost_response"
        self.assertEqual(sync.publish(self.out, self.out, api=api, env=self.env)["status"], "published")
        self.assertEqual(len([p for _, p, _ in api.calls if p == "/git/refs"]), 1)

    def test_unknown_outcome_no_retry(self):
        api, _ = self.collected()
        api.mode = "unknown"
        with self.assertRaises(sync.SyncError):
            sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(sync.load(self.out / "publication.json")["status"], "pending")
        self.assertEqual(len([p for _, p, _ in api.calls if p == "/git/refs"]), 1)

    def test_rejected_ref_not_repeated(self):
        api, _ = self.collected()
        api.mode = "rejected"
        with self.assertRaises(sync.SyncError):
            sync.publish(self.out, self.out, api=api, env=self.env)
        before = len(api.calls)
        with self.assertRaises(sync.SyncError):
            sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(len(api.calls), before)

    def test_partial_evidence_published_completion_nonzero(self):
        module = FakeCollectors(fail_google=True)
        api, result = self.collected(module)
        self.assertEqual(module.called, ["arxiv", "google"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"], 4)
        sync.publish(self.out, self.out, api=api, env=self.env)
        with self.assertRaises(sync.SyncError):
            sync.assert_complete(self.out)
        self.assertEqual(sync.main(["assert-complete", "--out", str(self.out)]), 1)

    def test_missing_query_is_partial(self):
        module = FakeCollectors()
        module.collect_arxiv = lambda: module.result("arxiv", 1)
        _, result = self.collected(module)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"], {"arxiv": "partial", "google": "complete"})

    def test_bad_seed_prepare_leaves_no_accepted_state(self):
        api = FakeAPI(self.seed + sync.encode(self.old[0]))
        with self.assertRaises(sync.SyncError):
            sync.prepare(self.out, self.out, api=api, env=self.env)
        self.assertFalse((self.out / "prepared.json").exists())
        self.assertEqual(api.calls, [])

    def test_http_error_receipt(self):
        def adapter(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 429, "limit", {}, io.BytesIO(b"limited"))
        tr = sync.SourceTransport(adapter)
        with self.assertRaises(urllib.error.HTTPError):
            tr.fetch("https://api.openalex.org/works")
        self.assertEqual(tr.receipts[0]["status"], 429)
        self.assertEqual(tr.receipts[0]["sha256"], sync.digest(b"limited"))
        self.assertFalse(tr.receipts[0]["parse_succeeded"])

    def test_real_pinned_collectors_with_fake_https(self):
        self.prepared()
        root = Path(sync.__file__).resolve().parent.parent
        module = sync.load_legacy(root)
        def adapter(req, timeout):
            if req.full_url.startswith("https://api.openalex.org/"):
                data = sync.encode({"results": [{"title": "Actual pinned parser", "publication_date": "2024-01-01", "primary_location": {"landing_page_url": "https://arxiv.org/abs/2401.00001"}}]})
            else:
                data = b"<rss><channel><item><title>News parser</title><link>https://example.org/news</link><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item></channel></rss>"
            return Response(data, req.full_url)
        result = sync.collect(root, self.out, module=module,
                              transport_factory=lambda: sync.SourceTransport(adapter), env=self.env)
        self.assertEqual(result["status"], "complete")
        capture = sync.load(self.out / "real_sources.json")
        self.assertEqual(len(capture["sources"]["arxiv"]["receipts"]), 2)
        self.assertEqual(len(capture["sources"]["google"]["receipts"]), 3)

    def test_existing_empty_or_missing_baseline_corpus_rejected(self):
        for seed in (b"", sync.encode(self.old[0])):
            with self.subTest(seed=seed):
                api = FakeAPI(seed, existing=True)
                api.baseline = self.seed
                with self.assertRaisesRegex(sync.SyncError, "baseline URL coverage"):
                    sync.prepare(self.out, self.out, api=api, env=self.env)
                self.assertFalse((self.out / "prepared.json").exists())
                self.assertEqual(api.calls, [])

    def test_missing_main_baseline_rejected_even_with_existing_branch(self):
        api = FakeAPI(self.seed, existing=True)
        api.baseline = b""
        with self.assertRaisesRegex(sync.SyncError, "baseline must not be empty"):
            sync.prepare(self.out, self.out, api=api, env=self.env)
        self.assertFalse((self.out / "prepared.json").exists())
        api = FakeAPI(self.seed, existing=True)
        original_tree = api.tree
        api.tree = lambda commit: {"truncated": False, "tree": []} if commit == "a" * 40 else original_tree(commit)
        with self.assertRaisesRegex(sync.SyncError, "baseline missing/invalid"):
            sync.prepare(self.out, self.out, api=api, env=self.env)

    def test_baseline_revalidated_before_collect_and_publish(self):
        self.prepared()
        (self.out / "baseline.jsonl").write_bytes(b"")
        with self.assertRaisesRegex(sync.SyncError, "baseline changed/missing"):
            sync.collect(self.out, self.out, module=FakeCollectors(), transport_factory=transport, env=self.env)
        (self.out / "baseline.jsonl").write_bytes(self.seed)
        sync.collect(self.out, self.out, module=FakeCollectors(), transport_factory=transport, env=self.env)
        (self.out / "baseline.jsonl").write_bytes(b"")
        api = FakeAPI(self.seed)
        with self.assertRaisesRegex(sync.SyncError, "baseline changed/missing"):
            sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(api.calls, [])

    def test_thousand_clock_refreshes_have_bounded_size_and_content_history(self):
        row = {"url": "https://example.org/large", "title": "large unchanged record",
               "text": "x" * (5 * 1024 * 1024), "collected_at": "2000-01-01T00:00:00Z"}
        records = {row["url"]: row}
        # Large text is shared in memory; encode only at the measured boundaries.
        initial_size = len(sync.corpus_bytes(records))
        for n in range(1, 1001):
            fresh = {**row, "collected_at": "2026-01-01T00:00:%02d+00:00" % (n % 60)}
            records, counters = sync.merge_records(records, [fresh])
            self.assertEqual(counters["content_changes"], 0)
            self.assertEqual(counters["new_urls"], 0)
        retained = records[row["url"]]
        self.assertNotIn("history", retained)
        self.assertEqual(retained["observations"]["count"], 1001)
        self.assertEqual(retained["observations"]["first"]["collected_at"], row["collected_at"])
        self.assertEqual(retained["collected_at"], row["collected_at"])
        self.assertNotEqual(retained["observations"]["latest"]["collected_at"], retained["collected_at"])
        self.assertLess(len(sync.corpus_bytes(records)) - initial_size, 2048)
        changed = {**row, "title": "meaningful new version", "text": "new content", "collected_at": "2027-01-01T00:00:00Z"}
        records, counters = sync.merge_records(records, [changed])
        self.assertEqual(counters["content_changes"], 1)
        historical = records[row["url"]]["history"]
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["text"], row["text"])
        self.assertNotIn("history", historical[0])
        # A later clock refresh retains exactly that one meaningful old version.
        records, _ = sync.merge_records(records, [{**changed, "collected_at": "2028-01-01T00:00:00Z"}])
        self.assertEqual(records[row["url"]]["history"], historical)
        sync.require_baseline({row["url"]: row}, records)

    def test_clock_only_baseline_refresh_can_publish_without_full_history(self):
        baseline_row = {"url": "https://example.org/arxiv0", "title": "arxiv0", "published": "2020-01-01", "collected_at": "2000-01-01T00:00:00Z",
                        "captured_at": "2000-01-01T00:00:00Z", "evidence_type": "inherited_capture",
                        "provenance": {"kind": "historical_import", "collected_at": "2000-01-01T00:00:00Z", "artifact": "public-baseline.json"}}
        self.seed += sync.encode(baseline_row)
        api, result = self.collected()
        record = sync.parse_corpus((self.out / "corpus.jsonl").read_bytes())[baseline_row["url"]]
        self.assertNotIn("history", record)
        self.assertEqual(record["observations"]["first"]["collected_at"], baseline_row["collected_at"])
        self.assertEqual(record["observations"]["count"], 2)
        self.assertEqual(sync.evidence(record), sync.evidence(baseline_row))
        latest = record["observations"]["latest"]
        self.assertGreater(sync.instant(latest["collected_at"]), sync.instant(record["collected_at"]))
        self.assertEqual(latest["evidence_type"], "external_capture")
        self.assertTrue(latest["provenance"]["parse_succeeded"])
        capture = sync.load(self.out / "real_sources.json")
        receipts = capture["sources"]["arxiv"]["receipts"]
        self.assertTrue(any(r["sha256"] == latest["provenance"]["response_sha256"] and r["received_at"] == latest["provenance"]["response_received_at"] for r in receipts))
        self.assertEqual(result["counters"]["content_changes"], 0)
        self.assertEqual(result["counters"]["evidence_refreshes"], 1)
        self.assertEqual(result["collection_scope"], ["arxiv", "google"])
        self.assertEqual(result["baseline_records"], 3)
        sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(sync.assert_complete(self.out)["status"], "complete")

    def test_existing_baseline_capture_evidence_tampering_rejected(self):
        original = {"url": "https://example.org/baseline", "title": "unchanged body", "text": "same",
                    "collected_at": "2020-01-01T00:00:00Z", "captured_at": "2020-01-01T00:00:00Z",
                    "evidence_type": "inherited_capture", "provenance": {"kind": "historical", "artifact": "baseline.json"}}
        mutations = []
        for key in ("collected_at", "captured_at", "provenance", "evidence_type"):
            mutations.append(("removed " + key, {k: v for k, v in original.items() if k != key}))
        mutations.extend((
            ("changed clock", {**original, "collected_at": "2021-01-01T00:00:00Z"}),
            ("future clock", {**original, "collected_at": "2099-01-01T00:00:00Z"}),
            ("fabricated provenance", {**original, "provenance": {"kind": "response_parse", "parse_succeeded": True}}),
            ("fabricated evidence type", {**original, "evidence_type": "external_capture"})))
        for label, bad in mutations:
            with self.subTest(mutation=label):
                # Even an exact self-declared first observation cannot repair the
                # missing original evidence in a real current/historical version.
                bad["observations"] = {"first": sync.evidence(original), "latest": sync.evidence(bad), "count": 99}
                api = FakeAPI(sync.encode(bad), existing=True)
                api.baseline = sync.encode(original)
                with self.assertRaisesRegex(sync.SyncError, "baseline content/capture evidence"):
                    sync.prepare(self.out, self.out, api=api, env=self.env)
                self.assertFalse((self.out / "prepared.json").exists())
                self.assertEqual(api.calls, [])

    def test_baseline_body_and_evidence_must_match_one_actual_version(self):
        original = {"url": "https://example.org/bound", "title": "original", "collected_at": "2020-01-01T00:00:00Z", "provenance": {"kind": "historical"}}
        bad = {**original, "collected_at": "2099-01-01T00:00:00Z"}
        bad["history"] = [{**original, "title": "different body"}]
        with self.assertRaisesRegex(sync.SyncError, "baseline content/capture evidence"):
            sync.require_baseline({original["url"]: original}, {original["url"]: bad})
        # A true content-change history containing the entire original is valid.
        legitimate = {**original, "title": "new body", "collected_at": "2026-01-01T00:00:00Z", "history": [original]}
        sync.require_baseline({original["url"]: original}, {original["url"]: legitimate})

    def test_collect_rejects_baseline_clock_tamper_with_consistent_digest(self):
        self.prepared()
        records = sync.parse_corpus(self.seed)
        records[self.old[1]["url"]]["collected_at"] = "2099-01-01T00:00:00Z"
        changed = sync.corpus_bytes(records)
        (self.out / "previous.jsonl").write_bytes(changed)
        state = sync.load(self.out / "prepared.json")
        state["seed_sha256"] = sync.digest(changed)
        sync.save(self.out / "prepared.json", state)
        module = FakeCollectors()
        with self.assertRaisesRegex(sync.SyncError, "baseline content/capture evidence"):
            sync.collect(self.out, self.out, module=module, transport_factory=transport, env=self.env)
        self.assertEqual(module.called, [])
        self.assertFalse((self.out / "real_sources.json").exists())

    def test_publish_rejects_baseline_evidence_tamper_with_consistent_digest(self):
        api, _ = self.collected()
        records = sync.parse_corpus((self.out / "corpus.jsonl").read_bytes())
        records[self.old[1]["url"]]["provenance"] = {"kind": "fabricated"}
        changed = sync.corpus_bytes(records)
        (self.out / "corpus.jsonl").write_bytes(changed)
        latest = sync.load(self.out / "latest.json")
        latest["corpus_sha256"] = sync.digest(changed)
        sync.save(self.out / "latest.json", latest)
        with self.assertRaisesRegex(sync.SyncError, "baseline content/capture evidence"):
            sync.publish(self.out, self.out, api=api, env=self.env)
        self.assertEqual(api.calls, [])

    def test_late_transport_setup_failure_retains_successful_source(self):
        api = self.prepared()
        module = FakeCollectors()
        created = []
        def factory():
            created.append(True)
            if len(created) == 2:
                raise RuntimeError("late transport constructor failure")
            return transport()
        result = sync.collect(self.out, self.out, module=module, transport_factory=factory, env=self.env)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"], {"arxiv": "complete", "google": "failed"})
        capture = sync.load(self.out / "real_sources.json")
        self.assertEqual(capture["sources"]["arxiv"]["items"], 2)
        self.assertEqual(len(capture["sources"]["arxiv"]["receipts"]), 2)
        self.assertTrue(all(r["parse_succeeded"] for r in capture["sources"]["arxiv"]["receipts"]))
        self.assertEqual(capture["sources"]["google"]["items"], 0)
        self.assertEqual(capture["sources"]["google"]["receipts"], [])
        self.assertEqual(module.called, ["arxiv"])
        records = sync.parse_corpus((self.out / "corpus.jsonl").read_bytes())
        self.assertEqual(len(records), len(self.old) + capture["sources"]["arxiv"]["items"])
        sync.publish(self.out, self.out, api=api, env=self.env)
        with self.assertRaises(sync.SyncError):
            sync.assert_complete(self.out)

    def test_canonical_lf_crlf_fingerprint_and_semantic_changes(self):
        root = Path(sync.__file__).resolve().parent.parent
        canonical = (root / "real_knowledge_sync.py").read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(sync.digest(canonical), sync.LEGACY_SHA256)
        path = self.out / "real_knowledge_sync.py"
        for data in (canonical, canonical.replace(b"\n", b"\r\n")):
            path.write_bytes(data)
            module = sync.load_legacy(self.out)
            self.assertEqual(module.OPENALEX_MAILTO, "")
            self.assertTrue(callable(module.collect_arxiv))
            self.assertTrue(callable(module.collect_google))
        for changed in (canonical + b"\n", canonical.replace(b"def collect_google():", b"def collect_google_changed():", 1), canonical.replace(b"\n", b"\r", 1)):
            path.write_bytes(changed)
            with self.assertRaisesRegex(sync.SyncError, "checksum mismatch"):
                sync.load_legacy(self.out)

    def test_incomplete_record_text_tails_are_opaque_and_preserved(self):
        for token in ("spectru", "www", "w", "lmcounc", "ins"):
            for scheme in ("https", "http"):
                for prefix in ("A truncated article ends at ", 'An article has <a href="'):
                    with self.subTest(token=token, scheme=scheme, prefix=prefix):
                        text = prefix + scheme + "://" + token
                        row = {"url": "https://example.org/article", "text": text,
                               "collected_at": "2020-01-01T00:00:00Z", "provenance": {"kind": "historical"}}
                        records = sync.parse_corpus(sync.encode(row))
                        self.assertEqual(records[row["url"]], row)
                        merged, _ = sync.merge_records(records, [])
                        self.assertEqual(merged, records)
                        self.assertEqual(sync.parse_corpus(sync.corpus_bytes(merged)), records)
                        # Flat content history can retain that exact original text.
                        changed = {**row, "text": "new body", "history": [row]}
                        sync.parse_corpus(sync.encode(changed))
                        # It never becomes a valid standalone or request URL.
                        with self.assertRaises(sync.SyncError):
                            sync.public_url(scheme + "://" + token)
                        with self.assertRaises(sync.SyncError):
                            sync.public_url(scheme + "://" + token, request=True)

    def test_opaque_tail_exception_does_not_relax_other_fields_or_links(self):
        for field in ("url", "title", "response_url", "source"):
            row = {"url": "https://example.org/article", field: "Read https://www"}
            with self.subTest(field=field), self.assertRaises(sync.SyncError):
                sync.parse_corpus(sync.encode(row))
        for provenance in ({"response_url": "https://www"}, {"text": "Read https://www"}):
            with self.subTest(provenance=provenance), self.assertRaises(sync.SyncError):
                sync.parse_corpus(sync.encode({"url": "https://example.org/article", "provenance": provenance}))
        bad_texts = (
            "https://www", "(https://www", "Read https://www more prose", "Read https://www ",
            "Read https://www/", "Read https://www?x=1", "Read https://www#fragment",
            "Read https://user@www", "Read https://www:443", "Read https://unknown",
            "Read https://localhost", "Read https://localhost/private", "Read https://printer",
            "Read https://router", "Read https://gateway", "Read https://internal",
            "Read https://example.local/private", "Read https://127.0.0.1/private",
            "Read https://192.168.1.1/private", "Read https://[::1]/private",
            "Read https://example.org/?token=secret", "Read https://example.org/?mailto=person%40example.org",
            "Read file:///private then https://www", "Read C:\\private\\file then https://www",
            "Read https://localhost/private then https://www", "Read ghp_" + "a" * 30 + " then https://www")
        for text in bad_texts:
            with self.subTest(text=text), self.assertRaises((sync.SyncError, ValueError)):
                sync.parse_corpus(sync.encode({"url": "https://example.org/article", "text": text}))
        # Receipts/manifests do not opt into record-prose handling.
        with self.assertRaises(sync.SyncError):
            sync.check_public({"text": "Read https://www"})

    def test_actual_main_seed_loads_and_preserves_all_records_unchanged(self):
        root = Path(sync.__file__).resolve().parent.parent
        path = root / "data" / "knowledge" / "training_corpus.jsonl"
        if not path.is_file():
            self.skipTest("readonly main seed not extracted in this checkout")
        raw = path.read_bytes()
        self.assertEqual(len(raw), 5085230)
        git_blob = sync.hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        self.assertEqual(git_blob, "2fcccb6891fcff0f4afd5c5338f6f9bea9b4b649")
        original = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        self.assertEqual(len(original), 8674)
        records = sync.parse_corpus(raw)
        self.assertEqual(len(records), 8674)
        self.assertTrue(all(records[row["url"]] == row for row in original))
        api = FakeAPI(raw)
        sync.prepare(root, self.out, api=api, env=self.env)
        module = FakeCollectors()
        module.collect_arxiv = lambda: {"status": "failed", "reason": "offline fixture", "items": []}
        module.collect_google = lambda: {"status": "failed", "reason": "offline fixture", "items": []}
        result = sync.collect(root, self.out, module=module, transport_factory=transport, env=self.env)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"], 8674)
        retained = sync.parse_corpus((self.out / "corpus.jsonl").read_bytes())
        self.assertEqual(retained, records)
        self.assertTrue(all(retained[row["url"]] == row for row in original))
        # Validate the actual publication inputs without making API writes/calls.
        files = sync.publication_files(self.out, sync.context(self.env))
        self.assertEqual(sync.parse_corpus(files["corpus.jsonl"]), records)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(api.calls, [])

    def test_nonempty_reason_not_green(self):
        _, result = self.collected(FakeCollectors(reason=True))
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all(v == "partial" for v in result["sources"].values()))

    def test_collect_token_rejected(self):
        self.prepared()
        with self.assertRaises(sync.SyncError):
            sync.collect(self.out, self.out, env={**self.env, "GITHUB_TOKEN": "offline-not-real"})

    def test_pinned_legacy_import_and_forbidden_calls(self):
        (self.out / "real_knowledge_sync.py").write_text("raise AssertionError('must not execute')")
        with self.assertRaises(sync.SyncError):
            sync.load_legacy(self.out)
        tree = ast.parse(Path(sync.__file__).read_text(encoding="utf-8"))
        forbidden = {"collect_organic_skincare", "collect_us_beauty", "collect_robotics", "collect_institutions", "prepare_real_training_corpus"}
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertFalse(calls & forbidden)
        self.assertNotIn("main", calls)


if __name__ == "__main__":
    unittest.main()
