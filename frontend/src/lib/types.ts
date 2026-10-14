/**
 * Types for the Faultline API v2. They mirror docs/API.md exactly (the contract is
 * authoritative; backend/faultline/api.py implements it). Every value the UI shows
 * comes from these responses: nothing is synthesised client-side.
 */

export type Tenant = string;

/** Epoch milliseconds as written by the backend into the graph. */
export type EpochMs = number;

// ------------------------------------------------------------------ /api/status

export interface EngineMeta {
  engine: string;
  digest: string;
}

export interface Readiness {
  ready: boolean;
  data_hash: string;
  seeded_at: EpochMs;
  engine: string;
}

export interface StatusResponse {
  status: "ok" | "unavailable";
  reason?: string;
  engine: EngineMeta;
  tenant: Tenant;
  graph: string;
  acl: "ro_user" | "default_user";
  graph_disabled: boolean;
  models: { orchestrator: string; specialists: string };
  llm_configured: boolean;
  /** Live-LLM spend in the last hour (audit graph); replay_only once over the hourly limit (§11.3). Absent on older backends. */
  llm_budget?: {
    usd_last_hour: number;
    runs_last_hour?: number;
    usd_per_hour_limit: number;
    replay_only: boolean;
  };
  templates: number;
  /** Pinned UDF libraries (GRAPH.UDF LIST): "missing" also covers a library loaded at a different sha. Absent when unavailable. */
  udf?: Record<string, "loaded" | "missing">;
  /** Absent when status is "unavailable". */
  ready?: Readiness;
  /** Absent when status is "unavailable". */
  counts?: { nodes: number; edges: number };
}

// ------------------------------------------------------------------ scenarios and runs

export interface Scenario {
  id: string;
  name: string;
  tenant: Tenant;
  report: string;
}

export type LlmMode = "baseline" | "anthropic";

export interface RunScenarioResponse {
  job: string;
  state: "running" | "done" | "failed";
  scenario: string;
  /** The tenant the scenario runs on (the job is bound to it: GET /api/jobs/{job}?tenant=…). */
  tenant?: string;
  incident?: string;
  run?: string;
  graph?: string;
  outcome?: Outcome;
  error?: string;
  started_at?: number;
  /**
   * Capability for choose/approve on this job's runs (public demo). Only its hash is stored in the graph;
   * the UI keeps it in sessionStorage keyed by job (and by each incident it learns of) and sends it as
   * X-Faultline-Run-Token.
   */
  run_token?: string;
  /**
   * Present when INTAKE split the scenario's alerts into several incidents (alert storm + concurrent fault): every
   * incident the job opened, each with its own run; the same run token is valid for all of them.
   */
  incidents?: RunScenarioIncident[];
}

/** GET /api/jobs/{job}: a run job's incidents (also those opened after the run response). */
export interface JobStatusResponse extends RunScenarioResponse {
  /** True when the caller presented this job's own run token (only then is `run_token` echoed back). */
  token_valid: boolean;
}

export interface RunScenarioIncident {
  incident: string;
  run: string;
  symptoms: string[];
  intake_round: number;
  outcome?: Outcome | "RUNNING";
}

export type Outcome =
  | "CONFIRMED"
  | "NOT_CONFIDENT"
  | "NO_INCIDENT"
  | "UNKNOWN_ESCALATED"
  | "FAILED"
  | "RUNNING";

export interface IncidentListItem {
  run: string;
  incident: string;
  graph: string;
  scenario: string;
  investigator: string;
  outcome: Outcome | null;
  cause: string | null;
  started_at: EpochMs;
  updated_at: EpochMs;
}

// ------------------------------------------------------------------ IncidentView

export interface IncidentInfo {
  id: string;
  title: string;
  stage: string;
  onset_at: EpochMs;
  opened_at: EpochMs;
  confident: boolean;
  targets: string[];
  kinds: string[];
}

export interface RunInfo {
  run: string;
  graph: string;
  scenario: string;
  outcome: Outcome | null;
  cause: string | null;
  investigator: string;
}

export interface StageRow {
  id: string;
  stage: string;
  ord: number;
  at: EpochMs;
  note: string;
}

export interface ToolCallRow {
  id: string;
  tool: string;
  template: string | null;
  ms: number;
  rows: number;
  at: EpochMs;
  evidence_id: string | null;
  kind: string | null;
  summary: string | null;
  /** Params the tool ran its template with (recorded on the ToolCall node). */
  params?: Record<string, unknown> | null;
  digest?: string | null;
}

