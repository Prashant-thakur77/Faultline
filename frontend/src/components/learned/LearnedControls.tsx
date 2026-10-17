"use client";

import Link from "next/link";
import { ArrowUpCircle, CircleCheck, CircleDot, CircleHelp, CircleMinus, ShieldAlert, Users, XCircle, type LucideIcon } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { fmtAgo } from "@/lib/format";
import type { Tone } from "@/lib/gate";
import { kindWord, learnedApi, type GapRow, type GuidelineRow, type GuidelineStatus, type LearnedState } from "@/lib/learned";
import { personText } from "@/lib/oncall";
import { ActorConfirm, Empty, Truncated, useOpenLearned } from "./bits";

const LINK = "rounded font-mono whitespace-nowrap text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400";

const GUIDE_STATUS: Record<GuidelineStatus, { tone: Tone; icon: LucideIcon; text: string }> = {
  proposed: { tone: "warn", icon: CircleDot, text: "proposed: waits for a decision" },
  active: { tone: "info", icon: ShieldAlert, text: "active: needs an override" },
  dismissed: { tone: "na", icon: CircleMinus, text: "dismissed" },
};

export function GuidelineStatusChip({ status }: { status: string | null }) {
  const m = status && status in GUIDE_STATUS ? GUIDE_STATUS[status as GuidelineStatus] : null;
  return m ? (
    <StatusChip tone={m.tone} icon={m.icon}>
      {m.text}
    </StatusChip>
  ) : (
    <StatusChip tone="na">{status ?? "status not recorded"}</StatusChip>
  );
}

/** Who acts and how they are asked: shared by every control in the panel (the id pre-fills; the key never does). */
export interface Acting {
  actor: string;
  onActor: (v: string) => void;
  listId: string;
  publicDemo: boolean | null;
  /** Re-read GET /api/learned after a change, and say what changed (role=status on the card). */
  onChanged: (message: string) => void;
}

/** The result of the last change on a card (a live region that is always there, so the change is announced). */
function Notice({ text }: { text: string | null }) {
  return (
    <p role="status" className={text ? "mb-2 flex items-center gap-1.5 text-xs text-emerald-200" : "sr-only"}>
      {text ? <CircleCheck aria-hidden className="size-3.5 shrink-0 text-emerald-300" /> : null}
      {text ?? ""}
    </p>
  );
}

// ------------------------------------------------------------------ guidelines

