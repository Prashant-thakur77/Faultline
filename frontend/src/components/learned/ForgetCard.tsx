"use client";

import { useId, useState } from "react";
import { Check, CircleCheck, CircleX, Copy, Eraser, LoaderCircle, OctagonAlert, RotateCcw, ScrollText, Search } from "lucide-react";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { QUERY_ID_CLS, ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { ApiError } from "@/lib/api";
import { fmtAgo } from "@/lib/format";
import { learnedApi, type ForgetPlan, type ForgetReceipt, type LearnedState, type ReceiptRow } from "@/lib/learned";
import { fmtWhen } from "@/lib/oncall";
import { cn } from "@/lib/utils";
import { KeyField, PersonField, useOpenLearned, writeErrorText } from "./bits";
import { EventKindChip } from "./LearnedCards";

const audit = (tenant: string) => `audit_${tenant}`;

function list(xs: string[]): string {
  return xs.length ? xs.join(", ") : "none";
}

/**
 * Forget a person's learned influence (T2: memory with receipts). Step 1, the dry run, lists exactly what will be
 * deleted and recomputed and returns a receipt token bound to that set (nothing is deleted). Step 2 sends the token
 * with an approver: the server deletes exactly that set in one write, recomputes what it fed, writes a ForgetReceipt
 * to audit_<tenant> and re-reads the graph to prove it. A stale token (the learned state changed) is refused (409).
 */
export function ForgetCard({ s, tenant, now, listId, actor, onActor, onForgotten }: {
  s: LearnedState;
  tenant: string;
  now: number;
  listId: string;
  actor: string;
  onActor: (v: string) => void;
  onForgotten: () => void;
}) {
  const open = useOpenLearned(tenant);
  const env = s.receipts;
  const personId = useId();
  const [person, setPerson] = useState("");
  const [plan, setPlan] = useState<ForgetPlan | null>(null);
  const [busy, setBusy] = useState<"dry" | "forget" | null>(null);
  const [err, setErr] = useState<{ op: "dry" | "forget"; head: string; text: string; stale: boolean } | null>(null);
  const [receipt, setReceipt] = useState<ForgetReceipt | null>(null);

  const fail = (op: "dry" | "forget", e: unknown) =>
    setErr({ op, ...writeErrorText(e), stale: op === "forget" && e instanceof ApiError && e.status === 409 });

  const dryRun = async (who = person.trim()) => {
    if (!who) return;
    setBusy("dry");
    setErr(null);
    setPlan(null);
    setReceipt(null);
    try {
      setPlan(await learnedApi.forgetDryRun(who, tenant));
    } catch (e) {
      fail("dry", e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Section
      id="learned-forget"
      level={3}
      title="Forget a person's influence"
      via={<ViaFalkor template={env.template} label="the forget receipts" onOpen={() => open(env, "forget receipts", audit(tenant))} />}
      aside={
        env.rows.length ? (
          <StatusChip tone="na" icon={ScrollText}>
            {env.rows.length} receipt{env.rows.length === 1 ? "" : "s"}
          </StatusChip>
        ) : null
      }
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        Removes everything Faultline learned from one person: their learning events and the guidelines their rejections
        proposed, then recomputes what those fed. Incidents, approvals and pages themselves are not changed. First a dry run
        shows exactly what goes; nothing is deleted until you confirm it.
      </p>

      {receipt ? (
        <ReceiptView r={receipt} tenant={tenant} />
      ) : (
        <>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!busy) void dryRun();
            }}
          >
            <PersonField
              id={personId}
              label="Person whose influence to forget"
              value={person}
              onChange={(v) => {
                setPerson(v);
                setPlan(null); // the token binds this person's exact set
                setErr(null);
              }}
              listId={listId}
            />
            <button
              type="submit"
              disabled={!!busy || !person.trim()}
              className="inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13px] text-zinc-100 ring-1 ring-white/15 outline-none hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy === "dry" ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : <Search aria-hidden className="size-4" />}
              Dry run: show what would be forgotten
            </button>
          </form>

          {plan ? (
            <DryRunView
              plan={plan}
              tenant={tenant}
              home={s.home}
              now={now}
              listId={listId}
              actor={actor}
              onActor={onActor}
              publicDemo={s.trust.public}
              busy={busy === "forget"}
              onForget={async (approver, key) => {
                setBusy("forget");
                setErr(null);
                try {
                  setReceipt(await learnedApi.forget({ person: plan.person, token: plan.token, approver }, tenant, key));
                  setPlan(null);
                  onForgotten();
                } catch (e) {
                  fail("forget", e);
                } finally {
                  setBusy(null);
                }
              }}
            />
          ) : null}
        </>
      )}

      {err ? (
        <div role="alert" className="mt-2 flex flex-wrap items-start gap-2 rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100">
          <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
          <p className="min-w-0 flex-1">
            {err.stale ? (
              <>
                <strong className="font-semibold">Changed since the dry run:</strong> {err.text} Nothing was deleted; run the dry run
                again and review the new list.
              </>
            ) : (
              <>
                <strong className="font-semibold">{err.op === "dry" ? "Dry run:" : "Forget:"}</strong> {err.head} {err.text}
              </>
            )}
          </p>
          {err.stale ? (
            <button
              type="button"
              onClick={() => void dryRun(plan?.person ?? person.trim())}
              className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-red-50 ring-1 ring-red-300/40 outline-none hover:bg-red-500/15 focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <RotateCcw aria-hidden className="size-3" /> Run the dry run again
            </button>
          ) : null}
        </div>
      ) : null}

      {receipt ? (
        <button
          type="button"
          onClick={() => {
            setReceipt(null);
            setPerson("");
          }}
          className="mt-2 rounded text-xs text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          Forget someone else
        </button>
      ) : null}

      {env.rows.length ? (
        <Disclosure className="mt-3" size="xs" defaultOpen={false} summary={<>Past forget receipts<span className="text-[var(--fl-subtle)]"> · {env.rows.length}</span></>}>
          <ul className="space-y-1.5" aria-label="Past forget receipts">
            {env.rows.map((r, i) => (
              <PastReceipt key={`${r.token ?? r.person}:${i}`} r={r} now={now} />
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </Section>
  );
}

function DryRunView({
  plan,
  tenant,
  home,
  now,
  listId,
  actor,
  onActor,
  publicDemo,
  busy,
  onForget,
}: {
  plan: ForgetPlan;
  tenant: string;
  home: string | null;
  now: number;
  listId: string;
  actor: string;
  onActor: (v: string) => void;
  publicDemo: boolean | null;
  busy: boolean;
  onForget: (approver: string, key: string | undefined) => void;
}) {
  const panel = useCypherPanel();
  const titleId = useId();
  const ackId = useId();
  const [ack, setAck] = useState(false);
  const [key, setKey] = useState("");
  const [copied, setCopied] = useState(false);
  if (plan.nEvents === 0) {
    return (
      <p role="status" className="mt-3 rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
        Nothing to forget: <span className="font-mono text-zinc-100">{plan.person}</span> has no learning event in{" "}
        <span className="font-mono">{home ?? "the on-call home graph"}</span>.
      </p>
    );
  }
  const g = plan.guidelines.length;
  return (
    <div className="mt-3 space-y-3">
      <section aria-label="What will be forgotten" className="space-y-2 rounded-lg border border-sky-500/40 bg-zinc-950/60 p-2.5">
        <h4 className="flex flex-wrap items-center gap-2 text-xs font-semibold text-sky-200">
          Dry run: {plan.nEvents} learning event{plan.nEvents === 1 ? "" : "s"} from <span className="font-mono">{plan.person}</span>
          <button
            type="button"
            className={QUERY_ID_CLS}
            aria-label="Q-LEARN-PERSON: open the Cypher panel for the person's learning events"
            onClick={() =>
              panel.open({
                template: "Q-LEARN-PERSON",
                title: `learning events of ${plan.person}`,
                origin: `POST /api/learned/forget dry run${home ? ` (${home})` : ""}`,
                recordedParams: { person: plan.person, after_at: -1, after_id: "" },
                ctx: {},
                tenant,
              })
            }
          >
            Q-LEARN-PERSON
          </button>
        </h4>
        {plan.byKind.length ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Events by kind">
            {plan.byKind.map((k) => (
              <li key={k.kind} className="inline-flex items-center gap-1 text-[11px] text-zinc-300">
                <EventKindChip kind={k.kind} /> <span className="font-mono">{k.n}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {/* stacked on phones: the labels would leave the ids a sliver of the width */}
        <dl className="grid grid-cols-1 gap-y-0.5 text-xs sm:grid-cols-[max-content_minmax(0,1fr)] sm:gap-x-3 sm:gap-y-1">
          <dt className="text-zinc-400">guidelines deleted</dt>
          <dd className="font-mono text-zinc-100">
            {plan.guidelines.length
              ? plan.guidelines.map((id, i) => (
                  <span key={id} className="inline-block max-w-full break-all">
                    {id}
                    {i < plan.guidelines.length - 1 ? ",\u00a0" : ""}
                  </span>
                ))
              : "none"}
          </dd>
          <dt className="text-zinc-400">preferences recomputed</dt>
          <dd className="font-mono break-all text-zinc-100">{list(plan.families)}</dd>
          <dt className="text-zinc-400">responder edges recomputed</dt>
          <dd className="font-mono break-all text-zinc-100">{list(plan.responded)}</dd>
          <dt className="text-zinc-400">knowledge gaps recomputed</dt>
          <dd className="font-mono break-all text-zinc-100">{list(plan.gaps)}</dd>
          <dt className="text-zinc-400">receipt token</dt>
          <dd className="flex flex-wrap items-center gap-2">
            <code className="rounded bg-zinc-800 px-1 font-mono text-[12px] font-semibold text-zinc-50" title={plan.token}>
              {plan.token.slice(0, 12)}
            </code>
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard?.writeText(plan.token).then(
                  () => setCopied(true),
                  () => setCopied(false),
                );
              }}
              aria-label="Copy receipt token"
              className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-zinc-300 ring-1 ring-white/10 outline-none hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </dd>
        </dl>
        <Disclosure size="xs" defaultOpen={false} summary={<>The {plan.events.length} event{plan.events.length === 1 ? "" : "s"}</>}>
          <ul className="space-y-1 text-[11px] text-zinc-300">
            {plan.events.map((e) => (
              <li key={e.id} className="break-words">
                <span className="font-mono text-zinc-400">{e.id}</span> · {e.kind ?? "–"}
                {e.family ? ` · ${e.family}` : ""}
                {e.incident ? ` · ${e.incident}` : ""}
                {e.gap ? ` · gap ${e.gap}` : ""}
                {e.guidelines.length ? ` · proposed ${e.guidelines.join(", ")}` : ""}
                {e.at !== null ? ` · ${fmtAgo(e.at, now)}` : ""}
              </li>
            ))}
          </ul>
        </Disclosure>
      </section>

      <div role="group" aria-labelledby={titleId} className="space-y-2 rounded-lg bg-red-500/[0.06] p-2.5 ring-1 ring-red-400/40">
        <p id={titleId} className="flex items-center gap-1.5 text-sm font-semibold text-red-100">
          <Eraser aria-hidden className="size-4 text-red-300" /> Forget {plan.person}&apos;s influence for good
        </p>
        <p className="text-xs leading-relaxed text-red-50/90">
          This cannot be undone. Faultline deletes these {plan.nEvents} learning event{plan.nEvents === 1 ? "" : "s"}
          {g ? ` and the ${g} guideline${g === 1 ? "" : "s"} they proposed (even one a colleague promoted)` : ""}, recomputes every
          preference, responder edge and knowledge gap they fed, and writes a receipt to{" "}
          <span className="font-mono">{audit(tenant)}</span>. The receipt token binds exactly this list: if anything changed since
          the dry run, the server refuses it.
        </p>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && ack && actor.trim()) onForget(actor.trim(), key.trim() || undefined);
          }}
        >
          <label htmlFor={ackId} className="flex items-start gap-2 text-xs text-zinc-100">
            <input
              id={ackId}
              type="checkbox"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-red-400 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            <span>
              I understand: what Faultline learned from <span className="font-mono">{plan.person}</span> is deleted and cannot be
              restored
            </span>
          </label>
          <div className="flex flex-wrap items-end gap-2">
            <PersonField label="Approver (an active person id)" value={actor} onChange={onActor} listId={listId} />
            <KeyField value={key} onChange={setKey} publicDemo={publicDemo} />
            <button
              type="submit"
              disabled={busy || !ack || !actor.trim()}
              className="inline-flex h-8 items-center gap-1.5 rounded-full bg-red-300 px-3.5 text-[13px] font-medium text-zinc-950 outline-none hover:bg-red-200 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" /> : <Eraser aria-hidden className="size-4" />}
              Forget for good
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** The receipt and the server's re-read proof: forgotten only when no event is left and no preference still cites one. */
function ReceiptView({ r, tenant }: { r: ForgetReceipt; tenant: string }) {
  return (
    <div
      role="status"
      className={cn(
        "space-y-2 rounded-xl p-3 ring-1",
        r.forgotten ? "bg-emerald-500/[0.07] ring-emerald-400/40" : "bg-red-500/[0.08] ring-red-400/50",
      )}
    >
      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-50">
        {r.forgotten ? (
          <StatusChip tone="pass" icon={CircleCheck}>
            forgotten
          </StatusChip>
        ) : (
          <StatusChip tone="fail" icon={CircleX}>
            {r.verdict ?? "proof not reported"}
          </StatusChip>
        )}
        Receipt: {r.person}&apos;s learned influence
      </p>
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <dt className="text-zinc-400">deleted</dt>
        <dd className="text-zinc-100">
          {r.events ?? "–"} event{r.events === 1 ? "" : "s"}, {r.guidelines ?? "–"} guideline{r.guidelines === 1 ? "" : "s"},{" "}
          {r.relationships ?? "–"} relationship{r.relationships === 1 ? "" : "s"}
        </dd>
        <dt className="text-zinc-400">recomputed</dt>
        <dd className="break-words text-zinc-100">
          preferences: <span className="font-mono">{list(r.familiesRecomputed)}</span> · responders:{" "}
          <span className="font-mono">{list(r.respondersRecomputed)}</span> · gaps: <span className="font-mono">{list(r.gapsRecomputed)}</span>
        </dd>
        <dt className="text-zinc-400">proof (re-read)</dt>
        <dd className="text-zinc-100">
          {r.eventsLeft ?? "–"} event{r.eventsLeft === 1 ? "" : "s"} left · {r.preferencesStillCiting ?? "–"} preference
          {r.preferencesStillCiting === 1 ? "" : "s"} still citing one
        </dd>
        <dt className="text-zinc-400">approved by</dt>
        <dd className="font-mono text-zinc-100">{r.approver ?? "–"}</dd>
        <dt className="text-zinc-400">when</dt>
        <dd className="text-zinc-100">{fmtWhen(r.at)}</dd>
        <dt className="text-zinc-400">token</dt>
        <dd className="font-mono break-all text-zinc-300" title={r.token ?? undefined}>
          {r.token ? r.token.slice(0, 12) : "–"}
        </dd>
        <dt className="text-zinc-400">written to</dt>
        <dd className="font-mono text-zinc-300">{audit(tenant)}</dd>
      </dl>
      {!r.forgotten ? (
        <p className="text-xs text-red-100">
          The server&apos;s re-read did not confirm it: some events or citations remain. Run the dry run again to see what is left.
        </p>
      ) : null}
    </div>
  );
}

function PastReceipt({ r, now }: { r: ReceiptRow; now: number }) {
  const clean = r.eventsLeft === 0 && r.preferencesStillCiting === 0;
  return (
    <li className="rounded-lg bg-white/[0.02] px-3 py-2 text-[11px] text-zinc-300 ring-1 ring-white/[0.05]">
      <p className="flex flex-wrap items-center gap-1.5">
        {clean ? (
          <StatusChip tone="pass" icon={CircleCheck}>
            forgotten
          </StatusChip>
        ) : (
          <StatusChip tone="fail" icon={CircleX}>
            incomplete
          </StatusChip>
        )}
        <span className="font-mono text-zinc-100">{r.person ?? "–"}</span>
        <span>approved by {r.approver ?? "–"}</span>
        <span className="ml-auto text-zinc-400">{r.at !== null ? fmtAgo(r.at, now) : "–"}</span>
      </p>
      <p className="mt-0.5 text-zinc-400">
        {r.events ?? "–"} events, {r.guidelines ?? "–"} guidelines deleted · {r.eventsLeft ?? "–"} left, {r.preferencesStillCiting ?? "–"} preferences
        still citing · token <span className="font-mono">{r.token ? r.token.slice(0, 12) : "–"}</span>
      </p>
    </li>
  );
}
