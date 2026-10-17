"use client";

import { useState } from "react";
import { Database, LoaderCircle, OctagonAlert, Pause, ShieldCheck, Unplug } from "lucide-react";
import { useAppStatus } from "@/components/AppShell";
import { StatusChip } from "@/components/StatusChip";
import { usePolled } from "@/hooks/usePolled";
import { ApiError, errorText } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { engineApi, fmtEngineMs, fmtWindow, insightSummary, type EngineInsight } from "@/lib/engine";
import { endpointMissing } from "@/lib/oncall";
import { useTenant } from "@/lib/tenant";
import { cn } from "@/lib/utils";
import { UpdatedAgo } from "./bits";
import { GuardsCard } from "./EngineGuards";
import { MemoryCard } from "./EngineMemory";
import { QueriesCard } from "./EngineQueries";
import { LiveTail } from "./EngineTail";

export const ENGINE_POLL_MS = 5_000;

/** One honest sentence for a failed read. */
export function insightErrorText(err: unknown): string {
  const what = "Inside FalkorDB (GET /api/engine/insight)";
  if (!(err instanceof ApiError)) return `${what} failed: ${errorText(err)}`;
  const d = err.detail.replace(/\.$/, "");
  if (endpointMissing(err)) return `${what}: this API has no such endpoint (HTTP ${err.status}), so the engine panel is not deployed on this server.`;
  if (err.status === null) return `${what} is unavailable: ${d}.`;
  if (err.status === 503) return `FalkorDB is unavailable: ${d} (HTTP 503). Nothing is shown in its place.`;
  if (err.status === 429) return `${what} is rate-limited: ${d} (HTTP 429). The next read retries.`;
  return `${what} failed: ${d} (HTTP ${err.status}).`;
}

/**
 * /engine: FalkorDB observing itself for the selected tenant, re-read every 5 s while the tab is visible (pause
 * freezes it). The verdict line, memory per graph (GRAPH.MEMORY USAGE), queries per template from the engine's own
 * telemetry stream, the live tail and the engine's guards. Fails loudly; never shows sample numbers.
 */
