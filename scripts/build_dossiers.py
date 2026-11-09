"""Precompute and commit all 6 Pull Dossiers (4 Demo + 2 Generalisation Test).

Target Dossiers:
  - Demo Dossiers (4): DIXON, SYRMA, NAVINFLUOR, POLYCAB
  - Generalisation Test (2): HDFCBANK (lender path: NII/PPOP/GNPA, no EBITDA), TITAN

Usage:
    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/build_dossiers.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
CACHE_ROOT = ROOT / ".cache" / "pull_docs"

for env_candidate in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
    if env_candidate.exists():
        load_dotenv(env_candidate, override=False)

from finn.pull.builder import build_company_dossier

TARGET_SYMBOLS = [
    # 4 Demo Dossiers (mandatory per DEMO_SCRIPT.md & User Item 4)
    "DIXON",
    "SYRMA",
    "NAVINFLUOR",
    "POLYCAB",
    # 2 Unseen Generalisation Test Dossiers (mandatory per User Item 4, including HDFCBANK lender path)
    "HDFCBANK",
    "TITAN",
]


def main() -> None:
    symbols = sys.argv[1:] if len(sys.argv) > 1 else TARGET_SYMBOLS
    summary_rows: list[dict] = []

    for idx, sym in enumerate(symbols, start=1):
        sym_u = sym.upper().strip()
        print(f"\n[{idx}/{len(symbols)}] Building primary-source dossier for {sym_u}...")
        t0 = time.monotonic()

        def _log_step(msg: str, pct: int) -> None:
            print(f"  [{pct:3d}%] {msg}")

        dossier = build_company_dossier(
            sym_u,
            DATA_DIR,
            cache_root=CACHE_ROOT,
            progress_cb=_log_step,
        )
        elapsed_s = round(time.monotonic() - t0, 1)
        vs = dossier.get("verification_summary", {})
        pvd = dossier.get("promised_vs_delivered", [])
        nvn = dossier.get("numbers_vs_narrative", [])
        bull = dossier.get("bull_case", [])
        bear = dossier.get("bear_case", [])
        net = dossier.get("network", {})

        row = {
            "symbol": sym_u,
            "is_lender": dossier.get("is_lender"),
            "elapsed_s": elapsed_s,
            "docs_verified": vs.get("total_documents_verified"),
            "concalls_verified": vs.get("concall_transcripts_verified"),
            "latest_call_untestable": vs.get("latest_call_marked_untestable"),
            "verified_citations": vs.get("total_verified_citations"),
            "min_rapidfuzz_score": vs.get("min_rapidfuzz_score"),
            "pvd_rows": len(pvd),
            "nvn_checks": len(nvn),
            "bull_points": len(bull),
            "bear_points": len(bear),
            "network_matched": net.get("total_matched"),
        }
        summary_rows.append(row)
        print(f"  -> Saved apps/api/data/snapshots/dossiers/{sym_u}.json ({elapsed_s}s): {json.dumps(row)}")

        if idx < len(symbols):
            time.sleep(2.0)

    print("\n=== DOSSIER PRECOMPUTE SUMMARY ===")
    print(json.dumps(summary_rows, indent=2))


if __name__ == "__main__":
    main()
