"use client";

import { useEffect, useState } from "react";
import { BASE_PATH } from "@/lib/site";
import type { EvalSummary } from "@/lib/types";

export type EvalSummaryState =
  | { state: "loading" }
  | { state: "ok"; summary: EvalSummary }
  | { state: "error"; error: string };

let cached: Promise<EvalSummary> | null = null;

function load(): Promise<EvalSummary> {
  cached ??= fetch(`${BASE_PATH}/evals/summary.json`, { cache: "no-store" }).then(async (r) => {
    if (!r.ok) throw new Error(`evals/summary.json: HTTP ${r.status}`);
    return (await r.json()) as EvalSummary;
  });
  cached.catch(() => {
    cached = null; // a failed load is retried next time, never remembered as "no results"
  });
  return cached;
}

/** Test hook: forget the loaded summary. */
export function resetEvalSummaryCache(): void {
  cached = null;
}

/**
 * The eval numbers the UI quotes (public/evals/summary.json, copied verbatim from
 * evals/results/latest.json by `npm run evals:summary`). Static, so it works on the replay site too.
 * Missing file = an explicit error state; nothing is filled in.
 */
export function useEvalSummary(): EvalSummaryState {
  const [s, setS] = useState<EvalSummaryState>({ state: "loading" });
  useEffect(() => {
    let alive = true;
    load()
      .then((summary) => alive && setS({ state: "ok", summary }))
      .catch((e: unknown) => alive && setS({ state: "error", error: e instanceof Error ? e.message : String(e) }));
    return () => {
      alive = false;
    };
  }, []);
  return s;
}

/** A value from the summary, or null when it is absent (callers render "–", never a guess). */
export function evalValue(s: EvalSummaryState, key: string): number | boolean | string | null {
  return s.state === "ok" ? (s.summary.values[key] ?? null) : null;
}
