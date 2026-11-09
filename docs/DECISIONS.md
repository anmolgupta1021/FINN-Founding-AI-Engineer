# Decisions log

Format: **D-NNN · date · decision** — *why* — tradeoff / what we gave up. Newest at the bottom.
This file feeds the final writeup.

---

### D-001 · 9 Nov · Interaction model: "The Brief" (ranked feed → dossiers → command bar)
*Why:* an investor's day is triage → interrupts → deep dives. A ranked, time-windowed brief fits triage; dossiers fit deep dives; a command bar replaces a chat box with structured answers.
*Rejected:* chat-first copilot (blank page, slow, hard to scan or cite); tabbed dashboard (Network becomes a bolted-on tab, which the brief explicitly warns against).

### D-002 · 9 Nov · Hosting: Next.js + FastAPI as one Vercel project via Vercel Services (beta), 1-hour time-box
*Why:* free-tier Render/HF sleep, so a 30–60 s cold start hits graders on first open. Vercel runs Python on Fluid Compute with a 300 s default timeout, and atomic deploys keep frontend and API in sync.
*Fallback:* if Services isn't working within 1 hour in P0, use two separate Vercel projects (web + api). Same code.

### D-003 · 9 Nov · Local-first data fetching; live fetch is best-effort only
*Why:* NSE/BSE commonly block datacenter and GitHub Actions IPs. `scripts/build_snapshots.py` runs on the developer's machine (residential IP) and commits JSON snapshots. Every fetcher detects empty, blocked or HTML-challenge responses and **falls back loudly**; the UI freshness chip says `Snapshot`.
*Tradeoff:* data is only as fresh as the last local run. That is acceptable for a demo, and we're honest about it in the UI.

### D-004 · 9 Nov · Neon Postgres, with committed JSON snapshots as the fallback on every read path
*Why:* Supabase pauses free projects after 7 days idle and graders may arrive later; Neon scales to zero and wakes in about a second. Every read goes Neon → snapshot JSON, so the app works even with no DB at all.

### D-005 · 9 Nov · No embeddings or vector DB (initially)
*Why:* filings are structured. Section-targeted extraction (MD&A, segment notes, financial statements, concall Q&A turns) plus Postgres full-text search is cheaper and easier to explain. We'll revisit if retrieval misses things.

### D-006 · 9 Nov · Pull jobs never run inside a request
*Why:* ingesting an AR (300+ pages) plus 4 transcripts takes minutes. The API enqueues a job (GitHub Actions `workflow_dispatch`, or a background worker with `waitUntil`; decided in P4), the worker writes progress rows to the DB, and the UI polls. The 4 demo dossiers are precomputed and committed.

### D-007 · 9 Nov · Citations are enforced in code, not just in the prompt
*Why:* the extraction model must return a verbatim quote plus a page for every claim. A verifier fuzzy-matches the quote against the stored page text (rapidfuzz partial ratio ≥ 90), and failures are dropped and logged. The reasoning model may only reference verified claim IDs, and sentences without a resolvable cite are removed before rendering. Empty fields render "not found in filings".

### D-008 · 9 Nov · Private network data never goes to an LLM
*Why:* on Gemini's free tier, Google may use prompts and responses to improve its products. Network ranking, path-finding and "why this person" text are deterministic SQL/graph code plus templates. The LLM sees only public filings, plus the investor's own query text for intent parsing.
*Real deployment:* a paid zero-retention endpoint would let us relax this, with care.

### D-009 · 9 Nov · Network = realistic **synthetic** people; real people only from filings
*Why:* scraping LinkedIn would breach its terms. The ~70 contacts are fictional. Real people named in filings (e.g. an incoming CFO) get **no fabricated bio**; their profile comes only from the filing's mandated "brief profile". Links between a synthetic contact and a real person are **inferred** from employer/tenure overlap and labelled in the UI: *"inferred from employer/tenure overlap, synthetic network"*.
*Real deployment:* consented contact import (OAuth), user-supplied LinkedIn data exports, licensed people-data providers under a DPA, CRM sync. Owner-scoped, with retention TTLs and deletion.

### D-010 · 9 Nov · Results card is cross-checked against screener.in quarterly figures
*Why:* the extracted Revenue/EBITDA/PBT/PAT come from the results PDF (with page cites). Screener figures are used **only as a check**, and a mismatch is surfaced as `Δ x% vs screener`, never hidden. EBITDA is often not printed; when derived (PBT + finance cost + D&A − other income) it is labelled `derived`.

### D-011 · 9 Nov · LLM routing: model names come from env and are verified live before wiring
*Why:* model names and free-tier limits change often, and Google now shows per-project limits in AI Studio rather than in a public table. Defaults: **bulk = a Flash-Lite model, strong = a Flash model with thinking enabled** (not Pro: Pro is not on the free tier). `scripts/check_models.py` (P1) calls `models.list` with the real key and does a 1-token ping per configured model before anything else runs.
*Design for low limits:* assume roughly 10 RPM and a few hundred RPD. Batch classification (~20 announcements per call), apply rules first, cache by content hash, precompute dossiers locally.

