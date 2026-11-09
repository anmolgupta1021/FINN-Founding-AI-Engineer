"use client";

import { useEffect, useId, useRef, useState } from "react";

interface NetworkHook {
  contact_id: string;
  name: string;
  headline: string;
  city?: string;
  degree?: number;
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
  status?: "reported" | "derived" | "unreliable";
  margin_pct?: number | null;
  verbatim_line?: string;
  screener_period?: string;
  screener_val?: number | null;
  screener_delta_pct?: number | null;
}

interface FilingDetails {
  kind?: "results" | "management_change";
  symbol?: string;
  period?: string;
  is_lender?: boolean;
  lender_note?: string | null;
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

interface NetworkAskResponse {
  query: string;
  count: number;
  total_contacts: number;
  total_links: number;
  inferred_label: string;
  privacy_guarantee: string;
  results: Array<
    NetworkHook & {
      score?: number;
      education?: Array<{ school: string; degree: string; year: number }>;
    }
  >;
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

interface VerbatimCitation {
  verified: boolean;
  doc_id: string;
  doc_label: string;
  doc_type?: string;
  pdf_url?: string;
  page: number;
  verbatim_quote: string;
  match_score: number;
  status: string;
}

interface DossierNetworkContact {
  contact_id: string;
  name: string;
  headline: string;
  city?: string;
  strength: number;
  degree: number;
  recency: string;
  bucket: string;
  org: string;
  role?: string;
  tenure: string;
  relation_label: string;
  path: string;
  expertise_tags: string[];
  diligence_prompt: string;
  draft_opener: string;
  inferred_label: string;
}

interface CompanyDossier {
  symbol: string;
  company_name: string;
  sector: string;
  bucket: string;
  is_lender: boolean;
  ebitda_policy_note: string;
  generated_at: string;
  freshness: string;
  primary_sources_only: boolean;
  screener_url?: string;
  business_model_1l: string;
  executive_summary: string;
  documents_manifest: Array<{
    doc_id: string;
    label: string;
    date_label?: string;
    doc_type: string;
    is_latest_call?: boolean;
    pdf_url: string;
    size_kb: number;
    page_count: number;
    doctype_check?: {
      is_transcript: boolean;
      distinct_speaker_count: number;
      speaker_turn_count: number;
      has_qa: boolean;
      promised_vs_delivered_testable: boolean;
      promised_vs_delivered_note: string;
    };
  }>;
  financial_trajectory: {
    is_lender: boolean;
    summary_stats: {
      is_lender: boolean;
      ebitda_label: string;
      revenue_cagr_pct?: number;
      pat_cagr_pct?: number;
      cumulative_5y_cfo_cr?: number;
      cumulative_5y_pat_cr?: number;
      cumulative_5y_cfo_to_pat_pct?: number;
    };
    annual_5y: Array<{
      period: string;
      revenue_cr?: number | null;
      revenue_or_nii_cr?: number | null;
      ebitda_derived_cr?: number | null;
      ebitda_margin_derived_pct?: number | null;
      ppop_or_financing_profit_cr?: number | null;
      financing_margin_pct?: number | null;
      ebitda_status: string;
      pbt_cr?: number | null;
      pat_cr?: number | null;
      cfo_cr?: number | null;
      cfo_to_pat_pct?: number | null;
      roce_pct?: number | null;
      roce_or_roe_pct?: number | null;
    }>;
  };
  segment_mix: Array<{
    segment: string;
    share_or_metric: string;
    citation: VerbatimCitation;
  }>;
  promised_vs_delivered: Array<{
    period_called: string;
    is_latest_call: boolean;
    promised_vs_delivered_testable: boolean;
    topic: string;
    promised_guidance: string;
    promised_citation: VerbatimCitation;
    delivered_summary: string;
    delivered_citation?: VerbatimCitation | null;
    verdict: string;
  }>;
  numbers_vs_narrative: Array<{
    check_title: string;
    numbers_observed: string;
    narrative_claimed: string;
    verdict: string;
    citation: VerbatimCitation;
  }>;
  bull_case: Array<{
    title: string;
    thesis: string;
    citation: VerbatimCitation;
  }>;
  bear_case: Array<{
    title: string;
    thesis: string;
    citation: VerbatimCitation;
  }>;
  unanswered_diligence_questions: Array<{
    topic: string;
    status: string;
    question_for_management_or_network: string;
  }>;
  network: {
    symbol: string;
    company_name: string;
    inferred_label: string;
    privacy_guarantee: string;
    ex_company: DossierNetworkContact[];
    competitors: DossierNetworkContact[];
    suppliers_customers: DossierNetworkContact[];
    total_matched: number;
  };
  verification_summary: {
    total_documents_verified: number;
    concall_transcripts_verified: number;
    latest_call_marked_untestable: boolean;
    total_verified_citations: number;
    min_rapidfuzz_score: number;
    quote_verification_rule: string;
  };
}

interface PullJobState {
  job_id: string;
  symbol: string;
  status: "running" | "completed" | "failed";
  step: string;
  progress_pct: number;
  steps_log?: Array<{ ts: string; step: string; progress_pct: number }>;
  error?: string | null;
}

const DEMO_DOSSIER_SYMBOLS = [
  { symbol: "DIXON", label: "DIXON · Demo #1 (EMS)" },
  { symbol: "SYRMA", label: "SYRMA · Demo #2 (EMS)" },
  { symbol: "NAVINFLUOR", label: "NAVINFLUOR · Demo #3 (Fluorochem)" },
  { symbol: "POLYCAB", label: "POLYCAB · Demo #4 (Cables & FMEG)" },
];

const GENERALISATION_DOSSIER_SYMBOLS = [
  { symbol: "HDFCBANK", label: "HDFCBANK · Unseen Lender Path (No EBITDA)" },
  { symbol: "TITAN", label: "TITAN · Unseen Consumer Discretionary" },
];

const NETWORK_QUICK_QUERIES = [
  "specialty chemicals",
  "ICICI Bank",
  "Cummins",
  "Cohance",
  "EMS working capital",
  "IIT Kanpur",
  "microfinance PAR 30",
];

export function BriefClient() {
  const [windowHours, setWindowHours] = useState<number>(24);
  const [asOf, setAsOf] = useState<string>("2026-11-06T23:59:59+05:30");
  const [volMultMin, setVolMultMin] = useState<number>(2.0);
  const [priceMoveMin, setPriceMoveMin] = useState<number>(2.5);
  const [portfolioOnly, setPortfolioOnly] = useState<boolean>(false);

  const handleSelectWindow = (hours: number) => {
    setLoading(true);
    setWindowHours(hours);
  };

  const handleSelectAsOf = (ts: string) => {
    setLoading(true);
    setAsOf(ts);
  };

  const [data, setData] = useState<BriefPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [routineOpen, setRoutineOpen] = useState<boolean>(false);
  const [activeCard, setActiveCard] = useState<BriefItem | null>(null);
  const [rulesModalOpen, setRulesModalOpen] = useState<boolean>(false);
  const [expandedHookId, setExpandedHookId] = useState<string | null>(null);

  const [networkQuery, setNetworkQuery] = useState<string>("specialty chemicals");
  const [networkData, setNetworkData] = useState<NetworkAskResponse | null>(null);
  const [networkLoading, setNetworkLoading] = useState<boolean>(true);
  const [expandedAskContactId, setExpandedAskContactId] = useState<string | null>(null);

  const [dossierSymbol, setDossierSymbol] = useState<string>("DIXON");
  const [customTickerInput, setCustomTickerInput] = useState<string>("");
  const [dossier, setDossier] = useState<CompanyDossier | null>(null);
  const [dossierLoading, setDossierLoading] = useState<boolean>(true);
  const [dossierError, setDossierError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<PullJobState | null>(null);
  const [activeCitation, setActiveCitation] = useState<VerbatimCitation | null>(null);

  const cardDialogRef = useRef<HTMLDialogElement | null>(null);
  const rulesDialogRef = useRef<HTMLDialogElement | null>(null);
  const citationDialogRef = useRef<HTMLDialogElement | null>(null);

  const cardDialogTitleId = useId();
  const rulesDialogTitleId = useId();
  const citationDialogTitleId = useId();
  const resultsTableCaptionId = useId();
  const trajectoryTableCaptionId = useId();
  const pvdTableCaptionId = useId();

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
    let cancelled = false;
    const params = new URLSearchParams({
      q: networkQuery,
      limit: "8",
    });
    fetch(`/api/v1/network/ask?${params.toString()}`, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as NetworkAskResponse;
      })
      .then((json) => {
        if (!cancelled) {
          setNetworkData(json);
          setNetworkLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setNetworkLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [networkQuery]);

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

  useEffect(() => {
    const dialog = citationDialogRef.current;
    if (!dialog) return;
    if (activeCitation && !dialog.open) {
      dialog.showModal();
    } else if (!activeCitation && dialog.open) {
      dialog.close();
    }
    return attachLightDismissFallback(dialog, () => setActiveCitation(null));
  }, [activeCitation]);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/v1/dossiers/${encodeURIComponent(dossierSymbol)}`, { cache: "no-store" })
      .then(async (res) => {
        if (res.status === 404) {
          throw new Error(`NOT_BUILT:${dossierSymbol}`);
        }
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return (await res.json()) as CompanyDossier;
      })
      .then((json) => {
        if (!cancelled) {
          setDossier(json);
          setDossierError(null);
          setDossierLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setDossier(null);
          setDossierError(e instanceof Error ? e.message : "Failed to load dossier");
          setDossierLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [dossierSymbol]);

  useEffect(() => {
    if (!activeJob || activeJob.status !== "running") return;
    let cancelled = false;
    const timer = setInterval(() => {
      fetch(`/api/v1/jobs/${encodeURIComponent(activeJob.job_id)}`, { cache: "no-store" })
        .then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return (await res.json()) as PullJobState;
        })
        .then((job) => {
          if (cancelled) return;
          setActiveJob(job);
          if (job.status === "completed") {
            fetch(`/api/v1/dossiers/${encodeURIComponent(job.symbol)}`, { cache: "no-store" })
              .then((r) => (r.ok ? (r.json() as Promise<CompanyDossier>) : null))
              .then((d) => {
                if (d && !cancelled) {
                  setDossier(d);
                  setDossierError(null);
                  setDossierLoading(false);
                }
              })
              .catch(() => {});
          }
        })
        .catch(() => {});
    }, 1200);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeJob]);

  function selectDossierTicker(sym: string) {
    const clean = sym.trim().toUpperCase();
    if (!clean) return;
    setDossierLoading(true);
    setDossierError(null);
    setActiveJob(null);
    setDossierSymbol(clean);
  }

  function triggerBackgroundDossierBuild(sym: string) {
    const clean = sym.trim().toUpperCase();
    if (!clean) return;
    setDossierSymbol(clean);
    fetch(`/api/v1/dossiers/${encodeURIComponent(clean)}/build`, { method: "POST" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as PullJobState;
      })
      .then((job) => {
        setActiveJob(job);
      })
      .catch((e: unknown) => {
        setDossierError(e instanceof Error ? e.message : "Failed to start background job");
      });
  }

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
              onChange={(e) => handleSelectAsOf(e.target.value)}
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
                  onClick={() => handleSelectWindow(opt.hours)}
                  className={`px-2 py-0.5 font-mono text-xs transition-colors ${
                    active
                      ? "bg-ink text-paper font-medium"
                      : "border border-rule bg-paper text-ink-2 hover:border-ink"
                  }`}
                  aria-pressed={active}
                >
                  {opt.label}
                </button>
              );
            })}
            {loading && (
              <span className="ml-1 font-mono text-[10px] text-amber animate-pulse">…</span>
            )}
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
        <div className="flex items-baseline justify-between border-b border-rule pb-1.5">
          <div className="flex items-center gap-2">
            <h2 className="font-serif text-lg font-semibold tracking-tight text-ink">
              {WINDOW_OPTIONS.find((opt) => opt.hours === windowHours)?.label ?? `${windowHours}h`} ·{" "}
              {data?.ranked_material.length ?? 0} material · {data?.routine_summary.count ?? 0} routine
            </h2>
            {loading && (
              <span className="font-mono text-xs text-amber animate-pulse">
                (loading...)
              </span>
            )}
          </div>
          <span className="font-mono text-[11px] text-muted">
            Anchor: {data?.demo_clock.anchor_date ?? "2026-11-06"}
          </span>
        </div>

        {(data?.ranked_material.length ?? 0) === 0 ? (
          <div className="border border-rule bg-paper-2 p-4 text-xs text-muted">
            No material filings (priority ≥ 50) in this {windowHours}h window. Expand the window to{" "}
            <button
              type="button"
              onClick={() => handleSelectWindow(168)}
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
                    <button
                      type="button"
                      onClick={() => {
                        selectDossierTicker(item.symbol);
                        document.getElementById("pull-dossier-section")?.scrollIntoView({ behavior: "smooth" });
                      }}
                      className="border border-rule bg-paper px-2.5 py-1 font-mono text-xs text-ink-2 hover:border-ink hover:text-ink"
                    >
                      Pull Dossier ({item.symbol}) →
                    </button>
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

      {/* [S5 & S7] Pull · Primary-Source Company Dossier & Background Job Poller */}
      <section
        id="pull-dossier-section"
        aria-label="Pull Primary-Source Company Dossier"
        className="space-y-4 border-t border-rule pt-4"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <span className="kicker">
              [S5] Pull · Primary-Source Research Dossier (Annual Report + 4 Verified Concall Transcripts Only)
            </span>
            <p className="mt-0.5 font-mono text-[11px] text-ink-2">
              Every claim carries a clickable verbatim quote verified via{" "}
              <code>rapidfuzz.partial_ratio &ge; 85</code>. Unsupported claims show{" "}
              <strong>&ldquo;not found in filings&rdquo;</strong>.
            </p>
          </div>
          <span className="font-mono text-[10px] text-up">
            0 News · 0 Broker Notes · Primary Filings Only
          </span>
        </div>

        {/* Demo Dossiers + Generalisation Dossiers + Any NSE Ticker Builder */}
        <div className="space-y-2 border border-rule bg-paper-2 p-3 text-xs">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase text-muted">4 Demo Dossiers:</span>
            {DEMO_DOSSIER_SYMBOLS.map((d) => (
              <button
                key={d.symbol}
                type="button"
                onClick={() => selectDossierTicker(d.symbol)}
                className={`px-2 py-1 font-mono text-[11px] ${
                  dossierSymbol === d.symbol
                    ? "bg-ink text-paper"
                    : "border border-rule bg-paper text-ink-2 hover:border-ink"
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="font-mono text-[10px] uppercase text-muted">2 Generalisation Tests:</span>
            {GENERALISATION_DOSSIER_SYMBOLS.map((g) => (
              <button
                key={g.symbol}
                type="button"
                onClick={() => selectDossierTicker(g.symbol)}
                className={`px-2 py-1 font-mono text-[11px] ${
                  dossierSymbol === g.symbol
                    ? "bg-ink text-paper"
                    : "border border-rule bg-paper text-ink-2 hover:border-ink"
                }`}
              >
                {g.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-rule pt-2">
            <label htmlFor="custom-dossier-ticker" className="font-mono text-[11px] text-ink-2">
              Any NSE Ticker:
            </label>
            <input
              id="custom-dossier-ticker"
              type="text"
              value={customTickerInput}
              onChange={(e) => setCustomTickerInput(e.target.value.toUpperCase())}
              placeholder="e.g. MARUTI, KAYNES, LAURUSLABS…"
              className="w-56 border border-rule bg-paper px-2.5 py-1 font-mono text-xs text-ink"
            />
            <button
              type="button"
              onClick={() => {
                if (customTickerInput.trim()) {
                  selectDossierTicker(customTickerInput);
                }
              }}
              className="border border-rule bg-paper px-2.5 py-1 font-mono text-xs text-ink hover:border-ink"
            >
              Load Snapshot
            </button>
            <button
              type="button"
              onClick={() => {
                const target = customTickerInput.trim() || dossierSymbol;
                triggerBackgroundDossierBuild(target);
              }}
              className="border border-ink bg-ink px-2.5 py-1 font-mono text-xs text-paper hover:opacity-90"
            >
              [S7] Run Background Pull Job ({customTickerInput.trim() || dossierSymbol}) →
            </button>
          </div>
        </div>

        {/* [S7] Build-in-Progress Job Poller */}
        {activeJob && (
          <div className="border-l-2 border-accent bg-paper-2 p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2 font-mono">
              <div>
                <span className="font-semibold text-ink">
                  [S7] Background Pull Job · <code>{activeJob.job_id}</code> ({activeJob.symbol})
                </span>
                <span
                  className={`ml-2 border px-1.5 py-0.5 text-[10px] uppercase ${
                    activeJob.status === "completed"
                      ? "border-up text-up"
                      : activeJob.status === "failed"
                        ? "border-signal text-signal"
                        : "border-accent text-accent"
                  }`}
                >
                  {activeJob.status} · {activeJob.progress_pct}%
                </span>
              </div>
              <button
                type="button"
                onClick={() => setActiveJob(null)}
                className="text-[11px] text-muted underline"
              >
                Dismiss
              </button>
            </div>
            <p className="mt-1 font-mono text-[11px] text-ink-2">{activeJob.step}</p>
            <div className="mt-2 h-1.5 w-full overflow-hidden bg-rule">
              <div
                className="h-full bg-accent transition-all duration-300"
                style={{ width: `${Math.min(100, Math.max(5, activeJob.progress_pct))}%` }}
              />
            </div>
            {activeJob.steps_log && activeJob.steps_log.length > 0 && (
              <ul className="mt-2 space-y-0.5 font-mono text-[10px] text-muted">
                {activeJob.steps_log.map((s, idx) => (
                  <li key={idx}>
                    [{s.progress_pct}%] {s.step}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Dossier Body */}
        {dossierLoading ? (
          <div className="border border-rule bg-paper-2 p-4 font-mono text-xs text-muted">
            Loading primary-source dossier for {dossierSymbol}…
          </div>
        ) : dossierError ? (
          <div className="space-y-2 border border-amber bg-paper-2 p-4 text-xs">
            <p className="font-mono text-amber">
              {dossierError.startsWith("NOT_BUILT:")
                ? `Dossier for ${dossierSymbol} is not precomputed in snapshots yet.`
                : `Could not load dossier (${dossierError}).`}
            </p>
            <button
              type="button"
              onClick={() => triggerBackgroundDossierBuild(dossierSymbol)}
              className="border border-ink bg-ink px-3 py-1.5 font-mono text-xs text-paper"
            >
              Trigger Background Pull Job for {dossierSymbol} →
            </button>
          </div>
        ) : dossier ? (
          <div className="space-y-4 border border-rule bg-paper p-3.5 sm:p-4">
            {/* Dossier Title & Verification Header */}
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-rule pb-3">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                  <span className="text-base font-bold text-ink">{dossier.symbol}</span>
                  <span className="text-ink-2">· {dossier.company_name}</span>
                  <span className="border border-rule bg-paper-2 px-1.5 py-0.5 text-[10px] uppercase">
                    {dossier.sector}
                  </span>
                  <span
                    className={`border px-1.5 py-0.5 text-[10px] ${
                      dossier.is_lender ? "border-amber text-amber" : "border-up text-up"
                    }`}
                  >
                    {dossier.is_lender
                      ? "EBITDA not meaningful for lenders (NII/PPOP/GNPA mode)"
                      : "Derived Operating EBITDA mode"}
                  </span>
                </div>
                <p className="font-serif text-[16px] leading-snug text-ink">
                  {dossier.business_model_1l}
                </p>
                <p className="text-xs text-ink-2">{dossier.executive_summary}</p>
              </div>
              <div className="shrink-0 space-y-1 text-right font-mono text-[11px]">
                <div className="border border-rule bg-paper-2 px-2 py-1 text-ink">
                  ✓ {dossier.verification_summary.total_verified_citations} Quotes Verified (rapidfuzz{" "}
                  &ge; {dossier.verification_summary.min_rapidfuzz_score}% + token # match)
                </div>
                <div className="text-[10px] text-muted">
                  Source: Deterministic primary-source extraction (no LLM)
                </div>
                {dossier.screener_url && (
                  <a
                    href={dossier.screener_url}
                    target="_blank"
                    rel="noreferrer"
                    className="block text-accent underline"
                  >
                    Screener.in Primary Index ↗
                  </a>
                )}
              </div>
            </div>

            {/* Verified Primary Filings Manifest (Doc-Type Check Badges) */}
            <div className="space-y-1.5">
              <span className="kicker">
                Primary Source Corpus · Concall Doc-Type Check (Speakers + Q&amp;A Verified)
              </span>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {dossier.documents_manifest.map((doc) => (
                  <div key={doc.doc_id} className="border border-rule bg-paper-2 p-2.5 text-xs">
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono font-semibold text-ink">{doc.label}</span>
                      <a
                        href={doc.pdf_url}
                        target="_blank"
                        rel="noreferrer"
                        className="shrink-0 font-mono text-[11px] text-accent underline"
                      >
                        PDF ({doc.page_count}p) ↗
                      </a>
                    </div>
                    {doc.doctype_check ? (
                      <div className="mt-1 space-y-0.5 font-mono text-[10px]">
                        <div className="text-up">
                          ✓ Transcript verified · {doc.doctype_check.distinct_speaker_count} speakers ·{" "}
                          {doc.doctype_check.speaker_turn_count} turns · Q&amp;A:{" "}
                          {doc.doctype_check.has_qa ? "Yes" : "No"}
                        </div>
                        {!doc.doctype_check.promised_vs_delivered_testable && (
                          <div className="text-amber">
                            ⚠ {doc.doctype_check.promised_vs_delivered_note}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="mt-1 font-mono text-[10px] text-ink-2">
                        ✓ Primary Annual Report ({doc.size_kb} KB · {doc.page_count} pages)
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* 5-Year Financial Trajectory Table (Sector-Aware) */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="kicker">
                  5-Year Financial Trajectory (₹ Cr) ·{" "}
                  {dossier.is_lender ? "Lender Accounting (NII / PPOP / PAT)" : "Operating Trajectory & Cash Conversion"}
                </span>
                <span className="font-mono text-[11px] text-ink-2">
                  {dossier.financial_trajectory.summary_stats.ebitda_label}
                  {dossier.financial_trajectory.summary_stats.revenue_cagr_pct !== undefined &&
                    ` · 5Y Rev CAGR: ${dossier.financial_trajectory.summary_stats.revenue_cagr_pct}%`}
                  {!dossier.is_lender &&
                    dossier.financial_trajectory.summary_stats.cumulative_5y_cfo_to_pat_pct !== undefined &&
                    ` · 5Y Cum. CFO/PAT: ${dossier.financial_trajectory.summary_stats.cumulative_5y_cfo_to_pat_pct}%`}
                </span>
              </div>

              <div
                tabIndex={0}
                role="region"
                aria-labelledby={trajectoryTableCaptionId}
                className="table-wrapper border border-rule"
              >
                <table className="text-left text-xs">
                  <caption id={trajectoryTableCaptionId} className="sr-only">
                    {dossier.company_name} 5-year financial trajectory in Crore Rupees
                  </caption>
                  <thead>
                    <tr className="border-b border-rule font-mono text-[11px] uppercase text-muted">
                      <th scope="col" className="px-2.5 py-2">
                        Period
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        {dossier.is_lender ? "Interest / Revenue (₹ Cr)" : "Revenue (₹ Cr)"}
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        {dossier.is_lender ? "Financing Profit / PPOP" : "Derived EBITDA (₹ Cr)"}
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        {dossier.is_lender ? "Financing Margin %" : "Derived EBITDA %"}
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        PBT (₹ Cr)
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        PAT (₹ Cr)
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        {dossier.is_lender ? "EBITDA Policy" : "CFO / PAT %"}
                      </th>
                      <th scope="col" className="px-2.5 py-2 text-right">
                        {dossier.is_lender ? "ROE %" : "ROCE %"}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {dossier.financial_trajectory.annual_5y.map((yr) => (
                      <tr key={yr.period}>
                        <th scope="row" className="px-2.5 py-1.5 font-mono font-semibold text-ink">
                          {yr.period}
                        </th>
                        <td className="num px-2.5 py-1.5 text-right text-ink">
                          {(yr.revenue_cr ?? yr.revenue_or_nii_cr)?.toLocaleString("en-IN") ?? "—"}
                        </td>
                        <td className="num px-2.5 py-1.5 text-right text-ink">
                          {(yr.ebitda_derived_cr ?? yr.ppop_or_financing_profit_cr)?.toLocaleString("en-IN") ?? "—"}
                        </td>
                        <td className="num px-2.5 py-1.5 text-right text-ink-2">
                          {(yr.ebitda_margin_derived_pct ?? yr.financing_margin_pct) !== null &&
                          (yr.ebitda_margin_derived_pct ?? yr.financing_margin_pct) !== undefined
                            ? `${yr.ebitda_margin_derived_pct ?? yr.financing_margin_pct}%`
                            : "—"}
                        </td>
                        <td className="num px-2.5 py-1.5 text-right text-ink">
                          {yr.pbt_cr?.toLocaleString("en-IN") ?? "—"}
                        </td>
                        <td className="num px-2.5 py-1.5 text-right font-medium text-ink">
                          {yr.pat_cr?.toLocaleString("en-IN") ?? "—"}
                        </td>
                        <td className="num px-2.5 py-1.5 text-right font-mono text-[11px] text-amber">
                          {dossier.is_lender
                            ? "EBITDA not meaningful for lenders"
                            : yr.cfo_to_pat_pct !== null && yr.cfo_to_pat_pct !== undefined
                              ? `${yr.cfo_to_pat_pct}%`
                              : "—"}
                        </td>
                        <td className="num px-2.5 py-1.5 text-right text-ink-2">
                          {(yr.roce_pct ?? yr.roce_or_roe_pct) !== null &&
                          (yr.roce_pct ?? yr.roce_or_roe_pct) !== undefined
                            ? `${yr.roce_pct ?? yr.roce_or_roe_pct}%`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Promised vs. Delivered Ledger (with Latest Call Untestable Rule) */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="kicker">
                  Promised vs. Delivered · Concall Guidance Track Record
                </span>
                <span className="font-mono text-[10px] text-amber">
                  Latest call is forward guidance only — marked untestable until subsequent quarter is filed
                </span>
              </div>

              {dossier.symbol === "DIXON" ? (
                <div className="border border-amber bg-paper-2 p-3 text-xs space-y-1">
                  <div className="font-mono text-[11px] font-semibold text-amber">
                    [Withdrawn Pending Part C Rebuild]
                  </div>
                  <p className="text-ink-2">
                    The DIXON Promised vs. Delivered table has been withdrawn from the UI pending Part C rebuild.
                    Its prior deterministic draft used historical commentary as guidance, revenue metrics as evidence for a volume target,
                    an unsourced run-rate, and subsequent concall commentary as delivered actuals.
                    It will be rebuilt with strict forward-looking guidance and filed results actuals only.
                  </p>
                </div>
              ) : (
                <div
                  tabIndex={0}
                  role="region"
                  aria-labelledby={pvdTableCaptionId}
                  className="table-wrapper border border-rule"
                >
                  <table className="text-left text-xs">
                  <caption id={pvdTableCaptionId} className="sr-only">
                    {dossier.company_name} Promised versus Delivered guidance comparison across the last 4 earnings calls
                  </caption>
                  <thead>
                    <tr className="border-b border-rule font-mono text-[11px] uppercase text-muted">
                      <th scope="col" className="px-2.5 py-2">
                        Concall / Topic
                      </th>
                      <th scope="col" className="px-2.5 py-2">
                        Promised Guidance (Primary Quote)
                      </th>
                      <th scope="col" className="px-2.5 py-2">
                        Delivered Outcome / Testability
                      </th>
                      <th scope="col" className="px-2.5 py-2">
                        Verdict
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {dossier.promised_vs_delivered.map((row, idx) => (
                      <tr key={idx} className={row.is_latest_call ? "bg-paper-2" : ""}>
                        <th scope="row" className="px-2.5 py-2 align-top font-mono text-ink">
                          <div>{row.period_called}</div>
                          <div className="mt-0.5 text-[11px] font-normal text-muted">{row.topic}</div>
                        </th>
                        <td className="px-2.5 py-2 align-top text-ink">
                          <p>{row.promised_guidance}</p>
                          {row.promised_citation?.verified && (
                            <button
                              type="button"
                              onClick={() => setActiveCitation(row.promised_citation)}
                              className="mt-1 inline-block border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] text-accent underline"
                            >
                              [quote verified: {row.promised_citation.doc_label}, p.{row.promised_citation.page}]
                            </button>
                          )}
                        </td>
                        <td className="px-2.5 py-2 align-top text-ink-2">
                          <p>{row.delivered_summary}</p>
                          {row.delivered_citation?.verified && (
                            <button
                              type="button"
                              onClick={() => setActiveCitation(row.delivered_citation!)}
                              className="mt-1 inline-block border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] text-accent underline"
                            >
                              [quote verified: {row.delivered_citation.doc_label}, p.{row.delivered_citation.page}]
                            </button>
                          )}
                        </td>
                        <td className="px-2.5 py-2 align-top font-mono text-[11px]">
                          <span
                            className={`inline-block border px-1.5 py-0.5 ${
                              !row.promised_vs_delivered_testable
                                ? "border-amber bg-paper text-amber"
                                : row.verdict === "Delivered"
                                  ? "border-up text-up"
                                  : row.verdict === "Missed"
                                    ? "border-signal text-signal"
                                    : "border-rule text-ink-2"
                            }`}
                          >
                            {row.verdict}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              )}
            </div>

            {/* Numbers vs. Narrative Checks */}
            <div className="space-y-2">
              <span className="kicker">
                Numbers vs. Narrative · Primary-Source Cross-Check (Annual Report vs Concall)
              </span>
              <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
                {dossier.numbers_vs_narrative.map((chk, idx) => (
                  <div key={idx} className="border border-rule bg-paper-2 p-3 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono font-semibold text-ink">{chk.check_title}</span>
                      <span className="border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] uppercase text-ink-2">
                        {chk.verdict}
                      </span>
                    </div>
                    <p className="mt-1.5 text-ink">
                      <strong className="font-mono text-[10px] uppercase text-muted">Numbers: </strong>
                      {chk.numbers_observed}
                    </p>
                    <p className="mt-1 text-ink-2">
                      <strong className="font-mono text-[10px] uppercase text-muted">Narrative: </strong>
                      {chk.narrative_claimed}
                    </p>
                    {chk.citation?.verified && (
                      <button
                        type="button"
                        onClick={() => setActiveCitation(chk.citation)}
                        className="mt-2 border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] text-accent underline"
                      >
                        [quote verified: {chk.citation.doc_label}, p.{chk.citation.page}]
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Bull vs. Bear Case (3 Bull / 3 Bear with Verbatim Source Sheet Citations) */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="space-y-2 border border-rule bg-paper-2 p-3 text-xs">
                <span className="kicker text-up">Primary-Source Bull Case (3 Verified Filings Claims)</span>
                <div className="space-y-2.5">
                  {dossier.bull_case.map((b, i) => (
                    <div key={i} className="border-l-2 border-up pl-2.5">
                      <div className="font-semibold text-ink">{b.title}</div>
                      <p className="mt-0.5 text-ink-2">{b.thesis}</p>
                      {b.citation?.verified && (
                        <button
                          type="button"
                          onClick={() => setActiveCitation(b.citation)}
                          className="mt-1 font-mono text-[10px] text-accent underline"
                        >
                          [quote verified: {b.citation.doc_label}, p.{b.citation.page}]
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-2 border border-rule bg-paper-2 p-3 text-xs">
                <span className="kicker text-signal">Primary-Source Bear Case &amp; Filing Risks</span>
                <div className="space-y-2.5">
                  {dossier.bear_case.map((b, i) => (
                    <div key={i} className="border-l-2 border-signal pl-2.5">
                      <div className="font-semibold text-ink">{b.title}</div>
                      <p className="mt-0.5 text-ink-2">{b.thesis}</p>
                      {b.citation?.verified && (
                        <button
                          type="button"
                          onClick={() => setActiveCitation(b.citation)}
                          className="mt-1 font-mono text-[10px] text-accent underline"
                        >
                          [quote verified: {b.citation.doc_label}, p.{b.citation.page}]
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Explicit "not found in filings" Diligence Gaps */}
            <div className="border border-rule bg-paper-2 p-3 text-xs">
              <span className="kicker">
                Where Filings Are Silent · Explicit &ldquo;not found in filings&rdquo; Guardrail
              </span>
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {dossier.unanswered_diligence_questions.map((u, i) => (
                  <div key={i} className="border border-rule bg-paper p-2.5">
                    <div className="flex items-center justify-between gap-2 font-mono text-[11px]">
                      <span className="font-semibold text-ink">{u.topic}</span>
                      <span className="border border-amber px-1.5 py-0.5 text-[10px] text-amber">
                        {u.status}
                      </span>
                    </div>
                    <p className="mt-1 text-ink-2">{u.question_for_management_or_network}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Woven-In Network for Dossier (Ex-Company, Competitors, Suppliers/Customers) */}
            <div className="space-y-2.5 border-t border-rule pt-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="kicker">
                  Woven-In Network for {dossier.symbol} · Ex-Company, Competitors &amp; Value-Chain Checks
                </span>
                <span className="font-mono text-[10px] text-amber">
                  {dossier.network.inferred_label}
                </span>
              </div>

              <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
                {[
                  { title: "Ex-Company (Knows the Company)", items: dossier.network.ex_company },
                  { title: "Competitors", items: dossier.network.competitors },
                  { title: "Suppliers / Customers / Sector", items: dossier.network.suppliers_customers },
                ].map((group) => (
                  <div key={group.title} className="border border-rule bg-paper-2 p-2.5 text-xs">
                    <div className="font-mono text-[11px] font-semibold uppercase text-ink">
                      {group.title} ({group.items.length})
                    </div>
                    {group.items.length === 0 ? (
                      <p className="mt-1.5 text-[11px] text-muted">No contacts in this bucket.</p>
                    ) : (
                      <div className="mt-2 space-y-2">
                        {group.items.map((ct) => (
                          <div key={ct.contact_id} className="border border-rule bg-paper p-2">
                            <div className="font-mono text-[11px] font-semibold text-ink">{ct.path}</div>
                            <div className="mt-0.5 text-[11px] text-ink-2">{ct.headline}</div>
                            <div className="mt-1 font-mono text-[10px] text-amber">{ct.inferred_label}</div>
                            <div className="mt-1.5 border-l-2 border-accent pl-2 font-mono text-[10px] text-ink-2">
                              &ldquo;{ct.draft_opener}&rdquo;
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </section>

      {/* [S8] Direct Network Query ("Ask FINN Network") */}
      <section aria-label="Ask your network" className="space-y-3 border-t border-rule pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <span className="kicker">
              [S8] Ask Your Network · {networkData?.total_contacts ?? 64} Synthetic Contacts ·{" "}
              {networkData?.total_links ?? 24} Graph Edges (1st &amp; 2nd Degree)
            </span>
          </div>
          <span className="font-mono text-[10px] text-amber">
            inferred from employer/tenure overlap, synthetic network
          </span>
        </div>

        <div className="space-y-2 border border-rule bg-paper-2 p-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="search"
              aria-label="Query your network by company, sector, expertise, or alma mater"
              placeholder="Who do I know in specialty chemicals, ICICI Bank, Cummins, EMS, IIT Kanpur…"
              value={networkQuery}
              onChange={(e) => setNetworkQuery(e.target.value)}
              className="w-full border border-rule bg-paper px-3 py-1.5 font-mono text-xs text-ink placeholder:text-muted"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase text-muted">Quick queries:</span>
            {NETWORK_QUICK_QUERIES.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setNetworkQuery(q)}
                className={`px-2 py-0.5 font-mono text-[11px] ${
                  networkQuery === q
                    ? "bg-ink text-paper"
                    : "border border-rule bg-paper text-ink-2 hover:border-ink"
                }`}
              >
                {q}
              </button>
            ))}
          </div>
        </div>

        {networkLoading && !networkData ? (
          <p className="text-xs text-muted">Searching 1st &amp; 2nd degree network graph…</p>
        ) : (networkData?.results.length ?? 0) === 0 ? (
          <p className="text-xs text-muted">
            No matching contacts in synthetic graph for &ldquo;{networkQuery}&rdquo;.
          </p>
        ) : (
          <div className="space-y-2">
            {networkData?.results.slice(0, 6).map((c) => {
              const isOpen = expandedAskContactId === c.contact_id;
              return (
                <div key={c.contact_id} className="border border-rule bg-paper p-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-mono font-semibold text-ink">{c.path}</span>
                      <span
                        className={`border px-1.5 py-0.5 font-mono text-[10px] ${
                          c.degree === 2
                            ? "border-accent text-accent"
                            : "border-rule bg-paper-2 text-ink-2"
                        }`}
                      >
                        {c.degree === 2 ? "2nd-degree warm intro" : `1st-degree · ${c.strength}/5`}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedAskContactId(isOpen ? null : c.contact_id)
                      }
                      className="font-mono text-[11px] text-accent underline"
                    >
                      {isOpen ? "Hide details" : "Why + Opener →"}
                    </button>
                  </div>
                  <p className="mt-1 text-ink-2">{c.headline}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-amber">{c.inferred_label}</p>

                  {isOpen && (
                    <div className="mt-2.5 space-y-2 border-t border-rule pt-2">
                      <ul className="list-disc space-y-1 pl-4 text-ink-2">
                        {c.why_reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                      <div className="border-l-2 border-accent bg-paper-2 px-2.5 py-2 font-mono text-[11px] text-ink">
                        <div className="text-[10px] uppercase text-muted">
                          Deterministic 2-line opener (zero LLM sees network):
                        </div>
                        <p className="mt-0.5">&ldquo;{c.draft_opener}&rdquo;</p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

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
                {activeCard.details.is_lender && (
                  <div className="border-l-2 border-amber bg-paper-2 px-3 py-2 font-mono text-xs text-amber">
                    <strong>{activeCard.details.lender_note ?? "EBITDA not meaningful for lenders"}</strong> — showing sector-appropriate NII, PPOP, PBT &amp; PAT.
                  </div>
                )}

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
                          Status / Cross-Check
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
                        const isUnreliable = row.status === "unreliable";
                        return (
                          <tr key={row.metric}>
                            <th scope="row" className="px-3 py-2 font-mono font-semibold text-ink">
                              {row.metric}
                              {row.derived && (
                                <span
                                  title={row.verbatim_line ?? "Derived from PDF lines"}
                                  className={`ml-1.5 border px-1 py-0.5 text-[10px] font-normal ${
                                    isUnreliable
                                      ? "border-signal text-signal"
                                      : "border-amber text-amber"
                                  }`}
                                >
                                  {isUnreliable ? "unreliable" : "derived"}
                                  {row.margin_pct !== null && row.margin_pct !== undefined
                                    ? ` · ${row.margin_pct.toFixed(1)}% margin`
                                    : ""}
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
                              {isUnreliable ? (
                                <span className="border border-signal bg-paper-2 px-1.5 py-0.5 text-[11px] text-signal">
                                  unreliable (margin {row.margin_pct ?? "—"}%)
                                </span>
                              ) : row.derived ? (
                                <span className="border border-amber bg-paper-2 px-1.5 py-0.5 text-[11px] text-amber">
                                  derived
                                  {delta !== null && delta !== undefined
                                    ? ` (Δ ${delta > 0 ? "+" : ""}${delta.toFixed(2)}% vs screener)`
                                    : ""}
                                </span>
                              ) : delta === null || delta === undefined ? (
                                <span className="text-muted">reported</span>
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

      {/* [S6] Verbatim Source Sheet Modal */}
      <dialog
        ref={citationDialogRef}
        {...({ closedby: "any" } as Record<string, unknown>)}
        aria-labelledby={citationDialogTitleId}
      >
        {activeCitation && (
          <div className="space-y-4 p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3 border-b border-rule pb-3">
              <div>
                <span className="kicker">[S6] Primary-Source Verbatim Quote Verification</span>
                <h2 id={citationDialogTitleId} className="mt-1 font-serif text-[19px] text-ink">
                  {activeCitation.doc_label} · Page {activeCitation.page}
                </h2>
              </div>
              <form method="dialog">
                <button
                  type="submit"
                  className="border border-rule bg-paper-2 px-2.5 py-1 font-mono text-xs text-ink"
                >
                  Close [Esc]
                </button>
              </form>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border border-rule bg-paper-2 px-3 py-2 font-mono text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-up">
                  ✓ Verified via rapidfuzz.partial_ratio ({activeCitation.match_score}% match)
                </span>
                <span className="text-muted">· Doc ID: {activeCitation.doc_id}</span>
              </div>
              {activeCitation.pdf_url && (
                <a
                  href={`${activeCitation.pdf_url}#page=${activeCitation.page}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent underline"
                >
                  Open Primary Filing PDF (p.{activeCitation.page}) ↗
                </a>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="font-mono text-[11px] uppercase text-muted">
                Verbatim Substring Matched on Page {activeCitation.page}:
              </div>
              <blockquote className="border-l-2 border-accent bg-paper-2 p-3 font-serif text-[15px] leading-relaxed text-ink">
                &ldquo;{activeCitation.verbatim_quote}&rdquo;
              </blockquote>
            </div>
          </div>
        )}
      </dialog>
    </div>
  );
}
