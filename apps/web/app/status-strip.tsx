"use client";

import { useEffect, useState } from "react";

type Health = { ok: boolean; db_configured: boolean; llm_configured: boolean; time: string };
type Company = { symbol: string; name: string; sector: string; mcap: string };
type Portfolio = { source: string; companies: Company[] };

export function StatusStrip() {
  const [health, setHealth] = useState<Health | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/v1/health").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch("/api/v1/portfolio").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
    ])
      .then(([h, p]) => {
        setHealth(h);
        setPortfolio(p);
      })
      .catch((e) => setError(`API unreachable (${e})`));
  }, []);

  return (
    <>
      <section className="flex flex-wrap gap-x-4 gap-y-1 border-b border-rule py-2 text-[12px]">
        <Chip label="API" value={error ? "down" : health ? "ok" : "…"} warn={!!error} />
        <Chip label="DB" value={health ? (health.db_configured ? "Neon" : "none") : "…"} warn={!!health && !health.db_configured} />
        <Chip label="LLM" value={health ? (health.llm_configured ? "key set" : "no key") : "…"} warn={!!health && !health.llm_configured} />
        <Chip label="Portfolio" value={portfolio ? (portfolio.source === "snapshot" ? "Snapshot" : "Live") : "…"} warn={portfolio?.source === "snapshot"} />
      </section>

      {error && <p className="py-3 text-[13px] text-signal">{error}</p>}

      {portfolio && (
        <section className="py-3">
          <div className="kicker pb-1">Portfolio · {portfolio.companies.length}</div>
          <ul>
            {portfolio.companies.map((c) => (
              <li key={c.symbol} className="flex items-baseline justify-between border-b border-rule py-[7px]">
                <span>
                  <span className="num text-[13px] font-medium">{c.symbol}</span>
                  <span className="ml-2 text-[13px] text-muted">{c.name}</span>
                </span>
                <span className="text-[12px] text-muted">{c.sector}</span>
              </li>
            ))}
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
