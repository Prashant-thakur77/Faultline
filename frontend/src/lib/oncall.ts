import { ApiError, apiRequest, ensureRunToken, tokenHeader } from "./api";
import type { EpochMs } from "./types";

/**
 * Typed client for the M19 on-call API (docs/API.md): who is on call, the pager, acks, contracts,
 * the shift report, hand-offs and the on-call stats. Every value comes from these responses, which the backend
 * reads from the tenant's FalkorDB graph; nothing here invents one.
 *
 * The parsers below turn each response into one shape. They accept the plan's bare-array form and the read-only
 * view envelope ({rows, template, params, ms}) the other view endpoints use, plus a few spellings of the same
 * field (a person as {id, name} or as an id). They never fill in a missing value: it stays null and the UI shows
 * "–". A response that is neither shape is an error (thrown as an ApiError, so the panel says so).
 */

// ------------------------------------------------------------------ shapes

export type PageStatus = "sent" | "delivery_failed" | "acked" | "escalated" | "resolved" | "superseded";
export type PageKind = "page" | "escalation" | "report" | "contract_notice";
export type ContractStatus = "active" | "exhausted" | "expired" | "revoked";

export interface PersonRef {
  id: string;
  name: string | null;
}

/** The query behind a panel, for its "via FalkorDB" chip and the Cypher panel. */
export interface QueryRef {
  template: string | null;
  params: Record<string, unknown> | null;
  ms: number | null;
}

/** GET /api/oncall/now: one row per team. */
export interface OnCallRow {
  team: string;
  teamName: string | null;
  person: PersonRef | null;
  from: EpochMs | null;
  to: EpochMs | null;
}

export interface OnCallNow extends QueryRef {
  rows: OnCallRow[];
  at: EpochMs | null;
}

export interface PageAck {
  by: PersonRef | null;
  at: EpochMs | null;
  via: string | null;
}

/** One step of a page's escalation history (Q-PAGE-CHAIN). */
export interface ChainStep {
  id: string;
  person: PersonRef | null;
  status: string | null;
  channel: string | null;
  attempt: number | null;
  sentAt: EpochMs | null;
  ack: PageAck | null;
}

/** A (:Page) node and what it points at (PAGES person, FOR incident, ACKED, ESCALATED_TO). */
export interface PageRow {
  id: string;
  incident: string | null;
  incidentTitle: string | null;
  channel: string | null;
  kind: string | null;
  urgency: string | null;
  sentAt: EpochMs | null;
  ackDueAt: EpochMs | null;
  status: string | null;
  attempt: number | null;
  detail: string | null;
  person: PersonRef | null;
  ack: PageAck | null;
  escalatedTo: string | null;
  /** Why this person was paged (the server's words, e.g. on call for the owning team). */
  reason: string | null;
  team: string | null;
  incidentStage: string | null;
  /** Every channel the page went to (in-app always), when recorded. */
  channels: string[];
  /** Per-channel delivery result as the server recorded it on the Page. */
  delivery: DeliveryResult[];
  /** The server's own overdue flag (Q-PAGES / Q-PAGE-OVERDUE), when the list carries it. */
  overdue: boolean | null;
  /**
   * The page's signed ack token, when the server hands it to this console (off the public demo, or to the holder of the
   * incident's run token). Used only to ack; never shown.
   */
  ackToken: string | null;
  /** The graph the page lives in (tenant or run graph). */
  graph: string | null;
  /** Escalation history, when the list embeds it (else GET /api/pages/{id} has it). */
  chain: ChainStep[] | null;
}

export interface DeliveryResult {
  channel: string;
  ok: boolean | null;
  detail: string | null;
}

/** A delivery channel and whether it is configured (absent from the API: null, and the UI says "not reported"). */
export interface ChannelInfo {
  channel: string;
  configured: boolean;
  detail: string | null;
}

export interface PagesList extends QueryRef {
  rows: PageRow[];
  channels: ChannelInfo[] | null;
  truncated: boolean;
}

export interface WhoFixesPerson {
  person: PersonRef;
  score: number | null;
  reasons: string[];
}

