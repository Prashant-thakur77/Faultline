import { COL_W } from "./layout";
import type { GraphModel, Role } from "./graphModel";

/**
 * Label legibility for the failure-flow graph view. Display only: it decides which names are printed
 * and how the view is framed, and answers no graph question (every role, hop count and impact set comes
 * from the gate runs and the FalkorDB reads behind /api/graph, /api/incidents and /api/preflight).
 *
 * React Flow scales node text with the zoom, so a 30-node graph fitted into a narrow column printed its
 * names at 2–6 px. Below DETAIL_ZOOM the view switches to a compact rendering:
 *  - key nodes (proof path, cause, symptoms, rejected suspects and their targets, min-cut ends; in
 *    preflight the changed component and its highest-impact reach) get a caption counter-scaled to a
 *    constant on-screen size, with the status as icon + text;
 *  - every other node prints its name inside its box only when it fits at LABEL_PX on screen, and
 *    otherwise stays an unlabelled box whose caption appears on hover, keyboard focus or selection.
 * Every name also stays in each node's aria-label and in the text alternatives under the graph.
 */

/** Minimum on-screen font size (CSS px) of any name the graph prints. */
export const LABEL_PX = 11;
/** At or above this zoom the node boxes carry their full text at ≥ LABEL_PX (11 px base × zoom). */
export const DETAIL_ZOOM = 1;
/** Box chrome in flow px: border and horizontal padding (zoomed out, a box with its name drops the icon). */
const BOX_CHROME = 18;
/** On-screen width an in-box name needs to be worth printing (about 6 monospace characters at LABEL_PX). */
export const NAME_MIN_PX = 44;
/** The initial view takes the widest focus set that still fits at this zoom (else the tighter one). */
export const MIN_FIT_ZOOM = 0.6;
/** Lowest zoom of the view and of any fit (a phone frames a 30-node reach at about 0.15). */
export const MIN_ZOOM = 0.1;

export type LabelLod = { mode: "detail" } | { mode: "compact"; inv: number; nameInBox: boolean };

/** How a node of `box` flow px renders at `zoom`; `inv` counter-scales text back to its on-screen size. */
export function labelLod(zoom: number, box: { w: number; h: number }): LabelLod {
  if (!Number.isFinite(zoom) || zoom <= 0 || zoom >= DETAIL_ZOOM) return { mode: "detail" };
  const nameInBox = (box.w - BOX_CHROME) * zoom >= NAME_MIN_PX && box.h * zoom >= LABEL_PX + 4;
  return { mode: "compact", inv: 1 / zoom, nameInBox };
}

export type ChipSide = "above" | "below";

/**
 * Captions alternate by layout column (x from the fixed layout), so the captions of two side-by-side
 * nodes on the same row never sit on the same side of their boxes and cannot overlap each other.
 */
export function chipSide(x: number): ChipSide {
  return Math.round(x / COL_W) % 2 === 0 ? "below" : "above";
}

/** Roles that keep a caption at any zoom in path mode ("rejected-path" tails stay hover-only). */
export const KEY_ROLES: readonly Role[] = ["cause", "path", "symptom", "rejected", "rejected-target"];

export interface RippleKeys {
  cause: Set<string>;
  blast: Map<string, number | null>;
  /** Extra nodes worth a caption (preflight: the highest-impact nodes the change reaches). */
  emphasis?: Set<string>;
}

/** Nodes that keep a readable caption however far the view is zoomed out. */
export function keyNodeIds(model: GraphModel, ripple: RippleKeys | null, cut: { u: string; v: string }[]): Set<string> {
  const ids = new Set<string>();
  if (ripple) {
    ripple.cause.forEach((id) => ids.add(id));
    ripple.emphasis?.forEach((id) => ids.add(id));
    // hop 0 = the symptoms the blast radius starts from
    ripple.blast.forEach((h, id) => {
      if (h === 0) ids.add(id);
    });
  } else {
    for (const n of model.nodes) if (n.roles.some((r) => KEY_ROLES.includes(r))) ids.add(n.id);
  }
  for (const c of cut) {
    ids.add(c.u);
    ids.add(c.v);
  }
  return ids;
}

/**
 * Focus sets for "Fit highlights", widest first. Path mode: every highlighted node, then the same without
 * the tails of rejected chains (the proof path, cause, symptoms, rejected suspects and their targets).
 * Ripple mode: the cause and the whole blast radius (that is the point of the mode). Both add the min-cut
 * ends. Empty and repeated sets are dropped; ids are sorted, so the result is stable across refreshes.
 */
