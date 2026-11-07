"""Offline regression tests for cumulative display assets and manual favorites."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asset_cache
import fetch_favorites
import fetch_metadata
import fetch_posters
import fetch_reviews
import generate_detail_pages


def work(did, **fields):
    return {"douban_id": did, "title": f"Work {did}", "category": "movie", **fields}


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.retries_path = self.root / "asset-retries.json"
        self.addCleanup(patch.stopall)
        patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden in offline tests")).start()
        patch("time.sleep").start()

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def setup_module(self, module, **files):
        for key, data in files.items():
            patch.object(module, key, self.write(key + ".json", data)).start()
        patch.object(module, "AssetRetryCache", lambda: asset_cache.AssetRetryCache(self.retries_path)).start()

    def run_main(self, module):
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()

    def test_retry_cooldown_survives_restart_and_is_per_asset(self):
        operation = Mock(return_value=None)
        first = asset_cache.AssetRetryCache(self.retries_path)
        first.fetch("poster", "1", operation)
        restarted = asset_cache.AssetRetryCache(self.retries_path)
        restarted.fetch("poster", "1", operation)
        self.assertEqual(operation.call_count, 1)
        restarted.fetch("metadata", "1", operation)
        self.assertEqual(operation.call_count, 2)

    def test_posters_reuse_hidden_cache_and_isolate_failure(self):
        self.setup_module(fetch_posters,
                          RESULT_FILE={"qualified": [work("1"), work("2"), work("3")]},
                          POSTERS_FILE={"1": "cached", "9": "hidden"})

        def fetch(item, metadata, config):
            if item["douban_id"] == "2":
                raise RuntimeError("one item failed")
            return "new"

        request = patch.object(fetch_posters, "_fetch_poster", side_effect=fetch).start()
        self.run_main(fetch_posters)
        self.run_main(fetch_posters)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.read(fetch_posters.POSTERS_FILE), {"1": "cached", "9": "hidden", "3": "new"})

    def test_metadata_failure_keeps_old_fields_and_other_items(self):
        self.setup_module(fetch_metadata,
                          RESULT_FILE={"qualified": [work("1"), work("2"), work("3")]},
                          META_FILE={"1": {"backdrop_path": "cached"}, "2": {"overview": "old"}, "9": {"overview": "hidden"}})
        request = patch.object(fetch_metadata, "_fetch_metadata", side_effect=[{}, {"overview": "new", "backdrop_path": ""}]).start()
        self.run_main(fetch_metadata)
        self.run_main(fetch_metadata)
        self.assertEqual(request.call_count, 2)
        values = self.read(fetch_metadata.META_FILE)
        self.assertEqual(values["2"], {"overview": "old"})
        self.assertEqual(values["3"]["overview"], "new")
        self.assertEqual(values["9"], {"overview": "hidden"})
        self.assertEqual(asset_cache.preserve_valid({"overview": "old"}, {"overview": "", "runtime": 100}),
                         {"overview": "old", "runtime": 100})

    def test_reviews_merge_favorites_and_preserve_hidden_cache(self):
        self.setup_module(fetch_reviews,
                          RESULT_FILE={"qualified": [work("1"), work("2"), work("3")]},
                          FAVORITES_FILE={"qualified": [work("1"), work("4")]},
                          REVIEWS_FILE={"1": [{"comment": "cached"}], "9": [{"comment": "hidden"}]})
        request = patch.object(fetch_reviews, "_fetch_reviews", side_effect=[[], [{"comment": "new"}], [{"comment": "favorite"}]]).start()
        self.run_main(fetch_reviews)
        self.run_main(fetch_reviews)
        self.assertEqual(request.call_count, 3)
        values = self.read(fetch_reviews.REVIEWS_FILE)
        self.assertEqual(values["9"], [{"comment": "hidden"}])
        self.assertEqual(values["4"], [{"comment": "favorite"}])

    def test_favorites_accept_json_array_dedupe_and_keep_valid_data_on_failure(self):
        previous = [work("1", rating=8.5, rating_count=5000), work("2", rating=8.8, rating_count=6000)]
        self.setup_module(fetch_favorites,
                          FAVORITES_FILE=["1", "1", "2", "3"],
                          FAVORITES_RESULT_FILE={"qualified": previous},
                          RESULT_FILE={"qualified": [work("3")]},
                          POSTERS_FILE={"1": "cached", "2": "cached"},
                          META_FILE={"1": {"backdrop_path": "cached"}, "2": {"backdrop_path": "cached"}})
        request = patch.object(fetch_favorites, "_fetch_subject", side_effect=lambda did: None if did == "1" else work("2", rating=None, rating_count=None, year="2020")).start()
        self.run_main(fetch_favorites)
        self.run_main(fetch_favorites)
        self.assertEqual(request.call_count, 3)
        values = self.read(fetch_favorites.FAVORITES_RESULT_FILE)["qualified"]
        self.assertEqual([item["douban_id"] for item in values], ["1", "2"])
        self.assertEqual(values[0]["rating"], 8.5)
        self.assertEqual(values[1]["rating_count"], 6000)
        self.assertEqual(fetch_favorites.FAVORITES_FILE.read_text(encoding="utf-8"), "1\n2\n")

    def test_restored_detail_generates_with_missing_count_and_bad_item_isolated(self):
        for key, value in {
            "RESULT_FILE": {"qualified": [work("1", rating=8.0, rating_count=None), work("2"), work("3", qualified_at="2020-01-01")]},
            "FAVORITES_FILE": {"qualified": []}, "METADATA_FILE": {}, "POSTERS_FILE": {}, "LIBRARY_FILE": {"items": {}}
        }.items():
            patch.object(generate_detail_pages, key, self.write(key + ".json", value)).start()
        detail_dir = self.root / "detail"
        detail_dir.mkdir()
        (detail_dir / "9.html").write_text("hidden page", encoding="utf-8")
        patch.object(generate_detail_pages, "DETAIL_DIR", detail_dir).start()
        original = generate_detail_pages.generate_detail_html

        def generate(item, metadata, posters):
            if item["douban_id"] == "2":
                raise ValueError("one item failed")
            return original(item, metadata, posters)

        patch.object(generate_detail_pages, "generate_detail_html", side_effect=generate).start()
        self.run_main(generate_detail_pages)
        self.assertIn("../#detail/1", (detail_dir / "1.html").read_text(encoding="utf-8"))
        self.assertTrue((detail_dir / "3.html").exists())
        self.assertEqual((detail_dir / "9.html").read_text(encoding="utf-8"), "hidden page")


if __name__ == "__main__":
    unittest.main()