export type HypothesisStatus =
  "open" | "eliminated" | "confirmed" | "unresolved";
export type HypothesisOrigin = "code" | "sweep" | "investigator" | "gate";

export interface Hypothesis {
  id: string;
  cause: string;
  status: HypothesisStatus;
  score: number | null;
  reason: string | null;
  origin: HypothesisOrigin;
  supports: string[];
  refutes: string[];
}

/** Check names are listed in docs/API.md (G1 grounded … G8 contradiction, N1/N2). */
export interface GateCheck {
  name: string;
  /** true = pass, false = fail (or downgrade when downgrade_only), null = not applicable. */
  passed: boolean | null;
  detail: string;
  template: string | null;
  params: Record<string, unknown> | null;
  evidence_ids: string[];
  downgrade_only: boolean;
}

export type GateOrigin = "sweep" | "confirm" | "no_incident";

export interface GateRun {
  id: string;
  cause: string;
  passed: boolean;
  confident: boolean;
  origin: GateOrigin;
  attempt: number;
  at: EpochMs;
  checks: GateCheck[];
}

export interface ProvenClaim {
  claim: string;
  evidence_ids: string[];
  check: string;
}

export interface InferredClaim {
  claim: string;
  basis: string;
}

export interface Rejection {
  cause: string;
  origin: GateOrigin;
  gate_run: string;
  failed: string[];
}

export interface Evidence {
  id: string;
  kind: string;
  source: string;
  tool: string;
  template: string | null;
  cypher: string | null;
  summary: string;
  digest: string | null;
  value: number | null;
  baseline: number | null;
  anomalous: boolean | null;
  about: string[];
}

/** One hop of the proven causal chain and whether an alert fired on it (Q-CHAIN-MON). */
export interface AlertHop {
  hop: number;
  id: string;
  label: string | null;
  alerted: boolean;
  /** Seconds from onset to the hop's first alert; null when it was silent. */
  first_alert_lag_s: number | null;
  has_telemetry: boolean;
}

/** "Why alerts missed it": alert coverage along the G2 chain. Empty object when there is no proven chain. */
export interface AlertCoverage {
  summary?: string;
  hops?: AlertHop[];
}

/** Who owned the changed component when the cause shipped vs now (Q-OWN-AT). Empty object when not applicable. */
export interface OwnershipAtChange {
  component?: string;
  at?: EpochMs;
  owner_then?: string | null;
  owner_now?: string | null;
  changed_hands?: boolean;
  summary?: string;
}

/** Advisory residue check (Q-RESIDUE-1): the confirmed cause explains k of n anomalous components. */
export interface Residue {
  advisory?: boolean;
  verdict?: string;
  k?: number;
  n?: number;
  explained?: string[];
  unexplained?: string[];
  summary?: string;
  evidence_id?: string | null;
  error?: string;
}

/** Learned remediation ordering (Q-REM-1): history line per offered fix; it only reorders. */
export interface RemedySummary {
  applied?: boolean;
  moved?: boolean;
  lines?: string[];
  note?: string;
  evidence_id?: string | null;
}

export interface Report {
  incident_id: string;
  outcome: Outcome;
  confident: boolean;
  cause_id: string | null;
  mechanism: string[];
  proven: ProvenClaim[];
  inferred: InferredClaim[];
  /** Active decisions the cause violates (G8 detail lines); absent on older exports. */
  contradictions?: string[];
  /** M12 fields: absent on older backends and on recordings made before them. */
  why_alerts_missed_it?: AlertCoverage;
  ownership?: OwnershipAtChange;
  residue?: Residue;
  remedy?: RemedySummary;
  /** Obligation clock (ROUTE): SLO burn, time to breach, customers reached; decides urgency, never the cause. */
  obligations?: Obligations | Record<string, never>;
  rejected: Rejection[];
  evidence: Evidence[];
}

// ------------------------------------------------------------------ crew (M17, Q-CREW-1)

/** One least-privilege role of the incident crew (backend `crew.roster()`). */
export interface CrewMember {
  key: string;
  id: string;
  name: string;
  /** One-line job description. */
  job: string;
  stages: string[];
  /** The only tools this role may call. */
  tools: string[];
  /** What it may write ("none (read-only)" when nothing). */
  writes: string;
  /** "none" = deterministic code; "optional" = a model may drive it (the lead). */
  model: "none" | "optional" | (string & {});
}

/** A graph call a step MADE (a ToolCall node). */
export interface CrewCall {
  id: string;
  tool: string;
  template: string | null;
  ms: number | null;
  rows: number | null;
  at: EpochMs | null;
}

