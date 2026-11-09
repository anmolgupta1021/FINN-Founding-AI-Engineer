"""Re-verify all citations across all 6 dossiers with strict rules:
  1. rapidfuzz.fuzz.partial_ratio >= 90.0
  2. Every numerical token in the quote MUST appear on the cited page.

Reports exact verification results and any dropped claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from finn.pull.chunker import fetch_company_primary_corpus
from finn.pull.verifier import NOT_FOUND_IN_FILINGS, verify_citation

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
DOSSIERS_DIR = DATA_DIR / "snapshots" / "dossiers"
CACHE_ROOT = ROOT / ".cache" / "pull_docs"

TARGET_SYMBOLS = ["DIXON", "SYRMA", "NAVINFLUOR", "POLYCAB", "HDFCBANK", "TITAN"]


def reverify_dossier(symbol: str) -> dict[str, Any]:
    dossier_path = DOSSIERS_DIR / f"{symbol}.json"
    if not dossier_path.exists():
        return {"symbol": symbol, "error": "file_not_found"}

    dossier = json.loads(dossier_path.read_text())
    corpus = fetch_company_primary_corpus(symbol, CACHE_ROOT)
    docs_by_id = corpus["docs_by_id"]

    total_citations = 0
    passed_citations = 0
    dropped_citations: list[dict[str, Any]] = []

    # 1. Segment mix
    new_segments = []
    for s in dossier.get("segment_mix", []):
        total_citations += 1
        v = verify_citation(s.get("citation"), docs_by_id, min_score=90.0)
        if v["verified"]:
            passed_citations += 1
            s["citation"] = v
            new_segments.append(s)
        else:
            dropped_citations.append({"type": "segment_mix", "item": s, "reason": v.get("reason"), "missing": v.get("missing_numbers")})
    dossier["segment_mix"] = new_segments

    # 2. AR highlights
    new_ar = []
    for a in dossier.get("ar_highlights", []):
        total_citations += 1
        v = verify_citation(a.get("citation"), docs_by_id, min_score=90.0)
        if v["verified"]:
            passed_citations += 1
            a["citation"] = v
            new_ar.append(a)
        else:
            dropped_citations.append({"type": "ar_highlights", "item": a, "reason": v.get("reason"), "missing": v.get("missing_numbers")})
    dossier["ar_highlights"] = new_ar

    # 3. Promised vs Delivered
    new_pvd = []
    for row in dossier.get("promised_vs_delivered", []):
        p_cit = row.get("promised_citation")
        if p_cit:
            total_citations += 1
            v_p = verify_citation(p_cit, docs_by_id, min_score=90.0)
            if v_p["verified"]:
                passed_citations += 1
                row["promised_citation"] = v_p
            else:
                dropped_citations.append({"type": "pvd_promised", "topic": row.get("topic"), "quote": p_cit.get("verbatim_quote"), "reason": v_p.get("reason"), "missing": v_p.get("missing_numbers")})
                row["promised_citation"] = None
                row["promised_guidance"] = NOT_FOUND_IN_FILINGS

        d_cit = row.get("delivered_citation")
        if d_cit:
            total_citations += 1
            v_d = verify_citation(d_cit, docs_by_id, min_score=90.0)
            if v_d["verified"]:
                passed_citations += 1
                row["delivered_citation"] = v_d
            else:
                dropped_citations.append({"type": "pvd_delivered", "topic": row.get("topic"), "quote": d_cit.get("verbatim_quote"), "reason": v_d.get("reason"), "missing": v_d.get("missing_numbers")})
                row["delivered_citation"] = None

        new_pvd.append(row)
    dossier["promised_vs_delivered"] = new_pvd

    # 4. Numbers vs Narrative
    new_nvn = []
    for n in dossier.get("numbers_vs_narrative", []):
        total_citations += 1
        v = verify_citation(n.get("citation"), docs_by_id, min_score=90.0)
        if v["verified"]:
            passed_citations += 1
            n["citation"] = v
            new_nvn.append(n)
        else:
            dropped_citations.append({"type": "nvn", "title": n.get("check_title"), "quote": n.get("citation", {}).get("verbatim_quote"), "reason": v.get("reason"), "missing": v.get("missing_numbers")})
    dossier["numbers_vs_narrative"] = new_nvn

    # 5. Bull case
    new_bull = []
    for b in dossier.get("bull_case", []):
        total_citations += 1
        v = verify_citation(b.get("citation"), docs_by_id, min_score=90.0)
        if v["verified"]:
            passed_citations += 1
            b["citation"] = v
            new_bull.append(b)
        else:
            dropped_citations.append({"type": "bull_case", "title": b.get("title"), "quote": b.get("citation", {}).get("verbatim_quote"), "reason": v.get("reason"), "missing": v.get("missing_numbers")})
    dossier["bull_case"] = new_bull

    # 6. Bear case
    new_bear = []
    for b in dossier.get("bear_case", []):
        total_citations += 1
        v = verify_citation(b.get("citation"), docs_by_id, min_score=90.0)
        if v["verified"]:
            passed_citations += 1
            b["citation"] = v
            new_bear.append(b)
        else:
            dropped_citations.append({"type": "bear_case", "title": b.get("title"), "quote": b.get("citation", {}).get("verbatim_quote"), "reason": v.get("reason"), "missing": v.get("missing_numbers")})
    dossier["bear_case"] = new_bear

    # Update verification summary in dossier
    all_scores = []
    for obj_list in (dossier.get("segment_mix", []), dossier.get("ar_highlights", []), dossier.get("numbers_vs_narrative", []), dossier.get("bull_case", []), dossier.get("bear_case", [])):
        for item in obj_list:
            sc = item.get("citation", {}).get("match_score")
            if sc:
                all_scores.append(float(sc))
    for r in dossier.get("promised_vs_delivered", []):
        for ck in ("promised_citation", "delivered_citation"):
            sc = (r.get(ck) or {}).get("match_score")
            if sc:
                all_scores.append(float(sc))

    dossier["verification_summary"] = {
        "total_documents_verified": len(dossier.get("documents_manifest", [])),
        "concall_transcripts_verified": sum(1 for m in dossier.get("documents_manifest", []) if m.get("doc_type") == "concall_transcript"),
        "latest_call_marked_untestable": any(not r.get("promised_vs_delivered_testable", True) for r in dossier.get("promised_vs_delivered", [])),
        "total_verified_citations": passed_citations,
        "dropped_citations_count": len(dropped_citations),
        "min_rapidfuzz_score": min(all_scores, default=100.0),
        "quote_verification_rule": "rapidfuzz.fuzz.partial_ratio >= 90.0 + all numbers in quote verified present on cited page",
    }

    dossier_path.write_text(json.dumps(dossier, indent=2, ensure_ascii=False) + "\n")

    return {
        "symbol": symbol,
        "total_checked": total_citations,
        "passed": passed_citations,
        "dropped": len(dropped_citations),
        "dropped_details": dropped_citations,
        "min_score": min(all_scores, default=100.0),
    }


def main() -> None:
    results = []
    for sym in TARGET_SYMBOLS:
        res = reverify_dossier(sym)
        results.append(res)
        print(f"[{sym}] total={res['total_checked']}, passed={res['passed']}, dropped={res['dropped']}, min_score={res['min_score']}%")
        if res["dropped"] > 0:
            for d in res["dropped_details"]:
                print(f"   -> Dropped: {d}")

    print("\nSummary:")
    print(json.dumps([{k: v for k, v in r.items() if k != "dropped_details"} for r in results], indent=2))


if __name__ == "__main__":
    main()
