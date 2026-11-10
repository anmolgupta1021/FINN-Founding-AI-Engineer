"""Batch-classify remaining unclassified filings (`cls_method == 'fallback'`) using Bulk LLM.

Takes all announcements where `cls_method == 'fallback'`, batches them into chunks
of 20, queries Gemini Bulk tier via `LLMRouter`, records every call in
`llm_ledger.jsonl` and `llm_cache.json`, and updates `announcements.json` and
its `cls_method_breakdown` metadata.

Usage:
    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/classify_remaining.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
SNAP_PATH = DATA_DIR / "snapshots" / "announcements" / "announcements.json"

for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
    if p.exists():
        load_dotenv(p, override=False)

from finn.llm.router import LLMRouter, _resolve_in_memory_key  # noqa: E402
from finn.pipeline.classify import (  # noqa: E402
    CATEGORIES,
    LLM_CLS_SYSTEM,
    score_priority,
    summarize_one_line,
)
from finn.store import get_contacts  # noqa: E402

BATCH_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "summary_1l": {"type": "STRING"},
                },
                "required": ["id", "category", "summary_1l"],
            },
        }
    },
    "required": ["items"],
}


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _resolve_in_memory_key()
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set in environment or in-memory.")
        sys.exit(1)
    if not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = api_key

    data = json.loads(SNAP_PATH.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = data.get("items", [])

    contacts = get_contacts(DATA_DIR).get("contacts", [])
    net_syms = {
        str(af.get("symbol") or "").upper()
        for ct in contacts
        for af in (ct.get("affiliations") or [])
        if af.get("symbol")
    }

    unclassified = [it for it in items if it.get("cls_method") == "fallback"]
    print(f"Total announcements: {len(items)}")
    print(f"Unclassified (fallback) announcements to process: {len(unclassified)}")

    if not unclassified:
        counts = Counter(it.get("cls_method") for it in items)
        data["cls_method_breakdown"] = {
            "rule": counts.get("rule", 0),
            "llm": counts.get("llm", 0),
            "fallback": counts.get("fallback", 0),
            "total": len(items),
        }
        SNAP_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"No fallback announcements remaining! Breakdown: {data['cls_method_breakdown']}")
        return

    router = LLMRouter(DATA_DIR)
    batch_size = 20
    batches = [unclassified[i : i + batch_size] for i in range(0, len(unclassified), batch_size)]
    print(f"Processing {len(unclassified)} items across {len(batches)} batches of {batch_size}...")

    total_in_tokens = 0
    total_out_tokens = 0
    total_thinking_tokens = 0
    total_cost_usd = 0.0
    total_cost_inr = 0.0
    newly_classified = 0

    for b_idx, batch in enumerate(batches, start=1):
        print(f"[{b_idx}/{len(batches)}] Classifying batch of {len(batch)} items...")
        payload = [
            {
                "id": str(it["id"]),
                "symbol": it.get("symbol", ""),
                "raw_category": it.get("raw_category", ""),
                "subject": it.get("subject", ""),
            }
            for it in batch
        ]
        res: dict[str, Any] = {}
        try:
            res = router.generate(
                task="classify_announcements_batch",
                tier="bulk",
                source_kind="public_filing",
                prompt_version="cls-batch-v1",
                system=LLM_CLS_SYSTEM,
                contents=payload,
                response_schema=BATCH_SCHEMA,
            )
            parsed_items = (res.get("parsed") or {}).get("items") or []
            if not parsed_items and res.get("text"):
                try:
                    parsed_items = (json.loads(res["text"]) or {}).get("items") or []
                except json.JSONDecodeError:
                    parsed_items = []
            by_id = {str(x.get("id")): x for x in parsed_items if isinstance(x, dict)}

            in_tok = int(res.get("in_tokens", 0))
            out_tok = int(res.get("out_tokens", 0))
            think_tok = int(res.get("thinking_tokens", 0))
            cost_u = float(res.get("cost_usd", 0.0))
            cost_i = float(res.get("cost_inr", 0.0))
            if not res.get("cache_hit", False):
                total_in_tokens += in_tok
                total_out_tokens += out_tok
                total_thinking_tokens += think_tok
                total_cost_usd += cost_u
                total_cost_inr += cost_i

            mapped = 0
            for it in batch:
                aid = str(it["id"])
                hit = by_id.get(aid)
                cat = hit.get("category") if hit else None
                if cat in CATEGORIES:
                    sym = str(it.get("symbol") or "")
                    it["category"] = cat
                    it["cls_method"] = "llm"
                    it["cls_rule"] = str(res.get("model") or "gemini-3.5-flash-lite")
                    it["cls_confidence"] = 0.80
                    it["priority"] = score_priority(it, category=cat, has_network_overlap=sym in net_syms)
                    it["summary_1l"] = (hit.get("summary_1l") if hit else None) or summarize_one_line(it, category=cat)
                    mapped += 1
                    newly_classified += 1
            print(
                f"   -> Batch {b_idx} done (model={res.get('model')}, hit={res.get('cache_hit')}, "
                f"{in_tok} in, {out_tok} out, ₹{cost_i:.4f}, mapped {mapped}/{len(batch)})"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"   -> Batch {b_idx} failed: {exc}")

        if b_idx < len(batches) and not res.get("cache_hit", False):
            time.sleep(4.2)

    data["items"] = items
    counts = Counter(it.get("cls_method") for it in items)
    data["cls_method_breakdown"] = {
        "rule": counts.get("rule", 0),
        "llm": counts.get("llm", 0),
        "fallback": counts.get("fallback", 0),
        "total": len(items),
    }
    SNAP_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("\nUpdated announcements.json successfully!")
    print(f"Newly classified by LLM: {newly_classified}/{len(unclassified)}")
    print(f"Final cls_method breakdown (776): {json.dumps(data['cls_method_breakdown'])}")
    print(
        f"Stage-2 remaining spend (live calls): {total_in_tokens} in tokens, {total_out_tokens} out tokens, "
        f"{total_thinking_tokens} thinking tokens, ${total_cost_usd:.6f} (₹{total_cost_inr:.4f})"
    )


if __name__ == "__main__":
    main()
