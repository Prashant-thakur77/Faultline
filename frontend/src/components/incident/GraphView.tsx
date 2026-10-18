"use client";

import { createContext, memo, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  getViewportForBounds,
  useReactFlow,
  useStore,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type ReactFlowState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Ban,
  Database,
  Gauge,
  GitCommitHorizontal,
  LayoutDashboard,
  Maximize2,
  RotateCcw,
  Route,
  Server,
  Sheet,
  Siren,
  Waves,
  type LucideIcon,
} from "lucide-react";
import type { GraphModel, ModelNode, Role } from "@/lib/graphModel";
import { layeredLayout } from "@/lib/layout";
import {
  LABEL_PX,
  MIN_ZOOM,
  boundsWithCaptions,
  captionSize,
  chipSide,
  chooseFit,
  cutLabels,
  fitCandidates,
  keyNodeIds,
  labelLod,
  placeCaptions,
  type Bounds,
  type CaptionSpot,
  type ChipSide,
  type FitRect,
} from "@/lib/graphLabels";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STEP_MS = 250;
const RIPPLE_MS = 320;

const LABEL_ICON: Record<string, LucideIcon> = {
  Service: Server,
  Datastore: Database,
  Table: Sheet,
  KPI: Gauge,
  Dashboard: LayoutDashboard,
  Deploy: GitCommitHorizontal,
};

export const ROLE_TEXT: Record<Role, string> = {
  cause: "cause",
  path: "on proof path",
  symptom: "symptom",
  rejected: "rejected suspect",
  "rejected-target": "rejected suspect's target",
  "rejected-path": "on a rejected suspect's chain",
};

/** Colours per edge kind; the legend repeats them with line style + text. */
export const EDGE_STYLE: Record<string, { stroke: string; dash?: string; width: number; text: string }> = {
  service: { stroke: "#71717a", width: 1.4, text: "service call (solid grey)" },
  data: { stroke: "#38bdf8", dash: "6 4", width: 1.4, text: "data lineage (dashed blue)" },
  cross: { stroke: "#c084fc", dash: "2 4", width: 2.2, text: "service → data crossing (dotted violet)" },
  change: { stroke: "#fb923c", dash: "8 3", width: 1.8, text: "change applied to (long-dash orange)" },
  hop: { stroke: "#a1a1aa", dash: "1 5", width: 1.4, text: "chain hop not in the failure-flow view" },
};

export const CUT_STYLE = { stroke: "#ef4444", dash: "9 5", width: 3.4 };

// Node size encodes betweenness (sqrt-scaled between these bounds); the layout slot is the max size.
export const NODE_MIN = { w: 156, h: 40 };
export const NODE_MAX = { w: 204, h: 58 };

export type GraphMode = "path" | "ripple";

/** Ripple mode input: the cause nodes (red) and the blast radius with its BFS hop count (yellow). */
export interface RippleData {
  cause: Set<string>;
  /** node id → hops from the nearest symptom (0 = the symptom itself); null when not known. */
  blast: Map<string, number | null>;
  /** Badge texts (default CAUSE / BLAST); preflight uses CHANGED / IMPACTED. */
  causeLabel?: string;
  blastLabel?: string;
  /**
   * Nodes that keep a readable caption when the view is zoomed out (preflight: the highest-impact nodes
   * the change reaches). The cause and the symptoms (hop 0) always keep theirs.
   */
  emphasis?: Set<string>;
}

export interface CutEdge {
  u: string;
  v: string;
  cost: number;
  domain: string;
}

type RippleRole = "cause" | "blast" | "dim" | null;

type FlNodeData = {
  node: ModelNode;
  dimmed: boolean;
  lit: boolean;
  mode: GraphMode;
  ripple: RippleRole;
  hops: number | null;
  size: { w: number; h: number };
  causeLabel: string;
  blastLabel: string;
  /** Keeps its caption at any zoom (proof path, cause, symptoms, rejected suspects, cut ends, emphasis). */
  keyNode: boolean;
  /** Preferred side of the zoomed-out caption (alternates by layout column; CaptionSpots may move it). */
  side: ChipSide;
  /** Caption placement order (lower first: it keeps its preferred side). */
  priority: number;
};

/**
 * Caption spots placed for the current zoom (CaptionPlacer → FlNode). null: an optional caption that gave way
 * (shown on hover / focus only); absent: not placed, so the node's preferred side.
 */
const CaptionSpots = createContext<ReadonlyMap<string, CaptionSpot | null>>(new Map());

