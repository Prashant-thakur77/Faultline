"use client";

import { Flag, Hand, Radio, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { fmtMs, fmtOffset } from "@/lib/format";
import { originText } from "@/lib/gate";
import type { StreamState, TimelineItem } from "@/hooks/useIncident";
import type { ToolCallRow } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

const STREAM_CHIP: Record<StreamState, { tone: "pass" | "running" | "info" | "fail" | "na" | "warn"; text: string }> = {
  connecting: { tone: "running", text: "connecting to the stream" },
  live: { tone: "pass", text: "live (SSE)" },
  following: { tone: "running", text: "following the action" },
  awaiting: { tone: "warn", text: "paused: awaiting approval" },
  done: { tone: "info", text: "run finished" },
  recorded: { tone: "na", text: "recorded run" },
  replay: { tone: "info", text: "replay (static files)" },
  idle: { tone: "na", text: "stream idle: polling the view" },
  lost: { tone: "fail", text: "stream unavailable (closed, or over 3 per visitor): polling the view" },
  collected: { tone: "na", text: "run collected: this run's graph was deleted; start a new run" },
};

/** Left column: stages, tool calls and gate runs in graph order (SSE while the run is live). */
export function StageTimeline({
  items,
  stream,
  announcement,
  onOpenToolCall,
  onOpenEvidence,
}: {
  items: TimelineItem[];
  stream: StreamState;
  announcement: string;
  onOpenToolCall: (tc: ToolCallRow) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const base = items.find((i) => i.kind !== "done")?.at ?? 0;
  const chip = STREAM_CHIP[stream];
  const Icon = stream === "live" ? Radio : stream === "awaiting" ? Hand : undefined;
  return (
    <section aria-labelledby="timeline-h" className="flex min-h-0 flex-col">
      <div className="flex items-center gap-2 px-3 pt-3 pb-2">
        <h2 id="timeline-h" className="text-sm font-semibold text-zinc-100">
          Stage timeline
        </h2>
        <StatusChip tone={chip.tone} icon={Icon} className="ml-auto">
          {chip.text}
        </StatusChip>
      </div>
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      {items.length === 0 ? (
        <p className="px-3 text-sm text-zinc-300">No stage events recorded yet for this run.</p>
      ) : (
        <ol className="space-y-1 px-3 pb-4">
          {items.map((it) => (
            <li key={it.key}>
              {it.kind === "stage" ? (
                <div className="mt-2 rounded-md border border-zinc-700 bg-zinc-800/70 px-2 py-1.5">
                  <div className="flex items-center gap-2">
                    <Flag aria-hidden className="size-3.5 text-sky-300" />
                    <span className="font-mono text-xs font-semibold tracking-wide text-zinc-50">{it.row.stage}</span>
                    <span className="ml-auto font-mono text-[11px] text-zinc-400">{fmtOffset(it.at, base)}</span>
                  </div>
                  {it.row.note ? <p className="mt-0.5 text-xs break-words text-zinc-300">{it.row.note}</p> : null}
                </div>
              ) : it.kind === "tool_call" ? (
                <ToolCallItem tc={it.row} offset={fmtOffset(it.at, base)} onOpen={onOpenToolCall} onOpenEvidence={onOpenEvidence} />
              ) : it.kind === "gate_run" ? (
                <div
                  className={cn(
                    "rounded-md border px-2 py-1.5",
                    it.row.passed ? "border-emerald-500/40 bg-emerald-500/5" : "border-red-500/50 bg-red-500/5",
                  )}
                >
                  <div className="flex items-center gap-2 text-xs">
                    {it.row.passed ? (
                      <StatusChip tone="pass" icon={ShieldCheck}>
                        gate passed
                      </StatusChip>
                    ) : (
                      <StatusChip tone="fail" icon={ShieldX}>
                        gate rejected
                      </StatusChip>
                    )}
                    <span className="truncate font-mono text-zinc-100">{it.row.cause}</span>
                    <span className="ml-auto font-mono text-[11px] text-zinc-400">{fmtOffset(it.at, base)}</span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-zinc-300">
                    {originText(it.row.origin)} · {it.row.checks.length} checks
                  </p>
                </div>
              ) : (
                <div className="mt-2 flex items-center gap-2 rounded-md border border-sky-500/40 px-2 py-1.5 text-xs text-sky-200">
                  <Flag aria-hidden className="size-3.5" /> run finished at stage{" "}
                  <span className="font-mono font-semibold">{it.stage}</span>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ToolCallItem({
  tc,
  offset,
  onOpen,
  onOpenEvidence,
}: {
  tc: ToolCallRow;
  offset: string;
  onOpen: (tc: ToolCallRow) => void;
  onOpenEvidence: (id: string) => void;
}) {
  return (
    <div className="rounded-md px-2 py-1 hover:bg-zinc-800/50">
      <div className="flex items-center gap-1.5 text-xs">
        <Wrench aria-hidden className="size-3 shrink-0 text-zinc-400" />
        <span className="truncate font-mono text-zinc-100">{tc.tool}</span>
        {tc.template ? (
          <button
            type="button"
            onClick={() => onOpen(tc)}
            className="inline-flex min-h-6 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
            aria-label={`${tc.template}: open the Cypher panel for tool call ${tc.tool}`}
          >
            {tc.template}
          </button>
        ) : (
          <span className="shrink-0 rounded bg-zinc-700/50 px-1 font-mono text-[11px] whitespace-nowrap text-zinc-300" title="not a graph query">
            no Cypher
          </span>
        )}
        <span className="ml-auto shrink-0 font-mono text-[11px] text-zinc-400">{offset}</span>
      </div>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-zinc-300">
        <span>{fmtMs(tc.ms)}</span>
        <span>
          {tc.rows} row{tc.rows === 1 ? "" : "s"}
        </span>
        {tc.evidence_id ? (
          <button
            type="button"
            onClick={() => onOpenEvidence(tc.evidence_id!)}
            className="inline-flex min-h-6 items-center rounded font-mono text-sky-300 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
            aria-label={`Evidence ${tc.evidence_id}: open details`}
          >
            {tc.evidence_id}
          </button>
        ) : null}
      </p>
      {tc.summary ? <p className="text-[11px] break-words text-zinc-400">{tc.summary}</p> : null}
    </div>
  );
}
