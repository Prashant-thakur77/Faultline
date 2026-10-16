"use client";

import { cn } from "@/lib/utils";

/** An evidence id as a button that opens the evidence in the Cypher panel. */
export function EvidenceChip({
  id,
  onOpen,
  relation,
}: {
  id: string;
  onOpen: (id: string) => void;
  /** Optional relation shown as text before the id ("supports", "refutes"). */
  relation?: "supports" | "refutes";
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(id)}
      className={cn(
        "inline-flex min-h-6 items-center gap-1 rounded px-1 font-mono text-[11px] leading-4 text-zinc-400 outline-none transition-colors hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400",
      )}
      aria-label={`${relation ? `${relation} ` : ""}evidence ${id}: open details`}
    >
      {relation ? (
        <span aria-hidden className={relation === "refutes" ? "text-red-400" : "text-emerald-400"}>
          {relation === "refutes" ? "✗" : "✓"}
        </span>
      ) : null}
      {id}
    </button>
  );
}

export function uniq(ids: string[]): string[] {
  return [...new Set(ids)];
}
