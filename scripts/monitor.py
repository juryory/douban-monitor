from __future__ import annotations

import json
import os
import re
import tomllib
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    return datetime.now(CST)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def log_step(title: str) -> None:
    print(title, flush=True)


def log_kv(label: str, value: Any) -> None:
    print(f"  - {label}: {value}", flush=True)


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
    "realert_cooldown_days": 7,
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
    "douban_collection_urls": [
        "https://m.douban.com/subject_collection/movie_weekly_best",
        "https://m.douban.com/subject_collection/tv_chinese_best_weekly",
        "https://m.douban.com/subject_collection/tv_global_best_weekly",
        "https://m.douban.com/subject_collection/show_domestic_best_weekly",
        "https://m.douban.com/subject_collection/show_global_best_weekly",
    ],
    "request_timeout_seconds": 20,
    "browser_headless": True,
    "browser_wait_ms": 5000,
    "browser_executable_path": "",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
}


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


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def normalize_douban_subject_url(url: str) -> tuple[str | None, str]:
    if "sec.douban.com/c?" in url:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        redirect = query.get("r", [None])[0]
        if redirect:
            url = urllib.parse.unquote(redirect)
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://m.douban.com" + url
    match = re.search(r"/subject/(\d+)/", url)
    if match:
        subject_id = match.group(1)
        return subject_id, f"https://movie.douban.com/subject/{subject_id}/"
    return None, url


def fetch_page_with_browser(url: str, config: dict[str, Any]) -> str:
    launch_kwargs: dict[str, Any] = {"headless": bool(config.get("browser_headless", True))}
    executable_path = str(config.get("browser_executable_path", "")).strip()
    if executable_path:
        launch_kwargs["executable_path"] = executable_path

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1200},
            user_agent=config["user_agent"],
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(config["request_timeout_seconds"]) * 1000)
            page.wait_for_timeout(int(config.get("browser_wait_ms", 5000)))
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return page.content()
        finally:
            context.close()
            browser.close()


def resolve_candidate_urls_from_collection_page(
    collection_url: str,
    rows: list[dict[str, str]],
    config: dict[str, Any],
) -> list[dict[str, str]]:
    unresolved_titles = [row["title"] for row in rows if row.get("title") and not row.get("href")]
    if not unresolved_titles:
        return rows

    launch_kwargs: dict[str, Any] = {"headless": bool(config.get("browser_headless", True))}
    executable_path = str(config.get("browser_executable_path", "")).strip()
    if executable_path:
        launch_kwargs["executable_path"] = executable_path

    resolved_map: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1200},
            user_agent=config["user_agent"],
        )
        page = context.new_page()
        try:
            page.goto(collection_url, wait_until="domcontentloaded", timeout=int(config["request_timeout_seconds"]) * 1000)
            page.wait_for_timeout(int(config.get("browser_wait_ms", 5000)))
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            for title in unresolved_titles:
                try:
                    locator = page.get_by_text(title, exact=True).first
                    if locator.count() == 0:
                        continue
                    with context.expect_page(timeout=8000) as new_page_info:
                        locator.click()
                    detail_page = new_page_info.value
                    try:
                        detail_page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    resolved_map[title] = detail_page.url
                    detail_page.close()
                except Exception:
                    continue
        finally:
            context.close()
            browser.close()

    for row in rows:
        if not row.get("href") and row.get("title") in resolved_map:
            row["href"] = resolved_map[row["title"]]
    return rows


def extract_weekly_candidates_with_browser(url: str, config: dict[str, Any]) -> list[dict[str, str]]:
    launch_kwargs: dict[str, Any] = {"headless": bool(config.get("browser_headless", True))}
    executable_path = str(config.get("browser_executable_path", "")).strip()
    if executable_path:
        launch_kwargs["executable_path"] = executable_path

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1200},
            user_agent=config["user_agent"],
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(config["request_timeout_seconds"]) * 1000)
            page.wait_for_timeout(int(config.get("browser_wait_ms", 5000)))
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            rows = page.evaluate(
                """
                () => {
                  const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                  const rows = [];
                  const seen = new Set();

                  const rawText = document.body?.innerText || '';
                  const lines = rawText.split('\\n').map(line => normalize(line)).filter(Boolean);
                  for (let i = 0; i < lines.length - 2; i++) {
                    if (!/^\\d+$/.test(lines[i])) continue;
                    const title = lines[i + 1];
                    const score = lines[i + 2];
                    if (!title || !/^\\d+(\\.\\d+)?$/.test(score)) continue;
                    const key = `title:${title}`;
                    if (seen.has(key)) continue;
                    rows.push({ href: '', title });
                    seen.add(key);
                  }

                  const textMap = new Map(rows.map(item => [item.title, item]));

                  for (const node of document.querySelectorAll('a[href*="/subject/"], a[href*="/movie/subject/"]')) {
                    const href = node.href || node.getAttribute('href') || '';
                    if (!href || !/\\/subject\\/\\d+/.test(href)) continue;
                    const title =
                      normalize(node.querySelector('img[alt]')?.getAttribute('alt')) ||
                      normalize(node.getAttribute('title')) ||
                      normalize(node.innerText) ||
                      normalize(node.textContent);
                    if (!title) continue;
                    if (textMap.has(title)) {
                      textMap.get(title).href = href;
                      continue;
                    }
                    if (!seen.has(href)) {
                      rows.push({ href, title });
                      seen.add(href);
                    }
                  }

                  return rows;
                }
                """
            )
            return rows if isinstance(rows, list) else []
        finally:
            context.close()
            browser.close()


