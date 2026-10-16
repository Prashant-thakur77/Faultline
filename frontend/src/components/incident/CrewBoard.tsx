"use client";

import { useId, useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowDown,
  Ban,
  CircleCheck,
  CircleMinus,
  CircleX,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import {
  crewBoard,
  durationMs,
  fmtDuration,
  gateLines,
  laneState,
  roleBadge,
  specialistName,
  type CrewLane,
  type GateLine,
  type LaneState,
} from "@/lib/crew";
import { fmtMs, fmtOffset } from "@/lib/format";
import { CHECK_STATE_TEXT, checkState, originText, sortChecks, type CheckState, type Tone } from "@/lib/gate";
import type { Crew, CrewCall, CrewMember, CrewStep, GateCheck, GateRun } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";
import { Disclosure } from "@/components/ui/Disclosure";
import { Section } from "./Section";

/** Calls shown per lane before "show all" (the rest stay one click away, never dropped). */
const CALLS_SHOWN = 8;

const LANE_STATE: Record<LaneState, { tone: Tone; icon?: LucideIcon }> = {
  done: { tone: "pass", icon: CircleCheck },
  failed: { tone: "fail", icon: CircleX },
  running: { tone: "running" },
  other: { tone: "na", icon: CircleMinus },
};

const DOT: Record<LaneState, string> = {
  done: "border-emerald-400/80 bg-emerald-500/30",
  failed: "border-red-400/80 bg-red-500/30",
  running: "border-sky-400/80 bg-sky-500/30",
  other: "border-zinc-400/70 bg-zinc-500/20",
};

const CHECK_ICON: Record<CheckState, LucideIcon> = {
  pass: CircleCheck,
  fail: CircleX,
  downgrade: TriangleAlert,
  na: CircleMinus,
};
const CHECK_TONE_TEXT: Record<CheckState, string> = {
  pass: "text-emerald-300",
  fail: "text-red-300",
  downgrade: "text-amber-300",
  na: "text-zinc-300",
};

export interface CrewBoardProps {
  /** The run's crew (Q-CREW-1); undefined when the run (older recording) did not record one. */
  crew: Crew | undefined;
  /** The incident's gate runs: the Gatekeeper's lane shows them (the gate's reads are recorded there). */
  gateRuns: GateRun[];
  onOpenCall: (call: CrewCall, step: CrewStep) => void;
  onOpenCheck: (run: GateRun, check: GateCheck) => void;
  /** Opens the crew query itself (Q-CREW-1) in the Cypher panel. */
  onOpenQuery?: (template: string) => void;
}

/**
 * Crew board (M17): the run as lanes in hand-off order (NEXT edges). Each lane is one Task record:
 * the role that claimed it, what it ran (graph calls → Cypher panel) and who it handed to. The lead's
 * lane fans out into the specialists it dispatched in parallel; the Gatekeeper's lane shows the
 * incident's gate runs. Everything shown is read from the payload; nothing is filled in.
 */
export function CrewBoard({ crew, gateRuns, onOpenCall, onOpenCheck, onOpenQuery }: CrewBoardProps) {
  if (!crew) {
    return (
      <Section id="crew" title="Crew">
        <p className="text-sm text-zinc-300">crew not recorded in this run</p>
      </Section>
    );
  }
  return <Board crew={crew} gateRuns={gateRuns} onOpenCall={onOpenCall} onOpenCheck={onOpenCheck} onOpenQuery={onOpenQuery} />;
}

function Board({ crew, gateRuns, onOpenCall, onOpenCheck, onOpenQuery }: CrewBoardProps & { crew: Crew }) {
  const reduced = useReducedMotion();
  const model = crewBoard(crew);
  const specCount = crew.steps.filter((s) => s.kind === "specialist").length;
  const crewCount = crew.steps.length - specCount;
  return (
    <Section
      id="crew"
      title="Crew"
      aside={
        <span className="text-xs text-[var(--fl-subtle)]">
          {crewCount} steps · {specCount} specialists
        </span>
      }
    >
      <p className="mb-4 text-xs leading-relaxed text-zinc-400">
        Every step below is a record in FalkorDB (
        {onOpenQuery ? (
          <button
            type="button"
            onClick={() => onOpenQuery(crew.template)}
            className="rounded font-mono text-zinc-200 underline decoration-zinc-500 underline-offset-2 outline-none hover:decoration-zinc-200 focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            {crew.template}
            <span className="sr-only"> (open the Cypher panel)</span>
          </button>
        ) : (
          <span className="font-mono text-zinc-200">{crew.template}</span>
        )}
        ): who claimed it, what it ran, and who it handed to.
      </p>

      {model.lanes.length === 0 && model.loose.length === 0 ? (
        <p className="text-sm text-zinc-300">No crew step recorded yet: steps appear as each role claims its task.</p>
      ) : (
        <ol aria-label="Crew steps in hand-off order" className="relative space-y-2">
          {model.lanes.map((lane, i) => (
            <motion.li
              key={lane.step.task}
              initial={reduced ? { opacity: 1, y: 0 } : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={reduced ? { duration: 0 } : { duration: 0.4, delay: Math.min(i, 12) * 0.06, ease: [0.22, 1, 0.36, 1] }}
              className="relative pl-6"
            >
              <Rail state={laneState(lane.step)} last={i === model.lanes.length - 1} />
              <Lane
                lane={lane}
                index={i}
                t0={model.t0}
                gateRuns={gateRuns}
                reduced={reduced}
                onOpenCall={onOpenCall}
                onOpenCheck={onOpenCheck}
              />
            </motion.li>
          ))}
        </ol>
      )}

      {model.loose.length ? (
        <div className="mt-3">
          <h3 className="mb-1 text-xs font-semibold text-zinc-200">Specialists with no lead step recorded</h3>
          <SpecialistGrid specs={model.loose} t0={model.t0} reduced={reduced} onOpenCall={onOpenCall} />
        </div>
      ) : null}
    </Section>
  );
}

/** The hand-off rail: a hairline joining the lanes and a state dot (decorative; the state chip carries the text). */
function Rail({ state, last }: { state: LaneState; last: boolean }) {
  return (
    <>
      <span aria-hidden className={cn("absolute top-0 left-[7px] w-px bg-[var(--fl-line)]", last ? "h-5" : "-bottom-2")} />
      <span aria-hidden className={cn("absolute top-4 left-[2px] size-[11px] rounded-full border", DOT[state])} />
    </>
  );
}

function Lane({
  lane,
  index,
  t0,
  gateRuns,
  reduced,
  onOpenCall,
  onOpenCheck,
}: {
  lane: CrewLane;
  index: number;
  t0: number | null;
  gateRuns: GateRun[];
  reduced: boolean;
  onOpenCall: (call: CrewCall, step: CrewStep) => void;
  onOpenCheck: (run: GateRun, check: GateCheck) => void;
}) {
  const hid = useId();
  const { step, member } = lane;
  const name = member?.name ?? step.role;
  const isGate = member?.key === "gatekeeper" || step.role === "gatekeeper";
  return (
    <article
      aria-labelledby={hid}
      className="rounded-xl bg-white/[0.02] px-4 py-3 ring-1 ring-white/[0.05] transition-colors hover:ring-white/[0.1]"
    >
      <LaneHeader
        hid={hid}
        index={index}
        name={name}
        member={member}
        step={step}
        t0={t0}
      />
      {member?.job ? <p className="mt-0.5 text-xs text-zinc-400">{member.job}</p> : null}
      {step.summary ? <p className="mt-1.5 text-sm break-words text-zinc-100">{step.summary}</p> : null}
      <Disclosure
        className="mt-2"
        size="xs"
        summary={
          <>
            What it ran
            <span className="text-[var(--fl-subtle)]">
              {" "}
              · {step.calls.length} graph call{step.calls.length === 1 ? "" : "s"}
              {lane.specialists.length ? ` · ${lane.specialists.length} specialists` : ""}
              {isGate && gateRuns.length ? ` · ${gateRuns.length} gate runs` : ""}
            </span>
          </>
        }
      >
      <Meta step={step} member={member} />
        <CallList step={step} label={name} onOpenCall={onOpenCall} />

        {lane.specialists.length ? (
          <div className="mt-3">
            <p className="mb-1.5 text-[11px] text-zinc-400">
              Dispatched {lane.specialists.length} specialist{lane.specialists.length === 1 ? "" : "s"} in parallel
            </p>
            <SpecialistGrid specs={lane.specialists} t0={t0} reduced={reduced} onOpenCall={onOpenCall} />
            {lane.handsTo.length ? (
              <p className="mt-1.5 flex items-center gap-1 text-[11px] text-zinc-400">
                <ArrowDown aria-hidden className="size-3.5 shrink-0" />
                their reports converge; hands to <span className="text-zinc-200">{lane.handsTo.join(", ")}</span>
              </p>
            ) : null}
          </div>
        ) : null}

        {isGate ? <GateRuns runs={gateRuns} onOpenCheck={onOpenCheck} /> : null}
      </Disclosure>
      {lane.handsTo.length && !lane.specialists.length ? (
        <p className="mt-2 flex items-center gap-1 text-[11px] text-zinc-400">
          <ArrowDown aria-hidden className="size-3.5 shrink-0" />
          hands to <span className="text-zinc-200">{lane.handsTo.join(", ")}</span>
        </p>
      ) : null}
    </article>
  );
}

function LaneHeader({
  hid,
  index,
  name,
  member,
  step,
  t0,
}: {
  hid: string;
  index: number;
  name: string;
  member: CrewMember | null;
  step: CrewStep;
  t0: number | null;
}) {
  const st = laneState(step);
  const badge = roleBadge(member);
  const dur = durationMs(step);
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span aria-hidden className="font-mono text-[11px] text-[var(--fl-muted)]">
        {String(index + 1).padStart(2, "0")}
      </span>
      <h3 id={hid} className="text-sm font-semibold text-zinc-50">
        {name}
      </h3>
      {badge ? <RoleBadge text={badge} decides={member?.key === "gatekeeper"} /> : null}
      {step.stage ? (
        <span className="rounded border border-white/[0.1] px-1 font-mono text-[10px] tracking-wide text-zinc-300">
          <span className="sr-only">stage </span>
          {step.stage}
        </span>
      ) : null}
      <span className="ml-auto flex flex-wrap items-center gap-1.5">
        <StatusChip tone={LANE_STATE[st].tone} icon={LANE_STATE[st].icon}>
          {st === "other" ? (step.state ?? "unknown") : st}
        </StatusChip>
        <span className="font-mono text-[11px] text-zinc-300" title="done_at − claimed_at">
          <span className="sr-only">took </span>
          {fmtDuration(dur)}
        </span>
        {t0 !== null && typeof step.claimed_at === "number" ? (
          <span className="font-mono text-[11px] text-zinc-400" title="claimed, from the run's first claim">
            <span className="sr-only">claimed at </span>
            {fmtOffset(step.claimed_at, t0)}
          </span>
        ) : null}
      </span>
    </div>
  );
}

function RoleBadge({ text, decides }: { text: string; decides?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full border px-1.5 text-[10px] leading-4 font-medium",
        decides ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-200" : "border-white/[0.12] text-zinc-300",
      )}
    >
      {text}
    </span>
  );
}

