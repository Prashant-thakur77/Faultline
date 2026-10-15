"use client";

import { useRef, useState } from "react";
import { Popover } from "@base-ui/react/popover";
import { CircleCheck, CircleX, Info, LoaderCircle, RefreshCcw, TriangleAlert, X } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { fmtInt, fmtMs, fmtTime, shortDigest } from "@/lib/format";
import type { RearmResponse } from "@/lib/types";
import type { StatusState } from "@/hooks/useStatus";
import { Button } from "@/components/ui/button";

type RearmResult = { ok: true; res: RearmResponse; at: number } | { ok: false; status: number | null; text: string; at: number };

/**
 * "Reset demo data (all visitors)" (POST /api/demo/rearm: GRAPH.COPY golden → tenant graph;
 * 1/min per visitor), behind an inline confirm step because it resets the graph every visitor
 * sees, with its result inline, and a Demo status popover (engine, counts, last re-arm, LLM configured), all
 * from /api/status and the re-arm response. Nothing is shown that the API did not return.
 */
export function DemoControls({ state }: { state: StatusState }) {
  const tenant = useTenant();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const resetRef = useRef<HTMLButtonElement>(null);
  const cancel = () => {
    setConfirming(false);
    requestAnimationFrame(() => resetRef.current?.focus()); // keep keyboard focus on the control
  };
  const [last, setLast] = useState<RearmResult | null>(null);
  const [lastOk, setLastOk] = useState<{ res: RearmResponse; at: number } | null>(null);
  const s = state.status;

  const rearm = async () => {
    setConfirming(false);
    setBusy(true);
    try {
      const res = await api.rearm(tenant);
      const at = Date.now();
      setLast({ ok: true, res, at });
      setLastOk({ res, at });
      state.refresh?.();
    } catch (e) {
      setLast({
        ok: false,
        status: e instanceof ApiError ? e.status : null,
        text: e instanceof ApiError ? e.detail : errorText(e),
        at: Date.now(),
      });
    } finally {
      setBusy(false);
      requestAnimationFrame(() => resetRef.current?.focus());
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {confirming ? (
        <span
          role="group"
          aria-label="Confirm reset"
          onKeyDown={(e) => {
            if (e.key === "Escape") cancel();
          }}
          className="inline-flex flex-wrap items-center gap-1.5 text-xs text-amber-200"
        >
          <TriangleAlert aria-hidden className="size-3.5 text-amber-300" />
          Restores the demo graph from its golden copy for every visitor.
          <Button size="sm" className="bg-red-700 text-white hover:bg-red-800" onClick={() => void rearm()} autoFocus>
            Reset now
          </Button>
          <Button size="sm" variant="outline" onClick={cancel}>
            Cancel
          </Button>
        </span>
      ) : (
        <Button
          ref={resetRef}
          size="sm"
          variant="outline"
          onClick={() => setConfirming(true)}
          disabled={busy}
          title="Restore the tenant graph from its golden copy (GRAPH.COPY) for all visitors; asks to confirm; rate-limited to once a minute"
        >
          {busy ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <RefreshCcw aria-hidden />}
          Reset demo data (all visitors)
        </Button>
      )}
      <span aria-live="polite" className="text-xs">
        {last ? (
          last.ok ? (
            <span className="inline-flex items-center gap-1 text-emerald-300">
              <CircleCheck aria-hidden className="size-3.5" />
              Reset {last.res.dst} from {last.res.src} in {fmtMs(last.res.ms)}
            </span>
          ) : (
            <span role="alert" className="inline-flex items-center gap-1 text-red-300">
              <CircleX aria-hidden className="size-3.5" />
              {last.status === 429 ? `Reset rate-limited: ${last.text}. Try again in a minute.` : `Reset failed: ${last.text}`}
              <button
                type="button"
                onClick={() => setLast(null)}
                className="rounded p-0.5 outline-none hover:bg-red-500/20 focus-visible:ring-2 focus-visible:ring-red-300"
                aria-label="Dismiss the reset message"
              >
                <X aria-hidden className="size-3" />
              </button>
            </span>
          )
        ) : null}
      </span>

      <Popover.Root>
        <Popover.Trigger
          render={<Button size="sm" variant="outline" />}
        >
          <Info aria-hidden /> Demo status
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Positioner sideOffset={6} align="end" className="z-50">
            <Popover.Popup className="w-80 rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-xs text-zinc-200 shadow-xl outline-none">
              <Popover.Title className="mb-2 text-sm font-semibold text-zinc-50">Demo status</Popover.Title>
              {!s ? (
                <p role="alert" className="text-red-300">
                  {state.error ? `API unreachable: ${state.error}` : "Waiting for /api/status…"}
                </p>
              ) : (
                <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1">
                  <dt className="text-zinc-400">status</dt>
                  <dd className={s.status === "ok" ? "text-emerald-300" : "text-red-300"}>
                    {s.status === "ok" ? "✓ ok" : `✗ unavailable${s.reason ? `: ${s.reason}` : ""}`}
                  </dd>
                  <dt className="text-zinc-400">engine</dt>
                  <dd className="font-mono break-all" title={s.engine.digest}>
                    FalkorDB {s.engine.engine} · {shortDigest(s.engine.digest)}
                  </dd>
                  <dt className="text-zinc-400">graph</dt>
                  <dd className="font-mono">{s.graph}</dd>
                  <dt className="text-zinc-400">counts</dt>
                  <dd className="font-mono">
                    {s.counts ? `${fmtInt(s.counts.nodes)} nodes · ${fmtInt(s.counts.edges)} edges` : "–"}
                  </dd>
                  <dt className="text-zinc-400">templates</dt>
                  <dd className="font-mono">{fmtInt(s.templates)}</dd>
                  <dt className="text-zinc-400">release</dt>
                  <dd className="font-mono">{s.version ? `v${s.version}` : "–"}</dd>
                  <dt className="text-zinc-400">seeded</dt>
                  <dd>{s.ready ? fmtTime(s.ready.seeded_at) : "–"}</dd>
                  <dt className="text-zinc-400">last reset</dt>
                  <dd>
                    {lastOk ? (
                      <>
                        {fmtTime(lastOk.at)} · {fmtMs(lastOk.res.ms)} · {lastOk.res.indexes} indexes
                        <span className="block text-zinc-400">(this browser session)</span>
                      </>
                    ) : (
                      <span className="text-zinc-400">none this session</span>
                    )}
                  </dd>
                  <dt className="text-zinc-400">LLM</dt>
                  <dd>
                    {s.llm_configured ? (
                      <span className="text-emerald-300">✓ configured</span>
                    ) : (
                      <span className="text-amber-300">✗ not configured: keyless baseline only</span>
                    )}
                    <span className="block font-mono text-[11px] text-zinc-400">
                      investigator: {s.models.orchestrator} · specialists: {s.models.specialists}
                    </span>
                  </dd>
                  <dt className="text-zinc-400">ablation</dt>
                  <dd>{s.graph_disabled ? <span className="text-red-300">✗ graph disabled (A4)</span> : "graph enabled"}</dd>
                </dl>
              )}
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