def resolve_douban_url_from_search(candidate: Candidate, config: dict[str, Any]) -> Candidate:
    if candidate.url or not candidate.title:
        return candidate

    search_url = "https://www.douban.com/search?cat=1002&q=" + urllib.parse.quote(candidate.title)
    html = fetch_page_with_browser(search_url, config)
    match = re.search(r"https?://movie\.douban\.com/subject/\d+/?", html)
    if not match:
        return candidate

    douban_id, normalized_url = normalize_douban_subject_url(match.group(0))
    candidate.url = normalized_url
    if douban_id:
        candidate.douban_id = douban_id
    return candidate


def fetch_douban_weekly_candidates_with_config(config: dict[str, Any]) -> list[Candidate]:
    candidates: list[Candidate] = []
    collection_urls = config.get("douban_collection_urls") or []
    for collection_url in collection_urls:
        rows = extract_weekly_candidates_with_browser(str(collection_url), config)
        rows = resolve_candidate_urls_from_collection_page(str(collection_url), rows, config)
        category = "unknown"
        source = "douban_weekly"
        url_text = str(collection_url)
        if "movie_" in url_text:
            category = "movie"
            source = "douban_movie_weekly"
        elif "tv_chinese" in url_text:
            category = "tv"
            source = "douban_tv_chinese_weekly"
        elif "tv_global" in url_text:
            category = "tv"
            source = "douban_tv_global_weekly"
        elif "show_domestic" in url_text:
            category = "variety"
            source = "douban_show_domestic_weekly"
        elif "show_global" in url_text:
            category = "variety"
            source = "douban_show_global_weekly"

        for row in rows:
            raw_url = str(row.get("href", "")).strip()
            title = str(row.get("title", "")).strip()
            douban_id = None
            normalized_url = None
            if raw_url:
                douban_id, normalized_url = normalize_douban_subject_url(raw_url)
            candidates.append(
                Candidate(
                    title=title or f"douban-subject-{douban_id or 'unknown'}",
                    category=category,
                    source=source,
                    douban_id=douban_id,
                    url=normalized_url,
                )
            )
    return candidates


def fetch_douban_subject_detail(candidate: Candidate, config: dict[str, Any]) -> Candidate:
    candidate = resolve_douban_url_from_search(candidate, config)
    if not candidate.url and candidate.douban_id:
        candidate.url = f"https://movie.douban.com/subject/{candidate.douban_id}/"
    if not candidate.url:
        return candidate

    html = fetch_url(candidate.url, config)

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        title = re.sub(r"\s*\(豆瓣\)\s*$", "", title)
        if title:
            candidate.title = title

    rating_match = re.search(r'property="v:average">([^<]+)<', html)
    if rating_match:
        try:
            candidate.rating = float(rating_match.group(1).strip())
        except ValueError:
            pass

    count_match = re.search(r'property="v:votes">([^<]+)<', html)
    if count_match:
        try:
            candidate.rating_count = int(count_match.group(1).strip().replace(",", ""))
        except ValueError:
            pass
    if candidate.rating_count is None:
        count_match = re.search(r"(\d[\d,]*)人评价", html)
        if count_match:
            candidate.rating_count = int(count_match.group(1).replace(",", ""))

    year_match = re.search(r"(\d{4})", html)
    if year_match and candidate.year is None:
        candidate.year = int(year_match.group(1))

    if candidate.rating is None or candidate.rating_count is None or candidate.title == "豆瓣":
        html = fetch_page_with_browser(candidate.url, config)

        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
            title = re.sub(r"\s*\(豆瓣\)\s*$", "", title)
            if title:
                candidate.title = title

        rating_match = re.search(r'property="v:average">([^<]+)<', html)
        if rating_match:
            try:
                candidate.rating = float(rating_match.group(1).strip())
            except ValueError:
                pass

        count_match = re.search(r'property="v:votes">([^<]+)<', html)
        if count_match:
            try:
                candidate.rating_count = int(count_match.group(1).strip().replace(",", ""))
            except ValueError:
                pass
        if candidate.rating_count is None:
            count_match = re.search(r"(\d[\d,]*)人评价", html)
            if count_match:
                candidate.rating_count = int(count_match.group(1).replace(",", ""))

        year_match = re.search(r"(\d{4})", html)
        if year_match and candidate.year is None:
            candidate.year = int(year_match.group(1))

    return candidate