function sizeFor(b: number | null, maxB: number): { w: number; h: number } {
  if (b === null || maxB <= 0) return NODE_MIN;
  const t = Math.sqrt(Math.max(0, b) / maxB);
  return { w: Math.round(NODE_MIN.w + (NODE_MAX.w - NODE_MIN.w) * t), h: Math.round(NODE_MIN.h + (NODE_MAX.h - NODE_MIN.h) * t) };
}

/**
 * Current zoom in 1 % steps, so nodes re-render on visible changes only. Rounded down: text counter-scaled by
 * 1 / zoom then prints at or just above its target size, never below it.
 */
const zoomOf = (s: ReactFlowState) => Math.floor(s.transform[2] * 100) / 100;

type BadgeSpec = { className: string; icon: LucideIcon; text: string };

/** What the node's status is, as icon + text (never colour alone); shared by both renderings. */
function statusOf(data: FlNodeData) {
  const n = data.node;
  const ripple = data.mode === "ripple";
  const cause = ripple ? data.ripple === "cause" : n.roles.includes("cause");
  const blast = ripple && data.ripple === "blast";
  const rejected = !ripple && n.roles.includes("rejected");
  const rejectedTarget = !ripple && n.roles.includes("rejected-target");
  const symptom = n.roles.includes("symptom");
  const onPath = !ripple && n.roles.includes("path");
  const badge: BadgeSpec | null = cause
    ? { className: "border-red-400 bg-red-700 text-white", icon: Siren, text: data.causeLabel }
    : blast
      ? symptom
        ? { className: "border-amber-300 bg-amber-400 text-zinc-950", icon: Gauge, text: "SYMPTOM" }
        : { className: "border-amber-300 bg-amber-300 text-zinc-950", icon: Waves, text: data.blastLabel }
      : rejected
        ? { className: "border-zinc-400 bg-zinc-700 text-zinc-50", icon: Ban, text: "REJECTED" }
        : symptom && !ripple
          ? { className: "border-amber-300 bg-amber-400 text-zinc-950", icon: Gauge, text: "SYMPTOM" }
          : rejectedTarget
            ? { className: "border-zinc-400 bg-zinc-800 text-zinc-100", icon: Ban, text: "REJ. TARGET" }
            : null;
  const box = cn(
    cause
      ? "border-red-400 bg-red-950 ring-2 ring-red-500/70"
      : blast
        ? "border-amber-300 bg-amber-900/70 ring-2 ring-amber-400/60"
        : onPath && data.lit
          ? "border-amber-300 bg-amber-950/60 ring-2 ring-amber-400/60"
          : rejected
            ? "border-zinc-400 bg-zinc-800"
            : symptom && !ripple
              ? "border-amber-300"
              : "border-zinc-600",
    data.dimmed && (ripple ? "opacity-30" : "opacity-60"),
  );
  const iconCls = cause ? "text-red-300" : blast ? "text-amber-200" : n.band === "data" ? "text-sky-300" : n.band === "change" ? "text-orange-300" : "text-zinc-300";
  return { ripple, cause, blast, rejected, symptom, badge, box, iconCls, emphasised: n.roles.length > 0 || blast || cause };
}

