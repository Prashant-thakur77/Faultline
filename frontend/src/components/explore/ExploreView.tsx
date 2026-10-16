"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { LayoutMode } from "@falkordb/canvas";
import { Code2, Crosshair, LoaderCircle, Network, OctagonAlert, TriangleAlert, X } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type { GraphResponse } from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { StatusChip } from "@/components/StatusChip";
import {
  CANVAS_PACKAGE,
  DOMAIN_COLOR,
  FalkorCanvas,
  LABEL_COLOR,
  OTHER_COLOR,
  WEAK_CAP,
  type CanvasStatus,
} from "./FalkorCanvas";

const LAYOUTS: { id: LayoutMode; text: string }[] = [
  { id: "force", text: "Force" },
  { id: "tree", text: "Tree" },
  { id: "radial", text: "Radial" },
];

type Load =
  | { state: "loading" }
  | { state: "ok"; data: GraphResponse; ms: number }
  | { state: "error"; error: string };

/**
 * /explore: the tenant's failure-flow graph (GET /api/graph) drawn by FalkorDB's own
 * `@falkordb/canvas` web component, with free force / tree / radial layouts for exploring.
 * The incident room keeps its fixed, committed layout; this view is for browsing.
 * Clicking a node opens its Cypher panel (Q-BLAST-1, re-runnable read-only); the node table
 * below is the keyboard and screen-reader alternative to the canvas.
 */
