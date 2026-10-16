"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, FastForward, Film, Pause, Play, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { sortTimeline, timelineFromView } from "@/hooks/useIncident";
import { fmtMs } from "@/lib/format";
import { blastAt, describeEvent, loadReplay, planAt, ReplayError, viewAt, type ReplayBundle } from "@/lib/replay";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusChip } from "@/components/StatusChip";
import { IncidentRoomLayout, type NotRecorded } from "@/components/incident/IncidentRoomLayout";
import { cn } from "@/lib/utils";

const SPEEDS = [0.5, 1, 2, 4, 8] as const;
/** At 1× one recorded event is shown every BASE_MS (the original run is far too fast to watch). */
const BASE_MS = 600;

const OFFLINE_REASON = "Replay mode: no live FalkorDB behind this page. PROFILE and Re-run need the live demo.";

/**
 * Replay page body: plays a recorded run (public/replay/<name>/) through the same incident-room
 * layout as the live view, with the backend off. Event order is the recorded order; pacing is
 * event-by-event (speed 0.5×–8×) because the recorded run itself took milliseconds.
 */
export function ReplayRoom({ name }: { name: string }) {
  const [bundle, setBundle] = useState<ReplayBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    loadReplay(name)
      .then((b) => !disposed && setBundle(b))
      .catch((e) => !disposed && setError(e instanceof ReplayError || e instanceof Error ? e.message : String(e)));
    return () => {
      disposed = true;
    };
  }, [name]);

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <div role="alert" className="max-w-xl rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-sm text-red-100">
          <p className="font-semibold">Recorded run &quot;{name}&quot; could not be loaded</p>
          <p className="mt-1 break-words">{error}</p>
          <Link href="/replay" className="mt-3 inline-flex items-center gap-1 text-sky-300 underline">
            <ArrowLeft aria-hidden className="size-4" /> All recorded runs
          </Link>
        </div>
      </div>
    );
  }
  if (!bundle) {
    return (
      <p className="p-8 text-sm text-zinc-300" aria-live="polite">
        Loading recorded run {name} from static files…
      </p>
    );
  }
  return <Player bundle={bundle} />;
}

