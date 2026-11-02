#!/usr/bin/env python3
"""Read-only GitHub feedback loop report for Jarvis/Luna."""
from __future__ import annotations
import json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "coarfamily-cyber/jarvis-luna"
REPO_ID = "1431541717"
API = "https://api.github.com"
MAX_PRS = 30
MAX_PAGES = 5
WINDOW_DAYS = 7

def parse_time(value):
    if not isinstance(value, str): return None
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None
    if parsed.tzinfo is None: return None
    return parsed.astimezone(timezone.utc)

def request_json(path, token):
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "jarvis-luna-feedback-report"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("github_read_failed:" + type(exc).__name__) from None

def recent_pull_requests(token, cutoff):
    found = []
    for page in range(1, MAX_PAGES + 1):
        query = urllib.parse.urlencode({"state":"all","sort":"updated","direction":"desc","per_page":100,"page":page})
        rows = request_json(f"/repos/{REPO}/pulls?{query}", token)
        if not isinstance(rows, list): raise RuntimeError("pull_request_response_invalid")
        if not rows: break
        stop = False
        for pr in rows:
            updated = parse_time(pr.get("updated_at"))
            if updated is None: continue
            if updated < cutoff: stop = True; continue
            found.append(pr)
            if len(found) >= MAX_PRS: return found
        if stop: break
    return found

def build_summary(pull_requests, reviews_by_pr, comments_by_pr, events_by_pr, *, now):
    cutoff = now - timedelta(days=WINDOW_DAYS)
    totals = {k:0 for k in ("pull_requests_reviewed","merged","closed_unmerged","reviews_approved",
        "reviews_changes_requested","reviews_commented","review_comments","review_comment_thumbs_up",
        "review_comment_thumbs_down","label_added_events","label_removed_events")}
    rows = []
    for pr in pull_requests:
        number = pr.get("number"); updated = parse_time(pr.get("updated_at"))
        if not isinstance(number,int) or updated is None or updated < cutoff: continue
        totals["pull_requests_reviewed"] += 1
        merged = pr.get("merged") is True or pr.get("merged_at") is not None
        if merged: totals["merged"] += 1
        elif pr.get("state") == "closed": totals["closed_unmerged"] += 1
        states = {"APPROVED":0,"CHANGES_REQUESTED":0,"COMMENTED":0}
        for review in reviews_by_pr.get(number,[]):
            submitted = parse_time(review.get("submitted_at")); state = review.get("state")
            if submitted and submitted >= cutoff and state in states: states[state] += 1
        ups = downs = comment_count = 0
        for comment in comments_by_pr.get(number,[]):
            created = parse_time(comment.get("created_at"))
            if not created or created < cutoff: continue
            comment_count += 1; reactions = comment.get("reactions") or {}
            ups += int(reactions.get("+1",0) or 0); downs += int(reactions.get("-1",0) or 0)
        added = removed = 0
        for event in events_by_pr.get(number,[]):
            created = parse_time(event.get("created_at"))
            if not created or created < cutoff: continue
            if event.get("event") == "labeled": added += 1
            elif event.get("event") == "unlabeled": removed += 1
        totals["reviews_approved"] += states["APPROVED"]
        totals["reviews_changes_requested"] += states["CHANGES_REQUESTED"]
        totals["reviews_commented"] += states["COMMENTED"]
        totals["review_comments"] += comment_count
        totals["review_comment_thumbs_up"] += ups; totals["review_comment_thumbs_down"] += downs
        totals["label_added_events"] += added; totals["label_removed_events"] += removed
        rows.append({"number":number,"merged":merged,"state":pr.get("state"),"review_states":states,
            "review_comments":comment_count,"comment_thumbs_up":ups,"comment_thumbs_down":downs,
            "labels_added":added,"labels_removed":removed})
    up=totals["review_comment_thumbs_up"]; down=totals["review_comment_thumbs_down"]
    recommendations=[]
    if totals["pull_requests_reviewed"] == 0:
        recommendations.append("표본 없음: 피드백 신호가 쌓일 때까지 개선안을 만들지 않습니다.")
    if down > up:
        recommendations.append("부정 반응이 긍정 반응보다 많음: 해당 리뷰 유형의 지침을 사람이 먼저 재검토하세요.")
    if totals["reviews_changes_requested"] > totals["reviews_approved"]:
        recommendations.append("변경 요청 리뷰가 승인 리뷰보다 많음: 반복 지적 항목을 테스트 기준 후보로 제안하세요.")
    if totals["closed_unmerged"] > totals["merged"]:
        recommendations.append("미병합 종료 PR이 병합 PR보다 많음: 실패 원인을 확인한 뒤 지침 변경을 검토하세요.")
    if not recommendations:
        recommendations.append("현재 집계만으로는 지침 변경 근거가 부족합니다. 변경 없이 추세를 관찰하세요.")
    return {"schema_version":1,"generated_at":now.isoformat(),"window_days":WINDOW_DAYS,
        "source":"GitHub REST API aggregate metadata only",
        "privacy":"Comment text is ignored and never stored or printed; only aggregate reaction counts are retained. No diffs, secrets, customer data, or Shopify data are retained.",
        "authority":{"mode":"read_only_proposal","prompt_changes_allowed":False,"workflow_changes_allowed":False,
            "merge_allowed":False,"shopify_write_allowed":False,"human_approval_required":True,"independent_tests_required":True},
        "totals":totals,"pull_requests":rows,"recommendations":recommendations,
        "limitations":["A merge is an outcome signal, not proof that every review comment was correct.",
            "Thumbs-up/down reactions are sparse and may be biased by who reacts.",
            "Label events are counted, not interpreted as quality labels.",
            "The report samples at most 30 recent PRs and the first 100 events/comments/reviews per PR.",
            "This report does not infer business performance or autonomously rewrite agent prompts."]}

