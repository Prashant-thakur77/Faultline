"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Lock, Pause, Play, PowerOff, RotateCcw, Scissors, X } from "lucide-react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { ExplainerClock, type PlayState } from "./clock";
import { useExplainerData, type ExplainerData } from "./data";
import { DURATIONS, SCENES, TOTAL, fmt, type Chip, type Values } from "./scenes";
import { labelSpecs, type LabelSpec, type Tone, type Ui } from "./world";

// three.js loads only in the browser, after the page
const ExplainerStage = dynamic(() => import("./ExplainerStage"), { ssr: false, loading: () => null });

/** What the recorder (scripts/record_demo_video.py, Playwright) drives. Scene numbers are 1-based. */
export type ExplainerApi = {
  go: (n: number) => void;
  /** play scene n once over `seconds` of wall time, then hold its last frame (narration-timed recording) */
  playScene: (n: number, seconds: number) => void;
  seek: (n: number, t: number) => void;
  play: () => void;
  pause: () => void;
  state: () => { scene: number; t: number; state: PlayState; mode: "animated" | "static" };
  perf: () => number[][];
  gpu: () => { programs: number; calls: number; triangles: number; geometries: number };
  resetPerf: () => void;
  sceneCount: number;
  durations: number[];
};
declare global {
  interface Window { __explainer?: ExplainerApi }
}

const TONE: Record<Tone, string> = {
  plain: "border-white/15 text-zinc-100",
  muted: "border-white/10 text-zinc-400",
  ember: "border-[#ff6b2c]/55 text-[#ffb995]",
  mint: "border-[#5ef0b4]/45 text-[#b4f8db]",
  iris: "border-[#9a7dff]/55 text-[#d6cbff]",
  amber: "border-[#ffc247]/50 text-[#ffe3a6]",
  gold: "border-[#ffd27a]/55 text-[#ffe9b8]",
};
/** Status is never colour alone: each state label also carries an icon and words. */
const ICON: Record<string, React.ReactNode> = {
  "n:checkout": <AlertTriangle className="size-3" aria-hidden />,
  rec0: <X className="size-3" aria-hidden />,
  gauge: <X className="size-3" aria-hidden />,
  pay1: <Check className="size-3" aria-hidden />,
  full: <Check className="size-3" aria-hidden />,
  verdict: <Check className="size-3" aria-hidden />,
  reread: <Check className="size-3" aria-hidden />,
  cut: <Scissors className="size-3" aria-hidden />,
  ro: <Lock className="size-3" aria-hidden />,
};

let glCache: boolean | null = null;
function hasWebGL(): boolean {
  if (glCache === null) {
    try {
      const c = document.createElement("canvas");
      const ctx = c.getContext("webgl2") || c.getContext("webgl");
      glCache = !!ctx;
      // release the probe context now: left to the garbage collector, its teardown forces a GPU finish that
      // stalls a frame (~200 ms measured) at a random moment mid-animation
      ctx?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      glCache = false;
    }
  }
  return glCache;
}
const noop = () => () => {};

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const START = DURATIONS.map((_, i) => DURATIONS.slice(0, i).reduce((a, b) => a + b, 0));

