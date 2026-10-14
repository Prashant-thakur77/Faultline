"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

/**
 * The S1 hero incident as the gate decides it, in seven scenes:
 *  0 checkout alerts → 1 the search ripples upstream → 2 D-rec-12 has no path to checkout (G2) →
 *  3 D-email-88 has a path but its edge carries 0.02 of the impact (G5) → 4 D-pay-417's causal path is drawn (proof) →
 *  5 the min-cut out of payment is marked on payment → checkout (containment) → 6 the fix is verified APPLIED and the alert clears.
 * Uncontrolled (`scene` unset) it loops; controlled, the scroll story drives it. Reduced motion shows a still frame.
 * Verdicts are HUD callouts on leader lines. The ids and checks are the hero scenario's (data/scenarios,
 * docs/EVALS.md); nothing is computed here.
 */
export const SCENES = 7;
const STEP_MS = 1500;

const N = {
  rec: { x: 74, y: 78, label: "D-rec-12" },
  email: { x: 74, y: 210, label: "D-email-88" },
  pay: { x: 74, y: 342, label: "D-pay-417" },
  srec: { x: 268, y: 78, label: "recommendation" },
  semail: { x: 268, y: 210, label: "email" },
  spay: { x: 268, y: 342, label: "payment" },
  front: { x: 470, y: 78, label: "frontend" },
  check: { x: 470, y: 276, label: "checkout" },
} as const;

const EMBER = "var(--fl-ember)";
const IRIS = "var(--fl-iris)";
const PROOF = "var(--fl-proof)";
const EASE = [0.22, 1, 0.36, 1] as const;

