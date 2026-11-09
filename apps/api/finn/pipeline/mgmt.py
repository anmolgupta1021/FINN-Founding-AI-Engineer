"""Real PDF extractor for Management Change filings (SEBI LODR Regulation 30).

Rule (user amendment #2):
- Never invent a bio for a real person.
- Download the actual exchange filing PDF, compute its sha256, extract page text with `pypdfium2`,
  and return the verbatim SEBI LODR disclosure / brief profile text with its exact page number.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pypdfium2 as pdfium


def download_filing_pdf(pdf_url: str, *, timeout_s: float = 15.0) -> bytes:
    """Download a PDF from NSE (`nsearchives.nseindia.com`) or BSE (`AttachLive` with automatic
    fallback to `AttachHis` since BSE moves attachments from AttachLive to AttachHis after ~72 hours).
    """
    from curl_cffi import requests as cffi_requests  # type: ignore[import-untyped]

    referer = "https://www.nseindia.com/" if "nseindia" in pdf_url else "https://www.bseindia.com/"
    candidate_urls = [pdf_url]
    if "/AttachLive/" in pdf_url:
        candidate_urls.append(pdf_url.replace("/AttachLive/", "/AttachHis/"))

    with cffi_requests.Session(impersonate="chrome") as s:
        last_status = None
        for u in candidate_urls:
            r = s.get(u, headers={"Referer": referer}, timeout=timeout_s)
            last_status = r.status_code
            if r.status_code == 200 and r.content.startswith(b"%PDF"):
                return bytes(r.content)
        raise RuntimeError(f"PDF download failed ({last_status}) from {pdf_url}")


def extract_pdf_pages_text(pdf_bytes: bytes) -> list[dict[str, Any]]:
    doc = pdfium.PdfDocument(pdf_bytes)
    pages: list[dict[str, Any]] = []
    for idx in range(len(doc)):
        page = doc[idx]
        textpage = page.get_textpage()
        txt = textpage.get_text_range() or ""
        pages.append({"page": idx + 1, "text": txt.strip()})
    return pages


def extract_mgmt_change_from_pdf(pdf_url: str) -> dict[str, Any]:
    """Download the real filing PDF and extract the page containing the SEBI LODR Regulation 30
    details / brief profile verbatim.
    """
    if not pdf_url.lower().endswith(".pdf"):
        raise RuntimeError(f"Non-PDF attachment skipped: {pdf_url}")

    pdf_bytes = download_filing_pdf(pdf_url)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    pages = extract_pdf_pages_text(pdf_bytes)
    if not pages:
        raise RuntimeError(f"Empty PDF at {pdf_url}")

    # Score pages for SEBI LODR Reg 30 Annexure / Brief profile markers
    best_page = pages[0]
    best_score = -1
    for p in pages:
        t = p["text"].lower()
        score = (
            (5 if "brief profile" in t else 0)
            + (4 if "reason for change" in t else 0)
            + (3 if "annexure" in t else 0)
            + (2 if "date of appointment" in t or "term of appointment" in t else 0)
            + (2 if "disclosure of relationships" in t else 0)
            + (1 if "din:" in t or "din " in t else 0)
        )
        if score > best_score:
            best_score = score
            best_page = p

    raw_text = re.sub(r"[ \t]+", " ", best_page["text"])
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    brief_profile = None
    for i, ln in enumerate(lines):
        if re.search(r"brief\s+profile", ln, re.IGNORECASE):
            chunk = "\n".join(lines[i : i + 14])
            brief_profile = chunk[:1100]
            break

    full_excerpt = "\n".join(lines[:40])[:1800]
    return {
        "pdf_url": pdf_url,
        "pdf_sha256": pdf_hash,
        "page_count": len(pages),
        "cited_page": best_page["page"],
        "filing_citation": f"Exchange Filing PDF · p. {best_page['page']} of {len(pages)}",
        "brief_profile_verbatim": brief_profile or full_excerpt,
        "page_verbatim_excerpt": full_excerpt,
    }
