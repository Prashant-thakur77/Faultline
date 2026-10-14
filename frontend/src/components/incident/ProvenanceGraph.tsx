"use client";

import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Bot, CircleCheck, Code2, Crosshair, ShieldCheck } from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { fmtMs } from "@/lib/format";
import {
  REL_TEXT,
  agentKindText,
  agentName,
  edgeKey,
  isGateAgent,
  layoutProvenance,
  lineage,
  type DrawnRel,
  type ProvenanceLayout,
} from "@/lib/provenance";
import type { CrewMember, ProvenanceEdge, ProvenanceNode, ProvenanceResponse } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

/** Line colour of each drawn edge kind when it is lit (hover/focus); unlit edges are a neutral hairline. */
const REL_STROKE: Record<DrawnRel, string> = {
  MADE: "rgb(125 211 252 / 0.85)", // sky-300
  PRODUCED_EVIDENCE: "rgb(196 181 253 / 0.9)", // violet-300
  SUPPORTS: "var(--fl-proof)",
};
const REL_ORDER: DrawnRel[] = ["MADE", "PRODUCED_EVIDENCE", "SUPPORTS"];
const BASE_STROKE = "rgb(255 255 255 / 0.18)";
const EASE = [0.22, 1, 0.36, 1] as const;

export interface ProvenanceHeaderProps {
  titleId: string;
  descId?: string;
  /** The template every edge was read with (Q-PROV-1). */
  template: string;
  onOpenQuery: () => void;
}

/** Title, the one-line promise, and the query that backs it (opens in the Cypher panel). */
export function ProvenanceHeader({ titleId, descId, template, onOpenQuery }: ProvenanceHeaderProps) {
  return (
    <div className="min-w-0">
      <h2 id={titleId} className="text-base font-semibold tracking-[-0.01em] text-zinc-50">
        Why do you believe this?
      </h2>
      <p id={descId} className="mt-1 max-w-3xl text-xs leading-relaxed text-zinc-300">
        Every arrow below is a stored edge in FalkorDB ({template}): which agent&apos;s call produced which evidence
        for this verdict.
      </p>
      <button
        type="button"
        onClick={onOpenQuery}
        className="mt-2 inline-flex min-h-7 items-center gap-1.5 rounded-md border border-violet-400/30 bg-violet-500/10 px-2 font-mono text-[11px] text-violet-200 outline-none transition-colors hover:border-violet-300/50 hover:bg-violet-500/20 focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        <Code2 aria-hidden className="size-3.5" />
        {template}
        <span className="font-sans text-zinc-300">open the query</span>
        <span className="sr-only"> in the Cypher panel</span>
      </button>
    </div>
  );
}

export interface ProvenanceGraphProps {
  data: ProvenanceResponse;
  /** The run's crew roster (names crew roles); specialists and the gate are named without it. */
  roster?: CrewMember[];
  onOpenCall: (call: ProvenanceNode) => void;
  onOpenEvidence: (evidence: ProvenanceNode) => void;
}

/**
 * "Why do you believe this?" (M17, Q-PROV-1): the run's own reasoning as a layered graph, left to right
 * Agent → Call → Evidence → Verdict, with the graph nodes each call SAW hanging under it as chips. Order is
 * deterministic (layoutProvenance); lines are measured from the laid-out cards so wrapped text never breaks them.
 * Hover or focus a node to trace its lineage; calls and evidence open their Cypher. A table repeats it as text.
 */
