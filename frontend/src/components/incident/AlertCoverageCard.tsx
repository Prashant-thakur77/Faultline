"use client";

import { BellOff, BellRing } from "lucide-react";
import type { IncidentView } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { TemplateButton } from "./ContainmentCard";
import { FieldAbsent, fmtLag, NodeButton } from "./ReportBits";
import { Section } from "./Section";
import type { IncidentActions } from "./useIncidentActions";

/**
 * Why alerts missed it (report.why_alerts_missed_it, Q-CHAIN-MON): along the proven causal chain,
 * which hops had an alert in the window (and how long after onset) and which were silent. The
 * table is the text alternative; status is chip icon + word, never colour alone.
 */
export function AlertCoverageCard({
  view,
  mode,
  actions,
}: {
  view: IncidentView;
  mode: "live" | "replay";
  actions: IncidentActions;
}) {
  const r = view.report;
  const cov = r?.why_alerts_missed_it;
  const hops = cov?.hops ?? [];
  const tc = actions.toolCallOf("alert_coverage");
  const open = () =>
    tc
      ? actions.openToolCall(tc)
      : actions.openTemplate("Q-CHAIN-MON", "why alerts missed it", "incident report (why_alerts_missed_it)", cov?.summary, {
          chain: r?.mechanism,
        });
  const alerted = hops.filter((h) => h.alerted).length;
  const first = hops.find((h) => h.alerted) ?? null;
  const chip =
    hops.length === 0 ? null : !first ? (
      <StatusChip tone="fail" icon={BellOff}>
        no hop alerted
      </StatusChip>
    ) : first.hop === 0 ? (
      <StatusChip tone="pass" icon={BellRing}>
        origin alerted
      </StatusChip>
    ) : (
      <StatusChip tone="warn" icon={BellOff}>
        {first.hop} silent hop{first.hop === 1 ? "" : "s"} first
      </StatusChip>
    );

  return (
    <Section
      id="alerts"
      title="Why alerts missed it"
      aside={
        hops.length ? (
          <>
            {chip}
            <TemplateButton template={tc?.template ?? "Q-CHAIN-MON"} label="alert coverage along the chain" onOpen={open} />
          </>
        ) : null
      }
    >
      {!r ? (
        <p className="text-sm text-zinc-300">Appears once the gate has proven a causal chain.</p>
      ) : cov === undefined ? (
        <FieldAbsent mode={mode} what="alert coverage" where="report" />
      ) : hops.length === 0 ? (
        <p className="text-sm text-zinc-300">
          No proven causal chain, so there is no chain to check alert coverage on.
        </p>
      ) : (
        <div className="space-y-2">
          {cov.summary ? <p className="text-xs text-zinc-200">{cov.summary}.</p> : null}
          <table className="w-full text-left text-xs">
            <caption className="sr-only">
              Alert coverage along the causal chain: {alerted} of {hops.length} hops alerted
            </caption>
            <thead className="text-zinc-400">
              <tr>
                <th scope="col" className="py-0.5 pr-2 font-medium">Hop</th>
                <th scope="col" className="py-0.5 pr-2 font-medium">Node</th>
                <th scope="col" className="py-0.5 pr-2 font-medium">Alert</th>
                <th scope="col" className="py-0.5 pr-2 text-right font-medium">After onset</th>
                <th scope="col" className="py-0.5 font-medium">Telemetry</th>
              </tr>
            </thead>
            <tbody>
              {hops.map((h) => (
                <tr key={`${h.hop}:${h.id}`} className="border-t border-zinc-800 align-middle">
                  <td className="py-1 pr-2 font-mono text-zinc-300">{h.hop + 1}</td>
                  <td className="py-1 pr-2">
                    <NodeButton id={h.id} onOpen={actions.openNode} tone={h.hop === 0 ? "cause" : "default"} />
                    {h.label ? <span className="ml-1 text-[11px] text-zinc-400">{h.label}</span> : null}
                  </td>
                  <td className="py-1 pr-2">
                    {h.alerted ? (
                      <StatusChip tone="info" icon={BellRing}>
                        alerted
                      </StatusChip>
                    ) : (
                      <StatusChip tone="warn" icon={BellOff}>
                        silent
                      </StatusChip>
                    )}
                  </td>
                  <td className="py-1 pr-2 text-right font-mono text-zinc-200">{h.alerted ? fmtLag(h.first_alert_lag_s) : "–"}</td>
                  <td className="py-1 text-zinc-300">{h.has_telemetry ? "yes" : "none recorded"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
