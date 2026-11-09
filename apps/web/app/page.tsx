import { BriefClient } from "./brief-client";

/**
 * FINN — Phase 2 Push ("The Brief", [S1]–[S4] in docs/DEMO_SCRIPT.md).
 * Mobile-first, calm paper & ink layout with deterministic Demo Clock,
 * real NSE/BSE PDF provenance, live PDF-extracted Results vs Screener cross-check,
 * verbatim SEBI LODR KMP bios, and woven-in synthetic network overlaps.
 */
export default function Home() {
  return (
    <main>
      <header className="flex items-baseline justify-between border-b border-ink pb-2">
        <div className="flex items-baseline gap-2.5">
          <h1 className="font-serif text-[28px] font-semibold tracking-tight">FINN</h1>
          <span className="font-mono text-[11px] text-muted">Push · Pull · Network</span>
        </div>
        <span className="kicker">Meera Iyer · 18 Holdings</span>
      </header>

      <BriefClient />
    </main>
  );
}