/** A Task node of the run: a crew step or a specialist work item the lead dispatched. */
export interface CrewStep {
  task: string;
  kind: "crew" | "specialist" | (string & {});
  /** Roster key for crew steps; topology / telemetry / data / change / code for specialists. */
  role: string;
  stage: string | null;
  agent: string | null;
  /** Task lifecycle: done / failed / running / claimed / open. */
  state: string | null;
  /** Contract outcome: done for crew steps; complete / insufficient for specialists. */
  status: string | null;
  claimed_at: EpochMs | null;
  done_at: EpochMs | null;
  summary: string | null;
  /** Task ids this one follows ((:Task)-[:NEXT]->(this)). */
  after: string[];
  /** Ids the step NAMES (a specialist's suspects). */
  names: string[];
  /** Number of evidence items it CITES. */
  cites: number;
  calls: CrewCall[];
  unknowns: string[] | null;
  limits: string[] | null;
  /** Times its lease expired and it was reclaimed. */
  reaps: number;
}

export interface Crew {
  roster: CrewMember[];
  steps: CrewStep[];
  /** The template the steps were read with (Q-CREW-1). */
  template: string;
}

export interface IncidentView {
  incident: IncidentInfo;
  run: RunInfo;
  stages: StageRow[];
  tool_calls: ToolCallRow[];
  hypotheses: Hypothesis[];
  gate_runs: GateRun[];
  /** The run's crew (Q-CREW-1); absent on older backends and recordings. */
  crew?: Crew;
  /** Present once the run has an outcome. */
  report?: Report;
}

// ------------------------------------------------------------------ provenance ("why do you believe this?", Q-PROV-1)

export type ProvenanceKind = "verdict" | "evidence" | "call" | "agent" | "seen";
export type ProvenanceRel = "SUPPORTS" | "PRODUCED_EVIDENCE" | "MADE" | "SAW";

/** One node of GET /api/incidents/{inc}/provenance. Extra fields depend on `kind`. */
export interface ProvenanceNode {
  id: string;
  kind: ProvenanceKind | (string & {});
  label: string;
  /** verdict: the change the confirmed hypothesis BLAMES. */
  blames?: string;
  /** evidence / call: the template it ran (null for a non-graph tool; may be combined, `Q-A+Q-B`). */
  template?: string | null;
  /** evidence: the recorded summary. */
  summary?: string | null;
  /** call: engine ms recorded on the ToolCall. */
  ms?: number | null;
  /** agent: the Task that MADE the call (null for the gate's own reads). */
  task?: string | null;
  /** agent: specialist / crew / gate. */
  task_kind?: string | null;
}

export interface ProvenanceEdge {
  source: string;
  target: string;
  rel: ProvenanceRel | (string & {});
}

export interface ProvenanceResponse {
  incident: string;
  /** Always Q-PROV-1: the template every edge below was read with. */
  template: string;
  cypher: string;
  params: Record<string, unknown>;
  nodes: ProvenanceNode[];
  edges: ProvenanceEdge[];
}

// ------------------------------------------------------------------ SSE

export type StreamEvent =
  | { type: "stage"; data: StageRow }
  | { type: "tool_call"; data: ToolCallRow }
  | { type: "gate_run"; data: GateRun }
  | { type: "done"; data: { stage: string } };

// ------------------------------------------------------------------ graph view

export interface GraphNode {
  id: string;
  label: string;
  tier: number | null;
  /** Betweenness centrality from FalkorDB (Q-CHOKE-ALL); null when not computed for the node. */
  betweenness?: number | null;
}

export type EdgeDomain = "service" | "data" | "cross";

export interface GraphEdge {
  source: string;
  target: string;
  cap: number | null;
  domain: EdgeDomain | string;
}

