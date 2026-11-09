"""Corporate announcement classifier & priority scorer.

Two-stage pipeline:
1. `classify_by_rule(item)` — deterministic regex/keyword rules in strict specificity order.
   Handles ~75-85% of exchange announcements with zero LLM calls.
2. `classify_batch(items, router)` — batches remaining low-confidence announcements (<= 20 per call)
   to `FINN_MODEL_BULK` (Flash-Lite) with structured JSON output, cached by sha256 content hash.

Categories match `docs/2_ENAM_Build_Challenge_Reference.pdf`:
  results, M&A, fund_raise, management_change, litigation, insider_trading,
  earnings_call, investor_meetings, credit_rating, dividend, bonus_split,
  capex, press_release, postal_ballot, agm_egm, pledging, unclassified
"""

from __future__ import annotations

import re
from typing import Any

from finn.llm.router import LLMRouter

CATEGORIES: tuple[str, ...] = (
    "results",
    "M&A",
    "fund_raise",
    "management_change",
    "litigation",
    "insider_trading",
    "earnings_call",
    "investor_meetings",
    "credit_rating",
    "dividend",
    "bonus_split",
    "capex",
    "press_release",
    "postal_ballot",
    "agm_egm",
    "pledging",
    "unclassified",
)

BASE_PRIORITY: dict[str, int] = {
    "results": 88,
    "M&A": 86,
    "management_change": 84,
    "capex": 80,
    "litigation": 78,
    "pledging": 78,
    "fund_raise": 75,
    "credit_rating": 68,
    "earnings_call": 65,
    "insider_trading": 62,
    "press_release": 58,
    "dividend": 52,
    "bonus_split": 50,
    "investor_meetings": 32,
    "agm_egm": 25,
    "postal_ballot": 22,
    "unclassified": 8,
}

