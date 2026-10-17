"use client";

import { CircleCheck } from "lucide-react";
import { fmtWhen, personText, type ChainStep } from "@/lib/oncall";
import { channelText, PageStatusChip } from "./bits";

/**
 * A page's escalation history (Q-PAGE-CHAIN): who was paged, in order, on which channel, and who acked. A text list
 * (an ordered list is its own text alternative); the current page is marked.
 */
export function PageChain({ steps, current, label }: { steps: ChainStep[]; current?: string; label: string }) {
  if (!steps.length) return <p className="text-xs text-zinc-400">No escalation: this page is the first and only one.</p>;
  return (
    <ol aria-label={label} className="relative space-y-2 pl-5 before:absolute before:top-2 before:bottom-2 before:left-[7px] before:w-px before:bg-white/[0.08]">
      {steps.map((s, i) => (
        <li key={s.id} className="relative text-xs">
          <span
            aria-hidden
            className={
              "absolute top-1 -left-5 size-[15px] rounded-full border-2 " +
              (s.ack ? "border-emerald-400 bg-emerald-500/30" : s.id === current ? "border-amber-300 bg-amber-500/25" : "border-zinc-600 bg-[var(--fl-surface)]")
            }
          />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium text-zinc-100">
              {s.attempt !== null ? `Attempt ${s.attempt}` : `Step ${i + 1}`}
              {s.id === current ? <span className="font-normal text-zinc-400"> (this page)</span> : null}
            </span>
            <PageStatusChip status={s.status} />
          </div>
          <p className="mt-0.5 break-words text-zinc-300">
            {personText(s.person)} · {channelText(s.channel)}
            {s.sentAt !== null ? <> · sent {fmtWhen(s.sentAt)}</> : null}
          </p>
          {s.ack ? (
            <p className="mt-0.5 flex items-center gap-1 text-emerald-200">
              <CircleCheck aria-hidden className="size-3.5" />
              acked{s.ack.by ? ` by ${personText(s.ack.by)}` : ""}
              {s.ack.at !== null ? ` at ${fmtWhen(s.ack.at)}` : ""}
              {s.ack.via ? ` via ${s.ack.via}` : ""}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