### D-012 · 9 Nov · PDF stack: pypdfium2 (text) + pdfplumber (tables), not PyMuPDF
*Why:* PyMuPDF is AGPL. pypdfium2 (Apache/BSD) is fast for page text; pdfplumber (MIT) handles results tables and runs in the local pipeline only.

### D-013 · 9 Nov · Lean deploy bundle: pipeline deps are kept out of the Vercel function
*Why:* yfinance, pandas, pdfplumber and bs4 live in a `pipeline` dependency group used locally and in CI. The deployed API carries only FastAPI, psycopg, httpx, google-genai, rapidfuzz and pypdfium2. That means faster cold starts and a smaller attack surface.

### D-014 · 9 Nov · Live ticker validation caught `JBCHEPHARM` delisting → swapped to `LAURUSLABS`
*Why:* live `yfinance` validation across all 22 NSE tickers succeeded on 21/22 (`as_of: 2026-11-09`) and flagged `$JBCHEPHARM.NS` / `.BO` as delisted (merged into Torrent Pharma). Swapped the 4th outside-portfolio research company to `LAURUSLABS` (Laurus Labs, BSE `540222`, API/CDMO peer to `SUNPHARMA` and `PIIND`). All 22/22 symbols now validate cleanly.

### D-015 · 9 Nov · NSE & BSE block standard `httpx` (HTTP 403), but succeed with Chrome TLS impersonation (`curl_cffi`)
*Why:* probing `www.nseindia.com/api/corporate-announcements` and `api.bseindia.com` with standard Python `httpx` returned HTTP 403 (Akamai / Cloudflare TLS JA3 fingerprint rejection). Switching both fetchers (`finn/fetchers/nse.py` and `bse.py`) to `curl_cffi.requests.Session(impersonate="chrome")` unlocked live responses (`HTTP 200`) across all 22 symbols (`407` live NSE announcements + `440` live BSE announcements over a 45-day window, deduplicated to `776` real exchange filings with resolvable PDF URLs).
*Tradeoff:* datacenter IPs (Vercel / GitHub Actions) can still be IP-blocked by Akamai even with Chrome TLS impersonation, so `scripts/build_snapshots.py` runs locally, records `exchange_probe.json`, and commits `announcements.json`.

### D-016 · 9 Nov · Provenance separation & uniform-random 40-item classifier benchmark
*Why:* every announcement in `announcements.json` now carries an explicit `source` (`"nse"` | `"bse"` | `"demo"`), and all 776 items in `announcements.json` are 100% real NSE/BSE filings (`359` NSE, `417` BSE, `0` demo, `776/776` with resolvable `.pdf` URLs). Replaced the earlier stratified sample with a strict uniform random sample without replacement (`random.Random(42).sample` across all 776 sorted filings) in `data/eval/real_announcements_40_to_label.json` (with zero post-hoc changes to `classify.py`). Stage-1 positive category rules match `13/40 (32.5%)`, Stage-1 explicit noise rule matches `3/40 (7.5%)`, and the remaining `24/40 (60.0%)` fall-through `unclassified` items (`cls_method == "fallback"`) are routed to Stage 2 LLM and are explicitly **not** counted as rule hits.

### D-017 · 9 Nov · Live PDF extractors (`mgmt.py` & `results.py`) + Screener.in cross-check
*Why:* hand-entered numbers and authored bios are disallowed. `finn/pipeline/mgmt.py` downloads actual NSE/BSE filing PDFs (with automatic BSE `AttachLive` → `AttachHis` archival fallback) and extracts the verbatim SEBI LODR "brief profile" paragraph, page number, and SHA-256 hash across 11 real management-change filings (`HDFCBANK` p.3, `ASIANPAINT` p.1, `KPITTECH` p.4, `LAURUSLABS` p.2, `BAJFINANCE` p.2, `DIXON` p.2, `SUNPHARMA` p.2, `TRENT` p.2). `finn/pipeline/results.py` extracts Consolidated Financial Results tables from `POLYCAB` (p.4 of 14, converting `₹ million ÷ 10 → ₹ cr`) and `BAJFINANCE` (p.14 of 48) and cross-checks them live against `screener.in`.

### D-018 · 9 Nov · Completed-session EOD price bars + visible Demo Clock
*Why:* fetching `yfinance` during Indian market hours (09:15–15:30 IST) returns a partial intraday bar as the latest row, distorting 1-day return and 20-day volume multiples. `finn/fetchers/prices.py` strips today's bar if fetched before `15:45 IST`, ensuring `as_of` (`2026-11-06`) is always a completed session. Added a visible `demo_clock` (`as_of` parameter defaulting to the frozen snapshot timestamp) so the `24h` digest window works deterministically on snapshot data while allowing users to switch windows or dates.

