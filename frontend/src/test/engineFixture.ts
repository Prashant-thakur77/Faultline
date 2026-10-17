/**
 * GET /api/engine/insight, shaped exactly as docs/API.md "Engine insight" documents it. Test-only: production code never
 * renders it.
 */
const stats = (n: number, p50: number, p95: number, cache: number, extra: Record<string, number> = {}) => ({
  n,
  total_ms_p50: p50,
  total_ms_p95: p95,
  wait_ms_p50: 0.015,
  wait_ms_p95: 0.13,
  exec_ms_p50: 0.025,
  exec_ms_p95: 0.053,
  report_ms_p50: 0.1,
  cache_pct: cache,
  writes: 0,
  timeouts: 0,
  ...extra,
});

const recent = (at: number, id: string, kind: "template" | "write", total: number, cache = false) => ({
  at,
  id,
  kind,
  total_ms: total,
  wait_ms: 0.07,
  exec_ms: 0.3,
  report_ms: total - 0.37,
  cache,
  write: kind === "write",
  timeout: false,
});

export const INSIGHT = {
  tenant: "acme",
  load: { running: 0, waiting: 0 },
  config: {
    QUERY_MEM_CAPACITY: 268435456,
    TIMEOUT_MAX: 10000,
    TIMEOUT_DEFAULT: 2000,
    MAX_QUEUED_QUERIES: 50,
    CACHE_SIZE: 25,
    MAX_INFO_QUERIES: 1000,
    THREAD_COUNT: 20,
  },
  rooms_not_reported: 0,
  source: "GRAPH.MEMORY USAGE + the engine's telemetry{graph} stream (FalkorDB 6.0)",
  privacy: "template and writer ids, timings and flags only; no query text, no parameters",
  graphs: {
    tenant_acme: {
      memory_mb: 2,
      memory: {
        total_graph_sz_mb: 2,
        label_matrices_sz_mb: 0,
        relation_matrices_sz_mb: 0,
        amortized_node_block_sz_mb: 0,
        amortized_node_attributes_by_label_sz_mb: { Node: 1, Service: 0 },
        amortized_edge_attributes_by_type_sz_mb: { PROPAGATES_TO: 0 },
        indices_sz_mb: 0,
      },
      telemetry: {
        entries: 1000,
        from: 1792245970,
        to: 1792252973,
        queries: [
          { id: "Q-META-1", kind: "template", ...stats(58, 0.15, 0.38, 15.5) },
          { id: "W-STAGE", kind: "write", ...stats(12, 0.9, 4.1, 80, { writes: 12 }) },
        ],
        unmapped: stats(225, 0.29, 3.9, 40),
        recent: [recent(1792252973, "Q-ONCALL-NOW", "template", 0.94), recent(1792252970, "W-STAGE", "write", 1.2, true)],
      },
    },
    eval_acme_api_v2_s1_1_abcd: {
      memory_mb: 3,
      memory: {
        total_graph_sz_mb: 3,
        label_matrices_sz_mb: 1,
        relation_matrices_sz_mb: 0,
        amortized_node_block_sz_mb: 0,
        amortized_node_attributes_by_label_sz_mb: { Node: 1 },
        amortized_edge_attributes_by_type_sz_mb: { PROPAGATES_TO: 0 },
        indices_sz_mb: 0,
      },
      telemetry: {
        entries: 400,
        from: 1792250000,
        to: 1792252980,
        queries: [{ id: "Q-INC-1", kind: "template", ...stats(40, 0.6, 1.2, 50) }],
        unmapped: { n: 0 },
        recent: [recent(1792252980, "Q-INC-1", "template", 0.55)],
      },
    },
    golden_acme: {
      memory_mb: 2,
      memory: { total_graph_sz_mb: 2, label_matrices_sz_mb: 0, relation_matrices_sz_mb: 0, amortized_node_block_sz_mb: 0, indices_sz_mb: 0 },
      telemetry: { entries: 0, from: null, to: null, queries: [], unmapped: { n: 0 }, recent: [] },
    },
  },
  templates: {
    entries: 1400,
    from: 1792245970,
    to: 1792252980,
    queries: [
      { id: "Q-META-1", kind: "template", ...stats(58, 0.15, 0.38, 15.5) },
      { id: "Q-INC-1", kind: "template", ...stats(40, 0.6, 1.2, 50) },
      { id: "W-STAGE", kind: "write", ...stats(12, 0.9, 4.1, 80, { writes: 12 }) },
    ],
    unmapped: stats(225, 0.29, 3.9, 40),
  },
};
