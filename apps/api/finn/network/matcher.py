"""Deterministic network matching engine for Push & Pull (DECISIONS D-008, D-009).

CRITICAL PRIVACY INVARIANT:
- Private network contacts (`contacts.json` / `contacts` table) NEVER go to any LLM.
- Every link between a synthetic contact and a real person named in an exchange filing
  is inferred purely from employer/alma-mater string matching against the verbatim
  SEBI LODR filing text and MUST carry the label:
  `"inferred from employer/tenure overlap, synthetic network"`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

INFERRED_SYNTHETIC_LABEL = "inferred from employer/tenure overlap, synthetic network"


def _days_since(last_contacted: str | None, ref_date: date) -> int:
    if not last_contacted:
        return 999
    try:
        dt = date.fromisoformat(last_contacted[:10])
        return max(0, (ref_date - dt).days)
    except ValueError:
        return 999


def _recency_phrase(days: int) -> str:
    if days < 14:
        return f"spoke {days}d ago"
    if days < 60:
        return f"spoke { max(1, days // 7) } wks ago"
    return f"spoke { max(1, days // 30) } mos ago"


def match_contacts_for_announcement(
    item: dict[str, Any],
    contacts: list[dict[str, Any]],
    company_links: list[dict[str, Any]],
    *,
    ref_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return top deterministic 'Who to call' matches for a corporate announcement."""
    anchor = ref_date or date(2026, 11, 6)
    sym = (item.get("symbol") or "").upper()
    det = item.get("details") or {}
    verbatim_bio = re.sub(
        r"\s+",
        " ",
        f"{det.get('brief_profile_verbatim', '')} {det.get('page_verbatim_excerpt', '')} {item.get('subject', '')}",
    ).lower()

    peer_map: dict[str, str] = {}
    for lk in company_links:
        if lk.get("src") == sym and lk.get("dst"):
            peer_map[lk["dst"]] = f"{lk.get('kind', 'peer')} ({lk.get('note', '')})"
        elif lk.get("dst") == sym and lk.get("src"):
            peer_map[lk["src"]] = f"{lk.get('kind', 'peer')} ({lk.get('note', '')})"

    scored: list[dict[str, Any]] = []
    for ct in contacts:
        affs = ct.get("affiliations") or []
        bio_overlaps: list[dict[str, Any]] = []
        direct_affs: list[dict[str, Any]] = []
        peer_affs: list[tuple[dict[str, Any], str]] = []

        for af in affs:
            org = (af.get("org") or "").strip()
            af_sym = (af.get("symbol") or "").upper()
            # Check if the contact's prior organization is explicitly named in the verbatim filing PDF text
            if org and len(org) >= 5 and org.lower() in verbatim_bio and af_sym != sym:
                bio_overlaps.append(af)
            if af_sym == sym:
                direct_affs.append(af)
            elif af_sym in peer_map:
                peer_affs.append((af, peer_map[af_sym]))

        if not bio_overlaps and not direct_affs and not peer_affs:
            continue

        days = _days_since(ct.get("last_contacted"), anchor)
        recency_str = _recency_phrase(days)
        strength = int(ct.get("strength", 3))

        score = strength * 12
        reasons: list[str] = []
        overlap_org = None
        overlap_tenure = None

        if bio_overlaps:
            score += 45
            af0 = bio_overlaps[0]
            overlap_org = af0["org"]
            overlap_tenure = f"{af0.get('start', '?')}–{af0.get('end', 'present')}"
            reasons.append(
                f"Filing PDF verbatim bio cites '{overlap_org}', where {ct['name']} served as {af0.get('role')} ({overlap_tenure})."
            )
        if direct_affs:
            score += 30
            af_d = direct_affs[0]
            if not overlap_org:
                overlap_org = af_d["org"]
                overlap_tenure = f"{af_d.get('start', '?')}–{af_d.get('end', 'present')}"
            reasons.append(
                f"Ex-{af_d['org']}: {af_d.get('role')} ({af_d.get('start', '?')}–{af_d.get('end', 'present')})."
            )
        if peer_affs:
            score += 15
            af_p, rel_desc = peer_affs[0]
            if not overlap_org:
                overlap_org = af_p["org"]
                overlap_tenure = f"{af_p.get('start', '?')}–{af_p.get('end', 'present')}"
            reasons.append(
                f"Ecosystem peer ({af_p['org']} · {rel_desc}): {af_p.get('role')} ({af_p.get('start', '?')}–{af_p.get('end', 'present')})."
            )

        reasons.append(
            f"Relationship strength {strength}/5 ({recency_str}) · Expertise: {', '.join(ct.get('expertise_tags', [])[:3])}."
        )
        if ct.get("notes"):
            reasons.append(f"Your note: \"{ct['notes']}\"")

        first_name = ct["name"].split()[0]
        if item.get("category") == "management_change" and bio_overlaps:
            path_str = (
                f"You → {ct['name']} (strength {strength}/5 · {recency_str}) "
                f"→ overlapped at {overlap_org} ({overlap_tenure})"
            )
            opener = (
                f"Hi {first_name} — saw {sym}'s exchange filing today. The brief profile mentions "
                f"{overlap_org} during your tenure ({overlap_tenure}). Would love 10 mins for your read on background & execution style."
            )
        else:
            path_str = (
                f"You → {ct['name']} (strength {strength}/5 · {recency_str}) "
                f"→ {overlap_org} ({overlap_tenure})"
            )
            opener = (
                f"Hi {first_name} — {sym} just filed '{item.get('summary_1l', item.get('subject', ''))[:70]}'. "
                f"Given your time at {overlap_org}, would love a quick sanity check this week."
            )

        scored.append(
            {
                "contact_id": ct["id"],
                "name": ct["name"],
                "headline": ct["headline"],
                "city": ct.get("city"),
                "strength": strength,
                "last_contacted": ct.get("last_contacted"),
                "recency": recency_str,
                "days_since_contact": days,
                "expertise_tags": ct.get("expertise_tags", []),
                "score": score,
                "path": path_str,
                "overlap_org": overlap_org,
                "overlap_tenure": overlap_tenure,
                "inferred_label": INFERRED_SYNTHETIC_LABEL,
                "why_reasons": reasons[:3],
                "draft_opener": opener,
            }
        )

    scored.sort(key=lambda x: (-x["score"], x["days_since_contact"]))
    return scored[:3]