# Ordered rules: (rule_name, category, compiled_regex). Evaluated top-to-bottom on `raw_category + " | " + subject`.
_ORDERED_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    # 1. Hard routine / compliance noise that often contains false-positive words like "Result" or "Appointment"
    (
        "noise_loss_of_shares_or_reg74",
        "unclassified",
        re.compile(
            r"(loss of share certificate|issue of duplicate share|regulation\s*74\s*\(\s*5\s*\)|"
            r"reconciliation of share capital audit|closure of trading window|"
            r"compliance certificate under reg|secretarial compliance report|"
            r"esop|employee stock option|allotment of \d+[\d,]* equity shares under.*esop|"
            r"iepf|unclaimed dividend transfer|brsr|business responsibility and sustainability|"
            r"appointment of secretarial auditor|appointment of cost auditor|"
            r"newspaper publication.*(?:transfer of equity|unclaimed|loss of share|notice of board meeting))",
            re.IGNORECASE,
        ),
    ),
    # 2. Pledging / encumbrance
    (
        "pledging_reg31",
        "pledging",
        re.compile(
            r"(pledge|encumbrance|release of pledged|creation of pledge|invocation of pledge|"
            r"regulation\s*31\s*\(\s*1\s*\)|disclosure.*encumbrance)",
            re.IGNORECASE,
        ),
    ),
    # 3. Insider trading (SAST / PIT / Reg 7(2) / Reg 29)
    (
        "insider_sast_pit",
        "insider_trading",
        re.compile(
            r"(prohibition of insider trading|sebi\s*\(\s*pit\s*\)|regulation\s*7\s*\(\s*2\s*\)|"
            r"substantial acquisition of shares|sast|regulation\s*29\s*\(\s*[12]\s*\)|"
            r"promoter.*(?:acquired|disposed|bought|sold|open market purchase))",
            re.IGNORECASE,
        ),
    ),
    # 4. Postal ballot (must run before AGM/EGM and management_change since postal ballots often approve directors)
    (
        "postal_ballot",
        "postal_ballot",
        re.compile(r"(postal ballot|scrutinizer.*postal ballot|notice of postal ballot)", re.IGNORECASE),
    ),
    # 5. AGM / EGM
    (
        "agm_egm",
        "agm_egm",
        re.compile(
            r"(\bagm\b|\begm\b|annual general meeting|extraordinary general meeting|"
            r"proceedings of .*general meeting|voting results of .*general meeting)",
            re.IGNORECASE,
        ),
    ),
    # 6. Earnings call (concall notice, transcript, audio/video recording)
    (
        "earnings_call",
        "earnings_call",
        re.compile(
            r"(earnings?\s*call|conference\s*call|concall|transcript of .*call|"
            r"audio\s*/?\s*video recording of .*call|post[-\s]*results?\s*conference call)",
            re.IGNORECASE,
        ),
    ),
    # 7. Investor / analyst meetings (1-on-1, group meet, conference attendance)
    (
        "investor_meetings",
        "investor_meetings",
        re.compile(
            r"(analyst\s*(?:/|\s*and\s*)?\s*institutional investor meet|"
            r"schedule of .*investor meet|intimation of .*investor meet|"
            r"one[-\s]*on[-\s]*one meet|investor conference)",
            re.IGNORECASE,
        ),
    ),
    # 8. Credit rating
    (
        "credit_rating",
        "credit_rating",
        re.compile(
            r"(credit rating|\bcrisil\b|\bicra\b|\bcare ratings?\b|\bindia ratings\b|"
            r"rating\s+(?:reaffirmed|upgraded|downgraded|assigned|withdrawn))",
            re.IGNORECASE,
        ),
    ),
    # 9. Bonus issue / stock split
    (
        "bonus_split",
        "bonus_split",
        re.compile(
            r"(bonus\s+issue|issue of bonus shares|sub[-\s]*division of equity shares|stock\s+split)",
            re.IGNORECASE,
        ),
    ),
    # 10. Fund raise (QIP, rights issue, preferential issue, buyback, commercial paper, NCDs)
    (
        "fund_raise",
        "fund_raise",
        re.compile(
            r"(qualified institutional placement|\bqip\b|rights\s+issue|preferential\s+(?:issue|allotment)|"
            r"buy[-\s]*back of equity shares|\bbuyback\b|issuance of commercial paper|"
            r"non[-\s]*convertible debentures|\bncd\b.*allotment)",
            re.IGNORECASE,
        ),
    ),
    # 11. M&A (acquisition, merger, demerger, scheme of arrangement, JV, stake sale/purchase, slump sale)
    (
        "mna",
        "M&A",
        re.compile(
            r"(acquisition of|acquire[ds]?\s+\d|merger|demerger|amalgamation|scheme of arrangement|"
            r"joint venture|share purchase agreement|slump sale|divestment|sale of stake|"
            r"wholly[-\s]*owned subsidiary.*acqui|incorporation of .*subsidiary.*joint venture)",
            re.IGNORECASE,
        ),
    ),
    # 12. Capex (new plant, capacity expansion, commissioning, greenfield/brownfield)
    (
        "capex",
        "capex",
        re.compile(
            r"(capacity expansion|commercial production|commissioning of .*plant|"
            r"greenfield|brownfield|setting up of new (?:plant|manufacturing|facility)|"
            r"capital expenditure plan|\bcapex\b\s+of)",
            re.IGNORECASE,
        ),
    ),
    # 13. Litigation / regulatory orders / tax demands / penalties / NCLT / show-cause
    (
        "litigation",
        "litigation",
        re.compile(
            r"(litigation|arbitration|show[-\s]*cause notice|penalty imposed|order passed by|"
            r"gst demand|income tax demand|sebi order|nclt|insolvency|compounding of offence|"
            r"regulatory (?:order|action|fine|warning))",
            re.IGNORECASE,
        ),
    ),
    # 14. Management change (CEO, CFO, MD, Whole-time / Independent Director, KMP, Company Secretary)
    (
        "management_change",
        "management_change",
        re.compile(
            r"(change in directorate|change in key managerial|change in management|"
            r"appointment of .*(?:chief|cfo|ceo|managing director|"
            r"whole[-\s]*time director|independent director|additional director|company secretary|kmp|head)|"
            r"resignation of .*(?:chief|cfo|ceo|managing director|director|company secretary|kmp|smp)|"
            r"cessation of .*director|re[-\s]*appointment of (?:managing director|whole[-\s]*time director|ceo|cfo)|"
            r"change in managing director)",
            re.IGNORECASE,
        ),
    ),
    # 15. Financial results (quarterly/annual outcome, unaudited/audited results, results deck, newspaper ad of results)
    (
        "results",
        "results",
        re.compile(
            r"(financial results|unaudited .*results|audited .*results|"
            r"outcome of board meeting.*results|board meeting.*consider.*financial results|"
            r"investor presentation.*(?:q[1-4]|fy\d{2}|results)|shareholder[s']?\s*letter.*q[1-4]|"
            r"newspaper publication.*financial results)",
            re.IGNORECASE,
        ),
    ),
    # 16. Standalone dividend declaration / record date for dividend
    (
        "dividend",
        "dividend",
        re.compile(
            r"(declaration of .*dividend|interim dividend|final dividend|"
            r"record date for .*dividend)",
            re.IGNORECASE,
        ),
    ),
    # 17. Press release / order win / partnership / product launch / rumour clarification
    (
        "press_release",
        "press_release",
        re.compile(
            r"(press release|media release|bagged an order|order win|receipt of order|"
            r"launch of new product|strategic partnership|clarification on news item|"
            r"mou signed|memorandum of understanding)",
            re.IGNORECASE,
        ),
    ),
]


