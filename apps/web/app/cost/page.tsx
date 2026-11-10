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
  thinking_tokens?: number;
  estimated_paid_cost_usd: number;
  estimated_paid_cost_inr: number;
  actual_free_tier_spend_inr: number;
  updated_at: string;
  recent: LedgerCall[];
}

const EMPTY_LEDGER: LedgerSummary = {
  total_calls: 0,
  cache_hits: 0,
  live_calls: 0,
  cache_hit_rate: 1.0,
  in_tokens: 0,
  out_tokens: 0,
  thinking_tokens: 0,
  estimated_paid_cost_usd: 0,
  estimated_paid_cost_inr: 0,
  actual_free_tier_spend_inr: 0,
  updated_at: "",
  recent: [],
};

export default function CostPage() {
  const [data, setData] = useState<LedgerSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

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
        setFetchError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ignore) return;
        setData(EMPTY_LEDGER);
        setFetchError(err instanceof Error ? err.message : "Failed to load /api/v1/llm/ledger");
        setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  const ledger = data ?? EMPTY_LEDGER;
  const totalTokens = (ledger.in_tokens || 0) + (ledger.out_tokens || 0) + (ledger.thinking_tokens || 0);

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
            Source: {fetchError ? `unavailable (${fetchError})` : loading ? "loading /api/v1/llm/ledger..." : "llm_ledger.jsonl (live)"}
          </span>
        </div>
        <p>
          Every external LLM call is recorded in an immutable append-only JSON Lines ledger
          (<code className="font-mono text-[11px]">llm_ledger.jsonl</code>) hashed by SHA-256 prompt content.
          Private investor network data never enters prompts.
        </p>
        <p className="border-t border-rule/60 pt-1 text-muted">
          <strong>Ledger Scope Disclosure:</strong> Totals above match{" "}
          <code className="font-mono text-[11px]">apps/api/data/snapshots/llm_ledger.jsonl</code> verbatim,
          covering all Stage-2 announcement classification batches across the 776 NSE/BSE filings and primary-source Pull pipelines
          for DIXON, POLYCAB, HDFCBANK, and KAYNES. NAVINFLUOR, SYRMA, and TITAN remain deterministic-extract only.
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
            ₹{(ledger.estimated_paid_cost_inr || 0).toFixed(4)}
          </div>
          <div className="mt-0.5 text-[11px] text-muted">
            ${(ledger.estimated_paid_cost_usd || 0).toFixed(6)} USD
          </div>
        </div>

        <div className="border border-rule p-3">
          <div className="kicker text-[10px]">Total Calls</div>
          <div className="num mt-1 text-2xl font-semibold text-ink">{ledger.total_calls}</div>
          <div className="mt-0.5 text-[11px] text-muted">
            {ledger.live_calls} live · {ledger.cache_hits} cached
          </div>
        </div>

        <div className="border border-rule p-3">
          <div className="kicker text-[10px]">Total Tokens</div>
          <div className="num mt-1 text-2xl font-semibold text-ink">{totalTokens.toLocaleString()}</div>
          <div className="mt-0.5 text-[11px] text-muted">
            {ledger.in_tokens.toLocaleString()} in · {ledger.out_tokens.toLocaleString()} out ·{" "}
            {(ledger.thinking_tokens || 0).toLocaleString()} think
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
          <h2 className="font-serif text-lg font-semibold tracking-tight">Ledger Calls (Recent {ledger.recent.length} of {ledger.total_calls})</h2>
          <span className="font-mono text-xs text-muted">{ledger.total_calls} total in llm_ledger.jsonl</span>
        </div>

        <div tabIndex={0} className="table-wrapper border border-rule">
          <table className="text-left text-xs">
            <caption className="sr-only">Immutable LLM Call Ledger</caption>
            <thead className="border-b border-rule bg-paper-2 font-mono text-[10px] uppercase text-muted">
              <tr>
                <th scope="col" className="p-2">Timestamp</th>
                <th scope="col" className="p-2">Task</th>
                <th scope="col" className="p-2">Model</th>
                <th scope="col" className="p-2 text-right">Tokens (In / Out / Think)</th>
                <th scope="col" className="p-2 text-right">Latency</th>
                <th scope="col" className="p-2 text-right">Paid Eq.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule font-mono text-[11px]">
              {ledger.recent.map((entry, idx) => (
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
                    {entry.in_tokens.toLocaleString()} / {entry.out_tokens.toLocaleString()} / {(entry.thinking_tokens || 0).toLocaleString()}
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
