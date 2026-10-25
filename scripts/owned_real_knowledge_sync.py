#!/usr/bin/env python3
"""Fixed owned-repository data-only synchronization; Python standard library only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request

REPO = "coarfamily-cyber/jarvis-luna"
REPO_ID = "1431541717"
OWNER_ID = "280980688"
BRANCH = "owned-real-knowledge"
WORKFLOW = ".github/workflows/owned-real-knowledge-sync.yml"
LEGACY_SHA256 = "6d0457eea6030df21e6ea15ff4360e5998d6c618c355e1f657b51e681b146db8"
API = "https://api.github.com/repos/" + REPO
HOSTS = frozenset(("api.openalex.org", "news.google.com"))
CORPUS_CAP = 16 * 1024 * 1024
BODY_CAP = 2 * 1024 * 1024
API_CAP = 24 * 1024 * 1024
CAPTURE_CAP = 4 * 1024 * 1024
MAX_FILES = 20000
SECRET = re.compile(r"github_pat_|gh[pousr]_[A-Za-z0-9]{16,}|-----BEGIN .*PRIVATE KEY|Bearer\s+[A-Za-z0-9]|sk-[A-Za-z0-9]{20,}", re.I)


class SyncError(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise SyncError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    need(isinstance(value, str), "missing capture clock")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyncError("invalid capture clock") from exc
    need(dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0, "clock must be UTC")
    return dt


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path, cap):
    with Path(path).open("rb") as stream:
        data = stream.read(cap + 1)
    need(len(data) <= cap, "local file cap")
    return data


def load(path):
    return json.loads(read_bytes(path, API_CAP))


def save(path, obj):
    data = encode(obj)
    need(len(data) <= API_CAP, "state cap")
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def sha(value):
    need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "invalid git SHA")
    return value


def context(env=None):
    e = os.environ if env is None else env
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPO,
                "GITHUB_REPOSITORY_ID": REPO_ID, "GITHUB_REPOSITORY_OWNER_ID": OWNER_ID,
                "GITHUB_REF": "refs/heads/main", "GITHUB_REF_TYPE": "branch",
                "GITHUB_WORKFLOW_REF": REPO + "/" + WORKFLOW + "@refs/heads/main",
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_API_URL": "https://api.github.com"}
    for key, value in expected.items():
        need(e.get(key) == value, "untrusted Actions context: " + key)
    need(e.get("GITHUB_EVENT_NAME") in ("schedule", "workflow_dispatch"), "unsupported event")
    source = sha(e.get("GITHUB_SHA"))
    need(e.get("GITHUB_WORKFLOW_SHA") == source, "workflow/source mismatch")
    run = e.get("GITHUB_RUN_ID", "")
    need(re.fullmatch(r"[1-9][0-9]{0,19}", run), "invalid run ID")
    return {"repository": REPO, "source_sha": source, "run_id": run, "run_attempt": 1,
            "run_url": "https://github.com/" + REPO + "/actions/runs/" + run,
            "capture_path": "captures/" + run + "-1/real_sources.json"}


def public_url(url, request=False):
    need(isinstance(url, str) and 0 < len(url) <= 8192, "invalid URL")
    need(not any(ord(c) < 33 for c in url), "unsafe URL characters")
    p = urllib.parse.urlsplit(url)
    need(p.scheme in (("https",) if request else ("http", "https")), "unsafe scheme")
    need(p.hostname and not p.username and not p.password, "unsafe authority")
    need(p.port in ((None, 443) if request else (None, 80, 443)), "unsafe port")
    host = p.hostname.lower()
    if request:
        need(host in HOSTS, "request host denied")
    need("." in host and not host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".test", ".invalid")), "private/local link")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    need(address is None, "IP literal denied")
    pairs = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    need(not any(re.fullmatch(r"access_token|token|api[_-]?key|password|secret|authorization|credential|contact|email", k, re.I) for k, _ in pairs), "credential/contact query")
    # Remove contact values from transport and public evidence, even when empty.
    clean_pairs = [(k, v) for k, v in pairs if k.lower() != "mailto"]
    query = p.query if len(clean_pairs) == len(pairs) else urllib.parse.urlencode(clean_pairs)
    result = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, query, p.fragment))
    need(not SECRET.search(result), "credential URL")
    return result


# The pinned main corpus contains these five cut-off host prefixes in prose.
# They are opaque text, not hosts or fetch destinations. Fail closed for any
# unrecognized dotless token rather than guessing whether it names a local host.
INCOMPLETE_PROSE_PREFIXES = frozenset(("spectru", "www", "w", "lmcounc", "ins"))


def incomplete_prose_tail(value, match):
    if match.end() != len(value) or not re.search(r"[^\W\d_]", value[:match.start()]):
        return False
    token = re.fullmatch(r"https?://([a-z]+)", match.group())
    return token is not None and token.group(1) in INCOMPLETE_PROSE_PREFIXES


def check_public(value, *, record=False, prose_tail=False):
    if isinstance(value, dict):
        for key, item in value.items():
            need(not re.fullmatch(r"token|password|api_key|authorization|secret", key, re.I), "credential field")
            if record and key == "history" and isinstance(item, list):
                for version in item:
                    check_public(version, record=True)
            else:
                # Only a record's direct text field (including flat historical
                # versions) is prose. Provenance and all structured URLs stay strict.
                check_public(item, prose_tail=record and key == "text" and isinstance(item, str))
    elif isinstance(value, list):
        for item in value:
            check_public(item)
    elif isinstance(value, str):
        need(not SECRET.search(value), "credential content")
        need(not re.search(r"file://|[A-Za-z]:\\", value, re.I), "local link")
        for match in re.finditer(r"https?://[^\s<>\"']+", value):
            if prose_tail and incomplete_prose_tail(value, match):
                continue
            link = match.group()
            need(public_url(link) == link, "contact URL in content")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SyncError("HTTP redirects rejected")


def open_request():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open


def bounded_response(response, cap):
    data = response.read(cap + 1)
    need(len(data) <= cap, "response body cap")
    return data


class SourceTransport:
    def __init__(self, adapter=None, clock=now):
        self.adapter = adapter or open_request()
        self.clock = clock
        self.receipts = []

    def fetch(self, url):
        url = public_url(url, request=True)
        receipt = {"url": url, "status": None, "bytes": 0, "sha256": None,
                   "received_at": None, "parse_succeeded": False}
        self.receipts.append(receipt)
        need(len(self.receipts) <= 8, "request count cap")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "owned-real-knowledge/1"}, method="GET")
            with self.adapter(req, timeout=20) as response:
                need(response.geturl() == url, "redirected response")
                receipt["status"] = response.status
                data = bounded_response(response, BODY_CAP)
                receipt.update(bytes=len(data), sha256=digest(data), received_at=self.clock())
                instant(receipt["received_at"])
                need(response.status == 200, "source status")
                return data
        except urllib.error.HTTPError as exc:
            receipt["status"] = exc.code
            receipt["error"] = type(exc).__name__
            try:
                data = bounded_response(exc, BODY_CAP)
                receipt.update(bytes=len(data), sha256=digest(data), received_at=self.clock())
            finally:
                exc.close()
            raise
        except Exception as exc:
            receipt["error"] = type(exc).__name__
            raise


class GitHubAPI:
    def __init__(self, token=None, adapter=None):
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        need(bool(self._token), "token required in prepare/publish only")
        self.adapter = adapter or open_request()

    def call(self, method, suffix, body=None):
        need(method in ("GET", "POST", "PATCH"), "unsupported method")
        need(suffix == "" or suffix.startswith("/"), "unsafe API path")
        path, sep, query = suffix.partition("?")
        need(not any(c in path for c in ("..", "#", "\\")), "unsafe API path")
        need(not sep or (method == "GET" and query == "recursive=1" and path.startswith("/git/trees/")), "unsafe API query")
        url = API + suffix
        headers = {"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "owned-real-knowledge/1"}
        data = None if body is None else encode(body)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with self.adapter(req, timeout=30) as response:
            need(response.geturl() == url, "GitHub redirect")
            need(200 <= response.status < 300, "GitHub status")
            return json.loads(bounded_response(response, API_CAP))

    def verify(self):
        doc = self.call("GET", "")
        need(str(doc.get("id")) == REPO_ID and doc.get("full_name") == REPO, "actual repository mismatch")
        need(str((doc.get("owner") or {}).get("id")) == OWNER_ID, "actual owner mismatch")

    def head(self):
        try:
            doc = self.call("GET", "/git/ref/heads/" + BRANCH)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        need(doc.get("ref") == "refs/heads/" + BRANCH, "unexpected ref")
        need((doc.get("object") or {}).get("type") == "commit", "ref not commit")
        return sha(doc["object"]["sha"])

    def tree(self, commit):
        doc = self.call("GET", "/git/commits/" + sha(commit))
        tree_sha = sha(doc["tree"]["sha"])
        return self.call("GET", "/git/trees/" + tree_sha + "?recursive=1")

    def blob(self, blob_sha, cap):
        doc = self.call("GET", "/git/blobs/" + sha(blob_sha))
        need(doc.get("encoding") == "base64" and 0 <= doc.get("size", cap + 1) <= cap, "invalid blob")
        data = base64.b64decode(doc["content"])
        need(len(data) == doc["size"] and len(data) <= cap, "blob size mismatch")
        need(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == blob_sha, "blob digest mismatch")
        return data


def allowed_path(name):
    return name in ("latest.json", "corpus.jsonl", "graph.json", "knowledge.md") or re.fullmatch(r"captures/[1-9][0-9]{0,19}-1/real_sources\.json", name) is not None


def tree_files(doc):
    need(doc.get("truncated") is False and isinstance(doc.get("tree"), list), "incomplete Git tree")
    need(len(doc["tree"]) <= MAX_FILES, "tree cap")
    files, seen = {}, set()
    for row in doc["tree"]:
        name = row.get("path", "")
        need(name and name not in seen, "duplicate/invalid tree path")
        seen.add(name)
        if row.get("type") == "tree":
            need(row.get("mode") == "040000" and (name == "captures" or re.fullmatch(r"captures/[1-9][0-9]{0,19}-1", name)), "forbidden directory")
            continue
        need(row.get("type") == "blob" and row.get("mode") == "100644" and allowed_path(name), "forbidden data blob")
        files[name] = sha(row["sha"])
    return files


def parse_corpus(data):
    need(len(data) <= CORPUS_CAP, "corpus cap")
    records = {}
    for line in data.decode("utf-8").splitlines():
        need(bool(line.strip()), "blank corpus row")
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise SyncError("malformed corpus") from exc
        need(isinstance(row, dict), "row must be object")
        url = row.get("url")
        need(public_url(url) == url, "nonpublic seed URL")
        need(url not in records, "duplicate seed URL")
        check_public(row, record=True)
        records[url] = row
    return records


def corpus_bytes(records):
    data = b"".join(encode(records[k]) for k in sorted(records))
    need(len(data) <= CORPUS_CAP, "corpus cap; pruning forbidden")
    return data


def prepare(root, out, api=None, env=None):
    ctx = context(env)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    need(not (out / "prepared.json").exists(), "prepare already exists")
    api = api or GitHubAPI()
    api.verify()
    # Always establish the source-main baseline, including when a data branch exists.
    tree = api.tree(ctx["source_sha"])
    need(tree.get("truncated") is False, "truncated main baseline tree")
    matches = [r for r in tree.get("tree", []) if r.get("path") == "data/knowledge/training_corpus.jsonl"]
    need(len(matches) == 1 and matches[0].get("mode") == "100644" and matches[0].get("type") == "blob", "tracked main baseline missing/invalid")
    baseline_data = api.blob(matches[0]["sha"], CORPUS_CAP)
    baseline = parse_corpus(baseline_data)
    need(bool(baseline), "main baseline must not be empty")
    head = api.head()
    if head:
        files = tree_files(api.tree(head))
        need("corpus.jsonl" in files and "latest.json" in files, "incomplete previous branch")
        seed = api.blob(files["corpus.jsonl"], CORPUS_CAP)
        origin = BRANCH + "/corpus.jsonl"
    else:
        seed = baseline_data
        files = {}
        origin = "main:data/knowledge/training_corpus.jsonl"
    records = parse_corpus(seed)
    require_baseline(baseline, records)
    (out / "baseline.jsonl").write_bytes(baseline_data)
    (out / "previous.jsonl").write_bytes(seed)
    result = {"schema_version": 1, "context": ctx, "expected_head": head, "previous_files": files,
              "baseline_sha256": digest(baseline_data), "baseline_records": len(baseline),
              "seed_origin": origin, "seed_sha256": digest(seed), "previous_records": len(records), "prepared_at": now()}
    save(out / "prepared.json", result)
    return result


def load_legacy(root):
    path = Path(root) / "real_knowledge_sync.py"
    # Git's canonical LF bytes and Windows CRLF checkouts have one fingerprint.
    # No stripping, decoding/re-encoding, or other semantic-byte normalization.
    data = read_bytes(path, BODY_CAP).replace(b"\r\n", b"\n")
    need(digest(data) == LEGACY_SHA256, "legacy checksum mismatch")
    spec = importlib.util.spec_from_file_location("_owned_pinned_collectors", path)
    module = importlib.util.module_from_spec(spec)
    # Execute exactly the verified bytes, not a second read or stale bytecode.
    # Checksum-pinned stdlib definitions only. Never call its entry point.
    exec(compile(data, str(path), "exec"), module.__dict__)
    module.OPENALEX_MAILTO = ""
    return module


def normalize_live(row, receipts, started, ended):
    need(isinstance(row, dict) and row.get("evidence_type") == "external_capture", "not live evidence")
    p = row.get("provenance") or {}
    need(p.get("kind") == "response_parse" and p.get("response_received") is True and p.get("parse_succeeded") is True, "missing parse evidence")
    at = row.get("collected_at")
    need(p.get("collected_at") == at and instant(started) <= instant(at) <= instant(ended), "capture outside attempt")
    response_url = public_url(p.get("response_url"), request=True)
    matches = [r for r in receipts if r["url"] == response_url and r["received_at"] and r["status"] == 200]
    need(len(matches) == 1, "missing/ambiguous response receipt")
    receipt = matches[0]
    need(instant(started) <= instant(receipt["received_at"]) <= instant(at), "invalid receipt clock")
    need(p.get("parser") in ("json", "rss_xml"), "unknown parser")
    receipt["parse_succeeded"] = True
    result = dict(row)
    result["url"] = public_url(row.get("url"))
    result["provenance"] = {**p, "response_url": response_url, "response_sha256": receipt["sha256"], "response_received_at": receipt["received_at"]}
    check_public(result, record=True)
    return result


EVIDENCE_FIELDS = frozenset(("collected_at", "captured_at", "provenance", "evidence_type"))
CLOCK_FIELDS = EVIDENCE_FIELDS | {"record_id", "history", "observations"}


def content(row):
    return {k: v for k, v in row.items() if k not in CLOCK_FIELDS}


def versions(row):
    history = row.get("history", [])
    need(isinstance(history, list) and all(isinstance(h, dict) and "history" not in h for h in history), "invalid/nested content history")
    return [row] + history


def require_baseline(baseline, records):
    need(bool(baseline) and set(baseline) <= set(records), "main baseline URL coverage missing")
    for url, original in baseline.items():
        retained = versions(records[url])
        # Bind body and exact original evidence in the same retained version.
        # Summaries/digests cannot attest a removed or fabricated baseline clock.
        need(all(any(same_version(old, v) for v in retained) for old in versions(original)), "main baseline content/capture evidence version missing")


def read_baseline(out, state):
    data = read_bytes(Path(out) / "baseline.jsonl", CORPUS_CAP)
    need(digest(data) == state.get("baseline_sha256"), "main baseline changed/missing")
    records = parse_corpus(data)
    need(len(records) == state.get("baseline_records") and bool(records), "main baseline count mismatch")
    return records


def evidence(row):
    return {k: row[k] for k in EVIDENCE_FIELDS if k in row}


def same_version(left, right):
    return content(left) == content(right) and evidence(left) == evidence(right)


def observation_update(old, fresh, refreshed):
    """Constant-size clock summary; immutable captures retain intermediate receipts."""
    latest = evidence(fresh)
    if old is None:
        return {"first": latest, "latest": latest, "count": 1}
    summary = old.get("observations")
    if summary is None:
        first = evidence(old)
        summary = {"first": first, "latest": first, "count": 1 if first else 0}
    need(isinstance(summary, dict) and isinstance(summary.get("count"), int) and summary["count"] >= 0, "invalid observation summary")
    return {"first": summary["first"], "latest": latest,
            "count": summary["count"] + int(refreshed)}


def merge_records(previous, incoming):
    merged = dict(previous)
    counters = {"new_urls": 0, "content_changes": 0, "evidence_refreshes": 0, "duplicate_live_urls": 0}
    seen = set()
    for row in incoming:
        url = row["url"]
        if url in seen:
            counters["duplicate_live_urls"] += 1
            continue
        seen.add(url)
        old = merged.get(url)
        fresh = dict(row)
        fresh["record_id"] = digest(url.encode())
        if old is None:
            counters["new_urls"] += 1
            fresh["observations"] = observation_update(None, fresh, True)
        else:
            changed = content(old) != content(fresh)
            latest_observed = old.get("observations", {}).get("latest", evidence(old))
            refreshed = latest_observed != evidence(fresh)
            counters["content_changes"] += int(changed)
            counters["evidence_refreshes"] += int(refreshed)
            history = list(versions(old)[1:])
            # Only meaningful content changes retain a full prior version.
            # Clock-only refreshes never copy the full text or append history.
            if changed:
                history.append({k: v for k, v in old.items() if k != "history"})
            if history:
                fresh["history"] = history
            fresh["observations"] = observation_update(old, fresh, refreshed)
            if not changed:
                # Original version evidence is immutable. The verified new capture
                # lives in bounded observations.latest and immutable source receipts.
                # Preserve absence too: an undated baseline is never backdated.
                for key in EVIDENCE_FIELDS:
                    fresh.pop(key, None)
                fresh.update(evidence(old))
        merged[url] = fresh
    need(set(previous) <= set(merged), "record deletion forbidden")
    return merged, counters


def collect(root, out, module=None, transport_factory=SourceTransport, env=None):
    e = os.environ if env is None else env
    need(not e.get("GITHUB_TOKEN"), "collect must not receive GITHUB_TOKEN")
    ctx = context(e)
    out = Path(out)
    state = load(out / "prepared.json")
    need(state["context"] == ctx, "prepared context mismatch")
    seed = read_bytes(out / "previous.jsonl", CORPUS_CAP)
    need(digest(seed) == state["seed_sha256"], "seed changed")
    previous = parse_corpus(seed)
    baseline = read_baseline(out, state)
    require_baseline(baseline, previous)
    need(not (out / "real_sources.json").exists(), "immutable collection already exists")
    started = now()
    sources, incoming = {}, []
    try:
        module = module or load_legacy(root)
        module.OPENALEX_MAILTO = ""
    except Exception as exc:
        sources = {name: {"status": "failed", "errors": ["collector initialization: " + type(exc).__name__], "items": 0, "receipts": []} for name in ("arxiv", "google")}
    if not sources:
        for name, attribute, expected in (("arxiv", "collect_arxiv", 2), ("google", "collect_google", 3)):
            transport = None
            errors, valid = [], []
            try:
                # Setup, function lookup, fetching, and parsing are source-local.
                transport = transport_factory()
                module.fetch = transport.fetch
                result = getattr(module, attribute)()
                need(isinstance(result, dict), "invalid source result")
                if result.get("status") != "ok" or result.get("reason"):
                    errors.append("collector reported failure/partial/empty")
                end = now()
                for evidence in (result.get("provenance") or {}).get("captures", []):
                    response_url = public_url(evidence.get("response_url"), request=True)
                    at = evidence.get("collected_at")
                    need(evidence.get("parse_succeeded") is True and evidence.get("response_received") is True and instant(started) <= instant(at) <= instant(end), "invalid source parse clock")
                    for receipt in transport.receipts:
                        if receipt["url"] == response_url and receipt["received_at"] and instant(receipt["received_at"]) <= instant(at):
                            receipt["parse_succeeded"] = True
                            receipt["parsed_at"] = at
                for row in result.get("items", []):
                    try:
                        valid.append(normalize_live(row, transport.receipts, started, end))
                    except Exception as exc:
                        errors.append("invalid item: " + type(exc).__name__)
            except Exception as exc:
                errors.append("collector error: " + type(exc).__name__)
            receipts = transport.receipts if transport is not None else []
            if len(receipts) != expected or any(not r["parse_succeeded"] or r["status"] != 200 for r in receipts):
                errors.append("missing/failed query capture")
            if not valid:
                errors.append("no valid external rows")
            sources[name] = {"status": "partial" if errors and valid else "failed" if errors else "complete",
                             "errors": sorted(set(errors)), "items": len(valid), "receipts": receipts}
            incoming.extend(valid)
    merged, counters = merge_records(previous, incoming)
    require_baseline(baseline, merged)
    corpus = corpus_bytes(merged)
    assembled = now()
    status = "complete" if all(sources[k]["status"] == "complete" for k in ("arxiv", "google")) else "partial"
    capture = {"schema_version": 1, "context": ctx, "attempt_started_at": started, "assembled_at": assembled, "status": status, "sources": sources}
    need(len(encode(capture)) <= CAPTURE_CAP, "capture cap")
    latest = {"schema_version": 1, **ctx, "assembled_at": assembled, "attempt_started_at": started,
              "status": status, "sources": {k: v["status"] for k, v in sources.items()},
              "capture_sha256": digest(encode(capture)), "corpus_sha256": digest(corpus),
              "previous_records": len(previous), "records": len(merged), "counters": counters,
              "baseline_records": len(baseline), "baseline_sha256": state["baseline_sha256"],
              "collection_scope": ["arxiv", "google"],
              "corpus_scope": "main baseline plus cumulative owned source captures",
              "captured_at": sorted({r["collected_at"] for r in incoming}),
              "production_recovered": False, "commercial_execution": False,
              "model_training_performed": False, "model_performance": "not_measured"}
    check_public(capture)
    (out / "corpus.jsonl").write_bytes(corpus)
    save(out / "latest.json", latest)
    save(out / "real_sources.json", capture)
    return latest


def publication_files(out, ctx):
    out = Path(out)
    corpus = read_bytes(out / "corpus.jsonl", CORPUS_CAP)
    records = parse_corpus(corpus)
    state = load(out / "prepared.json")
    baseline = read_baseline(out, state)
    previous = parse_corpus(read_bytes(out / "previous.jsonl", CORPUS_CAP))
    require_baseline(baseline, previous)
    require_baseline(baseline, records)
    need(set(previous) <= set(records), "publication deletes records")
    for url, row in previous.items():
        retained = versions(records[url])
        need(any(same_version(row, v) for v in retained), "historical content/capture evidence erased")
        need(all(h in records[url].get("history", []) for h in versions(row)[1:]), "history erased")
        if row.get("observations"):
            summary = records[url].get("observations", {})
            need(summary.get("first") == row["observations"]["first"] and summary.get("count", -1) >= row["observations"]["count"], "observation summary regressed")
    latest = load(out / "latest.json")
    capture = load(out / "real_sources.json")
    need(capture.get("context") == ctx and all(latest.get(k) == v for k, v in ctx.items()), "publication context mismatch")
    need(latest.get("corpus_sha256") == digest(corpus) and latest.get("capture_sha256") == digest(encode(capture)), "publication digest mismatch")
    need(all(latest.get(k) is False for k in ("production_recovered", "commercial_execution", "model_training_performed")), "false completion claims required")
    need(latest.get("status") == capture.get("status"), "status mismatch")
    check_public(latest)
    check_public(capture)
    need(len(encode(capture)) <= CAPTURE_CAP, "capture cap")
    return {"corpus.jsonl": corpus, "latest.json": encode(latest), ctx["capture_path"]: encode(capture)}


def publish(root, out, api=None, env=None):
    ctx = context(env)
    out = Path(out)
    state = load(out / "prepared.json")
    need(state["context"] == ctx, "prepared context mismatch")
    need(digest(read_bytes(out / "previous.jsonl", CORPUS_CAP)) == state["seed_sha256"], "seed changed")
    files = publication_files(out, ctx)
    api = api or GitHubAPI()
    api.verify()
    current = api.head()
    intent_file = out / "publication.json"
    if intent_file.exists():
        intent = load(intent_file)
        need(intent.get("context") == ctx and intent.get("file_digests") == {k: digest(v) for k, v in files.items()}, "non-exact replay")
        if current == intent.get("commit_sha"):
            intent["status"] = "published"
            save(intent_file, intent)
            return intent
        raise SyncError("unconfirmed prior intent; do not repeat writes")
    need(current == state["expected_head"], "CAS conflict since prepare")
    previous_files = state["previous_files"]
    if current:
        need(tree_files(api.tree(current)) == previous_files, "prepared tree mismatch")
    need(not (set(files) & {k for k in previous_files if k.startswith("captures/")}), "immutable capture exists")
    tree_map = dict(previous_files)
    for name, data in files.items():
        need(allowed_path(name), "forbidden output")
        doc = api.call("POST", "/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        tree_map[name] = sha(doc["sha"])
    need(set(previous_files) <= set(tree_map), "tree deletion")
    tree = [{"path": name, "mode": "100644", "type": "blob", "sha": value} for name, value in sorted(tree_map.items())]
    need(len(tree) <= MAX_FILES and all(allowed_path(r["path"]) for r in tree), "tree allowlist/cap")
    # No base_tree: first commit is an orphan, never a copy of main.
    tree_sha = sha(api.call("POST", "/git/trees", {"tree": tree})["sha"])
    commit_sha = sha(api.call("POST", "/git/commits", {"message": "Owned real knowledge capture " + ctx["run_id"] + "-1", "tree": tree_sha, "parents": [current] if current else []})["sha"])
    intent = {"schema_version": 1, "context": ctx, "expected_head": current, "commit_sha": commit_sha,
              "file_digests": {k: digest(v) for k, v in files.items()}, "status": "pending"}
    save(intent_file, intent)
    need(api.head() == current, "CAS conflict before ref update")
    try:
        if current:
            api.call("PATCH", "/git/refs/heads/" + BRANCH, {"sha": commit_sha, "force": False})
        else:
            api.call("POST", "/git/refs", {"ref": "refs/heads/" + BRANCH, "sha": commit_sha})
    except Exception as exc:
        try:
            observed = api.head()
        except Exception:
            raise SyncError("unknown ref outcome; no retry") from exc
        need(observed == commit_sha, "ref update failed/unknown; no retry")
    need(api.head() == commit_sha, "ref update not confirmed")
    intent["status"] = "published"
    save(intent_file, intent)
    return intent


def assert_complete(out):
    out = Path(out)
    capture = load(out / "real_sources.json")
    latest = load(out / "latest.json")
    publication = load(out / "publication.json")
    need(publication.get("status") == "published", "publication unconfirmed")
    need(latest.get("capture_sha256") == digest(encode(capture)), "capture mismatch")
    need(capture.get("status") == "complete" and latest.get("status") == "complete", "required collection partial/failed")
    need(set(capture.get("sources", {})) == {"arxiv", "google"}, "missing required source")
    need(all(v.get("status") == "complete" and not v.get("errors") for v in capture["sources"].values()), "required source incomplete")
    return {"status": "complete", "commit_sha": publication["commit_sha"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("prepare", "collect", "publish", "assert-complete"):
        command = sub.add_parser(mode)
        command.add_argument("--out", required=True, type=Path)
        if mode != "assert-complete":
            command.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = assert_complete(args.out) if args.mode == "assert-complete" else globals()[args.mode](args.root, args.out)
        print(json.dumps({"mode": args.mode, "status": result.get("status", "prepared"), "out": str(args.out)}, sort_keys=True))
        return 0
    except Exception as exc:
        # No exception message: adapters might include credential-bearing request data.
        print(json.dumps({"mode": args.mode, "status": "failed", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
