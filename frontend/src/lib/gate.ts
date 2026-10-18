import type {
  GateCheck,
  GateOrigin,
  GateRun,
  HypothesisStatus,
  IncidentView,
  Outcome,
} from "./types";

/**
 * Presentation helpers for gate runs, outcomes and chains. They only reshape what
 * the API returned (docs/API.md); verdicts are always the backend's.
 */

export type Tone = "pass" | "fail" | "warn" | "na" | "info" | "running";

// ------------------------------------------------------------------ checks

export type CheckState = "pass" | "fail" | "downgrade" | "noted" | "na";

/** "noted": an attach-only check (G8) found something for the plan; it never changes the verdict. */
export function checkState(c: GateCheck): CheckState {
  if (c.passed === null || c.passed === undefined) return "na";
  if (c.passed) return "pass";
  if (c.attach_only) return "noted";
  return c.downgrade_only ? "downgrade" : "fail";
}

export const CHECK_STATE_TEXT: Record<CheckState, string> = {
  pass: "pass",
  fail: "fail",
  downgrade: "downgrade",
  noted: "noted",
  na: "not evaluable",
};

export const CHECK_STATE_TONE: Record<CheckState, Tone> = {
  pass: "pass",
  fail: "fail",
  downgrade: "warn",
  noted: "info",
  na: "na",
};

/** Canonical display order of check names (docs/API.md). Unknown names sort last, stably. */
const CHECK_ORDER = [
  "G1 grounded",
  "G2 path",
  "G3 time",
  "G3 earlier upstream",
  "G4 quantitative",
  "G4 origin",
  "G5 sufficiency",
  "G6 competitors",
  "G6 unresolved",
  "G7 agreement",
  "G7 correlation",
  "G8 contradiction",
];

function checkRank(name: string): number {
  const i = CHECK_ORDER.indexOf(name);
  if (i >= 0) return i;
  if (/^N\d/.test(name)) return 100 + Number(name.slice(1, 2));
  return 200;
}

export function sortChecks(checks: GateCheck[]): GateCheck[] {
  return checks
    .map((c, i) => ({ c, i }))
    .sort((a, b) => checkRank(a.c.name) - checkRank(b.c.name) || a.i - b.i)
    .map((x) => x.c);
}

/** Short gate code ("G5", "N2") from a check name ("G5 sufficiency"). */
export function gateCode(name: string): string {
  return name.split(" ", 1)[0];
}

/** The G1–G8 codes a confirmation run did not record (shown as "not evaluated"). */
export function missingGates(run: GateRun): string[] {
  if (run.origin === "no_incident") return [];
  const seen = new Set(run.checks.map((c) => gateCode(c.name)));
  return ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"].filter((g) => !seen.has(g));
}

export const ORIGIN_TEXT: Record<GateOrigin, string> = {
  sweep: "competitor sweep",
  confirm: "confirmation gate",
  no_incident: "no-incident proof",
};

export function originText(o: string): string {
  return (ORIGIN_TEXT as Record<string, string>)[o] ?? o;
}

// ------------------------------------------------------------------ outcomes and hypotheses

export const OUTCOME_META: Record<Outcome, { tone: Tone; text: string; meaning: string }> = {
  CONFIRMED: {
    tone: "pass",
    text: "Cause confirmed",
    meaning: "the evidence gate passed and is confident about the cause (this says nothing about the fix)",
  },
  NOT_CONFIDENT: {
    tone: "warn",
    text: "Not confident",
    meaning: "gate passed, but a downgrade check failed",
  },
  NO_INCIDENT: { tone: "info", text: "No incident", meaning: "negative proof accepted" },
  UNKNOWN_ESCALATED: {
    tone: "warn",
    text: "Unknown, escalated",
    meaning: "no cause accepted; handed to a human",
  },
  FAILED: { tone: "fail", text: "Failed", meaning: "run error" },
  RUNNING: { tone: "running", text: "Running", meaning: "run in progress" },
};

export function outcomeMeta(o: Outcome | null | undefined) {
  return OUTCOME_META[o ?? "RUNNING"] ?? { tone: "na" as Tone, text: String(o), meaning: "" };
}

export const HYP_META: Record<HypothesisStatus, { tone: Tone; text: string }> = {
  confirmed: { tone: "pass", text: "confirmed" },
  eliminated: { tone: "fail", text: "eliminated" },
  open: { tone: "info", text: "open" },
  unresolved: { tone: "warn", text: "unresolved" },
};

// ------------------------------------------------------------------ chains

const ARROW = " → ";

