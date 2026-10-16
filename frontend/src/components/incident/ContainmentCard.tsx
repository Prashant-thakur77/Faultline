"use client";

import { CircleCheck, CircleX, Scissors, ShieldCheck, ShieldX } from "lucide-react";
import { fmtValue } from "@/lib/format";
import type { PlanItem, PlanResponse } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { QUERY_ID_CLS, ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Disclosure } from "@/components/ui/Disclosure";
import { Section } from "./Section";

const DOMAIN_TEXT: Record<string, string> = {
  service: "service call",
  data: "data lineage",
  cross: "service → data",
};

/** Loading / error / not-yet line shared by the plan cards. */
export function PlanPending({ error, stage, what }: { error: string | null; stage: string; what: string }) {
  if (error) {
    return (
      <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-2 text-sm text-red-100">
        Plan unavailable: {error}
      </p>
    );
  }
  if (stage === "NO_INCIDENT") {
    return <p className="text-sm text-zinc-300">None: the negative proof was accepted, so there is no {what}.</p>;
  }
  if (["RESOLVED", "UNKNOWN_ESCALATED", "FAILED"].includes(stage)) {
    return (
      <p className="text-sm text-zinc-300">
        No {what} was recorded; the run ended at <span className="font-mono">{stage}</span>.
      </p>
    );
  }
  return (
    <p className="text-sm text-zinc-300">
      No {what} recorded yet (current stage <span className="font-mono">{stage}</span>).
    </p>
  );
}

export function TemplateButton({
  template,
  onOpen,
  label,
}: {
  template: string | null;
  onOpen: () => void;
  label: string;
}) {
  if (template) return <ViaFalkor template={template} onOpen={onOpen} label={label} compact />;
  return (
    <button
      type="button"
      onClick={onOpen}
      className={QUERY_ID_CLS}
      aria-label={`no template: open the Cypher panel for ${label}`}
    >
      no Cypher
    </button>
  );
}

/**
 * Containment: the min-cut (Q-CUT-1, algo.maxFlow edge flows) that separates the failing
 * node from what must stay protected, and the what-if check on a GRAPH.COPY branch
 * (Q-WHATIF-1): does removing the cut contain the failure, and what stays connected.
 */
