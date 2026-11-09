"""Primary-Source Document Fetcher, Financial Table Parser & Section Chunker (`D-007`).

Fetches ONLY primary sources from `screener.in`:
  1. Latest Annual Report PDF (`#documents .annual-reports`)
  2. Last 4 Concall Transcript PDFs (`#documents .concalls`), verified via
     `verify_concall_transcript()` (speakers + Q&A check; latest call marked
     untestable for promised-vs-delivered).
  3. 5-Year Annual P&L + Cash Flow + Balance Sheet / Ratios + Last 6 Quarters
     cross-check tables (`#profit-loss`, `#cash-flow`, `#quarters`), sector-aware
     for lenders (`HDFCBANK`, `BAJFINANCE`, `CREDITACC`, `CAMS`) vs non-lenders.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from finn.pipeline.mgmt import download_filing_pdf, extract_pdf_pages_text
from finn.pipeline.results import LENDER_SYMBOLS
from finn.pull.doctype import verify_concall_transcript

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Keywords for selecting high-signal pages from 300+ page Annual Reports (0 LLM calls)
_AR_HIGH_SIGNAL_PATTERNS = [
    (re.compile(r"\b(?:management\s+discussion\s+and\s+analysis|md\s*&\s*a)\b", re.IGNORECASE), 18),
    (
        re.compile(
            r"\b(?:chairman'?s?\s+message|managing\s+director'?s?\s+message|letter\s+to\s+shareholders|from\s+the\s+desk)\b",
            re.IGNORECASE,
        ),
        16,
    ),
    (
        re.compile(
            r"\b(?:business\s+overview|operational\s+performance|segment\s+performance|segment\s+wise|division\s+wise)\b",
            re.IGNORECASE,
        ),
        14,
    ),
    (
        re.compile(
            r"\b(?:capacity\s+expansion|capex|order\s+book|new\s+products?|backward\s+integration|pli\s+scheme|r\s*&\s*d)\b",
            re.IGNORECASE,
        ),
        10,
    ),
    (
        re.compile(
            r"\b(?:guidance|outlook|key\s+risks|opportunities\s+and\s+threats|working\s+capital|cash\s+flow\s+from\s+operations)\b",
            re.IGNORECASE,
        ),
        9,
    ),
    (
        re.compile(
            r"\b(?:net\s+interest\s+income|net\s+interest\s+margin|casa\s+ratio|gross\s+npa|net\s+npa|credit\s+cost|slippages)\b",
            re.IGNORECASE,
        ),
        12,
    ),
]

_AR_LOW_SIGNAL_PATTERNS = [
    re.compile(r"\b(?:form\s+no\.?\s+mgt|secretarial\s+audit\s+report|extract\s+of\s+annual\s+return)\b", re.IGNORECASE),
    re.compile(r"\b(?:proxy\s+form|attendance\s+slip|notice\s+of\s+annual\s+general\s+meeting)\b", re.IGNORECASE),
    re.compile(r"\b(?:corporate\s+governance\s+report|business\s+responsibility\s+and\s+sustainability)\b", re.IGNORECASE),
]


def _parse_num(val: str) -> float | None:
    s = (val or "").replace(",", "").replace("%", "").replace("₹", "").strip()
    if not s or s in ("-", "—", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_screener_table(section) -> dict[str, dict[str, float | None]]:
    """Parse a Screener `#profit-loss`, `#quarters`, or `#cash-flow` section into `{row_name: {col_header: value}}`."""
    if not section:
        return {}
    table = section.select_one("table.data-table")
    if not table:
        return {}
    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")][1:]
    rows: dict[str, dict[str, float | None]] = {}
    for tr in table.select("tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if not tds:
            continue
        label = tds[0].replace("+", "").strip()
        vals = tds[1:]
        rows[label] = {
            headers[i]: _parse_num(vals[i])
            for i in range(min(len(headers), len(vals)))
            if headers[i]
        }
    return rows


def extract_financial_trajectory(html: str, symbol: str) -> dict[str, Any]:
    """Extract 5-year annual trajectory and recent quarterly trajectory from Screener HTML."""
    sym = symbol.upper()
    is_lender = sym in LENDER_SYMBOLS
    soup = BeautifulSoup(html, "lxml")

    pl_rows = _parse_screener_table(soup.select_one("#profit-loss"))
    cf_rows = _parse_screener_table(soup.select_one("#cash-flow"))
    q_rows = _parse_screener_table(soup.select_one("#quarters"))
    ratio_rows = _parse_screener_table(soup.select_one("#ratios"))

    def _find_row(table_dict: dict[str, dict[str, float | None]], candidates: list[str]) -> dict[str, float | None]:
        for cand in candidates:
            for k, v in table_dict.items():
                if k.lower().startswith(cand.lower()):
                    return v
        return {}

    sales_row = _find_row(pl_rows, ["Sales", "Revenue", "Interest Earned"])
    op_row = _find_row(pl_rows, ["Financing Profit", "Operating Profit"])
    opm_row = _find_row(pl_rows, ["Financing Margin", "OPM"])
    pbt_row = _find_row(pl_rows, ["Profit before tax"])
    pat_row = _find_row(pl_rows, ["Net Profit"])
    cfo_row = _find_row(cf_rows, ["Cash from Operating Activity"])
    roce_row = _find_row(ratio_rows, ["ROCE", "ROE"])

    years = [y for y in sales_row if y.upper() != "TTM"][-5:]
    annual_series: list[dict[str, Any]] = []
    for yr in years:
        rev = sales_row.get(yr)
        op = op_row.get(yr)
        opm = opm_row.get(yr)
        pbt = pbt_row.get(yr)
        pat = pat_row.get(yr)
        cfo = cfo_row.get(yr)
        roce = roce_row.get(yr)
        cfo_pat_pct = round((cfo / pat) * 100.0, 1) if (cfo is not None and pat and pat > 0) else None

        if is_lender:
            annual_series.append(
                {
                    "period": yr,
                    "revenue_or_nii_cr": rev,
                    "ppop_or_financing_profit_cr": op,
                    "financing_margin_pct": opm,
                    "ebitda_cr": None,
                    "ebitda_status": "EBITDA not meaningful for lenders",
                    "pbt_cr": pbt,
                    "pat_cr": pat,
                    "roce_or_roe_pct": roce,
                }
            )
        else:
            annual_series.append(
                {
                    "period": yr,
                    "revenue_cr": rev,
                    "ebitda_derived_cr": op,
                    "ebitda_margin_derived_pct": opm,
                    "ebitda_status": "derived",
                    "pbt_cr": pbt,
                    "pat_cr": pat,
                    "cfo_cr": cfo,
                    "cfo_to_pat_pct": cfo_pat_pct,
                    "roce_pct": roce,
                }
            )

    q_sales = _find_row(q_rows, ["Sales", "Revenue", "Interest Earned"])
    q_op = _find_row(q_rows, ["Financing Profit", "Operating Profit"])
    q_opm = _find_row(q_rows, ["Financing Margin", "OPM"])
    q_pbt = _find_row(q_rows, ["Profit before tax"])
    q_pat = _find_row(q_rows, ["Net Profit"])
    q_gnpa = _find_row(q_rows, ["Gross NPA"])
    q_nnpa = _find_row(q_rows, ["Net NPA"])

    quarters = list(q_sales.keys())[-6:]
    quarterly_series: list[dict[str, Any]] = []
    for q in quarters:
        if is_lender:
            quarterly_series.append(
                {
                    "quarter": q,
                    "revenue_or_nii_cr": q_sales.get(q),
                    "ppop_or_financing_profit_cr": q_op.get(q),
                    "financing_margin_pct": q_opm.get(q),
                    "ebitda_cr": None,
                    "ebitda_status": "EBITDA not meaningful for lenders",
                    "pbt_cr": q_pbt.get(q),
                    "pat_cr": q_pat.get(q),
                    "gross_npa_pct": q_gnpa.get(q),
                    "net_npa_pct": q_nnpa.get(q),
                }
            )
        else:
            quarterly_series.append(
                {
                    "quarter": q,
                    "revenue_cr": q_sales.get(q),
                    "ebitda_derived_cr": q_op.get(q),
                    "ebitda_margin_derived_pct": q_opm.get(q),
                    "ebitda_status": "derived",
                    "pbt_cr": q_pbt.get(q),
                    "pat_cr": q_pat.get(q),
                }
            )

    # Compute 5Y CAGR & cumulative CFO/PAT summary for Numbers-vs-Narrative check
    summary_stats: dict[str, Any] = {
        "is_lender": is_lender,
        "sector_accounting_mode": "lender_nii_ppop" if is_lender else "operating_ebitda_derived",
        "ebitda_label": "EBITDA not meaningful for lenders" if is_lender else "Derived Operating EBITDA (Screener OPM cross-check)",
    }
    if len(annual_series) >= 2:
        first = annual_series[0]
        last = annual_series[-1]
        n_years = max(1, len(annual_series) - 1)
        r0 = first.get("revenue_or_nii_cr") if is_lender else first.get("revenue_cr")
        r1 = last.get("revenue_or_nii_cr") if is_lender else last.get("revenue_cr")
        p0 = first.get("pat_cr")
        p1 = last.get("pat_cr")
        if r0 and r1 and r0 > 0 and r1 > 0:
            summary_stats["revenue_cagr_pct"] = round(((r1 / r0) ** (1.0 / n_years) - 1.0) * 100.0, 1)
        if p0 and p1 and p0 > 0 and p1 > 0:
            summary_stats["pat_cagr_pct"] = round(((p1 / p0) ** (1.0 / n_years) - 1.0) * 100.0, 1)
        if not is_lender:
            tot_cfo = sum(x.get("cfo_cr") or 0.0 for x in annual_series)
            tot_pat = sum(x.get("pat_cr") or 0.0 for x in annual_series)
            if tot_pat > 0:
                summary_stats["cumulative_5y_cfo_cr"] = round(tot_cfo, 1)
                summary_stats["cumulative_5y_pat_cr"] = round(tot_pat, 1)
                summary_stats["cumulative_5y_cfo_to_pat_pct"] = round((tot_cfo / tot_pat) * 100.0, 1)

    return {
        "symbol": sym,
        "is_lender": is_lender,
        "summary_stats": summary_stats,
        "annual_5y": annual_series,
        "quarterly_recent": quarterly_series,
    }


def parse_screener_document_links(html: str) -> dict[str, Any]:
    """Extract latest Annual Report link and last 4 Concall Transcript links from Screener HTML."""
    soup = BeautifulSoup(html, "lxml")
    ar_links: list[dict[str, str]] = []
    for li in soup.select(".documents.annual-reports ul.list-links li"):
        a = li.find("a", href=True)
        if a:
            ar_links.append(
                {
                    "title": " ".join(a.get_text(" ", strip=True).split()),
                    "url": a["href"],
                }
            )

    concall_links: list[dict[str, str]] = []
    for li in soup.select(".documents.concalls ul.list-links li"):
        date_el = li.select_one(".ink-600")
        date_label = date_el.get_text(" ", strip=True) if date_el else ""
        for a in li.find_all("a", href=True):
            txt = a.get_text(" ", strip=True)
            if "transcript" in txt.lower():
                concall_links.append(
                    {
                        "quarter_label": f"Concall {date_label}".strip(),
                        "date_label": date_label,
                        "url": a["href"],
                    }
                )
                break

    return {
        "annual_reports": ar_links[:2],
        "concalls": concall_links[:4],
    }


def _download_pdf_and_extract_pages(
    client: httpx.Client,
    url: str,
    cache_dir: Path,
) -> dict[str, Any]:
    """Download a PDF (or load from local page-text cache) and extract 1-based page text."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    cache_file = cache_dir / f"pdf_{url_hash}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if cached.get("ok") and cached.get("pages"):
                cached["pages"] = {int(k): v for k, v in cached["pages"].items()}
                return cached
        except (OSError, ValueError, TypeError):
            cached = {}

    try:
        pdf_bytes = download_filing_pdf(url, timeout_s=45.0)
    except Exception:  # noqa: BLE001
        pdf_bytes = b""

    if not pdf_bytes or b"%PDF" not in pdf_bytes[:1024]:
        return {
            "ok": False,
            "url": url,
            "final_url": url,
            "size_bytes": len(pdf_bytes),
            "page_count": 0,
            "pages": {},
        }

    pages_list = extract_pdf_pages_text(pdf_bytes)
    pages: dict[int, str] = {}
    for p in pages_list:
        txt = (p.get("text") or "").strip()
        if txt:
            pages[int(p["page"])] = txt

    payload = {
        "ok": True,
        "url": url,
        "final_url": url,
        "size_bytes": len(pdf_bytes),
        "page_count": len(pages_list),
        "non_empty_pages": len(pages),
        "pages": pages,
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False))
    return payload


