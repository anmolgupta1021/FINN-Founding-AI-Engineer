"""Unit tests for Phase 4 Pull engine (verifier, sector-aware trajectory, and dossier network weaving)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finn.network.matcher import match_contacts_for_dossier
from finn.pull.chunker import extract_financial_trajectory
from finn.pull.verifier import NOT_FOUND_IN_FILINGS, verify_citation
from main import app

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
client = TestClient(app)


def test_verify_citation_accepts_verbatim_and_rejects_invented() -> None:
    docs_by_id = {
        "DIXON_CONCALL_1": {
            "label": "DIXON Concall Q2 FY27 Transcript",
            "doc_type": "concall_transcript",
            "pdf_url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/dixon_q2.pdf",
            "pages": {
                5: (
                    "Atul Lall: Our mobile EMS volume grew 48% year-on-year in Q2 FY27, "
                    "and we are on track to commission the Noida display module facility by Q4 FY27."
                )
            },
        }
    }

    good = verify_citation(
        {
            "doc_id": "DIXON_CONCALL_1",
            "page": 5,
            "verbatim_quote": "mobile EMS volume grew 48% year-on-year in Q2 FY27, and we are on track to commission the Noida display module facility",
        },
        docs_by_id,
    )
    assert good["verified"] is True
    assert good["match_score"] >= 95.0
    assert good["status"] == "verified"

    bad = verify_citation(
        {
            "doc_id": "DIXON_CONCALL_1",
            "page": 5,
            "verbatim_quote": "Management guided for 95% gross margin in semiconductor wafer fabs by 2032.",
        },
        docs_by_id,
    )
    assert bad["verified"] is False
    assert bad["status"] == NOT_FOUND_IN_FILINGS

    # Number mismatch rejection test: text is close but number 48% is changed to 75%
    num_mismatch = verify_citation(
        {
            "doc_id": "DIXON_CONCALL_1",
            "page": 5,
            "verbatim_quote": "Atul Lall: Our mobile EMS volume grew 75% year-on-year in Q2 FY27, and we are on track",
        },
        docs_by_id,
    )
    assert num_mismatch["verified"] is False
    assert num_mismatch["numbers_verified"] is False
    assert "75" in num_mismatch["missing_numbers"]


def test_extract_financial_trajectory_sector_aware_lender_vs_non_lender() -> None:
    sample_html = """
    <html><body>
      <section id="profit-loss">
        <table class="data-table">
          <thead><tr><th></th><th>Mar 2024</th><th>Mar 2025</th></tr></thead>
          <tbody>
            <tr><td>Revenue +</td><td>250,000</td><td>310,000</td></tr>
            <tr><td>Financing Profit</td><td>42,000</td><td>51,000</td></tr>
            <tr><td>Financing Margin %</td><td>17%</td><td>16%</td></tr>
            <tr><td>Profit before tax</td><td>72,000</td><td>88,000</td></tr>
            <tr><td>Net Profit +</td><td>55,000</td><td>67,000</td></tr>
          </tbody>
        </table>
      </section>
      <section id="quarters">
        <table class="data-table">
          <thead><tr><th></th><th>Jun 2026</th><th>Sep 2026</th></tr></thead>
          <tbody>
            <tr><td>Revenue +</td><td>81,000</td><td>85,500</td></tr>
            <tr><td>Financing Profit</td><td>14,200</td><td>15,100</td></tr>
            <tr><td>Financing Margin %</td><td>18%</td><td>18%</td></tr>
            <tr><td>Profit before tax</td><td>22,500</td><td>23,800</td></tr>
            <tr><td>Net Profit +</td><td>16,800</td><td>17,900</td></tr>
            <tr><td>Gross NPA %</td><td>1.33%</td><td>1.36%</td></tr>
            <tr><td>Net NPA %</td><td>0.39%</td><td>0.41%</td></tr>
          </tbody>
        </table>
      </section>
    </body></html>
    """
    lender_traj = extract_financial_trajectory(sample_html, "HDFCBANK")
    assert lender_traj["is_lender"] is True
    assert lender_traj["summary_stats"]["ebitda_label"] == "EBITDA not meaningful for lenders"
    for row in lender_traj["annual_5y"]:
        assert row["ebitda_cr"] is None
        assert row["ebitda_status"] == "EBITDA not meaningful for lenders"
        assert row["ppop_or_financing_profit_cr"] is not None

    non_lender_traj = extract_financial_trajectory(sample_html, "DIXON")
    assert non_lender_traj["is_lender"] is False
    for row in non_lender_traj["annual_5y"]:
        assert row["ebitda_status"] == "derived"


def test_match_contacts_for_dossier_weaves_three_buckets() -> None:
    dixon_net = match_contacts_for_dossier(DATA_DIR, "DIXON")
    assert dixon_net["symbol"] == "DIXON"
    assert dixon_net["total_matched"] >= 3
    assert len(dixon_net["ex_company"]) >= 1
    assert len(dixon_net["competitors"]) >= 1
    for bucket in ("ex_company", "competitors", "suppliers_customers"):
        for ct in dixon_net[bucket]:
            assert ct["inferred_label"] == "inferred from employer/tenure overlap, synthetic network"
            assert "knows the company" in ct["path"] or "2nd-degree" in ct["path"]


def test_precomputed_dossiers_and_lender_generalisation_endpoints() -> None:
    idx_resp = client.get("/api/v1/dossiers")
    assert idx_resp.status_code == 200
    idx_data = idx_resp.json()
    assert idx_data["demo_symbols"] == ["DIXON", "SYRMA", "NAVINFLUOR", "POLYCAB"]
    assert "HDFCBANK" in idx_data["generalisation_symbols"]
    assert idx_data["precomputed_count"] >= 6

    for sym in ("DIXON", "SYRMA", "NAVINFLUOR", "POLYCAB", "HDFCBANK", "TITAN"):
        r = client.get(f"/api/v1/dossiers/{sym}")
        assert r.status_code == 200, f"Failed for {sym}"
        d = r.json()
        assert d["symbol"] == sym
        assert d["primary_sources_only"] is True
        assert d["verification_summary"]["concall_transcripts_verified"] == 4
        assert d["verification_summary"]["latest_call_marked_untestable"] is True
        assert d["verification_summary"]["min_rapidfuzz_score"] >= 85.0

        # Latest call must be untestable for promised-vs-delivered
        pvd = d["promised_vs_delivered"]
        assert len(pvd) >= 4
        assert pvd[0]["is_latest_call"] is True
        assert pvd[0]["promised_vs_delivered_testable"] is False
        assert pvd[0]["verdict"] == "Untestable (Latest Call)"

        # Lender path check on HDFCBANK
        if sym == "HDFCBANK":
            assert d["is_lender"] is True
            assert "EBITDA not meaningful for lenders" in d["ebitda_policy_note"]
            for yr in d["financial_trajectory"]["annual_5y"]:
                assert yr["ebitda_cr"] is None
                assert yr["ebitda_status"] == "EBITDA not meaningful for lenders"
        else:
            assert d["is_lender"] is False

    # Background job creation & polling endpoint
    build_r = client.post("/api/v1/dossiers/DIXON/build")
    assert build_r.status_code == 202
    job = build_r.json()
    assert job["symbol"] == "DIXON"
    poll_r = client.get(f"/api/v1/jobs/{job['job_id']}")
    assert poll_r.status_code == 200
    assert poll_r.json()["status"] in ("running", "completed")