### D-019 · 9 Nov · Sector-aware Results Card (NII/PPOP for lenders, derived EBITDA plausibility check for non-financials)
*Why:* `EBITDA` is not a meaningful metric for banks, NBFCs, or financial intermediaries (`HDFCBANK`, `BAJFINANCE`, `CREDITACC`, `CAMS`) because interest expense is their operating cost of funds. For lenders (`LENDER_SYMBOLS`), `results.py` omits `EBITDA`, displays the explicit banner `"EBITDA not meaningful for lenders"`, and extracts `NII` (`Interest Income − Finance Cost`), `PPOP` (`PBT + Impairment on financial instruments`), `PBT`, and `PAT` (`BAJFINANCE` Q2 FY27 p.14: `NII ₹13,334.66 cr`, `PPOP ₹10,703.29 cr`, `PBT ₹8,537.20 cr`, `PAT ₹6,366.57 cr`). For non-financials (`POLYCAB`), `EBITDA` (`₹1,422.49 cr`, `14.4%` margin) is always marked `"derived"` (never `"verified"` or `"✓ Match"`), and `check_ebitda_plausibility` verifies that `2.0% <= margin_pct <= 55.0%` or marks the row `"unreliable"`.

### D-020 · 9 Nov · Live Pull Spike on `DIXON` (520-page AR + 4 Concall Transcripts)
*Why:* before building Phase 4 (Pull), we spiked live fetching and `pypdfium2` text extraction on `DIXON` via `screener.in/company/DIXON/consolidated/` (`scripts/spike_pull_dixon.py`). All 5 documents resolved, downloaded (`545–892 ms`), and extracted cleanly (`100%` text-extractable PDFs):
- Annual Report FY26 (`14.77 MB`, `520 pages`, `516/520` non-empty text pages, `1,446,093` chars, extracted in `596 ms`).
- 4 Concall Transcripts (`Nov 2026` 24pp / `64.1k` chars; `Aug 2026` 21pp / `58.1k` chars; `May 2026` 21pp / `54.3k` chars; `Feb 2026` 21pp / `57.2k` chars; extracted in `23–38 ms` each).
*Architectural implication:* a 520-page AR is `1.45M` chars (~360k tokens), which would blow free-tier token quotas if sent whole. Because `pypdfium2` extracts all 520 pages in `0.6 s`, our P4 pipeline will filter the AR to high-signal sections (MD&A, Chairman/MD message, segment notes, financial statements ~30–40 pages) alongside the 4 concall transcripts (~58k chars each).

### D-021 · 9 Nov · 64-contact Synthetic Network + 24-edge `contact_links` Graph (1st & 2nd Degree)
*Why:* expanded `contacts.json` to `64` synthetic contacts and added `contact_links.json` (`24` contact-to-contact edges across shared employers and alma maters) covering all 22 companies, ecosystem competitors/suppliers/customers (`ICICI Bank`, `Cummins`, `Cohance`, `Dr. Reddy's`, `UTI AMC`, `Bosch`, `KEI`, `SRF`, `Spandana`, `Divi's`), and 10 education clusters. Planted 6 "aha" moments firing on real filings in the frozen window (including both 1st-degree and 2nd-degree warm-intro paths: `You → Bridge Contact → Target Contact`), exposed via Push cards and `GET /api/v1/network/ask` (`[S8]`). Every match carries `"inferred from employer/tenure overlap, synthetic network"` and zero network data touches an LLM.

### D-022 · 9 Nov · Live Gemini model verification caught `gemini-2.5-*` deprecation → wired router to `gemini-3.5-flash-lite` (bulk) & `gemini-3.6-flash` (strong)
*Why:* running `scripts/check_models.py` live against the Gemini Developer API revealed that `gemini-2.5-flash-lite` and `gemini-2.5-flash` return `404 NOT_FOUND` (`"no longer available to new users"`), while 18 models including `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.7-flash`, and `gemini-3.8-flash` are available. Wired `bulk_model = "gemini-3.5-flash-lite"` (`1,199 ms` ping) and `strong_model = "gemini-3.6-flash"` (`2,324 ms` ping with thinking) in `verified_models.json` and `finn/llm/router.py` (with automatic fallback to `gemini-3.1-flash-lite` / `gemini-3.5-flash` on transient `503` spikes). Ran Stage-2 `gemini-3.5-flash-lite` across the 24 unresolved announcements in `real_announcements_40_to_label.json` (`2` calls, `2,115` in / `1,705` out tokens, `₹0.0768` counterfactual cost, `₹0.00` free-tier spend) and across the 52 recent unresolved announcements (`Nov 4–6, 2026`, `3` calls, `4,279` in / `3,221` out tokens, `₹0.1476` counterfactual cost, `₹0.00` free-tier spend).

---

## Deliberately left out (running list)
- Auth / multi-user. Single demo investor; the schema is owner-scoped and RLS-ready.
- Intraday data. EOD only, per the brief.
- News, broker notes, research reports. Excluded from Pull by the brief.
- Voice, a native app, real LinkedIn data, embeddings.
- Web push notifications. Stretch goal only (iOS requires an installed PWA).
