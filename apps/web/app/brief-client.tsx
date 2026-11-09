"use client";

import { useEffect, useId, useRef, useState } from "react";

interface NetworkHook {
  contact_id: string;
  name: string;
  headline: string;
  city?: string;
  strength: number;
  last_contacted?: string;
  recency: string;
  expertise_tags: string[];
  path: string;
  overlap_org?: string;
  overlap_tenure?: string;
  inferred_label: string;
  why_reasons: string[];
  draft_opener: string;
}

interface ResultsRow {
  metric: string;
  cur: number;
  prev_q: number;
  yoy_q: number;
  qoq_pct: number;
  yoy_pct: number;
  page: string;
  derived: boolean;
  verbatim_line?: string;
  screener_period?: string;
  screener_val?: number | null;
  screener_delta_pct?: number | null;
}

interface FilingDetails {
  kind?: "results" | "management_change";
  symbol?: string;
  period?: string;
  unit?: string;
  raw_filing_unit?: string;
  pdf_url?: string;
  pdf_sha256?: string;
  cited_page?: number;
  page_count?: number;
  filing_citation?: string;
  screener_url?: string;
  screener_period?: string;
  rows?: ResultsRow[];
  brief_profile_verbatim?: string;
  page_verbatim_excerpt?: string;
}

interface BriefItem {
  id: string;
  symbol: string;
  company_name: string;
  sector: string;
  mcap: string;
  in_portfolio: boolean;
  source: "nse" | "bse" | "demo";
  exchange: string;
  ts: string;
  subject: string;
  pdf_url?: string;
  category: string;
  category_label: string;
  cls_method: string;
  priority: number;
  summary_1l: string;
  is_demo_scenario?: boolean;
  details?: FilingDetails;
  price_context?: {
    as_of: string;
    close: number;
    change_pct: number;
    volume_multiple: number;
  } | null;
  network_hooks: NetworkHook[];
}

interface TriggeredAlert {
  id: string;
  symbol: string;
  company_name: string;
  in_portfolio: boolean;
  as_of: string;
  close: number;
  change_pct: number;
  volume_multiple: number;
  headline: string;
  reasons: string[];
  severity: number;
  linked_filing?: {
    id: string;
    ts: string;
    category: string;
    summary_1l: string;
    pdf_url?: string;
  } | null;
}

interface ReconnectNudge {
  contact_id: string;
  name: string;
  headline: string;
  strength: number;
  last_contacted: string;
  months_stale: number;
  symbol: string;
  company_name: string;
  role_at_company: string;
  filing_id: string;
  filing_summary: string;
  filing_ts: string;
  filing_pdf_url?: string;
  nudge_line: string;
  draft_opener: string;
  inferred_label: string;
}

interface BriefPayload {
  demo_clock: {
    mode: string;
    anchor_ts: string;
    anchor_date: string;
    default_ts: string;
    presets: Array<{ id: string; label: string; as_of: string; note: string }>;
  };
  freshness: {
    prices: { source: string; as_of: string; chip: string; count: number };
    announcements: {
      source: string;
      as_of: string;
      chip: string;
      total: number;
      material_count: number;
      routine_count: number;
    };
    llm_spend: {
      total_calls: number;
      cache_hits: number;
      actual_free_tier_spend_inr: number;
    };
  };
  window_hours: number;
  portfolio_only: boolean;
  alert_rules: {
    vol_mult_min: number;
    price_move_min: number;
    categories: string[];
  };
  triggered_alerts: TriggeredAlert[];
  ranked_material: BriefItem[];
  routine_summary: {
    count: number;
    company_count: number;
    headline: string;
    items: BriefItem[];
  };
  reconnect_nudges: ReconnectNudge[];
  deep_extracted_cards: BriefItem[];
}

const WINDOW_OPTIONS = [
  { label: "24h", hours: 24 },
  { label: "3d", hours: 72 },
  { label: "7d", hours: 168 },
  { label: "14d", hours: 336 },
  { label: "45d", hours: 1080 },
];

