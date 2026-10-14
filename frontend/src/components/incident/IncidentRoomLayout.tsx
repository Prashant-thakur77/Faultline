"use client";

import { useMemo, useState } from "react";
import { CircleHelp, Route, ShieldCheck, Waves } from "lucide-react";
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
import { cn } from "@/lib/utils";
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
import { Section } from "./Section";
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
 * missed it → containment → who fixes it → ownership at the change → notify → memory →
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
  const remedyCall = actions.toolCallOf("remedy_stats");
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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {source.top}
      <div className="border-b border-white/[0.06] bg-black/20 px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="flex w-full min-w-0 flex-col gap-1 text-zinc-50 xl:w-auto">
            <span className="font-mono text-xs tracking-wide text-zinc-400">{view.incident.id}</span>
            <span className="text-2xl font-[510] leading-tight tracking-[-0.025em] [overflow-wrap:anywhere] sm:text-[28px]">
              {view.incident.title.replaceAll("_", " ")}
            </span>
          </h1>
          <StatusChip tone={causeTone} title={m.meaning}>
            {m.text}
          </StatusChip>
          {fixVerdict ? (
            <span className="inline-flex items-center gap-1 text-xs text-zinc-400">
              fix <VerdictChip verdict={fixVerdict} />
            </span>
          ) : null}
          <span className="text-xs text-zinc-400">
            stage <span className="font-mono text-zinc-100">{stage}</span>
          </span>
          <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {meta.map((x) => (
              <Meta
                key={x.label}
                label={x.label}
                value={x.value}
                mono={x.mono}
              />
            ))}
          </dl>
          {abstain ? (
            <p
              role="status"
              className="flex w-full items-center gap-2 rounded-md border border-amber-400/70 bg-amber-500/10 px-2 py-1 text-sm text-amber-50"
            >
              <CircleHelp
                aria-hidden
                className="size-4 shrink-0 text-amber-300"
              />
              <span>
                <strong className="font-semibold">Abstained:</strong> no change
                explains this; inferred origin{" "}
                <span className="font-mono font-semibold">
                  {abstain.origin}
                </span>
                {abstain.chain ? (
                  <span className="font-mono text-amber-200">
                    {" "}
                    ({abstain.chain.join(" → ")})
                  </span>
                ) : null}{" "}
                <span className="text-amber-200">
                  (unconfirmed: no gate check proved it)
                </span>
              </span>
            </p>
          ) : view.run.outcome === "NO_INCIDENT" ? (
            <p
              role="status"
              className="flex w-full items-center gap-2 rounded-md border border-sky-400/60 bg-sky-500/10 px-2 py-1 text-sm text-sky-50"
            >
              <ShieldCheck
                aria-hidden
                className="size-4 shrink-0 text-sky-300"
              />
              <span>
                <strong className="font-semibold">No incident:</strong> negative
                proof accepted (N1 measurements in band, N2 no change reaches an
                anomalous node). Nothing to contain or fix.
              </span>
            </p>
          ) : null}
          {source.viewError ? (
            <span role="alert" className="text-xs text-red-300">
              Latest refresh failed: {source.viewError.text}
            </span>
          ) : null}
        </div>
      </div>

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
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(250px,300px)_minmax(0,1fr)] xl:grid-cols-[minmax(260px,310px)_minmax(0,1fr)_minmax(380px,460px)]">
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

        <div className={"min-h-0 space-y-3 p-3 lg:overflow-y-auto " + (pane === "graph" || pane === "crew" ? "" : "hidden lg:block")}>
          <div id="pane-graph" className={"space-y-3 " + paneCls("graph")}>
            <section
              aria-labelledby="graph-h"
              className="fl-card rounded-2xl overflow-hidden"
            >
              <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-3 py-2">
                <h2 id="graph-h" className="text-sm font-semibold text-zinc-50">
                  Failure-flow graph
                </h2>
                <span className="text-xs text-zinc-400">
                  {graph
                    ? `${graph.nodes.length} nodes · ${graph.edges.length} PROPAGATES_TO edges · ${graph.graph}`
                    : ""}
                </span>
                <div
                  role="group"
                  aria-label="Graph view mode"
                  className="ml-auto flex overflow-hidden rounded-md border border-zinc-700"
                >
                  <ModeButton
                    active={effectiveMode === "path"}
                    onClick={() => setMode("path")}
                    icon={Route}
                    text="Path"
                  />
                  <ModeButton
                    active={effectiveMode === "ripple"}
                    onClick={() => setMode("ripple")}
                    icon={Waves}
                    text="Ripple"
                    disabledReason={ripple ? null : rippleReason}
                  />
                </div>
                <span className="w-full text-[11px] text-zinc-400 2xl:w-auto">
                  {source.graphNote ? `${source.graphNote} · ` : ""}
                  {effectiveMode === "ripple"
                    ? "Ripple: cause red, blast radius yellow (algo.BFS), rest dimmed"
                    : "Path: proof path lit edge by edge"}
                  {" · "}Tab to highlighted nodes, Enter opens the Cypher panel
                  {mode === "ripple" && !ripple && rippleReason
                    ? ` · Ripple unavailable: ${rippleReason}`
                    : ""}
                </span>
              </div>
              <div className="h-[clamp(360px,58vh,640px)]">
                {graphError ? (
                  <div
                    role="alert"
                    className="m-3 rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100"
                  >
                    Graph view unavailable: {graphError}
                  </div>
                ) : !graph || !model ? (
                  <p className="p-3 text-sm text-zinc-300">
                    Loading the failure-flow graph…
                  </p>
                ) : model.nodes.length === 0 ? (
                  <p className="p-3 text-sm text-zinc-300">
                    The incident graph has no PROPAGATES_TO edges, so there is
                    nothing to draw.
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
              <div className="border-t border-zinc-800 px-3 py-2">
                <GraphLegend
                  mode={effectiveMode}
                  hasCut={cut.length > 0}
                  topBetweenness={topB}
                  rippleText={
                    abstain
                      ? {
                          cause: [
                            "INFERRED",
                            "inferred upstream origin, NOT confirmed (red, dashed in the text)",
                          ],
                          blast: [
                            "BLAST",
                            "in the blast radius (yellow, with BFS hops from the symptom; algo.BFS, Q-BLAST-1)",
                          ],
                        }
                      : null
                  }
                />
              </div>
            </section>

            <section
              aria-labelledby="chain-h"
              className="fl-card rounded-2xl p-4"
            >
              <h2
                id="chain-h"
                className="mb-2 text-sm font-semibold text-zinc-50"
              >
                Causal chains (text alternative of the graph)
              </h2>
              {model ? (
                <ChainTable
                  chains={model.chains}
                  onOpenNode={actions.openNode}
                  emptyText={
                    view.run.outcome === "NO_INCIDENT"
                      ? "None: the negative proof was accepted, so no change has a causal chain to the symptom."
                      : abstain
                        ? `None proven: no change has a causal path to the symptom. The inferred origin ${abstain.origin} is not a proven chain.`
                        : undefined
                  }
                />
              ) : (
                <p className="text-sm text-zinc-300">
                  Waiting for the graph view…
                </p>
              )}
            </section>

            {blast ? (
              <section
                aria-labelledby="blast-h"
                className="fl-card rounded-2xl p-4"
              >
                <h2
                  id="blast-h"
                  className="mb-2 text-sm font-semibold text-zinc-50"
                >
                  Blast radius (text alternative of ripple mode)
                </h2>
                <BlastTable blast={blast} onOpenNode={actions.openNode} />
              </section>
            ) : null}
          </div>

          <div id="pane-crew" className={paneCls("crew")}>
            <CrewBoard
              crew={view.crew}
              gateRuns={view.gate_runs}
              onOpenCall={openCrewCall}
              onOpenCheck={actions.openCheck}
              onOpenQuery={(t) =>
                actions.openTemplate(t, `crew of ${view.run.run}`, "crew board (every Task of the run)")
              }
            />
          </div>
        </div>

        <div id="pane-verdict" className={"min-h-0 space-y-3 border-white/[0.06] p-3 lg:col-span-2 xl:col-span-1 xl:overflow-y-auto xl:border-l " + paneCls("verdict")}>
          <HypothesesCard
            view={view}
            onOpenToolCall={actions.openToolCall}
            onOpenEvidence={actions.openEvidence}
            mode={source.mode}
          />
          <GateChecklist
            runs={view.gate_runs}
            rejections={chains.rejected}
            onOpenCheck={actions.openCheck}
            onOpenEvidence={actions.openEvidence}
          />
          <RootCauseCard
            view={view}
            onOpenEvidence={actions.openEvidence}
            onOpenNode={actions.openNode}
            whyAction={
              hasConfirmedCause(view) ? <WhyBelieveButton view={view} mode={source.mode} actions={actions} /> : null
            }
          />
          {showResidue ? (
            <ResidueCard view={view} mode={source.mode} actions={actions} />
          ) : null}
          <ContradictionsCard view={view} onOpenCheck={actions.openCheck} />
          {source.mode === "live" ? (
            <LearnedEdgesCard
              view={view}
              stage={stage}
              onChanged={source.onRefreshPlan ?? (() => {})}
            />
          ) : null}
          {showAlerts ? (
            <AlertCoverageCard
              view={view}
              mode={source.mode}
              actions={actions}
            />
          ) : null}
          {absent.size ? (
            <Section
              id="notrecorded"
              title="Not in this recording"
              aside={<StatusChip tone="na">older recording</StatusChip>}
            >
              <p className="text-xs text-zinc-300">
                This run was recorded before these sections existed, so they are
                not shown (nothing is filled in):{" "}
                {[...absent].map((k) => NOT_RECORDED_TEXT[k]).join(", ")}. A
                live run shows them.
              </p>
            </Section>
          ) : null}
          {source.planUnavailable ? (
            <>
              <Unavailable
                id="containment"
                title="Containment"
                reason={source.planUnavailable}
              />
              <Unavailable
                id="whofixes"
                title="Who fixes it"
                reason={source.planUnavailable}
              />
              {showOwnership ? (
                <OwnershipCard
                  view={view}
                  plan={null}
                  planError={null}
                  mode={source.mode}
                  actions={actions}
                />
              ) : null}
              {showNotify ? (
                <Unavailable
                  id="notify"
                  title="Notify (who to tell)"
                  reason={source.planUnavailable}
                />
              ) : null}
              <Unavailable
                id="memory"
                title="Memory"
                reason={source.planUnavailable}
              />
              <Unavailable
                id="plan"
                title="Plan & approval"
                reason={source.planUnavailable}
              />
            </>
          ) : (
            <>
              <ContainmentCard
                plan={plan}
                error={source.planError}
                stage={stage}
                onOpenPlanItem={actions.openPlanItem}
              />
              <WhoFixesCard
                plan={plan}
                error={source.planError}
                stage={stage}
                onOpenPlanItem={actions.openPlanItem}
              />
              {!noIncident ? (
                <ObligationsCard
                  view={view}
                  mode={source.mode}
                  onOpenEvidence={actions.openEvidence}
                />
              ) : null}
              {showOwnership ? (
                <OwnershipCard
                  view={view}
                  plan={plan}
                  planError={source.planError}
                  mode={source.mode}
                  actions={actions}
                />
              ) : null}
              {showNotify ? (
                <NotifyCard
                  plan={plan}
                  error={source.planError}
                  stage={stage}
                  mode={source.mode}
                  onOpenPlanItem={actions.openPlanItem}
                />
              ) : null}
              <MemoryCard
                plan={plan}
                error={source.planError}
                stage={stage}
                onOpenTemplate={actions.openTemplate}
                incidentId={source.mode === "live" ? view.incident.id : null}
              />
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
                onOpenRemedy={
                  remedyCall ? () => actions.openToolCall(remedyCall) : null
                }
              />
            </>
          )}
          <EvidenceTable
            report={view.report}
            onOpenEvidence={actions.openEvidence}
          />
        </div>
      </div>
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
        "inline-flex items-center gap-1 px-2 py-1 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-inset",
        active
          ? "bg-sky-500/20 text-sky-100"
          : "text-zinc-300 hover:bg-zinc-800",
        disabled && "text-zinc-500 hover:bg-transparent",
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
