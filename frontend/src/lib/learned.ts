import { ApiError, apiRequest } from "./api";
import { toMs, type PersonRef } from "./oncall";
import type { EpochMs } from "./types";

/**
 * Typed client for what Faultline learned from the people using it (M21, docs/API.md):
 * GET /api/learned, guideline promote / dismiss, knowledge-gap dismiss and forgetting a person's influence (dry run,
 * then the receipt token). Every value comes from these responses, which the backend reads from the tenant's on-call
 * home graph (`oncall_<tenant>`) in FalkorDB; nothing here invents one. A missing value stays null and the UI shows
 * "–". A response that is not the documented shape is an error (an ApiError, so the panel says so).
 */

// ------------------------------------------------------------------ shapes

/** One section of GET /api/learned: its rows and the FalkorDB query that produced them (ViaFalkor). */
export interface Envelope<R> {
  rows: R[];
  template: string | null;
  params: Record<string, unknown> | null;
  ms: number | null;
  truncated: boolean;
  digest: string | null;
}

/** A learned preference (Q-LEARN-PREFS): per family and action kind, decayed to the server's `now`. */
export interface PreferenceRow {
  id: string;
  family: string;
  actionKind: string;
  /** Beta-smoothed (a+1)/(a+r+o+2) over the decayed sums. */
  pref: number | null;
  approvals: number | null;
  rejections: number | null;
  others: number | null;
  nApprove: number | null;
  nReject: number | null;
  nFamilyApprove: number | null;
  nFamily: number | null;
  lastAt: EpochMs | null;
  computedAt: EpochMs | null;
  /** Provenance: the LearnEvent ids it derives from. */
  events: string[];
  /** The server's own "why" sentence. */
  line: string | null;
}

export type GuidelineStatus = "proposed" | "active" | "dismissed";

export interface GuidelineRow {
  id: string;
  text: string | null;
  family: string | null;
  actionKind: string | null;
  status: string | null;
  source: string | null;
  by: PersonRef | null;
  at: EpochMs | null;
  incident: string | null;
  graph: string | null;
  /** The option the rejection was about. */
  option: string | null;
  event: string | null;
  decidedBy: PersonRef | null;
  decidedAt: EpochMs | null;
}

/** A learned responder edge ((:Person)-[:RESPONDED]->(component), Q-LEARN-RESPS). */
export interface ResponderRow {
  person: PersonRef;
  active: boolean | null;
  family: string | null;
  /** Decayed responses at the server's `now`. */
  score: number | null;
  n: number | null;
  acks: number | null;
  approvals: number | null;
  fixes: number | null;
  mttaMs: number | null;
  lastAt: EpochMs | null;
  incidents: number | null;
  events: string[];
}

export interface GapRow {
  id: string;
  text: string | null;
  n: number | null;
  firstAt: EpochMs | null;
  lastAt: EpochMs | null;
  status: string | null;
  intent: string | null;
  reason: string | null;
  about: string[];
  /** Teams owning what the question was about: who should document it. */
  owners: string[];
  events: string[];
}

/** An exact fix approved and verified APPLIED often enough to suggest a standing approval (Q-LEARN-SUGGESTS). */
export interface SuggestionRow {
  family: string | null;
  actionKind: string | null;
  paramsHash: string | null;
  n: number | null;
  incidents: string[];
  events: string[];
  lastAt: EpochMs | null;
  people: string[];
  /** An active contract that already covers it, else null. */
  coveredBy: string | null;
}

export type LearnEventKind =
  | "approve"
  | "reject"
  | "override"
  | "verified"
  | "ack"
  | "choose"
  | "grant"
  | "revoke"
  | "handoff"
  | "escalate_now"
  | "gap";

export interface LearnEventRow {
  id: string;
  kind: string | null;
  person: PersonRef | null;
  family: string | null;
  actionKind: string | null;
  option: string | null;
  at: EpochMs | null;
  incident: string | null;
  graph: string | null;
  via: string | null;
  reason: string | null;
  verdict: string | null;
  ackMs: number | null;
  text: string | null;
}