export interface ProofChain {
  nodes: string[];
  /** Relationship types between consecutive nodes (rels[i] joins nodes[i] and nodes[i + 1]); empty if not sent. */
  rels: string[];
  query: QueryRef | null;
}

/** GET /api/pages/{id}: the page, its incident's one-liner, the proof chain and who fixes it. */
export interface PageDetail {
  page: PageRow;
  incident: {
    id: string;
    title: string | null;
    line: string | null;
    stage: string | null;
    cause: string | null;
  } | null;
  proof: ProofChain | null;
  whoFixes: WhoFixesPerson[];
  whoFixesQuery: QueryRef | null;
  chain: ChainStep[];
  chainQuery: QueryRef | null;
  breachInMin: number | null;
  breachSlo: string | null;
}

export interface ContractUse {
  incident: string;
  at: EpochMs | null;
  verdict: string | null;
}

export interface Contract {
  id: string;
  family: string | null;
  actionKind: string | null;
  paramsHash: string | null;
  maxUses: number | null;
  uses: number | null;
  expiresAt: EpochMs | null;
  grantedAt: EpochMs | null;
  status: string | null;
  quote: string | null;
  grantedBy: PersonRef | null;
  covers: string | null;
  sourceIncident: string | null;
  revokedAt: EpochMs | null;
  revokedBy: string | null;
  usedIn: ContractUse[];
}

export interface ContractsList extends QueryRef {
  rows: Contract[];
}

/** POST /api/incidents/{id}/contract {step: "choose"}: the exact grant the server will record, bound by `hash`. */
export interface ContractQuote {
  /** The offered contract's id, when the server returns it (sent back with the approval). */
  id: string | null;
  hash: string;
  /** The offer must be approved before this (the server refuses a late approval with 409). */
  offerExpiresAt: EpochMs | null;
  /** The server's own sentence for what is being granted. */
  quote: string | null;
  /** The verified action the contract repeats (its option text). */
  option: string | null;
  maxUses: number | null;
  days: number | null;
  family: string | null;
  actionKind: string | null;
  paramsHash: string | null;
  expiresAt: EpochMs | null;
}

export type ReportSection = "incidents" | "pages" | "acks" | "actions" | "contract_uses" | "handoffs";

export const REPORT_SECTIONS: { key: ReportSection; label: string; short: string }[] = [
  { key: "incidents", label: "Incidents", short: "Incidents" },
  { key: "pages", label: "Pages", short: "Pages" },
  { key: "acks", label: "Acks", short: "Acks" },
  { key: "actions", label: "Actions", short: "Actions" },
  { key: "contract_uses", label: "Handled under contract", short: "Under contract" },
  { key: "handoffs", label: "Hand-offs", short: "Hand-offs" },
];

/** One row of a report section, reduced to what a list shows; `raw` keeps every field the server sent. */
export interface ReportItem {
  id: string | null;
  title: string | null;
  status: string | null;
  who: string | null;
  at: EpochMs | null;
  incident: string | null;
  raw: Record<string, unknown>;
}

export interface ShiftReport extends QueryRef {
  from: EpochMs | null;
  to: EpochMs | null;
  /** Per section: the server's count when it sent one, else the length of the rows it sent; null if neither. */
  counts: Record<ReportSection, number | null>;
  sections: Record<ReportSection, ReportItem[] | null>;
  /** A prose summary, when the server writes one. */
  summary: string | null;
}

export interface OnCallStats extends QueryRef {
  days: number | null;
  mttaMs: number | null;
  mttrMs: number | null;
  peoplePaged: number | null;
  handledUnderContract: number | null;
  pages: number | null;
  incidents: number | null;
}

