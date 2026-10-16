/**
 * The /explainer storyboard: nine scenes, each one real query or engine feature, its file, and a
 * one-line caption. Captions quote numbers only through `V` (public/evals/summary.json, copied verbatim from
 * evals/results/latest.json) or the graph-stats export; a missing value renders as "–", never as a guess.
 */

export type Values = Record<string, number | boolean | string | null>;

/** The engine's own per-type edge counts (public/explainer/graph-stats.json, from db.meta.stats via GRAPH_SCHEMA.md). */
export type GraphStats = {
  source: string;
  graph: string;
  engine: string | null;
  nodes: number;
  edges: number;
  rel_types_with_edges: number;
  rel_types: { type: string; lifecycle: string; edges: number }[];
  /** algo.* names resolved by smoke on the pinned engine (graph/algo/resolved.json) */
  algorithms?: string[];
  algorithms_engine?: string | null;
};

/** A query chip. `template` opens the Cypher panel on the recording's exported template; `params` picks the recorded call. */
export type Chip = { query: string; file: string; template?: string; params?: Record<string, string> };
export type Scene = {
  id: string;
  title: string;
  /** seconds when auto-played */
  duration: number;
  chips: Chip[];
  caption: (v: Values, s: GraphStats | null) => string;
};

/** A summary value as text, or "–" when absent (never a guess). */
export const fmt = (v: Values, k: string): string => {
  const x = v[k];
  return x === null || x === undefined ? "–" : String(x);
};

/** The share of an N x N adjacency matrix that holds no edge, from the engine's counts; null when unknown. */
export function emptyShare(edges: number | undefined, nodes: number | undefined): number | null {
  if (!edges || !nodes) return null;
  return 1 - edges / (nodes * nodes);
}

/** "99.9987%": digits up to the first one that is not a 9 (the point is how empty the matrix is). */
export function pct(x: number | null): string {
  if (x === null) return "–";
  const p = x * 100;
  for (let d = 1; d <= 8; d++) {
    const s = p.toFixed(d);
    if (Number(s) < 100 && !/^99\.9*$/.test(s)) return `${s}%`;
  }
  return `${p.toFixed(8)}%`;
}

const relEdges = (s: GraphStats | null, t: string) => s?.rel_types.find((r) => r.type === t)?.edges;

