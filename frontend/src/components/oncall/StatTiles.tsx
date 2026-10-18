"use client";

import { Hand, Moon, ShieldCheck, Users, type LucideIcon } from "lucide-react";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import type { Polled } from "@/hooks/usePolled";
import { fmtDuration, type OnCallStats } from "@/lib/oncall";
import { cn } from "@/lib/utils";
import { PanelError, useOpenQuery } from "./bits";

export const STAT_DAYS = [1, 7, 30] as const;

function Tile({ icon: Icon, label, value, note, moon }: { icon: LucideIcon; label: string; value: string; note: string; moon?: boolean }) {
  return (
    <div className="fl-card relative min-w-0 overflow-hidden rounded-2xl px-4 py-3.5 sm:px-5 sm:py-4">
      {moon ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_90%_at_100%_0%,color-mix(in_oklch,var(--fl-iris)_16%,transparent),transparent_60%)]"
        />
      ) : null}
      <dt className="relative flex items-start gap-1.5 text-xs text-zinc-400">
        <Icon aria-hidden className={cn("mt-px size-3.5 shrink-0", moon ? "text-[var(--fl-iris)]" : "text-[var(--fl-subtle)]")} />
        <span className="leading-snug">{label}</span>
      </dt>
      <dd className="relative mt-1.5 font-[510] text-[26px] leading-none tracking-[-0.02em] text-zinc-50 tabular-nums sm:text-[30px]">
        {value}
        {value === "–" ? <span className="sr-only"> (not reported)</span> : null}
      </dd>
      <dd className="relative mt-1.5 text-[11px] leading-snug text-[var(--fl-subtle)]">{note}</dd>
    </div>
  );
}

/** MTTA, MTTR, people paged and handled-under-contract over the chosen window (Q-ONCALL-STATS); "–" when not reported. */
export function StatTiles({
  polled,
  tenant,
  days,
  onDays,
}: {
  polled: Polled<OnCallStats>;
  tenant: string;
  days: number;
  onDays: (d: number) => void;
}) {
  const open = useOpenQuery(tenant);
  const s = polled.data;
  const n = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toLocaleString("en-US"));
  return (
    <section aria-labelledby="oncall-stats-h" className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 id="oncall-stats-h" className="text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
          The last {days === 1 ? "24 hours" : `${days} days`}
        </h2>
        <div role="group" aria-label="Stats window" className="inline-flex rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]">
          {STAT_DAYS.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={days === d}
              onClick={() => onDays(d)}
              className={cn(
                "h-6 rounded-full px-2.5 text-[11px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
                days === d ? "bg-zinc-50 font-medium text-zinc-950" : "text-zinc-300 hover:text-zinc-50",
              )}
            >
              {d === 1 ? "24 h" : `${d} d`}
            </button>
          ))}
        </div>
        {s?.template ? (
          <div className="ml-auto">
            <ViaFalkor template={s.template} label="the on-call stats" onOpen={() => open(s, `on-call stats, ${days} d`, "GET /api/oncall/stats")} />
          </div>
        ) : null}
      </div>
      {polled.error ? <PanelError error={polled.error} what="on-call stats (GET /api/oncall/stats)" stale={!!s} /> : null}
      <dl className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4" aria-busy={polled.loading && !s ? true : undefined}>
        <Tile icon={Hand} label="MTTA" value={s ? fmtDuration(s.mttaMs) : "–"} note="mean time to ack a page" />
        <Tile icon={ShieldCheck} label="MTTR" value={s ? fmtDuration(s.mttrMs) : "–"} note="mean time to a verified fix" />
        <Tile icon={Users} label="People paged" value={s ? n(s.peoplePaged) : "–"} note={s?.pages != null ? `${n(s.pages)} pages sent` : "humans woken"} />
        <Tile icon={Moon} label="Handled while you slept" value={s ? n(s.handledUnderContract) : "–"} note="fixed under a contract, nobody paged" moon />
      </dl>
      <p className="mt-2 text-[11px] leading-snug text-[var(--fl-subtle)]">
        On this demo the pages come from scripted incidents and the acknowledgements from the demo&apos;s own runs, so the times
        are seconds; the same query reads a real rota&apos;s pages unchanged.
      </p>
    </section>
  );
}
