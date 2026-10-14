"use client";

import { ArrowRight, CircleHelp, Unlink } from "lucide-react";
import { abstentionOf, gateCode, outcomeMeta, type Abstention } from "@/lib/gate";
import type { IncidentView } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { EvidenceChip, uniq } from "./EvidenceChip";
import { Section } from "./Section";

/** Root cause: outcome, the proven mechanism, proven claims (solid) and inferred claims (dashed). */
export function RootCauseCard({
  view,
  onOpenEvidence,
  onOpenNode,
  whyAction,
}: {
  view: IncidentView;
  onOpenEvidence: (id: string) => void;
  onOpenNode: (id: string) => void;
  /** "Why do you believe this?" entry point, shown under a confirmed cause. */
  whyAction?: React.ReactNode;
}) {
  const r = view.report;
  if (!r) {
    return (
      <Section id="root" title="Root cause">
        <p className="text-sm text-zinc-300">
          No report yet: it is assembled from the graph once the run has an outcome (current stage{" "}
          <span className="font-mono">{view.incident.stage}</span>).
        </p>
      </Section>
    );
  }
  const m = outcomeMeta(r.outcome);
  const abstain = abstentionOf(view);
  return (
    <Section
      id="root"
      title={abstain ? "Root cause: abstained" : "Root cause"}
      aside={
        <StatusChip tone={m.tone} title={m.meaning}>
          {m.text}
        </StatusChip>
      }
    >
      <p className="text-xs text-zinc-300">
        {abstain ? "no cause accepted: no change explains the symptom" : m.meaning}.
      </p>
      {r.cause_id ? (
        <div className="mt-2">
          <p className="text-xs text-zinc-400">Cause</p>
          <p className="font-mono text-base font-semibold text-red-300">{r.cause_id}</p>
          {whyAction ? <div className="mt-2">{whyAction}</div> : null}
        </div>
      ) : abstain ? (
        <AbstainBlock a={abstain} onOpenNode={onOpenNode} />
      ) : r.outcome === "NO_INCIDENT" ? (
        <p className="mt-2 text-sm text-zinc-200">
          Nothing to blame: the measurements are back in band (N1) and no change in the window reaches an anomalous node
          (N2). Both are proven below.
        </p>
      ) : (
        <p className="mt-2 text-sm text-zinc-300">No cause was accepted for this incident.</p>
      )}

      {r.mechanism.length ? (
        <div className="mt-2">
          <p className="mb-1 text-xs text-zinc-400">Mechanism (G2 chain)</p>
          <ol className="flex flex-wrap items-center gap-1" aria-label="Mechanism chain">
            {r.mechanism.map((id, i) => (
              <li key={id} className="flex items-center gap-1">
                {i > 0 ? <ArrowRight aria-label="to" className="size-3 text-zinc-400" /> : null}
                <button
                  type="button"
                  onClick={() => onOpenNode(id)}
                  className={
                    "inline-flex min-h-6 items-center rounded border px-1 font-mono text-[11px] outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400 " +
                    (i === 0 ? "border-red-400 text-red-200" : "border-amber-400/60 text-amber-100")
                  }
                >
                  {id}
                </button>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="mt-3">
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">
          Proven <span className="font-normal normal-case text-zinc-400">(solid: a gate check passed)</span>
        </h3>
        {r.proven.length ? (
          <ul className="space-y-1.5">
            {r.proven.map((p, i) => (
              <li key={i} className="rounded-md border border-solid border-emerald-500/50 bg-emerald-500/5 p-2">
                <div className="flex items-start gap-2">
                  <span className="shrink-0 rounded bg-emerald-500/15 px-1 font-mono text-[11px] text-emerald-200">
                    {gateCode(p.check)}
                  </span>
                  <p className="text-xs break-words text-zinc-100">{p.claim}</p>
                </div>
                {p.evidence_ids.length ? (
                  <div className="mt-1 flex flex-wrap gap-1 pl-8">
                    {uniq(p.evidence_ids).map((e) => (
                      <EvidenceChip key={e} id={e} onOpen={onOpenEvidence} />
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-zinc-300">No proven claims in this report.</p>
        )}
      </div>

      <div className="mt-3">
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">
          Inferred <span className="font-normal normal-case text-zinc-400">(dashed: not proven by a gate check)</span>
        </h3>
        {r.inferred.length ? (
          <ul className="space-y-1.5">
            {r.inferred.map((p, i) => {
              // Q-COUPLE-1: a G2-rejected suspect whose history says it co-fails with a symptom; not a claim.
              const missingEdge = /^possible missing edge\b/i.test(p.claim);
              return (
                <li key={i} className="rounded-md border border-dashed border-amber-400/60 p-2">
                  {missingEdge ? (
                    <StatusChip tone="warn" icon={Unlink} className="mb-1">
                      possible missing edge: confirm and add it
                    </StatusChip>
                  ) : null}
                  <p className="text-xs break-words text-zinc-100">{p.claim}</p>
                  <p className="mt-0.5 text-[11px] text-zinc-400">basis: {p.basis}</p>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-xs text-zinc-300">None: the report states nothing beyond what the gate proved.</p>
        )}
      </div>
    </Section>
  );
}

/** The run abstained: no change explains the symptom; the inferred origin is shown as unconfirmed. */
export function AbstainBlock({ a, onOpenNode }: { a: Abstention; onOpenNode: (id: string) => void }) {
  return (
    <div className="mt-2 rounded-md border-2 border-dashed border-amber-400/70 bg-amber-500/5 p-2">
      <p className="flex items-start gap-1.5 text-sm text-amber-50">
        <CircleHelp aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-300" />
        <span>
          <strong className="font-semibold">Abstained:</strong> no change explains this. Inferred origin{" "}
          <button
            type="button"
            onClick={() => onOpenNode(a.origin)}
            className="rounded border border-dashed border-amber-300 px-1 font-mono text-amber-100 outline-none hover:bg-amber-500/10 focus-visible:ring-2 focus-visible:ring-amber-300"
            aria-label={`${a.origin}: inferred origin, not confirmed. Open its context in the Cypher panel.`}
          >
            {a.origin}
          </button>{" "}
          <span className="text-amber-200">(unconfirmed)</span>
        </span>
      </p>
      {a.chain ? (
        <ol className="mt-1.5 flex flex-wrap items-center gap-1 pl-5" aria-label="Inferred chain (not proven)">
          {a.chain.map((id, i) => (
            <li key={`${id}:${i}`} className="flex items-center gap-1">
              {i > 0 ? <ArrowRight aria-label="to" className="size-3 text-zinc-400" /> : null}
              <span className="rounded border border-dashed border-amber-400/60 px-1 font-mono text-[11px] text-amber-100">{id}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {a.reason ? <p className="mt-1.5 pl-5 text-xs text-zinc-300">{a.reason}</p> : null}
      <p className="mt-1 pl-5 text-[11px] text-zinc-400">
        No gate check proved it, so it is not shown as a root cause.
      </p>
    </div>
  );
}
