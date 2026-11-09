"""Spike Pull on DIXON (1 Annual Report + last 4 Concall Transcripts from screener.in)
and update sector-aware Results cards in `announcements.json`.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finn.fetchers.screener import fetch_screener_documents
from finn.pipeline.mgmt import download_filing_pdf, extract_pdf_pages_text
from finn.pipeline.results import extract_results_from_pdf
from finn.pull.doctype import verify_concall_transcript

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"


def _probe_pdf_doc(kind: str, label: str, url: str, *, is_latest_call: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        pdf_bytes = download_filing_pdf(url, timeout_s=45.0)
        dl_ms = int((time.monotonic() - t0) * 1000)
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        size_bytes = len(pdf_bytes)
        size_mb = round(size_bytes / (1024 * 1024), 2)

        t1 = time.monotonic()
        pages = extract_pdf_pages_text(pdf_bytes)
        parse_ms = int((time.monotonic() - t1) * 1000)
        page_count = len(pages)
        non_empty_pages = [p for p in pages if len(p["text"].strip()) >= 80]
        total_chars = sum(len(p["text"]) for p in pages)

        # Find a substantive page excerpt (e.g., guidance, margin, revenue, or Q&A)
        sample_page = non_empty_pages[min(3, len(non_empty_pages) - 1)] if non_empty_pages else (pages[0] if pages else {"page": 1, "text": ""})
        for p in non_empty_pages[:40]:
            low = p["text"].lower()
            if any(k in low for k in ("guidance", "ebitda", "moderator:", "revenue", "mobile", "lighting")):
                sample_page = p
                break

        excerpt = re.sub(r"\s+", " ", sample_page["text"]).strip()[:360]
        qa_sample_page = non_empty_pages[min(6, len(non_empty_pages) - 1)] if len(non_empty_pages) > 5 else sample_page
        qa_excerpt = re.sub(r"\s+", " ", qa_sample_page["text"]).strip()[:360]

        out: dict[str, Any] = {
            "ok": True,
            "kind": kind,
            "label": label,
            "url": url,
            "size_bytes": size_bytes,
            "size_mb": size_mb,
            "sha256": sha[:16],
            "page_count": page_count,
            "non_empty_pages": len(non_empty_pages),
            "total_chars": total_chars,
            "download_ms": dl_ms,
            "extract_ms": parse_ms,
            "sample_page": sample_page["page"],
            "sample_excerpt": excerpt,
            "qa_sample_page": qa_sample_page["page"],
            "qa_sample_excerpt": qa_excerpt,
        }
        if kind == "concall_transcript":
            out["doctype_check"] = verify_concall_transcript(pages, is_latest_call=is_latest_call)
        return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "kind": kind,
            "label": label,
            "url": url,
            "error": str(exc)[:250],
        }


def main() -> None:
    # Part 1: Re-run sector-aware results extractor on POLYCAB and BAJFINANCE in announcements.json
    ann_path = DATA_DIR / "snapshots" / "announcements" / "announcements.json"
    ann_data = json.loads(ann_path.read_text(encoding="utf-8"))
    print("=== Updating Sector-Aware Results Cards in announcements.json ===")
    for item in ann_data["items"]:
        det = item.get("details") or {}
        if det.get("kind") == "results" and item.get("pdf_url"):
            ext = extract_results_from_pdf(item["symbol"], item["pdf_url"])
            item["details"] = ext
            print(
                f"  [{item['symbol']}] is_lender={ext['is_lender']} lender_note={ext['lender_note']} "
                f"| {ext['filing_citation']}"
            )
            for r in ext["rows"]:
                print(
                    f"    {r['metric']:<8} cur={r['cur']:>9.2f} prev={r['prev_q']:>9.2f} yoy={r['yoy_q']:>9.2f} | "
                    f"status={r['status']:<10} margin={r['margin_pct']!s:<6} screener={r['screener_val']!s:<8} delta={r['screener_delta_pct']}%"
                )
    ann_path.write_text(json.dumps(ann_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Part 2: Spike Pull for DIXON (1 Annual Report + last 4 Concall Transcripts)
    print("\n=== Spiking Pull on DIXON via Screener.in ===")
    docs = fetch_screener_documents("DIXON")
    print(
        f"Screener URL: {docs.get('screener_url')} | "
        f"Annual Reports found: {len(docs.get('annual_reports', []))} | "
        f"Concall Transcripts found: {len(docs.get('concall_transcripts', []))}"
    )

    ar_list = docs.get("annual_reports", [])[:1]
    cc_list = docs.get("concall_transcripts", [])[:4]

    results: list[dict[str, Any]] = []
    for ar in ar_list:
        print(f"\nFetching Annual Report: {ar['title']} -> {ar['url']}")
        rep = _probe_pdf_doc("annual_report", ar["title"], ar["url"])
        results.append(rep)
        print(
            f"  ok={rep.get('ok')} size={rep.get('size_mb')} MB pages={rep.get('page_count')} "
            f"non_empty={rep.get('non_empty_pages')} chars={rep.get('total_chars')} "
            f"dl={rep.get('download_ms')}ms extract={rep.get('extract_ms')}ms"
        )
        if rep.get("sample_excerpt"):
            print(f"  p.{rep['sample_page']} excerpt: {rep['sample_excerpt'][:180]}…")

    for idx, cc in enumerate(cc_list):
        print(f"\nFetching Concall Transcript ({cc['period']}): {cc['url']}")
        rep = _probe_pdf_doc(
            "concall_transcript",
            f"Concall {cc['period']}",
            cc["url"],
            is_latest_call=(idx == 0),
        )
        results.append(rep)
        dt_chk = rep.get("doctype_check") or {}
        print(
            f"  ok={rep.get('ok')} size={rep.get('size_mb')} MB pages={rep.get('page_count')} "
            f"is_transcript={dt_chk.get('is_transcript')} speakers={dt_chk.get('distinct_speaker_count')} "
            f"turns={dt_chk.get('speaker_turn_count')} has_qa={dt_chk.get('has_qa')} "
            f"testable={dt_chk.get('promised_vs_delivered_testable')}"
        )
        if rep.get("sample_excerpt"):
            print(f"  p.{rep['sample_page']} excerpt: {rep['sample_excerpt'][:180]}…")

    spike_out = DATA_DIR / "snapshots" / "pull_spike_dixon.json"
    spike_out.write_text(
        json.dumps(
            {
                "symbol": "DIXON",
                "spiked_at": datetime.now(UTC).isoformat(),
                "screener_url": docs.get("screener_url"),
                "annual_reports_available": len(docs.get("annual_reports", [])),
                "concalls_available": len(docs.get("concall_transcripts", [])),
                "probed_documents": results,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {spike_out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
