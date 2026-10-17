import type {
  EdgeProposal,
  OverrideResponse,
  PlaygroundMenu,
  PlaygroundResult,
  ApproveResponse,
  BlastResponse,
  ContrastResponse,
  DecisionRow,
  DecisionTrace,
  GuardrailsResponse,
  MemoryOverview,
  OwnerAtResult,
  OwnershipTeam,
  RejectResponse,
  TemplateResult,
  BrainAnswer,
  BrainHistory,
  BrainSubgraph,
  ExactAction,
  ForgetDryRun,
  ForgetReceipt,
  GraphResponse,
  PlanResponse,
  PreflightRequest,
  PreflightResponse,
  ProvenanceResponse,
  RearmResponse,
  RecordedPreflight,
  IncidentListItem,
  IncidentView,
  JobStatusResponse,
  LlmMode,
  ProfileResponse,
  RunScenarioResponse,
  Scenario,
  StatusResponse,
  TemplateInfo,
  TemplateRequest,
  TemplateRunResponse,
} from "./types";

/**
 * Typed client for the Faultline API v2 (docs/API.md).
 *
 * Fail loudly: a 503 or an unreachable backend is recorded in a small failure
 * store that the app shell renders as a red banner ("Live run unavailable: …").
 * Nothing here ever substitutes sample data for a failed call.
 */

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_FAULTLINE_API_URL ?? "http://localhost:8400"
).replace(/\/$/, "");

export const DEFAULT_TENANT =
  process.env.NEXT_PUBLIC_FAULTLINE_TENANT ?? "acme";

export class ApiError extends Error {
  constructor(
    /** Human-readable reason; the backend's `detail` when it sent one. */
    public readonly detail: string,
    /** HTTP status, or null when the backend could not be reached at all. */
    public readonly status: number | null,
    public readonly url: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** True when the condition is "the live system is unavailable" (banner-worthy). */
  get unavailable(): boolean {
    return this.status === null || this.status === 503;
  }
}

// ------------------------------------------------------------------ failure store (banner)

export interface Failure {
  /** Stable key: endpoint group, so a later success on the same endpoint clears it. */
  key: string;
  reason: string;
  status: number | null;
  at: number;
}

type Listener = () => void;
let failures: Failure[] = [];
const listeners = new Set<Listener>();

function emit() {
  for (const l of listeners) l();
}

export const failureStore = {
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  snapshot(): Failure[] {
    return failures;
  },
  serverSnapshot(): Failure[] {
    return EMPTY;
  },
  report(f: Omit<Failure, "at">) {
    const rest = failures.filter((x) => x.key !== f.key);
    failures = [...rest, { ...f, at: Date.now() }];
    emit();
  },
  clear(key: string) {
    if (!failures.some((x) => x.key === key)) return;
    failures = failures.filter((x) => x.key !== key);
    emit();
  },
};
const EMPTY: Failure[] = [];

// ------------------------------------------------------------------ fetch wrapper

async function request<T>(
  key: string,
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    const e = new ApiError(
      `Faultline API unreachable at ${API_BASE_URL}`,
      null,
      url,
    );
    failureStore.report({ key: "network", reason: e.detail, status: null });
    throw e;
  }
  failureStore.clear("network");
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) {
        // FastAPI validation errors (422): [{loc, msg, …}]
        detail = body.detail
          .map((d: unknown) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg: unknown }).msg)
              : JSON.stringify(d),
          )
          .join("; ");
      } else if (body.detail !== undefined)
        detail = JSON.stringify(body.detail);
    } catch {
      /* body was not JSON: keep the status line */
    }
    const e = new ApiError(detail, res.status, url);
    if (res.status === 503)
      failureStore.report({ key, reason: detail, status: 503 });
    throw e;
  }
  failureStore.clear(key);
  return (await res.json()) as T;
}

/** The fetch wrapper for feature clients in other modules (src/lib/oncall.ts): same banner and error rules. */
export const apiRequest = request;