function Player({ bundle }: { bundle: ReplayBundle }) {
  const reduced = useReducedMotion();
  const total = bundle.events.length;
  // Open on the finished room (the verdict, the proof and the plan): the story first, the playback on demand.
  const [cursor, setCursor] = useState(total);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const isPlaying = playing && !reduced && cursor < total;

  useEffect(() => {
    if (!isPlaying) return;
    const t = setTimeout(() => setCursor((c) => Math.min(total, c + 1)), BASE_MS / speed);
    return () => clearTimeout(t);
  }, [isPlaying, cursor, speed, total]);

  const view = useMemo(() => viewAt(bundle, cursor), [bundle, cursor]);
  const plan = useMemo(() => planAt(bundle, view), [bundle, view]);
  const blast = useMemo(() => blastAt(bundle, view), [bundle, view]);
  const timeline = useMemo(() => sortTimeline(timelineFromView(view)), [view]);
  const announcement = cursor > 0 ? describeEvent(bundle.events[cursor - 1]) : "";
  const span = total > 1 ? bundle.events[total - 1].at - bundle.events[0].at : 0;
  const offline = useMemo(() => ({ reason: OFFLINE_REASON, templates: bundle.templates ?? {} }), [bundle.templates]);
  const snap = bundle.manifest?.snapshot;

  const rec = bundle.manifest?.recorded ?? null;
  const graphNote = bundle.graph
    ? snap?.graph?.startsWith("tenant snapshot")
      ? `Topology: ${snap.graph}, taken ${snap.at.slice(0, 10)}; the run's own graph copy is not in the export`
      : `The run's own graph (${bundle.graph.graph}), exported with the recording`
    : null;

  const atEnd = cursor >= total;
  const controls = (
    <div className="border-b border-white/[0.06] bg-white/[0.015] px-4 py-2.5 sm:px-6">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-x-3 gap-y-2">
        <StatusChip tone="info" icon={Film}>
          Recorded run · static files · no API key
        </StatusChip>
        <Button
          size="sm"
          onClick={() => {
            setCursor(0);
            setPlaying(!reduced);
          }}
          className="rounded-full"
        >
          <SkipBack aria-hidden />
          {reduced ? "Step from the start" : "Play from the start"}
        </Button>
        <div role="group" aria-label="Playback" className="flex items-center gap-1">
          <Button size="icon-sm" variant="ghost" onClick={() => {
              setPlaying(false); // stepping is manual, like the slider: do not resume playback
              setCursor((c) => Math.max(0, c - 1));
            }}
            disabled={cursor === 0}
            aria-label="Previous event">
            <StepBack aria-hidden />
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => {
              if (atEnd) setCursor(0);
              setPlaying((p) => !(p && cursor < total));
            }}
            disabled={reduced}
            aria-label={isPlaying ? "Pause" : atEnd ? "Play again" : "Play"}
            title={reduced ? "Reduced motion is on: step with the buttons or the slider" : undefined}
          >
            {isPlaying ? <Pause aria-hidden /> : <Play aria-hidden />}
          </Button>
          <Button size="icon-sm" variant="ghost" onClick={() => {
              setPlaying(false);
              setCursor((c) => Math.min(total, c + 1));
            }}
            disabled={atEnd}
            aria-label="Next event">
            <StepForward aria-hidden />
          </Button>
          <Button size="icon-sm" variant="ghost" onClick={() => { setPlaying(false); setCursor(total); }} disabled={atEnd} aria-label="Jump to the end">
            <SkipForward aria-hidden />
          </Button>
        </div>
        <div role="radiogroup" aria-label="Playback speed" className="flex items-center gap-0.5 rounded-full bg-white/[0.04] p-0.5 ring-1 ring-white/[0.06]">
          <FastForward aria-hidden className="mx-1 size-3.5 text-[var(--fl-subtle)]" />
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={speed === s}
              onClick={() => setSpeed(s)}
              className={cn(
                "rounded-full px-1.5 py-0.5 font-mono text-[11px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-400",
                speed === s ? "bg-white/[0.1] text-zinc-50" : "text-zinc-400 hover:text-zinc-100",
              )}
            >
              {s}×
            </button>
          ))}
        </div>
        <label className="flex min-w-[220px] flex-1 items-center gap-2 text-xs text-zinc-400">
          <span className="whitespace-nowrap">
            Event <span className="font-mono text-zinc-100">{cursor}</span> / {total}
          </span>
          <input
            type="range"
            min={0}
            max={total}
            value={cursor}
            onChange={(e) => {
              setPlaying(false);
              setCursor(Number(e.target.value));
            }}
            className="w-full accent-zinc-300"
            aria-valuetext={`event ${cursor} of ${total}${cursor ? `: ${announcement}` : ""}`}
          />
        </label>
        <Disclosure size="xs" defaultOpen={false} summary="About this recording" className="w-full">
          <p className="max-w-4xl text-[11px] leading-relaxed text-zinc-400">
            1× = one recorded event every {BASE_MS / 1000} s; the recorded run took {fmtMs(span)} end to end.
            {reduced ? " Reduced motion is on: playback is manual (use the step buttons or the slider)." : ""} Hypotheses and
            the report appear when the gate decides (the export has no timestamps for them); the plan, the action and its
            verdict appear as their stages play.
            {bundle.templates ? "" : " This recording has no template snapshot, so Cypher text is unavailable."}
            {rec ? ` Recorded ${rec.scenario} through ${rec.final_stage} with ${rec.github} GitHub (${rec.investigator}).` : ""}
          </p>
        </Disclosure>
      </div>
    </div>
  );

  const missing = ["plan.json"].filter((f) => !bundle.manifest?.files.includes(f));
  // Sections this recording predates (M12 report / plan fields): one note instead of an empty card each.
  const rep = bundle.report;
  const notRecorded: NotRecorded[] = [
    ...(rep.residue === undefined ? (["residue"] as const) : []),
    ...(rep.why_alerts_missed_it === undefined ? (["alerts"] as const) : []),
    ...(rep.ownership === undefined && bundle.plan?.owner_at === undefined ? (["ownership"] as const) : []),
    ...(bundle.plan?.notify_set === undefined ? (["notify"] as const) : []),
    ...(rep.remedy === undefined ? (["remedy"] as const) : []),
  ];
  return (
    <IncidentRoomLayout
      source={{
        mode: "replay",
        view,
        graph: bundle.graph,
        graphError: bundle.graph ? null : "this recording has no graph.json export",
        graphNote,
        timeline,
        stream: "replay",
        announcement,
        plan,
        planError: null,
        planUnavailable: bundle.plan
          ? null
          : `examples/${bundle.name} has no ${missing.join(", ") || "plan"} export (containment, routing and the approval are recorded only in the live graph). Run the scenario live to see them.`,
        blast,
        blastError: null,
        blastUnavailable: bundle.blast ? (blast ? null : "the blast radius appears once the BLAST stage has played") : "this recording has no blast.json export",
        offline,
        notRecorded,
        top: controls,
        meta: [
          { label: "recording", value: `replay/${bundle.name}`, mono: true },
          { label: "run", value: view.run.run, mono: true },
          { label: "symptom", value: view.incident.targets.join(", ") || "–", mono: true },
          { label: "graph", value: view.run.graph, mono: true },
          { label: "events", value: String(total) },
        ],
      }}
    />
  );
}
