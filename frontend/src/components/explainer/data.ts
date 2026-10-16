"use client";

import { useEffect, useState } from "react";
import { BASE_PATH } from "@/lib/site";
import type { TemplateInfo } from "@/lib/types";
import type { GraphStats, Values } from "./scenes";

/**
 * Everything the explainer draws, from static exports of FalkorDB results (no API, so it also runs on the replay
 * site): the hero run's failure-flow graph, its blast radius, gate paths, containment cut, what-if branch, who-fixes
 * ranking and escalation tree (public/replay/s1-hero/*, written from the graph by `npm run replay:export`), the eval
 * numbers (public/evals/summary.json) and the engine's per-type edge counts (public/explainer/graph-stats.json).
 * Any missing file is an error the page shows; nothing is filled in.
 */

export type GNode = { id: string; label: string; tier?: number | null; betweenness?: number | null };
export type GEdge = { source: string; target: string; cap?: number; domain?: string };

export type ExplainerData = {
  graphName: string;
  nodes: GNode[];
  edges: GEdge[];
  /** CHANGED: suspect deploy → the component it changed (first hop of its recorded Q-GATE-1 chains) */
  changed: { deploy: string; target: string }[];
  /** recorded Q-GATE-1 calls: cause → symptom, the chain (empty = 0 rows) */
  paths: { cause: string; symptom: string; chain: string[]; ms: number | null }[];
  /** Q-BLAST-1 from the alerting symptom: id → hops */
  blast: { from: string; rows: { id: string; hops: number }[] };
  cut: { u: string; v: string }[];
  failing: string;
  protect: string[];
  branch: string;
  noLongerReached: string[];
  people: { id: string; name: string; score: number }[];
  tree: { from: string; to: string; w: number }[];
  owns: { team: string; ids: string[] }[];
  /** the recording's exported templates (exact Cypher) and its tool calls (params, ms, rows) for the Cypher panel */
  templates: Record<string, TemplateInfo>;
  calls: RecordedCall[];
  values: Values;
  run: string | null;
  stats: GraphStats;
};

export type RecordedCall = { template: string; params: Record<string, unknown>; ms: number | null; rows: number | null; summary: string; evidence: string | null };

export type DataState = { state: "loading" } | { state: "ok"; data: ExplainerData } | { state: "error"; error: string };

const RUN = "s1-hero";
const FILES = {
  graph: `/replay/${RUN}/graph.json`,
  blast: `/replay/${RUN}/blast.json`,
  plan: `/replay/${RUN}/plan.json`,
  calls: `/replay/${RUN}/tool_calls.json`,
  templates: `/replay/${RUN}/templates.json`,
  summary: "/evals/summary.json",
  stats: "/explainer/graph-stats.json",
} as const;

type Json = Record<string, unknown>;
const obj = (x: unknown, what: string): Json => {
  if (!x || typeof x !== "object" || Array.isArray(x)) throw new Error(`${what}: not an object`);
  return x as Json;
};
const arr = (x: unknown, what: string): unknown[] => {
  if (!Array.isArray(x)) throw new Error(`${what}: not a list`);
  return x;
};
const str = (x: unknown, what: string): string => {
  if (typeof x !== "string" || !x) throw new Error(`${what}: missing`);
  return x;
};

