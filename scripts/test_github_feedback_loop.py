import unittest
from datetime import datetime, timezone
from github_feedback_loop import build_summary

class FeedbackLoopTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,2,tzinfo=timezone.utc)
        self.prs=[{"number":1,"updated_at":"2026-11-01T00:00:00Z","merged_at":"2026-11-01T01:00:00Z","state":"closed"},
                  {"number":2,"updated_at":"2026-10-31T00:00:00Z","merged_at":None,"state":"closed"}]
        self.reviews={1:[{"submitted_at":"2026-11-01T00:00:00Z","state":"APPROVED"}],
                      2:[{"submitted_at":"2026-11-01T00:00:00Z","state":"CHANGES_REQUESTED"}]}
        self.comments={1:[{"created_at":"2026-11-01T00:00:00Z","reactions":{"+1":2,"-1":0}}],
                       2:[{"created_at":"2026-11-01T00:00:00Z","reactions":{"+1":0,"-1":1}}]}
        self.events={1:[{"created_at":"2026-11-01T00:00:00Z","event":"labeled"}],
                     2:[{"created_at":"2026-11-01T00:00:00Z","event":"unlabeled"}]}
    def test_aggregate_and_authority(self):
        r=build_summary(self.prs,self.reviews,self.comments,self.events,now=self.now)
        self.assertEqual(r["totals"]["merged"],1)
        self.assertEqual(r["totals"]["closed_unmerged"],1)
        self.assertEqual(r["totals"]["reviews_approved"],1)
        self.assertEqual(r["totals"]["reviews_changes_requested"],1)
        self.assertEqual(r["totals"]["review_comment_thumbs_up"],2)
        self.assertEqual(r["totals"]["review_comment_thumbs_down"],1)
        self.assertEqual(r["totals"]["label_added_events"],1)
        self.assertFalse(r["authority"]["prompt_changes_allowed"])
        self.assertFalse(r["authority"]["shopify_write_allowed"])
        self.assertTrue(r["authority"]["human_approval_required"])
        self.assertTrue(r["authority"]["independent_tests_required"])
    def test_old_pr_excluded(self):
        old=[{"number":3,"updated_at":"2026-10-20T00:00:00Z","merged":False,"state":"closed"}]
        r=build_summary(old,{}, {}, {},now=self.now)
        self.assertEqual(r["totals"]["pull_requests_reviewed"],0)
        self.assertIn("표본 없음",r["recommendations"][0])
    def test_empty_reactions_are_zero(self):
        c={1:[{"created_at":"2026-11-01T00:00:00Z","reactions":{}}]}
        r=build_summary(self.prs[:1],self.reviews,c,{},now=self.now)
        self.assertEqual(r["totals"]["review_comment_thumbs_up"],0)
        self.assertEqual(r["totals"]["review_comment_thumbs_down"],0)

if __name__=="__main__": unittest.main()
