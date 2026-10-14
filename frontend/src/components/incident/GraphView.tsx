"use client";

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  getViewportForBounds,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeProps,
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
};

function sizeFor(b: number | null, maxB: number): { w: number; h: number } {
  if (b === null || maxB <= 0) return NODE_MIN;
  const t = Math.sqrt(Math.max(0, b) / maxB);
  return { w: Math.round(NODE_MIN.w + (NODE_MAX.w - NODE_MIN.w) * t), h: Math.round(NODE_MIN.h + (NODE_MAX.h - NODE_MIN.h) * t) };
}

const FlNode = memo(function FlNode({ data }: NodeProps<Node<FlNodeData>>) {
  const n = data.node;
  const Icon = LABEL_ICON[n.label] ?? Server;
  const ripple = data.mode === "ripple";
  const cause = ripple ? data.ripple === "cause" : n.roles.includes("cause");
  const blast = ripple && data.ripple === "blast";
  const rejected = !ripple && n.roles.includes("rejected");
  const rejectedTarget = !ripple && n.roles.includes("rejected-target");
  const symptom = n.roles.includes("symptom");
  const onPath = !ripple && n.roles.includes("path");
  return (
    <div
      style={{ width: data.size.w, height: data.size.h }}
      className={cn(
        "relative flex items-center gap-2 rounded-lg border bg-zinc-900 px-2 py-1 text-left transition-[opacity,box-shadow,background-color] duration-200",
        n.band === "data" && "rounded-sm border-dashed",
        n.band === "change" && "rounded-full",
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
      )}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} className="!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
      <Icon aria-hidden className={cn("size-4 shrink-0", cause ? "text-red-300" : blast ? "text-amber-200" : n.band === "data" ? "text-sky-300" : n.band === "change" ? "text-orange-300" : "text-zinc-300")} />
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "truncate font-mono leading-4 text-zinc-50",
            n.roles.length || blast || cause ? "text-[12.5px] font-semibold" : "text-[11px]",
            rejected && "line-through decoration-zinc-400",
          )}
          title={n.id}
        >
          {n.id}
        </p>
        <p className="flex items-center gap-1 text-[10px] leading-3.5 text-zinc-300">
          <span>{n.label}</span>
          {n.tier !== null ? <span>· t{n.tier}</span> : null}
          {!ripple && n.step !== null ? <span className="font-semibold text-amber-200">· step {n.step + 1}</span> : null}
          {blast && data.hops !== null ? <span className="font-semibold text-amber-100">· {data.hops} hop{data.hops === 1 ? "" : "s"}</span> : null}
          {!ripple && n.outCap ? (
            <span
              className={cn(
                "ml-auto inline-flex items-center gap-0.5 rounded px-1 font-mono text-[10.5px] leading-3.5 font-bold",
                n.outCap.rejected ? "bg-zinc-100 text-zinc-950" : "bg-red-200 text-red-950",
              )}
              title={`capacity of the hop to ${n.outCap.to}`}
            >
              {n.outCap.rejected ? <Ban aria-hidden className="size-2.5" /> : null}
              cap {n.outCap.cap}
            </span>
          ) : null}
        </p>
      </div>
      {cause ? (
        <Badge className="border-red-400 bg-red-700 text-white" icon={Siren} text={data.causeLabel} />
      ) : blast ? (
        symptom ? (
          <Badge className="border-amber-300 bg-amber-400 text-zinc-950" icon={Gauge} text="SYMPTOM" />
        ) : (
          <Badge className="border-amber-300 bg-amber-300 text-zinc-950" icon={Waves} text={data.blastLabel} />
        )
      ) : rejected ? (
        <Badge className="border-zinc-400 bg-zinc-700 text-zinc-50" icon={Ban} text="REJECTED" />
      ) : symptom && !ripple ? (
        <Badge className="border-amber-300 bg-amber-400 text-zinc-950" icon={Gauge} text="SYMPTOM" />
      ) : rejectedTarget ? (
        <Badge className="border-zinc-400 bg-zinc-800 text-zinc-100" icon={Ban} text="REJ. TARGET" />
      ) : null}
      <Handle type="source" position={Position.Right} isConnectable={false} className="!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
    </div>
  );
});

