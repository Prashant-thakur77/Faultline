"use client";

import { useMemo, useState } from "react";
import { BellRing, LoaderCircle, Moon, OctagonAlert, Siren } from "lucide-react";
import { useNow, usePolled } from "@/hooks/usePolled";
import { fmtAgo } from "@/lib/format";
import { endpointMissing, needsAck, oncallApi, type OnCallNow, type PageRow } from "@/lib/oncall";
import { tenantGraph, useTenant } from "@/lib/tenant";
import { cn } from "@/lib/utils";
import { ContractsCard } from "./ContractsCard";
import { OnCallNowCard } from "./OnCallNowCard";
import { PagerInbox, PAGES_POLL_MS } from "./PagerInbox";
import { ShiftReportCard } from "./ShiftReport";
import { StatTiles } from "./StatTiles";

/**
 * /oncall: the verdict line (does anything wait for a human?), the stats, the live pager inbox, who is on call,
 * contracts, and the shift report with its hand-off note. Each panel reads its own endpoint and says so when it
 * fails; none of them borrows another's data to fill a gap.
 */
export function OnCallView() {
  const tenant = useTenant();
  const [days, setDays] = useState(7);
  const [hours, setHours] = useState(12);

  const pages = usePolled(`pages|${tenant}`, (s) => oncallApi.pages({ tenant }, s), { intervalMs: PAGES_POLL_MS });
  const now = usePolled(`now|${tenant}`, (s) => oncallApi.now(tenant, s), { intervalMs: 60_000 });
  const contracts = usePolled(`contracts|${tenant}`, (s) => oncallApi.contracts(tenant, s), { intervalMs: 15_000 });
  const stats = usePolled(`stats|${tenant}|${days}`, (s) => oncallApi.stats(tenant, days, s), { intervalMs: 60_000 });
  // the window ends at the moment of each read: re-read every minute, so a new hand-off or page shows up
  const report = usePolled(
    `report|${tenant}|${hours}`,
    (s) => {
      const to = Date.now();
      return oncallApi.report(tenant, to - hours * 3_600_000, to, s);
    },
    { intervalMs: 60_000 },
  );

  const people = useMemo(
    () =>
      (now.data?.rows ?? [])
        .map((r) => r.person)
        .filter((p): p is NonNullable<typeof p> => !!p)
        .filter((p, i, a) => a.findIndex((x) => x.id === p.id) === i),
    [now.data],
  );
  const incidents = useMemo(() => {
    const fromPages = (pages.data?.rows ?? []).map((p) => p.incident);
    const fromReport = (report.data?.sections.incidents ?? []).map((i) => i.id ?? i.incident);
    return [...new Set([...fromPages, ...fromReport].filter((x): x is string => !!x))].slice(0, 40);
  }, [pages.data, report.data]);

  return (
    <div className="mx-auto w-full max-w-[1400px] space-y-6 px-5 py-6 sm:px-8">
      <VerdictLine pages={pages.data?.rows ?? null} error={pages.error} loading={pages.loading} oncall={now.data} tenant={tenant} />
      <StatTiles polled={stats} tenant={tenant} days={days} onDays={setDays} />
      {/* phones read pager → who is on call → contracts → shift; desktop puts the pager and the shift on the left */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:grid-rows-[auto_1fr] lg:items-start">
        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          <PagerInbox polled={pages} tenant={tenant} />
        </div>
        <div className="min-w-0 space-y-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <OnCallNowCard polled={now} tenant={tenant} />
          <ContractsCard polled={contracts} tenant={tenant} />
        </div>
        <div className="min-w-0 lg:col-start-1 lg:row-start-2">
          <ShiftReportCard polled={report} tenant={tenant} hours={hours} onHours={setHours} people={people} incidents={incidents} />
        </div>
      </div>
    </div>
  );
}

/**
 * One sentence first: does anything wait for a human right now? Counted from the pager's rows (the server's
 * statuses); "past the ack window" uses the server's overdue flag when it sends one, else its ack_due_at.
 */
export function VerdictLine({
  pages,
  error,
  loading,
  oncall,
  tenant,
}: {
  pages: PageRow[] | null;
  error: unknown;
  loading: boolean;
  oncall: OnCallNow | null;
  tenant: string;
}) {
  const clock = useNow(5000);
  const waiting = (pages ?? []).filter(needsAck);
  const overdue = waiting.filter((p) => p.overdue ?? (p.ackDueAt !== null && p.ackDueAt < clock));
  const urgent = waiting.filter((p) => p.urgency === "urgent");
  const oldest = waiting.reduce<number | null>((m, p) => (p.sentAt !== null && (m === null || p.sentAt < m) ? p.sentAt : m), null);
  const onCall = (oncall?.rows ?? []).filter((r) => r.person);

  let icon = <LoaderCircle aria-hidden className="size-6 text-zinc-400 motion-safe:animate-spin" />;
  let head = "Reading the pager from FalkorDB…";
  let tone = "bg-zinc-600";
  let sub: string | null = null;
  if (!pages && error) {
    icon = <OctagonAlert aria-hidden className="size-6 text-red-300" />;
    head = endpointMissing(error)
      ? "On-call is not on this server: its API has no pager endpoint"
      : "Pager unavailable: see the inbox below";
    tone = "bg-red-400";
  } else if (pages && waiting.length) {
    icon = urgent.length ? <Siren aria-hidden className="size-6 text-red-300" /> : <BellRing aria-hidden className="size-6 text-amber-300" />;
    head = `${waiting.length} page${waiting.length === 1 ? "" : "s"} waiting for an ack`;
    tone = urgent.length ? "bg-red-400" : "bg-amber-300";
    sub = [
      urgent.length ? `${urgent.length} urgent` : null,
      oldest !== null ? `oldest sent ${fmtAgo(oldest, clock)}` : null,
      overdue.length ? `${overdue.length} past the ack window: the next person on the escalation tree is paged` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  } else if (pages) {
    icon = <Moon aria-hidden className="size-6 text-emerald-300" />;
    head = "All quiet: no page waits for an ack";
    tone = "bg-emerald-400";
    sub = pages.length ? `${pages.length} page${pages.length === 1 ? "" : "s"} in ${tenantGraph(tenant)}, all handled` : `No page in ${tenantGraph(tenant)} yet`;
  } else if (!loading) {
    head = "No answer from the pager yet";
  }

  return (
    <section aria-labelledby="oncall-verdict" className="fl-card relative flex flex-wrap items-center gap-x-5 gap-y-3 overflow-hidden rounded-2xl px-5 py-4">
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", tone)} />
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="shrink-0">{icon}</span>
        <div className="min-w-0">
          <h2 id="oncall-verdict" className="text-[17px] font-[560] leading-snug tracking-[-0.01em] text-zinc-50 sm:text-lg" aria-live="polite">
            {head}
          </h2>
          {sub ? <p className="mt-0.5 text-xs text-zinc-400">{sub}</p> : null}
        </div>
      </div>
      {onCall.length ? (
        <p className="min-w-0 text-xs text-zinc-400 sm:max-w-[45%] sm:text-right">
          On call now:{" "}
          <span className="text-zinc-200">
            {onCall
              .slice(0, 3)
              .map((r) => `${r.person!.name ?? r.person!.id} (${r.teamName ?? r.team})`)
              .join(", ")}
          </span>
          {onCall.length > 3 ? <span className="whitespace-nowrap"> +{onCall.length - 3} more</span> : null}
        </p>
      ) : null}
    </section>
  );
}
