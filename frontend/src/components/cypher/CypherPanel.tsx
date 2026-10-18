"use client";

import { useEffect, useMemo, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Check, CircleSlash, Copy, Gauge, Play, X } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { fmtMs, fmtValue, shortDigest } from "@/lib/format";
import { buildParams, cypherParams, splitTemplateId, type Provenance } from "@/lib/params";
import type { ProfileResponse, TemplateInfo, TemplateRunResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/StatusChip";
import type { CypherRequest } from "./CypherPanelContext";

/**
 * The Cypher panel: template id, purpose, the exact Cypher the backend runs, params,
 * GRAPH.PROFILE and a read-only re-run (rows, engine ms, digest, served_by), plus Copy.
 * Base UI's Dialog traps focus, closes on Esc and returns focus to the opener.
 */
export function CypherPanel({
  request,
  onClose,
  returnFocus,
}: {
  request: CypherRequest | null;
  onClose: () => void;
  returnFocus: React.RefObject<HTMLElement | null>;
}) {
  return (
    <Dialog.Root open={request !== null} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/70 transition-opacity data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup
          finalFocus={returnFocus}
          className="fixed top-1/2 left-1/2 z-50 flex max-h-[92vh] w-[min(64rem,96vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 text-zinc-100 shadow-2xl outline-none"
        >
          {request ? <PartsBody request={request} /> : null}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * A combined evidence id (`Q-A+Q-B`, `Q-GATE-3#2`) is several template runs: each part is shown with its own
 * template and recorded params (a switcher picks the part), instead of asking the API for a template that does not
 * exist (404).
 */
function PartsBody({ request }: { request: CypherRequest }) {
  const parts = useMemo(
    () => (request.template ? splitTemplateId(request.template, request.recordedParams) : []),
    [request.template, request.recordedParams],
  );
  const [idx, setIdx] = useState(0);
  if (parts.length <= 1) {
    const one = parts[0];
    return <PanelBody request={one ? { ...request, template: one.template } : request} />;
  }
  const part = parts[Math.min(idx, parts.length - 1)];
  const chooser = (
    <div role="group" aria-label={`This evidence ran ${parts.length} template queries`} className="mt-2 flex flex-wrap gap-1.5">
      {parts.map((p, i) => (
        <Button
          key={p.key}
          size="xs"
          variant={i === idx ? "default" : "outline"}
          aria-pressed={i === idx}
          onClick={() => setIdx(i)}
        >
          <span className="font-mono">{p.key}</span>
        </Button>
      ))}
    </div>
  );
  return (
    <PanelBody
      key={part.key}
      request={{ ...request, template: part.template, recordedParams: part.recordedParams }}
      chooser={chooser}
      combined={request.template}
    />
  );
}

function offlineInit(request: CypherRequest) {
  const tid = request.template;
  if (!request.offline || !tid) return null;
  const t = request.offline.templates[tid];
  if (!t) return { tpl: null, error: `template ${tid} is not in this recording's export`, params: "{}", provenance: {} };
  const { params, provenance } = buildParams(t.cypher, request.recordedParams, request.ctx);
  return { tpl: t, error: null, params: JSON.stringify(params, null, 2), provenance };
}

const PROV_TONE: Record<Provenance, "pass" | "warn" | "fail"> = {
  recorded: "pass",
  derived: "warn",
  missing: "fail",
};
const PROV_TEXT: Record<Provenance, string> = {
  recorded: "recorded by the run",
  derived: "derived from incident context (not recorded)",
  missing: "missing: fill in before running",
};

function PanelBody({
  request,
  chooser,
  combined,
}: {
  request: CypherRequest;
  chooser?: React.ReactNode;
  combined?: string | null;
}) {
  const tid = request.template;
  const offline = request.offline ?? null;
  // Replay: the template comes from the recording's snapshot, so the panel starts filled in.
  const [init] = useState(() => offlineInit(request));
  const [tpl, setTpl] = useState<TemplateInfo | null>(init?.tpl ?? null);
  const [tplError, setTplError] = useState<string | null>(init?.error ?? null);
  const [paramsText, setParamsText] = useState(init?.params ?? "{}");
  const [provenance, setProvenance] = useState<Record<string, Provenance>>(init?.provenance ?? {});
  const [copied, setCopied] = useState<string | null>(null);

  const [prof, setProf] = useState<{ res: ProfileResponse; rtt: number } | null>(null);
  const [profErr, setProfErr] = useState<string | null>(null);
  const [profBusy, setProfBusy] = useState(false);
  const [run, setRun] = useState<TemplateRunResponse | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  useEffect(() => {
    if (!tid || offline) return;
    const ctrl = new AbortController();
    api
      .template(tid, ctrl.signal)
      .then((t) => {
        setTpl(t);
        const { params, provenance } = buildParams(t.cypher, request.recordedParams, request.ctx);
        setParamsText(JSON.stringify(params, null, 2));
        setProvenance(provenance);
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setTplError(errorText(e));
      });
    return () => ctrl.abort();
  }, [tid, request.recordedParams, request.ctx, offline]);

  const parsed = useMemo((): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } => {
    try {
      const v = JSON.parse(paramsText) as unknown;
      if (!v || typeof v !== "object" || Array.isArray(v)) return { ok: false, error: "params must be a JSON object" };
      return { ok: true, value: v as Record<string, unknown> };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  }, [paramsText]);

  const missing = useMemo(() => {
    if (!tpl || !parsed.ok) return [];
    return cypherParams(tpl.cypher).filter((n) => parsed.value[n] === null || parsed.value[n] === undefined);
  }, [tpl, parsed]);

  const body = () => ({
    params: parsed.ok ? parsed.value : {},
    incident: request.incident,
    tenant: request.tenant,
  });

  const doProfile = async () => {
    if (!tid || !parsed.ok || offline) return;
    setProfBusy(true);
    setProfErr(null);
    const t0 = performance.now();
    try {
      const res = await api.profile(tid, body());
      setProf({ res, rtt: performance.now() - t0 });
    } catch (e) {
      setProfErr(errorText(e));
    } finally {
      setProfBusy(false);
    }
  };

  const doRun = async () => {
    if (!tid || !parsed.ok || offline) return;
    setRunBusy(true);
    setRunErr(null);
    try {
      setRun(await api.rerun(tid, body()));
    } catch (e) {
      setRunErr(errorText(e));
    } finally {
      setRunBusy(false);
    }
  };

  const copy = async (what: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
    } catch {
      setCopied(`${what}: copy blocked by the browser`);
    }
  };

  const ev = request.evidence ?? null;

  return (
    <>
      {/* A div, not <header>: inside a dialog a <header> would be a second page banner landmark. */}
      <div className="flex items-start gap-3 border-b border-zinc-800 px-5 py-3">
        <div className="min-w-0 flex-1">
          <Dialog.Title className="flex flex-wrap items-center gap-2 text-base font-semibold">
            {tid ? (
              <span className="rounded bg-violet-500/15 px-1.5 py-0.5 font-mono text-sm text-violet-200">{tid}</span>
            ) : (
              <span className="rounded bg-zinc-700/60 px-1.5 py-0.5 font-mono text-sm text-zinc-200">no template</span>
            )}
            <span className="min-w-0 break-words">{request.title}</span>
          </Dialog.Title>
          <Dialog.Description className="mt-0.5 text-xs text-zinc-400">
            Opened from {request.origin}
            {request.incident ? (
              <>
                {" "}
                · incident <span className="font-mono">{request.incident}</span>
              </>
            ) : null}
            {combined ? (
              <>
                {" "}
                · combined evidence <span className="font-mono break-all">{combined}</span>
              </>
            ) : null}
          </Dialog.Description>
          {chooser}
        </div>
        <Dialog.Close
          className="rounded-md p-1 text-zinc-300 outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400"
          aria-label="Close Cypher panel"
        >
          <X aria-hidden className="size-5" />
        </Dialog.Close>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4 text-sm">
        {request.detail ? (
          <section aria-label="Recorded detail">
            <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-400 uppercase">Recorded detail</h3>
            <p className="break-words text-zinc-200">{request.detail}</p>
          </section>
        ) : null}

        {ev ? <EvidenceFacts ev={ev} /> : null}

        {request.recorded ? (
          <section aria-label="Recorded tool call" className="flex flex-wrap items-center gap-2 text-xs">
            <h3 className="font-semibold tracking-wide text-zinc-400 uppercase">Recorded by the run</h3>
            {request.recorded.rows !== null ? (
              <StatusChip tone="info">
                {request.recorded.rows} row{request.recorded.rows === 1 ? "" : "s"}
              </StatusChip>
            ) : null}
            {request.recorded.ms !== null ? <StatusChip tone="info">engine {fmtMs(request.recorded.ms)}</StatusChip> : null}
            {request.recorded.digest ? (
              <span className="font-mono text-zinc-300" title={request.recorded.digest}>
                digest {shortDigest(request.recorded.digest, 16)}
              </span>
            ) : null}
          </section>
        ) : null}

        {!tid ? (
          <p className="rounded-md border border-dashed border-zinc-600 p-3 text-zinc-300">
            {ev
              ? `Produced by the tool "${ev.tool}" against ${ev.source} (the system under observation) and recorded in FalkorDB as an (:Evidence) node. It is not a graph query, so there is no Cypher to show, profile or re-run.`
              : "No template was recorded for this item, so there is no Cypher to show."}
          </p>
        ) : tplError ? (
          <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-red-200">
            Could not load template {tid}: {tplError}
          </p>
        ) : !tpl ? (
          <p className="text-zinc-400" aria-live="polite">
            Loading template {tid}…
          </p>
        ) : (
          <>
            <section aria-label="Template">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <h3 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">Cypher</h3>
                <span className="font-mono text-xs text-zinc-400">
                  {tpl.file} · LIMIT cap {tpl.limit}
                </span>
                <Button
                  size="xs"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => copy("Cypher", tpl.cypher)}
                >
                  <Copy aria-hidden /> Copy Cypher
                </Button>
              </div>
              {tpl.purpose ? <p className="mb-2 text-zinc-300">{tpl.purpose}</p> : null}
              {/* Focusable so keyboard users can scroll long Cypher (axe scrollable-region-focusable). */}
              <pre
                tabIndex={0}
                role="region"
                aria-label={`Cypher of ${tid}`}
                className="max-h-64 overflow-auto rounded-md border border-zinc-800 bg-zinc-950 p-3 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                {tpl.cypher}
              </pre>
            </section>

            <section aria-label="Parameters">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <h3 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
                  <label htmlFor="cypher-params">Params (JSON, editable)</label>
                </h3>
                <Button
                  size="xs"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => copy("params", paramsText)}
                >
                  <Copy aria-hidden /> Copy params
                </Button>
              </div>
              <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Where each param came from">
                {Object.entries(provenance).map(([k, p]) => (
                  <li key={k}>
                    <StatusChip tone={PROV_TONE[p]} title={PROV_TEXT[p]}>
                      <span className="font-mono">${k}</span>: {PROV_TEXT[p]}
                    </StatusChip>
                  </li>
                ))}
              </ul>
              <textarea
                id="cypher-params"
                spellCheck={false}
                value={paramsText}
                onChange={(e) => setParamsText(e.target.value)}
                rows={Math.min(12, Math.max(3, paramsText.split("\n").length))}
                className="w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 font-mono text-[12px] text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                aria-invalid={!parsed.ok}
                aria-describedby="cypher-params-help"
              />
              <p id="cypher-params-help" className="mt-1 text-xs text-zinc-400">
                {!parsed.ok ? (
                  <span className="text-red-300">Invalid JSON: {parsed.error}</span>
                ) : missing.length ? (
                  <span className="text-amber-300">
                    Missing values for {missing.map((m) => `$${m}`).join(", ")}: the engine will reject the query until
                    they are filled in.
                  </span>
                ) : (
                  "All template parameters have values."
                )}
              </p>
            </section>

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={doProfile} disabled={profBusy || !parsed.ok || !!offline}>
                <Gauge aria-hidden /> {profBusy ? "Profiling…" : "PROFILE"}
              </Button>
              <Button onClick={doRun} disabled={runBusy || !parsed.ok || !!offline}>
                <Play aria-hidden /> {runBusy ? "Running…" : "Re-run (read-only)"}
              </Button>
              {offline ? (
                <span role="note" className="flex items-center gap-1 text-xs text-amber-300">
                  <CircleSlash aria-hidden className="size-3.5" />
                  {offline.reason}
                </span>
              ) : (
                <span className="text-xs text-zinc-400">
                  Both go through the API&apos;s read-only path (GRAPH.RO_QUERY / GRAPH.PROFILE) on the incident&apos;s
                  graph, rate-limited 30/min.
                </span>
              )}
            </div>

            <section aria-label="Re-run result" aria-live="polite">
              {runErr ? (
                <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-red-200">
                  Re-run failed: {runErr}
                </p>
              ) : run ? (
                <RunResult run={run} evidence={combined ? null : ev /* one part's digest is not the combined one */} />
              ) : null}
            </section>

            <section aria-label="Profile result" aria-live="polite">
              {profErr ? (
                <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-red-200">
                  PROFILE failed: {profErr}
                </p>
              ) : prof ? (
                <ProfileResult prof={prof.res} rtt={prof.rtt} />
              ) : null}
            </section>
          </>
        )}
        <p className="sr-only" role="status">
          {copied ? `${copied} copied to the clipboard` : ""}
        </p>
        {copied ? (
          <p className="flex items-center gap-1 text-xs text-emerald-300" aria-hidden>
            <Check className="size-3.5" /> {copied} copied
          </p>
        ) : null}
      </div>
    </>
  );
}