def classify_by_rule(item: dict[str, Any]) -> tuple[str | None, float, str | None]:
    """Return `(category, confidence, rule_name)` if a high-confidence rule matches, else `(None, 0.0, None)`."""
    raw_cat = (item.get("raw_category") or "").strip()
    subject = (item.get("subject") or "").strip()
    combined = f"{raw_cat} | {subject}"

    for rule_name, category, pattern in _ORDERED_RULES:
        if pattern.search(combined):
            return category, 0.92, rule_name
    return None, 0.0, None


def score_priority(
    item: dict[str, Any],
    *,
    category: str,
    has_network_overlap: bool = False,
) -> int:
    """Compute a 0..100 priority score combining category weight, materiality cues, and network overlap."""
    base = BASE_PRIORITY.get(category, 8)
    text = f"{item.get('raw_category', '')} {item.get('subject', '')}".lower()

    # Demote routine derivatives inside material categories
    if "newspaper" in text and category == "results":
        base -= 55  # newspaper ad confirming results were published is low-signal
    elif (
        ("prior intimation" in text or "board meeting intimation" in text or "to consider and approve" in text)
        and "outcome" not in text
        and "approved" not in text
    ):
        base -= 25  # prior notice of a board meeting is lower priority than the actual outcome

    if category == "management_change":
        if any(k in text for k in ("cfo", "chief financial", "ceo", "chief executive", "managing director")):
            base += 10
        elif "company secretary" in text:
            base -= 14

    if re.search(r"(?:rs\.?|inr|₹)\s*\d+[\d,.\s]*(?:cr|crore|billion)", text):
        base += 6

    if any(k in text for k in ("downgrade", "resignation", "search and seizure", "suspension")):
        base += 7

    if has_network_overlap and category not in ("unclassified", "postal_ballot", "agm_egm"):
        base += 6

    return max(2, min(99, base))


