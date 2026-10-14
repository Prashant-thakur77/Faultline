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
import { Section } from "./Section";

const STATUS_ORDER = { confirmed: 0, open: 1, unresolved: 2, eliminated: 3 } as const;

/**
 * Blast radius + suspects: the BLAST tool calls and the hypotheses (Q-HYP-1) with score bars and
 * origin, with a "naive vs Faultline" toggle (§9.1.1) that shows what naive recency would have
 * blamed next to the gate's verdict (live only: it reads the run's recorded suspects from the API).
 */
export function HypothesesCard({
  view,
  onOpenToolCall,
  onOpenEvidence,
  mode = "live",
}: {
  view: IncidentView;
  onOpenToolCall: (tc: ToolCallRow) => void;
  onOpenEvidence: (id: string) => void;
  mode?: "live" | "replay";
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
    <Section id="suspects" title="Blast radius & suspects">
      {blastOnce.length ? (
        <ul className="mb-3 space-y-1">
          {blastOnce.map((t) => (
            <li key={`${t.id}:${t.at}`} className="flex items-center gap-2 text-xs">
              <Radar aria-hidden className="size-3.5 text-amber-300" />
              <span className="font-mono text-zinc-200">{t.tool}</span>
              <span className="text-zinc-300">{t.summary}</span>
              {t.template ? (
                <button
                  type="button"
                  onClick={() => onOpenToolCall(t)}
                  className="ml-auto inline-flex min-h-6 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
                  aria-label={`${t.template}: open the Cypher panel for ${t.tool}`}
                >
                  {t.template}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div role="group" aria-label="Suspects view" className="mb-2 flex w-fit overflow-hidden rounded-md border border-zinc-700">
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
        <ul className="space-y-2">
          {hyps.map((h) => (
            <HypothesisRow key={h.id} h={h} maxScore={maxScore} onOpenEvidence={onOpenEvidence} />
          ))}
        </ul>
      )}
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
  return (
    <li className="rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm text-zinc-50">{h.cause}</span>
        <StatusChip tone={meta.tone}>{meta.text}</StatusChip>
        <span className="rounded border border-zinc-600 px-1 text-[11px] text-zinc-300" title="who proposed this hypothesis">
          origin: {h.origin}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded bg-zinc-800" aria-hidden>
          <div className="h-full rounded bg-sky-400" style={{ width: `${pct}%` }} />
        </div>
        <span className="font-mono text-[11px] text-zinc-300">
          score {h.score === null ? "–" : score.toFixed(2)}
        </span>
      </div>
      {h.reason ? <p className="mt-1 text-xs break-words text-zinc-300">{h.reason}</p> : null}
      {h.supports.length || h.refutes.length ? (
        <div className="mt-1 flex flex-wrap gap-1">
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
        "inline-flex min-h-7 items-center gap-1 px-2 py-1 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-inset",
        active ? "bg-sky-500/20 text-sky-100" : "text-zinc-300 hover:bg-zinc-800",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {text}
      {active ? <span className="sr-only">(selected)</span> : null}
    </button>
  );
}
