"""Persistent display policy and bounded rating rechecks (no network code).

The caller holds the monitor process lock for the entire read/update/write cycle.
``persist`` must durably save the library; reservations are saved before requests
so a crash can waste a budget slot but cannot give that slot back.
"""
from __future__ import annotations

import copy
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

CST = timezone(timedelta(hours=8))
MIGRATION_VERSION = 1


class RateLimited(Exception):
    """An explicit rate limit or anti-bot response; stop additional requests."""

    def __init__(self, message: str = "rate limited", retry_after_seconds: float = 0):
        super().__init__(message)
        self.retry_after_seconds = max(0, retry_after_seconds)


def valid_rating(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    # Douban uses zero for subjects that do not have a published score.
    return rating if math.isfinite(rating) and 0 < rating <= 10 else None


def valid_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        count = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(count) if math.isfinite(count) and count >= 0 and count.is_integer() else None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=CST) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _now(value: datetime) -> datetime:
    return value.replace(tzinfo=CST) if value.tzinfo is None else value.astimezone(CST)


def apply_rating(entry: dict[str, Any], rating: Any, count: Any,
                 config: dict[str, Any], now: datetime) -> bool:
    """Merge an observation without allowing missing data to hide a work.

    Admission/recovery requires a score and a count from this observation. A
    missing count still permits a valid low score to hide a previously admitted
    work. ``qualified_at`` records first admission, never recovery or migration.
    """
    rating, count = valid_rating(rating), valid_count(count)
    if count is not None:
        entry["last_rating_count"] = count
    if rating is None:
        return False
    entry["last_rating"] = rating
    entry["last_valid_rating_at"] = _now(now).isoformat()
    threshold = float(config.get("min_rating", 8.0))
    if rating < threshold:
        entry["qualified"] = False
        entry["display_eligible"] = False
        entry["hidden_reason"] = "rating_below_threshold" if entry.get("ever_qualified") else None
    elif count is not None:
        entry["qualified"] = count > int(config.get("min_rating_count", 3000))
        if entry["qualified"]:
            if not entry.get("ever_qualified"):
                entry["qualified_at"] = _now(now).isoformat()
            entry["ever_qualified"] = True
            entry["display_eligible"] = True
            entry["hidden_reason"] = None
    return True


def _enqueue(library: dict[str, Any], douban_id: str, reason: str, now: datetime,
             *, new_departure: bool = False) -> None:
    tasks = library.setdefault("rating_rechecks", {})
    previous = tasks.get(douban_id)
    if previous:
        if previous.get("status") == "pending" and not new_departure:
            if reason == "off_list":
                previous["reason"] = reason
            return
        # A paused task stays paused during the same absence. A real new cycle
        # (observed on a list and then absent) can start another task.
        if not new_departure:
            return
    tasks[douban_id] = {
        "reason": reason,
        "status": "pending",
        "created_at": _now(now).isoformat(),
        "failures": 0,
        "next_retry_at": None,
    }


