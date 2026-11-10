# FINN — Founding AI Engineer Build Writeup

**Live App:** https://finn-bay.vercel.app · **Cost & Ledger:** https://finn-bay.vercel.app/cost  
**Target Role:** ENAM Holdings · Founding AI Engineer Challenge (IIT Kanpur – 2027)

---

## 1. Interaction Model & Design Philosophy: "The Brief"

An institutional public-equity investor's workflow splits cleanly into three modes: morning triage across portfolio holdings, interrupt-driven diligence on unexpected price moves or filings, and deep primary-source research on a single company. FINN implements all three in a single mobile-first Progressive Web App organised around **"The Brief"** (`ranked feed → company dossiers → command bar`) rather than a blank chat box or a bolted-on Contacts tab.

Every surface separates **what comes from primary exchange filings** from **what comes from synthetic relationship data** and enforces deterministic code checks wherever numbers or quotes can be verified programmatically.

---

## 2. Two-Speed Push Pipeline (776 Real NSE/BSE Filings)

Standard `httpx` requests to `www.nseindia.com` and `api.bseindia.com` return `HTTP 403` due to Akamai/Cloudflare TLS JA3 fingerprinting. Using `curl_cffi` with Chrome TLS impersonation locally, FINN ingested a 45-day corpus across 22 tracked NSE/BSE symbols (18 portfolio holdings + 4 watchlist peers including `LAURUSLABS`, which replaced delisted `JBCHEPHARM`). Deduplication produced **776 real exchange announcements** (`359` NSE, `417` BSE, `0` demo scenarios), every single one carrying a direct `.pdf` link (`776/776`).

Classification runs in two cost-controlled stages (`finn/pipeline/classify.py`):
1. **Stage-1 Deterministic Rules (`339/776 = 43.7%`):** Regex-ordered rules classify high-precision categories (Financial Results, KMP/Board Changes, Capex, M&A, Litigation, Earnings Calls) plus explicit noise filters (ESOP allotments, Regulation 74(5) depository certificates, loss of share certificates). On a uniform random 40-item sample (`data/eval/real_announcements_40_to_label.json`), Stage-1 rules match `16/40 (40.0%)`.
2. **Stage-2 Bulk LLM (`437/776 = 56.3%`, `0` fallback):** The remaining `364` previously unclassified announcements were processed in 19 batches of 20 using `gemini-3.5-flash-lite` (with automatic `gemini-3.1-flash-lite` fallback on rate pressure). Across all 24 batch calls recorded in `llm_ledger.jsonl`, Stage-2 consumed `36,633` input tokens and `28,858` output tokens (`$0.015205 USD` / `₹1.3077` counterfactual paid cost; `₹0.00` on free tier).

On top of the filing stream, completed-session EOD price bars from `yfinance` (stripping partial intraday candles before `15:45 IST`) drive configurable threshold alerts (≥2.0× 20-day average volume or ±2.5% price move). A visible **Demo Clock** supports frozen snapshots (`6 Nov 2026`, `28–29 Oct`, `15–19 Oct`) alongside a monotonic window scrubber (`24h / 3d / 7d / 14d / 45d`) verified in tests (`9 → 30 → 43 → 128` material items).

---

## 3. Sector-Aware Filing Extractors & Cross-Checks

Two deep PDF extractors run cleanly on live exchange filings without hand-entered numbers:
- **Quarterly Results vs Screener (`results.py`):** Extracts Q2 tables from `POLYCAB` (p.4, normalising `₹ million ÷ 10 → ₹ Cr`) and `BAJFINANCE` (p.14), automatically flagging deviations (`Δ x% vs screener`). For banks/NBFCs (`HDFCBANK`, `BAJFINANCE`, `CREDITACC`, `CAMS`), EBITDA is omitted with the banner `"EBITDA not meaningful for lenders"` in favour of NII, PPOP, PBT, PAT, and Gross/Net NPA. For non-financials, EBITDA is explicitly marked `"derived"` and screened against a `2.0%–55.0%` plausibility band.
- **Management-Change Brief Profiles (`mgmt.py`):** Extracts verbatim SEBI LODR biographical disclosures (page + SHA-256 hash) across filings such as `HDFCBANK` (p.3), `KPITTECH` (p.4), and `LAURUSLABS` (p.2). Re-appointments (`DIXON`, `BAJFINANCE`) are tagged and demoted below new KMP appointments. In the UI modal, **Person Diligence** parses only filing-stated career lines and generates "worth asking" prompts strictly from keywords present in the filing PDF.

---

## 4. Primary-Source Pull Engine & Code-Enforced Verdicts

