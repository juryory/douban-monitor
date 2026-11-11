"""Offline checks for feed categories, dates, identity and regeneration."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_rss import CATEGORIES, generate_feeds, render_feed


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
            self.assertEqual(generate_feeds(root), {"movie": 2, "tv": 1, "variety": 1, "all": 4})
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