export function GuidelinesCard({ s, tenant, now, acting, notice }: { s: LearnedState; tenant: string; now: number; acting: Acting; notice: string | null }) {
  const open = useOpenLearned(tenant);
  const env = s.guidelines;
  const live = env.rows.filter((g) => g.status !== "dismissed");
  const dismissed = env.rows.filter((g) => g.status === "dismissed");
  const proposed = live.filter((g) => g.status === "proposed").length;
  return (
    <Section
      id="learned-guidelines"
      level={3}
      title="Guidelines"
      via={<ViaFalkor template={env.template} label="the learned guidelines" onOpen={() => open(env, "learned guidelines", s.home)} />}
      aside={
        live.length ? (
          <StatusChip tone={proposed ? "warn" : "info"} icon={proposed ? CircleDot : ShieldAlert}>
            {proposed ? `${proposed} to decide` : `${live.length} active`}
          </StatusChip>
        ) : null
      }
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        A trusted person&apos;s rejection proposes a guideline from its reason, for that family and fix kind. Promoted, it flags
        that option on the next plan and approving it needs an explicit override. It never blocks silently and never changes
        the gate.
      </p>
      <Notice text={notice} />
      <Truncated env={env} />
      {live.length === 0 ? (
        <Empty>
          {dismissed.length
            ? "No proposed or active guideline: every one so far was dismissed."
            : "No guideline yet. When someone rejects an option with a reason, it is proposed here."}
        </Empty>
      ) : (
        <ul className="space-y-2" aria-label="Proposed and active guidelines">
          {live.map((g) => (
            <GuidelineItem key={g.id} g={g} tenant={tenant} now={now} acting={acting} />
          ))}
        </ul>
      )}
      {dismissed.length ? (
        <Disclosure className="mt-3" size="xs" defaultOpen={false} summary={<>Dismissed guidelines<span className="text-[var(--fl-subtle)]"> · {dismissed.length}</span></>}>
          <ul className="space-y-2" aria-label="Dismissed guidelines">
            {dismissed.map((g) => (
              <GuidelineItem key={g.id} g={g} tenant={tenant} now={now} acting={acting} />
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </Section>
  );
}

function GuidelineItem({ g, tenant, now, acting }: { g: GuidelineRow; tenant: string; now: number; acting: Acting }) {
  const decide = (action: "promote" | "dismiss") => (by: string, key: string | undefined) => learnedApi.guideline(g.id, action, by, tenant, key);
  return (
    <li className="rounded-xl bg-white/[0.02] px-3.5 py-2.5 ring-1 ring-white/[0.06]">
      <div className="flex flex-wrap items-center gap-1.5">
        <GuidelineStatusChip status={g.status} />
        <span className="font-mono text-[11px] text-zinc-400">{g.id}</span>
        <span className="text-[11px] text-zinc-400">
          for <span className="font-mono text-zinc-200">{g.family ?? "–"}</span> · {kindWord(g.actionKind)}
        </span>
      </div>
      <p className="mt-1.5 border-l-2 border-white/10 pl-2 text-sm break-words text-zinc-100">&ldquo;{g.text ?? "–"}&rdquo;</p>
      <p className="mt-1.5 text-[11px] break-words text-zinc-400">
        {g.source === "rejection" || !g.source ? "from the rejection by " : `from ${g.source} by `}
        <span className="text-zinc-200">{personText(g.by)}</span>
        {g.at !== null ? ` · ${fmtAgo(g.at, now)}` : ""}
        {g.option ? ` · of “${g.option}”` : ""}
        {g.incident ? (
          <>
            {" · on "}
            <Link href={`/incidents/${encodeURIComponent(g.incident)}?tenant=${encodeURIComponent(tenant)}`} className={LINK}>
              {g.incident}
            </Link>
          </>
        ) : null}
        {g.event ? (
          <>
            {" · "}
            <span className="inline-block max-w-full font-mono break-all text-[var(--fl-subtle)]">{g.event}</span>
          </>
        ) : null}
      </p>
      {g.decidedBy ? (
        <p className="mt-0.5 text-[11px] text-zinc-400">
          {g.status === "dismissed" ? "dismissed" : "promoted"} by <span className="text-zinc-200">{personText(g.decidedBy)}</span>
          {g.decidedAt !== null ? ` · ${fmtAgo(g.decidedAt, now)}` : ""}
        </p>
      ) : null}
      {g.status === "proposed" || g.status === "active" ? (
        <div className="mt-2 flex flex-wrap items-start gap-2">
          {g.status === "proposed" ? (
            <ActorConfirm
              label="Promote"
              ariaLabel={`Promote guideline ${g.id}`}
              icon={ArrowUpCircle}
              tone="primary"
              question={
                <>
                  Promote <span className="font-mono">{g.id}</span> to active? On the next plan for {g.family ?? "this family"}, the{" "}
                  {kindWord(g.actionKind)} option is flagged, and approving it needs an explicit override with a reason.
                </>
              }
              confirmLabel="Yes, promote"
              actor={acting.actor}
              onActor={acting.onActor}
              listId={acting.listId}
              publicDemo={acting.publicDemo}
              run={decide("promote")}
              onDone={() => acting.onChanged(`Guideline ${g.id} promoted to active.`)}
            />
          ) : null}
          <ActorConfirm
            label="Dismiss"
            ariaLabel={`Dismiss guideline ${g.id}`}
            icon={XCircle}
            question={
              <>
                Dismiss <span className="font-mono">{g.id}</span>? It stops showing on plans
                {g.status === "active" ? " and no longer needs an override" : ""}. It stays listed under Dismissed.
              </>
            }
            confirmLabel="Yes, dismiss"
            actor={acting.actor}
            onActor={acting.onActor}
            listId={acting.listId}
            publicDemo={acting.publicDemo}
            run={decide("dismiss")}
            onDone={() => acting.onChanged(`Guideline ${g.id} dismissed.`)}
          />
        </div>
      ) : null}
    </li>
  );
}

// ------------------------------------------------------------------ knowledge gaps

export function GapsCard({ s, tenant, now, acting, notice }: { s: LearnedState; tenant: string; now: number; acting: Acting; notice: string | null }) {
  const open = useOpenLearned(tenant);
  const env = s.gaps;
  const openRows = env.rows.filter((g) => g.status === "open");
  const dismissed = env.rows.filter((g) => g.status !== "open");
  return (
    <Section
      id="learned-gaps"
      level={3}
      title="Knowledge gaps"
      via={<ViaFalkor template={env.template} label="the knowledge gaps" onOpen={() => open(env, "knowledge gaps", s.home)} />}
      aside={openRows.length ? <StatusChip tone="warn" icon={CircleHelp}>{openRows.length} open</StatusChip> : null}
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        Company-brain questions trusted people asked that the graph could not answer. The teams that own what a question
        was about are who should document it.
      </p>
      <Notice text={notice} />
      <Truncated env={env} />
      {openRows.length === 0 ? (
        <Empty>
          {dismissed.length ? "No open gap: the ones asked so far were dismissed." : "No knowledge gap: every question asked so far was answered from the graph."}
        </Empty>
      ) : (
        <ul className="space-y-2" aria-label="Open knowledge gaps">
          {openRows.map((g) => (
            <GapItem key={g.id} g={g} tenant={tenant} now={now} acting={acting} />
          ))}
        </ul>
      )}
      {dismissed.length ? (
        <Disclosure className="mt-3" size="xs" defaultOpen={false} summary={<>Dismissed gaps<span className="text-[var(--fl-subtle)]"> · {dismissed.length}</span></>}>
          <p className="mb-2 text-[11px] text-zinc-400">A dismissed gap re-opens when a trusted person asks the question again.</p>
          <ul className="space-y-2" aria-label="Dismissed knowledge gaps">
            {dismissed.map((g) => (
              <GapItem key={g.id} g={g} tenant={tenant} now={now} acting={acting} />
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </Section>
  );
}

function GapItem({ g, tenant, now, acting }: { g: GapRow; tenant: string; now: number; acting: Acting }) {
  return (
    <li className="rounded-xl bg-white/[0.02] px-3.5 py-2.5 ring-1 ring-white/[0.06]">
      <p className="text-sm break-words text-zinc-100">&ldquo;{g.text ?? "–"}&rdquo;</p>
      <p className="mt-1 text-[11px] text-zinc-400">
        asked {g.n ?? "–"} time{g.n === 1 ? "" : "s"}
        {g.firstAt !== null ? ` · first ${fmtAgo(g.firstAt, now)}` : ""}
        {g.lastAt !== null ? ` · last ${fmtAgo(g.lastAt, now)}` : ""}
        {g.intent ? ` · ${g.intent} question` : ""}
      </p>
      {g.reason ? <p className="mt-0.5 text-[11px] break-words text-zinc-400">{g.reason}</p> : null}
      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-zinc-300">
        <Users aria-hidden className="size-3.5 text-[var(--fl-subtle)]" />
        Who should document it:
        {g.owners.length ? (
          <span className="font-mono text-zinc-100">{g.owners.join(", ")}</span>
        ) : (
          <span className="text-zinc-400">no team owns what it was about{g.about.length ? "" : " (it named nothing in the graph)"}</span>
        )}
        {g.about.length ? <span className="text-zinc-400">(about {g.about.join(", ")})</span> : null}
      </p>
      <p className="mt-0.5 font-mono text-[11px] text-[var(--fl-subtle)]">{g.id}</p>
      {g.status === "open" ? (
        <div className="mt-2">
          <ActorConfirm
            label="Dismiss"
            ariaLabel={`Dismiss knowledge gap ${g.id}`}
            icon={XCircle}
            question={<>Dismiss this gap? It leaves the open list until a trusted person asks it again.</>}
            confirmLabel="Yes, dismiss"
            actor={acting.actor}
            onActor={acting.onActor}
            listId={acting.listId}
            publicDemo={acting.publicDemo}
            run={(by, key) => learnedApi.dismissGap(g.id, by, tenant, key)}
            onDone={() => acting.onChanged(`Knowledge gap ${g.id} dismissed.`)}
          />
        </div>
      ) : null}
    </li>
  );
}
