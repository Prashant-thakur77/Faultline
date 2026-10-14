import { BASE_PATH } from "./site";
import { stageWords } from "./format";
import type {
  BlastResponse,
  Crew,
  GateRun,
  GraphResponse,
  Hypothesis,
  IncidentView,
  PlanResponse,
  Report,
  StageRow,
  TemplateInfo,
  ToolCallRow,
} from "./types";

/**
 * Replay data source: a recorded run's static exports under public/replay/<name>/
 * (copied from examples/<name>/ by scripts/export-replay.mjs). Nothing here talks to the
 * API, so replay works with the backend off. A missing required file is an error shown to
 * the user, never replaced by sample data.
 */

/** Recordings that ship with the static build (generateStaticParams). */
export const REPLAY_RUNS = ["s1-hero", "s2-data-incident"] as const;

/** Prefix for the static bundles (the Pages base path, "" in the live build). */
export { BASE_PATH };

export type ReplayEvent =
  | ({ type: "stage" } & StageRow)
  | ({ type: "tool_call" } & ToolCallRow)
  | ({ type: "gate_run" } & GateRun);

export interface ReplayManifest {
  name: string;
  incident: string;
  outcome: string;
  cause: string | null;
  events: number;
  files: string[];
  snapshot: { api: string; at: string; templates: boolean; graph: string | null };
  /** examples/<run>/manifest.json as written by scripts/record_demo.py. */
  recorded?: {
    scenario: string;
    incident: string;
    run: string;
    graph: string;
    final_stage: string;
    github: string;
    investigator: string;
    events: number;
    gate_runs: number;
    tool_calls: number;
  } | null;
}

export interface ReplayBundle {
  name: string;
  manifest: ReplayManifest | null;
  events: ReplayEvent[];
  gateRuns: GateRun[];
  toolCalls: ToolCallRow[];
  hypotheses: Hypothesis[];
  report: Report;
  templates: Record<string, TemplateInfo> | null;
  graph: GraphResponse | null;
  plan: PlanResponse | null;
  blast: BlastResponse | null;
  /** The recorded IncidentView (final state): incident facts such as targets and onset. */
  incident: IncidentView | null;
}

export class ReplayError extends Error {}

async function fetchText(url: string, required: boolean): Promise<string | null> {
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (e) {
    throw new ReplayError(`could not fetch ${url}: ${e instanceof Error ? e.message : String(e)}`);
  }
  if (res.status === 404) {
    if (required) throw new ReplayError(`${url} not found (HTTP 404): this recording is incomplete or does not exist`);
    return null;
  }
  if (!res.ok) throw new ReplayError(`${url}: HTTP ${res.status}`);
  return res.text();
}

async function fetchJson<T>(url: string, required: true): Promise<T>;
async function fetchJson<T>(url: string, required: false): Promise<T | null>;
async function fetchJson<T>(url: string, required: boolean): Promise<T | null> {
  const t = await fetchText(url, required);
  if (t === null) return null;
  try {
    return JSON.parse(t) as T;
  } catch (e) {
    throw new ReplayError(`${url} is not valid JSON: ${e instanceof Error ? e.message : String(e)}`);
  }
}

const KIND_RANK = { stage: 0, tool_call: 1, gate_run: 2 } as const;

