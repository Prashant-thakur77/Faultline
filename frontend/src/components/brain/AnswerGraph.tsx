"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ChevronDown, CircleAlert, Code2, LoaderCircle, Share2, TriangleAlert, Unlink } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import {
  GEOMETRY,
  kindStyle,
  layoutBrainGraph,
  subgraphIds,
  touching,
  type BrainGraphLayout,
  type PlacedNode,
  type Shape,
} from "@/lib/brainGraph";
import type { BrainAnswer, BrainSubgraph } from "@/lib/types";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useTenant } from "@/lib/tenant";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { cn } from "@/lib/utils";

/** Template the API reads the subgraph with; the response names it, this is only the label before it arrives. */
const SUB_TEMPLATE = "Q-BRAIN-SUB";
const EASE = [0.22, 1, 0.36, 1] as const;
const BASE_STROKE = "rgb(255 255 255 / 0.2)";
const LIT_STROKE = "rgb(125 211 252 / 0.9)"; // sky-300
/** Above this many lit lines, a focused node labels none of them (the hovered line still names itself). */
const MAX_LIT_LABELS = 8;

type Loaded = { key: string; data: BrainSubgraph; error?: undefined } | { key: string; data?: undefined; error: { text: string; status: number | null } };

/**
 * "Answer as a graph" (Q-BRAIN-SUB): under a brain answer with at least two citations, how the cited ids connect in
 * the tenant graph (paths of at most 2 hops). Cited nodes are filled, connecting nodes outlined and smaller. The
 * layout is deterministic (layoutBrainGraph); every node and the header open the query in the Cypher panel. Fails
 * loudly: an unavailable graph is said, never drawn from anything but the response.
 */
export function AnswerGraph({ answer }: { answer: BrainAnswer }) {
  const { ids, total } = useMemo(() => subgraphIds(answer.citations), [answer.citations]);
  if (ids.length < 2) return null;
  return <AnswerGraphSection answer={answer} ids={ids} total={total} />;
}

