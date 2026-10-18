"use client";

import { Blocks, FileCode, Fingerprint, LoaderCircle, OctagonAlert, PackageCheck, PackageX, SquareFunction } from "lucide-react";
import { useAppStatus } from "@/components/AppShell";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { Section } from "@/components/incident/Section";
import { StatusChip } from "@/components/StatusChip";
import type { StatusState } from "@/hooks/useStatus";
import type { UdfDetail, UdfLibrary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EngineVia } from "./bits";

/** One line per library we pin; a library the server names that is not here gets no description (none invented). */
const ABOUT: Record<string, string> = {
  flex: "FalkorDB's FLEX, vendored unmodified",
  faultline: "ours: scoring that runs inside the engine",
};

/** Libraries whose every function is ours, so the card lists all of them, not only the ones the queries call. */
const OURS = new Set(["faultline"]);

const CHIP_CLS = "inline-flex items-center rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-zinc-200 ring-1 ring-white/[0.08]";

/** The `{error}` form of udf_detail (GRAPH.UDF LIST failed), or null when it lists libraries. */
export function udfError(d: UdfDetail): string | null {
  const e = (d as { error?: unknown }).error;
  return typeof e === "string" ? e : null;
}

/** The libraries in the order the server sent them. */
export function udfLibraries(d: UdfDetail): [string, UdfLibrary][] {
  if (udfError(d) !== null) return [];
  return Object.entries(d as Record<string, UdfLibrary>);
}

/** The name a query calls: `flex.sim.jaccard` (the engine and the templates may give it with or without the prefix). */
export function qualified(lib: string, fn: string): string {
  return fn.startsWith(`${lib}.`) ? fn : `${lib}.${fn}`;
}

const sha = (s: string | null) => (s ? s.slice(0, 12) : "–");

/**
 * The UDF libraries loaded into FalkorDB (GRAPH.UDF LIST, read by GET /api/status): per library its state against the
 * pinned sha256, the functions our queries call and the templates that call them (each opens its Cypher). Fails loudly:
 * an unreadable list, FalkorDB down or an API that does not answer is said, and nothing is shown as loaded.
 */
export function UdfCard({ tenant, state }: { tenant: string; /** Tests pass a status; the page reads the app-wide poll. */ state?: StatusState }) {
  const app = useAppStatus();
  const st = state ?? app;
  const s = st.status;
  const detail = s?.status === "ok" ? s.udf_detail : undefined;
  const err = detail ? udfError(detail) : null;
  const libs = detail ? udfLibraries(detail) : [];
  const bad = libs.filter(([, l]) => l.state !== "loaded").length;

  let aside: React.ReactNode = null;
  if (err !== null) aside = <StatusChip tone="fail">unreadable</StatusChip>;
  else if (libs.length)
    aside = bad ? (
      <StatusChip tone="fail" icon={PackageX}>
        {bad} of {libs.length} not loaded as pinned
      </StatusChip>
    ) : (
      <StatusChip tone="pass" icon={PackageCheck}>
        {libs.length} of {libs.length} loaded
      </StatusChip>
    );

  let body: React.ReactNode;
  if (!s && st.error) {
    body = (
      <Alert>
        The Faultline API did not answer (GET /api/status): {st.error.replace(/\.$/, "")}. No library is shown in its place.
      </Alert>
    );
  } else if (!s) {
    body = (
      <p className="flex items-center gap-1.5 text-sm text-zinc-300">
        <LoaderCircle aria-hidden className="size-3.5 text-zinc-400 motion-safe:animate-spin" />
        Reading the libraries from FalkorDB…
      </p>
    );
  } else if (s.status !== "ok") {
    body = <Alert>FalkorDB is unavailable{s.reason ? `: ${s.reason.replace(/\.$/, "")}` : ""}. The libraries cannot be read, so none is shown.</Alert>;
  } else if (!detail) {
    body = (
      <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
        This server&apos;s status has no library detail, so nothing is shown here.
      </p>
    );
  } else if (err !== null) {
    body = <Alert>FalkorDB did not list its libraries (GRAPH.UDF LIST): {err.replace(/\.$/, "")}. No library is shown as loaded.</Alert>;
  } else if (!libs.length) {
    body = (
      <p className="rounded-xl bg-white/[0.02] px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/[0.05]">
        The status names no pinned library.
      </p>
    );
  } else {
    body = (
      <ul aria-label="UDF libraries" className="space-y-2">
        {libs.map(([name, lib]) => (
          <Library key={name} name={name} lib={lib} tenant={tenant} />
        ))}
      </ul>
    );
  }

  return (
    <Section id="engine-udf" title="UDF libraries in the engine" via={<EngineVia what="GRAPH.UDF LIST" />} aside={aside}>
      <p className="mb-3 text-xs leading-relaxed text-zinc-400">
        Functions loaded into FalkorDB with GRAPH.UDF LOAD, pinned by sha256, called inside read-only queries.
      </p>
      {st.error && s ? (
        <p role="alert" className="mb-2 text-[11px] text-red-200">
          The last status read failed ({st.error.replace(/\.$/, "")}); this is the answer before it.
        </p>
      ) : null}
      {body}
    </Section>
  );
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-100 ring-1 ring-red-500/40">
      <OctagonAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-red-300" />
      <span>{children}</span>
    </p>
  );
}

