"""Offline refresh retention, provenance and repository assignment checks."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from refresh_briefing_feeds_offline import refresh


class ScopedBriefingRefreshTests(unittest.TestCase):
    def test_retention_above_sixty_and_idempotence(self):
        old = [{'title': str(i), 'url': '', 'pool': 'news'} for i in range(60)]
        feed = {'teams': {'design': old}, 'generated_at': 'old-clock',
                'summary': {'design': {'total': 500}}, 'pool_size': 800}
        briefings = {'items': [{'id': 'new', 'title': 'Review', 'teams': ['design'],
                               'team_actions': {'design': 'Review only'}}]}
        original = deepcopy(feed)
        result = refresh(feed, briefings)
        self.assertEqual(result['teams']['design'][:60], old)
        self.assertEqual(len(result['teams']['design']), 61)
        for key in ('generated_at', 'summary', 'pool_size'):
            self.assertEqual(result[key], feed[key])
        self.assertEqual(feed, original)
        self.assertEqual(refresh(result, briefings), result)
        row = result['teams']['design'][-1]
        self.assertEqual(row['status'], 'generated_for_review_not_acknowledged')
        self.assertFalse(row['execution_verified']); self.assertFalse(row['business_approval'])

    def test_unknown_team_and_duplicate_source_fail_without_mutation(self):
        feed = {'teams': {'design': []}}
        for items in ([{'id': 'a', 'title': 'x', 'teams': ['unknown']}],
                      [{'id': 'a', 'title': 'x', 'teams': ['design']}] * 2):
            with self.assertRaises(ValueError): refresh(feed, {'items': items})
        self.assertEqual(feed, {'teams': {'design': []}})

    def test_repository_assignments_and_idempotence(self):
        root = Path(__file__).resolve().parent.parent
        feed = json.loads((root / 'data/team_feeds.json').read_text())
        briefings = json.loads((root / 'data/manual/team_briefings.json').read_text())
        self.assertEqual(refresh(feed, briefings), feed)
        for source in briefings['items']:
            for team in source['teams']:
                matching = [r for r in feed['teams'][team] if r.get('briefing_id') == source['id']
                            or (r.get('pool') == 'team_briefing' and r.get('title') == source['title']
                                and r.get('url', '') == source.get('source_url', ''))]
                self.assertEqual(len(matching), 1, (source['id'], team))


if __name__ == '__main__':
    unittest.main()