export interface EventCount {
  kind: string;
  n: number | null;
  people: number | null;
  lastAt: EpochMs | null;
}

/** A forget receipt (Q-LEARN-RECEIPTS, in audit_<tenant>). */
export interface ReceiptRow {
  person: string | null;
  approver: string | null;
  token: string | null;
  events: number | null;
  guidelines: number | null;
  relationships: number | null;
  families: string[];
  responders: string[];
  gaps: string[];
  eventsLeft: number | null;
  preferencesStillCiting: number | null;
  graph: string | null;
  at: EpochMs | null;
}

export interface LearnedState {
  tenant: string;
  /** The graph the learned state lives in (oncall_<tenant>). */
  home: string | null;
  /** The server clock the decays were computed at. */
  now: EpochMs | null;
  halfLifeDays: number | null;
  trust: { rule: string | null; public: boolean | null };
  preferences: Envelope<PreferenceRow>;
  guidelines: Envelope<GuidelineRow>;
  responders: Envelope<ResponderRow>;
  gaps: Envelope<GapRow>;
  suggestions: Envelope<SuggestionRow>;
  events: Envelope<LearnEventRow> & { counts: EventCount[] };
  receipts: Envelope<ReceiptRow>;
}

/** POST /api/learned/forget without a token: what forgetting deletes and recomputes, bound by `token`. */
export interface ForgetPlan {
  person: string;
  nEvents: number;
  byKind: { kind: string; n: number }[];
  events: {
    id: string;
    kind: string | null;
    family: string | null;
    actionKind: string | null;
    at: EpochMs | null;
    incident: string | null;
    gap: string | null;
    guidelines: string[];
  }[];
  guidelines: string[];
  families: string[];
  responded: string[];
  gaps: string[];
  token: string;
}

/** POST /api/learned/forget with the token: the receipt and its re-read proof. */
export interface ForgetReceipt {
  person: string;
  approver: string | null;
  token: string | null;
  graph: string | null;
  events: number | null;
  guidelines: number | null;
  relationships: number | null;
  familiesRecomputed: string[];
  respondersRecomputed: string[];
  gapsRecomputed: string[];
  eventsLeft: number | null;
  preferencesStillCiting: number | null;
  at: EpochMs | null;
  verdict: string | null;
  /** True only when the server's proof says "forgotten" and both re-read counts are 0. */
  forgotten: boolean;
}

// ------------------------------------------------------------------ field readers (never invent a value)

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

function str(v: unknown): string | null {
  if (typeof v === "string") return v.trim() ? v : null;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return null;
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  return null;
}

function bool(v: unknown): boolean | null {
  return typeof v === "boolean" ? v : null;
}

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.map(str).filter((x): x is string => x !== null) : [];
}

/** A list the receipts store as JSON text ("[\"payment\"]"), or a real list. */
function jsonStrings(v: unknown): string[] {
  if (Array.isArray(v)) return strings(v);
  if (typeof v === "string" && v.trim().startsWith("[")) {
    try {
      return strings(JSON.parse(v));
    } catch {
      return [];
    }
  }
  return [];
}

/** {id, name} or a bare id, with an optional separate name field. */
function personOf(v: unknown, name?: unknown): PersonRef | null {
  if (isObj(v)) {
    const id = str(v.id);
    return id ? { id, name: str(v.name) ?? str(name) } : null;
  }
  const id = str(v);
  return id ? { id, name: str(name) } : null;
}

function envelope<R>(raw: unknown, what: string, row: (v: Obj) => R | null): Envelope<R> {
  if (!isObj(raw) || !Array.isArray(raw.rows)) {
    throw new ApiError(`unexpected response for GET /api/learned: the ${what} section has no rows`, 200, "learned");
  }
  return {
    rows: raw.rows.filter(isObj).map(row).filter((x): x is R => x !== null),
    template: str(raw.template),
    params: isObj(raw.params) ? raw.params : null,
    ms: num(raw.ms),
    truncated: bool(raw.truncated) ?? false,
    digest: str(raw.digest),
  };
}