const enc = encodeURIComponent;
const q = (tenant: string) => `tenant=${enc(tenant)}`;

// ------------------------------------------------------------------ per-visitor capabilities (sessionStorage)

const RUN_TOKEN_PREFIX = "faultline.runToken.";
const JOB_TOKEN_PREFIX = "faultline.jobToken.";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null; // storage blocked: the server answers 403 on the public demo and the UI says so
  }
}

/**
 * Run tokens (public demo): POST /scenarios/{id}/run returns a token that lets only the visitor
 * who started the run choose/approve its actions. Kept in sessionStorage (this tab only), keyed
 * by incident id, and sent as X-Faultline-Run-Token. Never logged.
 */
export const runTokens = {
  get(incident: string): string | null {
    try {
      return storage()?.getItem(RUN_TOKEN_PREFIX + incident) ?? null;
    } catch {
      return null;
    }
  },
  set(incident: string, token: string): void {
    try {
      storage()?.setItem(RUN_TOKEN_PREFIX + incident, token);
    } catch {
      /* storage blocked: see get() */
    }
  },
  /** The token is issued per JOB: a job may open more incidents later (late intake rounds), after the run response. */
  setJob(job: string, tenant: string, token: string): void {
    try {
      storage()?.setItem(
        JOB_TOKEN_PREFIX + job,
        JSON.stringify({ tenant, token }),
      );
    } catch {
      /* storage blocked: see get() */
    }
  },
  jobs(): { job: string; tenant: string; token: string }[] {
    const st = storage();
    if (!st) return [];
    const out: { job: string; tenant: string; token: string }[] = [];
    try {
      for (let i = 0; i < st.length; i++) {
        const k = st.key(i);
        if (!k || !k.startsWith(JOB_TOKEN_PREFIX)) continue;
        const v = JSON.parse(st.getItem(k) ?? "null") as {
          tenant?: unknown;
          token?: unknown;
        } | null;
        if (v && typeof v.tenant === "string" && typeof v.token === "string")
          out.push({
            job: k.slice(JOB_TOKEN_PREFIX.length),
            tenant: v.tenant,
            token: v.token,
          });
      }
    } catch {
      return out;
    }
    return out;
  },
};

/**
 * The run token for an incident. An incident a late intake round opened after the run response is not in the
 * snapshot that response carried: ask each of this tab's jobs (GET /api/jobs/{job}, presenting the job's token) for
 * its incidents and remember the token for them. The server echoes the token only to its holder.
 */
export async function ensureRunToken(incident: string): Promise<string | null> {
  const have = runTokens.get(incident);
  if (have) return have;
  for (const j of runTokens.jobs()) {
    try {
      const res = await api.job(j.job, j.tenant, j.token);
      if (!res.token_valid) continue;
      for (const x of res.incidents ?? []) runTokens.set(x.incident, j.token);
      if (res.incident) runTokens.set(res.incident, j.token);
    } catch {
      /* job unknown (API restarted) or gone: try the next one */
    }
    const t = runTokens.get(incident);
    if (t) return t;
  }
  return null;
}

/** True for the public demo's "this incident belongs to another visitor's run" 403. */
export function isForeignRun(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 403 &&
    /another visitor/i.test(err.detail)
  );
}

export const FOREIGN_RUN_TEXT =
  "You can watch this incident, but only the visitor who started it can approve. Start your own run.";

/** A stable, anonymous per-tab user id for the brain's session history (sessionStorage). */
export function brainUserId(): string | null {
  try {
    if (typeof window === "undefined") return null;
    const k = "faultline.brainUser";
    let v = window.sessionStorage.getItem(k);
    if (!v) {
      const rnd =
        window.crypto?.randomUUID?.().replace(/-/g, "").slice(0, 12) ??
        Math.random().toString(36).slice(2, 14);
      v = `visitor-${rnd}`;
      window.sessionStorage.setItem(k, v);
    }
    return v;
  } catch {
    return null;
  }
}

