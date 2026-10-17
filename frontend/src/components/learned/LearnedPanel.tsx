"use client";

import { useId, useMemo, useState } from "react";
import { GraduationCap, LoaderCircle, OctagonAlert, ShieldCheck, Unplug } from "lucide-react";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { usePolled } from "@/hooks/usePolled";
import { ApiError, errorText } from "@/lib/api";
import { fmtAgo } from "@/lib/format";
import { knownPeople, learnedApi, type LearnedState } from "@/lib/learned";
import { endpointMissing } from "@/lib/oncall";
import { useTenant } from "@/lib/tenant";
import { cn } from "@/lib/utils";
import { ForgetCard } from "./ForgetCard";
import { EventsCard, PreferencesCard, RespondersCard, SuggestionsCard } from "./LearnedCards";
import { GapsCard, GuidelinesCard, type Acting } from "./LearnedControls";

export const LEARNED_POLL_MS = 30_000;

type Card = "guidelines" | "gaps";

/**
 * "What Faultline has learned" (M21, T2): what the people using Faultline taught it, read in one request from the
 * tenant's on-call home graph (GET /api/learned), each section with the FalkorDB query that produced it. Preferences,
 * guidelines (promote / dismiss), learned responders, knowledge gaps (dismiss), standing approvals to consider, the
 * recent learning events, and forgetting a person's influence with a receipt. Learning only reorders, suggests and
 * annotates: the gate, approvals and contracts keep their rules. Fails loudly; never shows sample data.
 */
