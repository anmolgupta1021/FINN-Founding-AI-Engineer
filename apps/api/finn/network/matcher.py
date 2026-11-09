"""Deterministic network matching & graph traversal engine for Push, Pull, and Ask (Phase 3).

CRITICAL PRIVACY INVARIANT (DECISIONS D-008, D-009):
- Private network contacts (`contacts.json` / `contact_links.json`) NEVER go to any LLM.
- Every link between a synthetic contact and a real person or company in an exchange filing
  is inferred purely from employer/tenure/alma-mater string matching and graph traversal,
  and MUST carry the label:
  `"inferred from employer/tenure overlap, synthetic network"`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from finn.store import get_company_links, get_contact_links, get_contacts, get_portfolio

INFERRED_SYNTHETIC_LABEL = "inferred from employer/tenure overlap, synthetic network"

_STOP_WORDS = frozenset(
    {
        "who",
        "knows",
        "know",
        "about",
        "can",
        "help",
        "with",
        "in",
        "at",
        "the",
        "for",
        "and",
        "or",
        "to",
        "me",
        "on",
        "of",
        "an",
        "a",
        "any",
        "anyone",
        "somebody",
        "someone",
        "introduce",
        "connect",
        "from",
        "worked",
        "working",
        "ex",
    }
)


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
        return f"spoke {max(1, days // 7)} wks ago"
    return f"spoke {max(1, days // 30)} mos ago"


def _build_bridge_lookup(
    contacts_by_id: dict[str, dict[str, Any]],
    contact_links: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """For each contact, find the strongest 1st-degree bridge contact (`strength >= 4`) connected via `contact_links`."""
    best_bridge: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for edge in contact_links:
        src_id = edge.get("src", "")
        dst_id = edge.get("dst", "")
        for a_id, b_id in ((src_id, dst_id), (dst_id, src_id)):
            bridge = contacts_by_id.get(a_id)
            target = contacts_by_id.get(b_id)
            if not bridge or not target:
                continue
            if int(bridge.get("strength", 0)) < 4:
                continue
            prev = best_bridge.get(b_id)
            if prev is None or int(bridge.get("strength", 0)) > int(prev[0].get("strength", 0)):
                best_bridge[b_id] = (bridge, edge)
    return best_bridge


def match_contacts_for_announcement(
    item: dict[str, Any],
    contacts: list[dict[str, Any]],
    company_links: list[dict[str, Any]],
    *,
    contact_links: list[dict[str, Any]] | None = None,
    ref_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return top deterministic 1st-degree and 2nd-degree 'Who to call' matches for a corporate announcement."""
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

    contacts_by_id = {c["id"]: c for c in contacts}
    bridge_map = _build_bridge_lookup(contacts_by_id, contact_links or [])

    scored: list[dict[str, Any]] = []
    for ct in contacts:
        affs = ct.get("affiliations") or []
        bio_overlaps: list[dict[str, Any]] = []
        direct_affs: list[dict[str, Any]] = []
        peer_affs: list[tuple[dict[str, Any], str]] = []

        for af in affs:
            org = (af.get("org") or "").strip()
            af_sym = (af.get("symbol") or "").upper()
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
        bridge_pair = bridge_map.get(ct["id"])
        degree = 2 if (strength <= 2 and bridge_pair is not None) else 1

        score = strength * 10 + (12 if degree == 2 else 0)
        reasons: list[str] = []
        overlap_org = None
        overlap_tenure = None

        if bio_overlaps:
            score += 48
            af0 = bio_overlaps[0]
            overlap_org = af0["org"]
            overlap_tenure = f"{af0.get('start', '?')}–{af0.get('end', 'present')}"
            reasons.append(
                f"Filing PDF verbatim bio cites '{overlap_org}', where {ct['name']} served as {af0.get('role')} ({overlap_tenure})."
            )
        if direct_affs:
            score += 32
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

        if degree == 2 and bridge_pair is not None:
            bridge_ct, edge = bridge_pair
            b_days = _days_since(bridge_ct.get("last_contacted"), anchor)
            b_recency = _recency_phrase(b_days)
            path_str = (
                f"You → {bridge_ct['name']} (strength {bridge_ct['strength']}/5 · {b_recency}) "
                f"→ {ct['name']} (2nd-degree · {overlap_org}, {overlap_tenure})"
            )
            reasons.append(
                f"Warm 2nd-degree intro via {bridge_ct['name']} ({edge.get('kind', 'ex_colleague')} at {edge.get('overlap_org')}, {edge.get('overlap_years')})."
            )
            b_first = bridge_ct["name"].split()[0]
            opener = (
                f"Hi {b_first} — saw {sym}'s exchange filing today. Could you introduce me to {ct['name']} "
                f"from your {edge.get('overlap_org')} days ({edge.get('overlap_years')}) for a 10-min perspective?"
            )
        else:
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

        reasons.append(
            f"Relationship strength {strength}/5 ({recency_str}) · Expertise: {', '.join(ct.get('expertise_tags', [])[:3])}."
        )
        if ct.get("notes") and len(reasons) < 3:
            reasons.append(f"Your note: \"{ct['notes']}\"")

        scored.append(
            {
                "contact_id": ct["id"],
                "name": ct["name"],
                "headline": ct["headline"],
                "city": ct.get("city"),
                "strength": strength,
                "degree": degree,
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
    top = scored[:3]
    if top and not any(x["degree"] == 2 for x in top):
        deg2_candidates = [x for x in scored[3:] if x["degree"] == 2]
        if deg2_candidates:
            top = [*top[:2], deg2_candidates[0]]
    return top


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
        if days < 120 or int(ct.get("strength", 3)) < 3:
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
    return nudges[:4]


def query_network(
    data_dir: Path,
    query: str,
    *,
    ref_date: date | None = None,
) -> dict[str, Any]:
    """Direct queryable Network engine (`[S8]` Ask).
    100% deterministic graph + keyword + company-ecosystem search. Zero LLM calls.
    """
    anchor = ref_date or date(2026, 11, 6)
    pf = get_portfolio(data_dir)
    contacts_payload = get_contacts(data_dir)
    contacts = contacts_payload.get("contacts", [])
    company_links = get_company_links(data_dir)
    contact_links = get_contact_links(data_dir)

    company_by_sym: dict[str, dict[str, Any]] = {}
    for c in pf.get("companies", []) + pf.get("research", []):
        company_by_sym[c["symbol"].upper()] = c

    q_clean = re.sub(r"[^\w\s+&+-]", " ", (query or "").strip())
    raw_tokens = [t.lower() for t in q_clean.split() if t.lower() not in _STOP_WORDS and len(t) >= 2]
    q_phrase = " ".join(raw_tokens)

    # Identify if query targets specific ticker symbols
    matched_syms: set[str] = set()
    for sym, comp in company_by_sym.items():
        if sym.lower() in raw_tokens or comp["name"].lower() in q_phrase:
            matched_syms.add(sym)
        for tok in raw_tokens:
            if len(tok) >= 4 and (tok in sym.lower() or tok in comp["name"].lower()):
                matched_syms.add(sym)

    peer_syms: dict[str, str] = {}
    for lk in company_links:
        if lk.get("src") in matched_syms and lk.get("dst"):
            peer_syms[lk["dst"]] = f"{lk.get('kind', 'peer')} of {lk['src']} ({lk.get('note', '')})"
        elif lk.get("dst") in matched_syms and lk.get("src"):
            peer_syms[lk["src"]] = f"{lk.get('kind', 'peer')} of {lk['dst']} ({lk.get('note', '')})"

    contacts_by_id = {c["id"]: c for c in contacts}
    bridge_map = _build_bridge_lookup(contacts_by_id, contact_links)

    results: list[dict[str, Any]] = []
    for ct in contacts:
        score = 0
        reasons: list[str] = []
        affs = ct.get("affiliations") or []
        tags = [str(t) for t in ct.get("expertise_tags", [])]
        tags_lower = " | ".join(tags).lower()
        headline_lower = (ct.get("headline") or "").lower()
        notes_lower = (ct.get("notes") or "").lower()

        # 1. Direct symbol / company match
        for af in affs:
            af_sym = (af.get("symbol") or "").upper()
            org = af.get("org") or ""
            tenure = f"{af.get('start', '?')}–{af.get('end', 'present')}"
            if af_sym and af_sym in matched_syms:
                score += 45
                reasons.append(f"Direct experience at {org} ({af_sym}): {af.get('role')} ({tenure}).")
            elif af_sym and af_sym in peer_syms:
                score += 25
                reasons.append(f"Ecosystem peer at {org} ({peer_syms[af_sym]}): {af.get('role')} ({tenure}).")

        # 2. Phrase & token matching across expertise_tags, affiliations.org, headline, notes, city
        if q_phrase and len(q_phrase) >= 4:
            if q_phrase in tags_lower:
                score += 40
                reasons.append(f"Exact expertise tag match: '{q_phrase}'.")
            if any(q_phrase in (af.get("org") or "").lower() for af in affs):
                af_hit = next(af for af in affs if q_phrase in (af.get("org") or "").lower())
                score += 42
                reasons.append(
                    f"Affiliation match: {af_hit.get('org')} — {af_hit.get('role')} ({af_hit.get('start')}–{af_hit.get('end')})."
                )

        token_hits: list[str] = []
        for tok in raw_tokens:
            if tok in tags_lower:
                score += 18
                token_hits.append(f"expertise '{tok}'")
            elif any(tok in (af.get("org") or "").lower() for af in affs):
                af_hit = next(af for af in affs if tok in (af.get("org") or "").lower())
                score += 20
                reasons.append(
                    f"Worked/studied at {af_hit.get('org')} ({af_hit.get('role')}, {af_hit.get('start')}–{af_hit.get('end')})."
                )
            elif tok in headline_lower or tok in notes_lower or tok in (ct.get("city") or "").lower():
                score += 10
                token_hits.append(tok)

        if token_hits and not reasons:
            reasons.append(f"Matched on {', '.join(token_hits[:3])} · Tags: {', '.join(tags[:4])}.")

        if score == 0 and raw_tokens:
            continue

        strength = int(ct.get("strength", 3))
        days = _days_since(ct.get("last_contacted"), anchor)
        recency_str = _recency_phrase(days)
        bridge_pair = bridge_map.get(ct["id"])
        degree = 2 if (strength <= 2 and bridge_pair is not None) else 1

        total_score = score + strength * 6
        af_primary = affs[0] if affs else {"org": "Network", "start": 2018, "end": 2024}
        overlap_org = af_primary.get("org", "Network")
        overlap_tenure = f"{af_primary.get('start', '?')}–{af_primary.get('end', 'present')}"

        if degree == 2 and bridge_pair is not None:
            bridge_ct, edge = bridge_pair
            b_days = _days_since(bridge_ct.get("last_contacted"), anchor)
            path_str = (
                f"You → {bridge_ct['name']} ({bridge_ct['strength']}/5 · {_recency_phrase(b_days)}) "
                f"→ {ct['name']} (2nd-degree via {edge.get('overlap_org')}, {edge.get('overlap_years')})"
            )
            reasons.append(
                f"2nd-degree warm intro via {bridge_ct['name']} ({edge.get('note') or edge.get('overlap_org')})."
            )
            opener = (
                f"Hi {bridge_ct['name'].split()[0]} — exploring {query or overlap_org} right now. "
                f"Would you mind connecting me with {ct['name']} from your {edge.get('overlap_org')} days?"
            )
        else:
            path_str = f"You → {ct['name']} (strength {strength}/5 · {recency_str}) → {overlap_org} ({overlap_tenure})"
            opener = (
                f"Hi {ct['name'].split()[0]} — looking closely at {query or overlap_org} this week. "
                f"Given your background ({ct['headline']}), would love 10 mins for your perspective."
            )

        reasons.append(f"Strength {strength}/5 ({recency_str}) · City: {ct.get('city', 'India')}.")
        if ct.get("notes") and len(reasons) < 3:
            reasons.append(f"Note: \"{ct['notes']}\"")

        results.append(
            {
                "contact_id": ct["id"],
                "name": ct["name"],
                "headline": ct["headline"],
                "city": ct.get("city"),
                "strength": strength,
                "degree": degree,
                "last_contacted": ct.get("last_contacted"),
                "recency": recency_str,
                "expertise_tags": tags,
                "affiliations": affs,
                "score": total_score,
                "path": path_str,
                "inferred_label": INFERRED_SYNTHETIC_LABEL,
                "why_reasons": reasons[:3],
                "draft_opener": opener,
            }
        )

    results.sort(key=lambda x: (-x["score"], -x["strength"], x["name"]))
    return {
        "query": query,
        "total_contacts": len(contacts),
        "total_links": len(contact_links),
        "total_contacts_in_network": len(contacts),
        "total_contact_links": len(contact_links),
        "matched_symbols": sorted(matched_syms),
        "peer_symbols": peer_syms,
        "count": len(results),
        "inferred_label": INFERRED_SYNTHETIC_LABEL,
        "privacy_guarantee": "100% deterministic local graph traversal — zero private network data ever sent to an LLM",
        "results": results[:12],
    }


def parse_anchor_date(anchor_ts: str | None) -> date:
    if not anchor_ts:
        return date(2026, 11, 6)
    try:
        return datetime.fromisoformat(anchor_ts).date()
    except ValueError:
        return date(2026, 11, 6)
