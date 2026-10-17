"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Ban,
  BellRing,
  ChevronsUp,
  CircleCheck,
  CircleHelp,
  FileSignature,
  Hand,
  Moon,
  MousePointerClick,
  Repeat,
  ShieldAlert,
  ShieldCheck,
  Stamp,
  ThumbsDown,
  type LucideIcon,
} from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { Avatar } from "@/components/oncall/bits";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { fmtAgo } from "@/lib/format";
import type { Tone } from "@/lib/gate";
import {
  eventWord,
  fmtDecayed,
  fmtPref,
  kindWord,
  type LearnEventKind,
  type LearnedState,
  type PreferenceRow,
  type ResponderRow,
  type SuggestionRow,
} from "@/lib/learned";
import { fmtDuration, personText } from "@/lib/oncall";
import { cn } from "@/lib/utils";
import { Empty, Truncated, useOpenLearned } from "./bits";

const incHref = (inc: string, tenant: string) => `/incidents/${encodeURIComponent(inc)}?tenant=${encodeURIComponent(tenant)}`;

const LINK = "rounded font-mono whitespace-nowrap text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400";

function ago(at: number | null, now: number): string {
  return at === null ? "–" : fmtAgo(at, now);
}

/** The provenance of a derived item: the LearnEvent ids it rests on (folded). */
function Provenance({ events, what }: { events: string[]; what: string }) {
  if (!events.length) return null;
  return (
    <Disclosure
      className="mt-1"
      size="xs"
      defaultOpen={false}
      summary={
        <>
          from {events.length} learning event{events.length === 1 ? "" : "s"}
        </>
      }
    >
      <p className="font-mono text-[11px] break-all text-zinc-400">
        <span className="sr-only">Learning events behind {what}: </span>
        {events.join(", ")}
      </p>
    </Disclosure>
  );
}

// ------------------------------------------------------------------ preferences

/** A preference as a bar plus its number (the bar is decorative; the words carry it). */
function PrefMeter({ value }: { value: number | null }) {
  const v = value === null ? 0 : Math.max(0, Math.min(1, value));
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-zinc-300">
      <span aria-hidden className="h-1.5 w-16 overflow-hidden rounded-full bg-white/[0.08]">
        <span className="block h-full rounded-full bg-[var(--fl-iris)]" style={{ width: `${Math.round(v * 100)}%` }} />
      </span>
      <span className="font-mono tabular-nums">preference {fmtPref(value)}</span>
    </span>
  );
}