export function ContainmentCard({
  plan,
  error,
  stage,
  onOpenPlanItem,
}: {
  plan: PlanResponse | null;
  error: string | null;
  stage: string;
  onOpenPlanItem: (item: PlanItem<unknown>, title: string) => void;
}) {
  const cut = plan?.containment_cut ?? null;
  const wi = plan?.whatif ?? null;
  const verdict = wi?.payload?.verdict ?? null;
  const contains = verdict === "contains";
  const row = wi?.payload?.rows?.[0] ?? null;
  const protect = Array.isArray(cut?.params?.protect) ? (cut!.params!.protect as unknown[]).map(String) : [];
  const failing = typeof cut?.params?.failing === "string" ? (cut.params.failing as string) : null;

  const cutRows = cut?.payload?.rows ?? [];
  return (
    <Section
      id="containment"
      title="Containment"
      aside={
        verdict ? (
          contains ? (
            <StatusChip tone="pass" icon={ShieldCheck}>
              contains
            </StatusChip>
          ) : (
            <StatusChip tone="fail" icon={ShieldX}>
              does not contain
            </StatusChip>
          )
        ) : null
      }
      via={cut ? <ViaFalkor template={cut.template} label="the min-cut" onOpen={() => onOpenPlanItem(cut, "containment min-cut")} /> : null}
    >
      {!cut ? (
        <PlanPending error={error} stage={stage} what="containment cut" />
      ) : (
        <div className="space-y-4">
          <p className="text-sm leading-relaxed text-zinc-300">
            The smallest cut
            {failing ? (
              <>
                {" "}
                that separates <span className="font-mono text-zinc-100">{failing}</span>
              </>
            ) : null}
            {protect.length ? (
              <>
                {" "}
                from <span className="font-mono text-zinc-100">{protect.join(", ")}</span>
              </>
            ) : null}
            : {cutRows.length} edge{cutRows.length === 1 ? "" : "s"}.
          </p>
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Edges in the minimum cut, with domain and cut cost</caption>
            <thead className="text-[var(--fl-subtle)]">
              <tr>
                <th scope="col" className="pb-1.5 pr-2 font-medium">
                  Cut edge
                </th>
                <th scope="col" className="pb-1.5 pr-2 font-medium">
                  Domain
                </th>
                <th scope="col" className="pb-1.5 text-right font-medium">
                  Cut cost
                </th>
              </tr>
            </thead>
            <tbody>
              {cutRows.map((r) => (
                <tr key={`${r.u}->${r.v}`} className="border-t border-white/[0.06]">
                  <td className="py-2 pr-2">
                    <span className="inline-flex items-center gap-1.5 font-mono text-zinc-100">
                      <Scissors aria-hidden className="size-3.5 text-[var(--fl-ember)]" />
                      {r.u} <span aria-label="to">→</span> {r.v}
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-zinc-400">{DOMAIN_TEXT[r.domain] ?? r.domain}</td>
                  <td className="py-2 text-right font-mono text-zinc-200">{fmtValue(r.cut_cost)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-white/[0.1]">
                <th scope="row" colSpan={2} className="py-2 pr-2 text-left font-medium text-zinc-400">
                  Max flow (failing → protected)
                </th>
                <td className="py-2 text-right font-mono font-semibold text-zinc-50">
                  {fmtValue(cut.payload?.max_flow ?? null)}
                </td>
              </tr>
            </tfoot>
          </table>

          <Disclosure
            summary={
              <>
                What-if on a graph copy
                {verdict ? (
                  <span className="text-[var(--fl-subtle)]">
                    {" "}
                    · {contains ? "contains the failure" : "does not contain it"}
                  </span>
                ) : null}
              </>
            }
            actions={wi ? <TemplateButton template={wi.template} label="the what-if check" onOpen={() => onOpenPlanItem(wi, "what-if: cut removed")} /> : null}
          >
            {!wi || !row ? (
              <PlanPending error={error} stage={stage} what="what-if result" />
            ) : (
              <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-2 text-xs">
                {wi.payload?.branch ? (
                  <>
                    <dt className="text-[var(--fl-subtle)]">branch</dt>
                    <dd className="truncate font-mono text-zinc-400" title={wi.payload.branch}>
                      GRAPH.COPY {wi.payload.branch}
                    </dd>
                  </>
                ) : null}
                <dt className="text-[var(--fl-subtle)]">verdict</dt>
                <dd className="text-zinc-300">
                  {contains ? "the failure no longer reaches the protected nodes" : "see \u201cprotected still reached\u201d below"}
                </dd>
                <dt className="text-[var(--fl-subtle)]">edges removed</dt>
                <dd className="font-mono text-zinc-100">{row.removed_edges}</dd>
                <dt className="text-[var(--fl-subtle)]">protected still reached</dt>
                <dd>
                  {row.protected_still_reached.length === 0 ? (
                    <span className="inline-flex items-center gap-1 text-emerald-300">
                      <CircleCheck aria-hidden className="size-3.5" /> none
                    </span>
                  ) : (
                    <span className="inline-flex flex-wrap items-center gap-1 text-red-300">
                      <CircleX aria-hidden className="size-3.5" />
                      <span className="font-mono">{row.protected_still_reached.join(", ")}</span>
                    </span>
                  )}
                </dd>
                <dt className="text-[var(--fl-subtle)]">still connected</dt>
                <dd>
                  <ul className="flex flex-wrap gap-x-3 gap-y-1" aria-label="Healthy paths after the cut">
                    {Object.entries(row.still_connected)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([k, ok]) => (
                        <li key={k} className={"inline-flex items-center gap-1 font-mono text-[11px] " + (ok ? "text-zinc-300" : "text-red-300")}>
                          {ok ? <CircleCheck aria-hidden className="size-3 text-emerald-400" /> : <CircleX aria-hidden className="size-3" />}
                          {k}
                          <span className="sr-only">{ok ? "still connected" : "disconnected"}</span>
                        </li>
                      ))}
                  </ul>
                </dd>
                <dt className="text-[var(--fl-subtle)]">no longer reached</dt>
                <dd className="text-zinc-300">
                  {row.no_longer_reached.length} of {row.reach_before.length} nodes the failure reached before
                  <span className="mt-0.5 block font-mono text-[11px] break-words text-[var(--fl-subtle)]">
                    {row.no_longer_reached.join(", ") || "\u2013"}
                  </span>
                </dd>
              </dl>
            )}
          </Disclosure>
        </div>
      )}
    </Section>
  );
}