export async function loadReplay(name: string): Promise<ReplayBundle> {
  if (!/^[A-Za-z0-9_-]+$/.test(name)) throw new ReplayError(`invalid recording name "${name}"`);
  const base = `${BASE_PATH}/replay/${name}`;
  const [eventsText, gateRuns, toolCalls, hypotheses, report, manifest, templates, graph, plan, blast, incident] = await Promise.all([
    fetchText(`${base}/events.jsonl`, true),
    fetchJson<GateRun[]>(`${base}/gate_runs.json`, true),
    fetchJson<ToolCallRow[]>(`${base}/tool_calls.json`, true),
    fetchJson<Hypothesis[]>(`${base}/hypotheses.json`, true),
    fetchJson<Report>(`${base}/report.json`, true),
    fetchJson<ReplayManifest>(`${base}/manifest.json`, false),
    fetchJson<Record<string, TemplateInfo>>(`${base}/templates.json`, false),
    fetchJson<GraphResponse>(`${base}/graph.json`, false),
    fetchJson<PlanResponse>(`${base}/plan.json`, false),
    fetchJson<BlastResponse>(`${base}/blast.json`, false),
    fetchJson<IncidentView>(`${base}/incident.json`, false),
  ]);
  const raw = (eventsText ?? "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l, i) => {
      try {
        return { e: JSON.parse(l) as ReplayEvent, i };
      } catch {
        throw new ReplayError(`events.jsonl line ${i + 1} is not valid JSON`);
      }
    });
  for (const { e, i } of raw) {
    if (!(e.type in KIND_RANK)) throw new ReplayError(`events.jsonl line ${i + 1}: unknown event type "${String(e.type)}"`);
    if (e.type === "gate_run" && typeof (e as { checks: unknown }).checks === "string") {
      (e as { checks: unknown }).checks = JSON.parse((e as unknown as { checks: string }).checks);
    }
  }
  // Recorded order: by time, then stage before tool call before gate run, then stage ordinal, then file order.
  raw.sort(
    (a, b) =>
      a.e.at - b.e.at ||
      KIND_RANK[a.e.type] - KIND_RANK[b.e.type] ||
      (a.e.type === "stage" && b.e.type === "stage" ? a.e.ord - b.e.ord : 0) ||
      a.i - b.i,
  );
  return {
    name,
    manifest,
    events: raw.map((x) => x.e),
    gateRuns,
    toolCalls,
    hypotheses,
    report,
    templates,
    graph,
    plan,
    blast,
    incident,
  };
}

function strip<T extends { type: string }>(e: T): Omit<T, "type"> {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { type, ...rest } = e;
  return rest;
}

/** The symptoms the confirmation gate checked (recorded G2 params), else the report mechanism's last node. */
export function replayTargets(b: ReplayBundle): string[] {
  if (b.incident?.incident.targets?.length) return b.incident.incident.targets;
  for (const g of b.gateRuns) {
    for (const c of g.checks) {
      const s = c.params?.symptoms;
      if (c.name === "G2 path" && Array.isArray(s) && s.length) return s.map(String);
    }
  }
  return [];
}

/** Stages after which the run has an outcome (the gate decided, or the run ended). */
const OUTCOME_STAGES = new Set(["GATE", "NO_INCIDENT", "UNKNOWN_ESCALATED", "FAILED", "RESOLVED"]);

/**
 * The incident view as it stood after the first `cursor` recorded events. Hypotheses, the
 * report and the outcome appear once the gate's stage event has played (the exports carry no
 * timestamps for them, and the outcome is written at the gate); every other row appears at its
 * recorded position. Incident facts (targets, onset, run, graph) come from incident.json.
 */
export function viewAt(b: ReplayBundle, cursor: number): IncidentView {
  const played = b.events.slice(0, cursor);
  const end = cursor >= b.events.length;
  const gateById = new Map(b.gateRuns.map((g) => [g.id, g]));
  const stages = played.filter((e) => e.type === "stage").map((e) => strip(e) as StageRow);
  const toolCalls = played.filter((e) => e.type === "tool_call").map((e) => strip(e) as ToolCallRow);
  const gateRuns = played
    .filter((e) => e.type === "gate_run")
    .map((e) => gateById.get(e.id) ?? (strip(e) as GateRun));
  const decided = end || stages.some((x) => OUTCOME_STAGES.has(x.stage));
  const lastStage = stages.at(-1)?.stage ?? "–";
  const rec = b.incident;
  const runId = rec?.run.run ?? stages[0]?.id.split("-se-")[0] ?? b.manifest?.incident ?? b.name;
  return {
    incident: {
      id: rec?.incident.id ?? b.report.incident_id,
      title: rec?.incident.title ?? b.name,
      stage: lastStage,
      onset_at: rec?.incident.onset_at ?? Number.NaN,
      opened_at: rec?.incident.opened_at ?? b.events[0]?.at ?? Number.NaN,
      confident: decided ? b.report.confident : false,
      targets: replayTargets(b),
      kinds: rec?.incident.kinds ?? [],
    },
    run: {
      run: runId,
      graph: rec?.run.graph ?? b.manifest?.recorded?.graph ?? "–",
      scenario: rec?.run.scenario ?? b.name,
      outcome: decided ? b.report.outcome : "RUNNING",
      cause: decided ? b.report.cause_id : null,
      investigator: rec?.run.investigator ?? b.manifest?.recorded?.investigator ?? "–",
    },
    stages,
    tool_calls: toolCalls,
    hypotheses: decided ? b.hypotheses : [],
    gate_runs: gateRuns,
    report: decided ? b.report : undefined,
    ...(rec?.crew ? { crew: crewAt(rec.crew, played, end) } : {}),
  };
}

