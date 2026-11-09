"""Real PDF extractor for Quarterly Results filings, with live Screener.in cross-check.

Rule (user amendment #3):
- Extract Revenue, EBITDA, PBT, and PAT directly from the real exchange results PDF (`nsearchives.nseindia.com`
  or `bseindia.com`), recording the page number and verbatim matched lines.
- Convert the filing's unit (`₹ Million` -> ÷10, `₹ Lakhs` -> ÷100, `₹ Crore` -> ×1) to `₹ cr`.
- Cross-check against Screener.in's `#quarters` table and surface any mismatch (`screener_delta_pct`) honestly.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from finn.fetchers.screener import fetch_screener_quarterly
from finn.pipeline.mgmt import download_filing_pdf, extract_pdf_pages_text

_NUM_RE = re.compile(r"\(?-?\d[\d,]*\.\d+\)?|\(?-?\d[\d,]+\)?")


def _detect_unit_divisor(page_text: str) -> tuple[str, float]:
    """Return `(raw_unit_label, divisor_to_crore)`."""
    t = page_text.lower()
    if re.search(r"(?:\bin\s+millions?\b|(?:₹|rs\.?|inr|rupees|\()\s*(?:in\s*)?millions?\b)", t):
        return "₹ Million (÷10 → ₹ cr)", 10.0
    if re.search(r"(?:\bin\s+(?:lakhs?|lacs?)\b|(?:₹|rs\.?|inr|rupees|\()\s*(?:in\s*)?(?:lakhs?|lacs?)\b)", t):
        return "₹ Lakhs (÷100 → ₹ cr)", 100.0
    return "₹ Crore", 1.0


def _extract_row_numbers(line: str, divisor: float) -> list[float]:
    vals: list[float] = []
    for tok in _NUM_RE.findall(line):
        clean = tok.replace(",", "").strip()
        neg = clean.startswith("(") and clean.endswith(")")
        clean = clean.strip("()")
        try:
            v = float(clean)
        except ValueError:
            continue
        if neg:
            v = -v
        vals.append(round(v / divisor, 2))
    return vals


def find_consolidated_results_page(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the page containing the Consolidated Statement of Unaudited/Audited Financial Results."""
    best: dict[str, Any] | None = None
    best_score = -1
    for p in pages:
        t = p["text"].lower()
        if "revenue from operations" not in t and "total income" not in t:
            continue
        if "profit before tax" not in t and "profit/(loss) before tax" not in t:
            continue
        score = 0
        if "consolidated" in t:
            score += 5
        if "quarter ended" in t:
            score += 4
        if "finance cost" in t:
            score += 2
        if "depreciation" in t:
            score += 2
        if "segment wise" in t or "segment revenue" in t:
            score -= 4
        if score > best_score:
            best_score = score
            best = p
    return best


def _match_metric_line(
    lines: list[str],
    patterns: tuple[str, ...],
    divisor: float,
    *,
    min_value_cr: float = 0.0,
) -> tuple[str | None, list[float]]:
    for pat in patterns:
        for idx, ln in enumerate(lines):
            low = ln.lower()
            if re.search(pat, low):
                combined = ln
                nums = _extract_row_numbers(combined, divisor)
                if len(nums) >= 4 and abs(nums[0] * divisor) <= 15 and abs(nums[1]) > abs(nums[0]) * 5:
                    nums = nums[1:]
                if len(nums) < 3 and idx + 1 < len(lines):
                    combined = f"{ln} {lines[idx + 1]}"
                    nums = _extract_row_numbers(combined, divisor)
                    if len(nums) >= 4 and abs(nums[0] * divisor) <= 15 and abs(nums[1]) > abs(nums[0]) * 5:
                        nums = nums[1:]
                if len(nums) >= 3 and abs(nums[0]) >= min_value_cr:
                    return combined.strip(), nums[:3]
    return None, []


