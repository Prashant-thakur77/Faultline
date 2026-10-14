"use client";

import { useEffect, useState } from "react";
import { Clock3, Scale } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { HYP_META } from "@/lib/gate";
import type { ContrastChange, ContrastResponse } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

/** "4 min 12 s before onset" (display only; the server computed the difference). */
export function fmtBeforeOnset(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return "–";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m} min ${r} s` : `${m} min`;
}

type Load = { state: "loading" } | { state: "ok"; data: ContrastResponse } | { state: "error"; error: string };

/**
 * Naive vs Faultline: what "blame the newest change" would have said, next to
 * what the gate decided, both from what this run recorded (GET /contrast: the run's window_changes
 * result, ordered newest first by Q-SUS-2, its pageRank result and the hypotheses). The UI decides
 * nothing: the naive pick and the verdicts come from the server; only equality is shown.
 */
export function NaiveContrast({
  incidentId,
  tenant,
  refreshKey,
  onOpenTemplate,
}: {
  incidentId: string;
  tenant: string;
  /** Re-read when the run moves on (e.g. the verdict lands). */
  refreshKey: string;
  onOpenTemplate: (template: string, title: string, origin: string, detail: string, params: Record<string, unknown>) => void;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .contrast(incidentId, tenant, ctrl.signal)
      .then((data) => setLoad({ state: "ok", data }))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setLoad({ state: "error", error: errorText(e) });
      });
    return () => ctrl.abort();
  }, [incidentId, tenant, refreshKey]);

  if (load.state === "loading") return <p className="text-xs text-zinc-300">Reading the run&apos;s recorded suspects from FalkorDB…</p>;
  if (load.state === "error") {
    return (
      <p role="alert" className="text-xs text-red-300">
        Naive contrast unavailable: {load.error}
      </p>
    );
  }
  return <ContrastView data={load.data} onOpenTemplate={onOpenTemplate} />;
}

export function ContrastView({
  data,
  onOpenTemplate,
}: {
  data: ContrastResponse;
  onOpenTemplate?: (template: string, title: string, origin: string, detail: string, params: Record<string, unknown>) => void;
}) {
  if (data.unavailable) return <p className="text-xs text-zinc-300">{data.unavailable}.</p>;
  const naive = new Set(data.naive);
  const agree = data.confirmed !== null && data.naive.length === 1 && data.naive[0] === data.confirmed;
  const wc = data.window_changes;
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-md border border-amber-400/50 bg-amber-500/5 p-2">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-amber-200 uppercase">
            <Clock3 aria-hidden className="size-3.5" /> Naive recency would blame
          </p>
          <p className="mt-0.5 font-mono text-sm text-zinc-50">{data.naive.join(", ") || "nothing (no change in the window)"}</p>
          <p className="text-[11px] text-zinc-300">
            {data.naive.length > 1
              ? `${data.naive.length} changes tie at the same instant: a coin flip between them`
              : "the newest change before onset, nothing else checked"}
          </p>
        </div>
        <div className="rounded-md border border-emerald-400/50 bg-emerald-500/5 p-2">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-emerald-200 uppercase">
            <Scale aria-hidden className="size-3.5" /> Faultline&apos;s gate decided
          </p>
          <p className="mt-0.5 font-mono text-sm text-zinc-50">{data.confirmed ?? "no confirmed cause"}</p>
          <p className="text-[11px] text-zinc-300">
            {data.confirmed ? "passed G1–G8 with a graph path (no path, no claim)" : `outcome ${data.outcome ?? "unknown"}: the gate made no claim`}
          </p>
        </div>
      </div>
      <p role="status" className="text-xs text-zinc-200">
        {data.confirmed === null ? (
          <StatusChip tone="info">naive would have blamed; the gate abstained</StatusChip>
        ) : agree ? (
          <StatusChip tone="pass">they agree on this incident</StatusChip>
        ) : naive.has(data.confirmed) ? (
          <StatusChip tone="warn">naive would have to guess: {data.naive.length} tied changes, one of them right</StatusChip>
        ) : (
          <StatusChip tone="warn">naive would have blamed the wrong change</StatusChip>
        )}
      </p>
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Every change in the window, newest first, with the gate&apos;s verdict on it</caption>
        <thead className="text-zinc-400">
          <tr>
            <th scope="col" className="py-0.5 pr-2 font-medium">Change</th>
            <th scope="col" className="py-0.5 pr-2 font-medium">Changed</th>
            <th scope="col" className="py-0.5 pr-2 font-medium">Before onset</th>
            <th scope="col" className="py-0.5 pr-2 text-right font-medium">pageRank</th>
            <th scope="col" className="py-0.5 font-medium">Gate</th>
          </tr>
        </thead>
        <tbody>
          {data.changes.map((c) => (
            <ChangeRow key={c.deploy} c={c} naive={naive.has(c.deploy)} />
          ))}
        </tbody>
      </table>
      <p className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
        From this run&apos;s recorded evidence
        {wc?.evidence_id ? <span className="font-mono">{wc.evidence_id}</span> : null}
        {wc?.template && onOpenTemplate ? (
          <button
            type="button"
            onClick={() =>
              onOpenTemplate(
                wc.template!,
                "every change in the window (naive recency's input)",
                `recorded window_changes result${wc.evidence_id ? ` (evidence ${wc.evidence_id})` : ""}`,
                wc.summary ?? "",
                wc.params,
              )
            }
            className="inline-flex min-h-6 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
            aria-label={`${wc.template}: open the Cypher panel for the window changes`}
          >
            {wc.template}
          </button>
        ) : null}
        {data.rank_causes ? <span>pageRank: the run&apos;s rank_causes result (algo.pageRank on a scratch projection)</span> : null}
      </p>
    </div>
  );
}

function ChangeRow({ c, naive }: { c: ContrastChange; naive: boolean }) {
  const meta = c.gate_status ? HYP_META[c.gate_status] : null;
  return (
    <tr className={cn("border-t border-zinc-800 align-top", c.confirmed && "bg-emerald-500/5")}>
      <td className="py-1 pr-2">
        <span className="font-mono text-zinc-100">{c.deploy}</span>
        {naive ? (
          <span className="ml-1 inline-flex">
            <StatusChip tone="warn" icon={Clock3}>
              naive pick
            </StatusChip>
          </span>
        ) : null}
      </td>
      <td className="py-1 pr-2 font-mono text-zinc-200">{c.target}</td>
      <td className="py-1 pr-2 whitespace-nowrap text-zinc-200">{fmtBeforeOnset(c.before_onset_ms)}</td>
      <td className="py-1 pr-2 text-right font-mono text-zinc-200">{c.pagerank === null ? "–" : c.pagerank.toFixed(2)}</td>
      <td className="py-1">
        {meta ? (
          <StatusChip tone={meta.tone}>{meta.text}</StatusChip>
        ) : (
          <StatusChip tone="na">not hypothesised</StatusChip>
        )}
        {c.gate_reason && c.gate_status !== "confirmed" ? (
          <span className="mt-0.5 block text-[11px] break-words text-zinc-300">{c.gate_reason}</span>
        ) : null}
      </td>
    </tr>
  );
}