function preference(v: Obj): PreferenceRow | null {
  const family = str(v.family);
  const kind = str(v.action_kind);
  if (!family || !kind) return null;
  return {
    id: str(v.id) ?? `pref|${family}|${kind}`,
    family,
    actionKind: kind,
    pref: num(v.pref),
    approvals: num(v.approvals),
    rejections: num(v.rejections),
    others: num(v.others),
    nApprove: num(v.n_approve),
    nReject: num(v.n_reject),
    nFamilyApprove: num(v.n_family_approve),
    nFamily: num(v.n_family),
    lastAt: toMs(v.last_at),
    computedAt: toMs(v.computed_at),
    events: strings(v.events),
    line: str(v.line),
  };
}

export function parseGuideline(v: Obj): GuidelineRow | null {
  const id = str(v.id);
  if (!id) return null;
  return {
    id,
    text: str(v.text),
    family: str(v.family),
    actionKind: str(v.action_kind),
    status: str(v.status),
    source: str(v.source),
    by: personOf(v.by, v.by_name),
    at: toMs(v.at),
    incident: str(v.incident),
    graph: str(v.graph),
    option: str(v.option),
    event: str(v.event),
    decidedBy: personOf(v.decided_by, v.decided_by_name),
    decidedAt: toMs(v.decided_at),
  };
}

function responder(v: Obj): ResponderRow | null {
  const person = personOf(v.person, v.name);
  if (!person) return null;
  return {
    person,
    active: bool(v.active),
    family: str(v.family),
    score: num(v.score),
    n: num(v.n),
    acks: num(v.acks),
    approvals: num(v.approvals),
    fixes: num(v.fixes),
    mttaMs: num(v.mtta_ms),
    lastAt: toMs(v.last_at),
    incidents: num(v.incidents),
    events: strings(v.events),
  };
}

function gap(v: Obj): GapRow | null {
  const id = str(v.id);
  if (!id) return null;
  return {
    id,
    text: str(v.text),
    n: num(v.n),
    firstAt: toMs(v.first_at),
    lastAt: toMs(v.last_at),
    status: str(v.status),
    intent: str(v.intent),
    reason: str(v.reason),
    about: strings(v.about),
    owners: strings(v.owners),
    events: strings(v.events),
  };
}

function suggestion(v: Obj): SuggestionRow {
  return {
    family: str(v.family),
    actionKind: str(v.action_kind),
    paramsHash: str(v.params_hash),
    n: num(v.n),
    incidents: strings(v.incidents),
    events: strings(v.events),
    lastAt: toMs(v.last_at),
    people: strings(v.people),
    coveredBy: str(v.covered_by),
  };
}

function learnEvent(v: Obj): LearnEventRow | null {
  const id = str(v.id);
  if (!id) return null;
  return {
    id,
    kind: str(v.kind),
    person: personOf(v.person, v.person_name),
    family: str(v.family),
    actionKind: str(v.action_kind),
    option: str(v.option),
    at: toMs(v.at),
    incident: str(v.incident),
    graph: str(v.graph),
    via: str(v.via),
    reason: str(v.reason),
    verdict: str(v.verdict),
    ackMs: num(v.ack_ms),
    text: str(v.text),
  };
}

function receipt(v: Obj): ReceiptRow {
  return {
    person: str(v.person),
    approver: str(v.approver),
    token: str(v.token),
    events: num(v.events),
    guidelines: num(v.guidelines),
    relationships: num(v.relationships),
    families: jsonStrings(v.families),
    responders: jsonStrings(v.responders),
    gaps: jsonStrings(v.gaps),
    eventsLeft: num(v.events_left),
    preferencesStillCiting: num(v.preferences_still_citing),
    graph: str(v.graph),
    at: toMs(v.at),
  };
}