FINN's Pull workflow (`finn/pull/{chunker,doctype,verifier,prompts,builder}.py`) fetches exclusively primary Annual Reports (up to 520 pages, extracted in `<0.6s` via Apache/BSD `pypdfium2`) and the last 4 Concall Transcripts from Screener. A deterministic doc-type verifier (`doctype.py`) rejects non-transcripts (requiring ≥15 speaker turns, ≥3 speakers, and Q&A cues) and marks the most recent call untestable (`"Untestable (Latest Call)"`).

Rather than asking an LLM to score management track records, FINN enforces strict separation in code:
1. **Extraction & Validation:** The bulk model extracts forward guidance claims `{metric, scope, condition, unit, fiscal_period, quote, page, doc_id}`. Before any claim survives, code (a) trims quotes to the single sentence carrying the guidance, (b) verifies `rapidfuzz.partial_ratio >= 90.0%` plus presence of every numeric token on the cited page, (c) drops quotes lacking an explicit unit or metric, and (d) rejects scope mismatches (e.g., `"Consolidated Revenue"` tagged as `segment`).
2. **Deterministic Verdicts:** Only unconditional, company-level targets whose fiscal quarters are fully filed receive scored verdicts (`Delivered`, `Missed`, `Moved goalposts`). Segment/product targets map to fixed-template `"Not comparable to filed numbers"`, conditional targets map to `"Conditional, not scored"`, and partial fiscal periods display progress (`"2 of 4 quarters filed; H1 = 66.7% of ₹56,000 Cr target"`) with zero LLM calls.
3. **Stated vs Filed & Citation-Gated Synthesis:** Past-quarter figures stated on calls (`"stated vs filed"`) are normalised (`million`/`billion` → `₹ Cr`) and checked against Screener actuals. Strong-tier synthesis (`Numbers vs Narrative`, 3 Bull, 3 Bear) must terminate every sentence with a resolvable verified `[C<id>]` ID; uncited sentences are dropped automatically.

Pull analysis is unhidden for the completed dossiers (`DIXON`, `POLYCAB`, `HDFCBANK`, plus end-to-end generalisation ticker `KAYNES`) alongside Screener Balance Sheet panels (`borrowings`, `D/E`, `working capital days`, or `CAR/GNPA/NNPA` for lenders) and verified AR Segment Mix. `NAVINFLUOR`, `SYRMA`, and `TITAN` remain deterministic-extracts only with `"Deterministic extracts only; analysis not generated."`.

---

## 5. Private Network Privacy Guarantee & Honesty Rules

A dedicated test suite guarantees that zero private contact data from `contacts.json` (64 realistic synthetic contacts, 24 `contact_links` edges) ever touches an LLM (`assert_no_private_network_data` executes before cache lookup, confirmed empty across `llm_cache.json` and `llm_ledger.jsonl`). All network paths, 2nd-degree bridges, reconnect nudges, and **Expertise Map** rankings (`strength × recency × tag match`) are 100% local deterministic graph operations:
- Overlap claims with real appointees use prior-employer (`kind="work"`) tenure dates only when printed in the filing (`KPITTECH` Cummins `2004–2017`); otherwise they emit `"tenure not stated in filing"` (`HDFCBANK` ICICI Bank, `LAURUSLABS` Cohance), excluding college alumni (`PSG College`) from prior-employer claims.
- Re-appointments and cards without appointee overlap show at most one `"knows the company"` hook (strongest × most recent).
- Any 1st- or 2nd-degree contact untouched for >12 months (`>365` days) is flagged `"stale tie"`. Every synthetic link displays `"inferred from employer/tenure overlap, synthetic network"`.

---

## 6. Deployment Architecture, Ledger Transparency & Known Boundaries

FINN deploys as a single Vercel project (`https://finn-bay.vercel.app`) via Vercel Services uniting Next.js 16 and Python FastAPI with atomic snapshot fallback if Neon Postgres is cold or unconfigured. Pipeline-heavy dependencies (`bs4`, `pdfplumber`) are excluded from the FastAPI runtime bundle and verified absent on cold start. A v4 Service Worker (`sw.js`) applies Network-First caching for HTML and full-URL `/api/v1/*` responses while pre-warming the Brief and dossiers for offline inspection.

All 71 LLM invocations across classification and Pull (`44` live, `27` cache hits; `831,135` in / `84,813` out / `16,073` thinking tokens; `$0.101357` paid-equivalent / `₹8.7167`, `₹0.00` free-tier spend) reconcile line-for-line between `llm_ledger.jsonl`, `/cost`, and per-dossier footers. Deliberate non-goals include multi-user auth, intraday feeds, real web push/VAPID delivery (alerts are an in-app demo-clock digest only), broker notes/news, and user-labelled ground-truth evaluation (0/40 manually labelled so far in `real_announcements_40_to_label.json`).