def summarize_one_line(item: dict[str, Any], *, category: str) -> str:
    """Deterministic clean 1-line summary when LLM is not needed."""
    subj = re.sub(r"\s+", " ", (item.get("subject") or "").strip())
    sym = item.get("symbol") or ""
    # Strip boilerplate Reg 30 prefixes
    cleaned = re.sub(
        r"^(?:intimation under regulation 30[^-:]*[-:\s]*|disclosure under regulation 30[^-:]*[-:\s]*|"
        r"regulation 30[^-:]*[-:\s]*|outcome of board meeting[^-:]*[-:\s]*)",
        "",
        subj,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        cleaned = subj
    if len(cleaned) > 140:
        cleaned = cleaned[:137].rstrip() + "…"
    return f"{sym}: {cleaned}" if sym and not cleaned.upper().startswith(sym.upper()) else cleaned


LLM_CLS_SYSTEM = (
    "You classify Indian stock exchange (NSE/BSE) corporate announcements into exactly one of the "
    "17 allowed categories and write a crisp one-line summary (max 110 chars, no emojis). "
    "Allowed categories: " + ", ".join(CATEGORIES) + ". "
    "Return JSON: {\"items\": [{\"id\": str, \"category\": str, \"summary_1l\": str}]}."
)


def classify_announcements(
    items: list[dict[str, Any]],
    *,
    router: LLMRouter | None = None,
    network_symbols: set[str] | None = None,
    allow_llm: bool = True,
) -> dict[str, Any]:
    """Classify and prioritise a list of announcements.
    Rules run first; unresolved items are sent to `router` (tier='bulk') in batches of 20.
    If `allow_llm=False` or no API key is configured, unresolved items fall back to `unclassified`.
    """
    net_syms = network_symbols or set()
    results: list[dict[str, Any]] = []
    unresolved_indices: list[int] = []

    for idx, item in enumerate(items):
        cat, conf, rule_name = classify_by_rule(item)
        if cat is not None:
            sym = item.get("symbol", "")
            prio = score_priority(item, category=cat, has_network_overlap=sym in net_syms)
            results.append(
                {
                    **item,
                    "category": cat,
                    "cls_method": "rule",
                    "cls_rule": rule_name,
                    "cls_confidence": conf,
                    "priority": prio,
                    "summary_1l": summarize_one_line(item, category=cat),
                }
            )
        else:
            results.append({**item})
            unresolved_indices.append(idx)

    llm_classified = 0
    if unresolved_indices and allow_llm and router is not None:
        for start in range(0, len(unresolved_indices), 20):
            batch_idx = unresolved_indices[start : start + 20]
            payload = [
                {
                    "id": str(items[i].get("id", i)),
                    "symbol": items[i].get("symbol", ""),
                    "raw_category": items[i].get("raw_category", ""),
                    "subject": items[i].get("subject", ""),
                }
                for i in batch_idx
            ]
            try:
                resp = router.generate(
                    task="classify_announcements_batch",
                    tier="bulk",
                    source_kind="public_filing",
                    prompt_version="cls-batch-v1",
                    system=LLM_CLS_SYSTEM,
                    contents=payload,
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "items": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "id": {"type": "STRING"},
                                        "category": {"type": "STRING"},
                                        "summary_1l": {"type": "STRING"},
                                    },
                                    "required": ["id", "category", "summary_1l"],
                                },
                            }
                        },
                        "required": ["items"],
                    },
                )
                parsed_items = (resp.get("parsed") or {}).get("items") or []
                by_id = {str(x.get("id")): x for x in parsed_items if isinstance(x, dict)}
            except Exception as exc:  # noqa: BLE001
                print(f"[classify_announcements] Stage-2 LLM batch error: {exc}")
                by_id = {}

            for i in batch_idx:
                item = items[i]
                hit = by_id.get(str(item.get("id", i)))
                cat = hit.get("category") if hit else None
                if cat not in CATEGORIES:
                    cat = "unclassified"
                    cls_method = "fallback"
                else:
                    cls_method = "llm"
                    llm_classified += 1
                sym = item.get("symbol", "")
                prio = score_priority(item, category=cat, has_network_overlap=sym in net_syms)
                summary = (hit.get("summary_1l") if hit else None) or summarize_one_line(item, category=cat)
                results[i] = {
                    **item,
                    "category": cat,
                    "cls_method": cls_method,
                    "cls_rule": None,
                    "cls_confidence": 0.80 if cls_method == "llm" else 0.50,
                    "priority": prio,
                    "summary_1l": summary,
                }
    else:
        for i in unresolved_indices:
            item = items[i]
            cat = "unclassified"
            sym = item.get("symbol", "")
            prio = score_priority(item, category=cat, has_network_overlap=sym in net_syms)
            results[i] = {
                **item,
                "category": cat,
                "cls_method": "fallback",
                "cls_rule": None,
                "cls_confidence": 0.50,
                "priority": prio,
                "summary_1l": summarize_one_line(item, category=cat),
            }

    rule_count = len(items) - len(unresolved_indices)
    total = len(items) or 1
    return {
        "total": len(items),
        "rule_count": rule_count,
        "llm_count": llm_classified,
        "fallback_count": len(unresolved_indices) - llm_classified,
        "rule_pct": round((rule_count / total) * 100.0, 1),
        "items": sorted(results, key=lambda x: (-int(x.get("priority", 0)), str(x.get("ts", "")))),
    }
