"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { BookOpenCheck, BrainCircuit, Search, User, Users, Wand2, X } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { fmtValue } from "@/lib/format";
import { tenantGraph, useTenant } from "@/lib/tenant";
import type { FamilyRow, MemoryOverview, RecallRow, RunbookRow, TemplateResult, ToolResult } from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";
import { ColdWarmCard } from "./ColdWarmCard";

type Load = { state: "loading" } | { state: "ok"; data: MemoryOverview } | { state: "error"; error: string; status: number | null };

const FIX_TEXT: Record<string, string> = { flip_flag: "feature flag", rollback_deploy: "rollback", open_issue: "issue", data_repair: "data repair" };

/**
 * Memory tab: recall (similarity, recency, salience as separate columns),
 * incident families (algo.labelPropagation), derived runbooks with their support and the
 * postmortems they were DERIVED_FROM, and the cold vs warm comparison from the last eval. Every
 * section reads the selected tenant's graph through GET /api/memory/overview (existing MCP tools
 * and catalogue templates, nothing recorded) and opens its query in the Cypher panel.
 */
export function MemoryView({ initialIncident }: { initialIncident: string | null }) {
  const tenant = useTenant();
  const router = useRouter();
  const inputId = useId();
  const listId = useId();
  const [incident, setIncident] = useState<string | null>(initialIncident);
  const [draft, setDraft] = useState(initialIncident ?? "");
  const [load, setLoad] = useState<{ key: string; load: Load }>({ key: "", load: { state: "loading" } });
  const [recent, setRecent] = useState<string[]>([]);
  const key = `${tenant}|${incident ?? ""}`;

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .memoryOverview(tenant, incident, ctrl.signal)
      .then((data) => setLoad({ key, load: { state: "ok", data } }))
      .catch((e) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setLoad({ key, load: { state: "error", error: errorText(e), status: e && typeof e === "object" && "status" in e ? (e.status as number | null) : null } });
      });
    return () => ctrl.abort();
  }, [key, tenant, incident]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .incidents(tenant, ctrl.signal)
      .then((xs) => setRecent([...new Set(xs.map((x) => x.incident))].slice(0, 20)))
      .catch(() => setRecent([])); // only suggestions: the page itself fails loudly on its own request
    return () => ctrl.abort();
  }, [tenant]);

  const current: Load = load.key === key ? load.load : { state: "loading" };
  const data = current.state === "ok" ? current.data : null;
  const suggestions = useMemo(() => {
    const fam = (data?.families.rows ?? []).flatMap((f) => f.incidents);
    return [...new Set([...recent, ...fam])].slice(0, 60);
  }, [data, recent]);

  const select = (id: string | null) => {
    setIncident(id);
    setDraft(id ?? "");
    const qs = new URLSearchParams({ tenant });
    if (id) qs.set("incident", id);
    router.replace(`/memory?${qs.toString()}`);
  };

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4 p-4">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div className="min-w-0 space-y-1">
          <h1 className="flex items-center gap-2 text-lg font-semibold text-zinc-50">
            <BrainCircuit aria-hidden className="size-5 text-violet-300" /> Memory
          </h1>
          <p className="max-w-3xl text-sm text-zinc-300">
            What the graph remembers in <span className="font-mono">{data?.graph ?? tenantGraph(tenant)}</span>: incident families,
            runbooks derived from past fixes, and what a given incident recalls. Memory may raise a prior or order the fixes; the
            gate still needs a graph path.
          </p>
        </div>
        <form
          className="ml-auto flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const v = draft.trim();
            select(v || null);
          }}
        >
          <label htmlFor={inputId} className="flex flex-col gap-0.5 text-xs text-zinc-400">
            Recall for incident
            <input
              id={inputId}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              list={listId}
              maxLength={160}
              spellCheck={false}
              autoComplete="off"
              placeholder="e.g. a recent run's incident id"
              className="h-8 w-64 rounded-md border border-zinc-700 bg-zinc-950 px-2 font-mono text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
          </label>
          <datalist id={listId}>
            {suggestions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <Button type="submit" size="sm" disabled={!draft.trim()}>
            <Search aria-hidden /> Recall
          </Button>
          {incident ? (
            <Button type="button" size="sm" variant="outline" onClick={() => select(null)}>
              <X aria-hidden /> Tenant view
            </Button>
          ) : null}
        </form>
      </header>

      <div aria-live="polite" className="sr-only">
        {current.state === "loading"
          ? "Loading memory from FalkorDB"
          : current.state === "error"
            ? `Memory unavailable: ${current.error}`
            : `Loaded ${data!.families.rows?.length ?? 0} families and ${data!.runbooks.rows.length} runbooks${incident ? `, recall for ${incident}` : ""}`}
      </div>

      {current.state === "error" ? (
        <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
          {current.status === 404 ? "Unknown incident: " : "Memory unavailable: "}
          {current.error}
        </p>
      ) : null}
      {current.state === "loading" ? <p className="text-sm text-zinc-300">Reading memory from FalkorDB…</p> : null}

      {data ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div className="min-w-0 space-y-4">
            {incident ? <RecallCard data={data} incident={incident} tenant={tenant} onSelect={select} /> : null}
            <FamiliesCard r={data.families} graph={data.graph} tenant={tenant} incident={incident} onSelect={select} />
          </div>
          <div className="min-w-0 space-y-4">
            <ColdWarmCard />
            <RunbooksCard r={data.runbooks} graph={data.graph} tenant={tenant} incident={incident} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function useOpen(graph: string, tenant: string, incident: string | null) {
  const panel = useCypherPanel();
  // re-run against the same graph the view read: a run incident's graph, else the tenant graph
  const runIncident = incident && graph !== tenantGraph(tenant) ? incident : undefined;
  return (template: string, params: Record<string, unknown>, title: string) =>
    panel.open({ template, title, origin: `GET /api/memory/overview (${graph})`, recordedParams: params, ctx: {}, incident: runIncident, tenant });
}

function QueryButton({ template, onOpen, what }: { template: string; onOpen: () => void; what: string }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex min-h-6 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
      aria-label={`${template}: open the Cypher panel for ${what}`}
    >
      {template}
    </button>
  );
}

function Panel({ id, title, icon: Icon, aside, children }: { id: string; title: string; icon: typeof Users; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`${id}-h`} className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={`${id}-h`} className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
          <Icon aria-hidden className="size-4 text-violet-300" /> {title}
        </h2>
        {aside ? <div className="ml-auto flex flex-wrap items-center gap-1">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

function ToolError({ name, error }: { name: string; error: string }) {
  return (
    <p role="alert" className="text-xs text-red-300">
      {name} failed: {error}
    </p>
  );
}

// ------------------------------------------------------------------ recall

export function RecallCard({
  data,
  incident,
  tenant,
  onSelect,
}: {
  data: MemoryOverview;
  incident: string;
  tenant: string;
  onSelect: (id: string) => void;
}) {
  const open = useOpen(data.graph, tenant, incident);
  const rec = data.recall;
  const recalled = data.recalled;
  return (
    <Panel
      id="recall"
      title={`Recall for ${incident}`}
      icon={Search}
      aside={
        <>
          {rec && rec.error === undefined ? (
            <QueryButton template={rec.template} what="recall" onOpen={() => open(rec.template, rec.params, `recall for ${incident}`)} />
          ) : null}
          {recalled ? (
            <QueryButton
              template={recalled.template}
              what="what RECALL linked during the run"
              onOpen={() => open(recalled.template, recalled.params, `RECALLED edges of ${incident}`)}
            />
          ) : null}
        </>
      }
    >
      <p className="text-xs text-zinc-400">
        Past incidents near this one in the vector index that also share a Symptom node with it (vector seed, structural
        confirmation). Similarity, recency (half-life from weights.yaml) and salience are separate columns, all computed in Cypher.
      </p>
      {!rec ? null : rec.error !== undefined ? (
        <ToolError name="similar_incidents" error={rec.error} />
      ) : rec.rows.length === 0 ? (
        <p className="text-xs text-zinc-300">Cold start: no past incident shares a symptom with {incident}.</p>
      ) : (
        <RecallTable rows={rec.rows} onSelect={onSelect} />
      )}
      {recalled ? (
        <p className="text-[11px] text-zinc-400">
          {recalled.rows.length
            ? `During its run, RECALL linked ${recalled.rows.length} precedent${recalled.rows.length === 1 ? "" : "s"} (RECALLED edges): ${recalled.rows.map((r) => r.id).join(", ")}.`
            : "No RECALLED edges: this incident was not investigated by an agent run, or its run recalled nothing."}
        </p>
      ) : null}
    </Panel>
  );
}

export function RecallTable({ rows, onSelect }: { rows: RecallRow[]; onSelect?: (id: string) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Recalled precedents with similarity, recency and salience</caption>
        <thead className="text-zinc-400">
          <tr>
            <th scope="col" className="py-0.5 pr-2 font-medium">Incident</th>
            <th scope="col" className="py-0.5 pr-2 text-right font-medium">Similarity</th>
            <th scope="col" className="py-0.5 pr-2 text-right font-medium">Recency</th>
            <th scope="col" className="py-0.5 pr-2 text-right font-medium">Salience</th>
            <th scope="col" className="py-0.5 pr-2 font-medium">Shared symptom</th>
            <th scope="col" className="py-0.5 font-medium">Fixed by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-zinc-800 align-top">
              <td className="py-1 pr-2">
                {onSelect ? (
                  <button
                    type="button"
                    onClick={() => onSelect(r.id)}
                    className="rounded font-mono text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
                    aria-label={`Recall for ${r.id}`}
                  >
                    {r.id}
                  </button>
                ) : (
                  <span className="font-mono text-zinc-100">{r.id}</span>
                )}
                {r.title ? <span className="block text-[11px] text-zinc-300">{r.title}</span> : null}
              </td>
              <td className="py-1 pr-2 text-right font-mono text-zinc-100">{fmtValue(r.similarity)}</td>
              <td className="py-1 pr-2 text-right font-mono text-zinc-100">{fmtValue(r.recency)}</td>
              <td className="py-1 pr-2 text-right font-mono text-zinc-100">{fmtValue(r.salience)}</td>
              <td className="py-1 pr-2 font-mono text-[11px] text-zinc-300">{r.shared.join(", ") || "–"}</td>
              <td className="py-1 text-zinc-200">{r.fixes.length ? r.fixes.map((f) => FIX_TEXT[f] ?? f).join(", ") : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ families

export function FamiliesCard({
  r,
  graph,
  tenant,
  incident,
  onSelect,
}: {
  r: ToolResult<FamilyRow>;
  graph: string;
  tenant: string;
  incident: string | null;
  onSelect: (id: string) => void;
}) {
  const open = useOpen(graph, tenant, incident);
  const [all, setAll] = useState(false);
  if (r.error !== undefined) {
    return (
      <Panel id="families" title="Incident families" icon={Users}>
        <ToolError name="incident_families" error={r.error} />
      </Panel>
    );
  }
  const shown = all ? r.rows : r.rows.slice(0, 8);
  return (
    <Panel
      id="families"
      title={`Incident families (${r.rows.length})`}
      icon={Users}
      aside={<QueryButton template={r.template} what="incident families" onOpen={() => open(r.template, r.params, "incident families")} />}
    >
      <p className="text-xs text-zinc-400">
        algo.labelPropagation over incidents, their symptoms and the components their causes changed. LEARN derives a runbook from a
        family once a fix has worked often enough.
      </p>
      {r.truncated ? <StatusChip tone="warn">truncated at the template LIMIT</StatusChip> : null}
      {r.rows.length === 0 ? <p className="text-xs text-zinc-300">No family of two or more incidents yet.</p> : null}
      <ul className="space-y-1.5">
        {shown.map((f) => (
          <li
            key={f.communityId}
            className={cn("rounded-md border p-2", f.mine ? "border-sky-400/60 bg-sky-500/5" : "border-zinc-800 bg-zinc-950/50")}
          >
            <p className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-medium text-zinc-100">family {f.communityId}</span>
              <span className="text-zinc-300">
                {f.size} incident{f.size === 1 ? "" : "s"}
              </span>
              {f.mine ? <StatusChip tone="info">{incident}&apos;s family</StatusChip> : null}
            </p>
            <ul className="mt-1 flex flex-wrap gap-1" aria-label={`Incidents in family ${f.communityId}`}>
              {f.incidents.slice(0, 30).map((i) => (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => onSelect(i)}
                    aria-pressed={i === incident}
                    className={cn(
                      "inline-flex min-h-6 items-center rounded border px-1.5 font-mono text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
                      i === incident ? "border-sky-400 bg-sky-500/20 text-sky-100" : "border-zinc-700 text-zinc-200 hover:bg-zinc-800",
                    )}
                  >
                    {i}
                  </button>
                </li>
              ))}
              {f.incidents.length > 30 ? <li className="text-[11px] text-zinc-400">+{f.incidents.length - 30} more</li> : null}
            </ul>
          </li>
        ))}
      </ul>
      {r.rows.length > 8 ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="text-xs text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {all ? "Show fewer families" : `Show all ${r.rows.length} families`}
        </button>
      ) : null}
    </Panel>
  );
}

// ------------------------------------------------------------------ runbooks

export function RunbooksCard({
  r,
  graph,
  tenant,
  incident,
}: {
  r: TemplateResult<RunbookRow>;
  graph: string;
  tenant: string;
  incident: string | null;
}) {
  const open = useOpen(graph, tenant, incident);
  const derived = r.rows.filter((x) => x.source === "derived").length;
  return (
    <Panel
      id="runbooks"
      title={`Runbooks in effect (${derived} derived)`}
      icon={BookOpenCheck}
      aside={<QueryButton template={r.template} what="runbooks in effect" onOpen={() => open(r.template, r.params, "runbooks in effect")} />}
    >
      <p className="text-xs text-zinc-400">
        Derived runbooks come first: LEARN writes one when a fix kind worked on a family; support counts the incidents it worked on,
        each linked by DERIVED_FROM to its postmortem.
      </p>
      {r.truncated ? <StatusChip tone="warn">truncated at the template LIMIT</StatusChip> : null}
      {r.rows.length === 0 ? (
        <p className="text-xs text-zinc-300">No runbook in effect in {graph}.</p>
      ) : (
        <ul className="space-y-1.5">
          {r.rows.map((x) => (
            <li key={x.id} className="rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
              <p className="flex flex-wrap items-center gap-1.5 text-xs">
                {x.source === "derived" ? (
                  <StatusChip tone="info" icon={Wand2}>
                    derived
                  </StatusChip>
                ) : (
                  <StatusChip tone="na" icon={User}>
                    {x.source ?? "human"}
                  </StatusChip>
                )}
                <span className="min-w-0 flex-1 text-zinc-100">{x.title ?? x.id}</span>
                <span className="font-mono text-zinc-200" title="incidents this fix worked on">
                  support {x.support}
                </span>
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-zinc-400">
                {x.id} · for {x.for_ids.join(", ") || "–"}
              </p>
              {x.derived_from.length ? (
                <details className="mt-0.5 text-[11px] text-zinc-300">
                  <summary className="cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                    DERIVED_FROM {x.derived_from.length} postmortem{x.derived_from.length === 1 ? "" : "s"}
                  </summary>
                  <p className="mt-0.5 font-mono break-words">{x.derived_from.join(", ")}</p>
                </details>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
