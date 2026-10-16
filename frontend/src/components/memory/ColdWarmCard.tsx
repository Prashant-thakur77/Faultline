"use client";

import { CircleCheck, CircleX, Snowflake, Sun } from "lucide-react";
import { evalValue, useEvalSummary, type EvalSummaryState } from "@/hooks/useEvalSummary";
import { StatusChip } from "@/components/StatusChip";

interface Pair {
  label: string;
  scenario: string;
  cold: string;
  warm: string;
  checks: { key: string; text: string }[];
}

const PAIRS: Pair[] = [
  {
    label: "S1b after S1 (fix: feature flag)",
    scenario: "memory",
    cold: "memory.cold_prior",
    warm: "memory.warm_prior",
    checks: [
      { key: "memory.gate_verdicts_identical", text: "gate verdicts identical cold vs warm" },
      { key: "memory.warm_top_precedent_is_s1", text: "warm: top precedent is the resolved S1" },
      { key: "memory.derived_runbook_first", text: "warm: the derived runbook comes first" },
    ],
  },
  {
    label: "S3b after S3 (fix: rollback)",
    scenario: "memory.s3b",
    cold: "memory.s3b.cold_prior",
    warm: "memory.s3b.warm_prior",
    checks: [
      { key: "memory.s3b.gate_verdicts_identical", text: "gate verdicts identical cold vs warm" },
      { key: "memory.s3b.warm_top_precedent_is_first", text: "warm: top precedent is the resolved S3" },
    ],
  },
];

function num(s: EvalSummaryState, k: string): number | null {
  const v = evalValue(s, k);
  return typeof v === "number" ? v : null;
}

/**
 * Cold vs warm ("from RESULTS"): the same scenario run on a graph without and
 * with the earlier incident written back. Numbers are copied verbatim from
 * evals/results/latest.json (public/evals/summary.json); bars are drawn from those values and each
 * bar also states its value in text. The gate's verdict must not change; memory only changes the prior.
 */
export function ColdWarmCard() {
  const s = useEvalSummary();
  return (
    <section aria-labelledby="coldwarm-h" className="space-y-2 fl-card rounded-2xl px-5 py-4">
      <h2 id="coldwarm-h" className="text-sm font-semibold text-zinc-50">
        Cold vs warm (from the last eval)
      </h2>
      <p className="text-xs text-zinc-400">
        Family prior on the cause&apos;s component when the same kind of incident comes back, without (cold) and with (warm) the
        earlier one written back. Memory may raise the prior; it never changes the gate&apos;s verdict.
      </p>
      {s.state === "loading" ? <p className="text-xs text-zinc-300">Loading eval results…</p> : null}
      {s.state === "error" ? (
        <p role="alert" className="text-xs text-red-300">
          Eval results unavailable: {s.error}
        </p>
      ) : null}
      {s.state === "ok" ? (
        <>
          {PAIRS.map((p) => {
            const cold = num(s, p.cold);
            const warm = num(s, p.warm);
            const trials = num(s, `${p.scenario}.trials`);
            return (
              <div key={p.label} className="space-y-1 rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
                <p className="text-xs font-medium text-zinc-100">
                  {p.label}
                  {trials !== null ? <span className="font-normal text-zinc-400"> · {trials} trials</span> : null}
                </p>
                <Bar icon={Snowflake} label="cold" value={cold} cls="bg-sky-400" />
                <Bar icon={Sun} label="warm" value={warm} cls="bg-amber-300" />
                <ul className="flex flex-wrap gap-1 pt-0.5">
                  {p.checks.map((c) => {
                    const v = evalValue(s, c.key);
                    return (
                      <li key={c.key}>
                        {v === null ? (
                          <StatusChip tone="na">{c.text}: not in this eval</StatusChip>
                        ) : v === true ? (
                          <StatusChip tone="pass" icon={CircleCheck}>
                            {c.text}
                          </StatusChip>
                        ) : (
                          <StatusChip tone="fail" icon={CircleX}>
                            {c.text}: no
                          </StatusChip>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
          <p className="text-[11px] text-zinc-400">
            Source: <span className="font-mono">{s.summary.source}</span> ({s.summary.run ?? "run unknown"}). Tool calls cold → warm:{" "}
            {String(evalValue(s, "memory.cold_tool_calls") ?? "–")} → {String(evalValue(s, "memory.warm_tool_calls") ?? "–")}.
          </p>
        </>
      ) : null}
    </section>
  );
}

function Bar({ icon: Icon, label, value, cls }: { icon: typeof Sun; label: string; value: number | null; cls: string }) {
  const pct = value === null ? 0 : Math.max(0, Math.min(100, value * 100));
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="flex w-14 items-center gap-1 text-zinc-300">
        <Icon aria-hidden className="size-3.5" />
        {label}
      </span>
      <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800" aria-hidden>
        <div className={`h-full rounded ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-14 text-right font-mono text-zinc-100">{value === null ? "–" : value.toFixed(4)}</span>
    </div>
  );
}
