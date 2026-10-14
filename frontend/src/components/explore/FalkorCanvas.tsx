"use client";

import { useEffect, useRef, useState } from "react";
import type { Data, FalkorDBCanvas, ForceGraphConfig, GraphNode as CanvasNode, LayoutMode } from "@falkordb/canvas";
import type { GraphResponse } from "@/lib/types";

/** Pinned in package.json (exact version); shown in the UI so nobody mistakes the renderer. */
export const CANVAS_PACKAGE = "@falkordb/canvas@0.3.3";

/** Node fill by label. Red and yellow are reserved for cause / blast radius in the incident room, so not used here. */
export const LABEL_COLOR: Record<string, string> = {
  Service: "#38bdf8",
  Datastore: "#a78bfa",
  Table: "#2dd4bf",
  KPI: "#a3e635",
  Dashboard: "#f472b6",
};
export const OTHER_COLOR = "#a1a1aa";

/** Edge stroke by PROPAGATES_TO domain. */
export const DOMAIN_COLOR: Record<string, string> = {
  service: "#71717a",
  data: "#2dd4bf",
  cross: "#c084fc",
};

/** Below this capacity an edge is drawn dashed (a best-effort call carries little of the failure). */
export const WEAK_CAP = 0.1;

export interface CanvasStatus {
  state: "loading" | "ready" | "error";
  error?: string;
}

/**
 * The FalkorDB canvas web component (`<falkordb-canvas>`), fed with GET /api/graph rows.
 * The package defines its custom element at import time (it extends HTMLElement), so it is
 * imported in an effect, on the client only. A load failure is reported, never papered over.
 */
export function FalkorCanvas({
  data,
  layout,
  selected,
  focus,
  onNodeClick,
  onStatus,
  label,
}: {
  data: GraphResponse;
  layout: LayoutMode;
  selected: string | null;
  focus: string | null;
  onNodeClick: (id: string) => void;
  onStatus: (s: CanvasStatus) => void;
  label: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<FalkorDBCanvas | null>(null);
  const [ready, setReady] = useState(false);
  // Callbacks read through refs so the canvas config is not rebuilt on every render.
  const clickRef = useRef(onNodeClick);
  const statusRef = useRef(onStatus);
  const selectedRef = useRef(selected);
  const focusRef = useRef(focus);
  useEffect(() => {
    clickRef.current = onNodeClick;
    statusRef.current = onStatus;
    selectedRef.current = selected;
    focusRef.current = focus;
  });

  // Mount the custom element once.
  useEffect(() => {
    let cancelled = false;
    const host = hostRef.current;
    if (!host) return;
    statusRef.current({ state: "loading" });
    let ro: ResizeObserver | null = null;
    let el: FalkorDBCanvas | null = null;
    import("@falkordb/canvas")
      .then(() => {
        if (cancelled) return;
        el = document.createElement("falkordb-canvas");
        el.style.display = "block";
        el.style.width = "100%";
        el.style.height = "100%";
        host.appendChild(el);
        const config: ForceGraphConfig = {
          width: host.clientWidth,
          height: host.clientHeight,
          backgroundColor: "#09090b",
          foregroundColor: "#e4e4e7",
          captionsKeys: [["name", true]],
          // Short links relative to the (betweenness-sized) nodes, so captions stay legible after zoom-to-fit.
          layoutOptions: { force: { linkDistance: 25, collisionPadding: 10 }, tree: { levelDistance: 110, nodeSpacing: 20 }, radial: { levelDistance: 110, nodeSpacing: 12 } },
          nodeStyle: { fontFamily: "ui-sans-serif, system-ui, sans-serif" },
          linkStyle: { fontFamily: "ui-sans-serif, system-ui, sans-serif" },
          // Views are capped at 100 edges (template LIMIT): small enough to always draw captions and arrows.
          largeGraph: { skipLabelsAtLowZoom: false, skipArrowsAtLowZoom: false, skipLinkLabelsAtLowZoom: true },
          isNodeSelected: (n: CanvasNode) => n.data.name === selectedRef.current || n.data.name === focusRef.current,
          linkLineDash: (l) => (typeof l.data.cap === "number" && l.data.cap < WEAK_CAP ? [4, 3] : []),
          eventHandlers: {
            onNodeClick: (n: CanvasNode) => {
              const id = n.data?.name;
              if (typeof id === "string") clickRef.current(id);
            },
          },
        };
        el.setConfig(config);
        canvasRef.current = el;
        ro = new ResizeObserver(() => {
          if (!el) return;
          el.setWidth(host.clientWidth);
          el.setHeight(host.clientHeight);
        });
        ro.observe(host);
        setReady(true);
        statusRef.current({ state: "ready" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        statusRef.current({ state: "error", error: `${CANVAS_PACKAGE} failed to load: ${err instanceof Error ? err.message : String(err)}` });
      });
    return () => {
      cancelled = true;
      ro?.disconnect();
      el?.remove();
      canvasRef.current = null;
    };
  }, []);

  // Data: string ids -> the numeric ids the component expects.
  useEffect(() => {
    const el = canvasRef.current;
    if (!ready || !el) return;
    el.setData(toCanvasData(data));
  }, [ready, data]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!ready || !el) return;
    el.setLayout(layout);
  }, [ready, layout]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!ready || !el) return;
    el.refresh();
  }, [ready, selected, focus]);

  // absolutely placed in its (relative) slot: the canvas the component draws never sizes the slot, so the resize
  // observer cannot feed back into itself (in a flowing layout each resize grew the slot, and the canvas, without end)
  return <div ref={hostRef} role="img" aria-label={label} className="absolute inset-0 overflow-hidden" />;
}

/** GET /api/graph rows -> the canvas' Data. Size grows with betweenness (sqrt-scaled), as in the incident room. */
export function toCanvasData(g: GraphResponse): Data {
  const index = new Map<string, number>();
  g.nodes.forEach((n, i) => index.set(n.id, i + 1));
  const maxB = Math.max(0, ...g.nodes.map((n) => n.betweenness ?? 0));
  return {
    nodes: g.nodes.map((n, i) => ({
      id: i + 1,
      labels: [n.label],
      color: LABEL_COLOR[n.label] ?? OTHER_COLOR,
      visible: true,
      size: 22 + (maxB > 0 ? 18 * Math.sqrt((n.betweenness ?? 0) / maxB) : 0),
      data: { name: n.id, label: n.label, tier: n.tier, betweenness: n.betweenness ?? null },
    })),
    links: g.edges
      .filter((e) => index.has(e.source) && index.has(e.target))
      .map((e, i) => ({
        id: i + 1,
        relationship: "PROPAGATES_TO",
        source: index.get(e.source)!,
        target: index.get(e.target)!,
        color: DOMAIN_COLOR[e.domain] ?? OTHER_COLOR,
        visible: true,
        width: e.cap === null ? 1 : 1 + 2 * Math.min(1, e.cap),
        data: { cap: e.cap, domain: e.domain },
      })),
  };
}
