"""Evaluate the 2-stage announcement classifier on the 40 uniformly random real announcements in
`data/eval/real_announcements_40_to_label.json`.

Guarantees:
1. The 40-item sample is drawn uniformly at random (`random.Random(42).sample`) across all 776 real NSE/BSE filings,
   NOT stratified by predicted category and NOT hand-picked.
2. Unclassified fall-through (`cls_method == "fallback"`) is NEVER counted as a rule hit.
   Even explicit noise-filter matches (`cls_rule == "noise_loss_of_shares_or_reg74"`) are reported separately from
   positive-category rule hits (`category != "unclassified"`).
3. Accuracy is reported strictly on `user_label` once provided by the user.
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

    total = res["total"]
    pos_rule_hits = [
        x for x in res["items"] if x["cls_method"] == "rule" and x["category"] != "unclassified"
    ]
    noise_rule_hits = [
        x for x in res["items"] if x["cls_method"] == "rule" and x["category"] == "unclassified"
    ]
    llm_hits = [x for x in res["items"] if x["cls_method"] == "llm"]
    fallthrough_unclassified = [x for x in res["items"] if x["cls_method"] == "fallback"]

    print(f"=== Classifier Coverage on {total} Uniformly Random Real Announcements (seed=42) ===")
    print(
        f"Stage 1 Positive Category Rules : {len(pos_rule_hits)}/{total} "
        f"({round(len(pos_rule_hits) / total * 100, 1)}%)"
    )
    print(
        f"Stage 1 Explicit Noise Rule     : {len(noise_rule_hits)}/{total} "
        f"({round(len(noise_rule_hits) / total * 100, 1)}%)"
    )
    print(
        f"Stage 2 Bulk LLM Classified     : {len(llm_hits)}/{total} "
        f"({round(len(llm_hits) / total * 100, 1)}%)"
    )
    print(
        f"Unclassified Fall-Through       : {len(fallthrough_unclassified)}/{total} "
        f"({round(len(fallthrough_unclassified) / total * 100, 1)}%) [NOT counted as rule hits]"
    )

    labelled = [row for row in items if (row.get("user_label") or "").strip()]
    if not labelled:
        print(
            f"\n0/{len(items)} items currently have `user_label` filled in "
            f"`{EVAL_FILE.relative_to(ROOT)}`."
        )
        print("Once you fill in `user_label`, re-run this script to see exact accuracy against your labels.")
        return

    correct = 0
    pos_rule_total = 0
    pos_rule_correct = 0
    noise_rule_total = 0
    noise_rule_correct = 0
    llm_total = 0
    llm_correct = 0
    fallthrough_total = 0
    fallthrough_correct = 0
    mismatches: list[str] = []

    for row in labelled:
        pred = by_id[row["id"]]
        gold_label = row["user_label"].strip()
        is_ok = pred["category"] == gold_label
        if is_ok:
            correct += 1

        if pred["cls_method"] == "rule" and pred["category"] != "unclassified":
            pos_rule_total += 1
            if is_ok:
                pos_rule_correct += 1
        elif pred["cls_method"] == "rule" and pred["category"] == "unclassified":
            noise_rule_total += 1
            if is_ok:
                noise_rule_correct += 1
        elif pred["cls_method"] == "llm":
            llm_total += 1
            if is_ok:
                llm_correct += 1
        else:
            fallthrough_total += 1
            if is_ok:
                fallthrough_correct += 1

        if not is_ok:
            mismatches.append(
                f"  - #{row['idx']} {row['symbol']} ({pred['cls_method']}/{pred.get('cls_rule')}): "
                f"user_label={gold_label} vs pred={pred['category']} | {row['subject'][:75]}"
            )

    print(f"\n=== Accuracy on {len(labelled)} User-Labelled Real Announcements ===")
    if pos_rule_total:
        print(
            f"Positive Category Rules accuracy : {pos_rule_correct}/{pos_rule_total} "
            f"({round(pos_rule_correct / pos_rule_total * 100, 1)}%)"
        )
    if noise_rule_total:
        print(
            f"Explicit Noise Rule accuracy     : {noise_rule_correct}/{noise_rule_total} "
            f"({round(noise_rule_correct / noise_rule_total * 100, 1)}%)"
        )
    if llm_total:
        print(
            f"Stage 2 (LLM) accuracy           : {llm_correct}/{llm_total} "
            f"({round(llm_correct / llm_total * 100, 1)}%)"
        )
    if fallthrough_total:
        print(
            f"Fall-through (no rule/no LLM)    : {fallthrough_correct}/{fallthrough_total} "
            f"({round(fallthrough_correct / fallthrough_total * 100, 1)}%)"
        )
    print(
        f"Overall accuracy                 : {correct}/{len(labelled)} "
        f"({round(correct / len(labelled) * 100, 1)}%)"
    )
    if mismatches:
        print("Disagreements:")
        for m in mismatches:
            print(m)


if __name__ == "__main__":
    main()
