import { ApiError, apiRequest } from "./api";
import type { EpochMs } from "./types";

/**
 * Typed client for FalkorDB observing itself (M20, docs/API.md "Engine insight"): GET /api/engine/insight returns, per
 * graph of the tenant, GRAPH.MEMORY USAGE and the engine's own telemetry stream (telemetry{graph}) aggregated per
 * template or writer id, plus engine load (GRAPH.INFO) and limits (GRAPH.CONFIG). Ids, timings and flags only: the
 * server never sends query text or parameters. Nothing here invents a value: a missing number stays null ("–").
 */

export interface QueryStats {
  n: number;
  totalP50: number | null;
  totalP95: number | null;
  waitP50: number | null;
  waitP95: number | null;
  execP50: number | null;
  execP95: number | null;
  reportP50: number | null;
  cachePct: number | null;
  writes: number | null;
  timeouts: number | null;
}

/** One template (Q-…) or writer (W-…) id in the stream window. */
export interface QueryRow extends QueryStats {
  id: string;
  kind: "template" | "write" | null;
}

export interface RecentQuery {
  /** Epoch ms: the stream entry id's millisecond when the server sends it (`at_ms`), else "Received at" (whole s). */
  at: EpochMs | null;
  id: string;
  kind: "template" | "write" | null;
  totalMs: number | null;
  waitMs: number | null;
  execMs: number | null;
  reportMs: number | null;
  cache: boolean | null;
  write: boolean | null;
  timeout: boolean | null;
  /** The graph whose stream recorded it. */
  graph: string;
}

export interface Telemetry {
  entries: number;
  from: EpochMs | null;
  to: EpochMs | null;
  /** p50 / p95 total ms over every entry of the window, mapped or not (computed by the server over the entries). */
  overallP50: number | null;
  overallP95: number | null;
  queries: QueryRow[];
  /** Ad-hoc / dynamic queries (guarded text2cypher, the official MCP server, operators): counted, never shown. */
  unmapped: QueryStats;
  recent: RecentQuery[];
}

/** GRAPH.MEMORY USAGE as the engine reports it: whole megabytes. */
export interface GraphMemory {
  totalMb: number | null;
  labelMatricesMb: number | null;
  relationMatricesMb: number | null;
  nodeBlockMb: number | null;
  nodeAttributesMb: number | null;
  edgeAttributesMb: number | null;
  indicesMb: number | null;
  /** Per label / relationship type (MB), largest first. */
  byLabel: { name: string; mb: number }[];
  byType: { name: string; mb: number }[];
}

export type GraphRole = "tenant" | "golden" | "oncall" | "audit" | "room" | "other";

/** The declared engine-enforced invariants (graph/constraints.py) the engine reports on one graph (db.constraints). */
export interface GraphConstraints {
  declared: number;
  operational: number;
  pending: number;
  missing: number;
  /** False for the append-only audit log, which carries no schema (so 0 there is expected, not a failure). */
  expected: boolean;
}

export interface GraphInsight {
  name: string;
  role: GraphRole;
  memory: GraphMemory;
  telemetry: Telemetry;
  /** null: not reported (an older server, or the engine refused the read): never shown as enforced. */
  constraints: GraphConstraints | null;
}

export interface EngineConfig {
  queryMemCapacity: number | null;
  timeoutMax: number | null;
  timeoutDefault: number | null;
  maxQueuedQueries: number | null;
  cacheSize: number | null;
  maxInfoQueries: number | null;
  threadCount: number | null;
}

export interface EngineInsight {
  tenant: string;
  /** The pinned engine (graph/algo/resolved.json); null from a server that does not send it. */
  engine: { version: string | null; digest: string | null } | null;
  load: { running: number | null; waiting: number | null };
  config: EngineConfig;
  roomsNotReported: number;
  source: string | null;
  privacy: string | null;
  graphs: GraphInsight[];
  /** The same aggregation over every graph above; `recent` is the server's merge of the graphs' streams (newest 20,
   * to the millisecond), null from a server that does not send it (the tail then merges the graphs' own). */
  templates: Omit<Telemetry, "recent"> & { recent: RecentQuery[] | null };
}

