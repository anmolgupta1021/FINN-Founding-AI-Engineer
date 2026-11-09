"""Verify live Gemini model names and free-tier behaviour, then write apps/api/data/snapshots/verified_models.json.

Usage:
    apps/api/.venv/bin/python scripts/check_models.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apps" / "api" / "data"
OUT_PATH = DATA_DIR / "snapshots" / "verified_models.json"

# Candidate order (newest live Gemini 3.x models first; falls back gracefully)
BULK_CANDIDATES = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]
STRONG_CANDIDATES = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]


def load_env_files() -> None:
    for p in (ROOT / ".env", ROOT / ".env.local", Path.home() / ".env"):
        if p.exists():
            load_dotenv(p, override=False)


def main() -> None:
    load_env_files()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    report: dict = {
        "verified_at": datetime.now(UTC).isoformat(),
        "key_present": bool(api_key),
        "free_tier_rate_limits_note": (
            "Google AI Studio enforces free-tier limits per project (dynamic in AI Studio -> Rate Limits). "
            "Typical free-tier envelopes: Flash-Lite ~15 RPM / 250k TPM / 500-1000 RPD; "
            "Flash (thinking) ~10 RPM / 250k TPM / 250-500 RPD; thinking tokens count toward output tokens. "
            "FINN stays well inside this by: (1) rules-first classification (~75%+ handled with 0 LLM calls), "
            "(2) batching remaining announcements up to 20 per call, and (3) sha256 content-hash caching."
        ),
        "available_gemini_models": [],
        "bulk_model": os.environ.get("FINN_MODEL_BULK") or "gemini-2.5-flash-lite",
        "strong_model": os.environ.get("FINN_MODEL_STRONG") or "gemini-2.5-flash",
        "strong_thinking_budget": int(os.environ.get("FINN_STRONG_THINKING_BUDGET") or 2048),
        "pings": {},
    }

    if not api_key:
        print("GEMINI_API_KEY not set in .env / .env.local / ~/.env.")
        print(f"Writing default verified_models.json -> bulk={report['bulk_model']}, strong={report['strong_model']}")
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(report, indent=2) + "\n")
        return

    from google import genai
    from google.genai import types

    modes_to_try = [False]
    listed: list[str] = []
    for mode in modes_to_try:
        try:
            c_try = genai.Client(vertexai=mode, api_key=api_key)
            for m in c_try.models.list():
                name = (getattr(m, "name", "") or "").replace("models/", "").replace("publishers/google/models/", "")
                if name.startswith("gemini-"):
                    listed.append(name)
            if listed:
                report["vertexai_express_mode"] = mode
                break
        except Exception as e:  # noqa: BLE001
            print(f"Note (vertexai={mode}): models.list() -> {str(e)[:140]}")
    if not listed:
        listed = sorted(set(BULK_CANDIDATES + STRONG_CANDIDATES))
    else:
        listed.sort()
        print(f"Found {len(listed)} gemini-* models on this key:")
        for name in listed:
            if any(k in name for k in ("flash", "pro")):
                print("  -", name)
    report["available_gemini_models"] = listed

    # Pick bulk (prefer flash-lite) and strong (prefer flash with thinking)
    flash_lites = [m for m in listed if "flash-lite" in m and "tts" not in m and "image" not in m]
    flashes = [
        m for m in listed
        if "flash" in m and "lite" not in m and "tts" not in m and "image" not in m and "audio" not in m and "live" not in m
    ]
    bulk_order = (
        [os.environ["FINN_MODEL_BULK"]] if os.environ.get("FINN_MODEL_BULK") else []
    ) + [m for m in BULK_CANDIDATES if m in listed] + list(reversed(flash_lites))
    strong_order = (
        [os.environ["FINN_MODEL_STRONG"]] if os.environ.get("FINN_MODEL_STRONG") else []
    ) + [m for m in STRONG_CANDIDATES if m in listed] + list(reversed(flashes))

    def try_ping(candidates: list[str], *, thinking_budget: int = 0) -> str | None:
        seen: set[str] = set()
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            for mode in modes_to_try:
                t0 = time.monotonic()
                try:
                    c_try = genai.Client(vertexai=mode, api_key=api_key)
                    cfg = types.GenerateContentConfig(max_output_tokens=16, temperature=0.0)
                    if thinking_budget > 0:
                        cfg.thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget)
                    r = c_try.models.generate_content(model=cand, contents="Reply with OK", config=cfg)
                    ms = int((time.monotonic() - t0) * 1000)
                    usage = getattr(r, "usage_metadata", None)
                    report["vertexai_express_mode"] = mode
                    report["pings"][cand] = {
                        "ok": True,
                        "vertexai": mode,
                        "latency_ms": ms,
                        "in_tokens": getattr(usage, "prompt_token_count", 0),
                        "out_tokens": getattr(usage, "candidates_token_count", 0),
                        "thinking_tokens": getattr(usage, "thoughts_token_count", 0),
                    }
                    print(f"  [PASS] {cand} (vertexai={mode}, {ms} ms)")
                    return cand
                except Exception as e:  # noqa: BLE001
                    report["pings"][f"{cand}:vertexai={mode}"] = {"ok": False, "error": str(e)[:200]}
                    print(f"  [FAIL] {cand} (vertexai={mode}): {str(e)[:120]}")
        return None

    print("\nPinging bulk (Flash-Lite) candidates:")
    picked_bulk = try_ping(bulk_order, thinking_budget=0)
    if picked_bulk:
        report["bulk_model"] = picked_bulk

    print("\nPinging strong (Flash + thinking) candidates:")
    picked_strong = try_ping(strong_order, thinking_budget=512)
    if picked_strong:
        report["strong_model"] = picked_strong

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nSaved {OUT_PATH.relative_to(ROOT)} -> bulk={report['bulk_model']}, strong={report['strong_model']}")


if __name__ == "__main__":
    main()
