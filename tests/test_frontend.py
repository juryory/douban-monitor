"""Run the real page scripts with local JSON and a minimal DOM, without a browser."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

# The DOM only stores rendered HTML: this checks data loading and rendering,
# while deliberately leaving browser layout and remote image loading out.
HARNESS = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const html = fs.readFileSync(path.join(input.root, 'index.html'), 'utf8');
const elements = new Map();
function element(key) {
  if (!elements.has(key)) elements.set(key, {
    innerHTML: '', textContent: '', value: key === 'sortSelect' ? 'added_desc' : '',
    style: {removeProperty(name) {delete this[name];}},
    classList: {add() {}, remove() {}, toggle() {}},
    addEventListener() {}, setAttribute() {}, removeAttribute() {},
    querySelectorAll() {return [];}
  });
  return elements.get(key);
}
const names = [
  'douban-monitor-result.json', 'douban-monitor-posters.json',
  'douban-monitor-metadata.json', 'douban-monitor-reviews.json',
  'douban-monitor-favorites-result.json'
];
const files = Object.fromEntries(names.map(name => {
  if (Object.hasOwn(input.overrides, name)) return [name, input.overrides[name]];
  const file = path.join(input.root, 'data', name);
  return [name, fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {}];
}));
const fetched = [];
const context = vm.createContext({
  document: {
    getElementById: element, querySelector: element,
    title: ''
  },
  window: {addEventListener() {}, scrollTo() {}, scrollY: 0},
  location: {hash: ''}, history: {back() {}},
  requestAnimationFrame() {}, setTimeout() {return 0;}, clearTimeout() {},
  fetch: async url => {
    // Only these repository JSON files are available. No network API exists here.
    assert.ok(url.startsWith('/data/'), `Unexpected fetch: ${url}`);
    const name = url.slice('/data/'.length);
    assert.ok(names.includes(name), `Unexpected fetch: ${url}`);
    fetched.push(name);
    return {ok: true, json: async () => structuredClone(files[name])};
  }
});
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).join('\n');
// Capture the existing entry point's promise so its caught failures are checked.
assert.match(scripts, /\binit\(\);\s*$/);
const instrumented = scripts.replace(/\binit\(\);\s*$/, 'globalThis.ready = init();');
(async () => {
  vm.runInContext(instrumented, context, {filename: 'index.html'});
  await context.ready;
  assert.equal(element('error').innerHTML, '', 'Page swallowed a render failure');
  const items = vm.runInContext('allItems', context);
  const expectedIds = [...new Set([
    ...(files['douban-monitor-result.json'].qualified || []),
    ...(files['douban-monitor-favorites-result.json'].qualified || [])
  ].map(item => item.douban_id))];
  assert.deepEqual([...items.map(item => item.douban_id)].sort(), expectedIds.sort());
  const gridHtml = element('grid').innerHTML;
  const cardCount = (gridHtml.match(/<div class="card"/g) || []).length;
  assert.equal(cardCount, expectedIds.length, 'A displayed work lost its card');
  // Historical entries must use the same working detail renderer as new entries.
  for (const item of items) {
    context.location.hash = `#detail/${item.douban_id}`;
    context.handleRoute();
    const detail = element('detailView').innerHTML;
    assert.ok(detail.includes('<h1 class="detail-title">'), `No detail for ${item.douban_id}`);
    assert.ok(detail.includes(context.esc(item.title)), `Wrong detail for ${item.douban_id}`);
  }
  context.location.hash = '';
  context.handleRoute();
  process.stdout.write(JSON.stringify({
    card_count: cardCount,
    item_count: items.length,
    expected_count: expectedIds.length,
    detail_count: items.length,
    meta: element('meta').textContent,
    has_missing_value_placeholder: gridHtml.includes('—'),
    has_null_count: gridHtml.includes('null人评'),
    fetched_count: fetched.length
  }));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


@unittest.skipUnless(NODE, "Node.js is optional; install it to run offline frontend regressions")
class FrontendTests(unittest.TestCase):
    def run_page(self, overrides=None):
        process = subprocess.run(
            [NODE, "-e", HARNESS],
            input=json.dumps({"root": str(ROOT), "overrides": overrides or {}}),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_repository_cumulative_list_and_every_detail_render_offline(self):
        output = self.run_page()
        self.assertEqual(output["card_count"], output["expected_count"])
        self.assertEqual(output["detail_count"], output["expected_count"])
        self.assertEqual(output["fetched_count"], 5)
        self.assertIn(f"累计收录 {output['item_count']} 部", output["meta"])

    def test_favorites_dedupe_missing_scores_and_zero_scan_count(self):
        output = self.run_page({
            "douban-monitor-result.json": {
                "run_at": "2026-11-08T09:00:00+08:00", "total": 0,
                "qualified": [
                    {"douban_id": "990000001", "title": "Historical <work>", "category": "movie",
                     "rating": None, "rating_count": None, "year": 2020, "qualified_at": "2020-01-01"},
                    {"douban_id": "990000002", "title": "Missing count", "category": "tv", "rating": 8.0},
                ],
            },
            "douban-monitor-favorites-result.json": {"qualified": [
                {"douban_id": "990000001", "title": "Duplicate favorite", "category": "movie"},
                {"douban_id": "990000003", "title": "Favorite", "category": "movie", "rating": 8.5, "rating_count": 5000},
            ]},
            "douban-monitor-posters.json": {},
            "douban-monitor-metadata.json": {},
            "douban-monitor-reviews.json": {},
        })
        self.assertEqual(output["card_count"], 3)
        self.assertEqual(output["detail_count"], 3)
        self.assertIn("本轮扫描 0 条", output["meta"])
        self.assertNotIn("?", output["meta"])
        self.assertTrue(output["has_missing_value_placeholder"])
        self.assertFalse(output["has_null_count"])


if __name__ == "__main__":
    unittest.main()
