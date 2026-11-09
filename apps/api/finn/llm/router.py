"""Provider-agnostic LLM router with two tiers:
- 'bulk'   -> FINN_MODEL_BULK   (Flash-Lite: classification, extraction, 1L summaries, intent parsing)
- 'strong' -> FINN_MODEL_STRONG (Flash with thinking: numbers-vs-narrative, bull/bear)

Enforces:
1. Privacy guard (`assert_no_private_network_data`) BEFORE cache or API call.
2. SHA-256 content-hash cache (`apps/api/data/snapshots/llm_cache.json`).
3. Call ledger (`apps/api/data/snapshots/llm_ledger.jsonl`).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from finn.llm.cache import ContentHashCache, compute_cache_key
from finn.llm.ledger import USD_TO_INR, LLMCallRecord, LLMLedger, estimate_cost_usd
from finn.llm.privacy import assert_no_private_network_data

ModelTier = Literal["bulk", "strong"]

DEFAULT_BULK_MODEL = "gemini-3.5-flash-lite"
DEFAULT_STRONG_MODEL = "gemini-3.6-flash"


def resolve_configured_models(data_dir: Path) -> dict[str, Any]:
    """Read verified_models.json (written by scripts/check_models.py) if present; env vars win."""
    verified_file = data_dir / "snapshots" / "verified_models.json"
    verified: dict[str, Any] = {}
    if verified_file.exists():
        try:
            verified = json.loads(verified_file.read_text())
        except json.JSONDecodeError:
            verified = {}

    bulk = (
        os.environ.get("FINN_MODEL_BULK")
        or verified.get("bulk_model")
        or DEFAULT_BULK_MODEL
    )
    strong = (
        os.environ.get("FINN_MODEL_STRONG")
        or verified.get("strong_model")
        or DEFAULT_STRONG_MODEL
    )
    thinking_budget = int(
        os.environ.get("FINN_STRONG_THINKING_BUDGET")
        or verified.get("strong_thinking_budget")
        or 2048
    )
    return {
        "bulk_model": bulk,
        "strong_model": strong,
        "strong_thinking_budget": thinking_budget,
        "verified_at": verified.get("verified_at"),
    }


class LLMRouter:
    def __init__(
        self,
        data_dir: Path,
        *,
        transport: Callable[[str, str, Any, dict[str, Any] | None, int], dict[str, Any]] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.cache = ContentHashCache(data_dir / "snapshots" / "llm_cache.json")
        self.ledger = LLMLedger(data_dir / "snapshots" / "llm_ledger.jsonl")
        self._transport = transport

    def model_for(self, tier: ModelTier) -> tuple[str, int]:
        cfg = resolve_configured_models(self.data_dir)
        if tier == "bulk":
            return cfg["bulk_model"], 0
        return cfg["strong_model"], int(cfg["strong_thinking_budget"])

    def generate(
        self,
        *,
        task: str,
        tier: ModelTier,
        source_kind: str,
        prompt_version: str,
        system: str,
        contents: Any,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 1. Privacy gate — always runs first, even before cache lookup.
        assert_no_private_network_data(
            {"system": system, "contents": contents},
            source_kind=source_kind,
            data_dir=self.data_dir,
        )

        model, thinking_budget = self.model_for(tier)
        key = compute_cache_key(
            model=model,
            prompt_version=prompt_version,
            system=system,
            contents=contents,
            response_schema=response_schema,
            thinking_budget=thinking_budget,
        )

        # 2. Content-hash cache lookup
        cached = self.cache.get(key)
        if cached is not None:
            rec = LLMCallRecord(
                ts=datetime.now(UTC).isoformat(),
                task=task,
                tier=tier,
                model=model,
                prompt_version=prompt_version,
                cache_key=key,
                cache_hit=True,
                in_tokens=int(cached.get("in_tokens", 0)),
                out_tokens=int(cached.get("out_tokens", 0)),
                thinking_tokens=int(cached.get("thinking_tokens", 0)),
                cost_usd=0.0,
                cost_inr=0.0,
                latency_ms=0,
            )
            self.ledger.record(rec)
            return {**cached, "cache_hit": True, "cache_key": key, "model": model}

        # 3. Live call via transport or google-genai
        t0 = time.monotonic()
        if self._transport is not None:
            raw = self._transport(model, system, contents, response_schema, thinking_budget)
        else:
            raw = self._call_gemini(model, system, contents, response_schema, thinking_budget)
        latency_ms = int((time.monotonic() - t0) * 1000)

        in_tokens = int(raw.get("in_tokens", 0))
        out_tokens = int(raw.get("out_tokens", 0))
        thinking_tokens = int(raw.get("thinking_tokens", 0))
        cost_usd = estimate_cost_usd(model, in_tokens, out_tokens + thinking_tokens, cache_hit=False)
        cost_inr = round(cost_usd * USD_TO_INR, 4)

        entry = {
            "text": raw.get("text", ""),
            "parsed": raw.get("parsed"),
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
            "thinking_tokens": thinking_tokens,
            "model": model,
            "prompt_version": prompt_version,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.cache.put(key, entry)

        rec = LLMCallRecord(
            ts=datetime.now(UTC).isoformat(),
            task=task,
            tier=tier,
            model=model,
            prompt_version=prompt_version,
            cache_key=key,
            cache_hit=False,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=cost_usd,
            cost_inr=cost_inr,
            latency_ms=latency_ms,
        )
        self.ledger.record(rec)
        return {**entry, "cache_hit": False, "cache_key": key}

    @staticmethod
    def _call_gemini(
        model: str,
        system: str,
        contents: Any,
        response_schema: dict[str, Any] | None,
        thinking_budget: int,
    ) -> dict[str, Any]:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set and request was not in content-hash cache")

        from google import genai
        from google.genai import types

        cfg_kwargs: dict[str, Any] = {"system_instruction": system, "temperature": 0.1}
        if response_schema is not None:
            cfg_kwargs["response_mime_type"] = "application/json"
            cfg_kwargs["response_schema"] = response_schema
        if thinking_budget > 0 and hasattr(types, "ThinkingConfig"):
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

        prompt_text = contents if isinstance(contents, str) else json.dumps(contents, ensure_ascii=False)
        client = genai.Client(vertexai=False, api_key=api_key)
        candidate_models = [model]
        if "flash-lite" in model and "gemini-3.1-flash-lite" not in candidate_models:
            candidate_models.append("gemini-3.1-flash-lite")
        elif "flash" in model and "gemini-3.5-flash" not in candidate_models:
            candidate_models.append("gemini-3.5-flash")

        last_exc: Exception | None = None
        resp = None
        for cand_model in candidate_models:
            try:
                resp = client.models.generate_content(
                    model=cand_model,
                    contents=prompt_text,
                    config=types.GenerateContentConfig(**cfg_kwargs),
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        if resp is None:
            raise last_exc or RuntimeError("Gemini call failed")
        usage = getattr(resp, "usage_metadata", None)
        in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
        think_tok = int(getattr(usage, "thoughts_token_count", 0) or 0)
        text = resp.text or ""
        parsed = None
        if response_schema is not None and text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        return {
            "text": text,
            "parsed": parsed,
            "in_tokens": in_tok,
            "out_tokens": out_tok,
            "thinking_tokens": think_tok,
        }
