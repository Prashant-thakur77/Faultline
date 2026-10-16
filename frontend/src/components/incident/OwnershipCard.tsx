"use client";

import { ArrowRightLeft, History, UserRound } from "lucide-react";
import { fmtTime } from "@/lib/format";
import type { IncidentView, PlanItem, PlanResponse } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { PlanPending } from "./ContainmentCard";
import { FieldAbsent } from "./ReportBits";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "./Section";
import type { IncidentActions } from "./useIncidentActions";

/**
 * Ownership when the change shipped (report.ownership + the ROUTE stage's owner_at result,
 * Q-OWN-AT / Q-OWN-PEOPLE): who owned the changed component then vs now. After a handover the
 * old team holds the context, so the people who worked on it then are listed with it.
 */
export function OwnershipCard({
  view,
  plan,
  planError,
  mode,
  actions,
}: {
  view: IncidentView;
  plan: PlanResponse | null;
  planError: string | null;
  mode: "live" | "replay";
  actions: IncidentActions;
}) {
  const own = view.report?.ownership;
  const item = plan?.owner_at;
  const p = item?.payload ?? null;
  // The report states it for the gate-accepted change; the plan's owner_at also covers an abstained run's
  // inferred origin (anchored at onset). Prefer the report, fall back to the recorded tool result.
  const fromReport = !!own && (own.owner_then !== undefined || own.summary !== undefined);
  const then = fromReport ? (own!.owner_then ?? null) : (p?.owner_then ?? null);
  const now = fromReport ? (own!.owner_now ?? null) : (p?.owner_now ?? null);
  const changed = fromReport ? own!.changed_hands === true : p?.changed_hands === true;
  const at = fromReport ? own!.at : p?.at;
  const component = fromReport ? own!.component : typeof item?.params?.id === "string" ? (item.params.id as string) : undefined;
  const knew = p?.knew_it_then ?? [];
  const anchor = fromReport ? `when ${view.report?.cause_id ?? "the change"} shipped` : "at incident onset (no confirmed change)";
  const known = fromReport || !!p;

  const tc = actions.toolCallOf("owner_at");
  const open = () =>
    item
      ? actions.openPlanItem(item as PlanItem<unknown>, "owner at the change")
      : tc
        ? actions.openToolCall(tc)
        : actions.openTemplate("Q-OWN-AT", "ownership over time", "incident report (ownership)", own?.summary, { node: component });

  let body: React.ReactNode;
  if (known) {
    body = (
      <div className="space-y-2">
        {fromReport && own?.summary ? <p className="text-xs text-zinc-200">{own.summary}.</p> : null}
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
          {component ? (
            <>
              <dt className="text-zinc-400">component</dt>
              <dd className="font-mono text-zinc-100">{component}</dd>
            </>
          ) : null}
          <dt className="text-zinc-400">owner {anchor}</dt>
          <dd className="font-mono text-zinc-100">{then ?? "no recorded owner"}</dd>
          <dt className="text-zinc-400">owner now</dt>
          <dd className="font-mono text-zinc-100">{now ?? "no current owner"}</dd>
          {typeof at === "number" ? (
            <>
              <dt className="text-zinc-400">as of</dt>
              <dd className="text-zinc-200">{fmtTime(at)}</dd>
            </>
          ) : null}
        </dl>
        {changed ? (
          <div>
            <p className="mb-1 flex items-center gap-1 text-[11px] text-zinc-400">
              <History aria-hidden className="size-3" /> Who held the context then ({then})
            </p>
            {!item ? (
              <p className="text-xs text-zinc-300">
                {item === undefined
                  ? mode === "replay"
                    ? "Not in this recording."
                    : "This backend's /plan response does not carry the owner_at people list."
                  : "Not recorded yet."}
              </p>
            ) : knew.length === 0 ? (
              <p className="text-xs text-zinc-300">Nobody from {then} committed to it during that ownership era.</p>
            ) : (
              <ul className="space-y-1" aria-label={`People from ${then} who worked on it`}>
                {knew.map((k) => (
                  <li key={k.person} className="flex flex-wrap items-center gap-2 text-xs">
                    <UserRound aria-hidden className="size-3.5 text-sky-300" />
                    <span className="font-semibold text-zinc-50">{k.name ?? k.person}</span>
                    <span className="font-mono text-[11px] text-zinc-300">{k.person}</span>
                    {k.active === false ? <StatusChip tone="warn">inactive</StatusChip> : null}
                    {typeof k.commits === "number" ? (
                      <span className="text-[11px] text-zinc-400">{k.commits} commits</span>
                    ) : null}
                    {k.other_teams.length ? (
                      <span className="text-[11px] text-zinc-400">now in {k.other_teams.join(", ")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>
    );
  } else if (!view.report && !plan) {
    body = <PlanPending error={planError} stage={view.incident.stage} what="ownership lookup" />;
  } else if (own === undefined && item === undefined) {
    body = <FieldAbsent mode={mode} what="ownership at the change" where="report" />;
  } else if (item === null && !own?.summary) {
    body = <PlanPending error={planError} stage={view.incident.stage} what="ownership lookup" />;
  } else {
    body = <p className="text-sm text-zinc-300">No gate-accepted change with a ship time, so there is no owner-at-change to look up.</p>;
  }

  return (
    <Section
      id="ownership"
      title="Ownership when the change shipped"
      via={known ? <ViaFalkor template={item?.template ?? tc?.template ?? "Q-OWN-AT"} label="ownership over time" onOpen={open} /> : null}
      aside={
        known ? (
          <>
            {changed ? (
              <StatusChip tone="warn" icon={ArrowRightLeft}>
                changed hands
              </StatusChip>
            ) : then ? (
              <StatusChip tone="info">same owner</StatusChip>
            ) : (
              <StatusChip tone="na">no owner then</StatusChip>
            )}
          </>
        ) : null
      }
    >
      {body}
    </Section>
  );
}
