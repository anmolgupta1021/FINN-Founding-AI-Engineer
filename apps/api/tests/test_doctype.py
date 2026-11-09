import json
from pathlib import Path

from finn.pull.doctype import LATEST_CALL_UNTESTABLE_NOTE, verify_concall_transcript

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_dixon_spike_concall_transcripts_and_latest_call_untestable() -> None:
    spike = json.loads((DATA_DIR / "snapshots" / "pull_spike_dixon.json").read_text())
    concalls = [d for d in spike["probed_documents"] if d["kind"] == "concall_transcript"]
    assert len(concalls) == 4

    # Latest call (index 0: Nov 2026 / Q2 FY27) is a transcript (speakers + Q&A) but untestable for promised-vs-delivered
    latest = concalls[0]["doctype_check"]
    assert latest["is_transcript"] is True
    assert latest["has_qa"] is True
    assert latest["speaker_turn_count"] >= 100
    assert latest["distinct_speaker_count"] >= 15
    assert latest["is_latest_call"] is True
    assert latest["promised_vs_delivered_testable"] is False
    assert latest["promised_vs_delivered_status"] == "untestable_latest_call"
    assert latest["promised_vs_delivered_note"] == LATEST_CALL_UNTESTABLE_NOTE

    # Earlier 3 calls (Aug 2026, May 2026, Feb 2026) are transcripts AND testable for promised-vs-delivered
    for earlier_doc in concalls[1:]:
        chk = earlier_doc["doctype_check"]
        assert chk["is_transcript"] is True
        assert chk["has_qa"] is True
        assert chk["speaker_turn_count"] >= 100
        assert chk["is_latest_call"] is False
        assert chk["promised_vs_delivered_testable"] is True
        assert chk["promised_vs_delivered_status"] == "testable"


def test_verify_concall_transcript_rejects_short_intimation() -> None:
    short_pages = [
        {
            "page": 1,
            "text": "Intimation under Regulation 30: Audio recording link for Q2 FY27 earnings call is available on website.",
        }
    ]
    chk = verify_concall_transcript(short_pages, is_latest_call=False)
    assert chk["is_transcript"] is False
    assert chk["doc_subtype"] == "concall_intimation_or_audio_link"
    assert chk["promised_vs_delivered_testable"] is False
