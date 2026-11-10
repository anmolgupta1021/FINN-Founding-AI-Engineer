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
    assert len(laurus["network_hooks"]) == 1
    assert laurus["network_hooks"][0]["name"] == "Meghna Reddy"
    assert "both worked at Cohance Lifesciences Limited (tenure not stated in filing)" in laurus["network_hooks"][0]["path"]
    assert all(h["name"] != "Mahesh Reddy" for h in laurus["network_hooks"])
    assert all(h["name"] != "Madhavan Iyengar" for h in laurus["network_hooks"])

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


from datetime import date

import pytest

from finn.network.matcher import _days_since, _recency_phrase


@pytest.mark.parametrize(
    ("days", "expected_phrase"),
    [
        (0, "spoke 0d ago"),
        (5, "spoke 5d ago"),
        (13, "spoke 13d ago"),
        (14, "spoke 2 wks ago"),
        (21, "spoke 3 wks ago"),
        (22, "spoke 3 wks ago"),
        (35, "spoke 5 wks ago"),
        (40, "spoke 5 wks ago"),
        (42, "spoke 6 wks ago"),
        (49, "spoke 7 wks ago"),
        (51, "spoke 7 wks ago"),
        (53, "spoke 7 wks ago"),
        (59, "spoke 8 wks ago"),
        (60, "spoke 2 mos ago"),
        (90, "spoke 3 mos ago"),
        (118, "spoke 3 mos ago"),
        (526, "spoke 17 mos ago"),
        (656, "spoke 21 mos ago"),
    ],
)
def test_recency_phrase_parametrized(days: int, expected_phrase: str):
    """Assert exact emitted phrases for boundary days."""
    assert _recency_phrase(days) == expected_phrase


@pytest.mark.parametrize(
    ("contact_dt", "anchor_dt", "expected_days", "expected_phrase"),
    [
        # Frozen demo clock anchor: 2026-11-06
        ("2026-09-14", date(2026, 11, 6), 53, "spoke 7 wks ago"),   # Siddharth Kulkarni
        ("2026-09-16", date(2026, 11, 6), 51, "spoke 7 wks ago"),   # Mahesh Reddy
        ("2025-01-19", date(2026, 11, 6), 656, "spoke 21 mos ago"), # Rajeshwari Deshmukh (seed)
        ("2026-08-22", date(2026, 11, 6), 76, "spoke 2 mos ago"),   # Meghna Reddy
        ("2026-10-12", date(2026, 11, 6), 25, "spoke 3 wks ago"),   # Nikhil Sharma
        ("2026-10-15", date(2026, 11, 6), 22, "spoke 3 wks ago"),   # Kunal Parekh
        ("2026-07-11", date(2026, 11, 6), 118, "spoke 3 mos ago"),  # Vikram Kulkarni
        # Prior announcement date anchor: 2026-10-26 (explains why earlier turn saw 6 wks / 5 wks)
        ("2026-09-14", date(2026, 10, 26), 42, "spoke 6 wks ago"),  # Siddharth Kulkarni under Oct 26
        ("2026-09-16", date(2026, 10, 26), 40, "spoke 5 wks ago"),  # Mahesh Reddy under Oct 26
    ],
)
def test_contact_recency_fixed_anchor_parametrized(
    contact_dt: str, anchor_dt: date, expected_days: int, expected_phrase: str
):
    """Assert exact mathematical days and recency phrases under fixed reference dates."""
    days = _days_since(contact_dt, anchor_dt)
    assert days == expected_days
    assert _recency_phrase(days) == expected_phrase


