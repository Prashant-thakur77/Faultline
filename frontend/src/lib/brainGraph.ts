import type { BrainSubgraph, BrainSubgraphEdge, BrainSubgraphNode } from "./types";

/**
 * "Answer as a graph" (Q-BRAIN-SUB): a brain answer's cited ids and the nodes that connect them, laid out in
 * columns by what a node is (who → decisions → context → systems). Pure and deterministic: the same payload always
 * yields the same picture (payload order and ids break every tie), so every demo run looks identical. Nothing is
 * inferred: a node or edge that is not in the payload is never drawn.
 */

/** The most ids one subgraph request may carry (the API's cap). */
export const MAX_SUBGRAPH_IDS = 12;

/** Unique, non-empty cited ids in answer order, capped at the API's limit. */
export function subgraphIds(citations: string[]): { ids: string[]; total: number } {
  const seen: string[] = [];
  for (const c of citations) {
    const id = c.trim();
    // the API splits ?ids= on commas, so an id containing one cannot be asked for
    if (id && !id.includes(",") && !seen.includes(id)) seen.push(id);
  }
  return { ids: seen.slice(0, MAX_SUBGRAPH_IDS), total: seen.length };
}

export type Shape = "circle" | "diamond" | "hexagon" | "square" | "cylinder" | "page" | "triangle" | "ring";

/** How each label is drawn: shape and colour. Unknown labels fall back to OTHER_KIND (a dotted ring, neutral). */
export interface KindStyle {
  shape: Shape;
  /** CSS colour for the shape (fill when cited, stroke always). */
  color: string;
}

export const KIND_STYLE: Record<string, KindStyle> = {
  Person: { shape: "circle", color: "rgb(125 211 252)" }, // sky-300
  Team: { shape: "hexagon", color: "rgb(196 181 253)" }, // violet-300
  Decision: { shape: "diamond", color: "rgb(252 211 77)" }, // amber-300
  Guardrail: { shape: "diamond", color: "rgb(253 186 116)" }, // orange-300
  SLO: { shape: "diamond", color: "rgb(253 186 116)" },
  Doc: { shape: "page", color: "rgb(212 212 216)" }, // zinc-300
  Runbook: { shape: "page", color: "rgb(165 180 252)" }, // indigo-300
  Incident: { shape: "triangle", color: "rgb(252 165 165)" }, // red-300
  Alert: { shape: "triangle", color: "rgb(253 164 175)" }, // rose-300
  Symptom: { shape: "triangle", color: "rgb(253 164 175)" },
  Deploy: { shape: "hexagon", color: "rgb(253 186 116)" },
  PR: { shape: "hexagon", color: "rgb(253 186 116)" },
  Commit: { shape: "hexagon", color: "rgb(253 186 116)" },
  ChangeFact: { shape: "hexagon", color: "rgb(253 186 116)" },
  Service: { shape: "square", color: "rgb(110 231 183)" }, // emerald-300
  Datastore: { shape: "cylinder", color: "rgb(103 232 249)" }, // cyan-300
  Table: { shape: "cylinder", color: "rgb(94 234 212)" }, // teal-300
  Transform: { shape: "square", color: "rgb(94 234 212)" },
  KPI: { shape: "square", color: "rgb(249 168 212)" }, // pink-300
  Dashboard: { shape: "square", color: "rgb(249 168 212)" },
};
export const OTHER_KIND: KindStyle = { shape: "ring", color: "rgb(212 212 216)" };

export function kindStyle(label: string): KindStyle {
  return KIND_STYLE[label] ?? OTHER_KIND;
}

/** Display label of a node: its domain label, or "Node" when the graph gave none. */
export function nodeLabel(n: Pick<BrainSubgraphNode, "label">): string {
  return n.label?.trim() || "Node";
}

interface ColumnDef {
  key: string;
  title: string;
  labels: string[];
}

/** Columns by what a node is; a label not listed lands in "context". */
const KIND_COLUMNS: ColumnDef[] = [
  { key: "who", title: "Who", labels: ["Person", "Team"] },
  { key: "decided", title: "Decisions", labels: ["Decision", "Guardrail", "SLO"] },
  {
    key: "context",
    title: "Context",
    labels: ["Doc", "Runbook", "Incident", "Alert", "Symptom", "Deploy", "PR", "Commit", "ChangeFact"],
  },
  { key: "systems", title: "Systems", labels: ["Service", "Datastore", "Table", "Transform", "KPI", "Dashboard"] },
];
const FALLBACK_COLUMN = "context";

/** Card geometry, px. Cited cards are larger than connecting ones. */
export const GEOMETRY = {
  padX: 26,
  padTop: 30,
  padBottom: 10,
  colPitch: 184,
  rowPitch: 64,
  cited: { w: 140, h: 54 },
  link: { w: 128, h: 40 },
} as const;

