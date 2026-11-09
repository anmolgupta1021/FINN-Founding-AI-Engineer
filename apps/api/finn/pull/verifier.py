"""Code-level Citation & Verbatim Quote Verifier (`D-007`).

Every factual claim, Promised-vs-Delivered row, and Bull/Bear argument in a Pull
dossier MUST carry a primary-source citation:
  `{doc_id, doc_label, pdf_url, page, verbatim_quote}`

`verify_citation()` normalizes whitespace and checks that `verbatim_quote` occurs on
the cited `page` (allowing ±1 page for cover-page offset) with
`rapidfuzz.fuzz.partial_ratio >= 85`. Any claim that fails verification is rejected
or explicitly labelled `"not found in filings"`.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

NOT_FOUND_IN_FILINGS = "not found in filings"
MIN_QUOTE_MATCH_SCORE = 90.0


def _extract_numbers(text: str) -> list[str]:
    """Extract integer and decimal numbers (ignoring standalone punctuation)."""
    return re.findall(r"\b\d+(?:\.\d+)?\b", text or "")


def _norm_ws(text: str) -> str:
    """Collapse whitespace and normalize smart quotes/dashes for substring comparison."""
    if not text:
        return ""
    cleaned = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00a0", " ")
    )
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def verify_citation(
    citation: dict[str, Any] | None,
    docs_by_id: dict[str, dict[str, Any]],
    *,
    min_score: float = MIN_QUOTE_MATCH_SCORE,
) -> dict[str, Any]:
    """Verify a single citation dict against extracted PDF page texts in `docs_by_id`.

    `docs_by_id[doc_id]` must contain:
      - `label`: human-readable document title (e.g. 'Concall Q2 FY27 (Oct 2026)')
      - `pdf_url`: direct URL to primary filing PDF
      - `pages`: `dict[int, str]` mapping 1-based page number -> extracted text
    """
    if not citation or not isinstance(citation, dict):
        return {
            "verified": False,
            "status": NOT_FOUND_IN_FILINGS,
            "match_score": 0.0,
            "reason": "missing_citation_object",
        }

    doc_id = str(citation.get("doc_id") or "").strip()
    quote = str(citation.get("verbatim_quote") or "").strip()
    raw_page = citation.get("page")

    if not doc_id or doc_id not in docs_by_id:
        return {
            "verified": False,
            "doc_id": doc_id or None,
            "status": NOT_FOUND_IN_FILINGS,
            "match_score": 0.0,
            "reason": f"unknown_doc_id:{doc_id}",
        }

    if not quote or len(quote) < 12 or quote.lower() == NOT_FOUND_IN_FILINGS:
        return {
            "verified": False,
            "doc_id": doc_id,
            "status": NOT_FOUND_IN_FILINGS,
            "match_score": 0.0,
            "reason": "empty_or_short_quote",
        }

    doc = docs_by_id[doc_id]
    pages: dict[int, str] = doc.get("pages") or {}
    try:
        cited_page = int(raw_page)
    except (TypeError, ValueError):
        cited_page = 1

    norm_quote = _norm_ws(quote)
    # Check cited_page first, then ±1 page in case of PDF cover offset, then scan doc if needed
    candidate_pages = [cited_page, cited_page - 1, cited_page + 1]
    best_page = cited_page
    best_score = 0.0

    for pno in candidate_pages:
        if pages.get(pno):
            score = float(fuzz.partial_ratio(norm_quote, _norm_ws(pages[pno])))
            if score > best_score:
                best_score = score
                best_page = pno

    if best_score < min_score:
        for pno, ptext in pages.items():
            if not ptext or pno in candidate_pages:
                continue
            score = float(fuzz.partial_ratio(norm_quote, _norm_ws(ptext)))
            if score > best_score:
                best_score = score
                best_page = pno

    quote_nums = _extract_numbers(quote)
    page_text = pages.get(best_page, "")
    missing_nums = [n for n in quote_nums if not re.search(rf"\b{re.escape(n)}\b", page_text)]
    numbers_verified = len(missing_nums) == 0

    verified = (best_score >= min_score) and numbers_verified
    status = "verified" if verified else NOT_FOUND_IN_FILINGS
    reason = None if verified else ("numbers_mismatch" if not numbers_verified else "low_match_score")

    return {
        "verified": verified,
        "doc_id": doc_id,
        "doc_label": doc.get("label") or citation.get("doc_label") or doc_id,
        "doc_type": doc.get("doc_type") or "primary_filing",
        "pdf_url": doc.get("pdf_url") or citation.get("pdf_url"),
        "page": best_page,
        "cited_page": cited_page,
        "verbatim_quote": quote,
        "match_score": round(best_score, 1),
        "numbers_verified": numbers_verified,
        "missing_numbers": missing_nums if not numbers_verified else [],
        "reason": reason,
        "status": status,
    }


def filter_verified_claims(
    claims: list[dict[str, Any]],
    docs_by_id: dict[str, dict[str, Any]],
    *,
    min_score: float = MIN_QUOTE_MATCH_SCORE,
) -> tuple[list[dict[str, Any]], int]:
    """Verify a list of claims; keep only those whose `citation` passes `verify_citation`.

    Returns `(verified_claims, dropped_count)`.
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in claims:
        cit = item.get("citation") or {
            "doc_id": item.get("doc_id"),
            "page": item.get("page"),
            "verbatim_quote": item.get("verbatim_quote"),
        }
        v = verify_citation(cit, docs_by_id, min_score=min_score)
        if v.get("verified"):
            enriched = dict(item)
            enriched["citation"] = v
            kept.append(enriched)
        else:
            dropped += 1
    return kept, dropped
