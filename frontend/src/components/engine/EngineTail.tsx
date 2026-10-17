"use client";

import { CircleCheck, CircleX, Pause, PenLine, Play, Zap } from "lucide-react";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { fmtEngineMs, tailRows, type EngineInsight, type RecentQuery } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { EngineVia, UpdatedAgo, useOpenTemplate } from "./bits";

export const TAIL_N = 20;

function clock(ms: number | null): string {
  if (ms === null) return "–";
  return new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Wait / execution / report as one bar (decorative; the numbers are written next to it). */
function SplitBar({ q }: { q: RecentQuery }) {
  const parts = [
    { v: q.waitMs ?? 0, cls: "bg-zinc-400" },
    { v: q.execMs ?? 0, cls: "bg-[var(--fl-iris)]" },
    { v: q.reportMs ?? 0, cls: "bg-sky-400" },
  ];
  const sum = parts.reduce((a, p) => a + p.v, 0);
  return (
    <span aria-hidden className="flex h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-white/[0.06]">
      {sum > 0 ? parts.map((p, i) => (p.v > 0 ? <span key={i} className={p.cls} style={{ width: `${(100 * p.v) / sum}%` }} /> : null)) : null}
    </span>
  );
}

/** "w 0.05 · e 0.07 · r 0.13" (milliseconds): the letters are the legend's; screen readers hear the words. */
function Split({ q }: { q: RecentQuery }) {
  const n = (v: number | null) => (v === null ? "–" : v < 0.01 ? v.toFixed(3) : v < 10 ? v.toFixed(2) : v.toFixed(1));
  return (
    <span className="font-mono text-[10px] whitespace-nowrap text-zinc-400 tabular-nums">
      <span aria-hidden>w</span>
      <span className="sr-only">wait</span> {n(q.waitMs)} <span aria-hidden>· e</span>
      <span className="sr-only">, execution</span> {n(q.execMs)} <span aria-hidden>· r</span>
      <span className="sr-only">, report</span> {n(q.reportMs)}
      <span className="sr-only"> ms</span>
    </span>
  );
}

/**
 * The newest queries the engine recorded across the tenant's graphs (the server merges the graphs' streams to the
 * millisecond), re-read every few seconds while the tab is visible. Pause freezes the whole page's numbers.
 */
export function LiveTail({
  d,
  tenant,
  paused,
  onPause,
  at,
}: {
  d: EngineInsight;
  tenant: string;
  paused: boolean;
  onPause: (paused: boolean) => void;
  /** When this answer was read (client clock). */
  at: number | null;
}) {
  const open = useOpenTemplate(tenant);
  const rows = tailRows(d, TAIL_N);
  const byId = new Map(d.templates.queries.map((r) => [r.id, r]));
  return (
    <Section
      id="engine-tail"
      title="Live tail"
      via={<EngineVia what="telemetry{graph} stream" />}
      aside={
        <button
          type="button"
          onClick={() => onPause(!paused)}
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-full px-3 text-xs outline-none ring-1 focus-visible:ring-2 focus-visible:ring-sky-400",
            paused ? "bg-amber-500/10 text-amber-100 ring-amber-400/50 hover:bg-amber-500/15" : "text-zinc-200 ring-white/15 hover:bg-white/[0.05]",
          )}
        >
          {paused ? <Play aria-hidden className="size-3.5" /> : <Pause aria-hidden className="size-3.5" />}
          {paused ? "Resume updates" : "Pause updates"}
        </button>
      }
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        The {TAIL_N} newest mapped queries, newest first: total time and its split into wait (queued), execution and report
        (serialising the reply).{" "}
        {paused ? (
          <span className="text-amber-200">
            Paused: these are the numbers as last read{at !== null ? <> (<UpdatedAgo at={at} />)</> : null}.
          </span>
        ) : (
          <>
            Re-read every 5 seconds while this tab is visible{at !== null ? <>; <UpdatedAgo at={at} /></> : null}.
          </>
        )}
      </p>
      <ul aria-label="Split legend" className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-400">
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm bg-zinc-400" /> wait
        </li>
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm bg-[var(--fl-iris)]" /> execution
        </li>
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm bg-sky-400" /> report
        </li>
      </ul>
      {rows.length === 0 ? (
        <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
          No mapped query in the streams yet.
        </p>
      ) : (
        <ol aria-label="Most recent queries, newest first" className="divide-y divide-white/[0.05]">
          {rows.map((q, i) => (
            <li key={`${q.graph}:${q.at}:${q.id}:${i}`} className="py-1.5 text-xs">
              <div className="flex items-center gap-x-2.5">
                <span className="w-[4.75rem] shrink-0 font-mono text-[11px] text-zinc-400 tabular-nums">{clock(q.at)}</span>
                {q.kind === "template" ? (
                  <button
                    type="button"
                    onClick={() => open(q.id, byId.get(q.id) ?? null)}
                    className={cn(QUERY_ID_CLS, "min-w-0 truncate text-sky-300 hover:text-sky-200")}
                    aria-label={`${q.id}: open the Cypher panel for this template`}
                  >
                    {q.id}
                  </button>
                ) : (
                  <span className="inline-flex min-w-0 items-center gap-1 truncate font-mono text-[11px] text-zinc-200">
                    <PenLine aria-hidden className="size-3 shrink-0 text-amber-300" />
                    {q.id}
                  </span>
                )}
                <span className="ml-auto w-16 shrink-0 text-right font-mono text-zinc-100 tabular-nums">{fmtEngineMs(q.totalMs)}</span>
                <SplitBar q={q} />
              </div>
              {/* second line, under the id: which graph's stream, the split in numbers, the flags */}
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 pl-[5.375rem]">
                <span className="min-w-0 max-w-full truncate font-mono text-[11px] text-[var(--fl-subtle)]" title={q.graph}>
                  {q.graph}
                </span>
                <Split q={q} />
                {q.cache ? (
                  <StatusChip tone="pass" icon={Zap}>
                    cached plan
                  </StatusChip>
                ) : null}
                {q.write ? (
                  <StatusChip tone="info" icon={PenLine}>
                    write
                  </StatusChip>
                ) : null}
                {q.timeout ? (
                  <StatusChip tone="fail" icon={CircleX}>
                    timeout
                  </StatusChip>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="mt-2 flex items-center gap-1.5 text-[11px] text-zinc-400">
        <CircleCheck aria-hidden className="size-3.5 text-[var(--fl-subtle)]" />
        Ids and timings only: no query text and no parameters leave the engine reader.
      </p>
    </Section>
  );
}
