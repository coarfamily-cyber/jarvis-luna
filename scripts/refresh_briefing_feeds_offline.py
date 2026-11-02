"""Explicit local briefing-only refresh; never calls build_team_feeds.main()."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from build_team_feeds import briefing_rows, team_feed_row
from team_briefing_overlay import load_team_briefings, REVIEW_FEEDS


def refresh(feed, briefings):
    """Append missing assignments, preserving every old row and global metadata."""
    result = deepcopy(feed)
    teams = result['teams']
    rows = briefing_rows(briefings)  # validates duplicate source IDs first
    for source in rows:
        for team in source['teams']:
            if team not in teams or not isinstance(teams[team], list):
                raise ValueError('unknown briefing team')
            existing = teams[team]
            if any((r.get('briefing_id') == source.get('briefing_id')
                    if source.get('briefing_id') and r.get('briefing_id') else
                    r.get('pool') == 'team_briefing' and r.get('title') == source['title']
                    and r.get('url', '') == source['url']) for r in existing):
                continue
            existing.append(team_feed_row(source, team))
    canonical = json.dumps(briefings, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    result['briefing_refresh'] = {
        'generator': 'scripts/refresh_briefing_feeds_offline.py',
        'scope': 'local_manual_briefing_assignments_only',
        'source_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
        'source_items': len(rows),
        'retention': 'all_previous_rows_preserved_no_60_item_truncation',
        'aggregate_metadata_scope': 'unchanged_last_full_build_excludes_this_scoped_refresh',
        'stored_rows_by_team': {t: len(r) for t, r in teams.items()},
        'status': 'generated_for_review_not_acknowledged',
        'execution_verified': False, 'business_approval': False,
    }
    return result


def main():
    root = Path(__file__).resolve().parent.parent
    target = root / REVIEW_FEEDS
    result = refresh(json.loads((root / 'data/team_feeds.json').read_text(encoding='utf-8')),
                     load_team_briefings(root))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