/** A G2 detail is the chain the gate found, joined by " → ". Anything else is not a chain. */
export function parseChain(detail: string | null | undefined): string[] | null {
  if (!detail || !detail.includes(ARROW)) return null;
  const parts = detail.split(ARROW).map((s) => s.trim());
  return parts.length >= 2 && parts.every((p) => p.length > 0 && !p.includes(" ")) ? parts : null;
}

function passedG2Chain(run: GateRun): string[] | null {
  const g2 = run.checks.find((c) => c.name === "G2 path" && c.passed === true);
  return g2 ? parseChain(g2.detail) : null;
}

export interface RejectionView {
  cause: string;
  origin: GateOrigin;
  gateRunId: string;
  /** Failed (non-downgrade) checks of that gate run, in canonical order. */
  failed: { check: GateCheck | null; text: string }[];
  chain: string[] | null;
}

export interface ChainSet {
  /** The proven mechanism: report.mechanism, or the passed G2 chain of the accepted cause. */
  proof: { cause: string; chain: string[]; source: "report" | "gate" } | null;
  rejected: RejectionView[];
}

export function chainsOf(view: IncidentView): ChainSet {
  const runsById = new Map(view.gate_runs.map((g) => [g.id, g]));
  const chainFor = (cause: string): string[] | null => {
    for (const g of view.gate_runs) {
      if (g.cause !== cause) continue;
      const c = passedG2Chain(g);
      if (c && c[0] === cause) return c;
    }
    return null;
  };

  let proof: ChainSet["proof"] = null;
  const r = view.report;
  if (r && r.mechanism.length >= 2 && r.cause_id) {
    proof = { cause: r.cause_id, chain: r.mechanism, source: "report" };
  } else if (!r) {
    const accepted = [...view.gate_runs]
      .reverse()
      .find((g) => g.origin === "confirm" && g.passed && g.cause !== "NO_INCIDENT");
    const c = accepted ? passedG2Chain(accepted) : null;
    if (accepted && c) proof = { cause: accepted.cause, chain: c, source: "gate" };
  }

  let rejected: RejectionView[];
  if (r) {
    rejected = r.rejected.map((rej) => {
      const run = runsById.get(rej.gate_run);
      const failed = rej.failed.map((text) => {
        const check = run?.checks.find((c) => text.startsWith(`${c.name}:`)) ?? null;
        return { check, text: check ? text.slice(check.name.length + 1).trim() : text };
      });
      return {
        cause: rej.cause,
        origin: rej.origin,
        gateRunId: rej.gate_run,
        failed,
        chain: chainFor(rej.cause),
      };
    });
  } else {
    // No report yet (run still in flight): the failed gate runs recorded so far.
    rejected = view.gate_runs
      .filter((g) => !g.passed && g.cause !== "NO_INCIDENT")
      .map((g) => ({
        cause: g.cause,
        origin: g.origin,
        gateRunId: g.id,
        failed: sortChecks(g.checks)
          .filter((c) => checkState(c) === "fail")
          .map((c) => ({ check: c, text: c.detail })),
        chain: chainFor(g.cause),
      }));
  }
  // Rejections never overlap with the proven cause.
  rejected = rejected.filter((x) => x.cause !== proof?.cause);
  return { proof, rejected };
}

// ------------------------------------------------------------------ abstention (no change explains it)

export interface Abstention {
  /** The inferred upstream origin (a node, not a change); never confirmed by the gate. */
  origin: string;
  /** The chain the GATE note records for it (origin → … → symptom), when present. */
  chain: string[] | null;
  /** The hypothesis reason, verbatim. */
  reason: string | null;
  /** The GATE stage note, verbatim. */
  note: string | null;
}

/**
 * The run abstained: NOT_CONFIDENT with no cause, and an inferred origin recorded as an
 * unresolved code hypothesis ("inferred: …"). Display only; nothing here is a proof.
 */
export function abstentionOf(view: IncidentView): Abstention | null {
  if (view.run.outcome !== "NOT_CONFIDENT" || view.run.cause || view.report?.cause_id) return null;
  const h = view.hypotheses.find((x) => x.status === "unresolved" && (x.reason ?? "").startsWith("inferred:"));
  const gate = [...view.stages].reverse().find((s) => s.stage === "GATE");
  const m = gate?.note.match(/inferred upstream origin (\S+) \(([^)]*)\)/);
  const origin = h?.cause ?? m?.[1] ?? null;
  if (!origin) return null;
  const chain = m && m[1] === origin ? m[2].split("→").map((x) => x.trim()).filter(Boolean) : null;
  return { origin, chain: chain && chain.length >= 2 ? chain : null, reason: h?.reason ?? null, note: gate?.note ?? null };
}
