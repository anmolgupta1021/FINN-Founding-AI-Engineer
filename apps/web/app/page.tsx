import { StatusStrip } from "./status-strip";

/**
 * P0 shell. Proves: PWA install, typography/tokens, and the web → api route via Vercel Services.
 * The real Brief (S1 in docs/DEMO_SCRIPT.md) replaces the body in P2.
 */
export default function Home() {
  return (
    <main>
      <header className="flex items-baseline justify-between border-b border-ink pb-2">
        <h1 className="font-serif text-[28px] font-semibold tracking-tight">FINN</h1>
        <span className="kicker">ENAM · Morning Brief</span>
      </header>

      <section className="border-b border-rule py-4">
        <p className="font-serif text-[20px] leading-snug">
          What changed, why it matters, and who you know who can explain it.
        </p>
      </section>

      <StatusStrip />
    </main>
  );
}
