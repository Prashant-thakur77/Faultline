"use client";

import { ArrowRight, CircleHelp, Unlink } from "lucide-react";
import { abstentionOf, gateCode, outcomeMeta, type Abstention } from "@/lib/gate";
import type { IncidentView } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { EvidenceChip, uniq } from "./EvidenceChip";
import { Disclosure } from "@/components/ui/Disclosure";
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
      {r.cause_id ? (
        <div>
          <p className="text-xs text-[var(--fl-subtle)]">Cause</p>
          <p className="mt-0.5 font-mono text-2xl font-semibold tracking-tight text-[var(--fl-ember)]">{r.cause_id}</p>
          <p className="mt-1 text-xs text-zinc-400">{m.meaning}.</p>
          {whyAction ? <div className="mt-3">{whyAction}</div> : null}
        </div>
      ) : abstain ? (
        <AbstainBlock a={abstain} onOpenNode={onOpenNode} />
      ) : r.outcome === "NO_INCIDENT" ? (
        <p className="text-sm text-zinc-200">
          Nothing to blame: the measurements are back in band (N1) and no change in the window reaches an anomalous node
          (N2). Both are proven below.
        </p>
      ) : (
        <p className="text-sm text-zinc-300">
          {abstain ? "No cause accepted: no change explains the symptom." : `No cause was accepted for this incident. ${m.meaning}.`}
        </p>
      )}

      {r.mechanism.length ? (
        <div className="mt-4">
          <p className="mb-1.5 text-xs text-[var(--fl-subtle)]">Mechanism (the G2 path)</p>
          <ol className="flex flex-wrap items-center gap-1" aria-label="Mechanism chain">
            {r.mechanism.map((id, i) => (
              <li key={id} className="flex items-center gap-1">
                {i > 0 ? <ArrowRight aria-label="to" className="size-3 text-zinc-400" /> : null}
                <button
                  type="button"
                  onClick={() => onOpenNode(id)}
                  className={
                    "inline-flex min-h-7 items-center rounded-md px-2 font-mono text-xs outline-none transition-colors hover:bg-white/[0.08] focus-visible:ring-2 focus-visible:ring-sky-400 " +
                    (i === 0 ? "bg-[color-mix(in_oklch,var(--fl-ember)_16%,transparent)] text-orange-100" : "bg-white/[0.05] text-zinc-100")
                  }
                >
                  {id}
                </button>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {r.proven.length ? (
        <Disclosure
          className="mt-4 border-t border-white/[0.06] pt-3"
          summary={
            <>
              <span className="text-emerald-300" aria-hidden>
                ✓{" "}
              </span>
              Proven by {r.proven.length} gate check{r.proven.length === 1 ? "" : "s"}
            </>
          }
        >
          <ul className="space-y-2" aria-label="Proven claims (a gate check passed)">
            {r.proven.map((p, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span className="mt-px w-8 shrink-0 font-mono text-[11px] text-emerald-300">{gateCode(p.check)}</span>
                <div className="min-w-0">
                  <p className="text-xs break-words text-zinc-200">{p.claim}</p>
                  {p.evidence_ids.length ? (
                    <div className="-ml-1 flex flex-wrap gap-x-1">
                      {uniq(p.evidence_ids).map((e) => (
                        <EvidenceChip key={e} id={e} onOpen={onOpenEvidence} />
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </Disclosure>
      ) : (
        <p className="mt-4 text-xs text-zinc-400">No proven claims in this report.</p>
      )}

      {r.inferred.length ? (
        <div className="mt-4">
          <h3 className="mb-1.5 text-xs font-medium text-zinc-400">
            Inferred <span className="font-normal text-[var(--fl-subtle)]">(dashed: not proven by a gate check)</span>
          </h3>
          <ul className="space-y-1.5">
            {r.inferred.map((p, i) => {
              // Q-COUPLE-1: a G2-rejected suspect whose history says it co-fails with a symptom; not a claim.
              const missingEdge = /^possible missing edge\b/i.test(p.claim);
              return (
                <li key={i} className="rounded-lg border border-dashed border-amber-400/50 px-3 py-2">
                  {missingEdge ? (
                    <StatusChip tone="warn" icon={Unlink} className="mb-1">
                      possible missing edge: confirm and add it
                    </StatusChip>
                  ) : null}
                  <p className="text-xs break-words text-zinc-100">{p.claim}</p>
                  <p className="mt-0.5 text-[11px] text-[var(--fl-subtle)]">basis: {p.basis}</p>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--fl-subtle)]">Nothing inferred: the report states only what the gate proved.</p>
      )}
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
