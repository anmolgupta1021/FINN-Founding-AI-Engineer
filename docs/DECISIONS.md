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

---

## Deliberately left out (running list)
- Auth / multi-user. Single demo investor; the schema is owner-scoped and RLS-ready.
- Intraday data. EOD only, per the brief.
- News, broker notes, research reports. Excluded from Pull by the brief.
- Voice, a native app, real LinkedIn data, embeddings.
- Web push notifications. Stretch goal only (iOS requires an installed PWA).
