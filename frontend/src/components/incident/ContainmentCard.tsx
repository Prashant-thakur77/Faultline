"use client";

import { CircleCheck, CircleX, Scissors, ShieldCheck, ShieldX } from "lucide-react";
import { fmtValue } from "@/lib/format";
import type { PlanItem, PlanResponse } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
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
  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex min-h-6 shrink-0 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] whitespace-nowrap text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
      aria-label={`${template ?? "no template"}: open the Cypher panel for ${label}`}
    >
      {template ?? "no Cypher"}
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
    >
      {!cut ? (
        <PlanPending error={error} stage={stage} what="containment cut" />
      ) : (
        <div className="space-y-3">
          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <h3 className="text-xs font-semibold tracking-wide text-zinc-300 uppercase">Min-cut</h3>
              <span className="text-[11px] text-zinc-400">
                {failing ? (
                  <>
                    separates <span className="font-mono text-zinc-200">{failing}</span>
                  </>
                ) : null}
                {protect.length ? (
                  <>
                    {" "}
                    from <span className="font-mono text-zinc-200">{protect.join(", ")}</span>
                  </>
                ) : null}
              </span>
              <span className="ml-auto">
                <TemplateButton template={cut.template} label="the min-cut" onOpen={() => onOpenPlanItem(cut, "containment min-cut")} />
              </span>
            </div>
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Edges in the minimum cut, with domain and cut cost</caption>
              <thead className="text-zinc-400">
                <tr>
                  <th scope="col" className="py-1 pr-2 font-medium">
                    Cut edge
                  </th>
                  <th scope="col" className="py-1 pr-2 font-medium">
                    Domain
                  </th>
                  <th scope="col" className="py-1 text-right font-medium">
                    Cut cost
                  </th>
                </tr>
              </thead>
              <tbody>
                {(cut.payload?.rows ?? []).map((r) => (
                  <tr key={`${r.u}->${r.v}`} className="border-t border-zinc-800">
                    <td className="py-1.5 pr-2">
                      <span className="inline-flex items-center gap-1 font-mono text-red-200">
                        <Scissors aria-hidden className="size-3.5 text-red-300" />
                        {r.u} <span aria-label="to">→</span> {r.v}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-zinc-200">{DOMAIN_TEXT[r.domain] ?? r.domain}</td>
                    <td className="py-1.5 text-right font-mono text-zinc-100">{fmtValue(r.cut_cost)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-zinc-700">
                  <th scope="row" colSpan={2} className="py-1.5 pr-2 text-left font-medium text-zinc-300">
                    Max flow (failing → protected)
                  </th>
                  <td className="py-1.5 text-right font-mono font-semibold text-zinc-50">
                    {fmtValue(cut.payload?.max_flow ?? null)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <h3 className="text-xs font-semibold tracking-wide text-zinc-300 uppercase">What-if</h3>
              {wi?.payload?.branch ? (
                <span className="truncate font-mono text-[11px] text-zinc-400" title={wi.payload.branch}>
                  on GRAPH.COPY {wi.payload.branch}
                </span>
              ) : null}
              {wi ? (
                <span className="ml-auto">
                  <TemplateButton template={wi.template} label="the what-if check" onOpen={() => onOpenPlanItem(wi, "what-if: cut removed")} />
                </span>
              ) : null}
            </div>
            {!wi || !row ? (
              <PlanPending error={error} stage={stage} what="what-if result" />
            ) : (
              <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
                <dt className="text-zinc-400">verdict</dt>
                <dd>
                  {contains ? (
                    <>
                      <StatusChip tone="pass" icon={ShieldCheck}>
                        contains
                      </StatusChip>
                      <span className="mt-0.5 block text-zinc-300">the failure no longer reaches the protected nodes</span>
                    </>
                  ) : (
                    <>
                      <StatusChip tone="fail" icon={ShieldX}>
                        does not contain
                      </StatusChip>
                      <span className="mt-0.5 block text-zinc-300">see &ldquo;protected still reached&rdquo; below</span>
                    </>
                  )}
                </dd>
                <dt className="text-zinc-400">edges removed</dt>
                <dd className="font-mono text-zinc-100">{row.removed_edges}</dd>
                <dt className="text-zinc-400">protected still reached</dt>
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
                <dt className="text-zinc-400">still connected</dt>
                <dd>
                  <ul className="flex flex-wrap gap-1.5" aria-label="Healthy paths after the cut">
                    {Object.entries(row.still_connected)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([k, ok]) => (
                        <li
                          key={k}
                          className={
                            "inline-flex items-center gap-1 rounded border px-1 font-mono text-[11px] " +
                            (ok ? "border-emerald-500/40 text-emerald-200" : "border-red-500/50 text-red-200")
                          }
                        >
                          {k}
                          <span aria-hidden>{ok ? "✓" : "✗"}</span>
                          <span className="sr-only">{ok ? "still connected" : "disconnected"}</span>
                        </li>
                      ))}
                  </ul>
                </dd>
                <dt className="text-zinc-400">no longer reached</dt>
                <dd>
                  <details>
                    <summary className="cursor-pointer text-zinc-200 outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                      {row.no_longer_reached.length} of {row.reach_before.length} nodes the failure reached before
                    </summary>
                    <p className="mt-1 font-mono text-[11px] break-words text-zinc-300">
                      {row.no_longer_reached.join(", ") || "–"}
                    </p>
                  </details>
                </dd>
              </dl>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}
