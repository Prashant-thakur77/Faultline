import { specialistName } from "./crew";
import type { CrewMember, ProvenanceEdge, ProvenanceNode, ProvenanceResponse } from "./types";

/**
 * Layered layout for the "why do you believe this?" graph (Q-PROV-1): columns Agent → Call → Evidence → Verdict,
 * with the nodes each call SAW hanging under it. Pure and deterministic: the same payload always yields the same
 * order (payload order breaks every tie), so every demo run looks identical. Nothing is inferred: a node or edge
 * that is not in the payload is never drawn.
 */

/** The three edge kinds drawn as lines (SAW is drawn as chips under the call). */
export type DrawnRel = "MADE" | "PRODUCED_EVIDENCE" | "SUPPORTS";

export const REL_TEXT: Record<DrawnRel | "SAW", { from: string; to: string; what: string }> = {
  MADE: { from: "agent", to: "call", what: "the agent made the tool call" },
  PRODUCED_EVIDENCE: { from: "call", to: "evidence", what: "the call produced the evidence" },
  SUPPORTS: { from: "evidence", to: "verdict", what: "the evidence supports the verdict" },
  SAW: { from: "call", to: "graph node", what: "the call read this graph node" },
};

export interface ProvenanceCallRow {
  call: ProvenanceNode;
  agents: ProvenanceNode[];
  saw: ProvenanceNode[];
}

/** One evidence item as a text-alternative row: who produced it and what it supports. */
export interface ProvenanceRow {
  evidence: ProvenanceNode;
  calls: ProvenanceCallRow[];
  verdicts: ProvenanceNode[];
}

export interface ProvenanceLayout {
  agents: ProvenanceNode[];
  calls: ProvenanceNode[];
  evidence: ProvenanceNode[];
  verdicts: ProvenanceNode[];
  /** call id → the graph nodes it SAW (sorted by label). */
  saw: Map<string, ProvenanceNode[]>;
  /** Drawn edges (MADE, PRODUCED_EVIDENCE, SUPPORTS) whose two ends are both in the layout. */
  edges: (ProvenanceEdge & { rel: DrawnRel })[];
  rows: ProvenanceRow[];
}

const DRAWN = new Set<string>(["MADE", "PRODUCED_EVIDENCE", "SUPPORTS"]);

/** Order `items` by the mean index of their neighbours in an already-ordered column; payload order breaks ties. */
function byBarycenter(
  items: ProvenanceNode[],
  neighbours: (id: string) => string[],
  index: Map<string, number>,
  tie?: (id: string) => number,
): ProvenanceNode[] {
  const pos = new Map(items.map((n, i) => [n.id, i]));
  const key = new Map(items.map((n) => [n.id, mean(neighbours(n.id).map((x) => index.get(x)))]));
  const tieKey = new Map(items.map((n) => [n.id, tie ? tie(n.id) : 0]));
  // nodes with no placed neighbour (Infinity) sink to the end; payload order is the last word
  const cmp = (x: number, y: number) => (x === y ? 0 : x < y ? -1 : 1);
  return [...items].sort(
    (a, b) =>
      cmp(key.get(a.id)!, key.get(b.id)!) ||
      cmp(tieKey.get(a.id)!, tieKey.get(b.id)!) ||
      (pos.get(a.id) ?? 0) - (pos.get(b.id) ?? 0),
  );
}

/** Mean of the defined values; Infinity when there are none. */
function mean(xs: (number | undefined)[]): number {
  const v = xs.filter((x): x is number => x !== undefined);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : Number.POSITIVE_INFINITY;
}

const indexOf = (xs: ProvenanceNode[]) => new Map(xs.map((n, i) => [n.id, i]));

