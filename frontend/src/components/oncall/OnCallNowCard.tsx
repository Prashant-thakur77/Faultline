"use client";

import { LoaderCircle, PhoneCall } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import type { Polled } from "@/hooks/usePolled";
import { fmtWhen, type OnCallNow } from "@/lib/oncall";
import { tenantGraph } from "@/lib/tenant";
import { Avatar, PanelError, useOpenQuery } from "./bits";

/** Who is on call now, per team: the active ON_CALL edges at the server's clock (Q-ONCALL-NOW). */
export function OnCallNowCard({ polled, tenant }: { polled: Polled<OnCallNow>; tenant: string }) {
  const open = useOpenQuery(tenant);
  const data = polled.data;
  const rows = data?.rows ?? [];
  const covered = rows.filter((r) => r.person);
  return (
    <Section
      id="oncallnow"
      title="On call now"
      via={
        data?.template ? (
          <ViaFalkor template={data.template} label="who is on call now" onOpen={() => open(data, "on call now", "GET /api/oncall/now")} />
        ) : null
      }
      aside={
        data ? (
          <StatusChip tone={covered.length ? "info" : "warn"} icon={PhoneCall}>
            {covered.length} of {rows.length} team{rows.length === 1 ? "" : "s"} covered
          </StatusChip>
        ) : null
      }
    >
      {polled.error ? <PanelError error={polled.error} what="on call now (GET /api/oncall/now)" stale={!!data} /> : null}
      {polled.loading && !data && !polled.error ? (
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> Reading the rota from FalkorDB…
        </p>
      ) : null}
      {data && rows.length === 0 ? (
        <p className="text-sm text-zinc-300">
          Nobody is on call now in {tenantGraph(tenant)}: no ON_CALL edge covers this moment. Pages fall back to the
          escalation tree.
        </p>
      ) : null}
      {rows.length ? (
        <ul aria-label="On call now, per team" className="divide-y divide-white/[0.05]">
          {rows.map((r) => (
            <li key={`${r.team}:${r.person?.id ?? "-"}`} className="flex min-w-0 items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              {r.person ? <Avatar name={r.person.name} id={r.person.id} /> : <span aria-hidden className="size-8 shrink-0 rounded-full border border-dashed border-zinc-600" />}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-zinc-50">
                  {r.person ? (
                    <>
                      <span className="font-medium">{r.person.name ?? r.person.id}</span>
                      {r.person.name ? <span className="font-mono text-[11px] text-zinc-400"> {r.person.id}</span> : null}
                    </>
                  ) : (
                    <span className="text-amber-200">nobody on call</span>
                  )}
                </p>
                <p className="text-[11px] text-zinc-400 sm:truncate">
                  {r.teamName ?? r.team}
                  {r.teamName ? <span className="hidden font-mono sm:inline"> · {r.team}</span> : null}
                  {r.to !== null ? <span className="sm:hidden"> · until {fmtWhen(r.to)}</span> : null}
                </p>
              </div>
              {r.to !== null ? (
                <p className="hidden shrink-0 text-right text-[11px] text-zinc-400 sm:block">
                  until
                  <span className="block font-mono text-zinc-300">{fmtWhen(r.to)}</span>
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}
