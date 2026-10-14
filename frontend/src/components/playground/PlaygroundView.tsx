"use client";

import { useEffect, useState } from "react";
import { FlaskConical, LoaderCircle } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type {
  PlaygroundMenu,
  PlaygroundResult,
} from "@/lib/types";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { Button } from "@/components/ui/button";
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

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold text-zinc-50">
          <FlaskConical aria-hidden className="size-5 text-amber-300" /> Break
          the graph
        </h1>
        <p className="max-w-3xl text-sm text-zinc-300">
          Change one thing in the graph and watch which decisions move. The
          change is applied to a{" "}
          <code className="font-mono text-zinc-100">GRAPH.COPY</code> of the
          hero incident{menu ? ` (${menu.scenario})` : ""}; the product then
          runs on the original and on the copy, and every decision is compared.
          If the graph were decoration, nothing would move.
        </p>
      </header>

      {menuErr ? (
        <p
          role="alert"
          className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100"
        >
          Playground unavailable: {menuErr}
        </p>
      ) : null}

      {menu ? (
        <fieldset className="space-y-2 fl-card rounded-2xl overflow-hidden p-3">
          <legend className="px-1 text-sm font-semibold text-zinc-100">
            Pick one change
          </legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {menu.perturbations.map((p) => (
              <label
                key={p.id}
                className={cn(
                  "flex cursor-pointer gap-2 rounded-md border p-2 text-sm",
                  pick === p.id
                    ? "border-amber-400 bg-amber-500/10"
                    : "border-zinc-700 hover:border-zinc-500",
                )}
              >
                <input
                  type="radio"
                  name="perturbation"
                  value={p.id}
                  checked={pick === p.id}
                  onChange={() => setPick(p.id)}
                  className="mt-1"
                />
                <span>
                  <span className="font-semibold text-zinc-50">{p.label}</span>
                  <span className="block text-xs text-zinc-400">{p.what}</span>
                  <span className="block text-xs text-zinc-300">
                    Expect: {p.expect}{" "}
                    <span className="font-mono text-zinc-400">
                      ({p.algorithm})
                    </span>
                  </span>
                </span>
              </label>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={run} disabled={busy || !pick}>
              {busy ? (
                <LoaderCircle
                  aria-hidden
                  className="motion-safe:animate-spin"
                />
              ) : null}
              {busy ? "Running the product twice…" : "Break it"}
            </Button>
          </div>
        </fieldset>
      ) : null}

      {err ? (
        <p
          role="alert"
          className="rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100"
        >
          Run failed: {err}
        </p>
      ) : null}

      {res ? (
        <section
          aria-labelledby="pg-diff"
          className="fl-card rounded-2xl overflow-hidden"
        >
          <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-3 py-2">
            <h2 id="pg-diff" className="text-sm font-semibold text-zinc-50">
              What moved
            </h2>
            <StatusChip tone={res.changed.length ? "warn" : "pass"}>
              {res.changed.length
                ? `${res.changed.length} decision(s) changed`
                : "no decision changed"}
            </StatusChip>
            <span className="text-xs text-zinc-400">
              applied:{" "}
              {Object.entries(res.applied)
                .map(([k, v]) => `${k} ${v}`)
                .join(", ")}{" "}
              · {res.seconds} s
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">
                Every decision before and after the change
              </caption>
              <thead className="text-zinc-400">
                <tr>
                  <th scope="col" className="px-3 py-2">
                    Decision
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Before
                  </th>
                  <th scope="col" className="px-3 py-2">
                    After
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Decided by
                  </th>
                </tr>
              </thead>
              <tbody>
                {res.diff.map((d) => (
                  <tr
                    key={d.decision}
                    className={cn(
                      "border-t border-zinc-800 align-top",
                      d.changed ? "bg-amber-500/10" : "",
                    )}
                  >
                    <th
                      scope="row"
                      className="px-3 py-2 font-medium text-zinc-100"
                    >
                      {d.decision}
                      {d.changed ? (
                        <span className="ml-1 text-amber-300">(changed)</span>
                      ) : null}
                    </th>
                    <td className="px-3 py-2 break-words text-zinc-300">
                      {show(d.before)}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2 break-words",
                        d.changed ? "text-amber-100" : "text-zinc-300",
                      )}
                    >
                      {show(d.after)}
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex flex-wrap gap-1">
                        {d.templates.map((t) => (
                          <button
                            key={t}
                            type="button"
                            onClick={() =>
                              panel.open({
                                template: t,
                                title: `${t} · ${d.decision}`,
                                origin: `playground: ${res.perturbation.label}`,
                                ctx: {},
                                tenant,
                              })
                            }
                            className="rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
                            aria-label={`${t}: open the Cypher that decides ${d.decision}`}
                          >
                            {t}
                          </button>
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
