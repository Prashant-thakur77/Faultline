"use client";

import { Ban, CircleCheck, CircleMinus, CircleX, ShieldCheck, ShieldX, TriangleAlert, type LucideIcon } from "lucide-react";
import {
  CHECK_STATE_TEXT,
  CHECK_STATE_TONE,
  checkState,
  missingGates,
  originText,
  sortChecks,
  type CheckState,
  type RejectionView,
} from "@/lib/gate";
import type { GateCheck, GateRun } from "@/lib/types";
import { StatusChip, TONE_CLASS } from "@/components/StatusChip";
import { cn } from "@/lib/utils";
import { EvidenceChip, uniq } from "./EvidenceChip";
import { Section } from "./Section";

const STATE_ICON: Record<CheckState, LucideIcon> = {
  pass: CircleCheck,
  fail: CircleX,
  downgrade: TriangleAlert,
  na: CircleMinus,
};
const STATE_GLYPH: Record<CheckState, string> = { pass: "✓", fail: "✗", downgrade: "!", na: "–" };

/** One plain-English line per gate code, shown as the checklist's legend. */
const GATE_LEGEND: [string, string][] = [
  ["G1", "every id was seen by this run"],
  ["G2", "a graph path from the change to the symptom"],
  ["G3", "the timing fits, no earlier upstream change"],
  ["G4", "a metric on that path is off its baseline"],
  ["G4 origin", "the anomaly shows at the changed component before the alerting symptom; downgrade-only"],
  ["G5", "enough graph flow to explain the impact"],
  ["G6", "every rival suspect ruled out"],
  ["G7", "the specialists name the same change"],
  ["G7 correlation", "the change and code/data specialists name the same deploy on the proven chain"],
  ["G8", "decisions it violates (shown, never blocks)"],
  ["N1/N2", "no-incident proof: metrics in band, no change reaches an anomaly"],
];

/**
 * Gate checklist G1–G8 per gate run (pass ✓ / fail ✗ / downgrade ! / not evaluable –, neutral; colour + icon +
 * text). Rejections from the competitor sweep are listed first, as first-class results.
 */
