"""Unit tests for Phase 4 Pull engine (verifier, sector-aware trajectory, and dossier network weaving)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finn.network.matcher import match_contacts_for_dossier
from finn.pull.chunker import extract_financial_trajectory
from finn.pull.prompts import (
    compute_guidance_verdict_in_code,
    compute_reported_vs_stated_in_code,
    resolve_fiscal_period_quarters,
    trim_quote_to_guidance_sentence,
    validate_claim_scope_consistency,
    validate_claim_unit_and_metric,
)
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
        assert d["verification_summary"]["min_rapidfuzz_score"] >= 85.0
        assert "balance_sheet_panel" in d and d["balance_sheet_panel"]["borrowings_cr"] is not None

        if sym in ("DIXON", "POLYCAB", "HDFCBANK"):
            assert d["analysis_generated"] is True
            assert len(d["promised_vs_delivered"]) >= 1
            assert d["llm_provenance"]["cost_usd"] > 0
            for row in d["promised_vs_delivered"]:
                assert row.get("promised_citation", {}).get("verified") is True
                if row.get("is_latest_call"):
                    assert row["verdict"] == "Untestable (Latest Call)"
                    assert row["promised_vs_delivered_testable"] is False
            for sec in (d["numbers_vs_narrative"], d["bull_case"], d["bear_case"]):
                assert len(sec) >= 1
                for item in sec:
                    assert item["citation"]["verified"] is True
        else:
            assert d["analysis_generated"] is False
            assert d["analysis_header"] == "Deterministic extracts only; analysis not generated."
            assert d["promised_vs_delivered"] == []
            assert d["numbers_vs_narrative"] == []
            assert d["bull_case"] == []
            assert d["bear_case"] == []

        # Lender path check on HDFCBANK
        if sym == "HDFCBANK":
            assert d["is_lender"] is True
            assert "EBITDA not meaningful for lenders" in d["ebitda_policy_note"]
            assert d["balance_sheet_panel"]["car_pct"] == 19.7
            for yr in d["financial_trajectory"]["annual_5y"]:
                assert yr["ebitda_cr"] is None
                assert yr["ebitda_status"] == "EBITDA not meaningful for lenders"
        else:
            assert d["is_lender"] is False
            assert d["balance_sheet_panel"]["working_capital_days"] is not None

    # Background job creation & polling endpoint
    build_r = client.post("/api/v1/dossiers/DIXON/build")
    assert build_r.status_code == 202
    job = build_r.json()
    assert job["symbol"] == "DIXON"
    poll_r = client.get(f"/api/v1/jobs/{job['job_id']}")
    assert poll_r.status_code == 200
    assert poll_r.json()["status"] in ("running", "completed")


def test_guidance_unit_validation_drops_missing_unit_dixon_fixture() -> None:
    # Truncated DIXON #1 quote ends with '33-34' and lacks any unit inside the quote
    ok_missing, reason = validate_claim_unit_and_metric(
        {
            "metric": "Volume Growth",
            "unit": "million units",
            "quote": "And with the outlook for H2, we feel we should be somewhere around 33-34",
        }
    )
    assert ok_missing is False
    assert reason == "missing_unit_in_quote"

    ok_no_unit, reason2 = validate_claim_unit_and_metric(
        {
            "metric": "Volume Growth",
            "unit": "",
            "quote": "And with the outlook for H2, we feel we should be somewhere around 33-34",
        }
    )
    assert ok_no_unit is False
    assert reason2 == "missing_unit"

    ok_valid, reason3 = validate_claim_unit_and_metric(
        {
            "metric": "Mobile Volume",
            "unit": "million units",
            "quote": "One is, of course, this year volumes, you have broadly saying 33-34 million",
        }
    )
    assert ok_valid is True
    assert reason3 is None


def test_guidance_verdict_branches_with_dixon_fixtures() -> None:
    dixon_traj = {
        "annual_5y": [
            {"period": "Mar 2026", "revenue_cr": 48873.0, "ebitda_margin_derived_pct": 3.8, "pat_cr": 1645.0}
        ],
        "quarterly_recent": [
            {"quarter": "Jun 2025", "revenue_cr": 12836.0, "ebitda_margin_derived_pct": 3.8, "pat_cr": 280.0},
            {"quarter": "Sep 2025", "revenue_cr": 14855.0, "ebitda_margin_derived_pct": 3.8, "pat_cr": 746.0},
            {"quarter": "Dec 2025", "revenue_cr": 10672.0, "ebitda_margin_derived_pct": 3.9, "pat_cr": 321.0},
            {"quarter": "Mar 2026", "revenue_cr": 10511.0, "ebitda_margin_derived_pct": 3.9, "pat_cr": 298.0},
            {"quarter": "Jun 2026", "revenue_cr": 15548.0, "ebitda_margin_derived_pct": 3.0, "pat_cr": 718.0},
            {"quarter": "Sep 2026", "revenue_cr": 21794.0, "ebitda_margin_derived_pct": 2.7, "pat_cr": 411.0},
        ],
    }

    assert resolve_fiscal_period_quarters("FY27") == ["Jun 2026", "Sep 2026", "Dec 2026", "Mar 2027"]
    assert resolve_fiscal_period_quarters("H2 FY27") == ["Dec 2026", "Mar 2027"]
    assert resolve_fiscal_period_quarters("Q3 FY26") == ["Dec 2025"]

    # 1. Latest call -> Untestable (Latest Call) + fixed template
    v_latest = compute_guidance_verdict_in_code(
        {
            "metric": "Operating EBITDA Margin",
            "scope": "consolidated",
            "condition": None,
            "target_low": 80,
            "unit": "bps",
            "fiscal_period": "FY28",
            "is_latest_call": True,
        },
        dixon_traj,
    )
    assert v_latest["verdict"] == "Untestable (Latest Call)"
    assert v_latest["has_verdict"] is False
    assert v_latest["one_line_explanation"].startswith("Fixed template:")

    # 2. Segment/product scope (DIXON #4 Rs 3,500-4,000 Cr segment target) -> Not comparable to filed numbers
    v_seg = compute_guidance_verdict_in_code(
        {
            "metric": "IT Hardware / Display Revenue",
            "scope": "segment",
            "condition": None,
            "target_low": 3500.0,
            "target_high": 4000.0,
            "unit": "crores",
            "fiscal_period": "FY27",
            "quote": "We feel that for next year, the numbers are going to be somewhere around INR3,500 crores to INR4,000 crores.",
            "is_latest_call": False,
        },
        dixon_traj,
    )
    assert v_seg["verdict"] == "Not comparable to filed numbers"
    assert v_seg["has_verdict"] is False
    assert v_seg["one_line_explanation"].startswith("Fixed template:")

    # 3. Conditional guidance (DIXON #3 Rs 56,000 Cr "without the Vivo numbers") -> Conditional, not scored
    v_cond = compute_guidance_verdict_in_code(
        {
            "metric": "Consolidated Revenue",
            "scope": "consolidated",
            "condition": "without the Vivo numbers",
            "target_low": 56000.0,
            "unit": "crores",
            "fiscal_period": "FY27",
            "quote": "Without the Vivo numbers, this year, we closed at almost INR48,000 crores -- INR48,800-odd crores. Next year, we are targeting almost INR56,000 crores without the Vivo numbers, and mobile volume being flat.",
            "is_latest_call": False,
        },
        dixon_traj,
    )
    assert v_cond["verdict"] == "Conditional, not scored"
    assert v_cond["has_verdict"] is False
    assert "without the Vivo numbers" in v_cond["delivered_summary"]
    assert v_cond["one_line_explanation"].startswith("Fixed template:")

    # 4. Incomplete fiscal period (unconditional FY27 target when only Jun 2026 & Sep 2026 are filed)
    v_inc = compute_guidance_verdict_in_code(
        {
            "metric": "Consolidated Revenue",
            "scope": "consolidated",
            "condition": None,
            "target_low": 56000.0,
            "unit": "crores",
            "fiscal_period": "FY27",
            "quote": "We target INR56,000 crores revenue in FY27.",
            "is_latest_call": False,
        },
        dixon_traj,
    )
    assert v_inc["verdict"] == "No verdict (period incomplete)"
    assert v_inc["has_verdict"] is False
    assert "2 of 4 quarters filed (Jun 2026, Sep 2026)" in v_inc["delivered_summary"]
    assert "66.7% of ₹56,000 Cr target" in v_inc["delivered_summary"]
    assert v_inc["one_line_explanation"].startswith("Fixed template:")

    # 5a. Complete, consolidated, unconditional numeric target -> Delivered (H1 FY27 actual 37,342 >= 35,000)
    v_deliv = compute_guidance_verdict_in_code(
        {
            "metric": "Consolidated Revenue",
            "scope": "consolidated",
            "condition": None,
            "target_low": 35000.0,
            "unit": "crores",
            "fiscal_period": "H1 FY27",
            "is_latest_call": False,
        },
        dixon_traj,
    )
    assert v_deliv["verdict"] == "Delivered"
    assert v_deliv["has_verdict"] is True
    assert v_deliv["one_line_explanation"] is None

    # 5b. Complete, consolidated, unconditional numeric target -> Missed (H1 FY27 actual 37,342 < 40,000)
    v_miss = compute_guidance_verdict_in_code(
        {
            "metric": "Consolidated Revenue",
            "scope": "consolidated",
            "condition": None,
            "target_low": 40000.0,
            "unit": "crores",
            "fiscal_period": "H1 FY27",
            "is_latest_call": False,
        },
        dixon_traj,
    )
    assert v_miss["verdict"] == "Missed"
    assert v_miss["has_verdict"] is True
    assert v_miss["one_line_explanation"] is None

    # 5c. Complete, consolidated, unconditional numeric target revised later -> Moved goalposts
    v_moved = compute_guidance_verdict_in_code(
        {
            "metric": "Consolidated Revenue",
            "scope": "consolidated",
            "condition": None,
            "target_low": 40000.0,
            "unit": "crores",
            "fiscal_period": "H1 FY27",
            "goalposts_moved": True,
            "is_latest_call": False,
        },
        dixon_traj,
    )
    assert v_moved["verdict"] == "Moved goalposts"
    assert v_moved["has_verdict"] is True


def test_scope_consistency_sentence_trim_and_reported_vs_stated() -> None:
    # Scope consistency validator rejects wider labels on segment/product scope
    bad_scope1, reason1 = validate_claim_scope_consistency({"metric": "Consolidated Revenue", "scope": "segment"})
    assert bad_scope1 is False
    assert reason1 == "scope_mismatch_wider_label_on_segment_or_product"

    bad_scope2, reason2 = validate_claim_scope_consistency({"metric": "Operating EBITDA Margin", "scope": "segment"})
    assert bad_scope2 is False
    assert reason2 == "scope_mismatch_bare_company_metric_without_segment_qualifier"

    good_scope, _ = validate_claim_scope_consistency({"metric": "Display & Camera Module Margin Expansion", "scope": "segment"})
    assert good_scope is True

    # Sentence trimmer removes mid-sentence fragments & unrelated run-ons
    t1 = trim_quote_to_guidance_sentence(
        "business. We feel that in next couple of years, this is going to be almost INR 15,000 crore to INR 20,000 crore business for us. Further, as I mentioned in my opening remarks, and that our joint venture with Inventec is going to get operationalized"
    )
    assert t1 == "We feel that in next couple of years, this is going to be almost INR 15,000 crore to INR 20,000 crore business for us."

    t2 = trim_quote_to_guidance_sentence(
        "Without the Vivo numbers, this year, we closed at almost INR48,000 crores -- INR48,800-odd crores. Next year, we are targeting almost INR56,000 crores without the Vivo numbers, and mobile volume being flat."
    )
    assert t2 == "Next year, we are targeting almost INR56,000 crores without the Vivo numbers, and mobile volume being flat."

    # Reported vs Stated comparison on DIXON Jun 2026
    dixon_traj = {
        "quarterly_recent": [
            {"quarter": "Jun 2026", "revenue_cr": 15548.0, "ebitda_derived_cr": 463.0, "pat_cr": 718.0},
        ]
    }
    rvs_rev = compute_reported_vs_stated_in_code({"metric": "Revenue", "quarter_referenced": "Jun 2026", "stated_value": 15557.0}, dixon_traj)
    assert rvs_rev is not None
    assert rvs_rev["label"] == "stated vs filed"
    assert rvs_rev["filed_value"] == 15548.0
    assert rvs_rev["status"] == "Match (within 2%)"

    rvs_pat = compute_reported_vs_stated_in_code({"metric": "PAT", "quarter_referenced": "Jun 2026", "stated_value": 218.0}, dixon_traj)
    assert rvs_pat is not None
    assert rvs_pat["filed_value"] == 718.0
    assert "Variance" in rvs_pat["status"]

    # Millions & billions conversion + full-year row check (Polycab unit pattern)
    poly_traj = {
        "quarterly_recent": [
            {"quarter": "Sep 2026", "pat_cr": 990.0, "ebitda_margin_derived_pct": 14.0},
            {"quarter": "Mar 2026", "revenue_cr": 8864.0},
        ],
        "annual_5y": [{"period": "Mar 2026", "revenue_cr": 28884.0}],
    }
    rvs_mn = compute_reported_vs_stated_in_code(
        {"metric": "PAT", "quarter_referenced": "Sep 2026", "stated_value": 9900.0, "unit": "million"},
        poly_traj,
    )
    assert rvs_mn is not None and rvs_mn["stated_value"] == 990.0 and rvs_mn["status"] == "Match (within 2%)"

    rvs_bn = compute_reported_vs_stated_in_code(
        {"metric": "Revenue", "quarter_referenced": "Mar 2026", "stated_value": 285.0, "unit": "billion", "quote": "Revenue crossed INR 285 billion milestone"},
        poly_traj,
    )
    assert rvs_bn is not None and rvs_bn["stated_value"] == 28500.0 and rvs_bn["filed_value"] == 28884.0 and rvs_bn["status"] == "Match (within 2%)"



