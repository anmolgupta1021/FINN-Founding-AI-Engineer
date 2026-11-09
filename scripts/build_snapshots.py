"""Build and commit all Phase 1 snapshots from the developer's machine (residential IP).

Steps:
1. Validate all 22 symbols (18 portfolio + 4 research) via live yfinance (.NS/.BO) and write
   `apps/api/data/snapshots/prices/eod_prices.json`.
2. Probe live NSE (`www.nseindia.com`) and BSE (`api.bseindia.com`) announcement endpoints;
   record whether each succeeded or blocked in `apps/api/data/snapshots/announcements/exchange_probe.json`.
3. Classify and prioritise the frozen demo window announcements via the 2-stage classifier
   (rules first, bulk LLM second) and write `apps/api/data/snapshots/announcements/announcements.json`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from finn.fetchers.bse import fetch_bse_announcements
from finn.fetchers.nse import fetch_nse_announcements
from finn.fetchers.prices import fetch_eod_prices_live
from finn.llm.router import LLMRouter
from finn.pipeline.classify import classify_announcements

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"


def main() -> None:
    for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
        if p.exists():
            load_dotenv(p, override=False)

    portfolio = json.loads((DATA_DIR / "seed" / "portfolio.json").read_text())
    all_entries = portfolio["companies"] + portfolio.get("research", [])
    symbols = [c["symbol"] for c in all_entries]
    print(f"=== 1. Validating & fetching EOD prices for {len(symbols)} symbols via yfinance ===")
    prices_res = fetch_eod_prices_live(symbols, days=35)
    print(f"Succeeded: {prices_res['count']}/{len(symbols)} | as_of: {prices_res['as_of']}")
    if prices_res["failed"]:
        print(f"FAILED symbols: {prices_res['failed']}")
    else:
        print("All 22 symbols validated cleanly on NSE (.NS).")

    prices_path = DATA_DIR / "snapshots" / "prices" / "eod_prices.json"
    prices_path.parent.mkdir(parents=True, exist_ok=True)
    prices_path.write_text(json.dumps(prices_res, indent=2) + "\n")
    print(f"Wrote {prices_path.relative_to(ROOT)}")

    print("\n=== 2. Probing live NSE and BSE corporate announcement endpoints ===")
    now = datetime.now(UTC)
    from_dt = now - timedelta(days=14)
    sample_syms = ["HDFCBANK", "INFY", "POLYCAB", "DIXON", "KAYNES"]
    sample_bse = {c["symbol"]: c["bse_code"] for c in all_entries if c["symbol"] in sample_syms}

    nse_res = fetch_nse_announcements(sample_syms, from_date=from_dt, to_date=now)
    print(f"NSE probe -> ok={nse_res.ok} blocked={nse_res.blocked} status={nse_res.status_code} items={len(nse_res.items)} ({nse_res.reason})")

    bse_res = fetch_bse_announcements(sample_bse, from_date=from_dt, to_date=now)
    print(f"BSE probe -> ok={bse_res.ok} blocked={bse_res.blocked} status={bse_res.status_code} items={len(bse_res.items)} ({bse_res.reason})")

    probe_summary = (
        f"NSE: {'OK (' + str(len(nse_res.items)) + ' items)' if nse_res.ok else 'BLOCKED (' + nse_res.reason + ')'} · "
        f"BSE: {'OK (' + str(len(bse_res.items)) + ' items)' if bse_res.ok else 'BLOCKED (' + bse_res.reason + ')'}"
    )
    probe_report = {
        "probed_at": now.isoformat(),
        "sample_symbols": sample_syms,
        "summary": probe_summary,
        "nse": {
            "ok": nse_res.ok,
            "blocked": nse_res.blocked,
            "status_code": nse_res.status_code,
            "reason": nse_res.reason,
            "item_count": len(nse_res.items),
            "sample": nse_res.items[:5],
        },
        "bse": {
            "ok": bse_res.ok,
            "blocked": bse_res.blocked,
            "status_code": bse_res.status_code,
            "reason": bse_res.reason,
            "item_count": len(bse_res.items),
            "sample": bse_res.items[:5],
        },
    }
    probe_path = DATA_DIR / "snapshots" / "announcements" / "exchange_probe.json"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_text(json.dumps(probe_report, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {probe_path.relative_to(ROOT)}")

    print("\n=== 3. Classifying & freezing demo window announcements ===")
    demo_seed = json.loads((DATA_DIR / "seed" / "demo_window_announcements.json").read_text())
    contacts_seed = json.loads((DATA_DIR / "seed" / "network" / "contacts.json").read_text())
    network_symbols: set[str] = set()
    for c in contacts_seed.get("contacts", []):
        for aff in c.get("affiliations", []):
            if sym := aff.get("symbol"):
                network_symbols.add(sym)

    router = LLMRouter(DATA_DIR)
    classified = classify_announcements(
        demo_seed["items"],
        router=router,
        network_symbols=network_symbols,
        allow_llm=True,
    )
    ann_snapshot = {
        "source": "snapshot",
        "as_of": "2026-11-09",
        "window_start": demo_seed["window_start"],
        "window_end": demo_seed["window_end"],
        "exchange_probe_summary": probe_summary,
        "total": classified["total"],
        "rule_count": classified["rule_count"],
        "llm_count": classified["llm_count"],
        "rule_pct": classified["rule_pct"],
        "items": classified["items"],
    }
    ann_path = DATA_DIR / "snapshots" / "announcements" / "announcements.json"
    ann_path.write_text(json.dumps(ann_snapshot, indent=2, ensure_ascii=False) + "\n")
    print(
        f"Wrote {ann_path.relative_to(ROOT)} "
        f"({classified['total']} items, rules={classified['rule_pct']}%)"
    )


if __name__ == "__main__":
    main()
