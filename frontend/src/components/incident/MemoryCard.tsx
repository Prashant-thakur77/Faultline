"use client";

import Link from "next/link";
import { BrainCircuit, CircleCheck, CircleHelp, CircleX } from "lucide-react";
import { fmtValue } from "@/lib/format";
import { useTenant } from "@/lib/tenant";
import type { FixHistoryRow, PlanResponse, Verdict } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { PlanPending, TemplateButton } from "./ContainmentCard";
import { Section } from "./Section";

export const FIX_KIND_TEXT: Record<string, string> = {
  flip_flag: "feature flag",
  rollback_deploy: "rollback",
  open_issue: "issue",
};

const VERDICT_TONE: Record<Verdict, { tone: "pass" | "warn" | "fail"; icon: typeof CircleCheck; glyph: string }> = {
  APPLIED: { tone: "pass", icon: CircleCheck, glyph: "✓" },
  NOT_APPLIED: { tone: "warn", icon: CircleX, glyph: "✗" },
  UNKNOWN: { tone: "fail", icon: CircleHelp, glyph: "?" },
};

/** "worked before: 3× APPLIED" (or "2× NOT_APPLIED") for one fix-history row. */
export function FixHistoryChip({ row }: { row: FixHistoryRow }) {
  const v = row.verdict;
  const meta = v ? VERDICT_TONE[v] : null;
  const label =
    v === "APPLIED" ? `worked before: ${row.n}× APPLIED` : v ? `tried before: ${row.n}× ${v}` : `tried before: ${row.n}× (no verdict)`;
  return (
    <StatusChip tone={meta?.tone ?? "na"} icon={meta?.icon} title={`precedents: ${row.incidents.join(", ")}`}>
      {meta ? <span aria-hidden>{meta.glyph}</span> : null}
      {label}
    </StatusChip>
  );
}

/**
 * Memory: the past incidents RECALL linked to this one (Q-MEM-4: RECALLED edges, vector
 * seed kept only when a Symptom node is shared) and how each fix kind fared on them (Q-MEM-5).
 */
export function MemoryCard({
  plan,
  error,
  stage,
  onOpenTemplate,
  incidentId = null,
}: {
  plan: PlanResponse | null;
  error: string | null;
  stage: string;
  onOpenTemplate: (template: string, title: string, origin: string, detail?: string) => void;
  /** Live room: links to the Memory tab for this incident (families, runbooks, recall). */
  incidentId?: string | null;
}) {
  const tenant = useTenant();
  const mem = plan?.memory ?? null;
  return (
    <Section
      id="memory"
      title="Memory"
      aside={
        mem ? (
          <>
            <TemplateButton
              template="Q-MEM-4"
              label="recalled precedents"
              onOpen={() => onOpenTemplate("Q-MEM-4", "recalled precedents", "plan memory (GET /plan)", `${mem.recalled.length} recalled`)}
            />
            <TemplateButton
              template="Q-MEM-5"
              label="fix history"
              onOpen={() => onOpenTemplate("Q-MEM-5", "fix history of the precedents", "plan memory (GET /plan)", `${mem.fix_history.length} fix kinds`)}
            />
          </>
        ) : null
      }
    >
      {!plan ? (
        <PlanPending error={error} stage={stage} what="memory" />
      ) : !mem ? (
        <p className="text-sm text-zinc-300">This backend&apos;s /plan response has no memory fields.</p>
      ) : (
        <div className="space-y-2.5">
          <div>
            <h3 className="mb-1 flex items-center gap-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">
              <BrainCircuit aria-hidden className="size-3.5" /> Recalled precedents
            </h3>
            {mem.recalled.length === 0 ? (
              <p className="text-xs text-zinc-300">Cold start: RECALL found no past incident sharing a symptom.</p>
            ) : (
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Past incidents recalled for this incident: similarity, recency and salience</caption>
                <thead className="text-zinc-400">
                  <tr>
                    <th scope="col" className="py-0.5 pr-2 font-medium">Incident</th>
                    <th scope="col" className="py-0.5 pr-2 font-medium">Title</th>
                    <th scope="col" className="py-0.5 pr-2 text-right font-medium">Similarity</th>
                    <th scope="col" className="py-0.5 pr-2 text-right font-medium">Recency</th>
                    <th scope="col" className="py-0.5 text-right font-medium">Salience</th>
                  </tr>
                </thead>
                <tbody>
                  {mem.recalled.map((r) => (
                    <tr key={r.id} className="border-t border-zinc-800 align-top">
                      <td className="py-1 pr-2 font-mono whitespace-nowrap text-zinc-100">{r.id}</td>
                      <td className="py-1 pr-2 text-zinc-200">
                        {r.title ?? "–"}
                        {r.actions.length ? (
                          <span className="block text-[11px] text-zinc-400">
                            fixed by{" "}
                            {r.actions
                              .map((a) => `${FIX_KIND_TEXT[a.kind] ?? a.kind}${a.target ? ` ${a.target}` : ""} (${a.verdict ?? "no verdict"})`)
                              .join("; ")}
                          </span>
                        ) : null}
                      </td>
                      <td className="py-1 pr-2 text-right font-mono text-zinc-100">{fmtValue(r.similarity)}</td>
                      <td className="py-1 pr-2 text-right font-mono text-zinc-100">{fmtValue(r.recency)}</td>
                      <td className="py-1 text-right font-mono text-zinc-100">{fmtValue(r.salience)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">Fix history on those precedents</h3>
            {mem.fix_history.length === 0 ? (
              <p className="text-xs text-zinc-300">No recorded fixes on the recalled incidents.</p>
            ) : (
              <ul className="space-y-1" aria-label="Fix kinds and how they fared">
                {mem.fix_history.map((f) => (
                  <li key={`${f.kind}:${f.verdict}`} className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="w-24 shrink-0 text-zinc-200">{FIX_KIND_TEXT[f.kind] ?? f.kind}</span>
                    <FixHistoryChip row={f} />
                    <span className="font-mono text-[11px] text-zinc-400">{f.incidents.join(", ")}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {incidentId ? (
            <p className="text-xs">
              <Link
                href={`/memory?incident=${encodeURIComponent(incidentId)}&tenant=${encodeURIComponent(tenant)}`}
                className="text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                Open in the Memory tab
              </Link>{" "}
              <span className="text-zinc-400">(families, derived runbooks, recall, cold vs warm)</span>
            </p>
          ) : null}
        </div>
      )}
    </Section>
  );
}
