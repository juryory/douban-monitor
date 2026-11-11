"""Generate four static RSS 2.0 feeds from the website's display data."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://douban.juryory.com"
CATEGORIES = {"movie": "电影", "tv": "剧集", "variety": "综艺", "all": "全部"}
CST = timezone(timedelta(hours=8))
ATOM = "http://www.w3.org/2005/Atom"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("atom", ATOM)
ET.register_namespace("content", CONTENT)


def text_html(value: object) -> str:
    return escape(str(value), quote=True)


def image_url(value: str | None, size: str = "w780") -> str:
    """Accept cached HTTP(S) images or TMDB paths; never emit active URL schemes."""
    if not value:
        return ""
    if value.startswith("/") and not value.startswith("//"):
        return f"https://image.tmdb.org/t/p/{size}{value}"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in ("https", "http") and parsed.netloc else ""


def render_content(item: dict, meta: dict, poster: str | None, reviews: list[dict],
                   site_url: str) -> str:
    """Reader-friendly HTML that works without page CSS, JavaScript or embeds."""
    parts = []

    def paragraph(value: object) -> None:
        parts.append(f"<p>{text_html(value).replace(chr(10), '<br />')}</p>")

    def image(url: str, alt: str, width: int) -> str:
        return (f'<img src="{text_html(url)}" alt="{text_html(alt)}" width="{width}" '
                'style="max-width:100%;height:auto;" />')

    title = item.get("title") or "未知作品"
    poster_url = (image_url(meta.get("poster_path"), "w500") or image_url(poster, "w500")
                  or image_url(meta.get("backdrop_path")))
    if poster_url:
        parts.append(f"<p>{image(poster_url, title + ' 海报', 260)}</p>")
    if meta.get("original_title"):
        paragraph(meta["original_title"])
    details = [str(item.get("year") or ""), CATEGORIES.get(item.get("category"), "其他")]
    if meta.get("runtime"):
        details.append(f"{meta['runtime']}分钟")
    details.extend(meta.get("countries") or [])
    paragraph(" · ".join(value for value in details if value))
    if meta.get("genres"):
        paragraph("类型：" + " / ".join(meta["genres"]))
    if meta.get("release_date"):
        paragraph("首播 / 上映日期：" + meta["release_date"])
    rating, count = item.get("rating"), item.get("rating_count")
    paragraph(f"豆瓣评分：{rating if rating is not None else '暂无'} / 10　"
              f"评分人数：{count if count is not None else '暂无'}")
    if meta.get("director"):
        paragraph("导演 / 主创：" + meta["director"])
    if meta.get("overview"):
        parts.append("<h2>剧情简介</h2>")
        paragraph(meta["overview"])
    cast = meta.get("cast") or []
    if cast:
        parts.append("<h2>主演</h2><ul>")
        for actor in cast:
            photo = image_url(actor.get("profile_path"), "w185")
            label = actor.get("name") or "未知演员"
            if actor.get("character"):
                label += " — " + actor["character"]
            parts.append("<li>" + (image(photo, actor.get("name") or "演员", 64) + " " if photo else "")
                         + text_html(label) + "</li>")
        parts.append("</ul>")
    stills = list(dict.fromkeys(url for path in (meta.get("stills") or [])
                               if (url := image_url(path))))
    if stills:
        parts.append("<h2>剧照</h2>")
        for index, url in enumerate(stills, 1):
            parts.append(f"<p>{image(url, f'{title} 剧照 {index}', 720)}</p>")
    if reviews:
        parts.append("<h2>豆瓣短评</h2>")
        for review in reviews:
            parts.append("<blockquote>")
            header = [review.get("user") or "豆瓣用户", review.get("date") or ""]
            stars = review.get("rating")
            if isinstance(stars, (int, float)) and 0 < stars <= 5:
                header.append(f"{'★' * int(stars)}{'☆' * (5 - int(stars))}（{stars}/5）")
            paragraph(" · ".join(value for value in header if value))
            paragraph(review.get("comment") or "")
            parts.append("</blockquote>")
    did = item["douban_id"]
    parts.append(f'<p><a href="{text_html(site_url)}/detail/{did}.html">查看完整详情</a>'
                 f' · <a href="https://movie.douban.com/subject/{did}/">豆瓣作品页</a></p>')
    return "\n".join(parts)


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
                site_url: str = SITE_URL, *, metadata: dict | None = None,
                posters: dict | None = None, reviews: dict | None = None) -> bytes:
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
        content = render_content(item, (metadata or {}).get(did) or {},
                                 (posters or {}).get(did), (reviews or {}).get(did) or [], site_url)
        # Some readers use description only; others prefer content:encoded.
        add(entry, "description", content)
        add(entry, f"{{{CONTENT}}}encoded", content)
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def generate_feeds(project_root: Path = ROOT, site_url: str = SITE_URL) -> dict[str, int]:
    data_dir = project_root / "data"
    # The main result must exist and parse successfully before any feed is replaced.
    result = json.loads((data_dir / "douban-monitor-result.json").read_text(encoding="utf-8"))
    favorites_path = data_dir / "douban-monitor-favorites-result.json"
    favorites = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else {}
    caches = {}
    for name in ("metadata", "posters", "reviews"):
        path = data_dir / f"douban-monitor-{name}.json"
        try:
            caches[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (ValueError, OSError):
            # Optional enrichment must not interrupt the basic subscription.
            caches[name] = {}
    items = {}
    for item in result.get("qualified", []) + favorites.get("qualified", []):
        did = str(item.get("douban_id") or "")
        if did.isascii() and did.isdigit() and did not in items:
            items[did] = item
    output = data_dir / "rss"
    output.mkdir(parents=True, exist_ok=True)
    counts = {}
    for category in CATEGORIES:
        content = render_feed(list(items.values()), category, result.get("run_at"), site_url, **caches)
        path = output / f"{category}.xml"
        temporary = path.with_suffix(".xml.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        counts[category] = sum(category == "all" or item.get("category") == category
                               for item in items.values())
    return counts


if __name__ == "__main__":
    print(json.dumps(generate_feeds(), ensure_ascii=False))
