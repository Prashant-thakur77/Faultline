"use client";

import { Activity, Clock, Gauge, Globe, Layers, MemoryStick, ScrollText, ShieldAlert, type LucideIcon } from "lucide-react";
import { Section } from "@/components/incident/Section";
import { fmtInt } from "@/lib/format";
import { fmtBytes, type EngineInsight } from "@/lib/engine";
import { REPO_URL } from "@/lib/site";
import { EngineVia } from "./bits";

function seconds(ms: number | null): string {
  if (ms === null) return "–";
  return ms >= 1000 ? `${+(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function Guard({ icon: Icon, title, value, children, warn }: { icon: LucideIcon; title: string; value: string; children?: React.ReactNode; warn?: boolean }) {
  return (
    <li className="flex gap-3 rounded-xl bg-white/[0.02] px-3.5 py-2.5 ring-1 ring-white/[0.06]">
      {warn ? (
        <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-300" />
      ) : (
        <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--fl-subtle)]" />
      )}
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
          <span className="text-zinc-200">{title}</span>
          <span className={warn ? "font-mono text-amber-200" : "font-mono text-zinc-50"}>{value}</span>
        </p>
        {children ? <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-400">{children}</p> : null}
      </div>
    </li>
  );
}

const doc = (p: string) =>
  REPO_URL ? (
    <a href={`${REPO_URL}/blob/main/${p}`} className="rounded text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400" rel="noreferrer" target="_blank">
      {p}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ) : (
    <code className="font-mono text-zinc-300">{p}</code>
  );

/** The limits the engine enforces on every query (GRAPH.CONFIG GET), its load now (GRAPH.INFO), and the network guard. */
export function GuardsCard({ d }: { d: EngineInsight }) {
  const c = d.config;
  const cap = c.queryMemCapacity;
  return (
    <Section id="engine-guards" title="Engine guards" via={<EngineVia what="GRAPH.CONFIG · GRAPH.INFO" />}>
      <ul className="space-y-2" aria-label="Engine limits">
        <Guard
          icon={MemoryStick}
          title="Memory per query"
          value={cap === null ? "not reported" : cap === 0 ? "no cap" : fmtBytes(cap)}
          warn={cap === 0}
        >
          QUERY_MEM_CAPACITY: a query that needs more is stopped by the engine, raw read-only Cypher included
          {cap === 0 ? " (0 means unlimited)" : ""}.
        </Guard>
        <Guard
          icon={Clock}
          title="Query timeout"
          value={`${seconds(c.timeoutDefault)} default · ${seconds(c.timeoutMax)} max`}
          warn={c.timeoutDefault === 0 || c.timeoutMax === 0}
        >
          TIMEOUT_DEFAULT applies when a query sets none; TIMEOUT_MAX caps what any query may ask for.
        </Guard>
        <Guard icon={Layers} title="Queue and threads" value={`${c.maxQueuedQueries ?? "–"} queued · ${c.threadCount ?? "–"} threads`}>
          MAX_QUEUED_QUERIES and THREAD_COUNT: beyond the queue the engine refuses new work instead of slowing every query.
        </Guard>
        <Guard icon={Gauge} title="Plan cache" value={`${c.cacheSize ?? "–"} plans`}>
          CACHE_SIZE: Faultline&apos;s queries are fixed, parameterised templates, so their plans are reused.
        </Guard>
        <Guard icon={ScrollText} title="Telemetry window" value={`last ${c.maxInfoQueries !== null ? fmtInt(c.maxInfoQueries) : "–"} per graph`}>
          MAX_INFO_QUERIES: how many queries each graph&apos;s stream keeps for this page.
        </Guard>
        <Guard icon={Activity} title="Load now" value={`${d.load.running ?? "–"} running · ${d.load.waiting ?? "–"} waiting`}>
          GRAPH.INFO, engine-wide.
        </Guard>
        <Guard icon={Globe} title="Internet egress" value="none in production">
          The production compose puts FalkorDB on an internal Docker network with no route out, so a query cannot fetch
          from the internet (LOAD CSV). The development compose does not isolate it. See {doc("docs/HONEST_LIMITS.md")}.
        </Guard>
      </ul>
    </Section>
  );
}
