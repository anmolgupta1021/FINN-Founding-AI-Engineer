import json
from pathlib import Path

from finn.pipeline.classify import classify_announcements, classify_by_rule, score_priority

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_rules_precision_and_split_on_gold_30() -> None:
    gold = json.loads((DATA_DIR / "seed" / "classifier_gold_30.json").read_text())["items"]
    assert len(gold) == 30

    rule_hits = 0
    for row in gold:
        cat, conf, _ = classify_by_rule(row)
        if cat is not None:
            rule_hits += 1
            assert conf >= 0.90
            assert cat == row["expected_category"], f"Rule mismatch on {row['id']}: {cat} != {row['expected_category']}"

    # Rules handle 25/30 (83.3%) with 100% precision; 5 ambiguous Reg-30 items defer to Stage 2 LLM
    assert rule_hits == 25


def test_priority_ordering_material_vs_routine() -> None:
    gold = json.loads((DATA_DIR / "seed" / "classifier_gold_30.json").read_text())["items"]
    res = classify_announcements(gold, router=None, network_symbols={"KAYNES", "POLYCAB"}, allow_llm=False)
    by_id = {x["id"]: x for x in res["items"]}

    # Material CFO appointment at network-overlap stock ranks at top (> 90)
    assert by_id["g03"]["priority"] >= 90
    # Actual Q2 results outcome ranks much higher than newspaper publication of extract of results
    assert by_id["g01"]["priority"] >= 88
    assert by_id["g27"]["priority"] <= 40
    # Routine filings (ESOP, loss of shares, Reg 74(5), trading window) stay <= 12
    for rid in ("g22", "g23", "g24", "g25", "g26", "g30"):
        assert by_id[rid]["category"] == "unclassified"
        assert by_id[rid]["priority"] <= 12

    # Score boost for network overlap works
    p_no_net = score_priority(by_id["g05"], category="capex", has_network_overlap=False)
    p_with_net = score_priority(by_id["g05"], category="capex", has_network_overlap=True)
    assert p_with_net == p_no_net + 6