def select_high_signal_ar_pages(pages: dict[int, str], *, max_pages: int = 26) -> list[tuple[int, str]]:
    """Deterministically rank and select the top `max_pages` from an Annual Report (0 LLM calls).

    Prioritizes Chairman/MD letters, MD&A, Segment Revenue performance, Capacity/Capex,
    Cash Flow conversion, and Lender NII/NIM/Asset Quality discussions.
    """
    scored: list[tuple[int, int, str]] = []
    for pno, text in pages.items():
        if len(text) < 250:
            continue
        if any(pat.search(text[:800]) for pat in _AR_LOW_SIGNAL_PATTERNS):
            continue
        score = 0
        head = text[:600]
        for pat, weight in _AR_HIGH_SIGNAL_PATTERNS:
            hits = len(pat.findall(text))
            if hits:
                score += weight + min(hits * 2, 10)
            if pat.search(head):
                score += 8
        # Slight bonus for pages in the first 120 pages (usually Narrative + MD&A)
        if 2 <= pno <= 120:
            score += 4
        if score > 0:
            scored.append((score, pno, text))

    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = sorted(scored[:max_pages], key=lambda x: x[1])
    return [(pno, txt) for _, pno, txt in picked]


def fetch_company_primary_corpus(
    symbol: str,
    cache_root: Path,
) -> dict[str, Any]:
    """Fetch Screener financial trajectory + Annual Report + 4 verified Concall Transcripts for `symbol`."""
    sym = symbol.upper()
    sym_cache = cache_root / sym
    sym_cache.mkdir(parents=True, exist_ok=True)
    html_cache = sym_cache / "screener_page.html"

    with httpx.Client(headers=HEADERS, timeout=45.0, follow_redirects=True) as client:
        html = ""
        screener_url = f"https://www.screener.in/company/{sym}/consolidated/"
        if html_cache.exists():
            html = html_cache.read_text(encoding="utf-8")
        if not html or len(html) < 2000:
            r = client.get(screener_url)
            if r.status_code == 200 and len(r.text) > 2000:
                html = r.text
            else:
                screener_url = f"https://www.screener.in/company/{sym}/"
                r2 = client.get(screener_url)
                html = r2.text if r2.status_code == 200 else ""
            if html:
                html_cache.write_text(html, encoding="utf-8")

        trajectory = extract_financial_trajectory(html, sym)
        doc_links = parse_screener_document_links(html)

        docs_by_id: dict[str, dict[str, Any]] = {}
        manifest: list[dict[str, Any]] = []

        # 1. Annual Report (try first link, fallback to second if first is non-PDF)
        for ar_meta in doc_links.get("annual_reports", []):
            ar_res = _download_pdf_and_extract_pages(client, ar_meta["url"], sym_cache)
            if ar_res.get("ok") and ar_res.get("non_empty_pages", 0) >= 5:
                doc_id = f"{sym}_AR_LATEST"
                label = f"{sym} {ar_meta['title']} (Annual Report)"
                docs_by_id[doc_id] = {
                    "doc_id": doc_id,
                    "label": label,
                    "doc_type": "annual_report",
                    "pdf_url": ar_res["final_url"],
                    "page_count": ar_res["page_count"],
                    "pages": ar_res["pages"],
                    "selected_pages": select_high_signal_ar_pages(ar_res["pages"]),
                }
                manifest.append(
                    {
                        "doc_id": doc_id,
                        "label": label,
                        "doc_type": "annual_report",
                        "pdf_url": ar_res["final_url"],
                        "size_kb": round(ar_res["size_bytes"] / 1024, 1),
                        "page_count": ar_res["page_count"],
                        "non_empty_pages": ar_res["non_empty_pages"],
                        "doctype_verified": True,
                    }
                )
                break

        # 2. Last 4 Concall Transcripts (verified via verify_concall_transcript)
        for idx, cc_meta in enumerate(doc_links.get("concalls", [])[:4]):
            cc_res = _download_pdf_and_extract_pages(client, cc_meta["url"], sym_cache)
            if not cc_res.get("ok") or not cc_res.get("pages"):
                continue
            is_latest = idx == 0
            dt_check = verify_concall_transcript(cc_res["pages"], is_latest_call=is_latest)
            date_slug = re.sub(r"[^A-Za-z0-9]+", "_", cc_meta.get("date_label") or f"Q{idx + 1}").strip("_").upper()
            doc_id = f"{sym}_CONCALL_{idx + 1}_{date_slug}"
            label = f"{sym} {cc_meta['quarter_label']} Transcript"
            docs_by_id[doc_id] = {
                "doc_id": doc_id,
                "label": label,
                "date_label": cc_meta.get("date_label"),
                "doc_type": "concall_transcript",
                "is_latest_call": is_latest,
                "pdf_url": cc_res["final_url"],
                "page_count": cc_res["page_count"],
                "pages": cc_res["pages"],
                "doctype_check": dt_check,
            }
            manifest.append(
                {
                    "doc_id": doc_id,
                    "label": label,
                    "date_label": cc_meta.get("date_label"),
                    "doc_type": "concall_transcript",
                    "is_latest_call": is_latest,
                    "pdf_url": cc_res["final_url"],
                    "size_kb": round(cc_res["size_bytes"] / 1024, 1),
                    "page_count": cc_res["page_count"],
                    "doctype_check": dt_check,
                }
            )

    return {
        "symbol": sym,
        "screener_url": screener_url,
        "trajectory": trajectory,
        "manifest": manifest,
        "docs_by_id": docs_by_id,
    }
