"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Braces, Plug, TerminalSquare } from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { API_TABS } from "@/lib/proofSnippets";
import { CodeCard } from "./CodeCard";

const ICON = { mcp: Plug, rest: TerminalSquare, cypher: Braces } as const;

/** "Plug it into your agent": the same graph over MCP, REST or plain Cypher. */
export function ApiTabs() {
  const [tab, setTab] = useState(0);
  const reduced = useReducedMotion();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const t = API_TABS[tab];
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const n = (tab + d + API_TABS.length) % API_TABS.length;
    setTab(n);
    refs.current[n]?.focus();
  };
  return (
    <section id="api" aria-labelledby="api-title" className="relative isolate scroll-mt-20 overflow-hidden py-24 lg:py-32">
      <div className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[420px] w-[820px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--fl-iris)_22%,transparent),transparent)]" aria-hidden />
      <div className="mx-auto max-w-[920px] px-5 text-center sm:px-8">
        <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-[var(--fl-subtle)]">For agents</p>
        <h2 id="api-title" className="mt-4 text-[clamp(2rem,4.6vw,3.5rem)] font-[510] leading-[1.06] tracking-[-0.03em]">
          <span className="fl-gradient-text">Context, not guesses.</span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-[17px] leading-relaxed text-[var(--fl-muted)]">
          Plug the graph into any agent. Every tool answers with the Cypher it ran, its parameters and a digest of the rows.
        </p>

        <div role="tablist" aria-label="Interfaces" onKeyDown={onKey} className="mx-auto mt-10 inline-flex gap-1 rounded-full border border-white/[0.08] bg-white/[0.02] p-1">
          {API_TABS.map((x, i) => {
            const Icon = ICON[x.id as keyof typeof ICON];
            const on = i === tab;
            return (
              <button key={x.id} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" id={`api-tab-${x.id}`}
                      aria-selected={on} aria-controls="api-panel" tabIndex={on ? 0 : -1} onClick={() => setTab(i)}
                      className={"fl-press relative inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-sky-400 " + (on ? "text-zinc-50" : "text-[var(--fl-muted)] hover:text-zinc-200")}>
                {on ? (reduced ? <span className="absolute inset-0 rounded-full bg-white/[0.08]" aria-hidden />   // no slide under reduced motion
                  : <motion.span layoutId="fl-api-tab" className="absolute inset-0 rounded-full bg-white/[0.08]" transition={{ type: "spring", stiffness: 400, damping: 34 }} aria-hidden />) : null}
                <Icon className="relative size-4" aria-hidden /><span className="relative">{x.label}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="mx-auto mt-8 max-w-[860px] px-5 sm:px-8">
        <div id="api-panel" role="tabpanel" aria-labelledby={`api-tab-${t.id}`} data-spot
             className="overflow-hidden rounded-2xl border border-white/10 bg-[#0c0d0e] text-left shadow-[0_30px_80px_-30px_rgb(0_0_0/0.8)]">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={t.id} initial={reduced ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={reduced ? { opacity: 0 } : { opacity: 0, y: -6 }}
                        transition={{ duration: reduced ? 0 : 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}>
              <CodeCard title={t.label} meta={t.meta} code={t.code} lang={t.lang} bare />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
