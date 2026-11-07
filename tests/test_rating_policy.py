import copy
import json
import unittest
from datetime import datetime, timedelta

from scripts import rating_policy as policy


NOW = datetime(2026, 11, 8, 9, tzinfo=policy.CST)
FIRST_QUALIFIED = "2026-04-10T09:00:00+08:00"
CONFIG = {
    "min_rating": 8.0,
    "min_rating_count": 3000,
    "douban_collection_urls": ["https://m.douban.com/subject_collection/first",
                               "https://m.douban.com/subject_collection/second"],
    "rating_recheck_daily_limit": 20,
    "rating_recheck_interval_seconds": 3,
    "rating_recheck_max_retries": 3,
    "rating_recheck_retry_delay_hours": 24,
}


def legacy_entry(douban_id="100", rating=8.5):
    return {"douban_id": douban_id, "title": "A", "qualified": True,
            "qualified_at": FIRST_QUALIFIED, "last_rating": rating,
            "last_rating_count": 4000, "last_checked_at": FIRST_QUALIFIED}


def snapshots(first=("100",), second=("200",)):
    return {"first": {"success": True, "ids": list(first)},
            "second": {"success": True, "ids": list(second)}}


def baseline():
    library = {"items": {"100": legacy_entry()}}
    policy.migrate_library(library, {}, CONFIG, NOW)
    policy.update_memberships(library, snapshots(), CONFIG, NOW,
                              {"100": {"rating": 8.5, "count": 4000}})
    return library


