"""Generate four static RSS 2.0 feeds from the website's display data."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://douban.juryory.com"
CATEGORIES = {"movie": "电影", "tv": "剧集", "variety": "综艺", "all": "全部"}
CST = timezone(timedelta(hours=8))
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("atom", ATOM)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value)
        return date.replace(tzinfo=CST) if date.tzinfo is None else date
    except (ValueError, TypeError):
        return None


def add(parent: ET.Element, tag: str, value: object, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attrs)
    # XML 1.0 forbids control characters, even inside escaped text.
    element.text = "".join(c for c in str(value) if c in "\t\n\r" or
                           0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or
                           0x10000 <= ord(c) <= 0x10FFFF)
    return element


def render_feed(items: list[dict], category: str, run_at: str | None,
                site_url: str = SITE_URL) -> bytes:
    site_url = site_url.rstrip("/")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add(channel, "title", f"豆瓣高分监控 · {CATEGORIES[category]}")
    add(channel, "link", site_url + "/")
    add(channel, "description", f"豆瓣高分监控：{CATEGORIES[category]}订阅，随每日监控更新。")
    add(channel, "language", "zh-CN")
    add(channel, "ttl", "60")
    ET.SubElement(channel, f"{{{ATOM}}}link", {
        "href": f"{site_url}/data/rss/{category}.xml",
        "rel": "self", "type": "application/rss+xml",
    })
    if date := parse_date(run_at):
        add(channel, "lastBuildDate", format_datetime(date))

    def published(item: dict) -> datetime | None:
        return parse_date(item.get("qualified_at")) or parse_date(item.get("first_discovered_at"))

    selected = [item for item in items if category == "all" or item.get("category") == category]
    # Unknown historical dates remain undated instead of becoming new on every run.
    selected.sort(key=lambda item: (
        -(published(item).timestamp() if published(item) else float("-inf")),
        str(item["douban_id"]),
    ))
    for item in selected:
        did = str(item["douban_id"])
        entry = ET.SubElement(channel, "item")
        add(entry, "title", item.get("title") or "未知作品")
        add(entry, "link", f"{site_url}/detail/{did}.html")
        add(entry, "guid", f"urn:douban:subject:{did}", isPermaLink="false")
        label = CATEGORIES.get(item.get("category"), "其他")
        add(entry, "category", label)
        if date := published(item):
            add(entry, "pubDate", format_datetime(date))
        description = [f"分类：{label}"]
        if item.get("year"):
            description.append(f"年份：{item['year']}")
        rating = item.get("rating")
        count = item.get("rating_count")
        description.extend([
            f"豆瓣评分：{rating if rating is not None else '暂无'}",
            f"评分人数：{count if count is not None else '暂无'}",
            f"豆瓣链接：https://movie.douban.com/subject/{did}/",
        ])
        add(entry, "description", "\n".join(description))
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def generate_feeds(project_root: Path = ROOT, site_url: str = SITE_URL) -> dict[str, int]:
    data_dir = project_root / "data"
    # The main result must exist and parse successfully before any feed is replaced.
    result = json.loads((data_dir / "douban-monitor-result.json").read_text(encoding="utf-8"))
    favorites_path = data_dir / "douban-monitor-favorites-result.json"
    favorites = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else {}
    items = {}
    for item in result.get("qualified", []) + favorites.get("qualified", []):
        did = str(item.get("douban_id") or "")
        if did.isascii() and did.isdigit() and did not in items:
            items[did] = item
    output = data_dir / "rss"
    output.mkdir(parents=True, exist_ok=True)
    counts = {}
    for category in CATEGORIES:
        content = render_feed(list(items.values()), category, result.get("run_at"), site_url)
        path = output / f"{category}.xml"
        temporary = path.with_suffix(".xml.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        counts[category] = sum(category == "all" or item.get("category") == category
                               for item in items.values())
    return counts


if __name__ == "__main__":
    print(json.dumps(generate_feeds(), ensure_ascii=False))