function EvidenceFacts({ ev }: { ev: NonNullable<CypherRequest["evidence"]> }) {
  return (
    <section aria-label="Evidence" className="rounded-md border border-zinc-800 bg-zinc-950/60 p-3">
      <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-400 uppercase">Evidence {ev.id}</h3>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-zinc-400">kind</dt>
        <dd className="font-mono">{ev.kind}</dd>
        <dt className="text-zinc-400">source · tool</dt>
        <dd className="font-mono">
          {ev.source} · {ev.tool}
        </dd>
        <dt className="text-zinc-400">summary</dt>
        <dd className="break-words">{ev.summary}</dd>
        {ev.value !== null || ev.baseline !== null ? (
          <>
            <dt className="text-zinc-400">value / baseline</dt>
            <dd className="font-mono">
              {fmtValue(ev.value)} / {fmtValue(ev.baseline)}
            </dd>
          </>
        ) : null}
        <dt className="text-zinc-400">about</dt>
        <dd className="font-mono break-words">{ev.about.join(", ") || "–"}</dd>
        <dt className="text-zinc-400">digest</dt>
        <dd className="font-mono break-all">{ev.digest ?? "–"}</dd>
      </dl>
    </section>
  );
}

function RunResult({ run, evidence }: { run: TemplateRunResponse; evidence: CypherRequest["evidence"] }) {
  const cols = useMemo(() => {
    const c: string[] = [];
    for (const r of run.rows) for (const k of Object.keys(r)) if (!c.includes(k)) c.push(k);
    return c;
  }, [run.rows]);
  const shown = run.rows.slice(0, 50);
  const recorded = evidence?.source === "falkordb" ? evidence.digest : null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <StatusChip tone="info">
          {run.rows.length} row{run.rows.length === 1 ? "" : "s"}
        </StatusChip>
        <StatusChip tone="info">engine {fmtMs(run.ms)}</StatusChip>
        {run.truncated ? <StatusChip tone="warn">truncated at the LIMIT cap</StatusChip> : null}
        <span className="font-mono text-zinc-300" title={run.digest}>
          digest {shortDigest(run.digest, 16)}
        </span>
        {recorded ? (
          recorded === run.digest ? (
            <StatusChip tone="pass">matches recorded evidence {evidence?.id}</StatusChip>
          ) : (
            <StatusChip tone="warn" title={`recorded ${recorded}`}>
              differs from recorded evidence {evidence?.id} (params or graph state differ)
            </StatusChip>
          )
        ) : null}
      </div>
      <p className="text-xs text-zinc-400">
        served by <span className="font-mono text-zinc-200">{run.served_by}</span>
      </p>
      {run.rows.length === 0 ? (
        <p className="rounded-md border border-zinc-700 p-3 text-zinc-200">
          0 rows. For a G2 path query this means no path, so no claim.
        </p>
      ) : (
        <div className="max-h-72 overflow-auto rounded-md border border-zinc-800">
          <table className="w-full text-left font-mono text-[12px]">
            <caption className="sr-only">Rows returned by the read-only re-run</caption>
            <thead className="sticky top-0 bg-zinc-900 text-zinc-400">
              <tr>
                {cols.map((c) => (
                  <th key={c} scope="col" className="px-2 py-1 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i} className="border-t border-zinc-800 align-top">
                  {cols.map((c) => (
                    <td key={c} className="px-2 py-1 break-words text-zinc-100">
                      {Array.isArray(r[c]) && (r[c] as unknown[]).every((x) => typeof x === "string")
                        ? (r[c] as string[]).join(" → ")
                        : fmtValue(r[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {run.rows.length > shown.length ? (
        <p className="text-xs text-zinc-400">Showing the first {shown.length} of {run.rows.length} rows.</p>
      ) : null}
    </div>
  );
}

function ProfileResult({ prof, rtt }: { prof: ProfileResponse; rtt: number }) {
  const text = useMemo(() => (Array.isArray(prof.plan) ? prof.plan.join("\n") : String(prof.plan ?? "")), [prof.plan]);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <h3 className="font-semibold tracking-wide text-zinc-400 uppercase">GRAPH.PROFILE</h3>
        {typeof prof.engine_ms === "number" ? (
          <StatusChip tone="info">engine {fmtMs(prof.engine_ms)}</StatusChip>
        ) : (
          <StatusChip tone="na">engine timing not included in the profile response</StatusChip>
        )}
        <StatusChip tone="na">round trip {fmtMs(rtt)} (browser)</StatusChip>
        {prof.graph ? (
          <span className="text-zinc-400">
            on graph <span className="font-mono text-zinc-200">{prof.graph}</span>
          </span>
        ) : null}
      </div>
      <pre
        tabIndex={0}
        role="region"
        aria-label="GRAPH.PROFILE output"
        className="max-h-64 overflow-auto rounded-md border border-zinc-800 bg-zinc-950 p-3 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        {text}
      </pre>
    </div>
  );
}
