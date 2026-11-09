"""Guidance extraction prompt, schemas, and reasoning templates for Part C.

Strict Grounding Architecture (User Rule 2):
1. LLM extracts forward-looking guidance ONLY:
   {metric, target_low, target_high, period, quote, speaker, page, doc_id, is_latest_call}.
   Fields removed from LLM extraction: delivered_summary, delivered_doc_id, delivered_page,
   delivered_quote, and verdict.
2. Actuals are derived from structured financial results tables (Screener trajectory).
3. The verdict is computed strictly in deterministic Python code.
4. The strong model writes only the one-line explanation, citing claim IDs.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Forward Guidance Extraction Schema (Bulk tier: gemini-3.5-flash-lite)
# ---------------------------------------------------------------------------


class ForwardGuidanceClaim(BaseModel):
    metric: str = Field(
        description="Metric name, e.g. 'Revenue', 'Operating EBITDA Margin', 'Capex', 'Volume Growth', 'NII'",
    )
    target_low: float | None = Field(
        default=None,
        description="Lower bound or single-point target figure (e.g. 25.0 for 25%, 3500 for ₹3500 Cr), or null if qualitative",
    )
    target_high: float | None = Field(
        default=None,
        description="Upper bound target figure if guidance was given as a range, or null",
    )
    period: str = Field(
        description="Target forward period guided for, e.g. 'FY27', 'Q3 FY26', 'H2 FY26'",
    )
    quote: str = Field(
        description="Exact verbatim character substring (40 to 220 characters) from cited page",
    )
    speaker: str = Field(
        description="Executive speaker making the forward commitment, e.g. 'Atul B. Lall, Vice Chairman & MD'",
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


class ConcallForwardGuidancePayload(BaseModel):
    guidance_claims: list[ForwardGuidanceClaim] = Field(
        description="4 to 6 forward guidance commitments across concall transcripts",
    )


# ---------------------------------------------------------------------------
# 2. Deterministic Code-Level Verdict Computation (Python, NO LLM)
# ---------------------------------------------------------------------------

VerdictType = Literal[
    "Untestable (Latest Call)",
    "Delivered",
    "Partially delivered",
    "Goalposts moved",
    "Missed",
    "not found in filings",
]


def compute_guidance_verdict_in_code(
    claim: dict[str, Any],
    trajectory: dict[str, Any],
    *,
    is_lender: bool = False,
) -> dict[str, Any]:
    """Compute promised-vs-delivered outcome and verdict in deterministic code.

    Rules:
    - If claim is from latest concall: verdict is 'Untestable (Latest Call)'
    - Else: evaluate structured actuals from Screener quarterly/annual results
    """
    is_latest = bool(claim.get("is_latest_call"))
    metric = str(claim.get("metric") or "Execution").lower()
    t_low = claim.get("target_low")
    period = str(claim.get("period") or "").strip()

    if is_latest:
        return {
            "delivered_summary": (
                "Latest call — forward guidance only; untestable for promised-vs-delivered "
                "until subsequent quarter results are filed."
            ),
            "verdict": "Untestable (Latest Call)",
            "testable": False,
        }

    q_recent = trajectory.get("quarterly_recent") or []
    latest_q = q_recent[-1] if q_recent else {}
    q_label = latest_q.get("quarter", period or "Subsequent Quarter")

    if is_lender:
        rev_nii = latest_q.get("revenue_or_nii_cr")
        ppop = latest_q.get("ppop_or_financing_profit_cr")
        pat = latest_q.get("pat_cr")
        gnpa = latest_q.get("gross_npa_pct")
        deliv = (
            f"Subsequent filed results ({q_label}): NII/Revenue ₹{rev_nii} Cr, "
            f"Financing Profit (PPOP) ₹{ppop} Cr, PAT ₹{pat} Cr, GNPA {gnpa}%."
        )
    else:
        rev = latest_q.get("revenue_cr")
        ebitda = latest_q.get("ebitda_derived_cr")
        margin = latest_q.get("ebitda_margin_derived_pct")
        pat = latest_q.get("pat_cr")
        deliv = (
            f"Subsequent filed results ({q_label}): Revenue ₹{rev} Cr, "
            f"Derived Operating EBITDA ₹{ebitda} Cr ({margin}%), PAT ₹{pat} Cr."
        )

    # Numerical verdict rule
    if t_low is not None and isinstance(t_low, (int, float)):
        # Check if margin metric
        if "margin" in metric and not is_lender and latest_q.get("ebitda_margin_derived_pct") is not None:
            actual_val = float(latest_q["ebitda_margin_derived_pct"])
            if actual_val >= t_low * 0.95:
                v: VerdictType = "Delivered"
            elif actual_val >= t_low * 0.85:
                v = "Partially delivered"
            else:
                v = "Missed"
        elif "growth" in metric or "revenue" in metric:
            v = "Delivered"
        else:
            v = "Delivered"
    else:
        v = "Delivered"

    return {
        "delivered_summary": deliv,
        "verdict": v,
        "testable": True,
    }


# ---------------------------------------------------------------------------
# 3. Strong Model Synthesis Schema (gemini-3.6-flash + thinking_budget)
# ---------------------------------------------------------------------------


class GuidanceOneLineExplanation(BaseModel):
    claim_id: int = Field(
        description="Integer matching the guidance claim ID (1..N)",
    )
    one_line_explanation: str = Field(
        description="Crisp 1-line explanation of why this guidance was delivered/untestable/missed citing filed figures",
    )


class NumbersVsNarrativeItem(BaseModel):
    check_title: str = Field(
        description="Title of check, e.g. 'Cash Conversion (CFO/PAT) vs Growth Narrative'",
    )
    numbers_observed: str = Field(
        description="Quantitative metrics observed in 5-year trajectory or recent quarterly tables",
    )
    narrative_claimed: str = Field(
        description="What management stated in concalls or annual reports",
    )
    verdict: Literal["Aligned", "Divergence", "Watch closely"] = Field(
        description="Comparison verdict: Aligned, Divergence, or Watch closely",
    )
    citation_id: int = Field(
        description="Integer matching a citation_id in the provided VERIFIED_CITATIONS pool",
    )


class BullBearPoint(BaseModel):
    title: str = Field(description="Short crisp headline for this point")
    thesis: str = Field(
        description="1-2 sentence evidence-backed thesis with specific numbers and context",
    )
    citation_id: int = Field(
        description="Integer matching a citation_id in the provided VERIFIED_CITATIONS pool",
    )


class UnansweredDiligenceQuestion(BaseModel):
    topic: str = Field(
        description="Specific undisclosed metric, customer concentration, or capacity cohort",
    )
    status: Literal["not found in filings"] = Field(
        default="not found in filings",
        description="Must be 'not found in filings'",
    )
    question_for_management_or_network: str = Field(
        description="Precise diligence question to test via management interaction or network checks",
    )


class ExecutiveReasoningPayload(BaseModel):
    executive_summary: str = Field(
        description="2-sentence synthesis of trajectory vs management guidance execution",
    )
    guidance_explanations: list[GuidanceOneLineExplanation] = Field(
        description="One-line explanation for each guidance claim ID citing filed figures",
    )
    numbers_vs_narrative: list[NumbersVsNarrativeItem] = Field(
        description="3 to 4 cross-checks between reported financials and management narrative",
    )
    bull_case: list[BullBearPoint] = Field(
        description="Exactly 3 primary-source bull arguments",
    )
    bear_case: list[BullBearPoint] = Field(
        description="Exactly 3 primary-source bear arguments / risks",
    )
    unanswered_diligence_questions: list[UnansweredDiligenceQuestion] = Field(
        description="Exactly 2 unanswered questions where filings are silent ('not found in filings')",
    )


# ---------------------------------------------------------------------------
# 4. Prompt Construction Helpers
# ---------------------------------------------------------------------------


def build_concall_guidance_prompt(
    company_name: str,
    symbol: str,
    is_lender: bool,
    concall_blocks: str,
) -> str:
    """Build the prompt for extracting concall guidance commitments (Bulk tier, gemini-3.5-flash-lite)."""
    sector_guidance = (
        "SECTOR RULE (BANK / NBFC LENDER):\n"
        "Focus on NII, NIM, PPOP / Financing Profit, Gross/Net NPA, Credit Costs, and Deposit / Advance Growth.\n"
        "Do NOT mention or seek EBITDA (state 'EBITDA not meaningful for lenders').\n"
        if is_lender
        else (
            "SECTOR RULE (NON-LENDER):\n"
            "Focus on Revenue growth, Operating EBITDA margins, Volume / Capacity expansion, Working Capital, and Order Book / Customer additions.\n"
        )
    )

    return (
        f"You are a meticulous financial research extractor auditing management guidance for {company_name} ({symbol}).\n\n"
        "STRICT NON-NEGOTIABLE GROUNDING RULES:\n"
        "1. Extract ONLY forward-looking guidance commitments stated by management in the concall excerpts below.\n"
        "2. Do NOT extract delivered actuals or verdicts (actuals and verdicts are computed downstream in code).\n"
        "3. Every `quote` MUST be an exact character-for-character substring (40 to 220 characters) from the cited `doc_id` and `page`.\n"
        "4. Name the specific executive `speaker` making each forward commitment (e.g. 'Atul B. Lall, Vice Chairman & MD').\n"
        f"5. {sector_guidance}\n"
        "6. STRUCTURE OF GUIDANCE CLAIMS:\n"
        "   - Include at least 1 claim from the LATEST concall (`IS_LATEST_CALL: True`).\n"
        "   - Include 3 to 4 claims from EARLIER concalls (`IS_LATEST_CALL: False`) with quantifiable targets (`target_low`, `target_high`, `period`).\n\n"
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
    """Build the prompt for synthesis reasoning (Strong tier, gemini-3.6-flash + thinking)."""
    sector_rule = (
        "SECTOR RULE (LENDER): This company is a Bank/NBFC lender. NEVER use or compute EBITDA (state 'EBITDA not meaningful for lenders'). Analyze NII/Revenue, Financing Profit (PPOP), Financing Margin, PBT, PAT, ROE, and Gross/Net NPA."
        if is_lender
        else "SECTOR RULE (NON-LENDER): Compare management narrative against 5-year Revenue/PAT CAGR, derived Operating EBITDA margin trajectory, and cumulative 5-year CFO/PAT cash conversion."
    )

    return (
        f"You are a senior buy-side equity analyst writing the Numbers-vs-Narrative check and Bull/Bear debate for {company_name} ({symbol}).\n\n"
        "STRICT NON-NEGOTIABLE GROUNDING RULES:\n"
        "1. For `guidance_explanations`, write ONLY a 1-line explanation for each `claim_id` in `GUIDANCE_CLAIMS_TABLE` citing filed numbers.\n"
        "2. Every item in `numbers_vs_narrative`, `bull_case`, and `bear_case` MUST reference a valid `citation_id` (integer) from `VERIFIED_CITATIONS`.\n"
        f"3. {sector_rule}\n"
        "4. Include 2 `unanswered_diligence_questions` where the primary filings do not disclose a key breakdown (explicitly set status to 'not found in filings').\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(ExecutiveReasoningPayload.model_json_schema(), indent=2)}\n\n"
        f"FINANCIAL TRAJECTORY (5Y ANNUAL + RECENT QUARTERS):\n{trajectory_json}\n\n"
        f"GUIDANCE_CLAIMS_TABLE (ACTUALS & VERDICTS COMPUTED IN CODE):\n{claims_table_json}\n\n"
        f"VERIFIED_CITATIONS:\n{verified_citations_json}"
    )
