"""FINN API entrypoint (Vercel Python service: entrypoint = main:app).

P0: health + a snapshot-backed endpoint that proves the read path works with no DB and no network.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI

app = FastAPI(title="FINN API", version="0.1.0")
router = APIRouter(prefix="/api/v1")

# Snapshots are committed inside the API service (apps/api/data) so they ship in the function bundle.
_HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FINN_DATA_DIR") or (_HERE / "data"))


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "finn-api",
        "time": datetime.now(UTC).isoformat(),
        "data_dir_found": DATA_DIR.exists(),
        "db_configured": bool(os.environ.get("DATABASE_URL")),
        "llm_configured": bool(os.environ.get("GEMINI_API_KEY")),
    }


@router.get("/portfolio")
def portfolio() -> dict:
    """P0 read path: committed seed JSON. Later: Neon first, this as fallback."""
    path = DATA_DIR / "seed" / "portfolio.json"
    if not path.exists():
        return {"source": "missing", "companies": []}
    return {"source": "snapshot", **json.loads(path.read_text())}


app.include_router(router)
