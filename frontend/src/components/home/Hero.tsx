"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, ChevronRight, Hammer } from "lucide-react";
import { useEvalSummary } from "@/hooks/useEvalSummary";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useIntroDone } from "@/lib/intro";
import { Contours } from "@/components/motion/Contours";
import { DATA_SCENARIO, requestHeroRun, requestScenarioRun } from "@/lib/heroRun";
import { BASE_PATH, STATIC_SITE } from "@/lib/site";

const SLIDE = [0.65, 0.05, 0, 1] as const;

// three.js only loads in the browser, after the page: the hero reads fine without it
const HeroGraph3D = dynamic(() => import("./HeroGraph3D"), { ssr: false, loading: () => null });

/**
 * Home hero: headline, one line, actions, then the product itself in a frame that flattens as it scrolls in;
 * a serif headline in a white gradient; reveal timing from the intro loader. The product
 * shot is a real screenshot of the incident room on the hero scenario (frontend/scripts/screenshots.py).
 */
export function Hero() {
  const reduced = useReducedMotion();
  const ready = useIntroDone();   // the intro has wiped (or was skipped): start the reveal
  // three.js loads once the reveal has started and the browser is idle, so it never stalls the intro or the headline
  const [show3d, setShow3d] = useState(false);
  useEffect(() => {
    if (!ready) return;
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (id: number) => void };
    // after the route's slide-in (template.tsx, 0.42 s): starting WebGL during it makes the switch to this page stutter
    let id: number | undefined;
    const t = setTimeout(() => {
      if (w.requestIdleCallback) id = w.requestIdleCallback(() => setShow3d(true), { timeout: 1200 });
      else setShow3d(true);
    }, 480);
    return () => { clearTimeout(t); if (id !== undefined) w.cancelIdleCallback?.(id); };
  }, [ready]);
  // Reduced motion still passes a target (instant): hydration renders with motion on, and a motion element whose
  // `animate` disappears keeps its last value, which would leave the hero at opacity 0.
  const still = { initial: false as const, transition: { duration: 0 } };
  const rise = (d: number) =>
    reduced ? { ...still, animate: { opacity: 1, y: 0 } }
      : { initial: { opacity: 0, y: 18 }, animate: ready ? { opacity: 1, y: 0 } : { opacity: 0, y: 18 }, transition: { duration: 0.75, delay: d, ease: SLIDE } };
  // headline lines rise out of their own masks, one after another
  const line = (d: number) =>
    reduced ? { ...still, animate: { y: "0%" } }
      : { initial: { y: "105%" }, animate: ready ? { y: "0%" } : { y: "105%" }, transition: { duration: 1, delay: d, ease: SLIDE } };
  const cta = "fl-press group inline-flex h-11 items-center gap-2 rounded-full px-5 text-[15px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-sky-400";

  return (
    <section aria-labelledby="hero-title" className="relative isolate shrink-0 overflow-hidden">
      <div className="fl-aurora -z-10" aria-hidden />
      <div className="fl-beam -z-10" aria-hidden />
      <Contours opacity={0.13} />
      <Frame />
      <div className="mx-auto grid max-w-[1240px] items-center gap-4 px-5 pt-14 sm:px-8 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)] lg:pt-16">
        <div>
          <motion.div {...rise(0)}>
            <a href="#api" className="fl-ring fl-press inline-flex rounded-full p-px outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#0b0b0c] px-3.5 py-1 text-[13px] text-zinc-200">
                New: graph-ranked context packs for your agent <ChevronRight className="size-3.5 text-zinc-400" aria-hidden />
              </span>
            </a>
          </motion.div>
          <h1 id="hero-title" className="font-hero mt-7 text-[clamp(3.1rem,7.6vw,6.4rem)] leading-[0.9]">
            <span className="block overflow-hidden pb-[0.05em]"><motion.span {...line(0.05)} className="block text-zinc-50">No path,</motion.span></span>
            <span className="block overflow-hidden pb-[0.08em]"><motion.span {...line(0.17)} className="fl-gradient-text block pr-2">no claim.</motion.span></span>
          </h1>
          <motion.p {...rise(0.18)} className="mt-7 max-w-[34rem] text-[18px] leading-[1.55] text-[var(--fl-muted)]">
            Faultline won&apos;t blame a deploy until FalkorDB proves it: a causal path from the change to the symptom, and
            enough capacity on that path to carry the impact. Otherwise it says <span className="text-zinc-100">&ldquo;I don&apos;t know&rdquo;</span>.
          </motion.p>
          <motion.div {...rise(0.28)} className="mt-9 flex flex-wrap items-center gap-2">
            {STATIC_SITE ? (
              <Link href="/replay" data-magnetic className={cta + " bg-zinc-50 text-zinc-950 hover:bg-white"}>
                Watch a recorded incident <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            ) : (
              // scrolls to the launcher (#run) and starts the hero scenario there, so its progress and any error show
              <a href="#run" data-magnetic onClick={requestHeroRun} className={cta + " bg-zinc-50 text-zinc-950 hover:bg-white"}>
                Run the hero incident <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </a>
            )}
            {STATIC_SITE ? null : (
              // the cross-domain data incident: the agent proposes the transform repair and the warehouse verifies it
              <a href="#run" onClick={() => requestScenarioRun(DATA_SCENARIO)} className={cta + " text-zinc-200 hover:bg-white/[0.06]"}>
                Run the data incident
              </a>
            )}
            {STATIC_SITE ? null : (
              <Link href="/playground" className={cta + " text-zinc-200 hover:bg-white/[0.06]"}>
                <Hammer className="size-4" aria-hidden /> Break the graph
              </Link>
            )}
          </motion.div>
        </div>
        <motion.div initial={reduced ? false : { opacity: 0, scale: 0.94 }} animate={ready || reduced ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.94 }}
                    transition={reduced ? { duration: 0 } : { duration: 1.4, delay: 0.25, ease: SLIDE }}
                    className="relative -mx-5 h-[340px] sm:mx-0 sm:h-[440px] lg:-mr-12 lg:h-[560px]">
          {/* a soft floor light under the object */}
          <div className="pointer-events-none absolute inset-x-[12%] bottom-[8%] h-24 rounded-[50%] bg-[radial-gradient(closest-side,rgb(255_255_255/0.07),transparent)]" aria-hidden />
          {show3d ? <HeroGraph3D /> : null}
        </motion.div>
      </div>

      <motion.div {...rise(0.4)} className="mx-auto mt-16 max-w-[1260px] px-3 sm:px-6 lg:mt-20">
        <figure className="fl-tilt relative">
          <div className="rounded-[18px] border border-white/10 bg-[var(--fl-surface)] p-1.5 shadow-[0_40px_120px_-40px_rgb(0_0_0/0.9),0_0_0_1px_rgb(0_0_0/0.4)]">
            {/* eslint-disable-next-line @next/next/no-img-element -- static export: a plain, pre-compressed WebP */}
            <img src={`${BASE_PATH}/shots/incident-room.webp`} width={1440} height={900} decoding="async" fetchPriority="high"
                 alt="The incident room on the hero scenario: the stage timeline, the failure-flow graph with the proof path and the min-cut, the suspects (D-pay-417 confirmed; D-email-88 and D-rec-12 eliminated by the gate) and the evidence gate."
                 className="block h-auto w-full rounded-[13px]" />
          </div>
          {/* the frame dissolves into the page */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/5 rounded-b-[18px] bg-gradient-to-b from-transparent to-[var(--fl-bg)]" aria-hidden />
          <figcaption className="sr-only">The Faultline incident room</figcaption>
        </figure>
      </motion.div>
      <Numbers />
    </section>
  );
}

