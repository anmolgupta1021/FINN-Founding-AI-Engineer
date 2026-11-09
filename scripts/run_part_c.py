"""Part C Execution Runner.

Executes:
1. DIXON first:
   - Primary-source concall guidance extraction via Gemini Bulk tier (gemini-3.5-flash-lite)
   - Code-level quote verification (rapidfuzz >= 90.0 + numerical token matching)
   - Executive reasoning & synthesis via Gemini Strong tier (gemini-3.6-flash + thinking)
   - Reports verdict distribution and pull_* ledger rows
2. Remaining five dossiers (SYRMA, NAVINFLUOR, POLYCAB, HDFCBANK, TITAN)
3. Strict code-level verification across all 6 dossiers

Usage:
    PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/run_part_c.py [--dixon-only]
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
CACHE_ROOT = ROOT / ".cache" / "pull_docs"
LEDGER_PATH = DATA_DIR / "snapshots" / "llm_ledger.jsonl"

from dotenv import load_dotenv

for env_candidate in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
    if env_candidate.exists():
        load_dotenv(env_candidate, override=False)

from finn.pull.builder import build_company_dossier
from finn.pull.verifier import MIN_QUOTE_MATCH_SCORE


def check_api_key_configured() -> bool:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return bool(key and len(key.strip()) > 10)


def get_recent_pull_ledger_rows(since_ts: float) -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    rows = []
    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                task = rec.get("task", "")
                if task.startswith("pull_"):
                    rows.append(rec)
            except json.JSONDecodeError:
                continue
    return rows


def run_dossier_part_c(symbol: str) -> dict:
    sym = symbol.upper().strip()
    print(f"\n==================================================")
    print(f"  PART C: Executing Primary-Source LLM Pipeline for {sym}")
    print(f"==================================================")
    t0 = time.monotonic()

    def _step(msg: str, pct: int) -> None:
        print(f"  [{pct:3d}%] {msg}")

    dossier = build_company_dossier(
        sym,
        DATA_DIR,
        cache_root=CACHE_ROOT,
        progress_cb=_step,
    )
    elapsed = round(time.monotonic() - t0, 1)

    pvd = dossier.get("promised_vs_delivered", [])
    verdicts = [r.get("verdict", "unknown") for r in pvd]
    verdict_dist = dict(Counter(verdicts))

    nvn = dossier.get("numbers_vs_narrative", [])
    bull = dossier.get("bull_case", [])
    bear = dossier.get("bear_case", [])
    vs = dossier.get("verification_summary", {})

    print(f"\n✓ Completed {sym} in {elapsed}s")
    print(f"  Promised-vs-Delivered rows: {len(pvd)}")
    print(f"  Verdict distribution: {json.dumps(verdict_dist, indent=2)}")
    print(f"  Numbers-vs-Narrative checks: {len(nvn)}")
    print(f"  Bull points: {len(bull)} | Bear points: {len(bear)}")
    print(f"  Verified citations: {vs.get('total_verified_citations')} (min score: {vs.get('min_rapidfuzz_score')}%)")

    return {
        "symbol": sym,
        "elapsed_s": elapsed,
        "verdict_dist": verdict_dist,
        "pvd_count": len(pvd),
        "nvn_count": len(nvn),
        "bull_count": len(bull),
        "bear_count": len(bear),
        "verified_citations": vs.get("total_verified_citations"),
        "dossier": dossier,
    }


def main() -> None:
    dixon_only = "--dixon-only" in sys.argv
    has_key = check_api_key_configured()

    print("=== PART C: DOSSIER LLM REGENERATION & GROUNDING ===")
    print(f"Live GEMINI_API_KEY configured: {has_key}")

    if not has_key:
        print("\n[BLOCKED] GEMINI_API_KEY is not set in the environment.")
        print("Waiting for key to be provided before triggering live LLM calls.")
        print("Pre-written prompt and schema: apps/api/finn/pull/prompts.py [READY]")
        sys.exit(1)

    t_start = time.time()

    # Step 1: Run DIXON first as mandated
    dixon_res = run_dossier_part_c("DIXON")

    # Inspect DIXON pull_* ledger rows
    ledger_rows = get_recent_pull_ledger_rows(t_start)
    dixon_rows = [r for r in ledger_rows if "dixon" in r.get("task", "").lower()]
    print("\n--- DIXON pull_* Ledger Records ---")
    print(f"Found {len(dixon_rows)} pull_* records for DIXON:")
    for r in dixon_rows:
        print(
            f"  - task={r.get('task')} | model={r.get('model')} | "
            f"in={r.get('in_tokens')} out={r.get('out_tokens')} thinking={r.get('thinking_tokens')} | "
            f"cost_inr=₹{r.get('cost_inr')} | cache_hit={r.get('cache_hit')}"
        )

    if dixon_only:
        print("\nCompleted DIXON run (--dixon-only flag supplied).")
        return

    # Step 2: Run remaining 5 dossiers
    remaining_symbols = ["SYRMA", "NAVINFLUOR", "POLYCAB", "HDFCBANK", "TITAN"]
    results = [dixon_res]
    for sym in remaining_symbols:
        res = run_dossier_part_c(sym)
        results.append(res)
        time.sleep(2.0)

    # Step 3: Run final reverification across all 6 dossiers
    print("\n==================================================")
    print("  RUNNING STRICT RE-VERIFICATION (RAPIDFUZZ >= 90)")
    print("==================================================")
    from reverify_dossiers import reverify_dossier

    for sym in ["DIXON", "SYRMA", "NAVINFLUOR", "POLYCAB", "HDFCBANK", "TITAN"]:
        chk = reverify_dossier(sym)
        print(
            f"[{sym}] checked={chk.get('total_checked')} passed={chk.get('passed')} "
            f"dropped={chk.get('dropped')} min_score={chk.get('min_score')}%"
        )

    print("\n=== PART C EXECUTION COMPLETE FOR ALL 6 DOSSIERS ===")


if __name__ == "__main__":
    main()
