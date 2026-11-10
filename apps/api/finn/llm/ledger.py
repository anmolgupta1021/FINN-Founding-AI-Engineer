"""Token & cost ledger for every LLM call (cache hit or live)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Reference list prices (USD per 1M tokens) used to compute counterfactual paid cost
# even when running on the $0 AI Studio free tier.
PRICE_PER_1M_USD: dict[str, tuple[float, float]] = {
    "flash-lite": (0.10, 0.40),
    "flash": (0.30, 2.50),
    "pro": (1.25, 10.00),
}
USD_TO_INR = 86.0


def estimate_cost_usd(model: str, in_tokens: int, out_tokens: int, *, cache_hit: bool) -> float:
    if cache_hit:
        return 0.0
    m = model.lower()
    if "lite" in m:
        in_rate, out_rate = PRICE_PER_1M_USD["flash-lite"]
    elif "pro" in m:
        in_rate, out_rate = PRICE_PER_1M_USD["pro"]
    else:
        in_rate, out_rate = PRICE_PER_1M_USD["flash"]
    return round((in_tokens * in_rate + out_tokens * out_rate) / 1_000_000.0, 6)


@dataclass
class LLMCallRecord:
    ts: str
    task: str
    tier: str
    model: str
    prompt_version: str
    cache_key: str
    cache_hit: bool
    in_tokens: int
    out_tokens: int
    thinking_tokens: int
    cost_usd: float
    cost_inr: float
    latency_ms: int


class LLMLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, rec: LLMCallRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def summary(self) -> dict[str, Any]:
        rows = self.read_all()
        total_calls = len(rows)
        cache_hits = sum(1 for r in rows if r.get("cache_hit"))
        in_tok = sum(int(r.get("in_tokens", 0)) for r in rows)
        out_tok = sum(int(r.get("out_tokens", 0)) for r in rows)
        thinking_tok = sum(int(r.get("thinking_tokens", 0) or 0) for r in rows)
        cost_usd = round(sum(float(r.get("cost_usd", 0.0)) for r in rows), 6)
        cost_inr = round(sum(float(r.get("cost_inr", 0.0)) for r in rows), 4)
        return {
            "total_calls": total_calls,
            "cache_hits": cache_hits,
            "live_calls": total_calls - cache_hits,
            "cache_hit_rate": round(cache_hits / total_calls, 3) if total_calls else 1.0,
            "in_tokens": in_tok,
            "out_tokens": out_tok,
            "thinking_tokens": thinking_tok,
            "estimated_paid_cost_usd": cost_usd,
            "estimated_paid_cost_inr": cost_inr,
            "actual_free_tier_spend_inr": 0.0,
            "updated_at": datetime.now(UTC).isoformat(),
            "recent": list(reversed(rows[-60:])),
        }

    def dossier_cost_summary(self, symbol: str) -> dict[str, Any]:
        """Compute exact per-dossier token & cost totals from llm_ledger.jsonl."""
        suffix = f"_{symbol.lower()}"
        sym_rows = [r for r in self.read_all() if str(r.get("task", "")).lower().endswith(suffix)]
        live_rows = [r for r in sym_rows if not r.get("cache_hit")]
        models_used: list[str] = []
        # Include the latest version run models (last 3 distinct tasks: ar, concalls, reasoning)
        latest_by_task: dict[str, dict[str, Any]] = {}
        for r in sym_rows:
            latest_by_task[str(r.get("task", ""))] = r
            m = str(r.get("model") or "")
            if m and m not in models_used:
                models_used.append(m)
        latest_models = list(
            dict.fromkeys(str(r.get("model") or "") for r in latest_by_task.values() if r.get("model"))
        )
        return {
            "symbol": symbol.upper(),
            "total_calls": len(sym_rows),
            "live_calls": len(live_rows),
            "cache_hits": len(sym_rows) - len(live_rows),
            "models_used": latest_models or models_used,
            "all_models_seen": models_used,
            "in_tokens": sum(int(r.get("in_tokens", 0)) for r in live_rows),
            "out_tokens": sum(int(r.get("out_tokens", 0)) for r in live_rows),
            "thinking_tokens": sum(int(r.get("thinking_tokens", 0) or 0) for r in live_rows),
            "cost_usd": round(sum(float(r.get("cost_usd", 0.0)) for r in live_rows), 6),
            "cost_inr": round(sum(float(r.get("cost_inr", 0.0)) for r in live_rows), 4),
            "latest_run_tasks": [
                {
                    "task": r.get("task"),
                    "model": r.get("model"),
                    "prompt_version": r.get("prompt_version"),
                    "cache_hit": r.get("cache_hit"),
                    "in_tokens": r.get("in_tokens"),
                    "out_tokens": r.get("out_tokens"),
                    "thinking_tokens": r.get("thinking_tokens", 0),
                }
                for r in latest_by_task.values()
            ],
        }