export interface HandoffResult {
  id: string;
  at: EpochMs | null;
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

/** The first of several spellings that is present (not undefined/null). */
function pick(o: Obj, ...keys: string[]): unknown {
  for (const k of keys) if (o[k] !== undefined && o[k] !== null) return o[k];
  return undefined;
}

/** Epoch ms from epoch ms, epoch seconds (< 1e11) or an ISO string; null otherwise. */
export function toMs(v: unknown): EpochMs | null {
  if (typeof v === "number" && Number.isFinite(v)) return v < 1e11 ? v * 1000 : v;
  if (typeof v === "string" && v.trim()) {
    if (/^\d+(\.\d+)?$/.test(v.trim())) return toMs(Number(v));
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

function person(v: unknown, name?: unknown): PersonRef | null {
  if (isObj(v)) {
    const id = str(pick(v, "id", "person"));
    return id ? { id, name: str(pick(v, "name")) ?? str(name) } : null;
  }
  const id = str(v);
  return id ? { id, name: str(name) } : null;
}

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.map(str).filter((x): x is string => x !== null) : [];
}

function query(o: Obj, fallback: string | null): QueryRef {
  return {
    template: str(o.template) ?? fallback,
    params: isObj(o.params) ? o.params : null,
    ms: num(o.ms),
  };
}

/** The rows of a response: the bare array, or the envelope's `rows` (or the named list). Throws on anything else. */
function listOf(raw: unknown, what: string, ...names: string[]): { rows: unknown[]; env: Obj } {
  if (Array.isArray(raw)) return { rows: raw, env: {} };
  if (isObj(raw)) {
    for (const n of ["rows", ...names]) if (Array.isArray(raw[n])) return { rows: raw[n] as unknown[], env: raw };
  }
  throw new ApiError(`unexpected response for ${what}: expected a list or {rows: [...]}`, 200, what);
}

/** A single-row template answer ({rows: [row], template, params}) flattened onto its envelope; else the object. */
function oneRow(raw: Obj): Obj {
  if (Array.isArray(raw.rows) && raw.rows.length === 1 && isObj(raw.rows[0])) return { ...raw, ...raw.rows[0] };
  return raw;
}

function ack(o: Obj): PageAck | null {
  const a = isObj(o.ack) ? o.ack : isObj(o.acked) ? o.acked : null;
  if (a) {
    const by = person(pick(a, "by", "person"), a.by_name ?? a.name);
    const at = toMs(a.at);
    return by || at ? { by, at, via: str(a.via) } : null;
  }
  const by = person(o.acked_by, o.acked_by_name);
  const at = toMs(o.acked_at);
  return by || at ? { by, at, via: str(pick(o, "ack_via", "acked_via")) } : null;
}

function chainStep(v: unknown): ChainStep | null {
  if (!isObj(v)) return null;
  const id = str(pick(v, "id", "page"));
  if (!id) return null;
  return {
    id,
    person: person(pick(v, "person", "to", "person_id"), pick(v, "person_name", "name")),
    status: str(v.status),
    channel: str(v.channel),
    attempt: num(v.attempt),
    sentAt: toMs(v.sent_at),
    ack: ack(v),
  };
}

function chainOf(v: unknown): ChainStep[] | null {
  if (!Array.isArray(v)) return null;
  return v.map(chainStep).filter((x): x is ChainStep => x !== null);
}

function delivery(v: unknown): DeliveryResult[] {
  let o: unknown = v;
  if (typeof v === "string") {
    try {
      o = JSON.parse(v);
    } catch {
      return [];
    }
  }
  if (!isObj(o)) return [];
  return Object.entries(o).map(([channel, r]) =>
    isObj(r)
      ? { channel, ok: bool(r.ok), detail: str(pick(r, "error", "detail", "reason")) ?? (num(r.status) !== null ? `HTTP ${num(r.status)}` : null) }
      : { channel, ok: bool(r), detail: null },
  );
}

export function parsePage(v: unknown): PageRow | null {
  if (!isObj(v)) return null;
  const id = str(v.id);
  if (!id) return null;
  const inc = v.incident;
  return {
    id,
    incident: isObj(inc) ? str(inc.id) : str(inc),
    incidentTitle: str(pick(v, "incident_title", "title")) ?? (isObj(inc) ? str(pick(inc, "title", "line")) : null),
    channel: str(v.channel),
    kind: str(v.kind),
    urgency: str(v.urgency),
    sentAt: toMs(v.sent_at),
    ackDueAt: toMs(v.ack_due_at),
    status: str(v.status),
    attempt: num(v.attempt),
    detail: str(v.detail),
    person: person(pick(v, "person", "to", "person_id"), pick(v, "person_name", "name")),
    ack: ack(v),
    escalatedTo: str(pick(v, "escalated_to", "next")),
    reason: str(v.reason),
    team: str(v.team),
    incidentStage: str(v.incident_stage) ?? (isObj(inc) ? str(inc.stage) : null),
    channels: strings(v.channels),
    delivery: delivery(v.delivery),
    overdue: bool(v.overdue),
    ackToken: str(v.ack_token),
    graph: str(v.graph),
    chain: chainOf(v.chain),
  };
}

function channels(v: unknown): ChannelInfo[] | null {
  if (Array.isArray(v)) {
    const out: ChannelInfo[] = [];
    for (const c of v) {
      if (typeof c === "string") out.push({ channel: c, configured: true, detail: null });
      else if (isObj(c) && str(pick(c, "channel", "name"))) {
        out.push({
          channel: str(pick(c, "channel", "name"))!,
          configured: bool(c.configured) ?? true,
          detail: str(c.detail),
        });
      }
    }
    return out;
  }
  if (isObj(v)) {
    // {"slack": true, "telegram": false, ...}
    return Object.entries(v)
      .filter(([, x]) => typeof x === "boolean")
      .map(([k, x]) => ({ channel: k, configured: x as boolean, detail: null }));
  }
  return null;
}

/** The channels the API reports as configured (in-app always counts); null when it does not report them. */
export function externalChannels(chs: ChannelInfo[] | null): ChannelInfo[] | null {
  if (!chs) return null;
  return chs.filter((c) => c.configured && !/^(in[-_ ]?app|inapp|ui)$/i.test(c.channel));
}

export function parsePages(raw: unknown): PagesList {
  const { rows, env } = listOf(raw, "GET /api/pages", "pages");
  return {
    ...query(env, null),
    rows: rows.map(parsePage).filter((x): x is PageRow => x !== null),
    channels: channels(env.channels),
    truncated: bool(env.truncated) ?? false,
  };
}

export function parseOnCallNow(raw: unknown): OnCallNow {
  const { rows, env } = listOf(raw, "GET /api/oncall/now", "oncall", "teams");
  const out: OnCallRow[] = [];
  for (const r of rows) {
    if (!isObj(r)) continue;
    const team = isObj(r.team) ? str(r.team.id) : str(r.team);
    if (!team) continue;
    out.push({
      team,
      teamName: str(pick(r, "team_name")) ?? (isObj(r.team) ? str(r.team.name) : null),
      person: person(pick(r, "person", "person_id"), pick(r, "person_name", "name")),
      from: toMs(r.from),
      to: toMs(r.to),
    });
  }
  return { ...query(env, "Q-ONCALL-NOW"), rows: out, at: toMs(pick(env, "at", "now")) };
}

function whoFixes(v: unknown): WhoFixesPerson[] {
  const rows = Array.isArray(v) ? v : isObj(v) && Array.isArray(v.rows) ? v.rows : [];
  const out: WhoFixesPerson[] = [];
  for (const r of rows) {
    if (!isObj(r)) {
      const p = person(r);
      if (p) out.push({ person: p, score: null, reasons: [] });
      continue;
    }
    const p = person(pick(r, "person", "id"), r.name);
    if (p) out.push({ person: p, score: num(r.score), reasons: strings(r.reasons) });
  }
  return out;
}

function proof(v: unknown): ProofChain | null {
  if (Array.isArray(v)) {
    const nodes = v.map((x) => (isObj(x) ? str(pick(x, "id", "node")) : str(x))).filter((x): x is string => x !== null);
    return nodes.length ? { nodes, rels: [], query: null } : null;
  }
  if (isObj(v)) {
    const nodes = strings(pick(v, "nodes", "path", "chain"));
    if (!nodes.length) return null;
    return { nodes, rels: strings(pick(v, "rels", "relationships", "edges")), query: str(v.template) ? query(v, null) : null };
  }
  return null;
}

export function parsePageDetail(raw: unknown): PageDetail {
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/pages/{id}: expected an object", 200, "page");
  raw = oneRow(raw);
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/pages/{id}", 200, "page");
  const parsed = parsePage(isObj(raw.page) ? raw.page : raw);
  if (!parsed) throw new ApiError("GET /api/pages/{id} returned no page id", 200, "page");
  const page = parsed.ackToken ? parsed : { ...parsed, ackToken: str(raw.ack_token) };
  const inc = raw.incident;
  const incident = isObj(inc)
    ? {
        id: str(inc.id) ?? page.incident ?? "",
        title: str(inc.title),
        line: str(pick(inc, "line", "one_liner", "summary", "verdict")),
        stage: str(inc.stage) ?? page.incidentStage,
        cause: str(inc.cause),
      }
    : page.incident
      ? { id: page.incident, title: page.incidentTitle, line: str(pick(raw, "line", "one_liner", "verdict")), stage: page.incidentStage, cause: null }
      : null;
  const wf = pick(raw, "who_fixes", "whoFixes");
  const ch = pick(raw, "chain", "escalation");
  const obl = isObj(raw.obligations) ? raw.obligations : null;
  const breach = obl && isObj(obl.breach) ? obl.breach : isObj(raw.breach) ? raw.breach : null;
  return {
    page,
    incident: incident && incident.id ? incident : null,
    proof: proof(pick(raw, "proof", "proof_chain", "path")),
    whoFixes: whoFixes(wf),
    whoFixesQuery: isObj(wf) && str(wf.template) ? query(wf, null) : null,
    chain: chainOf(isObj(ch) ? ch.rows : ch) ?? page.chain ?? [],
    chainQuery: isObj(ch) && str(ch.template) ? query(ch, null) : { template: "Q-PAGE-CHAIN", params: null, ms: null },
    breachInMin: num(pick(raw, "breach_in_min")) ?? (breach ? num(breach.breach_in_min) : null),
    breachSlo: breach ? str(breach.slo) : null,
  };
}

export function parseContract(v: unknown): Contract | null {
  if (!isObj(v)) return null;
  const id = str(v.id);
  if (!id) return null;
  const used = Array.isArray(v.used_in) ? v.used_in : [];
  return {
    id,
    family: str(v.family),
    actionKind: str(pick(v, "action_kind", "action")),
    paramsHash: str(v.params_hash),
    maxUses: num(v.max_uses),
    uses: num(v.uses),
    expiresAt: toMs(v.expires_at),
    grantedAt: toMs(v.granted_at),
    status: str(v.status),
    quote: str(v.quote),
    grantedBy: person(v.granted_by, v.granted_by_name),
    covers: str(v.covers),
    sourceIncident: str(v.source_incident),
    revokedAt: toMs(v.revoked_at),
    revokedBy: str(v.revoked_by),
    usedIn: used
      .map((u) => (isObj(u) && str(u.incident) ? { incident: str(u.incident)!, at: toMs(u.at), verdict: str(u.verdict) } : null))
      .filter((x): x is ContractUse => x !== null),
  };
}

export function parseContracts(raw: unknown): ContractsList {
  const { rows, env } = listOf(raw, "GET /api/contracts", "contracts");
  return { ...query(env, null), rows: rows.map(parseContract).filter((x): x is Contract => x !== null) };
}

export function parseContractQuote(raw: unknown): ContractQuote {
  if (!isObj(raw)) throw new ApiError("unexpected response for the contract choose step", 200, "contract");
  if (isObj(raw.contract) && !str(raw.hash)) raw = { ...raw, ...raw.contract };
  if (!isObj(raw)) throw new ApiError("unexpected response for the contract choose step", 200, "contract");
  const hash = str(pick(raw, "hash", "plan_hash", "contract_hash"));
  if (!hash) throw new ApiError("the contract choose step returned no hash: nothing to approve", 200, "contract");
  const scope = isObj(raw.scope) ? raw.scope : {};
  return {
    id: str(pick(raw, "id", "contract", "contract_id")),
    hash,
    offerExpiresAt: toMs(raw.offer_expires_at),
    quote: str(raw.quote),
    option: str(raw.option),
    maxUses: num(pick(scope, "max_uses")) ?? num(raw.max_uses),
    days: num(pick(scope, "days")) ?? num(raw.days),
    family: str(pick(scope, "family")) ?? str(raw.family),
    actionKind: str(pick(scope, "action_kind")) ?? str(raw.action_kind),
    paramsHash: str(pick(scope, "params_hash")) ?? str(raw.params_hash),
    expiresAt: toMs(pick(scope, "expires_at")) ?? toMs(raw.expires_at),
  };
}

function reportItem(v: unknown): ReportItem | null {
  if (!isObj(v)) {
    const s = str(v);
    return s ? { id: s, title: null, status: null, who: null, at: null, incident: null, raw: { id: s } } : null;
  }
  const who = pick(v, "name", "to_name", "person_name", "person", "by", "to", "approver", "from");
  return {
    id: str(pick(v, "id", "page", "action", "contract")),
    title: str(pick(v, "title", "summary", "note", "option", "line", "family", "kind")),
    status: str(pick(v, "status", "verdict", "outcome", "stage")),
    who: isObj(who) ? str(pick(who, "name", "id")) : str(who),
    at: toMs(pick(v, "at", "sent_at", "opened_at", "acked_at", "started_at")),
    incident: isObj(v.incident) ? str(v.incident.id) : str(v.incident),
    raw: v,
  };
}

export function parseReport(raw: unknown): ShiftReport {
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/oncall/report: expected an object", 200, "report");
  raw = oneRow(raw);
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/oncall/report", 200, "report");
  const countsRaw = isObj(raw.counts) ? raw.counts : {};
  const counts = {} as Record<ReportSection, number | null>;
  const sections = {} as Record<ReportSection, ReportItem[] | null>;
  for (const { key } of REPORT_SECTIONS) {
    const list = raw[key];
    sections[key] = Array.isArray(list) ? list.map(reportItem).filter((x): x is ReportItem => x !== null) : null;
    counts[key] = num(countsRaw[key]) ?? num(raw[`${key}_count`]) ?? (sections[key] ? sections[key]!.length : null);
  }
  const win = isObj(raw.window) ? raw.window : raw;
  const params = isObj(raw.params) ? raw.params : {};
  return {
    ...query(raw, "Q-SHIFT-REPORT"),
    // the window the server read: its own fields, else the params it ran Q-SHIFT-REPORT with
    from: toMs(win.from) ?? toMs(params.from),
    to: toMs(win.to) ?? toMs(params.to),
    counts,
    sections,
    summary: str(pick(raw, "summary", "text")),
  };
}

/** A duration in ms from `<key>_ms`, `<key>_s` or `<key>_min` (whichever the server sent). */
function duration(o: Obj, key: string): number | null {
  const v = isObj(o[key]) ? (o[key] as Obj) : null;
  const ms = num(o[`${key}_ms`]) ?? (v ? num(v.ms) : null);
  if (ms !== null) return ms;
  const s = num(o[`${key}_s`]) ?? num(o[`${key}_sec`]) ?? (v ? num(v.s) : null);
  if (s !== null) return s * 1000;
  const m = num(o[`${key}_min`]) ?? (v ? num(v.min) : null);
  return m !== null ? m * 60_000 : null;
}

export function parseStats(raw: unknown): OnCallStats {
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/oncall/stats: expected an object", 200, "stats");
  const flat = oneRow(raw);
  const o = isObj(flat.stats) ? { ...flat, ...flat.stats } : flat;
  // Q-ONCALL-STATS returns sums and counts; the server's own means win when it sends them (display arithmetic only)
  const mean = (sum: unknown, n: unknown) => {
    const a = num(sum);
    const b = num(n);
    return a !== null && b !== null && b > 0 ? a / b : null;
  };
  return {
    ...query(raw, "Q-ONCALL-STATS"),
    days: num(o.days),
    mttaMs: duration(o, "mtta") ?? mean(o.ack_ms_sum, o.acked_incidents),
    mttrMs: duration(o, "mttr") ?? mean(o.resolve_ms_sum, o.resolved_incidents),
    peoplePaged:
      num(pick(o, "people_paged", "people_woken", "woken", "humans_woken")) ?? (Array.isArray(o.people) ? o.people.length : num(o.people)),
    handledUnderContract: num(pick(o, "handled_under_contract", "handled_while_asleep", "contract_handled", "under_contract")),
    pages: num(pick(o, "pages", "pages_sent")),
    incidents: num(pick(o, "incidents", "incidents_paged")),
  };
}

// ------------------------------------------------------------------ client

const enc = encodeURIComponent;
const q = (tenant: string) => `tenant=${enc(tenant)}`;
const keyHeader = (key?: string): Record<string, string> => (key ? { "X-Faultline-Approver-Key": key } : {});

export const oncallApi = {
  async now(tenant: string, signal?: AbortSignal): Promise<OnCallNow> {
    return parseOnCallNow(await apiRequest<unknown>("oncall-now", `/api/oncall/now?${q(tenant)}`, { signal }));
  },

  async pages(opts: { tenant: string; status?: string; incident?: string }, signal?: AbortSignal): Promise<PagesList> {
    const st = opts.status ? `&status=${enc(opts.status)}` : "";
    const inc = opts.incident ? `&incident=${enc(opts.incident)}` : "";
    return parsePages(await apiRequest<unknown>("pages", `/api/pages?${q(opts.tenant)}${st}${inc}`, { signal }));
  },

  async page(id: string, tenant: string, signal?: AbortSignal): Promise<PageDetail> {
    return parsePageDetail(await apiRequest<unknown>("page", `/api/pages/${enc(id)}?${q(tenant)}`, { signal }));
  },

  /**
   * Ack with the page's signed token (the link's `?t=`, or the one the server handed this console), else with this
   * tab's run token for the incident, else with the approver key (sent only when typed, never stored).
   */
  ack(id: string, tenant: string, token?: string | null, approverKey?: string, incident?: string | null): Promise<unknown> {
    return apiRequest<unknown>("page-ack", `/api/pages/${enc(id)}/ack?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify(token ? { token } : {}),
      headers: { ...(!token && incident ? tokenHeader(incident) : {}), ...keyHeader(approverKey) },
    });
  },

  async contracts(tenant: string, signal?: AbortSignal): Promise<ContractsList> {
    return parseContracts(await apiRequest<unknown>("contracts", `/api/contracts?${q(tenant)}`, { signal }));
  },

  revokeContract(id: string, tenant: string, approverKey?: string): Promise<unknown> {
    return apiRequest<unknown>("contract-revoke", `/api/contracts/${enc(id)}/revoke?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({}),
      headers: keyHeader(approverKey),
    });
  },

  /** Contract step 1: the scope the human picked → the exact grant and its hash (nothing is written). */
  async contractChoose(
    inc: string,
    scope: { max_uses: number; days: number },
    tenant: string,
    actionId?: string | null,
  ): Promise<ContractQuote> {
    await ensureRunToken(inc);
    const raw = await apiRequest<unknown>("contract", `/api/incidents/${enc(inc)}/contract?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({ step: "choose", scope, ...(actionId ? { action_id: actionId } : {}) }),
      headers: tokenHeader(inc),
    });
    return parseContractQuote(raw);
  },

  /** Contract step 2: approve exactly that hash (409 when the scope or the incident changed since). */
  async contractApprove(
    inc: string,
    body: { hash: string; approver: string },
    approverKey: string | undefined,
    tenant: string,
  ): Promise<Contract | null> {
    await ensureRunToken(inc);
    const raw = await apiRequest<unknown>("contract", `/api/incidents/${enc(inc)}/contract?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify({
        step: "approve",
        hash: body.hash,
        approver: body.approver,
        ...(approverKey ? { approver_key: approverKey } : {}),
      }),
      headers: { ...tokenHeader(inc), ...keyHeader(approverKey) },
    });
    return parseContract(isObj(raw) && isObj(raw.contract) ? raw.contract : raw);
  },