export const tokenHeader = (incident: string): Record<string, string> => {
  const t = runTokens.get(incident);
  return t ? { "X-Faultline-Run-Token": t } : {};
};

export const api = {
  status(
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<StatusResponse> {
    return request("status", `/api/status?${q(tenant)}`, { signal });
  },

  scenarios(signal?: AbortSignal): Promise<Scenario[]> {
    return request("scenarios", "/api/scenarios", { signal });
  },

  /** Starts a run; stores its run token (if any) for the incident so this tab can approve it. */
  async runScenario(id: string, llm: LlmMode): Promise<RunScenarioResponse> {
    const res = await request<RunScenarioResponse>(
      "run",
      `/api/scenarios/${enc(id)}/run`,
      {
        method: "POST",
        body: JSON.stringify({ llm }),
      },
    );
    if (res.run_token && res.job)
      runTokens.setJob(res.job, res.tenant ?? DEFAULT_TENANT, res.run_token);
    if (res.incident && res.run_token)
      runTokens.set(res.incident, res.run_token);
    for (const x of res.incidents ?? [])
      if (res.run_token) runTokens.set(x.incident, res.run_token);
    return res;
  },

  /** A run job's incidents, also those opened after the run response; the token is echoed only to its holder. */
  job(
    job: string,
    tenant: string,
    token?: string,
    signal?: AbortSignal,
  ): Promise<JobStatusResponse> {
    return request("job", `/api/jobs/${enc(job)}?${q(tenant)}`, {
      signal,
      headers: token ? { "X-Faultline-Run-Token": token } : {},
    });
  },

  incidents(
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<IncidentListItem[]> {
    return request("incidents", `/api/incidents?${q(tenant)}`, { signal });
  },

  incident(
    id: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<IncidentView> {
    return request("incident", `/api/incidents/${enc(id)}?${q(tenant)}`, {
      signal,
    });
  },

  graph(
    opts: { tenant?: string; incident?: string; focus?: string },
    signal?: AbortSignal,
  ): Promise<GraphResponse> {
    const tenant = opts.tenant ?? DEFAULT_TENANT;
    const inc = opts.incident ? `&incident=${enc(opts.incident)}` : "";
    const focus = opts.focus ? `&focus=${enc(opts.focus)}` : "";
    return request("graph", `/api/graph?${q(tenant)}${inc}${focus}`, {
      signal,
    });
  },

  template(tid: string, signal?: AbortSignal): Promise<TemplateInfo> {
    return request("template", `/api/templates/${enc(tid)}`, { signal });
  },

  profile(tid: string, body: TemplateRequest): Promise<ProfileResponse> {
    return request("profile", `/api/templates/${enc(tid)}/profile`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  rerun(tid: string, body: TemplateRequest): Promise<TemplateRunResponse> {
    return request("rerun", `/api/templates/${enc(tid)}/run`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  blast(
    inc: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<BlastResponse> {
    return request("blast", `/api/incidents/${enc(inc)}/blast?${q(tenant)}`, {
      signal,
    });
  },

  /** "Why do you believe this?" (Q-PROV-1): verdict ← evidence ← tool call ← agent, and what each call saw. */
  provenance(
    inc: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<ProvenanceResponse> {
    return request(
      "provenance",
      `/api/incidents/${enc(inc)}/provenance?${q(tenant)}`,
      { signal },
    );
  },

  plan(
    inc: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<PlanResponse> {
    return request("plan", `/api/incidents/${enc(inc)}/plan?${q(tenant)}`, {
      signal,
    });
  },

  /** Step 1: choose an option; the server renders the exact action and its plan hash (409 if not available). */
  async choose(
    inc: string,
    actionId: string,
    tenant = DEFAULT_TENANT,
  ): Promise<ExactAction> {
    await ensureRunToken(inc);
    return request("choose", `/api/incidents/${enc(inc)}/choose?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ action_id: actionId }),
      headers: tokenHeader(inc),
    });
  },

  /**
   * Step 2: approve the exact action by its plan hash (409 if stale / not awaiting approval).
   * With real GitHub (FAULTLINE_GITHUB=real) the server also requires X-Faultline-Approver-Key
   * (403/503 without it); the key is sent only when the approver typed one, and never stored.
   */
  async approve(
    inc: string,
    body: {
      action_id: string;
      plan_hash: string;
      approver: string;
      /** M21: approving an option an ACTIVE learned guideline is against: the guideline's id and why (3–300 chars). */
      override_guideline?: string;
      override_reason?: string;
    },
    approverKey?: string,
    tenant = DEFAULT_TENANT,
  ): Promise<ApproveResponse> {
    await ensureRunToken(inc);
    return request(
      "approve",
      `/api/incidents/${enc(inc)}/approve?${q(tenant)}`,
      {
        method: "POST",
        body: JSON.stringify(body),
        headers: {
          ...tokenHeader(inc),
          ...(approverKey ? { "X-Faultline-Approver-Key": approverKey } : {}),
        },
      },
    );
  },

  /**
   * Reject the exact chosen action (by its plan hash) with a reason: the option is disabled for good and the
   * incident stays AWAITING_APPROVAL. Same guards as approve (409 stale, 422 approver/reason, 403 run token / key).
   */
  async reject(
    inc: string,
    body: {
      action_id: string;
      plan_hash: string;
      approver: string;
      reason: string;
    },
    approverKey?: string,
    tenant = DEFAULT_TENANT,
  ): Promise<RejectResponse> {
    await ensureRunToken(inc);
    return request("reject", `/api/incidents/${enc(inc)}/reject?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        ...tokenHeader(inc),
        ...(approverKey ? { "X-Faultline-Approver-Key": approverKey } : {}),
      },
    });
  },

  /** Naive recency vs the gate, from the run's recorded suspects (read-only). */
  contrast(
    inc: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<ContrastResponse> {
    return request(
      "contrast",
      `/api/incidents/${enc(inc)}/contrast?${q(tenant)}`,
      { signal },
    );
  },

  /** Memory tab: families, runbooks in effect and (for one incident) its recall. */
  memoryOverview(
    tenant = DEFAULT_TENANT,
    incident?: string | null,
    signal?: AbortSignal,
  ): Promise<MemoryOverview> {
    const inc = incident ? `&incident=${enc(incident)}` : "";
    return request("memory", `/api/memory/overview?${q(tenant)}${inc}`, {
      signal,
    });
  },

  brainDecisions(
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<TemplateResult<DecisionRow>> {
    return request("brain-decisions", `/api/brain/decisions?${q(tenant)}`, {
      signal,
    });
  },

  brainDecisionTrace(
    id: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<DecisionTrace> {
    return request(
      "brain-decision",
      `/api/brain/decisions/${enc(id)}?${q(tenant)}`,
      { signal },
    );
  },

  brainOwnership(
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<TemplateResult<OwnershipTeam>> {
    return request("brain-ownership", `/api/brain/ownership?${q(tenant)}`, {
      signal,
    });
  },

  brainOwnerAt(
    component: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<OwnerAtResult> {
    return request(
      "brain-owner-at",
      `/api/brain/ownership/${enc(component)}?${q(tenant)}`,
      { signal },
    );
  },

  brainGuardrails(
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<GuardrailsResponse> {
    return request("brain-guardrails", `/api/brain/guardrails?${q(tenant)}`, {
      signal,
    });
  },

  tenants(
    signal?: AbortSignal,
  ): Promise<{ tenant: string; graph: string; ready: boolean }[]> {
    return request("tenants", "/api/tenants", { signal });
  },

  /** `user` (anonymous per-tab id) lets the brain keep this visitor's session history in the graph. */
  brainAsk(
    question: string,
    llm: LlmMode,
    user?: string | null,
    tenant = DEFAULT_TENANT,
  ): Promise<BrainAnswer> {
    return request("brain", `/api/brain/ask?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify(user ? { question, llm, user } : { question, llm }),
    });
  },

  /** Q-BRAIN-SUB: how 1–12 cited ids connect (paths of at most 2 hops), for "answer as a graph". */
  brainSubgraph(
    ids: string[],
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<BrainSubgraph> {
    return request(
      "brain-subgraph",
      `/api/brain/subgraph?${q(tenant)}&ids=${enc(ids.join(","))}`,
      { signal },
    );
  },

  brainHistory(
    user: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<BrainHistory> {
    return request(
      "brain-history",
      `/api/brain/history?${q(tenant)}&user=${enc(user)}`,
      { signal },
    );
  },

  /** Forget with a receipt, step 1: dry run (what would be deleted + the receipt token). */
  forgetDryRun(docId: string, tenant = DEFAULT_TENANT): Promise<ForgetDryRun> {
    return request("forget", `/api/memory/forget?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ doc_id: docId }),
    });
  },

  /** Step 2: execute exactly the dry run's set (409 if the graph changed since). */
  forgetExecute(
    docId: string,
    token: string,
    approver: string,
    tenant = DEFAULT_TENANT,
  ): Promise<ForgetReceipt> {
    return request("forget", `/api/memory/forget?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ doc_id: docId, token, approver }),
    });
  },

  /** Latest recorded preflight for a PR id (404 when none). */
  preflightGet(
    pr: string,
    tenant = DEFAULT_TENANT,
    signal?: AbortSignal,
  ): Promise<RecordedPreflight> {
    return request(
      "preflight-get",
      `/api/preflight?${q(tenant)}&pr=${enc(pr)}`,
      { signal },
    );
  },

  preflight(
    body: PreflightRequest,
    tenant = DEFAULT_TENANT,
  ): Promise<PreflightResponse> {
    return request("preflight", `/api/preflight?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** Step 1 without planHash (review), step 2 with planHash + approver (record). */
  decisionOverride(
    decision: string,
    body: {
      change: string;
      verdict: string;
      why: string;
      incident: string;
      plan_hash?: string;
      approver?: string;
    },
    tenant = DEFAULT_TENANT,
  ): Promise<OverrideResponse> {
    return request(
      "override",
      `/api/decisions/${enc(decision)}/override?${q(tenant)}`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );
  },

  humanFix(
    inc: string,
    body: { change: string; by: string; why: string },
    tenant = DEFAULT_TENANT,
  ): Promise<{ id: string }> {
    return request(
      "human-fix",
      `/api/incidents/${enc(inc)}/human-fix?${q(tenant)}`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  edgeProposals(
    inc: string,
    tenant = DEFAULT_TENANT,
  ): Promise<{ incident: string; proposals: EdgeProposal[] }> {
    return request(
      "edge-proposals",
      `/api/incidents/${enc(inc)}/edge-proposals?${q(tenant)}`,
    );
  },

  approveEdge(
    inc: string,
    pid: string,
    body: { plan_hash: string; approver: string },
    tenant = DEFAULT_TENANT,
  ): Promise<{ approved: string }> {
    return request(
      "edge-approve",
      `/api/incidents/${enc(inc)}/edge-proposals/${enc(pid)}/approve?${q(tenant)}`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );
  },

  playgroundMenu(): Promise<PlaygroundMenu> {
    return request("playground", "/api/playground");
  },

  playgroundRun(id: string): Promise<PlaygroundResult> {
    return request("playground-run", `/api/playground/${enc(id)}`, {
      method: "POST",
    });
  },

  rearm(tenant = DEFAULT_TENANT): Promise<RearmResponse> {
    return request("rearm", `/api/demo/rearm?${q(tenant)}`, { method: "POST" });
  },
};

export function incidentEventsUrl(id: string, tenant = DEFAULT_TENANT): string {
  return `${API_BASE_URL}/api/incidents/${enc(id)}/events?${q(tenant)}`;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    return err.status === null ? err.detail : `${err.status}: ${err.detail}`;
  }
  return err instanceof Error ? err.message : String(err);
}
