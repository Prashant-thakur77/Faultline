"use client";

import { useState } from "react";
import { Clock3, Radar, Scale } from "lucide-react";
import { HYP_META } from "@/lib/gate";
import { useTenant } from "@/lib/tenant";
import { cn } from "@/lib/utils";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import type { Hypothesis, IncidentView, ToolCallRow } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { EvidenceChip, uniq } from "./EvidenceChip";
import { NaiveContrast } from "./NaiveContrast";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Section } from "./Section";

const STATUS_ORDER = { confirmed: 0, open: 1, unresolved: 2, eliminated: 3 } as const;

/**
 * Blast radius + suspects: the BLAST tool calls and the hypotheses (Q-HYP-1) with score bars and
 * origin, with a "naive vs Faultline" toggle that shows what naive recency would have
 * blamed next to the gate's verdict (live only: it reads the run's recorded suspects from the API).
 */
export function HypothesesCard({
  view,
  onOpenToolCall,
  onOpenEvidence,
  mode = "live",
  onOpenTemplate,
}: {
  view: IncidentView;
  onOpenToolCall: (tc: ToolCallRow) => void;
  onOpenEvidence: (id: string) => void;
  mode?: "live" | "replay";
  /** Opens a template in the Cypher panel (the room's actions; offline-aware in replay). */
  onOpenTemplate?: (template: string, title: string, origin: string) => void;
}) {
  const [lens, setLens] = useState<"faultline" | "naive">("faultline");
  const tenant = useTenant();
  const panel = useCypherPanel();
  const running = !view.run.outcome || view.run.outcome === "RUNNING";
  const blast = view.tool_calls.filter((t) => t.tool === "blast_radius" || t.tool === "chokepoints");
  const seen = new Set<string>();
  const blastOnce = blast.filter((t) => (seen.has(t.tool) ? false : (seen.add(t.tool), true)));
  const hyps = [...view.hypotheses].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) ||
      (b.score ?? 0) - (a.score ?? 0) ||
      a.cause.localeCompare(b.cause),
  );
  const maxScore = Math.max(1, ...hyps.map((h) => h.score ?? 0));

  return (
    <Section
      id="suspects"
      title="Suspects"
      aside={hyps.length ? <span className="text-xs text-[var(--fl-subtle)]">{hyps.length} ranked</span> : null}
      via={
        onOpenTemplate ? (
          <ViaFalkor template="Q-HYP-1" label="the suspects" onOpen={() => onOpenTemplate("Q-HYP-1", "suspects of this incident", "suspects card")} />
        ) : null
      }
    >
      <div role="group" aria-label="Suspects view" className="mb-3 flex w-fit rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]">
        <LensButton active={lens === "faultline"} onClick={() => setLens("faultline")} icon={Scale} text="Faultline (gate)" />
        <LensButton active={lens === "naive"} onClick={() => setLens("naive")} icon={Clock3} text="Naive recency" />
      </div>
      {lens === "naive" ? (
        mode === "replay" ? (
          <p className="text-xs text-zinc-300">
            Not in this recording: the contrast reads the run&apos;s recorded suspects from the live API. A live run shows it.
          </p>
        ) : running ? (
          <p className="text-xs text-zinc-300">The contrast appears once the gate has decided.</p>
        ) : (
          <NaiveContrast
            incidentId={view.incident.id}
            tenant={tenant}
            refreshKey={`${view.run.outcome}:${view.hypotheses.length}`}
            onOpenTemplate={(template, title, origin, detail, params) =>
              panel.open({
                template,
                title,
                origin,
                detail,
                recordedParams: params,
                ctx: { incident: view.incident.id, run: view.run.run, onset: view.incident.onset_at, targets: view.incident.targets },
                incident: view.incident.id,
                tenant,
              })
            }
          />
        )
      ) : hyps.length === 0 ? (
        <p className="text-sm text-zinc-300">
          {view.run.outcome && view.run.outcome !== "RUNNING"
            ? "No hypotheses were recorded for this incident."
            : "No hypotheses recorded yet for this incident."}
        </p>
      ) : (
        <ul className="divide-y divide-white/[0.06]">
          {hyps.map((h) => (
            <HypothesisRow key={h.id} h={h} maxScore={maxScore} onOpenEvidence={onOpenEvidence} />
          ))}
        </ul>
      )}
      {blastOnce.length ? (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-white/[0.06] pt-3" aria-label="Scope queries">
          {blastOnce.map((t) => (
            <li key={`${t.id}:${t.at}`} className="flex items-center gap-1.5 text-xs text-zinc-400">
              <Radar aria-hidden className="size-3.5 text-[var(--fl-subtle)]" />
              <span>
                {t.tool.replaceAll("_", " ")}: <span className="text-zinc-300">{t.summary}</span>
              </span>
              {t.template ? <ViaFalkor compact template={t.template} label={t.tool} onOpen={() => onOpenToolCall(t)} /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

function HypothesisRow({
  h,
  maxScore,
  onOpenEvidence,
}: {
  h: Hypothesis;
  maxScore: number;
  onOpenEvidence: (id: string) => void;
}) {
  const meta = HYP_META[h.status] ?? { tone: "na" as const, text: h.status };
  const score = h.score ?? 0;
  const pct = Math.max(0, Math.min(100, (score / maxScore) * 100));
  const cause = h.status === "confirmed";
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("font-mono text-sm", cause ? "font-semibold text-zinc-50" : h.status === "eliminated" ? "text-zinc-400" : "text-zinc-100")}>
          {h.cause}
        </span>
        <StatusChip tone={meta.tone}>{meta.text}</StatusChip>
        <span className="text-[11px] text-[var(--fl-subtle)]" title="who proposed this hypothesis">
          origin: {h.origin}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <span className="h-1 w-16 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden>
            <span
              className={cn("block h-full rounded-full", cause ? "bg-[var(--fl-ember)]" : "bg-zinc-500")}
              style={{ width: `${pct}%` }}
            />
          </span>
          <span
            className="font-mono text-[11px] text-zinc-400"
            title="investigation order only: path closeness, time to onset, anomaly, algo.pageRank and memory prior, weighted in weights.yaml. The verdict comes from the gate, never from this score."
          >
            score {h.score === null ? "\u2013" : score.toFixed(2)}
          </span>
        </span>
      </div>
      {h.reason ? <p className="mt-1 text-xs leading-relaxed break-words text-zinc-400">{h.reason}</p> : null}
      {h.supports.length || h.refutes.length ? (
        <div className="mt-1 -ml-1 flex flex-wrap gap-x-1">
          {uniq(h.supports).map((e) => (
            <EvidenceChip key={`s-${e}`} id={e} relation="supports" onOpen={onOpenEvidence} />
          ))}
          {uniq(h.refutes).map((e) => (
            <EvidenceChip key={`r-${e}`} id={e} relation="refutes" onOpen={onOpenEvidence} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

function LensButton({ active, onClick, icon: Icon, text }: { active: boolean; onClick: () => void; icon: typeof Scale; text: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex min-h-7 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
        active ? "bg-white/[0.1] text-zinc-50" : "text-zinc-400 hover:text-zinc-100",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {text}
      {active ? <span className="sr-only">(selected)</span> : null}
    </button>
  );
}