  async report(tenant: string, from: EpochMs, to: EpochMs, signal?: AbortSignal): Promise<ShiftReport> {
    return parseReport(
      await apiRequest<unknown>("oncall-report", `/api/oncall/report?${q(tenant)}&from=${Math.round(from)}&to=${Math.round(to)}`, { signal }),
    );
  },

  /** `from` defaults (server side) to who is on call now for the incoming person's team; the key only on the public demo. */
  async handoff(body: { note: string; to: string; incident?: string; from?: string }, tenant: string, approverKey?: string): Promise<HandoffResult> {
    const raw = await apiRequest<unknown>("handoff", `/api/handoffs?${q(tenant)}`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: keyHeader(approverKey),
    });
    const o = isObj(raw) && isObj(raw.handoff) ? raw.handoff : raw;
    const id = isObj(o) ? str(o.id) : null;
    if (!id || !isObj(o)) throw new ApiError("POST /api/handoffs returned no hand-off id", 200, "handoff");
    return { id, at: toMs(o.at) };
  },

  async stats(tenant: string, days: number, signal?: AbortSignal): Promise<OnCallStats> {
    return parseStats(await apiRequest<unknown>("oncall-stats", `/api/oncall/stats?${q(tenant)}&days=${days}`, { signal }));
  },
};

