"use client";

import { useMemo, useState } from "react";
import { ArrowRight, CircleHelp, Route, ShieldCheck, Waves } from "lucide-react";
import type { StreamState, TimelineItem } from "@/hooks/useIncident";
import { fmtTime } from "@/lib/format";
import { abstentionOf, chainsOf, originText, outcomeMeta } from "@/lib/gate";
import { buildGraphModel } from "@/lib/graphModel";
import type {
  BlastResponse,
  CrewCall,
  GraphResponse,
  IncidentView,
  PlanResponse,
} from "@/lib/types";
import type { CypherRequest } from "@/components/cypher/CypherPanelContext";
import { StatusChip } from "@/components/StatusChip";
import { OfflineTemplatesProvider, ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Disclosure, FoldProvider } from "@/components/ui/Disclosure";
import { cn } from "@/lib/utils";
import { AgentNotesCard } from "./AgentNotesCard";
import { AlertCoverageCard } from "./AlertCoverageCard";
import { BlastTable } from "./BlastTable";
import { ChainTable } from "./ChainTable";
import { ContainmentCard } from "./ContainmentCard";
import { ContradictionsCard } from "./ContradictionsCard";
import { CrewBoard } from "./CrewBoard";
import { LearnedEdgesCard } from "./LearnedEdgesCard";
import { EvidenceTable } from "./EvidenceTable";
import { GateChecklist } from "./GateChecklist";
import { GraphLegend } from "./GraphLegend";
import {
  GraphView,
  type CutEdge,
  type GraphMode,
  type RippleData,
} from "./GraphView";
import { HypothesesCard } from "./HypothesesCard";
import { MemoryCard } from "./MemoryCard";
import { NotifyCard } from "./NotifyCard";
import { ObligationsCard } from "./ObligationsCard";
import { OwnershipCard } from "./OwnershipCard";
import { PlanApprovalCard, VerdictChip } from "./PlanApprovalCard";
import { hasConfirmedCause, WhyBelieveButton } from "./ProvenanceDialog";
import { ResidueCard } from "./ResidueCard";
import { RootCauseCard } from "./RootCauseCard";
import { Section, SectionFold } from "./Section";
import { StageTimeline } from "./StageTimeline";
import { useIncidentActions } from "./useIncidentActions";
import { WhoFixesCard } from "./WhoFixesCard";

/** M12 sections a recording can predate (replay only); each is replaced by one shared note. */
export type NotRecorded =
  "residue" | "alerts" | "ownership" | "notify" | "remedy";

const NOT_RECORDED_TEXT: Record<NotRecorded, string> = {
  residue: "residue check",
  alerts: "why alerts missed it",
  ownership: "ownership when the change shipped",
  notify: "who to notify",
  remedy: "learned remediation ordering",
};

/**
 * Where the incident room's data comes from. The live room fills it from the API (SSE +
 * polling); the replay page fills it from a recorded run's static exports. The layout
 * renders whatever it is given and never invents a value that the source does not have.
 */
export interface RoomSource {
  mode: "live" | "replay";
  view: IncidentView;
  viewError?: { text: string; status: number | null } | null;
  graph: GraphResponse | null;
  graphError: string | null;
  /** Extra line under the graph title (replay: where the graph came from). */
  graphNote?: string | null;
  timeline: TimelineItem[];
  stream: StreamState;
  announcement: string;
  plan: PlanResponse | null;
  planError: string | null;
  /** Set when the source cannot have a plan at all (replay export without one): the reason. */
  planUnavailable?: string | null;
  blast: BlastResponse | null;
  blastError: string | null;
  blastUnavailable?: string | null;
  onRefreshPlan?: () => void;
  onApproved?: () => void;
  offline?: CypherRequest["offline"];
  /** Replay: sections this recording predates; hidden, and listed once in a "not in this recording" note. */
  notRecorded?: NotRecorded[];
  /** Rendered above the incident header (replay controls). */
  top?: React.ReactNode;
  /** Header metadata overrides (replay: fields the export does not carry). */
  meta?: { label: string; value: string; mono?: boolean }[];
}

