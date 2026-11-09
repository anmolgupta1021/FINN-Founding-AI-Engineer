from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["service"] == "finn-api"
    assert body["data_dir_found"] is True


def test_portfolio_snapshot_fallback() -> None:
    resp = client.get("/api/v1/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] in ("snapshot", "neon")
    assert len(body["companies"]) == 18
    assert len(body.get("research", [])) == 4
    symbols = {c["symbol"] for c in body["companies"]}
    assert {"HDFCBANK", "DIXON", "KAYNES", "POLYCAB", "IEX"}.issubset(symbols)
    research_syms = {c["symbol"] for c in body["research"]}
    assert research_syms == {"SYRMA", "NAVINFLUOR", "PIDILITIND", "LAURUSLABS"}


def test_prices_endpoint_all_22_completed_session() -> None:
    resp = client.get("/api/v1/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 22
    assert body.get("completed_session") is True
    assert "Prices · EOD" in body["freshness_chip"]
    assert "POLYCAB" in body["prices"]
    assert "LAURUSLABS" in body["prices"]
    assert body["prices"]["POLYCAB"]["close"] > 0


def test_announcements_provenance_and_demo_clock() -> None:
    resp = client.get("/api/v1/announcements")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 400
    assert body["provenance"]["demo_count"] == 0
    assert body["provenance"]["with_resolvable_pdf_url"] == body["total"]
    assert body["demo_clock"]["mode"] == "frozen"

    # 24h window relative to frozen demo clock works and returns only filings from that 24h window
    w24 = client.get("/api/v1/announcements?window_hours=24").json()
    assert 0 < w24["total"] < body["total"]


def test_freshness_and_ledger_endpoints() -> None:
    fr = client.get("/api/v1/freshness")
    assert fr.status_code == 200
    fbody = fr.json()
    assert fbody["prices"]["count"] == 22
    assert fbody["announcements"]["total"] >= 400
    assert "bulk_model" in fbody["models"]

    lg = client.get("/api/v1/llm/ledger")
    assert lg.status_code == 200
    assert "total_calls" in lg.json()
