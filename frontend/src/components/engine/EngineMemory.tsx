"use client";

import { HardDrive } from "lucide-react";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import { Disclosure } from "@/components/ui/Disclosure";
import { fmtInt } from "@/lib/format";
import { ROLE_TEXT, type EngineInsight, type GraphInsight, type GraphMemory } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { EngineVia } from "./bits";

type Part = { key: string; label: string; cls: string; mb: (m: GraphMemory) => number | null };

/** The parts GRAPH.MEMORY USAGE itemises, in one fixed order and colour (the colours are decorative; the words carry it). */
export const PARTS: Part[] = [
  {
    key: "matrices",
    label: "Adjacency matrices",
    cls: "bg-[var(--fl-iris)]",
    mb: (m) => (m.labelMatricesMb === null && m.relationMatricesMb === null ? null : (m.labelMatricesMb ?? 0) + (m.relationMatricesMb ?? 0)),
  },
  { key: "nodes", label: "Node block", cls: "bg-sky-400", mb: (m) => m.nodeBlockMb },
  { key: "nattr", label: "Node attributes", cls: "bg-emerald-400", mb: (m) => m.nodeAttributesMb },
  { key: "eattr", label: "Edge attributes", cls: "bg-amber-300", mb: (m) => m.edgeAttributesMb },
  { key: "idx", label: "Indices", cls: "bg-rose-300", mb: (m) => m.indicesMb },
];

/** What the itemised parts leave of the total (the engine rounds each part to whole MB); null when nothing is left. */
export function notItemised(m: GraphMemory): number | null {
  if (m.totalMb === null) return null;
  const sum = PARTS.reduce((a, p) => a + (p.mb(m) ?? 0), 0);
  return m.totalMb - sum > 0 ? m.totalMb - sum : null;
}

export function MemoryCard({ d }: { d: EngineInsight }) {
  const total = d.graphs.reduce<number | null>((a, g) => (g.memory.totalMb === null ? a : (a ?? 0) + g.memory.totalMb), null);
  return (
    <Section
      id="engine-memory"
      title="Memory per graph"
      via={<EngineVia what="GRAPH.MEMORY USAGE" />}
      aside={
        d.graphs.length ? (
          <StatusChip tone="na" icon={HardDrive}>
            {d.graphs.length} graph{d.graphs.length === 1 ? "" : "s"} · {total ?? "–"} MB
          </StatusChip>
        ) : null
      }
    >
      <p className="mb-3 max-w-4xl text-xs leading-relaxed text-zinc-400">
        FalkorDB stores each graph as sparse adjacency matrices (GraphBLAS): one matrix per label and one per relationship
        type, and a traversal is a sparse matrix operation over them. Sizes are what GRAPH.MEMORY USAGE reports, in whole
        megabytes, so the parts of a small graph read 0.
      </p>
      {d.graphs.length === 0 ? (
        <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
          No graph of {d.tenant || "this tenant"} exists in FalkorDB yet (seed it with <code className="font-mono">make seed</code>).
        </p>
      ) : (
        <>
          <ul aria-label="Memory legend" className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-400">
            {PARTS.map((p) => (
              <li key={p.key} className="inline-flex items-center gap-1.5">
                <span aria-hidden className={cn("size-2.5 rounded-sm", p.cls)} />
                {p.label}
              </li>
            ))}
            <li className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-sm bg-white/[0.14]" />
              Not itemised (rounding)
            </li>
          </ul>
          <ul aria-label="Graphs of this tenant" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {d.graphs.map((g) => (
              <GraphTile key={g.name} g={g} />
            ))}
          </ul>
          {d.roomsNotReported > 0 ? (
            <p className="mt-2 text-[11px] text-zinc-400">
              +{d.roomsNotReported} more clean room{d.roomsNotReported === 1 ? "" : "s"} not reported (the API lists the first ones only).
            </p>
          ) : null}
        </>
      )}
    </Section>
  );
}

function GraphTile({ g }: { g: GraphInsight }) {
  const m = g.memory;
  const rest = notItemised(m);
  const base = m.totalMb && m.totalMb > 0 ? m.totalMb : null;
  const top = [...m.byLabel.map((x) => ({ ...x, what: "label" })), ...m.byType.map((x) => ({ ...x, what: "type" }))]
    .filter((x) => x.mb > 0)
    .sort((a, b) => b.mb - a.mb)
    .slice(0, 6);
  return (
    <li className="min-w-0 rounded-xl bg-white/[0.02] px-3.5 py-3 ring-1 ring-white/[0.06]">
      <p className="truncate font-mono text-xs text-zinc-100" title={g.name}>
        {g.name}
      </p>
      <p className="text-[11px] text-zinc-400">{ROLE_TEXT[g.role]}</p>
      <p className="mt-1.5 font-[510] text-[26px] leading-none tracking-[-0.02em] text-zinc-50 tabular-nums">
        {m.totalMb ?? "–"}
        <span className="ml-1 text-sm font-normal text-zinc-400">MB</span>
      </p>
      {/* decorative: the list below carries every number */}
      <div aria-hidden className="mt-2 flex h-2 w-full overflow-hidden rounded-full bg-white/[0.05]">
        {base
          ? PARTS.map((p) => {
              const v = p.mb(m) ?? 0;
              return v > 0 ? <span key={p.key} className={p.cls} style={{ width: `${(100 * v) / base}%` }} /> : null;
            })
          : null}
        {base && rest ? <span className="bg-white/[0.14]" style={{ width: `${(100 * rest) / base}%` }} /> : null}
      </div>
      <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 text-[11px] text-zinc-400">
        {PARTS.map((p) => (
          <div key={p.key} className="contents">
            <dt className="truncate">{p.label}</dt>
            <dd className="text-right font-mono text-zinc-200 tabular-nums">{p.mb(m) ?? "–"} MB</dd>
          </div>
        ))}
        {rest ? (
          <div className="contents">
            <dt className="truncate">Not itemised</dt>
            <dd className="text-right font-mono text-zinc-200 tabular-nums">{rest} MB</dd>
          </div>
        ) : null}
      </dl>
      <p className="mt-1.5 text-[11px] text-zinc-400">
        {fmtInt(g.telemetry.entries)} quer{g.telemetry.entries === 1 ? "y" : "ies"} in its telemetry stream
      </p>
      <Disclosure className="mt-1" size="xs" defaultOpen={false} summary="Largest labels and types">
        {top.length ? (
          <ul className="space-y-0.5 text-[11px] text-zinc-300">
            {top.map((x) => (
              <li key={`${x.what}:${x.name}`} className="flex justify-between gap-2">
                <span className="truncate font-mono">
                  {x.what === "type" ? `[:${x.name}]` : `(:${x.name})`}
                </span>
                <span className="font-mono tabular-nums">{x.mb} MB</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[11px] text-zinc-400">
            Every label&apos;s and relationship type&apos;s attributes read 0 MB ({m.byLabel.length} labels, {m.byType.length} types).
          </p>
        )}
      </Disclosure>
    </li>
  );
}
