"""EOD prices & volume fetcher via yfinance (.NS / .BO) with completed-session enforcement.

If run during Indian market hours (before 15:45 IST on the same calendar date as the last bar),
yfinance's `history()` includes today's partial intraday bar. We strip that partial bar so `as_of`,
`close`, `change_pct`, and `volume_multiple` always reflect the last *completed* trading session.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))


def _is_incomplete_intraday_bar(bar_date_str: str, now_ist: datetime) -> bool:
    today_str = now_ist.strftime("%Y-%m-%d")
    if bar_date_str != today_str:
        return False
    # NSE closes at 15:30 IST; post-close settlement completes ~15:45 IST
    market_settled = (now_ist.hour > 15) or (now_ist.hour == 15 and now_ist.minute >= 45)
    return not market_settled


def fetch_eod_prices_live(symbols: list[str], *, days: int = 40) -> dict[str, Any]:
    import yfinance as yf

    now_ist = datetime.now(IST)
    out: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    dropped_intraday_dates: set[str] = set()

    for sym in symbols:
        df = None
        used_suffix = ".NS"
        for suffix in (".NS", ".BO"):
            ticker = yf.Ticker(f"{sym}{suffix}")
            hist = ticker.history(period=f"{days}d", auto_adjust=False)
            if hist is not None and not hist.empty and len(hist) >= 2:
                df = hist
                used_suffix = suffix
                break
        if df is None or df.empty:
            failed.append(sym)
            continue

        df = df.dropna(subset=["Close"])
        bars: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            dt_str = idx.strftime("%Y-%m-%d")
            if _is_incomplete_intraday_bar(dt_str, now_ist):
                dropped_intraday_dates.add(dt_str)
                continue
            bars.append(
                {
                    "date": dt_str,
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"] or 0),
                }
            )

        if len(bars) < 2:
            failed.append(sym)
            continue

        bars = bars[-22:]
        latest = bars[-1]
        prev = bars[-2]
        change_pct = (
            round(((latest["close"] - prev["close"]) / prev["close"]) * 100.0, 2)
            if prev["close"]
            else 0.0
        )
        prior_vols = [b["volume"] for b in bars[:-1][-20:] if b["volume"] > 0]
        avg_vol_20d = int(sum(prior_vols) / len(prior_vols)) if prior_vols else latest["volume"]
        vol_mult = round(latest["volume"] / avg_vol_20d, 2) if avg_vol_20d > 0 else 1.0

        out[sym] = {
            "symbol": sym,
            "yahoo_ticker": f"{sym}{used_suffix}",
            "as_of": latest["date"],
            "completed_session": True,
            "close": latest["close"],
            "prev_close": prev["close"],
            "change_pct": change_pct,
            "volume": latest["volume"],
            "avg_volume_20d": avg_vol_20d,
            "volume_multiple": vol_mult,
            "high_20d": max(b["high"] for b in bars[-20:]),
            "low_20d": min(b["low"] for b in bars[-20:]),
            "sparkline_20d": [b["close"] for b in bars[-20:]],
            "bars": bars[-20:],
        }

    latest_date = max((v["as_of"] for v in out.values()), default=None)
    return {
        "source": "yfinance",
        "as_of": latest_date,
        "completed_session": True,
        "dropped_partial_intraday_dates": sorted(dropped_intraday_dates),
        "fetched_at": datetime.now(UTC).isoformat(),
        "count": len(out),
        "failed": failed,
        "prices": out,
    }


def load_prices_snapshot(data_dir: Path) -> dict[str, Any]:
    snap = data_dir / "snapshots" / "prices" / "eod_prices.json"
    if not snap.exists():
        return {
            "source": "missing",
            "as_of": None,
            "fetched_at": None,
            "freshness_chip": "Prices · unavailable",
            "prices": {},
        }
    raw = json.loads(snap.read_text(encoding="utf-8"))
    as_of = raw.get("as_of") or "unknown"
    return {
        **raw,
        "source": "snapshot",
        "freshness_chip": f"Prices · EOD {as_of} (Snapshot)",
    }
