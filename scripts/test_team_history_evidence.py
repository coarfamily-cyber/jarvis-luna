"""팀 자기개선 git 이력 근거 테스트 (2026-10-17)."""
import sys
import tempfile
import subprocess
import os
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import team_history_evidence as th  # noqa: E402


def pt(date, value, den=None, clock="2026-10-01T00:00:00+00:00", commit="c"):
    return {"date": date, "value": value, "denominator": den, "source_clock": clock, "commit": commit}


class VerdictTest(unittest.TestCase):
    def test_same_source_clock_is_not_refreshed_not_no_change(self):
        v = th.verdict("increase", pt("2026-10-17", 4), pt("2026-10-10", 4))
        self.assertEqual(v["verdict"], "source_not_refreshed")

    def test_direction_aware(self):
        self.assertEqual(th.verdict("increase", pt("b", 5, clock="2"), pt("a", 3, clock="1"))["verdict"], "improved")
        self.assertEqual(th.verdict("decrease", pt("b", 5, clock="2"), pt("a", 3, clock="1"))["verdict"], "worse")

    def test_changed_denominator_uses_ratio(self):
        # 실측: 가격팀 10/10 → 3/7 (대상 S 목록 축소). 개수가 아니라 비율로 판정한다.
        v = th.verdict("increase", pt("b", 3, 7, clock="2"), pt("a", 10, 10, clock="1"))
        self.assertTrue(v["denominator_changed"])
        self.assertEqual(v["verdict"], "worse")
        self.assertEqual(th.verdict("increase", pt("b", 7, 7, clock="2"), pt("a", 9, 10, clock="1"))["verdict"], "improved")

    def test_missing_denominator_is_not_comparable(self):
        v = th.verdict("increase", pt("b", 0, None, clock="2"), pt("a", 9, 9, clock="1"))
        self.assertEqual(v["verdict"], "not_comparable")

    def test_missing_history_is_reported(self):
        self.assertEqual(th.verdict("increase", pt("b", 1), None)["verdict"], "insufficient_history")


class ShallowGuardTest(unittest.TestCase):
    def test_shallow_clone_keeps_existing_file(self):
        with mock.patch.object(th, "git", side_effect=lambda *a: "true\n" if a[0] == "rev-parse" else
                               "2099-01-01T00:00:00+09:00\n"), \
                mock.patch.object(th, "build") as build:
            self.assertEqual(th.main(["--keep-if-shallow", "--output", "/nonexistent/x.json"]), 0)
        build.assert_not_called()


class OwnedRepositoryBindingTest(unittest.TestCase):
    def test_real_first_parent_selection_keeps_commit_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args, date=None):
                env = dict(os.environ)
                if date:
                    env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
                return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("config", "user.name", "Local regression fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "sample").write_text("old")
            git("add", "sample")
            git("commit", "-qm", "imported fixture", date="2026-10-23T01:00:00Z")
            old = git("rev-parse", "HEAD")
            (root / "sample").write_text("new")
            git("commit", "-qam", "owned fixture", date="2026-10-24T01:00:00Z")
            new = git("rev-parse", "HEAD")
            measured = {"ops": ("count", "items", "increase", 2, None,
                                "sample", "2026-10-23T01:00:00Z")}
            with mock.patch.object(th, "ROOT", root), \
                 mock.patch.object(th.tb, "measure_with", return_value=measured):
                doc = th.build(1, "HEAD", th.datetime(2026, 10, 24, 12, tzinfo=th.KST))
            points = doc["teams"]["ops"]["series"]
            self.assertEqual([p["commit"] for p in points], [old, new])
            self.assertTrue(all(p["commit_url"] ==
                "https://github.com/coarfamily-cyber/jarvis-luna/commit/" + p["commit"]
                for p in points))
            self.assertEqual(doc["teams"]["ops"]["vs_previous_day"]["verdict"],
                             "source_not_refreshed")

    def test_new_measurements_link_to_owned_repository(self):
        commit = "3b9c0dab12271ce33f457fba0673a0953e6d306e"
        measured = {"ops": ("count", "items", "increase", 2, None,
                            "data/ops.json", "2026-10-25T00:00:00Z")}
        with mock.patch.object(th, "commit_before", return_value=(commit, "2026-10-25T00:00:00Z")), \
             mock.patch.object(th, "git", return_value=commit), \
             mock.patch.object(th.tb, "measure_with", return_value=measured):
            doc = th.build(0, "HEAD", th.datetime(2026, 10, 25, 12, tzinfo=th.KST))
        point = doc["teams"]["ops"]["latest"]
        self.assertEqual(point["commit_url"],
                         "https://github.com/coarfamily-cyber/jarvis-luna/commit/" + commit)
        self.assertEqual(point["source_clock"], "2026-10-25T00:00:00Z")
        self.assertTrue(doc["not_business_verification"])


class RealHistoryTest(unittest.TestCase):
    def test_measures_with_same_rules_as_baselines(self):
        doc = th.build(1, "HEAD")
        self.assertEqual(doc["schema_version"], 1)
        for team in doc["teams"].values():
            for p in team["series"]:
                self.assertRegex(p["commit"], r"^[0-9a-f]{40}$")
                self.assertTrue(p["commit_url"].endswith(p["commit"]))


if __name__ == "__main__":
    unittest.main()
