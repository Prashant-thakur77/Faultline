"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Cpu, Play, Star } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { slugWords } from "@/lib/format";
import { HERO_SCENARIO, RUN_HERO_EVENT, RUN_SCENARIO_EVENT } from "@/lib/heroRun";
import { tenantStore } from "@/lib/tenant";
import Link from "next/link";
import type { LlmMode, RunScenarioIncident, Scenario } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAppStatus } from "./AppShell";
import { StatusChip } from "./StatusChip";

/**
 * Lists GET /api/scenarios (the hero scenario first) and starts one with POST /api/scenarios/{id}/run, then opens its
 * incident room. The home hero's "Run the hero incident" asks for the hero run with a window event (lib/heroRun).
 */
/** The scenario list scrolls inside the card on desktop and fades out at the bottom. */
const SCROLL = "outline-none focus-visible:ring-2 focus-visible:ring-sky-400 lg:[mask-image:linear-gradient(to_bottom,#000_calc(100%-2.5rem),transparent)]";

export function ScenarioLauncher() {
  const router = useRouter();
  const { status } = useAppStatus();
  const llmConfigured = status?.llm_configured === true;
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [llm, setLlm] = useState<LlmMode>("baseline");
  const [busy, setBusy] = useState<string | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [opened, setOpened] = useState<{ scenario: string; tenant: string | null; incidents: RunScenarioIncident[] } | null>(
    null,
  );
  const groupId = useId();
  // the hero call to action may fire before the list has loaded: it is remembered and run once the list arrives
  const heroPending = useRef(false);

  const effectiveLlm: LlmMode = llm === "anthropic" && !llmConfigured ? "baseline" : llm;

  // the hero first, the rest in the API's order
  const ordered = useMemo(
    () => (scenarios ? [...scenarios.filter((s) => s.id === HERO_SCENARIO), ...scenarios.filter((s) => s.id !== HERO_SCENARIO)] : null),
    [scenarios],
  );

  /** `list`: the scenario list to read the tenant from when the state has not caught up yet (a pending hero run). */
  const launch = async (id: string, list: Scenario[] | null = scenarios) => {
    setBusy(id);
    setRunErr(null);
    setOpened(null);
    try {
      const r = await api.runScenario(id, effectiveLlm);
      if (!r.incident) {
        throw new Error(r.error ? `run failed before the incident was written: ${r.error}` : "the run did not create an incident");
      }
      // The incident lives in its scenario's tenant graph: the whole UI follows it there.
      const t = list?.find((s) => s.id === id)?.tenant ?? null;
      if (t) tenantStore.set(t);
      if ((r.incidents?.length ?? 0) > 1) {
        // INTAKE split the alerts into several incidents: list them all instead of opening only the first
        setOpened({ scenario: id, tenant: t, incidents: r.incidents ?? [] });
        setBusy(null);
        return;
      }
      router.push(`/incidents/${encodeURIComponent(r.incident)}${t ? `?tenant=${encodeURIComponent(t)}` : ""}`);
    } catch (e) {
      setRunErr(
        e instanceof ApiError && e.status === 403 && effectiveLlm === "anthropic"
          ? `the live LLM needs the operator's key on the public demo (HTTP 403, no anonymous spend). Use the Baseline investigator, or watch the recorded replay.`
          : e instanceof ApiError && e.status === 429
            ? `${e.detail} (HTTP 429). Try again in a few seconds.`
            : errorText(e),
      );
      setBusy(null);
    }
  };

  // the event listener below is registered once; it reads the launcher's current state through this ref
  const latest = useRef({ scenarios, busy, launch });
  useEffect(() => {
    latest.current = { scenarios, busy, launch };
  });

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .scenarios(ctrl.signal)
      .then((list) => {
        setScenarios(list);
        if (heroPending.current) {
          heroPending.current = false;
          if (list.some((s) => s.id === HERO_SCENARIO)) void latest.current.launch(HERO_SCENARIO, list);
        }
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setLoadErr(errorText(e));
      });
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const onHero = () => {
      const cur = latest.current;
      if (cur.busy !== null) return;
      if (cur.scenarios === null) {
        heroPending.current = true;
        return;
      }
      if (cur.scenarios.some((s) => s.id === HERO_SCENARIO)) void cur.launch(HERO_SCENARIO);
    };
    window.addEventListener(RUN_HERO_EVENT, onHero);
    // any seeded scenario by id (the home page's "Run the data incident"), same launcher, same guards
    const onScenario = (e: Event) => {
      const id = (e as CustomEvent<{ id?: string }>).detail?.id;
      const cur = latest.current;
      if (!id || cur.busy) return;
      if (cur.scenarios?.some((s) => s.id === id)) void cur.launch(id);
    };
    window.addEventListener(RUN_SCENARIO_EVENT, onScenario);
    return () => {
      window.removeEventListener(RUN_HERO_EVENT, onHero);
      window.removeEventListener(RUN_SCENARIO_EVENT, onScenario);
    };
  }, []);

  return (
    <Card className="fl-glass rounded-3xl bg-transparent lg:h-full lg:min-h-0">
      <CardHeader>
        <CardTitle>Run a scenario</CardTitle>
        <CardDescription className="text-zinc-400">
          Each run happens in a fresh GRAPH.COPY clean room of the tenant graph.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col">
        <fieldset className="space-y-1.5">
          <legend id={groupId} className="text-xs font-medium text-zinc-300">
            Investigator
          </legend>
          <div role="radiogroup" aria-labelledby={groupId} className="flex flex-wrap gap-2">
            <ModeButton
              checked={effectiveLlm === "baseline"}
              onSelect={() => setLlm("baseline")}
              icon={<Cpu aria-hidden className="size-4" />}
              label="Deterministic"
              hint="the investigator behind every published number"
            />
            {llmConfigured ? (
              <ModeButton
                checked={effectiveLlm === "anthropic"}
                onSelect={() => setLlm("anthropic")}
                icon={<Bot aria-hidden className="size-4" />}
                label="Claude"
                hint={status ? `proposes and calls the graph tools (${status.models.orchestrator}); the gate decides` : "proposes; the gate decides"}
              />
            ) : (
              <Tooltip>
                <TooltipTrigger
                  render={<span tabIndex={0} />}
                  className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                  aria-label="Claude investigator: runs on your own server with an Anthropic API key; this public demo is keyless"
                >
                  <ModeButton
                    checked={false}
                    disabled
                    onSelect={() => undefined}
                    icon={<Bot aria-hidden className="size-4" />}
                    label="Claude"
                    hint="on your own server, with an API key"
                  />
                </TooltipTrigger>
                <TooltipContent>
                  This public demo runs keyless. On your own server, set ANTHROPIC_API_KEY and Claude drives the
                  investigation through the same graph tools while the same deterministic gate decides.
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </fieldset>

        {loadErr ? (
          <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-2 text-sm text-red-200">
            Could not list scenarios: {loadErr}
          </p>
        ) : ordered === null ? (
          <p className="text-sm text-zinc-400">Loading scenarios…</p>
        ) : ordered.length === 0 ? (
          <p className="text-sm text-zinc-300">The API lists no scenarios (data/scenarios is empty).</p>
        ) : (
          <div className={"rounded-lg border border-zinc-800 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overscroll-contain lg:pb-6 " + SCROLL}
               role="region" aria-label="Scenarios (scrolls)" tabIndex={0} data-lenis-prevent>
          <ul className="divide-y divide-zinc-800">
            {ordered.map((s) => {
              const hero = s.id === HERO_SCENARIO;
              return (
              <li key={s.id} data-scenario={s.id} className={"flex items-center gap-3 px-3 py-2.5 " + (hero ? "bg-white/[0.03]" : "")}>
                <span className="w-12 shrink-0 font-mono text-sm font-semibold text-zinc-100">{s.id}</span>
                <div className="min-w-0 flex-1">
                  {hero ? (
                    <span className="mb-0.5 inline-flex items-center gap-1 rounded-full border border-amber-300/40 bg-amber-400/10 px-1.5 text-[10.5px] font-medium tracking-wide text-amber-100 uppercase">
                      <Star aria-hidden className="size-3" /> hero
                    </span>
                  ) : null}
                  {/* the readable name in full, wrapped; the raw id-style name stays in the tooltip */}
                  <p className="text-xs break-words text-zinc-400" title={s.name}>
                    {s.title ?? slugWords(s.name)}
                  </p>
                  <p className="text-sm text-zinc-200">&ldquo;{s.report}&rdquo;</p>
                </div>
                <span className="hidden font-mono text-xs text-zinc-400 sm:inline">{s.tenant}</span>
                <Button
                  onClick={() => launch(s.id)}
                  disabled={busy !== null}
                  aria-label={`Run scenario ${s.id}${hero ? " (the hero incident)" : ""} with the ${effectiveLlm} investigator`}
                >
                  <Play aria-hidden /> {busy === s.id ? "Starting…" : "Run"}
                </Button>
              </li>
              );
            })}
          </ul>
          </div>
        )}
        {runErr ? (
          <p role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-2 text-sm text-red-200">
            Run not started: {runErr}
          </p>
        ) : null}
        {opened ? (
          <div role="status" className="rounded-md border border-sky-500/40 bg-sky-500/10 p-2 text-sm text-zinc-100">
            <p>
              {opened.scenario}: INTAKE opened {opened.incidents.length} incidents (algo.WCC grouping); each is
              investigated on its own.
            </p>
            <ul className="mt-1 list-disc pl-5">
              {opened.incidents.map((x) => (
                <li key={x.incident}>
                  <Link
                    className="font-mono text-sky-300 underline underline-offset-2 hover:text-sky-200"
                    href={`/incidents/${encodeURIComponent(x.incident)}${opened.tenant ? `?tenant=${encodeURIComponent(opened.tenant)}` : ""}`}
                  >
                    {x.incident}
                  </Link>{" "}
                  <span className="text-zinc-300">({x.symptoms.join(", ")})</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div role="status" aria-live="polite">
          {busy ? <StatusChip tone="running">starting {busy}: preparing the clean-room graph…</StatusChip> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function ModeButton({
  checked,
  disabled,
  onSelect,
  icon,
  label,
  hint,
}: {
  checked: boolean;
  disabled?: boolean;
  onSelect: () => void;
  icon: React.ReactNode;
  label: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      tabIndex={disabled ? -1 : undefined}
      onClick={onSelect}
      className={
        "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-sky-400 " +
        (disabled
          ? "cursor-not-allowed border-zinc-800 text-zinc-400"
          : checked
            ? "border-sky-400 bg-sky-500/15 text-zinc-50"
            : "border-zinc-700 text-zinc-200 hover:bg-zinc-800")
      }
    >
      {icon}
      <span>
        <span className="font-medium">{label}</span>
        {checked ? <span className="sr-only"> (selected)</span> : null}
        <span className="block text-xs text-zinc-400">{hint}</span>
      </span>
    </button>
  );
}