/**
 * Incident room: left = stage timeline, centre = graph view + text
 * alternatives + crew board, right = suspects → gate → root cause → residue → contradictions → why alerts
 * missed it → containment → who fixes it → ownership at the change → notify → notes from other agents (live) → memory →
 * plan & approval → evidence.
 */
export function IncidentRoomLayout({ source }: { source: RoomSource }) {
  const { view, graph, graphError, plan, blast } = source;
  const actions = useIncidentActions(view, source.offline ?? null);
  const [mode, setMode] = useState<GraphMode>("path");
  // phones/tablets: one pane at a time (verdict first); desktop shows every column
  const [pane, setPane] = useState<"verdict" | "graph" | "crew" | "timeline">("verdict");
  const paneCls = (p: typeof pane) => (pane === p ? "" : "hidden lg:block");

  const chains = useMemo(() => chainsOf(view), [view]);
  const abstain = useMemo(() => abstentionOf(view), [view]);
  const model = useMemo(() => {
    if (!graph) return null;
    const notes = new Map(
      chains.rejected.map((r) => [
        r.cause,
        `rejected by ${originText(r.origin)}: ${r.failed.map((f) => f.text).join("; ")}`,
      ]),
    );
    // "NO_INCIDENT" is the negative-proof hypothesis, not a suspect with a chain: keep it off the graph.
    const suspects = {
      ...chains,
      rejected: chains.rejected.filter((r) => r.cause !== "NO_INCIDENT"),
    };
    return buildGraphModel(graph, suspects, view.incident.targets, notes);
  }, [view, graph, chains]);

  const ripple = useMemo((): RippleData | null => {
    if (!blast) return null;
    const cause = new Set<string>();
    let causeLabel: string | undefined;
    if (chains.proof)
      chains.proof.chain.slice(0, 2).forEach((id) => cause.add(id));
    else if (view.report?.cause_id) cause.add(view.report.cause_id);
    else if (abstain) {
      // Abstained: the inferred origin is marked as such, never as a cause.
      cause.add(abstain.origin);
      causeLabel = "INFERRED";
    }
    const hops = new Map<string, number>();
    for (const [symptom, b] of Object.entries(blast.blast)) {
      if (!cause.has(symptom)) hops.set(symptom, 0);
      for (const r of b.rows) {
        if (cause.has(r.id)) continue;
        const prev = hops.get(r.id);
        if (prev === undefined || r.hops < prev) hops.set(r.id, r.hops);
      }
    }
    return { cause, blast: hops, causeLabel };
  }, [blast, chains, view.report, abstain]);

  const cut = useMemo(
    (): CutEdge[] =>
      (plan?.containment_cut?.payload?.rows ?? []).map((r) => ({
        u: r.u,
        v: r.v,
        cost: r.cut_cost,
        domain: r.domain,
      })),
    [plan],
  );

  const topB = useMemo(() => {
    let best: { id: string; score: number } | null = null;
    for (const n of graph?.nodes ?? []) {
      if (
        typeof n.betweenness === "number" &&
        (!best || n.betweenness > best.score)
      )
        best = { id: n.id, score: n.betweenness };
    }
    return best;
  }, [graph]);

  // M12 sections. A negative proof has no chain, cause or route, so they stay out of its room; otherwise
  // each section renders and says plainly when its field is absent (older recording / backend) or empty.
  const noIncident = view.run.outcome === "NO_INCIDENT";
  const absent = new Set(source.notRecorded ?? []);
  const showResidue = !noIncident && !abstain && !absent.has("residue");
  const showAlerts = !noIncident && !abstain && !absent.has("alerts");
  const showOwnership = !noIncident && !absent.has("ownership");
  const showNotify = !noIncident && !absent.has("notify");
  // Notes from other agents (live only) are read around one component: the confirmed cause's target (the hop after the
  // change on the proof path), else the incident's main symptom.
  const notesFocus = (chains.proof && chains.proof.chain.length >= 2 ? chains.proof.chain[1] : null) ?? view.incident.targets[0] ?? null;
  const remedyCall = actions.toolCallOf("remedy_stats");
  const learnedCall = actions.toolCallOf("learned_preferences"); // M21: what the team taught Faultline (the plan's learned order)
  // A crew call is a ToolCall node: open the recorded row (with its params) when the view has it, else the call as the
  // crew query returned it (the panel then derives params and labels them so).
  const openCrewCall = (c: CrewCall) =>
    actions.openToolCall(
      view.tool_calls.find((t) => t.id === c.id) ?? {
        id: c.id,
        tool: c.tool,
        template: c.template,
        ms: c.ms ?? Number.NaN,
        rows: c.rows ?? Number.NaN,
        at: c.at ?? Number.NaN,
        evidence_id: null,
        kind: null,
        summary: null,
      },
    );

  const m = outcomeMeta(view.run.outcome);
  // The fix's own verdict (separate from the cause): the approved option's, else the last failed attempt's.
  const fixVerdict =
    (plan?.options ?? []).find(
      (o) => (o.status === "approved" || o.status === "executed") && o.verdict,
    )?.verdict ??
    (plan?.options ?? [])
      .filter((o) => o.status === "failed" && o.verdict)
      .at(-1)?.verdict ??
    null;
  // A confirmed cause is not a fixed incident: drop the green once the fix did not verify.
  const causeTone =
    m.tone === "pass" && fixVerdict && fixVerdict !== "APPLIED"
      ? "info"
      : m.tone;
  const layoutKey = `${graph?.graph ?? ""}:${model?.chains.map((c) => c.nodes.join(">")).join("|") ?? ""}`;
  const rippleReason =
    source.blastUnavailable ??
    (source.blastError
      ? `blast radius unavailable: ${source.blastError}`
      : !blast
        ? "loading the blast radius…"
        : null);
  const effectiveMode: GraphMode =
    mode === "ripple" && ripple ? "ripple" : "path";
  const stage = view.incident.stage;
  const meta = source.meta ?? [
    { label: "scenario", value: view.run.scenario, mono: true },
    {
      label: "symptom",
      value: view.incident.targets.join(", ") || "–",
      mono: true,
    },
    { label: "onset", value: fmtTime(view.incident.onset_at) },
    { label: "investigator", value: view.run.investigator },
    { label: "graph", value: view.run.graph, mono: true },
  ];

  // The proof behind the verdict line: the accepted gate run of the proven cause and its path and flow checks.
  const proofRun = chains.proof
    ? ([...view.gate_runs]
        .filter((r) => r.cause === chains.proof!.cause && r.passed)
        .sort((a, b) => b.at - a.at)[0] ?? null)
    : null;
  const g2 = proofRun?.checks.find((c) => c.name === "G2 path") ?? null;
  const g5 = proofRun?.checks.find((c) => c.name === "G5 sufficiency") ?? null;
  const ruledOut = [...new Set(chains.rejected.map((r) => r.cause).filter((c) => c !== "NO_INCIDENT"))];
  const canChoose = source.mode === "live" && stage === "AWAITING_APPROVAL" && !!plan && !source.planUnavailable;
  const goToPlan = () => {
    setPane("verdict");
    requestAnimationFrame(() => {
      const sec = document.getElementById("plan-h")?.closest("section");
      if (!sec) return;
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      sec.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      (sec.querySelector<HTMLElement>("ul[aria-label='Action options'] button") ?? sec.querySelector<HTMLElement>("h2"))?.focus({ preventScroll: true });
    });
  };

  return (
    <OfflineTemplatesProvider templates={source.offline?.templates ?? null}>
    <FoldProvider>
    <div className="flex min-h-0 flex-1 flex-col">
      {source.top}
      <header className="border-b border-white/[0.06] px-4 pt-5 pb-4 sm:px-6">
        <div className="mx-auto max-w-[1920px] space-y-3">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
            <h1 className="flex w-full min-w-0 flex-col gap-1 text-zinc-50 xl:w-auto">
              <span className="font-mono text-[11px] tracking-wide text-[var(--fl-subtle)]">{view.incident.id}</span>
              <span className="text-2xl font-[510] leading-tight tracking-[-0.025em] [overflow-wrap:anywhere] sm:text-[28px]">
                {view.incident.title.replaceAll("_", " ")}
              </span>
            </h1>
            <div className="flex flex-wrap items-center gap-2 pb-1">
              <StatusChip tone={causeTone} title={m.meaning}>
                {m.text}
              </StatusChip>
              {fixVerdict ? (
                <span className="inline-flex items-center gap-1 text-xs text-zinc-400">
                  fix <VerdictChip verdict={fixVerdict} />
                </span>
              ) : null}
            </div>
            {canChoose ? (
              <button
                type="button"
                onClick={goToPlan}
                className="fl-press ml-auto mb-1 inline-flex min-h-9 items-center gap-1.5 rounded-full bg-zinc-50 px-4 text-sm font-medium text-zinc-950 outline-none hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
              >
                Choose a fix <ArrowRight aria-hidden className="size-4" />
              </button>
            ) : null}
          </div>

          {abstain ? (
            <p
              role="status"
              className="flex w-full items-center gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-50 ring-1 ring-amber-400/50"
            >
              <CircleHelp aria-hidden className="size-4 shrink-0 text-amber-300" />
              <span>
                <strong className="font-semibold">Abstained:</strong> no change explains this; inferred origin{" "}
                <span className="font-mono font-semibold">{abstain.origin}</span>
                {abstain.chain ? <span className="font-mono text-amber-200"> ({abstain.chain.join(" → ")})</span> : null}{" "}
                <span className="text-amber-200">(unconfirmed: no gate check proved it)</span>
              </span>
            </p>
          ) : view.run.outcome === "NO_INCIDENT" ? (
            <p role="status" className="flex w-full items-center gap-2 rounded-lg bg-sky-500/10 px-3 py-2 text-sm text-sky-50 ring-1 ring-sky-400/40">
              <ShieldCheck aria-hidden className="size-4 shrink-0 text-sky-300" />
              <span>
                <strong className="font-semibold">No incident:</strong> negative proof accepted (N1 measurements in band, N2
                no change reaches an anomalous node). Nothing to contain or fix.
              </span>
            </p>
          ) : chains.proof ? (
            <div>
              <p className="max-w-5xl text-[15px] leading-relaxed text-zinc-300">
                <span className="font-mono font-semibold text-[var(--fl-ember)]">{chains.proof.cause}</span>{" "}
                <span className="text-zinc-100">caused this</span>, proven by a graph path{" "}
                <span className="font-mono text-zinc-200">
                  {chains.proof.chain.map((id, i) => (
                    <span key={`${id}:${i}`}>
                      {i ? " → " : ""}
                      <span className="whitespace-nowrap">{id}</span>
                    </span>
                  ))}
                </span>
                {g5?.passed ? " that carries the impact" : ""}.
                {ruledOut.length ? (
                  <>
                    {" "}
                    {ruledOut.length} other suspect{ruledOut.length === 1 ? "" : "s"} ruled out (
                    {ruledOut.map((c, i) => (
                      <span key={c}>
                        {i ? ", " : ""}
                        <span className="font-mono whitespace-nowrap">{c}</span>
                      </span>
                    ))}
                    ).
                  </>
                ) : null}
              </p>
            </div>
          ) : !view.run.outcome || view.run.outcome === "RUNNING" ? (
            <p className="text-[15px] text-zinc-400">Investigating: the verdict appears here once the evidence gate decides.</p>
          ) : null}

          <Disclosure
            size="xs"
            actions={
              proofRun && (g2 || g5) ? (
                <span className="flex flex-wrap items-center gap-1">
                  {g2 ? <ViaFalkor template={g2.template} label="the proof path (G2)" onOpen={() => actions.openCheck(proofRun, g2)} /> : null}
                  {g5 ? <ViaFalkor compact template={g5.template} label="the flow check (G5)" onOpen={() => actions.openCheck(proofRun, g5)} /> : null}
                </span>
              ) : null
            }
            summary={
              <>
                Run details
                <span className="text-[var(--fl-subtle)]">
                  {" "}
                  · {meta.slice(0, 2).map((x) => x.value).join(" · ")}
                </span>
              </>
            }
          >
            <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
              {meta.map((x) => (
                <Meta key={x.label} label={x.label} value={x.value} mono={x.mono} />
              ))}
              <Meta label="stage" value={stage} mono />
            </dl>
          </Disclosure>
          {source.viewError ? (
            <p role="alert" className="text-xs text-red-300">
              Latest refresh failed: {source.viewError.text}
            </p>
          ) : null}
        </div>
      </header>

      <div className="sticky top-14 z-30 border-b border-white/[0.06] bg-[color-mix(in_oklch,var(--fl-bg)_85%,transparent)] px-4 py-2 backdrop-blur-xl lg:hidden">
        <div role="tablist" aria-label="Incident panes" className="mx-auto flex max-w-md rounded-full border border-white/[0.08] bg-white/[0.03] p-1 text-sm">
          {([["verdict", "Verdict"], ["graph", "Graph"], ["crew", "Crew"], ["timeline", "Timeline"]] as const).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={pane === k} aria-controls={`pane-${k}`}
                    onClick={() => setPane(k)}
                    className={"flex-1 rounded-full px-3 py-1.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400 " +
                      (pane === k ? "bg-white/[0.1] text-zinc-50" : "text-zinc-400")}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(230px,270px)_minmax(0,1fr)] xl:grid-cols-[minmax(230px,270px)_minmax(0,1fr)_minmax(400px,470px)]">
        <aside
          id="pane-timeline"
          className={"min-h-0 border-white/[0.06] lg:overflow-y-auto lg:border-r " + paneCls("timeline")}
          aria-label="Run timeline"
        >
          <StageTimeline
            items={source.timeline}
            stream={source.stream}
            announcement={source.announcement}
            onOpenToolCall={actions.openToolCall}
            onOpenEvidence={actions.openEvidence}
          />
        </aside>

        <div className={"min-h-0 space-y-4 p-4 lg:overflow-y-auto " + (pane === "graph" || pane === "crew" ? "" : "hidden lg:block")}>
          <div id="pane-graph" className={"space-y-4 " + paneCls("graph")}>
            <section aria-labelledby="graph-h" className="fl-card overflow-hidden rounded-2xl">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 pt-3.5 pb-3">
                <h2 id="graph-h" className="text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
                  Failure-flow graph
                </h2>
                <span className="text-xs text-[var(--fl-subtle)]">
                  {graph ? `${graph.nodes.length} nodes · ${graph.edges.length} edges` : ""}
                </span>
                <div
                  role="group"
                  aria-label="Graph view mode"
                  className="ml-auto flex rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]"
                >
                  <ModeButton active={effectiveMode === "path"} onClick={() => setMode("path")} icon={Route} text="Path" />
                  <ModeButton
                    active={effectiveMode === "ripple"}
                    onClick={() => setMode("ripple")}
                    icon={Waves}
                    text="Ripple"
                    disabledReason={ripple ? null : rippleReason}
                  />
                </div>
                <p className="w-full text-xs text-[var(--fl-subtle)]" id="graph-hint">
                  {source.graphNote ? `${source.graphNote} · ` : ""}
                  {effectiveMode === "ripple"
                    ? "Ripple: the cause in red, its blast radius in yellow, the rest dimmed."
                    : "Path: the proof path lights up hop by hop."}
                  <span className="sr-only"> Tab to the highlighted nodes; Enter opens the Cypher panel.</span>
                  {mode === "ripple" && !ripple && rippleReason ? ` Ripple unavailable: ${rippleReason}` : ""}
                </p>
              </div>
              <div className="h-[clamp(380px,60vh,680px)] border-y border-white/[0.06]">
                {graphError ? (
                  <div role="alert" className="m-3 rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
                    Graph view unavailable: {graphError}
                  </div>
                ) : !graph || !model ? (
                  <p className="p-3 text-sm text-zinc-300">Loading the failure-flow graph…</p>
                ) : model.nodes.length === 0 ? (
                  <p className="p-3 text-sm text-zinc-300">
                    The incident graph has no PROPAGATES_TO edges, so there is nothing to draw.
                  </p>
                ) : (
                  <GraphView
                    model={model}
                    onOpenNode={actions.openNode}
                    layoutKey={layoutKey}
                    mode={effectiveMode}
                    ripple={ripple}
                    cut={cut}
                  />
                )}
              </div>
              <div className="space-y-2 px-4 py-3">
                <GraphLegend
                  mode={effectiveMode}
                  hasCut={cut.length > 0}
                  topBetweenness={topB}
                  note={`Zoomed out, names stay on ${
                    effectiveMode === "ripple" ? "the cause, the symptoms" : "the proof path, the symptoms, the rejected suspects"
                  }${cut.length ? " and the min-cut ends" : ""}; hover, focus or zoom in for any other box, or read the text alternatives below.`}
                  rippleText={
                    abstain
                      ? {
                          cause: ["INFERRED", "inferred upstream origin, NOT confirmed (red, dashed in the text)"],
                          blast: ["BLAST", "in the blast radius (yellow, with BFS hops from the symptom; algo.BFS, Q-BLAST-1)"],
                        }
                      : null
                  }
                />
                <div className="flex flex-wrap items-center gap-1">
                  <ViaFalkor
                    template="Q-VIEW-1+Q-CHOKE-ALL"
                    label="the failure-flow graph and node betweenness"
                    onOpen={() => actions.openTemplate("Q-VIEW-1", "failure-flow graph", "graph view (GET /api/graph)")}
                  />
                  {effectiveMode === "ripple" ? (
                    <ViaFalkor
                      compact
                      template="Q-BLAST-1"
                      label="the blast radius"
                      onOpen={() => {
                        const tc = actions.toolCallOf("blast_radius");
                        if (tc) actions.openToolCall(tc);
                        else actions.openTemplate("Q-BLAST-1", "blast radius", "graph view (ripple)");
                      }}
                    />
                  ) : null}
                </div>
              </div>
            </section>

            <TextAlternatives
              model={model}
              blast={blast}
              onOpenNode={actions.openNode}
              emptyText={
                view.run.outcome === "NO_INCIDENT"
                  ? "None: the negative proof was accepted, so no change has a causal chain to the symptom."
                  : abstain
                    ? `None proven: no change has a causal path to the symptom. The inferred origin ${abstain.origin} is not a proven chain.`
                    : undefined
              }
            />
          </div>

          <div id="pane-crew" className={paneCls("crew")}>
            <CrewBoard
              crew={view.crew}
              gateRuns={view.gate_runs}
              onOpenCall={openCrewCall}
              onOpenCheck={actions.openCheck}
              onOpenQuery={(t) => actions.openTemplate(t, `crew of ${view.run.run}`, "crew board (every Task of the run)")}
            />
          </div>
        </div>

        <div
          id="pane-verdict"
          className={"min-h-0 space-y-4 border-white/[0.06] p-4 lg:col-span-2 xl:col-span-1 xl:overflow-y-auto xl:border-l " + paneCls("verdict")}
        >
          <RootCauseCard
            view={view}
            onOpenEvidence={actions.openEvidence}
            onOpenNode={actions.openNode}
            whyAction={hasConfirmedCause(view) ? <WhyBelieveButton view={view} mode={source.mode} actions={actions} /> : null}
          />
          <HypothesesCard
            view={view}
            onOpenToolCall={actions.openToolCall}
            onOpenEvidence={actions.openEvidence}
            onOpenTemplate={(t, title, origin) => actions.openTemplate(t, title, origin)}
            mode={source.mode}
          />
          <GateChecklist
            runs={view.gate_runs}
            rejections={chains.rejected}
            onOpenCheck={actions.openCheck}
            onOpenEvidence={actions.openEvidence}
          />
          {!noIncident && !source.planUnavailable ? (
            <ObligationsCard view={view} mode={source.mode} onOpenEvidence={actions.openEvidence} />
          ) : null}
          {source.planUnavailable ? (
            <>
              <Unavailable id="containment" title="Containment" reason={source.planUnavailable} />
              <Unavailable id="whofixes" title="Who fixes it" reason={source.planUnavailable} />
              <Unavailable id="plan" title="Plan & approval" reason={source.planUnavailable} />
            </>
          ) : (
            <>
              <ContainmentCard plan={plan} error={source.planError} stage={stage} onOpenPlanItem={actions.openPlanItem} />
              <WhoFixesCard plan={plan} error={source.planError} stage={stage} onOpenPlanItem={actions.openPlanItem} />
              <PlanApprovalCard
                incidentId={view.incident.id}
                stage={stage}
                stages={view.stages}
                plan={plan}
                error={source.planError}
                onRefresh={source.onRefreshPlan ?? (() => {})}
                onApproved={source.onApproved ?? (() => {})}
                readOnly={source.mode === "replay"}
                remedy={view.report?.remedy ?? null}
                onOpenRemedy={remedyCall ? () => actions.openToolCall(remedyCall) : null}
                learnedQuery={
                  learnedCall ? { template: learnedCall.template, onOpen: () => actions.openToolCall(learnedCall) } : null
                }
              />
            </>
          )}

          <div className="pt-4">
            <h2 className="mb-1 px-1 text-xs font-medium tracking-wide text-[var(--fl-subtle)]">More context</h2>
            <p className="mb-3 px-1 text-xs text-[var(--fl-subtle)]">
              Advisory reads: each is a FalkorDB query; none of them changes the verdict.
            </p>
            <SectionFold>
              <div className="space-y-2">
                {showResidue ? <ResidueCard view={view} mode={source.mode} actions={actions} /> : null}
                <ContradictionsCard view={view} onOpenCheck={actions.openCheck} />
                {showAlerts ? <AlertCoverageCard view={view} mode={source.mode} actions={actions} /> : null}
                {showOwnership ? (
                  <OwnershipCard
                    view={view}
                    plan={source.planUnavailable ? null : plan}
                    planError={source.planUnavailable ? null : source.planError}
                    mode={source.mode}
                    actions={actions}
                  />
                ) : null}
                {source.planUnavailable ? (
                  <>
                    {showNotify ? <Unavailable id="notify" title="Notify (who to tell)" reason={source.planUnavailable} /> : null}
                    <Unavailable id="memory" title="Memory" reason={source.planUnavailable} />
                  </>
                ) : (
                  <>
                    {showNotify ? (
                      <NotifyCard
                        plan={plan}
                        error={source.planError}
                        stage={stage}
                        mode={source.mode}
                        onOpenPlanItem={actions.openPlanItem}
                        incidentId={source.mode === "live" ? view.incident.id : null}
                      />
                    ) : null}
                    {source.mode === "live" ? <AgentNotesCard focus={notesFocus} /> : null}
                    <MemoryCard
                      plan={plan}
                      error={source.planError}
                      stage={stage}
                      onOpenTemplate={actions.openTemplate}
                      incidentId={source.mode === "live" ? view.incident.id : null}
                    />
                  </>
                )}
                {source.mode === "live" ? (
                  <LearnedEdgesCard view={view} stage={stage} onChanged={source.onRefreshPlan ?? (() => {})} />
                ) : null}
                {absent.size ? (
                  <Section id="notrecorded" title="Not in this recording" aside={<StatusChip tone="na">older recording</StatusChip>}>
                    <p className="text-xs text-zinc-300">
                      This run was recorded before these sections existed, so they are not shown (nothing is filled in):{" "}
                      {[...absent].map((k) => NOT_RECORDED_TEXT[k]).join(", ")}. A live run shows them.
                    </p>
                  </Section>
                ) : null}
                <EvidenceTable report={view.report} onOpenEvidence={actions.openEvidence} />
              </div>
            </SectionFold>
          </div>
        </div>
      </div>
    </div>
    </FoldProvider>
    </OfflineTemplatesProvider>
  );
}

