"""Content-hash cache for LLM calls (keyed by sha256 of canonical request spec)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def compute_cache_key(
    *,
    model: str,
    prompt_version: str,
    system: str,
    contents: Any,
    response_schema: dict[str, Any] | None = None,
    thinking_budget: int = 0,
) -> str:
    canonical = json.dumps(
        {
            "model": model,
            "prompt_version": prompt_version,
            "system": system,
            "contents": contents,
            "response_schema": response_schema,
            "thinking_budget": thinking_budget,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ContentHashCache:
    """Simple JSON file cache committed under apps/api/data/snapshots/llm_cache.json."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._store: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._store is None:
            if self.path.exists():
                try:
                    self._store = json.loads(self.path.read_text())
                except json.JSONDecodeError:
                    self._store = {}
            else:
                self._store = {}
        return self._store

    def get(self, key: str) -> dict[str, Any] | None:
        return self._load().get(key)

    def put(self, key: str, entry: dict[str, Any]) -> None:
        store = self._load()
        store[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(store, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
