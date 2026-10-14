"use client";

import { motion } from "framer-motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { Mark } from "@/components/motion/Mark";
import { Contours } from "@/components/motion/Contours";

const SLIDE = [0.65, 0.05, 0, 1] as const;

/** Three ideas as figure cards: isometric line art that draws itself in, a light that follows the pointer. */
export function Features() {
  const reduced = useReducedMotion();
  const cards = [
    { fig: "FIG 0.1", title: "Path, or no claim", art: <FigPath reduced={reduced} />,
      body: "algo.SPpaths looks for the causal chain from a change to the symptom. If FalkorDB returns no path, the change is out, whatever the model thinks." },
    { fig: "FIG 0.2", title: "Capacity, not coincidence", art: <FigFlow reduced={reduced} />,
      body: "algo.maxFlow bounds how much of the impact a suspect can explain. A same-minute deploy on a best-effort edge carries 0.02 of it: rejected." },
    { fig: "FIG 0.3", title: "Contain it on a copy", art: <FigCopy reduced={reduced} />,
      body: "The containment is the min-cut, tried first on a GRAPH.COPY clean room with a predicted outcome; then one human-approved action, verified." },
  ];
  return (
    <section aria-labelledby="features-title" className="relative isolate mx-auto max-w-[1200px] px-5 py-24 sm:px-8 lg:py-32">
      <Contours opacity={0.07} />
      <h2 id="features-title" className="max-w-[920px] text-[clamp(1.9rem,4.2vw,3rem)] font-[510] leading-[1.08] tracking-[-0.022em] text-zinc-50">
        An on-call agent that <Mark>proves before it blames.</Mark>{" "}
        <span className="text-[var(--fl-muted)]">Every claim it makes is a FalkorDB query: a causal path, enough flow to carry the impact, and the smallest cut that contains it.</span>
      </h2>
      <div className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.08] md:grid-cols-3">
        {cards.map((c, i) => (
          <motion.article key={c.fig} data-spot
                          initial={reduced ? false : { opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.3 }}
                          transition={reduced ? { duration: 0 } : { duration: 0.75, delay: i * 0.08, ease: SLIDE }}
                          className="flex flex-col bg-[var(--fl-bg)] p-7">
            <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--fl-subtle)]">{c.fig}</p>
            <div className="my-8 flex h-40 items-center justify-center">{c.art}</div>
            <h3 className="text-[19px] font-[590] tracking-[-0.012em] text-zinc-100">{c.title}</h3>
            <p className="mt-2 text-[15px] leading-relaxed text-[var(--fl-muted)]">{c.body}</p>
          </motion.article>
        ))}
      </div>
    </section>
  );
}

/* --- line art: isometric planes, our own drawings --- */
const GREY = "rgb(255 255 255 / 0.28)";
const plane = (cx: number, cy: number, w = 74, h = 30) => `M ${cx} ${cy - h} L ${cx + w} ${cy} L ${cx} ${cy + h} L ${cx - w} ${cy} Z`;

function Draw({ d, reduced, delay = 0, stroke = GREY, width = 1, dash }: { d: string; reduced: boolean; delay?: number; stroke?: string; width?: number; dash?: string }) {
  return (
    <motion.path d={d} fill="none" stroke={stroke} strokeWidth={width} strokeDasharray={dash} strokeLinecap="round" strokeLinejoin="round"
                 initial={reduced ? false : { pathLength: 0, opacity: 0 }} whileInView={{ pathLength: 1, opacity: 1 }} viewport={{ once: true, amount: 0.6 }}
                 transition={reduced ? { duration: 0 } : { duration: 1.2, delay, ease: SLIDE }} />
  );
}

/** Three stacked layers (changes, services, symptoms) and the causal path piercing them. */
function FigPath({ reduced }: { reduced: boolean }) {
  return (
    <svg viewBox="0 0 240 160" className="h-full w-auto" aria-hidden>
      {[40, 80, 120].map((y, i) => <Draw key={y} d={plane(120, y)} reduced={reduced} delay={i * 0.12} />)}
      {[[96, 40], [140, 34], [104, 80], [150, 86], [120, 120]].map(([x, y], i) => (
        <motion.circle key={i} cx={x} cy={y} r={3} fill="#0b0b0c" stroke={GREY}
                       initial={reduced ? false : { scale: 0 }} whileInView={{ scale: 1 }} viewport={{ once: true }} transition={{ delay: reduced ? 0 : 0.5 + i * 0.06 }} />
      ))}
      <Draw d="M 96 40 L 104 80 L 120 120" reduced={reduced} delay={0.8} stroke="var(--fl-ember)" width={2} />
      <Draw d="M 140 34 L 150 86" reduced={reduced} delay={0.9} dash="2 4" />
    </svg>
  );
}

/** Two channels into one symptom: a wide one that carries the impact and a hairline that carries 0.02 of it. */
function FigFlow({ reduced }: { reduced: boolean }) {
  return (
    <svg viewBox="0 0 240 160" className="h-full w-auto" aria-hidden>
      <Draw d={plane(120, 120, 60, 24)} reduced={reduced} />
      <Draw d="M 40 40 C 90 40, 90 112, 112 116" reduced={reduced} delay={0.2} stroke="var(--fl-proof)" width={7} />
      <Draw d="M 200 40 C 150 40, 150 112, 128 116" reduced={reduced} delay={0.35} width={1} dash="2 4" />
      <text x="174" y="32" fontSize="10" className="fill-zinc-500 font-mono">0.02</text>
      <text x="22" y="32" fontSize="10" className="fill-zinc-500 font-mono">1.00</text>
    </svg>
  );
}

/** The graph, copied (GRAPH.COPY), with the min-cut drawn across the front copy. */
function FigCopy({ reduced }: { reduced: boolean }) {
  return (
    <svg viewBox="0 0 240 160" className="h-full w-auto" aria-hidden>
      {[0, 1, 2].map((k) => <Draw key={k} d={plane(104 + k * 16, 72 + k * 18, 64, 26)} reduced={reduced} delay={k * 0.14} stroke={k === 2 ? "rgb(255 255 255 / 0.45)" : GREY} />)}
      <Draw d="M 92 92 L 180 140" reduced={reduced} delay={0.7} stroke="var(--fl-ember)" width={1.6} dash="5 4" />
      <motion.g initial={reduced ? false : { opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: reduced ? 0 : 1.1 }}>
        <circle cx="136" cy="116" r="7" fill="#0b0b0c" stroke="var(--fl-ember)" />
        <path d="M 133 113 L 139 119 M 139 113 L 133 119" stroke="var(--fl-ember)" strokeWidth="1.4" strokeLinecap="round" />
      </motion.g>
    </svg>
  );
}
