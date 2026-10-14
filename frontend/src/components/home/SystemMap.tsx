"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { useReducedMotion } from "@/hooks/useReducedMotion";

/**
 * "Where it sits": an isometric system map (our own line art). Inputs on the left feed evidence into the
 * FalkorDB context graph; the crew above it proposes and the graph's queries decide; outputs leave on the right.
 * Every part is a focusable button; hovering or focusing one lights it and explains it in the caption under
 * the map. Packets ride the wires only while the map is on screen and never under reduced motion.
 * Illustrative: no numbers here are measurements.
 */

type PartId = "alerts" | "deploys" | "warehouse" | "docs" | "graph" | "crew" | "action" | "owners" | "preflight";
type Tile = { cx: number; cy: number; w: number; h: number; d: number };
type Group = "reads" | "decides" | "acts";

const GREY = "rgb(255 255 255 / 0.28)";
const WHITE = "rgb(255 255 255 / 0.88)";
const EMBER = "var(--fl-ember)";
const IRIS = "var(--fl-iris)";
const PROOF = "var(--fl-proof)";
const TOP_FILL = "#111214";
const SIDE_FILL = "#0b0c0d";

type Part = {
  id: PartId; name: string; sub: string; caption: string; tone: string; group: Group;
  tile: Tile; hit: [number, number, number, number][];
};

const IN_Y = [140, 255, 370, 485];
const OUT_Y = [150, 275, 400];
const inTile = (cy: number): Tile => ({ cx: 232, cy, w: 44, h: 22, d: 10 });
const outTile = (cy: number): Tile => ({ cx: 930, cy, w: 44, h: 22, d: 10 });
const GRAPH: Tile = { cx: 560, cy: 400, w: 150, h: 75, d: 14 };
const CREW: Tile = { cx: 560, cy: 170, w: 84, h: 42, d: 10 };

const PARTS: Part[] = [
  { id: "alerts", name: "Alerts", sub: "PagerDuty-style pages", tone: EMBER, group: "reads", tile: inTile(IN_Y[0]), hit: [[10, 108, 280, 70]],
    caption: "Pages land as symptoms on the services that raised them; algo.WCC groups a storm into separate incidents before anything is blamed." },
  { id: "deploys", name: "Deploys", sub: "GitHub", tone: WHITE, group: "reads", tile: inTile(IN_Y[1]), hit: [[10, 223, 280, 70]],
    caption: "Deploys and merged PRs become CHANGED edges, so every suspect is a real change with a time, a diff and an author." },
  { id: "warehouse", name: "Warehouse", sub: "dbt · SQL", tone: WHITE, group: "reads", tile: inTile(IN_Y[2]), hit: [[10, 338, 280, 70]],
    caption: "dbt and SQL lineage is ingested into the same graph, so a data incident traces through tables the way a page traces through services." },
  { id: "docs", name: "Docs & decisions", sub: "ADRs · runbooks", tone: WHITE, group: "reads", tile: inTile(IN_Y[3]), hit: [[10, 453, 280, 70]],
    caption: "ADRs and runbooks become nodes linked to what they govern, so who decided what, and why, is a query rather than a search." },
  { id: "graph", name: "FalkorDB context graph", sub: "one graph per tenant", tone: IRIS, group: "decides", tile: GRAPH, hit: [[404, 318, 316, 210], [730, 448, 280, 110]],
    caption: "One FalkorDB graph per tenant holds topology, evidence, decisions and memory; paths, flows and cuts are computed in the graph, never in app code." },
  { id: "crew", name: "Faultline crew", sub: "proposes · the gate decides", tone: WHITE, group: "decides", tile: CREW, hit: [[420, 64, 280, 162]],
    caption: "The agents read through a read-only connection and propose hypotheses; the deterministic Evidence Gate keeps only what a query proves." },
  { id: "action", name: "One approved action", sub: "PR · flag", tone: PROOF, group: "acts", tile: outTile(OUT_Y[0]), hit: [[880, 118, 312, 70]],
    caption: "A human approves the exact plan, bound to its hash; it runs once and is verified through a second channel before it counts as applied." },
  { id: "owners", name: "Who fixes it", sub: "owners · experts", tone: PROOF, group: "acts", tile: outTile(OUT_Y[1]), hit: [[880, 243, 312, 70]],
    caption: "Ownership and expertise edges name who should fix it, ranked from the evidence rather than guessed from a team list." },
  { id: "preflight", name: "Preflight on PRs", sub: "blocks risky merges", tone: PROOF, group: "acts", tile: outTile(OUT_Y[2]), hit: [[880, 368, 312, 70]],
    caption: "The same graph checks a pull request before it ships: a change with a risky path to something critical is held at the gate." },
];

