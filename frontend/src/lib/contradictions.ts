import type { GateCheck, GateRun, IncidentView } from "./types";

/**
 * Splits the G8 check detail ("violates ADR-012: payment.client.timeout_ms <= 2000 (actual 5000);
 * violates ADR-013: …") into decision chips. Display only: the verdict is the gate's; when a
 * part does not match the recorded format it is shown verbatim.
 */
export interface Violation {
  decision: string;
  key: string;
  op: string;
  expected: string;
  actual: string;
}

/** A reviewer's recorded answer to a contradiction for this change (M15 #3). */
export interface OverrideAnswer {
  verdict: string;
  why: string;
}

/** A contradiction a reviewer marked intentional: not a violation for this change, shown with who and why. */
export interface AcceptedDeviation {
  decision: string;
  fact: string;
  by: string;
  why: string;
}

export type ContradictionPart =
  | {
      parsed: Violation;
      raw: string;
      answer: OverrideAnswer | null;
      accepted?: undefined;
    }
  | {
      parsed: null;
      raw: string;
      answer?: undefined;
      accepted: AcceptedDeviation;
    }
  | { parsed: null; raw: string; answer?: undefined; accepted?: undefined };

const RE =
  /^violates\s+(\S+?):\s+(.+?)\s+(<=|>=|==|!=|<|>|=|in|not in)\s+(.+?)\s+\(actual\s+(.+?)\)(?:\s+\((intentional|accidental|discuss):\s+(.*)\))?$/;
const ACCEPTED =
  /^accepted deviation from\s+(\S+)\s+\((.+?)\):\s+marked intentional by\s+(\S+):\s+(.*)$/;

export function parseContradictions(detail: string): ContradictionPart[] {
  return detail
    .split(/;\s+(?=violates\s|accepted deviation from\s)/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((raw): ContradictionPart => {
      const m = raw.match(RE);
      if (m) {
        return {
          raw,
          parsed: {
            decision: m[1],
            key: m[2],
            op: m[3],
            expected: m[4],
            actual: m[5],
          },
          answer: m[6] ? { verdict: m[6], why: m[7] ?? "" } : null,
        };
      }
      const a = raw.match(ACCEPTED);
      if (a)
        return {
          raw,
          parsed: null,
          accepted: { decision: a[1], fact: a[2], by: a[3], why: a[4] },
        };
      return { raw, parsed: null };
    });
}

/** The G8 check of the accepted cause (confirmation gate preferred), with its gate run. */
export function g8Of(
  view: IncidentView,
): { run: GateRun; check: GateCheck } | null {
  const cause = view.report?.cause_id ?? null;
  const runs = [...view.gate_runs].sort((a, b) => b.at - a.at);
  const pick = (pred: (r: GateRun) => boolean) => {
    for (const r of runs) {
      if (!pred(r)) continue;
      const c = r.checks.find((x) => x.name.startsWith("G8"));
      if (c) return { run: r, check: c };
    }
    return null;
  };
  return (
    pick((r) => r.origin === "confirm" && (!cause || r.cause === cause)) ??
    pick((r) => !cause || r.cause === cause) ??
    null
  );
}
