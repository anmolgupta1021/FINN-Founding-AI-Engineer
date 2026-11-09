# FINN — 3-minute demo script

> **Rule:** every feature we build must earn a line in this script. If it isn't here, it's a stretch goal.
> Device: phone (PWA installed to home screen) or a 390×844 browser viewport.
> Persona: **Meera Iyer**, PM at a lean long-only fund. 18 holdings. ~70 people in her network (synthetic).

Timings are cumulative. **[S#]** = screen. Lines in *italics* = what the presenter says.

---

## 0:00 – 0:20 · Open the app → **[S1] The Brief**

- Opens straight onto **The Brief** for `Last 24h` (default window). No login, no splash.
- Top line: date, freshness chips → `Prices · EOD 13 Nov` `Filings · Live 08:12` (or `Snapshot 13 Nov` — shown honestly in amber ink).
- Below: **3–5 ranked items** in large serif headlines; then a single collapsed line:
  `+ 23 routine filings across 11 companies (ESOP, compliance, newspaper ads…)`.
- *"Meera has 18 holdings and 40-odd filings overnight. FINN shows her the four that matter and buries the rest — but never hides them."*
- **Manual Verification Checklist — Scrubber Presets:** Tap each preset in the window scrubber:
  - Tap `24h` → displays `24h · 9 material · 15 routine`
  - Tap `3d` → displays `3d · 30 material · 50 routine`
  - Tap `7d` → displays `7d · 43 material · 105 routine`
  - Tap `14d` → displays `14d · 128 material · 243 routine`
  - Notice active counts in the header and loading indicator `(loading...)` while fetching. Tap back to `24h`.

## 0:20 – 0:55 · Management change → **[S2] Event: KMP / SMP / Board appointment**

- Top item in the `24h` frozen window (`2026-11-06`): **"HDFC Bank Limited — Change in Management (Mr. V. N. Srivatsan)"** (or in `14d`: **"KPIT Technologies — Appointment of Mr. Anant Talaulicar as Lead Independent Director"** / **"Laurus Labs — Appointment of Mr. Kundan Kumar Jha"**) — all 100% real NSE filings.
- Event screen shows, in order:
  1. One-line *what happened*, direct NSE PDF link + page cite + SHA-256 hash.
  2. **Who they are** — verbatim SEBI LODR "brief profile" extracted directly from the filing PDF (e.g., `HDFCBANK` p.3 of 3: ~34 years experience, 25 years in BFSI, ex-Head – Compliance: Overseas Banking & Data Privacy Officer at **ICICI Bank Limited**, MBA from **PSG College of Technology**; `KPITTECH` p.4 of 8: ex-Chairman & MD of **Cummins Group in India** 2004–2017, M.S. **University of Michigan**; `LAURUSLABS` p.2 of 2: ex-CS & Head of Legal at **Cohance Lifesciences** and **Dr. Reddy's Laboratories**).
  3. **Who to call** — `You → <Contact> (strong · spoke 5 wks ago) → overlapped at <prior employer>`.
     Label directly under the path: *"inferred from employer/tenure overlap, synthetic network"*.
  4. Tap → "Why this person" (3 bullet reasons) + a drafted 2-line opener (deterministic template, no LLM sees the network).
- *"FINN doesn't stop at 'Change in Senior Management'. It pulls who this person is verbatim from page 3 of the NSE PDF, and shows who in Meera's network overlapped with them."*

## 0:55 – 1:20 · Results → **[S3] Event: Quarterly results card**

- Back → second item: **"Polycab Q2 FY27 results"**.
- Compact table: `Revenue / EBITDA / PBT / PAT` × `This Q / QoQ % / YoY %`, tabular numerals.
- Each row has a page cite (`Results p.3`). EBITDA marked `derived` with a tooltip of the formula.
- A **cross-check column** against screener.in: ✓ match, or an amber `Δ 2.1% vs screener` flag — *surfaced, not hidden*.
- *"First cut of the numbers, straight from the results PDF, cross-checked, and honest when two sources disagree."*

## 1:20 – 1:40 · Triggered alert + reconnect nudge (still **[S1]**)

- Alert strip at top of Brief: `IEX · Volume 3.1× 20-day avg · Close −6.4%` — threshold chip shows `your rule: ≥2× vol, ±5%`.
- Tap the rule chip → **[S4] Alert rules** sheet: two sliders + category toggles. Change `±5%` → `±3%`. Close.
- Low in the Brief: **Reconnect** line — *"You haven't spoken to Arjun Mehta in 14 months. His ex-employer Aarti Industries just announced a ₹X cr capex plan."* Tap → person card.
- *"Meera decides what 'unusual' means. And FINN quietly turns news into reasons to stay in touch."*

## 1:40 – 2:35 · Pull → **[S5] Company dossier**

- Tap the command bar → type `SYRMA` (not in portfolio) → **[S5] Dossier: Syrma SGS** (precomputed + committed).
- Header: `Built from FY25 Annual Report + 4 concall transcripts · 98 quotes verified · deterministic primary-source extraction`.
- Section order (scroll):
  1. **Promised vs Delivered** (hero) — last 4 quarters. Each row: guidance quote (speaker, quarter, page) → what was reported → verdict chip `Delivered / Missed / Goalposts moved / Not found in filings`.
  2. **Trajectory** — 5-yr sparklines: revenue, EBITDA margin, PAT, CFO/PAT.
  3. **Business** — segment mix bar, cited.
  4. **Bull / Bear** — 3 points each; every sentence ends in a tappable cite chip. Tap one → **[S6] Source sheet** showing the verbatim quote highlighted in its page context.
  5. **Who to call** — `Ex-Syrma: 0 · Competitors (Dixon, Kaynes): 2 · Customers: 1` → top suggestion with reason.
- *"Pull only reads what the company itself filed. Every sentence is a verified quote. If the filings don't say it, FINN says 'not found in filings' — it doesn't make it up."*

## 2:35 – 2:50 · Any ticker → **[S7] Build in progress**

- Command bar → type a ticker we didn't pick (e.g. one the grader suggests) → `Build dossier`.
- Progress view polling job rows: `Finding filings on screener ✓ · Downloading FY25 AR (6.2 MB) ✓ · Reading p. 118/344 … · Extracting claims · Verifying quotes`.
- *"It isn't hard-wired. Any NSE ticker — it runs as a background job, so nothing times out. We'll come back to it."*

## 2:50 – 3:00 · Network, asked directly → **[S8] Ask**

- Command bar → `who knows specialty chemicals` → ranked people with expertise tags, last-contacted, strength; one line each on *why*.
- Close on the footer: `Today's LLM spend: ₹0.00 (all cached)`.
- *"Push, Pull and her own network — in one place, on her phone. That's FINN."*

---

## Screens inventory (build list)

| # | Screen | Phase |
|---|---|---|
| S1 | The Brief (window scrubber, ranked items, collapsed routine, alert strip, reconnect line, freshness chips) | P2/P3 |
| S2 | Event: management change (filing bio + Who to call + synthetic/inferred label) | P2/P3 |
| S3 | Event: results card (QoQ/YoY + page cites + screener cross-check) | P2 |
| S4 | Alert rules sheet | P2 |
| S5 | Company dossier (Promised vs Delivered hero) | P4 |
| S6 | Source sheet (verbatim quote in page context) | P4 |
| S7 | Build-in-progress (job polling) | P4 |
| S8 | Ask results (network query) + person card | P3/P5 |

## Backup plan & Verification Status during a live demo
- **Offline Drill:** Service worker (`sw.js`) caches shell and snapshot API responses. Interactive simulation with Chrome DevTools offline mode is marked **unverified** until tested in a live browser window.
- **Git Repository:** Local git repository only; no remote is configured (`git remote -v` is empty).
- Network dies → every screen reads committed snapshots; freshness chips flip to `Snapshot`. Nothing else changes.
- Live build of an unknown ticker slow/blocked → show the pre-built 4th dossier; explain the job model.
