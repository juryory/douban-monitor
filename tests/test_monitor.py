"""Offline integration tests: no Douban, TMDB, subprocess or Git execution."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import monitor as m

NOW = datetime.fromisoformat("2026-11-08T09:00:00+08:00")
OLD = "2024-01-02T09:00:00+08:00"


def historic(did="1", **changes):
    return {"key": did, "douban_id": did, "title": f"Work {did}", "category": "movie",
            "qualified_at": OLD, "first_discovered_at": OLD, "qualified": False,
            "watch_status": "archived", "last_rating": 8.3, "last_rating_count": 5000,
            "url": f"https://movie.douban.com/subject/{did}/", **changes}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.config = {**m.DEFAULT_CONFIG, "douban_collection_urls": ["subject_collection/a"],
                       "rating_recheck_daily_limit": 0, "auto_git_push": False}
        self.addCleanup(patch.stopall)
        patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden")).start()
        patch("subprocess.run", side_effect=AssertionError("Subprocess forbidden")).start()
        patch("time.sleep").start()

    def migrate(self, entries, state=None):
        library = {"items": copy.deepcopy(entries)}
        m.migrate_library(library, state or {}, self.config, NOW)
        return library

    def test_rating_boundary_and_existing_count_threshold(self):
        self.assertTrue(m.should_qualify(m.Candidate("A", "movie", "douban_weekly", rating=8.0, rating_count=3001), self.config))
        self.assertFalse(m.should_qualify(m.Candidate("A", "movie", "douban_weekly", rating=8.0, rating_count=3000), self.config))
        for value in (None, 0, float("nan"), float("inf"), -1, 11):
            self.assertFalse(m.should_qualify(m.Candidate("A", "movie", "douban_weekly", rating=value, rating_count=5000), self.config))

    def test_history_survives_only_new_candidate_and_archive(self):
        library = self.migrate({"1": historic()})
        candidates = [m.Candidate("B", "movie", "douban_weekly", douban_id="2", rating=8, rating_count=4000)]
        m.update_library(library, candidates, self.config, NOW)
        m.archive_expired_library_items(library, self.config, NOW)
        result = m.build_result_json(candidates, self.config, NOW, library)
        self.assertEqual([item["douban_id"] for item in result["qualified"]], ["1", "2"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["display_count"], 2)
        self.assertEqual(result["qualified"][0]["qualified_at"], OLD)

    def test_sparse_observation_keeps_valid_library_and_notification_data(self):
        library = self.migrate({"1": historic()})
        state = {"items": {"1": {"title": "Original", "category": "movie", "url": "old-url",
                 "last_rating": 8.3, "last_rating_count": 5000, "first_qualified_at": OLD}}}
        candidate = m.Candidate("douban-subject-1", "unknown", "douban_weekly", douban_id="1")
        m.update_library(library, [candidate], self.config, NOW)
        m.update_state(state, [candidate], self.config, NOW)
        for entry in (library["items"]["1"], state["items"]["1"]):
            self.assertEqual(entry["last_rating"], 8.3)
            self.assertEqual(entry["last_rating_count"], 5000)
            self.assertTrue(entry["url"])
            self.assertFalse(entry["title"].startswith("douban-subject-"))
        self.assertTrue(library["items"]["1"]["display_eligible"])

    def test_low_without_count_hides_then_qualified_recovery_preserves_date(self):
        library = self.migrate({"1": historic()})
        entry = library["items"]["1"]
        candidate = m.Candidate("A", "movie", "douban_weekly", douban_id="1", rating=7.9)
        m.update_library(library, [candidate], self.config, NOW)
        self.assertFalse(entry["display_eligible"])
        self.assertEqual(entry["last_rating_count"], 5000)
        candidate.rating = 8.0
        m.update_library(library, [candidate], self.config, NOW)
        self.assertFalse(entry["display_eligible"])
        candidate.rating_count = 4000
        m.update_library(library, [candidate], self.config, NOW)
        self.assertTrue(entry["display_eligible"])
        self.assertEqual(entry["qualified_at"], OLD)

    def test_observation_only_does_not_appear_even_with_high_score(self):
        library = self.migrate({"1": historic(qualified_at=None, qualified=False)})
        self.assertEqual(m.build_result_json([], self.config, NOW, library)["qualified"], [])

    def test_collection_requires_nonempty_complete_unique_membership(self):
        malformed = [
            {}, {"total": 0, "subject_collection_items": []},
            {"total": 3, "subject_collection_items": [{"id": "1", "title": "A"}]},
            {"total": 2, "subject_collection_items": [{"id": "1", "title": "A"}] * 2},
            {"total": 1, "subject_collection_items": [{"id": "1"}]},
            {"total": 1, "subject_collection_items": [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]},
        ]
        for payload in malformed:
            with self.subTest(payload=payload), patch.object(m, "rexxar_get", return_value=payload):
                candidates, snapshots = m.fetch_douban_weekly_candidates_lite(self.config)
                self.assertEqual(candidates, [])
                self.assertFalse(snapshots["a"]["success"])

    def test_collection_wrapped_subject_and_integer_year(self):
        payload = {"total": 1, "subject_collection_items": [{"subject": {
            "id": "1", "title": "A", "year": 2026, "rating": {"value": 8.0, "count": 4000}}}]}
        with patch.object(m, "rexxar_get", return_value=payload):
            candidates, snapshots = m.fetch_douban_weekly_candidates_lite(self.config)
        self.assertTrue(snapshots["a"]["success"])
        self.assertEqual(snapshots["a"]["ids"], ["1"])
        self.assertEqual(candidates[0].year, 2026)
        self.assertEqual(candidates[0].rating, 8.0)

    def test_pagination_partial_failure_invalidates_whole_snapshot(self):
        config = {**self.config, "douban_collection_max_items": {"a": 30}}
        payload = {"total": 30, "subject_collection_items": [{"id": str(i), "title": str(i)} for i in range(20)]}
        with patch.object(m, "rexxar_get", side_effect=[payload, OSError("page 2 failed")]):
            candidates, snapshots = m.fetch_douban_weekly_candidates_lite(config)
        self.assertEqual(candidates, [])
        self.assertFalse(snapshots["a"]["success"])

    def test_budgeted_fetch_never_falls_back_to_another_endpoint(self):
        with patch.object(m, "rexxar_get", side_effect=OSError("failed")) as fetch:
            with self.assertRaises(OSError):
                m.fetch_recheck_rating("1", {"category": "tv"}, self.config)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args, ("/tv/1",))

    def test_rate_limit_is_propagated_without_endpoint_fallback(self):
        with patch.object(m, "rexxar_get", side_effect=m.RateLimited("429")) as fetch:
            with self.assertRaises(m.RateLimited):
                m.fetch_douban_subject_detail_via_rexxar("1", self.config)
        self.assertEqual(fetch.call_count, 1)

    def test_http_limit_detection(self):
        error = urllib.error.HTTPError("https://example.test", 429, "limited", {}, None)
        self.addCleanup(error.close)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(m.RateLimited):
                m.rexxar_get("/movie/1")

    def test_validation_page_and_retry_after_are_rate_limits(self):
        response = Mock()
        response.read.return_value = b"<html>captcha required</html>"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(m.RateLimited):
                m.rexxar_get("/movie/1")
        error = urllib.error.HTTPError("https://example.test", 418, "blocked", {"Retry-After": "172800"}, None)
        self.addCleanup(error.close)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(m.RateLimited) as caught:
                m.rexxar_get("/movie/1")
        self.assertEqual(caught.exception.retry_after_seconds, 172800)

    def test_offline_rebuild_uses_no_network_or_git_and_preserves_scan_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "data").mkdir()
            m.save_json(root / "data/douban-monitor-library.json", {"items": {"1": historic()}})
            m.save_json(root / "data/douban-monitor-result.json", {"run_at": OLD, "total": 17, "qualified": []})
            with contextlib.redirect_stdout(io.StringIO()), patch.object(m, "now_cst", return_value=NOW):
                summary = m.offline_rebuild(root / "scripts", self.config)
                again = m.offline_rebuild(root / "scripts", self.config)
            result = m.load_json(root / "data/douban-monitor-result.json", {})
            self.assertEqual((result["run_at"], result["total"]), (OLD, 17))
            self.assertEqual(summary["after_display_count"], 1)
            self.assertEqual(summary["historical_pending_count"], again["historical_pending_count"])
            self.assertEqual(summary["extra_rating_requests"], 0)

    def test_all_collectors_fail_still_render_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            m.save_json(root / "data/douban-monitor-library.json", {"items": {"1": historic()}})
            with patch.object(m, "fetch_douban_weekly_candidates_lite", return_value=([], {"a": {"success": False}})), \
                 patch.object(m, "fetch_tmdb_hot_candidates_with_config", return_value=[]), \
                 patch.object(m, "now_cst", return_value=NOW), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                m.run(root / "scripts", self.config)
            result = m.load_json(root / "data/douban-monitor-result.json", {})
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["qualified"][0]["douban_id"], "1")

    def test_monitor_lock_excludes_parallel_rebuild_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with m.monitor_lock(root):
                with self.assertRaises(RuntimeError):
                    with m.monitor_lock(root):
                        self.fail("lock acquired twice")
            with m.monitor_lock(root):
                pass


if __name__ == "__main__":
    unittest.main()