export function LearnedPanel() {
  const tenant = useTenant();
  const listId = useId();
  const polled = usePolled(`learned|${tenant}`, (sig) => learnedApi.state(tenant, sig), { intervalMs: LEARNED_POLL_MS });
  const data = polled.data;
  // who acts pre-fills every control's person field (the approver key never pre-fills: typed per change)
  const [actor, setActor] = useState("");
  const [notice, setNotice] = useState<{ tenant: string; card: Card; text: string } | null>(null);
  const said = (card: Card) => (notice && notice.tenant === tenant && notice.card === card ? notice.text : null);
  const people = useMemo(() => knownPeople(data), [data]);
  // "ago" is measured from the server clock the decays were computed at; else from when this answer was read
  const now = data?.now ?? polled.at ?? 0;

  const acting = (card: Card): Acting => ({
    actor,
    onActor: setActor,
    listId,
    publicDemo: data?.trust.public ?? null,
    onChanged: (text) => {
      setNotice({ tenant, card, text });
      polled.refresh();
    },
  });

  return (
    <section id="learned" aria-labelledby="learned-h" className="mx-auto w-full max-w-[1400px] scroll-mt-20 space-y-4 px-5 pb-10 sm:px-8">
      <LearnedVerdict data={data} error={polled.error} loading={polled.loading} />
      <datalist id={listId}>
        {people.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name ? `${p.name} (${p.id})` : p.id}
          </option>
        ))}
      </datalist>
      {polled.error ? <LearnedError error={polled.error} stale={!!data} /> : null}
      {data ? (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
            <div className="min-w-0 space-y-4">
              <GuidelinesCard s={data} tenant={tenant} now={now} acting={acting("guidelines")} notice={said("guidelines")} />
              <PreferencesCard s={data} tenant={tenant} now={now} />
            </div>
            <div className="min-w-0 space-y-4">
              <SuggestionsCard s={data} tenant={tenant} now={now} />
              <RespondersCard s={data} tenant={tenant} now={now} />
              <GapsCard s={data} tenant={tenant} now={now} acting={acting("gaps")} notice={said("gaps")} />
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
            <div className="min-w-0">
              <EventsCard s={data} tenant={tenant} now={now} />
            </div>
            <div className="min-w-0">
              <ForgetCard s={data} tenant={tenant} now={now} listId={listId} actor={actor} onActor={setActor} onForgotten={polled.refresh} />
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

/** One honest sentence for a failed read: the endpoint missing, the API down, FalkorDB down, or an HTTP error. */
export function learnedErrorText(err: unknown): string {
  const what = "What Faultline learned (GET /api/learned)";
  if (!(err instanceof ApiError)) return `${what} failed: ${errorText(err)}`;
  const d = err.detail.replace(/\.$/, "");
  if (endpointMissing(err)) return `${what}: this API has no such endpoint (HTTP ${err.status}), so the learning backend is not deployed on this server.`;
  if (err.status === null) return `${what} is unavailable: ${d}.`;
  if (err.status === 503) return `${what} is unavailable: ${d} (HTTP 503). Nothing is shown in its place.`;
  return `${what} failed: ${d} (HTTP ${err.status}).`;
}

function LearnedError({ error, stale }: { error: unknown; stale: boolean }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-100 ring-1 ring-red-500/40">
      <OctagonAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
      <span>
        {learnedErrorText(error)}
        {stale ? " Showing the last answer the server gave; it may be out of date." : ""}
      </span>
    </p>
  );
}

/** Totals for the verdict line, all from the server's rows and counts. */
export function learnedSummary(s: LearnedState) {
  const events = s.events.counts.reduce((a, c) => a + (c.n ?? 0), 0);
  const newest = s.events.counts.reduce<number | null>((m, c) => (c.lastAt !== null && (m === null || c.lastAt > m) ? c.lastAt : m), null);
  const proposed = s.guidelines.rows.filter((g) => g.status === "proposed").length;
  const active = s.guidelines.rows.filter((g) => g.status === "active").length;
  const gaps = s.gaps.rows.filter((g) => g.status === "open").length;
  const suggested = s.suggestions.rows.filter((r) => !r.coveredBy).length;
  const empty =
    events === 0 &&
    !s.events.rows.length &&
    !s.preferences.rows.length &&
    !s.guidelines.rows.length &&
    !s.responders.rows.length &&
    !s.gaps.rows.length &&
    !s.suggestions.rows.length;
  return { events, newest, proposed, active, gaps, suggested, empty };
}

/** One sentence first: has Faultline learned anything, and does anything wait for a human decision? */
export function LearnedVerdict({ data, error, loading }: { data: LearnedState | null; error: unknown; loading: boolean }) {
  let icon = <LoaderCircle aria-hidden className="size-6 text-zinc-400 motion-safe:animate-spin" />;
  let head = "Reading what Faultline learned from FalkorDB…";
  let tone = "bg-zinc-600";
  let sub: string | null = null;
  if (!data && error) {
    icon = endpointMissing(error) ? <Unplug aria-hidden className="size-6 text-red-300" /> : <OctagonAlert aria-hidden className="size-6 text-red-300" />;
    head = endpointMissing(error)
      ? "Learning is not on this server: its API has no /api/learned endpoint"
      : "What Faultline learned is unavailable: see below";
    tone = "bg-red-400";
  } else if (data) {
    const t = learnedSummary(data);
    if (t.empty) {
      icon = <GraduationCap aria-hidden className="size-6 text-zinc-300" />;
      head = "Nothing learned yet";
      tone = "bg-zinc-500";
      sub =
        "Faultline learns only from trusted people: approvals, rejections with a reason, acks and verified fixes, and brain questions the graph could not answer.";
    } else {
      const waiting = [
        t.proposed ? `${t.proposed} guideline${t.proposed === 1 ? "" : "s"} wait${t.proposed === 1 ? "s" : ""} for a decision` : null,
        t.suggested ? `${t.suggested} standing approval${t.suggested === 1 ? "" : "s"} suggested` : null,
        t.gaps ? `${t.gaps} open knowledge gap${t.gaps === 1 ? "" : "s"}` : null,
      ].filter(Boolean);
      icon = waiting.length ? (
        <GraduationCap aria-hidden className="size-6 text-amber-300" />
      ) : (
        <ShieldCheck aria-hidden className="size-6 text-emerald-300" />
      );
      tone = waiting.length ? "bg-amber-300" : "bg-emerald-400";
      head = `Learned from ${t.events} event${t.events === 1 ? "" : "s"}${t.newest !== null && data.now !== null ? `, newest ${fmtAgo(t.newest, data.now)}` : ""}`;
      sub = waiting.length ? waiting.join(" · ") : "Nothing waits for a decision.";
      if (t.active) sub += ` · ${t.active} active guideline${t.active === 1 ? "" : "s"}`;
    }
  } else if (!loading) {
    head = "No answer from the learning API yet";
  }
  return (
    <div className="fl-card relative overflow-hidden rounded-2xl px-5 py-4">
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", tone)} />
      <div className="flex flex-wrap items-start gap-x-5 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-[18rem] items-start gap-3">
          <span className="mt-0.5 shrink-0">{icon}</span>
          <div className="min-w-0">
            <h2 id="learned-h" className="text-xs font-medium tracking-wide text-[var(--fl-subtle)] uppercase">
              What Faultline has learned
            </h2>
            <p aria-live="polite" className="mt-0.5 text-[17px] font-[560] leading-snug tracking-[-0.01em] text-zinc-50 sm:text-lg">
              {head}
            </p>
            {sub ? <p className="mt-0.5 text-xs text-zinc-400">{sub}</p> : null}
          </div>
        </div>
        {data ? (
          <div className="flex w-full min-w-0 flex-col items-start gap-1 text-xs text-zinc-400 sm:w-auto sm:max-w-[45%] sm:items-end sm:text-right">
            <p>
              Reading <span className="font-mono text-zinc-200">{data.home ?? "the on-call home graph"}</span>
              {data.halfLifeDays !== null ? ` · half-life ${data.halfLifeDays} days` : ""}
            </p>
            {data.trust.public ? (
              <StatusChip tone="info" icon={ShieldCheck}>
                public demo: changes need the approver key
              </StatusChip>
            ) : null}
          </div>
        ) : null}
      </div>
      {data?.trust.rule ? (
        <Disclosure className="mt-2" size="xs" defaultOpen={false} summary="Who Faultline learns from">
          <p className="text-xs leading-relaxed text-zinc-300">
            {data.trust.rule.replace(/[.\s]*$/, ".")} Learning only reorders, suggests and annotates: the evidence gate, the
            two-step approval and contracts keep their rules.
          </p>
        </Disclosure>
      ) : null}
    </div>
  );
}