async function get(path: string): Promise<unknown> {
  const r = await fetch(`${BASE_PATH}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

/** Turns the six exports into what the scenes draw. Throws (with the file named) on any shape it does not expect. */
export function parseExplainer(raw: Record<keyof typeof FILES, unknown>): ExplainerData {
  const g = obj(raw.graph, "graph.json");
  const nodes = arr(g.nodes, "graph.json nodes") as GNode[];
  const edges = arr(g.edges, "graph.json edges") as GEdge[];
  if (!nodes.length || !edges.length) throw new Error("graph.json: empty graph");

  // Q-GATE-1 calls, as recorded (params may be a JSON string in the export)
  const calls = arr(raw.calls, "tool_calls.json").map((c, i) => obj(c, `tool_calls.json[${i}]`));
  const recorded: RecordedCall[] = calls.filter((c) => typeof c.template === "string").map((c) => ({
    template: c.template as string,
    params: typeof c.params === "string" ? (JSON.parse(c.params) as Record<string, unknown>) : ((c.params as Record<string, unknown>) ?? {}),
    ms: typeof c.ms === "number" ? c.ms : null,
    rows: typeof c.rows === "number" ? c.rows : null,
    summary: String(c.summary ?? ""),
    evidence: typeof c.evidence_id === "string" ? c.evidence_id : null,
  }));
  const paths: ExplainerData["paths"] = [];
  const seen = new Set<string>();
  for (const c of calls) {
    if (c.template !== "Q-GATE-1") continue;
    const p = typeof c.params === "string" ? (JSON.parse(c.params) as Json) : obj(c.params, "Q-GATE-1 params");
    const cause = str(p.cause, "Q-GATE-1 cause");
    const symptom = str(p.symptom, "Q-GATE-1 symptom");
    const key = `${cause}>${symptom}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const rows = Number(c.rows ?? 0);
    const summary = String(c.summary ?? "");
    paths.push({ cause, symptom, chain: rows > 0 ? summary.split(" → ").map((s) => s.trim()) : [], ms: typeof c.ms === "number" ? c.ms : null });
  }
  const changed: ExplainerData["changed"] = [];
  for (const p of paths) {
    if (p.chain.length >= 2 && p.chain[0] === p.cause && !changed.some((c) => c.deploy === p.cause)) changed.push({ deploy: p.cause, target: p.chain[1] });
  }
  if (!changed.length) throw new Error("tool_calls.json: no recorded Q-GATE-1 chains");

  const b = obj(obj(raw.blast, "blast.json").blast, "blast.json blast");
  const from = Object.keys(b)[0];
  if (!from) throw new Error("blast.json: no blast radius");
  const blastRows = arr(obj(b[from], `blast.json ${from}`).rows, "blast.json rows").map((r) => obj(r, "blast row"));

  const plan = obj(raw.plan, "plan.json");
  const cutEv = obj(plan.containment_cut, "plan.json containment_cut");
  const cutPayload = obj(cutEv.payload, "containment_cut payload");
  const cutParams = obj(cutEv.params, "containment_cut params");
  const whatif = obj(obj(plan.whatif, "plan.json whatif").payload, "whatif payload");
  const whatRow = obj(arr(whatif.rows, "whatif rows")[0], "whatif row");
  const who = arr(obj(obj(plan.who_fixes, "plan.json who_fixes").payload, "who_fixes payload").rows, "who_fixes rows").map((r) => obj(r, "who row"));
  const tree = arr(obj(obj(plan.escalation_tree, "plan.json escalation_tree").payload, "escalation payload").rows, "escalation rows").map((r) => obj(r, "tree row"));
  const notify = arr(obj(obj(plan.notify_set, "plan.json notify_set").payload, "notify payload").rows, "notify rows").map((r) => obj(r, "notify row"));
  const ownerAt = obj(obj(plan.owner_at, "plan.json owner_at").payload, "owner_at payload");

  const summary = obj(raw.summary, "summary.json");
  const stats = obj(raw.stats, "graph-stats.json") as unknown as GraphStats;
  if (!Array.isArray(stats.rel_types) || typeof stats.nodes !== "number") throw new Error("graph-stats.json: unexpected shape");

  const owns = notify.map((r) => ({ team: str(r.team, "notify team"), ids: arr(r.owns_impacted ?? [], "owns_impacted").map(String) }));
  const failing = str(cutParams.failing, "containment_cut failing");
  if (typeof ownerAt.owner_now === "string" && !owns.some((o) => o.team === ownerAt.owner_now)) owns.push({ team: ownerAt.owner_now, ids: [failing] });

  return {
    graphName: String(g.graph ?? ""),
    nodes, edges, changed, paths,
    blast: { from, rows: blastRows.map((r) => ({ id: str(r.id, "blast id"), hops: Number(r.hops) })) },
    cut: arr(cutPayload.rows, "containment_cut rows").map((r) => { const o = obj(r, "cut row"); return { u: str(o.u, "cut u"), v: str(o.v, "cut v") }; }),
    failing,
    protect: arr(cutParams.protect, "containment_cut protect").map(String),
    branch: str(whatif.branch, "whatif branch"),
    noLongerReached: arr(whatRow.no_longer_reached ?? [], "no_longer_reached").map(String),
    people: who.map((r) => ({ id: str(r.person, "who person"), name: String(r.name ?? r.person), score: Number(r.score) })),
    tree: tree.map((r) => ({ from: str(r.from, "tree from"), to: str(r.to, "tree to"), w: Number(r.w) })),
    owns,
    templates: obj(raw.templates, "templates.json") as unknown as Record<string, TemplateInfo>,
    calls: recorded,
    values: obj(summary.values, "summary.json values") as Values,
    run: typeof summary.run === "string" ? summary.run : null,
    stats,
  };
}

/** Loads and parses the exports once per mount; an error names the file that failed. */
export function useExplainerData(): DataState {
  const [s, setS] = useState<DataState>({ state: "loading" });
  useEffect(() => {
    let alive = true;
    const keys = Object.keys(FILES) as (keyof typeof FILES)[];
    Promise.all(keys.map((k) => get(FILES[k])))
      .then((vals) => parseExplainer(Object.fromEntries(keys.map((k, i) => [k, vals[i]])) as Record<keyof typeof FILES, unknown>))
      .then((data) => alive && setS({ state: "ok", data }))
      .catch((e: unknown) => alive && setS({ state: "error", error: e instanceof Error ? e.message : String(e) }));
    return () => { alive = false; };
  }, []);
  return s;
}
