"use client";

import { CircleAlert, Info, Scale } from "lucide-react";
import type { IncidentView } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { TemplateButton } from "./ContainmentCard";
import { FieldAbsent, NodeButton } from "./ReportBits";
import { Section } from "./Section";
import type { IncidentActions } from "./useIncidentActions";

/**
 * Residue check (report.residue, Q-RESIDUE-1): the confirmed cause explains k of n components
 * measured anomalous; the rest mean another fault may be active. Advisory: it never changes the
 * gate's verdict, and the card says so.
 */
export function ResidueCard({ view, mode, actions }: { view: IncidentView; mode: "live" | "replay"; actions: IncidentActions }) {
  const r = view.report;
  const res = r?.residue;
  const tc = actions.toolCallOf("residue_check");
  const open = () =>
    tc
      ? actions.openToolCall(tc)
      : actions.openTemplate("Q-RESIDUE-1", "residue check", "incident report (residue)", res?.summary, {
          cause: r?.cause_id ?? undefined,
        });
  const has = !!res && typeof res.k === "number" && typeof res.n === "number";
  const k = res?.k ?? 0;
  const n = res?.n ?? 0;
  const unexplained = res?.unexplained ?? [];
  const explained = res?.explained ?? [];

  return (
    <Section
      id="residue"
      title="Residue check"
      aside={
        has ? (
          <>
            {n === 0 ? (
              <StatusChip tone="na">nothing measured</StatusChip>
            ) : k === n ? (
              <StatusChip tone="pass">
                explains {k} of {n}
              </StatusChip>
            ) : (
              <StatusChip tone="warn">
                explains {k} of {n}
              </StatusChip>
            )}
            <TemplateButton template={tc?.template ?? "Q-RESIDUE-1"} label="the residue check" onOpen={open} />
          </>
        ) : null
      }
    >
      {!r ? (
        <p className="text-sm text-zinc-300">Appears once the gate has confirmed a cause.</p>
      ) : res === undefined ? (
        <FieldAbsent mode={mode} what="the residue check" where="report" />
      ) : res.error ? (
        <p role="alert" className="flex items-start gap-1.5 rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100">
          <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
          <span>
            <strong className="font-semibold">Residue check failed:</strong> {res.error}
          </span>
        </p>
      ) : !has ? (
        <p className="text-sm text-zinc-300">
          Not run: the residue check only runs after the gate confirms a cause.
        </p>
      ) : (
        <div className="space-y-2">
          <p className="flex items-start gap-1.5 text-xs text-zinc-200">
            <Scale aria-hidden className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
            <span>{res.summary ? `${res.summary}.` : `The confirmed cause explains ${k} of ${n} anomalous components.`}</span>
          </p>
          {unexplained.length ? (
            <div role="note" className="rounded-md border border-dashed border-amber-400/70 bg-amber-500/5 p-2">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-100">
                <CircleAlert aria-hidden className="size-3.5 text-amber-300" />
                Another fault may be active ({unexplained.length} not reachable from the cause)
              </p>
              <ul className="mt-1 flex flex-wrap gap-1" aria-label="Anomalous components the cause does not reach">
                {unexplained.map((id) => (
                  <li key={id}>
                    <NodeButton id={id} onOpen={actions.openNode} tone="warn" note="unexplained by the cause" />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {explained.length ? (
            <div>
              <p className="mb-1 text-[11px] text-zinc-400">Explained (downstream of the cause)</p>
              <ul className="flex flex-wrap gap-1" aria-label="Anomalous components the cause explains">
                {explained.map((id) => (
                  <li key={id}>
                    <NodeButton id={id} onOpen={actions.openNode} note="explained by the cause" />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="flex items-center gap-1 text-[11px] text-zinc-400">
            <Info aria-hidden className="size-3" /> Advisory: reported, never gating; it does not change the verdict.
          </p>
        </div>
      )}
    </Section>
  );
}
