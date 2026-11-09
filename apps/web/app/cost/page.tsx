"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface LedgerCall {
  ts: string;
  task: string;
  tier: string;
  model: string;
  prompt_version?: string;
  cache_key: string;
  cache_hit: boolean;
  in_tokens: number;
  out_tokens: number;
  thinking_tokens?: number;
  cost_usd: number;
  cost_inr: number;
  latency_ms: number;
}

interface LedgerSummary {
  total_calls: number;
  cache_hits: number;
  live_calls: number;
  cache_hit_rate: number;
  in_tokens: number;
  out_tokens: number;
  estimated_paid_cost_usd: number;
  estimated_paid_cost_inr: number;
  actual_free_tier_spend_inr: number;
  updated_at: string;
  recent: LedgerCall[];
}

const FALLBACK_LEDGER: LedgerSummary = {
  total_calls: 5,
  cache_hits: 0,
  live_calls: 5,
  cache_hit_rate: 0.0,
  in_tokens: 6394,
  out_tokens: 4926,
  estimated_paid_cost_usd: 0.002609,
  estimated_paid_cost_inr: 0.2244,
  actual_free_tier_spend_inr: 0.0,
  updated_at: "2026-11-09T08:48:36Z",
  recent: [
    {
      ts: "2026-11-09T08:46:40Z",
      task: "classify_announcements_batch",
      tier: "bulk",
      model: "gemini-3.5-flash-lite",
      prompt_version: "cls-batch-v1",
      cache_key: "6fc61142d8ad4eafa59cd77c10bd73468879b9dd9081a7f2ec1f11ef11d94d56",
      cache_hit: false,
      in_tokens: 1666,
      out_tokens: 1432,
      cost_usd: 0.000739,
      cost_inr: 0.0636,
      latency_ms: 3651,
    },
    {
      ts: "2026-11-09T08:46:42Z",
      task: "classify_announcements_batch",
      tier: "bulk",
      model: "gemini-3.5-flash-lite",
      prompt_version: "cls-batch-v1",
      cache_key: "17087b3b7b36f3fa513615ac1d2778abdaae9f442413501a81de096348bccd51",
      cache_hit: false,
      in_tokens: 449,
      out_tokens: 273,
      cost_usd: 0.000154,
      cost_inr: 0.0132,
      latency_ms: 1304,
    },
    {
      ts: "2026-11-09T08:48:31Z",
      task: "classify_announcements_batch",
      tier: "bulk",
      model: "gemini-3.5-flash-lite",
      prompt_version: "cls-batch-v1",
      cache_key: "6544d961c1530a2d11eb8040cd4f9af9db217620d89e50e47787921bfe774e63",
      cache_hit: false,
      in_tokens: 1562,
      out_tokens: 1152,
      cost_usd: 0.000617,
      cost_inr: 0.0531,
      latency_ms: 3991,
    },
    {
      ts: "2026-11-09T08:48:34Z",
      task: "classify_announcements_batch",
      tier: "bulk",
      model: "gemini-3.5-flash-lite",
      prompt_version: "cls-batch-v1",
      cache_key: "8522c10bcac11f56b86d76158d5874decc11d5f897350600117fcf991e84fc54",
      cache_hit: false,
      in_tokens: 1690,
      out_tokens: 1331,
      cost_usd: 0.000701,
      cost_inr: 0.0603,
      latency_ms: 3288,
    },
    {
      ts: "2026-11-09T08:48:36Z",
      task: "classify_announcements_batch",
      tier: "bulk",
      model: "gemini-3.5-flash-lite",
      prompt_version: "cls-batch-v1",
      cache_key: "07c97ad660b7a33540c4dfb3cd83a944e4856be9ca669f8c84bf8708ea3b1874",
      cache_hit: false,
      in_tokens: 1027,
      out_tokens: 738,
      cost_usd: 0.000398,
      cost_inr: 0.0342,
      latency_ms: 2158,
    },
  ],
};

