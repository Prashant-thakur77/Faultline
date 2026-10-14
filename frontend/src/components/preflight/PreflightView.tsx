"use client";

import { useEffect, useId, useMemo, useState } from "react";
import {
  ArrowRight,
  CircleAlert,
  Eye,
  FileWarning,
  GitPullRequest,
  Info,
  LoaderCircle,
  OctagonX,
  Play,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { fmtMs, fmtTime, fmtValue, shortDigest } from "@/lib/format";
import { buildGraphModel } from "@/lib/graphModel";
import type { GraphResponse, PreflightRequest, PreflightResponse, PreflightVerdict, RecordedPreflight } from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { GraphLegend } from "@/components/incident/GraphLegend";
import { GraphView, type RippleData } from "@/components/incident/GraphView";
import { Section } from "@/components/incident/Section";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";
import { CommentPreview } from "./CommentPreview";
import { DecisionChip, ReversalCards } from "./ReversalCard";

const PAYMENT_BEFORE = JSON.stringify({ client: { timeout_ms: 1500, retries: 2 }, currency: "USD" });

/** Example PRs (inputs, not results: the verdict always comes from the API). */
const EXAMPLES: { label: string; expect: string; body: PreflightRequest }[] = [
  {
    label: "S6: payment timeout 5000 ms, retries 0",
    expect: "expected: block",
    body: {
      repo: "Prashant-thakur77/faultline-demo-app",
      number: 7,
      title: "payment: raise client timeout to 5000 ms, drop retries",
      author: "p-017",
      head_sha: "5e6a1c0",
      files: [
        {
          path: "src/payment/config.json",
          before: PAYMENT_BEFORE,
          after: JSON.stringify({ client: { timeout_ms: 5000, retries: 0 }, currency: "USD" }),
        },
      ],
    },
  },
  {
    label: "payment timeout 1800 ms",
    expect: "expected: require review",
    body: {
      repo: "Prashant-thakur77/faultline-demo-app",
      number: 8,
      title: "payment: raise client timeout to 1800 ms",
      author: "p-017",
      head_sha: "9b2d7e4",
      files: [
        {
          path: "src/payment/config.json",
          before: PAYMENT_BEFORE,
          after: JSON.stringify({ client: { timeout_ms: 1800, retries: 2 }, currency: "USD" }),
        },
      ],
    },
  },
  {
    label: "catalog: off-peak migrations again",
    expect: "expected: reinstates a reversed decision",
    body: {
      repo: "Prashant-thakur77/faultline-demo-app",
      number: 9,
      title: "catalog: run DB migrations in the off-peak window again",
      author: "p-004",
      head_sha: "c41d9a2",
      files: [
        {
          path: "src/product-catalog/config.yaml",
          before: "db:\n  migration_mode: online\n  pool: 20\n",
          after: "db:\n  migration_mode: online\n  migration_window: off_peak\n  pool: 20\n",
        },
      ],
    },
  },
];

const VERDICT_META: Record<PreflightVerdict, { text: string; icon: LucideIcon; cls: string; bar: string; meaning: string }> = {
  allow: {
    text: "ALLOW",
    icon: ShieldCheck,
    cls: "border-emerald-400 bg-emerald-500/15 text-emerald-100",
    bar: "bg-emerald-400",
    meaning: "risk below the review threshold; no comment is posted",
  },
  require_review: {
    text: "REQUIRE REVIEW",
    icon: Eye,
    cls: "border-amber-400 bg-amber-500/15 text-amber-100",
    bar: "bg-amber-400",
    meaning: "risk at or above the review threshold: the listed reviewers must approve",
  },
  block: {
    text: "BLOCK",
    icon: OctagonX,
    cls: "border-red-400 bg-red-500/15 text-red-100",
    bar: "bg-red-400",
    meaning: "risk at or above the block threshold: the PR must not merge as is",
  },
};

const TERM_TEXT: Record<string, string> = {
  blast: "blast radius",
  revenue: "revenue path",
  betweenness: "chokepoint (betweenness)",
  past_incidents: "past incidents",
  decision: "decision contradicted",
  bus_factor: "bus factor",
  uncertainty: "uncertainty",
};

const PREFLIGHT_TEMPLATES = [
  { id: "Q-PRE-3", what: "which component each changed file belongs to" },
  { id: "Q-PRE-1", what: "impact: algo.BFS over PROPAGATES_TO from the changed components" },
  { id: "Q-PRE-2", what: "changed components of the PR" },
  { id: "Q-DEC-1", what: "active decisions the PR's facts contradict" },
];

/**
 * Pre-deploy gate (preflight): POST a PR (files with before/after) and show the graph's verdict,
 * the weighted risk terms, contradicted decisions, the path to the revenue tier, reviewers, what
 * would change the verdict, the PR comment it would post, extracted facts and the evidence Cypher.
 */
export function PreflightView({ focus = null, prRef = null }: { focus?: string | null; prRef?: string | null }) {
  const tenant = useTenant();
  const editorId = useId();
  const [text, setText] = useState(() => JSON.stringify(EXAMPLES[0].body, null, 2));
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{
    r: PreflightResponse;
    req: PreflightRequest | null;
    recordedAt?: number | null;
    /** Fields the recorded (GET) result does not carry. */
    missing?: Set<string>;
  } | null>(null);
  const [loadingPr, setLoadingPr] = useState(!!prRef);
  const [err, setErr] = useState<{ status: number | null; text: string } | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [graphErr, setGraphErr] = useState<string | null>(null);

  // Deep link (/preflight?pr=…): load the latest recorded preflight for that PR.
  useEffect(() => {
    if (!prRef) return;
    const ctrl = new AbortController();
    api
      .preflightGet(prRef, tenant, ctrl.signal)
      .then((d) => {
        const { r, missing } = fromRecorded(d);
        setRes({ r, req: null, recordedAt: d.at ?? null, missing });
      })
      .catch((e) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setErr({
          status: e instanceof ApiError ? e.status : null,
          text: e instanceof ApiError && e.status === 404 ? `no preflight is recorded for ${prRef}` : e instanceof ApiError ? e.detail : errorText(e),
        });
      })
      .finally(() => setLoadingPr(false));
    return () => ctrl.abort();
  }, [prRef, tenant]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .graph({ tenant: tenant }, ctrl.signal)
      .then(setGraph)
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setGraphErr(errorText(e));
      });
    return () => ctrl.abort();
  }, [tenant]);

  const parsed = useMemo((): { ok: true; value: PreflightRequest } | { ok: false; error: string } => {
    try {
      const v = JSON.parse(text) as unknown;
      if (!v || typeof v !== "object" || Array.isArray(v)) return { ok: false, error: "the body must be a JSON object" };
      const o = v as Record<string, unknown>;
      if (!Array.isArray(o.files)) return { ok: false, error: "\"files\" must be an array of {path, before, after}" };
      return { ok: true, value: v as PreflightRequest };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  }, [text]);

  const run = async (body: PreflightRequest) => {
    setBusy(true);
    setErr(null);
    try {
      setRes({ r: await api.preflight(body, tenant), req: body });
    } catch (e) {
      setErr({ status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid w-full max-w-[1600px] grid-cols-1 gap-4 p-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-4">
        <section aria-labelledby="pf-h" className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <h1 id="pf-h" className="flex items-center gap-2 text-lg font-semibold text-zinc-50">
            <GitPullRequest aria-hidden className="size-5 text-violet-300" /> Preflight: the pre-deploy gate
          </h1>
          <p className="text-sm text-zinc-300">
            The same graph that explains incidents scores a PR before it ships: what the change reaches, which revenue
            path, which decisions it contradicts and who must review it. Weights come from weights.yaml; every term from a
            FalkorDB query.
          </p>
          {prRef || focus ? (
            <p role="note" className="rounded-md border border-sky-500/40 bg-sky-500/10 p-2 text-xs text-sky-100">
              Opened from a PR comment{prRef ? <> for <span className="font-mono">{prRef}</span></> : null}
              {focus ? (
                <>
                  {" "}
                  (focus <span className="font-mono">{focus}</span>, highlighted on the graph)
                </>
              ) : null}
              {loadingPr ? ". Loading its latest recorded preflight…" : res?.req === null ? ". Showing its latest recorded preflight." : "."}
            </p>
          ) : null}
          <div>
            <h2 className="mb-1 text-xs font-semibold tracking-wide text-zinc-400 uppercase">Example PRs</h2>
            <ul className="flex flex-col gap-1.5">
              {EXAMPLES.map((ex) => (
                <li key={ex.label}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setText(JSON.stringify(ex.body, null, 2));
                      void run(ex.body);
                    }}
                    className="flex w-full items-center gap-2 rounded-md border border-zinc-700 px-2 py-1.5 text-left text-sm text-zinc-100 outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
                  >
                    <GitPullRequest aria-hidden className="size-3.5 shrink-0 text-zinc-400" />
                    <span className="flex-1">{ex.label}</span>
                    <span className="text-[11px] text-zinc-400">{ex.expect}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (parsed.ok && !busy) void run(parsed.value);
            }}
          >
            <label htmlFor={editorId} className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
              PR body (JSON, editable)
            </label>
            <textarea
              id={editorId}
              value={text}
              onChange={(e) => setText(e.target.value)}
              spellCheck={false}
              rows={16}
              aria-invalid={!parsed.ok}
              aria-describedby={`${editorId}-help`}
              className="w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 font-mono text-[12px] text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            <p id={`${editorId}-help`} className="text-xs text-zinc-400">
              {parsed.ok ? (
                <>
                  {"{repo, number, title, author, head_sha, files:[{path, before, after}]}"} · POST /api/preflight
                </>
              ) : (
                <span className="text-red-300">Invalid body: {parsed.error}</span>
              )}
            </p>
            <Button type="submit" disabled={busy || !parsed.ok}>
              {busy ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <Play aria-hidden />}
              Run preflight
            </Button>
          </form>
        </section>
        {res ? <FactsAndEvidence r={res.r} req={res.req} missing={res.missing ?? null} /> : null}
      </div>

      <div className="space-y-4" aria-live="polite" aria-busy={busy}>
        {err ? (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
            <p>
              <strong className="font-semibold">
                {err.status === 404
                  ? "Not found:"
                  : err.status === 422
                  ? "PR body not accepted:"
                  : err.status === 401
                    ? "Preflight key required:"
                    : err.status === 429
                      ? "Rate limited:"
                      : "Preflight failed:"}
              </strong>{" "}
              {err.text}
              {err.status ? ` (HTTP ${err.status})` : ""}
            </p>
          </div>
        ) : null}
        {res?.req === null ? (
          <p className="text-xs text-zinc-400">
            Recorded preflight{res.recordedAt ? ` from ${fmtTime(res.recordedAt)}` : ""} (GET /api/preflight). Run a body on the left
            to score a new revision.
          </p>
        ) : null}
        {res && res.r.recorded === false ? (
          <p role="note" className="flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-500/10 px-2 py-1 text-xs text-sky-100">
            <Info aria-hidden className="size-3.5 shrink-0 text-sky-300" />
            Assessed on a clean-room copy; not recorded (deep link unavailable).
          </p>
        ) : null}
        {res ? <Verdict r={res.r} /> : !busy && !err && !loadingPr ? (
          <p className="rounded-lg border border-dashed border-zinc-700 p-4 text-sm text-zinc-300">
            Run an example PR or your own body. The verdict, its terms and the evidence appear here.
          </p>
        ) : busy ? (
          <p className="text-sm text-zinc-300">Scoring the PR against the graph…</p>
        ) : null}
        <PreflightGraph graph={graph} graphErr={graphErr} r={res?.r ?? null} focus={focus} />
        {res ? <Assessment r={res.r} /> : null}
        {res ? (
          <Section
            id="pf-comment"
            title="PR comment preview"
            aside={res.r.comment ? <StatusChip tone="info">would be posted</StatusChip> : <StatusChip tone="na">none</StatusChip>}
          >
            {res.missing?.has("comment") ? (
              <p className="text-sm text-zinc-300">
                The recorded result does not include the comment (GET /api/preflight returns no comment). Run the PR on the
                left to render it.
              </p>
            ) : res.r.comment ? (
              <div className="rounded-md border border-zinc-700 bg-zinc-950 p-3">
                <CommentPreview markdown={res.r.comment} />
              </div>
            ) : (
              <p className="text-sm text-zinc-300">An allow verdict posts no comment.</p>
            )}
          </Section>
        ) : null}
      </div>
    </div>
  );
}

function Verdict({ r }: { r: PreflightResponse }) {
  const m = VERDICT_META[r.verdict];
  const Icon = m.icon;
  const pct = (x: number) => `${Math.max(0, Math.min(1, x)) * 100}%`;
  const terms = Object.entries(r.terms).sort(([, a], [, b]) => b.weighted - a.weighted);
  const maxW = Math.max(0.0001, ...terms.map(([, t]) => t.weighted));
  return (
    <Section id="pf-verdict" title="Verdict" aside={<span className="font-mono text-[11px] text-zinc-400">{r.pr} · {r.run_id} · {fmtMs(r.ms)}</span>}>
      <div className="flex flex-wrap items-center gap-3">
        <span className={cn("inline-flex items-center gap-2 rounded-lg border-2 px-3 py-1.5 text-xl font-bold tracking-wide", m.cls)} data-verdict={r.verdict}>
          <Icon aria-hidden className="size-6" />
          {m.text}
        </span>
        <p className="text-sm text-zinc-300">{m.meaning}.</p>
      </div>

      <div className="mt-3">
        <p className="mb-1 flex justify-between text-xs text-zinc-300">
          <span>
            risk <span className="font-mono font-semibold text-zinc-50">{fmtValue(r.risk)}</span>
          </span>
          <span className="text-zinc-400">0 – 1</span>
        </p>
        <div
          className="relative h-3 rounded bg-zinc-800"
          role="img"
          aria-label={`Risk ${r.risk}; review threshold ${r.thresholds.require_review}; block threshold ${r.thresholds.block}`}
        >
          <div className={cn("absolute inset-y-0 left-0 rounded", m.bar)} style={{ width: pct(r.risk) }} />
          <div className="absolute -inset-y-1 w-0.5 bg-amber-200" style={{ left: pct(r.thresholds.require_review) }} />
          <div className="absolute -inset-y-1 w-0.5 bg-red-200" style={{ left: pct(r.thresholds.block) }} />
        </div>
        <div className="relative mt-1 h-4 font-mono text-[10.5px]" aria-hidden>
          <span className="absolute -translate-x-1/2 text-amber-200" style={{ left: pct(r.thresholds.require_review) }}>
            review {r.thresholds.require_review}
          </span>
          <span className="absolute -translate-x-1/2 text-red-200" style={{ left: pct(r.thresholds.block) }}>
            block {r.thresholds.block}
          </span>
        </div>
      </div>

      <ReversalCards reversals={r.reversals ?? []} />

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <caption className="mb-1 text-left text-xs font-semibold tracking-wide text-zinc-300 uppercase">
            Risk terms (weighted contribution)
          </caption>
          <thead className="text-zinc-400">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">Term</th>
              <th scope="col" className="py-1 pr-2 font-medium">Value</th>
              <th scope="col" className="py-1 pr-2 font-medium">Weighted</th>
              <th scope="col" className="py-1 font-medium">Why (from the graph)</th>
            </tr>
          </thead>
          <tbody>
            {terms.map(([k, t]) => (
              <tr key={k} className="border-t border-zinc-800 align-top">
                <td className="py-1.5 pr-2 whitespace-nowrap text-zinc-100">{TERM_TEXT[k] ?? k}</td>
                <td className="py-1.5 pr-2 font-mono text-zinc-200">{fmtValue(t.value)}</td>
                <td className="py-1.5 pr-2">
                  <span className="flex items-center gap-1.5">
                    <span className="font-mono text-zinc-50">+{fmtValue(t.weighted)}</span>
                    <span className="h-1.5 w-14 rounded bg-zinc-800" aria-hidden>
                      <span className="block h-full rounded bg-violet-400" style={{ width: `${(t.weighted / maxW) * 100}%` }} />
                    </span>
                  </span>
                </td>
                <td className="py-1.5 break-words text-zinc-300">{t.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {r.would_change_if.length ? (
        <div className="mt-3">
          <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">Would change if</h3>
          <ul className="space-y-1 text-xs">
            {r.would_change_if.map((w, i) => {
              const wm = VERDICT_META[w.verdict];
              const WIcon = wm.icon;
              return (
                <li key={i} className="flex flex-wrap items-start gap-1.5">
                  <span className={cn("inline-flex items-center gap-1 rounded border px-1 text-[10.5px] font-bold", wm.cls)}>
                    <WIcon aria-hidden className="size-3" /> {wm.text}
                  </span>
                  <span className="min-w-0 flex-1 text-zinc-200">if {w.if.replace(/^if\s+/, "")}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </Section>
  );
}

function Assessment({ r }: { r: PreflightResponse }) {
  const a = r.assessment;
  const decisions = a.decisions.length
    ? a.decisions
    : r.decision_links.map((d) => ({ decision: d.id, title: d.title, url: d.url, rule_key: null, op: null, expected: null, actual: null, about: null, violated: true }));
  const past = Object.entries(a.past_incidents);
  return (
    <Section id="pf-assess" title="Why: path, decisions, reviewers">
      <div className="space-y-3 text-xs">
        <div>
          <h3 className="mb-1 font-semibold tracking-wide text-zinc-300 uppercase">Path</h3>
          {a.changed.length ? (
            <p className="flex flex-wrap items-center gap-1.5">
              {a.changed.map((c) => (
                <span key={c} className="rounded border border-red-400 bg-red-950 px-1 font-mono text-red-100">
                  {c}
                </span>
              ))}
              <ArrowRight aria-label="reaches" className="size-3.5 text-zinc-400" />
              {a.revenue_tier1.length ? (
                a.revenue_tier1.map((n) => (
                  <span key={n} className="rounded border border-amber-300 bg-amber-900/60 px-1 font-mono text-amber-50">
                    {n}
                  </span>
                ))
              ) : (
                <span className="text-zinc-300">no tier-1 revenue node</span>
              )}
              {a.revenue_tier1.length ? <span className="text-zinc-400">(revenue path, tier 1)</span> : null}
            </p>
          ) : (
            <p className="text-zinc-300">No changed component was found in the graph for these files.</p>
          )}
          <details className="mt-1">
            <summary className="cursor-pointer text-zinc-300 outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
              {a.impacted.length} impacted node{a.impacted.length === 1 ? "" : "s"} (algo.BFS)
            </summary>
            <p className="mt-1 font-mono break-words text-zinc-300">{a.impacted.join(", ") || "–"}</p>
          </details>
        </div>

        <div>
          <h3 className="mb-1 font-semibold tracking-wide text-zinc-300 uppercase">Decisions</h3>
          {decisions.length === 0 ? (
            <p className="text-zinc-300">The PR contradicts no active decision.</p>
          ) : (
            <ul className="space-y-1.5">
              {decisions.map((d) => (
                <li key={d.decision} className={cn("rounded-md border p-2", d.violated ? "border-amber-400/50 bg-amber-500/5" : "border-zinc-700")}>
                  <p className="flex flex-wrap items-center gap-1.5">
                    <DecisionChip id={d.decision} url={d.url} />
                    {d.violated ? (
                      <StatusChip tone="warn" icon={FileWarning}>
                        contradicted
                      </StatusChip>
                    ) : (
                      <StatusChip tone="pass">respected</StatusChip>
                    )}
                    <span className="text-zinc-200">{d.title}</span>
                  </p>
                  {d.rule_key ? (
                    <p className="mt-1 font-mono text-zinc-300">
                      {d.rule_key} {d.op} {fmtValue(d.expected)} · PR sets{" "}
                      <span className={d.violated ? "font-semibold text-red-200" : "text-emerald-200"}>
                        {d.violated ? "✗ " : "✓ "}
                        {fmtValue(d.actual)}
                      </span>
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <h3 className="mb-1 font-semibold tracking-wide text-zinc-300 uppercase">Required reviewers</h3>
            {r.reviewers.length ? (
              <ul className="flex flex-wrap gap-1.5">
                {r.reviewers.map((p) => (
                  <li key={p} className="inline-flex items-center gap-1 rounded border border-sky-500/50 bg-sky-500/10 px-1.5 font-mono text-sky-100">
                    <UserRound aria-hidden className="size-3" /> {p}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-zinc-300">None required.</p>
            )}
            <p className="mt-1 text-zinc-400">owner team, active, not the author</p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold tracking-wide text-zinc-300 uppercase">History and bus factor</h3>
            {past.length ? (
              past.map(([c, incs]) => (
                <p key={c} className="text-zinc-200">
                  <span className="font-mono">{c}</span>: {incs.length} past incident{incs.length === 1 ? "" : "s"} caused by
                  changes here
                </p>
              ))
            ) : (
              <p className="text-zinc-300">No past incidents caused by changes here.</p>
            )}
            {Object.entries(a.bus_factor).map(([c, n]) => (
              <p key={c} className={n <= 1 ? "text-amber-200" : "text-zinc-200"}>
                {n <= 1 ? "⚠ " : ""}bus factor <span className="font-mono">{c}</span> = {n}
              </p>
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}

function PreflightGraph({
  graph,
  graphErr,
  r,
  focus,
}: {
  graph: GraphResponse | null;
  graphErr: string | null;
  r: PreflightResponse | null;
  focus: string | null;
}) {
  const tenant = useTenant();
  const model = useMemo(() => (graph ? buildGraphModel(graph, { proof: null, rejected: [] }, [], new Map()) : null), [graph]);
  const ripple = useMemo((): RippleData | null => {
    const changed = r ? r.assessment.changed : focus ? [focus] : [];
    if (!changed.length) return null;
    const blast = new Map<string, number | null>();
    for (const n of r?.assessment.impacted ?? []) if (!changed.includes(n)) blast.set(n, null);
    return { cause: new Set(changed), blast, causeLabel: r ? "CHANGED" : "FOCUS", blastLabel: "IMPACTED" };
  }, [r, focus]);
  const panel = useCypherPanel();
  return (
    <section aria-labelledby="pf-graph-h" className="fl-card rounded-2xl overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-3 py-2">
        <h2 id="pf-graph-h" className="text-sm font-semibold text-zinc-50">
          What the change reaches
        </h2>
        <span className="text-xs text-zinc-400">
          {graph ? `${graph.graph} · changed red, impacted yellow, rest dimmed` : ""}
        </span>
      </div>
      <div className="h-[420px]">
        {graphErr ? (
          <p role="alert" className="m-3 rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
            Graph view unavailable: {graphErr}
          </p>
        ) : !model ? (
          <p className="p-3 text-sm text-zinc-300">Loading the tenant&apos;s failure-flow graph…</p>
        ) : (
          <GraphView
            model={model}
            layoutKey={`${graph?.graph}:${r?.run_id ?? focus ?? ""}`}
            mode={ripple ? "ripple" : "path"}
            ripple={ripple}
            onOpenNode={(id) =>
              panel.open({
                template: "Q-CTX-1",
                title: `context of ${id}`,
                origin: "preflight graph",
                ctx: { node: id, onset: nowMs() },
                tenant: tenant,
              })
            }
          />
        )}
      </div>
      <div className="border-t border-zinc-800 px-3 py-2">
        <GraphLegend
          mode={ripple ? "ripple" : "path"}
          rippleText={
            ripple
              ? {
                  cause: [r ? "CHANGED" : "FOCUS", r ? "component the PR changes (red)" : "node named in the link (red)"],
                  blast: ["IMPACTED", "reached by a failure of the change (yellow; algo.BFS, Q-PRE-1)"],
                }
              : null
          }
        />
      </div>
    </section>
  );
}

/** Wall clock for "$now" in Q-CTX-1 (on-call right now); only called from click handlers. */
function nowMs(): number {
  return Date.now();
}

function FactsAndEvidence({
  r,
  req,
  missing,
}: {
  r: PreflightResponse;
  req: PreflightRequest | null;
  missing: Set<string> | null;
}) {
  const tenant = useTenant();
  const panel = useCypherPanel();
  const files = req
    ? req.files.map((f) => `file:${f.path}`)
    : [...new Set(r.facts.map((f) => f.file).filter((f): f is string => !!f))];
  const open = (tid: string, what: string) => {
    const exact = tid === r.evidence.template && r.evidence.params ? r.evidence.params : null;
    panel.open({
      template: tid,
      title: `${tid} · preflight`,
      origin: `preflight run ${r.run_id} (${r.pr})${tid === r.evidence.template ? ` → evidence ${r.evidence.evidence_id}` : ""}`,
      detail: exact
        ? `${what}. Params as recorded on the evidence.`
        : `${what}. Params are derived from the PR the way the preflight engine builds them (not recorded for this query).`,
      recordedParams: exact,
      ctx: { pr: r.pr, files },
      recorded: tid === r.evidence.template ? { ms: r.evidence.ms, rows: null, digest: r.evidence.digest } : null,
      tenant: tenant,
    });
  };
  return (
    <>
      <Section id="pf-facts" title="Extracted facts" aside={<span className="text-[11px] text-zinc-400">{r.facts.length} facts</span>}>
        {missing?.has("facts") ? (
          <p className="text-sm text-zinc-300">Not in the recorded result (GET /api/preflight returns no facts).</p>
        ) : r.facts.length ? (
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Facts the preflight extracted from the changed files</caption>
            <thead className="text-zinc-400">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium">Key</th>
                <th scope="col" className="py-1 pr-2 font-medium">Value</th>
                <th scope="col" className="py-1 pr-2 font-medium">About</th>
                <th scope="col" className="py-1 font-medium">File</th>
              </tr>
            </thead>
            <tbody>
              {r.facts.map((f) => (
                <tr key={`${f.key}:${f.file}`} className="border-t border-zinc-800">
                  <td className="py-1.5 pr-2 font-mono break-all text-zinc-100">{f.key}</td>
                  <td className="py-1.5 pr-2 font-mono text-zinc-100">{fmtValue(f.value)}</td>
                  <td className="py-1.5 pr-2 font-mono text-zinc-300">{f.about ?? "–"}</td>
                  <td className="py-1.5 font-mono break-all text-zinc-400">{f.file ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-zinc-300">No facts were extracted from the changed files.</p>
        )}
        {r.notes.length ? (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-zinc-300">
            {r.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        ) : null}
        {r.unknown_files.length ? (
          <p className="mt-2 flex items-start gap-1 text-xs text-amber-200">
            <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Files the graph does not know (raise uncertainty): <span className="font-mono">{r.unknown_files.join(", ")}</span>
          </p>
        ) : null}
      </Section>

      <Section id="pf-evidence" title="Evidence (Cypher)">
        {missing?.has("template") && r.evidence.cypher ? (
          <p className="mb-2 text-xs">
            <button
              type="button"
              onClick={() =>
                panel.open({
                  template: "recorded",
                  title: `recorded evidence ${r.evidence.evidence_id}`,
                  origin: `preflight run ${r.run_id} (${r.pr})`,
                  detail: "Exact Cypher and params recorded on the evidence. The recorded result does not name its template, so re-run it from the template list below.",
                  recordedParams: r.evidence.params ?? null,
                  ctx: {},
                  tenant: tenant,
                  offline: {
                    reason: "Recorded query shown as stored; use the template buttons below to PROFILE or re-run.",
                    templates: { recorded: { id: "recorded", purpose: "recorded preflight evidence", cypher: r.evidence.cypher, file: "evidence", limit: 0 } },
                  },
                })
              }
              className="inline-flex min-h-6 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
            >
              recorded Cypher of {r.evidence.evidence_id}
            </button>
          </p>
        ) : null}
        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
          <dt className="text-zinc-400">evidence</dt>
          <dd className="font-mono text-zinc-100">{r.evidence.evidence_id}</dd>
          <dt className="text-zinc-400">served by</dt>
          <dd className="text-zinc-200">{r.evidence.served_by}</dd>
          <dt className="text-zinc-400">digest</dt>
          <dd className="font-mono text-zinc-200" title={r.evidence.digest}>
            {shortDigest(r.evidence.digest, 16)}
          </dd>
          <dt className="text-zinc-400">engine</dt>
          <dd className="font-mono text-zinc-200">{fmtMs(r.evidence.ms)}</dd>
        </dl>
        <h3 className="mt-2 mb-1 text-xs font-semibold tracking-wide text-zinc-300 uppercase">Queries behind the verdict</h3>
        <ul className="space-y-1 text-xs">
          {PREFLIGHT_TEMPLATES.map((t) => (
            <li key={t.id} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => open(t.id, t.what)}
                className="inline-flex min-h-6 shrink-0 items-center rounded bg-violet-500/15 whitespace-nowrap px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
                aria-label={`${t.id}: open the Cypher panel (${t.what})`}
              >
                {t.id}
              </button>
              <span className="text-zinc-300">{t.what}</span>
              {t.id === r.evidence.template ? <StatusChip tone="info">recorded evidence</StatusChip> : null}
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

/** Normalise GET /api/preflight (recorded) into the POST shape, noting what it lacks. */
function fromRecorded(d: RecordedPreflight): { r: PreflightResponse; missing: Set<string> } {
  const missing = new Set<string>();
  const row = d.assessment ?? d.rows?.[0] ?? {};
  const assessment: PreflightResponse["assessment"] = {
    changed: row.changed ?? [],
    impacted: row.impacted ?? [],
    revenue_tier1: row.revenue_tier1 ?? [],
    decisions: row.decisions ?? [],
    past_incidents: row.past_incidents ?? {},
    bus_factor: row.bus_factor ?? {},
    gaps: row.gaps ?? [],
    reviewers: row.reviewers ?? d.reviewers ?? [],
  };
  if (!d.facts) missing.add("facts");
  if (d.comment === undefined) missing.add("comment");
  if (!d.evidence?.template) missing.add("template");
  const r: PreflightResponse = {
    pr: d.pr,
    run_id: d.run_id,
    verdict: d.verdict,
    risk: d.risk,
    thresholds: d.thresholds,
    terms: d.terms,
    would_change_if: d.would_change_if ?? [],
    reviewers: d.reviewers ?? assessment.reviewers,
    decision_links: d.decision_links ?? [],
    reversals: d.reversals ?? [],
    assessment,
    facts: d.facts ?? [],
    notes: d.notes ?? [],
    unknown_files: d.unknown_files ?? [],
    evidence: d.evidence ?? {
      evidence_id: d.evidence_id ?? "–",
      template: "",
      cypher: d.cypher ?? "",
      served_by: "recorded in FalkorDB (GET /api/preflight)",
      digest: "",
      ms: Number.NaN,
      params: d.params ?? null,
    },
    comment: d.comment ?? null,
    ms: d.ms ?? Number.NaN,
  };
  return { r, missing };
}