export function ProvenanceGraph({ data, roster = [], onOpenCall, onOpenEvidence }: ProvenanceGraphProps) {
  const layout = useMemo(() => layoutProvenance(data), [data]);
  if (!layout.verdicts.length && !layout.evidence.length) {
    return (
      <p className="rounded-lg border border-dashed border-[var(--fl-line)] p-4 text-sm text-zinc-300">
        {data.template} returned no confirmed verdict with supporting evidence for this incident, so there is nothing
        to draw.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <Graph layout={layout} roster={roster} onOpenCall={onOpenCall} onOpenEvidence={onOpenEvidence} />
      <Legend />
      <TextAlternative layout={layout} roster={roster} />
    </div>
  );
}

interface Geometry {
  w: number;
  h: number;
  paths: Map<string, { d: string; mx: number; my: number }>;
}

/** Measure each drawn edge from its two cards (right-middle → left-middle), re-measured on resize. */
function useEdgeGeometry(ref: React.RefObject<HTMLDivElement | null>, edges: ProvenanceEdge[]): Geometry | null {
  const [geo, setGeo] = useState<Geometry | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let frame = 0;
    const measure = () => {
      const box = el.getBoundingClientRect();
      const at = new Map<string, DOMRect>();
      el.querySelectorAll<HTMLElement>("[data-prov-id]").forEach((n) => {
        if (n.dataset.provId) at.set(n.dataset.provId, n.getBoundingClientRect());
      });
      const paths = new Map<string, { d: string; mx: number; my: number }>();
      for (const e of edges) {
        const a = at.get(e.source);
        const b = at.get(e.target);
        if (!a || !b) continue;
        const x1 = a.right - box.left;
        const y1 = a.top + a.height / 2 - box.top;
        const x2 = b.left - box.left - 3; // leave room for the arrowhead
        const y2 = b.top + b.height / 2 - box.top;
        const dx = Math.max(16, (x2 - x1) / 2);
        paths.set(edgeKey(e), {
          d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
          mx: (x1 + x2) / 2,
          my: (y1 + y2) / 2,
        });
      }
      setGeo({ w: box.width, h: box.height, paths });
    };
    const queue = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    queue();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(queue) : null;
    ro?.observe(el);
    window.addEventListener("resize", queue);
    return () => {
      cancelAnimationFrame(frame);
      ro?.disconnect();
      window.removeEventListener("resize", queue);
    };
  }, [ref, edges]);
  return geo;
}

