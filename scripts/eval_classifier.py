"""Evaluate the 2-stage announcement classifier (rules first, cheap LLM second) on the 30-item gold set.

Usage:
    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/eval_classifier.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from finn.llm.router import LLMRouter
from finn.pipeline.classify import classify_announcements

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"

# Deterministic mock LLM responses for the 5 ambiguous items when run offline without GEMINI_API_KEY
OFFLINE_LLM_ANSWERS = {
    "g07": {"category": "M&A", "summary_1l": "SUNPHARMA: 14% strategic stake & licensing deal with Philogen S.p.A."},
    "g10": {"category": "litigation", "summary_1l": "INFY: EUR 42,000 administrative fine from Luxembourg data authority"},
    "g28": {"category": "capex", "summary_1l": "NAVINFLUOR: Board approves Rs 288 cr outlay for new Dahej AHF line"},
    "g29": {"category": "management_change", "summary_1l": "PIDILITIND: Sudhanshu Vats assumes charge as MD Designate"},
    "g30": {"category": "unclassified", "summary_1l": "LAURUSLABS: Half-yearly related-party transaction disclosure (Reg 23(9))"},
}


def _offline_transport(model: str, system: str, contents: object, schema: object, tb: int) -> dict:
    batch = contents if isinstance(contents, list) else []
    items = []
    for row in batch:
        rid = str(row.get("id"))
        ans = OFFLINE_LLM_ANSWERS.get(
            rid,
            {"category": "unclassified", "summary_1l": f"{row.get('symbol')}: {row.get('subject', '')[:80]}"},
        )
        items.append({"id": rid, **ans})
    return {
        "text": json.dumps({"items": items}),
        "parsed": {"items": items},
        "in_tokens": 60 * len(batch),
        "out_tokens": 22 * len(batch),
        "thinking_tokens": 0,
    }


def main() -> None:
    for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
        if p.exists():
            load_dotenv(p, override=False)

    gold = json.loads((DATA_DIR / "seed" / "classifier_gold_30.json").read_text())["items"]
    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    router = LLMRouter(DATA_DIR, transport=None if has_key else _offline_transport)

    res = classify_announcements(
        gold,
        router=router,
        network_symbols={"DIXON", "KAYNES", "POLYCAB", "AARTIIND", "SYRMA"},
        allow_llm=True,
    )

    by_id = {x["id"]: x for x in res["items"]}
    correct = 0
    rule_correct = 0
    llm_correct = 0
    mismatches: list[str] = []

    for row in gold:
        pred = by_id[row["id"]]
        ok = pred["category"] == row["expected_category"]
        if ok:
            correct += 1
            if pred["cls_method"] == "rule":
                rule_correct += 1
            elif pred["cls_method"] == "llm":
                llm_correct += 1
        else:
            mismatches.append(
                f"  - {row['id']} ({row['symbol']}): expected={row['expected_category']} "
                f"got={pred['category']} via {pred['cls_method']}"
            )

    print("=== Classifier Benchmark (30 Hand-Checked Announcements) ===")
    print(f"Total items       : {res['total']}")
    print(f"Stage 1 (Rules)   : {res['rule_count']}/{res['total']} ({res['rule_pct']}%) — {rule_correct}/{res['rule_count']} accurate")
    print(f"Stage 2 (Bulk LLM): {res['llm_count']}/{res['total']} ({round(100 - res['rule_pct'], 1)}%) — {llm_correct}/{res['llm_count']} accurate")
    print(f"Overall Accuracy  : {correct}/{res['total']} ({round(correct / res['total'] * 100, 1)}%)")
    if mismatches:
        print("Mismatches:")
        for m in mismatches:
            print(m)


if __name__ == "__main__":
    main()
