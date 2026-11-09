"""BSE corporate announcements fetcher (`api.bseindia.com`) with Chrome TLS impersonation and block detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from finn.fetchers.nse import ExchangeFetchResult

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}


def fetch_bse_announcements(
    scrip_map: dict[str, str],
    *,
    from_date: datetime,
    to_date: datetime,
    timeout_s: float = 10.0,
) -> ExchangeFetchResult:
    from_str = from_date.strftime("%Y%m%d")
    to_str = to_date.strftime("%Y%m%d")
    items: list[dict[str, Any]] = []

    try:
        from curl_cffi import requests as cffi_requests  # type: ignore[import-untyped]

        with cffi_requests.Session(impersonate="chrome") as s:
            for sym, scrip in scrip_map.items():
                params = {
                    "pageno": "1",
                    "strCat": "-1",
                    "strPrevDate": from_str,
                    "strScrip": scrip,
                    "strSearch": "P",
                    "strToDate": to_str,
                    "strType": "C",
                    "subcategory": "-1",
                }
                r = s.get(BSE_API, params=params, headers=BSE_HEADERS, timeout=timeout_s)
                ctype = r.headers.get("content-type", "")
                if r.status_code in (401, 403, 429) or "text/html" in ctype:
                    return ExchangeFetchResult(
                        exchange="bse",
                        ok=False,
                        blocked=True,
                        status_code=r.status_code,
                        reason=f"BSE API blocked on {sym}/{scrip} (HTTP {r.status_code}, content-type={ctype})",
                        items=items,
                    )
                if r.status_code != 200:
                    continue
                payload = r.json()
                rows = payload.get("Table", []) if isinstance(payload, dict) else []
                for row in rows:
                    att = row.get("ATTACHMENTNAME") or ""
                    pdf_url = (
                        f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}"
                        if att
                        else None
                    )
                    items.append(
                        {
                            "id": f"bse:{sym}:{row.get('NEWSID') or len(items)}",
                            "symbol": sym,
                            "exchange": "bse",
                            "ts": row.get("NEWS_DT") or row.get("DissemDT") or "",
                            "raw_category": (row.get("CATEGORYNAME") or "").strip(),
                            "subject": (row.get("NEWSSUB") or row.get("HEADLINE") or "").strip(),
                            "pdf_url": pdf_url,
                        }
                    )
        return ExchangeFetchResult(
            exchange="bse",
            ok=True,
            blocked=False,
            status_code=200,
            reason=f"Fetched {len(items)} live BSE announcements across {len(scrip_map)} symbols",
            items=items,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return ExchangeFetchResult(
            exchange="bse",
            ok=False,
            blocked=True,
            status_code=None,
            reason=f"BSE fetch error: {exc}",
            items=items,
        )