// ------------------------------------------------------------------ error wording

/** True when the route itself does not exist on this API (FastAPI's bare 404/405), not "unknown id". */
export function endpointMissing(err: unknown): boolean {
  return err instanceof ApiError && ((err.status === 404 && /^not found$/i.test(err.detail.trim())) || err.status === 405);
}

/** One honest sentence for a failed on-call read. */
export function oncallErrorText(err: unknown, what: string): string {
  const W = what.charAt(0).toUpperCase() + what.slice(1);
  if (!(err instanceof ApiError)) return `${W} failed: ${err instanceof Error ? err.message : String(err)}`;
  if (endpointMissing(err)) return `${W}: this API has no such endpoint (HTTP ${err.status}), so the on-call backend is not deployed on this server.`;
  if (err.status === null) return `${W} unavailable: ${err.detail.replace(/\.$/, "")}.`;
  return `${W} failed: ${err.detail.replace(/\.$/, "")} (HTTP ${err.status}).`;
}

// ------------------------------------------------------------------ display words (pure)

export const PAGE_STATUS_TEXT: Record<PageStatus, string> = {
  sent: "awaiting ack",
  delivery_failed: "delivery failed",
  acked: "acked",
  escalated: "escalated",
  resolved: "resolved",
  superseded: "superseded",
};