function Graph({
  layout,
  roster,
  onOpenCall,
  onOpenEvidence,
}: {
  layout: ProvenanceLayout;
  roster: CrewMember[];
  onOpenCall: (call: ProvenanceNode) => void;
  onOpenEvidence: (evidence: ProvenanceNode) => void;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const geo = useEdgeGeometry(ref, layout.edges);
  const markerBase = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [active, setActive] = useState<string | null>(null);
  const [hotEdge, setHotEdge] = useState<string | null>(null);
  const lit = useMemo(() => (active ? lineage(active, layout.edges) : null), [active, layout.edges]);
  const produces = useMemo(() => {
    const m = new Set<string>();
    for (const e of layout.edges) if (e.rel === "PRODUCED_EVIDENCE") m.add(e.target);
    return m;
  }, [layout.edges]);

  const hover = (id: string) => ({
    onMouseEnter: () => setActive(id),
    onMouseLeave: () => setActive((a) => (a === id ? null : a)),
    onFocus: () => setActive(id),
    onBlur: () => setActive((a) => (a === id ? null : a)),
  });
  const dim = (id: string) => (lit && !lit.nodes.has(id) ? "opacity-50" : "");
  const appear = (col: number, i: number) => ({
    initial: reduced ? { opacity: 1, x: 0 } : { opacity: 0, x: -6 },
    animate: { opacity: 1, x: 0 },
    transition: reduced ? { duration: 0 } : { duration: 0.35, delay: col * 0.12 + Math.min(i, 10) * 0.03, ease: EASE },
  });

  return (
    <div
      className="overflow-x-auto overscroll-x-contain rounded-xl border border-[var(--fl-line)] bg-black/20"
      role="group"
      aria-label="Provenance graph, left to right: agents, tool calls, evidence, verdict"
    >
      <div ref={ref} className="relative min-w-[980px] p-4">
        <svg aria-hidden className="absolute inset-0 overflow-visible" width={geo?.w ?? 0} height={geo?.h ?? 0}>
          <defs>
            {(["base", ...REL_ORDER] as const).map((k) => (
              <marker
                key={k}
                id={`${markerBase}-${k}`}
                viewBox="0 0 6 6"
                refX="5"
                refY="3"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L6,3 L0,6 z" fill={k === "base" ? BASE_STROKE : REL_STROKE[k]} />
              </marker>
            ))}
          </defs>
          {geo
            ? layout.edges.map((e) => {
                const k = edgeKey(e);
                const p = geo.paths.get(k);
                if (!p) return null;
                const on = hotEdge === k || !!lit?.edges.has(k);
                const labelled = hotEdge === k; // a label only on the hovered line: lit lineages stay uncluttered
                const faded = (lit && !on) || (hotEdge !== null && hotEdge !== k && !lit);
                const col = REL_ORDER.indexOf(e.rel);
                return (
                  <g key={k}>
                    <motion.path
                      d={p.d}
                      fill="none"
                      stroke={on ? REL_STROKE[e.rel] : BASE_STROKE}
                      strokeWidth={on ? 1.5 : 1}
                      markerEnd={`url(#${markerBase}-${on ? e.rel : "base"})`}
                      initial={reduced ? { pathLength: 1, opacity: 1 } : { pathLength: 0, opacity: 0 }}
                      animate={{ pathLength: 1, opacity: faded ? 0.3 : 1 }}
                      transition={
                        reduced ? { duration: 0 } : { duration: 0.5, delay: 0.15 + col * 0.18, ease: EASE }
                      }
                    />
                    {/* a wide invisible stroke so a hairline is hoverable; its <title> names the stored edge */}
                    <path
                      d={p.d}
                      fill="none"
                      stroke="transparent"
                      strokeWidth={10}
                      style={{ pointerEvents: "stroke" }}
                      onMouseEnter={() => setHotEdge(k)}
                      onMouseLeave={() => setHotEdge((h) => (h === k ? null : h))}
                    >
                      <title>{`${e.rel}: ${REL_TEXT[e.rel].what}`}</title>
                    </path>
                    {labelled ? (
                      <text
                        x={p.mx}
                        y={p.my - 4}
                        textAnchor="middle"
                        className="fill-zinc-200 font-mono text-[9.5px]"
                        style={{ paintOrder: "stroke", stroke: "var(--fl-surface)", strokeWidth: 4 }}
                      >
                        {e.rel}
                      </text>
                    ) : null}
                  </g>
                );
              })
            : null}
        </svg>

        <div className="pointer-events-none relative grid grid-cols-[minmax(160px,0.9fr)_minmax(220px,1.1fr)_minmax(240px,1.35fr)_minmax(160px,0.9fr)] gap-x-14">
          <Column title="Agents" count={layout.agents.length} rel="MADE">
            {layout.agents.map((a, i) => (
              <motion.li key={a.id} {...appear(0, i)} className="pointer-events-auto">
                <div className={cn("transition-opacity duration-150 motion-reduce:transition-none", dim(a.id))}>
                  <AgentCard node={a} roster={roster} hover={hover(a.id)} />
                </div>
              </motion.li>
            ))}
          </Column>
          <Column title="Tool calls" count={layout.calls.length} rel="PRODUCED_EVIDENCE">
            {layout.calls.map((c, i) => (
              <motion.li key={c.id} {...appear(1, i)} className="pointer-events-auto">
                <div className={cn("transition-opacity duration-150 motion-reduce:transition-none", dim(c.id))}>
                  <CallCard node={c} saw={layout.saw.get(c.id) ?? []} hover={hover(c.id)} onOpen={onOpenCall} />
                </div>
              </motion.li>
            ))}
          </Column>
          <Column title="Evidence" count={layout.evidence.length} rel="SUPPORTS">
            {layout.evidence.map((e, i) => (
              <motion.li key={e.id} {...appear(2, i)} className="pointer-events-auto">
                <div className={cn("transition-opacity duration-150 motion-reduce:transition-none", dim(e.id))}>
                  <EvidenceCard node={e} produced={produces.has(e.id)} hover={hover(e.id)} onOpen={onOpenEvidence} />
                </div>
              </motion.li>
            ))}
          </Column>
          <Column title="Verdict" count={layout.verdicts.length}>
            {layout.verdicts.map((v, i) => (
              <motion.li key={v.id} {...appear(3, i)} className="pointer-events-auto">
                <div className={cn("transition-opacity duration-150 motion-reduce:transition-none", dim(v.id))}>
                  <VerdictCard node={v} hover={hover(v.id)} />
                </div>
              </motion.li>
            ))}
          </Column>
        </div>
      </div>
    </div>
  );
}

function Column({
  title,
  count,
  rel,
  children,
}: {
  title: string;
  count: number;
  /** The edge kind leaving this column to the right. */
  rel?: DrawnRel;
  children: React.ReactNode;
}) {
  const hid = useId();
  return (
    <section aria-labelledby={hid} className="flex min-w-0 flex-col">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 id={hid} className="text-[11px] font-medium tracking-wide whitespace-nowrap text-zinc-400 uppercase">
          {title} <span className="font-mono normal-case">{count}</span>
        </h3>
        {rel ? (
          <span aria-hidden className="ml-auto font-mono text-[10px] whitespace-nowrap text-zinc-400">
            {rel} →
          </span>
        ) : null}
      </div>
      <ul aria-labelledby={hid} className="flex flex-1 flex-col justify-center gap-2.5">
        {children}
      </ul>
    </section>
  );
}

type Hover = {
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onFocus: () => void;
  onBlur: () => void;
};

const CARD =
  "w-full rounded-lg border px-2.5 py-2 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-sky-400";

function AgentCard({ node, roster, hover }: { node: ProvenanceNode; roster: CrewMember[]; hover: Hover }) {
  const gate = isGateAgent(node);
  const Icon = gate ? ShieldCheck : Bot;
  return (
    <div
      data-prov-id={node.id}
      onMouseEnter={hover.onMouseEnter}
      onMouseLeave={hover.onMouseLeave}
      className={cn(
        CARD,
        gate ? "border-emerald-400/30 bg-emerald-500/[0.05]" : "border-[var(--fl-line)] bg-white/[0.025]",
      )}
    >
      <p className="flex items-center gap-1.5 text-[13px] font-medium text-zinc-50">
        <Icon aria-hidden className={cn("size-3.5 shrink-0", gate ? "text-emerald-300" : "text-zinc-300")} />
        <span className="min-w-0 [overflow-wrap:anywhere]">{agentName(node, roster)}</span>
      </p>
      <p className={cn("mt-0.5 text-[11px]", gate ? "text-emerald-200" : "text-zinc-400")}>{agentKindText(node)}</p>
      {node.task ? (
        <p className="mt-0.5 truncate font-mono text-[10px] text-zinc-400" title={node.task}>
          <span className="sr-only">task </span>
          {node.task}
        </p>
      ) : null}
    </div>
  );
}

function CallCard({
  node,
  saw,
  hover,
  onOpen,
}: {
  node: ProvenanceNode;
  saw: ProvenanceNode[];
  hover: Hover;
  onOpen: (n: ProvenanceNode) => void;
}) {
  return (
    <div>
      <button
        type="button"
        data-prov-id={node.id}
        onClick={() => onOpen(node)}
        {...hover}
        className={cn(CARD, "border-white/[0.09] bg-white/[0.03] hover:border-white/[0.2] hover:bg-white/[0.05]")}
      >
        <span className="block font-mono text-[12px] text-zinc-100">{node.label}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 font-mono text-[11px]">
          <span className="text-violet-200 [overflow-wrap:anywhere]">{node.template ?? "no template"}</span>
          <span className="text-zinc-400">{fmtMs(node.ms)}</span>
        </span>
        <span className="sr-only">
          . Tool call {node.id}. Open the Cypher panel{node.template ? ` for ${node.template}` : ""}.
        </span>
      </button>
      {saw.length ? (
        <div className="mt-1 ml-3 flex items-start gap-1.5 border-l border-[var(--fl-line)] pt-1 pl-2">
          <span className="text-[10px] leading-4 text-zinc-400" title="SAW: graph nodes this call read">
            saw
          </span>
          <ul aria-label={`Graph nodes ${node.label} (${node.id}) saw`} className="flex min-w-0 flex-wrap gap-1">
            {saw.map((s) => (
              <li
                key={s.id}
                className="rounded border border-white/[0.1] bg-white/[0.02] px-1 font-mono text-[10px] leading-4 text-zinc-300"
              >
                {s.label}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function EvidenceCard({
  node,
  produced,
  hover,
  onOpen,
}: {
  node: ProvenanceNode;
  produced: boolean;
  hover: Hover;
  onOpen: (n: ProvenanceNode) => void;
}) {
  return (
    <button
      type="button"
      data-prov-id={node.id}
      onClick={() => onOpen(node)}
      {...hover}
      className={cn(CARD, "border-white/[0.09] bg-white/[0.03] hover:border-white/[0.2] hover:bg-white/[0.05]")}
    >
      <span className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="text-[12px] font-medium text-zinc-100">{node.label}</span>
        <span className="font-mono text-[10px] text-zinc-400">{node.id}</span>
      </span>
      {node.summary ? (
        <span className="mt-0.5 line-clamp-3 block text-[11.5px] leading-snug text-zinc-300" title={node.summary}>
          {node.summary}
        </span>
      ) : null}
      <span className="mt-1 flex flex-wrap items-center gap-1.5">
        <span className="rounded bg-violet-500/15 px-1 font-mono text-[10px] text-violet-200 [overflow-wrap:anywhere]">
          {node.template ?? "no template"}
        </span>
        {!produced ? <span className="text-[10px] text-amber-200">no producing call recorded</span> : null}
      </span>
      <span className="sr-only">. Open the Cypher panel.</span>
    </button>
  );
}

function VerdictCard({ node, hover }: { node: ProvenanceNode; hover: Hover }) {
  return (
    <div
      data-prov-id={node.id}
      onMouseEnter={hover.onMouseEnter}
      onMouseLeave={hover.onMouseLeave}
      className={cn(CARD, "border-red-400/45 bg-red-500/[0.06]")}
    >
      <p className="flex items-center gap-1.5 text-[11px] text-zinc-300">
        <Crosshair aria-hidden className="size-3.5 text-red-300" />
        cause
      </p>
      <p className="mt-0.5 font-mono text-sm font-semibold text-red-200 [overflow-wrap:anywhere]">
        {node.blames ?? node.label}
      </p>
      <StatusChip tone="pass" icon={CircleCheck} className="mt-1.5">
        confirmed
      </StatusChip>
    </div>
  );
}

function Legend() {
  return (
    <div className="space-y-1.5 text-[11px] text-zinc-400">
      <ul aria-label="Edge kinds" className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {REL_ORDER.map((r) => (
          <li key={r} className="inline-flex items-center gap-1.5">
            <svg aria-hidden width="18" height="6" className="shrink-0">
              <line x1="0" y1="3" x2="18" y2="3" stroke={REL_STROKE[r]} strokeWidth="1.5" />
            </svg>
            <span className="font-mono text-zinc-200">{r}</span>
            <span>
              {REL_TEXT[r].from} → {REL_TEXT[r].to}
            </span>
          </li>
        ))}
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="rounded border border-white/[0.1] px-1 font-mono text-[10px] leading-4 text-zinc-300">
            node
          </span>
          <span className="font-mono text-zinc-200">SAW</span>
          <span>
            {REL_TEXT.SAW.from} → {REL_TEXT.SAW.to} (chips)
          </span>
        </li>
      </ul>
      <p>Hover or focus a card to trace its lineage. Calls and evidence open their Cypher (Enter).</p>
    </div>
  );
}

function TextAlternative({ layout, roster }: { layout: ProvenanceLayout; roster: CrewMember[] }) {
  return (
    <details className="group rounded-lg border border-[var(--fl-line)] px-3 py-2">
      <summary className="cursor-pointer rounded text-xs text-zinc-300 outline-none hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400">
        Text alternative: the same graph as a table ({layout.rows.length} evidence item
        {layout.rows.length === 1 ? "" : "s"})
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-xs">
          <caption className="sr-only">
            For each evidence item: the tool calls that produced it, the agents that made them, what each call saw and
            the verdict it supports
          </caption>
          <thead className="text-zinc-400">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">Evidence</th>
              <th scope="col" className="py-1 pr-3 font-medium">Produced by (call)</th>
              <th scope="col" className="py-1 pr-3 font-medium">Made by (agent)</th>
              <th scope="col" className="py-1 pr-3 font-medium">Saw</th>
              <th scope="col" className="py-1 font-medium">Supports</th>
            </tr>
          </thead>
          <tbody>
            {layout.rows.map((r) => (
              <tr key={r.evidence.id} className="border-t border-[var(--fl-line)] align-top">
                <th scope="row" className="py-1.5 pr-3 font-normal">
                  <span className="text-zinc-100">{r.evidence.label}</span>{" "}
                  <span className="font-mono text-[10px] text-zinc-400">{r.evidence.id}</span>
                  {r.evidence.summary ? <span className="block text-zinc-300">{r.evidence.summary}</span> : null}
                </th>
                <td className="py-1.5 pr-3 font-mono text-zinc-200">
                  {r.calls.length
                    ? r.calls.map((c) => (
                        <span key={c.call.id} className="block">
                          {c.call.id} · {c.call.template ?? "no template"} · {fmtMs(c.call.ms)}
                        </span>
                      ))
                    : "no producing call recorded"}
                </td>
                <td className="py-1.5 pr-3 text-zinc-200">
                  {r.calls.length
                    ? r.calls.map((c) => (
                        <span key={c.call.id} className="block">
                          {c.agents.map((a) => agentName(a, roster)).join(", ") || "–"}
                        </span>
                      ))
                    : "–"}
                </td>
                <td className="py-1.5 pr-3 font-mono text-zinc-300">
                  {r.calls.length
                    ? r.calls.map((c) => (
                        <span key={c.call.id} className="block">
                          {c.saw.map((s) => s.label).join(", ") || "–"}
                        </span>
                      ))
                    : "–"}
                </td>
                <td className="py-1.5 font-mono whitespace-nowrap text-red-200">
                  {r.verdicts.map((v) => v.blames ?? v.label).join(", ") || "–"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