def build_reconnect_nudges(
    material_items: list[dict[str, Any]],
    all_recent_items: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
    company_by_symbol: dict[str, dict[str, Any]],
    *,
    ref_date: date | None = None,
) -> list[dict[str, Any]]:
    """Identify stale relationships (>= 120 days since contact) warmed up by a fresh filing."""
    anchor = ref_date or date(2026, 11, 6)
    pool = material_items if len(material_items) >= 3 else all_recent_items
    by_sym: dict[str, dict[str, Any]] = {}
    for it in pool:
        s = (it.get("symbol") or "").upper()
        if s and s not in by_sym and int(it.get("priority", 0)) >= 55:
            by_sym[s] = it

    nudges: list[dict[str, Any]] = []
    for ct in contacts:
        days = _days_since(ct.get("last_contacted"), anchor)
        if days < 120:
            continue
        months = max(4, round(days / 30))
        for af in ct.get("affiliations") or []:
            af_sym = (af.get("symbol") or "").upper()
            if af_sym in by_sym:
                filing = by_sym[af_sym]
                comp_name = company_by_symbol.get(af_sym, {}).get("name", af_sym)
                first_name = ct["name"].split()[0]
                nudges.append(
                    {
                        "contact_id": ct["id"],
                        "name": ct["name"],
                        "headline": ct["headline"],
                        "strength": ct.get("strength", 3),
                        "last_contacted": ct.get("last_contacted"),
                        "months_stale": months,
                        "symbol": af_sym,
                        "company_name": comp_name,
                        "role_at_company": f"{af.get('role')} ({af.get('start')}–{af.get('end')})",
                        "filing_id": filing["id"],
                        "filing_summary": filing.get("summary_1l") or filing.get("subject"),
                        "filing_ts": filing.get("ts"),
                        "filing_pdf_url": filing.get("pdf_url"),
                        "nudge_line": (
                            f"You haven't spoken to {ct['name']} in {months} months. "
                            f"Their ex-employer {comp_name} ({af_sym}) filed: {filing.get('summary_1l') or filing.get('subject')}"
                        ),
                        "draft_opener": (
                            f"Hi {first_name} — realized it's been {months} months since we caught up! "
                            f"Saw {comp_name}'s recent exchange filing ({filing.get('summary_1l', '')[:65]}) and thought of you. Coffee or a quick call next week?"
                        ),
                        "inferred_label": INFERRED_SYNTHETIC_LABEL,
                    }
                )
                break

    nudges.sort(key=lambda x: (-x["months_stale"], -x["strength"]))
    return nudges[:3]


def parse_anchor_date(anchor_ts: str | None) -> date:
    if not anchor_ts:
        return date(2026, 11, 6)
    try:
        return datetime.fromisoformat(anchor_ts).date()
    except ValueError:
        return date(2026, 11, 6)
