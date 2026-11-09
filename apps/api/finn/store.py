"""Unified read store: Neon Postgres first (when `DATABASE_URL` is configured),
committed JSON snapshots under `apps/api/data/snapshots/` as the guaranteed fallback.

Every response includes explicit freshness metadata so the UI chip is always honest.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from finn.fetchers.prices import load_prices_snapshot
from finn.llm.ledger import LLMLedger


def _db_url() -> str | None:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    return url or None


def get_portfolio(data_dir: Path) -> dict[str, Any]:
    url = _db_url()
    if url:
        try:
            import psycopg

            with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, bse_code, isin, name, sector, mcap_bucket, in_portfolio, research_why "
                    "FROM companies ORDER BY in_portfolio DESC, symbol ASC"
                )
                rows = cur.fetchall()
                if rows:
                    companies = [
                        {
                            "symbol": r[0],
                            "bse_code": r[1],
                            "isin": r[2],
                            "name": r[3],
                            "sector": r[4],
                            "mcap": r[5],
                        }
                        for r in rows
                        if r[6]
                    ]
                    research = [
                        {
                            "symbol": r[0],
                            "bse_code": r[1],
                            "isin": r[2],
                            "name": r[3],
                            "sector": r[4],
                            "mcap": r[5],
                            "in_portfolio": bool(r[6]),
                            "why": r[7],
                        }
                        for r in rows
                        if not r[6]
                    ]
                    return {
                        "source": "neon",
                        "freshness_chip": "Portfolio · Neon DB",
                        "companies": companies,
                        "research": research,
                    }
        except (OSError, RuntimeError, ValueError) as exc:
            _ = exc

    path = data_dir / "seed" / "portfolio.json"
    if not path.exists():
        return {"source": "missing", "freshness_chip": "Portfolio · missing", "companies": [], "research": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        "source": "snapshot",
        "freshness_chip": "Portfolio · Snapshot",
        **raw,
    }


def get_prices(data_dir: Path, *, symbols: list[str] | None = None) -> dict[str, Any]:
    url = _db_url()
    if url:
        try:
            import psycopg

            with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, yahoo_ticker, as_of::text, close::float8, prev_close::float8, "
                    "change_pct::float8, volume, avg_volume_20d, volume_multiple::float8, "
                    "high_20d::float8, low_20d::float8, sparkline_json, bars_json, fetched_at::text "
                    "FROM prices_eod"
                )
                rows = cur.fetchall()
                if rows:
                    prices = {}
                    for r in rows:
                        if symbols and r[0] not in symbols:
                            continue
                        prices[r[0]] = {
                            "symbol": r[0],
                            "yahoo_ticker": r[1],
                            "as_of": r[2],
                            "close": r[3],
                            "prev_close": r[4],
                            "change_pct": r[5],
                            "volume": r[6],
                            "avg_volume_20d": r[7],
                            "volume_multiple": r[8],
                            "high_20d": r[9],
                            "low_20d": r[10],
                            "sparkline_20d": r[11],
                            "bars": r[12],
                        }
                    as_of = max((v["as_of"] for v in prices.values()), default="unknown")
                    return {
                        "source": "neon",
                        "as_of": as_of,
                        "freshness_chip": f"Prices · EOD {as_of}",
                        "count": len(prices),
                        "prices": prices,
                    }
        except (OSError, RuntimeError, ValueError) as exc:
            _ = exc

    snap = load_prices_snapshot(data_dir)
    if symbols:
        snap["prices"] = {k: v for k, v in snap.get("prices", {}).items() if k in symbols}
        snap["count"] = len(snap["prices"])
    return snap


def get_announcements(
    data_dir: Path,
    *,
    window_hours: int | None = None,
    as_of_ts: str | None = None,
    symbol: str | None = None,
    include_demo: bool = True,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    source = "snapshot"
    as_of: str | None = None
    demo_clock_default: str | None = None
    provenance: dict[str, Any] = {}
    probe_note: str | None = None

    url = _db_url()
    if url:
        try:
            import psycopg

            with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT id, symbol, source, exchange, ts::text, raw_category, subject, pdf_url, "
                    "category, cls_method, cls_rule, priority, summary_1l, is_demo_scenario, details_json "
                    "FROM announcements ORDER BY priority DESC, ts DESC"
                )
                rows = cur.fetchall()
                if rows:
                    source = "neon"
                    for r in rows:
                        items.append(
                            {
                                "id": r[0],
                                "symbol": r[1],
                                "source": r[2],
                                "exchange": r[3],
                                "ts": r[4],
                                "raw_category": r[5],
                                "subject": r[6],
                                "pdf_url": r[7],
                                "category": r[8],
                                "cls_method": r[9],
                                "cls_rule": r[10],
                                "priority": r[11],
                                "summary_1l": r[12],
                                "is_demo_scenario": bool(r[13]),
                                "details": r[14] or {},
                            }
                        )
                if include_demo:
                    cur.execute(
                        "SELECT id, symbol, source, exchange, ts::text, raw_category, subject, pdf_url, "
                        "category, cls_method, cls_rule, priority, summary_1l, is_demo_scenario, details_json "
                        "FROM demo_announcements ORDER BY priority DESC, ts DESC"
                    )
                    for r in cur.fetchall():
                        items.append(
                            {
                                "id": r[0],
                                "symbol": r[1],
                                "source": "demo",
                                "exchange": r[3],
                                "ts": r[4],
                                "raw_category": r[5],
                                "subject": r[6],
                                "pdf_url": r[7],
                                "category": r[8],
                                "cls_method": r[9],
                                "cls_rule": r[10],
                                "priority": r[11],
                                "summary_1l": r[12],
                                "is_demo_scenario": True,
                                "details": r[14] or {},
                            }
                        )
        except (OSError, RuntimeError, ValueError):
            items = []
            source = "snapshot"

    if not items:
        snap_path = data_dir / "snapshots" / "announcements" / "announcements.json"
        if snap_path.exists():
            raw = json.loads(snap_path.read_text(encoding="utf-8"))
            items = list(raw.get("items", []))
            as_of = raw.get("as_of") or raw.get("window_end")
            demo_clock_default = raw.get("demo_clock_default") or raw.get("window_end")
            provenance = raw.get("provenance") or {}
            probe_note = raw.get("exchange_probe_summary")
        if include_demo:
            demo_path = data_dir / "snapshots" / "announcements" / "demo_announcements.json"
            if demo_path.exists():
                demo_raw = json.loads(demo_path.read_text(encoding="utf-8"))
                for d in demo_raw.get("items", []):
                    items.append({**d, "source": "demo", "is_demo_scenario": True})

    if not include_demo:
        items = [x for x in items if not x.get("is_demo_scenario") and x.get("source") != "demo"]
    if symbol:
        items = [x for x in items if x.get("symbol", "").upper() == symbol.upper()]

    # Demo-clock mode: default anchor is the frozen snapshot's latest timestamp (`demo_clock_default`),
    # or a user-chosen `as_of_ts` ISO string (or "live" for current wall clock).
    parsed_ts = []
    for x in items:
        try:
            parsed_ts.append(datetime.fromisoformat(str(x["ts"])))
        except ValueError:
            pass
    default_anchor = max(parsed_ts) if parsed_ts else datetime.now(UTC)

    if as_of_ts and as_of_ts.lower() == "live":
        anchor = datetime.now(UTC)
        clock_mode = "live"
    elif as_of_ts:
        try:
            anchor = datetime.fromisoformat(as_of_ts)
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=UTC)
            clock_mode = "custom"
        except ValueError:
            anchor = default_anchor
            clock_mode = "frozen"
    else:
        anchor = default_anchor
        clock_mode = "frozen"

    if window_hours is not None and items:
        cutoff = anchor - timedelta(hours=window_hours)
        filtered = []
        for x in items:
            try:
                dt = datetime.fromisoformat(str(x["ts"]))
                if cutoff <= dt <= anchor:
                    filtered.append(x)
            except ValueError:
                filtered.append(x)
        items = filtered

    items.sort(key=lambda x: (-int(x.get("priority", 0)), str(x.get("ts", ""))), reverse=False)
    material = [x for x in items if int(x.get("priority", 0)) >= 50]
    routine = [x for x in items if int(x.get("priority", 0)) < 50]

    chip = f"Filings · {as_of or 'Frozen window'} ({'Neon' if source == 'neon' else 'Snapshot'})"
    return {
        "source": source,
        "as_of": as_of,
        "demo_clock": {
            "mode": clock_mode,
            "anchor_ts": anchor.isoformat(),
            "default_ts": demo_clock_default or default_anchor.isoformat(),
        },
        "provenance": provenance,
        "freshness_chip": chip,
        "exchange_probe_summary": probe_note,
        "total": len(items),
        "material_count": len(material),
        "routine_count": len(routine),
        "material": material,
        "routine": routine,
        "items": items,
    }


def get_freshness_overview(data_dir: Path) -> dict[str, Any]:
    prices = get_prices(data_dir)
    ann = get_announcements(data_dir)
    ledger = LLMLedger(data_dir / "snapshots" / "llm_ledger.jsonl").summary()
    verified_path = data_dir / "snapshots" / "verified_models.json"
    models = json.loads(verified_path.read_text()) if verified_path.exists() else {}
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "db_configured": bool(_db_url()),
        "llm_configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
        "prices": {
            "source": prices.get("source"),
            "as_of": prices.get("as_of"),
            "chip": prices.get("freshness_chip"),
            "count": prices.get("count", 0),
        },
        "announcements": {
            "source": ann.get("source"),
            "as_of": ann.get("as_of"),
            "chip": ann.get("freshness_chip"),
            "total": ann.get("total", 0),
            "material_count": ann.get("material_count", 0),
            "routine_count": ann.get("routine_count", 0),
            "exchange_probe_summary": ann.get("exchange_probe_summary"),
        },
        "models": {
            "bulk_model": models.get("bulk_model", "gemini-2.5-flash-lite"),
            "strong_model": models.get("strong_model", "gemini-2.5-flash"),
            "verified_at": models.get("verified_at"),
        },
        "llm_spend": {
            "total_calls": ledger["total_calls"],
            "cache_hits": ledger["cache_hits"],
            "estimated_paid_cost_inr": ledger["estimated_paid_cost_inr"],
            "actual_free_tier_spend_inr": ledger["actual_free_tier_spend_inr"],
        },
    }
