"use client";

import { useEffect, useId, useState } from "react";
import {
  ArrowLeftRight,
  CircleCheck,
  CircleSlash,
  FileClock,
  GitBranch,
  Network,
  ShieldAlert,
  Unlink,
  UserX,
  Users,
  type LucideIcon,
} from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type {
  DecisionRow,
  DecisionTrace,
  GuardrailsResponse,
  KnowledgeFinding,
  OwnerAtResult,
  OwnershipTeam,
  TemplateResult,
} from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error"; error: string };

/** Fetch on mount and whenever `deps` change; an aborted fetch never overwrites a newer one. */
function useLoad<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]): Load<T> {
  const [s, setS] = useState<{ key: string; load: Load<T> }>({ key: "", load: { state: "loading" } });
  const key = JSON.stringify(deps);
  useEffect(() => {
    const ctrl = new AbortController();
    fn(ctrl.signal)
      .then((data) => setS({ key, load: { state: "ok", data } }))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setS({ key, load: { state: "error", error: errorText(e) } });
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` encodes deps
  }, [key]);
  return s.key === key ? s.load : { state: "loading" };
}

function fmtDate(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  return new Date(ms).toISOString().slice(0, 10);
}

/** A template chip that opens the Cypher panel with the exact params the view ran with (re-run is read-only). */
function QueryChip({ template, params, title, origin }: { template: string; params: Record<string, unknown>; title: string; origin: string }) {
  const panel = useCypherPanel();
  const tenant = useTenant();
  return (
    <button
      type="button"
      onClick={() => panel.open({ template, title, origin, recordedParams: params, ctx: {}, tenant })}
      className="inline-flex min-h-6 items-center rounded px-1 font-mono text-[11px] whitespace-nowrap text-zinc-400 outline-none transition-colors hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400"
      aria-label={`${template}: open the Cypher panel for ${title}`}
    >
      {template}
    </button>
  );
}

function Card({ id, icon: Icon, title, aside, children }: { id: string; icon: LucideIcon; title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`${id}-h`} className="min-w-0 space-y-2 fl-card rounded-2xl px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={`${id}-h`} className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
          <Icon aria-hidden className="size-4 text-zinc-400" /> {title}
        </h2>
        {aside ? <div className="ml-auto flex flex-wrap items-center gap-1">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

function LoadState({ load, what }: { load: Load<unknown>; what: string }) {
  if (load.state === "loading") return <p className="text-xs text-zinc-300">Loading {what} from FalkorDB…</p>;
  if (load.state === "error") {
    return (
      <p role="alert" className="text-xs text-red-300">
        {what} unavailable: {load.error}
      </p>
    );
  }
  return null;
}

/**
 * Company-brain widgets: decision tracer, ownership map and guardrails, each
 * read from the selected tenant's graph through read-only GETs that call the existing MCP tools
 * (trace_decision, owner_at, missing_guardrails, knowledge_health) or catalogue templates.
 */
export function BrainWidgets() {
  const tenant = useTenant();
  return (
    <div className="grid gap-4 xl:grid-cols-3" key={tenant}>
      <DecisionTracer tenant={tenant} />
      <OwnershipMap tenant={tenant} />
      <Guardrails tenant={tenant} />
    </div>
  );
}

// ------------------------------------------------------------------ decision tracer

export function DecisionTracer({ tenant }: { tenant: string }) {
  const selectId = useId();
  const list = useLoad<TemplateResult<DecisionRow>>((s) => api.brainDecisions(tenant, s), [tenant]);
  const rows = list.state === "ok" ? list.data.rows : [];
  // default: the first decision that something superseded (the interesting chain), else the first one
  const fallback = rows.find((d) => d.superseded_by.length)?.id ?? rows[0]?.id ?? null;
  const [picked, setPicked] = useState<string | null>(null);
  const did = picked && rows.some((d) => d.id === picked) ? picked : fallback;
  const trace = useLoad<DecisionTrace | null>((s) => (did ? api.brainDecisionTrace(did, tenant, s) : Promise.resolve(null)), [did, tenant]);

  return (
    <Card
      id="dectrace"
      icon={GitBranch}
      title="Decision tracer"
      aside={
        list.state === "ok" ? (
          <>
            <QueryChip template={list.data.template} params={list.data.params} title="every decision" origin="GET /api/brain/decisions" />
            {trace.state === "ok" && trace.data ? (
              <QueryChip
                template={trace.data.chain.template}
                params={trace.data.chain.params}
                title={`SUPERSEDES chain of ${did}`}
                origin={`GET /api/brain/decisions/${did}`}
              />
            ) : null}
          </>
        ) : null
      }
    >
      <p className="text-xs text-zinc-400">A decision&apos;s SUPERSEDES chain to its current head (trace_decision), with the sources it cites.</p>
      <LoadState load={list} what="decisions" />
      {list.state === "ok" && rows.length === 0 ? <p className="text-xs text-zinc-300">No decisions in tenant_{tenant}.</p> : null}
      {rows.length ? (
        <label htmlFor={selectId} className="flex flex-col gap-0.5 text-xs text-zinc-400">
          Decision
          <select
            id={selectId}
            value={did ?? ""}
            onChange={(e) => setPicked(e.target.value)}
            className="h-8 rounded-md border border-zinc-700 bg-zinc-950 px-2 text-sm text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            {rows.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id}: {d.title ?? "untitled"} ({d.status ?? "no status"})
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div aria-live="polite">
        {did ? <LoadState load={trace} what="the trace" /> : null}
        {trace.state === "ok" && trace.data ? <TraceView t={trace.data} asked={did!} /> : null}
      </div>
    </Card>
  );
}

export function TraceView({ t, asked }: { t: DecisionTrace; asked: string }) {
  if (t.trace.error !== undefined) {
    return (
      <p role="alert" className="text-xs text-red-300">
        trace_decision failed: {t.trace.error}
      </p>
    );
  }
  const head = t.trace.rows[0];
  const chain = t.chain.rows;
  return (
    <div className="space-y-2">
      <ol className="space-y-1.5" aria-label={`SUPERSEDES chain of ${asked}, oldest first`}>
        {chain.map((d, i) => {
          const isHead = d.id === head?.head;
          return (
            <li
              key={d.id}
              className={cn("rounded-md border p-2", isHead ? "border-emerald-500/50 bg-emerald-500/5" : "border-zinc-800 bg-zinc-950/50")}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-zinc-400" aria-hidden>
                  {i + 1}.
                </span>
                <span className="font-mono text-sm text-zinc-50">{d.id}</span>
                {isHead ? (
                  <StatusChip tone="pass" icon={CircleCheck}>
                    current head
                  </StatusChip>
                ) : (
                  <StatusChip tone="na" icon={CircleSlash}>
                    {d.status ?? "no status"}
                  </StatusChip>
                )}
                {d.id === asked ? <StatusChip tone="info">selected</StatusChip> : null}
                <span className="ml-auto text-[11px] text-zinc-400">decided {fmtDate(d.decided_at)}</span>
              </div>
              <p className="mt-0.5 text-xs text-zinc-200">{d.title ?? "untitled"}</p>
              {d.supersedes?.length ? <p className="text-[11px] text-zinc-400">supersedes {d.supersedes.join(", ")}</p> : null}
            </li>
          );
        })}
      </ol>
      {head ? (
        <p className="text-xs text-zinc-300">
          {head.head === asked ? (
            <>
              <span className="font-mono">{asked}</span> is still in force (nothing supersedes it).
            </>
          ) : (
            <>
              <span className="font-mono">{asked}</span> is superseded; the decision in force is{" "}
              <span className="font-mono font-semibold text-zinc-50">{head.head}</span> ({head.depth} hop
              {head.depth === 1 ? "" : "s"} along SUPERSEDES).
            </>
          )}
        </p>
      ) : null}
      {head?.sources?.length ? (
        <div className="text-xs">
          <p className="text-zinc-400">Sources the head cites (Q-DEC-3)</p>
          <ul className="mt-0.5 space-y-0.5">
            {head.sources.map((s, i) => (
              <li key={s} className="font-mono text-[11px] break-all text-zinc-200">
                {head.source_ids?.[i] ? <span className="text-zinc-400">{head.source_ids[i]}: </span> : null}
                {s}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-zinc-400">The head cites no source document.</p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ ownership map

export function OwnershipMap({ tenant }: { tenant: string }) {
  const map = useLoad<TemplateResult<OwnershipTeam>>((s) => api.brainOwnership(tenant, s), [tenant]);
  const [comp, setComp] = useState<string | null>(null);
  const hist = useLoad<OwnerAtResult | null>((s) => (comp ? api.brainOwnerAt(comp, tenant, s) : Promise.resolve(null)), [comp, tenant]);
  const [showAll, setShowAll] = useState(false);
  const teams = map.state === "ok" ? map.data.rows : [];
  const shown = showAll ? teams : teams.slice(0, 6);

  return (
    <Card
      id="ownmap"
      icon={Users}
      title="Ownership map"
      aside={
        <>
          {map.state === "ok" ? (
            <QueryChip template={map.data.template} params={map.data.params} title="ownership map" origin="GET /api/brain/ownership" />
          ) : null}
          {hist.state === "ok" && hist.data && hist.data.error === undefined ? (
            <QueryChip template={hist.data.template} params={hist.data.params} title={`ownership history of ${comp}`} origin={`GET /api/brain/ownership/${comp}`} />
          ) : null}
        </>
      }
    >
      <p className="text-xs text-zinc-400">Who owns what now (OWNS). Pick a component for its ownership history (owner_at).</p>
      <LoadState load={map} what="the ownership map" />
      {map.state === "ok" && map.data.truncated ? <StatusChip tone="warn">truncated at the template LIMIT</StatusChip> : null}
      <ul className="space-y-2">
        {shown.map((t) => (
          <li key={t.team} className="rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
            <p className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-semibold text-zinc-50">{t.name ?? t.team}</span>
              <span className="font-mono text-zinc-400">{t.team}</span>
              <span className="ml-auto text-zinc-300">
                {t.n_owned} owned · {t.active_members} active member{t.active_members === 1 ? "" : "s"}
              </span>
              {t.active_members === 0 ? (
                <StatusChip tone="fail" icon={UserX}>
                  nobody active
                </StatusChip>
              ) : null}
            </p>
            <ul className="mt-1 flex flex-wrap gap-1" aria-label={`Components owned by ${t.name ?? t.team}`}>
              {t.owns.map((c) => (
                <li key={c}>
                  <button
                    type="button"
                    aria-pressed={comp === c}
                    onClick={() => setComp(c)}
                    className={cn(
                      "inline-flex min-h-6 items-center rounded border px-1.5 font-mono text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
                      comp === c ? "border-sky-400 bg-sky-500/20 text-sky-100" : "border-zinc-700 text-zinc-200 hover:bg-zinc-800",
                    )}
                  >
                    {c}
                  </button>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {teams.length > 6 ? (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          aria-expanded={showAll}
          className="text-xs text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {showAll ? "Show fewer teams" : `Show all ${teams.length} teams`}
        </button>
      ) : null}
      <div aria-live="polite">
        {comp ? <LoadState load={hist} what={`the history of ${comp}`} /> : null}
        {hist.state === "ok" && hist.data ? <OwnerHistory r={hist.data} comp={comp!} /> : null}
      </div>
    </Card>
  );
}

export function OwnerHistory({ r, comp }: { r: OwnerAtResult; comp: string }) {
  if (r.error !== undefined) {
    return (
      <p role="alert" className="text-xs text-red-300">
        owner_at failed: {r.error}
      </p>
    );
  }
  return (
    <div className="space-y-1.5 rounded-md border border-sky-500/30 bg-zinc-950/60 p-2">
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-200">
        <span className="font-mono font-semibold text-zinc-50">{comp}</span>
        {r.changed_hands ? (
          <StatusChip tone="warn" icon={ArrowLeftRight}>
            changed hands
          </StatusChip>
        ) : null}
        owned now by <span className="font-mono">{r.owner_now ?? "nobody"}</span>
      </p>
      {r.rows.length === 0 ? (
        <p className="text-xs text-zinc-300">No OWNED_AT history recorded for {comp}.</p>
      ) : (
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Ownership periods of {comp}, oldest first</caption>
          <thead className="text-zinc-400">
            <tr>
              <th scope="col" className="py-0.5 pr-2 font-medium">Team</th>
              <th scope="col" className="py-0.5 pr-2 font-medium">From</th>
              <th scope="col" className="py-0.5 font-medium">To</th>
            </tr>
          </thead>
          <tbody>
            {r.rows.map((p) => (
              <tr key={`${p.team}:${p.since}`} className="border-t border-zinc-800">
                <td className="py-1 pr-2 font-mono text-zinc-100">
                  {p.team}
                  {p.current ? <span className="ml-1 font-sans text-[11px] text-emerald-300">(current)</span> : null}
                </td>
                <td className="py-1 pr-2 text-zinc-200">{fmtDate(p.since)}</td>
                <td className="py-1 text-zinc-200">{p.until === null ? "now" : fmtDate(p.until)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ guardrails

const KIND: Record<string, { icon: LucideIcon; text: string }> = {
  stale_runbook: { icon: FileClock, text: "stale runbook" },
  handover_without_runbook: { icon: ArrowLeftRight, text: "handover, no runbook since" },
  decision_at_risk: { icon: ShieldAlert, text: "decision at risk" },
  missing_edge: { icon: Unlink, text: "likely missing edge" },
};

export function Guardrails({ tenant }: { tenant: string }) {
  const g = useLoad<GuardrailsResponse>((s) => api.brainGuardrails(tenant, s), [tenant]);
  const mg = g.state === "ok" ? g.data.missing_guardrails : null;
  const kh = g.state === "ok" ? g.data.knowledge_health : null;
  return (
    <Card
      id="guardrails"
      icon={ShieldAlert}
      title="Guardrails"
      aside={
        <>
          {mg && mg.error === undefined ? (
            <QueryChip template={mg.template} params={mg.params} title="missing guardrails" origin="GET /api/brain/guardrails" />
          ) : null}
          {kh && kh.error === undefined
            ? kh.templates.map((tid) => (
                <QueryChip
                  key={tid}
                  template={tid}
                  params={(kh.params as Record<string, Record<string, unknown>>)[tid] ?? {}}
                  title={`knowledge health (${tid})`}
                  origin="GET /api/brain/guardrails → knowledge_health"
                />
              ))
            : null}
        </>
      }
    >
      <p className="text-xs text-zinc-400">
        Revenue-path services with no owner or no runbook (missing_guardrails), and where knowledge has decayed (knowledge_health).
      </p>
      <LoadState load={g} what="guardrails" />
      {mg ? <MissingGuardrails r={mg} /> : null}
      {kh ? <KnowledgeFindings r={kh} /> : null}
    </Card>
  );
}

function MissingGuardrails({ r }: { r: GuardrailsResponse["missing_guardrails"] }) {
  if (r.error !== undefined) {
    return (
      <p role="alert" className="text-xs text-red-300">
        missing_guardrails failed: {r.error}
      </p>
    );
  }
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">Missing guardrails ({r.rows.length})</h3>
      {r.rows.length === 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-zinc-200">
          <CircleCheck aria-hidden className="size-3.5 text-emerald-300" /> Every revenue-path service has an owner and a current runbook.
        </p>
      ) : (
        <ul className="space-y-1">
          {r.rows.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-mono text-zinc-100">{x.id}</span>
              {x.tier !== null ? <span className="text-[11px] text-zinc-400">tier {x.tier}</span> : null}
              {x.no_owner ? (
                <StatusChip tone="fail" icon={UserX}>
                  no owner
                </StatusChip>
              ) : null}
              {x.no_runbook ? (
                <StatusChip tone="warn" icon={FileClock}>
                  no runbook
                </StatusChip>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function KnowledgeFindings({ r }: { r: GuardrailsResponse["knowledge_health"] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (r.error !== undefined) {
    return (
      <p role="alert" className="text-xs text-red-300">
        knowledge_health failed: {r.error}
      </p>
    );
  }
  const groups = new Map<string, KnowledgeFinding[]>();
  for (const f of r.rows) groups.set(f.kind, [...(groups.get(f.kind) ?? []), f]);
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">
        Knowledge health ({r.rows.length} finding{r.rows.length === 1 ? "" : "s"}, stale after {r.stale_days} days)
      </h3>
      {r.rows.length === 0 ? <p className="text-xs text-zinc-200">No knowledge-health findings.</p> : null}
      <ul className="space-y-1">
        {[...groups.entries()].map(([kind, fs]) => {
          const meta = KIND[kind] ?? { icon: Network, text: kind };
          const Icon = meta.icon;
          const expanded = open === kind;
          return (
            <li key={kind} className="rounded-md border border-zinc-800 bg-zinc-950/50">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : kind)}
                className="flex min-h-7 w-full items-center gap-1.5 px-2 py-1 text-left text-xs text-zinc-100 outline-none hover:bg-zinc-800/60 focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                <Icon aria-hidden className="size-3.5 text-amber-300" />
                <span className="font-medium">{meta.text}</span>
                <span className="ml-auto font-mono text-zinc-300">{fs.length}</span>
              </button>
              {expanded ? (
                <ul className="space-y-1 border-t border-zinc-800 px-2 py-1.5">
                  {fs.map((f, i) => (
                    <li key={`${f.id}:${f.ref}:${i}`} className="text-[11px] text-zinc-300">
                      <span className="font-mono text-zinc-100">{f.id}</span>: {f.why}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
