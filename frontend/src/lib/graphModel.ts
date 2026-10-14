import type { ChainSet } from "./gate";
import type { GraphResponse } from "./types";

/**
 * Joins /api/graph (the failure-flow graph) with the chains the gate recorded, for the
 * graph view and its text alternative. It decides nothing: roles come from the report /
 * gate runs, edges and capacities from /api/graph. Change nodes (the first chain element,
 * which /api/graph does not include) are attached to the node they changed.
 */

export type Band = "service" | "data" | "change";
export type Role = "cause" | "path" | "symptom" | "rejected" | "rejected-target" | "rejected-path";
export type EdgeKind = "service" | "data" | "cross" | "change" | "hop";

export interface ModelNode {
  id: string;
  label: string;
  tier: number | null;
  band: Band;
  roles: Role[];
  /** 0-based position on the proof chain, when on it. */
  step: number | null;
  /** Not in /api/graph: added from a recorded chain. */
  synthetic: boolean;
  /** Capacity (< 1) of this node's outgoing hop on a recorded chain: the flow bottleneck. */
  outCap: { cap: number; to: string; rejected: boolean } | null;
  /** Betweenness centrality from /api/graph (null when the backend did not compute it). */
  betweenness: number | null;
}

export interface ModelEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  cap: number | null;
  /** 0-based index of this hop on the proof chain. */
  proofStep: number | null;
  rejected: boolean;
  synthetic: boolean;
}

export interface ChainStep {
  from: string;
  to: string;
  kind: EdgeKind;
  cap: number | null;
  inGraph: boolean;
}

export interface ChainView {
  kind: "proof" | "rejected";
  cause: string;
  nodes: string[];
  steps: ChainStep[];
  note: string;
}

export interface GraphModel {
  nodes: ModelNode[];
  edges: ModelEdge[];
  chains: ChainView[];
  changes: { id: string; target: string }[];
}

const DATA_LABELS = new Set(["Table", "KPI", "Dashboard", "Column", "Dataset", "Metric"]);

export function bandOf(label: string): Band {
  if (label === "Deploy" || label === "Change") return "change";
  return DATA_LABELS.has(label) ? "data" : "service";
}

const edgeId = (s: string, t: string) => `${s}->${t}`;

export function buildGraphModel(
  g: GraphResponse,
  chains: ChainSet,
  symptoms: string[],
  rejectionNotes: Map<string, string>,
): GraphModel {
  const nodes = new Map<string, ModelNode>();
  for (const n of g.nodes) {
    nodes.set(n.id, {
      id: n.id,
      label: n.label,
      tier: n.tier,
      band: bandOf(n.label),
      roles: [],
      step: null,
      synthetic: false,
      outCap: null,
      betweenness: typeof n.betweenness === "number" ? n.betweenness : null,
    });
  }
  const edges = new Map<string, ModelEdge>();
  for (const e of g.edges) {
    const kind: EdgeKind = e.domain === "data" || e.domain === "cross" ? e.domain : "service";
    edges.set(edgeId(e.source, e.target), {
      id: edgeId(e.source, e.target),
      source: e.source,
      target: e.target,
      kind,
      cap: e.cap,
      proofStep: null,
      rejected: false,
      synthetic: false,
    });
  }

  const changes: { id: string; target: string }[] = [];
  const addRole = (id: string, r: Role) => {
    const n = nodes.get(id);
    if (n && !n.roles.includes(r)) n.roles.push(r);
  };

  const ensureChainNodes = (chain: string[]) => {
    chain.forEach((id, i) => {
      if (nodes.has(id)) return;
      const isChange = i === 0;
      nodes.set(id, {
        id,
        label: isChange ? "Deploy" : "not in failure-flow view",
        tier: null,
        band: isChange ? "change" : "service",
        roles: [],
        step: null,
        synthetic: true,
        outCap: null,
        betweenness: null,
      });
      if (isChange && chain.length > 1) changes.push({ id, target: chain[1] });
    });
  };

  const chainSteps = (chain: string[]): ChainStep[] =>
    chain.slice(1).map((to, i) => {
      const from = chain[i];
      const e = edges.get(edgeId(from, to));
      const fromNode = nodes.get(from);
      return e
        ? { from, to, kind: e.kind, cap: e.cap, inGraph: true }
        : { from, to, kind: fromNode?.band === "change" ? "change" : "hop", cap: null, inGraph: false };
    });

  const ensureEdges = (steps: ChainStep[]) => {
    for (const s of steps) {
      const id = edgeId(s.from, s.to);
      if (!edges.has(id)) {
        edges.set(id, { id, source: s.from, target: s.to, kind: s.kind, cap: null, proofStep: null, rejected: false, synthetic: true });
      }
    }
  };

  const views: ChainView[] = [];
  if (chains.proof) {
    const c = chains.proof.chain;
    ensureChainNodes(c);
    const steps = chainSteps(c);
    ensureEdges(steps);
    c.forEach((id, i) => {
      const n = nodes.get(id)!;
      n.step = i;
      addRole(id, i === 0 ? "cause" : "path");
    });
    steps.forEach((s, i) => (edges.get(edgeId(s.from, s.to))!.proofStep = i));
    views.push({
      kind: "proof",
      cause: chains.proof.cause,
      nodes: c,
      steps,
      note: chains.proof.source === "report" ? "proven mechanism (report)" : "accepted G2 chain (gate run)",
    });
  }
  for (const r of chains.rejected) {
    addRole(r.cause, "rejected");
    if (!r.chain) {
      views.push({ kind: "rejected", cause: r.cause, nodes: [r.cause], steps: [], note: rejectionNotes.get(r.cause) ?? "rejected" });
      continue;
    }
    ensureChainNodes(r.chain);
    addRole(r.cause, "rejected");
    if (r.chain.length > 1) addRole(r.chain[1], "rejected-target");
    r.chain.slice(2).forEach((id) => addRole(id, "rejected-path"));
    const steps = chainSteps(r.chain);
    ensureEdges(steps);
    for (const s of steps) {
      const e = edges.get(edgeId(s.from, s.to))!;
      if (e.proofStep === null) e.rejected = true;
    }
    views.push({ kind: "rejected", cause: r.cause, nodes: r.chain, steps, note: rejectionNotes.get(r.cause) ?? "rejected" });
  }
  for (const s of symptoms) addRole(s, "symptom");

  // Bottlenecks: a chain hop that carries less than the whole flow is labelled on its source node.
  for (const v of views) {
    for (const st of v.steps) {
      if (st.cap === null || st.cap >= 1) continue;
      const n = nodes.get(st.from);
      if (n && (!n.outCap || st.cap < n.outCap.cap)) n.outCap = { cap: st.cap, to: st.to, rejected: v.kind === "rejected" };
    }
  }

  return {
    nodes: [...nodes.values()].sort((a, b) => a.id.localeCompare(b.id)),
    edges: [...edges.values()].sort((a, b) => a.id.localeCompare(b.id)),
    chains: views,
    changes,
  };
}