/** Framing marks: "+" registration marks at the corners, a ruler along the foot, a scroll cue. Decorative. */
function Frame() {
  return (
    <div className="pointer-events-none absolute inset-3 sm:inset-5" aria-hidden>
      {["left-0 top-0", "right-0 top-0"].map((pos) => (
        <span key={pos} className={`absolute ${pos} size-3 text-zinc-600`}>
          <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-current" />
          <span className="absolute left-0 top-1/2 h-px w-full -translate-y-1/2 bg-current" />
        </span>
      ))}
      <div className="absolute right-3 top-[52vh] hidden flex-col items-center gap-3 lg:flex">
        <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-zinc-500 [writing-mode:vertical-rl]">Scroll to explore</span>
        <span className="relative h-10 w-px overflow-hidden bg-white/10"><span className="fl-scroll-cue absolute inset-0 bg-zinc-300" /></span>
      </div>
    </div>
  );
}

/** Three numbers, read from public/evals/summary.json (copied from evals/results/latest.json). */
function Numbers() {
  const s = useEvalSummary();
  const v = s.state === "ok" ? s.summary.values : {};
  const get = (k: string) => (k in v && v[k] !== null ? String(v[k]) : "–");
  // each number says how to read it: two of them are zeros, and zero is the result we want
  const items: { big: string; unit: string; tag: string; good: string; text: React.ReactNode; exact?: string }[] = [
    // Safety, not accuracy: the honest trade (right causes, hand-offs to a human) is stated next to the zero.
    { big: get("deep.fresh.all.wrong_confident"), unit: "confident wrong blames", tag: "Safety", good: "lower is better",
      text: (
        <>
          confident wrong blames in {get("deep.fresh.all.cases")} generated test worlds built to trap it. The
          trade: {get("deep.fresh.all.right_cause")}/{get("deep.fresh.all.cause_cases")} right causes ·{" "}
          {get("deep.fresh.all.abstained")} of {get("deep.fresh.all.cases")} handed to a human
        </>
      ) },
    // the same worlds given to a strong LLM alone (evals/llm_deep.py): it finds more causes, and blames innocent changes
    { big: get("llm_deep.deep.all.wrong_confident"), unit: "wrong blames by an LLM", tag: "Versus an LLM", good: "same worlds",
      text: (
        <>
          confident wrong blames by a strong LLM alone (claude-opus-5-5) given the same telemetry on the same{" "}
          {get("llm_deep.deep.all.cases")} worlds: it names {get("llm_deep.deep.all.right_cause")}/{get("llm_deep.deep.all.cause_cases")}{" "}
          right causes, but nothing checks its guesses against the graph
        </>
      ) },
    // the real OpenTelemetry Demo with its own fault flags (evals/faultbench_otel.py): real services, real telemetry
    { big: get("otel.faultline.wrong.k"), unit: "wrong blames on real services", tag: "Real services", good: "lower is better",
      text: (
        <>
          wrong blames in {get("otel.faultline.wrong.n")} windows of the OpenTelemetry Demo&apos;s real services and
          telemetry, broken with its own fault flags (our topology and decoys):{" "}
          {get("otel.faultline.right_cause.k")}/{get("otel.faultline.right_cause.n")} right causes. A threshold on the same
          telemetry: {get("otel.Tplus.wrong.k")} wrong
        </>
      ) },
  ];
  return (
    <div className="mx-auto max-w-[1200px] px-5 pb-20 pt-6 sm:px-8">
      <dl className="grid border-y border-white/[0.08] sm:grid-cols-3">
        {items.map((it, i) => (
          <div key={i} className={"py-8 sm:px-8 " + (i ? "border-t border-white/[0.08] sm:border-l sm:border-t-0" : "sm:pl-0")}>
            <dt className="sr-only">{it.unit}</dt>
            <dd>
              <p className="mb-4 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--fl-subtle)]">
                {it.tag}<span className="size-1 rounded-full bg-white/25" aria-hidden /><span className="text-[var(--fl-proof)]">{it.good}</span>
              </p>
              <span className="text-[56px] font-[510] leading-none tracking-[-0.03em] text-zinc-50" title={it.exact}>{it.big}</span>
              <p className="mt-4 max-w-[22rem] text-[14px] leading-relaxed text-[var(--fl-muted)]">{it.text}</p>
            </dd>
          </div>
        ))}
      </dl>
      {s.state === "error" ? (
        <p role="alert" className="mt-4 text-xs text-red-300">Measured numbers unavailable: {s.error}</p>
      ) : (
        <p className="mt-5 font-mono text-[11px] text-[var(--fl-subtle)]">
          Measured and pre-registered · evals/results/latest.json{s.state === "ok" && s.summary.run ? ` (${s.summary.run})` : ""}
        </p>
      )}
    </div>
  );
}