export default function CostPage() {
  const [data, setData] = useState<LedgerSummary>(FALLBACK_LEDGER);
  const [loading, setLoading] = useState<boolean>(true);
  const [sourceTag, setSourceTag] = useState<"live" | "snapshot">("snapshot");

  useEffect(() => {
    let ignore = false;
    fetch("/api/v1/llm/ledger", { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload: LedgerSummary) => {
        if (ignore) return;
        setData(payload);
        setSourceTag("live");
        setLoading(false);
      })
      .catch(() => {
        if (ignore) return;
        setData(FALLBACK_LEDGER);
        setSourceTag("snapshot");
        setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  const totalTokens = (data.in_tokens || 0) + (data.out_tokens || 0);

  return (
    <main className="space-y-6">
      <header className="flex items-baseline justify-between border-b border-ink pb-2">
        <div className="flex items-baseline gap-2.5">
          <Link href="/" className="font-serif text-[28px] font-semibold tracking-tight hover:opacity-80">
            FINN
          </Link>
          <span className="font-mono text-[11px] text-muted">/cost · LLM Ledger</span>
        </div>
        <Link
          href="/"
          className="font-mono text-xs text-accent underline underline-offset-2 hover:opacity-80"
        >
          ← Back to Brief
        </Link>
      </header>

      {/* Honesty Banner */}
      <div className="border border-rule bg-paper-2 p-3 text-xs text-ink-2 space-y-1">
        <div className="flex items-center justify-between">
          <span className="kicker">LLM Call Transparency</span>
          <span className="font-mono text-[10px] uppercase text-muted">
            Source: {sourceTag} {loading && "(refreshing...)"}
          </span>
        </div>
        <p>
          Every external LLM call is recorded in an immutable append-only JSON Lines ledger
          (<code className="font-mono text-[11px]">llm_ledger.jsonl</code>) hashed by SHA-256 prompt content.
          Private investor network data never enters prompts.
        </p>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="border border-rule p-3">
          <div className="kicker text-[10px]">Actual Spend</div>
          <div className="num mt-1 text-2xl font-semibold text-up">₹0.00</div>
          <div className="mt-0.5 text-[11px] text-muted">Free-tier Gemini</div>
        </div>

        <div className="border border-rule p-3">
          <div className="kicker text-[10px]">Paid Eq. Cost</div>
          <div className="num mt-1 text-2xl font-semibold text-ink">
            ₹{(data.estimated_paid_cost_inr || 0).toFixed(4)}
          </div>
          <div className="mt-0.5 text-[11px] text-muted">
            ${(data.estimated_paid_cost_usd || 0).toFixed(6)} USD
          </div>
        </div>

        <div className="border border-rule p-3">
          <div className="kicker text-[10px]">Total Calls</div>
          <div className="num mt-1 text-2xl font-semibold text-ink">{data.total_calls}</div>
          <div className="mt-0.5 text-[11px] text-muted">
            {data.live_calls} live · {data.cache_hits} cached
          </div>
        </div>

        <div className="border border-rule p-3">
          <div className="kicker text-[10px]">Total Tokens</div>
          <div className="num mt-1 text-2xl font-semibold text-ink">{totalTokens.toLocaleString()}</div>
          <div className="mt-0.5 text-[11px] text-muted">
            {data.in_tokens.toLocaleString()} in · {data.out_tokens.toLocaleString()} out
          </div>
        </div>
      </div>

      {/* Tier & Quota Disclosure */}
      <section className="space-y-2">
        <h2 className="font-serif text-lg font-semibold tracking-tight">Two-Tier Router Architecture</h2>
        <div className="border border-rule text-xs">
          <div className="border-b border-rule bg-paper-2 p-2.5 font-medium">
            Strict Separation of Concern
          </div>
          <div className="divide-y divide-rule">
            <div className="p-2.5 space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-mono font-medium text-ink">Bulk Tier · gemini-3.5-flash-lite</span>
                <span className="font-mono text-[10px] text-muted">Free-Tier Quota (Console Observed*)</span>
              </div>
              <p className="text-ink-2">
                Used for high-volume announcement classification and filtering. Zero thinking tokens.
              </p>
              <div className="font-mono text-[11px] text-muted">
                Rate Limits: ~15 RPM · ~250k TPM · ~500–1000 RPD (*unverified web console estimate)
              </div>
            </div>

            <div className="p-2.5 space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-mono font-medium text-ink">Complex Tier · gemini-3.6-flash</span>
                <span className="font-mono text-[10px] text-muted">Free-Tier Quota (Console Observed*)</span>
              </div>
              <p className="text-ink-2">
                Used for deep synthesis and verbatim guidance extraction with strict thinking budget.
              </p>
              <div className="font-mono text-[11px] text-muted">
                Rate Limits: ~10 RPM · ~250k TPM · ~250 RPD (*unverified web console estimate)
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Ledger Feed Table */}
      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <h2 className="font-serif text-lg font-semibold tracking-tight">Ledger Calls</h2>
          <span className="font-mono text-xs text-muted">{data.recent.length} recorded</span>
        </div>

        <div tabIndex={0} className="table-wrapper border border-rule">
          <table className="text-left text-xs">
            <caption className="sr-only">Immutable LLM Call Ledger</caption>
            <thead className="border-b border-rule bg-paper-2 font-mono text-[10px] uppercase text-muted">
              <tr>
                <th scope="col" className="p-2">Timestamp</th>
                <th scope="col" className="p-2">Task</th>
                <th scope="col" className="p-2">Model</th>
                <th scope="col" className="p-2 text-right">Tokens (In / Out)</th>
                <th scope="col" className="p-2 text-right">Latency</th>
                <th scope="col" className="p-2 text-right">Paid Eq.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule font-mono text-[11px]">
              {data.recent.map((entry, idx) => (
                <tr key={`${entry.ts}-${idx}`} className="hover:bg-paper-2/60">
                  <td className="p-2 text-muted whitespace-nowrap">
                    {entry.ts.slice(11, 19)} UTC
                  </td>
                  <td className="p-2 font-sans font-medium text-ink">
                    {entry.task}
                    {entry.cache_hit && (
                      <span className="ml-1.5 rounded border border-rule px-1 text-[9px] text-muted">
                        CACHED
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-muted whitespace-nowrap">{entry.model}</td>
                  <td className="p-2 text-right num whitespace-nowrap">
                    {entry.in_tokens.toLocaleString()} / {entry.out_tokens.toLocaleString()}
                  </td>
                  <td className="p-2 text-right num text-muted whitespace-nowrap">
                    {(entry.latency_ms / 1000).toFixed(1)}s
                  </td>
                  <td className="p-2 text-right num text-ink font-medium whitespace-nowrap">
                    ₹{(entry.cost_inr || 0).toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Privacy Guarantee */}
      <footer className="border-t border-rule pt-4 text-xs text-muted space-y-1">
        <div className="font-medium text-ink-2">Zero-Leakage Privacy Policy</div>
        <p>
          FINN enforces programmatic privacy boundaries: private investor contacts and relationships are
          resolved 100% locally on device using deterministic graph traversal and never transmitted to any LLM.
        </p>
      </footer>
    </main>
  );
}
