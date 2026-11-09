"""Apply apps/api/finn/schema.sql and seed Neon Postgres from the committed JSON snapshots.
If DATABASE_URL is not set, prints a clear status message and verifies the snapshot read paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from finn.store import get_announcements, get_freshness_overview, get_portfolio, get_prices

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
DATA_DIR = API_DIR / "data"
SCHEMA_SQL = API_DIR / "finn" / "schema.sql"


def main() -> None:
    for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
        if p.exists():
            load_dotenv(p, override=False)

    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        print("DATABASE_URL is not set — verifying snapshot fallback read paths:")
        pf = get_portfolio(DATA_DIR)
        pr = get_prices(DATA_DIR)
        an = get_announcements(DATA_DIR)
        fr = get_freshness_overview(DATA_DIR)
        print(f"  portfolio     -> source={pf['source']} holdings={len(pf['companies'])} research={len(pf.get('research', []))}")
        print(f"  prices        -> source={pr['source']} count={pr.get('count', 0)} as_of={pr.get('as_of')}")
        print(f"  announcements -> source={an['source']} total={an['total']} (material={an['material_count']}, routine={an['routine_count']})")
        print(f"  freshness     -> {fr['prices']['chip']} | {fr['announcements']['chip']}")
        return

    import psycopg

    portfolio = json.loads((DATA_DIR / "seed" / "portfolio.json").read_text())
    links = json.loads((DATA_DIR / "seed" / "company_links.json").read_text())["links"]
    contacts = json.loads((DATA_DIR / "seed" / "network" / "contacts.json").read_text())["contacts"]
    prices_snap = json.loads((DATA_DIR / "snapshots" / "prices" / "eod_prices.json").read_text())
    ann_snap = json.loads((DATA_DIR / "snapshots" / "announcements" / "announcements.json").read_text())

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

            for c in portfolio["companies"]:
                cur.execute(
                    """
                    INSERT INTO companies (symbol, bse_code, isin, name, sector, mcap_bucket, in_portfolio, research_why)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE, NULL)
                    ON CONFLICT (symbol) DO UPDATE SET
                      bse_code = EXCLUDED.bse_code,
                      isin = EXCLUDED.isin,
                      name = EXCLUDED.name,
                      sector = EXCLUDED.sector,
                      mcap_bucket = EXCLUDED.mcap_bucket,
                      in_portfolio = TRUE
                    """,
                    (c["symbol"], c.get("bse_code"), c.get("isin"), c["name"], c["sector"], c["mcap"]),
                )

            for r in portfolio.get("research", []):
                cur.execute(
                    """
                    INSERT INTO companies (symbol, bse_code, isin, name, sector, mcap_bucket, in_portfolio, research_why)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                      bse_code = EXCLUDED.bse_code,
                      isin = EXCLUDED.isin,
                      name = EXCLUDED.name,
                      sector = EXCLUDED.sector,
                      mcap_bucket = EXCLUDED.mcap_bucket,
                      in_portfolio = EXCLUDED.in_portfolio,
                      research_why = EXCLUDED.research_why
                    """,
                    (
                        r["symbol"],
                        r.get("bse_code"),
                        r.get("isin"),
                        r["name"],
                        r["sector"],
                        r["mcap"],
                        bool(r.get("in_portfolio", False)),
                        r.get("why"),
                    ),
                )

            for lk in links:
                cur.execute(
                    """
                    INSERT INTO company_links (src_symbol, dst_symbol, kind, note)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (src_symbol, dst_symbol, kind) DO UPDATE SET note = EXCLUDED.note
                    """,
                    (lk["src"], lk["dst"], lk["kind"], lk.get("note")),
                )

            for sym, p in prices_snap.get("prices", {}).items():
                cur.execute(
                    """
                    INSERT INTO prices_eod (
                      symbol, yahoo_ticker, as_of, close, prev_close, change_pct,
                      volume, avg_volume_20d, volume_multiple, high_20d, low_20d,
                      sparkline_json, bars_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (symbol) DO UPDATE SET
                      as_of = EXCLUDED.as_of,
                      close = EXCLUDED.close,
                      prev_close = EXCLUDED.prev_close,
                      change_pct = EXCLUDED.change_pct,
                      volume = EXCLUDED.volume,
                      avg_volume_20d = EXCLUDED.avg_volume_20d,
                      volume_multiple = EXCLUDED.volume_multiple,
                      high_20d = EXCLUDED.high_20d,
                      low_20d = EXCLUDED.low_20d,
                      sparkline_json = EXCLUDED.sparkline_json,
                      bars_json = EXCLUDED.bars_json,
                      fetched_at = NOW()
                    """,
                    (
                        sym,
                        p["yahoo_ticker"],
                        p["as_of"],
                        p["close"],
                        p["prev_close"],
                        p["change_pct"],
                        p["volume"],
                        p["avg_volume_20d"],
                        p["volume_multiple"],
                        p["high_20d"],
                        p["low_20d"],
                        json.dumps(p["sparkline_20d"]),
                        json.dumps(p["bars"]),
                    ),
                )

            for a in ann_snap.get("items", []):
                cur.execute(
                    """
                    INSERT INTO announcements (
                      id, symbol, exchange, ts, raw_category, subject, pdf_url,
                      category, cls_method, cls_rule, priority, summary_1l,
                      is_demo_scenario, details_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                      category = EXCLUDED.category,
                      cls_method = EXCLUDED.cls_method,
                      priority = EXCLUDED.priority,
                      summary_1l = EXCLUDED.summary_1l,
                      details_json = EXCLUDED.details_json
                    """,
                    (
                        a["id"],
                        a["symbol"],
                        a["exchange"],
                        a["ts"],
                        a.get("raw_category"),
                        a["subject"],
                        a.get("pdf_url"),
                        a["category"],
                        a["cls_method"],
                        a.get("cls_rule"),
                        a["priority"],
                        a["summary_1l"],
                        bool(a.get("is_demo_scenario", False)),
                        json.dumps(a.get("details") or {}),
                    ),
                )

            for ct in contacts:
                cur.execute(
                    """
                    INSERT INTO contacts (
                      id, name, headline, city, strength, last_contacted,
                      expertise_tags, notes_enc, affiliations_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                      headline = EXCLUDED.headline,
                      strength = EXCLUDED.strength,
                      last_contacted = EXCLUDED.last_contacted,
                      expertise_tags = EXCLUDED.expertise_tags,
                      notes_enc = EXCLUDED.notes_enc,
                      affiliations_json = EXCLUDED.affiliations_json
                    """,
                    (
                        ct["id"],
                        ct["name"],
                        ct["headline"],
                        ct.get("city"),
                        ct["strength"],
                        ct.get("last_contacted"),
                        json.dumps(ct.get("expertise_tags", [])),
                        ct.get("notes"),
                        json.dumps(ct.get("affiliations", [])),
                    ),
                )
        conn.commit()
    print("Neon schema applied and seeded successfully.")


if __name__ == "__main__":
    main()
