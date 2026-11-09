"""Guidance extraction prompt, schemas, and reasoning templates for Part C.

Enforces:
1. Pydantic structured schemas for concall guidance commitments & executive synthesis.
2. Code-level citation verification schema ({doc_id, page, verbatim_quote, speaker}).
3. Strict sector-aware rules (Lenders vs Non-lenders).
4. Verbatim quote grounding (40 to 220 chars) with exact numerical token validation.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured LLM Extraction
# ---------------------------------------------------------------------------

VerdictType = Literal[
    "Untestable (Latest Call)",
    "Delivered",
    "Partially delivered",
    "Goalposts moved",
    "Missed",
    "not found in filings",
]

NumbersVerdictType = Literal["Aligned", "Divergence", "Watch closely"]


class GuidanceCommitment(BaseModel):
    period_called: str = Field(
        description="Concall label, e.g. 'Q2 FY27 Concall (Latest)' or 'Q1 FY27 Concall'",
    )
    is_latest_call: bool = Field(
        description="True ONLY for the most recent concall in the corpus",
    )
    topic: str = Field(
        description="Topic of guidance, e.g. 'Mobile Division Revenue', 'Operating EBITDA Margins', 'Capex Commissioning', 'NII/NIM Outlook'",
    )
    speaker: str = Field(
        description="Executive speaker making the forward guidance commitment, e.g. 'Atul B. Lall, Vice Chairman & MD'",
    )
    promised_guidance: str = Field(
        description="Summary of forward-looking guidance commitment made by management",
    )
    promised_doc_id: str = Field(
        description="Exact doc_id matching one of the concall block headers",
    )
    promised_page: int = Field(
        description="1-based page number where the promised quote appears",
    )
    promised_quote: str = Field(
        description="Exact verbatim character substring (40 to 220 chars) from the cited page",
    )
    delivered_summary: str = Field(
        description="Delivered outcome reported in subsequent concall or quarterly results table. For latest call, must state forward guidance untestable until next quarter filed.",
    )
    delivered_doc_id: str | None = Field(
        default=None,
        description="Exact doc_id of subsequent concall where delivery was reported, or null if latest call",
    )
    delivered_page: int | None = Field(
        default=None,
        description="1-based page number of delivered quote, or null if latest call",
    )
    delivered_quote: str | None = Field(
        default=None,
        description="Exact verbatim substring from subsequent concall page, or null if latest call",
    )
    verdict: VerdictType = Field(
        description="Audit verdict. MUST be 'Untestable (Latest Call)' for is_latest_call=True",
    )


class ConcallGuidancePayload(BaseModel):
    promised_vs_delivered: list[GuidanceCommitment] = Field(
        description="4 to 5 guidance commitments across recent concalls, with Row 1 being the latest call (untestable)",
    )


class NumbersVsNarrativeItem(BaseModel):
    check_title: str = Field(
        description="Title of check, e.g. 'Cash Conversion (CFO/PAT) vs Capacity Expansion'",
    )
    numbers_observed: str = Field(
        description="Quantitative metrics observed in 5-year trajectory or recent quarterly tables",
    )
    narrative_claimed: str = Field(
        description="What management stated in concalls or annual reports",
    )
    verdict: NumbersVerdictType = Field(
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
# Prompt Construction Helpers
# ---------------------------------------------------------------------------


def build_concall_guidance_prompt(
    company_name: str,
    symbol: str,
    is_lender: bool,
    concall_blocks: str,
    quarterly_actuals_json: str,
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
        f"You are a meticulous buy-side financial research analyst auditing management guidance for {company_name} ({symbol}).\n\n"
        "STRICT NON-NEGOTIABLE GROUNDING RULES:\n"
        "1. Extract ONLY from the concall transcript page blocks and quarterly financial table below. Zero outside knowledge.\n"
        "2. Every `promised_quote` and `delivered_quote` MUST be an exact character-for-character substring (40 to 220 characters) from the cited `doc_id` and `page`.\n"
        "3. Every numerical figure in your summary MUST appear verbatim in the cited page text.\n"
        "4. Name the specific executive `speaker` making each forward commitment (e.g. 'Atul B. Lall, Vice Chairman & MD').\n"
        f"5. {sector_guidance}\n"
        "6. STRUCTURE OF PROMISED-VS-DELIVERED ROWS:\n"
        "   - Row 1 MUST come from the LATEST concall (`IS_LATEST_CALL: True`). Because subsequent results have not been filed yet, set `verdict` to 'Untestable (Latest Call)' and `delivered_summary` to 'Latest call — forward guidance only; untestable for promised-vs-delivered until subsequent quarter results are filed.'\n"
        "   - Rows 2 to 5 MUST come from EARLIER concalls (`IS_LATEST_CALL: False`) where management gave specific forward guidance, and compare against what was subsequently delivered in later concalls or the quarterly actuals table.\n"
        "   - Allowed verdict values for earlier calls: 'Delivered', 'Partially delivered', 'Goalposts moved', 'Missed', or 'not found in filings'.\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(ConcallGuidancePayload.model_json_schema(), indent=2)}\n\n"
        f"SCREENER QUARTERLY ACTUALS (₹ Cr):\n{quarterly_actuals_json}\n\n"
        f"CONCALL TRANSCRIPT EXCERPTS:\n{concall_blocks}"
    )


def build_reasoning_prompt(
    company_name: str,
    symbol: str,
    is_lender: bool,
    trajectory_json: str,
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
        "1. Use ONLY the 5-Year / Quarterly Financial Trajectory and the Verified Primary Filing Citations (`citation_id` 1..N) below.\n"
        "2. Every item in `numbers_vs_narrative`, `bull_case`, and `bear_case` MUST reference a valid `citation_id` (integer) from `VERIFIED_CITATIONS`.\n"
        f"3. {sector_rule}\n"
        "4. Include 2 `unanswered_diligence_questions` where the primary filings do not disclose a key breakdown (explicitly set status to 'not found in filings').\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(ExecutiveReasoningPayload.model_json_schema(), indent=2)}\n\n"
        f"FINANCIAL TRAJECTORY (5Y ANNUAL + RECENT QUARTERS):\n{trajectory_json}\n\n"
        f"VERIFIED_CITATIONS:\n{verified_citations_json}"
    )