const DEFAULT_CAPTION = {
  name: "The loop",
  caption: "Evidence comes in from the systems you already run, every verdict is a FalkorDB query, and one approved action goes out and is written back.",
};

const GROUP_LABEL: Record<Group, string> = { reads: "Reads", decides: "Decides", acts: "Acts" };

/* --- isometric geometry: a tile is a rhombus top (2:1) with two visible side faces --- */
function slab({ cx, cy, w, h, d }: Tile) {
  return {
    top: `M ${cx} ${cy - h} L ${cx + w} ${cy} L ${cx} ${cy + h} L ${cx - w} ${cy} Z`,
    sides: `M ${cx - w} ${cy} L ${cx} ${cy + h} L ${cx + w} ${cy} L ${cx + w} ${cy + d} L ${cx} ${cy + h + d} L ${cx - w} ${cy + d} Z`,
    edge: `M ${cx} ${cy + h} V ${cy + h + d}`,
  };
}
const inset = (t: Tile, k: number): Tile => ({ ...t, w: t.w * k, h: t.h * k });
/** Maps the unit square [-1, 1]² onto a tile's top face, so glyphs can be drawn flat and land in isometric. */
const onTop = ({ cx, cy, w, h }: Tile) => `matrix(${w / 2} ${h / 2} ${-w / 2} ${h / 2} ${cx} ${cy})`;

function Slab({ tile, stroke, fill = TOP_FILL }: { tile: Tile; stroke: string; fill?: string }) {
  const s = slab(tile);
  return (
    <g strokeLinejoin="round">
      <path d={s.sides} fill={SIDE_FILL} stroke={stroke} strokeWidth={1} />
      <path d={s.edge} stroke={stroke} strokeWidth={1} />
      <path d={s.top} style={{ fill }} stroke={stroke} strokeWidth={1} />
    </g>
  );
}

