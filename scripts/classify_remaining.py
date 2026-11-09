"""Batch-classify remaining unclassified filings using gemini-3.5-flash-lite.

Takes all announcements where `cls_method == 'fallback'`, batches them into chunks
of 20, queries `gemini-3.5-flash-lite` via `LLMRouter`, records every call in
`llm_ledger.jsonl` and `llm_cache.json`, and updates `announcements.json`.

Usage:
    export GEMINI_API_KEY="AIzaSy..."
    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/classify_remaining.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
SNAP_PATH = DATA_DIR / "snapshots" / "announcements" / "announcements.json"

for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
    if p.exists():
        load_dotenv(p, override=False)

from finn.llm.router import LLMRouter  # noqa: E402
from finn.pipeline.classify import BATCH_CLASSIFY_SYSTEM, format_batch_for_prompt, parse_batch_response  # noqa: E402


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set in environment or .env.local.")
        print("To run, execute: export GEMINI_API_KEY=\"AIzaSy...\" && PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/classify_remaining.py")
        sys.exit(1)

    data = json.loads(SNAP_PATH.read_text(encoding="utf-8"))
    items = data.get("items", [])

    unclassified = [it for it in items if it.get("cls_method") == "fallback"]
    print(f"Total announcements: {len(items)}")
    print(f"Unclassified announcements to process: {len(unclassified)}")

    if not unclassified:
        print("No unclassified announcements remaining!")
        return

    router = LLMRouter(DATA_DIR)
    batch_size = 20
    batches = [unclassified[i : i + batch_size] for i in range(0, len(unclassified), batch_size)]
    print(f"Processing {len(unclassified)} items across {len(batches)} batches of {batch_size}...")

    updated_by_id: dict[str, dict[str, Any]] = {}
    total_in_tokens = 0
    total_out_tokens = 0
    total_cost_inr = 0.0

    for b_idx, batch in enumerate(batches, start=1):
        print(f"[{b_idx}/{len(batches)}] Classifying batch of {len(batch)} items...")
        prompt = format_batch_for_prompt(batch)
        try:
            res = router.generate(
                task="batch_classify_remaining",
                tier="bulk",
                source_kind="announcement_batch",
                prompt_version="batch_cls_v1",
                system=BATCH_CLASSIFY_SYSTEM,
                contents=prompt,
            )
            raw_text = res.get("text", "")
            results_map = parse_batch_response(raw_text)
            in_tok = int(res.get("in_tokens", 0))
            out_tok = int(res.get("out_tokens", 0))
            cost = float(res.get("cost_inr", 0.0))
            total_in_tokens += in_tok
            total_out_tokens += out_tok
            total_cost_inr += cost

            for it in batch:
                aid = it["id"]
                if aid in results_map:
                    cat, prio, summary = results_map[aid]
                    it["category"] = cat
                    it["priority"] = prio
                    it["summary_1l"] = summary
                    it["cls_method"] = "llm"
                    it["cls_rule"] = "gemini-3.5-flash-lite"
                    updated_by_id[aid] = it
            print(f"   -> Batch {b_idx} done ({in_tok} in, {out_tok} out, ₹{cost:.4f}, mapped {len(results_map)} items)")
        except Exception as exc:  # noqa: BLE001
            print(f"   -> Batch {b_idx} failed: {exc}")

        if b_idx < len(batches):
            time.sleep(2.0)

    # Save updated announcements.json
    data["items"] = items
    # Update provenance / metadata
    rule_count = sum(1 for it in items if it.get("cls_method") == "rule")
    llm_count = sum(1 for it in items if it.get("cls_method") == "llm")
    fallback_count = sum(1 for it in items if it.get("cls_method") == "fallback")
    data["cls_method_breakdown"] = {
        "rule": rule_count,
        "llm": llm_count,
        "fallback": fallback_count,
        "total": len(items),
    }
    SNAP_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("\nUpdated announcements.json successfully!")
    print(f"Breakdown: rule={rule_count}, llm={llm_count}, fallback={fallback_count}")
    print(f"Spend: {total_in_tokens} in tokens, {total_out_tokens} out tokens, ₹{total_cost_inr:.4f}")


if __name__ == "__main__":
    main()