class RatingPolicyTests(unittest.TestCase):
    def test_migration_evidence_and_missing_dates_are_preserved(self):
        library = {"items": {
            "100": legacy_entry(), "101": legacy_entry("101", 7.9),
            "102": legacy_entry("102", None),
            "103": {"douban_id": "103", "last_rating": 9.0, "qualified": False},
            "104": {"douban_id": "104", "last_rating": 8.0, "qualified": True},
            "105": {"douban_id": "105", "last_rating": None, "qualified": False},
            "106": {"douban_id": "106", "last_rating": 0, "qualified": True},
            "tmdb:1": {"qualified": True, "last_rating": 8.8},
        }}
        state = {"items": {"105": {"first_qualified_at": FIRST_QUALIFIED}}}
        policy.migrate_library(library, state, CONFIG, NOW)
        self.assertTrue(library["items"]["100"]["display_eligible"])
        self.assertFalse(library["items"]["101"]["display_eligible"])
        self.assertTrue(library["items"]["102"]["display_eligible"])
        self.assertFalse(library["items"]["103"]["display_eligible"])
        self.assertIsNone(library["items"]["104"]["qualified_at"])
        self.assertEqual(library["items"]["105"]["qualified_at"], FIRST_QUALIFIED)
        self.assertTrue(library["items"]["106"]["display_eligible"])
        self.assertTrue(library["items"]["tmdb:1"]["display_eligible"])
        self.assertNotIn("tmdb:1", library["rating_rechecks"])
        self.assertNotIn("103", library["rating_rechecks"])
        previous = copy.deepcopy(library)
        policy.migrate_library(library, state, CONFIG, NOW + timedelta(days=1))
        self.assertEqual(library, previous)

    def test_migration_recovers_valid_state_rating_after_legacy_overwrite(self):
        library = {"items": {"100": legacy_entry(rating=None)}}
        state = {"items": {"100": {"last_rating": 8.0, "last_rating_count": 5000,
                                    "last_seen_at": FIRST_QUALIFIED}}}
        policy.migrate_library(library, state, CONFIG, NOW)
        self.assertEqual(library["items"]["100"]["last_rating"], 8.0)
        self.assertEqual(library["items"]["100"]["last_valid_rating_at"], FIRST_QUALIFIED)

    def test_duplicate_id_aliases_share_evidence_and_latest_valid_score(self):
        library = {"items": {
            "100": {"douban_id": "100", "qualified": False, "last_rating": None, "title": "A"},
            "douban:100": {**legacy_entry(), "last_rating": 7.9,
                           "last_checked_at": "2026-11-07T09:00:00+08:00"},
            "douban:101": legacy_entry("101"),
        }}
        policy.migrate_library(library, {}, CONFIG, NOW)
        self.assertEqual(set(library["items"]), {"100", "douban:100", "101", "douban:101"})
        for key in ("100", "douban:100"):
            self.assertTrue(library["items"][key]["ever_qualified"])
            self.assertEqual(library["items"][key]["qualified_at"], FIRST_QUALIFIED)
            self.assertEqual(library["items"][key]["last_rating"], 7.9)
            self.assertFalse(library["items"][key]["display_eligible"])
        self.assertEqual(len(library["rating_rechecks"]), 2)

    def test_one_departure_task_and_any_list_prevents_departure(self):
        library = baseline()
        policy.update_memberships(library, snapshots(("200",), ("100",)), CONFIG, NOW, {})
        self.assertEqual(library["items"]["100"]["membership_status"], "on_list")
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "completed")
        policy.update_memberships(library, snapshots(("200",), ("300",)), CONFIG, NOW, {})
        task = copy.deepcopy(library["rating_rechecks"]["100"])
        self.assertEqual(task["reason"], "off_list")
        self.assertEqual(task["status"], "pending")
        policy.update_memberships(library, snapshots(("200",), ("300",)), CONFIG, NOW + timedelta(days=1), {})
        self.assertEqual(library["rating_rechecks"]["100"], task)
        self.assertEqual(len(library["rating_rechecks"]), 1)

    def test_failure_and_anomalous_empty_snapshot_keep_memberships(self):
        library = baseline()
        policy.update_memberships(library, {"first": {"success": False, "ids": []},
                                           "second": {"success": True, "ids": []}}, CONFIG, NOW, {})
        self.assertEqual(library["items"]["100"]["known_collections"], ["first"])
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "completed")

    def test_reentry_cancels_failed_departure_and_next_departure_has_new_retries(self):
        library = baseline()
        gone = snapshots(("200",), ("300",))
        policy.update_memberships(library, gone, CONFIG, NOW, {})
        task = library["rating_rechecks"]["100"]
        task["failures"] = 3
        task["next_retry_at"] = (NOW + timedelta(days=1)).isoformat()
        policy.update_memberships(library, snapshots(), CONFIG, NOW, {})
        self.assertEqual(task["status"], "cancelled")
        policy.update_memberships(library, gone, CONFIG, NOW + timedelta(hours=1), {})
        new_task = library["rating_rechecks"]["100"]
        self.assertEqual(new_task["status"], "pending")
        self.assertEqual(new_task["failures"], 0)
        self.assertIsNone(new_task["next_retry_at"])

    def test_new_failed_collection_defers_departure_until_known(self):
        library = baseline()
        config = {**CONFIG, "douban_collection_urls": CONFIG["douban_collection_urls"] + ["third"]}
        changed = snapshots(("200",), ("300",))
        changed["third"] = {"success": False, "ids": []}
        policy.update_memberships(library, changed, config, NOW, {})
        self.assertEqual(library["items"]["100"]["membership_status"], "unknown")
        self.assertTrue(library["items"]["100"]["departure_pending"])
        changed["third"] = {"success": True, "ids": ["400"]}
        policy.update_memberships(library, changed, config, NOW, {})
        self.assertEqual(library["rating_rechecks"]["100"]["reason"], "off_list")

    def test_valid_boundaries_missing_counts_and_recovery_date(self):
        entry = {"ever_qualified": False, "display_eligible": False}
        policy.apply_rating(entry, 8.0, 3000, CONFIG, NOW)
        self.assertFalse(entry["display_eligible"])
        policy.apply_rating(entry, 8.0, 3001, CONFIG, NOW)
        self.assertTrue(entry["display_eligible"])
        first = entry["qualified_at"]
        policy.apply_rating(entry, 8.0, None, CONFIG, NOW)
        self.assertTrue(entry["display_eligible"])
        policy.apply_rating(entry, 7.9, None, CONFIG, NOW)
        self.assertFalse(entry["display_eligible"])
        policy.apply_rating(entry, 8.1, None, CONFIG, NOW)
        self.assertFalse(entry["display_eligible"])
        policy.apply_rating(entry, 8.0, 3001, CONFIG, NOW + timedelta(days=1))
        self.assertTrue(entry["display_eligible"])
        self.assertEqual(entry["qualified_at"], first)
        self.assertEqual(entry["last_rating_count"], 3001)
        missing_date = {"ever_qualified": True, "display_eligible": False, "qualified_at": None}
        policy.apply_rating(missing_date, 8.0, 4000, CONFIG, NOW)
        self.assertIsNone(missing_date["qualified_at"])

    def test_invalid_observations_do_not_overwrite_valid_rating(self):
        for invalid in (None, "", 0, -1, 11, float("nan"), float("inf"), True):
            with self.subTest(invalid=invalid):
                entry = {**legacy_entry(), "ever_qualified": True, "display_eligible": True}
                policy.apply_rating(entry, invalid, None, CONFIG, NOW)
                self.assertEqual(entry["last_rating"], 8.5)
                self.assertEqual(entry["last_rating_count"], 4000)
                self.assertTrue(entry["display_eligible"])

    def test_fresh_rating_reused_and_continued_absence_not_requeued(self):
        library = baseline()
        gone = snapshots(("200",), ("300",))
        policy.update_memberships(library, gone, CONFIG, NOW, {"100": {"rating": 8.0, "count": None}})
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "completed")
        self.assertTrue(library["items"]["100"]["off_list_verified"])
        executed = policy.process_recheck_queue(library, CONFIG, NOW,
            lambda *_: self.fail("a fresh valid rating must be reused"), lambda: None)
        self.assertEqual(executed, 0)
        policy.update_memberships(library, gone, CONFIG, NOW + timedelta(days=1), {})
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "completed")
        policy.update_memberships(library, snapshots(), CONFIG, NOW + timedelta(days=2), {})
        self.assertFalse(library["items"]["100"]["off_list_verified"])
        policy.update_memberships(library, gone, CONFIG, NOW + timedelta(days=3), {})
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "pending")

    def test_missing_rating_on_list_keeps_task_waiting_for_regular_fetch(self):
        library = {"items": {"100": legacy_entry(rating=None)}}
        policy.migrate_library(library, {}, CONFIG, NOW)
        policy.update_memberships(library, snapshots(), CONFIG, NOW, {})
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "pending")
        self.assertEqual(policy.process_recheck_queue(library, CONFIG, NOW,
            lambda *_: self.fail("do not repeat an on-list fetch"), lambda: None), 0)
        policy.update_memberships(library, snapshots(), CONFIG, NOW,
                                  {"100": {"rating": 8.0, "count": 4000}})
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "completed")

    def test_large_migration_budget_survives_restarts_and_natural_day(self):
        library = {"items": {str(i): legacy_entry(str(i)) for i in range(100, 150)}}
        policy.migrate_library(library, {}, CONFIG, NOW)
        config = {**CONFIG, "rating_recheck_interval_seconds": 0}
        saved = []
        calls = []
        def fetch(douban_id, entry):
            calls.append(douban_id)
            self.assertEqual(saved[-1]["rating_recheck_budget"]["used"], len(calls))
            return {"rating": 8.0, "count": None}
        count = policy.process_recheck_queue(library, config, NOW, fetch,
                                             lambda: saved.append(copy.deepcopy(library)), clock=lambda: NOW)
        self.assertEqual(count, 20)
        self.assertEqual(len(calls), 20)
        restarted = json.loads(json.dumps(library))
        self.assertEqual(policy.process_recheck_queue(restarted, config, NOW,
            lambda *_: self.fail("same-day budget reset"), lambda: None, clock=lambda: NOW), 0)
        tomorrow_utc = datetime(2026, 11, 8, 16, tzinfo=policy.timezone.utc)
        self.assertEqual(policy.process_recheck_queue(restarted, config, tomorrow_utc,
            lambda *_: {"rating": 8.1, "count": 5000}, lambda: None, clock=lambda: tomorrow_utc), 20)
        self.assertEqual(restarted["rating_recheck_budget"]["date"], "2026-11-09")

    def test_failure_missing_rating_delayed_and_retries_pause(self):
        library = {"items": {"100": legacy_entry()}}
        policy.migrate_library(library, {}, CONFIG, NOW)
        config = {**CONFIG, "rating_recheck_interval_seconds": 0}
        for attempt in range(4):
            stamp = NOW + timedelta(days=attempt)
            policy.process_recheck_queue(library, config, stamp, lambda *_: {"rating": None},
                                          lambda: None, clock=lambda: stamp)
            self.assertEqual(library["rating_rechecks"]["100"]["failures"], attempt + 1)
            self.assertEqual(library["items"]["100"]["last_rating"], 8.5)
            self.assertEqual(library["items"]["100"]["last_rating_count"], 4000)
            self.assertTrue(library["items"]["100"]["display_eligible"])
            self.assertEqual(policy.process_recheck_queue(library, config, stamp,
                lambda *_: self.fail("failure retried immediately"), lambda: None, clock=lambda: stamp), 0)
        self.assertEqual(library["rating_rechecks"]["100"]["status"], "paused")
        policy.migrate_library(library, {}, CONFIG, NOW + timedelta(days=5))
        policy.update_memberships(library, snapshots(("200",), ("300",)), CONFIG, NOW, {})
        stamp = NOW + timedelta(days=10)
        self.assertEqual(policy.process_recheck_queue(library, config, stamp,
            lambda *_: self.fail("paused task re-created"), lambda: None, clock=lambda: stamp), 0)

    def test_rate_limit_stops_batch_and_persists_cooldown(self):
        library = {"items": {str(i): legacy_entry(str(i)) for i in range(100, 103)}}
        policy.migrate_library(library, {}, CONFIG, NOW)
        saved = []
        def blocked(*_):
            raise policy.RateLimited("429", retry_after_seconds=172800)
        self.assertEqual(policy.process_recheck_queue(library, CONFIG, NOW, blocked,
            lambda: saved.append(copy.deepcopy(library)), clock=lambda: NOW), 1)
        self.assertEqual(library["rating_recheck_budget"]["used"], 1)
        self.assertEqual(library["rating_recheck_budget"]["cooldown_until"],
                         (NOW + timedelta(days=2)).isoformat())
        self.assertEqual(saved[-1], library)
        self.assertEqual(policy.process_recheck_queue(library, CONFIG, NOW + timedelta(hours=1),
            lambda *_: self.fail("cooldown ignored"), lambda: None,
            clock=lambda: NOW + timedelta(hours=1)), 0)

    def test_interval_covers_previous_process_and_crash_reservation(self):
        library = {"items": {"100": legacy_entry()}}
        policy.migrate_library(library, {}, CONFIG, NOW)
        library["rating_recheck_budget"] = {"date": NOW.date().isoformat(), "used": 1,
                                             "last_request_at": NOW.isoformat()}
        current = [NOW + timedelta(seconds=1)]
        slept = []
        def sleep(seconds):
            slept.append(seconds)
            current[0] += timedelta(seconds=seconds)
        class Crash(BaseException):
            pass
        saved = []
        with self.assertRaises(Crash):
            policy.process_recheck_queue(library, CONFIG, NOW,
                lambda *_: (_ for _ in ()).throw(Crash()),
                lambda: saved.append(copy.deepcopy(library)), sleep=sleep, clock=lambda: current[0])
        self.assertEqual(slept, [2])
        self.assertEqual(saved[-1]["rating_recheck_budget"]["used"], 2)
        restarted = saved[-1]
        self.assertEqual(policy.process_recheck_queue(restarted, CONFIG, current[0],
            lambda *_: self.fail("crash reservation discarded"), lambda: None,
            clock=lambda: current[0]), 0)

    def test_normal_priority_and_persistent_fairness_with_limit_one(self):
        library = {"items": {str(i): legacy_entry(str(i)) for i in range(100, 108)}}
        policy.migrate_library(library, {}, CONFIG, NOW)
        for douban_id in map(str, range(101, 108)):
            library["rating_rechecks"][douban_id]["reason"] = "off_list"
        calls = []
        config = {**CONFIG, "rating_recheck_daily_limit": 1, "rating_recheck_interval_seconds": 0}
        def fetch(douban_id, _):
            calls.append(douban_id)
            return {"rating": 8.0, "count": 4000}
        for day in range(6):
            stamp = NOW + timedelta(days=day)
            policy.process_recheck_queue(library, config, stamp, fetch, lambda: None, clock=lambda: stamp)
            library = json.loads(json.dumps(library))
        self.assertEqual(calls[:5], ["101", "102", "103", "104", "105"])
        self.assertEqual(calls[5], "100")


if __name__ == "__main__":
    unittest.main()
