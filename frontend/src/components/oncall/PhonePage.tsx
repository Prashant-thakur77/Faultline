"use client";

import Link from "next/link";
import { sentence } from "@/lib/format";
import { AlarmClock, ArrowRight, ChevronDown, ChevronsUp, CircleCheck, LoaderCircle, Route, Users } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { fmtBreach } from "@/components/incident/ObligationsCard";
import { StatusChip } from "@/components/StatusChip";
import { usePolled } from "@/hooks/usePolled";
import { ApiError } from "@/lib/api";
import { fmtWhen, needsAck, oncallApi, personText, type PageDetail } from "@/lib/oncall";
import { tenantGraph, useTenant } from "@/lib/tenant";
import { cn } from "@/lib/utils";
import { AckControl } from "./AckControl";
import { Avatar, channelText, PageStatusChip, PanelError, UrgencyChip, useOpenQuery } from "./bits";
import { AckDue, SentAgo } from "./Countdown";
import { PageChain } from "./PageChain";
import { DeliveryProblems } from "./PagerInbox";

const KIND_TEXT: Record<string, string> = {
  escalation: "escalation",
  report: "report",
  contract_notice: "contract notice",
};

/**
 * /oncall/page/[id]: the page as the person paged sees it, phone first. The verdict line, the time to SLO breach and
 * the ack window, one large Ack (signed with the link's token), then why (the proof path), who fixes it and the
 * escalation so far. Re-read every 10 s while visible, so an ack or escalation elsewhere shows here.
 */
export function PhonePage({ pageId, token }: { pageId: string; token: string | null }) {
  const tenant = useTenant();
  const polled = usePolled(`page|${tenant}|${pageId}`, (s) => oncallApi.page(pageId, tenant, s), { intervalMs: 10_000 });
  const d = polled.data;

  if (!d) {
    return (
      <div className="mx-auto w-full max-w-[560px] px-4 py-6 sm:px-6">
        <p className="font-mono text-[11px] tracking-[0.2em] text-[var(--fl-subtle)] uppercase">Faultline page</p>
        <h1 className="mt-2 text-2xl font-[560] tracking-[-0.02em] text-zinc-50">Page {pageId}</h1>
        <div className="mt-4">
          {polled.error ? (
            polled.error instanceof ApiError && polled.error.status === 404 && !/^not found$/i.test(polled.error.detail.trim()) ? (
              <p role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-100 ring-1 ring-red-500/40">
                No page {pageId} in {tenantGraph(tenant)}: {polled.error.detail}
              </p>
            ) : (
              <PanelError error={polled.error} what="this page (GET /api/pages/{id})" />
            )
          ) : (
            <p className="flex items-center gap-2 text-sm text-zinc-300">
              <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> Reading the page from FalkorDB…
            </p>
          )}
        </div>
      </div>
    );
  }
  return <PageBody d={d} tenant={tenant} token={token} stale={!!polled.error} error={polled.error} onChanged={polled.refresh} />;
}

