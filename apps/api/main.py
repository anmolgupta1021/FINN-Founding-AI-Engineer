"""FINN API entrypoint (Vercel Python service: entrypoint = main:app).

Every read endpoint uses `finn.store`, which reads Neon Postgres first (when `DATABASE_URL` is set)
and falls back to committed JSON snapshots under `apps/api/data/snapshots/`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, Query

from finn.llm.ledger import LLMLedger
from finn.pipeline.alerts import build_brief
from finn.store import get_announcements, get_freshness_overview, get_portfolio, get_prices

app = FastAPI(title="FINN API", version="0.3.0")
router = APIRouter(prefix="/api/v1")

# Snapshots are committed inside the API service (apps/api/data) so they ship in the function bundle.
_HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FINN_DATA_DIR") or (_HERE / "data"))


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "finn-api",
        "version": "0.2.0",
        "time": datetime.now(UTC).isoformat(),
        "data_dir_found": DATA_DIR.exists(),
        "db_configured": bool(os.environ.get("DATABASE_URL")),
        "llm_configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    }


@router.get("/portfolio")
def portfolio() -> dict:
    return get_portfolio(DATA_DIR)


@router.get("/prices")
def prices(symbols: str | None = Query(default=None, description="Comma-separated NSE symbols")) -> dict:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return get_prices(DATA_DIR, symbols=sym_list)


@router.get("/announcements")
def announcements(
    window_hours: int | None = Query(default=None, ge=1, le=1080),
    as_of: str | None = Query(default=None, description="ISO timestamp for demo clock, or 'live'"),
    symbol: str | None = Query(default=None),
    include_demo: bool = Query(default=True),
) -> dict:
    return get_announcements(
        DATA_DIR,
        window_hours=window_hours,
        as_of_ts=as_of,
        symbol=symbol,
        include_demo=include_demo,
    )


@router.get("/brief")
def brief(
    window_hours: int = Query(default=24, ge=1, le=1080),
    as_of: str | None = Query(default=None, description="ISO timestamp for demo clock, or 'live'"),
    vol_mult_min: float = Query(default=2.0, ge=1.0, le=10.0),
    price_move_min: float = Query(default=2.5, ge=0.5, le=20.0),
    portfolio_only: bool = Query(default=False),
) -> dict:
    return build_brief(
        DATA_DIR,
        window_hours=window_hours,
        as_of_ts=as_of,
        vol_mult_min=vol_mult_min,
        price_move_min=price_move_min,
        portfolio_only=portfolio_only,
    )


@router.get("/freshness")
def freshness() -> dict:
    return get_freshness_overview(DATA_DIR)


@router.get("/llm/ledger")
def llm_ledger() -> dict:
    return LLMLedger(DATA_DIR / "snapshots" / "llm_ledger.jsonl").summary()


app.include_router(router)