function Meta({ step, member }: { step: CrewStep; member: CrewMember | null }) {
  const parts: React.ReactNode[] = [];
  if (step.agent)
    parts.push(
      <span key="a">
        claimed by <span className="font-mono text-zinc-300 [overflow-wrap:anywhere]">{step.agent}</span>
      </span>,
    );
  if (member?.writes) parts.push(<span key="w">writes: {member.writes}</span>);
  if (step.reaps > 0) parts.push(<span key="r" className="text-amber-200">lease reclaimed {step.reaps}×</span>);
  if (!parts.length) return null;
  return (
    <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-zinc-400">
      {parts}
    </p>
  );
}

function CallList({
  step,
  label,
  onOpenCall,
}: {
  step: CrewStep;
  label: string;
  onOpenCall: (call: CrewCall, step: CrewStep) => void;
}) {
  const [all, setAll] = useState(false);
  if (!step.calls.length) return null;
  const shown = all ? step.calls : step.calls.slice(0, CALLS_SHOWN);
  const hidden = step.calls.length - shown.length;
  return (
    <div className="mt-2">
      <ul aria-label={`Graph calls by ${label} (${step.calls.length})`} className="flex flex-wrap gap-1">
        {shown.map((c) => (
          <li key={c.id} className="min-w-0 max-w-full">
            <button
              type="button"
              onClick={() => onOpenCall(c, step)}
              className="inline-flex max-w-full flex-wrap items-center gap-x-1.5 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-left font-mono text-[11px] leading-4 text-zinc-300 outline-none transition-colors hover:border-white/[0.2] hover:bg-white/[0.06] focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <span className="text-zinc-100">{c.tool}</span>
              <span className="text-zinc-400 [overflow-wrap:anywhere]">{c.template ?? "no template"}</span>
              <span className="text-zinc-400">{fmtMs(c.ms)}</span>
              <span className="sr-only">. Open the Cypher panel{c.template ? ` for ${c.template}` : ""}.</span>
            </button>
          </li>
        ))}
      </ul>
      {hidden > 0 || all ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mt-1 rounded text-[11px] text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {all ? "show fewer calls" : `show ${hidden} more call${hidden === 1 ? "" : "s"}`}
        </button>
      ) : null}
    </div>
  );
}

