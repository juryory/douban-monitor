"""Fetch hot short reviews from Douban Frodo API."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))
from monitor import frodo_get

DATA_DIR = _ROOT / "data"
RESULT_FILE = DATA_DIR / "douban-monitor-result.json"
REVIEWS_FILE = DATA_DIR / "douban-monitor-reviews.json"


def _fetch_reviews(douban_id: str) -> list[dict]:
    """Fetch up to 6 hot short reviews for a subject."""
    for ep in (f"/movie/{douban_id}/interests", f"/tv/{douban_id}/interests"):
        try:
            data = frodo_get(ep, params={
                "count": 6,
                "order_by": "hot",
                "status": "done",
            })
            interests = data.get("interests") or []
            reviews: list[dict] = []
            for it in interests:
                comment = (it.get("comment") or "").strip()
                if not comment:
                    continue
                user_info = it.get("user") or {}
                rating_obj = it.get("rating") or {}
                reviews.append({
                    "user": user_info.get("name", ""),
                    "rating": int(rating_obj["value"]) if rating_obj.get("value") else None,
                    "comment": comment,
                    "date": (it.get("create_time") or "")[:10],
                })
            if reviews:
                return reviews
        except Exception:
            continue
    return []


def main() -> None:
    text = RESULT_FILE.read_text(encoding="utf-8").strip() if RESULT_FILE.exists() else ""
    if not text:
        print(f"{RESULT_FILE} 缺失或为空，跳过短评抓取")
        return
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"{RESULT_FILE} 解析失败（{e}），跳过短评抓取")
        return
    items = result.get("qualified", [])

    seen: set[str] = set()
    unique = []
    for item in items:
        did = item.get("douban_id")
        if did and did not in seen:
            seen.add(did)
            unique.append(item)

    reviews: dict[str, list] = {}
    if REVIEWS_FILE.exists():
        text = REVIEWS_FILE.read_text(encoding="utf-8").strip()
        if text:
            try:
                reviews = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                reviews = {}

    total = len(unique)
    for i, item in enumerate(unique):
        did = item["douban_id"]
        title = item["title"]
        prefix = f"[{i+1}/{total}]"

        if did in reviews:
            mark = "✓" if reviews[did] else "∅"
            print(f"{prefix} skip {mark} {title}")
            continue

        print(f"{prefix} {title}", end="  ", flush=True)
        revs = _fetch_reviews(did)
        reviews[did] = revs
        time.sleep(0.5)
        print(f"{len(revs)} 条短评" if revs else "(无短评)")

    REVIEWS_FILE.write_text(
        json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    found = sum(1 for v in reviews.values() if v)
    print(f"\n完成：{found}/{len(reviews)} 条有短评，保存至 {REVIEWS_FILE}")


if __name__ == "__main__":
    main()