// ------------------------------------------------------------------ readers (never invent a value)

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  return null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

function bool(v: unknown): boolean | null {
  return typeof v === "boolean" ? v : null;
}

/** Epoch seconds (the stream's "Received at") or ms → ms. */
function secs(v: unknown): EpochMs | null {
  const n = num(v);
  if (n === null) return null;
  return n < 1e11 ? n * 1000 : n;
}

function kindOf(v: unknown): QueryRow["kind"] {
  return v === "template" || v === "write" ? v : null;
}

function stats(o: Obj): QueryStats {
  return {
    n: num(o.n) ?? 0,
    totalP50: num(o.total_ms_p50),
    totalP95: num(o.total_ms_p95),
    waitP50: num(o.wait_ms_p50),
    waitP95: num(o.wait_ms_p95),
    execP50: num(o.exec_ms_p50),
    execP95: num(o.exec_ms_p95),
    reportP50: num(o.report_ms_p50),
    cachePct: num(o.cache_pct),
    writes: num(o.writes),
    timeouts: num(o.timeouts),
  };
}

function recentList(raw: unknown, graph: string): RecentQuery[] {
  return (Array.isArray(raw) ? raw : []).filter(isObj).flatMap((r) => {
    const id = str(r.id);
    return id
      ? [
          {
            at: secs(r.at_ms) ?? secs(r.at),
            id,
            kind: kindOf(r.kind),
            totalMs: num(r.total_ms),
            waitMs: num(r.wait_ms),
            execMs: num(r.exec_ms),
            reportMs: num(r.report_ms),
            cache: bool(r.cache),
            write: bool(r.write),
            timeout: bool(r.timeout),
            graph: str(r.graph) ?? graph,
          },
        ]
      : [];
  });
}

function constraintsOf(v: unknown): GraphConstraints | null {
  if (!isObj(v)) return null;
  const declared = num(v.declared);
  const operational = num(v.operational);
  if (declared === null || operational === null) return null;
  return { declared, operational, pending: num(v.pending) ?? 0, missing: num(v.missing) ?? 0, expected: v.expected !== false };
}

function telemetry(raw: unknown, graph: string): Telemetry {
  const t = isObj(raw) ? raw : {};
  const queries = (Array.isArray(t.queries) ? t.queries : [])
    .filter(isObj)
    .flatMap((q) => {
      const id = str(q.id);
      return id ? [{ id, kind: kindOf(q.kind), ...stats(q) }] : [];
    });
  return {
    entries: num(t.entries) ?? 0,
    from: secs(t.from),
    to: secs(t.to),
    overallP50: num(t.total_ms_p50),
    overallP95: num(t.total_ms_p95),
    queries,
    unmapped: stats(isObj(t.unmapped) ? t.unmapped : {}),
    recent: recentList(t.recent, graph),
  };
}

function breakdown(v: unknown): { name: string; mb: number }[] {
  if (!isObj(v)) return [];
  return Object.entries(v)
    .map(([name, mb]) => ({ name, mb: num(mb) }))
    .filter((x): x is { name: string; mb: number } => x.mb !== null)
    .sort((a, b) => b.mb - a.mb || a.name.localeCompare(b.name));
}

const sumOf = (xs: { mb: number }[]): number | null => (xs.length ? xs.reduce((a, x) => a + x.mb, 0) : null);

function memory(raw: unknown, total: unknown): GraphMemory {
  const m = isObj(raw) ? raw : {};
  const byLabel = breakdown(m.amortized_node_attributes_by_label_sz_mb);
  const byType = breakdown(m.amortized_edge_attributes_by_type_sz_mb);
  return {
    totalMb: num(total) ?? num(m.total_graph_sz_mb),
    labelMatricesMb: num(m.label_matrices_sz_mb),
    relationMatricesMb: num(m.relation_matrices_sz_mb),
    nodeBlockMb: num(m.amortized_node_block_sz_mb),
    nodeAttributesMb: sumOf(byLabel),
    edgeAttributesMb: sumOf(byType),
    indicesMb: num(m.indices_sz_mb),
    byLabel,
    byType,
  };
}

