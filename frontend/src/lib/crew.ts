import { checkState, sortChecks } from "./gate";
import type { Crew, CrewMember, CrewStep, GateCheck, GateRun } from "./types";

/**
 * Presentation helpers for the crew board. They only reorder and group what Q-CREW-1 returned
 * (hand-off order follows the recorded NEXT edges); every value shown comes from the payload.
 */

export interface CrewLane {
  step: CrewStep;
  member: CrewMember | null;
  /** Roster names of the steps this one handed to (its NEXT edges), in lane order. */
  handsTo: string[];
  /** Specialist work items dispatched from this lane (the lead's), in claim order. */
  specialists: CrewStep[];
}

export interface CrewBoardModel {
  lanes: CrewLane[];
  /** Specialist items with no lead step to hang them on (shown on their own, never dropped). */
  loose: CrewStep[];
  /** Earliest claim in the run (offsets are shown from it); null when nothing has a timestamp. */
  t0: number | null;
}

const num = (x: number | null | undefined): x is number => typeof x === "number" && Number.isFinite(x);

function byClaim(a: CrewStep, b: CrewStep): number {
  const ca = num(a.claimed_at) ? a.claimed_at : Number.POSITIVE_INFINITY;
  const cb = num(b.claimed_at) ? b.claimed_at : Number.POSITIVE_INFINITY;
  if (ca !== cb) return ca < cb ? -1 : 1;
  return a.task.localeCompare(b.task);
}

/** Crew steps in hand-off order: a topological walk of the `after` (NEXT) edges, ties and orphans by claimed_at. */
export function handoffOrder(steps: CrewStep[]): CrewStep[] {
  const ids = new Set(steps.map((s) => s.task));
  const indeg = new Map<string, number>();
  const children = new Map<string, CrewStep[]>();
  for (const s of steps) {
    const preds = [...new Set(s.after ?? [])].filter((p) => ids.has(p) && p !== s.task);
    indeg.set(s.task, preds.length);
    for (const p of preds) children.set(p, [...(children.get(p) ?? []), s]);
  }
  const ready = steps.filter((s) => indeg.get(s.task) === 0);
  const out: CrewStep[] = [];
  const placed = new Set<string>();
  while (ready.length) {
    ready.sort(byClaim);
    const s = ready.shift()!;
    out.push(s);
    placed.add(s.task);
    for (const c of children.get(s.task) ?? []) {
      const d = (indeg.get(c.task) ?? 0) - 1;
      indeg.set(c.task, d);
      if (d === 0) ready.push(c);
    }
  }
  // A cycle in the recorded edges (should not happen): keep every step, by claim time.
  return [...out, ...steps.filter((s) => !placed.has(s.task)).sort(byClaim)];
}

export function crewBoard(crew: Crew): CrewBoardModel {
  const roster = new Map(crew.roster.map((m) => [m.key, m]));
  const crewSteps = handoffOrder(crew.steps.filter((s) => s.kind !== "specialist"));
  const specs = crew.steps.filter((s) => s.kind === "specialist").sort(byClaim);
  const leads = crewSteps.filter((s) => s.role === "lead");

  const dispatched = new Map<string, CrewStep[]>();
  const loose: CrewStep[] = [];
  for (const sp of specs) {
    // the latest lead step claimed at or before the specialist (a re-dispatch hangs on its own lead step)
    const lead =
      [...leads].reverse().find((l) => num(l.claimed_at) && num(sp.claimed_at) && l.claimed_at <= sp.claimed_at) ??
      leads[0];
    if (lead) dispatched.set(lead.task, [...(dispatched.get(lead.task) ?? []), sp]);
    else loose.push(sp);
  }

  const lanes = crewSteps.map((step) => ({
    step,
    member: roster.get(step.role) ?? null,
    handsTo: crewSteps
      .filter((n) => (n.after ?? []).includes(step.task))
      .map((n) => roster.get(n.role)?.name ?? n.role),
    specialists: dispatched.get(step.task) ?? [],
  }));
  const times = crew.steps.map((s) => s.claimed_at).filter(num);
  return { lanes, loose, t0: times.length ? Math.min(...times) : null };
}

/** done_at − claimed_at, or null while either is missing. */
export function durationMs(s: CrewStep): number | null {
  return num(s.claimed_at) && num(s.done_at) ? Math.max(0, s.done_at - s.claimed_at) : null;
}

export function fmtDuration(ms: number | null): string {
  if (ms === null) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

/** Display name of a specialist role key ("topology" → "Topology specialist"). */
export function specialistName(role: string): string {
  return `${role.charAt(0).toUpperCase()}${role.slice(1)} specialist`;
}

export type LaneState = "done" | "failed" | "running" | "other";

export function laneState(s: CrewStep): LaneState {
  const v = (s.state ?? "").toLowerCase();
  if (v === "done") return "done";
  if (v === "failed" || v === "error") return "failed";
  if (v === "running" || v === "claimed" || v === "open") return "running";
  return "other";
}

/** The role badge: what decides inside this role (from the roster's model field). */
export function roleBadge(member: CrewMember | null): string | null {
  if (!member) return null;
  if (member.key === "gatekeeper") return "code: decides";
  if (member.model === "none") return "deterministic";
  if (member.model === "optional") return "model optional";
  return member.model ? `model: ${member.model}` : null;
}

export interface GateLine {
  run: GateRun;
  /** The first failing (blocking) check of a rejected run, in canonical check order. */
  firstFail: GateCheck | null;
  /** Checks of the run that could not be evaluated (passed === null), e.g. G7 with one channel. */
  notEvaluable: GateCheck[];
  /** Downgrade-only checks that failed (the run still passed, with less confidence or a note). */
  downgrades: GateCheck[];
}

/** The incident's gate runs as the Gatekeeper lane shows them, in recorded order. */
export function gateLines(runs: GateRun[]): GateLine[] {
  return [...runs]
    .sort((a, b) => a.at - b.at || a.id.localeCompare(b.id))
    .map((run) => {
      const checks = sortChecks(run.checks);
      const firstFail = run.passed
        ? null
        : (checks.find((c) => checkState(c) === "fail") ?? checks.find((c) => c.passed === false) ?? null);
      return {
        run,
        firstFail,
        notEvaluable: checks.filter((c) => checkState(c) === "na"),
        downgrades: checks.filter((c) => checkState(c) === "downgrade"),
      };
    });
}