export function parseLearned(raw: unknown): LearnedState {
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/learned: expected an object", 200, "learned");
  const trust = isObj(raw.trust) ? raw.trust : {};
  const ev = envelope(raw.events, "events", learnEvent);
  const counts = isObj(raw.events) && Array.isArray(raw.events.counts) ? raw.events.counts : [];
  return {
    tenant: str(raw.tenant) ?? "",
    home: str(raw.home),
    now: toMs(raw.now),
    halfLifeDays: num(raw.half_life_days),
    trust: { rule: str(trust.rule), public: bool(trust.public) },
    preferences: envelope(raw.preferences, "preferences", preference),
    guidelines: envelope(raw.guidelines, "guidelines", parseGuideline),
    responders: envelope(raw.responders, "responders", responder),
    gaps: envelope(raw.gaps, "knowledge gaps", gap),
    suggestions: envelope(raw.suggestions, "suggestions", suggestion),
    events: {
      ...ev,
      counts: counts
        .filter(isObj)
        .map((c) => ({ kind: str(c.kind) ?? "", n: num(c.n), people: num(c.people), lastAt: toMs(c.last_at) }))
        .filter((c) => c.kind),
    },
    receipts: envelope(raw.receipts, "receipts", receipt),
  };
}

export function parseForgetPlan(raw: unknown): ForgetPlan {
  if (!isObj(raw) || raw.dry_run !== true) {
    throw new ApiError("unexpected response for the forget dry run: expected {dry_run: true, …}", 200, "learned-forget");
  }
  const token = str(raw.token);
  const person = str(raw.person);
  if (!token || !person) throw new ApiError("the forget dry run returned no receipt token: nothing to confirm", 200, "learned-forget");
  const byKind = isObj(raw.by_kind)
    ? Object.entries(raw.by_kind)
        .map(([kind, n]) => ({ kind, n: num(n) ?? 0 }))
        .filter((x) => x.n > 0)
    : [];
  const events = (Array.isArray(raw.events) ? raw.events : []).filter(isObj).flatMap((e) => {
    const id = str(e.id);
    return id
      ? [
          {
            id,
            kind: str(e.kind),
            family: str(e.family),
            actionKind: str(e.action_kind),
            at: toMs(e.at),
            incident: str(e.incident),
            gap: str(e.gap),
            guidelines: strings(e.guidelines),
          },
        ]
      : [];
  });
  return {
    person,
    nEvents: num(raw.n_events) ?? events.length,
    byKind,
    events,
    guidelines: strings(raw.guidelines),
    families: strings(raw.families),
    responded: strings(raw.responded),
    gaps: strings(raw.gaps),
    token,
  };
}

export function parseForgetReceipt(raw: unknown): ForgetReceipt {
  if (!isObj(raw) || raw.dry_run !== false) {
    throw new ApiError("unexpected response for the forget: expected {dry_run: false, …}", 200, "learned-forget");
  }
  const person = str(raw.person);
  if (!person) throw new ApiError("the forget answered without the person it forgot", 200, "learned-forget");
  const proof = isObj(raw.proof) ? raw.proof : {};
  const eventsLeft = num(proof.events_left) ?? num(raw.events_left);
  const citing = num(proof.preferences_still_citing) ?? num(raw.preferences_still_citing);
  const verdict = str(proof.verdict);
  return {
    person,
    approver: str(raw.approver),
    token: str(raw.token),
    graph: str(raw.graph),
    events: num(raw.events),
    guidelines: num(raw.guidelines),
    relationships: num(raw.relationships),
    familiesRecomputed: jsonStrings(raw.families_recomputed),
    respondersRecomputed: jsonStrings(raw.responders_recomputed),
    gapsRecomputed: jsonStrings(raw.gaps_recomputed),
    eventsLeft,
    preferencesStillCiting: citing,
    at: toMs(raw.at),
    verdict,
    forgotten: verdict === "forgotten" && eventsLeft === 0 && citing === 0,
  };
}

// ------------------------------------------------------------------ client

const enc = encodeURIComponent;
const q = (tenant: string) => `tenant=${enc(tenant)}`;
const keyHeader = (key?: string): Record<string, string> => (key ? { "X-Faultline-Approver-Key": key } : {});