export function graphRole(name: string, tenant: string): GraphRole {
  if (name === `tenant_${tenant}`) return "tenant";
  if (name.startsWith(`golden_${tenant}`)) return "golden";
  if (name === `oncall_${tenant}`) return "oncall";
  if (name === `audit_${tenant}`) return "audit";
  if (name.startsWith(`eval_${tenant}_`)) return "room";
  return "other";
}

const ROLE_ORDER: Record<GraphRole, number> = { tenant: 0, golden: 1, oncall: 2, audit: 3, room: 4, other: 5 };

export function parseInsight(raw: unknown): EngineInsight {
  if (!isObj(raw)) throw new ApiError("unexpected response for GET /api/engine/insight: expected an object", 200, "engine-insight");
  if (!isObj(raw.graphs) || !isObj(raw.templates)) {
    throw new ApiError("unexpected response for GET /api/engine/insight: no graphs or templates", 200, "engine-insight");
  }
  const tenant = str(raw.tenant) ?? "";
  const cfg = isObj(raw.config) ? raw.config : {};
  const load = isObj(raw.load) ? raw.load : {};
  const graphs = Object.entries(raw.graphs)
    .filter(([, v]) => isObj(v))
    .map(([name, v]) => {
      const g = v as Obj;
      return {
        name,
        role: graphRole(name, tenant),
        memory: memory(g.memory, g.memory_mb),
        telemetry: telemetry(g.telemetry, name),
        constraints: constraintsOf(g.constraints),
      };
    })
    .sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || a.name.localeCompare(b.name));
  const all = telemetry(raw.templates, "");
  const eng = isObj(raw.engine) ? raw.engine : null;
  return {
    tenant,
    engine: eng ? { version: str(eng.version), digest: str(eng.digest) } : null,
    load: { running: num(load.running), waiting: num(load.waiting) },
    config: {
      queryMemCapacity: num(cfg.QUERY_MEM_CAPACITY),
      timeoutMax: num(cfg.TIMEOUT_MAX),
      timeoutDefault: num(cfg.TIMEOUT_DEFAULT),
      maxQueuedQueries: num(cfg.MAX_QUEUED_QUERIES),
      cacheSize: num(cfg.CACHE_SIZE),
      maxInfoQueries: num(cfg.MAX_INFO_QUERIES),
      threadCount: num(cfg.THREAD_COUNT),
    },
    roomsNotReported: num(raw.rooms_not_reported) ?? 0,
    source: str(raw.source),
    privacy: str(raw.privacy),
    graphs,
    templates: {
      entries: all.entries,
      from: all.from,
      to: all.to,
      overallP50: all.overallP50,
      overallP95: all.overallP95,
      queries: all.queries,
      unmapped: all.unmapped,
      recent: Array.isArray(raw.templates.recent) ? all.recent : null,
    },
  };
}

export const engineApi = {
  async insight(tenant: string, signal?: AbortSignal): Promise<EngineInsight> {
    return parseInsight(await apiRequest<unknown>("engine-insight", `/api/engine/insight?tenant=${encodeURIComponent(tenant)}`, { signal }));
  },
};

// ------------------------------------------------------------------ derived for display (pure; arithmetic on server numbers)

/** The newest `n` recorded queries over all graphs (each graph's stream keeps its own; merged by time, newest first). */
export function mergeRecent(graphs: GraphInsight[], n = 20): RecentQuery[] {
  return graphs
    .flatMap((g) => g.telemetry.recent)
    .map((r, i) => ({ r, i }))
    .sort((a, b) => (b.r.at ?? 0) - (a.r.at ?? 0) || a.i - b.i)
    .slice(0, n)
    .map((x) => x.r);
}

/** The live tail's rows: the server's own merge across graphs when it sends one, else each graph's list merged here. */
export function tailRows(d: EngineInsight, n = 20): RecentQuery[] {
  return d.templates.recent ? d.templates.recent.slice(0, n) : mergeRecent(d.graphs, n);
}

