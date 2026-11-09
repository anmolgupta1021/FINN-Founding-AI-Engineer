import json
from pathlib import Path

from finn.pipeline.classify import classify_announcements, classify_by_rule, score_priority

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EVAL_FILE = Path(__file__).resolve().parents[3] / "data" / "eval" / "real_announcements_40_to_label.json"


def test_real_announcements_provenance_and_pdf_urls() -> None:
    snap = json.loads((DATA_DIR / "snapshots" / "announcements" / "announcements.json").read_text())
    prov = snap["provenance"]
    assert prov["total"] >= 400
    assert prov["demo_count"] == 0
    assert prov["with_resolvable_pdf_url"] == prov["total"]
    assert prov["nse_count"] + prov["bse_count"] == prov["total"]

    for item in snap["items"]:
        assert item["source"] in ("nse", "bse")
        assert item["pdf_url"].startswith("http")
        assert item["pdf_url"].lower().endswith(".pdf")
        assert item["is_demo_scenario"] is False


def test_real_40_eval_file_structure() -> None:
    raw = json.loads(EVAL_FILE.read_text())
    assert raw["count"] == 40
    assert len(raw["items"]) == 40
    assert "Uniform random sample without replacement" in raw["sampling_method"]
    res = classify_announcements(raw["items"], router=None, allow_llm=False)
    assert res["total"] == 40
    # 13 positive category rules + 3 noise rules = 16 rule hits; 24 unclassified fall-through are NOT counted as rule hits
    assert res["rule_count"] == 16
    assert res["fallback_count"] == 24
    assert res["rule_count"] + res["fallback_count"] == 40


def test_priority_ordering_material_vs_routine() -> None:
    sample = [
        {
            "id": "1",
            "symbol": "POLYCAB",
            "raw_category": "Outcome of Board Meeting",
            "subject": "Polycab India Limited has submitted to the Exchange, the financial results for the period ended September 30, 2026.",
        },
        {
            "id": "2",
            "symbol": "POLYCAB",
            "raw_category": "Newspaper Publication",
            "subject": "Newspaper Publication of Extract of Unaudited Consolidated Financial Results",
        },
        {
            "id": "3",
            "symbol": "HDFCBANK",
            "raw_category": "ESOP/ESOS/ESPS",
            "subject": "Allotment of 4675598 equity shares under ESOP scheme",
        },
    ]
    c1, _, _ = classify_by_rule(sample[0])
    c2, _, _ = classify_by_rule(sample[1])
    c3, _, _ = classify_by_rule(sample[2])
    assert c1 == "results"
    assert c2 == "results"
    assert c3 == "unclassified"

    p1 = score_priority(sample[0], category="results", has_network_overlap=True)
    p2 = score_priority(sample[1], category="results", has_network_overlap=True)
    p3 = score_priority(sample[2], category="unclassified", has_network_overlap=False)
    assert p1 >= 88
    assert p2 <= 45
    assert p3 <= 12
