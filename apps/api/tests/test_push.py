from fastapi.testclient import TestClient

from finn.network.matcher import INFERRED_SYNTHETIC_LABEL
from main import app

client = TestClient(app)


def test_brief_default_24h_frozen_clock():
    r = client.get("/api/v1/brief?window_hours=24")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_clock"]["mode"] == "frozen"
    assert body["demo_clock"]["anchor_date"] == "2026-11-06"
    assert len(body["ranked_material"]) >= 2
    assert body["routine_summary"]["count"] >= 1

    # Verify HDFCBANK management_change PDF extraction + inferred synthetic network hook
    hdfc_mgmt = [
        x
        for x in body["ranked_material"]
        if x["symbol"] == "HDFCBANK" and (x.get("details") or {}).get("kind") == "management_change"
    ]
    assert len(hdfc_mgmt) >= 1
    item = hdfc_mgmt[0]
    assert "ICICI" in item["details"]["brief_profile_verbatim"]
    assert item["details"]["cited_page"] == 3
    assert len(item["network_hooks"]) >= 1
    top_hook = item["network_hooks"][0]
    assert top_hook["name"] == "Nandini Subramanian"
    assert "ICICI Bank Limited" in top_hook["path"]
    assert top_hook["inferred_label"] == INFERRED_SYNTHETIC_LABEL


def test_brief_triggered_alerts_and_threshold_tuning():
    r_strict = client.get("/api/v1/brief?vol_mult_min=4.0&price_move_min=6.0")
    assert r_strict.status_code == 200
    strict_alerts = r_strict.json()["triggered_alerts"]
    strict_syms = [a["symbol"] for a in strict_alerts]
    # TITAN has 5.55x volume on 2026-11-06
    assert "TITAN" in strict_syms

    r_loose = client.get("/api/v1/brief?vol_mult_min=2.0&price_move_min=2.0")
    loose_alerts = r_loose.json()["triggered_alerts"]
    assert len(loose_alerts) > len(strict_alerts)


def test_brief_deep_extracted_results_and_reconnect_nudges():
    r = client.get("/api/v1/brief?window_hours=168")
    assert r.status_code == 200
    body = r.json()

    results_cards = [
        x for x in body["deep_extracted_cards"] if (x.get("details") or {}).get("kind") == "results"
    ]
    polycab = next(x for x in results_cards if x["symbol"] == "POLYCAB")
    rows = {row["metric"]: row for row in polycab["details"]["rows"]}
    assert rows["Revenue"]["cur"] == 9898.90
    assert rows["Revenue"]["screener_val"] == 9899.0
    assert abs(rows["Revenue"]["screener_delta_pct"]) <= 0.05

    assert len(body["reconnect_nudges"]) >= 1
    for nudge in body["reconnect_nudges"]:
        assert nudge["months_stale"] >= 4
        assert nudge["inferred_label"] == INFERRED_SYNTHETIC_LABEL
