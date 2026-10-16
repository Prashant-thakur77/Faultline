"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Database, LoaderCircle } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type { Perturbation, PlaygroundMenu, PlaygroundResult } from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";

/** A value from the diff, readable: lists joined, suspect verdicts as "status: reason", empty as "—". */
function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length ? v.join(" · ") : "—";
  if (typeof v === "object") {
    const o = v as { status?: string; reason?: string };
    if (o.status) return `${o.status}: ${o.reason ?? ""}`;
    return JSON.stringify(v);
  }
  return String(v);
}

/** "algo.SPpaths / algo.BFS" or "algo.maxFlow + G4 origin" → the parts, as the menu names them (no names added). */
function algoParts(algorithm: string): string[] {
  return algorithm
    .split(/\s*[/+]\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** A quiet, non-interactive "via FalkorDB · algo.X" mark (the menu names procedures, not templates to open). */
function AlgoChip({ parts, max }: { parts: string[]; max?: number }) {
  const shown = max ? parts.slice(0, max) : parts;
  const more = parts.length - shown.length;
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 text-[11px] text-[var(--fl-subtle)]">
      <Database aria-hidden className="size-3 shrink-0" />
      <span>via FalkorDB</span>
      <span aria-hidden>·</span>
      <span className="truncate font-mono text-zinc-300">
        {shown.join(" · ")}
        {more > 0 ? ` +${more}` : ""}
      </span>
    </span>
  );
}

/**
 * Break the graph (M15 #2): pick one change from a fixed menu. The API applies it to a GRAPH.COPY of the hero
 * incident's clean room, runs the product on both rooms and returns every decision before/after with the templates
 * that decide it. Nothing here decides anything: the diff is the product's own output, read twice.
 */
export function PlaygroundView() {
  const tenant = useTenant();
  const panel = useCypherPanel();
  const [menu, setMenu] = useState<PlaygroundMenu | null>(null);
  const [menuErr, setMenuErr] = useState<string | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<PlaygroundResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const resultRef = useRef<HTMLElement>(null);

  useEffect(() => {
    api.playgroundMenu().then(
      (m) => {
        setMenu(m);
        setPick(m.perturbations[0]?.id ?? null);
      },
      (e) => setMenuErr(errorText(e)),
    );
  }, []);

  async function run() {
    if (!pick) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      setRes(await api.playgroundRun(pick));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  // bring the result into view once it lands (no smooth scroll under reduced motion)
  useEffect(() => {
    if (!res) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    resultRef.current?.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }, [res]);

  const sel = menu?.perturbations.find((p) => p.id === pick) ?? null;

  return (
    <div className="mx-auto w-full max-w-[1200px] space-y-6 px-5 py-6 sm:px-8">
      <Disclosure size="xs" defaultOpen={false} summary="How it works">
        <p className="max-w-3xl text-[13px] leading-relaxed text-[var(--fl-muted)]">
          The change is applied to a <code className="font-mono text-zinc-200">GRAPH.COPY</code> of the hero
          incident{menu ? ` (${menu.scenario})` : ""}. The product then runs on the original and on the copy, and every
          decision is compared, each with the query that decides it. If the graph were decoration, nothing would move.
        </p>
      </Disclosure>

      {menuErr ? (
        <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-500/40">
          Playground unavailable: {menuErr}
        </p>
      ) : null}

      {menu ? (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-start">
          <fieldset className="min-w-0">
            <legend className="mb-3 text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">Pick one change</legend>
            <ul className="space-y-2">
              {menu.perturbations.map((p) => (
                <OptionCard key={p.id} p={p} checked={pick === p.id} onPick={() => setPick(p.id)} disabled={busy} />
              ))}
            </ul>
          </fieldset>

          {sel ? (
            <section
              aria-labelledby="pg-sel-h"
              className="fl-card rounded-2xl px-5 py-5 sm:px-6 lg:sticky lg:top-4"
            >
              <p className="text-xs text-[var(--fl-subtle)]">Selected change</p>
              <h2 id="pg-sel-h" className="mt-1 text-lg font-[560] leading-snug tracking-[-0.01em] text-zinc-50">
                {sel.label}
              </h2>
              <dl className="mt-5 space-y-4">
                <div>
                  <dt className="text-xs font-medium text-zinc-400">What changes</dt>
                  <dd className="mt-1 text-sm leading-relaxed text-zinc-200">{sel.what}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-zinc-400">What should move</dt>
                  <dd className="mt-1 text-sm leading-relaxed text-zinc-200">{sel.expect}</dd>
                  <dd className="mt-2">
                    <AlgoChip parts={algoParts(sel.algorithm)} />
                  </dd>
                </div>
              </dl>
              <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-white/[0.06] pt-5">
                <button
                  type="button"
                  onClick={run}
                  disabled={busy || !pick}
                  aria-describedby="pg-run-help"
                  className="fl-press inline-flex min-h-10 items-center gap-2 rounded-full bg-zinc-50 px-5 text-sm font-medium text-zinc-950 outline-none hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busy ? (
                    <>
                      <LoaderCircle aria-hidden className="size-4 motion-safe:animate-spin" />
                      Running the product twice…
                    </>
                  ) : (
                    <>
                      Break it
                      <ArrowRight aria-hidden className="size-4" />
                    </>
                  )}
                </button>
                <p id="pg-run-help" className="text-xs text-[var(--fl-subtle)]">
                  Runs on a GRAPH.COPY; the original graph is not touched.
                </p>
              </div>
            </section>
          ) : null}
        </div>
      ) : null}

      {busy ? (
        <p role="status" className="fl-card flex items-center gap-2 rounded-2xl px-5 py-4 text-sm text-zinc-300">
          <LoaderCircle aria-hidden className="size-4 text-zinc-400 motion-safe:animate-spin" />
          Running the product on the original and on the copy, then comparing every decision…
        </p>
      ) : null}

      {err ? (
        <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-500/40">
          Run failed: {err}
        </p>
      ) : null}

      {res ? (
        <section ref={resultRef} aria-labelledby="pg-diff" className="fl-card scroll-mt-4 overflow-hidden rounded-2xl">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 pt-4 pb-3">
            <h2 id="pg-diff" className="text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
              What moved
            </h2>
            <StatusChip tone={res.changed.length ? "warn" : "pass"}>
              {res.changed.length ? `${res.changed.length} decision(s) changed` : "no decision changed"}
            </StatusChip>
            <span className="text-xs text-[var(--fl-subtle)]">
              {res.perturbation.label} · applied{" "}
              {Object.entries(res.applied)
                .map(([k, v]) => `${k} ${v}`)
                .join(", ")}{" "}
              · {res.seconds} s
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Every decision before and after the change</caption>
              <thead className="text-[var(--fl-subtle)] max-sm:sr-only">
                <tr className="border-t border-white/[0.06]">
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Decision
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    Before
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    After
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    Decided by
                  </th>
                </tr>
              </thead>
              <tbody>
                {res.diff.map((d) => (
                  <tr
                    key={d.decision}
                    className={cn(
                      "border-t border-white/[0.06] align-top max-sm:grid max-sm:grid-cols-2 max-sm:gap-x-4 max-sm:gap-y-2 max-sm:px-5 max-sm:py-3",
                      d.changed && "shadow-[inset_2px_0_0_var(--color-amber-400)]",
                    )}
                  >
                    <th scope="row" className="px-5 py-2.5 font-medium text-zinc-100 max-sm:col-span-2 max-sm:p-0">
                      {d.decision}
                      {d.changed ? <span className="ml-1.5 text-[11px] font-normal text-amber-300">(changed)</span> : null}
                    </th>
                    <td className="px-3 py-2.5 break-words text-zinc-400 max-sm:p-0">
                      <span aria-hidden className="mb-0.5 block text-[10px] text-[var(--fl-subtle)] sm:hidden">Before</span>
                      {show(d.before)}
                    </td>
                    <td className={cn("px-3 py-2.5 break-words max-sm:p-0", d.changed ? "text-zinc-50" : "text-zinc-400")}>
                      <span aria-hidden className="mb-0.5 block text-[10px] text-[var(--fl-subtle)] sm:hidden">After</span>
                      {show(d.after)}
                    </td>
                    <td className="px-3 py-2 max-sm:col-span-2 max-sm:p-0">
                      <span className="flex flex-wrap gap-1">
                        {d.templates.map((t) => (
                          <ViaFalkor
                            key={t}
                            compact
                            template={t}
                            label={`the decision ${d.decision}`}
                            onOpen={() =>
                              panel.open({
                                template: t,
                                title: `${t} · ${d.decision}`,
                                origin: `playground: ${res.perturbation.label}`,
                                ctx: {},
                                tenant,
                              })
                            }
                          />
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

/**
 * One option: a native radio laid invisibly over the whole card (so a click anywhere is a click on the radio itself),
 * shown as an indicator in the page accent; keyboard and screen readers see the plain radio, the title and one quiet "via FalkorDB" mark. The mechanics and the expectation are the selected
 * option's detail panel; for the others they stay available to assistive tech as the radio's description.
 */
function OptionCard({ p, checked, onPick, disabled }: { p: Perturbation; checked: boolean; onPick: () => void; disabled: boolean }) {
  const descId = `pg-opt-${p.id}-desc`;
  return (
    <li>
      <label
        className={cn(
          "group relative flex cursor-pointer items-start gap-3 rounded-xl px-4 py-3.5 ring-1 transition-[background-color,box-shadow] duration-150",
          "has-[input:focus-visible]:ring-2 has-[input:focus-visible]:ring-sky-400",
          checked
            ? "bg-white/[0.05] shadow-[0_12px_32px_-18px_rgb(0_0_0/0.9)] ring-[color-mix(in_oklch,var(--fl-iris)_70%,transparent)]"
            : "bg-white/[0.015] ring-white/[0.06] hover:bg-white/[0.03] hover:ring-white/[0.12]",
        )}
      >
        <input
          type="radio"
          name="perturbation"
          value={p.id}
          checked={checked}
          onChange={onPick}
          disabled={disabled}
          aria-describedby={descId}
          className="absolute inset-0 z-10 m-0 size-full cursor-pointer appearance-none rounded-xl opacity-0 disabled:cursor-not-allowed"
        />
        <span
          aria-hidden
          className={cn(
            "mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border transition-colors",
            checked ? "border-[var(--fl-iris)]" : "border-zinc-500 group-hover:border-zinc-300",
          )}
        >
          <span className={cn("size-2 rounded-full transition-transform", checked ? "scale-100 bg-[var(--fl-iris)]" : "scale-0")} />
        </span>
        <span className="min-w-0 space-y-1">
          <span className={cn("block text-sm leading-snug", checked ? "font-medium text-zinc-50" : "text-zinc-200")}>{p.label}</span>
          <AlgoChip parts={algoParts(p.algorithm)} max={1} />
        </span>
      </label>
      <span id={descId} className="sr-only">
        {p.what}. Expect: {p.expect}
      </span>
    </li>
  );
}