function AnswerGraphSection({ answer, ids, total }: { answer: BrainAnswer; ids: string[]; total: number }) {
  const selected = useTenant();
  const tenant = answer.tenant ?? selected;
  const panel = useCypherPanel();
  const headId = useId();
  const bodyId = useId();
  const [open, setOpen] = useState(true);
  const [nonce, setNonce] = useState(0);
  const reqKey = `${tenant}:${answer.run_id}:${ids.join(",")}:${nonce}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    api
      .brainSubgraph(ids, tenant, ctrl.signal)
      .then((data) => setLoaded({ key: reqKey, data }))
      .catch((e) => {
        if ((e instanceof DOMException && e.name === "AbortError") || ctrl.signal.aborted) return;
        setLoaded({
          key: reqKey,
          error: { text: e instanceof ApiError ? e.detail : errorText(e), status: e instanceof ApiError ? e.status : null },
        });
      });
    return () => ctrl.abort();
  }, [open, ids, tenant, reqKey]);

  const cur = loaded?.key === reqKey ? loaded : null;
  const data = cur?.data ?? null;
  const layout = useMemo(() => (data ? layoutBrainGraph(data, ids) : null), [data, ids]);

  const openQuery = (node?: PlacedNode) =>
    panel.open({
      template: data?.template ?? SUB_TEMPLATE,
      title: node ? `${node.id} · answer as a graph` : `answer ${answer.run_id} as a graph`,
      origin: node
        ? `brain answer ${answer.run_id}: ${node.cited ? "cited" : "connecting"} node ${node.id} (${node.label})`
        : `brain answer ${answer.run_id} (Answer as a graph)`,
      detail: node
        ? `${node.name}. This query drew the whole answer graph; the params are the ones the API used.`
        : data
          ? "GET /api/brain/subgraph ran this query; the params are the ones the API used."
          : "The params below are the answer's cited ids, as the graph view asks for them.",
      recordedParams: data?.params ?? { ids },
      ctx: { ids, node: node?.id },
      tenant,
    });

  const status =
    !open
      ? ""
      : cur === null
        ? "Loading the answer graph"
        : cur.error
          ? `Answer graph unavailable: ${cur.error.text}`
          : layout
            ? `Answer graph loaded: ${layout.nodes.length} nodes, ${layout.edges.length} edges${data?.truncated ? ", truncated" : ""}`
            : "";

  return (
    <section aria-labelledby={headId} className="space-y-2 border-t border-[var(--fl-line)] pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headId} className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          <Share2 aria-hidden className="size-3.5" /> Answer as a graph
        </h3>
        <button
          type="button"
          onClick={() => openQuery()}
          className="inline-flex min-h-6 items-center gap-1 rounded px-1.5 font-mono text-[11px] text-zinc-400 hover:text-zinc-100 hover:bg-white/[0.05] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          <Code2 aria-hidden className="size-3" />
          {data?.template ?? SUB_TEMPLATE}
          <span className="sr-only"> : open the query that draws this graph in the Cypher panel</span>
        </button>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((o) => !o)}
          className="ml-auto inline-flex min-h-6 items-center gap-1 rounded px-1.5 text-[11px] text-zinc-300 outline-none hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          <ChevronDown aria-hidden className={cn("size-3.5 transition-transform motion-reduce:transition-none", open ? "" : "-rotate-90")} />
          {open ? "Hide" : "Show"}
          <span className="sr-only"> the answer as a graph</span>
        </button>
      </div>
      <p role="status" aria-live="polite" className="sr-only">
        {status}
      </p>
      <div id={bodyId} hidden={!open} className="space-y-2">
        {open ? (
          <>
            <p className="text-xs text-zinc-400">
              How the {ids.length} cited id{ids.length === 1 ? "" : "s"} connect in the tenant graph, through paths of at
              most 2 hops.
              {total > ids.length ? ` The first ${ids.length} of ${total} cited ids are drawn (the query takes at most ${ids.length}).` : ""}
            </p>
            {cur === null ? (
              <p className="flex items-center gap-2 text-xs text-zinc-300">
                <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" />
                Reading how the cited ids connect from FalkorDB…
              </p>
            ) : cur.error ? (
              <GraphError error={cur.error} onRetry={() => setNonce((n) => n + 1)} />
            ) : layout && data ? (
              <GraphBody layout={layout} data={data} onOpenNode={openQuery} />
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}

function GraphError({ error, onRetry }: { error: { text: string; status: number | null }; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-start gap-2 rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100">
      <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
      <p className="min-w-0 flex-1">
        <strong className="font-semibold">
          {error.status === 503 ? "Graph unavailable:" : error.status === null ? "API unreachable:" : "Could not draw the answer graph:"}
        </strong>{" "}
        {error.text}
        {error.status ? ` (HTTP ${error.status})` : ""}. Nothing is drawn in its place.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded border border-red-400/40 px-1.5 py-0.5 text-[11px] text-red-100 outline-none hover:bg-red-500/20 focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        Retry
      </button>
    </div>
  );
}

function GraphBody({
  layout,
  data,
  onOpenNode,
}: {
  layout: BrainGraphLayout;
  data: BrainSubgraph;
  onOpenNode: (n: PlacedNode) => void;
}) {
  if (!layout.nodes.length) {
    return (
      <p className="flex items-start gap-1.5 rounded-md border border-dashed border-[var(--fl-line)] p-3 text-xs text-zinc-300">
        <Unlink aria-hidden className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
        {data.template} found no path of at most 2 hops between any two cited ids, so there is nothing to draw.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {data.truncated ? (
        <p className="flex items-start gap-1.5 text-xs text-amber-200">
          <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-amber-300" />
          Truncated: the query hit its row limit, so some connecting paths are not drawn.
        </p>
      ) : null}
      <Graph layout={layout} onOpenNode={onOpenNode} />
      {layout.unconnected.length ? (
        <p className="flex flex-wrap items-center gap-1 text-xs text-zinc-300">
          <Unlink aria-hidden className="size-3.5 text-zinc-400" />
          Not connected to another cited id within 2 hops:
          {layout.unconnected.map((id) => (
            <span key={id} className="rounded border border-white/10 px-1 font-mono text-[11px] text-zinc-200">
              {id}
            </span>
          ))}
        </p>
      ) : null}
      <Legend layout={layout} />
      <EdgeList layout={layout} />
    </div>
  );
}

function Graph({ layout, onOpenNode }: { layout: BrainGraphLayout; onOpenNode: (n: PlacedNode) => void }) {
  const reduced = useReducedMotion();
  const markerBase = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [active, setActive] = useState<string | null>(null);
  const [hotPair, setHotPair] = useState<string | null>(null);
  const lit = useMemo(() => (active ? touching(active, layout.pairs) : null), [active, layout.pairs]);
  const byId = useMemo(() => new Map(layout.nodes.map((n) => [n.id, n])), [layout.nodes]);
  const labelLit = !!lit && lit.pairs.size <= MAX_LIT_LABELS;

  return (
    <div
      role="group"
      aria-label={`Answer graph: ${layout.nodes.length} nodes in columns ${layout.columns.map((c) => c.title).join(", ")}`}
      // w-0 + min-w-full: the fixed-size drawing scrolls inside the card instead of widening the page on a phone
      className="max-h-[560px] w-0 min-w-full overflow-auto overscroll-contain rounded-lg border border-[var(--fl-line)] bg-black/20"
    >
      <div className="relative" style={{ width: layout.width, height: layout.height }}>
        {layout.columns.map((c) => (
          <p
            key={c.key}
            aria-hidden
            className="absolute top-2 text-[10.5px] font-medium tracking-wide text-zinc-400 uppercase"
            style={{ left: c.x, width: GEOMETRY.cited.w }}
          >
            {c.title} <span className="font-mono normal-case">{c.count}</span>
          </p>
        ))}
        <svg aria-hidden className="absolute inset-0 overflow-visible" width={layout.width} height={layout.height}>
          <defs>
            {(["base", "lit"] as const).map((k) => (
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
                <path d="M0,0 L6,3 L0,6 z" fill={k === "base" ? BASE_STROKE : LIT_STROKE} />
              </marker>
            ))}
          </defs>
          {layout.pairs.map((p) => {
            const on = hotPair === p.key || !!lit?.pairs.has(p.key);
            const faded = (lit && !on) || (hotPair !== null && hotPair !== p.key && !lit);
            const marker = `url(#${markerBase}-${on ? "lit" : "base"})`;
            const a = byId.get(p.a)!;
            const b = byId.get(p.b)!;
            const labelled = hotPair === p.key || (labelLit && on);
            return (
              <g key={p.key} data-pair={p.key} data-lit={on ? "true" : undefined}>
                <motion.path
                  d={p.d}
                  fill="none"
                  stroke={on ? LIT_STROKE : BASE_STROKE}
                  strokeWidth={on ? 1.5 : 1}
                  markerEnd={p.forward ? marker : undefined}
                  markerStart={p.backward ? marker : undefined}
                  initial={reduced ? { pathLength: 1, opacity: 1 } : { pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: faded ? 0.25 : 1 }}
                  transition={reduced ? { duration: 0 } : { duration: 0.45, delay: 0.12 + Math.max(a.col, b.col) * 0.08, ease: EASE }}
                />
                {/* a wide invisible stroke so a hairline is hoverable; its <title> names every stored edge */}
                <path
                  d={p.d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={10}
                  style={{ pointerEvents: "stroke" }}
                  onMouseEnter={() => setHotPair(p.key)}
                  onMouseLeave={() => setHotPair((h) => (h === p.key ? null : h))}
                >
                  <title>{p.edges.map((e) => `${e.source} —${e.rel}→ ${e.target}`).join("\n")}</title>
                </path>
                {labelled ? (
                  <text
                    x={p.mx}
                    y={p.my - 4}
                    textAnchor="middle"
                    className="fill-zinc-100 font-mono text-[9.5px]"
                    style={{ paintOrder: "stroke", stroke: "var(--fl-surface)", strokeWidth: 4 }}
                  >
                    {p.rels.join(" · ")}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
        <ul aria-label="Nodes, column by column" className="absolute inset-0">
          {layout.nodes.map((n) => (
            <motion.li
              key={n.id}
              className="absolute"
              style={{ left: n.x, top: n.y, width: n.w, height: n.h }}
              initial={reduced ? { opacity: 1, y: 0 } : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={reduced ? { duration: 0 } : { duration: 0.3, delay: n.col * 0.08 + Math.min(n.row, 8) * 0.025, ease: EASE }}
            >
              <NodeCard
                node={n}
                dim={!!lit && !lit.nodes.has(n.id)}
                degree={layout.edges.filter((e) => e.source === n.id || e.target === n.id).length}
                onOpen={() => onOpenNode(n)}
                onActive={(on) => setActive((cur) => (on ? n.id : cur === n.id ? null : cur))}
              />
            </motion.li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function NodeCard({
  node,
  dim,
  degree,
  onOpen,
  onActive,
}: {
  node: PlacedNode;
  dim: boolean;
  degree: number;
  onOpen: () => void;
  onActive: (on: boolean) => void;
}) {
  const style = kindStyle(node.label);
  return (
    <button
      type="button"
      data-node-id={node.id}
      data-cited={node.cited ? "true" : "false"}
      onClick={onOpen}
      onMouseEnter={() => onActive(true)}
      onMouseLeave={() => onActive(false)}
      onFocus={() => onActive(true)}
      onBlur={() => onActive(false)}
      title={`${node.name} (${node.label} ${node.id})`}
      className={cn(
        "flex size-full items-center gap-1.5 rounded-md border px-2 text-left outline-none transition-[opacity,border-color,background-color] duration-150 focus-visible:ring-2 focus-visible:ring-sky-400 motion-reduce:transition-none",
        node.cited
          ? "border-white/[0.16] bg-[#141518] hover:border-white/[0.3]"
          : "border-dashed border-white/[0.14] bg-[#101113] hover:border-white/[0.28]",
        dim && "opacity-40",
      )}
    >
      <NodeShape shape={style.shape} color={style.color} filled={node.cited} size={node.cited ? 14 : 11} />
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            node.cited
              ? "line-clamp-2 text-[12px] leading-[1.2] font-medium text-zinc-50"
              : "block truncate text-[11.5px] text-zinc-300",
          )}
        >
          {node.name}
        </span>
        <span className={cn("mt-0.5 block truncate font-mono text-zinc-400", node.cited ? "text-[10.5px]" : "text-[10px]")}>
          {node.label} · {node.id}
        </span>
      </span>
      <span className="sr-only">
        . {node.cited ? "Cited in the answer" : "Connects cited ids"}; {degree} edge{degree === 1 ? "" : "s"} here. Open the
        Cypher panel.
      </span>
    </button>
  );
}

/** The label's shape: filled for a cited node, outlined for a connecting one (never colour alone). */
export function NodeShape({ shape, color, filled, size }: { shape: Shape; color: string; filled: boolean; size: number }) {
  const common = {
    fill: filled ? color : "none",
    fillOpacity: filled ? 0.85 : undefined,
    stroke: color,
    strokeWidth: filled ? 1 : 1.6,
    strokeLinejoin: "round" as const,
  };
  let el: React.ReactNode;
  switch (shape) {
    case "circle":
      el = <circle cx="8" cy="8" r="6.2" {...common} />;
      break;
    case "diamond":
      el = <polygon points="8,1.2 14.8,8 8,14.8 1.2,8" {...common} />;
      break;
    case "hexagon":
      el = <polygon points="4.6,1.8 11.4,1.8 14.8,8 11.4,14.2 4.6,14.2 1.2,8" {...common} />;
      break;
    case "square":
      el = <rect x="2" y="2" width="12" height="12" rx="2.5" {...common} />;
      break;
    case "cylinder":
      el = <path d="M2 4.2 C2 1.8 14 1.8 14 4.2 V11.8 C14 14.2 2 14.2 2 11.8 Z M2 4.2 C2 6.4 14 6.4 14 4.2" {...common} />;
      break;
    case "page":
      el = <path d="M3 1.5 H10.2 L13 4.3 V14.5 H3 Z" {...common} />;
      break;
    case "triangle":
      el = <polygon points="8,1.5 14.8,14.2 1.2,14.2" {...common} />;
      break;
    default:
      el = <circle cx="8" cy="8" r="5.8" {...common} strokeDasharray={filled ? undefined : "2 2"} />;
  }
  return (
    <svg aria-hidden width={size} height={size} viewBox="0 0 16 16" className="shrink-0 overflow-visible" data-shape={shape}>
      {el}
    </svg>
  );
}

function Legend({ layout }: { layout: BrainGraphLayout }) {
  return (
    <div className="space-y-1.5 text-[11px] text-zinc-400">
      <ul aria-label="Node kinds" className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {layout.labels.map((l) => {
          const s = kindStyle(l);
          return (
            <li key={l} className="inline-flex items-center gap-1">
              <NodeShape shape={s.shape} color={s.color} filled size={11} />
              <span className="text-zinc-200">{l}</span>
            </li>
          );
        })}
        <li className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block size-2.5 rounded-full bg-zinc-300" />
          filled: cited in the answer
        </li>
        <li className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block size-2.5 rounded-full border border-dashed border-zinc-300" />
          outlined, smaller: connects them
        </li>
      </ul>
      <ul aria-label="Relationship types" className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {layout.rels.map((r) => (
          <li key={r.rel} className="inline-flex items-baseline gap-1">
            <span className="font-mono text-zinc-200">{r.rel}</span>
            <span>
              {r.ends.slice(0, 2).join(", ")}
              {r.ends.length > 2 ? ", …" : ""} ×{r.count}
            </span>
          </li>
        ))}
      </ul>
      <p>Hover or focus a node to light its edges and name them; hover a line for its type. Enter opens the query.</p>
    </div>
  );
}

function EdgeList({ layout }: { layout: BrainGraphLayout }) {
  const name = new Map(layout.nodes.map((n) => [n.id, n.name]));
  return (
    <details className="rounded-md border border-[var(--fl-line)] px-2.5 py-1.5">
      <summary className="cursor-pointer rounded text-xs text-zinc-300 outline-none hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400">
        Text alternative: the {layout.edges.length} edge{layout.edges.length === 1 ? "" : "s"} as a list
      </summary>
      <ul aria-label="Edges of the answer graph" className="mt-1.5 space-y-0.5 text-xs">
        {layout.edges.map((e) => (
          <li key={`${e.source}|${e.rel}|${e.target}`} className="break-words text-zinc-200">
            {name.get(e.source)} <span className="font-mono text-[10.5px] text-zinc-400">({e.source})</span>{" "}
            <span className="font-mono text-sky-200">—{e.rel}→</span> {name.get(e.target)}{" "}
            <span className="font-mono text-[10.5px] text-zinc-400">({e.target})</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
