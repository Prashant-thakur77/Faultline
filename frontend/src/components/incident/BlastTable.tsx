"use client";

import { fmtValue } from "@/lib/format";
import type { BlastResponse } from "@/lib/types";

/**
 * Text alternative of ripple mode: the blast radius of each symptom as returned by
 * /api/incidents/{id}/blast (algo.BFS rows, ranked by impact on the server).
 */
export function BlastTable({ blast, onOpenNode }: { blast: BlastResponse; onOpenNode: (id: string) => void }) {
  const entries = Object.entries(blast.blast);
  if (!entries.length) return <p className="text-sm text-zinc-300">No symptom has a recorded blast radius.</p>;
  return (
    <div className="space-y-3">
      {entries.map(([symptom, b]) => (
        <div key={symptom} className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="mb-1 text-left text-sm text-zinc-200">
              Blast radius of <span className="font-mono">{symptom}</span>
              <span className="text-zinc-400">
                {" "}
                · {b.rows.length} node{b.rows.length === 1 ? "" : "s"} · {b.template} · <span className="font-mono">{b.via}</span>
              </span>
            </caption>
            <thead className="text-zinc-400">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium">Node</th>
                <th scope="col" className="py-1 pr-2 font-medium">Kind</th>
                <th scope="col" className="py-1 pr-2 font-medium">Tier</th>
                <th scope="col" className="py-1 pr-2 font-medium">Revenue</th>
                <th scope="col" className="py-1 pr-2 font-medium">Hops</th>
                <th scope="col" className="py-1 text-right font-medium">Impact</th>
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r) => (
                <tr key={r.id} className="border-t border-zinc-800">
                  <td className="py-1.5 pr-2">
                    <button
                      type="button"
                      onClick={() => onOpenNode(r.id)}
                      className="inline-flex min-h-6 items-center rounded font-mono text-sky-300 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
                      aria-label={`${r.id}: open the Cypher panel`}
                    >
                      {r.id}
                    </button>
                  </td>
                  <td className="py-1.5 pr-2 text-zinc-200">{r.label}</td>
                  <td className="py-1.5 pr-2 font-mono text-zinc-200">{r.tier ?? "–"}</td>
                  <td className="py-1.5 pr-2 text-zinc-200">{r.revenue ? "yes" : "no"}</td>
                  <td className="py-1.5 pr-2 font-mono text-zinc-200">{r.hops}</td>
                  <td className="py-1.5 text-right font-mono text-zinc-100">{fmtValue(r.impact)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
