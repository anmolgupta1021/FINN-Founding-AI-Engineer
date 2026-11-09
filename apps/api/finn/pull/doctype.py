"""Document-type verifier for Concall Transcripts and Annual Reports (Phase 4).

Ensures:
1. A PDF linked under Screener's 'Concalls' section is an actual verbatim transcript
   (with speakers + Q&A turns), not a 1-page audio intimation or investor slide deck.
2. The latest concall in the series is explicitly marked untestable for
   Promised-vs-Delivered (`promised_vs_delivered_testable = False`), because subsequent
   quarter results have not been filed yet.
"""

from __future__ import annotations

import re
from typing import Any

LATEST_CALL_UNTESTABLE_NOTE = (
    "Latest call — forward guidance only; untestable for promised-vs-delivered "
    "until subsequent quarter results are filed."
)

_SPEAKER_TURN_RE = re.compile(r"(?m)^\s*([A-Z][A-Za-z .&'()-]{2,45}):\s+\S")
_QA_CUES_RE = re.compile(
    r"(first question|next question|question-and-answer|question from the line|moderator:|"
    r"we will now begin the question|operator:)",
    re.IGNORECASE,
)
_HEADER_CUES_RE = re.compile(
    r"(management:|moderator:|earnings conference call|q[1-4]\s*fy)",
    re.IGNORECASE,
)


def verify_concall_transcript(
    pages: list[dict[str, Any]] | dict[int, str],
    *,
    is_latest_call: bool = False,
) -> dict[str, Any]:
    """Verify whether `pages` (`[{'page': int, 'text': str}, ...]` or `{page_no: text}`)
    is a genuine concall transcript containing speaker turns and Q&A, and annotate
    whether it is testable for promised-vs-delivered.
    """
    page_count = len(pages)
    if isinstance(pages, dict):
        full_text = "\n".join(str(v) for _, v in sorted(pages.items()))
    else:
        full_text = "\n".join(str(p.get("text", "")) for p in pages)
    total_chars = len(full_text)

    speaker_matches = _SPEAKER_TURN_RE.findall(full_text)
    distinct_speakers: list[str] = []
    seen_lower: set[str] = set()
    _ignore_labels = {
        "page",
        "date",
        "time",
        "note",
        "subject",
        "ref",
        "sub",
        "dear sir",
        "isin",
        "encl",
        "regd. office",
        "registered office",
        "e-mail",
        "email",
        "cin",
        "scrip code",
        "website",
        "tel",
        "fax",
        "phone",
        "symbol",
        "kind attn",
    }
    for sp in speaker_matches:
        s_clean = re.sub(r"\s+", " ", sp).strip()
        s_low = s_clean.lower()
        if s_low in _ignore_labels or any(s_low.startswith(k) for k in ("regd", "isin", "cin", "scrip")):
            continue
        if s_low not in seen_lower:
            seen_lower.add(s_low)
            distinct_speakers.append(s_clean)

    speaker_turn_count = len(speaker_matches)
    qa_hits = len(_QA_CUES_RE.findall(full_text))
    header_hits = len(_HEADER_CUES_RE.findall(full_text[:6000]))

    has_speakers = speaker_turn_count >= 15 and len(distinct_speakers) >= 3
    has_qa = qa_hits >= 2 or speaker_turn_count >= 25
    is_transcript = page_count >= 8 and total_chars >= 12000 and has_speakers and has_qa

    if is_transcript:
        doc_subtype = "verbatim_concall_transcript"
    elif page_count <= 4 and total_chars < 8000:
        doc_subtype = "concall_intimation_or_audio_link"
    else:
        doc_subtype = "presentation_or_non_transcript"

    return {
        "is_transcript": is_transcript,
        "doc_subtype": doc_subtype,
        "page_count": page_count,
        "total_chars": total_chars,
        "speaker_turn_count": speaker_turn_count,
        "distinct_speaker_count": len(distinct_speakers),
        "sample_speakers": distinct_speakers[:8],
        "has_qa": has_qa,
        "qa_cue_hits": qa_hits,
        "header_cue_hits": header_hits,
        "is_latest_call": is_latest_call,
        "promised_vs_delivered_testable": bool(is_transcript and not is_latest_call),
        "promised_vs_delivered_status": (
            "untestable_latest_call"
            if is_latest_call
            else ("testable" if is_transcript else "not_a_transcript")
        ),
        "promised_vs_delivered_note": (
            LATEST_CALL_UNTESTABLE_NOTE
            if is_latest_call
            else (
                "Testable against subsequent reported quarterly results."
                if is_transcript
                else "Document is not a verbatim Q&A transcript; excluded from promised-vs-delivered."
            )
        ),
    }