export function ExploreView({ tenant: urlTenant, focus }: { tenant: string | null; focus: string | null }) {
  const router = useRouter();
  // A ?tenant= in the URL wins (deep links; AppShell also selects it app-wide); else the top bar's tenant.
  const topBarTenant = useTenant();
  const tenant = urlTenant ?? topBarTenant;
  const panel = useCypherPanel();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [layout, setLayout] = useState<LayoutMode>("force");
  const [selected, setSelected] = useState<string | null>(null);
  const [canvas, setCanvas] = useState<CanvasStatus>({ state: "loading" });
  const [focusInput, setFocusInput] = useState(focus ?? "");

  useEffect(() => {
    const ac = new AbortController();
    const t0 = performance.now();
    api
      .graph({ tenant, focus: focus ?? undefined }, ac.signal)
      .then((data) => setLoad({ state: "ok", data, ms: performance.now() - t0 }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setLoad({ state: "error", error: errorText(err) });
      });
    return () => ac.abort();
  }, [tenant, focus]);

  const go = useCallback(
    (t: string, f: string | null) => {
      const qs = new URLSearchParams({ tenant: t });
      if (f) qs.set("focus", f);
      router.push(`/explore?${qs.toString()}`);
    },
    [router],
  );

  const data = load.state === "ok" ? load.data : null;
  const viewTemplate = focus ? "Q-VIEW-2" : "Q-VIEW-1";

  const openNode = useCallback(
    (id: string) => {
      setSelected(id);
      panel.open({
        template: "Q-BLAST-1",
        title: `blast radius of ${id}`,
        origin: `Explore (FalkorDB canvas) · ${data?.graph ?? `tenant_${tenant}`}`,
        detail: "Everything a failure at this node can reach: algo.BFS over PROPAGATES_TO.",
        ctx: { node: id },
        tenant,
      });
    },
    [panel, data?.graph, tenant],
  );

  const openView = () =>
    panel.open({
      template: viewTemplate,
      title: focus ? `scoped view around ${focus}` : "unscoped failure-flow view",
      origin: `GET /api/graph?tenant=${tenant}${focus ? `&focus=${focus}` : ""}`,
      detail: focus
        ? "The API composes $ids from the focus, its blast radius (Q-BLAST-1) and its upstream within 3 hops (Q-LIN-1); the ids pre-filled here are the nodes that came back (derived). Node sizes use Q-CHOKE-ALL (betweenness)."
        : "Node sizes use Q-CHOKE-ALL (betweenness).",
      ctx: { ids: focus && data ? data.nodes.map((n) => n.id) : undefined, node: focus ?? undefined },
      tenant,
    });

  const sortedNodes = useMemo(
    () => (data ? [...data.nodes].sort((a, b) => (b.betweenness ?? -1) - (a.betweenness ?? -1) || a.id.localeCompare(b.id)) : []),
    [data],
  );
  const degree = useMemo(() => {
    const m = new Map<string, { out: number; in: number }>();
    for (const e of data?.edges ?? []) {
      m.set(e.source, { out: (m.get(e.source)?.out ?? 0) + 1, in: m.get(e.source)?.in ?? 0 });
      m.set(e.target, { out: m.get(e.target)?.out ?? 0, in: (m.get(e.target)?.in ?? 0) + 1 });
    }
    return m;
  }, [data]);
  const labelsPresent = useMemo(() => [...new Set((data?.nodes ?? []).map((n) => n.label))].sort(), [data]);
  const domainsPresent = useMemo(() => [...new Set((data?.edges ?? []).map((e) => e.domain))].sort(), [data]);

  const live =
    load.state === "loading"
      ? `Loading the ${focus ? `view around ${focus}` : "graph"} of tenant_${tenant} from FalkorDB…`
      : load.state === "error"
        ? `Graph not loaded: ${load.error}`
        : `${data!.graph}: ${data!.nodes.length} nodes, ${data!.edges.length} edges${data!.truncated ? " (truncated at the template LIMIT)" : ""}. Canvas ${canvas.state}.`;

  return (
    <div className="mx-auto flex w-full max-w-[1920px] flex-1 flex-col gap-3 p-4 lg:min-h-0">
      <header className="flex flex-wrap items-start gap-x-6 gap-y-2">
        <div className="min-w-0 space-y-1">
          <h1 className="flex items-center gap-2 text-lg font-semibold text-zinc-50">
            <Network aria-hidden className="size-5 text-sky-300" /> Explore (FalkorDB canvas)
          </h1>
          <p className="max-w-3xl text-sm text-zinc-300">
            The live failure-flow graph (<code className="font-mono text-zinc-200">PROPAGATES_TO</code>, from{" "}
            <code className="font-mono text-zinc-200">GET /api/graph</code>) drawn by FalkorDB&apos;s{" "}
            <code className="font-mono text-zinc-200">{CANVAS_PACKAGE}</code> web component. Free layouts for browsing;
            the incident room keeps its fixed layout. Click a node (or use the table) to open its Cypher.
          </p>
        </div>
        <form
          className="ml-auto flex flex-wrap items-end gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            go(tenant, focusInput.trim() || null);
          }}
        >
          <p className="flex flex-col gap-0.5">
            <span className="text-xs text-zinc-400">Tenant (switch in the top bar)</span>
            <span className="py-1 font-mono text-zinc-100">tenant_{tenant}</span>
          </p>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-zinc-400">Focus node id (scopes large tenants)</span>
            <input
              value={focusInput}
              onChange={(e) => setFocusInput(e.target.value)}
              list="explore-node-ids"
              placeholder="none: whole graph"
              className="w-56 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-zinc-100 outline-none placeholder:text-zinc-500 focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            <datalist id="explore-node-ids">
              {sortedNodes.map((n) => (
                <option key={n.id} value={n.id} />
              ))}
            </datalist>
          </label>
          <button
            type="submit"
            className="inline-flex items-center gap-1 rounded-md border border-sky-500/50 bg-sky-500/10 px-2.5 py-1 font-medium text-sky-200 outline-none hover:bg-sky-500/20 focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            <Crosshair aria-hidden className="size-4" /> Scope
          </button>
          {focus ? (
            <button
              type="button"
              onClick={() => {
                setFocusInput("");
                go(tenant, null);
              }}
              className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1 text-zinc-200 outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <X aria-hidden className="size-4" /> Clear focus
            </button>
          ) : null}
          <fieldset className="flex flex-col gap-0.5">
            <legend className="text-xs text-zinc-400">Layout</legend>
            <div role="radiogroup" aria-label="Layout" className="flex overflow-hidden rounded-md border border-zinc-700">
              {LAYOUTS.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  role="radio"
                  aria-checked={layout === l.id}
                  onClick={() => setLayout(l.id)}
                  className={
                    "px-2.5 py-1 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-inset " +
                    (layout === l.id ? "bg-zinc-700 font-semibold text-zinc-50" : "text-zinc-300 hover:bg-zinc-800")
                  }
                >
                  {l.text}
                </button>
              ))}
            </div>
          </fieldset>
          <button
            type="button"
            onClick={openView}
            disabled={load.state !== "ok"}
            className="inline-flex items-center gap-1 rounded-md border border-violet-500/50 bg-violet-500/10 px-2.5 py-1 text-violet-200 outline-none hover:bg-violet-500/20 focus-visible:ring-2 focus-visible:ring-violet-400 disabled:opacity-50"
          >
            <Code2 aria-hidden className="size-4" /> View query ({viewTemplate})
          </button>
        </form>
      </header>

      <p aria-live="polite" className="sr-only">
        {live}
      </p>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        {load.state === "loading" ? (
          <StatusChip tone="running" icon={LoaderCircle}>
            loading graph…
          </StatusChip>
        ) : load.state === "ok" ? (
          <>
            <StatusChip tone="pass">
              {data!.graph} · {data!.nodes.length} nodes · {data!.edges.length} edges · {Math.round(load.ms)} ms
            </StatusChip>
            {focus ? (
              <StatusChip tone="info" icon={Crosshair}>
                scoped to {focus}: upstream ≤ 3 hops + blast radius
              </StatusChip>
            ) : (
              <StatusChip tone="info">unscoped</StatusChip>
            )}
            {data!.truncated ? (
              <StatusChip tone="warn" icon={TriangleAlert} title="The view hit the template LIMIT">
                truncated: not the whole graph (template LIMIT); scope it with a focus node
              </StatusChip>
            ) : (
              <StatusChip tone="pass">complete (under the template LIMIT)</StatusChip>
            )}
          </>
        ) : null}
        {canvas.state === "loading" ? (
          <StatusChip tone="running" icon={LoaderCircle}>
            loading {CANVAS_PACKAGE}…
          </StatusChip>
        ) : canvas.state === "error" ? (
          <StatusChip tone="fail" icon={OctagonAlert}>
            canvas failed
          </StatusChip>
        ) : null}
      </div>

      {load.state === "error" ? (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-500/60 bg-red-950/60 p-3 text-sm text-red-100">
          <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
          <p>
            <strong className="font-semibold">Graph unavailable:</strong> {load.error}. No substitute data is shown.{" "}
            <Link href="/replay/s1-hero" className="font-semibold text-sky-200 underline">
              Watch the recorded run
            </Link>
          </p>
        </div>
      ) : null}
      {canvas.state === "error" ? (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-500/60 bg-red-950/60 p-3 text-sm text-red-100">
          <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
          <p>
            <strong className="font-semibold">Canvas unavailable:</strong> {canvas.error}. The node table below still lists the
            graph.
          </p>
        </div>
      ) : null}
      {data && data.nodes.length === 0 ? (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-amber-500/50 bg-amber-950/40 p-3 text-sm text-amber-100">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-300" />
          <p>
            0 nodes: {focus ? <>no failure-flow node <code className="font-mono">{focus}</code> in {data.graph}</> : <>{data.graph} has no failure-flow edges</>}.
          </p>
        </div>
      ) : null}

      <div className="grid gap-3 lg:h-[min(82vh,900px)] lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section aria-labelledby="explore-canvas-h" className="flex min-h-[560px] flex-col fl-card rounded-2xl overflow-hidden">
          <h2 id="explore-canvas-h" className="sr-only">
            Graph canvas
          </h2>
          <div className="relative min-h-0 flex-1">
            {data && data.nodes.length > 0 ? (
              <FalkorCanvas
                data={data}
                layout={layout}
                selected={selected}
                focus={focus}
                onNodeClick={openNode}
                onStatus={setCanvas}
                label={`${data.graph} failure-flow graph, ${data.nodes.length} nodes and ${data.edges.length} edges, drawn by ${CANVAS_PACKAGE}. The node table lists the same graph.`}
              />
            ) : null}
          </div>
          <Legend labels={labelsPresent} domains={domainsPresent} />
        </section>

        <section aria-labelledby="explore-table-h" className="flex min-h-0 flex-col fl-card rounded-2xl p-4">
          <h2 id="explore-table-h" className="mb-2 text-sm font-semibold text-zinc-50">
            Nodes (text alternative), by betweenness
          </h2>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Nodes of the graph shown, with label, tier, betweenness and degree</caption>
              <thead className="sticky top-0 bg-zinc-900 text-zinc-400">
                <tr>
                  <th scope="col" className="py-1 pr-2 font-medium">node</th>
                  <th scope="col" className="py-1 pr-2 font-medium">label</th>
                  <th scope="col" className="py-1 pr-2 text-right font-medium">betw.</th>
                  <th scope="col" className="py-1 pr-2 text-right font-medium">in/out</th>
                  <th scope="col" className="py-1 font-medium"><span className="sr-only">actions</span></th>
                </tr>
              </thead>
              <tbody>
                {sortedNodes.map((n) => {
                  const d = degree.get(n.id);
                  const isSel = n.id === selected || n.id === focus;
                  return (
                    <tr key={n.id} className={"border-t border-zinc-800 " + (isSel ? "bg-sky-500/10" : "")}>
                      <th scope="row" className="py-1 pr-2 font-mono font-normal break-all text-zinc-100">
                        {n.id}
                        {n.id === focus ? <span className="ml-1 text-sky-300">(focus)</span> : null}
                      </th>
                      <td className="py-1 pr-2 whitespace-nowrap text-zinc-300">
                        <span aria-hidden className="mr-1 inline-block size-2 rounded-full" style={{ background: LABEL_COLOR[n.label] ?? OTHER_COLOR }} />
                        {n.label}
                        {n.tier !== null ? <span className="text-zinc-400"> · t{n.tier}</span> : null}
                      </td>
                      <td className="py-1 pr-2 text-right font-mono text-zinc-200">{n.betweenness == null ? "–" : n.betweenness.toFixed(1)}</td>
                      <td className="py-1 pr-2 text-right font-mono text-zinc-300">
                        {d?.in ?? 0}/{d?.out ?? 0}
                      </td>
                      <td className="py-1">
                        <div className="flex gap-1">
                          <button
                            type="button"
                            onClick={() => openNode(n.id)}
                            className="inline-flex min-h-6 items-center rounded border border-violet-500/40 px-1.5 py-0.5 text-violet-200 outline-none hover:bg-violet-500/15 focus-visible:ring-2 focus-visible:ring-violet-400"
                          >
                            Cypher<span className="sr-only"> for {n.id} (Q-BLAST-1)</span>
                          </button>
                          {n.id !== focus ? (
                            <button
                              type="button"
                              onClick={() => {
                                setFocusInput(n.id);
                                go(tenant, n.id);
                              }}
                              className="inline-flex min-h-6 items-center rounded border border-sky-500/40 px-1.5 py-0.5 text-sky-200 outline-none hover:bg-sky-500/15 focus-visible:ring-2 focus-visible:ring-sky-400"
                            >
                              Focus<span className="sr-only"> the view on {n.id}</span>
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {data && data.edges.length > 0 ? (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer rounded text-zinc-300 outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                  Edges ({data.edges.length}): source → target, domain, capacity
                </summary>
                <table className="mt-1 w-full text-left">
                  <caption className="sr-only">PROPAGATES_TO edges with domain and capacity</caption>
                  <thead className="text-zinc-400">
                    <tr>
                      <th scope="col" className="py-1 pr-2 font-medium">edge</th>
                      <th scope="col" className="py-1 pr-2 font-medium">domain</th>
                      <th scope="col" className="py-1 text-right font-medium">cap</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.edges.map((e) => (
                      <tr key={`${e.source}>${e.target}`} className="border-t border-zinc-800">
                        <td className="py-1 pr-2 font-mono break-all text-zinc-200">
                          {e.source} → {e.target}
                        </td>
                        <td className="py-1 pr-2 text-zinc-300">{e.domain}</td>
                        <td className="py-1 text-right font-mono text-zinc-200">{e.cap == null ? "–" : e.cap}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function Legend({ labels, domains }: { labels: string[]; domains: string[] }) {
  if (!labels.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-800 px-3 py-2 text-xs text-zinc-300">
      <span className="text-zinc-400">Nodes:</span>
      {labels.map((l) => (
        <span key={l} className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: LABEL_COLOR[l] ?? OTHER_COLOR }} />
          {l}
        </span>
      ))}
      <span className="text-zinc-400">· size = betweenness (Q-CHOKE-ALL)</span>
      <span className="text-zinc-400">Edges:</span>
      {domains.map((d) => (
        <span key={d} className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block h-0.5 w-4" style={{ background: DOMAIN_COLOR[d] ?? OTHER_COLOR }} />
          {d}
        </span>
      ))}
      <span className="text-zinc-400">· width = capacity; dashed = cap &lt; {WEAK_CAP}</span>
    </div>
  );
}