const FlNode = memo(function FlNode({ data }: NodeProps<Node<FlNodeData>>) {
  const zoom = useStore(zoomOf);
  const spot = useContext(CaptionSpots).get(data.node.id);
  const lod = labelLod(zoom, data.size);
  const n = data.node;
  const Icon = LABEL_ICON[n.label] ?? Server;
  const st = statusOf(data);
  const shell = cn(
    "relative flex items-center gap-2 rounded-lg border bg-zinc-900 px-2 py-1 text-left transition-[opacity,box-shadow,background-color] duration-200",
    n.band === "data" && "rounded-sm border-dashed",
    n.band === "change" && "rounded-full",
    st.box,
  );
  const handles = (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} className="!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Right} isConnectable={false} className="!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
    </>
  );

  if (lod.mode === "compact") {
    // Zoomed out: text inside the box would print below LABEL_PX, so names are counter-scaled instead.
    const standing = data.keyNode && spot !== null;
    const inBox = lod.nameInBox && !standing;
    return (
      <div style={{ width: data.size.w, height: data.size.h }} className={cn(shell, !inBox && "justify-center")} data-dimmed={data.dimmed || undefined}>
        {handles}
        {/* the name, when it fits at LABEL_PX on screen (the icon gives it the room), else the type icon alone */}
        {inBox ? (
          <p
            data-node-label
            className={cn("min-w-0 flex-1 truncate font-mono leading-tight text-zinc-50", st.rejected && "line-through decoration-zinc-400")}
            style={{ fontSize: LABEL_PX * lod.inv }}
          >
            {n.id}
          </p>
        ) : (
          <Icon aria-hidden className={cn("size-4 shrink-0", st.iconCls)} />
        )}
        <Caption data={data} badge={st.badge} inv={lod.inv} always={standing} spot={spot ?? { side: data.side, dx: 0 }} />
      </div>
    );
  }

  return (
    <div style={{ width: data.size.w, height: data.size.h }} className={shell}>
      {handles}
      <Icon aria-hidden className={cn("size-4 shrink-0", st.iconCls)} />
      <div className="min-w-0 flex-1">
        <p
          data-node-label
          className={cn(
            "truncate font-mono leading-4 text-zinc-50",
            st.emphasised ? "text-[12.5px] font-semibold" : "text-[11px]",
            st.rejected && "line-through decoration-zinc-400",
          )}
          title={n.id}
        >
          {n.id}
        </p>
        <p className="flex items-center gap-1 text-[10px] leading-3.5 text-zinc-300">
          <span>{n.label}</span>
          {n.tier !== null ? <span>· t{n.tier}</span> : null}
          {!st.ripple && n.step !== null ? <span className="font-semibold text-amber-200">· step {n.step + 1}</span> : null}
          {st.blast && data.hops !== null ? <span className="font-semibold text-amber-100">· {data.hops} hop{data.hops === 1 ? "" : "s"}</span> : null}
          {!st.ripple && n.outCap ? <CapPill node={n} /> : null}
        </p>
      </div>
      {st.badge ? <Badge {...st.badge} /> : null}
    </div>
  );
});

function CapPill({ node, className }: { node: ModelNode; className?: string }) {
  if (!node.outCap) return null;
  return (
    <span
      className={cn(
        "ml-auto inline-flex items-center gap-0.5 rounded px-1 font-mono text-[10.5px] leading-3.5 font-bold whitespace-nowrap",
        node.outCap.rejected ? "bg-zinc-100 text-zinc-950" : "bg-red-200 text-red-950",
        className,
      )}
      title={`capacity of the hop to ${node.outCap.to}`}
    >
      {node.outCap.rejected ? <Ban aria-hidden className="size-2.5" /> : null}
      cap {node.outCap.cap}
    </span>
  );
}

/**
 * The zoomed-out caption: status (icon + text) over the full name, counter-scaled by `inv` so it prints at a
 * constant on-screen size whatever the zoom. Key nodes always show it; other nodes on hover, keyboard focus or
 * selection (globals.css, `.fl-graph .fl-caption-hover`). aria-hidden: the node's aria-label already says all of it.
 */
function Caption({
  data,
  badge,
  inv,
  always,
  spot,
}: {
  data: FlNodeData;
  badge: BadgeSpec | null;
  inv: number;
  always: boolean;
  spot: CaptionSpot;
}) {
  const n = data.node;
  const above = spot.side === "above";
  const ripple = data.mode === "ripple";
  const parts = captionParts(data, badge);
  return (
    <div
      aria-hidden
      data-node-caption={always ? "key" : "hover"}
      className={cn("pointer-events-none absolute left-1/2 z-10", !always && "fl-caption-hover")}
      style={{
        [above ? "bottom" : "top"]: "100%",
        // dx is in screen px; the translation happens in flow units, before the counter-scale
        transform: `translateX(calc(-50% + ${spot.dx * inv}px)) scale(${inv})`,
        transformOrigin: above ? "50% 100%" : "50% 0",
      }}
    >
      <div className={above ? "pb-1" : "pt-1"}>
        <div className="flex flex-col items-center gap-0.5 rounded-md border border-white/15 bg-zinc-950/95 px-1.5 py-1 shadow-lg shadow-black/60">
          <span className="flex items-center gap-1 text-[10.5px] leading-3.5 whitespace-nowrap text-zinc-300">
            {parts.badge ? (
              <span className={cn("flex items-center gap-0.5 rounded border px-1 font-bold tracking-wide", parts.badge.className)}>
                <parts.badge.icon aria-hidden className="size-3" />
                {parts.badge.text}
              </span>
            ) : null}
            {parts.kind ? <span>{parts.kind}</span> : null}
            {parts.step !== null ? <span className="rounded border border-amber-300 bg-amber-950/60 px-1 font-semibold text-amber-100">step {parts.step}</span> : null}
            {parts.hops !== null ? (
              <span className="font-semibold text-amber-100">
                {parts.hops} hop{parts.hops === 1 ? "" : "s"}
              </span>
            ) : null}
            {parts.tier !== null ? <span>t{parts.tier}</span> : null}
            {parts.cap ? <CapPill node={n} className="ml-0" /> : null}
          </span>
          <span
            data-node-label
            className={cn("font-mono text-[12px] leading-4 font-semibold whitespace-nowrap text-zinc-50", data.node.roles.includes("rejected") && !ripple && "line-through decoration-zinc-400")}
          >
            {n.id}
          </span>
        </div>
      </div>
    </div>
  );
}

