"""Shared retry cooldown for missing display assets (separate from score checks)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Any


class AssetRetryCache:
    """Keep failed asset lookups from replaying the entire historical backlog."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(__file__).resolve().parent.parent / "data" / "douban-monitor-asset-retries.json"
        self.entries: dict = {}
        if self.path.exists():
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))

    def fetch(self, kind: str, douban_id: str, operation: Callable[[], Any]) -> Any:
        key = f"{kind}:{douban_id}"
        now = datetime.now(timezone.utc)
        retry_at = self.entries.get(key, {}).get("retry_after")
        if retry_at and datetime.fromisoformat(retry_at) > now:
            return None
        try:
            result = operation()
        except Exception as exc:
            print(f"  [{kind}] {douban_id} 获取失败：{exc}")
            result = None
        if result:
            self.entries.pop(key, None)
        else:
            self.entries[key] = {"retry_after": (now + timedelta(days=7)).isoformat()}
        # Persist each attempt so a later item failing cannot lose the cooldown.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)
        return result


def preserve_valid(existing: dict, incoming: dict) -> dict:
    """A sparse response must not replace already useful metadata with blanks."""
    return {**existing, **{k: v for k, v in incoming.items()
                          if v not in (None, "", [], {}) or k not in existing}}