export function GateChecklist({
  runs,
  rejections,
  onOpenCheck,
  onOpenEvidence,
}: {
  runs: GateRun[];
  rejections: RejectionView[];
  onOpenCheck: (run: GateRun, check: GateCheck) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const byId = new Map(runs.map((r) => [r.id, r]));
  const ordered = [...runs].sort((a, b) => a.at - b.at || a.id.localeCompare(b.id));
  return (
    <Section id="gate" title="Evidence gate" aside={<span className="text-[11px] text-zinc-400">{runs.length} gate runs</span>}>
      <p className="mb-2 text-[11px] leading-relaxed text-zinc-300">
        {GATE_LEGEND.map(([code, text], i) => (
          <span key={code}>
            {i ? <span aria-hidden className="text-zinc-400"> · </span> : null}
            <abbr title={text} className="font-mono font-semibold text-zinc-100 no-underline">
              {code}
            </abbr>{" "}
            {text}
            {i < GATE_LEGEND.length - 1 ? <span className="sr-only">;</span> : null}
          </span>
        ))}
      </p>
      {rejections.length ? (
        <div className="mb-3 space-y-2">
          <h3 className="text-xs font-semibold text-zinc-300">Rejected suspects</h3>
          <ul className="space-y-2">
            {rejections.map((r) => (
              <li key={`${r.gateRunId}:${r.cause}`} className="rounded-md border border-red-500/50 bg-red-500/10 p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Ban aria-hidden className="size-4 text-red-300" />
                  {r.cause === "NO_INCIDENT" ? (
                    <>
                      <span className="text-sm text-zinc-50">&ldquo;No incident&rdquo; hypothesis</span>
                      <StatusChip tone="fail">refuted: this is an incident</StatusChip>
                    </>
                  ) : (
                    <>
                      <span className="font-mono text-sm text-zinc-50 line-through decoration-red-300/70">{r.cause}</span>
                      <StatusChip tone="fail">rejected</StatusChip>
                    </>
                  )}
                </div>
                {r.failed.map((f, i) => {
                  const run = byId.get(r.gateRunId);
                  return f.check && run ? (
                    <button
                      key={i}
                      type="button"
                      onClick={() => onOpenCheck(run, f.check!)}
                      className="mt-1 block w-full rounded text-left text-sm text-red-100 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-red-300"
                    >
                      <strong className="font-semibold">Rejected by {originText(r.origin)}:</strong>{" "}
                      <span className="break-words">{f.text}</span>
                      {f.check.template ? (
                        <span className="ml-1 rounded bg-violet-500/20 px-1 font-mono text-[11px] text-violet-200">
                          {f.check.template}
                        </span>
                      ) : null}
                      <span className="sr-only"> Open the Cypher panel for {f.check.name}.</span>
                    </button>
                  ) : (
                    <p key={i} className="mt-1 text-sm break-words text-red-100">
                      <strong className="font-semibold">Rejected by {originText(r.origin)}:</strong> {f.text}
                    </p>
                  );
                })}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {ordered.length === 0 ? (
        <p className="text-sm text-zinc-300">No gate run recorded yet: the gate runs once suspects are investigated.</p>
      ) : (
        <ol className="space-y-3">
          {ordered.map((run) => (
            <GateRunBlock key={run.id} run={run} onOpenCheck={onOpenCheck} onOpenEvidence={onOpenEvidence} />
          ))}
        </ol>
      )}
    </Section>
  );
}

function verdict(run: GateRun): { tone: "pass" | "fail" | "warn" | "info"; text: string; icon: LucideIcon } {
  if (!run.passed) return { tone: "fail", text: "rejected", icon: ShieldX };
  if (run.origin === "no_incident") return { tone: "info", text: "negative proof accepted", icon: ShieldCheck };
  if (run.origin === "sweep") return { tone: "info", text: "survived the sweep", icon: ShieldCheck };
  return run.confident
    ? { tone: "pass", text: "accepted, confident", icon: ShieldCheck }
    : { tone: "warn", text: "accepted, not confident", icon: TriangleAlert };
}

function GateRunBlock({
  run,
  onOpenCheck,
  onOpenEvidence,
}: {
  run: GateRun;
  onOpenCheck: (run: GateRun, check: GateCheck) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const v = verdict(run);
  const missing = missingGates(run);
  return (
    <li className={cn("rounded-md border p-2", run.passed ? "border-zinc-700" : "border-red-500/40")}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm text-zinc-50">{run.cause}</span>
        <StatusChip tone={v.tone} icon={v.icon}>
          {v.text}
        </StatusChip>
        <span className="text-[11px] text-zinc-400">
          {originText(run.origin)} · attempt {run.attempt}
        </span>
      </div>
      <ul className="space-y-1" aria-label={`Checks for ${run.cause} (${originText(run.origin)})`}>
        {sortChecks(run.checks).map((c, i) => (
          <CheckRow key={`${c.name}:${i}`} run={run} check={c} onOpen={onOpenCheck} onOpenEvidence={onOpenEvidence} />
        ))}
      </ul>
      {missing.length ? (
        <p className="mt-1.5 flex items-center gap-1 text-[11px] text-zinc-400">
          <CircleMinus aria-hidden className="size-3" />
          Not recorded in this gate run: {missing.join(", ")}
        </p>
      ) : null}
    </li>
  );
}

function CheckRow({
  run,
  check,
  onOpen,
  onOpenEvidence,
}: {
  run: GateRun;
  check: GateCheck;
  onOpen: (run: GateRun, check: GateCheck) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const s = checkState(check);
  const Icon = STATE_ICON[s];
  const tone = CHECK_STATE_TONE[s];
  const flow = parseFlow(check.detail);
  return (
    <li className="rounded border border-transparent hover:border-zinc-700">
      <button
        type="button"
        onClick={() => onOpen(run, check)}
        className="flex w-full items-start gap-2 rounded px-1 py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        {/* Accessible name from content (WCAG 2.5.3, label in name): "G2 path: pass. <template> <detail>
            Open the Cypher panel." The visual order keeps the status chip in the left column. */}
        <span className={cn("mt-0.5 inline-flex w-[5.6rem] shrink-0 items-center gap-1 rounded border px-1 text-[11px] font-medium", TONE_CLASS[tone])}>
          <Icon aria-hidden className="size-3.5" />
          <span aria-hidden>{STATE_GLYPH[s]}</span>
          <span className="sr-only">{check.name}: </span>
          {CHECK_STATE_TEXT[s]}
          <span className="sr-only">{check.downgrade_only ? " (downgrade-only check)" : ""}. </span>
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span aria-hidden className="text-xs font-semibold text-zinc-50">{check.name}</span>
            {check.downgrade_only ? (
              <span aria-hidden className="rounded border border-zinc-600 px-1 text-[10px] text-zinc-300">downgrade-only</span>
            ) : null}
            {check.template ? (
              <span className="rounded bg-violet-500/15 px-1 font-mono text-[10px] text-violet-200">{check.template}</span>
            ) : null}
          </span>
          <span className="block text-xs break-words text-zinc-300">{check.detail}</span>
          {flow ? <FlowBar {...flow} /> : null}
          <span className="sr-only"> Open the Cypher panel{check.template ? ` for ${check.template}` : ""}.</span>
        </span>
      </button>
      {check.evidence_ids.length ? (
        <div className="flex flex-wrap gap-1 pb-1 pl-[6.6rem]">
          {uniq(check.evidence_ids).map((e) => (
            <EvidenceChip key={e} id={e} onOpen={onOpenEvidence} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

/** "max flow 0.0692 < needed 0.8000" in a G5 detail → a bar (display of the recorded numbers only). */
function parseFlow(detail: string): { flow: number; needed: number; ok: boolean } | null {
  const m = detail.match(/max flow ([\d.]+)\s*(<|≥|>=|>)\s*needed ([\d.]+)/);
  if (!m) return null;
  const flow = Number(m[1]);
  const needed = Number(m[3]);
  if (!Number.isFinite(flow) || !Number.isFinite(needed)) return null;
  return { flow, needed, ok: m[2] !== "<" };
}

function FlowBar({ flow, needed, ok }: { flow: number; needed: number; ok: boolean }) {
  const scale = Math.max(1, flow, needed);
  return (
    <span className="mt-1 block" aria-hidden>
      <span className="relative block h-2 overflow-hidden rounded bg-zinc-800">
        <span
          className={cn("absolute inset-y-0 left-0 rounded", ok ? "bg-emerald-400" : "bg-red-400")}
          style={{ width: `${(flow / scale) * 100}%` }}
        />
        <span className="absolute inset-y-0 w-0.5 bg-zinc-100" style={{ left: `${(needed / scale) * 100}%` }} />
      </span>
      <span className="mt-0.5 flex justify-between font-mono text-[10px] text-zinc-400">
        <span>flow {flow}</span>
        <span>needed {needed} (white tick)</span>
      </span>
    </span>
  );
}
