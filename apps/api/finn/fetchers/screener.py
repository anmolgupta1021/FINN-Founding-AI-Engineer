"""Screener.in fetcher for quarterly financial tables (cross-check for Results cards)
and primary-source document links (Annual Reports + Concall transcripts for Pull).
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

SCREENER_BASE = "https://www.screener.in"


def _parse_num(cell_text: str) -> float | None:
    cleaned = cell_text.replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in ("-", "—"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_screener_quarterly(symbol: str, *, timeout_s: float = 12.0) -> dict[str, Any]:
    """Fetch the `#quarters` table from `https://www.screener.in/company/<SYMBOL>/consolidated/`
    (falling back to standalone `/company/<SYMBOL>/` if consolidated has no quarterly rows).
    Returns normalized quarterly series in ₹ cr for `Revenue`, `EBITDA`, `PBT`, `PAT`.
    """
    from curl_cffi import requests as cffi_requests  # type: ignore[import-untyped]

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.screener.in/",
    }

    with cffi_requests.Session(impersonate="chrome") as s:
        for suffix in ("consolidated/", ""):
            url = f"{SCREENER_BASE}/company/{symbol}/{suffix}"
            r = s.get(url, headers=headers, timeout=timeout_s)
            if r.status_code != 200 or "quarters" not in r.text:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            q_sec = soup.select_one("section#quarters table.data-table")
            if q_sec is None:
                continue

            headers_th = [th.get_text(" ", strip=True) for th in q_sec.select("thead th")]
            periods = [h for h in headers_th[1:] if h]
            if not periods:
                continue

            series: dict[str, dict[str, float | None]] = {}
            for tr in q_sec.select("tbody tr"):
                tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
                if len(tds) < 2:
                    continue
                label = re.sub(r"\s*\+\s*$", "", tds[0]).strip()
                vals = [_parse_num(v) for v in tds[1 : 1 + len(periods)]]
                series[label] = dict(zip(periods, vals, strict=False))

            # Map Screener labels -> canonical FINN metric names
            rev = series.get("Sales") or series.get("Revenue") or {}
            ebitda = series.get("Operating Profit") or series.get("Financing Profit") or {}
            pbt = series.get("Profit before tax") or {}
            pat = series.get("Net Profit") or {}

            if any(v is not None for v in rev.values()):
                return {
                    "ok": True,
                    "symbol": symbol,
                    "basis": "consolidated" if suffix else "standalone",
                    "url": url,
                    "periods": periods,
                    "metrics": {
                        "Revenue": rev,
                        "EBITDA": ebitda,
                        "PBT": pbt,
                        "PAT": pat,
                    },
                    "raw_rows": series,
                }

    return {"ok": False, "symbol": symbol, "periods": [], "metrics": {}}


def fetch_screener_documents(symbol: str, *, timeout_s: float = 15.0) -> dict[str, Any]:
    """Extract Annual Report links and Concall Transcript links from `section#documents` on Screener.in."""
    from curl_cffi import requests as cffi_requests  # type: ignore[import-untyped]

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.screener.in/",
    }

    with cffi_requests.Session(impersonate="chrome") as s:
        for suffix in ("consolidated/", ""):
            url = f"{SCREENER_BASE}/company/{symbol}/{suffix}"
            r = s.get(url, headers=headers, timeout=timeout_s)
            if r.status_code != 200 or "documents" not in r.text:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            doc_sec = soup.select_one("section#documents")
            if doc_sec is None:
                continue

            annual_reports: list[dict[str, str]] = []
            ar_box = doc_sec.select_one(".annual-reports")
            if ar_box:
                for a in ar_box.select("a[href]"):
                    href = (a.get("href") or "").strip()
                    txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                    if href:
                        annual_reports.append({"title": txt, "url": href})

            concalls: list[dict[str, str]] = []
            cc_box = doc_sec.select_one(".concalls")
            if cc_box:
                for li in cc_box.select("li"):
                    row_text = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
                    period_m = re.match(r"^([A-Za-z]{3}\s+\d{4})", row_text)
                    period = period_m.group(1) if period_m else row_text[:15]
                    for a in li.select("a[href]"):
                        link_label = a.get_text(" ", strip=True)
                        href = (a.get("href") or "").strip()
                        if "transcript" in link_label.lower() and href:
                            concalls.append(
                                {
                                    "period": period,
                                    "label": link_label,
                                    "url": href,
                                }
                            )

            if annual_reports or concalls:
                return {
                    "ok": True,
                    "symbol": symbol,
                    "screener_url": url,
                    "annual_reports": annual_reports,
                    "concall_transcripts": concalls,
                }

    return {"ok": False, "symbol": symbol, "annual_reports": [], "concall_transcripts": []}
