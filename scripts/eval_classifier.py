"""Evaluate the 2-stage announcement classifier on the 40 real announcements in
`data/eval/real_announcements_40_to_label.json`.

Reports:
1. Rule vs Bulk-LLM split across all 40 real exchange announcements.
2. Accuracy (overall, Stage-1 rules, and Stage-2 LLM) on all items where `user_label` has been filled in.
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

from finn.llm.router import LLMRouter
from finn.pipeline.classify import classify_announcements

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
EVAL_FILE = ROOT / "data" / "eval" / "real_announcements_40_to_label.json"


def main() -> None:
    for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
        if p.exists():
            load_dotenv(p, override=False)

    raw = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    items = raw["items"]
    router = LLMRouter(DATA_DIR)
    res = classify_announcements(items, router=router, allow_llm=True)
    by_id = {x["id"]: x for x in res["items"]}

    print(f"=== Classifier Split on {res['total']} Fresh Real Exchange Announcements ===")
    print(f"Stage 1 (Deterministic Rules) : {res['rule_count']}/{res['total']} ({res['rule_pct']}%)")
    print(f"Stage 2 (LLM / Unresolved)    : {res['total'] - res['rule_count']}/{res['total']} ({round(100 - res['rule_pct'], 1)}%)")

    labelled = [row for row in items if (row.get("user_label") or "").strip()]
    if not labelled:
        print(
            f"\n0/{len(items)} items currently have `user_label` filled in "
            f"`{EVAL_FILE.relative_to(ROOT)}`."
        )
        print("Once you fill in `user_label`, re-run this script to see exact accuracy against your labels.")
        return

    correct = 0
    rule_total = 0
    rule_correct = 0
    other_total = 0
    other_correct = 0
    mismatches: list[str] = []

    for row in labelled:
        pred = by_id[row["id"]]
        gold_label = row["user_label"].strip()
        is_ok = pred["category"] == gold_label
        if is_ok:
            correct += 1
        if pred["cls_method"] == "rule":
            rule_total += 1
            if is_ok:
                rule_correct += 1
        else:
            other_total += 1
            if is_ok:
                other_correct += 1
        if not is_ok:
            mismatches.append(
                f"  - #{row['idx']} {row['symbol']} ({pred['cls_method']}): "
                f"user_label={gold_label} vs pred={pred['category']} | {row['subject'][:75]}"
            )

    print(f"\n=== Accuracy on {len(labelled)} User-Labelled Real Announcements ===")
    if rule_total:
        print(f"Stage 1 (Rules) accuracy : {rule_correct}/{rule_total} ({round(rule_correct / rule_total * 100, 1)}%)")
    if other_total:
        print(f"Stage 2 (LLM) accuracy   : {other_correct}/{other_total} ({round(other_correct / other_total * 100, 1)}%)")
    print(f"Overall accuracy         : {correct}/{len(labelled)} ({round(correct / len(labelled) * 100, 1)}%)")
    if mismatches:
        print("Disagreements:")
        for m in mismatches:
            print(m)


if __name__ == "__main__":
    main()
