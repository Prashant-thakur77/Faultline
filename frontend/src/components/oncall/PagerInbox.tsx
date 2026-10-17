"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Inbox, LoaderCircle, Radio, Smartphone, TriangleAlert } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import type { Polled } from "@/hooks/usePolled";
import { fmtClock } from "@/lib/format";
import {
  externalChannels,
  needsAck,
  oncallApi,
  personText,
  type ChainStep,
  type ChannelInfo,
  type PageRow,
  type PagesList,
} from "@/lib/oncall";
import { cn } from "@/lib/utils";
import { AckControl } from "./AckControl";
import { Avatar, channelText, PageStatusChip, PanelError, UrgencyChip, useOpenQuery } from "./bits";
import { AckDue, SentAgo } from "./Countdown";
import { PageChain } from "./PageChain";

export const PAGES_POLL_MS = 5000;

const KIND_TEXT: Record<string, string> = {
  page: "page",
  escalation: "escalation",
  report: "report",
  contract_notice: "contract notice",
};

/**
 * Where pages go. In-app always; external channels only when the API reports them configured. When the API does
 * not report its channels at all, that is said too (nothing is assumed).
 */
export function ChannelNote({ channels }: { channels: ChannelInfo[] | null }) {
  const ext = externalChannels(channels);
  if (ext === null) {
    return <p className="text-xs text-[var(--fl-subtle)]">This API does not report its delivery channels.</p>;
  }
  if (!ext.length) {
    return (
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-300">
        <StatusChip tone="info" icon={Smartphone}>
          in-app only
        </StatusChip>
        No external channel configured: pages are in-app only.
      </p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-300">
      <StatusChip tone="pass" icon={Radio}>
        {ext.length + 1} channels
      </StatusChip>
      Delivered in-app and by {ext.map((c) => channelText(c.channel)).join(", ")}.
    </p>
  );
}

/**
 * The live pager inbox: every (:Page) of the tenant from GET /api/pages, newest first as the server orders them,
 * re-read every 5 s while the tab is visible. Status, urgency, who was paged, the ack window, Ack, and each page's
 * escalation chain (Q-PAGE-CHAIN, read on demand).
 */
export function PagerInbox({ polled, tenant }: { polled: Polled<PagesList>; tenant: string }) {
  const open = useOpenQuery(tenant);
  const [filter, setFilter] = useState<"open" | "all">("open");
  const data = polled.data;
  const rows = data?.rows ?? [];
  const waiting = rows.filter(needsAck);
  const shown = filter === "open" ? waiting : rows;

  return (
    <Section
      id="pager"
      title="Pager inbox"
      via={
        data?.template ? (
          <ViaFalkor template={data.template} label="the pager inbox" onOpen={() => open(data, "pager inbox", "GET /api/pages")} />
        ) : null
      }
      aside={
        polled.error && data ? (
          <StatusChip tone="warn" icon={TriangleAlert}>
            updates paused
          </StatusChip>
        ) : data ? (
          <StatusChip tone="info" icon={Radio} title={polled.at ? `last read ${fmtClock(polled.at)}` : undefined}>
            live · every {PAGES_POLL_MS / 1000} s
          </StatusChip>
        ) : null
      }
    >
      <p className="sr-only" aria-live="polite">
        {data ? `${waiting.length} page${waiting.length === 1 ? "" : "s"} waiting for an ack` : ""}
      </p>
      {polled.error ? <PanelError error={polled.error} what="the pager (GET /api/pages)" stale={!!data} /> : null}
      {polled.loading && !data && !polled.error ? (
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> Reading pages from FalkorDB…
        </p>
      ) : null}
      {data ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div role="group" aria-label="Show pages" className="inline-flex rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]">
              {(
                [
                  ["open", `Needs ack · ${waiting.length}`],
                  ["all", `All · ${rows.length}`],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={filter === k}
                  onClick={() => setFilter(k)}
                  className={cn(
                    "h-7 rounded-full px-3 text-xs outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
                    filter === k ? "bg-zinc-50 font-medium text-zinc-950" : "text-zinc-300 hover:text-zinc-50",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <ChannelNote channels={data.channels} />
          </div>
          {data.truncated ? <StatusChip tone="warn">truncated at the query LIMIT: older pages are not listed</StatusChip> : null}
          {shown.length === 0 ? (
            <div className="flex items-center gap-3 rounded-xl bg-white/[0.02] px-4 py-5 ring-1 ring-white/[0.05]">
              <Inbox aria-hidden className="size-5 shrink-0 text-[var(--fl-subtle)]" />
              <p className="text-sm text-zinc-300">
                {filter === "open"
                  ? rows.length
                    ? "Nothing waits for an ack. Every page in the graph has been acked, escalated or resolved."
                    : "No page in the graph yet. A confirmed incident pages whoever is on call for the owning team."
                  : "No page in the graph yet."}
              </p>
            </div>
          ) : (
            <ul aria-label={filter === "open" ? "Pages waiting for an ack" : "All pages"} className="space-y-2">
              {shown.map((p) => (
                <PageItem key={p.id} page={p} tenant={tenant} onChanged={polled.refresh} />
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </Section>
  );
}

function PageItem({ page: p, tenant, onChanged }: { page: PageRow; tenant: string; onChanged: () => void }) {
  const open = useOpenQuery(tenant);
  const waiting = needsAck(p);
  const who = p.person ? personText(p.person) : "nobody recorded";
  return (
    <li
      className={cn(
        "rounded-xl px-3.5 py-3 ring-1",
        waiting ? (p.urgency === "urgent" ? "bg-red-500/[0.04] ring-red-400/25" : "bg-amber-500/[0.03] ring-amber-300/20") : "bg-white/[0.02] ring-white/[0.06]",
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <Avatar name={p.person?.name} id={p.person?.id ?? "?"} className="mt-0.5 hidden sm:inline-flex" />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <PageStatusChip status={p.status} kind={p.kind} />
            <UrgencyChip urgency={p.urgency} />
            {p.kind && p.kind !== "page" ? <StatusChip tone="na">{KIND_TEXT[p.kind] ?? p.kind}</StatusChip> : null}
            {p.attempt !== null && p.attempt > 1 ? <span className="text-[11px] text-zinc-400">attempt {p.attempt}</span> : null}
          </div>
          <p className="text-sm break-words text-zinc-50">
            <span className="font-medium">{p.person?.name ?? p.person?.id ?? "Nobody recorded"}</span>
            {p.person?.name ? <span className="font-mono text-[11px] text-zinc-400"> {p.person.id}</span> : null}
            <span className="text-zinc-400"> · {channelText(p.channels.length ? p.channels : p.channel)}</span>
          </p>
          {p.reason ? <p className="text-[11px] break-words text-zinc-400">Why them: {p.reason}</p> : null}
          {p.incident ? (
            <p className="text-xs break-words text-zinc-300">
              <Link
                href={`/incidents/${encodeURIComponent(p.incident)}?tenant=${encodeURIComponent(tenant)}`}
                className="rounded font-mono text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                {p.incident}
              </Link>
              {p.incidentTitle ? <span> · {p.incidentTitle}</span> : null}
            </p>
          ) : null}
          <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-zinc-400">
            <SentAgo at={p.sentAt} />
            {waiting ? <AckDue dueAt={p.ackDueAt} /> : null}
            {p.ack ? (
              <span className="text-emerald-200">
                acked{p.ack.by ? ` by ${p.ack.by.name ?? p.ack.by.id}` : ""}
                {p.ack.at !== null ? ` at ${fmtClock(p.ack.at).slice(0, 8)}` : ""}
                {p.ack.via ? ` via ${p.ack.via}` : ""}
              </span>
            ) : null}
            {p.escalatedTo ? <span>escalated to {p.escalatedTo}</span> : null}
          </p>
          <DeliveryProblems page={p} />
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-2 sm:pl-11">
        {waiting ? <AckControl pageId={p.id} tenant={tenant} token={p.ackToken} incident={p.incident} who={who} onAcked={onChanged} /> : null}
        <Link
          href={`/oncall/page/${encodeURIComponent(p.id)}?tenant=${encodeURIComponent(tenant)}`}
          className="inline-flex h-8 items-center gap-1 rounded-full px-3 text-[13px] text-zinc-200 ring-1 ring-white/10 outline-none hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400"
          aria-label={`Open page ${p.id}, as the person paged sees it`}
        >
          Open page <ArrowUpRight aria-hidden className="size-3.5" />
        </Link>
      </div>
      <ChainDisclosure page={p} tenant={tenant} onOpenQuery={(steps) => open({ template: "Q-PAGE-CHAIN", params: null, ms: null }, `escalation chain of ${p.id} (${steps} steps)`, `GET /api/pages/${p.id}`)} />
    </li>
  );
}

/** Channels that did not take the page (the server's per-channel result), or the page's own delivery detail. */
export function DeliveryProblems({ page: p }: { page: PageRow }) {
  const failed = p.delivery.filter((d) => d.ok === false);
  if (failed.length) {
    return (
      <p className="text-[11px] break-words text-red-200">
        Not delivered by {failed.map((d) => `${channelText(d.channel)}${d.detail ? ` (${d.detail})` : ""}`).join(", ")}; it stays in the in-app pager.
      </p>
    );
  }
  return p.status === "delivery_failed" && p.detail ? <p className="text-[11px] break-words text-red-200">Delivery: {p.detail}</p> : null;
}

/** The escalation chain, read on first open (GET /api/pages/{id}) unless the list already carried it. */
function ChainDisclosure({ page, tenant, onOpenQuery }: { page: PageRow; tenant: string; onOpenQuery: (steps: number) => void }) {
  const [state, setState] = useState<{ steps: ChainStep[] | null; error: unknown; busy: boolean }>({
    steps: page.chain,
    error: null,
    busy: false,
  });
  const steps = page.chain ?? state.steps;
  const load = () => {
    if (steps || state.busy) return;
    setState((s) => ({ ...s, busy: true, error: null }));
    oncallApi.page(page.id, tenant).then(
      (d) => setState({ steps: d.chain, error: null, busy: false }),
      (e: unknown) => setState({ steps: null, error: e, busy: false }),
    );
  };
  return (
    <div className="mt-2 sm:pl-11">
      <Disclosure
        size="xs"
        defaultOpen={false}
        onToggle={(o) => o && load()}
        summary={<>Escalation chain{steps ? <span className="text-[var(--fl-subtle)]"> · {steps.length}</span> : null}</>}
        actions={
          steps ? (
            <button
              type="button"
              onClick={() => onOpenQuery(steps.length)}
              className="inline-flex min-h-6 items-center rounded px-1 font-mono text-[11px] whitespace-nowrap text-zinc-400 outline-none hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400"
              aria-label={`Q-PAGE-CHAIN: open the Cypher panel for the escalation chain of ${page.id}`}
            >
              Q-PAGE-CHAIN
            </button>
          ) : null
        }
      >
        <div className="pt-1">
          {state.busy ? (
            <p className="flex items-center gap-2 text-xs text-zinc-300">
              <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" /> Reading the chain…
            </p>
          ) : state.error ? (
            <PanelError error={state.error} what="the escalation chain (GET /api/pages/{id})" />
          ) : steps ? (
            <PageChain steps={steps} current={page.id} label={`Escalation chain of ${page.id}`} />
          ) : null}
        </div>
      </Disclosure>
    </div>
  );
}