export function fitCandidates(model: GraphModel, ripple: RippleKeys | null, cut: { u: string; v: string }[]): string[][] {
  const cutIds = cut.flatMap((c) => [c.u, c.v]);
  const sets: string[][] = [];
  if (ripple) {
    sets.push([...ripple.cause, ...ripple.blast.keys(), ...cutIds]);
  } else {
    const full = model.nodes.filter((n) => n.roles.length > 0).map((n) => n.id);
    const core = model.nodes.filter((n) => n.roles.some((r) => KEY_ROLES.includes(r))).map((n) => n.id);
    sets.push([...full, ...cutIds], [...core, ...cutIds]);
  }
  const out: string[][] = [];
  const seen = new Set<string>();
  for (const s of sets) {
    const ids = [...new Set(s)].sort();
    const key = ids.join("\u0000");
    if (!ids.length || seen.has(key)) continue;
    seen.add(key);
    out.push(ids);
  }
  return out;
}

/**
 * The first (widest) candidate whose fit zoom is at least `min`. When none is, the widest one that still fits
 * within `slack` of the closest zoom any candidate allows: framing more costs nothing when the other axis
 * limits the zoom anyway. Null when there is no candidate.
 */
export function chooseFit<T>(candidates: readonly T[], zoomOf: (c: T) => number, min = MIN_FIT_ZOOM, slack = 0.95): T | null {
  if (!candidates.length) return null;
  const zooms = candidates.map(zoomOf);
  const ok = zooms.findIndex((z) => z >= min);
  if (ok >= 0) return candidates[ok];
  const best = Math.max(...zooms);
  return candidates[zooms.findIndex((z) => z >= best * slack)];
}

/** On-screen size (CSS px) of a caption: a status line over the name, 12 px monospace (≈ 0.6 em a character). */
export function captionSize(name: string, status: string, pills: number): { w: number; h: number } {
  const w = Math.max(name.length * 7.4, status.length * 6.7 + pills * 18) + 16;
  return { w: Math.ceil(w), h: 46 };
}

export interface FitRect {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** The node's standing caption (on-screen px) and its preferred side, when it has one. */
  caption?: { w: number; h: number; side: ChipSide } | null;
  /** Placement order of the caption (lower first: it keeps its preferred side). */
  priority?: number;
}

/** A label of fixed on-screen size (w × h px) centred on a flow point (x, y): the min-cut labels. */
export interface FixedLabel {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function boundsOf(list: readonly { x: number; y: number; w: number; h: number }[]): Bounds {
  const x0 = Math.min(...list.map((r) => r.x));
  const y0 = Math.min(...list.map((r) => r.y));
  const x1 = Math.max(...list.map((r) => r.x + r.w));
  const y1 = Math.max(...list.map((r) => r.y + r.h));
  return { x: x0, y: y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0) };
}

type Box = { x: number; y: number; w: number; h: number };

/** Where a caption sits: over or under its node, shifted `dx` screen px from the node's centre line. */
export interface CaptionSpot {
  side: ChipSide;
  dx: number;
}

/** A caption's box in screen px (flow coordinates × zoom), over or under its node. */
function captionBox(r: FitRect, spot: CaptionSpot, z: number): Box {
  const c = r.caption!;
  const cx = (r.x + r.w / 2) * z + spot.dx;
  return { x: cx - c.w / 2, y: spot.side === "above" ? r.y * z - c.h : (r.y + r.h) * z, w: c.w, h: c.h };
}

function overlap(a: Box, b: Box): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}

/** Captions from this priority on (rejected suspects, min-cut ends) give way when no free spot is left. */
export const OPTIONAL_PRIORITY = 3;

/**
 * Places each standing caption at `zoom`. In priority order, a caption takes the first free spot among: its
 * preferred side, the other side, then both sides shifted a third of its width towards the middle of the
 * graph (still touching its node). A spot is free when it overlaps no caption already placed, no other
 * captioned node's box and no fixed label (min-cut). With no free spot, a caption below OPTIONAL_PRIORITY
 * takes the least overlapped spot and an optional one is dropped (null: its name then shows on hover / focus,
 * like any other node's). Greedy and deterministic (ties: x, then y, then id).
 */