const NS = { vectorEffect: "non-scaling-stroke" as const, fill: "none", strokeWidth: 1.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

/** Line glyphs printed on each tile's top face (local units, drawn flat). */
function Glyph({ id, stroke, tone }: { id: PartId; stroke: string; tone: string }) {
  switch (id) {
    case "alerts":
      return (
        <>
          <polyline points="-0.62,0.18 -0.26,0.18 -0.12,-0.36 0.06,0.52 0.2,0.18 0.62,0.18" stroke={stroke} {...NS} />
          <circle cx={0.42} cy={-0.42} r={0.1} fill={tone} />
        </>
      );
    case "deploys":
      return (
        <>
          <path d="M -0.6 0.28 L 0.6 0.28 M -0.25 0.28 C 0 0.28, -0.05 -0.32, 0.25 -0.32 L 0.6 -0.32" stroke={stroke} {...NS} />
          {[[-0.6, 0.28], [0.6, 0.28], [0.6, -0.32]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r={0.1} fill={TOP_FILL} stroke={stroke} vectorEffect="non-scaling-stroke" />)}
        </>
      );
    case "warehouse":
      return <path d="M -0.56 -0.46 H 0.56 V 0.46 H -0.56 Z M -0.56 -0.16 H 0.56 M -0.56 0.15 H 0.56 M -0.18 -0.46 V 0.46 M 0.18 -0.46 V 0.46" stroke={stroke} {...NS} />;
    case "docs":
      return <path d="M -0.42 -0.56 H 0.2 L 0.42 -0.34 V 0.56 H -0.42 Z M 0.2 -0.56 V -0.34 H 0.42 M -0.24 -0.16 H 0.24 M -0.24 0.06 H 0.24 M -0.24 0.28 H 0.08" stroke={stroke} {...NS} />;
    case "action":
      return (
        <>
          <rect x={-0.58} y={-0.24} width={1.16} height={0.48} rx={0.24} stroke={stroke} {...NS} />
          <circle cx={0.33} cy={0} r={0.15} fill={tone} />
        </>
      );
    case "owners":
      return (
        <>
          <circle cx={0} cy={-0.26} r={0.2} stroke={stroke} {...NS} />
          <path d="M -0.44 0.52 Q -0.44 0.06 0 0.06 Q 0.44 0.06 0.44 0.52" stroke={stroke} {...NS} />
        </>
      );
    case "preflight":
      return (
        <>
          <path d="M -0.45 -0.28 V 0.33 M 0.45 0.33 V -0.12 Q 0.45 -0.4 0.16 -0.4 M 0.3 -0.52 L 0.16 -0.4 L 0.3 -0.28" stroke={stroke} {...NS} />
          {[[-0.45, -0.42], [-0.45, 0.46], [0.45, 0.46]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r={0.12} fill={TOP_FILL} stroke={stroke} vectorEffect="non-scaling-stroke" />)}
        </>
      );
    default:
      return null;
  }
}

/* the small graph printed on the platform: a cause (ember) and the path that proves it (mint) */
const G_NODES: Record<string, [number, number]> = {
  a: [-0.6, -0.45], b: [-0.1, -0.66], c: [0.46, -0.4], d: [-0.34, 0.04], e: [0.14, -0.06],
  f: [0.6, 0.26], g: [-0.56, 0.56], h: [0.1, 0.56],
};
const G_EDGES = ["ab", "bc", "ad", "be", "de", "ec", "ef", "dg", "gh", "hf", "eh"];
const G_PATH = ["ad", "de", "ef"];

function ContextGraph({ lit }: { lit: boolean }) {
  return (
    <g transform={onTop(inset(GRAPH, 0.82))}>
      {G_EDGES.map((k) => {
        const [p, q] = [G_NODES[k[0]], G_NODES[k[1]]];
        const proof = G_PATH.includes(k);
        return (
          <line key={k} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} vectorEffect="non-scaling-stroke"
                stroke={proof ? PROOF : "rgb(255 255 255 / 0.26)"} strokeWidth={proof ? 1.8 : 1} strokeOpacity={proof && !lit ? 0.75 : 1} />
        );
      })}
      {Object.entries(G_NODES).map(([k, [x, y]]) => (
        <circle key={k} cx={x} cy={y} r={k === "a" ? 0.075 : 0.055} vectorEffect="non-scaling-stroke"
                fill={k === "a" ? EMBER : TOP_FILL} stroke={k === "a" ? EMBER : lit ? IRIS : "rgb(255 255 255 / 0.5)"} strokeWidth={1} />
      ))}
    </g>
  );
}

/** Three small blocks on the crew's platform: two agents and, in mint, the gate. */
function CrewBlocks({ stroke }: { stroke: string }) {
  const blocks: [number, number, string][] = [[528, 172, stroke], [560, 156, stroke], [592, 172, PROOF]];
  return (
    <>
      {blocks.map(([x, y, s]) => <Slab key={x} tile={{ cx: x, cy: y - 11, w: 12, h: 6, d: 11 }} stroke={s} />)}
    </>
  );
}