export const SCENES: Scene[] = [
  {
    id: "tenant", title: "One graph per tenant", duration: 7,
    chips: [{ query: "GRAPH.COPY golden_acme → tenant_acme", file: "graph/tenant.py" }, { query: "ACL user per tenant", file: "deploy/users.acl.template" }],
    caption: (_v, s) =>
      `Alerts, deploys, warehouse lineage, docs and people stream into one FalkorDB graph per tenant${s ? `: ${s.graph} holds ${s.nodes.toLocaleString("en-US")} nodes and ${s.edges.toLocaleString("en-US")} edges` : ""}.`,
  },
  {
    id: "matrices", title: "Sparse matrices underneath", duration: 8.5,
    chips: [{ query: "CALL db.meta.stats()", file: "templates/schema_stats.cypher" }],
    caption: (_v, s) => {
      const n = s?.nodes;
      return `FalkorDB stores each relationship type as a sparse adjacency matrix and traverses by matrix multiplication. `
        + `PROPAGATES_TO has ${relEdges(s, "PROPAGATES_TO") ?? "–"} edges among ${n?.toLocaleString("en-US") ?? "–"} nodes: `
        + `${pct(emptyShare(relEdges(s, "PROPAGATES_TO"), n))} of its matrix is empty.`;
    },
  },
  {
    id: "blast", title: "The blast radius", duration: 6,
    chips: [{ query: "CALL algo.BFS(s, 8, 'PROPAGATES_TO')", file: "templates/blast_radius.cypher", template: "Q-BLAST-1", params: { id: "checkout" } }],
    caption: (v) =>
      `Checkout pages. algo.BFS spreads from it over the failure-flow edges, one hop at a time: that frontier is the blast radius (Q-BLAST-1, ${fmt(v, "profile.Q-BLAST-1.engine_ms_p50")} ms engine p50).`,
  },
  {
    id: "path", title: "No path, no claim", duration: 8,
    chips: [{ query: "CALL algo.SPpaths({sourceNode: c, targetNode: s, …})", file: "templates/gate_path.cypher", template: "Q-GATE-1", params: { cause: "D-rec-12", symptom: "checkout" } }],
    caption: (v) =>
      `Three deploys landed in the window. From D-rec-12, algo.SPpaths finds no path to checkout: 0 rows, so it cannot be blamed. `
      + `${fmt(v, "s1.chain")} lights up (G2, ${fmt(v, "profile.Q-GATE-1.engine_ms_p50")} ms engine p50).`,
  },
  {
    id: "flow", title: "Can it carry the impact?", duration: 8,
    chips: [{ query: "CALL algo.maxFlow({sourceNodes, targetNodes, capacityProperty: 'cap'})", file: "templates/gate_flow.cypher", template: "Q-GATE-3" }],
    caption: (v) =>
      `A path is not enough. Edges become pipes sized by capacity: the email deploy's max flow is ${fmt(v, "s1.D-email-88.max_flow")}, `
      + `the outage needs ${fmt(v, "s1.D-email-88.needed")}. Rejected by G5; the payment pipe runs full.`,
  },
  {
    id: "cut", title: "Contain it on a copy", duration: 8,
    chips: [{ query: "algo.maxFlow → edgeFlows → min-cut", file: "templates/cut_flow.cypher", template: "Q-CUT-1" }, { query: "GRAPH.COPY → what-if branch", file: "graph/copy.py", template: "Q-WHATIF-1" }],
    caption: (v) =>
      `The smallest set of edges that contains the failure is the min-cut, read from max-flow's edge flows (${fmt(v, "profile.Q-CUT-1.engine_ms_p50")} ms). `
      + `It is tried first on a GRAPH.COPY branch (${fmt(v, "scale.1k.copy_ms")} ms for ${fmt(v, "scale.1k.nodes")} nodes): the protected services are no longer reached.`,
  },
  {
    id: "who", title: "Who fixes it", duration: 6.5,
    chips: [{ query: "CALL algo.HarmonicCentrality({relationshipTypes: ['KNOWS_ABOUT']})", file: "templates/harmonic.cypher", template: "Q-ORG-HARM" }, { query: "CALL algo.MSF({objective: 'maximize'})", file: "templates/msf.cypher", template: "Q-ORG-MSF" }],
    caption: () =>
      "People close to the payment code and its past fixes rank by harmonic centrality; the top responder steps forward, and a maximum spanning forest draws the escalation chain.",
  },
  {
    id: "readonly", title: "Read-only by design", duration: 7,
    chips: [{ query: "GRAPH.RO_QUERY … TIMEOUT · LIMIT", file: "graph/ro.py" }, { query: "W_WB_1 (one atomic write)", file: "graph/writes.py" }],
    caption: (v) =>
      `The model can only point. Every read is GRAPH.RO_QUERY with a timeout and a LIMIT; after approval one atomic query writes the decision back, `
      + `and a separate read-only connection re-reads it: ${fmt(v, "s1.writeback")}.`,
  },
  {
    id: "unplug", title: "Switch FalkorDB off", duration: 9.5,
    chips: [{ query: "FAULTLINE_DISABLE_GRAPH=true (arm A4)", file: "evals/ladder.py" }],
    caption: (v) =>
      `Switch FalkorDB off and it refuses to confirm anything: no graph, no claim. Remove algo.SPpaths and algo.maxFlow together and the right cause `
      + `falls from ${fmt(v, "ladder.full.b.right_cause")} to ${fmt(v, "ladder.neither.b.right_cause")} of ${fmt(v, "ladder.full.b.confirm_cases")} cases. `
      + `Faultline calls every algo.* procedure the pinned engine ships, ${fmt(v, "repo.algorithms")} of them, and each changes a decision. No path, no claim.`,
  },
];

export const DURATIONS = SCENES.map((s) => s.duration);
export const TOTAL = DURATIONS.reduce((a, b) => a + b, 0);