/** The recorded crew as it stood at the cursor: steps claimed by the last played event's time (all at the end). */
function crewAt(crew: Crew, played: ReplayEvent[], end: boolean): Crew {
  if (end) return crew;
  const now = played.reduce((m, e) => (Number.isFinite(e.at) ? Math.max(m, e.at) : m), Number.NEGATIVE_INFINITY);
  return { ...crew, steps: crew.steps.filter((s) => typeof s.claimed_at === "number" && s.claimed_at <= now) };
}

/**
 * The recorded plan (plan.json, final state) revealed as the playback reaches it: each plan
 * item once its tool call has played, memory after RECALL, options at AWAITING_APPROVAL, and
 * the action's status / PR / verdict / channels only once EXECUTE / VERIFY / WRITEBACK played.
 */
export function planAt(b: ReplayBundle, view: IncidentView): PlanResponse | null {
  const p = b.plan;
  if (!p) return null;
  const tcIds = new Set(view.tool_calls.map((t) => t.id));
  const seen = new Set(view.stages.map((x) => x.stage));
  const item = <T,>(x: T & { id: string } | null): T | null => (x && tcIds.has(x.id) ? x : null);
  const executed = seen.has("EXECUTE");
  const verified = seen.has("WRITEBACK") || seen.has("RESOLVED") || seen.has("UNKNOWN_ESCALATED");
  return {
    ...p,
    stage: view.incident.stage,
    containment_cut: item(p.containment_cut),
    whatif: item(p.whatif),
    who_fixes: item(p.who_fixes),
    bus_factor: item(p.bus_factor),
    escalation_tree: item(p.escalation_tree),
    // Recordings older than M12 have no such keys: keep them undefined so the panels say "not in this recording".
    ...(p.notify_set !== undefined ? { notify_set: item(p.notify_set) } : {}),
    ...(p.owner_at !== undefined ? { owner_at: item(p.owner_at) } : {}),
    memory: seen.has("RECALL") ? (p.memory ?? null) : null,
    options: seen.has("AWAITING_APPROVAL")
      ? p.options.map((o) => {
          if (o.status !== "approved" && o.status !== "executed" && o.status !== "failed") return o;
          if (!executed) return { ...o, status: "option", verdict: null, explanation: null, channels: null, external_ref: null, approval_id: null };
          if (!verified) return { ...o, status: "approved", verdict: null, explanation: null, channels: null };
          return o;
        })
      : [],
  };
}

/** blast.json once the BLAST stage has played. */
export function blastAt(b: ReplayBundle, view: IncidentView): BlastResponse | null {
  return b.blast && view.stages.some((x) => x.stage === "BLAST") ? b.blast : null;
}

export function describeEvent(e: ReplayEvent): string {
  if (e.type === "stage") return `Stage ${stageWords(e.stage)}${e.note ? `: ${e.note}` : ""}`;
  if (e.type === "gate_run") return `Gate run for ${e.cause}: ${e.passed ? "passed" : "rejected"} (${e.origin})`;
  return `Tool call ${e.tool}${e.summary ? `: ${e.summary}` : ""}`;
}