export function layoutProvenance(data: Pick<ProvenanceResponse, "nodes" | "edges">): ProvenanceLayout {
  const kind = (k: string) => data.nodes.filter((n) => n.kind === k);
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const out = new Map<string, ProvenanceEdge[]>();
  const into = new Map<string, ProvenanceEdge[]>();
  for (const e of data.edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    (out.get(e.source) ?? out.set(e.source, []).get(e.source)!).push(e);
    (into.get(e.target) ?? into.set(e.target, []).get(e.target)!).push(e);
  }
  const targets = (id: string, rel: string) => (out.get(id) ?? []).filter((e) => e.rel === rel).map((e) => e.target);
  const sources = (id: string, rel: string) => (into.get(id) ?? []).filter((e) => e.rel === rel).map((e) => e.source);

  const verdicts = kind("verdict");
  // right to left: evidence by the verdict it supports, calls by their evidence, agents by their calls
  let evidence = byBarycenter(kind("evidence"), (id) => targets(id, "SUPPORTS"), indexOf(verdicts));
  let calls = byBarycenter(kind("call"), (id) => targets(id, "PRODUCED_EVIDENCE"), indexOf(evidence));
  const agents = byBarycenter(kind("agent"), (id) => targets(id, "MADE"), indexOf(calls));
  // left to right: calls grouped under their agent (evidence order breaks ties), then evidence follows its calls
  const evIx = indexOf(evidence);
  const evBary = (id: string) => mean(targets(id, "PRODUCED_EVIDENCE").map((x) => evIx.get(x)));
  calls = byBarycenter(calls, (id) => sources(id, "MADE"), indexOf(agents), evBary);
  evidence = byBarycenter(evidence, (id) => sources(id, "PRODUCED_EVIDENCE"), indexOf(calls));

  const saw = new Map<string, ProvenanceNode[]>();
  for (const c of calls) {
    const seen = targets(c.id, "SAW")
      .map((id) => byId.get(id))
      .filter((n): n is ProvenanceNode => !!n)
      .sort((a, b) => a.label.localeCompare(b.label));
    if (seen.length) saw.set(c.id, seen);
  }

  const placed = new Set([...agents, ...calls, ...evidence, ...verdicts].map((n) => n.id));
  const edges = data.edges.filter(
    (e): e is ProvenanceEdge & { rel: DrawnRel } => DRAWN.has(e.rel) && placed.has(e.source) && placed.has(e.target),
  );

  const callIx = indexOf(calls);
  const agentIx = indexOf(agents);
  const rows: ProvenanceRow[] = evidence.map((ev) => ({
    evidence: ev,
    verdicts: targets(ev.id, "SUPPORTS")
      .map((id) => byId.get(id))
      .filter((n): n is ProvenanceNode => !!n),
    calls: sources(ev.id, "PRODUCED_EVIDENCE")
      .map((id) => byId.get(id))
      .filter((n): n is ProvenanceNode => !!n)
      .sort((a, b) => (callIx.get(a.id) ?? 0) - (callIx.get(b.id) ?? 0))
      .map((call) => ({
        call,
        agents: sources(call.id, "MADE")
          .map((id) => byId.get(id))
          .filter((n): n is ProvenanceNode => !!n)
          .sort((a, b) => (agentIx.get(a.id) ?? 0) - (agentIx.get(b.id) ?? 0)),
        saw: saw.get(call.id) ?? [],
      })),
  }));

  return { agents, calls, evidence, verdicts, saw, edges, rows };
}

/** True for the gate's own reads (its checks bypass the crew's ToolBox, so no Task claims them). */
export function isGateAgent(n: ProvenanceNode): boolean {
  return n.task_kind === "gate" || n.id === "agent:gate";
}

/** Display name of an agent: the roster's name for a crew role, "X specialist" for a specialist, else the label. */
export function agentName(n: ProvenanceNode, roster: CrewMember[] = []): string {
  if (isGateAgent(n)) return n.label;
  if (n.task_kind === "specialist") return specialistName(n.label);
  return roster.find((m) => m.key === n.label)?.name ?? n.label;
}

/** What kind of agent it is, in words. */
export function agentKindText(n: ProvenanceNode): string {
  if (isGateAgent(n)) return "gate: reads in code";
  if (n.task_kind === "specialist") return "specialist";
  if (n.task_kind === "crew") return "crew step";
  return n.task_kind ?? "agent";
}

/**
 * Every node on a lineage through `id`: everything upstream of it (against the edges) and everything downstream
 * (along them), never mixing directions, so hovering one evidence lights its calls, their agents and its verdict,
 * not its siblings. Presentation only (which lines to light): the edges themselves come from Q-PROV-1.
 */
export function lineage(id: string, edges: ProvenanceEdge[]): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set([id]);
  const lit = new Set<string>();
  const walk = (start: string, forward: boolean) => {
    const stack = [start];
    const seen = new Set([start]);
    while (stack.length) {
      const cur = stack.pop()!;
      for (const e of edges) {
        const from = forward ? e.source : e.target;
        const to = forward ? e.target : e.source;
        if (from !== cur) continue;
        lit.add(edgeKey(e));
        nodes.add(to);
        if (!seen.has(to)) {
          seen.add(to);
          stack.push(to);
        }
      }
    }
  };
  walk(id, true);
  walk(id, false);
  return { nodes, edges: lit };
}

export function edgeKey(e: ProvenanceEdge): string {
  return `${e.source}|${e.rel}|${e.target}`;
}