export const learnedApi = {
  async state(tenant: string, signal?: AbortSignal): Promise<LearnedState> {
    return parseLearned(await apiRequest<unknown>("learned", `/api/learned?${q(tenant)}`, { signal }));
  },

  /** Promote (proposed → active) or dismiss a guideline; `by` must be an active person. Key only when typed. */
  async guideline(gid: string, action: "promote" | "dismiss", by: string, tenant: string, approverKey?: string): Promise<GuidelineRow | null> {
    const raw = await apiRequest<unknown>("learned-guideline", `/api/learned/guidelines/${enc(gid)}?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ action, by }),
      headers: keyHeader(approverKey),
    });
    return isObj(raw) && isObj(raw.guideline) ? parseGuideline(raw.guideline) : null;
  },

  async dismissGap(gid: string, by: string, tenant: string, approverKey?: string): Promise<unknown> {
    return apiRequest<unknown>("learned-gap", `/api/learned/gaps/${enc(gid)}/dismiss?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ by }),
      headers: keyHeader(approverKey),
    });
  },

  /** Step 1: the dry run (nothing is deleted). */
  async forgetDryRun(person: string, tenant: string, approverKey?: string): Promise<ForgetPlan> {
    const raw = await apiRequest<unknown>("learned-forget", `/api/learned/forget?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ person }),
      headers: keyHeader(approverKey),
    });
    return parseForgetPlan(raw);
  },

  /** Step 2: forget exactly the dry run's set, bound by its token (409 when the learned state changed since). */
  async forget(body: { person: string; token: string; approver: string }, tenant: string, approverKey?: string): Promise<ForgetReceipt> {
    const raw = await apiRequest<unknown>("learned-forget", `/api/learned/forget?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: keyHeader(approverKey),
    });
    return parseForgetReceipt(raw);
  },
};

// ------------------------------------------------------------------ display words (pure)

export const KIND_WORD: Record<string, string> = {
  flip_flag: "flag flip",
  rollback_deploy: "rollback",
  open_issue: "issue",
  data_repair: "data repair",
};

export function kindWord(kind: string | null | undefined): string {
  if (!kind) return "–";
  return KIND_WORD[kind] ?? kind.replace(/_/g, " ");
}

export const EVENT_WORD: Record<LearnEventKind, string> = {
  approve: "approved",
  reject: "rejected",
  override: "overrode a guideline",
  verified: "fix verified",
  ack: "acked a page",
  choose: "chose",
  grant: "granted a contract",
  revoke: "revoked a contract",
  handoff: "handed off",
  escalate_now: "escalated now",
  gap: "asked, unanswered",
};

export function eventWord(kind: string | null | undefined): string {
  if (!kind) return "event";
  return EVENT_WORD[kind as LearnEventKind] ?? kind.replace(/_/g, " ");
}

/** "0.86" for a preference in [0, 1]; "–" otherwise. */
export function fmtPref(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "–" : v.toFixed(2);
}

/** A decayed count: one decimal ("4.6"), whole numbers without one; "–" for null. */
export function fmtDecayed(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(1);
}

/** The people mentioned anywhere in the learned state, for the person-id suggestions (deduplicated, ids first seen). */
export function knownPeople(s: LearnedState | null): PersonRef[] {
  if (!s) return [];
  const out = new Map<string, PersonRef>();
  const add = (p: PersonRef | null) => {
    if (!p) return;
    const had = out.get(p.id);
    if (!had || (!had.name && p.name)) out.set(p.id, { id: p.id, name: p.name ?? had?.name ?? null });
  };
  s.events.rows.forEach((e) => add(e.person));
  s.responders.rows.forEach((r) => add(r.person));
  s.guidelines.rows.forEach((g) => {
    add(g.by);
    add(g.decidedBy);
  });
  return [...out.values()];
}

/** A guideline id the server named in a 409 ("… is against active guideline gl-… ("text", promoted by …): …"). */
export function guidelineFrom409(detail: string): { id: string; text: string | null; promotedBy: string | null } | null {
  const m = detail.match(/against active guideline (gl-[0-9a-f]{6,40})/);
  if (!m) return null;
  const t = detail.match(/\("(.*)", promoted by (.*?)\): /);
  return { id: m[1], text: t ? t[1] : null, promotedBy: t ? t[2] : null };
}
