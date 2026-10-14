"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight, Pause, Play } from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { BASE_PATH } from "@/lib/site";

/** How long (ms) each screen stays up while the tour plays by itself. */
export const TOUR_ADVANCE_MS = 6000;

/** A point on the screenshot, in percent of its width and height (the shots are 1440×900). */
type Pt = { x: number; y: number };

type Callout = {
  text: string;
  /** what the dot points at */
  anchor: Pt;
  /** where the leader line meets the bubble */
  bubble: Pt;
  /** which way the bubble extends from its point */
  side: "left" | "right";
};

type Shot = {
  id: string;
  tab: string;
  eyebrow: string;
  title: [string, string];
  body: string;
  href: string;
  src: string;
  alt: string;
  callout: Callout;
};

/* Callout anchors were placed by eye on each 1440×900 screenshot in public/shots/. */
export const TOUR_SHOTS: Shot[] = [
  {
    id: "incident", tab: "Incident room", eyebrow: "Incident room",
    title: ["One incident,", "decided in the open."],
    body: "The stage timeline, the failure path lit hop by hop, and every suspect the gate tried, each ruled in or out by a query you can open.",
    href: "/replay/s1-hero", src: "/shots/incident-room-full.webp",
    alt: "The incident room on the hero scenario: the stage timeline, the failure-flow graph with the proof path, and the suspects: D-pay-417 confirmed, D-email-88 and D-rec-12 eliminated by the gate, each with its reason.",
    callout: { text: "two look-alike deploys eliminated by the gate", anchor: { x: 77.9, y: 55 }, bubble: { x: 66, y: 45 }, side: "left" },
  },
  {
    id: "crew", tab: "Crew", eyebrow: "Crew",
    title: ["Specialists hand off,", "they do not chat."],
    body: "Each specialist claims its step, runs its templates and hands off. The lane shows who claimed what, which query it ran and how long it took.",
    href: "/replay/s1-hero", src: "/shots/crew.webp",
    alt: "The crew lanes of the hero incident: Triage groups the alert storm and hands to Historian, which recalls precedents and runbooks; each step shows who claimed it, the queries it ran and their timings.",
    callout: { text: "every step is a record in FalkorDB", anchor: { x: 24, y: 64.2 }, bubble: { x: 31, y: 76 }, side: "right" },
  },
  {
    id: "why", tab: "Why", eyebrow: "Provenance",
    title: ["Ask why,", "get the edges."],
    body: "Agent, tool call, evidence, verdict: every arrow is a stored edge, so the answer to “why do you believe this?” is itself a query.",
    href: "/replay/s1-hero", src: "/shots/provenance.webp",
    alt: "The “Why do you believe this?” panel: agents, their tool calls, the evidence each produced and the verdict D-pay-417 confirmed, connected by stored edges.",
    callout: { text: "the verdict's own provenance, edge by edge", anchor: { x: 74.3, y: 46.5 }, bubble: { x: 70, y: 64 }, side: "left" },
  },
  {
    id: "preflight", tab: "Preflight", eyebrow: "Pre-deploy gate",
    title: ["The same graph,", "before the deploy."],
    body: "A pull request is scored on what it reaches, who must review it and which decisions it contradicts, including one the org already reversed.",
    href: "/preflight", src: "/shots/preflight-reversal.webp",
    alt: "Preflight on a pull request: the verdict is require review, with an amber card saying the change reinstates a reversed decision, ADR-009 replaced by ADR-021, and the weighted risk terms below.",
    callout: { text: "reinstates a decision the org reversed", anchor: { x: 45.1, y: 55.3 }, bubble: { x: 40, y: 62 }, side: "left" },
  },
  {
    id: "brain", tab: "Brain", eyebrow: "Company brain",
    title: ["Every decision,", "with its people."],
    body: "Ask who decided something and whether they are still here. Every id in the answer was returned by a read-only query of that question.",
    href: "/brain", src: "/shots/brain-graph.webp",
    alt: "The company brain answering “Who decided the payment timeout, and are they still here?”: the decisions, who made them and whether they are still on the team, and the answer drawn as a graph of people, decisions, context and systems.",
    callout: { text: "who decided, and are they still here", anchor: { x: 46.9, y: 76 }, bubble: { x: 41, y: 64 }, side: "left" },
  },
];

const EASE = [0.25, 0.46, 0.45, 0.94] as const;
/** Callout blue: white 13 px text on it is 5.2:1. */
const BLUE = "#2563eb";
const BLUE_LINE = "#3b82f6";

