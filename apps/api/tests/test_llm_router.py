import shutil
from pathlib import Path

import pytest

from finn.llm.privacy import PrivacyViolationError
from finn.llm.router import LLMRouter

REAL_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _make_isolated_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(REAL_DATA_DIR / "seed", data_dir / "seed")
    (data_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    return data_dir


def test_privacy_blocks_forbidden_source_kind(tmp_path: Path) -> None:
    data_dir = _make_isolated_data_dir(tmp_path)
    calls: list[str] = []
    router = LLMRouter(
        data_dir,
        transport=lambda m, s, c, schema, tb: calls.append(m) or {"text": "ok", "in_tokens": 5, "out_tokens": 2},
    )
    with pytest.raises(PrivacyViolationError, match="source_kind"):
        router.generate(
            task="bad_call",
            tier="bulk",
            source_kind="network",
            prompt_version="v1",
            system="Summarize contact",
            contents="Who should I call?",
        )
    assert calls == []


def test_privacy_blocks_contact_notes_and_ids(tmp_path: Path) -> None:
    data_dir = _make_isolated_data_dir(tmp_path)
    calls: list[str] = []
    router = LLMRouter(
        data_dir,
        transport=lambda m, s, c, schema, tb: calls.append(m) or {"text": "ok", "in_tokens": 5, "out_tokens": 2},
    )
    # 1. Exact substring of Rohan Desai's synthetic meeting note must be blocked even if source_kind='public_filing'
    with pytest.raises(PrivacyViolationError, match="Private investor network"):
        router.generate(
            task="leak_note",
            tier="bulk",
            source_kind="public_filing",
            prompt_version="v1",
            system="Extract claims",
            contents="Met at Bengaluru EMS roundtable. Sharp on Kaynes vs Syrma receivable days",
        )
    # 2. Contact ID must be blocked
    with pytest.raises(PrivacyViolationError, match="Private"):
        router.generate(
            task="leak_id",
            tier="bulk",
            source_kind="user_query_text",
            prompt_version="v1",
            system="Parse intent",
            contents="Intro via contact:rohan_desai",
        )
    # 3. Forbidden dict key ('notes') must be blocked
    with pytest.raises(PrivacyViolationError, match="forbidden key"):
        router.generate(
            task="leak_key",
            tier="bulk",
            source_kind="public_filing",
            prompt_version="v1",
            system="Classify",
            contents={"subject": "Filing", "notes": "private relationship note"},
        )
    assert calls == []


def test_router_sha256_cache_and_ledger(tmp_path: Path) -> None:
    data_dir = _make_isolated_data_dir(tmp_path)
    transport_calls: list[tuple[str, int]] = []

    def fake_transport(model: str, system: str, contents: object, schema: object, tb: int) -> dict:
        transport_calls.append((model, tb))
        return {
            "text": '{"category": "results"}',
            "parsed": {"category": "results"},
            "in_tokens": 120,
            "out_tokens": 18,
            "thinking_tokens": tb // 4 if tb else 0,
        }

    router = LLMRouter(data_dir, transport=fake_transport)

    # First call: live
    r1 = router.generate(
        task="classify_announcement",
        tier="bulk",
        source_kind="public_filing",
        prompt_version="cls-v1",
        system="Classify NSE filing",
        contents={"symbol": "POLYCAB", "subject": "Outcome of Board Meeting - Q2 Results"},
    )
    assert r1["cache_hit"] is False
    assert len(transport_calls) == 1

    # Second identical call: hits SHA-256 content-hash cache, zero transport calls
    r2 = router.generate(
        task="classify_announcement",
        tier="bulk",
        source_kind="public_filing",
        prompt_version="cls-v1",
        system="Classify NSE filing",
        contents={"symbol": "POLYCAB", "subject": "Outcome of Board Meeting - Q2 Results"},
    )
    assert r2["cache_hit"] is True
    assert r2["cache_key"] == r1["cache_key"]
    assert len(transport_calls) == 1

    # Strong tier routes to strong model with thinking budget > 0
    r3 = router.generate(
        task="narrative_vs_numbers",
        tier="strong",
        source_kind="public_filing",
        prompt_version="nvn-v1",
        system="Compare guidance vs actuals",
        contents={"claims": ["c1", "c2"]},
    )
    assert r3["cache_hit"] is False
    assert len(transport_calls) == 2
    assert transport_calls[1][1] > 0

    summary = router.ledger.summary()
    assert summary["total_calls"] == 3
    assert summary["cache_hits"] == 1
    assert summary["live_calls"] == 2
    assert summary["in_tokens"] == 360


def test_cost_endpoint_matches_llm_ledger_jsonl_exactly() -> None:
    """Section 6.3: /api/v1/llm/ledger & dossier llm_provenance match llm_ledger.jsonl line-by-line."""
    import json

    from fastapi.testclient import TestClient

    from main import app

    rows = [
        json.loads(line)
        for line in (REAL_DATA_DIR / "snapshots" / "llm_ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]
    client = TestClient(app)
    api_summary = client.get("/api/v1/llm/ledger").json()

    assert api_summary["total_calls"] == len(rows)
    assert api_summary["cache_hits"] == sum(1 for r in rows if r.get("cache_hit"))
    assert api_summary["live_calls"] == sum(1 for r in rows if not r.get("cache_hit"))
    assert api_summary["in_tokens"] == sum(int(r.get("in_tokens", 0)) for r in rows)
    assert api_summary["out_tokens"] == sum(int(r.get("out_tokens", 0)) for r in rows)
    assert api_summary["thinking_tokens"] == sum(int(r.get("thinking_tokens", 0) or 0) for r in rows)
    assert api_summary["estimated_paid_cost_usd"] == round(sum(float(r.get("cost_usd", 0.0)) for r in rows), 6)
    assert api_summary["estimated_paid_cost_inr"] == round(sum(float(r.get("cost_inr", 0.0)) for r in rows), 4)

    for sym in ("DIXON", "POLYCAB", "HDFCBANK"):
        sym_live = [
            r for r in rows if str(r.get("task", "")).lower().endswith(f"_{sym.lower()}") and not r.get("cache_hit")
        ]
        d = client.get(f"/api/v1/dossiers/{sym}").json()
        assert d["llm_provenance"]["cost_usd"] == round(sum(float(r.get("cost_usd", 0.0)) for r in sym_live), 6)
        assert d["llm_provenance"]["cost_inr"] == round(sum(float(r.get("cost_inr", 0.0)) for r in sym_live), 4)


def test_no_private_contact_data_in_any_llm_cache_or_ledger() -> None:
    """Section 6.4: assert that zero private contact names, IDs, or notes appear in LLM cache or ledger."""
    import json

    contacts_raw = (REAL_DATA_DIR / "seed" / "network" / "contacts.json").read_text()
    contacts = json.loads(contacts_raw).get("contacts", [])
    cache_text = (REAL_DATA_DIR / "snapshots" / "llm_cache.json").read_text()
    ledger_text = (REAL_DATA_DIR / "snapshots" / "llm_ledger.jsonl").read_text()
    combined = f"{cache_text}\n{ledger_text}"

    assert len(contacts) >= 50
    for ct in contacts:
        assert ct["id"] not in combined
        assert ct["name"] not in combined
        note = (ct.get("notes") or "").strip()
        if len(note) >= 16:
            assert note not in combined