function PageBody({
  d,
  tenant,
  token,
  stale,
  error,
  onChanged,
}: {
  d: PageDetail;
  tenant: string;
  token: string | null;
  stale: boolean;
  error: unknown;
  onChanged: () => void;
}) {
  const open = useOpenQuery(tenant);
  const p = d.page;
  const waiting = needsAck(p);
  const title = d.incident?.title ?? p.incidentTitle ?? (p.incident ? `Incident ${p.incident}` : `Page ${p.id}`);
  const line = d.incident?.line ?? null;
  const incident = d.incident?.id ?? p.incident;
  // the link's own token first; else the one the server handed this console (off the public demo, or the run's owner)
  const ackToken = token ?? p.ackToken;

  return (
    <article aria-labelledby="page-title" className="mx-auto w-full max-w-[560px] space-y-4 px-4 py-5 sm:px-6 sm:py-8">
      <header className="space-y-3">
        <p className="font-mono text-[11px] tracking-[0.2em] text-[var(--fl-subtle)] uppercase">
          Faultline page{p.kind && KIND_TEXT[p.kind] ? ` · ${KIND_TEXT[p.kind]}` : ""}
        </p>
        <div className="flex flex-wrap items-center gap-1.5" aria-live="polite">
          <UrgencyChip urgency={p.urgency} />
          <PageStatusChip status={p.status} kind={p.kind} />
        </div>
        <h1 id="page-title" className="text-[26px] font-[560] leading-[1.15] tracking-[-0.02em] break-words text-zinc-50 sm:text-[30px]">
          {title}
        </h1>
        {line ? <p className="text-[15px] leading-relaxed break-words text-zinc-300">{line}</p> : null}
        {d.incident?.cause ? (
          <p className="text-sm text-zinc-400">
            Cause: <span className="font-mono break-all text-zinc-100">{d.incident.cause}</span>
          </p>
        ) : null}
      </header>

      {stale ? <PanelError error={error} what="this page (GET /api/pages/{id})" stale /> : null}

      <dl className="grid grid-cols-2 gap-2">
        <div className="fl-card rounded-2xl px-4 py-3">
          <dt className="flex items-center gap-1 text-xs text-zinc-400">
            <AlarmClock aria-hidden className="size-3.5" /> time to SLO breach
          </dt>
          <dd className="mt-1 font-mono text-xl leading-tight text-zinc-50">{fmtBreach(d.breachInMin)}</dd>
          {d.breachSlo ? <dd className="mt-0.5 truncate font-mono text-[11px] text-zinc-400">{d.breachSlo}</dd> : null}
        </div>
        <div className="fl-card rounded-2xl px-4 py-3">
          <dt className="text-xs text-zinc-400">{p.ack ? "acked" : "ack window"}</dt>
          <dd className="mt-1 text-[15px] leading-tight text-zinc-50">
            {p.ack ? (
              <span className="inline-flex items-center gap-1 text-emerald-200">
                <CircleCheck aria-hidden className="size-4" />
                {p.ack.at !== null ? fmtWhen(p.ack.at) : "yes"}
              </span>
            ) : waiting ? (
              <AckDue dueAt={p.ackDueAt} />
            ) : (
              <span className="text-zinc-300">closed</span>
            )}
          </dd>
          {p.ack?.by ? <dd className="mt-0.5 truncate text-[11px] text-zinc-400">by {p.ack.by.name ?? p.ack.by.id}</dd> : null}
        </div>
      </dl>

      <div className="space-y-2.5">
        {waiting ? (
          <AckControl pageId={p.id} tenant={tenant} token={ackToken} incident={incident} big onAcked={onChanged} />
        ) : p.ack ? (
          <p role="status" className="flex items-center justify-center gap-2 rounded-full bg-emerald-500/10 py-3.5 text-base font-medium text-emerald-100 ring-1 ring-emerald-400/40">
            <CircleCheck aria-hidden className="size-5" /> Acked: the escalation stopped.
          </p>
        ) : (
          <p role="status" className="flex items-center justify-center gap-2 rounded-full bg-white/[0.03] py-3.5 text-sm text-zinc-300 ring-1 ring-white/10">
            This page is no longer open ({p.status ?? "status not recorded"}).
          </p>
        )}
        {waiting && !ackToken ? (
          <p className="text-center text-xs text-zinc-400">This link carries no ack token, so the server will ask for the approver key.</p>
        ) : null}
        {p.reason ? <p className="text-center text-xs break-words text-zinc-400">Why you: {sentence(p.reason)}</p> : null}
        <DeliveryProblems page={p} />
        {incident ? (
          <Link
            href={`/incidents/${encodeURIComponent(incident)}?tenant=${encodeURIComponent(tenant)}`}
            className="fl-press flex h-12 w-full items-center justify-center gap-2 rounded-full text-[15px] font-medium text-zinc-100 ring-1 ring-white/15 outline-none hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            Open the incident <ArrowRight aria-hidden className="size-4" />
          </Link>
        ) : null}
        <p className="text-center text-xs text-zinc-400">
          To {personText(p.person)} · {channelText(p.channels.length ? p.channels : p.channel)}
          {p.attempt !== null ? ` · attempt ${p.attempt}` : ""} · <SentAgo at={p.sentAt} />
        </p>
      </div>

      <Card
        id="proof"
        icon={Route}
        title="Why: the proof path"
        via={
          d.proof?.query?.template ? (
            <ViaFalkor template={d.proof.query.template} compact label="the proof path" onOpen={() => open(d.proof!.query, "proof path", `GET /api/pages/${p.id}`)} />
          ) : null
        }
      >
        {d.proof ? (
          <ol aria-label="Proof path, cause first" className="space-y-1">
            {d.proof.nodes.map((n, i) => (
              <li key={`${n}:${i}`} className="text-sm">
                <span
                  className={cn(
                    "inline-block max-w-full rounded-md px-2 py-1 font-mono text-[13px] break-all",
                    i === 0 ? "bg-red-500/10 text-red-100 ring-1 ring-red-400/40" : "bg-white/[0.04] text-zinc-100 ring-1 ring-white/[0.08]",
                  )}
                >
                  {n}
                  {i === 0 ? <span className="font-sans text-[11px] text-red-200"> (cause)</span> : null}
                </span>
                {i < d.proof!.nodes.length - 1 ? (
                  <span className="flex items-center gap-1 py-0.5 pl-3 text-[11px] text-zinc-400">
                    <ChevronDown aria-hidden className="size-3.5" />
                    {d.proof!.rels[i] ? <span className="font-mono">{d.proof!.rels[i]}</span> : <span className="sr-only">then</span>}
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-zinc-300">No proof path came with this page: the incident has no confirmed cause yet, so open it to see the gate.</p>
        )}
      </Card>

      <Card
        id="pagewho"
        icon={Users}
        title="Who fixes it"
        via={
          d.whoFixesQuery?.template ? (
            <ViaFalkor template={d.whoFixesQuery.template} compact label="who fixes it" onOpen={() => open(d.whoFixesQuery, "who fixes it", `GET /api/pages/${p.id}`)} />
          ) : null
        }
      >
        {d.whoFixes.length ? (
          <ol aria-label="People ranked by the graph" className="space-y-2">
            {d.whoFixes.slice(0, 3).map((w, i) => (
              <li key={w.person.id} className="flex min-w-0 items-start gap-3">
                <Avatar name={w.person.name} id={w.person.id} />
                <div className="min-w-0">
                  <p className="text-sm text-zinc-50">
                    <span className="font-medium">{w.person.name ?? w.person.id}</span>
                    {w.person.name ? <span className="font-mono text-[11px] text-zinc-400"> {w.person.id}</span> : null}
                    {i === 0 ? <StatusChip tone="info" className="ml-1.5 align-middle">top</StatusChip> : null}
                  </p>
                  {w.reasons.length ? <p className="text-xs break-words text-zinc-400">{w.reasons.slice(0, 2).join(" · ")}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-zinc-300">No ranking came with this page.</p>
        )}
      </Card>

      <Card
        id="pagechain"
        icon={ChevronsUp}
        title="Escalation so far"
        via={
          d.chainQuery?.template ? (
            <ViaFalkor template={d.chainQuery.template} compact label="the escalation chain" onOpen={() => open(d.chainQuery, `escalation chain of ${p.id}`, `GET /api/pages/${p.id}`)} />
          ) : null
        }
      >
        <PageChain steps={d.chain} current={p.id} label={`Escalation chain of ${p.id}`} />
      </Card>
    </article>
  );
}

function Card({
  id,
  icon: Icon,
  title,
  via,
  children,
}: {
  id: string;
  icon: typeof Route;
  title: string;
  via?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-h`} className="fl-card rounded-2xl px-4 py-4 sm:px-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 id={`${id}-h`} className="flex items-center gap-1.5 text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
          <Icon aria-hidden className="size-4 text-[var(--fl-subtle)]" /> {title}
        </h2>
        {via ? <div className="ml-auto">{via}</div> : null}
      </div>
      {children}
    </section>
  );
}