function SpecialistGrid({
  specs,
  t0,
  reduced,
  onOpenCall,
}: {
  specs: CrewStep[];
  t0: number | null;
  reduced: boolean;
  onOpenCall: (call: CrewCall, step: CrewStep) => void;
}) {
  return (
    <div className="@container">
      <ul
        aria-label="Specialists dispatched in parallel"
        className="grid grid-cols-1 gap-2 @xl:grid-cols-2 @3xl:grid-cols-3 @5xl:grid-cols-5"
      >
        {specs.map((s, i) => (
          <motion.li
            key={s.task}
            initial={reduced ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={reduced ? { duration: 0 } : { duration: 0.35, delay: 0.1 + i * 0.05, ease: [0.22, 1, 0.36, 1] }}
            className="min-w-0"
          >
            <Specialist step={s} t0={t0} onOpenCall={onOpenCall} />
          </motion.li>
        ))}
      </ul>
    </div>
  );
}

function specialistStatus(s: CrewStep): { tone: Tone; text: string; icon?: LucideIcon } {
  const v = (s.status ?? "").toLowerCase();
  if (v === "complete") return { tone: "pass", text: "complete", icon: CircleCheck };
  if (v === "insufficient") return { tone: "warn", text: "insufficient", icon: TriangleAlert };
  const st = laneState(s);
  if (st === "failed") return { tone: "fail", text: s.status ?? "failed", icon: CircleX };
  if (st === "running") return { tone: "running", text: s.status ?? "running" };
  return { tone: "na", text: s.status ?? s.state ?? "unknown", icon: CircleMinus };
}

function Specialist({
  step,
  t0,
  onOpenCall,
}: {
  step: CrewStep;
  t0: number | null;
  onOpenCall: (call: CrewCall, step: CrewStep) => void;
}) {
  const hid = useId();
  const name = specialistName(step.role);
  const st = specialistStatus(step);
  const unknowns = step.unknowns ?? [];
  const limits = step.limits ?? [];
  return (
    <article
      aria-labelledby={hid}
      className={cn(
        "h-full rounded-lg border p-2.5",
        st.tone === "warn" ? "border-amber-400/30 bg-amber-500/[0.04]" : "border-[var(--fl-line)] bg-white/[0.02]",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <h4 id={hid} className="text-xs font-semibold text-zinc-50">
          {name}
        </h4>
        <StatusChip tone={st.tone} icon={st.icon}>
          {st.text}
        </StatusChip>
      </div>
      <p className="mt-0.5 font-mono text-[11px] text-zinc-400">
        <span className="sr-only">took </span>
        {fmtDuration(durationMs(step))}
        {t0 !== null && typeof step.claimed_at === "number" ? ` · ${fmtOffset(step.claimed_at, t0)}` : ""}
        {` · cites ${step.cites}`}
      </p>
      <div className="mt-1.5">
        <p className="text-[11px] text-zinc-400">{step.names.length ? "names" : "names no suspect"}</p>
        {step.names.length ? (
          <ul aria-label={`Suspects ${name} names`} className="mt-0.5 flex flex-wrap gap-1">
            {step.names.map((n) => (
              <li key={n} className="rounded border border-white/[0.1] px-1 font-mono text-[11px] text-zinc-100 [overflow-wrap:anywhere]">
                {n}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {unknowns.length ? (
        <div className="mt-1.5">
          <p className="text-[11px] text-amber-200">unknowns</p>
          <ul className="mt-0.5 space-y-0.5 text-[11px] leading-snug break-words text-zinc-300">
            {unknowns.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <CallList step={step} label={name} onOpenCall={onOpenCall} />
      {limits.length ? (
        <details className="mt-1.5 text-[11px] text-zinc-400">
          <summary className="cursor-pointer rounded outline-none hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-sky-400">
            limits ({limits.length})
          </summary>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4 leading-snug break-words text-zinc-300">
            {limits.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  );
}

function verdict(run: GateRun): { tone: Tone; text: string; icon: LucideIcon } {
  if (!run.passed) return { tone: "fail", text: "rejected", icon: ShieldX };
  if (run.origin === "no_incident") return { tone: "info", text: "negative proof accepted", icon: ShieldCheck };
  if (run.origin === "sweep") return { tone: "info", text: "passed the sweep", icon: ShieldCheck };
  return run.confident
    ? { tone: "pass", text: "passed, confident", icon: ShieldCheck }
    : { tone: "warn", text: "passed, not confident", icon: TriangleAlert };
}

function GateRuns({ runs, onOpenCheck }: { runs: GateRun[]; onOpenCheck: (run: GateRun, check: GateCheck) => void }) {
  const lines = gateLines(runs);
  return (
    <div className="mt-3">
      <h4 className="text-xs font-semibold text-zinc-200">
        Gate runs{" "}
        <span className="font-normal text-zinc-400">(the gate&apos;s own reads, recorded on each run)</span>
      </h4>
      {lines.length === 0 ? (
        <p className="mt-1 text-xs text-zinc-300">No gate run recorded for this incident yet.</p>
      ) : (
        <ul aria-label="Gate runs, candidate by candidate" className="mt-1.5 space-y-1.5">
          {lines.map((l) => (
            <GateRunLine key={l.run.id} line={l} onOpenCheck={onOpenCheck} />
          ))}
        </ul>
      )}
    </div>
  );
}

function GateRunLine({ line, onOpenCheck }: { line: GateLine; onOpenCheck: (run: GateRun, check: GateCheck) => void }) {
  const { run, firstFail, notEvaluable, downgrades } = line;
  const v = verdict(run);
  return (
    <li
      className={cn(
        "rounded-lg border p-2",
        run.passed ? "border-[var(--fl-line)]" : "border-red-500/40 bg-red-500/[0.05]",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {!run.passed ? <Ban aria-hidden className="size-3.5 text-red-300" /> : null}
        <span
          className={cn(
            "font-mono text-xs text-zinc-50 [overflow-wrap:anywhere]",
            !run.passed && "line-through decoration-red-300/70",
          )}
        >
          {run.cause}
        </span>
        <StatusChip tone={v.tone} icon={v.icon}>
          {v.text}
        </StatusChip>
        <span className="text-[11px] text-zinc-400">
          {originText(run.origin)} · attempt {run.attempt}
        </span>
      </div>
      {firstFail ? (
        <CheckButton run={run} check={firstFail} lead="failed" onOpen={onOpenCheck} />
      ) : null}
      {run.passed ? <CheckStrip run={run} onOpen={onOpenCheck} /> : null}
      {[...downgrades, ...notEvaluable].map((c, i) => (
        <CheckButton
          key={`${c.name}:${i}`}
          run={run}
          check={c}
          lead={checkState(c) === "na" ? "not evaluable" : "downgrade"}
          onOpen={onOpenCheck}
        />
      ))}
    </li>
  );
}

function CheckButton({
  run,
  check,
  lead,
  onOpen,
}: {
  run: GateRun;
  check: GateCheck;
  lead: string;
  onOpen: (run: GateRun, check: GateCheck) => void;
}) {
  const s = checkState(check);
  const Icon = CHECK_ICON[s];
  return (
    <button
      type="button"
      onClick={() => onOpen(run, check)}
      className="mt-1 flex w-full items-start gap-1.5 rounded px-0.5 text-left text-xs outline-none hover:bg-white/[0.03] focus-visible:ring-2 focus-visible:ring-sky-400"
    >
      <Icon aria-hidden className={cn("mt-0.5 size-3.5 shrink-0", CHECK_TONE_TEXT[s])} />
      <span className="min-w-0 flex-1 break-words text-zinc-200">
        <strong className="font-semibold text-zinc-50">{check.name}</strong>{" "}
        <span className={CHECK_TONE_TEXT[s]}>
          {lead}
          {check.detail ? ":" : ""}
        </span>
        {check.detail ? <> {check.detail}</> : null}
        {check.template ? (
          <span className="ml-1 font-mono text-[10px] text-[var(--fl-subtle)]">{check.template}</span>
        ) : null}
        <span className="sr-only"> Open the Cypher panel.</span>
      </span>
    </button>
  );
}

/** A passed run's checks as compact chips (code, icon and state word); each opens its query. */
function CheckStrip({ run, onOpen }: { run: GateRun; onOpen: (run: GateRun, check: GateCheck) => void }) {
  const checks = sortChecks(run.checks);
  if (!checks.length) return null;
  return (
    <ul aria-label={`Checks for ${run.cause}`} className="mt-1.5 flex flex-wrap gap-1">
      {checks.map((c, i) => {
        const s = checkState(c);
        const Icon = CHECK_ICON[s];
        return (
          <li key={`${c.name}:${i}`}>
            <button
              type="button"
              onClick={() => onOpen(run, c)}
              title={`${c.name}: ${c.detail}`}
              className="inline-flex items-center gap-1 rounded border border-white/[0.08] px-1 font-mono text-[10px] leading-4 text-zinc-300 outline-none hover:border-white/[0.2] focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <Icon aria-hidden className={cn("size-3", CHECK_TONE_TEXT[s])} />
              <span>{c.name}</span>
              <span className={CHECK_TONE_TEXT[s]}>{CHECK_STATE_TEXT[s]}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