export function EngineView() {
  const tenant = useTenant();
  const [paused, setPaused] = useState(false);
  const polled = usePolled(`engine|${tenant}`, (s) => engineApi.insight(tenant, s), { intervalMs: ENGINE_POLL_MS, enabled: !paused });
  const d = polled.data;
  // errors are announced by their own role=alert line; this region only says live or paused
  const live = paused ? "Paused: the numbers stay as last read." : d ? "Live: re-read every 5 seconds." : "";

  return (
    <div className="mx-auto w-full max-w-[1400px] space-y-4 px-5 py-6 sm:px-8">
      {/* announced on change only: the numbers below change every few seconds and are not read out */}
      <p className="sr-only" aria-live="polite">
        {live}
      </p>
      <EngineVerdict d={d} error={polled.error} loading={polled.loading} paused={paused} at={polled.at} />
      {polled.error ? (
        <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-100 ring-1 ring-red-500/40">
          <OctagonAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
          <span>
            {insightErrorText(polled.error)}
            {d ? " Showing the last answer the engine gave; it may be out of date." : ""}
          </span>
        </p>
      ) : null}
      {d ? (
        <>
          <MemoryCard d={d} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
            <div className="min-w-0">
              <QueriesCard d={d} tenant={tenant} />
            </div>
            <div className="min-w-0 space-y-4">
              <LiveTail d={d} tenant={tenant} paused={paused} onPause={setPaused} at={polled.at} />
              <GuardsCard d={d} />
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** One sentence first: which engine, how much of it this tenant uses, and how fast its queries run. */
export function EngineVerdict({
  d,
  error,
  loading,
  paused,
  at,
}: {
  d: EngineInsight | null;
  error: unknown;
  loading: boolean;
  paused: boolean;
  /** When this answer was read (client clock). */
  at: number | null;
}) {
  const status = useAppStatus().status;
  // the engine names itself in the insight response; /api/status only for a server that does not
  const version = d?.engine?.version ?? status?.engine?.engine ?? null;
  let icon = <LoaderCircle aria-hidden className="size-6 text-zinc-400 motion-safe:animate-spin" />;
  let head = "Reading FalkorDB's own memory and telemetry…";
  let tone = "bg-zinc-600";
  let sub: React.ReactNode = null;
  if (!d && error) {
    icon = endpointMissing(error) ? <Unplug aria-hidden className="size-6 text-red-300" /> : <OctagonAlert aria-hidden className="size-6 text-red-300" />;
    head = endpointMissing(error) ? "The engine panel is not on this server" : "FalkorDB's own numbers are unavailable: see below";
    tone = "bg-red-400";
  } else if (d) {
    const s = insightSummary(d);
    icon = <Database aria-hidden className="size-6 text-[var(--fl-iris)]" />;
    tone = s.timeouts ? "bg-red-400" : "bg-[var(--fl-iris)]";
    head = [
      `FalkorDB${version ? ` ${version}` : ""}`,
      `${s.graphs} graph${s.graphs === 1 ? "" : "s"} for ${d.tenant}`,
      s.memoryMb !== null ? `${s.memoryMb} MB` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    sub = (
      <>
        {s.entries ? (
          <>
            {fmtInt(s.entries)} quer{s.entries === 1 ? "y" : "ies"}
            {s.windowMs !== null ? ` in the last ${fmtWindow(s.windowMs)}` : ""}
            {s.overallP50 !== null ? (
              <>
                {" · "}p50 {fmtEngineMs(s.overallP50)}, p95 {fmtEngineMs(s.overallP95)}
                {s.busiest ? (
                  <>
                    {" · busiest "}
                    <span className="font-mono text-zinc-200">{s.busiest.id}</span>
                  </>
                ) : null}
              </>
            ) : s.busiest ? (
              // a server without the overall percentiles: the busiest template's own
              <>
                {" · busiest "}
                <span className="font-mono text-zinc-200">{s.busiest.id}</span> p50 {fmtEngineMs(s.busiest.totalP50)}, p95{" "}
                {fmtEngineMs(s.busiest.totalP95)}
              </>
            ) : null}
            {" · "}
            <span className={s.timeouts ? "text-red-200" : undefined}>
              {s.timeouts} timeout{s.timeouts === 1 ? "" : "s"}
            </span>
            {s.cachePct !== null ? ` · plan cache ${Math.round(s.cachePct)}%` : ""}
          </>
        ) : (
          "No query recorded in the telemetry streams yet"
        )}
        {" · "}
        {d.load.running ?? "–"} running, {d.load.waiting ?? "–"} waiting now
      </>
    );
  } else if (!loading) {
    head = "No answer from FalkorDB yet";
  }
  return (
    <section aria-labelledby="engine-verdict" className="fl-card relative overflow-hidden rounded-2xl px-5 py-4">
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", tone)} />
      <div className="flex flex-wrap items-start gap-x-5 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-[20rem] items-start gap-3">
          <span className="mt-0.5 shrink-0">{icon}</span>
          <div className="min-w-0">
            <h2 id="engine-verdict" className="text-[17px] font-[560] leading-snug tracking-[-0.01em] text-zinc-50 sm:text-lg">
              {head}
            </h2>
            {sub ? <p className="mt-0.5 text-xs leading-relaxed text-zinc-400">{sub}</p> : null}
          </div>
        </div>
        {d ? (
          <div className="flex w-full min-w-0 flex-col items-start gap-1 text-xs text-zinc-400 sm:w-auto sm:max-w-[40%] sm:items-end sm:text-right">
            <StatusChip tone={paused ? "warn" : "info"} icon={paused ? Pause : Database}>
              {paused ? "paused" : "live · every 5 s"}
            </StatusChip>
            {at !== null ? (
              <p>
                <UpdatedAgo at={at} />
              </p>
            ) : null}
            <p className="inline-flex items-center gap-1">
              <ShieldCheck aria-hidden className="size-3.5 text-[var(--fl-subtle)]" />
              {d.privacy ?? "ids and timings only"}
            </p>
          </div>
        ) : null}
      </div>
      {d?.source ? <p className="mt-2 text-[11px] text-[var(--fl-subtle)]">Source: {d.source}.</p> : null}
    </section>
  );
}