export interface PlacedNode {
  id: string;
  label: string;
  name: string;
  cited: boolean;
  col: number;
  row: number;
  /** Top-left corner and size of the card. */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DrawnPair {
  /** `a|b` with a placed before b (column, then row). */
  key: string;
  a: string;
  b: string;
  /** Every stored edge between the two, in payload order. */
  edges: BrainSubgraphEdge[];
  /** An edge runs a → b (arrowhead at b) / b → a (arrowhead at a). */
  forward: boolean;
  backward: boolean;
  /** Distinct relationship types between the two, in payload order. */
  rels: string[];
  d: string;
  /** The curve's midpoint (where its label sits). */
  mx: number;
  my: number;
}

export interface RelSummary {
  rel: string;
  count: number;
  /** Distinct "SourceLabel → TargetLabel" pairs, in payload order. */
  ends: string[];
}

export interface BrainGraphLayout {
  columns: { key: string; title: string; x: number; count: number }[];
  nodes: PlacedNode[];
  /** One drawn line per connected pair (parallel edges share it; the text list keeps each one). */
  pairs: DrawnPair[];
  /** The payload's edges whose ends are both drawn, exact duplicates removed, in payload order. */
  edges: BrainSubgraphEdge[];
  rels: RelSummary[];
  /** Labels drawn, in first-appearance order (for the legend). */
  labels: string[];
  /** Requested ids the payload does not contain (not connected to any other cited id within the hop limit). */
  unconnected: string[];
  width: number;
  height: number;
}

const cmp = (x: string, y: string) => (x < y ? -1 : x > y ? 1 : 0);

export function layoutBrainGraph(
  data: Pick<BrainSubgraph, "nodes" | "edges">,
  requested: string[] = [],
): BrainGraphLayout {
  // nodes: first occurrence of each id wins
  const byId = new Map<string, BrainSubgraphNode>();
  for (const n of data.nodes) if (n.id && !byId.has(n.id)) byId.set(n.id, n);
  const nodes = [...byId.values()];

  // edges: both ends drawn, no exact duplicates, no self-loops
  const seenEdge = new Set<string>();
  const edges: BrainSubgraphEdge[] = [];
  for (const e of data.edges) {
    if (!byId.has(e.source) || !byId.has(e.target) || e.source === e.target) continue;
    const k = `${e.source}|${e.rel}|${e.target}`;
    if (seenEdge.has(k)) continue;
    seenEdge.add(k);
    edges.push(e);
  }
  const nbrs = new Map<string, Set<string>>(nodes.map((n) => [n.id, new Set<string>()]));
  for (const e of edges) {
    nbrs.get(e.source)!.add(e.target);
    nbrs.get(e.target)!.add(e.source);
  }

  // columns: by kind; when every node is one kind, split cited from connecting instead
  const kindCol = (n: BrainSubgraphNode) =>
    KIND_COLUMNS.find((c) => c.labels.includes(nodeLabel(n)))?.key ?? FALLBACK_COLUMN;
  let defs: { key: string; title: string; members: BrainSubgraphNode[] }[] = KIND_COLUMNS.map((c) => ({
    key: c.key,
    title: c.title,
    members: nodes.filter((n) => kindCol(n) === c.key),
  })).filter((c) => c.members.length);
  if (defs.length === 1) {
    defs = [
      { key: "cited", title: "Cited", members: nodes.filter((n) => n.cited) },
      { key: "via", title: "Connecting", members: nodes.filter((n) => !n.cited) },
    ].filter((c) => c.members.length);
  }

  // initial order inside a column: cited first, then by label (in column order), then id
  const labelRank = (n: BrainSubgraphNode) => {
    const all = KIND_COLUMNS.flatMap((c) => c.labels);
    const i = all.indexOf(nodeLabel(n));
    return i < 0 ? all.length : i;
  };
  const cols: string[][] = defs.map((c) =>
    [...c.members]
      .sort(
        (a, b) =>
          Number(b.cited) - Number(a.cited) ||
          labelRank(a) - labelRank(b) ||
          cmp(nodeLabel(a), nodeLabel(b)) ||
          cmp(a.id, b.id),
      )
      .map((n) => n.id),
  );
  const maxRows = Math.max(1, ...cols.map((c) => c.length));
  const colOf = new Map<string, number>();
  cols.forEach((c, ci) => c.forEach((id) => colOf.set(id, ci)));
  const rowY = (ci: number, i: number) =>
    GEOMETRY.padTop + ((maxRows - cols[ci].length) / 2) * GEOMETRY.rowPitch + i * GEOMETRY.rowPitch + GEOMETRY.rowPitch / 2;
  const centreY = new Map<string, number>();
  const place = (ci: number) => cols[ci].forEach((id, i) => centreY.set(id, rowY(ci, i)));
  cols.forEach((_, ci) => place(ci));

  // barycentre sweeps (alternating direction): order each column by the mean height of its neighbours (a node in
  // the same column counts too, so connectors gather round the cited node they hang off); a node with none keeps its
  // height; the previous order breaks ties
  for (let it = 0; it < 4; it++) {
    const order = cols.map((_, i) => i);
    if (it % 2) order.reverse();
    for (const ci of order) {
      const keyed = cols[ci].map((id, i) => {
        const ys = [...nbrs.get(id)!].map((o) => centreY.get(o)!);
        return { id, i, key: ys.length ? ys.reduce((s, y) => s + y, 0) / ys.length : centreY.get(id)! };
      });
      keyed.sort((p, q) => p.key - q.key || p.i - q.i);
      cols[ci] = keyed.map((k) => k.id);
      place(ci);
    }
  }

  const colX = (ci: number) => GEOMETRY.padX + ci * GEOMETRY.colPitch;
  const placed: PlacedNode[] = [];
  cols.forEach((c, ci) =>
    c.forEach((id, row) => {
      const n = byId.get(id)!;
      const size = n.cited ? GEOMETRY.cited : GEOMETRY.link;
      placed.push({
        id,
        label: nodeLabel(n),
        name: n.name?.trim() || id,
        cited: !!n.cited,
        col: ci,
        row,
        x: colX(ci) + (GEOMETRY.cited.w - size.w) / 2,
        y: centreY.get(id)! - size.h / 2,
        w: size.w,
        h: size.h,
      });
    }),
  );
  const at = new Map(placed.map((p) => [p.id, p]));

  // one line per unordered pair
  const pairs = new Map<string, DrawnPair>();
  for (const e of edges) {
    const s = at.get(e.source)!;
    const t = at.get(e.target)!;
    const sFirst = s.col < t.col || (s.col === t.col && s.row < t.row);
    const [a, b] = sFirst ? [s, t] : [t, s];
    const key = `${a.id}|${b.id}`;
    let p = pairs.get(key);
    if (!p) {
      p = { key, a: a.id, b: b.id, edges: [], forward: false, backward: false, rels: [], d: "", mx: 0, my: 0 };
      pairs.set(key, p);
    }
    p.edges.push(e);
    if (sFirst) p.forward = true;
    else p.backward = true;
    if (!p.rels.includes(e.rel)) p.rels.push(e.rel);
  }
  const GAP = 3; // room for an arrowhead
  for (const p of pairs.values()) {
    const a = at.get(p.a)!;
    const b = at.get(p.b)!;
    let pts: [number, number][];
    if (a.col !== b.col) {
      const x1 = a.x + a.w + (p.backward ? GAP : 0);
      const x2 = b.x - (p.forward ? GAP : 0);
      const y1 = a.y + a.h / 2;
      const y2 = b.y + b.h / 2;
      const dx = Math.max(24, (x2 - x1) / 2);
      pts = [
        [x1, y1],
        [x1 + dx, y1],
        [x2 - dx, y2],
        [x2, y2],
      ];
    } else {
      // same column: an arc bulging to the left of the cards
      const x1 = a.x - (p.backward ? GAP : 0);
      const x2 = b.x - (p.forward ? GAP : 0);
      const y1 = a.y + a.h / 2;
      const y2 = b.y + b.h / 2;
      const k = Math.min(30, 12 + 7 * Math.abs(b.row - a.row));
      const cx = Math.min(a.x, b.x) - k;
      pts = [
        [x1, y1],
        [cx, y1],
        [cx, y2],
        [x2, y2],
      ];
    }
    const r = (v: number) => Math.round(v * 10) / 10;
    p.d = `M ${r(pts[0][0])} ${r(pts[0][1])} C ${r(pts[1][0])} ${r(pts[1][1])}, ${r(pts[2][0])} ${r(pts[2][1])}, ${r(pts[3][0])} ${r(pts[3][1])}`;
    // cubic Bézier at t = 0.5
    p.mx = r((pts[0][0] + 3 * pts[1][0] + 3 * pts[2][0] + pts[3][0]) / 8);
    p.my = r((pts[0][1] + 3 * pts[1][1] + 3 * pts[2][1] + pts[3][1]) / 8);
  }

  const rels = new Map<string, RelSummary>();
  for (const e of edges) {
    const r = rels.get(e.rel) ?? rels.set(e.rel, { rel: e.rel, count: 0, ends: [] }).get(e.rel)!;
    r.count++;
    const ends = `${at.get(e.source)!.label} → ${at.get(e.target)!.label}`;
    if (!r.ends.includes(ends)) r.ends.push(ends);
  }

  const labels: string[] = [];
  for (const n of placed) if (!labels.includes(n.label)) labels.push(n.label);

  return {
    columns: defs.map((c, ci) => ({ key: c.key, title: c.title, x: colX(ci), count: cols[ci].length })),
    nodes: placed,
    pairs: [...pairs.values()],
    edges,
    rels: [...rels.values()],
    labels,
    unconnected: requested.filter((id) => !byId.has(id)),
    width: GEOMETRY.padX * 2 + (defs.length - 1) * GEOMETRY.colPitch + GEOMETRY.cited.w,
    height: GEOMETRY.padTop + maxRows * GEOMETRY.rowPitch + GEOMETRY.padBottom,
  };
}

/** The lines and neighbours a node lights when hovered or focused (presentation only). */
export function touching(id: string, pairs: DrawnPair[]): { nodes: Set<string>; pairs: Set<string> } {
  const nodes = new Set([id]);
  const lit = new Set<string>();
  for (const p of pairs) {
    if (p.a !== id && p.b !== id) continue;
    lit.add(p.key);
    nodes.add(p.a);
    nodes.add(p.b);
  }
  return { nodes, pairs: lit };
}
