"use client";

import { useId, useMemo, useState } from "react";
import { CircleX, EyeOff, PenLine } from "lucide-react";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { fmtInt } from "@/lib/format";
import { fmtEngineMs, fmtWindow, type EngineInsight, type QueryRow, type Telemetry } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { CacheBar, EngineVia, useOpenTemplate } from "./bits";
import { useTemplatePurposes } from "./useTemplatePurposes";

type Kind = "all" | "template" | "write";
const SHOWN = 12;

const KINDS: { key: Kind; label: string }[] = [
  { key: "all", label: "All" },
  { key: "template", label: "Reads (templates)" },
  { key: "write", label: "Writes" },
];

/**
 * The engine's telemetry stream aggregated per template (Q-…) or writer (W-…) id, most frequent first: runs, total
 * p50 / p95, plan-cache share and timeouts. Each template opens its Cypher; each row carries the catalogue's purpose.
 * Over every graph of the tenant, or one graph. Ad-hoc queries are counted only.
 */
export function QueriesCard({ d, tenant }: { d: EngineInsight; tenant: string }) {
  const selectId = useId();
  const [graph, setGraph] = useState<string>("");
  const [kind, setKind] = useState<Kind>("all");
  const [all, setAll] = useState(false);
  const tel: Pick<Telemetry, "entries" | "from" | "to" | "queries" | "unmapped"> =
    (graph && d.graphs.find((g) => g.name === graph)?.telemetry) || d.templates;
  const rows = useMemo(() => tel.queries.filter((r) => kind === "all" || r.kind === kind), [tel, kind]);
  const shown = all ? rows : rows.slice(0, SHOWN);
  const purposes = useTemplatePurposes(shown.map((r) => r.id));
  const open = useOpenTemplate(tenant);
  const timeouts = tel.queries.reduce((a, r) => a + (r.timeouts ?? 0), 0) + (tel.unmapped.timeouts ?? 0);
  const span = tel.from !== null && tel.to !== null ? tel.to - tel.from : null;

  return (
    <Section
      id="engine-queries"
      title="Queries by template"
      via={<EngineVia what="telemetry{graph} stream" />}
      aside={
        timeouts ? (
          <StatusChip tone="fail" icon={CircleX}>
            {timeouts} timeout{timeouts === 1 ? "" : "s"}
          </StatusChip>
        ) : tel.entries ? (
          <StatusChip tone="pass">0 timeouts</StatusChip>
        ) : null
      }
    >
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        FalkorDB records every query&apos;s wait, execution and report time, plan-cache use and write and timeout flags
        in a per-graph stream (the last {d.config.maxInfoQueries !== null ? fmtInt(d.config.maxInfoQueries) : "–"} each).
        Faultline maps each one back to its template or writer id. Percentiles are nearest-rank over{" "}
        {fmtInt(tel.entries)} quer{tel.entries === 1 ? "y" : "ies"}
        {span !== null ? ` from the last ${fmtWindow(span)}` : ""}.
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-x-4 gap-y-2">
        <label htmlFor={selectId} className="flex flex-col gap-0.5 text-[11px] text-zinc-400">
          Graph
          <select
            id={selectId}
            value={graph}
            onChange={(e) => {
              setGraph(e.target.value);
              setAll(false);
            }}
            className="h-8 max-w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 font-mono text-xs text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            <option value="">all {d.graphs.length} graphs</option>
            {d.graphs.map((g) => (
              <option key={g.name} value={g.name}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <div role="group" aria-label="Kind of query" className="flex flex-wrap gap-1">
          {KINDS.map((k) => (
            <button
              key={k.key}
              type="button"
              aria-pressed={kind === k.key}
              onClick={() => {
                setKind(k.key);
                setAll(false);
              }}
              className={cn(
                "inline-flex h-7 items-center rounded-full px-3 text-xs outline-none ring-1 focus-visible:ring-2 focus-visible:ring-sky-400",
                kind === k.key ? "bg-white/[0.08] text-zinc-50 ring-white/25" : "text-zinc-300 ring-white/10 hover:bg-white/[0.04]",
              )}
            >
              {k.label}
            </button>
          ))}
        </div>
      </div>

      {tel.entries === 0 ? (
        <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
          No query recorded yet in {graph ? `${graph}'s telemetry stream` : "these graphs' telemetry streams"}.
        </p>
      ) : rows.length === 0 ? (
        <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
          No {kind === "write" ? "write" : "template"} in this window.
        </p>
      ) : (
        <>
        {/* phones: one compact item per id (a table would push the numbers off-screen) */}
        <ul aria-label="Queries by template or writer id, most frequent first" className="divide-y divide-white/[0.06] sm:hidden">
          {shown.map((r) => (
            <QueryItem key={r.id} r={r} purpose={purposes[r.id] ?? null} onOpen={() => open(r.id, r)} />
          ))}
        </ul>
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full min-w-[560px] text-left text-xs">
            <caption className="sr-only">
              Queries in the engine&apos;s telemetry stream by template or writer id, most frequent first: runs, total time
              p50 and p95, plan-cache hits and timeouts
            </caption>
            <thead className="text-[11px] text-zinc-400">
              <tr>
                <th scope="col" className="py-1 pr-3 font-medium">Query</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">Runs</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">p50</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">p95</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">Plan cache</th>
                <th scope="col" className="py-1 text-right font-medium">Timeouts</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <QueryTr key={r.id} r={r} purpose={purposes[r.id] ?? null} onOpen={() => open(r.id, r)} />
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
      {rows.length > SHOWN ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mt-2 rounded text-xs text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {all ? `Show the top ${SHOWN}` : `Show all ${rows.length} ids`}
        </button>
      ) : null}
      {tel.unmapped.n ? (
        <p className="mt-3 flex items-start gap-1.5 text-[11px] text-zinc-400">
          <EyeOff aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--fl-subtle)]" />
          <span>
            +{fmtInt(tel.unmapped.n)} ad-hoc quer{tel.unmapped.n === 1 ? "y" : "ies"} (guarded text2cypher, the official MCP
            server, operators): counted only, never shown. p50 {fmtEngineMs(tel.unmapped.totalP50)}, p95{" "}
            {fmtEngineMs(tel.unmapped.totalP95)}.
          </span>
        </p>
      ) : null}
    </Section>
  );
}

function QueryId({ r, onOpen }: { r: QueryRow; onOpen: () => void }) {
  return r.kind === "template" ? (
    <button type="button" onClick={onOpen} className={cn(QUERY_ID_CLS, "-ml-1 text-xs text-sky-300 hover:text-sky-200")} aria-label={`${r.id}: open the Cypher panel for this template`}>
      {r.id}
    </button>
  ) : (
    <span className="inline-flex items-center gap-1 font-mono text-xs text-zinc-200">
      <PenLine aria-hidden className="size-3 text-amber-300" />
      {r.id}
    </span>
  );
}

function QueryItem({ r, purpose, onOpen }: { r: QueryRow; purpose: string | null; onOpen: () => void }) {
  return (
    <li className="py-2">
      <QueryId r={r} onOpen={onOpen} />
      <span className="block truncate text-[11px] text-zinc-400" title={purpose ?? undefined}>
        {r.kind === "write" ? "one atomic write (graph/writes.py)" : (purpose ?? "\u00a0")}
      </span>
      <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-300">
        <span>
          <span className="font-mono text-zinc-100 tabular-nums">{fmtInt(r.n)}</span> runs
        </span>
        <span>
          p50 <span className="font-mono text-zinc-100 tabular-nums">{fmtEngineMs(r.totalP50)}</span>
        </span>
        <span>
          p95 <span className="font-mono text-zinc-100 tabular-nums">{fmtEngineMs(r.totalP95)}</span>
        </span>
        <span className="inline-flex items-center gap-1">
          cache <CacheBar pct={r.cachePct} />
        </span>
        {r.timeouts ? (
          <StatusChip tone="fail" icon={CircleX}>
            {r.timeouts} timeout{r.timeouts === 1 ? "" : "s"}
          </StatusChip>
        ) : (
          <span>{r.timeouts ?? "–"} timeouts</span>
        )}
      </p>
    </li>
  );
}

function QueryTr({ r, purpose, onOpen }: { r: QueryRow; purpose: string | null; onOpen: () => void }) {
  return (
    <tr className="border-t border-white/[0.06] align-top">
      <td className="max-w-[22rem] py-1.5 pr-3">
        <QueryId r={r} onOpen={onOpen} />
        <span className="block truncate text-[11px] text-zinc-400" title={purpose ?? undefined}>
          {r.kind === "write" ? "one atomic write (graph/writes.py)" : (purpose ?? " ")}
        </span>
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-zinc-100 tabular-nums">{fmtInt(r.n)}</td>
      <td className="py-1.5 pr-3 text-right font-mono whitespace-nowrap text-zinc-100 tabular-nums">{fmtEngineMs(r.totalP50)}</td>
      <td className="py-1.5 pr-3 text-right font-mono whitespace-nowrap text-zinc-100 tabular-nums">{fmtEngineMs(r.totalP95)}</td>
      <td className="py-1.5 pr-3 text-right text-zinc-300">
        <CacheBar pct={r.cachePct} />
      </td>
      <td className="py-1.5 text-right">
        {r.timeouts ? (
          <StatusChip tone="fail" icon={CircleX}>
            {r.timeouts}
          </StatusChip>
        ) : (
          <span className="font-mono text-zinc-400 tabular-nums">{r.timeouts ?? "–"}</span>
        )}
      </td>
    </tr>
  );
}
