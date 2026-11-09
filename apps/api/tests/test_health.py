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


def test_prices_endpoint_all_22_symbols() -> None:
    resp = client.get("/api/v1/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 22
    assert "Prices · EOD" in body["freshness_chip"]
    assert "POLYCAB" in body["prices"]
    assert "LAURUSLABS" in body["prices"]
    assert body["prices"]["POLYCAB"]["close"] > 0

    filtered = client.get("/api/v1/prices?symbols=POLYCAB,DIXON").json()
    assert filtered["count"] == 2


def test_announcements_and_window_filtering() -> None:
    resp = client.get("/api/v1/announcements")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 32
    assert body["material_count"] == 8
    assert body["routine_count"] == 24
    # Highest priority item in the demo window is Kaynes CFO appointment or Polycab Q2 results
    top = body["material"][0]
    assert top["symbol"] in ("KAYNES", "POLYCAB")
    assert top["priority"] >= 88

    # Without demo scenario items, Kaynes synthetic CFO scenario is excluded
    no_demo = client.get("/api/v1/announcements?include_demo=false").json()
    assert no_demo["total"] == 31


def test_freshness_and_ledger_endpoints() -> None:
    fr = client.get("/api/v1/freshness")
    assert fr.status_code == 200
    fbody = fr.json()
    assert fbody["prices"]["count"] == 22
    assert fbody["announcements"]["total"] == 32
    assert "bulk_model" in fbody["models"]

    lg = client.get("/api/v1/llm/ledger")
    assert lg.status_code == 200
    assert "total_calls" in lg.json()
