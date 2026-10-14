/**
 * Parameters for the Cypher panel.
 *
 * Recorded params (what the gate stored on the check) always win. When a check or
 * evidence item did not record params, the panel pre-fills the template's `$names`
 * from the incident's own context (incident id, run id, onset, symptom targets, the
 * gate run's cause and its G2 chain) and labels each one "derived" so nobody mistakes
 * it for what the gate ran. Anything that cannot be derived stays null and is shown
 * as missing; the user can edit the JSON before re-running.
 */

export type Provenance = "recorded" | "derived" | "missing";

export interface ParamContext {
  incident?: string;
  run?: string;
  onset?: number;
  targets?: string[];
  cause?: string;
  /** Chain cause → … → symptom from a G2 check, when known. */
  chain?: string[];
  evidenceIds?: string[];
  /** Node the panel was opened for (graph view). */
  node?: string;
  /** Explore view: the node ids the scoped view returned (Q-VIEW-2's $ids, derived). */
  ids?: string[];
  /** Preflight: the PR node id (pr:owner/name#n). */
  pr?: string;
  /** Preflight: the changed files' graph ids (file:<path>). */
  files?: string[];
}

/** `$name` placeholders in a Cypher text, in first-appearance order. */
export function cypherParams(cypher: string): string[] {
  const seen: string[] = [];
  for (const m of cypher.matchAll(/\$([A-Za-z_][A-Za-z0-9_]*)/g)) {
    if (!seen.includes(m[1])) seen.push(m[1]);
  }
  return seen;
}

function derive(name: string, ctx: ParamContext, recorded: Record<string, unknown>): unknown {
  const symptoms = Array.isArray(recorded.symptoms) ? (recorded.symptoms as unknown[]) : ctx.targets;
  switch (name) {
    case "inc":
      return ctx.incident;
    case "run":
      return ctx.run;
    case "onset":
      return ctx.onset;
    case "cause":
    case "change":
      return ctx.cause ?? ctx.pr;
    case "pr":
      return ctx.pr;
    case "files":
      return ctx.files;
    case "symptom":
      return symptoms && symptoms.length === 1 ? symptoms[0] : undefined;
    case "symptoms":
      return symptoms;
    case "chain":
      return ctx.chain;
    case "sources":
      // The changed node: the hop after the change on its recorded G2 chain.
      return ctx.chain && ctx.chain.length >= 2 ? [ctx.chain[1]] : undefined;
    case "evidence":
      return ctx.evidenceIds && ctx.evidenceIds.length ? [...new Set(ctx.evidenceIds)] : undefined;
    case "id":
      return ctx.node;
    case "ids":
      if (ctx.ids && ctx.ids.length) return ctx.ids;
      return ctx.node ? [ctx.node] : ctx.cause ? [ctx.cause] : undefined;
    case "now":
      return ctx.onset;
    default:
      return undefined;
  }
}

export function buildParams(
  cypher: string,
  recorded: Record<string, unknown> | null | undefined,
  ctx: ParamContext,
): { params: Record<string, unknown>; provenance: Record<string, Provenance> } {
  const rec = recorded ?? {};
  const params: Record<string, unknown> = {};
  const provenance: Record<string, Provenance> = {};
  for (const name of cypherParams(cypher)) {
    if (name in rec) {
      params[name] = rec[name];
      provenance[name] = "recorded";
      continue;
    }
    const v = derive(name, ctx, rec);
    params[name] = v === undefined ? null : v;
    provenance[name] = v === undefined ? "missing" : "derived";
  }
  // Keep any recorded key the template does not reference, so the record is shown whole.
  for (const [k, v] of Object.entries(rec)) {
    if (!(k in params)) {
      params[k] = v;
      provenance[k] = "recorded";
    }
  }
  return { params, provenance };
}

/**
 * A combined evidence id names several template runs: tools that answer with several templates record
 * `Q-A+Q-B`, and a template run more than once keeps each run as `Q-GATE-3#2`, `Q-GATE-3#3` (backend
 * tools._combine). Each part maps to its base template (the part before `#`) and to its own recorded params,
 * which the backend stores under the part's key. A plain id is one part.
 */
export interface TemplatePart {
  /** The key the recorded params are stored under (e.g. `Q-GATE-3#2`). */
  key: string;
  /** The catalogue template id to load (`Q-GATE-3`). */
  template: string;
  /** This part's recorded params: the entry under `key` for a combined record, else the record itself. */
  recordedParams: Record<string, unknown> | null;
}

export function splitTemplateId(tid: string, recorded?: Record<string, unknown> | null): TemplatePart[] {
  const keys = tid.split("+").map((k) => k.trim()).filter(Boolean);
  const counts = new Map<string, number>();
  const parts: TemplatePart[] = [];
  for (const raw of keys) {
    const base = raw.split("#")[0];
    // the backend keys the n-th repeat of a template as `<id>#n`; an id given without `#` keeps its own numbering
    const n = (counts.get(base) ?? 0) + 1;
    counts.set(base, n);
    const key = raw.includes("#") ? raw : n === 1 ? base : `${base}#${n}`;
    const own = recorded && keys.length > 1 ? recorded[key] : undefined;
    parts.push({
      key,
      template: base,
      recordedParams:
        keys.length > 1
          ? own && typeof own === "object" && !Array.isArray(own)
            ? (own as Record<string, unknown>)
            : null
          : (recorded ?? null),
    });
  }
  return parts;
}