def tmdb_get(path: str, config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    api_key = get_env("TMDB_API_KEY")
    bearer = get_env("TMDB_BEARER_TOKEN")
    if not api_key and not bearer:
        return {}

    query = dict(params)
    headers = {"User-Agent": config["user_agent"], "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    else:
        query["api_key"] = api_key

    url = f"{config['tmdb_base_url']}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=config["request_timeout_seconds"]) as response:
        return json.loads(response.read().decode("utf-8"))


def tmdb_results_to_candidates(media_type: str, payload: dict[str, Any]) -> list[Candidate]:
    results = payload.get("results") or []
    candidates: list[Candidate] = []
    for item in results:
        tmdb_id = item.get("id")
        if tmdb_id is None:
            continue
        title = item.get("title") or item.get("name") or f"tmdb-{media_type}-{tmdb_id}"
        date_value = item.get("release_date") or item.get("first_air_date") or ""
        year = int(date_value[:4]) if len(date_value) >= 4 and date_value[:4].isdigit() else None
        candidates.append(
            Candidate(
                title=title,
                category="movie" if media_type == "movie" else "tv",
                source=f"tmdb_{payload.get('_source_name', 'popular')}",
                tmdb_id=int(tmdb_id),
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
                {"language": config["tmdb_language"], "region": config["tmdb_region"], "page": page},
            )
            if not payload:
                continue
            payload["_source_name"] = source_name
            candidates.extend(tmdb_results_to_candidates(media_type, payload))
    return candidates


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
        if candidate.title and (not existing.title or existing.title.startswith("douban-subject-")):
            existing.title = candidate.title
        if candidate.rating is not None:
            existing.rating = candidate.rating
        if candidate.rating_count is not None:
            existing.rating_count = candidate.rating_count
        if candidate.url:
            existing.url = candidate.url
        if candidate.douban_id:
            existing.douban_id = candidate.douban_id
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
    return {"high": config["high_watch_days"], "medium": config["medium_watch_days"], "low": config["low_watch_days"]}[tier]


def admission_reason(candidate: Candidate, config: dict[str, Any]) -> str | None:
    rating = candidate.rating or 0.0
    count = candidate.rating_count or 0
    if candidate.source.startswith("douban_"):
        return "appeared_on_douban_weekly"
    if candidate.source.startswith("tmdb"):
        return "appeared_on_tmdb_hot"
    if rating >= config["admission_min_rating"]:
        return "rating_at_least_7_5"
    if count >= config["admission_min_rating_count"]:
        return "rating_count_at_least_1000"
    return None


def should_qualify(candidate: Candidate, config: dict[str, Any]) -> bool:
    return (candidate.rating or 0.0) > config["min_rating"] and (candidate.rating_count or 0) > config["min_rating_count"]


def update_library(library_data: dict[str, Any], candidates: list[Candidate], config: dict[str, Any], now: datetime) -> dict[str, Any]:
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
        entry["title"] = candidate.title
        entry["category"] = candidate.category
        entry["url"] = candidate.url
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


def update_state(state_data: dict[str, Any], candidates: list[Candidate], config: dict[str, Any], now: datetime) -> tuple[dict[str, Any], list[Candidate], list[tuple[Candidate, str]]]:
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
        entry["title"] = candidate.title
        entry["category"] = candidate.category
        entry["url"] = candidate.url
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
            trigger = f"评分较上次提醒提升 {(candidate.rating or 0.0) - previous_rating:.1f}"
        elif (candidate.rating_count or 0) - previous_count >= config["rating_count_delta_for_realert"]:
            trigger = f"评分人数较上次提醒增加 {(candidate.rating_count or 0) - previous_count}"
        else:
            for milestone in config["milestone_counts"]:
                if previous_count < milestone <= (candidate.rating_count or 0) and milestone not in entry["milestones_notified"]:
                    entry["milestones_notified"].append(milestone)
                    trigger = f"评分人数跨过 {milestone}"
                    break
        if trigger:
            entry["last_notified_at"] = iso(now)
            entry["notified_stage"] = "second_look"
            second_look.append((candidate, trigger))

    state_data["updated_at"] = iso(now)
    return state_data, new_qualified, second_look


def render_report(new_qualified: list[Candidate], second_look: list[tuple[Candidate, str]], observed: list[Candidate], config: dict[str, Any], now: datetime) -> str:
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
        lines.extend([
            f"- 标题: {item.title}",
            f"- 类型: {item.category}",
            f"- 评分: {item.rating}",
            f"- 评分人数: {item.rating_count}",
            f"- 链接: {item.url or 'N/A'}",
            "- 触发原因: 首次达标",
        ])
    lines.extend(["", "## 值得二次关注"])
    if not second_look:
        lines.append("- 无")
    for item, trigger in second_look:
        lines.extend([
            f"- 标题: {item.title}",
            f"- 类型: {item.category}",
            f"- 评分: {item.rating}",
            f"- 评分人数: {item.rating_count}",
            f"- 链接: {item.url or 'N/A'}",
            f"- 触发原因: {trigger}",
        ])
    lines.extend(["", "## 继续观察"])
    pending = [item for item in observed if not should_qualify(item, config)]
    if not pending:
        lines.append("- 无")
    for item in pending:
        lines.extend([
            f"- 标题: {item.title}",
            f"- 评分: {item.rating}",
            f"- 评分人数: {item.rating_count}",
        ])
    return "\n".join(lines) + "\n"


def run(base_dir: Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    project_root = base_dir.parent
    file_config = load_toml(project_root / "config.toml")
    config = {**DEFAULT_CONFIG, **file_config, **(config or {})}
    now = now_cst()

    state_path = project_root / "data" / "douban-monitor-state.json"
    library_path = project_root / "data" / "douban-monitor-library.json"
    report_path = project_root / "reports" / f"douban-monitor-{now.strftime('%Y%m%d')}.md"

    state_data = load_json(state_path, {"version": 1, "updated_at": None, "items": {}})
    library_data = load_json(library_path, {"version": 1, "updated_at": None, "items": {}})

    log_step("[1/5] 抓取豆瓣榜单候选...")
    douban_candidates = fetch_douban_weekly_candidates_with_config(config)
    log_kv("豆瓣榜单候选数", len(douban_candidates))

    log_step("[2/5] 抓取 TMDB 候选...")
    tmdb_candidates = fetch_tmdb_hot_candidates_with_config(config)
    log_kv("TMDB 候选数", len(tmdb_candidates))

    log_step("[3/5] 去重并补详情页...")
    candidates: list[Candidate] = []
    candidates.extend(douban_candidates)
    candidates.extend(tmdb_candidates)
    deduped_candidates = dedupe_candidates(candidates)
    log_kv("去重后候选数", len(deduped_candidates))
    candidates = [enrich_with_tmdb(fetch_douban_subject_detail(item, config)) for item in deduped_candidates]
    detail_ready = sum(1 for item in candidates if item.url)
    rating_ready = sum(1 for item in candidates if item.rating is not None)
    rating_count_ready = sum(1 for item in candidates if item.rating_count is not None)
    log_kv("已有详情页链接", detail_ready)
    log_kv("已获取评分", rating_ready)
    log_kv("已获取评分人数", rating_count_ready)

    log_step("[4/5] 更新状态与监控库...")
    library_data = update_library(library_data, candidates, config, now)
    library_data = archive_expired_library_items(library_data, config, now)
    state_data, new_qualified, second_look = update_state(state_data, candidates, config, now)
    report = render_report(new_qualified, second_look, candidates, config, now)
    pending_count = sum(1 for item in candidates if not should_qualify(item, config))
    log_kv("新增命中", len(new_qualified))
    log_kv("值得二次关注", len(second_look))
    log_kv("继续观察", pending_count)
    log_kv("监控库条目数", len(library_data.get("items", {})))
    log_kv("状态条目数", len(state_data.get("items", {})))

    log_step("[5/5] 写入文件...")
    save_json(state_path, state_data)
    save_json(library_path, library_data)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    log_kv("状态文件", state_path)
    log_kv("监控库文件", library_path)
    log_kv("报告文件", report_path)

    return {"state_path": state_path, "library_path": library_path, "report_path": report_path}


if __name__ == "__main__":
    run(Path(__file__).resolve().parent)
