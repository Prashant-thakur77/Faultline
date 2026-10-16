"use client";

import { useId, useState } from "react";
import { ChevronRight, Flag, Hand, Radio, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { fmtMs, fmtOffset } from "@/lib/format";
import { originText } from "@/lib/gate";
import type { StreamState, TimelineItem } from "@/hooks/useIncident";
import type { ToolCallRow } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { useFold } from "@/components/ui/Disclosure";
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

/** Stage names as people say them ("AWAITING_APPROVAL" → "Awaiting approval"); the raw stage is kept in a title. */
export function stageLabel(stage: string): string {
  const t = stage.replaceAll("_", " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

type Group = { stage: Extract<TimelineItem, { kind: "stage" }> | null; items: TimelineItem[] };

/** Stages in order, each owning the tool calls and gate runs recorded after it. */
function groupByStage(items: TimelineItem[]): Group[] {
  const out: Group[] = [];
  for (const it of items) {
    if (it.kind === "stage") out.push({ stage: it, items: [] });
    else if (out.length) out[out.length - 1].items.push(it);
    else out.push({ stage: null, items: [it] });
  }
  return out;
}

/**
 * Left rail: one row per stage (the story), with its tool calls one click away and gate verdicts always shown
 * (they are the story's turning points). SSE keeps it live while the run streams.
 */
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
  const groups = groupByStage(items.filter((i) => i.kind !== "done"));
  const done = items.find((i) => i.kind === "done");
  const fold = useFold();
  return (
    <section aria-labelledby="timeline-h" className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4 pb-3">
        <h2 id="timeline-h" className="text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
          Timeline
        </h2>
        <StatusChip tone={chip.tone} icon={Icon} className="ml-auto">
          {chip.text}
        </StatusChip>
      </div>
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      {items.length === 0 ? (
        <p className="px-4 text-sm text-zinc-300">No stage events recorded yet for this run.</p>
      ) : (
        <ol className="relative px-4 pb-6 before:absolute before:top-2 before:bottom-8 before:left-[1.4rem] before:w-px before:bg-white/[0.08]">
          {groups.map((g, gi) => (
            <StageGroup
              key={g.stage?.key ?? `pre-${gi}`}
              group={g}
              base={base}
              last={gi === groups.length - 1}
              fold={fold}
              onOpenToolCall={onOpenToolCall}
              onOpenEvidence={onOpenEvidence}
            />
          ))}
          {done && done.kind === "done" ? (
            <li className="relative mt-2 flex items-center gap-2 pl-6 text-xs text-zinc-400">
              <Flag aria-hidden className="absolute left-0 size-3.5 text-[var(--fl-subtle)]" />
              Run finished at {stageLabel(done.stage)}
              <span className="sr-only"> (stage {done.stage})</span>
            </li>
          ) : null}
        </ol>
      )}
    </section>
  );
}

function StageGroup({
  group,
  base,
  last,
  fold,
  onOpenToolCall,
  onOpenEvidence,
}: {
  group: Group;
  base: number;
  last: boolean;
  fold: boolean;
  onOpenToolCall: (tc: ToolCallRow) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const [open, setOpen] = useState(!fold);
  const id = useId();
  const calls = group.items.filter((i): i is Extract<TimelineItem, { kind: "tool_call" }> => i.kind === "tool_call");
  const gates = group.items.filter((i): i is Extract<TimelineItem, { kind: "gate_run" }> => i.kind === "gate_run");
  const st = group.stage;
  return (
    <li className="relative py-1">
      <div className="flex items-start gap-2">
        <span
          aria-hidden
          className={cn(
            "relative z-10 mt-[0.45rem] size-2.5 shrink-0 rounded-full ring-4 ring-[var(--fl-bg)]",
            last ? "bg-[var(--fl-iris)]" : "bg-zinc-500",
          )}
        />
        <div className="min-w-0 flex-1">
          {calls.length ? (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={id}
              onClick={() => setOpen((o) => !o)}
              className="group flex w-full items-center gap-1.5 rounded-md py-0.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <span className="text-[13px] font-medium text-zinc-100 group-hover:text-white" title={st?.row.stage}>
                {st ? stageLabel(st.row.stage) : "Before the first stage"}
              </span>
              <span className="text-[11px] text-[var(--fl-subtle)]">
                {calls.length} call{calls.length === 1 ? "" : "s"}
              </span>
              <ChevronRight
                aria-hidden
                className={cn("size-3.5 text-zinc-600 transition-transform motion-reduce:transition-none group-hover:text-zinc-300", open && "rotate-90")}
              />
              {st ? <span className="ml-auto font-mono text-[11px] text-[var(--fl-subtle)]">{fmtOffset(st.at, base)}</span> : null}
            </button>
          ) : (
            <div className="flex items-center gap-1.5 py-0.5">
              <span className="text-[13px] font-medium text-zinc-100" title={st?.row.stage}>
                {st ? stageLabel(st.row.stage) : "Before the first stage"}
              </span>
              {st ? <span className="ml-auto font-mono text-[11px] text-[var(--fl-subtle)]">{fmtOffset(st.at, base)}</span> : null}
            </div>
          )}
          {st?.row.note ? <p className="text-xs break-words text-zinc-400">{st.row.note}</p> : null}
          {calls.length ? (
            <ol id={id} hidden={!open} className="mt-1 space-y-0.5" aria-label={`Tool calls in ${st ? stageLabel(st.row.stage) : "the run"}`}>
              {calls.map((it) => (
                <li key={it.key}>
                  <ToolCallItem tc={it.row} offset={fmtOffset(it.at, base)} onOpen={onOpenToolCall} onOpenEvidence={onOpenEvidence} />
                </li>
              ))}
            </ol>
          ) : null}
          {gates.length ? (
            <ul className="mt-1 space-y-1">
              {gates.map((it) => (
                <li key={it.key} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
                  {it.row.passed ? (
                    <StatusChip tone="pass" icon={ShieldCheck}>
                      gate passed
                    </StatusChip>
                  ) : (
                    <StatusChip tone="fail" icon={ShieldX}>
                      gate rejected
                    </StatusChip>
                  )}
                  <span className="truncate font-mono text-zinc-200">{it.row.cause}</span>
                  <span className="text-[11px] text-[var(--fl-subtle)]">
                    {originText(it.row.origin)} · {it.row.checks.length} checks
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </li>
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
    <div className="rounded-md px-1.5 py-1 hover:bg-white/[0.03]">
      <div className="flex items-center gap-1.5 text-xs">
        <Wrench aria-hidden className="size-3 shrink-0 text-[var(--fl-subtle)]" />
        <span className="truncate font-mono text-zinc-200">{tc.tool}</span>
        {tc.template ? (
          <button
            type="button"
            onClick={() => onOpen(tc)}
            className={QUERY_ID_CLS}
            aria-label={`${tc.template}: open the Cypher panel for tool call ${tc.tool}`}
          >
            {tc.template}
          </button>
        ) : (
          <span className="shrink-0 px-1 font-mono text-[11px] whitespace-nowrap text-[var(--fl-subtle)]" title="not a graph query">
            no Cypher
          </span>
        )}
        <span className="ml-auto shrink-0 font-mono text-[11px] text-zinc-400">{offset}</span>
      </div>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 pl-[1.125rem] text-[11px] text-[var(--fl-subtle)]">
        <span>{fmtMs(tc.ms)}</span>
        <span>
          {tc.rows} row{tc.rows === 1 ? "" : "s"}
        </span>
        {tc.evidence_id ? (
          <button
            type="button"
            onClick={() => onOpenEvidence(tc.evidence_id!)}
            className="inline-flex min-h-6 items-center rounded font-mono text-zinc-400 outline-none hover:text-zinc-100 hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
            aria-label={`Evidence ${tc.evidence_id}: open details`}
          >
            {tc.evidence_id}
          </button>
        ) : null}
      </p>
      {tc.summary ? <p className="pl-[1.125rem] text-[11px] break-words text-zinc-400">{tc.summary}</p> : null}
    </div>
  );
}
