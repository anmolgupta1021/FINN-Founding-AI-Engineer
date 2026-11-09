-- FINN Neon Postgres schema (idempotent; owner-scoped for network tables).
-- Every read path in `apps/api/finn/store.py` falls back to committed JSON snapshots if Neon is unconfigured or unreachable.

CREATE TABLE IF NOT EXISTS companies (
    symbol        TEXT PRIMARY KEY,
    bse_code      TEXT,
    isin          TEXT,
    name          TEXT NOT NULL,
    sector        TEXT NOT NULL,
    mcap_bucket   TEXT NOT NULL,
    in_portfolio  BOOLEAN NOT NULL DEFAULT TRUE,
    research_why  TEXT
);

CREATE TABLE IF NOT EXISTS company_links (
    src_symbol    TEXT NOT NULL REFERENCES companies(symbol) ON DELETE CASCADE,
    dst_symbol    TEXT NOT NULL REFERENCES companies(symbol) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    note          TEXT,
    PRIMARY KEY (src_symbol, dst_symbol, kind)
);

CREATE TABLE IF NOT EXISTS prices_eod (
    symbol           TEXT PRIMARY KEY REFERENCES companies(symbol) ON DELETE CASCADE,
    yahoo_ticker     TEXT NOT NULL,
    as_of            DATE NOT NULL,
    close            NUMERIC(12, 2) NOT NULL,
    prev_close       NUMERIC(12, 2) NOT NULL,
    change_pct       NUMERIC(8, 2) NOT NULL,
    volume           BIGINT NOT NULL,
    avg_volume_20d   BIGINT NOT NULL,
    volume_multiple  NUMERIC(8, 2) NOT NULL,
    high_20d         NUMERIC(12, 2) NOT NULL,
    low_20d          NUMERIC(12, 2) NOT NULL,
    sparkline_json   JSONB NOT NULL,
    bars_json        JSONB NOT NULL,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS announcements (
    id               TEXT PRIMARY KEY,
    symbol           TEXT NOT NULL REFERENCES companies(symbol) ON DELETE CASCADE,
    source           TEXT NOT NULL DEFAULT 'nse' CHECK (source IN ('nse', 'bse')),
    exchange         TEXT NOT NULL,
    ts               TIMESTAMPTZ NOT NULL,
    raw_category     TEXT,
    subject          TEXT NOT NULL,
    pdf_url          TEXT,
    category         TEXT NOT NULL,
    cls_method       TEXT NOT NULL,
    cls_rule         TEXT,
    priority         INTEGER NOT NULL,
    summary_1l       TEXT NOT NULL,
    is_demo_scenario BOOLEAN NOT NULL DEFAULT FALSE,
    details_json     JSONB
);

CREATE INDEX IF NOT EXISTS idx_announcements_ts_prio ON announcements (ts DESC, priority DESC);
CREATE INDEX IF NOT EXISTS idx_announcements_symbol ON announcements (symbol);

-- Separate table for any synthetic DEMO scenario items (never mixed into real `announcements`)
CREATE TABLE IF NOT EXISTS demo_announcements (
    id               TEXT PRIMARY KEY,
    symbol           TEXT NOT NULL REFERENCES companies(symbol) ON DELETE CASCADE,
    source           TEXT NOT NULL DEFAULT 'demo' CHECK (source = 'demo'),
    exchange         TEXT NOT NULL DEFAULT 'DEMO',
    ts               TIMESTAMPTZ NOT NULL,
    raw_category     TEXT,
    subject          TEXT NOT NULL,
    pdf_url          TEXT,
    category         TEXT NOT NULL,
    cls_method       TEXT NOT NULL,
    cls_rule         TEXT,
    priority         INTEGER NOT NULL,
    summary_1l       TEXT NOT NULL,
    is_demo_scenario BOOLEAN NOT NULL DEFAULT TRUE,
    details_json     JSONB
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id               BIGSERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    task             TEXT NOT NULL,
    tier             TEXT NOT NULL,
    model            TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    cache_key        TEXT NOT NULL,
    cache_hit        BOOLEAN NOT NULL,
    in_tokens        INTEGER NOT NULL,
    out_tokens       INTEGER NOT NULL,
    thinking_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd         NUMERIC(10, 6) NOT NULL,
    cost_inr         NUMERIC(10, 4) NOT NULL,
    latency_ms       INTEGER NOT NULL
);

-- Private investor network (owner-scoped; never sent to any LLM — DECISIONS D-008)
CREATE TABLE IF NOT EXISTS contacts (
    id               TEXT PRIMARY KEY,
    owner_id         TEXT NOT NULL DEFAULT 'investor:meera_iyer',
    name             TEXT NOT NULL,
    headline         TEXT NOT NULL,
    city             TEXT,
    strength         INTEGER NOT NULL CHECK (strength BETWEEN 1 AND 5),
    last_contacted   DATE,
    expertise_tags   JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes_enc        TEXT,
    affiliations_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS contact_links (
    src_contact_id   TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    dst_contact_id   TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    kind             TEXT NOT NULL,
    overlap_org      TEXT,
    overlap_years    TEXT,
    strength         INTEGER NOT NULL DEFAULT 4 CHECK (strength BETWEEN 1 AND 5),
    note             TEXT,
    PRIMARY KEY (src_contact_id, dst_contact_id, kind)
);
