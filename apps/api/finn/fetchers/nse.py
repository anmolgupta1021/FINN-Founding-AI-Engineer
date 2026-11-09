"""NSE corporate announcements fetcher with Chrome TLS impersonation (`curl_cffi`) and explicit block detection.

NSE (`www.nseindia.com`) sits behind Akamai Bot Manager, which blocks standard Python `httpx` / `urllib`
TLS JA3 fingerprints with HTTP 403. When `curl_cffi` is installed (bundled with `yfinance`), we use
`impersonate="chrome"` to establish the session cookie on `/companies-listing/corporate-filings-announcements`
and then query `/api/corporate-announcements`. If NSE still returns 401/403/429 or HTML, we return
`blocked=True` so the caller falls back loudly to the committed snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

NSE_BASE = "https://www.nseindia.com"
NSE_LANDING = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": NSE_LANDING,
}


@dataclass
class ExchangeFetchResult:
    exchange: str
    ok: bool
    blocked: bool
    status_code: int | None
    reason: str
    items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_nse_announcements(
    symbols: list[str],
    *,
    from_date: datetime,
    to_date: datetime,
    timeout_s: float = 10.0,
) -> ExchangeFetchResult:
    from_str = from_date.strftime("%d-%m-%Y")
    to_str = to_date.strftime("%d-%m-%Y")
    items: list[dict[str, Any]] = []

    try:
        from curl_cffi import requests as cffi_requests  # type: ignore[import-untyped]

        with cffi_requests.Session(impersonate="chrome") as s:
            warm = s.get(NSE_LANDING, timeout=timeout_s)
            if warm.status_code in (401, 403, 429) or "Access Denied" in warm.text[:400]:
                return ExchangeFetchResult(
                    exchange="nse",
                    ok=False,
                    blocked=True,
                    status_code=warm.status_code,
                    reason=f"NSE warm-up blocked even with Chrome TLS impersonation (HTTP {warm.status_code})",
                    items=[],
                )
            for sym in symbols:
                url = (
                    f"{NSE_BASE}/api/corporate-announcements"
                    f"?index=equities&symbol={sym}&from_date={from_str}&to_date={to_str}"
                )
                r = s.get(url, headers=NSE_HEADERS, timeout=timeout_s)
                ctype = r.headers.get("content-type", "")
                if r.status_code in (401, 403, 429) or "text/html" in ctype or "Access Denied" in r.text[:300]:
                    return ExchangeFetchResult(
                        exchange="nse",
                        ok=False,
                        blocked=True,
                        status_code=r.status_code,
                        reason=f"NSE API blocked on {sym} (HTTP {r.status_code}, content-type={ctype})",
                        items=items,
                    )
                if r.status_code != 200:
                    continue
                payload = r.json()
                rows = payload if isinstance(payload, list) else payload.get("data", [])
                for row in rows:
                    att = row.get("attchmntFile") or ""
                    if att and not att.startswith("http"):
                        att = f"https://nsearchives.nseindia.com/corporate/{att.lstrip('/')}"
                    items.append(
                        {
                            "id": f"nse:{sym}:{row.get('seq_id') or row.get('an_dt') or len(items)}",
                            "symbol": sym,
                            "exchange": "nse",
                            "ts": row.get("an_dt") or row.get("sort_date") or "",
                            "raw_category": (row.get("desc") or "").strip(),
                            "subject": (row.get("attchmntText") or row.get("desc") or "").strip(),
                            "pdf_url": att or None,
                        }
                    )
        return ExchangeFetchResult(
            exchange="nse",
            ok=True,
            blocked=False,
            status_code=200,
            reason=f"Fetched {len(items)} live NSE announcements across {len(symbols)} symbols",
            items=items,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return ExchangeFetchResult(
            exchange="nse",
            ok=False,
            blocked=True,
            status_code=None,
            reason=f"NSE fetch error: {exc}",
            items=items,
        )