export const CHANNEL_TEXT: Record<string, string> = {
  in_app: "in-app",
  inapp: "in-app",
  "in-app": "in-app",
  slack: "Slack",
  webhook: "Slack webhook",
  telegram: "Telegram",
  pagerduty: "PagerDuty",
  email: "email",
  ses: "email (SES)",
};

/** Pages a human still has to ack (the server's statuses; "escalated" pages were handed to the next person). */
export function needsAck(p: Pick<PageRow, "status" | "kind">): boolean {
  return (p.status === "sent" || p.status === "delivery_failed") && p.kind !== "contract_notice" && p.kind !== "report";
}

/** "3 min", "1 h 20 min", "2 d 4 h" for a non-negative duration; "–" for null. */
export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "–";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 && m < 10 ? `${m} min ${s % 60} s` : `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
}

/** "m:ss" for a countdown under an hour, else fmtDuration. */
export function fmtCountdown(ms: number): string {
  if (ms < 0) return fmtDuration(-ms);
  const s = Math.floor(ms / 1000);
  if (s >= 3600) return fmtDuration(ms);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function personText(p: PersonRef | null | undefined): string {
  if (!p) return "–";
  return p.name ? `${p.name} (${p.id})` : p.id;
}

/** "Fri 17 Oct, 14:05" in the viewer's zone: short enough for a phone row; "–" for null. */
export function fmtWhen(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  return new Date(ms).toLocaleString(undefined, { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
