from fastapi.testclient import TestClient

from finn.network.matcher import INFERRED_SYNTHETIC_LABEL
from finn.pipeline.results import LENDER_EBITDA_LABEL, check_ebitda_plausibility
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

    # Verify HDFCBANK management_change PDF extraction + Network Honesty Rule
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
    assert "both worked at ICICI Bank Limited (tenure not stated in filing)" in top_hook["path"]
    assert top_hook["inferred_label"] == INFERRED_SYNTHETIC_LABEL
    # No 2nd-degree claim when filing does not state appointee's prior-employer tenure dates
    assert [h for h in item["network_hooks"] if h.get("degree") == 2] == []

    # Check Laurus/Jha, Bajaj CISO, Dixon/Vachani, and KPIT/Talaulicar in deep_extracted_cards
    cards_by_id = {x["id"]: x for x in body["deep_extracted_cards"]}

    laurus = cards_by_id["nse:LAURUSLABS:106834235"]
    assert "both worked at Cohance Lifesciences Limited (tenure not stated in filing)" in laurus["network_hooks"][0]["path"]

    bajfin_ciso = cards_by_id["nse:BAJFINANCE:106822209"]
    assert all("knows the company" in h["path"] for h in bajfin_ciso["network_hooks"])

    dixon_vachani = cards_by_id["nse:DIXON:106800816"]
    assert all("knows the company" in h["path"] for h in dixon_vachani["network_hooks"])

    kpit_talaulicar = cards_by_id["nse:KPITTECH:106831889"]
    assert "overlapped at Cummins Group in India (filing states 2004–2017)" in kpit_talaulicar["network_hooks"][0]["path"]
    kpit_deg2 = [h for h in kpit_talaulicar["network_hooks"] if h.get("degree") == 2]
    assert len(kpit_deg2) == 1
    assert "via Siddharth Kulkarni" in kpit_deg2[0]["path"]
    assert "target last contacted" in kpit_deg2[0]["path"]
    assert "Rajeshwari Deshmukh" in kpit_deg2[0]["path"]
    assert "filing states 2004–2017" in kpit_deg2[0]["path"]


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


def test_brief_deep_extracted_results_sector_aware_and_reconnect_nudges():
    r = client.get("/api/v1/brief?window_hours=168")
    assert r.status_code == 200
    body = r.json()

    results_cards = [
        x for x in body["deep_extracted_cards"] if (x.get("details") or {}).get("kind") == "results"
    ]
    polycab = next(x for x in results_cards if x["symbol"] == "POLYCAB")
    assert polycab["details"]["is_lender"] is False
    assert polycab["details"]["lender_note"] is None
    rows = {row["metric"]: row for row in polycab["details"]["rows"]}
    assert rows["Revenue"]["cur"] == 9898.90
    assert rows["Revenue"]["screener_val"] == 9899.0
    assert abs(rows["Revenue"]["screener_delta_pct"]) <= 0.05
    assert rows["EBITDA"]["derived"] is True
    assert rows["EBITDA"]["status"] == "derived"
    assert rows["EBITDA"]["margin_pct"] == 14.4

    # Lender results card: BAJFINANCE must NOT show EBITDA; shows NII, PPOP, PBT, PAT + lender_note
    bajfin = next(x for x in results_cards if x["symbol"] == "BAJFINANCE")
    assert bajfin["details"]["is_lender"] is True
    assert bajfin["details"]["lender_note"] == LENDER_EBITDA_LABEL
    bf_metrics = [row["metric"] for row in bajfin["details"]["rows"]]
    assert "EBITDA" not in bf_metrics
    assert bf_metrics == ["NII", "PPOP", "PBT", "PAT"]
    bf_rows = {row["metric"]: row for row in bajfin["details"]["rows"]}
    assert bf_rows["NII"]["cur"] == 13334.66
    assert bf_rows["PPOP"]["cur"] == 10703.29
    assert bf_rows["PBT"]["cur"] == 8537.20
    assert bf_rows["PAT"]["cur"] == 6366.57

    assert len(body["reconnect_nudges"]) >= 1
    for nudge in body["reconnect_nudges"]:
        assert nudge["months_stale"] >= 4
        assert nudge["inferred_label"] == INFERRED_SYNTHETIC_LABEL


def test_ebitda_plausibility_check():
    status_ok, margin_ok = check_ebitda_plausibility(1422.49, 9898.90)
    assert status_ok == "derived"
    assert margin_ok == 14.4

    status_low, margin_low = check_ebitda_plausibility(50.0, 10000.0)
    assert status_low == "unreliable"
    assert margin_low == 0.5

    status_high, margin_high = check_ebitda_plausibility(7500.0, 10000.0)
    assert status_high == "unreliable"
    assert margin_high == 75.0


def test_network_ask_endpoint_1st_and_2nd_degree():
    r = client.get("/api/v1/network/ask?q=ICICI+Bank&limit=6")
    assert r.status_code == 200
    body = r.json()
    assert body["total_contacts"] == 67
    assert body["total_links"] == 24
    assert body["inferred_label"] == INFERRED_SYNTHETIC_LABEL
    assert len(body["results"]) >= 2

    deg1 = [c for c in body["results"] if c["degree"] == 1]
    deg2 = [c for c in body["results"] if c["degree"] == 2]
    assert len(deg1) >= 1
    assert len(deg2) >= 1
    assert any("Arvind Raghavan" in c["path"] for c in deg2)
    for c in body["results"]:
        assert c["inferred_label"] == INFERRED_SYNTHETIC_LABEL


def test_brief_window_scrubber_monotonicity():
    """A5: Assert count(24h) <= count(3d) <= count(7d) <= count(14d), and counts are not all equal."""
    windows = [24, 72, 168, 336]
    material_counts = []
    routine_counts = []
    total_counts = []

    for w in windows:
        r = client.get(f"/api/v1/brief?window_hours={w}&as_of=2026-11-06T23:59:59%2B05:30")
        assert r.status_code == 200
        data = r.json()
        mat = len(data.get("ranked_material", []))
        rout = data.get("routine_summary", {}).get("count", 0)
        tot = mat + rout
        material_counts.append(mat)
        routine_counts.append(rout)
        total_counts.append(tot)

    # Monotonicity check
    assert material_counts[0] <= material_counts[1] <= material_counts[2] <= material_counts[3]
    assert routine_counts[0] <= routine_counts[1] <= routine_counts[2] <= routine_counts[3]
    assert total_counts[0] <= total_counts[1] <= total_counts[2] <= total_counts[3]

    # Verify counts are strictly not all equal
    assert material_counts[0] < material_counts[-1]
    assert routine_counts[0] < routine_counts[-1]
    assert total_counts[0] < total_counts[-1]
