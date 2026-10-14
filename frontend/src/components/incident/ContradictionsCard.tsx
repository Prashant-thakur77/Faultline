"use client";

import { FileWarning, Scale } from "lucide-react";
import { checkState } from "@/lib/gate";
import { g8Of, parseContradictions } from "@/lib/contradictions";
import type { GateCheck, GateRun, IncidentView } from "@/lib/types";
import { STATIC_SITE } from "@/lib/site";
import { useTenant } from "@/lib/tenant";
import { StatusChip } from "@/components/StatusChip";
import { OverrideForm } from "./OverrideForm";
import { Section } from "./Section";

/**
 * Contradictions (G8): active decisions (ADRs) the accepted cause violates. G8 is a
 * downgrade-only check: it attaches the decision to the incident, it never blocks the claim.
 * Each decision chip opens the G8 check's Cypher (Q-DEC-1) with its recorded params.
 */
export function ContradictionsCard({
  view,
  onOpenCheck,
}: {
  view: IncidentView;
  onOpenCheck: (run: GateRun, check: GateCheck) => void;
}) {
  const tenant = useTenant();
  const g8 = g8Of(view);
  const fallback = view.report?.contradictions ?? [];

  if (!g8 && !fallback.length) {
    return (
      <Section id="contradictions" title="Contradictions">
        <p className="text-sm text-zinc-300">
          {view.report && !view.report.cause_id
            ? "No cause was accepted, so there is no change to check against active decisions (G8)."
            : view.report
              ? "G8 was not recorded for the accepted cause, so no decision check is shown."
              : "Shown once the confirmation gate has checked the cause against active decisions (G8)."}
        </p>
      </Section>
    );
  }

  const state = g8 ? checkState(g8.check) : "fail";
  if (g8 && state === "pass") {
    return (
      <Section
        id="contradictions"
        title="Contradictions"
        aside={<StatusChip tone="pass">no decision violated</StatusChip>}
      >
        <button
          type="button"
          onClick={() => onOpenCheck(g8.run, g8.check)}
          className="w-full rounded text-left text-sm text-zinc-200 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          G8: {g8.check.detail || "the cause violates no active decision"}
          {g8.check.template ? (
            <span className="ml-1 rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200">
              {g8.check.template}
            </span>
          ) : null}
        </button>
      </Section>
    );
  }
  if (g8 && state === "na") {
    return (
      <Section
        id="contradictions"
        title="Contradictions"
        aside={<StatusChip tone="na">not applicable</StatusChip>}
      >
        <p className="text-sm text-zinc-300">
          G8: {g8.check.detail || "not applicable to this cause"}
        </p>
      </Section>
    );
  }

  const lines = g8 ? [g8.check.detail] : fallback;
  const all = lines.flatMap(parseContradictions);
  const accepted = all.flatMap((p) => (p.accepted ? [p.accepted] : []));
  const parts = all.filter((p) => !p.accepted);
  const open = g8 ? () => onOpenCheck(g8.run, g8.check) : undefined;
  const cause = view.report?.cause_id ?? null;

  return (
    <Section
      id="contradictions"
      title="Contradictions"
      aside={
        <StatusChip tone={parts.length ? "warn" : "pass"} icon={FileWarning}>
          {parts.length} decision{parts.length === 1 ? "" : "s"} violated
          {accepted.length ? `, ${accepted.length} accepted` : ""}
        </StatusChip>
      }
    >
      <p className="mb-2 text-xs text-zinc-300">
        The cause
        {view.report?.cause_id ? (
          <span className="font-mono"> {view.report.cause_id}</span>
        ) : null}{" "}
        violates these active decisions. G8 attaches them to the incident
        (downgrade-only); it never blocks the claim.
      </p>
      <ul className="space-y-2" aria-label="Violated decisions">
        {parts.map((p, i) => (
          <li
            key={i}
            className="rounded-md border border-amber-400/50 bg-amber-500/5 p-2"
          >
            {p.parsed ? (
              <button
                type="button"
                onClick={open}
                disabled={!open}
                className="block w-full rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-amber-300 enabled:hover:bg-amber-500/10"
              >
                <span className="sr-only">Decision </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-400 px-1.5 font-mono text-[11px] font-bold text-zinc-950">
                    <Scale aria-hidden className="size-3" />
                    {p.parsed.decision}
                  </span>
                  <StatusChip tone="warn">violated</StatusChip>
                  {p.answer ? (
                    <StatusChip tone="info">
                      answered: {p.answer.verdict}
                    </StatusChip>
                  ) : null}
                  {g8?.check.template ? (
                    <span className="ml-auto rounded bg-violet-500/15 px-1 font-mono text-[10px] text-violet-200">
                      {g8.check.template}
                    </span>
                  ) : null}
                </span>
                <span className="mt-1.5 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
                  <span className="text-zinc-400">rule</span>
                  <span className="font-mono break-all text-zinc-100">
                    {p.parsed.key} {p.parsed.op} {p.parsed.expected}
                  </span>
                  <span className="text-zinc-400">expected</span>
                  <span className="font-mono text-emerald-200">
                    {p.parsed.op} {p.parsed.expected}
                  </span>
                  <span className="text-zinc-400">actual</span>
                  <span className="font-mono font-semibold text-red-200">
                    <span aria-hidden>✗ </span>
                    {p.parsed.actual}
                  </span>
                </span>
                {open ? (
                  <span className="sr-only">
                    {" "}
                    Open the Cypher panel for the G8 check.
                  </span>
                ) : null}
                {p.answer?.why ? (
                  <span className="mt-1 block text-xs text-zinc-300">
                    Reviewer: {p.answer.why}
                  </span>
                ) : null}
              </button>
            ) : (
              <p className="text-xs break-words text-zinc-100">{p.raw}</p>
            )}
            {p.parsed && cause && !STATIC_SITE ? (
              <OverrideForm
                decision={p.parsed.decision}
                change={cause}
                incident={view.incident.id}
                tenant={tenant}
              />
            ) : null}
          </li>
        ))}
      </ul>
      {accepted.length ? (
        <ul className="mt-2 space-y-1" aria-label="Accepted deviations">
          {accepted.map((a) => (
            <li
              key={a.decision}
              className="rounded-md border border-zinc-700 p-2 text-xs text-zinc-300"
            >
              <StatusChip tone="na">accepted deviation</StatusChip>{" "}
              <span className="font-mono text-zinc-100">{a.decision}</span> (
              {a.fact}): marked intentional by{" "}
              <span className="font-mono">{a.by}</span>: {a.why}
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}
