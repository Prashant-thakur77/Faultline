"use client";

import { Megaphone, PhoneCall, TriangleAlert } from "lucide-react";
import { fmtValue } from "@/lib/format";
import type { PlanItem, PlanResponse } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { PlanPending } from "./ContainmentCard";
import { FieldAbsent } from "./ReportBits";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "./Section";

/**
 * Notify (plan.notify_set, Q-NOTIFY-1 over the algo.SSpaths blast radius): the teams that own
 * something the failure reaches, with who is on call for each now. This is who to TELL, not who
 * fixes it (that ranking is the "Who fixes it" card). Ordered by weighted impact (code + weights).
 */
export function NotifyCard({
  plan,
  error,
  stage,
  mode,
  onOpenPlanItem,
}: {
  plan: PlanResponse | null;
  error: string | null;
  stage: string;
  mode: "live" | "replay";
  onOpenPlanItem: (item: PlanItem<unknown>, title: string) => void;
}) {
  const item = plan?.notify_set;
  const rows = item?.payload?.rows ?? [];
  const target = typeof item?.params?.target_id === "string" ? (item.params.target_id as string) : null;

  return (
    <Section
      id="notify"
      title="Notify (who to tell)"
      via={item ? <ViaFalkor template={item.template} label="the notify list" onOpen={() => onOpenPlanItem(item, "who to notify")} /> : null}
      aside={
        item ? (
          <>
            <StatusChip tone="info" icon={Megaphone}>
              {rows.length} team{rows.length === 1 ? "" : "s"}
            </StatusChip>
          </>
        ) : null
      }
    >
      <p className="mb-2 text-[11px] text-zinc-400">
        Who to tell, not who fixes it: the teams that own something in the blast radius
        {target ? (
          <>
            {" "}
            of <span className="font-mono text-zinc-300">{target}</span>
          </>
        ) : null}
        , with who is on call for each now.
      </p>
      {!plan ? (
        <PlanPending error={error} stage={stage} what="notify list" />
      ) : item === undefined ? (
        <FieldAbsent mode={mode} what="the notify list" where="/plan" />
      ) : item === null ? (
        <PlanPending error={error} stage={stage} what="notify list" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-zinc-300">No team owns anything in the blast radius.</p>
      ) : (
        <ol className="space-y-1.5" aria-label="Teams to notify, by impact">
          {rows.map((t) => (
            <li key={t.team} className="rounded-md border border-zinc-700 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-zinc-50">{t.name ?? t.team}</span>
                <span className="font-mono text-[11px] text-zinc-300">{t.team}</span>
                <span className="ml-auto font-mono text-[11px] text-zinc-300" title="tier weight × bottleneck cap / (1 + hops), summed">
                  impact {fmtValue(t.impact)}
                  {t.nearest_hops !== null ? ` · ${t.nearest_hops} hop${t.nearest_hops === 1 ? "" : "s"}` : ""}
                </span>
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                {t.oncall.length ? (
                  <>
                    <StatusChip tone="info" icon={PhoneCall}>
                      on call
                    </StatusChip>
                    <span className="font-mono text-zinc-100">{t.oncall.join(", ")}</span>
                  </>
                ) : (
                  <StatusChip tone="warn" icon={TriangleAlert}>
                    no one on call now
                  </StatusChip>
                )}
              </p>
              {t.owns_impacted.length ? (
                <p className="mt-1 text-[11px] text-zinc-400">
                  owns impacted: <span className="font-mono text-zinc-200">{t.owns_impacted.join(", ")}</span>
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