export function placeCaptions(
  rects: readonly FitRect[],
  zoom: number,
  labels: readonly FixedLabel[] = [],
): Map<string, CaptionSpot | null> {
  const z = zoom > 0 ? zoom : 1;
  const withCaption = rects.filter((r) => r.caption);
  const mid = withCaption.length ? (Math.min(...withCaption.map((r) => r.x)) + Math.max(...withCaption.map((r) => r.x + r.w))) / 2 : 0;
  const boxes = withCaption.map((r) => ({ id: r.id, box: { x: r.x * z, y: r.y * z, w: r.w * z, h: r.h * z } }));
  const taken: Box[] = labels.map((l) => ({ x: l.x * z - l.w / 2, y: l.y * z - l.h / 2, w: l.w, h: l.h }));
  const order = [...withCaption].sort(
    (a, b) => (a.priority ?? 9) - (b.priority ?? 9) || a.x - b.x || a.y - b.y || a.id.localeCompare(b.id),
  );
  const out = new Map<string, CaptionSpot | null>();
  for (const r of order) {
    const pref = r.caption!.side;
    const other: ChipSide = pref === "above" ? "below" : "above";
    // inwards only: a caption pushed past the graph's outer nodes would widen the fitted view
    const shift = Math.round(r.caption!.w / 3) * (r.x + r.w / 2 <= mid ? 1 : -1);
    const spots: CaptionSpot[] = [
      { side: pref, dx: 0 },
      { side: other, dx: 0 },
      { side: pref, dx: shift },
      { side: other, dx: shift },
    ];
    let best = spots[0];
    let bestCost = Infinity;
    for (const spot of spots) {
      const box = captionBox(r, spot, z);
      let cost = 0;
      for (const t of taken) cost += overlap(box, t);
      for (const o of boxes) if (o.id !== r.id) cost += overlap(box, o.box);
      if (cost < bestCost) {
        best = spot;
        bestCost = cost;
      }
      if (cost === 0) break;
    }
    if (bestCost > 0 && (r.priority ?? OPTIONAL_PRIORITY) >= OPTIONAL_PRIORITY) {
      out.set(r.id, null);
      continue;
    }
    out.set(r.id, best);
    taken.push(captionBox(r, best, z));
  }
  return out;
}

/** The min-cut labels ("✂ cut n", 11 px monospace) at the midpoint of their edge (right handle → left handle). */
export function cutLabels(rects: ReadonlyMap<string, FitRect>, cut: readonly { u: string; v: string; cost: number }[]): FixedLabel[] {
  const out: FixedLabel[] = [];
  for (const c of cut) {
    const s = rects.get(c.u);
    const t = rects.get(c.v);
    if (!s || !t) continue;
    out.push({ x: (s.x + s.w + t.x) / 2, y: (s.y + s.h / 2 + t.y + t.h / 2) / 2, w: `✂ cut ${c.cost}`.length * 6.7 + 12, h: 18 });
  }
  return out;
}

/**
 * Bounds of the boxes plus their standing captions, where placeCaptions puts them. A caption keeps its
 * on-screen size, so its size in flow units depends on the zoom the bounds lead to: a few fixed-point rounds
 * of zoom → bounds → zoom settle it.
 */
export function boundsWithCaptions(
  list: readonly FitRect[],
  zoomFor: (b: Bounds) => number,
  labels: readonly FixedLabel[] = [],
  rounds = 4,
): Bounds {
  let b = boundsOf(list);
  for (let i = 0; i < rounds; i++) {
    const z = zoomFor(b);
    if (!(z > 0)) break;
    const spots = placeCaptions(list, z, labels);
    const parts: Box[] = [];
    for (const r of list) {
      parts.push(r);
      const spot = spots.get(r.id);
      if (!r.caption || !spot) continue;
      const c = captionBox(r, spot, z);
      parts.push({ x: c.x / z, y: c.y / z, w: c.w / z, h: c.h / z });
    }
    b = boundsOf(parts);
  }
  return b;
}

/**
 * Preflight's highest-impact nodes, from the assessment FalkorDB returned: the revenue tier-1 components
 * the change reaches and any KPI it reaches (by the node's label in /api/graph). The changed components
 * already carry their own caption, so they are left out.
 */
export function preflightEmphasis(
  a: { changed: string[]; impacted: string[]; revenue_tier1: string[] },
  labelOf: (id: string) => string | undefined,
): string[] {
  const changed = new Set(a.changed);
  const out = new Set<string>();
  for (const id of a.revenue_tier1) if (!changed.has(id)) out.add(id);
  for (const id of a.impacted) if (!changed.has(id) && labelOf(id) === "KPI") out.add(id);
  return [...out];
}
