"use client";

import { cn } from "@/lib/utils";
import { StatusChip } from "@/components/StatusChip";

/**
 * Shared bits for the incident room's M12 sections (why alerts missed it, residue, ownership at
 * the change, notify). A field the source does not carry is said out loud, never filled in.
 */

/** The report / plan field is absent: a recording made before it existed, or an older backend. */
export function FieldAbsent({ mode, what, where }: { mode: "live" | "replay"; what: string; where: "report" | "/plan" }) {
  return mode === "replay" ? (
    <p className="flex flex-wrap items-center gap-2 text-sm text-zinc-300">
      <StatusChip tone="na">not in this recording</StatusChip>
      <span>This run was recorded before {what} existed; nothing is shown in its place.</span>
    </p>
  ) : (
    <p className="text-sm text-zinc-300">
      This backend&apos;s {where} response has no {what} field (an API started before the change); restart it on the current code.
    </p>
  );
}

/** A node id that opens its graph context (or its G2 path, for a change) in the Cypher panel. */
export function NodeButton({
  id,
  onOpen,
  tone = "default",
  note,
}: {
  id: string;
  onOpen: (id: string) => void;
  tone?: "default" | "cause" | "warn";
  /** Extra words for the accessible name, e.g. "silent hop". */
  note?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(id)}
      className={cn(
        "inline-flex min-h-6 items-center rounded border px-1 font-mono text-[11px] outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400",
        tone === "cause"
          ? "border-red-400 text-red-200"
          : tone === "warn"
            ? "border-dashed border-amber-400/70 text-amber-100"
            : "border-zinc-600 text-sky-200",
      )}
      aria-label={`${id}${note ? ` (${note})` : ""}: open the Cypher panel`}
    >
      {id}
    </button>
  );
}

/** Seconds relative to onset, signed ("+42 s", "−30 s"). */
export function fmtLag(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return "–";
  return s >= 0 ? `+${s} s` : `−${Math.abs(s)} s`;
}
