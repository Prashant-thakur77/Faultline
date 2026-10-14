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
        "inline-flex min-h-6 items-center gap-1 rounded border px-1 font-mono text-[11px] leading-4 outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400",
        relation === "refutes"
          ? "border-red-500/40 text-red-200"
          : relation === "supports"
            ? "border-emerald-500/40 text-emerald-200"
            : "border-sky-500/40 text-sky-200",
      )}
      aria-label={`${relation ? `${relation} ` : ""}evidence ${id}: open details`}
    >
      {relation ? <span aria-hidden>{relation === "refutes" ? "✗" : "✓"}</span> : null}
      {id}
    </button>
  );
}

export function uniq(ids: string[]): string[] {
  return [...new Set(ids)];
}