/**
 * "See it work": a tabbed tour of real screens. Each screenshot carries one callout pointing at the one thing that
 * screen proves. It advances by itself every few seconds only while on screen, not hovered and not focused, never
 * under reduced motion; choosing a tab stops it (the play button resumes).
 */
export function ProductTour() {
  const reduced = useReducedMotion();
  const [tab, setTab] = useState(0);
  const [visible, setVisible] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [stopped, setStopped] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const playing = !reduced && !stopped && visible && !hovered && !focused;
  const s = TOUR_SHOTS[tab];

  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!playing) return;
    const t = window.setTimeout(() => setTab((i) => (i + 1) % TOUR_SHOTS.length), TOUR_ADVANCE_MS);
    return () => window.clearTimeout(t);
  }, [playing, tab]);

  // keep the active tab in view inside its own scrolling row (phones), without scrolling the page
  useEffect(() => {
    const list = listRef.current, btn = tabRefs.current[tab];
    if (!list || !btn || list.scrollWidth <= list.clientWidth) return;
    const left = btn.offsetLeft - (list.clientWidth - btn.offsetWidth) / 2;
    list.scrollTo?.({ left: Math.max(0, left), behavior: reduced ? "auto" : "smooth" });
  }, [tab, reduced]);

  const choose = (i: number, focus = false) => {
    setTab(i);
    setStopped(true);
    if (focus) tabRefs.current[i]?.focus();
  };
  const onKey = (e: React.KeyboardEvent) => {
    const n = TOUR_SHOTS.length;
    const next = e.key === "ArrowRight" ? (tab + 1) % n : e.key === "ArrowLeft" ? (tab - 1 + n) % n
      : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    choose(next, true);
  };

  return (
    <section ref={rootRef} id="tour" aria-labelledby="tour-title" className="relative isolate mx-auto max-w-[1280px] scroll-mt-20 px-5 py-24 sm:px-8 lg:py-32">
      <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-[var(--fl-subtle)]">Product tour</p>
      <h2 id="tour-title" className="mt-4 max-w-[920px] text-[clamp(1.9rem,4.2vw,3rem)] font-[510] leading-[1.08] tracking-[-0.022em] text-zinc-50">
        See it work.{" "}
        <span className="text-[var(--fl-muted)]">The same graph behind every screen, from the incident room to the company brain.</span>
      </h2>

      <div className="mt-14 grid gap-y-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)] lg:gap-x-14"
           onPointerEnter={() => setHovered(true)} onPointerLeave={() => setHovered(false)}
           onFocus={() => setFocused(true)}
           onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false); }}>
        <div className="flex min-w-0 items-stretch gap-2 lg:col-start-2">
          <div ref={listRef} role="tablist" aria-label="Product screens" onKeyDown={onKey}
               className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {TOUR_SHOTS.map((x, i) => {
              const on = i === tab;
              return (
                <button key={x.id} ref={(el) => { tabRefs.current[i] = el; }} type="button" role="tab" id={`tour-tab-${x.id}`}
                        aria-selected={on} aria-controls="tour-panel" tabIndex={on ? 0 : -1} onClick={() => choose(i)}
                        className={"relative min-w-max shrink-0 grow basis-0 whitespace-nowrap rounded-t-md border-t pb-3 pl-1 pr-5 pt-3 text-left font-mono text-[12px] uppercase tracking-[0.14em] outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400 "
                          + (on ? "border-white/60 text-zinc-50" : "border-white/[0.12] text-[var(--fl-muted)] hover:border-white/25 hover:text-zinc-200")}>
                  {x.tab}
                  {/* auto-advance progress, under the active tab; only drawn while the tour plays */}
                  <span className="absolute inset-x-1 bottom-0 h-px overflow-hidden" aria-hidden>
                    {on && playing ? (
                      <motion.span key={`p-${tab}`} className="block h-full origin-left" style={{ background: BLUE_LINE }}
                                   initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: TOUR_ADVANCE_MS / 1000, ease: "linear" }} />
                    ) : null}
                  </span>
                </button>
              );
            })}
          </div>
          {reduced ? null : (
            <button type="button" onClick={() => setStopped((v) => !v)} aria-pressed={!stopped}
                    aria-label={stopped ? "Play the tour" : "Pause the tour"}
                    className="fl-press mb-2 inline-flex size-8 shrink-0 items-center justify-center self-end rounded-full border border-white/[0.1] text-[var(--fl-muted)] outline-none hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400">
              {stopped ? <Play className="size-3.5" aria-hidden /> : <Pause className="size-3.5" aria-hidden />}
            </button>
          )}
        </div>

        <div id="tour-panel" role="tabpanel" aria-labelledby={`tour-tab-${s.id}`}
             className="grid gap-y-6 lg:col-span-2 lg:grid-cols-subgrid">
          <motion.div key={s.id} initial={reduced ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                      transition={reduced ? { duration: 0 } : { duration: 0.35, ease: EASE }} className="min-w-0 lg:pt-1">
            <p className="font-mono text-[12px] uppercase tracking-[0.18em]">
              <span className="text-[var(--fl-subtle)]">{String(tab + 1).padStart(2, "0")}</span>
              <span className="ml-3 text-zinc-200">{s.eyebrow}</span>
            </p>
            <h3 className="mt-5 text-[clamp(1.55rem,2.3vw,2rem)] font-[510] leading-[1.1] tracking-[-0.02em]">
              <span className="block text-zinc-50">{s.title[0]}</span>
              <span className="block text-[var(--fl-muted)]">{s.title[1]}</span>
            </h3>
            <p className="mt-5 max-w-md text-[16px] leading-relaxed text-[var(--fl-muted)]">{s.body}</p>
            <Link href={s.href} className="group mt-6 inline-flex items-center gap-1.5 rounded text-[15px] text-zinc-100 outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-sky-400">
              Open it live
              <ArrowUpRight className="size-4 text-[var(--fl-muted)] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden />
              <span className="sr-only">: {s.tab}</span>
            </Link>
          </motion.div>

          <figure className="min-w-0">
            <div className="rounded-[14px] border border-white/10 bg-[var(--fl-surface)] p-1 shadow-[0_40px_120px_-40px_rgb(0_0_0/0.9),0_0_0_1px_rgb(0_0_0/0.4)] sm:rounded-[18px] sm:p-1.5">
              <div className="relative aspect-[1440/900] overflow-hidden rounded-[10px] sm:rounded-[13px]">
                {TOUR_SHOTS.map((x, i) => {
                  const on = i === tab;
                  return (
                    <motion.div key={x.id} aria-hidden={!on} className="absolute inset-0" style={{ zIndex: on ? 1 : 0 }}
                                initial={false} animate={{ opacity: on ? 1 : 0, scale: on ? 1 : 1.02 }}
                                transition={reduced ? { duration: 0 } : { duration: 0.38, ease: EASE }}>
                      {/* eslint-disable-next-line @next/next/no-img-element -- static export: a plain, pre-compressed WebP */}
                      <img src={`${BASE_PATH}${x.src}`} width={1440} height={900} alt={on ? x.alt : ""}
                           loading={i === 0 ? "eager" : "lazy"} decoding="async" className="block h-auto w-full" />
                      <CalloutMark c={x.callout} reduced={reduced} />
                    </motion.div>
                  );
                })}
              </div>
            </div>
            {/* phones: the bubble would cover the shot, so the callout becomes a caption */}
            <figcaption className="mt-3 flex items-start gap-2 text-[14px] leading-snug text-zinc-200 sm:sr-only">
              <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: BLUE_LINE }} aria-hidden />
              <span>{s.callout.text}</span>
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}

