"""Review overlay consumers and writers never replace imported bytes."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import build_team_feeds as builder
import build_market_team as market
import refresh_briefing_feeds_offline as refresher
import team_briefing_overlay as views

ROOT = Path(__file__).resolve().parent.parent


class ReviewOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-overlay-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (views.BRIEFINGS, views.OVERLAY, views.FEEDS, views.REVIEW_FEEDS):
            target = self.root / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def test_read_views_and_preserve_base(self):
        before = {name:(self.root/name).read_bytes() for name in (views.BRIEFINGS, views.FEEDS)}
        self.assertEqual(len(views.load_team_briefings(self.root)['items']),25)
        feed = views.load_team_feeds(self.root)
        self.assertEqual(sum(map(len,feed['teams'].values())),751)
        for name, raw in before.items(): self.assertEqual((self.root/name).read_bytes(),raw)

    def test_duplicate_overlay_or_changed_base_fails(self):
        path = self.root / views.OVERLAY; doc=json.loads(path.read_text())
        doc['items'].append(deepcopy(doc['items'][0]));path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError,'duplicate'):views.load_team_briefings(self.root)
        shutil.copyfile(ROOT / views.OVERLAY,path)
        path=self.root/views.BRIEFINGS;path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'base changed'):views.load_team_briefings(self.root)

    def test_missing_stale_or_claimed_approval_feed_fails(self):
        path=self.root/views.REVIEW_FEEDS
        original=path.read_bytes()
        doc=json.loads(original);doc['teams']['knowledge'][-1]['business_approval']=True
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError,'offline refresh'):views.load_team_feeds(self.root)
        path.write_bytes(original);path.unlink()
        with self.assertRaises(ValueError):views.load_team_feeds(self.root)

    def test_refresh_cli_is_byte_idempotent_and_writes_review_only(self):
        before={name:(self.root/name).read_bytes() for name in (views.BRIEFINGS, views.FEEDS, views.OVERLAY, views.REVIEW_FEEDS)}
        with patch.object(refresher,'__file__',str(self.root/'scripts/refresh_briefing_feeds_offline.py')):
            refresher.main();refresher.main()
        for name,raw in before.items():self.assertEqual((self.root/name).read_bytes(),raw)

    def test_legacy_fixture_without_overlay_keeps_old_shape(self):
        (self.root/views.OVERLAY).unlink()
        self.assertEqual(views.load_team_briefings(self.root),json.loads((self.root/views.BRIEFINGS).read_text()))
        self.assertEqual(views.load_team_feeds(self.root),json.loads((self.root/views.FEEDS).read_text()))

    def test_market_consumer_sees_new_owner_review_assignments(self):
        with patch.object(market,'D',self.root/'data'),patch.object(market,'marketing_videos',return_value=[]):
            board=market.build_marketing_playbook()
        titles={row['title'] for row in board['적용_브리핑']}
        additions=json.loads((self.root/views.OVERLAY).read_text())['items']
        self.assertTrue({row['title'] for row in additions if 'market' in row['teams']} <= titles)

    def test_full_builder_default_is_unconsumed_review_candidate(self):
        self.assertEqual(builder.OUT,ROOT/'review/candidates/team_feeds.json')
        self.assertNotEqual(builder.OUT,ROOT/views.FEEDS)
        self.assertNotEqual(builder.OUT,ROOT/views.REVIEW_FEEDS)


if __name__=='__main__':unittest.main()