/* --- wires --- */
type Wire = { id: string; d: string; ends: [PartId, PartId]; packet: string; dur: number };
const inWire = (y: number, ex: number, ey: number) => `M 276 ${y} C 386 ${y}, ${ex - 90} ${ey}, ${ex} ${ey}`;
const outWire = (y: number) => `M 644 170 C 744 170, 790 ${y}, 886 ${y}`;
const WIRES: Wire[] = [
  { id: "w-alerts", d: inWire(IN_Y[0], 509, 350), ends: ["alerts", "graph"], packet: EMBER, dur: 7.5 },
  { id: "w-deploys", d: inWire(IN_Y[1], 482, 364), ends: ["deploys", "graph"], packet: WHITE, dur: 8.5 },
  { id: "w-warehouse", d: inWire(IN_Y[2], 455, 377), ends: ["warehouse", "graph"], packet: WHITE, dur: 8 },
  { id: "w-docs", d: inWire(IN_Y[3], 428, 391), ends: ["docs", "graph"], packet: WHITE, dur: 9 },
  { id: "w-hyp", d: "M 540 214 V 335", ends: ["crew", "graph"], packet: WHITE, dur: 5 },
  { id: "w-verdict", d: "M 580 335 V 214", ends: ["graph", "crew"], packet: IRIS, dur: 5 },
  { id: "w-action", d: outWire(OUT_Y[0]), ends: ["crew", "action"], packet: PROOF, dur: 8 },
  { id: "w-owners", d: outWire(OUT_Y[1]), ends: ["crew", "owners"], packet: PROOF, dur: 8.5 },
  { id: "w-preflight", d: outWire(OUT_Y[2]), ends: ["crew", "preflight"], packet: PROOF, dur: 9 },
];

function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** True while `ref` is on screen (packets animate only then). */
function useOnScreen(ref: React.RefObject<Element | null>): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => setOn(e.isIntersecting), { threshold: 0.1 });
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return on;
}

