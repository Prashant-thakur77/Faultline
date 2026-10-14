"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { SNIPPETS, type Snippet } from "@/lib/proofSnippets";
import { scrollToElement } from "@/lib/smooth";
import { CodeCard } from "./CodeCard";
import { GraphHeroArt } from "./GraphHeroArt";

type Step = { n: string; title: string; short: string; weight: number; tag: string; scene: number; body: React.ReactNode; snippet: Snippet };

/** The hero incident, decided step by step. Facts are the recorded S1 run's (public/replay/s1-hero). */
// `weight`: a segment's share of the "one incident" bar. Visual rhythm only, not a measured duration.
const STEPS: Step[] = [
  { n: "01", title: "Alert", short: "Alert", weight: 9, tag: "algo.WCC", scene: 1, snippet: SNIPPETS.storm,
    body: <>Checkout and frontend page at once. Weakly connected components over the failure edges group the storm into incidents, so two faults never blend into one story. The search then runs upstream from the symptom.</> },
  { n: "02", title: "Path", short: "Path", weight: 15, tag: "G2 · algo.SPpaths", scene: 2, snippet: SNIPPETS.path,
    body: <>Three deploys landed in the same few minutes. <span className="font-mono text-zinc-100">D-rec-12</span> changed recommendation, and FalkorDB returns no path from it to checkout. No path, no claim: it is out before any model reasons about it.</> },
  { n: "03", title: "Flow", short: "Flow", weight: 13, tag: "G5 · algo.maxFlow", scene: 3, snippet: SNIPPETS.flow,
    body: <>A path is not enough. <span className="font-mono text-zinc-100">D-email-88</span> reaches checkout over a best-effort edge whose max flow is 0.02, far below the share of the impact it would need to carry. Rejected.</> },
  { n: "04", title: "Proof", short: "Proof", weight: 17, tag: "the path is the proof", scene: 4, snippet: SNIPPETS.proof,
    body: <><span className="font-mono text-zinc-100">D-pay-417</span> → payment → checkout, and the flow carries all of it. The chain comes back hop by hop and is drawn as returned; a hop learned from an earlier incident names that incident.</> },
  { n: "05", title: "Cut", short: "Cut", weight: 11, tag: "min-cut · GRAPH.COPY", scene: 5, snippet: SNIPPETS.cut,
    body: <>The smallest containment is the min-cut out of payment, computed from max-flow&apos;s edge flows. Every option is tried on its own GRAPH.COPY of the tenant graph first, with a predicted outcome.</> },
  { n: "06", title: "Act & remember", short: "Act", weight: 14, tag: "two-step approval", scene: 6, snippet: SNIPPETS.writeback,
    body: <>A human approves the exact plan: flag paymentGate off. A second channel verifies it as APPLIED, the decision is written back, and a separate read-only connection re-reads every id, so the next incident starts warm.</> },
];