def _library_by_douban_id(library: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for key, entry in library.get("items", {}).items():
        douban_id = entry.get("douban_id")
        if douban_id is None and str(key).isdigit():
            douban_id = str(key)
            entry["douban_id"] = douban_id
        if douban_id:
            result.setdefault(str(douban_id), []).append(entry)
    for douban_id, entries in result.items():
        canonical = library.get("items", {}).get(douban_id)
        if canonical in entries:
            entries.sort(key=lambda entry: entry is not canonical)
    return result


def _synchronize_aliases(library: dict[str, Any], config: dict[str, Any]) -> None:
    """Preserve legacy alias records, with one common policy per Douban ID."""
    for douban_id, entries in _library_by_douban_id(library).items():
        ever = any(entry.get("ever_qualified") for entry in entries)
        dates = [entry["qualified_at"] for entry in entries if entry.get("qualified_at")]
        first = min(dates, key=lambda value: _dt(value) or datetime.max.replace(tzinfo=CST)) if dates else None
        valid_entries = [entry for entry in entries if valid_rating(entry.get("last_rating")) is not None]
        latest = max(valid_entries, key=lambda entry: _dt(entry.get("last_valid_rating_at"))
                     or datetime.min.replace(tzinfo=CST)) if valid_entries else entries[0]
        canonical = library["items"].get(douban_id)
        if canonical is None:
            canonical = copy.deepcopy(latest)
            canonical["key"] = douban_id
            library["items"][douban_id] = canonical
            entries.append(canonical)
        # Complete sparse canonical records using existing data, without
        # discarding old aliases or resetting discovery/qualification times.
        for source in [latest, *entries]:
            for key, value in source.items():
                if canonical.get(key) in (None, "", []) and value not in (None, "", []):
                    canonical[key] = copy.deepcopy(value)
        rating = valid_rating(latest.get("last_rating"))
        counts = [valid_count(entry.get("last_rating_count")) for entry in [latest, *entries]]
        count = next((value for value in counts if value is not None), None)
        for entry in entries:
            entry["ever_qualified"] = ever
            entry["qualified_at"] = first
            entry["last_rating"] = rating
            entry["last_rating_count"] = count
            entry["last_valid_rating_at"] = latest.get("last_valid_rating_at") if rating is not None else None
            entry["display_eligible"] = ever and (rating is None or rating >= float(config.get("min_rating", 8.0)))
            entry["hidden_reason"] = "rating_below_threshold" if ever and not entry["display_eligible"] else None


def migrate_library(library: dict[str, Any], state: dict[str, Any],
                    config: dict[str, Any], now: datetime) -> dict[str, Any]:
    """One idempotent migration using evidence already saved in the repository."""
    if library.get("migration_version", 0) >= MIGRATION_VERSION:
        return library
    state_items = state.get("items", {})
    state_by_id = {str(e["douban_id"]): e for e in state_items.values() if e.get("douban_id")}
    _library_by_douban_id(library)
    for key, entry in library.setdefault("items", {}).items():
        state_entry = state_items.get(key) or state_by_id.get(str(entry.get("douban_id"))) or {}
        qualified_at = entry.get("qualified_at") or state_entry.get("first_qualified_at")
        ever = bool(entry.get("ever_qualified") or qualified_at or entry.get("qualified")
                    or state_entry.get("qualified"))
        entry["ever_qualified"] = ever
        entry["qualified_at"] = qualified_at  # Missing historic dates stay missing.
        rating = valid_rating(entry.get("last_rating"))
        checked_at = entry.get("last_valid_rating_at") or entry.get("last_checked_at")
        state_rating = valid_rating(state_entry.get("last_rating"))
        state_checked = state_entry.get("last_seen_at")
        if state_rating is not None and (rating is None or (
            _dt(state_checked) and _dt(checked_at) and _dt(state_checked) > _dt(checked_at)
        )):
            rating = state_rating
            entry["last_rating"] = rating
            state_count = valid_count(state_entry.get("last_rating_count"))
            if state_count is not None:
                entry["last_rating_count"] = state_count
            checked_at = state_checked
        entry["last_valid_rating_at"] = checked_at if rating is not None else None
        entry["last_rating"] = rating
        entry["last_rating_count"] = valid_count(entry.get("last_rating_count"))
        entry["display_eligible"] = ever and (rating is None or rating >= float(config.get("min_rating", 8.0)))
        entry["hidden_reason"] = "rating_below_threshold" if ever and not entry["display_eligible"] else None
        entry.setdefault("known_collections", [])
        entry.setdefault("membership_status", "unknown")
        entry.setdefault("off_list_verified", False)
        if ever and entry.get("douban_id") and not entry["known_collections"]:
            _enqueue(library, str(entry["douban_id"]), "migration", now)
    _synchronize_aliases(library, config)
    library["migration_version"] = MIGRATION_VERSION
    library["migrated_at"] = _now(now).isoformat()
    return library


def _collection_ids(config: dict[str, Any], snapshots: dict[str, Any]) -> set[str]:
    urls = config.get("douban_collection_urls")
    if urls is None:
        return set(snapshots)
    return {str(url).split("subject_collection/")[-1].split("?")[0].strip("/") for url in urls}


def _complete(task: dict[str, Any], entries: list[dict[str, Any]], now: datetime) -> None:
    task["status"] = "completed"
    task["completed_at"] = _now(now).isoformat()
    task["next_retry_at"] = None
    task.pop("last_error", None)
    for entry in entries:
        if not entry.get("known_collections"):
            entry["off_list_verified"] = True


def update_memberships(library: dict[str, Any], snapshots: dict[str, dict[str, Any]],
                       config: dict[str, Any], now: datetime,
                       fresh_ratings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Use per-list last valid membership; missing candidates carry no meaning."""
    collections = library.setdefault("collections", {})
    monitored = _collection_ids(config, snapshots)
    for collection_id, snapshot in snapshots.items():
        ids = snapshot.get("ids")
        if snapshot.get("success") and isinstance(ids, (list, tuple, set)) and ids:
            # Empty lists are anomalous, not proof of universal departures.
            normalized = {str(value) for value in ids if str(value).isdigit()}
            if len(normalized) != len(set(map(str, ids))):
                continue
            collections[collection_id] = {"ids": sorted(normalized), "updated_at": _now(now).isoformat()}
    known = {key: set(collections[key].get("ids", [])) for key in monitored if key in collections}
    all_known = bool(monitored) and len(known) == len(monitored)
    by_id = _library_by_douban_id(library)
    tasks = library.setdefault("rating_rechecks", {})
    for douban_id, entries in by_id.items():
        on_lists = sorted(key for key, ids in known.items() if douban_id in ids)
        for entry in entries:
            previous_on = entry.get("membership_status") == "on_list" or bool(entry.get("known_collections"))
            previous_on = previous_on or entry.get("departure_pending", False)
            entry["known_collections"] = on_lists
            if on_lists:
                entry["membership_status"] = "on_list"
                entry["departure_pending"] = False
                entry["off_list_verified"] = False
            elif all_known:
                entry["membership_status"] = "off_list"
                entry["departure_pending"] = False
                if previous_on and entry.get("ever_qualified"):
                    entry["off_list_verified"] = False
                    _enqueue(library, douban_id, "off_list", now, new_departure=True)
            else:
                entry["membership_status"] = "unknown"
                entry["departure_pending"] = bool(previous_on)
        task = tasks.get(douban_id)
        # A previous departure no longer needs an extra request once the work
        # returns. A later departure gets its own retry lifecycle. Migration
        # tasks with missing scores wait for a valid regular observation.
        if on_lists and task and task.get("reason") == "off_list" and task.get("status") in {"pending", "paused"}:
            task["status"] = "cancelled"
            task["cancelled_at"] = _now(now).isoformat()
        observation = fresh_ratings.get(douban_id) or {}
        rating = valid_rating(observation.get("rating"))
        if rating is not None:
            for entry in entries:
                apply_rating(entry, rating, observation.get("count"), config, now)
            # A valid score from any existing fetch path satisfies the task.
            if task and task.get("status") in {"pending", "paused"}:
                _complete(task, entries, now)
    return library


def process_recheck_queue(
    library: dict[str, Any], config: dict[str, Any], now: datetime,
    fetch_rating: Callable[[str, dict[str, Any]], dict[str, Any]],
    persist: Callable[[], None], sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Run due tasks serially, with durable daily reservations and backoff.

    ``fetch_rating`` performs exactly one HTTP request and returns rating/count.
    Exceptions and missing ratings consume a slot and leave old data intact.
    """
    now = _now(now)
    if clock is None:
        # Real elapsed time, anchored to the supplied run time for deterministic
        # callers and natural-day rollover during a long-running queue.
        started = time.monotonic()
        clock = lambda: now + timedelta(seconds=time.monotonic() - started)
    current = lambda: _now(clock())
    budget = library.setdefault("rating_recheck_budget", {})
    tasks = library.setdefault("rating_rechecks", {})
    by_id = _library_by_douban_id(library)
    limit = max(0, int(config.get("rating_recheck_daily_limit", 20)))
    interval = max(0.0, float(config.get("rating_recheck_interval_seconds", 3)))
    retries = max(0, int(config.get("rating_recheck_max_retries", 3)))
    delay = timedelta(hours=max(0, float(config.get("rating_recheck_retry_delay_hours", 24))))
    executed = 0
    while True:
        stamp = current()
        cooldown = _dt(budget.get("cooldown_until"))
        if cooldown and stamp < cooldown:
            break
        date = stamp.date().isoformat()
        # A clock rollback must never restore an older day's full budget.
        saved_date = budget.get("date")
        if saved_date is None or date > saved_date:
            budget["date"], budget["used"] = date, 0
        if int(budget.get("used", 0)) >= limit:
            break
        due = [(key, task) for key, task in tasks.items()
               if task.get("status") == "pending" and key in by_id
               and not any(e.get("known_collections") for e in by_id[key])
               and (_dt(task.get("next_retry_at")) is None or _dt(task.get("next_retry_at")) <= stamp)]
        if not due:
            break
        normal = sorted((pair for pair in due if pair[1].get("reason") == "off_list"),
                        key=lambda p: (p[1].get("created_at") or "", p[0]))
        historical = sorted((pair for pair in due if pair[1].get("reason") != "off_list"),
                            key=lambda p: (p[1].get("created_at") or "", p[0]))
        if historical and (not normal or int(budget.get("off_list_streak", 0)) >= 5):
            douban_id, task = historical[0]
            next_streak = 0
        else:
            douban_id, task = normal[0]
            next_streak = int(budget.get("off_list_streak", 0)) + 1
        previous_request = _dt(budget.get("last_request_at"))
        wait = interval - (stamp - previous_request).total_seconds() if previous_request else 0
        if wait > 0:
            sleep(wait)
            stamp = current()
        # Sleep can cross local midnight. Recompute the daily reservation then.
        date = stamp.date().isoformat()
        if date > budget["date"]:
            budget["date"], budget["used"] = date, 0
        budget["used"] = int(budget.get("used", 0)) + 1
        budget["last_request_at"] = stamp.isoformat()
        budget["off_list_streak"] = next_streak
        task["last_attempt_at"] = stamp.isoformat()
        # A crash after reservation must not immediately retry the same work.
        task["next_retry_at"] = (stamp + delay).isoformat()
        persist()
        executed += 1
        error: Exception | None = None
        try:
            observation = fetch_rating(douban_id, by_id[douban_id][0]) or {}
            rating = valid_rating(observation.get("rating"))
            if rating is None:
                raise ValueError("rating missing or invalid")
            finished = current()
            for entry in by_id[douban_id]:
                entry["last_checked_at"] = finished.isoformat()
                apply_rating(entry, rating, observation.get("count"), config, finished)
            _complete(task, by_id[douban_id], finished)
        except Exception as exc:
            error = exc
            finished = current()
            for entry in by_id[douban_id]:
                entry["last_checked_at"] = finished.isoformat()
            task["failures"] = int(task.get("failures", 0)) + 1
            task["last_error"] = str(exc)[:300]
            task["next_retry_at"] = (finished + delay).isoformat()
            if task["failures"] > retries:
                task["status"] = "paused"
                task["paused_at"] = finished.isoformat()
            if isinstance(exc, RateLimited):
                cooldown_seconds = max(86400.0, delay.total_seconds(), exc.retry_after_seconds)
                budget["cooldown_until"] = (finished + timedelta(seconds=cooldown_seconds)).isoformat()
        persist()
        if isinstance(error, RateLimited):
            break
    return executed