function Library({ name, lib, tenant }: { name: string; lib: UdfLibrary; tenant: string }) {
  const panel = useCypherPanel();
  const ours = OURS.has(name);
  // ours: every function the engine registered (or, when it has none loaded, the ones the queries call)
  // an API from before the function lists sends none: show the library without them instead of failing the page
  const functions = lib.functions ?? [];
  const all = ours && functions.length > 0;
  const fns = all ? functions : (lib.used ?? []);
  const templates = lib.templates ?? [];
  const fnLabel = all ? `Functions (${fns.length})` : "Called by our queries";
  const open = (id: string) =>
    panel.open({
      template: id,
      title: `${id} · calls ${name}`,
      origin: "the UDF libraries in the engine (GRAPH.UDF LIST via GET /api/status)",
      detail: `This template calls functions of the ${name} library, which is loaded into FalkorDB and pinned by sha256 (${sha(lib.pinned_sha)}).`,
      recordedParams: null,
      ctx: {},
      tenant,
    });

  return (
    <li className="rounded-xl bg-white/[0.02] px-3.5 py-3 ring-1 ring-white/[0.06]">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 items-start gap-2">
          <Blocks aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--fl-subtle)]" />
          <div className="min-w-0">
            <p className="font-mono text-sm text-zinc-50">{name}</p>
            {ABOUT[name] ? <p className="text-[11px] text-zinc-400">{ABOUT[name]}</p> : null}
          </div>
        </div>
        <LibState lib={lib} />
      </div>
      {lib.state !== "loaded" ? (
        <p className="mt-1.5 text-[11px] leading-relaxed text-red-200">
          {lib.state === "mismatch"
            ? `FalkorDB has different code under this name (sha256 ${sha(lib.loaded_sha)}, pinned ${sha(lib.pinned_sha)}), so the queries below would not run the pinned functions. Restart the API or run make up to load the pinned file.`
            : "Not loaded in FalkorDB, so the queries below fail. Restart the API or run make up."}
        </p>
      ) : null}
      <dl className="mt-2 space-y-2 text-[11px] text-zinc-400">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <dt className="inline-flex items-center gap-1">
            <Fingerprint aria-hidden className="size-3 text-[var(--fl-subtle)]" />
            Pinned sha256
          </dt>
          <dd className="font-mono text-zinc-200" title={lib.pinned_sha}>
            {sha(lib.pinned_sha)}
          </dd>
          {lib.state === "mismatch" ? (
            <>
              <dt className="ml-2">loaded</dt>
              <dd className="font-mono text-red-200">{sha(lib.loaded_sha)}</dd>
            </>
          ) : null}
        </div>
        <div>
          <dt className="mb-1 inline-flex items-center gap-1">
            <SquareFunction aria-hidden className="size-3 text-[var(--fl-subtle)]" />
            {fnLabel}
          </dt>
          <dd>
            {fns.length ? (
              <ul aria-label={`${name}: ${all ? "functions" : "functions our queries call"}`} className="flex flex-wrap gap-1">
                {fns.map((f) => (
                  <li key={f} className={CHIP_CLS}>
                    {qualified(name, f)}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-zinc-300">none</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="mb-1 inline-flex items-center gap-1">
            <FileCode aria-hidden className="size-3 text-[var(--fl-subtle)]" />
            Templates that call {fns.length === 1 ? "it" : "them"}
          </dt>
          <dd>
            {templates.length ? (
              <ul aria-label={`${name}: templates that call it`} className="flex flex-wrap gap-1">
                {templates.map((id) => (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => open(id)}
                      aria-label={`${id}: open the Cypher panel for this template`}
                      className={cn(QUERY_ID_CLS, "text-sky-300 ring-1 ring-white/[0.08] hover:text-sky-200")}
                    >
                      {id}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-zinc-300">no template calls this library</span>
            )}
          </dd>
        </div>
      </dl>
    </li>
  );
}

function LibState({ lib }: { lib: UdfLibrary }) {
  if (lib.state === "loaded") return <StatusChip tone="pass">loaded</StatusChip>;
  if (lib.state === "mismatch") return <StatusChip tone="fail">different code loaded</StatusChip>;
  return <StatusChip tone="fail">not loaded</StatusChip>;
}