def main():
    if (os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("GITHUB_REPOSITORY")!=REPO
        or os.environ.get("GITHUB_REPOSITORY_ID")!=REPO_ID or os.environ.get("GITHUB_REF")!="refs/heads/main"
        or os.environ.get("GITHUB_RUN_ATTEMPT")!="1"):
        raise RuntimeError("execution_context_invalid")
    token=os.environ.get("GH_TOKEN")
    if not token: raise RuntimeError("github_token_missing")
    now=datetime.now(timezone.utc); prs=recent_pull_requests(token,now-timedelta(days=WINDOW_DAYS))
    reviews={}; comments={}; events={}
    for pr in prs:
        n=pr["number"]
        reviews[n]=request_json(f"/repos/{REPO}/pulls/{n}/reviews?per_page=100",token)
        comments[n]=request_json(f"/repos/{REPO}/pulls/{n}/comments?per_page=100",token)
        events[n]=request_json(f"/repos/{REPO}/issues/{n}/events?per_page=100",token)
        if not all(isinstance(x,list) for x in (reviews[n],comments[n],events[n])):
            raise RuntimeError("github_feedback_response_invalid")
    result=build_summary(prs,reviews,comments,events,now=now)
    out=Path(os.environ.get("RUNNER_TEMP","."))/f"jarvis-feedback-{os.environ.get('GITHUB_RUN_ID','local')}"
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    (out/"feedback_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    t=result["totals"]
    lines=["# Jarvis/Luna GitHub feedback loop",f"- 기간: 최근 {WINDOW_DAYS}일",
        f"- PR: {t['pull_requests_reviewed']}건 / 병합 {t['merged']}건",
        f"- 리뷰 승인 {t['reviews_approved']}건 / 변경 요청 {t['reviews_changes_requested']}건",
        f"- 리뷰 댓글 👍 {t['review_comment_thumbs_up']} / 👎 {t['review_comment_thumbs_down']}",
        f"- 라벨 추가 {t['label_added_events']}건 / 제거 {t['label_removed_events']}건","","## 개선 후보 (자동 적용하지 않음)"]
    lines += ["- "+x for x in result["recommendations"]]
    lines += ["","## 권한 경계","- 읽기 전용 집계만 수행합니다.","- 프롬프트·워크플로·Shopify 설정은 변경하지 않습니다.",
        "- 실제 변경은 사람 승인과 독립 테스트를 모두 통과해야 합니다."]
    md="\n".join(lines)+"\n"; (out/"feedback_summary.md").write_text(md,encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f: f.write(md)
    print(json.dumps({"status":"ok","output":str(out),"totals":t},ensure_ascii=False))
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        msg=str(exc); print("feedback_report_failed:"+(msg[:100] if msg.isascii() else "redacted"),file=sys.stderr)
        raise SystemExit(1)