function curve(a: { x: number; y: number }, b: { x: number; y: number }, dx = 60) {
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const on = () => setNarrow(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

export function GraphHeroArt({ className = "", scene, paused = false }: { className?: string; scene?: number; paused?: boolean }) {
  const reduced = useReducedMotion();
  const narrow = useNarrow();   // phones: the art renders at ~55% scale, so labels get larger units
  const fs = narrow ? 1.3 : 1;
  const [tick, setTick] = useState(0);
  const controlled = scene !== undefined;
  useEffect(() => {
    if (reduced || controlled || paused) return;   // reduced motion, driven from outside, or still hidden: no timer
    const t = setInterval(() => setTick((p) => (p + 1) % (SCENES + 1)), STEP_MS);
    return () => clearInterval(t);
  }, [reduced, controlled, paused]);
  const phase = controlled ? scene : reduced ? 4 : tick;
  const at = (k: number) => phase >= k && phase <= SCENES - 1;
  const only = (a: number, b: number) => phase >= a && phase <= b;
  const verified = at(6);

  const edges = [
    { id: "srec-front", d: curve(N.srec, N.front), w: 1.6 },
    { id: "semail-check", d: curve(N.semail, N.check), w: 1, dash: "3 5" },
    { id: "spay-check", d: curve(N.spay, N.check), w: 2.4 },
    { id: "front-check", d: `M ${N.check.x} ${N.check.y - 26} L ${N.front.x} ${N.front.y + 26}`, w: 1, dash: "2 6" },
  ];
  const proofD = `M ${N.pay.x + 52} ${N.pay.y} L ${N.spay.x - 58} ${N.spay.y} ${curve(N.spay, N.check).replace("M", "L")}`;
  const cut = { x: 384, y: 300 };   // on payment → checkout, one of the two edges in the plan's min-cut (Q-CUT-1)

  return (
    <svg viewBox="0 0 600 420" className={className} role="img"
         aria-label="Animated proof of the hero incident: checkout alerts; D-rec-12 has no path to it (G2); D-email-88's path cannot carry the impact (G5, 0.02); D-pay-417's causal path is proved; the min-cut out of payment is marked; the fix, flag paymentGate off, is verified APPLIED.">
      <defs>
        <radialGradient id="fl-node" cx="50%" cy="40%" r="60%">
          <stop offset="0" stopColor="oklch(0.32 0.02 285)" />
          <stop offset="1" stopColor="oklch(0.2 0.01 285)" />
        </radialGradient>
        <filter id="fl-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <pattern id="fl-dots" width="20" height="20" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.8" fill="oklch(1 0 0 / 0.07)" />
        </pattern>
      </defs>
      <rect width="600" height="420" fill="url(#fl-dots)" />
      {[[8, 8], [592, 8], [8, 412], [592, 412]].map(([x, y], i) => (
        <path key={i} d={`M ${x - 5} ${y} H ${x + 5} M ${x} ${y - 5} V ${y + 5}`} stroke="oklch(1 0 0 / 0.25)" strokeWidth="1" />
      ))}

      {narrow ? null : [["changes", 74], ["services", 268], ["symptoms", 470]].map(([t, x]) => (
        <text key={t as string} x={x as number} y={24} textAnchor="middle" className="fill-zinc-400 font-mono" fontSize="10.5" letterSpacing="2.5">
          {(t as string).toUpperCase()}
        </text>
      ))}

      {/* CHANGED edges, sketched in first (the wireframe before the nodes) */}
      {(["rec", "email", "pay"] as const).map((k, i) => {
        const svc = N[("s" + k) as "srec" | "semail" | "spay"];
        return (
          <motion.path key={k} d={`M ${N[k].x + 52} ${N[k].y} L ${svc.x - 58} ${svc.y}`} stroke="oklch(1 0 0 / 0.2)" strokeWidth="1.2" fill="none"
                       initial={reduced ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
                       transition={{ duration: 0.9, delay: 0.1 + i * 0.08, ease: EASE }} />
        );
      })}

      {/* failure-flow edges, with the search ripple travelling upstream from the alert */}
      {edges.map((e, i) => (
        <g key={e.id}>
          <motion.path d={e.d} stroke={IRIS} strokeOpacity={0.4} strokeWidth={e.w} strokeDasharray={e.dash} fill="none"
                       initial={reduced ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
                       transition={{ duration: 1.1, delay: 0.25 + i * 0.1, ease: EASE }} />
          {e.id === "semail-check" || e.id === "spay-check" ? (
            <motion.path d={e.d} stroke={EMBER} strokeWidth={e.w + 1.5} fill="none" strokeLinecap="round" initial={false}
                         animate={only(1, 3) && !reduced ? { pathLength: [0, 1], pathOffset: [1, 0], opacity: [0, 0.9, 0] } : { opacity: 0 }}
                         transition={{ duration: 1.2, ease: "easeInOut" }} />
          ) : null}
        </g>
      ))}

      {/* the proof path: D-pay-417 → payment → checkout */}
      <motion.path d={proofD} stroke={PROOF} strokeWidth="3.5" fill="none" strokeLinecap="round" filter="url(#fl-glow)"
                   initial={false} animate={at(4) ? { pathLength: 1, opacity: 1 } : { pathLength: 0, opacity: 0 }}
                   transition={{ duration: reduced ? 0 : 1.1, ease: EASE }} />

      {/* the min-cut mark on payment → checkout */}
      <motion.g initial={false} animate={{ opacity: at(5) ? 1 : 0 }} transition={{ duration: 0.4 }}>
        <circle cx={cut.x} cy={cut.y} r={13} fill="oklch(0.16 0.01 285)" stroke={EMBER} strokeWidth="1.5" />
        <path d={`M ${cut.x - 6} ${cut.y - 6} L ${cut.x + 6} ${cut.y + 6} M ${cut.x + 6} ${cut.y - 6} L ${cut.x - 6} ${cut.y + 6}`}
              stroke={EMBER} strokeWidth="2" strokeLinecap="round" />
      </motion.g>

      {/* alert rings on checkout; they stop once the fix verifies */}
      {[0, 1, 2].map((i) => (
        <motion.circle key={i} cx={N.check.x} cy={N.check.y} r={30} fill="none" stroke={EMBER} strokeWidth="1.5" initial={false}
                       animate={!verified && !reduced ? { r: [30, 70], opacity: [0.6, 0] } : { opacity: 0 }}
                       transition={verified ? { duration: 0.3 } : { duration: 2.4, delay: i * 0.8, repeat: Infinity, ease: "easeOut" }} />
      ))}

      {/* nodes */}
      {(Object.keys(N) as (keyof typeof N)[]).map((k, i) => {
        const n = N[k];
        const isChange = k === "rec" || k === "email" || k === "pay";
        const w = (isChange ? 104 : k === "srec" ? 128 : 112) * (narrow ? 1.18 : 1);
        const dim = (k === "rec" && at(2)) || (k === "email" && at(3));
        const proved = k === "pay" && at(4);
        const symptom = k === "check";
        const stroke = symptom ? (verified ? PROOF : EMBER) : proved ? PROOF : "oklch(1 0 0 / 0.14)";
        return (
          <motion.g key={k} initial={reduced ? false : { opacity: 0 }} animate={{ opacity: dim ? 0.38 : 1 }}
                    transition={{ duration: 0.5, delay: reduced ? 0 : 0.45 + i * 0.05 }}>
            <rect x={n.x - w / 2} y={n.y - 22} width={w} height={44} rx={isChange ? 10 : 22}
                  fill="url(#fl-node)" stroke={stroke} strokeWidth={proved || symptom ? 1.8 : 1} />
            <text x={n.x} y={n.y + 5} textAnchor="middle" fontSize={14 * fs} className={isChange ? "fill-zinc-100 font-mono" : "fill-zinc-200"}>
              {n.label}
            </text>
          </motion.g>
        );
      })}

      {/* HUD callouts on leader lines */}
      <Callout show={at(2)} from={[N.rec.x, N.rec.y + 22]} to={[N.rec.x, N.rec.y + 54]} left={N.rec.x - 52} tone={EMBER} text={narrow ? "G2 · no path" : "G2 · no path to checkout"} fs={fs} />
      <Callout show={at(3)} from={[N.email.x, N.email.y + 22]} to={[N.email.x, N.email.y + 54]} left={N.email.x - 52} tone={EMBER} text="G5 · carries 0.02" fs={fs} />
      <Callout show={at(4)} from={[N.pay.x, N.pay.y + 22]} to={[N.pay.x, N.pay.y + 54]} left={N.pay.x - 52} tone={PROOF} text={narrow ? "proved" : "proved · path + flow"} fs={fs} />
      <Callout show={at(5) && !verified} from={[cut.x, cut.y + 13]} to={[cut.x + 36, cut.y + 74]} tone={EMBER} text={narrow ? "min-cut" : "min-cut · out of payment"} fs={fs} />
      <Callout show={verified} from={[N.check.x, N.check.y + 22]} to={[N.check.x + 10, N.check.y + 74]} tone={PROOF} text="verified · APPLIED" fs={fs} />
    </svg>
  );
}

function Callout({ show, from, to, tone, text, fs = 1, left }: { show: boolean; from: [number, number]; to: [number, number]; tone: string; text: string; fs?: number; left?: number }) {
  const w = (text.length * 6.6 + 22) * fs;
  const x = left ?? to[0] - w / 2;   // `left`: box starts there (the change column sits on the art's left edge)
  return (
    <motion.g initial={false} animate={{ opacity: show ? 1 : 0 }} transition={{ duration: 0.35 }}>
      <motion.path d={`M ${from[0]} ${from[1]} L ${to[0]} ${to[1] - 12 * fs}`} stroke={tone} strokeOpacity="0.7" strokeWidth="1" fill="none"
                   initial={false} animate={{ pathLength: show ? 1 : 0 }} transition={{ duration: 0.4 }} />
      <circle cx={from[0]} cy={from[1]} r="2.2" fill={tone} />
      <rect x={x} y={to[1] - 12 * fs} width={w} height={22 * fs} rx={3} fill="oklch(0.15 0.01 285)" stroke={tone} strokeOpacity="0.75" />
      <text x={x + w / 2} y={to[1] + 3.5 * fs} textAnchor="middle" fontSize={11 * fs} fill={tone} className="font-mono" letterSpacing="0.3">{text}</text>
    </motion.g>
  );
}