export function SystemMap() {
  const reduced = useReducedMotion();
  const compact = useMedia("(max-width: 1023px)");   // below lg the map's labels would render under 11 px: list them instead
  const frame = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(frame);
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const captionId = `map-caption-${uid}`;
  const [hover, setHover] = useState<PartId | null>(null);
  const [pinned, setPinned] = useState<PartId | null>(null);
  const shown = hover ?? pinned;
  const part = PARTS.find((p) => p.id === shown);
  const live = onScreen && !reduced;
  const ease = reduced ? "none" : "opacity 0.25s var(--fl-ease-quick), transform 0.3s var(--fl-ease)";

  const pick = (id: PartId) => setPinned((p) => (p === id ? null : id));
  const handlers = (id: PartId) => ({
    onMouseEnter: () => setHover(id),
    onMouseLeave: () => setHover(null),
    onFocus: () => setHover(id),
    onBlur: () => setHover(null),
    onClick: () => pick(id),
  });

  return (
    <section aria-labelledby={`map-title-${uid}`} className="relative isolate mx-auto max-w-[1200px] px-5 py-24 sm:px-8 lg:py-32">
      <h2 id={`map-title-${uid}`} className="max-w-[920px] text-[clamp(1.9rem,4.2vw,3rem)] font-[510] leading-[1.08] tracking-[-0.022em] text-zinc-50">
        Where it sits.{" "}
        <span className="text-[var(--fl-muted)]">It reads what your stack already emits, and decides only through the graph.</span>
      </h2>

      <div ref={frame} data-spot className="relative mt-14 overflow-hidden rounded-2xl border border-white/[0.08] bg-[var(--fl-surface)] p-3 sm:p-5">
        <svg viewBox={compact ? "172 112 820 410" : "0 44 1200 548"} className="block h-auto w-full"
             role={compact ? undefined : "group"} aria-label={compact ? undefined : "System map: the parts Faultline reads, decides with and acts on"}
             aria-hidden={compact ? true : undefined}>
          <defs>
            <pattern id={`iso-${uid}`} width="64" height="32" patternUnits="userSpaceOnUse">
              <path d="M 0 0 L 64 32 M 0 32 L 64 0" stroke="rgb(255 255 255 / 0.055)" strokeWidth="1" />
            </pattern>
            <radialGradient id={`fade-${uid}`} cx="50%" cy="50%" r="60%">
              <stop offset="0.35" stopColor="#fff" />
              <stop offset="1" stopColor="#000" />
            </radialGradient>
            <mask id={`mask-${uid}`}><rect width="1200" height="640" fill={`url(#fade-${uid})`} /></mask>
          </defs>
          <rect width="1200" height="640" fill={`url(#iso-${uid})`} mask={`url(#mask-${uid})`} />

          {/* wires first, so the tiles sit on top of their ends */}
          {WIRES.map((w) => {
            const lit = shown !== null && w.ends.includes(shown);
            return (
              <path key={w.id} id={`${w.id}-${uid}`} d={w.d} fill="none" strokeWidth={lit ? 1.4 : 1} strokeDasharray="3 5"
                    stroke={lit ? w.packet : GREY} style={{ transition: reduced ? "none" : "stroke 0.25s" }} />
            );
          })}
          {live ? WIRES.map((w, i) => (
            <g key={`p-${w.id}`} opacity={0}>
              <path d="M 0 -3.2 L 6.4 0 L 0 3.2 L -6.4 0 Z" fill={w.packet} />
              <animateMotion dur={`${w.dur}s`} begin={`${(i * 0.85) % 4}s`} repeatCount="indefinite">
                <mpath href={`#${w.id}-${uid}`} />
              </animateMotion>
              <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.12;0.88;1" dur={`${w.dur}s`} begin={`${(i * 0.85) % 4}s`} repeatCount="indefinite" />
            </g>
          )) : null}

          {/* wire labels */}
          <g className="font-mono max-lg:hidden" fontSize="14.5" letterSpacing="1.6" fill="#a1a1aa">
            <text x={286} y={342}>EVIDENCE IN</text>
            <text x={528} y={236} textAnchor="end">HYPOTHESES</text>
            <text x={592} y={236}>VERDICTS</text>
            <text x={700} y={146}>PROOF OUT</text>
          </g>

          {PARTS.map((p) => {
            const lit = shown === p.id;
            const dim = shown !== null && !lit;
            const core = p.id === "graph";
            const base = core ? "color-mix(in oklch, var(--fl-iris) 70%, transparent)" : GREY;
            const stroke = lit ? p.tone : base;
            const fill = lit ? `color-mix(in oklch, ${p.tone} 13%, ${TOP_FILL})` : TOP_FILL;
            const { tile } = p;
            const ring = slab({ ...tile, w: tile.w + 12, h: tile.h + 6 }).top;
            return (
              <g key={p.id} role="button" tabIndex={compact ? -1 : 0} aria-label={`${p.name}: ${p.sub}`} aria-pressed={pinned === p.id}
                 aria-describedby={captionId} className="group cursor-pointer outline-none" {...handlers(p.id)}
                 onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(p.id); } }}>
                {p.hit.map(([x, y, w, h]) => <rect key={`${x},${y}`} x={x} y={y} width={w} height={h} fill="transparent" />)}
                {/* only the art dims when another part is lit; the labels keep their contrast */}
                <g style={{ opacity: dim ? 0.5 : 1, transform: lit && !reduced ? "translateY(-5px)" : "none", transition: ease }}>
                  {core ? <Slab tile={{ ...tile, cy: tile.cy + 22, d: 8 }} stroke={GREY} /> : null}
                  <Slab tile={tile} stroke={stroke} fill={fill} />
                  <path d={slab(inset(tile, 0.8)).top} fill="none" stroke={stroke} strokeOpacity={0.35} />
                  {core ? <ContextGraph lit={lit} /> : p.id === "crew" ? <CrewBlocks stroke={lit ? WHITE : "rgb(255 255 255 / 0.4)"} /> : (
                    <g transform={onTop(inset(tile, 0.8))}><Glyph id={p.id} stroke={lit ? p.tone : "rgb(255 255 255 / 0.55)"} tone={p.tone} /></g>
                  )}
                </g>
                {/* keyboard focus: a sky ring around the tile */}
                <path d={ring} fill="none" stroke="oklch(0.746 0.16 232.661)" strokeWidth={1.6} strokeDasharray="4 3"
                      className="opacity-0 group-focus-visible:opacity-100" />
                <PartLabel p={p} lit={lit} />
              </g>
            );
          })}
        </svg>

        <div className="mt-3 flex items-center justify-between px-1 font-mono text-[11px] text-zinc-400">
          <span className="uppercase tracking-[0.16em]">{compact ? "Tap a part below" : "Hover a part"}</span>
          <span>illustrative</span>
        </div>
      </div>

      {/* the caption: what the lit part does, in one sentence */}
      <div className="mt-5 flex min-h-[4.5rem] items-start gap-3 sm:min-h-[3.5rem]">
        <span aria-hidden className="mt-[0.55rem] size-2 shrink-0 rotate-45 rounded-[1px]" style={{ background: part ? part.tone : "rgb(255 255 255 / 0.6)" }} />
        <p id={captionId} className="max-w-3xl text-[15px] leading-relaxed text-[var(--fl-muted)]">
          <span className="font-[560] text-zinc-100">{part ? part.name : DEFAULT_CAPTION.name}.</span>{" "}
          {part ? part.caption : DEFAULT_CAPTION.caption}
        </p>
      </div>

      {compact ? (
        <div className="mt-6 grid gap-6">
          {(["reads", "decides", "acts"] as Group[]).map((g) => (
            <div key={g}>
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-zinc-400">{GROUP_LABEL[g]}</p>
              <ul className="mt-2 border-t border-white/[0.08]">
                {PARTS.filter((p) => p.group === g).map((p) => (
                  <li key={p.id} className="border-b border-white/[0.08]">
                    <button type="button" aria-pressed={pinned === p.id} aria-describedby={captionId} {...handlers(p.id)}
                            className="flex w-full items-center gap-3 rounded py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                      <span aria-hidden className="size-1.5 shrink-0 rotate-45" style={{ background: shown === p.id ? p.tone : "rgb(255 255 255 / 0.35)" }} />
                      <span className={"text-[15px] " + (shown === p.id ? "text-zinc-50" : "text-zinc-200")}>{p.name}</span>
                      <span className="ml-auto text-[13px] text-zinc-400">{p.sub}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** The label beside (inputs, outputs), above (crew) or right of (graph) a part. Hidden below lg, where the list takes over. */
function PartLabel({ p, lit }: { p: Part; lit: boolean }) {
  const title = lit ? "fill-zinc-50" : "fill-zinc-200";
  const t = p.tile;
  if (p.id === "graph") {
    return (
      <g className="max-lg:hidden">
        <circle cx={742} cy={465} r={4.5} fill={IRIS} />
        <text x={756} y={472} fontSize="21" className={title} fontWeight={500}>{p.name}</text>
        <g className="font-mono" fontSize="14.5" letterSpacing="1.6" fill="#a1a1aa">
          {["ONE GRAPH PER TENANT", "PATHS · FLOW · CUTS", "MEMORY ON THE NODES"].map((l, i) => <text key={l} x={742} y={502 + i * 23}>{l}</text>)}
        </g>
      </g>
    );
  }
  if (p.id === "crew") {
    return (
      <g className="max-lg:hidden" textAnchor="middle">
        <text x={t.cx} y={86} fontSize="18" className={title} fontWeight={500}>{p.name}</text>
        <text x={t.cx} y={110} fontSize="14.5" letterSpacing="1.6" fill="#a1a1aa" className="font-mono">PROPOSES · THE GATE DECIDES</text>
      </g>
    );
  }
  const left = p.group === "reads";
  const x = left ? t.cx - t.w - 18 : t.cx + t.w + 18;
  return (
    <g className="max-lg:hidden" textAnchor={left ? "end" : "start"}>
      <text x={x} y={t.cy - 3} fontSize="18" className={title}>{p.name}</text>
      <text x={x} y={t.cy + 18} fontSize="14.5" fill="#a1a1aa">{p.sub}</text>
    </g>
  );
}
