"use client";

import Link from "next/link";
import { ArrowUpRight, BellRing, LoaderCircle } from "lucide-react";
import { StatusChip } from "@/components/StatusChip";
import { usePolled, type Polled } from "@/hooks/usePolled";
import { fmtClock } from "@/lib/format";
import { needsAck, oncallApi, type PagesList } from "@/lib/oncall";
import { channelText, PageStatusChip, PanelError } from "./bits";
import { AckDue, SentAgo } from "./Countdown";
import { ChannelNote, DeliveryProblems, PAGES_POLL_MS } from "./PagerInbox";

/** GET /api/pages?incident=: the pages sent for one incident, re-read every 5 s while the tab is visible. */
export function useIncidentPages(incident: string | null, tenant: string): Polled<PagesList> {
  return usePolled(`inc-pages|${tenant}|${incident ?? ""}`, (s) => oncallApi.pages({ tenant, incident: incident! }, s), {
    intervalMs: PAGES_POLL_MS,
    enabled: !!incident,
  });
}

/** "2 pages · 1 acked" for a folded card header (counts of the server's statuses). */
export function IncidentPagesChip({ polled }: { polled: Polled<PagesList> }) {
  const rows = polled.data?.rows;
  if (!rows) return null;
  const acked = rows.filter((p) => p.status === "acked" || p.ack).length;
  const waiting = rows.filter(needsAck).length;
  return (
    <StatusChip tone={waiting ? "warn" : rows.length ? "pass" : "na"} icon={BellRing}>
      {rows.length} page{rows.length === 1 ? "" : "s"}
      {rows.length ? ` · ${acked} acked` : ""}
      {waiting ? ` · ${waiting} waiting` : ""}
    </StatusChip>
  );
}

/**
 * The real pages for this incident (who was paged, on which channel, the ack state), under the notify list. The
 * notify list says who to tell; this says who was actually told and whether they answered.
 */
export function IncidentPages({ polled, tenant }: { polled: Polled<PagesList>; tenant: string }) {
  const rows = polled.data?.rows ?? [];
  return (
    <div className="mt-3 space-y-2 border-t border-white/[0.06] pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13px] font-medium text-zinc-100">Pages sent</h3>
        <Link
          href={`/oncall?tenant=${encodeURIComponent(tenant)}`}
          className="ml-auto inline-flex items-center gap-1 rounded text-xs text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          Open the pager <ArrowUpRight aria-hidden className="size-3.5" />
        </Link>
      </div>
      {polled.error ? <PanelError error={polled.error} what="this incident's pages (GET /api/pages)" stale={!!polled.data} /> : null}
      {polled.loading && !polled.data && !polled.error ? (
        <p className="flex items-center gap-2 text-xs text-zinc-300">
          <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" /> Reading pages from FalkorDB…
        </p>
      ) : null}
      {polled.data ? <ChannelNote channels={polled.data.channels} /> : null}
      {polled.data && rows.length === 0 ? <p className="text-xs text-zinc-300">No page sent for this incident yet.</p> : null}
      {rows.length ? (
        <ul aria-label="Pages sent for this incident" className="space-y-1.5">
          {rows.map((p) => (
            <li key={p.id} className="rounded-lg bg-white/[0.02] px-2.5 py-2 text-xs ring-1 ring-white/[0.06]">
              <div className="flex flex-wrap items-center gap-1.5">
                <PageStatusChip status={p.status} kind={p.kind} />
                <span className="font-medium text-zinc-100">{p.person?.name ?? p.person?.id ?? "nobody recorded"}</span>
                {p.person?.name ? <span className="font-mono text-[11px] text-zinc-400">{p.person.id}</span> : null}
                <span className="text-zinc-400">· {channelText(p.channels.length ? p.channels : p.channel)}</span>
                {p.attempt !== null && p.attempt > 1 ? <span className="text-zinc-400">· attempt {p.attempt}</span> : null}
                <Link
                  href={`/oncall/page/${encodeURIComponent(p.id)}?tenant=${encodeURIComponent(tenant)}`}
                  className="ml-auto rounded font-mono text-[11px] text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
                  aria-label={`Open page ${p.id}`}
                >
                  {p.id}
                </Link>
              </div>
              <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-zinc-400">
                <SentAgo at={p.sentAt} />
                {needsAck(p) ? <AckDue dueAt={p.ackDueAt} /> : null}
                {p.ack ? (
                  <span className="text-emerald-200">
                    acked{p.ack.by ? ` by ${p.ack.by.name ?? p.ack.by.id}` : ""}
                    {p.ack.at !== null ? ` at ${fmtClock(p.ack.at).slice(0, 8)}` : ""}
                  </span>
                ) : null}
              </p>
              <div className="mt-0.5">
                <DeliveryProblems page={p} />
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