/** Constraints over the graphs that are expected to carry them (the audit log is not): the fewest enforced on any of
 * them, and the graphs below the declared count. null when no graph reported its constraints. */
export function constraintSummary(graphs: GraphInsight[]) {
  const withC = graphs.filter((g) => g.constraints?.expected);
  if (!withC.length) return null;
  const declared = Math.max(...withC.map((g) => g.constraints!.declared));
  const enforced = Math.min(...withC.map((g) => g.constraints!.operational));
  const short = withC.filter((g) => g.constraints!.operational < g.constraints!.declared).map((g) => g.name);
  const unreported = graphs.filter((g) => g.constraints === null).map((g) => g.name);
  return { declared, enforced, graphs: withC.length, short, unreported, notExpected: graphs.filter((g) => g.constraints && !g.constraints.expected).map((g) => g.name) };
}

/** The verdict line's numbers, all from the response (sums of counts; no percentile is combined across ids: the
 * overall p50 / p95 are the server's, over the entries). */
export function insightSummary(d: EngineInsight) {
  const t = d.templates;
  const rows = t.queries;
  const memory = d.graphs.reduce<number | null>((a, g) => (g.memory.totalMb === null ? a : (a ?? 0) + g.memory.totalMb), null);
  const timeouts = rows.reduce((a, r) => a + (r.timeouts ?? 0), 0) + (t.unmapped.timeouts ?? 0);
  const writes = rows.reduce((a, r) => a + (r.writes ?? 0), 0) + (t.unmapped.writes ?? 0);
  const busiest = rows.find((r) => r.kind === "template") ?? null;
  const reads = rows.filter((r) => r.kind === "template");
  const slowest = reads.reduce<QueryRow | null>((m, r) => (r.totalP95 !== null && (m === null || (m.totalP95 ?? 0) < r.totalP95) ? r : m), null);
  // plan-cache hits over every mapped and unmapped entry: cache_pct × n summed (each id's % is rounded to 0.1)
  const cached = rows.reduce((a, r) => a + ((r.cachePct ?? 0) * r.n) / 100, 0) + ((t.unmapped.cachePct ?? 0) * t.unmapped.n) / 100;
  const cachePct = t.entries ? (100 * cached) / t.entries : null;
  return {
    graphs: d.graphs.length,
    memoryMb: memory,
    entries: t.entries,
    windowMs: t.from !== null && t.to !== null ? t.to - t.from : null,
    timeouts,
    writes,
    busiest,
    slowest,
    cachePct,
    ids: rows.length,
    overallP50: t.overallP50,
    overallP95: t.overallP95,
  };
}

export const ROLE_TEXT: Record<GraphRole, string> = {
  tenant: "live tenant graph",
  golden: "golden copy",
  oncall: "on-call home",
  audit: "audit log",
  room: "clean room (GRAPH.COPY)",
  other: "graph",
};

/** "256 MB" for a byte count; "–" for null. */
export function fmtBytes(b: number | null): string {
  if (b === null) return "–";
  if (b >= 1024 ** 3) return `${+(b / 1024 ** 3).toFixed(1)} GB`;
  if (b >= 1024 ** 2) return `${+(b / 1024 ** 2).toFixed(1)} MB`;
  if (b >= 1024) return `${+(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

/** Engine durations: "0.15 ms", "12.3 ms", "1.24 s"; "–" for null. */
export function fmtEngineMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  if (ms >= 1000) return `${+(ms / 1000).toFixed(2)} s`;
  if (ms >= 10) return `${ms.toFixed(1)} ms`;
  if (ms >= 1) return `${ms.toFixed(2)} ms`;
  return `${ms < 0.01 ? ms.toFixed(3) : ms.toFixed(2)} ms`;
}

/** "2 h 29 min" for a window; "–" for null. */
export function fmtWindow(ms: number | null): string {
  if (ms === null || ms < 0) return "–";
  const m = Math.round(ms / 60_000);
  if (m < 1) return `${Math.round(ms / 1000)} s`;
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}