export interface GraphResponse {
  graph: string;
  /** The node the view was scoped to (`?focus=`), or null for the unscoped view. */
  focus?: string | null;
  /** True when the view hit the template LIMIT: the graph shown is NOT the whole graph. */
  truncated?: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ------------------------------------------------------------------ Cypher panel

export interface TemplateInfo {
  id: string;
  purpose: string;
  cypher: string;
  file: string;
  limit: number;
}

export interface TemplateRequest {
  params: Record<string, unknown>;
  incident?: string;
  tenant: Tenant;
}

/** POST /api/templates/{tid}/profile: GRAPH.PROFILE on the incident's graph. */
export interface ProfileResponse {
  id: string;
  /** Operator tree, one line per operator, as GRAPH.PROFILE printed it. */
  plan: string[];
  /** Total engine time in ms (from the profile). */
  engine_ms: number | null;
  /** Graph the profile ran on. */
  graph: string;
}

export interface TemplateRunResponse {
  rows: Record<string, unknown>[];
  ms: number;
  digest: string;
  truncated: boolean;
  served_by: string;
  cypher: string;
}

// ------------------------------------------------------------------ action path (two-step approval)

export interface BlastRow {
  id: string;
  label: string;
  tier: number | null;
  revenue: boolean;
  hops: number;
  max_cap: number | null;
  impact: number;
}

export interface BlastResponse {
  graph: string;
  blast: Record<string, { rows: BlastRow[]; template: string; via: string }>;
}

/** A recorded plan-stage tool result: {id, evidence_id, summary, template, params, payload, at}. */
export interface PlanItem<P> {
  id: string;
  evidence_id: string | null;
  summary: string | null;
  template: string | null;
  params: Record<string, unknown> | null;
  payload: P | null;
  at: EpochMs;
}

export interface CutRow {
  u: string;
  v: string;
  cut_cost: number;
  domain: string;
}
export interface CutPayload {
  rows: CutRow[];
  max_flow: number | null;
  source_side?: string[];
}

export interface WhatIfRow {
  removed_edges: number;
  reach_before: string[];
  reach_after: string[];
  no_longer_reached: string[];
  protected_still_reached: string[];
  still_connected: Record<string, boolean>;
}
export interface WhatIfPayload {
  rows: WhatIfRow[];
  verdict: string;
  branch?: string;
}

export interface WhoFixesRow {
  person: string;
  name: string | null;
  score: number;
  teams: string[];
  reasons: string[];
}
export interface WhoFixesPayload {
  rows: WhoFixesRow[];
}

export interface BusFactorPayload {
  bus_factor: number | null;
  top_contributor_inactive: boolean | null;
  rows?: { person: string; n: number; active: boolean; last_at: EpochMs }[];
  total_commits?: number;
}

/** Who to NOTIFY (Q-NOTIFY-1): teams owning something in the blast radius; not who fixes it. */
export interface NotifyRow {
  team: string;
  name: string | null;
  owns_impacted: string[];
  oncall: string[];
  impact: number | null;
  nearest_hops: number | null;
}
export interface NotifyPayload {
  rows: NotifyRow[];
}

/** People from the then-owning team who worked on the component (Q-OWN-PEOPLE). */
export interface KnewItThenRow {
  person: string;
  name: string | null;
  active: boolean | null;
  commits: number | null;
  last_at: EpochMs | null;
  other_teams: string[];
}
export interface OwnerAtPayload {
  rows: {
    team: string;
    name: string | null;
    since: EpochMs | null;
    until: EpochMs | null;
    covers_at: boolean;
    current: boolean;
  }[];
  owner_then: string | null;
  owner_now: string | null;
  changed_hands: boolean;
  knew_it_then: KnewItThenRow[];
  at: EpochMs;
}

export interface EscalationPayload {
  rows: { from: string; to: string; w: number }[];
  managers?: { manager: string; person: string }[];
  people?: string[];
}

export type Verdict = "APPLIED" | "NOT_APPLIED" | "UNKNOWN";
export type OptionStatus =
  "option" | "chosen" | "approved" | "executed" | "failed" | "rejected";

/**
 * One telemetry target checked by verification: a symptom (after vs baseline × band), a
 * protected node checked for collateral damage (after vs the max before the action), or a
 * protected node with no usable signal (ok null + note).
 */
export interface TelemetryTarget {
  ok: boolean | null;
  collateral?: boolean;
  after?: number[];
  baseline?: number | null;
  band?: number | null;
  before_action_max?: number | null;
  note?: string;
}

export interface TelemetryChannel {
  ok: boolean | null;
  /** Current shape: one entry per checked node. */
  targets?: Record<string, TelemetryTarget>;
  /** Older single-target shape (still rendered when present). */
  after?: number[];
  baseline?: number | null;
  band?: number | null;
}

export interface VerifyChannels {
  github_main?: {
    ok: boolean | null;
    served_by?: string;
    detail?: string;
  } | null;
  telemetry?: TelemetryChannel | null;
  [k: string]: unknown;
}

export interface ExactAction {
  kind: string;
  incident: string;
  args: Record<string, unknown>;
  branch: string;
  idem: string;
  file?: string | null;
  before?: string | null;
  after?: string | null;
  commit?: string | null;
  rollback?: string | null;
  title?: string | null;
  body?: string | null;
  /** PR description the server will open (includes the reviewers). */
  pr_body?: string | null;
  plan_hash: string;
}

export interface OptionFuture {
  key: string;
  predicted: "contains" | "does_not_contain" | "unknown";
  line: string;
  /** Protected nodes the origin can still reach with a residual worth naming. */
  exposed: string[];
  evidence_id?: string | null;
}

export interface ActionOption {
  id: string;
  kind: string;
  option: string;
  enabled: boolean;
  reason: string | null;
  target: string | null;
  status: OptionStatus;
  preview: Record<string, unknown> | null;
  /** The exact action once chosen (same shape as the /choose response). */
  spec: ExactAction | null;
  plan_hash: string | null;
  idem: string | null;
  external_ref: string | null;
  verdict: Verdict | null;
  explanation: string | null;
  channels: VerifyChannels | null;
  approval_id: string | null;
  /** Set when a human rejected this exact action (POST /reject): who, why and when (absent on older backends). */
  rejected_by?: string | null;
  reject_reason?: string | null;
  rejected_at?: EpochMs | null;
  /** Futures (M14 #1): this option's predicted outcome from its own GRAPH.COPY branch (Q-FUTURE-1). An object when
   * options come straight from the agent; JSON text when read back from the graph (/plan). Absent: not simulated. */
  future?: OptionFuture | string | null;
  /** Learned ordering (present when options come straight from the agent; /plan carries it in `reason`). */
  static_rank?: number | null;
  history?: {
    successes: number;
    failures: number;
    n: number;
    rate: number;
    target: string;
    line: string;
  } | null;
}

export interface RecalledIncident {
  id: string;
  title: string | null;
  similarity: number | null;
  recency: number | null;
  salience: number | null;
  shared: string[];
  actions: { kind: string; verdict: Verdict | null; target: string | null }[];
  cause_targets: string[];
}

export interface FixHistoryRow {
  kind: string;
  verdict: Verdict | null;
  n: number;
  incidents: string[];
}

/** What RECALL found (Q-MEM-4) and how each fix kind fared on those precedents (Q-MEM-5). */
export interface PlanMemory {
  recalled: RecalledIncident[];
  fix_history: FixHistoryRow[];
}

export interface PlanResponse {
  stage: string;
  /** Absent on backends older than the memory fields. */
  memory?: PlanMemory | null;
  containment_cut: PlanItem<CutPayload> | null;
  whatif: PlanItem<WhatIfPayload> | null;
  who_fixes: PlanItem<WhoFixesPayload> | null;
  bus_factor: PlanItem<BusFactorPayload> | null;
  escalation_tree: PlanItem<EscalationPayload> | null;
  /** Absent (undefined) on backends and recordings older than M12; null until ROUTE recorded it. */
  notify_set?: PlanItem<NotifyPayload> | null;
  owner_at?: PlanItem<OwnerAtPayload> | null;
  options: ActionOption[];
}

export interface ApproveResponse {
  approved: true;
  state: string;
  mine: boolean;
  idem: string;
  approval_id: string;
  /** The approver as checked in the tenant graph (an active Person); 422 otherwise. */
  approver?: {
    id: string;
    name: string | null;
    owner_team: string | null;
    committed: boolean | number | null;
  };
}

export interface RearmResponse {
  src: string;
  dst: string;
  ms: number;
  indexes: number;
  schema_reapplied?: { created: number; existing: number };
}

// ------------------------------------------------------------------ company brain

export type BrainIntent =
  | "people"
  | "decision"
  | "gaps"
  | "blast"
  | "context"
  | "knowledge"
  | "owner_then"
  | "asof"
  | "history"
  | "llm";

export interface BrainStep {
  tool: string;
  args: Record<string, unknown>;
  /** Template id; "T2C" for a guarded text2cypher query (tier 3). */
  template: string | null;
  cypher: string | null;
  rows: number | null;
  evidence_id: string | null;
  via: string | null;
  ms: number | null;
  error: string | null;
  /** The exact template params the step ran with. */
  params?: Record<string, unknown> | null;
}

export interface BrainAnswer {
  question: string;
  tenant: string;
  run_id: string;
  intent: BrainIntent | string;
  tier: 1 | 2 | 3;
  /** Markdown; node ids cited as [id]. */
  answer: string;
  citations: string[];
  steps: BrainStep[];
  sources: string[];
  guard: { ok: boolean; cited: string[]; unseen: string[]; reason: string };
  answered_by: string;
  ms: number;
}

/** GET /api/brain/subgraph (Q-BRAIN-SUB): how an answer's cited ids connect, through paths of at most 2 hops. */
export interface BrainSubgraphNode {
  id: string;
  /** The node's domain label (Decision, Person, Service…); null when the node carries none. */
  label: string | null;
  name: string | null;
  /** True for an id the answer cited; false for a node that only connects them. */
  cited: boolean;
}

export interface BrainSubgraphEdge {
  rel: string;
  source: string;
  target: string;
}

export interface BrainSubgraph {
  template: string;
  cypher: string;
  params: Record<string, unknown>;
  /** True when the query hit its LIMIT: some connecting paths are not in the payload. */
  truncated: boolean;
  nodes: BrainSubgraphNode[];
  edges: BrainSubgraphEdge[];
}

// ------------------------------------------------------------------ preflight (pre-deploy gate)

export interface PreflightFile {
  path: string;
  before: string;
  after: string;
}

export interface PreflightRequest {
  repo: string;
  number: number;
  title: string;
  author: string;
  head_sha: string;
  files: PreflightFile[];
}

export type PreflightVerdict = "allow" | "require_review" | "block";

export interface PreflightTerm {
  value: number;
  weighted: number;
  why: string;
}

export interface PreflightDecision {
  decision: string;
  title: string | null;
  rule_key: string | null;
  op: string | null;
  expected: unknown;
  actual: unknown;
  url: string | null;
  about: string | null;
  violated: boolean;
}

/**
 * The PR puts back a value the organisation decided once and later reversed (advisory: it never changes
 * the verdict or the risk). `head` is the decision in force; `because` the evidence for the reversal.
 */
export interface PreflightReversal {
  reversed: string;
  reversed_title: string | null;
  rule_key: string | null;
  actual: unknown;
  about: string | null;
  head: string;
  head_title: string | null;
  /** Epoch ms the head decision was taken (null when unrecorded). */
  head_decided_at: EpochMs | null;
  head_url: string | null;
  because: { id: string; title: string | null }[];
}

export interface PreflightResponse {
  pr: string;
  run_id: string;
  verdict: PreflightVerdict;
  risk: number;
  thresholds: { require_review: number; block: number };
  terms: Record<string, PreflightTerm>;
  would_change_if: { term: string; verdict: PreflightVerdict; if: string }[];
  reviewers: string[];
  decision_links: { id: string; title: string | null; url: string | null }[];
  /** Reversed decisions the PR reinstates (advisory; absent on older backends). */
  reversals?: PreflightReversal[];
  assessment: {
    changed: string[];
    impacted: string[];
    revenue_tier1: string[];
    decisions: PreflightDecision[];
    past_incidents: Record<string, string[]>;
    bus_factor: Record<string, number>;
    gaps: unknown[];
    reviewers: string[];
  };
  facts: {
    key: string;
    value: unknown;
    about: string | null;
    file: string | null;
  }[];
  notes: string[];
  unknown_files: string[];
  evidence: {
    evidence_id: string;
    template: string;
    cypher: string;
    served_by: string;
    digest: string;
    ms: number;
    /** Exact template params (newer backends). */
    params?: Record<string, unknown> | null;
  };
  /** Markdown PR comment; null when the verdict is allow. */
  comment: string | null;
  ms: number;
  /** false on the public demo: assessed on a clean-room copy and not recorded (no deep link). */
  recorded?: boolean;
}

/**
 * GET /api/preflight?pr=…: the latest recorded preflight for a PR. As served it carries the
 * verdict fields plus the evidence's Cypher/params and the assessment as `rows[0]`; it does not
 * carry facts, notes, unknown files, the comment or the evidence template (see the UI's notes).
 */
export interface RecordedPreflight {
  pr: string;
  run_id: string;
  evidence_id?: string;
  at?: EpochMs;
  cypher?: string;
  params?: Record<string, unknown> | null;
  verdict: PreflightVerdict;
  risk: number;
  thresholds: PreflightResponse["thresholds"];
  terms: PreflightResponse["terms"];
  would_change_if?: PreflightResponse["would_change_if"];
  reviewers?: string[];
  decision_links?: PreflightResponse["decision_links"];
  reversals?: PreflightReversal[];
  rows?: Partial<PreflightResponse["assessment"]>[];
  // Present if the backend starts returning the full POST shape.
  assessment?: PreflightResponse["assessment"];
  facts?: PreflightResponse["facts"];
  notes?: string[];
  unknown_files?: string[];
  evidence?: PreflightResponse["evidence"];
  comment?: string | null;
  ms?: number;
}

// ------------------------------------------------------------------ memory: forget with a receipt

export interface ForgetDryRun {
  dry_run: true;
  doc: {
    id: string;
    title: string | null;
    kind: string | null;
    url: string | null;
    produced: string[];
  };
  owned: { id: string; label: string; rels: number; has_vector: boolean }[];
  nodes: number;
  relationships: number;
  vectors: number;
  kept: string[];
  /** Receipt token: binds the approval to exactly this set (409 if the graph changed since). */
  token: string;
}

export interface ForgetReceipt {
  dry_run: false;
  /** true on the public demo: executed on a clean-room copy; the live graph is unchanged. */
  clean_room?: boolean;
  tenant: string;
  graph: string | null;
  doc: string;
  approver: string;
  token: string;
  nodes: number;
  relationships: number;
  vectors: number;
  vectors_still_found: number;
  forgotten_ids: string[];
  kept_ids: string[];
  proof: { vector_requery: string };
  /** The same question asked before and after (M17): the answers, and the ids the answer no longer cites. */
  flip?: ForgetFlip;
}

export interface ForgetFlipAnswer {
  answer: string;
  citations: string[];
  intent: string;
}

export interface ForgetFlip {
  question: string;
  before?: ForgetFlipAnswer;
  after?: ForgetFlipAnswer;
  no_longer_cited?: string[];
  answer_changed?: boolean;
  error?: string;
}

// ------------------------------------------------------------------ brain session history (T2)

export interface BrainHistoryTurn {
  session: string;
  seq: number;
  role: string;
  text: string;
  at: EpochMs | null;
  refs: string[] | string | null;
}

export interface BrainHistory {
  user: string;
  turns: BrainHistoryTurn[];
}

// ------------------------------------------------------------------ M13: reject, contrast, memory tab, brain widgets

/** POST /api/incidents/{inc}/reject */
export interface RejectResponse {
  rejected: true;
  action_id: string;
  status: "rejected";
  rejected_at: EpochMs;
  stage: string;
  reason: string;
  approver: { id: string; name?: string | null; [k: string]: unknown };
}

/** A template result as the read-only view endpoints return it (re-runnable in the Cypher panel). */
export interface TemplateResult<R> {
  rows: R[];
  template: string;
  params: Record<string, unknown>;
  ms: number;
  truncated: boolean;
  digest?: string;
}

/** An MCP tool envelope (tools.py `_envelope`), or the tool's loud error. */
export type ToolResult<R, X = object> =
  | ({
      rows: R[];
      via: string;
      template: string;
      cypher: string;
      params: Record<string, unknown>;
      ms: number;
      digest: string;
      truncated: boolean;
      evidence_id: string;
      error?: undefined;
    } & X)
  | { error: string; rows?: undefined };

/** One change of the run's recorded window_changes result, with what the gate said about it. */
export interface ContrastChange {
  deploy: string;
  kind: string | null;
  target: string;
  at: EpochMs;
  before_onset_ms: number | null;
  /** The run's recorded pageRank (normalised) of the changed node, when rank_causes ran. */
  pagerank: number | null;
  gate_status: "confirmed" | "eliminated" | "open" | "unresolved" | null;
  gate_reason: string | null;
  confirmed: boolean;
}

export interface RecordedRef {
  template: string | null;
  evidence_id: string | null;
  params: Record<string, unknown>;
  summary: string | null;
}

/** GET /api/incidents/{inc}/contrast */
export interface ContrastResponse {
  graph: string;
  onset_at: EpochMs | null;
  confirmed: string | null;
  outcome: string | null;
  /** Naive recency's pick: the newest change before onset (all of them when several share that instant). */
  naive: string[];
  changes: ContrastChange[];
  window_changes: RecordedRef | null;
  rank_causes: RecordedRef | null;
  unavailable: string | null;
}

export interface FamilyRow {
  communityId: number;
  incidents: string[];
  size: number;
  mine: boolean;
}

export interface RunbookRow {
  id: string;
  title: string | null;
  source: string | null;
  support: number;
  salience: number;
  reviewed_at: EpochMs | null;
  for_ids: string[];
  derived_from: string[];
}

export interface RecallRow {
  id: string;
  title: string | null;
  distance: number | null;
  similarity: number | null;
  salience: number | null;
  recency: number | null;
  opened_at: EpochMs | null;
  shared: string[];
  fixes: string[];
  cause_targets: string[];
  postmortem: string[];
}

/** GET /api/memory/overview */
export interface MemoryOverview {
  graph: string;
  incident: string | null;
  families: ToolResult<FamilyRow>;
  runbooks: TemplateResult<RunbookRow>;
  recall?: ToolResult<RecallRow>;
  recalled?: TemplateResult<RecalledIncident>;
}

export interface DecisionRow {
  id: string;
  title: string | null;
  status: string | null;
  decided_at: EpochMs | null;
  url: string | null;
  constrains?: string[];
  supersedes?: string[];
  superseded_by: string[];
}

/** GET /api/brain/decisions/{id} */
export interface DecisionTrace {
  trace: ToolResult<{
    id: string;
    status: string | null;
    head: string;
    depth: number;
    title?: string | null;
    sources?: string[];
    source_ids?: string[];
  }>;
  chain: TemplateResult<DecisionRow>;
}

export interface OwnershipTeam {
  team: string;
  name: string | null;
  owns: string[];
  n_owned: number;
  active_members: number;
}

export type OwnerAtResult = ToolResult<
  OwnerAtPayload["rows"][number],
  Omit<OwnerAtPayload, "rows">
>;

export interface GuardrailRow {
  id: string;
  name: string | null;
  no_owner: boolean;
  no_runbook: boolean;
  tier: number | null;
}

export interface KnowledgeFinding {
  kind:
    | "stale_runbook"
    | "handover_without_runbook"
    | "decision_at_risk"
    | "missing_edge"
    | string;
  id: string;
  ref: string | null;
  tier: number | null;
  why: string;
  owner?: string | null;
  ask?: string[];
}

/** GET /api/brain/guardrails */
export interface GuardrailsResponse {
  missing_guardrails: ToolResult<GuardrailRow>;
  knowledge_health: ToolResult<
    KnowledgeFinding,
    { stale_days: number; templates: string[] }
  >;
}

/** public/evals/summary.json: selected keys of evals/results/latest.json (scripts/export-eval-summary.mjs). */
export interface EvalSummary {
  source: string;
  run: string | null;
  generated_from_mtime: string | null;
  values: Record<string, number | boolean | string | null>;
}

// ------------------------------------------------------------------ obligation clock (report.obligations)

export interface SloRow {
  slo: string;
  service: string;
  label?: string | null;
  tier?: number | null;
  objective: number;
  budget?: number;
  window_days: number;
  error_rate: number | null;
  burn: number | null;
  budget_remaining: number;
  breach_in_min: number | null;
  status: "unmeasured" | "breached" | "burning" | "within_budget" | string;
}

export interface CustomerRow {
  customer: string;
  name: string | null;
  tier?: string | number | null;
  mrr: number;
  through: string[];
  via: string[];
  paths?: number;
  path: string[];
  hops?: number;
}

export interface Obligations {
  urgent: boolean | null;
  reason: string;
  page_within_min: number | null;
  breach: {
    slo: string;
    service: string;
    breach_in_min: number;
    burn: number;
    budget_remaining: number;
  } | null;
  revenue_at_risk: number;
  customers_reached: number;
  slos: SloRow[];
  customers: CustomerRow[];
  evidence_id?: string | null;
}

/** Break the graph (M15 #2): GET /api/playground, POST /api/playground/{id}. */
export interface Perturbation {
  id: string;
  label: string;
  what: string;
  expect: string;
  algorithm: string;
}

export interface PlaygroundMenu {
  scenario: string;
  perturbations: Perturbation[];
}

export interface PlaygroundDiffRow {
  decision: string;
  before: unknown;
  after: unknown;
  changed: boolean;
  templates: string[];
}

export interface PlaygroundResult {
  scenario: string;
  perturbation: Perturbation;
  applied: Record<string, number>;
  diff: PlaygroundDiffRow[];
  changed: string[];
  seconds: number;
}

/** POST /api/decisions/{decision}/override (M15 #3): step 1 (review) and step 2 (recorded). */
export interface OverrideResponse {
  decision: string;
  change: string;
  verdict: "intentional" | "accidental" | "discuss";
  why: string;
  contradiction: {
    title: string | null;
    rule_key: string;
    op: string;
    expected: unknown;
    actual: unknown;
    about: string;
  };
  current_override: {
    verdict: string;
    by: string;
    why: string;
    at: number;
  } | null;
  plan_hash: string;
  step: string;
  override?: string;
}

/** M15 #4: a failure link a verified fix showed the graph was missing (GET /api/incidents/{inc}/edge-proposals). */
export interface EdgeProposal {
  id: string;
  src: string;
  dst: string;
  cap: number;
  why: string;
  status: "proposed" | "approved";
  plan_hash: string;
  action: string;
  change: string;
  approved_by: string | null;
}
