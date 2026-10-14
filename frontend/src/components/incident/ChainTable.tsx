"use client";

import type { ChainView } from "@/lib/graphModel";
import { StatusChip } from "@/components/StatusChip";

const KIND_TEXT: Record<string, string> = {
  service: "service call",
  data: "data lineage",
  cross: "service → data",
  change: "change applied",
  hop: "hop (not in view)",
};

/**
 * Text alternative of the graph view: every recorded chain as a table of
 * hops, with a button per node that opens the same Cypher panel as the graph.
 */
export function ChainTable({
  chains,
  onOpenNode,
  emptyText,
}: {
  chains: ChainView[];
  onOpenNode: (id: string) => void;
  /** Shown instead of the default when there is no chain (finished runs say why). */
  emptyText?: string;
}) {
  if (!chains.length) {
    return (
      <p className="text-sm text-zinc-300">
        {emptyText ?? "No causal chain recorded for this incident yet: the gate has not accepted or rejected a cause with a G2 path."}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {chains.map((c) => (
        <div key={`${c.kind}:${c.cause}`} className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="mb-1 text-left text-sm text-zinc-200">
              <span className="mr-2 inline-block align-middle">
                {c.kind === "proof" ? (
                  <StatusChip tone="pass">proof path</StatusChip>
                ) : (
                  <StatusChip tone="fail">rejected</StatusChip>
                )}
              </span>
              <span className="font-mono">{c.cause}</span>
              <span className="text-zinc-400"> · {c.note}</span>
            </caption>
            <thead className="text-zinc-400">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium">Hop</th>
                <th scope="col" className="py-1 pr-2 font-medium">From</th>
                <th scope="col" className="py-1 pr-2 font-medium">Edge</th>
                <th scope="col" className="py-1 pr-2 font-medium">Capacity</th>
                <th scope="col" className="py-1 font-medium">To</th>
              </tr>
            </thead>
            <tbody>
              {c.steps.length === 0 ? (
                <tr className="border-t border-zinc-800">
                  <td colSpan={5} className="py-1.5 text-zinc-300">
                    No G2 chain was recorded for this suspect.
                  </td>
                </tr>
              ) : (
                c.steps.map((s, i) => (
                  <tr key={`${s.from}-${s.to}`} className="border-t border-zinc-800">
                    <td className="py-1.5 pr-2 font-mono text-zinc-300">{i + 1}</td>
                    <td className="py-1.5 pr-2">
                      <NodeButton id={s.from} onOpen={onOpenNode} />
                    </td>
                    <td className="py-1.5 pr-2 text-zinc-200">{KIND_TEXT[s.kind] ?? s.kind}</td>
                    <td className="py-1.5 pr-2 font-mono text-zinc-200">{s.cap === null ? "–" : s.cap}</td>
                    <td className="py-1.5">
                      <NodeButton id={s.to} onOpen={onOpenNode} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function NodeButton({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(id)}
      className="rounded font-mono text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
      aria-label={`${id}: open the Cypher panel`}
    >
      {id}
    </button>
  );
}
