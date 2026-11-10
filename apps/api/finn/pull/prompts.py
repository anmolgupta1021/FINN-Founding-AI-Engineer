"""Guidance extraction prompt, schemas, and deterministic verdict engine for Part C.

Strict Grounding Architecture:
1. LLM extracts forward-looking guidance AND historical reported-vs-stated call figures separately:
   - `guidance_claims`: {metric, scope, condition, target_low, target_high, unit, fiscal_period, quote, speaker, page, doc_id, is_latest_call}
   - `reported_vs_stated_claims`: past-quarter numbers stated on calls compared against filed Screener tables (NOT labeled as guidance)
2. Deterministic validators enforce:
   - Quote sentence trimming (no mid-sentence starts or unrelated run-ons)
   - Explicit unit & metric in quote (drops truncated quotes like '33-34')
   - Metric/scope consistency (rejects wider labels like 'Consolidated Revenue' when scope is 'segment'/'product')
   - Code-level quote + numerical verification (rapidfuzz >= 90.0)
3. Verdicts are computed strictly in deterministic Python code:
   - Untestable (Latest Call) -> fixed template text, no LLM explanation
   - segment / product scope or unfiled operational metric -> "Not comparable to filed numbers", fixed template
   - explicit condition -> "Conditional, not scored", fixed template
   - incomplete fiscal period -> progress summary ("2 of 4 quarters filed; H1 = X% of target") + "No verdict (period incomplete)", fixed template
   - ONLY fully reported, consolidated, unconditional numeric targets earn: "Delivered" | "Missed" | "Moved goalposts"
4. Strong model writes 1-line guidance explanations ONLY for rows that earned a verdict, plus citation-validated synthesis.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Extraction Schemas (Bulk tier: gemini-3.5-flash-lite)
# ---------------------------------------------------------------------------


class ForwardGuidanceClaim(BaseModel):
    metric: str = Field(
        description=(
            "Specific metric stated in the quote. If scope is 'segment' or 'product', MUST include the segment/product "
            "name (e.g. 'Display & Camera Module Margin Expansion', 'IT Hardware / JV Business Revenue'). "
            "NEVER label a segment/product target as 'Consolidated Revenue' or bare 'Operating EBITDA Margin'."
        ),
    )
    scope: Literal["consolidated", "segment", "product"] = Field(
        description="'consolidated' if entire company; 'segment' if business vertical/division; 'product' if product line/JV/facility.",
    )
    condition: str | None = Field(
        default=None,
        description="Explicit condition or exclusion stated in the quote (e.g. 'without the Vivo numbers'), or null if unconditional.",
    )
    target_low: float | None = Field(
        default=None,
        description="Lower bound or single-point target figure, or null if qualitative.",
    )
    target_high: float | None = Field(
        default=None,
        description="Upper bound target figure if given as a range, or null.",
    )
    unit: str = Field(
        description="Unit explicitly stated inside the quote (e.g. 'crores', '%', 'bps', 'million units'). Empty string if absent.",
    )
    fiscal_period: str = Field(
        description="Normalized Indian fiscal period guided for relative to call date, e.g. 'FY27', 'H2 FY27', 'Q3 FY27', 'FY28'.",
    )
    quote: str = Field(
        description="ONLY the complete verbatim sentence carrying the forward guidance + metric + number + unit. No mid-sentence starts, no unrelated adjacent sentences.",
    )
    speaker: str = Field(
        description="Executive speaker making the forward commitment, e.g. 'Atul Lall, Vice Chairman & MD'",
    )
    page: int = Field(
        description="1-based page number where the quote appears in the concall transcript",
    )
    doc_id: str = Field(
        description="Exact doc_id matching one of the concall block headers",
    )
    is_latest_call: bool = Field(
        default=False,
        description="True ONLY if this guidance was stated on the most recent concall in the corpus",
    )


class ReportedVsStatedClaim(BaseModel):
    metric: Literal["Revenue", "EBITDA", "EBITDA Margin", "PAT", "NII", "PPOP", "Gross NPA", "ROCE", "ROE"] = Field(
        description="Historical financial metric stated by management for a completed quarter/period",
    )
    quarter_referenced: str = Field(
        description="Screener-style completed quarter/period label, e.g. 'Jun 2026', 'Sep 2026', 'Dec 2025', 'Mar 2026'",
    )
    stated_value: float = Field(
        description="Numeric value stated by management on the call (in Rs Crores for Revenue/EBITDA/PAT/NII/PPOP, or % for Margin/NPA/ROCE/ROE)",
    )
    unit: str = Field(
        description="Unit stated in quote, e.g. 'crores' or '%'",
    )
    quote: str = Field(
        description="Complete verbatim sentence from the concall stating this historical quarter figure",
    )
    speaker: str = Field(
        description="Executive speaker stating the historical figure",
    )
    page: int = Field(
        description="1-based page number in the concall transcript",
    )
    doc_id: str = Field(
        description="Exact concall doc_id",
    )


class ConcallForwardGuidancePayload(BaseModel):
    guidance_claims: list[ForwardGuidanceClaim] = Field(
        description="1 to 2 forward guidance commitments per concall across ALL concalls (up to 8 total)",
    )
    reported_vs_stated_claims: list[ReportedVsStatedClaim] = Field(
        default_factory=list,
        description="2 to 4 historical past-quarter financial figures stated in concalls for cross-checking against filed results",
    )


# ---------------------------------------------------------------------------
# 2. Deterministic Trimming, Unit/Metric & Scope Consistency Validators
# ---------------------------------------------------------------------------

_UNIT_IN_QUOTE_RE = re.compile(
    r"(?:%|percent|per\s+cent|bps|basis\s+points?|crores?|cr\b|lakhs?|millions?|mn\b|billions?|bn\b|"
    r"₹|rs\.?|inr|usd|\$|units?|pieces?|sets?|phones?|tons?|tonnes?|mt\b|mw\b|gw\b|kv\b|x\b)",
    re.IGNORECASE,
)

_UNFILED_METRICS_RE = re.compile(
    r"\b(?:volume|volumes|capacity|units|phones|smartphones|lighting|refrigerators|tvs|washing\s*machines|"
    r"sq\s*ft|headcount|plants|factory|facilities|long-term|run\s*rate|order\s*book|dealer|stores|capex|export\s+numbers?)\b",
    re.IGNORECASE,
)

_WIDER_SCOPE_RE = re.compile(
    r"\b(?:consolidated|company[-\s]*wide|overall|group|total\s+company|standalone\s+company|enterprise)\b",
    re.IGNORECASE,
)

_BARE_COMPANY_METRICS = frozenset({
    "operating ebitda margin",
    "ebitda margin",
    "ebitda",
    "revenue",
    "sales",
    "turnover",
    "pat",
    "net profit",
    "pbt",
    "profit",
    "nii",
    "nim",
    "ppop",
    "roce",
    "roe",
})

_FORWARD_VERB_RE = re.compile(
    r"\b(?:target(?:ing)?|guid(?:e|ance|ing)|expect(?:ing|ed)?|should\s+be|feel|aim(?:ing)?|"
    r"project(?:ed|ing)?|outlook|expand|improve|next\s+(?:year|fiscal|quarter|couple)|fy\s*'?\d{2})\b",
    re.IGNORECASE,
)


def trim_quote_to_guidance_sentence(quote: str, page_text: str | None = None, *, is_historical: bool = False) -> str:
    """Trim a raw extracted excerpt to the clean complete sentence carrying the claim.

    - Strips leading mid-sentence fragments (e.g. 'business. We feel...' or 'So, ...')
    - Strips trailing unrelated run-on sentences (e.g. 'Further, as I mentioned...')
    """
    cleaned = re.sub(r"\s+", " ", (quote or "").strip())
    if not cleaned:
        return cleaned

    # Split on sentence boundaries (keeping decimal numbers intact)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", cleaned) if s.strip()]
    if len(sentences) <= 1:
        # Check if single string starts mid-sentence before a period like "business. We feel..."
        m_lead = re.match(r"^[a-z][^.]*\.\s+([A-Z].+)$", cleaned)
        if m_lead:
            return m_lead.group(1).strip()
        return cleaned

    # Filter out leading broken lowercase fragments
    if re.match(r"^[a-z]", sentences[0]) and len(sentences) > 1:
        sentences = sentences[1:]

    # Filter to sentences that actually end cleanly if others exist, or keep sentences with numbers + units
    scored: list[tuple[int, int, str]] = []
    for idx, sent in enumerate(sentences):
        has_num = bool(re.search(r"\d", sent))
        has_unit = bool(_UNIT_IN_QUOTE_RE.search(sent))
        has_fwd = bool(_FORWARD_VERB_RE.search(sent))
        ends_clean = sent.endswith((".", "!", "?"))
        starts_clean = bool(re.match(r"^[A-Z\"']", sent))

        score = 0
        if has_num and has_unit:
            score += 50
        elif has_num:
            score += 15
        if not is_historical and has_fwd:
            score += 30
        if ends_clean:
            score += 10
        if starts_clean:
            score += 10
        scored.append((score, -idx, sent))

    scored.sort(reverse=True)
    best_sent = scored[0][2]
    return best_sent


def validate_claim_unit_and_metric(claim: dict[str, Any]) -> tuple[bool, str | None]:
    """Ensure the quote itself contains an explicit unit and a stated metric.

    Drops truncated quotes like 'around 33-34' that omit the unit.
    """
    metric = str(claim.get("metric") or "").strip()
    unit = str(claim.get("unit") or "").strip()
    quote = str(claim.get("quote") or "").strip()

    if not metric or metric.lower() in {"unknown", "n/a", "none", "null"}:
        return False, "missing_metric"
    if not unit or unit.lower() in {"unknown", "n/a", "none", "null"}:
        return False, "missing_unit"
    if not _UNIT_IN_QUOTE_RE.search(quote):
        return False, "missing_unit_in_quote"

    u_low = unit.lower()
    q_low = quote.lower()
    if ("million" in u_low or "mn" in u_low) and not re.search(r"(?:million|mn\b)", q_low):
        return False, "unit_not_in_quote"
    if re.search(r"\b(?:crores?|cr|inr|rs\.?)\b|₹", u_low) and not re.search(
        r"(?:crores?|cr\b|inr|\brs\.?|₹)", q_low
    ):
        return False, "unit_not_in_quote"
    if "bps" in u_low and not re.search(r"(?:bps|basis\s+points?)", q_low):
        return False, "unit_not_in_quote"
    if ("%" in u_low or "percent" in u_low) and not re.search(r"(?:%|percent|per\s+cent)", q_low):
        return False, "unit_not_in_quote"

    return True, None


def validate_claim_scope_consistency(claim: dict[str, Any]) -> tuple[bool, str | None]:
    """Reject claims whose metric label implies a wider scope than its scope tag.

    Example: 'Consolidated Revenue' or bare 'Operating EBITDA Margin' with scope='segment' is rejected.
    """
    scope = str(claim.get("scope") or "").strip().lower()
    metric = str(claim.get("metric") or "").strip()
    m_low = metric.lower()

    if scope not in {"consolidated", "segment", "product"}:
        return False, f"invalid_scope:{scope}"

    if scope in {"segment", "product"}:
        if _WIDER_SCOPE_RE.search(m_low):
            return False, "scope_mismatch_wider_label_on_segment_or_product"
        if m_low in _BARE_COMPANY_METRICS:
            return False, "scope_mismatch_bare_company_metric_without_segment_qualifier"

    return True, None


def resolve_fiscal_period_quarters(fiscal_period: str | None) -> list[str] | None:
    """Resolve Indian FY notation (e.g. 'FY27', 'H1 FY27', 'Q3 FY26') to Screener quarter labels."""
    if not fiscal_period:
        return None
    fp = re.sub(r"\s+", " ", fiscal_period.strip())

    direct_m = re.match(r"^(Jun|Sep|Dec|Mar)\s+(20\d{2})$", fp, re.IGNORECASE)
    if direct_m:
        return [f"{direct_m.group(1).title()} {direct_m.group(2)}"]

    m = re.search(
        r"\b(?:(?P<subq>Q[1-4]|H[12]|9M)\s*)?FY\s*'?(?P<yr>\d{2,4})\b",
        fp,
        re.IGNORECASE,
    )
    if not m:
        return None

    yr_num = int(m.group("yr"))
    end_yr = yr_num if yr_num >= 2000 else 2000 + yr_num
    start_yr = end_yr - 1

    quarters_all = [
        f"Jun {start_yr}",
        f"Sep {start_yr}",
        f"Dec {start_yr}",
        f"Mar {end_yr}",
    ]

    subq = (m.group("subq") or "").upper()
    if subq == "Q1":
        return [quarters_all[0]]
    if subq == "Q2":
        return [quarters_all[1]]
    if subq == "Q3":
        return [quarters_all[2]]
    if subq == "Q4":
        return [quarters_all[3]]
    if subq == "H1":
        return quarters_all[:2]
    if subq == "H2":
        return quarters_all[2:]
    if subq == "9M":
        return quarters_all[:3]
    return quarters_all


# ---------------------------------------------------------------------------
# 3. Deterministic Code-Level Verdict & Reported-vs-Stated Engines
# ---------------------------------------------------------------------------

VerdictType = Literal[
    "Untestable (Latest Call)",
    "Not comparable to filed numbers",
    "Conditional, not scored",
    "No verdict (period incomplete)",
    "Delivered",
    "Missed",
    "Moved goalposts",
]

SCORED_VERDICTS = frozenset({"Delivered", "Missed", "Moved goalposts"})


def _normalize_stated_to_crores(
    stated_f: float,
    *,
    unit: str,
    quote: str,
    col: str,
) -> tuple[float, str]:
    """Normalize INR stated figure in millions/billions/lakhs into INR Crores when Screener col is Cr."""
    if col not in {"revenue_cr", "revenue_or_nii_cr", "pat_cr", "ebitda_derived_cr", "ppop_or_financing_profit_cr"}:
        return stated_f, unit or "%"
    combined = f"{unit} {quote}".lower()
    if re.search(r"\b(?:billion|bn)\b", combined):
        return round(stated_f * 100.0, 2), "crores (from billion)"
    if re.search(r"\b(?:million|mn)\b", combined):
        return round(stated_f / 10.0, 2), "crores (from million)"
    if re.search(r"\b(?:lakh|lac)s?\b", combined):
        return round(stated_f / 100.0, 2), "crores (from lakh)"
    return stated_f, unit or "crores"


def compute_reported_vs_stated_in_code(
    claim: dict[str, Any],
    trajectory: dict[str, Any],
    *,
    is_lender: bool = False,
) -> dict[str, Any] | None:
    """Compare a past-quarter figure stated on a concall against Screener filed numbers."""
    q_label = str(claim.get("quarter_referenced") or "").strip()
    metric = str(claim.get("metric") or "").strip()
    stated_val = claim.get("stated_value")
    unit = str(claim.get("unit") or "").strip()
    quote = str(claim.get("quote") or "").strip()
    if not q_label or stated_val is None:
        return None

    m_low = metric.lower()
    col_map: dict[str, str] = {
        "revenue": "revenue_or_nii_cr" if is_lender else "revenue_cr",
        "nii": "revenue_or_nii_cr",
        "ebitda": "ppop_or_financing_profit_cr" if is_lender else "ebitda_derived_cr",
        "ppop": "ppop_or_financing_profit_cr",
        "ebitda margin": "financing_margin_pct" if is_lender else "ebitda_margin_derived_pct",
        "pat": "pat_cr",
        "gross npa": "gross_npa_pct",
        "roce": "roce_pct",
    }
    col = col_map.get(m_low)
    stated_norm, normalized_unit = _normalize_stated_to_crores(
        float(stated_val), unit=unit, quote=quote, col=col or ""
    )

    q_recent = trajectory.get("quarterly_recent") or []
    ann_5y = trajectory.get("annual_5y") or []
    q_row = next((q for q in q_recent if q.get("quarter", "").lower() == q_label.lower()), None)
    ann_row = next((a for a in ann_5y if a.get("period", "").lower() == q_label.lower()), None)

    # Pick annual row when statement cites full-year figure (e.g. FY26 Mar 2026 milestone ~3x quarterly)
    row = q_row or ann_row
    period_compared = q_label
    if q_row and ann_row and col and q_row.get(col) and ann_row.get(col):
        qv = float(q_row[col])
        av = float(ann_row[col])
        if qv > 0 and av > 0 and abs(stated_norm - av) / av < 0.15 and abs(stated_norm - qv) / qv > 1.0:
            row = ann_row
            period_compared = f"{q_label} (Full-Year)"

    if not row:
        return {
            "quarter_referenced": period_compared,
            "metric": metric,
            "stated_value": stated_norm,
            "unit": normalized_unit,
            "filed_value": None,
            "variance": None,
            "variance_pct": None,
            "status": "Filed quarter outside recent table",
            "label": "stated vs filed",
        }

    filed_val = row.get(col) if col else None
    if filed_val is None:
        return {
            "quarter_referenced": period_compared,
            "metric": metric,
            "stated_value": stated_norm,
            "unit": normalized_unit,
            "filed_value": None,
            "variance": None,
            "variance_pct": None,
            "status": "Metric not disclosed in Screener row",
            "label": "stated vs filed",
        }

    filed_f = float(filed_val)
    variance = round(stated_norm - filed_f, 2)
    variance_pct = round(((stated_norm - filed_f) / filed_f) * 100, 1) if filed_f != 0 else 0.0
    if col in {"ebitda_margin_derived_pct", "financing_margin_pct"} and abs(variance) <= 0.6:
        status = "Match (within Screener integer rounding)"
    elif abs(variance_pct) <= 2.0:
        status = "Match (within 2%)"
    else:
        status = "Variance vs filed (check one-offs / ex-items)"

    return {
        "quarter_referenced": period_compared,
        "metric": metric,
        "stated_value": stated_norm,
        "unit": normalized_unit,
        "filed_value": filed_f,
        "variance": variance,
        "variance_pct": variance_pct,
        "status": status,
        "label": "stated vs filed",
    }


def _summarize_period_progress(
    *,
    metric: str,
    unit: str,
    t_low: float | None,
    req_quarters: list[str],
    filed_quarters: list[dict[str, Any]],
    q_by_label: dict[str, dict[str, Any]],
    is_lender: bool,
) -> str:
    n_filed = len(filed_quarters)
    n_req = len(req_quarters)
    if n_filed == 0:
        return f"0 of {n_req} quarters filed ({', '.join(req_quarters)}); no results reported yet."

    labels_str = ", ".join(q["quarter"] for q in filed_quarters)
    prefix = "H1" if n_filed == 2 and filed_quarters[0]["quarter"].startswith("Jun") else "Reported"
    m_low = metric.lower()
    u_low = unit.lower()

    if "margin" in m_low and not is_lender:
        margins = [q.get("ebitda_margin_derived_pct") for q in filed_quarters if q.get("ebitda_margin_derived_pct") is not None]
        if margins:
            avg_m = round(sum(float(x) for x in margins) / len(margins), 2)
            target_str = f" vs {t_low}% target" if t_low is not None else ""
            return f"{n_filed} of {n_req} quarters filed ({labels_str}); {prefix} avg EBITDA margin = {avg_m}%{target_str}."

    rev_key = "revenue_or_nii_cr" if is_lender else "revenue_cr"
    if ("%" in u_low or "percent" in u_low) and ("growth" in m_low or "revenue" in m_low):
        cur_sum = sum(float(q.get(rev_key) or 0.0) for q in filed_quarters)
        prior_vals: list[float] = []
        for q in filed_quarters:
            parts = q["quarter"].split()
            if len(parts) == 2:
                pq = q_by_label.get(f"{parts[0]} {int(parts[1]) - 1}")
                if pq and pq.get(rev_key) is not None:
                    prior_vals.append(float(pq[rev_key]))
        if len(prior_vals) == n_filed and sum(prior_vals) > 0:
            yoy = round(((cur_sum - sum(prior_vals)) / sum(prior_vals)) * 100, 1)
            target_str = f" vs {t_low}% target" if t_low is not None else ""
            return f"{n_filed} of {n_req} quarters filed ({labels_str}); {prefix} YoY revenue growth = {yoy}%{target_str}."
        return f"{n_filed} of {n_req} quarters filed ({labels_str}); {prefix} revenue = ₹{cur_sum:,.0f} Cr."

    if t_low is not None and t_low > 0 and ("revenue" in m_low or "sales" in m_low or "turnover" in m_low or "pat" in m_low):
        col = "pat_cr" if "pat" in m_low or "profit" in m_low else rev_key
        actual_sum = sum(float(q.get(col) or 0.0) for q in filed_quarters)
        pct = round((actual_sum / float(t_low)) * 100, 1)
        return (
            f"{n_filed} of {n_req} quarters filed ({labels_str}); "
            f"{prefix} = ₹{actual_sum:,.0f} Cr ({pct}% of ₹{t_low:,.0f} Cr target)"
        )

    actual_sum = sum(float(q.get(rev_key) or 0.0) for q in filed_quarters)
    return f"{n_filed} of {n_req} quarters filed ({labels_str}); {prefix} revenue = ₹{actual_sum:,.0f} Cr."


def compute_guidance_verdict_in_code(
    claim: dict[str, Any],
    trajectory: dict[str, Any],
    *,
    is_lender: bool = False,
) -> dict[str, Any]:
    """Compute promised-vs-delivered outcome and verdict strictly in deterministic code."""
    is_latest = bool(claim.get("is_latest_call"))
    metric = str(claim.get("metric") or "Execution").strip()
    scope = str(claim.get("scope") or "consolidated").strip().lower()
    raw_cond = claim.get("condition")
    condition = str(raw_cond).strip() if raw_cond and str(raw_cond).strip().lower() not in {"none", "null", "n/a"} else None
    t_low = claim.get("target_low")
    unit = str(claim.get("unit") or "").strip()
    fiscal_period = str(claim.get("fiscal_period") or claim.get("period") or "").strip()

    # 1. Latest call
    if is_latest:
        return {
            "delivered_summary": (
                "Latest call — forward guidance only; untestable for promised-vs-delivered "
                "until subsequent quarter results are filed."
            ),
            "verdict": "Untestable (Latest Call)",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": (
                "Fixed template: Guidance was stated on the latest available concall and "
                "remains untestable until subsequent quarterly results are filed."
            ),
        }

    # 2. Scope (segment/product) or unfiled operational metric (check metric ONLY, never accidental words in quote)
    if scope in {"segment", "product"}:
        return {
            "delivered_summary": (
                f"Not comparable to filed numbers: {scope}-level guidance ('{metric}') "
                "is not broken out in consolidated quarterly financial statements."
            ),
            "verdict": "Not comparable to filed numbers",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": (
                f"Fixed template: {scope.capitalize()}-level guidance ('{metric}') cannot be scored "
                "against consolidated financial statements."
            ),
        }

    if _UNFILED_METRICS_RE.search(metric):
        return {
            "delivered_summary": (
                f"Not comparable to filed numbers: operational metric ('{metric}') "
                "is not reported in filed quarterly financial statements."
            ),
            "verdict": "Not comparable to filed numbers",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": (
                f"Fixed template: Operational or capex metric ('{metric}') is not disclosed in "
                "quarterly financial tables and is not scored."
            ),
        }

    q_recent = trajectory.get("quarterly_recent") or []
    ann_5y = trajectory.get("annual_5y") or []
    q_by_label = {q["quarter"]: q for q in q_recent if q.get("quarter")}
    req_quarters = resolve_fiscal_period_quarters(fiscal_period)
    filed_quarters = [q_by_label[ql] for ql in (req_quarters or []) if ql in q_by_label]

    # 3. Conditional guidance
    if condition:
        progress_note = ""
        if req_quarters:
            progress_note = " " + _summarize_period_progress(
                metric=metric,
                unit=unit,
                t_low=t_low if isinstance(t_low, (int, float)) else None,
                req_quarters=req_quarters,
                filed_quarters=filed_quarters,
                q_by_label=q_by_label,
                is_lender=is_lender,
            )
        return {
            "delivered_summary": f"Conditional, not scored (condition: '{condition}').{progress_note}",
            "verdict": "Conditional, not scored",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": (
                f"Fixed template: Guidance is explicitly conditional ('{condition}') and "
                "is not scored against unadjusted consolidated filings."
            ),
        }

    # 4. Require numeric target
    if t_low is None or not isinstance(t_low, (int, float)):
        return {
            "delivered_summary": "Not comparable to filed numbers: qualitative guidance without an unconditional numeric target.",
            "verdict": "Not comparable to filed numbers",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": "Fixed template: Qualitative guidance without a numeric target is not scored.",
        }

    # 5. Resolve guided fiscal period to quarters & check completeness
    if not req_quarters:
        return {
            "delivered_summary": f"Period '{fiscal_period or 'unspecified'}' does not map to a completed quarterly horizon; no verdict assigned.",
            "verdict": "No verdict (period incomplete)",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": "Fixed template: Guided horizon could not be resolved to filed quarterly periods.",
        }

    ann_match = None
    if len(req_quarters) == 4:
        end_label = req_quarters[-1]
        ann_match = next((a for a in ann_5y if a.get("period") == end_label), None)

    if len(filed_quarters) < len(req_quarters) and ann_match is None:
        progress = _summarize_period_progress(
            metric=metric,
            unit=unit,
            t_low=float(t_low),
            req_quarters=req_quarters,
            filed_quarters=filed_quarters,
            q_by_label=q_by_label,
            is_lender=is_lender,
        )
        return {
            "delivered_summary": progress,
            "verdict": "No verdict (period incomplete)",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": (
                f"Fixed template: {fiscal_period} is incomplete ({len(filed_quarters)} of {len(req_quarters)} "
                "quarters filed); showing progress only without a verdict."
            ),
        }

    # 6. Fully reported, consolidated, unconditional numeric target -> Delivered | Missed | Moved goalposts
    if claim.get("goalposts_moved"):
        return {
            "delivered_summary": f"Subsequent concall revised {metric} guidance for {fiscal_period}; marked Moved goalposts.",
            "verdict": "Moved goalposts",
            "testable": True,
            "has_verdict": True,
            "one_line_explanation": None,
        }

    m_low = metric.lower()
    u_low = unit.lower()
    rev_key = "revenue_or_nii_cr" if is_lender else "revenue_cr"
    target_val = float(t_low)

    if "margin" in m_low and not is_lender:
        if filed_quarters:
            margins = [float(q["ebitda_margin_derived_pct"]) for q in filed_quarters if q.get("ebitda_margin_derived_pct") is not None]
            actual_val = round(sum(margins) / len(margins), 2) if margins else None
        elif ann_match and ann_match.get("ebitda_margin_derived_pct") is not None:
            actual_val = float(ann_match["ebitda_margin_derived_pct"])
        else:
            actual_val = None

        if actual_val is None:
            return {
                "delivered_summary": "Not comparable to filed numbers: margin data missing for resolved period.",
                "verdict": "Not comparable to filed numbers",
                "testable": False,
                "has_verdict": False,
                "one_line_explanation": "Fixed template: Margin data is unavailable for the resolved reporting period.",
            }
        v: VerdictType = "Delivered" if actual_val >= target_val else "Missed"
        deliv = f"Filed {fiscal_period} ({', '.join(req_quarters)}): Derived Operating EBITDA Margin {actual_val}% vs guided {target_val}%."
        return {
            "delivered_summary": deliv,
            "verdict": v,
            "testable": True,
            "has_verdict": True,
            "one_line_explanation": None,
        }

    if "npa" in m_low and is_lender:
        gnpas = [float(q["gross_npa_pct"]) for q in filed_quarters if q.get("gross_npa_pct") is not None]
        if not gnpas:
            return {
                "delivered_summary": "Not comparable to filed numbers: Gross NPA not reported for resolved period.",
                "verdict": "Not comparable to filed numbers",
                "testable": False,
                "has_verdict": False,
                "one_line_explanation": "Fixed template: Gross NPA data is unavailable for the resolved period.",
            }
        actual_gnpa = gnpas[-1]
        v = "Delivered" if actual_gnpa <= target_val else "Missed"
        deliv = f"Filed {fiscal_period}: Gross NPA {actual_gnpa}% vs guided ceiling {target_val}%."
        return {
            "delivered_summary": deliv,
            "verdict": v,
            "testable": True,
            "has_verdict": True,
            "one_line_explanation": None,
        }

    if ("%" in u_low or "percent" in u_low) and ("growth" in m_low or "revenue" in m_low or "sales" in m_low):
        if len(filed_quarters) == len(req_quarters):
            cur_sum = sum(float(q.get(rev_key) or 0.0) for q in filed_quarters)
            prior_vals: list[float] = []
            for q in filed_quarters:
                parts = q["quarter"].split()
                if len(parts) == 2:
                    pq = q_by_label.get(f"{parts[0]} {int(parts[1]) - 1}")
                    if pq and pq.get(rev_key) is not None:
                        prior_vals.append(float(pq[rev_key]))
            if len(prior_vals) == len(filed_quarters) and sum(prior_vals) > 0:
                actual_growth = round(((cur_sum - sum(prior_vals)) / sum(prior_vals)) * 100, 1)
                v = "Delivered" if actual_growth >= target_val else "Missed"
                deliv = f"Filed {fiscal_period}: Revenue ₹{cur_sum:,.0f} Cr (+{actual_growth}% YoY) vs guided +{target_val}%."
                return {
                    "delivered_summary": deliv,
                    "verdict": v,
                    "testable": True,
                    "has_verdict": True,
                    "one_line_explanation": None,
                }
        return {
            "delivered_summary": f"Prior-year baseline unavailable in quarterly table for {fiscal_period}; not scored.",
            "verdict": "Not comparable to filed numbers",
            "testable": False,
            "has_verdict": False,
            "one_line_explanation": "Fixed template: Prior-year comparison quarters are not in the recent table.",
        }

    if "revenue" in m_low or "sales" in m_low or "turnover" in m_low or "pat" in m_low or "profit" in m_low:
        col = "pat_cr" if ("pat" in m_low or "profit" in m_low) else rev_key
        if len(filed_quarters) == len(req_quarters):
            actual_val = sum(float(q.get(col) or 0.0) for q in filed_quarters)
        else:
            actual_val = float((ann_match or {}).get(col) or 0.0)
        v = "Delivered" if actual_val >= target_val else "Missed"
        deliv = f"Filed {fiscal_period}: Actual ₹{actual_val:,.0f} Cr vs guided target ₹{target_val:,.0f} Cr."
        return {
            "delivered_summary": deliv,
            "verdict": v,
            "testable": True,
            "has_verdict": True,
            "one_line_explanation": None,
        }

    return {
        "delivered_summary": f"Not comparable to filed numbers: metric '{metric}' not mapped to quarterly table.",
        "verdict": "Not comparable to filed numbers",
        "testable": False,
        "has_verdict": False,
        "one_line_explanation": f"Fixed template: Metric '{metric}' is not directly comparable to Screener quarterly columns.",
    }


# ---------------------------------------------------------------------------
# 4. Strong Model Synthesis Schema
# ---------------------------------------------------------------------------


class GuidanceOneLineExplanation(BaseModel):
    claim_id: int = Field(description="Integer matching a scored verdict guidance claim ID")
    one_line_explanation: str = Field(
        description="Crisp 1-line explanation citing filed figures and why this claim was Delivered/Missed/Moved goalposts",
    )


class NumbersVsNarrativeItem(BaseModel):
    check_title: str = Field(description="Title of check, e.g. 'Cash Conversion (CFO/PAT) vs Growth Narrative'")
    numbers_observed: str = Field(description="Quantitative metrics observed in 5-year trajectory or recent quarterly tables")
    narrative_claimed: str = Field(
        description="1 sentence stating what management claimed, ending with exact citation tag [C<id>] from VERIFIED_CITATIONS",
    )
    verdict: Literal["Aligned", "Divergence", "Watch closely"] = Field(description="Aligned, Divergence, or Watch closely")
    citation_id: int = Field(description="Integer matching a citation_id in VERIFIED_CITATIONS")


class BullBearPoint(BaseModel):
    title: str = Field(description="Short crisp headline for this point")
    thesis: str = Field(
        description="1 sentence evidence-backed thesis citing specific numbers and ending with [C<id>] from VERIFIED_CITATIONS. Every sentence MUST carry a resolvable [C<id>].",
    )
    citation_id: int = Field(description="Integer matching a citation_id in VERIFIED_CITATIONS")


class UnansweredDiligenceQuestion(BaseModel):
    topic: str = Field(description="Specific undisclosed metric, customer concentration, or capacity cohort")
    status: Literal["not found in filings"] = Field(default="not found in filings")
    question_for_management_or_network: str = Field(description="Precise diligence question")


class ExecutiveReasoningPayload(BaseModel):
    executive_summary: str = Field(description="2-sentence synthesis of trajectory vs management guidance execution")
    guidance_explanations: list[GuidanceOneLineExplanation] = Field(
        description="One-line explanation ONLY for scored claims in GUIDANCE_CLAIMS_AND_CODE_VERDICTS (empty list if none)",
    )
    numbers_vs_narrative: list[NumbersVsNarrativeItem] = Field(description="3 cross-checks between financials and narrative")
    bull_case: list[BullBearPoint] = Field(description="3 primary-source bull arguments")
    bear_case: list[BullBearPoint] = Field(description="3 primary-source bear arguments / risks")
    unanswered_diligence_questions: list[UnansweredDiligenceQuestion] = Field(description="2 unanswered questions")


# ---------------------------------------------------------------------------
# 5. Prompt Construction Helpers
# ---------------------------------------------------------------------------


def build_concall_guidance_prompt(
    company_name: str,
    symbol: str,
    is_lender: bool,
    concall_blocks: str,
) -> str:
    """Build the prompt for extracting concall guidance AND historical reported-vs-stated claims."""
    sector_guidance = (
        "SECTOR RULE (BANK / NBFC LENDER): Focus on NII, NIM, PPOP, Gross/Net NPA, Credit Costs, Deposits/Advances. Never mention EBITDA."
        if is_lender
        else "SECTOR RULE (NON-LENDER): Focus on Consolidated Revenue, Operating EBITDA Margin, PAT, and specific Segment/Product targets."
    )

    return (
        f"You are a meticulous financial research extractor auditing {company_name} ({symbol}).\n\n"
        "STRICT NON-NEGOTIABLE GROUNDING RULES:\n"
        "1. `guidance_claims`: Extract ONLY forward-looking guidance commitments across ALL concall DOC_IDs below (1 to 2 claims per concall).\n"
        "   - Check EVERY concall DOC_ID individually (both IS_LATEST_CALL: True and IS_LATEST_CALL: False).\n"
        "   - Do NOT put past-quarter actuals into `guidance_claims` — put past-quarter figures into `reported_vs_stated_claims`!\n"
        "2. CLEAN SENTENCE RULE FOR `quote`:\n"
        "   - Extract ONLY the complete verbatim sentence containing the target + metric + number + unit.\n"
        "   - NEVER start mid-sentence (e.g. 'business. We feel...') and NEVER include unrelated adjacent sentences.\n"
        "   - CRITICAL: The quote MUST explicitly include the unit (e.g. 'crores', 'bps', '%', 'million').\n"
        "3. METRIC/SCOPE CONSISTENCY RULE:\n"
        "   - If `scope` is 'segment' or 'product', `metric` MUST name the specific segment/product/JV (e.g. 'IT Hardware / Inventec JV Business Revenue', 'Display & Camera Module Margin Expansion').\n"
        "   - NEVER label a segment/product target as 'Consolidated Revenue' or bare 'Operating EBITDA Margin'. Reserve 'Consolidated ...' strictly for `scope='consolidated'`.\n"
        "4. Populate `condition` if explicitly stated (e.g. 'without the Vivo numbers'), else null.\n"
        "5. Normalize `fiscal_period` using Indian FY notation (e.g. May 2026 call saying 'next year' -> 'FY27'; 'next couple of years' in Oct 2026 call -> 'FY28').\n"
        "6. `reported_vs_stated_claims`: Extract 2 to 4 past-quarter reported Revenue / EBITDA / EBITDA Margin / PAT / NII / GNPA statements from the opening remarks (one per completed quarter where available) for filed cross-checking.\n"
        f"7. {sector_guidance}\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(ConcallForwardGuidancePayload.model_json_schema(), indent=2)}\n\n"
        f"CONCALL TRANSCRIPT EXCERPTS:\n{concall_blocks}"
    )


def build_reasoning_prompt(
    company_name: str,
    symbol: str,
    is_lender: bool,
    trajectory_json: str,
    claims_table_json: str,
    verified_citations_json: str,
) -> str:
    """Build the reasoning prompt for the Strong model."""
    explanation_rule = (
        "1. For `guidance_explanations`, write ONLY a crisp 1-line explanation for each scored `claim_id` in "
        "`GUIDANCE_CLAIMS_AND_CODE_VERDICTS` citing code-computed actuals and verdict. Do NOT alter the verdict."
        if claims_table_json.strip() not in {"[]", ""}
        else "1. No guidance rows earned a numeric verdict; return an empty list `[]` for `guidance_explanations`."
    )

    return (
        f"You are a senior equity research analyst authoring the synthesis for {company_name} ({symbol}).\n\n"
        "CRITICAL RULES:\n"
        f"{explanation_rule}\n"
        "2. For `numbers_vs_narrative`, `bull_case`, and `bear_case`:\n"
        "   - Every item MUST reference an integer `citation_id` present in `VERIFIED_CITATIONS`.\n"
        "   - Write 1 crisp sentence (or 1-2 sentences where EVERY sentence explicitly includes `[C<id>]`, e.g. `[C4]`, referencing a valid integer in `VERIFIED_CITATIONS`). Any sentence without a valid resolvable `[C<id>]` will be dropped in post-processing.\n"
        "3. Use ONLY figures in `FINANCIAL_TRAJECTORY` and quotes in `VERIFIED_CITATIONS`. Do NOT invent figures.\n"
        f"{'4. LENDER RULE: Never mention EBITDA; analyze NII, PPOP/Financing Profit, NIM, and GNPA/NNPA.' if is_lender else '4. NON-LENDER RULE: Focus on revenue scale, derived operating EBITDA margin, CFO/PAT cash conversion, and ROCE.'}\n\n"
        f"FINANCIAL_TRAJECTORY:\n{trajectory_json}\n\n"
        f"GUIDANCE_CLAIMS_AND_CODE_VERDICTS:\n{claims_table_json}\n\n"
        f"VERIFIED_CITATIONS:\n{verified_citations_json}\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(ExecutiveReasoningPayload.model_json_schema(), indent=2)}"
    )
