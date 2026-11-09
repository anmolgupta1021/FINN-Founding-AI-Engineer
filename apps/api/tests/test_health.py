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
    assert body["source"] == "snapshot"
    assert len(body["companies"]) == 18
    symbols = {c["symbol"] for c in body["companies"]}
    assert {"HDFCBANK", "DIXON", "KAYNES", "POLYCAB", "IEX"}.issubset(symbols)