export function PreferencesCard({ s, tenant, now }: { s: LearnedState; tenant: string; now: number }) {
  const open = useOpenLearned(tenant);
  const env = s.preferences;
  const fams = [...new Set(env.rows.map((r) => r.family))];
  return (
    <Section
      id="learned-prefs"
      level={3}
      title="Preferences"
      via={<ViaFalkor template={env.template} label="the learned preferences" onOpen={() => open(env, "learned preferences", s.home)} />}
      aside={env.rows.length ? <StatusChip tone="na">{fams.length} famil{fams.length === 1 ? "y" : "ies"}</StatusChip> : null}
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        Per incident family and fix kind, from trusted approvals and rejections, decayed with a{" "}
        {s.halfLifeDays !== null ? `${fmtDecayed(s.halfLifeDays)}-day` : ""} half-life (older choices count less). A plan
        blends them into its order once the family has enough recorded choices; the gate never sees them.
      </p>
      <Truncated env={env} />
      {env.rows.length === 0 ? (
        <Empty>No preference yet. Approvals and rejections by trusted people on incidents with a family are learned here.</Empty>
      ) : (
        <ul className="space-y-3" aria-label="Learned preferences by family">
          {fams.map((f) => {
            const rows = env.rows.filter((r) => r.family === f);
            return (
              <li key={f}>
                <p className="mb-1.5 text-xs text-zinc-400">
                  family <span className="font-mono text-zinc-100">{f}</span>
                  {rows[0].nFamily !== null ? ` · ${rows[0].nFamily} recorded choice${rows[0].nFamily === 1 ? "" : "s"}` : ""}
                </p>
                <ul className="space-y-1.5">
                  {rows.map((r) => (
                    <PreferenceItem key={r.id} r={r} now={now} />
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

function PreferenceItem({ r, now }: { r: PreferenceRow; now: number }) {
  return (
    <li className="rounded-xl bg-white/[0.02] px-3.5 py-2.5 ring-1 ring-white/[0.06]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-medium text-zinc-50">{kindWord(r.actionKind)}</span>
        <PrefMeter value={r.pref} />
        <span className="ml-auto text-[11px] text-zinc-400">last seen {ago(r.lastAt, now)}</span>
      </div>
      {r.line ? <p className="mt-1 text-xs break-words text-zinc-200">{r.line}</p> : null}
      <p className="mt-1 text-[11px] text-zinc-400">
        decayed: {fmtDecayed(r.approvals)} approval{r.approvals === 1 ? "" : "s"} · {fmtDecayed(r.rejections)} rejection
        {r.rejections === 1 ? "" : "s"} · {fmtDecayed(r.others)} other · counted: {r.nApprove ?? "–"} approved, {r.nReject ?? "–"} rejected
      </p>
      <Provenance events={r.events} what={`the ${kindWord(r.actionKind)} preference for ${r.family}`} />
    </li>
  );
}

// ------------------------------------------------------------------ responders

export function RespondersCard({ s, tenant, now }: { s: LearnedState; tenant: string; now: number }) {
  const open = useOpenLearned(tenant);
  const env = s.responders;
  return (
    <Section
      id="learned-responders"
      level={3}
      title="Who actually responds"
      via={<ViaFalkor template={env.template} label="the learned responders" onOpen={() => open(env, "learned responders", s.home)} />}
      aside={env.rows.length ? <StatusChip tone="na">{env.rows.length}</StatusChip> : null}
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        A person&apos;s acks, approvals and verified fixes for a family write a RESPONDED edge to its component. A strong
        responder is added to the first wave of pages; the rota&apos;s on-call is still paged.
      </p>
      <Truncated env={env} />
      {env.rows.length === 0 ? (
        <Empty>No responder learned yet. Acks, approvals and verified fixes by trusted people show up here.</Empty>
      ) : (
        <ul className="space-y-2" aria-label="Learned responders">
          {env.rows.map((r) => (
            <ResponderItem key={`${r.person.id}|${r.family}`} r={r} now={now} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function ResponderItem({ r, now }: { r: ResponderRow; now: number }) {
  return (
    <li className="flex gap-3 rounded-xl bg-white/[0.02] px-3.5 py-2.5 ring-1 ring-white/[0.06]">
      <Avatar name={r.person.name} id={r.person.id} />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
          <span className="font-medium text-zinc-50">{r.person.name ?? r.person.id}</span>
          {r.person.name ? <span className="font-mono text-xs text-zinc-400">{r.person.id}</span> : null}
          {r.active === false ? (
            <StatusChip tone="na" icon={Ban}>
              inactive: not paged
            </StatusChip>
          ) : null}
        </p>
        <p className="mt-0.5 text-xs text-zinc-300">
          for <span className="font-mono text-zinc-100">{r.family ?? "–"}</span> · score {fmtDecayed(r.score)} (decayed) ·{" "}
          {r.n ?? "–"} response{r.n === 1 ? "" : "s"} on {r.incidents ?? "–"} incident{r.incidents === 1 ? "" : "s"}
        </p>
        <p className="mt-0.5 text-[11px] text-zinc-400">
          {r.acks ?? "–"} ack{r.acks === 1 ? "" : "s"} · {r.approvals ?? "–"} approval{r.approvals === 1 ? "" : "s"} · {r.fixes ?? "–"} verified fix
          {r.fixes === 1 ? "" : "es"} · {r.mttaMs !== null ? `mean time to ack ${fmtDuration(r.mttaMs)}` : r.acks === 0 ? "no ack yet" : "ack time not recorded"} · last{" "}
          {ago(r.lastAt, now)}
        </p>
        <Provenance events={r.events} what={`${r.person.id} as a responder`} />
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ contract suggestions

export function SuggestionsCard({ s, tenant, now }: { s: LearnedState; tenant: string; now: number }) {
  const open = useOpenLearned(tenant);
  const env = s.suggestions;
  const pending = env.rows.filter((r) => !r.coveredBy).length;
  return (
    <Section
      id="learned-suggestions"
      level={3}
      title="Standing approvals to consider"
      via={<ViaFalkor template={env.template} label="the contract suggestions" onOpen={() => open(env, "contract suggestions", s.home)} />}
      aside={
        env.rows.length ? (
          <StatusChip tone={pending ? "info" : "pass"} icon={pending ? Moon : CircleCheck}>
            {pending ? `${pending} suggested` : "all covered"}
          </StatusChip>
        ) : null
      }
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        The same exact fix (family, action, parameters), approved by a trusted person and verified APPLIED on enough
        incidents. A suggestion grants nothing: a human grants a contract in two steps from a verified incident.
      </p>
      <Truncated env={env} />
      {env.rows.length === 0 ? (
        <Empty>No suggestion yet: no exact fix has been approved and verified often enough.</Empty>
      ) : (
        <ul className="space-y-2" aria-label="Contract suggestions">
          {env.rows.map((r) => (
            <SuggestionItem key={`${r.family}|${r.actionKind}|${r.paramsHash}`} r={r} tenant={tenant} now={now} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function SuggestionItem({ r, tenant, now }: { r: SuggestionRow; tenant: string; now: number }) {
  return (
    <li className="rounded-xl bg-white/[0.02] px-3.5 py-2.5 ring-1 ring-white/[0.06]">
      <div className="flex flex-wrap items-center gap-1.5">
        {r.coveredBy ? (
          <StatusChip tone="pass" icon={CircleCheck}>
            covered
          </StatusChip>
        ) : (
          <StatusChip tone="info" icon={Moon}>
            suggested
          </StatusChip>
        )}
        <span className="text-sm font-medium text-zinc-50">{kindWord(r.actionKind)}</span>
        <span className="text-xs text-zinc-400">for family</span>
        <span className="font-mono text-xs break-all text-zinc-200">{r.family ?? "–"}</span>
      </div>
      <p className="mt-1 text-xs text-zinc-300">
        approved and verified <span className="font-mono">APPLIED</span> on {r.n ?? "–"} incident{r.n === 1 ? "" : "s"}
        {r.people.length ? ` by ${r.people.join(", ")}` : ""} · last {ago(r.lastAt, now)}
        {r.paramsHash ? (
          <>
            {" "}
            · params{" "}
            <span className="font-mono text-zinc-400" title={r.paramsHash}>
              {r.paramsHash.slice(0, 12)}
            </span>
          </>
        ) : null}
      </p>
      {r.coveredBy ? (
        <p className="mt-1 text-[11px] text-zinc-400">
          Already covered by contract <span className="font-mono text-zinc-200">{r.coveredBy}</span>:{" "}
          <Link href={`/oncall?tenant=${encodeURIComponent(tenant)}`} className="rounded text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400">
            see it under On-call, Contracts
          </Link>
          .
        </p>
      ) : r.incidents.length ? (
        <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-zinc-400">
          <FileSignature aria-hidden className="size-3.5 text-[var(--fl-iris)]" />
          Grant it from a verified incident&apos;s room (two steps):
          {r.incidents.slice(0, 4).map((inc, i) => (
            <span key={inc}>
              <Link href={`${incHref(inc, tenant)}#plan-h`} className={LINK} aria-label={`Grant a contract from incident ${inc}`}>
                {inc}
              </Link>
              {i < Math.min(r.incidents.length, 4) - 1 ? "," : ""}
            </span>
          ))}
          {r.incidents.length > 4 ? <span>+{r.incidents.length - 4} more</span> : null}
        </p>
      ) : null}
      <Provenance events={r.events} what={`the ${kindWord(r.actionKind)} suggestion for ${r.family}`} />
    </li>
  );
}

// ------------------------------------------------------------------ recent learning events

const EVENT_META: Record<LearnEventKind, { tone: Tone; icon: LucideIcon }> = {
  approve: { tone: "pass", icon: Stamp },
  reject: { tone: "warn", icon: ThumbsDown },
  override: { tone: "warn", icon: ShieldAlert },
  verified: { tone: "pass", icon: ShieldCheck },
  ack: { tone: "info", icon: Hand },
  choose: { tone: "na", icon: MousePointerClick },
  grant: { tone: "info", icon: FileSignature },
  revoke: { tone: "warn", icon: Ban },
  handoff: { tone: "na", icon: Repeat },
  escalate_now: { tone: "warn", icon: ChevronsUp },
  gap: { tone: "na", icon: CircleHelp },
};

export function EventKindChip({ kind }: { kind: string | null }) {
  const m = kind && kind in EVENT_META ? EVENT_META[kind as LearnEventKind] : { tone: "na" as Tone, icon: BellRing };
  return (
    <StatusChip tone={m.tone} icon={m.icon}>
      {eventWord(kind)}
    </StatusChip>
  );
}

export function EventsCard({ s, tenant, now }: { s: LearnedState; tenant: string; now: number }) {
  const open = useOpenLearned(tenant);
  const env = s.events;
  const [all, setAll] = useState(false);
  const shown = all ? env.rows : env.rows.slice(0, 10);
  return (
    <Section
      id="learned-events"
      level={3}
      title="Recent learning events"
      via={<ViaFalkor template={env.template} label="the recent learning events" onOpen={() => open(env, "recent learning events", s.home)} />}
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        Every learned item rests on these events: who did what, on which family and incident, and when. Choices, grants,
        hand-offs and escalations are kept for provenance; only approvals, rejections, acks and verified fixes move a
        preference or a responder.
      </p>
      {env.counts.length ? (
        <ul className="mb-3 flex flex-wrap gap-1.5" aria-label="Learning events by kind">
          {env.counts.map((c) => (
            <li key={c.kind} className="inline-flex items-center gap-1 text-[11px] text-zinc-300">
              <EventKindChip kind={c.kind} />
              <span className="font-mono tabular-nums">{c.n ?? "–"}</span>
              {c.people !== null ? (
                <span className="text-zinc-400">
                  ({c.people} {c.people === 1 ? "person" : "people"})
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <Truncated env={env} />
      {env.rows.length === 0 ? (
        <Empty>No learning event yet.</Empty>
      ) : (
        <>
          <ol className="space-y-1.5" aria-label="Recent learning events, newest first">
            {shown.map((e) => (
              <li key={e.id} className="rounded-lg bg-white/[0.02] px-3 py-2 ring-1 ring-white/[0.05]">
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                  <EventKindChip kind={e.kind} />
                  <span className="text-zinc-100">{personText(e.person)}</span>
                  {e.family ? (
                    <span className="text-zinc-400">
                      on <span className="font-mono text-zinc-200">{e.family}</span>
                    </span>
                  ) : null}
                  <span className="ml-auto text-[11px] text-zinc-400">{ago(e.at, now)}</span>
                </p>
                <p className="mt-0.5 text-[11px] break-words text-zinc-400">
                  {[
                    e.option ?? (e.actionKind ? kindWord(e.actionKind) : null),
                    e.reason ? `“${e.reason}”` : null,
                    e.verdict ? `verdict ${e.verdict}` : null,
                    e.ackMs !== null ? `acked after ${fmtDuration(e.ackMs)}` : null,
                    e.text ? `“${e.text}”` : null,
                    e.via ? `via ${e.via}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  {e.incident ? (
                    <>
                      {" · "}
                      <Link href={incHref(e.incident, tenant)} className={cn(LINK, "text-[11px]")}>
                        {e.incident}
                      </Link>
                    </>
                  ) : null}
                  {" · "}
                  <span className="inline-block max-w-full font-mono break-all text-[var(--fl-subtle)]">{e.id}</span>
                </p>
              </li>
            ))}
          </ol>
          {env.rows.length > 10 ? (
            <button
              type="button"
              onClick={() => setAll((v) => !v)}
              aria-expanded={all}
              className="mt-2 rounded text-xs text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              {all ? "Show fewer events" : `Show all ${env.rows.length} events`}
            </button>
          ) : null}
        </>
      )}
    </Section>
  );
}
