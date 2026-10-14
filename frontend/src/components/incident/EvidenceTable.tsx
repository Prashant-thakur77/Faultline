"use client";

import { Database, Network } from "lucide-react";
import type { Report } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { Section } from "./Section";

/** Evidence cited by the report: kind, source, ABOUT chips, summary; each row opens the Cypher panel. */
export function EvidenceTable({
  report,
  onOpenEvidence,
}: {
  report: Report | undefined;
  onOpenEvidence: (id: string) => void;
}) {
  return (
    <Section
      id="evidence"
      title="Evidence"
      aside={report ? <span className="text-[11px] text-zinc-400">{report.evidence.length} cited</span> : null}
    >
      {!report ? (
        <p className="text-sm text-zinc-300">
          The cited-evidence list arrives with the report. Every tool call&apos;s evidence id is already in the
          timeline.
        </p>
      ) : report.evidence.length === 0 ? (
        <p className="text-sm text-zinc-300">
          The report cites no evidence items for outcome <span className="font-mono">{report.outcome}</span>.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Evidence cited by the report</caption>
            <thead className="text-zinc-400">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium">Id · kind</th>
                <th scope="col" className="py-1 pr-2 font-medium">Source</th>
                <th scope="col" className="py-1 font-medium">About · summary</th>
              </tr>
            </thead>
            <tbody>
              {report.evidence.map((e) => (
                <tr key={e.id} className="border-t border-zinc-800 align-top">
                  <td className="py-1.5 pr-2">
                    <button
                      type="button"
                      onClick={() => onOpenEvidence(e.id)}
                      className="inline-flex min-h-6 items-center rounded font-mono text-sky-300 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
                      aria-label={`Evidence ${e.id} (${e.kind}): open ${e.template ? `the Cypher panel for ${e.template}` : "details"}`}
                    >
                      {e.id}
                    </button>
                    <p className="font-mono text-[11px] text-zinc-300">{e.kind}</p>
                    {e.template ? (
                      <p className="font-mono text-[10px] text-violet-200">{e.template}</p>
                    ) : null}
                  </td>
                  <td className="py-1.5 pr-2">
                    {e.source === "falkordb" ? (
                      <StatusChip tone="info" icon={Network}>
                        FalkorDB
                      </StatusChip>
                    ) : (
                      <StatusChip tone="na" icon={Database}>
                        {e.source}
                      </StatusChip>
                    )}
                    {e.anomalous !== null ? (
                      <p className="mt-1">
                        {e.anomalous ? (
                          <StatusChip tone="warn">anomalous</StatusChip>
                        ) : (
                          <StatusChip tone="pass">in band</StatusChip>
                        )}
                      </p>
                    ) : null}
                  </td>
                  <td className="py-1.5">
                    <div className="flex flex-wrap gap-1">
                      {e.about.map((a) => (
                        <span key={a} className="rounded border border-zinc-600 px-1 font-mono text-[10px] text-zinc-200">
                          {a}
                        </span>
                      ))}
                    </div>
                    <p className="mt-0.5 break-words text-zinc-200">{e.summary}</p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