/** The dot (with a pulsing ring), the leader line and the bubble; the bubble and line from 640 px up. */
function CalloutMark({ c, reduced }: { c: Callout; reduced: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      <svg className="absolute inset-0 hidden h-full w-full sm:block" viewBox="0 0 100 100" preserveAspectRatio="none">
        <line x1={c.anchor.x} y1={c.anchor.y} x2={c.bubble.x} y2={c.bubble.y} stroke={BLUE_LINE} strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="absolute size-2.5 -translate-x-1/2 -translate-y-1/2 sm:size-3" style={{ left: `${c.anchor.x}%`, top: `${c.anchor.y}%` }}>
        {reduced ? null : <span className="absolute inset-0 animate-ping rounded-full opacity-70 motion-reduce:animate-none" style={{ background: BLUE_LINE }} />}
        <span className="absolute inset-0 rounded-full border-2 border-white" style={{ background: BLUE }} />
      </span>
      <span className={"absolute hidden -translate-y-1/2 whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-medium leading-tight text-white shadow-[0_8px_24px_-8px_rgb(0_0_0/0.7)] sm:block md:text-[12px] lg:rounded-lg lg:px-2.5 lg:py-1.5 lg:text-[13px] "
                        + (c.side === "left" ? "-translate-x-full" : "")}
            style={{ left: `${c.bubble.x}%`, top: `${c.bubble.y}%`, background: BLUE, borderColor: BLUE_LINE }}>
        {c.text}
      </span>
    </div>
  );
}