def extract_results_from_pdf(
    symbol: str,
    pdf_url: str,
    *,
    period_label: str = "Latest Q",
) -> dict[str, Any]:
    if not pdf_url.lower().endswith(".pdf"):
        raise RuntimeError(f"Non-PDF attachment skipped: {pdf_url}")

    pdf_bytes = download_filing_pdf(pdf_url)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    pages = extract_pdf_pages_text(pdf_bytes)
    target = find_consolidated_results_page(pages)
    if target is None:
        raise RuntimeError(f"Could not locate Consolidated Financial Results table in {pdf_url}")

    page_no = target["page"]
    raw_unit, divisor = _detect_unit_divisor(target["text"])
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in target["text"].splitlines() if ln.strip()]

    # Match 'Total revenue from operations' first (needed for NBFCs like Bajaj Finance that list sub-items above total)
    rev_line, rev_vals = _match_metric_line(
        lines,
        (r"total\s+revenue\s+from\s+operations", r"revenue\s+from\s+operations", r"income\s+from\s+operations"),
        divisor,
        min_value_cr=25.0,
    )
    _other_inc_line, other_inc_vals = _match_metric_line(
        lines,
        (r"\bother income\b",),
        divisor,
    )
    _fin_line, fin_vals = _match_metric_line(
        lines,
        (r"finance costs?",),
        divisor,
    )
    _dep_line, dep_vals = _match_metric_line(
        lines,
        (r"depreciation,?\s*amorti[sz]ation", r"depreciation and amorti[sz]ation"),
        divisor,
    )
    pbt_line, pbt_vals = _match_metric_line(
        lines,
        (r"profit\s*(?:/\s*\(loss\))?\s*before\s*tax",),
        divisor,
        min_value_cr=1.0,
    )
    pbt_idx = next((i for i, ln in enumerate(lines) if pbt_line and pbt_line[:25] in ln), 0)
    pat_line, pat_vals = _match_metric_line(
        lines[pbt_idx + 1 :],
        (
            r"profit\s*(?:/\s*\(loss\))?\s*for the period",
            r"profit\s*(?:/\s*\(loss\))?\s*for the quarter",
            r"profit\s*(?:/\s*\(loss\))?\s*after\s*tax",
            r"net profit\s*(?:/\s*\(loss\))?\s*for the period",
        ),
        divisor,
        min_value_cr=1.0,
    )

    if len(rev_vals) < 3 or len(pbt_vals) < 3 or len(pat_vals) < 3:
        raise RuntimeError(
            f"Incomplete metric extraction on p.{page_no} of {pdf_url}: "
            f"rev={rev_vals}, pbt={pbt_vals}, pat={pat_vals}"
        )

    ebitda_vals: list[float] = []
    for i in range(3):
        oi = other_inc_vals[i] if len(other_inc_vals) >= 3 else 0.0
        fc = fin_vals[i] if len(fin_vals) >= 3 else 0.0
        da = dep_vals[i] if len(dep_vals) >= 3 else 0.0
        ebitda_vals.append(round(pbt_vals[i] + fc + da - oi, 2))

    screener = fetch_screener_quarterly(symbol)
    screener_period = None
    if screener.get("ok") and screener.get("periods"):
        rev_map = screener["metrics"].get("Revenue", {})
        best_p = None
        best_diff = float("inf")
        for p_name, s_val in rev_map.items():
            if s_val is not None:
                diff = abs(s_val - rev_vals[0])
                if diff < best_diff:
                    best_diff = diff
                    best_p = p_name
        screener_period = best_p

    def _build_row(
        metric: str,
        vals: list[float],
        verbatim_line: str | None,
        *,
        derived: bool = False,
    ) -> dict[str, Any]:
        cur, prev_q, yoy_q = vals[0], vals[1], vals[2]
        qoq_pct = round(((cur - prev_q) / abs(prev_q)) * 100.0, 1) if prev_q else 0.0
        yoy_pct = round(((cur - yoy_q) / abs(yoy_q)) * 100.0, 1) if yoy_q else 0.0
        s_val = None
        delta_pct = None
        if screener_period and screener.get("ok"):
            s_val = screener["metrics"].get(metric, {}).get(screener_period)
            if s_val is not None and s_val != 0:
                delta_pct = round(((cur - s_val) / abs(s_val)) * 100.0, 2)
        return {
            "metric": metric,
            "cur": cur,
            "prev_q": prev_q,
            "yoy_q": yoy_q,
            "qoq_pct": qoq_pct,
            "yoy_pct": yoy_pct,
            "page": f"Filing PDF p. {page_no}" + (" (derived)" if derived else ""),
            "derived": derived,
            "verbatim_line": verbatim_line,
            "screener_period": screener_period,
            "screener_val": s_val,
            "screener_delta_pct": delta_pct,
        }

    rows = [
        _build_row("Revenue", rev_vals, rev_line, derived=False),
        _build_row(
            "EBITDA",
            ebitda_vals,
            f"Derived from p.{page_no}: PBT ({pbt_vals[0]}) + FinCost ({fin_vals[0] if fin_vals else 0}) + D&A ({dep_vals[0] if dep_vals else 0}) - OtherInc ({other_inc_vals[0] if other_inc_vals else 0})",
            derived=True,
        ),
        _build_row("PBT", pbt_vals, pbt_line, derived=False),
        _build_row("PAT", pat_vals, pat_line, derived=False),
    ]

    return {
        "kind": "results",
        "symbol": symbol,
        "period": screener_period or period_label,
        "unit": "₹ cr",
        "raw_filing_unit": raw_unit,
        "pdf_url": pdf_url,
        "pdf_sha256": pdf_hash,
        "cited_page": page_no,
        "page_count": len(pages),
        "filing_citation": f"Consolidated Financial Results PDF · p. {page_no} of {len(pages)}",
        "screener_url": screener.get("url"),
        "screener_period": screener_period,
        "rows": rows,
    }