function Badge({ className, icon: Icon, text }: { className: string; icon: LucideIcon; text: string }) {
  return (
    <span className={cn("absolute -top-2.5 right-1.5 flex items-center gap-0.5 rounded border px-1 text-[9px] leading-3.5 font-bold tracking-wide", className)}>
      <Icon aria-hidden className="size-2.5" />
      {text}
    </span>
  );
}

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
  // "Fit highlights" frames what the current mode highlights: chain roles (path) or cause + blast
  // radius (ripple), plus both ends of every min-cut edge. Keyed by content, not identity: the
  // live room re-reads the incident every second while an action runs, and a new fitViewOptions
  // object on every refresh made React Flow re-fit against unmeasured nodes (blank canvas).
  const focusKey = useMemo(() => {
    const ids = new Set<string>();
    if (isRipple && ripple) {
      ripple.cause.forEach((id) => ids.add(id));
      ripple.blast.forEach((_, id) => ids.add(id));
    } else {
      for (const n of model.nodes) if (n.roles.length > 0) ids.add(n.id);
    }
    for (const c of cut) {
      ids.add(c.u);
      ids.add(c.v);
    }
    return [...ids].filter((id) => positions.has(id)).sort().join("\u0000");
  }, [model.nodes, positions, isRipple, ripple, cut]);
  const focusIds = useMemo(() => (focusKey ? focusKey.split("\u0000").map((id) => ({ id })) : []), [focusKey]);
  const fitOptions = useMemo(
    // maxZoom keeps a one- or two-node focus (e.g. a lone symptom) from filling the whole view.
    () => (focusIds.length ? { padding: 0.12, nodes: focusIds, maxZoom: 1.1 } : { padding: 0.08 }),
    [focusIds],
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
      return {
        id: n.id,
        type: "fl",
        position: { x: p.x + (NODE_MAX.w - size.w) / 2, y: p.y + (NODE_MAX.h - size.h) / 2 },
        data: {
          node: n,
          dimmed: isRipple ? rr === "dim" : highlight && !interesting,
          lit: litNode,
          mode: isRipple ? "ripple" : "path",
          ripple: rr,
          hops: h,
          size,
          causeLabel: ripple?.causeLabel ?? "CAUSE",
          blastLabel: ripple?.blastLabel ?? "BLAST",
        },
        draggable: false,
        connectable: false,
        focusable: isRipple ? rr === "cause" || ripple!.blast.has(n.id) : interesting,
        ariaLabel: describe(n, proof?.nodes.length ?? 0, isRipple ? "ripple" : "path", rr, h),
      };
    });

  // Layout rectangles keyed by content (stable across the live room's 1 s refreshes).
  const rectKey = nodes.map((n) => `${n.id}\u0001${n.position.x}\u0001${n.position.y}\u0001${n.data.size.w}\u0001${n.data.size.h}`).join("\u0000");

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

  const edges: Edge[] = edgeList
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
        type: "default",
        focusable: false,
        animated: (isLit || rippleEdge) && !reduced && !c,
        zIndex: c ? 20 : isLit ? 10 : e.rejected ? 5 : 0,
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
        label: c ? `✂ cut ${c.cost}` : undefined,
        labelStyle: c ? { fill: "#fecaca", fontSize: 11, fontWeight: 700, fontFamily: "var(--font-geist-mono)" } : undefined,
        labelBgStyle: c ? { fill: "#450a0a", stroke: "#ef4444", strokeWidth: 1 } : undefined,
        labelBgPadding: c ? ([4, 2] as [number, number]) : undefined,
        labelBgBorderRadius: 3,
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
    <div className="flex h-full flex-col">
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
        <ReactFlow
          key={`${layoutKey}:${isRipple ? "ripple" : "path"}:${cut.length}`}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitViewOptions={fitOptions}
          minZoom={0.15}
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
          <FitButtons hasFocus={focusIds.length > 0} fitOptions={fitOptions} rectKey={rectKey} />
          <AutoFit fitOptions={fitOptions} rectKey={rectKey} />
        </ReactFlow>
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
              <RotateCcw aria-hidden /> {isRipple ? "Replay ripple" : "Replay path"}
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

type FitOptions = { padding: number; nodes?: { id: string }[]; maxZoom?: number };
type Rects = Map<string, { x: number; y: number; w: number; h: number }>;

/**
 * Fits the viewport from the layout's own node rectangles (positions + sizes are ours, from the
 * fixed layout and betweenness sizing) and applies it with setViewport. React Flow's fitView()
 * waits for measured nodes; with controlled nodes the measurement never reaches the store, so the
 * view could stay unfitted (blank or cropped). Only the canvas size is read from React Flow.
 */
function parseRects(rectKey: string): Rects {
  const m: Rects = new Map();
  for (const row of rectKey ? rectKey.split("\u0000") : []) {
    const [id, x, y, w, h] = row.split("\u0001");
    m.set(id, { x: Number(x), y: Number(y), w: Number(w), h: Number(h) });
  }
  return m;
}

function useFit(rectKey: string) {
  const rf = useReactFlow();
  const rects = useMemo(() => parseRects(rectKey), [rectKey]);
  const width = useStore((st) => st.width);
  const height = useStore((st) => st.height);
  return useCallback(
    (opts: FitOptions) => {
      if (!width || !height || rects.size === 0) return false;
      const ids = opts.nodes?.map((n) => n.id).filter((id) => rects.has(id));
      const list = (ids && ids.length ? ids : [...rects.keys()]).map((id) => rects.get(id)!);
      const x0 = Math.min(...list.map((r) => r.x));
      const y0 = Math.min(...list.map((r) => r.y));
      const x1 = Math.max(...list.map((r) => r.x + r.w));
      const y1 = Math.max(...list.map((r) => r.y + r.h));
      const bounds = { x: x0, y: y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0) };
      void rf.setViewport(getViewportForBounds(bounds, width, height, 0.15, opts.maxZoom ?? 2, opts.padding));
      return true;
    },
    [rf, width, height, rects],
  );
}

/** Fits on mount, and again when the highlighted set, the layout or the canvas size changes. */
function AutoFit({ fitOptions, rectKey }: { fitOptions: FitOptions; rectKey: string }) {
  const fit = useFit(rectKey);
  useEffect(() => {
    const id = requestAnimationFrame(() => fit(fitOptions));
    return () => cancelAnimationFrame(id);
  }, [fitOptions, fit]);
  return null;
}

function FitButtons({
  hasFocus,
  fitOptions,
  rectKey,
}: {
  hasFocus: boolean;
  fitOptions: FitOptions;
  rectKey: string;
}) {
  const fit = useFit(rectKey);
  if (!hasFocus) return null;
  return (
    <Panel position="top-left" className="flex gap-1.5">
      <Button size="sm" variant="outline" onClick={() => fit(fitOptions)}>
        <Route aria-hidden /> Fit highlights
      </Button>
      <Button size="sm" variant="outline" onClick={() => fit({ padding: 0.06 })}>
        <Maximize2 aria-hidden /> Whole graph
      </Button>
    </Panel>
  );
}