function attachLightDismissFallback(dialog: HTMLDialogElement | null, onClose: () => void) {
  if (!dialog) return () => {};
  const handleClose = () => onClose();
  dialog.addEventListener("close", handleClose);

  // Fallback for browsers without native `<dialog closedby="any">` support (e.g. Safari)
  let handleBackdropClick: ((event: MouseEvent) => void) | null = null;
  if (typeof HTMLDialogElement !== "undefined" && !("closedBy" in HTMLDialogElement.prototype)) {
    handleBackdropClick = (event: MouseEvent) => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      const isDialogContent =
        rect.top <= event.clientY &&
        event.clientY <= rect.top + rect.height &&
        rect.left <= event.clientX &&
        event.clientX <= rect.left + rect.width;
      if (isDialogContent) return;
      dialog.close();
    };
    dialog.addEventListener("click", handleBackdropClick);
  }

  return () => {
    dialog.removeEventListener("close", handleClose);
    if (handleBackdropClick) {
      dialog.removeEventListener("click", handleBackdropClick);
    }
  };
}

function formatTsShort(iso: string): string {
  if (!iso) return "";
  const d = iso.slice(0, 10);
  const t = iso.slice(11, 16);
  return `${d} · ${t} IST`;
}

export function BriefClient() {
  const [windowHours, setWindowHours] = useState<number>(24);
  const [asOf, setAsOf] = useState<string>("2026-11-06T23:59:59+05:30");
  const [volMultMin, setVolMultMin] = useState<number>(2.0);
  const [priceMoveMin, setPriceMoveMin] = useState<number>(2.5);
  const [portfolioOnly, setPortfolioOnly] = useState<boolean>(false);

  const [data, setData] = useState<BriefPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [routineOpen, setRoutineOpen] = useState<boolean>(false);
  const [activeCard, setActiveCard] = useState<BriefItem | null>(null);
  const [rulesModalOpen, setRulesModalOpen] = useState<boolean>(false);
  const [expandedHookId, setExpandedHookId] = useState<string | null>(null);

  const cardDialogRef = useRef<HTMLDialogElement | null>(null);
  const rulesDialogRef = useRef<HTMLDialogElement | null>(null);

  const cardDialogTitleId = useId();
  const rulesDialogTitleId = useId();
  const resultsTableCaptionId = useId();

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      window_hours: String(windowHours),
      as_of: asOf,
      vol_mult_min: String(volMultMin),
      price_move_min: String(priceMoveMin),
      portfolio_only: String(portfolioOnly),
    });

    fetch(`/api/v1/brief?${params.toString()}`, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return (await res.json()) as BriefPayload;
      })
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setError(null);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load brief");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [windowHours, asOf, volMultMin, priceMoveMin, portfolioOnly]);

  useEffect(() => {
    const dialog = cardDialogRef.current;
    if (!dialog) return;
    if (activeCard && !dialog.open) {
      dialog.showModal();
    } else if (!activeCard && dialog.open) {
      dialog.close();
    }
    return attachLightDismissFallback(dialog, () => setActiveCard(null));
  }, [activeCard]);

  useEffect(() => {
    const dialog = rulesDialogRef.current;
    if (!dialog) return;
    if (rulesModalOpen && !dialog.open) {
      dialog.showModal();
    } else if (!rulesModalOpen && dialog.open) {
      dialog.close();
    }
    return attachLightDismissFallback(dialog, () => setRulesModalOpen(false));
  }, [rulesModalOpen]);

  const resultsSpotlights = (data?.deep_extracted_cards ?? []).filter(
    (c) => c.details?.kind === "results",
  );
  const mgmtSpotlights = (data?.deep_extracted_cards ?? []).filter(
    (c) => c.details?.kind === "management_change" && c.details?.brief_profile_verbatim?.toLowerCase().includes("brief profile"),
  );

  return (
    <div className="space-y-5 pb-12">
      {/* Top Freshness & Demo-Clock Control Bar */}
      <section aria-label="Data freshness and demo clock" className="border-b border-rule pb-3 pt-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 border border-rule bg-paper-2 px-2 py-0.5 font-mono text-[11px]">
              <span className="h-1.5 w-1.5 rounded-full bg-up" />
              {data?.freshness.prices.chip ?? "Prices · EOD 2026-11-06"}
            </span>
            <span className="inline-flex items-center gap-1 border border-rule bg-paper-2 px-2 py-0.5 font-mono text-[11px] text-amber">
              {data?.freshness.announcements.source === "neon" ? "Neon DB" : "Snapshot"} ·{" "}
              {data?.freshness.announcements.total ?? 776} real NSE/BSE PDFs
            </span>
          </div>
          <span className="num text-[11px] text-muted">
            LLM spend: ₹{(data?.freshness.llm_spend.actual_free_tier_spend_inr ?? 0).toFixed(2)}
          </span>
        </div>

        {/* Demo Clock selector */}
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border border-rule bg-paper-2 px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="kicker">Demo Clock</span>
            <select
              aria-label="Select demo clock anchor date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="border border-rule bg-paper px-2 py-1 font-mono text-xs text-ink"
            >
              {(data?.demo_clock.presets ?? [
                {
                  id: "frozen_nov06",
                  label: "Frozen · 6 Nov 2026 (Default)",
                  as_of: "2026-11-06T23:59:59+05:30",
                  note: "",
                },
              ]).map((p) => (
                <option key={p.id} value={p.as_of}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {/* Window Scrubber */}
          <div className="flex items-center gap-1" role="group" aria-label="Digest time window">
            {WINDOW_OPTIONS.map((opt) => {
              const active = windowHours === opt.hours;
              return (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => setWindowHours(opt.hours)}
                  className={`px-2 py-0.5 font-mono text-xs transition-colors ${
                    active
                      ? "bg-ink text-paper font-medium"
                      : "border border-rule bg-paper text-ink-2 hover:border-ink"
                  }`}
                >
                  {opt.label}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => setPortfolioOnly((v) => !v)}
              className={`ml-1 px-2 py-0.5 font-mono text-[11px] ${
                portfolioOnly
                  ? "bg-accent text-paper"
                  : "border border-rule bg-paper text-muted hover:text-ink"
              }`}
              title="Toggle between 18 portfolio holdings only vs all 22 tracked companies"
            >
              {portfolioOnly ? "18 Holdings" : "All 22"}
            </button>
          </div>
        </div>
      </section>

      {error && (
        <div className="border border-signal bg-paper-2 p-3 text-xs text-signal">
          API unreachable ({error}) — retry or check snapshot fallback.
        </div>
      )}

      {/* [S1 / S4] Triggered EOD Alerts Strip */}
      <section aria-label="Triggered alerts" className="space-y-2 border-b border-rule pb-4">
        <div className="flex items-center justify-between">
          <span className="kicker">
            Triggered Market Alerts · Session {data?.demo_clock.anchor_date ?? "2026-11-06"}
          </span>
          <button
            type="button"
            onClick={() => setRulesModalOpen(true)}
            className="border border-rule bg-paper-2 px-2 py-0.5 font-mono text-[11px] text-accent underline-offset-2 hover:underline"
          >
            Rule: ≥{volMultMin.toFixed(1)}× vol, ±{priceMoveMin.toFixed(1)}% · Tune
          </button>
        </div>

        {loading && !data ? (
          <p className="text-xs text-muted">Evaluating price & volume rules…</p>
        ) : (data?.triggered_alerts.length ?? 0) === 0 ? (
          <p className="text-xs text-muted">
            No holdings crossed ≥{volMultMin.toFixed(1)}× volume or ±{priceMoveMin.toFixed(1)}% on{" "}
            {data?.demo_clock.anchor_date}. Tap &ldquo;Tune&rdquo; to adjust thresholds.
          </p>
        ) : (
          <div className="space-y-1.5">
            {data?.triggered_alerts.slice(0, 4).map((al) => (
              <div
                key={al.id}
                className="flex flex-col justify-between gap-1 border-l-2 border-signal bg-paper-2 px-3 py-2 text-xs sm:flex-row sm:items-center"
              >
                <div>
                  <span className="num font-medium text-ink">{al.headline}</span>
                  <span className="ml-2 text-muted">({al.company_name})</span>
                  {al.linked_filing && (
                    <div className="mt-0.5 text-[11px] text-ink-2">
                      Latest filing ({al.linked_filing.ts.slice(0, 10)}): {al.linked_filing.summary_1l}
                      {al.linked_filing.pdf_url && (
                        <a
                          href={al.linked_filing.pdf_url}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-1.5 font-mono text-accent underline"
                        >
                          PDF ↗
                        </a>
                      )}
                    </div>
                  )}
                </div>
                <span className="num text-[11px] text-muted">Close ₹{al.close.toLocaleString("en-IN")}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Deep-Extracted PDF Cards Quick Bar (S2 & S3 Instant Access) */}
      {(resultsSpotlights.length > 0 || mgmtSpotlights.length > 0) && (
        <section aria-label="Deep extracted PDF cards" className="space-y-2 border-b border-rule pb-4">
          <div className="flex items-baseline justify-between">
            <span className="kicker">Live PDF Extractions · Results vs Screener & Verbatim KMP Bios</span>
            <span className="font-mono text-[11px] text-muted">Tap to open [S2] / [S3]</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {resultsSpotlights.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setExpandedHookId(null);
                  setActiveCard(item);
                }}
                className="flex flex-col justify-between border border-rule bg-paper-2 p-2.5 text-left transition-colors hover:border-ink"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold text-accent">
                    [S3] {item.symbol} · Q2 Results PDF
                  </span>
                  <span className="border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] uppercase">
                    {item.source} · p.{item.details?.cited_page}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-2">
                  {item.company_name} ({item.details?.period}) · Cross-checked vs Screener.in
                </p>
              </button>
            ))}
            {mgmtSpotlights.slice(0, 4).map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setExpandedHookId(null);
                  setActiveCard(item);
                }}
                className="flex flex-col justify-between border border-rule bg-paper-2 p-2.5 text-left transition-colors hover:border-ink"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold text-signal">
                    [S2] {item.symbol} · KMP / Board PDF
                  </span>
                  <span className="border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] uppercase">
                    {item.source} · p.{item.details?.cited_page}
                  </span>
                </div>
                <p className="mt-1 line-clamp-1 text-xs text-ink-2">{item.summary_1l}</p>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* [S1] Ranked Material Filings in Active Window */}
      <section aria-label="Prioritised material filings" className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="kicker">
            Material Filings ({data?.ranked_material.length ?? 0}) · Window {windowHours}h as of{" "}
            {data?.demo_clock.anchor_date ?? "2026-11-06"}
          </h2>
          <span className="font-mono text-[11px] text-muted">Ranked by priority 0–100</span>
        </div>

        {(data?.ranked_material.length ?? 0) === 0 ? (
          <div className="border border-rule bg-paper-2 p-4 text-xs text-muted">
            No material filings (priority ≥ 50) in this {windowHours}h window. Expand the window to{" "}
            <button
              type="button"
              onClick={() => setWindowHours(168)}
              className="font-mono text-accent underline"
            >
              7d
            </button>{" "}
            or{" "}
            <button
              type="button"
              onClick={() => setWindowHours(1080)}
              className="font-mono text-accent underline"
            >
              45d
            </button>{" "}
            to inspect earlier filings.
          </div>
        ) : (
          <div className="divide-y divide-rule border-t border-b border-rule">
            {data?.ranked_material.map((item) => {
              const hasDeepCard = Boolean(item.details?.kind);
              const topHook = item.network_hooks?.[0];
              return (
                <article key={item.id} className="space-y-2 py-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-mono font-semibold text-ink">{item.symbol}</span>
                      <span className="text-muted">· {item.company_name}</span>
                      <span
                        className={`border px-1.5 py-0.5 font-mono text-[10px] uppercase ${
                          item.source === "demo"
                            ? "border-amber text-amber"
                            : "border-rule bg-paper-2 text-ink-2"
                        }`}
                      >
                        {item.source}
                      </span>
                      <span className="border border-rule px-1.5 py-0.5 font-mono text-[10px] text-ink-2">
                        {item.category_label} · P{item.priority}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
                      {item.price_context && (
                        <span>
                          ₹{item.price_context.close.toLocaleString("en-IN")} (
                          <span
                            className={
                              item.price_context.change_pct >= 0 ? "text-up" : "text-down"
                            }
                          >
                            {item.price_context.change_pct >= 0 ? "+" : ""}
                            {item.price_context.change_pct.toFixed(2)}%
                          </span>
                          )
                        </span>
                      )}
                      <span>{formatTsShort(item.ts)}</span>
                    </div>
                  </div>

                  <h3 className="font-serif text-[18px] leading-snug text-ink">
                    {item.summary_1l}
                  </h3>

                  <p className="text-xs text-ink-2">{item.subject}</p>

                  {/* Action & Citation Row */}
                  <div className="flex flex-wrap items-center gap-3 pt-0.5 text-xs">
                    {item.pdf_url && (
                      <a
                        href={item.pdf_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-accent underline underline-offset-2"
                      >
                        Official {item.exchange} PDF ↗
                      </a>
                    )}
                    {hasDeepCard && (
                      <button
                        type="button"
                        onClick={() => {
                          setExpandedHookId(null);
                          setActiveCard(item);
                        }}
                        className="border border-ink bg-ink px-2.5 py-1 font-mono text-xs text-paper hover:opacity-90"
                      >
                        {item.details?.kind === "results"
                          ? `Open Results Card (${item.details.filing_citation}) →`
                          : `Open Verbatim Bio (${item.details?.filing_citation}) →`}
                      </button>
                    )}
                  </div>

                  {/* Woven-in Network Hook Preview */}
                  {topHook && (
                    <div className="mt-1.5 border-l-2 border-accent bg-paper-2 px-3 py-2 text-xs">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-mono text-[11px] text-ink">
                          <strong className="font-semibold">Who to call:</strong> {topHook.path}
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setExpandedHookId(topHook.contact_id);
                            setActiveCard(item);
                          }}
                          className="font-mono text-[11px] text-accent underline"
                        >
                          Why {topHook.name.split(" ")[0]} + Opener →
                        </button>
                      </div>
                      <p className="mt-0.5 font-mono text-[10px] text-amber">
                        {topHook.inferred_label}
                      </p>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {/* Collapsed Routine Filings Drawer — never hides routine disclosures */}
        {data && data.routine_summary.count > 0 && (
          <div className="border border-rule bg-paper-2">
            <button
              type="button"
              onClick={() => setRoutineOpen((o) => !o)}
              aria-expanded={routineOpen}
              className="flex w-full items-center justify-between px-3 py-2.5 text-left font-mono text-xs text-ink-2 hover:text-ink"
            >
              <span>{data.routine_summary.headline}</span>
              <span className="text-accent">{routineOpen ? "Collapse −" : "Inspect all +"}</span>
            </button>

            {routineOpen && (
              <div className="divide-y divide-rule border-t border-rule bg-paper px-3 py-2">
                {data.routine_summary.items.map((r) => (
                  <div
                    key={r.id}
                    className="flex flex-col justify-between gap-1 py-2 text-xs sm:flex-row sm:items-center"
                  >
                    <div>
                      <span className="font-mono font-medium text-ink">{r.symbol}</span>
                      <span className="ml-1.5 border border-rule px-1 py-0.5 font-mono text-[10px] uppercase text-muted">
                        {r.source} · {r.category_label} · P{r.priority}
                      </span>
                      <p className="mt-0.5 text-ink-2">{r.subject}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2 font-mono text-[11px]">
                      <span className="text-muted">{formatTsShort(r.ts)}</span>
                      {r.pdf_url && (
                        <a
                          href={r.pdf_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent underline"
                        >
                          PDF ↗
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* [S1] Reconnect Nudges */}
      {data && data.reconnect_nudges.length > 0 && (
        <section aria-label="Network reconnect nudges" className="space-y-2 border-t border-rule pt-4">
          <div className="flex items-baseline justify-between">
            <span className="kicker">Reconnect · Stale Relationships Warmed by Filings</span>
            <span className="font-mono text-[10px] text-amber">
              inferred from employer/tenure overlap, synthetic network
            </span>
          </div>
          <div className="space-y-2">
            {data.reconnect_nudges.map((nudge) => (
              <div key={nudge.contact_id} className="border border-rule bg-paper-2 p-3 text-xs">
                <p className="font-serif text-[15px] text-ink">{nudge.nudge_line}</p>
                <p className="mt-1 text-muted">
                  {nudge.headline} · Role: {nudge.role_at_company} · Last spoke: {nudge.last_contacted}
                </p>
                <div className="mt-2 border-l-2 border-rule pl-2.5 font-mono text-[11px] text-ink-2">
                  Draft opener: &ldquo;{nudge.draft_opener}&rdquo;
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* [S2 & S3] Modal Dialog for Results Card & Management-Change Card */}
      <dialog
        ref={cardDialogRef}
        {...({ closedby: "any" } as Record<string, unknown>)}
        aria-labelledby={cardDialogTitleId}
      >
        {activeCard && (
          <div className="space-y-4 p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3 border-b border-rule pb-3">
              <div>
                <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
                  <span className="font-semibold text-ink">{activeCard.symbol}</span>
                  <span className="text-muted">· {activeCard.company_name}</span>
                  <span className="border border-rule bg-paper-2 px-1.5 py-0.5 text-[10px] uppercase">
                    {activeCard.source}
                  </span>
                  <span className="text-muted">{formatTsShort(activeCard.ts)}</span>
                </div>
                <h2 id={cardDialogTitleId} className="mt-1 font-serif text-[20px] leading-snug text-ink">
                  {activeCard.summary_1l}
                </h2>
              </div>
              <form method="dialog">
                <button
                  type="submit"
                  className="border border-rule bg-paper-2 px-2.5 py-1 font-mono text-xs text-ink hover:border-ink"
                >
                  Close [Esc]
                </button>
              </form>
            </div>

            {/*Provenance & PDF link bar */}
            <div className="flex flex-wrap items-center justify-between gap-2 border border-rule bg-paper-2 px-3 py-2 font-mono text-xs">
              <div>
                <span className="text-ink-2">
                  Cite: <strong>{activeCard.details?.filing_citation ?? "Exchange Filing PDF"}</strong>
                </span>
                {activeCard.details?.pdf_sha256 && (
                  <span className="ml-2 text-[11px] text-muted">
                    SHA256: {activeCard.details.pdf_sha256.slice(0, 12)}…
                  </span>
                )}
              </div>
              {activeCard.pdf_url && (
                <a
                  href={activeCard.pdf_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent underline"
                >
                  Open Original {activeCard.exchange} PDF ↗
                </a>
              )}
            </div>

            {/* [S3] Results Card Table */}
            {activeCard.details?.kind === "results" && activeCard.details.rows && (
              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="font-mono text-ink-2">
                    All figures normalized to <strong>{activeCard.details.unit}</strong> (raw PDF unit:{" "}
                    <code>{activeCard.details.raw_filing_unit}</code>)
                  </span>
                  {activeCard.details.screener_url && (
                    <a
                      href={activeCard.details.screener_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-accent underline"
                    >
                      Cross-checked vs Screener.in ({activeCard.details.screener_period}) ↗
                    </a>
                  )}
                </div>

                <div
                  tabIndex={0}
                  role="region"
                  aria-labelledby={resultsTableCaptionId}
                  className="table-wrapper border border-rule"
                >
                  <table className="text-left text-xs">
                    <caption id={resultsTableCaptionId} className="sr-only">
                      {activeCard.company_name} quarterly financial results extracted from filing PDF and cross-checked against Screener.in
                    </caption>
                    <thead>
                      <tr className="border-b border-rule font-mono text-[11px] uppercase text-muted">
                        <th scope="col" className="px-3 py-2">
                          Metric
                        </th>
                        <th scope="col" className="px-3 py-2 text-right">
                          This Q (PDF)
                        </th>
                        <th scope="col" className="px-3 py-2 text-right">
                          QoQ %
                        </th>
                        <th scope="col" className="px-3 py-2 text-right">
                          YoY %
                        </th>
                        <th scope="col" className="px-3 py-2 text-right">
                          Screener.in
                        </th>
                        <th scope="col" className="px-3 py-2 text-right">
                          Cross-Check
                        </th>
                        <th scope="col" className="px-3 py-2">
                          Source Page
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-rule">
                      {activeCard.details.rows.map((row) => {
                        const delta = row.screener_delta_pct;
                        const mismatch = delta !== null && delta !== undefined && Math.abs(delta) > 1.0;
                        return (
                          <tr key={row.metric}>
                            <th scope="row" className="px-3 py-2 font-mono font-semibold text-ink">
                              {row.metric}
                              {row.derived && (
                                <span
                                  title={row.verbatim_line ?? "Derived from PDF lines"}
                                  className="ml-1.5 border border-amber px-1 py-0.5 text-[10px] font-normal text-amber"
                                >
                                  derived
                                </span>
                              )}
                            </th>
                            <td className="num px-3 py-2 text-right font-medium text-ink">
                              ₹{row.cur.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td
                              className={`num px-3 py-2 text-right ${
                                row.qoq_pct >= 0 ? "text-up" : "text-down"
                              }`}
                            >
                              {row.qoq_pct >= 0 ? "+" : ""}
                              {row.qoq_pct.toFixed(1)}%
                            </td>
                            <td
                              className={`num px-3 py-2 text-right ${
                                row.yoy_pct >= 0 ? "text-up" : "text-down"
                              }`}
                            >
                              {row.yoy_pct >= 0 ? "+" : ""}
                              {row.yoy_pct.toFixed(1)}%
                            </td>
                            <td className="num px-3 py-2 text-right text-ink-2">
                              {row.screener_val !== null && row.screener_val !== undefined
                                ? `₹${row.screener_val.toLocaleString("en-IN")}`
                                : "—"}
                            </td>
                            <td className="num px-3 py-2 text-right">
                              {delta === null || delta === undefined ? (
                                <span className="text-muted">n/a</span>
                              ) : mismatch ? (
                                <span className="border border-amber bg-paper-2 px-1.5 py-0.5 text-[11px] text-amber">
                                  Δ {delta > 0 ? "+" : ""}
                                  {delta.toFixed(2)}% vs screener
                                </span>
                              ) : (
                                <span className="text-up">✓ Match ({delta.toFixed(2)}%)</span>
                              )}
                            </td>
                            <td className="px-3 py-2 font-mono text-[11px] text-muted">{row.page}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Verbatim extracted PDF lines */}
                <details className="border border-rule bg-paper-2 p-2.5 text-xs">
                  <summary className="cursor-pointer font-mono text-[11px] text-ink-2">
                    Inspect verbatim extracted PDF rows (p.{activeCard.details.cited_page})
                  </summary>
                  <div className="mt-2 space-y-1 font-mono text-[11px] text-muted">
                    {activeCard.details.rows.map((r) => (
                      <div key={r.metric}>
                        <strong className="text-ink">{r.metric}:</strong> {r.verbatim_line}
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}

            {/* [S2] Management-Change Verbatim Bio */}
            {activeCard.details?.kind === "management_change" && (
              <div className="space-y-3">
                <div>
                  <span className="kicker">
                    Who They Are · Verbatim from SEBI LODR Filing ({activeCard.details.filing_citation})
                  </span>
                  <pre className="mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap border border-rule bg-paper-2 p-3 font-sans text-xs leading-relaxed text-ink">
                    {activeCard.details.brief_profile_verbatim || activeCard.details.page_verbatim_excerpt}
                  </pre>
                </div>
              </div>
            )}

            {/* Woven-in Network Section ("Who to Call") */}
            <div className="space-y-2.5 border-t border-rule pt-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="kicker">Who to Call · Deterministic Network Overlap</span>
                <span className="font-mono text-[10px] text-amber">
                  inferred from employer/tenure overlap, synthetic network
                </span>
              </div>

              {activeCard.network_hooks.length === 0 ? (
                <p className="text-xs text-muted">
                  No direct or prior-employer overlap found in your synthetic network for this filing.
                </p>
              ) : (
                <div className="space-y-2">
                  {activeCard.network_hooks.map((hook) => {
                    const isExpanded =
                      expandedHookId === hook.contact_id || activeCard.network_hooks[0]?.contact_id === hook.contact_id;
                    return (
                      <div key={hook.contact_id} className="border border-rule bg-paper-2 p-3 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono font-semibold text-ink">{hook.path}</span>
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedHookId(isExpanded ? null : hook.contact_id)
                            }
                            className="font-mono text-[11px] text-accent underline"
                          >
                            {isExpanded ? "Hide details" : `Why ${hook.name.split(" ")[0]}`}
                          </button>
                        </div>
                        <p className="mt-0.5 font-mono text-[10px] text-amber">{hook.inferred_label}</p>

                        {isExpanded && (
                          <div className="mt-2.5 space-y-2 border-t border-rule pt-2">
                            <ul className="list-disc space-y-1 pl-4 text-ink-2">
                              {hook.why_reasons.map((reason, idx) => (
                                <li key={idx}>{reason}</li>
                              ))}
                            </ul>
                            <div className="border-l-2 border-accent bg-paper px-2.5 py-2 font-mono text-[11px] text-ink">
                              <div className="text-[10px] uppercase text-muted">
                                Deterministic 2-line opener (zero LLM sees network):
                              </div>
                              <p className="mt-0.5">&ldquo;{hook.draft_opener}&rdquo;</p>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </dialog>

      {/* [S4] Alert Rules Modal Dialog */}
      <dialog
        ref={rulesDialogRef}
        {...({ closedby: "any" } as Record<string, unknown>)}
        aria-labelledby={rulesDialogTitleId}
      >
        <div className="space-y-4 p-4 sm:p-5">
          <div className="flex items-center justify-between border-b border-rule pb-2.5">
            <h2 id={rulesDialogTitleId} className="font-serif text-[20px] text-ink">
              [S4] Triggered Alert Thresholds
            </h2>
            <form method="dialog">
              <button
                type="submit"
                className="border border-rule bg-paper-2 px-2.5 py-1 font-mono text-xs text-ink"
              >
                Done
              </button>
            </form>
          </div>

          <div className="space-y-4 text-xs">
            <div>
              <label htmlFor="vol-slider" className="flex justify-between font-mono text-ink">
                <span>Minimum Volume Multiple (vs 20-day avg)</span>
                <span className="num font-semibold text-accent">≥ {volMultMin.toFixed(1)}×</span>
              </label>
              <input
                id="vol-slider"
                type="range"
                min={1.2}
                max={5.0}
                step={0.1}
                value={volMultMin}
                onChange={(e) => setVolMultMin(parseFloat(e.target.value))}
                className="mt-1.5 w-full accent-accent"
              />
              <div className="flex justify-between font-mono text-[10px] text-muted">
                <span>1.2× (sensitive)</span>
                <span>2.0× (default)</span>
                <span>5.0× (extreme spikes only)</span>
              </div>
            </div>

            <div>
              <label htmlFor="price-slider" className="flex justify-between font-mono text-ink">
                <span>Minimum Absolute EOD Price Move</span>
                <span className="num font-semibold text-accent">± {priceMoveMin.toFixed(1)}%</span>
              </label>
              <input
                id="price-slider"
                type="range"
                min={1.0}
                max={8.0}
                step={0.5}
                value={priceMoveMin}
                onChange={(e) => setPriceMoveMin(parseFloat(e.target.value))}
                className="mt-1.5 w-full accent-accent"
              />
              <div className="flex justify-between font-mono text-[10px] text-muted">
                <span>±1.0%</span>
                <span>±2.5% (default)</span>
                <span>±8.0%</span>
              </div>
            </div>
          </div>
        </div>
      </dialog>
    </div>
  );
}
