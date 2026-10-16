"use client";

import { AlarmClock, BellRing, CircleHelp, Clock, Users } from "lucide-react";
import type { IncidentView, Obligations } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { Disclosure } from "@/components/ui/Disclosure";
import { Section } from "./Section";

/** "~42 min" / "~3.5 h" / "~2.0 days"; "no breach projected" (display only: the server computed the minutes). */
export function fmtBreach(m: number | null | undefined): string {
  if (m === null || m === undefined || !Number.isFinite(m)) return "no breach projected";
  if (m < 120) return `~${m.toFixed(0)} min`;
  if (m < 2880) return `~${(m / 60).toFixed(1)} h`;
  return `~${(m / 1440).toFixed(1)} days`;
}

const SLO_STATUS: Record<string, { tone: "fail" | "warn" | "pass" | "na"; text: string }> = {
  breached: { tone: "fail", text: "breached" },
  burning: { tone: "warn", text: "burning" },
  within_budget: { tone: "pass", text: "within budget" },
  unmeasured: { tone: "na", text: "unmeasured" },
};

function isObligations(o: unknown): o is Obligations {
  return !!o && typeof o === "object" && "reason" in o;
}

/**
 * Obligations at risk: the obligation clock the run recorded in ROUTE (report.obligations): time to
 * the soonest SLO breach, customers reached through the failure, and the one decision it makes,
 * whether this pages now. It decides urgency only, never the cause. Every value is the server's.
 */
export function ObligationsCard({ view, mode, onOpenEvidence }: { view: IncidentView; mode: "live" | "replay"; onOpenEvidence: (id: string) => void }) {
  const o = view.report?.obligations;
  const running = !view.run.outcome || view.run.outcome === "RUNNING";
  let body: React.ReactNode;
  let aside: React.ReactNode = null;
  if (!view.report) {
    body = <p className="text-sm text-zinc-300">{running ? "The obligation clock runs in ROUTE, after the gate decides." : "No report recorded."}</p>;
  } else if (!isObligations(o)) {
    body = (
      <p className="text-sm text-zinc-300">
        {mode === "replay"
          ? "Not in this recording: it was made before the obligation clock existed."
          : "No obligation clock was recorded for this run (no SLO or customer data, or an older backend)."}
      </p>
    );
  } else {
    aside =
      o.urgent === null ? (
        <StatusChip tone="na" icon={CircleHelp}>
          urgency unknown
        </StatusChip>
      ) : o.urgent ? (
        <StatusChip tone="fail" icon={BellRing}>
          URGENT: page now
        </StatusChip>
      ) : (
        <StatusChip tone="info" icon={Clock}>
          not urgent
        </StatusChip>
      );
    body = <ObligationsBody o={o} onOpenEvidence={onOpenEvidence} />;
  }
  return (
    <Section id="obligations" title="Obligations at risk" aside={aside}>
      {body}
    </Section>
  );
}

export function ObligationsBody({ o, onOpenEvidence }: { o: Obligations; onOpenEvidence?: (id: string) => void }) {
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-white/[0.03] px-3 py-2.5">
          <dt className="flex items-center gap-1 text-zinc-400">
            <AlarmClock aria-hidden className="size-3.5" /> time to SLO breach
          </dt>
          <dd className="mt-1 font-mono text-lg leading-tight text-zinc-50">{fmtBreach(o.breach?.breach_in_min)}</dd>
          {o.breach ? (
            <dd className="text-[11px] text-zinc-300">
              <span className="font-mono">{o.breach.slo}</span> on <span className="font-mono">{o.breach.service}</span>
            </dd>
          ) : null}
          {o.page_within_min !== null ? <dd className="text-[11px] text-zinc-400">paging line: {o.page_within_min.toFixed(0)} min</dd> : null}
        </div>
        <div className="rounded-lg bg-white/[0.03] px-3 py-2.5">
          <dt className="flex items-center gap-1 text-zinc-400">
            <Users aria-hidden className="size-3.5" /> customers reached
          </dt>
          <dd className="mt-1 font-mono text-lg leading-tight text-zinc-50">{o.customers_reached}</dd>
          <dd className="text-[11px] text-zinc-300">{o.revenue_at_risk.toLocaleString("en-US", { maximumFractionDigits: 0 })} MRR at risk</dd>
        </div>
      </dl>
      <p className="text-xs leading-relaxed break-words text-zinc-400">
        {o.reason}.
        {o.evidence_id && onOpenEvidence ? (
          <>
            {" "}
            <button
              type="button"
              onClick={() => onOpenEvidence(o.evidence_id!)}
              className={QUERY_ID_CLS}
              aria-label={`Evidence ${o.evidence_id}: open the obligation clock's queries`}
            >
              {o.evidence_id}
            </button>
          </>
        ) : null}
      </p>
      <Disclosure
        size="xs"
        summary={
          <>
            SLOs on the failure path
            <span className="text-[var(--fl-subtle)]"> · {o.slos.length}</span>
          </>
        }
      >
      {o.slos.length ? (
        <table className="w-full text-left text-xs">
          <caption className="sr-only">SLOs on the failing component and its blast radius, most burning first</caption>
          <thead className="text-zinc-400">
            <tr>
              <th scope="col" className="py-0.5 pr-2 font-medium">SLO</th>
              <th scope="col" className="py-0.5 pr-2 text-right font-medium">Burn</th>
              <th scope="col" className="py-0.5 pr-2 text-right font-medium">Budget left</th>
              <th scope="col" className="py-0.5 font-medium">Breach</th>
            </tr>
          </thead>
          <tbody>
            {o.slos.slice(0, 8).map((s) => {
              const st = SLO_STATUS[s.status] ?? { tone: "na" as const, text: s.status };
              return (
                <tr key={`${s.slo}:${s.service}`} className="border-t border-white/[0.06] align-top">
                  <td className="py-1 pr-2">
                    <span className="font-mono text-zinc-100">{s.slo}</span>
                    <span className="block text-[11px] text-zinc-400">{s.service}</span>
                  </td>
                  <td className="py-1 pr-2 text-right font-mono text-zinc-100">{s.burn === null ? "–" : `${s.burn.toFixed(1)}x`}</td>
                  <td className="py-1 pr-2 text-right font-mono text-zinc-100">{`${Math.round(s.budget_remaining * 100)}%`}</td>
                  <td className="py-1">
                    <StatusChip tone={st.tone}>{st.text}</StatusChip>
                    <span className="mt-0.5 block text-[11px] text-zinc-300">{fmtBreach(s.breach_in_min)}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="text-xs text-zinc-300">No SLO covers the failing component or its blast radius.</p>
      )}
      {o.slos.length > 8 ? <p className="text-[11px] text-zinc-400">+{o.slos.length - 8} more SLOs (in the report).</p> : null}
      </Disclosure>
      {o.customers.length ? (
        <Disclosure
          size="xs"
          summary={`${o.customers.length} customer${o.customers.length === 1 ? "" : "s"} reached, with the nearest failure path`}
        >
          <ul className="space-y-0.5 text-xs text-zinc-300">
            {o.customers.map((c) => (
              <li key={c.customer} className="text-[11px]">
                <span className="font-mono text-zinc-100">{c.customer}</span> {c.name ?? ""} ·{" "}
                {c.mrr.toLocaleString("en-US", { maximumFractionDigits: 0 })} MRR · <span className="font-mono">{c.path.join(" → ")}</span>
              </li>
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </div>
  );
}