/** What a caption's status line carries; kept short, since a narrow caption collides less. */
function captionParts(data: FlNodeData, badge: BadgeSpec | null) {
  const n = data.node;
  const ripple = data.mode === "ripple";
  const cause = ripple ? data.ripple === "cause" : n.roles.includes("cause");
  // the cause is step 1 by definition; its badge says so
  const step = !ripple && n.step !== null && !cause ? n.step + 1 : null;
  return {
    badge,
    // the node type only when nothing else on the line says what the node is
    kind: !badge && step === null ? `${n.label}${n.tier !== null ? ` · t${n.tier}` : ""}` : null,
    step,
    hops: ripple && data.ripple === "blast" && data.hops !== null && data.hops > 0 ? data.hops : null,
    tier: badge && ripple && n.tier !== null ? n.tier : null,
    cap: !ripple && n.outCap !== null,
  };
}

/** On-screen size of `Caption` for the fit and placement (lib/graphLabels.ts captionSize). */
function captionEstimate(data: FlNodeData): { w: number; h: number } {
  const n = data.node;
  const p = captionParts(data, statusOf(data).badge);
  const text = [
    p.badge?.text,
    p.kind,
    p.step !== null ? `step ${p.step}` : null,
    p.hops !== null ? `${p.hops} hops` : null,
    p.tier !== null ? `t${p.tier}` : null,
    p.cap && n.outCap ? `cap ${n.outCap.cap}` : null,
  ].filter(Boolean);
  return captionSize(n.id, text.join(" "), (p.badge ? 1 : 0) + (p.step !== null ? 1 : 0) + (p.cap ? 1 : 0));
}

function Badge({ className, icon: Icon, text }: BadgeSpec) {
  return (
    <span className={cn("absolute -top-2.5 right-1.5 flex items-center gap-0.5 rounded border px-1 text-[9px] leading-3.5 font-bold tracking-wide", className)}>
      <Icon aria-hidden className="size-2.5" />
      {text}
    </span>
  );
}

type FlEdgeData = { cut: number | null };

/**
 * Bezier edge whose min-cut label is HTML (EdgeLabelRenderer), counter-scaled like the node captions so
 * "✂ cut n" stays legible when the view is zoomed out. Without a cut it is the plain default edge.
 */
function FlEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data }: EdgeProps<Edge<FlEdgeData>>) {
  const zoom = useStore(zoomOf);
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const inv = zoom > 0 && zoom < 1 ? 1 / zoom : 1;
  return (
    <>
      {/* no interaction path: edges are display only, and a lit or cut edge (drawn above the nodes) must not
          swallow the hover, click or tap meant for a node underneath it */}
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} interactionWidth={0} />
      {data && data.cut !== null ? (
        <EdgeLabelRenderer>
          <div
            aria-hidden
            className="pointer-events-none absolute flex items-center gap-0.5 rounded border border-red-500 bg-red-950 px-1 font-mono text-[11px] leading-4 font-bold whitespace-nowrap text-red-200"
            style={{ transform: `translate(${lx}px, ${ly}px) scale(${inv}) translate(-50%, -50%)`, transformOrigin: "0 0", zIndex: 40 }}
          >
            ✂ cut {data.cut}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const edgeTypes = { fl: FlEdge };

const nodeTypes = { fl: FlNode };

function describe(n: ModelNode, chainLen: number, mode: GraphMode, ripple: RippleRole, hops: number | null): string {
  const roles = mode === "ripple" ? [] : n.roles.map((r) => ROLE_TEXT[r]);
  const rip =
    mode === "ripple"
      ? ripple === "cause"
        ? "cause"
        : ripple === "blast"
          ? hops === null
            ? "in the blast radius"
            : `in the blast radius, ${hops} hop${hops === 1 ? "" : "s"} from a symptom`
          : "outside the blast radius"
      : "";
  const step = mode === "path" && n.step !== null ? `step ${n.step + 1} of ${chainLen}` : "";
  const cap = mode === "path" && n.outCap ? `hop to ${n.outCap.to} has capacity ${n.outCap.cap}` : "";
  const b = n.betweenness !== null ? `betweenness ${n.betweenness}` : "";
  return [n.id, n.label, step, rip, ...roles, cap, b, "Press Enter to open the Cypher panel."].filter(Boolean).join(", ");
}

/**
 * Caption placement order: the cause first, then symptoms, the proof path and preflight's highest-impact
 * nodes, then rejected suspects, then min-cut ends. Earlier captions keep their preferred side.
 */
function captionPriority(n: ModelNode, rr: RippleRole, hops: number | null, emphasis: Set<string> | null): number {
  if (rr !== null) return rr === "cause" ? 0 : hops === 0 ? 1 : emphasis?.has(n.id) ? 2 : 4;
  if (n.roles.includes("cause")) return 0;
  if (n.roles.includes("symptom")) return 1;
  if (n.roles.includes("path")) return 2;
  if (n.roles.includes("rejected") || n.roles.includes("rejected-target")) return 3;
  return 4;
}

export function GraphView({
  model,
  onOpenNode,
  layoutKey,
  mode = "path",
  ripple = null,
  cut = [],
}: {
  model: GraphModel;
  onOpenNode: (id: string) => void;
  /** Changes when the underlying graph changes (resets the path animation). */
  layoutKey: string;
  mode?: GraphMode;
  ripple?: RippleData | null;
  /** Min-cut edges from the containment plan (dashed red "cut" style). */
  cut?: CutEdge[];
}) {
  const reduced = useReducedMotion();
  const proof = model.chains.find((c) => c.kind === "proof") ?? null;
  const hops = proof?.steps.length ?? 0;
  const [litState, setLit] = useState(0);
  const [runId, setRunId] = useState(0);
  const isRipple = mode === "ripple" && ripple !== null;
  const maxHop = useMemo(() => (ripple ? Math.max(0, ...[...ripple.blast.values()].map((h) => h ?? 0)) : 0), [ripple]);
  const [rippleState, setRipple] = useState(-1);

  // Edge-by-edge path animation: one hop every 250 ms (skipped under reduced motion).
  useEffect(() => {
    if (reduced || hops === 0 || mode !== "path") return;
    let i = 0;
    const t = setInterval(() => {
      i += 1;
      setLit(i);
      if (i >= hops) clearInterval(t);
    }, STEP_MS);
    return () => clearInterval(t);
  }, [reduced, hops, runId, layoutKey, mode]);
  const lit = reduced ? hops : litState;

  // Ripple: the blast radius spreads one BFS hop at a time from the symptoms.
  useEffect(() => {
    if (reduced || !isRipple) return;
    let i = -1;
    const t = setInterval(() => {
      i += 1;
      setRipple(i);
      if (i >= maxHop) clearInterval(t);
    }, RIPPLE_MS);
    return () => {
      clearInterval(t);
      setRipple(-1);
    };
  }, [reduced, isRipple, maxHop, runId, layoutKey]);
  const rippleLevel = reduced ? maxHop : rippleState;

  const positions = useMemo(
    () =>
      layeredLayout({
        nodes: model.nodes
          .filter((n) => n.band !== "change")
          .map((n) => ({ id: n.id, band: n.band === "data" ? "data" : "service" })),
        edges: model.edges.filter((e) => e.kind !== "change"),
        changes: model.changes,
      }),
    [model],
  );

  const maxB = useMemo(() => Math.max(0, ...model.nodes.map((n) => n.betweenness ?? 0)), [model.nodes]);

  const highlight = proof !== null || model.chains.length > 0;
  // Nodes whose caption stays readable however far the view is zoomed out (lib/graphLabels.ts).
  const keys = useMemo(() => keyNodeIds(model, isRipple ? ripple : null, cut), [model, isRipple, ripple, cut]);
  // "Fit highlights" frames what the current mode highlights: chain roles (path) or cause + blast
  // radius (ripple), plus both ends of every min-cut edge; when that is too wide for the column to
  // stay readable, a tighter set (the proof chain and the rejected suspects) is framed instead.
  // Keyed by content, not identity: the live room re-reads the incident every second while an
  // action runs, and a new fit object on every refresh made React Flow re-fit against unmeasured
  // nodes (blank canvas).
  const focusKey = useMemo(
    () =>
      fitCandidates(model, isRipple ? ripple : null, cut)
        .map((ids) => ids.filter((id) => positions.has(id)))
        .filter((ids) => ids.length > 0)
        .map((ids) => ids.join("\u0001"))
        .join("\u0000"),
    [model, positions, isRipple, ripple, cut],
  );
  const fitPlan = useMemo(
    // maxZoom keeps a one- or two-node focus (e.g. a lone symptom) from filling the whole view.
    (): FitPlan => ({ candidates: focusKey ? focusKey.split("\u0000").map((s) => s.split("\u0001")) : [], padding: FOCUS_PADDING, maxZoom: 1.1 }),
    [focusKey],
  );

  const rippleRole = (id: string): RippleRole => {
    if (!isRipple || !ripple) return null;
    if (ripple.cause.has(id)) return "cause";
    const h = ripple.blast.get(id);
    if (h !== undefined && (h ?? 0) <= rippleLevel) return "blast";
    return "dim";
  };

  const nodes: Node<FlNodeData>[] = model.nodes
    .filter((n) => positions.has(n.id))
    .map((n) => {
      const interesting = n.roles.length > 0;
      // A path node lights once the animation has reached it (the cause is lit from the start).
      const litNode = n.step !== null && n.step <= lit;
      const size = sizeFor(n.betweenness, maxB);
      const p = positions.get(n.id)!;
      const rr = rippleRole(n.id);
      const h = ripple?.blast.get(n.id) ?? null;
      const keyNode = keys.has(n.id);
      const focusable = isRipple ? rr === "cause" || ripple!.blast.has(n.id) : interesting;
      return {
        id: n.id,
        type: "fl",
        position: { x: p.x + (NODE_MAX.w - size.w) / 2, y: p.y + (NODE_MAX.h - size.h) / 2 },
        // key nodes (and their captions) paint above the other nodes and the lit / cut edges
        zIndex: keyNode ? 30 : 0,
        data: {
          node: n,
          dimmed: !keyNode && (isRipple ? rr === "dim" : highlight && !interesting),
          lit: litNode,
          mode: isRipple ? "ripple" : "path",
          ripple: rr,
          hops: h,
          size,
          causeLabel: ripple?.causeLabel ?? "CAUSE",
          blastLabel: ripple?.blastLabel ?? "BLAST",
          keyNode,
          side: chipSide(p.x),
          priority: captionPriority(n, rr, h, ripple?.emphasis ?? null),
        },
        draggable: false,
        connectable: false,
        focusable,
        // a label only on a node that is in the tab order (React Flow gives it role=button then); a non-focusable
        // node's wrapper has no role, so an aria-label there is prohibited and its caption is visible text anyway
        ariaLabel: focusable ? describe(n, proof?.nodes.length ?? 0, isRipple ? "ripple" : "path", rr, h) : undefined,
      };
    });

  // Layout rectangles (+ the standing captions' on-screen size and side) keyed by content: stable across
  // the live room's 1 s refreshes.
  const rectKey = nodes
    .map((n) => {
      const c = n.data.keyNode ? captionEstimate(n.data) : null;
      return [n.id, n.position.x, n.position.y, n.data.size.w, n.data.size.h, c ? c.w : "", c ? c.h : "", c ? n.data.side : "", n.data.priority].join("\u0001");
    })
    .join("\u0000");

  const cutKey = cut.map((c) => `${c.u}\u0001${c.v}\u0001${c.cost}`).join("\u0000");
  const cutKeys = new Map(cut.map((c) => [`${c.u}->${c.v}`, c]));
  const edgeList = [...model.edges];
  for (const c of cut) {
    const id = `${c.u}->${c.v}`;
    if (!edgeList.some((e) => e.id === id)) {
      edgeList.push({ id, source: c.u, target: c.v, kind: c.domain === "data" || c.domain === "cross" ? c.domain : "service", cap: null, proofStep: null, rejected: false, synthetic: true });
    }
  }
  const inRipple = (id: string) => {
    const r = rippleRole(id);
    return r === "cause" || r === "blast";
  };

  const edges: Edge<FlEdgeData>[] = edgeList
    .filter((e) => positions.has(e.source) && positions.has(e.target))
    .map((e) => {
      const base = EDGE_STYLE[e.kind] ?? EDGE_STYLE.service;
      const c = cutKeys.get(e.id);
      const onProof = e.proofStep !== null && !isRipple;
      const isLit = onProof && e.proofStep! < lit;
      const rippleEdge = isRipple && inRipple(e.source) && inRipple(e.target);
      let stroke = isLit ? "#f87171" : e.rejected && !isRipple ? "#d4d4d8" : rippleEdge ? "#fbbf24" : base.stroke;
      let width = isLit ? 3.4 : e.rejected && !isRipple ? 2.2 : rippleEdge ? 2.6 : base.width;
      let dash = isLit ? undefined : e.rejected && !isRipple ? "5 5" : rippleEdge ? undefined : base.dash;
      let opacity = isRipple ? (rippleEdge ? 1 : 0.15) : highlight && !onProof && !e.rejected ? 0.4 : 1;
      if (c) {
        stroke = CUT_STYLE.stroke;
        width = CUT_STYLE.width;
        dash = CUT_STYLE.dash;
        opacity = 1;
      }
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: "fl",
        focusable: false,
        selectable: false,
        animated: (isLit || rippleEdge) && !reduced && !c,
        zIndex: c ? 20 : isLit ? 10 : e.rejected ? 5 : 0,
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
        data: { cut: c ? c.cost : null },
        style: { stroke, strokeWidth: width, strokeDasharray: dash, opacity },
      };
    });

  const liveText = isRipple
    ? rippleLevel >= maxHop && ripple
      ? `Ripple shown: cause ${[...ripple.cause].join(", ")}; ${ripple.blast.size} nodes in the blast radius, up to ${maxHop} hops from the symptoms`
      : ""
    : proof && lit >= hops
      ? `Proof path shown: ${proof.nodes.join(" to ")}`
      : "";

  return (
    <div className="fl-graph flex h-full flex-col">
      <div
        className="relative min-h-0 flex-1"
        onKeyDown={(ev) => {
          if (ev.key !== "Enter") return;
          const el = (ev.target as HTMLElement).closest(".react-flow__node");
          const id = el?.getAttribute("data-id");
          if (id) {
            ev.preventDefault();
            onOpenNode(id);
          }
        }}
      >
        {/* the provider (keyed, so a new graph or mode starts fresh) lets CaptionPlacer read the zoom outside <ReactFlow> */}
        <ReactFlowProvider key={`${layoutKey}:${isRipple ? "ripple" : "path"}:${cut.length}`}>
        <CaptionPlacer rectKey={rectKey} cutKey={cutKey}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          minZoom={MIN_ZOOM}
          maxZoom={2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          edgesFocusable={false}
          deleteKeyCode={null}
          onNodeClick={(_, n) => onOpenNode(n.id)}
          proOptions={{ hideAttribution: false }}
          colorMode="dark"
          ariaLabelConfig={{
            "node.a11yDescription.default": "Press Enter to open the Cypher panel for this node.",
            "node.a11yDescription.keyboardDisabled": "Press Enter to open the Cypher panel for this node.",
          }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#3f3f46" />
          <Controls showInteractive={false} showFitView={false} position="bottom-left" />
          <FitButtons hasFocus={fitPlan.candidates.length > 0} fitPlan={fitPlan} rectKey={rectKey} cutKey={cutKey} />
          <AutoFit fitPlan={fitPlan} rectKey={rectKey} cutKey={cutKey} />
        </ReactFlow>
        </CaptionPlacer>
        </ReactFlowProvider>
        {(isRipple || proof) && !reduced ? (
          <div className="absolute top-2 right-2 z-10">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setLit(0);
                setRipple(-1);
                setRunId((r) => r + 1);
              }}
            >
              <RotateCcw aria-hidden /> <span className="max-sm:sr-only">{isRipple ? "Replay ripple" : "Replay path"}</span>
            </Button>
          </div>
        ) : null}
      </div>
      <p className="sr-only" aria-live="polite">
        {liveText}
      </p>
    </div>
  );
}

type FitPadding = Parameters<typeof getViewportForBounds>[5];
/**
 * Room around a fitted focus, in px: the top clears the Fit / Replay buttons. Standing captions are part of
 * the fitted bounds (lib/graphLabels.ts boundsWithCaptions), so they need no room of their own.
 */
const FOCUS_PADDING: FitPadding = { top: "52px", bottom: "12px", left: "12px", right: "12px" };
const WHOLE_PADDING: FitPadding = { top: "52px", bottom: "12px", left: "12px", right: "12px" };

/** Focus sets in order of preference (empty = the whole graph), the padding and the zoom cap. */
type FitPlan = { candidates: string[][]; padding: FitPadding; maxZoom: number };
type Rects = Map<string, FitRect>;

function parseCut(cutKey: string): { u: string; v: string; cost: number }[] {
  return (cutKey ? cutKey.split("\u0000") : []).map((row) => {
    const [u, v, cost] = row.split("\u0001");
    return { u, v, cost: Number(cost) };
  });
}

/** Places the standing captions for the current zoom (lib/graphLabels.ts placeCaptions) and hands the spots to the nodes. */
function CaptionPlacer({ rectKey, cutKey, children }: { rectKey: string; cutKey: string; children: ReactNode }) {
  const zoom = useStore(zoomOf);
  const rects = useMemo(() => parseRects(rectKey), [rectKey]);
  const labels = useMemo(() => cutLabels(rects, parseCut(cutKey)), [rects, cutKey]);
  const spots = useMemo(() => placeCaptions([...rects.values()], zoom, labels), [rects, zoom, labels]);
  return <CaptionSpots.Provider value={spots}>{children}</CaptionSpots.Provider>;
}

/**
 * Fits the viewport from the layout's own node rectangles (positions + sizes are ours, from the
 * fixed layout and betweenness sizing) and applies it with setViewport. React Flow's fitView()
 * waits for measured nodes; with controlled nodes the measurement never reaches the store, so the
 * view could stay unfitted (blank or cropped). Only the canvas size is read from React Flow.
 */
function parseRects(rectKey: string): Rects {
  const m: Rects = new Map();
  for (const row of rectKey ? rectKey.split("\u0000") : []) {
    const [id, x, y, w, h, cw, ch, side, priority] = row.split("\u0001");
    const caption = cw ? { w: Number(cw), h: Number(ch), side: side as ChipSide } : null;
    m.set(id, { id, x: Number(x), y: Number(y), w: Number(w), h: Number(h), caption, priority: Number(priority) });
  }
  return m;
}

function useFit(rectKey: string, cutKey: string) {
  const rf = useReactFlow();
  const rects = useMemo(() => parseRects(rectKey), [rectKey]);
  const labels = useMemo(() => cutLabels(rects, parseCut(cutKey)), [rects, cutKey]);
  const width = useStore((st) => st.width);
  const height = useStore((st) => st.height);
  return useCallback(
    (plan: FitPlan) => {
      if (!width || !height || rects.size === 0) return false;
      const viewportFor = (b: Bounds) => getViewportForBounds(b, width, height, MIN_ZOOM, plan.maxZoom, plan.padding);
      const zoomFor = (b: Bounds) => viewportFor(b).zoom;
      const focus = plan.candidates
        .map((ids) => ids.filter((id) => rects.has(id)).map((id) => rects.get(id)!))
        .filter((list) => list.length > 0)
        .map((list) => boundsWithCaptions(list, zoomFor, labels));
      // The widest focus that still fits at a readable zoom, else the tighter one (lib/graphLabels.ts chooseFit).
      const bounds = chooseFit(focus, zoomFor) ?? boundsWithCaptions([...rects.values()], zoomFor, labels);
      void rf.setViewport(viewportFor(bounds));
      return true;
    },
    [rf, width, height, rects, labels],
  );
}

/** Fits on mount, and again when the highlighted set, the layout or the canvas size changes. */
function AutoFit({ fitPlan, rectKey, cutKey }: { fitPlan: FitPlan; rectKey: string; cutKey: string }) {
  const fit = useFit(rectKey, cutKey);
  useEffect(() => {
    const id = requestAnimationFrame(() => fit(fitPlan));
    return () => cancelAnimationFrame(id);
  }, [fitPlan, fit]);
  return null;
}

const WHOLE_GRAPH: FitPlan = { candidates: [], padding: WHOLE_PADDING, maxZoom: 2 };

function FitButtons({
  hasFocus,
  fitPlan,
  rectKey,
  cutKey,
}: {
  hasFocus: boolean;
  fitPlan: FitPlan;
  rectKey: string;
  cutKey: string;
}) {
  const fit = useFit(rectKey, cutKey);
  if (!hasFocus) return null;
  // Narrow screens: icon buttons (the words stay as their accessible names) so they do not collide with "Replay".
  return (
    <Panel position="top-left" className="flex gap-1.5">
      <Button size="sm" variant="outline" onClick={() => fit(fitPlan)}>
        <Route aria-hidden /> <span className="max-sm:sr-only">Fit highlights</span>
      </Button>
      <Button size="sm" variant="outline" onClick={() => fit(WHOLE_GRAPH)}>
        <Maximize2 aria-hidden /> <span className="max-sm:sr-only">Whole graph</span>
      </Button>
    </Panel>
  );
}
