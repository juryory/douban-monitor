"""Regression cases found while reviewing history and retry integration."""
import copy
import unittest
from datetime import datetime, timedelta

from scripts import monitor
from scripts import rating_policy as policy


NOW = datetime(2026, 11, 8, 9, tzinfo=policy.CST)


class MonitorReviewTests(unittest.TestCase):
    def test_known_qualification_with_unknown_date_is_not_redated(self):
        state = {"items": {"100": {
            "douban_id": "100", "title": "A", "category": "movie",
            "qualified": True, "first_qualified_at": None,
            "last_rating": 8.5, "last_rating_count": 5000,
            "milestones_notified": [],
        }}}
        candidate = monitor.Candidate("A", "movie", "douban_movie_weekly",
                                      douban_id="100", rating=8.0, rating_count=5000)
        updated, first_hits, _ = monitor.update_state(
            state, [candidate], copy.deepcopy(monitor.DEFAULT_CONFIG), NOW)
        self.assertIsNone(updated["items"]["100"]["first_qualified_at"])
        self.assertEqual(first_hits, [])

    def test_retry_and_rate_limit_wait_from_response_completion(self):
        for error in (TimeoutError("timed out"), policy.RateLimited("429")):
            with self.subTest(error=type(error).__name__):
                library = {"items": {"100": {
                    "douban_id": "100", "qualified": True,
                    "qualified_at": "2026-04-10T09:00:00+08:00",
                    "last_rating": 8.5, "last_rating_count": 5000,
                }}}
                config = {**monitor.DEFAULT_CONFIG, "rating_recheck_interval_seconds": 0}
                policy.migrate_library(library, {}, config, NOW)
                clock = [NOW]

                def fetch(*_):
                    clock[0] += timedelta(minutes=5)
                    raise error

                count = policy.process_recheck_queue(
                    library, config, NOW, fetch, lambda: None, clock=lambda: clock[0])
                self.assertEqual(count, 1)
                retry = datetime.fromisoformat(library["rating_rechecks"]["100"]["next_retry_at"])
                self.assertGreaterEqual(retry, clock[0] + timedelta(hours=24))
                if isinstance(error, policy.RateLimited):
                    cooldown = datetime.fromisoformat(library["rating_recheck_budget"]["cooldown_until"])
                    self.assertGreaterEqual(cooldown, clock[0] + timedelta(hours=24))


if __name__ == "__main__":
    unittest.main()
