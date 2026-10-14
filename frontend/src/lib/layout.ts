/**
 * Deterministic layered layout for the failure-flow graph.
 *
 * Display only: it positions what /api/graph returned and answers no graph question
 * (reachability, ranking and paths all come from FalkorDB). The same input always
 * yields the same coordinates: every iteration is over id-sorted arrays, ties break
 * by id, and nothing is random. Changes (deploys) sit in a dedicated lane on the
 * far left next to the node they changed; sinks (KPI, dashboards, edge proxies)
 * end up on the right.
 */

export interface LayoutInput {
  nodes: { id: string; band: "service" | "data" }[];
  edges: { source: string; target: string }[];
  /** Change nodes and the node each one changed (placed in the left lane). */
  changes: { id: string; target: string }[];
}

export interface Point {
  x: number;
  y: number;
}

export const COL_W = 216;
export const ROW_H = 74;
const BAND_GAP = 46;

export function layeredLayout(input: LayoutInput): Map<string, Point> {
  const ids = [...new Set(input.nodes.map((n) => n.id))].sort();
  const known = new Set(ids);
  const band = new Map(input.nodes.map((n) => [n.id, n.band]));
  const edges = input.edges
    .filter((e) => known.has(e.source) && known.has(e.target) && e.source !== e.target)
    .map((e) => [e.source, e.target] as const)
    .sort((a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]));

  const out = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const [s, t] of edges) out.get(s)!.push(t);

  // 1. Break cycles: iterative DFS in id order; back edges are ignored for layering.
  const state = new Map<string, 0 | 1 | 2>();
  const back = new Set<string>();
  for (const root of ids) {
    if (state.get(root)) continue;
    const stack: [string, number][] = [[root, 0]];
    state.set(root, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const [v, i] = top;
      const succ = out.get(v)!;
      if (i < succ.length) {
        top[1] = i + 1;
        const w = succ[i];
        const st = state.get(w) ?? 0;
        if (st === 1) back.add(`${v}\u0000${w}`);
        else if (st === 0) {
          state.set(w, 1);
          stack.push([w, 0]);
        }
      } else {
        state.set(v, 2);
        stack.pop();
      }
    }
  }
  const dag = edges.filter(([s, t]) => !back.has(`${s}\u0000${t}`));

  // 2. Longest-path layering (Kahn, id-ordered queue).
  const indeg = new Map(ids.map((id) => [id, 0]));
  const dagOut = new Map<string, string[]>(ids.map((id) => [id, []]));
  const dagIn = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const [s, t] of dag) {
    dagOut.get(s)!.push(t);
    dagIn.get(t)!.push(s);
    indeg.set(t, indeg.get(t)! + 1);
  }
  const layer = new Map(ids.map((id) => [id, 0]));
  const queue = ids.filter((id) => indeg.get(id) === 0);
  while (queue.length) {
    queue.sort();
    const v = queue.shift()!;
    for (const w of dagOut.get(v)!) {
      layer.set(w, Math.max(layer.get(w)!, layer.get(v)! + 1));
      indeg.set(w, indeg.get(w)! - 1);
      if (indeg.get(w) === 0) queue.push(w);
    }
  }

  // 3. Order within layers: service band above data band; barycenter sweeps inside a band.
  const maxLayer = Math.max(0, ...layer.values());
  const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const id of ids) layers[layer.get(id)!].push(id);
  const bandRank = (id: string) => (band.get(id) === "data" ? 1 : 0);
  const pos = new Map<string, number>();
  for (const l of layers) {
    l.sort((a, b) => bandRank(a) - bandRank(b) || a.localeCompare(b));
    l.forEach((id, i) => pos.set(id, i));
  }
  const reorder = (l: string[], neighbours: Map<string, string[]>) => {
    const bc = new Map<string, number>();
    for (const id of l) {
      const ns = neighbours.get(id)!;
      bc.set(id, ns.length ? ns.reduce((acc, n) => acc + pos.get(n)!, 0) / ns.length : pos.get(id)!);
    }
    l.sort(
      (a, b) =>
        bandRank(a) - bandRank(b) || bc.get(a)! - bc.get(b)! || pos.get(a)! - pos.get(b)! || a.localeCompare(b),
    );
    l.forEach((id, i) => pos.set(id, i));
  };
  for (let sweep = 0; sweep < 4; sweep++) {
    for (let i = 1; i < layers.length; i++) reorder(layers[i], dagIn);
    for (let i = layers.length - 2; i >= 0; i--) reorder(layers[i], dagOut);
  }

  // 4. Coordinates: the service band is top-aligned, the data band starts below the tallest service column.
  const maxServices = Math.max(0, ...layers.map((l) => l.filter((id) => bandRank(id) === 0).length));
  const dataTop = maxServices * ROW_H + (maxServices ? BAND_GAP : 0);
  const points = new Map<string, Point>();
  layers.forEach((l, li) => {
    let s = 0;
    let d = 0;
    for (const id of l) {
      const y = bandRank(id) === 0 ? s++ * ROW_H : dataTop + d++ * ROW_H;
      points.set(id, { x: (li + 1) * COL_W, y });
    }
  });

  // 5. Change lane (x = 0): each change beside its target; stacked when several share one.
  const laneStep = ROW_H * 0.75;
  const laneTaken: number[] = [];
  for (const c of [...input.changes].sort((a, b) => a.id.localeCompare(b.id))) {
    const t = points.get(c.target);
    if (!t || points.has(c.id)) continue;
    let y = t.y;
    while (laneTaken.some((u) => Math.abs(u - y) < laneStep - 1)) y += laneStep;
    laneTaken.push(y);
    points.set(c.id, { x: 0, y });
  }
  return points;
}
