from __future__ import annotations

import json
import os
import re
import tomllib
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    return datetime.now(CST)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class Candidate:
    title: str
    category: str
    source: str
    douban_id: str | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    url: str | None = None
    year: int | None = None
    rating: float | None = None
    rating_count: int | None = None


@dataclass
class LibraryItem:
    key: str
    title: str
    category: str
    sources: list[str]
    watch_status: str
    watch_tier: str
    admission_reason: str
    first_discovered_at: str
    last_discovered_at: str
    watch_started_at: str
    watch_expires_at: str
    last_seen_in_sources_at: str
    resolution_failures: int = 0
    douban_id: str | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    original_title: str | None = None
    url: str | None = None
    year: int | None = None
    last_rating: float | None = None
    last_rating_count: int | None = None
    last_checked_at: str | None = None
    qualified: bool = False
    qualified_at: str | None = None
    archived_at: str | None = None
    archive_reason: str | None = None


@dataclass
class StateItem:
    douban_id: str | None
    title: str
    category: str
    url: str | None
    first_seen_at: str
    last_seen_at: str
    first_qualified_at: str | None = None
    last_notified_at: str | None = None
    last_rating: float | None = None
    last_rating_count: int | None = None
    peak_rating: float | None = None
    peak_rating_count: int | None = None
    notified_stage: str | None = None
    qualified: bool = False
    milestones_notified: list[int] = field(default_factory=list)


DEFAULT_CONFIG = {
    "min_rating": 8.0,
    "min_rating_count": 3000,
    "admission_min_rating": 7.5,
    "admission_min_rating_count": 1000,
    "drop_rating_threshold": 7.5,
    "weak_growth_threshold": 100,
    "realert_cooldown_days": 7,
    "post_alert_watch_days": 21,
    "high_watch_days": 30,
    "medium_watch_days": 14,
    "low_watch_days": 7,
    "rating_delta_for_realert": 0.3,
    "rating_count_delta_for_realert": 5000,
    "milestone_counts": [10000, 30000, 100000],
    "tmdb_base_url": "https://api.themoviedb.org/3",
    "tmdb_language": "zh-CN",
    "tmdb_region": "CN",
    "tmdb_movie_pages": 1,
    "tmdb_tv_pages": 1,
    "douban_weekly_url": "https://m.douban.com/subject_collection/movie_weekly_best",
    "ptgen_static_base_url": "https://ourbits.github.io/PtGen",
    "ptgen_api_base_url": "https://api.ourhelp.club/infogen",
    "request_timeout_seconds": 20,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
}

PTGEN_SCORE_KEYS = {"rating", "rate", "score", "average", "douban_rating"}
PTGEN_COUNT_KEYS = {"rating_count", "vote_count", "votes", "num_raters", "douban_vote_count"}
PTGEN_TITLE_KEYS = {"title", "name", "chinese_title", "translated_title", "subject_title"}
PTGEN_YEAR_KEYS = {"year", "release_year"}
PTGEN_URL_KEYS = {"url", "link", "subject_url", "douban_url"}
PTGEN_IMDB_KEYS = {"imdb_id", "imdb"}


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def candidate_key(candidate: Candidate) -> str:
    if candidate.douban_id:
        return candidate.douban_id
    if candidate.imdb_id:
        return candidate.imdb_id
    if candidate.tmdb_id is not None:
        return f"tmdb:{candidate.tmdb_id}"
    title = candidate.title.strip().lower()
    year = candidate.year or 0
    return f"{title}:{candidate.category}:{year}"


class DoubanWeeklyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.subject_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if not href:
            return
        if "/movie/subject/" in href or "/subject/" in href:
            if href not in self.subject_urls:
                self.subject_urls.append(href)