/** The graph's text alternatives (proof-path and blast-radius tables), one tab each under the graph. */
function TextAlternatives({
  model,
  blast,
  onOpenNode,
  emptyText,
}: {
  model: ReturnType<typeof buildGraphModel> | null;
  blast: BlastResponse | null;
  onOpenNode: (id: string) => void;
  emptyText?: string;
}) {
  const [tab, setTab] = useState<"chain" | "blast">("chain");
  const tabs = [
    ["chain", "Proof path"],
    ["blast", "Blast radius"],
  ] as const;
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = tab === "chain" ? "blast" : "chain";
    setTab(next);
    document.getElementById(`alt-tab-${next}`)?.focus();
  };
  return (
    <div className="fl-card rounded-2xl px-5 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <p className="text-xs text-[var(--fl-subtle)]">As a table</p>
        <div role="tablist" aria-label="Text alternatives of the graph" className="flex rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]">
          {tabs.map(([k, label]) => (
            <button
              key={k}
              id={`alt-tab-${k}`}
              type="button"
              role="tab"
              aria-selected={tab === k}
              aria-controls={`alt-panel-${k}`}
              tabIndex={tab === k ? 0 : -1}
              onKeyDown={onKey}
              onClick={() => setTab(k)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
                tab === k ? "bg-white/[0.1] text-zinc-50" : "text-zinc-400 hover:text-zinc-100",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <section id="alt-panel-chain" role="tabpanel" aria-labelledby="chain-h" hidden={tab !== "chain"}>
        <h2 id="chain-h" className="sr-only">
          Causal chains (text alternative of the graph)
        </h2>
        {model ? (
          <ChainTable chains={model.chains} onOpenNode={onOpenNode} emptyText={emptyText} />
        ) : (
          <p className="text-sm text-zinc-300">Waiting for the graph view…</p>
        )}
      </section>
      <section id="alt-panel-blast" role="tabpanel" aria-labelledby="blast-h" hidden={tab !== "blast"}>
        <h2 id="blast-h" className="sr-only">
          Blast radius (text alternative of ripple mode)
        </h2>
        {blast ? <BlastTable blast={blast} onOpenNode={onOpenNode} /> : <p className="text-sm text-zinc-300">Loading the blast radius…</p>}
      </section>
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  icon: Icon,
  text,
  disabledReason = null,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Route;
  text: string;
  disabledReason?: string | null;
}) {
  const disabled = !!disabledReason;
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      aria-disabled={disabled || undefined}
      title={disabledReason ?? undefined}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
        active
          ? "bg-white/[0.1] text-zinc-50"
          : "text-zinc-400 hover:text-zinc-100",
        disabled && "text-zinc-600 hover:text-zinc-600",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {text}
      {active ? <span className="sr-only">(selected)</span> : null}
    </button>
  );
}

function Unavailable({
  id,
  title,
  reason,
}: {
  id: string;
  title: string;
  reason: string;
}) {
  return (
    <Section
      id={id}
      title={title}
      aside={<StatusChip tone="na">not in this recording</StatusChip>}
    >
      <p className="text-sm text-zinc-300">{reason}</p>
    </Section>
  );
}

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-1">
      <dt className="text-zinc-400">{label}</dt>
      <dd className={mono ? "font-mono text-zinc-100" : "text-zinc-100"}>
        {value}
      </dd>
    </div>
  );
}