/** Scroll story: the steps scroll past a pinned proof graph that changes scene with them (phones: graph on top). */
export function ProofStory() {
  const reduced = useReducedMotion();
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    // implicit root: the viewport, clipped by the scrolling <main> on desktop, so this works for either scroller
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.step));
      },
      { rootMargin: "-50% 0px -45% 0px" },
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, []);

  const go = (i: number) => {
    const el = refs.current[i];
    setActive(i);
    if (el) scrollToElement(el, { block: "center", smooth: !reduced });
  };
  const step = STEPS[active];

  return (
    <section id="how" aria-labelledby="how-title" className="relative mx-auto max-w-[1200px] scroll-mt-20 px-5 pb-24 sm:px-8">
      <h2 id="how-title" className="max-w-[920px] text-[clamp(1.9rem,4.2vw,3rem)] font-[510] leading-[1.08] tracking-[-0.022em] text-zinc-50">
        How it decides.{" "}
        <span className="text-[var(--fl-muted)]">The hero incident, step by step: every verdict, and the query that made it.</span>
      </h2>

      {/* block on phones (a grid row would confine the sticky graph to its own height), two columns on desktop */}
      <div className="mt-10 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-x-12">
        {/* the pinned instrument: sticky under the top bar on phones, centred beside the steps on desktop */}
        <div className="sticky top-14 z-10 -mx-5 bg-[var(--fl-bg)]/90 px-5 pb-3 pt-2 backdrop-blur-md sm:-mx-8 sm:px-8 lg:order-2 lg:top-0 lg:mx-0 lg:flex lg:h-[calc(100dvh-3.5rem)] lg:items-center lg:self-start lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
          <div className="w-full">
            <StoryBar active={active} onPick={go} reduced={reduced} />
            <figure data-spot className="relative mt-3 w-full rounded-[20px] border border-white/[0.08] bg-[var(--fl-surface)] p-2 sm:p-4">
              <figcaption className="flex items-baseline justify-between gap-4 px-1.5 pt-1 font-mono text-[11px] text-zinc-400 sm:px-1 sm:pt-0">
                <span>Fig 2.{active + 1}</span>
                <span className="truncate uppercase tracking-[0.14em]">{step.tag}</span>
              </figcaption>
              <GraphHeroArt className="h-auto max-h-[34vh] w-full lg:max-h-none" scene={step.scene} />
            </figure>
          </div>
        </div>

        <ol className="lg:order-1">
          {STEPS.map((s, i) => (
            <li key={s.n} ref={(el) => { refs.current[i] = el; }} data-step={i}
                aria-current={active === i ? "step" : undefined}
                className="flex min-h-[72vh] flex-col justify-center py-10 first:pt-6 lg:min-h-[86vh]">
              <motion.div initial={false} animate={{ opacity: active === i || reduced ? 1 : 0.35 }} transition={{ duration: 0.6, ease: [0.65, 0.05, 0, 1] }}>
                <div className="flex items-baseline gap-4">
                  <span className="font-mono text-sm text-[var(--fl-ember)]">{s.n}</span>
                  <h3 className="text-[32px] font-[510] tracking-[-0.025em] text-zinc-50 sm:text-[40px]">{s.title}</h3>
                </div>
                <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[var(--fl-subtle)]">{s.tag}</p>
                <p className="mt-5 max-w-xl text-[16px] leading-relaxed text-[var(--fl-muted)]">{s.body}</p>
                <div className="mt-6 max-w-xl">
                  <CodeCard title={s.snippet.id} meta={`templates/${s.snippet.file}`} code={s.snippet.code} />
                </div>
              </motion.div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/**
 * "One incident" (above the pinned figure): one segment per step, unequal widths for rhythm (not data), the
 * done and active segments filled, the rest dim, then fine dashes for the incidents that start warm after it.
 * The segments are the step buttons. Phones show the step numbers, wider screens the short titles.
 */
function StoryBar({ active, onPick, reduced }: { active: number; onPick: (i: number) => void; reduced: boolean }) {
  const t = reduced ? { duration: 0 } : { duration: 0.5, ease: [0.35, 0, 0, 1] as const };
  return (
    <nav aria-label="Proof steps">
      <div className="flex items-baseline justify-between font-mono text-[11px] text-zinc-400">
        <span className="uppercase tracking-[0.16em]">One incident</span>
        <span>illustrative</span>
      </div>
      <ol className="mt-2 flex gap-[3px]">
        {STEPS.map((s, i) => {
          const on = i === active;
          return (
            <li key={s.n} style={{ width: `${s.weight}%` }} className="min-w-0">
              <button type="button" onClick={() => onPick(i)} aria-label={`Step ${s.n}: ${s.title}`} aria-current={on ? "step" : undefined}
                      className="group block w-full rounded-[2px] pb-0.5 pt-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                <span className="relative block h-[6px] overflow-hidden rounded-[1px] bg-white/[0.16] transition-colors duration-150 group-hover:bg-white/[0.3]">
                  <motion.span aria-hidden className="absolute inset-0 origin-left bg-white" initial={false}
                               animate={{ scaleX: i <= active ? 1 : 0, opacity: on ? 1 : 0.72 }} transition={t} />
                </span>
                <span className={"mt-2 block truncate font-mono text-[11px] uppercase tracking-[0.1em] transition-colors duration-150 "
                                 + (on ? "text-zinc-50" : "text-zinc-400 group-hover:text-zinc-200")}>
                  <span className="sm:hidden">{s.n}</span>
                  <span className="hidden sm:inline">{s.short}</span>
                </span>
              </button>
            </li>
          );
        })}
        <li aria-hidden className="min-w-0 flex-1 pt-1.5">
          <span className="block h-[6px] bg-[repeating-linear-gradient(90deg,rgb(255_255_255/0.22)_0_2px,transparent_2px_5px)]" />
        </li>
      </ol>
    </nav>
  );
}
