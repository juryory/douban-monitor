"""Offline checks for feed categories, dates, identity and regeneration."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_rss import CATEGORIES, CONTENT, generate_feeds, render_feed


class RssTests(unittest.TestCase):
    def test_categories_deduplication_and_removed_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            result = {"run_at": "2026-11-11T09:00:00+08:00", "qualified": [
                {"douban_id": "1", "category": "movie", "title": "电影"},
                {"douban_id": "2", "category": "tv", "title": "剧集"},
                {"douban_id": "3", "category": "variety", "title": "综艺"},
            ]}
            result_path = data / "douban-monitor-result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            (data / "douban-monitor-favorites-result.json").write_text(json.dumps({"qualified": [
                {"douban_id": "1", "category": "tv", "title": "重复收藏"},
                {"douban_id": "4", "category": "movie", "title": "收藏"},
            ]}), encoding="utf-8")
            (data / "douban-monitor-metadata.json").write_text(json.dumps({
                "1": {"overview": "Cached synopsis", "poster_path": "/poster.jpg"},
                "4": {"overview": "Favorite synopsis"},
            }), encoding="utf-8")
            (data / "douban-monitor-reviews.json").write_text(json.dumps({
                "1": [{"user": "Reader", "comment": "Cached review", "rating": 4}],
            }), encoding="utf-8")
            self.assertEqual(generate_feeds(root), {"movie": 2, "tv": 1, "variety": 1, "all": 4})
            body = ET.parse(data / "rss/movie.xml").findtext("channel/item/description")
            self.assertIn("Cached synopsis", body)
            self.assertIn("Cached review", body)
            self.assertIn("https://image.tmdb.org/t/p/w500/poster.jpg", body)
            for category in CATEGORIES:
                feed = ET.parse(data / "rss" / f"{category}.xml")
                self.assertTrue(feed.findtext("channel/title"))
                for entry in feed.findall("channel/item"):
                    if category != "all":
                        self.assertEqual(entry.findtext("category"), CATEGORIES[category])
            result["qualified"] = result["qualified"][:1]
            result_path.write_text(json.dumps(result), encoding="utf-8")
            generate_feeds(root)
            self.assertEqual(ET.parse(data / "rss/tv.xml").findall("channel/item"), [])

    def test_full_html_content_images_and_escaping(self):
        item = {"douban_id": "1", "title": "A & B", "category": "movie", "year": "2018",
                "rating": 8.5, "rating_count": 162344}
        meta = {"original_title": "Original title", "overview": '<script>alert(1)</script>\n第二段',
                "poster_path": "/poster.jpg", "runtime": 133, "countries": ["美国"],
                "genres": ["西部", "喜剧"], "director": "某导演", "release_date": "2018-11-09",
                "cast": [{"name": "主演", "character": '<角色>', "profile_path": "/actor.jpg"},
                         {"name": "无照片演员", "profile_path": "javascript:alert(1)"}],
                "stills": ["/still.jpg", "/still.jpg", "https://example.org/scene.jpg",
                           "javascript:alert(1)"]}
        review = {"user": "Reader & friend", "comment": '<img src=x onerror=alert(1)>\n第二行',
                  "rating": 4, "date": "2018-11-19"}
        feed = ET.fromstring(render_feed([item], "movie", None, metadata={"1": meta},
                                        reviews={"1": [review]}))
        entry = feed.find("channel/item")
        body = entry.findtext(f"{{{CONTENT}}}encoded")
        self.assertEqual(entry.findtext("description"), body)
        # Parse HTML's XML-compatible subset to verify actual tags and escaping,
        # rather than just checking that keywords appear somewhere in the XML.
        html = ET.fromstring("<article>" + body + "</article>")
        self.assertEqual([h.text for h in html.findall("h2")], ["剧情简介", "剧照", "豆瓣短评"])
        self.assertEqual(len(html.findall(".//img")), 3)
        self.assertEqual(len(html.findall(".//blockquote")), 1)
        self.assertEqual(html.findall(".//blockquote/p")[1].find("br").tail, "第二行")
        self.assertIsNone(html.find(".//script"))
        self.assertNotIn("javascript:", body)
        self.assertNotIn("主演", body)
        self.assertNotIn("角色", body)
        self.assertNotIn("actor.jpg", body)
        self.assertNotIn("无照片演员", body)
        self.assertIn("★★★★☆", body)
        self.assertIn("133分钟", body)
        self.assertIn("162344", body)
        for image in html.findall(".//img"):
            self.assertTrue(image.get("src").startswith("https://"))

    def test_missing_enrichment_still_has_readable_content(self):
        feed = ET.fromstring(render_feed([{"douban_id": "1", "title": "Minimal", "category": "tv"}],
                                        "all", None))
        body = feed.findtext("channel/item/description")
        html = ET.fromstring("<article>" + body + "</article>")
        self.assertEqual(html.findall("h2"), [])
        self.assertEqual(html.findall(".//img"), [])
        self.assertIn("豆瓣评分：暂无", body)
        self.assertIn("评分人数：暂无", body)
        self.assertEqual(len(html.findall(".//a")), 2)

    def test_stable_identity_dates_order_and_xml_escaping(self):
        items = [
            {"douban_id": "1", "category": "movie", "title": "A & <B>\x00",
             "qualified_at": "2026-10-01T09:00:00+08:00", "rating": 8.0, "rating_count": 3001},
            {"douban_id": "2", "category": "movie", "title": "Undated"},
            {"douban_id": "3", "category": "movie", "title": "Newest",
             "qualified_at": "2026-11-01T09:00:00+08:00"},
        ]
        first = ET.fromstring(render_feed(items, "all", "2026-11-11T09:00:00+08:00"))
        entries = first.findall("channel/item")
        self.assertEqual([e.findtext("title") for e in entries], ["Newest", "A & <B>", "Undated"])
        self.assertIn("3001", entries[1].findtext("description"))
        self.assertIsNone(entries[2].find("pubDate"))
        self.assertEqual(entries[1].findtext("pubDate"), "Thu, 01 Oct 2026 09:00:00 +0800")
        items[0]["rating"] = 8.5
        second = ET.fromstring(render_feed(items, "all", "2026-11-12T09:00:00+08:00"))
        self.assertEqual([e.findtext("guid") for e in entries],
                         [e.findtext("guid") for e in second.findall("channel/item")])
        self.assertEqual(entries[1].find("guid").get("isPermaLink"), "false")


if __name__ == "__main__":
    unittest.main()
