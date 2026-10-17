"use client";

import { Timer, TimerOff } from "lucide-react";
import { useNow } from "@/hooks/usePolled";
import { fmtAgo } from "@/lib/format";
import { fmtCountdown, fmtDuration } from "@/lib/oncall";

/** "sent 3 min ago" (client clock against the server's sent_at). */
export function SentAgo({ at }: { at: number | null }) {
  const now = useNow(5000);
  if (at === null) return <span>sent at an unrecorded time</span>;
  return <time dateTime={new Date(at).toISOString()}>sent {fmtAgo(at, now)}</time>;
}

/**
 * The ack window of an open page, from its ack_due_at: "ack due in 3:12", then "ack window passed 40 s ago". Display
 * only: the escalation itself is decided by the server's Q-PAGE-OVERDUE read, not by this clock.
 */
export function AckDue({ dueAt, className }: { dueAt: number | null; className?: string }) {
  const now = useNow(1000);
  if (dueAt === null) return null;
  const left = dueAt - now;
  return left >= 0 ? (
    <span className={"inline-flex items-center gap-1 tabular-nums " + (className ?? "")}>
      <Timer aria-hidden className="size-3.5 shrink-0" />
      ack due in {fmtCountdown(left)}
    </span>
  ) : (
    <span className={"inline-flex items-center gap-1 text-amber-200 tabular-nums " + (className ?? "")}>
      <TimerOff aria-hidden className="size-3.5 shrink-0" />
      ack window passed {fmtDuration(-left)} ago
    </span>
  );
}