export function FalkorExplainer() {
  const data = useExplainerData();
  const reduced = useReducedMotion();
  const gl = useSyncExternalStore(noop, hasWebGL, () => null);   // null while server-rendered
  const [failed, setFailed] = useState<string | null>(null);
  const [stageView, setStageView] = useState(false);   // ?view=stage: the stage fills the window (recording)
  const [autoplay, setAutoplay] = useState(true);
  const [stageCaptions, setStageCaptions] = useState(true);   // ?captions=0: a clean stage for the video
  const [stageChips, setStageChips] = useState(false);   // ?captions=chips: only the scene title and its FalkorDB calls (the video burns its own subtitles)
  const [clock] = useState(() => new ExplainerClock(DURATIONS));   // mutable by design: the frame loop owns it
  const [scene, setScene] = useState(0);
  const [play, setPlay] = useState<PlayState>("paused");
  const [visible, setVisible] = useState(true);
  const stageRef = useRef<HTMLDivElement>(null);
  const labels = useRef<Record<string, HTMLDivElement | null>>({});
  const lastOp = useRef<Record<string, number>>({});
  const fills = useRef<(HTMLSpanElement | null)[]>([]);
  const timeText = useRef<HTMLSpanElement>(null);
  const totalBar = useRef<HTMLSpanElement>(null);
  const panel = useCypherPanel();

  const animated = !!gl && !reduced && !failed && data.state === "ok";
  const mode: "animated" | "static" = animated ? "animated" : "static";

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    // reading the URL once on mount (no useSearchParams: the page is also statically exported)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (q.get("view") === "stage") setStageView(true);
    if (q.get("autoplay") === "0") setAutoplay(false);
    if (q.get("captions") === "0") setStageCaptions(false);
    if (q.get("captions") === "chips") { setStageCaptions(false); setStageChips(true); }
  }, []);

  // React hears about scene and play-state changes only (a few per minute)
  useEffect(() => clock.subscribe(() => { setScene(clock.scene); setPlay(clock.state); }), [clock]);

  // progress: written to the DOM from the frame loop, never through React state
  useEffect(() => {
    clock.setProgress((s, t) => {
      const k = Math.min(1, t / DURATIONS[s]);
      const f = fills.current[s];
      if (f) f.style.transform = `scaleX(${k})`;
      if (totalBar.current) totalBar.current.style.transform = `scaleX(${(START[s] + t) / TOTAL})`;
      if (timeText.current) timeText.current.textContent = `${mmss(START[s] + t)} / ${mmss(TOTAL)}`;
    });
    return () => clock.setProgress(null);
  }, [clock]);

  // static mode (reduced motion, no WebGL): each scene is its final, still frame; animated: from the scene's start
  useEffect(() => {
    if (data.state === "loading") return;
    if (mode === "static") { clock.pause(); clock.seek(clock.scene, DURATIONS[clock.scene]); }
    else clock.seek(clock.scene, 0);
  }, [mode, clock, data.state]);

  // auto-play once the recording has loaded, unless the viewer asked for stillness
  useEffect(() => {
    if (animated && autoplay) clock.play();
  }, [animated, autoplay, clock]);

  // off screen: no frames, so the clock (advanced only by frames) pauses with it
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.05 });
    io.observe(el);
    return () => io.disconnect();
  }, [data.state]);

  const go = useCallback((n: number) => {
    const s = Math.max(0, Math.min(SCENES.length - 1, n));
    if (mode === "static") clock.seek(s, DURATIONS[s]);
    else clock.go(s);
  }, [clock, mode]);
  const toggle = useCallback(() => {
    if (mode === "static") return;
    if (clock.state === "playing") clock.pause();
    else clock.play();
  }, [clock, mode]);

  // the recorder's handle (1-based scene numbers)
  useEffect(() => {
    const api: ExplainerApi = {
      go: (n) => go(n - 1),
      playScene: (n, seconds) => { if (mode === "static") go(n - 1); else clock.playScene(n - 1, seconds); },
      seek: (n, t) => clock.seek(n - 1, t),
      play: () => clock.play(),
      pause: () => clock.pause(),
      state: () => ({ scene: clock.scene + 1, t: clock.t, state: clock.state, mode }),
      perf: () => clock.frames.map((f) => [...f]),
      gpu: () => ({ ...clock.gpu }),
      resetPerf: () => clock.resetFrames(),
      sceneCount: SCENES.length,
      durations: [...DURATIONS],
    };
    window.__explainer = api;
    return () => { if (window.__explainer === api) delete window.__explainer; };
  }, [go, clock, mode]);

  const ui = useMemo<Ui>(() => ({
    at: (key, x, y, o) => {
      const el = labels.current[key];
      if (!el) return;
      const op = o < 0.01 ? 0 : Math.min(1, o);
      if (op === 0 && lastOp.current[key] === 0) return;
      lastOp.current[key] = op;
      el.style.opacity = String(op);
      el.style.visibility = op === 0 ? "hidden" : "visible";
      if (x >= 0) {
        // keep a centred label inside the stage: near the edge a long one ("Alerts & telemetry") was clipped
        const w = el.parentElement?.clientWidth ?? 0;
        const half = el.offsetWidth / 2 + 8;
        const cx = w > 2 * half ? Math.min(Math.max(x, half), w - half) : x;
        el.style.transform = `translate(-50%, 0) translate(${cx.toFixed(1)}px, ${y.toFixed(1)}px)`;
      }
      else el.style.setProperty("--k", String(op));
    },
  }), []);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.target instanceof HTMLButtonElement && (e.key === " " || e.key === "Enter")) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(scene + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(scene - 1); }
    else if (e.key === "Home") { e.preventDefault(); go(0); }
    else if (e.key === "End") { e.preventDefault(); go(SCENES.length - 1); }
    else if (e.key === " " || e.key === "k") { e.preventDefault(); toggle(); }
  };

  const values: Values = data.state === "ok" ? data.data.values : {};
  const stats = data.state === "ok" ? data.data.stats : null;
  const cur = SCENES[scene];
  const specs = useMemo(() => (data.state === "ok" ? labelSpecs(data.data) : []), [data]);

  const openChip = (c: Chip) => {
    if (data.state !== "ok" || !c.template) return;
    const d = data.data;
    const call = d.calls.find((k) => {
      const parts = k.template.split("+");
      if (!parts.includes(c.template!)) return false;
      const params = (parts.length > 1 ? (k.params[c.template!] as Record<string, unknown>) : k.params) ?? {};
      return Object.entries(c.params ?? {}).every(([pk, pv]) => JSON.stringify(params[pk] ?? "").includes(pv));
    });
    const composite = !!call && call.template.includes("+");
    clock.pause();
    panel.open({
      template: c.template,
      title: `${c.template} · ${cur.title}`,
      origin: `explainer scene ${scene + 1} (hero recording s1-hero)`,
      detail: call?.summary ?? null,
      recordedParams: call ? ((composite ? call.params[c.template] : call.params) as Record<string, unknown>) : null,
      ctx: {},
      tenant: "acme",
      recorded: call && !composite ? { ms: call.ms, rows: call.rows } : null,
      offline: { reason: "Explainer: the Cypher exported with the hero recording. PROFILE and Re-run run in the incident room on the live demo.", templates: d.templates },
    });
  };

  const stage = (
    <div ref={stageRef} data-scene={scene + 1} data-state={play} data-mode={mode}
         role="region" aria-roledescription="explainer" aria-label={`How FalkorDB decides, scene ${scene + 1} of ${SCENES.length}: ${cur.title}`}
         tabIndex={0} onKeyDown={onKey}
         className={"isolate overflow-hidden bg-[#060607] outline-none focus-visible:ring-2 focus-visible:ring-sky-400 "
           + (stageView ? "fixed inset-0 z-[80]" : "relative aspect-[4/5] w-full rounded-[20px] border border-white/[0.08] sm:aspect-[16/9]")}>
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_55%_at_50%_45%,rgb(154_125_255/0.10),transparent_70%),radial-gradient(40%_40%_at_15%_90%,rgb(255_107_44/0.05),transparent_70%)]" />
      {data.state === "ok" && gl && !failed ? (
        <div className="absolute inset-0">
          <ExplainerStage data={data.data} clock={clock} still={!animated} running={visible} ui={ui} scene={scene} onFail={setFailed} />
        </div>
      ) : null}
      {/* labels: placed from the frame loop; they repeat what the caption says, so hidden from assistive tech */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        {specs.map((l) => <Label key={l.key} spec={l} ref={(el) => { labels.current[l.key] = el; }} />)}
        {data.state === "ok" ? <Overlays d={data.data} refFor={(k) => (el) => { labels.current[k] = el; }} /> : null}
      </div>
      {data.state === "loading" ? (
        <p className="absolute inset-0 grid place-items-center font-mono text-[12px] text-zinc-500">Loading the hero recording…</p>
      ) : null}
      {data.state === "ok" && (!gl || failed) ? (
        <div className="absolute inset-0 grid place-items-center p-6 text-center">
          <div className="max-w-md">
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--fl-subtle)]">Scene {scene + 1} · {cur.title}</p>
            <p className="mt-3 text-[15px] leading-relaxed text-zinc-200">{cur.caption(values, stats)}</p>
          </div>
        </div>
      ) : null}
      <div className="pointer-events-none absolute right-4 top-3 flex items-center gap-2 font-mono text-[11px] text-zinc-400 sm:right-5 sm:top-4">
        <span className="text-zinc-200">{String(scene + 1).padStart(2, "0")}</span>
        <span>/ {String(SCENES.length).padStart(2, "0")}</span>
        <span className="hidden text-zinc-500 sm:inline">· {cur.title}</span>
      </div>
      {stageView && stageCaptions ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/50 to-transparent px-8 pb-7 pt-16">
          <p className="max-w-[min(70rem,90vw)] text-[clamp(15px,1.45vw,22px)] leading-snug text-zinc-100">{cur.caption(values, stats)}</p>
          <ChipRow chips={cur.chips} />
        </div>
      ) : null}
      {stageView && stageChips ? (
        <div className="pointer-events-none absolute left-6 top-5 max-w-[min(56rem,80vw)] sm:left-8 sm:top-6">
          <p className="font-mono text-[13px] uppercase tracking-[0.2em] text-[var(--fl-iris)]">Inside FalkorDB · {cur.title}</p>
          <ChipRow chips={cur.chips} large />
        </div>
      ) : null}
    </div>
  );

  return (
    <div className="mx-auto w-full max-w-[1200px] px-5 pb-24 pt-10 sm:px-8 sm:pt-14">
      <header className="max-w-[880px]">
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-[var(--fl-iris)]">How FalkorDB decides</p>
        <h1 className="mt-3 text-[clamp(2rem,4.6vw,3.4rem)] font-[560] leading-[1.04] tracking-[-0.03em] text-zinc-50 [font-family:var(--font-mona)]">
          Inside the graph.{" "}
          <span className="text-[var(--fl-muted)]">Nine moments where a FalkorDB query, not the model, makes the call.</span>
        </h1>
      </header>

      {data.state === "error" ? (
        <div role="alert" className="mt-8 flex items-start gap-3 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p><span className="font-semibold">Explainer data unavailable.</span> {data.error}. Nothing is drawn without the recording; the scenes are listed below as text.</p>
        </div>
      ) : null}
      {data.state === "ok" && gl === false ? (
        <p role="status" className="mt-6 text-sm text-amber-200">WebGL is unavailable in this browser, so the scenes play as captioned steps.</p>
      ) : null}
      {failed ? (
        <p role="alert" className="mt-6 text-sm text-red-300">The 3D stage stopped ({failed}); the scenes continue as captioned steps.</p>
      ) : null}

      <div className="mt-8">{stage}</div>

      {/* controls */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3" onKeyDown={onKey}>
        <div className="flex items-center gap-1.5">
          {mode === "animated" ? (
            <button type="button" onClick={toggle} aria-label={play === "playing" ? "Pause" : play === "done" ? "Replay from the start" : "Play"}
                    className="inline-flex h-9 items-center gap-2 rounded-full bg-zinc-50 px-4 text-[13px] font-medium text-zinc-950 outline-none transition-colors hover:bg-white focus-visible:ring-2 focus-visible:ring-sky-400">
              {play === "playing" ? <Pause className="size-3.5" aria-hidden /> : play === "done" ? <RotateCcw className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
              {play === "playing" ? "Pause" : play === "done" ? "Replay" : "Play"}
            </button>
          ) : null}
          <button type="button" onClick={() => go(scene - 1)} disabled={scene === 0} aria-label="Previous scene"
                  className="grid size-9 place-items-center rounded-full border border-white/10 text-zinc-200 outline-none transition-colors hover:border-white/25 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-35">
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          <button type="button" onClick={() => go(scene + 1)} disabled={scene === SCENES.length - 1} aria-label="Next scene"
                  className="grid size-9 place-items-center rounded-full border border-white/10 text-zinc-200 outline-none transition-colors hover:border-white/25 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-35">
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </div>
        <nav aria-label="Scenes" className="hidden min-w-0 flex-1 sm:block">
          <ol className="flex gap-[3px]">
            {SCENES.map((s, i) => (
              <li key={s.id} style={{ flexGrow: s.duration }} className="min-w-0 basis-0">
                <button type="button" onClick={() => go(i)} aria-label={`Scene ${i + 1}: ${s.title}`} aria-current={i === scene ? "step" : undefined}
                        className="group block w-full rounded-[2px] py-2 outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                  <span className="relative block h-[5px] overflow-hidden rounded-[1px] bg-white/[0.14] transition-colors group-hover:bg-white/[0.28]">
                    <span ref={(el) => { fills.current[i] = el; }} aria-hidden
                          className={"absolute inset-0 origin-left " + (i === scene ? "bg-zinc-50" : "bg-zinc-400")}
                          style={{ transform: `scaleX(${i < scene || (i === scene && mode === "static") ? 1 : 0})` }} />
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </nav>
        <span className="font-mono text-[11px] text-zinc-400 sm:hidden" aria-hidden>{scene + 1} / {SCENES.length}</span>
        <span ref={timeText} className="ml-auto font-mono text-[11px] tabular-nums text-zinc-500 sm:ml-0" aria-hidden>
          {mmss(START[scene])} / {mmss(TOTAL)}
        </span>
        <span ref={totalBar} aria-hidden className="hidden" />
      </div>

      {/* the caption: announced on every scene change */}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        <div aria-live="polite" aria-atomic="true" data-testid="caption">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--fl-ember)]">
            Scene {scene + 1} of {SCENES.length}
          </p>
          <h2 className="mt-2 text-[26px] font-[540] tracking-[-0.02em] text-zinc-50">{cur.title}</h2>
          <p className="mt-3 max-w-2xl text-[15.5px] leading-relaxed text-[var(--fl-muted)]">{cur.caption(values, stats)}</p>
        </div>
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-zinc-500">The real query</p>
          <ChipRow chips={cur.chips} onOpen={data.state === "ok" ? openChip : undefined} />
        </div>
      </div>

      {data.state === "ok" ? <ProofTables d={data.data} /> : null}

      {/* every scene as text: the reduced-motion step-through and the transcript */}
      <section aria-labelledby="xp-all" className="mt-16 border-t border-white/[0.07] pt-10">
        <h2 id="xp-all" className="text-[22px] font-[540] tracking-[-0.02em] text-zinc-50">All nine scenes, as text</h2>
        <ol className="mt-6 grid gap-x-10 gap-y-7 md:grid-cols-2">
          {SCENES.map((s, i) => (
            <li key={s.id} data-testid="scene-text" className="min-w-0">
              <button type="button" onClick={() => { go(i); stageRef.current?.focus({ preventScroll: true }); stageRef.current?.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" }); }}
                      className="text-left outline-none focus-visible:ring-2 focus-visible:ring-sky-400" aria-label={`Show scene ${i + 1}: ${s.title}`}>
                <span className="font-mono text-[11px] text-[var(--fl-subtle)]">{String(i + 1).padStart(2, "0")} · {s.duration}s</span>
                <span className="mt-1 block text-[16px] font-[540] text-zinc-100">{s.title}</span>
              </button>
              <p className="mt-1.5 text-[14px] leading-relaxed text-[var(--fl-muted)]">{s.caption(values, stats)}</p>
              <ChipRow chips={s.chips} compact />
            </li>
          ))}
        </ol>
        <p className="mt-10 font-mono text-[11px] leading-relaxed text-[var(--fl-subtle)]">
          Drawn from the hero recording (public/replay/s1-hero, exported from FalkorDB) · numbers from evals/results/latest.json
          {data.state === "ok" && data.data.run ? ` (${data.data.run})` : ""} · per-type edge counts from db.meta.stats on {stats?.graph ?? "golden_acme"} ·
          the matrix scene shows how FalkorDB stores a graph (its design docs: sparse adjacency matrices, GraphBLAS). Layout is fixed and illustrative.
        </p>
      </section>
    </div>
  );
}

function ChipRow({ chips, onOpen, compact, large }: { chips: Chip[]; onOpen?: (c: Chip) => void; compact?: boolean; large?: boolean }) {
  return (
    <ul className={"flex flex-wrap gap-2 " + (compact ? "mt-2.5" : "mt-3")}>
      {chips.map((c) => {
        const body = (
          <>
            <span className="text-[#d6cbff]">{c.query}</span>
            <span className="text-zinc-500">{c.file}</span>
          </>
        );
        const cls = "inline-flex max-w-full flex-wrap items-baseline gap-x-2 rounded-md border border-[#9a7dff]/25 bg-[#9a7dff]/[0.06] px-2 py-1 text-left font-mono "
          + (compact ? "text-[10.5px]" : large ? "text-[14px] px-2.5 py-1.5" : "text-[11.5px]");
        return (
          <li key={c.query} className="min-w-0">
            {onOpen && c.template ? (
              <button type="button" onClick={() => onOpen(c)} aria-label={`Open the Cypher for ${c.template}: ${c.query} (${c.file})`}
                      className={cls + " outline-none transition-colors hover:border-[#9a7dff]/60 focus-visible:ring-2 focus-visible:ring-sky-400"}>
                {body}<span className="text-zinc-400 underline decoration-dotted underline-offset-2">Cypher</span>
              </button>
            ) : <span className={cls}>{body}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function Label({ spec, ref }: { spec: LabelSpec; ref: (el: HTMLDivElement | null) => void }) {
  return (
    <div ref={ref} style={{ opacity: 0, visibility: "hidden" }}
         className={"absolute left-0 top-0 whitespace-nowrap rounded-[6px] border bg-[#060607]/80 px-1.5 py-0.5 font-mono text-[10px] leading-tight sm:text-[10.5px] " + TONE[spec.tone]}>
      <span className="flex items-center gap-1">{ICON[spec.key] ?? null}{spec.text}</span>
      {spec.sub ? <span className="hidden text-[9.5px] text-zinc-400 sm:block">{spec.sub}</span> : null}
    </div>
  );
}

/** Fixed overlays for the last scene: FalkorDB off, the capability ladder, the end card (faded from the frame loop). */
function Overlays({ d, refFor }: { d: ExplainerData; refFor: (k: string) => (el: HTMLDivElement | null) => void }) {
  const v = d.values;
  const n = Number(v["ladder.full.b.confirm_cases"]);
  const rows: [string, string][] = [
    ["every gate", "ladder.full.b.right_cause"],
    ["without algo.SPpaths", "ladder.no_sppaths.b.right_cause"],
    ["without algo.maxFlow", "ladder.no_maxflow.b.right_cause"],
    ["without both", "ladder.neither.b.right_cause"],
  ];
  const hide = { opacity: 0, visibility: "hidden" as const };
  return (
    <>
      <div ref={refFor("ov:a4")} style={hide} className="absolute left-1/2 top-[9%] -translate-x-1/2 rounded-xl border border-white/15 bg-black/70 px-4 py-3 text-center backdrop-blur-md">
        <p className="flex items-center justify-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-[#ffb995]"><PowerOff className="size-3.5" aria-hidden />FalkorDB off</p>
        <p className="mt-1.5 text-[clamp(14px,1.7vw,20px)] font-[540] text-zinc-50">It refuses to confirm anything.</p>
        <p className="mt-1 font-mono text-[10.5px] text-zinc-400">no graph, no claim · fail-closed by design (arm A4)</p>
      </div>
      <div ref={refFor("ov:ladder")} style={{ ...hide, ["--k" as string]: 0 }} className="absolute left-1/2 top-[30%] w-[min(30rem,88%)] -translate-x-1/2 rounded-xl border border-white/12 bg-black/75 p-4 backdrop-blur-md sm:left-auto sm:right-[4%] sm:top-1/2 sm:-translate-y-1/2 sm:translate-x-0">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-zinc-400">Right cause named · of {fmt(v, "ladder.full.b.confirm_cases")} cases with one</p>
        <ul className="mt-3 grid gap-2">
          {rows.map(([name, key]) => {
            const x = Number(v[key]);
            const w = Number.isFinite(x) && n > 0 ? (x / n) * 100 : 0;
            const drop = key === "ladder.neither.b.right_cause";
            return (
              <li key={key} className="grid grid-cols-[9.5rem_minmax(0,1fr)_2.5rem] items-center gap-3 font-mono text-[11px]">
                <span className="truncate text-zinc-300">{name}</span>
                <span className="h-2 overflow-hidden rounded-full bg-white/10">
                  <span className={"block h-full rounded-full " + (drop ? "bg-[#ff6b2c]" : "bg-[#5ef0b4]")} style={{ width: `calc(${w}% * var(--k, 0))` }} />
                </span>
                <span className={"text-right tabular-nums " + (drop ? "text-[#ffb995]" : "text-zinc-100")}>{fmt(v, key)}</span>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 font-mono text-[10px] text-zinc-500">evals/ladder.py · either algorithm alone still finds the cause; remove both and it cannot</p>
      </div>
      <div ref={refFor("ov:end")} style={hide} className="absolute inset-0 grid place-items-center bg-[radial-gradient(50%_45%_at_50%_50%,rgb(6_6_7/0.88),rgb(6_6_7/0.35)_70%,transparent)]">
       <div className="mx-auto w-[min(46rem,92%)] text-center">
        <p className="text-[clamp(30px,5.6vw,68px)] font-[620] leading-[1] tracking-[-0.035em] text-zinc-50 [font-family:var(--font-mona)]">No path, no claim.</p>
        <p className="mx-auto mt-4 max-w-xl text-[clamp(13px,1.5vw,17px)] leading-snug text-zinc-300">
          Faultline calls every <span className="font-mono text-[#d6cbff]">algo.*</span> procedure the pinned engine ships,{" "}
          <span className="text-zinc-50">{fmt(v, "repo.algorithms")}</span> of them, and each one changes a decision.
        </p>
        <ul className="mx-auto mt-4 flex max-w-2xl flex-wrap justify-center gap-1.5">
          {(d.stats.algorithms ?? []).map((a) => (
            <li key={a} className="rounded border border-[#9a7dff]/30 bg-black/50 px-1.5 py-0.5 font-mono text-[10px] text-[#d6cbff] sm:text-[11px]">{a}</li>
          ))}
        </ul>
        <p className="mt-3 font-mono text-[10px] text-zinc-500">{d.stats.engine ?? "FalkorDB"} · resolved by the smoke suite</p>
       </div>
      </div>
    </>
  );
}

/** The text alternative for the decision: each suspect's recorded path query, and the proof path hop by hop. */
function ProofTables({ d }: { d: ExplainerData }) {
  const symptom = d.blast.from;
  const proof = d.paths.find((p) => p.cause === "D-pay-417" && p.symptom === symptom)?.chain ?? [];
  const hop = (a: string, b: string) => {
    if (d.changed.some((c) => c.deploy === a && c.target === b)) return "CHANGED";
    const e = d.edges.find((x) => x.source === a && x.target === b);
    return e ? `PROPAGATES_TO (cap ${e.cap ?? "–"})` : "–";
  };
  const g5 = (cause: string) => (cause === "D-email-88" ? `max flow ${fmt(d.values, "s1.D-email-88.max_flow")} < needed ${fmt(d.values, "s1.D-email-88.needed")}: rejected (G5)` : null);
  return (
    <section aria-labelledby="xp-proof" className="mt-14 grid gap-10 lg:grid-cols-2">
      <h2 id="xp-proof" className="sr-only">The decision, as tables</h2>
      <div>
        <h3 className="font-mono text-[11px] uppercase tracking-[0.16em] text-zinc-400">Suspects · recorded Q-GATE-1 to {symptom}</h3>
        <table className="mt-3 w-full border-collapse text-left text-[13px]">
          <thead><tr className="border-b border-white/10 font-mono text-[10.5px] uppercase tracking-[0.12em] text-zinc-500">
            <th scope="col" className="py-2 pr-3 font-normal">Deploy</th><th scope="col" className="py-2 pr-3 font-normal">Path</th><th scope="col" className="py-2 font-normal">Verdict</th>
          </tr></thead>
          <tbody>
            {d.changed.map((c) => {
              const p = d.paths.find((x) => x.cause === c.deploy && x.symptom === symptom);
              const none = !p || p.chain.length === 0;
              const verdict = none ? "no path, 0 rows: rejected (G2)" : g5(c.deploy) ?? "path and flow hold: the cause";
              const ok = !none && !g5(c.deploy);
              return (
                <tr key={c.deploy} className="border-b border-white/[0.06] align-top">
                  <th scope="row" className="py-2 pr-3 font-mono text-[12px] font-normal text-zinc-100">{c.deploy}</th>
                  <td className="py-2 pr-3 font-mono text-[12px] text-zinc-300">{none ? "—" : p!.chain.join(" → ")}</td>
                  <td className={"py-2 " + (ok ? "text-[#b4f8db]" : "text-[#ffb995]")}>
                    <span className="inline-flex items-start gap-1.5">{ok ? <Check className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : <X className="mt-0.5 size-3.5 shrink-0" aria-hidden />}{verdict}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="font-mono text-[11px] uppercase tracking-[0.16em] text-zinc-400">The proof path, hop by hop</h3>
        <table className="mt-3 w-full border-collapse text-left text-[13px]">
          <thead><tr className="border-b border-white/10 font-mono text-[10.5px] uppercase tracking-[0.12em] text-zinc-500">
            <th scope="col" className="py-2 pr-3 font-normal">Hop</th><th scope="col" className="py-2 pr-3 font-normal">From</th><th scope="col" className="py-2 pr-3 font-normal">Relationship</th><th scope="col" className="py-2 font-normal">To</th>
          </tr></thead>
          <tbody>
            {proof.slice(1).map((b, i) => (
              <tr key={b} className="border-b border-white/[0.06]">
                <td className="py-2 pr-3 font-mono text-[12px] text-zinc-500">{i + 1}</td>
                <td className="py-2 pr-3 font-mono text-[12px] text-zinc-100">{proof[i]}</td>
                <td className="py-2 pr-3 font-mono text-[12px] text-[#d6cbff]">{hop(proof[i], b)}</td>
                <td className="py-2 font-mono text-[12px] text-zinc-100">{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-[12.5px] text-zinc-500">Returned by algo.SPpaths and drawn as returned; the gate keeps a cause only with this path.</p>
      </div>
    </section>
  );
}
