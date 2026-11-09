"use client";

import { useEffect, useState } from "react";

type Company = { symbol: string; name: string; sector: string; mcap: string };
type Portfolio = { source: string; companies: Company[]; research?: Company[] };
type PriceRow = {
  symbol: string;
  as_of: string;
  close: number;
  change_pct: number;
  volume_multiple: number;
};
type PricesResp = { source: string; as_of: string; freshness_chip: string; prices: Record<string, PriceRow> };
type FreshnessResp = {
  db_configured: boolean;
  llm_configured: boolean;
  prices: { chip: string; count: number };
  announcements: {
    chip: string;
    total: number;
    material_count: number;
    routine_count: number;
    exchange_probe_summary?: string;
  };
  models: { bulk_model: string; strong_model: string };
  llm_spend: { total_calls: number; cache_hits: number; actual_free_tier_spend_inr: number };
};

export function StatusStrip() {
  const [freshness, setFreshness] = useState<FreshnessResp | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [prices, setPrices] = useState<PricesResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/v1/freshness").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch("/api/v1/portfolio").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch("/api/v1/prices").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
    ])
      .then(([f, p, pr]) => {
        setFreshness(f);
        setPortfolio(p);
        setPrices(pr);
      })
      .catch((e) => setError(`API unreachable (${e})`));
  }, []);

  return (
    <>
      <section className="flex flex-wrap gap-x-4 gap-y-1 border-b border-rule py-2 text-[12px]">
        <Chip
          label="Prices"
          value={freshness ? freshness.prices.chip.replace("Prices · ", "") : "…"}
          warn={prices?.source === "snapshot"}
        />
        <Chip
          label="Filings"
          value={
            freshness
              ? `${freshness.announcements.material_count} material · ${freshness.announcements.routine_count} routine`
              : "…"
          }
          warn={true}
        />
        <Chip
          label="Models"
          value={freshness ? `${freshness.models.bulk_model} / ${freshness.models.strong_model}` : "…"}
        />
        <Chip
          label="LLM spend"
          value={freshness ? `₹${freshness.llm_spend.actual_free_tier_spend_inr.toFixed(2)}` : "…"}
        />
      </section>

      {freshness?.announcements.exchange_probe_summary && (
        <section className="border-b border-rule py-1.5 text-[11px] text-muted">
          Live exchange probe: <span className="num text-ink">{freshness.announcements.exchange_probe_summary}</span>
        </section>
      )}

      {error && <p className="py-3 text-[13px] text-signal">{error}</p>}

      {portfolio && (
        <section className="py-3">
          <div className="flex items-baseline justify-between pb-1">
            <span className="kicker">Portfolio · {portfolio.companies.length} holdings</span>
            <span className="kicker">Close · 1D · Vol/20D</span>
          </div>
          <ul>
            {portfolio.companies.map((c) => {
              const pr = prices?.prices?.[c.symbol];
              const chg = pr?.change_pct ?? 0;
              const chgColor = chg > 0 ? "text-up" : chg < 0 ? "text-down" : "text-muted";
              const volWarn = (pr?.volume_multiple ?? 1) >= 2.0;
              return (
                <li
                  key={c.symbol}
                  className="flex items-baseline justify-between border-b border-rule py-[7px]"
                >
                  <div className="min-w-0 pr-2">
                    <span className="num text-[13px] font-medium">{c.symbol}</span>
                    <span className="ml-2 truncate text-[13px] text-muted">{c.name}</span>
                  </div>
                  {pr ? (
                    <div className="num shrink-0 text-[12px]">
                      <span>₹{pr.close.toLocaleString("en-IN")}</span>
                      <span className={`ml-2 ${chgColor}`}>
                        {chg > 0 ? `+${chg.toFixed(1)}%` : `${chg.toFixed(1)}%`}
                      </span>
                      <span className={`ml-2 ${volWarn ? "font-semibold text-amber" : "text-muted"}`}>
                        {pr.volume_multiple.toFixed(1)}×
                      </span>
                    </div>
                  ) : (
                    <span className="text-[12px] text-muted">{c.sector}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
}

function Chip({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <span>
      <span className="text-muted">{label}</span>{" "}
      <span className={warn ? "text-amber" : "text-ink"}>{value}</span>
    </span>
  );
}
