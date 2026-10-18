"use client";

import { Database } from "lucide-react";
import { useNow } from "@/hooks/usePolled";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { fmtEngineMs, type QueryStats } from "@/lib/engine";

/**
 * The provenance label of a panel that reads an engine command (GRAPH.MEMORY USAGE, the telemetry stream,
 * GRAPH.CONFIG) rather than a Cypher template: same quiet look as the "via FalkorDB" chip, but not a button, since
 * there is no Cypher to open.
 */
export function EngineVia({ what }: { what: string }) {
  return (
    // on a phone the command list wraps at its spaces (never cut: "db.constraints" stays readable)
    <span className="inline-flex min-h-6 max-w-full items-baseline gap-1.5 px-1 py-0.5 text-[11px] text-zinc-400">
      <Database aria-hidden className="size-3 shrink-0 translate-y-0.5 text-zinc-500" />
      <span className="shrink-0 whitespace-nowrap">via FalkorDB</span>
      <span className="shrink-0 text-[var(--fl-subtle)]">·</span>
      <span className="min-w-0 font-mono break-words">{what}</span>
    </span>
  );
}

/** Opens the Cypher panel for a template id seen in the engine's telemetry (the stream keeps no parameters). */
export function useOpenTemplate(tenant: string) {
  const panel = useCypherPanel();
  return (id: string, s: QueryStats | null) =>
    panel.open({
      template: id,
      title: `${id} · engine telemetry`,
      origin: "the engine's telemetry stream (GET /api/engine/insight)",
      detail: s
        ? `${s.n} run${s.n === 1 ? "" : "s"} in the stream window: total p50 ${fmtEngineMs(s.totalP50)}, p95 ${fmtEngineMs(s.totalP95)}; plan cache ${s.cachePct ?? "–"}%; the stream keeps ids and timings, not parameters.`
        : "Seen in the engine's telemetry stream, which keeps ids and timings, not parameters.",
      recordedParams: null,
      ctx: {},
      tenant,
    });
}

/** A plan-cache hit share as a bar plus the number (the bar is decorative). */
export function CacheBar({ pct }: { pct: number | null }) {
  const v = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className="h-1.5 w-12 overflow-hidden rounded-full bg-white/[0.08]">
        <span className="block h-full rounded-full bg-[var(--fl-iris)]" style={{ width: `${v}%` }} />
      </span>
      <span className="w-12 text-right font-mono tabular-nums">{pct === null ? "–" : `${+pct.toFixed(1)}%`}</span>
    </span>
  );
}

/** "updated 3 s ago": its own one-second clock, so the tables around it do not re-render every second. */
export function UpdatedAgo({ at }: { at: number }) {
  const now = useNow(1000);
  return <>updated {Math.max(0, Math.round((now - at) / 1000))} s ago</>;
}
