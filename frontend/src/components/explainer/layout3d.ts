/**
 * The explainer's fixed, committed 3D layout for the hero tenant's incident graph, so every run (and every recorded
 * frame of the video) looks identical. Display only: positions answer no graph question; who reaches whom comes
 * from FalkorDB's recorded results. Failure flows left to right: the suspect deploys on the far left, the services
 * they changed, checkout in the middle, what it feeds on the right, the warehouse lineage along the floor.
 * An id that is not listed (a re-exported graph) gets a deterministic place on an outer ring, never a random one.
 */
export type V3 = [number, number, number];

export const LAYOUT: Record<string, V3> = {
  // suspect deploys (CHANGED)
  "D-rec-12": [-4.7, 1.75, 0.35],
  "D-email-88": [-4.75, 0.3, -0.2],
  "D-pay-417": [-4.7, -1.15, 0.4],
  // the services they changed
  recommendation: [-2.75, 2.05, 0.1],
  email: [-2.6, 0.35, -0.45],
  payment: [-2.55, -1.05, 0.35],
  // checkout's other upstreams
  "product-catalog": [-1.55, 2.75, -0.9],
  "astronomy-db": [-3.25, 3.05, -1.7],
  cart: [-1.05, 1.15, 0.85],
  cache: [-2.0, 1.25, 1.55],
  currency: [-0.85, -0.35, 1.35],
  queue: [-0.95, -1.15, -1.0],
  accounting: [-2.1, -2.0, -1.6],
  "fraud-detection": [-0.35, -1.95, -1.45],
  shipping: [0.15, 1.75, 0.6],
  quote: [-0.35, 2.85, 1.25],
  // the symptom and downstream
  checkout: [0.55, 0.0, 0.0],
  frontend: [2.25, 0.85, -0.35],
  ad: [1.35, 2.55, -1.1],
  "frontend-proxy": [3.95, 0.35, 0.2],
  mcp: [3.35, 1.85, -0.75],
  agent: [4.45, 2.25, 0.05],
  chatbot: [5.15, 1.25, -0.5],
  "flagd-ui": [4.75, -0.85, -0.9],
  "image-provider": [3.45, -0.95, 0.75],
  // warehouse lineage
  "raw.raw_orders": [-1.3, -2.75, 0.65],
  "staging.stg_orders": [0.2, -2.8, 0.6],
  "marts.fct_revenue": [1.7, -2.7, 0.4],
  "marts.exec_revenue_metric": [3.05, -2.55, 0.2],
  "kpi.exec_revenue": [4.25, -2.3, 0.1],
  "dash.exec_morning": [5.25, -1.9, 0.0],
  "raw.raw_fx_rates": [-0.75, -3.6, -0.6],
  "staging.stg_fx_rates": [0.6, -3.55, -0.55],
  "raw.raw_customers": [-2.7, -3.25, 1.0],
  "staging.stg_customers": [-1.55, -3.65, 1.25],
};

/** A stable hash of an id (FNV-1a), for the fallback ring. */
function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

export function place(id: string): V3 {
  const p = LAYOUT[id];
  if (p) return p;
  const a = ((hash(id) % 3600) / 3600) * Math.PI * 2;
  return [Math.cos(a) * 6.2, Math.sin(a) * 3.6, -2.2];
}