def test_section5_network_card_cleanup_and_honesty_rules() -> None:
    """Section 5.1-5.5: reappointment/no-overlap cap, HDFC prior-employer only, stale tie >12m, tenure honesty + synthetic label."""
    r = client.get("/api/v1/brief?window_hours=168")
    assert r.status_code == 200
    body = r.json()
    cards = body["ranked_material"] + body["deep_extracted_cards"]
    by_id = {c["id"]: c for c in cards}

    # 5.1: Re-appointments & cards without an appointee overlap show at most ONE "knows the company" hook
    dixon_vachani = by_id["nse:DIXON:106800816"]
    assert len([h for h in dixon_vachani["network_hooks"] if h["link_type"] == "knows_company"]) <= 1
    assert len(dixon_vachani["network_hooks"]) == 1
    assert dixon_vachani["network_hooks"][0]["name"] == "Rohan Desai"  # strongest (5/5) + most recent (35d)

    bajfin_ciso = by_id["nse:BAJFINANCE:106822209"]
    assert len([h for h in bajfin_ciso["network_hooks"] if h["link_type"] == "knows_company"]) == 1
    assert bajfin_ciso["network_hooks"][0]["name"] == "Vikramaditya Joshi"  # 4/5, 83d < 93d < 118d

    # Synthetic re-appointment unit check even if bio text mentions a prior org
    from pathlib import Path

    from finn.network.matcher import match_contacts_for_announcement
    from finn.store import get_company_links, get_contact_links, get_contacts

    data_dir = Path(__file__).resolve().parents[1] / "data"
    contacts = get_contacts(data_dir)["contacts"]
    c_links = get_company_links(data_dir)
    k_links = get_contact_links(data_dir)
    reappt_hooks = match_contacts_for_announcement(
        {
            "symbol": "DIXON",
            "subject": "Re-appointment of Mr. Atul B. Lall as Vice Chairman & MD",
            "details": {"kind": "management_change", "brief_profile_verbatim": "Re-appointment of MD."},
        },
        contacts,
        c_links,
        contact_links=k_links,
    )
    assert len([h for h in reappt_hooks if h["link_type"] == "knows_company"]) <= 1

    # 5.2: HDFC card: only contacts overlapping the appointee's prior employer (ICICI Bank, never PSG College)
    hdfc = by_id["nse:HDFCBANK:106850382"]
    assert len(hdfc["network_hooks"]) == 1
    assert hdfc["network_hooks"][0]["name"] == "Nandini Subramanian"
    assert "ICICI Bank" in hdfc["network_hooks"][0]["path"]
    assert all("PSG College" not in h["path"] for h in hdfc["network_hooks"])

    # 5.3: Stale tie (> 12 months / > 365 days) marked "stale tie" on every card (1st- and 2nd-degree)
    kpit = by_id["nse:KPITTECH:106831889"]
    kpit_deg2 = [h for h in kpit["network_hooks"] if h["degree"] == 2]
    assert len(kpit_deg2) == 1
    assert kpit_deg2[0]["is_stale_tie"] is True
    assert "stale tie" in kpit_deg2[0]["path"]

    for card in cards:
        for h in card.get("network_hooks") or []:
            if h.get("days_since_contact", 0) > 365:
                assert h.get("is_stale_tie") is True
                assert "stale tie" in h.get("path", "")
            # 5.4: Synthetic-to-real label + tenure honesty on every hook
            assert h["inferred_label"] == INFERRED_SYNTHETIC_LABEL
            if h["link_type"] == "same_org_tenure_not_in_filing":
                assert "tenure not stated in filing" in h["path"]


def test_section9_2_expertise_map_ask_ranking() -> None:
    """Section 9.2: 'who are my go-to people for <theme>' returns ranked list (strength x recency x tag match) + WHY line."""
    r = client.get("/api/v1/network/ask?q=who+are+my+go-to+people+for+semiconductors")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    results = body["results"]
    scores = [x["score"] for x in results]
    assert scores == sorted(scores, reverse=True)
    for row in results:
        assert "ranking_breakdown" in row
        assert row["ranking_breakdown"]["strength"] >= 1
        assert row["ranking_breakdown"]["recency_weight"] > 0
        assert len(row["why_reasons"]) >= 1
        assert row["inferred_label"] == INFERRED_SYNTHETIC_LABEL