def fetch_url(url: str, config: dict[str, Any]) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": config["user_agent"],
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=config["request_timeout_seconds"]) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json_url(url: str, config: dict[str, Any]) -> dict[str, Any]:
    return json.loads(fetch_url(url, config))


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def normalize_douban_subject_url(url: str) -> tuple[str | None, str]:
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://m.douban.com" + url
    match = re.search(r"/subject/(\d+)/", url)
    if match:
        subject_id = match.group(1)
        return subject_id, f"https://movie.douban.com/subject/{subject_id}/"
    return None, url


def parse_rating_count_text(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    match = re.search(r"(\d[\d,]*)", text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_rating_text(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    if not match:
        return None
    rating = float(match.group(1))
    return rating if 0.0 <= rating <= 10.0 else None


def recursive_collect(obj: Any, key_bag: set[str], out: list[Any]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in key_bag:
                out.append(value)
            recursive_collect(value, key_bag, out)
    elif isinstance(obj, list):
        for item in obj:
            recursive_collect(item, key_bag, out)


def recursive_find_first_matching_url(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in PTGEN_URL_KEYS and isinstance(value, str) and "douban.com/subject/" in value:
                return value
            found = recursive_find_first_matching_url(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = recursive_find_first_matching_url(item)
            if found:
                return found
    elif isinstance(obj, str) and "douban.com/subject/" in obj:
        return obj
    return None


def recursive_find_imdb_id(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in PTGEN_IMDB_KEYS and isinstance(value, str) and value.startswith("tt"):
                return value
            found = recursive_find_imdb_id(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = recursive_find_imdb_id(item)
            if found:
                return found
    elif isinstance(obj, str):
        match = re.search(r"\btt\d+\b", obj)
        if match:
            return match.group(0)
    return None


def parse_ptgen_payload(payload: dict[str, Any], candidate: Candidate) -> Candidate:
    title_values: list[Any] = []
    score_values: list[Any] = []
    count_values: list[Any] = []
    year_values: list[Any] = []

    recursive_collect(payload, PTGEN_TITLE_KEYS, title_values)
    recursive_collect(payload, PTGEN_SCORE_KEYS, score_values)
    recursive_collect(payload, PTGEN_COUNT_KEYS, count_values)
    recursive_collect(payload, PTGEN_YEAR_KEYS, year_values)

    title = next((str(v).strip() for v in title_values if str(v).strip()), candidate.title)
    rating = next((parse_rating_text(v) for v in score_values if parse_rating_text(v) is not None), candidate.rating)
    rating_count = next(
        (parse_rating_count_text(v) for v in count_values if parse_rating_count_text(v) is not None),
        candidate.rating_count,
    )
    year = next((int(str(v)[:4]) for v in year_values if str(v)[:4].isdigit()), candidate.year)

    subject_url = recursive_find_first_matching_url(payload)
    imdb_id = recursive_find_imdb_id(payload) or candidate.imdb_id
    douban_id = candidate.douban_id
    if subject_url:
        resolved_douban_id, normalized_url = normalize_douban_subject_url(subject_url)
        douban_id = resolved_douban_id or douban_id
        candidate.url = normalized_url

    blob = json.dumps(payload, ensure_ascii=False)
    if rating is None:
        score_match = re.search(r"豆瓣评分[^\d]*(\d+(?:\.\d+)?)", blob)
        if score_match:
            rating = float(score_match.group(1))
    if rating_count is None:
        count_match = re.search(r"(\d[\d,]*)人评价", blob)
        if count_match:
            rating_count = int(count_match.group(1).replace(",", ""))
    if not candidate.url:
        url_match = re.search(r"https?://(?:movie|www)\.douban\.com/subject/\d+/?", blob)
        if url_match:
            resolved_douban_id, normalized_url = normalize_douban_subject_url(url_match.group(0))
            douban_id = resolved_douban_id or douban_id
            candidate.url = normalized_url

    candidate.title = title
    candidate.rating = rating
    candidate.rating_count = rating_count
    candidate.year = year
    candidate.imdb_id = imdb_id
    candidate.douban_id = douban_id
    return candidate


def ptgen_fetch_payload(site: str, sid: str, config: dict[str, Any]) -> dict[str, Any]:
    static_url = f"{config['ptgen_static_base_url'].rstrip('/')}/{site}/{sid}.json"
    try:
        return fetch_json_url(static_url, config)
    except Exception:
        fallback_url = f"{config['ptgen_api_base_url']}?site={urllib.parse.quote(site)}&sid={urllib.parse.quote(sid)}"
        try:
            return fetch_json_url(fallback_url, config)
        except Exception:
            return {}


def fetch_douban_weekly_candidates_with_config(config: dict[str, Any]) -> list[Candidate]:
    html = fetch_url(config["douban_weekly_url"], config)
    parser = DoubanWeeklyParser()
    parser.feed(html)
    candidates: list[Candidate] = []
    for raw_url in parser.subject_urls:
        douban_id, normalized_url = normalize_douban_subject_url(raw_url)
        candidates.append(
            Candidate(
                title=f"douban-subject-{douban_id or 'unknown'}",
                category="unknown",
                source="douban_weekly",
                douban_id=douban_id,
                url=normalized_url,
            )
        )
    return candidates


def tmdb_get(path: str, config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    api_key = get_env("TMDB_API_KEY")
    bearer = get_env("TMDB_BEARER_TOKEN")
    if not api_key and not bearer:
        return {}

    query = dict(params)
    headers = {
        "User-Agent": config["user_agent"],
        "Accept": "application/json",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    else:
        query["api_key"] = api_key

    url = f"{config['tmdb_base_url']}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=config["request_timeout_seconds"]) as response:
        return json.loads(response.read().decode("utf-8"))


def tmdb_external_ids(media_type: str, tmdb_id: int, config: dict[str, Any]) -> dict[str, Any]:
    return tmdb_get(f"/{media_type}/{tmdb_id}/external_ids", config, {})


def tmdb_results_to_candidates(media_type: str, payload: dict[str, Any], config: dict[str, Any]) -> list[Candidate]:
    results = payload.get("results") or []
    candidates: list[Candidate] = []
    for item in results:
        tmdb_id = item.get("id")
        if tmdb_id is None:
            continue
        external_ids = tmdb_external_ids(media_type, int(tmdb_id), config)
        imdb_id = external_ids.get("imdb_id")
        title = item.get("title") or item.get("name") or f"tmdb-{media_type}-{tmdb_id}"
        date_value = item.get("release_date") or item.get("first_air_date") or ""
        year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else None
        candidates.append(
            Candidate(
                title=title,
                category="movie" if media_type == "movie" else "tv",
                source=f"tmdb_{payload.get('_source_name', 'popular')}",
                tmdb_id=int(tmdb_id),
                imdb_id=imdb_id,
                year=year,
            )
        )
    return candidates


def fetch_tmdb_hot_candidates_with_config(config: dict[str, Any]) -> list[Candidate]:
    sources = [
        ("movie", "/trending/movie/week", "trending_movie", config["tmdb_movie_pages"]),
        ("movie", "/movie/popular", "popular_movie", config["tmdb_movie_pages"]),
        ("tv", "/trending/tv/week", "trending_tv", config["tmdb_tv_pages"]),
        ("tv", "/tv/popular", "popular_tv", config["tmdb_tv_pages"]),
    ]
    candidates: list[Candidate] = []
    for media_type, path, source_name, pages in sources:
        for page in range(1, int(pages) + 1):
            payload = tmdb_get(
                path,
                config,
                {
                    "language": config["tmdb_language"],
                    "region": config["tmdb_region"],
                    "page": page,
                },
            )
            if not payload:
                continue
            payload["_source_name"] = source_name
            candidates.extend(tmdb_results_to_candidates(media_type, payload, config))
    return candidates


def resolve_with_ptgen_config(candidate: Candidate, config: dict[str, Any]) -> Candidate:
    if candidate.douban_id:
        payload = ptgen_fetch_payload("douban", candidate.douban_id, config)
        if payload:
            return parse_ptgen_payload(payload, candidate)
        return candidate
    if candidate.imdb_id:
        payload = ptgen_fetch_payload("imdb", candidate.imdb_id, config)
        if payload:
            return parse_ptgen_payload(payload, candidate)
    return candidate


def enrich_with_tmdb(candidate: Candidate) -> Candidate:
    return candidate


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for candidate in candidates:
        key = candidate_key(candidate)
        existing = merged.get(key)
        if not existing:
            merged[key] = candidate
            continue
        if candidate.rating is not None:
            existing.rating = candidate.rating
        if candidate.rating_count is not None:
            existing.rating_count = candidate.rating_count
        if candidate.url:
            existing.url = candidate.url
        if candidate.douban_id:
            existing.douban_id = candidate.douban_id
        if candidate.imdb_id:
            existing.imdb_id = candidate.imdb_id
        if candidate.tmdb_id is not None:
            existing.tmdb_id = candidate.tmdb_id
    return list(merged.values())


def assign_watch_tier(candidate: Candidate, config: dict[str, Any]) -> str:
    rating = candidate.rating or 0.0
    count = candidate.rating_count or 0
    if rating >= config["min_rating"] and count < config["min_rating_count"]:
        return "high"
    if rating >= 7.8 or count >= 2000:
        return "medium"
    return "low"


def watch_days_for_tier(tier: str, config: dict[str, Any]) -> int:
    return {
        "high": config["high_watch_days"],
        "medium": config["medium_watch_days"],
        "low": config["low_watch_days"],
    }[tier]


def admission_reason(candidate: Candidate, config: dict[str, Any]) -> str | None:
    rating = candidate.rating or 0.0
    count = candidate.rating_count or 0
    if candidate.source == "douban_weekly":
        return "appeared_on_douban_weekly"
    if candidate.source.startswith("tmdb") and (candidate.douban_id or candidate.imdb_id):
        return "appeared_on_tmdb_hot_and_mappable"
    if rating >= config["admission_min_rating"]:
        return "rating_at_least_7_5"
    if count >= config["admission_min_rating_count"]:
        return "rating_count_at_least_1000"
    return None


def should_qualify(candidate: Candidate, config: dict[str, Any]) -> bool:
    return (candidate.rating or 0.0) > config["min_rating"] and (candidate.rating_count or 0) > config["min_rating_count"]


def update_library(
    library_data: dict[str, Any],
    candidates: list[Candidate],
    config: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    items = library_data.setdefault("items", {})
    for candidate in candidates:
        reason = admission_reason(candidate, config)
        if not reason:
            continue
        key = candidate_key(candidate)
        tier = assign_watch_tier(candidate, config)
        expires_at = now + timedelta(days=watch_days_for_tier(tier, config))
        entry = items.get(key)
        if not entry:
            item = LibraryItem(
                key=key,
                title=candidate.title,
                category=candidate.category,
                sources=[candidate.source],
                watch_status="active",
                watch_tier=tier,
                admission_reason=reason,
                first_discovered_at=iso(now),
                last_discovered_at=iso(now),
                watch_started_at=iso(now),
                watch_expires_at=iso(expires_at),
                last_seen_in_sources_at=iso(now),
                douban_id=candidate.douban_id,
                tmdb_id=candidate.tmdb_id,
                imdb_id=candidate.imdb_id,
                url=candidate.url,
                year=candidate.year,
                last_rating=candidate.rating,
                last_rating_count=candidate.rating_count,
                last_checked_at=iso(now),
                qualified=should_qualify(candidate, config),
                qualified_at=iso(now) if should_qualify(candidate, config) else None,
            )
            items[key] = asdict(item)
            continue

        entry["last_discovered_at"] = iso(now)
        entry["last_seen_in_sources_at"] = iso(now)
        entry["watch_tier"] = tier
        entry["watch_expires_at"] = iso(expires_at)
        entry["last_checked_at"] = iso(now)
        entry["last_rating"] = candidate.rating
        entry["last_rating_count"] = candidate.rating_count
        entry["qualified"] = should_qualify(candidate, config)
        if entry["qualified"] and not entry.get("qualified_at"):
            entry["qualified_at"] = iso(now)
        if candidate.source not in entry["sources"]:
            entry["sources"].append(candidate.source)
        for field_name in ("douban_id", "tmdb_id", "imdb_id", "url", "year"):
            value = getattr(candidate, field_name)
            if value is not None:
                entry[field_name] = value

    library_data["updated_at"] = iso(now)
    return library_data


def archive_expired_library_items(library_data: dict[str, Any], config: dict[str, Any], now: datetime) -> dict[str, Any]:
    for entry in library_data.get("items", {}).values():
        if entry.get("archived_at"):
            continue
        expires_at = parse_dt(entry.get("watch_expires_at"))
        if expires_at and expires_at < now and not entry.get("qualified"):
            entry["watch_status"] = "archived"
            entry["archived_at"] = iso(now)
            entry["archive_reason"] = "watch_window_expired_without_qualification"
            continue
        rating = entry.get("last_rating") or 0.0
        if rating < config["drop_rating_threshold"]:
            entry["watch_status"] = "archived"
            entry["archived_at"] = iso(now)
            entry["archive_reason"] = "rating_below_threshold"
    library_data["updated_at"] = iso(now)
    return library_data


def update_state(
    state_data: dict[str, Any],
    candidates: list[Candidate],
    config: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], list[Candidate], list[tuple[Candidate, str]]]:
    items = state_data.setdefault("items", {})
    new_qualified: list[Candidate] = []
    second_look: list[tuple[Candidate, str]] = []

    for candidate in candidates:
        key = candidate.douban_id or candidate_key(candidate)
        entry = items.get(key)
        qualifies = should_qualify(candidate, config)
        if not entry:
            state_item = StateItem(
                douban_id=candidate.douban_id,
                title=candidate.title,
                category=candidate.category,
                url=candidate.url,
                first_seen_at=iso(now),
                last_seen_at=iso(now),
                first_qualified_at=iso(now) if qualifies else None,
                last_notified_at=iso(now) if qualifies else None,
                last_rating=candidate.rating,
                last_rating_count=candidate.rating_count,
                peak_rating=candidate.rating,
                peak_rating_count=candidate.rating_count,
                notified_stage="initial" if qualifies else None,
                qualified=qualifies,
            )
            items[key] = asdict(state_item)
            if qualifies:
                new_qualified.append(candidate)
            continue

        previous_rating = entry.get("last_rating") or 0.0
        previous_count = entry.get("last_rating_count") or 0
        entry["last_seen_at"] = iso(now)
        entry["last_rating"] = candidate.rating
        entry["last_rating_count"] = candidate.rating_count
        entry["peak_rating"] = max(entry.get("peak_rating") or 0.0, candidate.rating or 0.0)
        entry["peak_rating_count"] = max(entry.get("peak_rating_count") or 0, candidate.rating_count or 0)

        if qualifies and not entry.get("first_qualified_at"):
            entry["first_qualified_at"] = iso(now)
            entry["last_notified_at"] = iso(now)
            entry["notified_stage"] = "initial"
            entry["qualified"] = True
            new_qualified.append(candidate)
            continue

        if not qualifies:
            continue

        cooldown_cutoff = now - timedelta(days=config["realert_cooldown_days"])
        last_notified_at = parse_dt(entry.get("last_notified_at"))
        if last_notified_at and last_notified_at > cooldown_cutoff:
            continue

        trigger: str | None = None
        if (candidate.rating or 0.0) - previous_rating >= config["rating_delta_for_realert"]:
            trigger = f"rating +{(candidate.rating or 0.0) - previous_rating:.1f} since last alert"
        elif (candidate.rating_count or 0) - previous_count >= config["rating_count_delta_for_realert"]:
            trigger = f"rating_count +{(candidate.rating_count or 0) - previous_count} since last alert"
        else:
            for milestone in config["milestone_counts"]:
                if previous_count < milestone <= (candidate.rating_count or 0) and milestone not in entry["milestones_notified"]:
                    entry["milestones_notified"].append(milestone)
                    trigger = f"crossed {milestone} ratings"
                    break

        if trigger:
            entry["last_notified_at"] = iso(now)
            entry["notified_stage"] = "second_look"
            second_look.append((candidate, trigger))

    state_data["updated_at"] = iso(now)
    return state_data, new_qualified, second_look


def render_report(
    new_qualified: list[Candidate],
    second_look: list[tuple[Candidate, str]],
    observed: list[Candidate],
    config: dict[str, Any],
    now: datetime,
) -> str:
    lines = [
        "# 豆瓣高分监控",
        "",
        f"运行时间: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"阈值: 评分 > {config['min_rating']}，评分人数 > {config['min_rating_count']}",
        "",
        "## 新增命中",
    ]
    if not new_qualified:
        lines.append("- 无")
    for item in new_qualified:
        lines.extend(
            [
                f"- 标题: {item.title}",
                f"- 类型: {item.category}",
                f"- 评分: {item.rating}",
                f"- 评分人数: {item.rating_count}",
                f"- 链接: {item.url or 'N/A'}",
                "- 触发原因: 首次达标",
            ]
        )

    lines.extend(["", "## 值得二次关注"])
    if not second_look:
        lines.append("- 无")
    for item, trigger in second_look:
        lines.extend(
            [
                f"- 标题: {item.title}",
                f"- 类型: {item.category}",
                f"- 评分: {item.rating}",
                f"- 评分人数: {item.rating_count}",
                f"- 链接: {item.url or 'N/A'}",
                f"- 触发原因: {trigger}",
            ]
        )

    lines.extend(["", "## 继续观察"])
    pending = [item for item in observed if not should_qualify(item, config)]
    if not pending:
        lines.append("- 无")
    for item in pending:
        lines.extend(
            [
                f"- 标题: {item.title}",
                f"- 评分: {item.rating}",
                f"- 评分人数: {item.rating_count}",
            ]
        )
    return "\n".join(lines) + "\n"


def run(
    base_dir: Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Path]:
    project_root = base_dir.parent
    file_config = load_toml(project_root / "config.toml")
    config = {**DEFAULT_CONFIG, **file_config, **(config or {})}
    now = now_cst()

    state_path = project_root / "data" / "douban-monitor-state.json"
    library_path = project_root / "data" / "douban-monitor-library.json"
    report_path = project_root / "reports" / f"douban-monitor-{now.strftime('%Y%m%d')}.md"

    state_data = load_json(state_path, {"version": 1, "updated_at": None, "items": {}})
    library_data = load_json(library_path, {"version": 1, "updated_at": None, "items": {}})

    candidates: list[Candidate] = []
    candidates.extend(fetch_douban_weekly_candidates_with_config(config))
    candidates.extend(fetch_tmdb_hot_candidates_with_config(config))
    candidates = [enrich_with_tmdb(resolve_with_ptgen_config(item, config)) for item in dedupe_candidates(candidates)]

    library_data = update_library(library_data, candidates, config, now)
    library_data = archive_expired_library_items(library_data, config, now)
    state_data, new_qualified, second_look = update_state(state_data, candidates, config, now)

    report = render_report(new_qualified, second_look, candidates, config, now)

    save_json(state_path, state_data)
    save_json(library_path, library_data)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "state_path": state_path,
        "library_path": library_path,
        "report_path": report_path,
    }


if __name__ == "__main__":
    result = run(Path(__file__).resolve().parent)
    for name, path in result.items():
        print(f"{name}: {path}")
