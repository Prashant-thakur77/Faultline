import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import type { ExplainerData } from "./data";
import { place, type V3 } from "./layout3d";
import { emptyShare, fmt, pct } from "./scenes";
import type { Pose } from "./timeline";

/**
 * The explainer's three.js world, built once outside React and mutated every frame from a pose (timeline.ts).
 * Instanced meshes for every repeated shape, one additive point cloud per space for the glow (a cheap bloom
 * stand-in, no post-processing), shared geometries and materials, no allocation in the frame loop.
 * Everything drawn comes from the hero recording's exports (data.ts); positions are the committed layout.
 */

export type Tone = "plain" | "ember" | "mint" | "iris" | "amber" | "gold" | "muted";
export type LabelSpec = { key: string; text: string; tone: Tone; sub?: string };
/** Positions and fades the HTML labels; called from the frame loop (no React state). */
export type Ui = { at: (key: string, x: number, y: number, opacity: number) => void };

const HEX = {
  ember: "#ff6b2c", amber: "#ffc247", mint: "#5ef0b4", iris: "#9a7dff", sky: "#7cc7ff", gold: "#ffd27a",
  white: "#ffffff", svc: "#8a909c", deploy: "#d4d7de", data: "#5f8fa0", dark: "#202228", grey: "#3b3e46", person: "#c7c1ff",
};
const col = (h: string) => new THREE.Color(h);
const C = Object.fromEntries(Object.entries(HEX).map(([k, v]) => [k, col(v)])) as Record<keyof typeof HEX, THREE.Color>;

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const smooth = (x: number) => { const t = clamp01(x); return t * t * t * (t * (t * 6 - 15) + 10); };
const v3 = (p: V3) => new THREE.Vector3(p[0], p[1], p[2]);

/**
 * Additive light that leaves the canvas alpha alone: the canvas is transparent over the page, and plain additive
 * blending would also write alpha, punching dark discs through to the page behind every glow.
 */
function additive<T extends THREE.Material>(m: T): T {
  m.blending = THREE.CustomBlending;
  m.blendEquation = THREE.AddEquation;
  m.blendSrc = THREE.SrcAlphaFactor;
  m.blendDst = THREE.OneFactor;
  m.blendSrcAlpha = THREE.ZeroFactor;
  m.blendDstAlpha = THREE.OneFactor;
  m.transparent = true;
  m.depthWrite = false;
  return m;
}

/* ------------------------------------------------------------------ glow: additive points, one draw call each */

const GLOW_VS = /* glsl */ `
attribute vec3 aColor;
attribute float aSize;
uniform float uScale;
varying vec3 vColor;
void main() {
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = clamp(aSize * uScale / -mv.z, 0.0, 300.0);
  gl_Position = projectionMatrix * mv;
}`;
const GLOW_FS = /* glsl */ `
varying vec3 vColor;
void main() {
  vec2 c = gl_PointCoord - 0.5;
  float d = length(c) * 2.0;
  if (d > 1.0) discard;
  float a = exp(-d * d * 5.5) * 0.7 + exp(-d * d * 42.0) * 0.55;
  a *= 1.0 - smoothstep(0.7, 1.0, d);
  gl_FragColor = vec4(vColor * a, 1.0);
}`;

class Glow {
  readonly points: THREE.Points;
  private pos: Float32Array;
  private colr: Float32Array;
  private size: Float32Array;
  private n = 0;
  constructor(private cap: number, mat: THREE.ShaderMaterial) {
    const g = new THREE.BufferGeometry();
    this.pos = new Float32Array(cap * 3);
    this.colr = new Float32Array(cap * 3);
    this.size = new Float32Array(cap);
    g.setAttribute("position", new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute("aColor", new THREE.BufferAttribute(this.colr, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute("aSize", new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    this.points = new THREE.Points(g, mat);
    this.points.frustumCulled = false;
    this.points.renderOrder = 10;
  }
  reset() { this.n = 0; }
  add(x: number, y: number, z: number, c: THREE.Color, k: number, size: number) {
    if (k <= 0.004 || size <= 0 || this.n >= this.cap) return;
    const i = this.n++;
    this.pos[i * 3] = x; this.pos[i * 3 + 1] = y; this.pos[i * 3 + 2] = z;
    this.colr[i * 3] = c.r * k; this.colr[i * 3 + 1] = c.g * k; this.colr[i * 3 + 2] = c.b * k;
    this.size[i] = size;
  }
  addV(p: THREE.Vector3, c: THREE.Color, k: number, size: number) { this.add(p.x, p.y, p.z, c, k, size); }
  commit() {
    const g = this.points.geometry;
    g.setDrawRange(0, this.n);
    for (const name of ["position", "aColor", "aSize"]) (g.getAttribute(name) as THREE.BufferAttribute).needsUpdate = true;
  }
  /** One dark point, so a warm-up render draws (and compiles) the cloud even before it has any light. */
  prime() { this.reset(); this.add(0, 0, 0, C_BLACK, 1, 0.001); this.colr.fill(0, 0, 3); this.commit(); }
  dispose() { this.points.geometry.dispose(); }
}
const C_BLACK = new THREE.Color(0, 0, 0);

/* ------------------------------------------------------------------ the world */

type Kind = "svc" | "deploy" | "data";
type Edge = { a: number; b: number; cap: number; changed: boolean; data: boolean };

/** One drawn copy of the incident graph: the live tenant graph, or its GRAPH.COPY branch. */
type Layer = {
  group: THREE.Group;
  pos: THREE.Vector3[];
  meshes: Record<Kind, THREE.InstancedMesh>;
  slot: number[];
  lines: THREE.LineSegments;
  linePos: Float32Array;
  lineCol: Float32Array;
  glow: Glow;
  mat: THREE.MeshStandardMaterial;
};

export type World = {
  root: THREE.Group;
  /** Shows every object (returns the undo), so the renderer can compile all shaders up front. */
  everything: () => () => void;
  tick: (p: Pose, time: number, cam: THREE.PerspectiveCamera, size: { width: number; height: number }, still: boolean, ui: Ui) => void;
  dispose: () => void;
};

const UP = new THREE.Vector3(0, 1, 0);
/** arr[o..o+5] = a, b (two points of a line segment), without allocating. */
function seg(arr: Float32Array, o: number, ax: number, ay: number, az: number, bx: number, by: number, bz: number) {
  arr[o] = ax; arr[o + 1] = ay; arr[o + 2] = az; arr[o + 3] = bx; arr[o + 4] = by; arr[o + 5] = bz;
}
const PIPE = new THREE.Color("#3a3d45");

export function labelSpecs(d: ExplainerData): LabelSpec[] {
  const v = d.values;
  const s = d.stats;
  const rel = (t: string) => s.rel_types.find((r) => r.type === t)?.edges;
  const grp = (n: number) => n.toLocaleString("en-US");
  const recChain = d.paths.find((p) => p.cause === "D-rec-12" && p.symptom === "checkout");
  const top = [...d.people].sort((a, b) => b.score - a.score).slice(0, 3);
  const deck = ["PROPAGATES_TO", "CHANGED", "OWNS"];
  return [
    { key: "src:0", text: "Alerts & telemetry", tone: "plain", sub: "services · symptoms" },
    { key: "src:1", text: "Deploys", tone: "plain", sub: "GitHub · CHANGED" },
    { key: "src:2", text: "Warehouse", tone: "plain", sub: "dbt · SQL lineage" },
    { key: "src:3", text: "Docs & ADRs", tone: "plain", sub: "decisions · runbooks" },
    { key: "src:4", text: "People", tone: "plain", sub: "owners · on-call" },
    { key: "box:main", text: "tenant_acme", tone: "iris", sub: `one FalkorDB graph · ${grp(s.nodes)} nodes · ${grp(s.edges)} edges` },
    { key: "box:0", text: "tenant_globex", tone: "muted" },
    { key: "box:1", text: "golden_acme", tone: "muted", sub: "GRAPH.COPY source" },
    { key: "box:2", text: d.graphName || "eval clean room", tone: "muted", sub: "this incident's copy" },
    { key: "plate", text: `${s.engine ?? "FalkorDB"}`, tone: "iris", sub: "GRAPH.RO_QUERY · TIMEOUT · LIMIT" },
    ...deck.map((t, i) => ({
      key: `mat:${i}`, text: t, tone: (i === 0 ? "mint" : i === 1 ? "ember" : "iris") as Tone,
      sub: `${rel(t) ?? "–"} edges · ${pct(emptyShare(rel(t), s.nodes))} empty`,
    })),
    { key: "mat:more", text: `+ ${Math.max(0, s.rel_types_with_edges - deck.length)} more relationship types`, tone: "muted", sub: "one sparse matrix each" },
    { key: "mat:row", text: "checkout's row = one hop", tone: "mint", sub: "frontier × matrix → next frontier" },
    { key: "n:checkout", text: "checkout", tone: "ember", sub: "alerting" },
    { key: "n:frontend", text: "frontend", tone: "amber", sub: "1 hop" },
    { key: "n:frontend-proxy", text: "frontend-proxy", tone: "amber", sub: "2 hops" },
    { key: "n:D-rec-12", text: "D-rec-12", tone: "plain" },
    { key: "n:D-email-88", text: "D-email-88", tone: "plain" },
    { key: "n:D-pay-417", text: "D-pay-417", tone: "ember", sub: "cause" },
    { key: "n:payment", text: "payment", tone: "mint" },
    { key: "n:email", text: "email", tone: "plain" },
    { key: "rec0", text: `D-rec-12 → checkout · ${recChain && recChain.chain.length === 0 ? "0 rows" : "–"}`, tone: "ember", sub: "no path, no claim (G2)" },
    { key: "pay1", text: fmt(v, "s1.chain"), tone: "mint", sub: "algo.SPpaths · 1 row" },
    { key: "gauge", text: `max flow ${fmt(v, "s1.D-email-88.max_flow")}  vs  needed ${fmt(v, "s1.D-email-88.needed")}`, tone: "ember", sub: "D-email-88 · rejected (G5)" },
    { key: "full", text: "payment → checkout runs full", tone: "mint", sub: "cap 1.0" },
    { key: "live", text: "tenant graph", tone: "muted", sub: "untouched" },
    { key: "branch", text: "GRAPH.COPY", tone: "iris", sub: d.branch },
    { key: "cut", text: `min-cut · ${d.cut.map((c) => `${c.u}→${c.v}`).join(", ")}`, tone: "ember", sub: "from algo.maxFlow edgeFlows" },
    { key: "verdict", text: "contains", tone: "mint", sub: `protected (${d.protect.join(", ")}) no longer reached` },
    ...top.map((p, i) => ({ key: `p:${i}`, text: p.name, tone: (i === 0 ? "mint" : "iris") as Tone, sub: `${p.id} · score ${p.score}` })),
    { key: "tree", text: "escalation tree", tone: "iris", sub: "algo.MSF" },
    { key: "model", text: "the model", tone: "plain", sub: "can only point" },
    { key: "ro", text: "GRAPH.RO_QUERY", tone: "iris", sub: "TIMEOUT · LIMIT · read-only user" },
    { key: "write", text: "one atomic write", tone: "gold", sub: "W_WB_1 · CAUSED · RESOLVED_BY · decision" },
    { key: "reread", text: `re-read ${fmt(v, "s1.writeback")}`, tone: "mint", sub: "separate read-only connection" },
  ];
}

export function buildWorld(d: ExplainerData): World {
  const disposables: { dispose: () => void }[] = [];
  const keep = <T extends { dispose: () => void }>(x: T) => (disposables.push(x), x);
  const root = new THREE.Group();

  /* shared geometry and materials */
  const gSphere = keep(new THREE.IcosahedronGeometry(1, 3));
  const gOcta = keep(new THREE.OctahedronGeometry(1.25, 0));
  const gBox = keep(new RoundedBoxGeometry(1.5, 1.5, 1.5, 2, 0.28));
  const gCyl = keep(new THREE.CylinderGeometry(1, 1, 1, 14, 1, true));
  const glowMat = keep(additive(new THREE.ShaderMaterial({ uniforms: { uScale: { value: 500 } }, vertexShader: GLOW_VS, fragmentShader: GLOW_FS })));
  const lineMat = () => keep(additive(new THREE.LineBasicMaterial({ vertexColors: true, toneMapped: false })));
  const basic = (hex: string, opacity = 1, add = false) => {
    const m = new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity, toneMapped: false });
    return keep(add ? additive(m) : m);
  };

  /* the incident graph: nodes (deploys from the recorded CHANGED hops) and edges */
  const ids: string[] = [];
  const kind: Kind[] = [];
  const radius: number[] = [];
  const maxB = Math.max(1, ...d.nodes.map((n) => n.betweenness ?? 0));
  for (const c of d.changed) { ids.push(c.deploy); kind.push("deploy"); radius.push(0.12); }
  for (const n of d.nodes) {
    ids.push(n.id);
    const data = n.label === "Table" || n.label === "KPI" || n.label === "Dashboard";
    kind.push(data ? "data" : "svc");
    // node size = betweenness (from FalkorDB), log-scaled
    radius.push(data ? 0.085 : 0.095 + 0.12 * Math.log1p(n.betweenness ?? 0) / Math.log1p(maxB));
  }
  const idx = new Map(ids.map((id, i) => [id, i]));
  const at = (id: string) => idx.get(id) ?? -1;
  const home = ids.map((id) => v3(place(id)));
  const edges: Edge[] = [];
  for (const c of d.changed) if (at(c.target) >= 0) edges.push({ a: at(c.deploy), b: at(c.target), cap: 1, changed: true, data: false });
  for (const e of d.edges) {
    if (at(e.source) < 0 || at(e.target) < 0) continue;
    edges.push({ a: at(e.source), b: at(e.target), cap: e.cap ?? 1, changed: false, data: e.domain === "data" });
  }
  const edgeIdx = (u: string, v: string) => edges.findIndex((e) => ids[e.a] === u && ids[e.b] === v);
  const hopsOf = new Map(d.blast.rows.map((r) => [r.id, r.hops]));
  const symptom = d.blast.from;
  const payChain = d.paths.find((p) => p.cause === "D-pay-417" && p.symptom === symptom)?.chain ?? [];
  const recChain = d.paths.find((p) => p.cause === "D-rec-12" && p.chain.length > 0)?.chain ?? [];
  const emailChain = d.paths.find((p) => p.cause === "D-email-88" && p.symptom === symptom)?.chain ?? [];
  const onPay = new Set(payChain);
  const cutSet = new Set(d.cut.map((c) => edgeIdx(c.u, c.v)).filter((i) => i >= 0));
  const protect = new Set(d.protect);
  const quiet = new Set(d.noLongerReached);

  function makeLayer(tint: number): Layer {
    const group = new THREE.Group();
    const mat = keep(new THREE.MeshStandardMaterial({ color: "#ffffff", metalness: 0.35, roughness: 0.34, transparent: tint < 1, opacity: tint }));
    const count: Record<Kind, number> = { svc: 0, deploy: 0, data: 0 };
    const slot = kind.map((k) => count[k]++);
    const mk = (g: THREE.BufferGeometry, n: number) => {
      const m = new THREE.InstancedMesh(g, mat, Math.max(1, n));
      m.count = n;
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(1, n) * 3), 3).setUsage(THREE.DynamicDrawUsage);
      m.frustumCulled = false;
      group.add(m);
      return m;
    };
    const meshes = { svc: mk(gSphere, count.svc), deploy: mk(gOcta, count.deploy), data: mk(gBox, count.data) };
    const lg = keep(new THREE.BufferGeometry());
    const linePos = new Float32Array(edges.length * 6);
    const lineCol = new Float32Array(edges.length * 6);
    lg.setAttribute("position", new THREE.BufferAttribute(linePos, 3).setUsage(THREE.DynamicDrawUsage));
    lg.setAttribute("color", new THREE.BufferAttribute(lineCol, 3).setUsage(THREE.DynamicDrawUsage));
    const lines = new THREE.LineSegments(lg, lineMat());
    lines.frustumCulled = false;
    group.add(lines);
    const glow = new Glow(420, glowMat);
    disposables.push(glow);
    group.add(glow.points);
    return { group, pos: home.map((p) => p.clone()), meshes, slot, lines, linePos, lineCol, glow, mat };
  }

  const main = makeLayer(1);
  const branch = makeLayer(0.9);
  root.add(main.group, branch.group);

  /* sources (scene 1): five tiles streaming into the tenant graph */
  const SRC = [0, 1, 2, 3, 4].map((i) => new THREE.Vector3(-9.6, 3.0 - i * 1.5, 0.4));
  const srcOf = (i: number) => (kind[i] === "deploy" ? 1 : kind[i] === "data" ? 2 : 0);
  const srcTargets = [0, 1, 2, 3, 4].map((sI) => { const l = ids.map((_, i) => i).filter((i) => srcOf(i) === sI); return l.length ? l : ids.map((_, i) => i); });
  const srcMat = keep(new THREE.MeshStandardMaterial({ color: "#16171b", metalness: 0.5, roughness: 0.3, transparent: true }));
  const gTile = keep(new RoundedBoxGeometry(0.8, 0.8, 0.14, 3, 0.12));
  const tiles = SRC.map((p) => { const m = new THREE.Mesh(gTile, srcMat); m.position.copy(p); root.add(m); return m; });
  const worldGlow = new Glow(900, glowMat);
  disposables.push(worldGlow);
  root.add(worldGlow.points);

  /* tenant boxes */
  const boxLines = (w: number, h: number, dz: number, hex: string) => {
    const l = new THREE.LineSegments(keep(new THREE.EdgesGeometry(keep(new THREE.BoxGeometry(w, h, dz)))), basic(hex, 0, true));
    root.add(l);
    return l;
  };
  const box = boxLines(11.9, 7.9, 4.6, HEX.iris);
  box.position.set(0.25, -0.3, 0);
  const others = [0, 1, 2].map((i) => { const b = boxLines(2.6, 1.7, 1.2, "#8a8fa0"); b.position.set(9.4, 2.5 - i * 2.5, -0.6); return b; });
  const otherDots = others.map((b, bi) => Array.from({ length: 11 }, (_, i) => new THREE.Vector3(
    b.position.x + Math.sin(i * 2.1 + bi) * 1.0, b.position.y + Math.cos(i * 1.7 + bi * 2) * 0.6, b.position.z + Math.sin(i * 3.3) * 0.4)));

  /* the FalkorDB plate under the graph */
  // matte on purpose: a glossy slab seen at a grazing angle mirrors the whole environment
  const plate = new THREE.Mesh(keep(new RoundedBoxGeometry(13, 0.22, 5.2, 3, 0.09)),
    keep(new THREE.MeshBasicMaterial({ color: "#0b0b10", transparent: true })));
  const plateEdge = new THREE.LineSegments(keep(new THREE.EdgesGeometry(keep(new THREE.BoxGeometry(13.05, 0.24, 5.25)))), basic(HEX.iris, 0.5, true));
  const plateY = -4.75;
  root.add(plate, plateEdge);

  /* sparse matrices (scene 2): rows and columns = nodes (plus owner teams), lit cells = edges */
  const teams = d.owns.map((o) => o.team);
  const order = [...ids.keys()].sort((a, b) => home[a].x - home[b].x || ids[a].localeCompare(ids[b])).map((i) => ids[i]).concat(teams);
  const N = order.length;
  const ord = new Map(order.map((id, i) => [id, i]));
  const S = 4.1;
  const cs = S / N;
  const deck = new THREE.Group();
  root.add(deck);
  const planeMats: THREE.MeshBasicMaterial[] = [];
  const gridMats: THREE.LineBasicMaterial[] = [];
  const planeOff = (k: number) => new THREE.Vector3(0.32 * k, 0.26 * k, -0.85 * k);
  const gridGeo = keep(new THREE.BufferGeometry());
  {
    const g: number[] = [];
    for (let i = 0; i <= N; i += 1) {
      const u = -S / 2 + i * cs;
      g.push(u, -S / 2, 0, u, S / 2, 0, -S / 2, u, 0, S / 2, u, 0);
    }
    gridGeo.setAttribute("position", new THREE.Float32BufferAttribute(g, 3));
  }
  const gPlane = keep(new THREE.PlaneGeometry(S, S));
  const planeEdges = keep(new THREE.EdgesGeometry(gPlane));
  const deckHex = [HEX.mint, HEX.ember, HEX.iris];
  for (let k = 0; k < 3; k++) {
    const g = new THREE.Group();
    g.position.copy(planeOff(k));
    const pm = basic("#0c0d11", 0);
    planeMats.push(pm);
    g.add(new THREE.Mesh(gPlane, pm));
    const gm = keep(additive(new THREE.LineBasicMaterial({ color: deckHex[k], opacity: 0, toneMapped: false })));
    gridMats.push(gm);
    const grid = new THREE.LineSegments(gridGeo, gm);
    grid.position.z = 0.002;
    g.add(grid);
    const em = basic(deckHex[k], 0, true);
    planeMats.push(em);
    const edge = new THREE.LineSegments(planeEdges, em);
    edge.position.z = 0.003;
    g.add(edge);
    deck.add(g);
  }
  // one faint outline per remaining relationship type (one merged line geometry), fading with depth
  const ghostN = Math.min(60, Math.max(0, d.stats.rel_types_with_edges - 3));
  const ghostMat = keep(additive(new THREE.LineBasicMaterial({ vertexColors: true, opacity: 0, toneMapped: false })));
  const ghostGeo = keep(new THREE.BufferGeometry());
  {
    const pos: number[] = [];
    const cl: number[] = [];
    const h = S / 2;
    for (let i = 0; i < ghostN; i++) {
      const o = planeOff(2).add(new THREE.Vector3(0.05 * (i + 1), 0.04 * (i + 1), -0.13 * (i + 1)));
      const c = 1 - (0.8 * i) / Math.max(1, ghostN);
      const corners = [[-h, -h], [h, -h], [h, h], [-h, h]];
      for (let k = 0; k < 4; k++) {
        const [x0, y0] = corners[k], [x1, y1] = corners[(k + 1) % 4];
        pos.push(o.x + x0, o.y + y0, o.z, o.x + x1, o.y + y1, o.z);
        for (let j = 0; j < 2; j++) cl.push(C.iris.r * c, C.iris.g * c, C.iris.b * c);
      }
    }
    ghostGeo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    ghostGeo.setAttribute("color", new THREE.Float32BufferAttribute(cl, 3));
  }
  deck.add(new THREE.LineSegments(ghostGeo, ghostMat));
  const rowBar = new THREE.Mesh(keep(new THREE.PlaneGeometry(S, cs * 1.1)), basic(HEX.mint, 0, true));
  deck.add(rowBar);
  // cells: PROPAGATES_TO from the recorded edges, CHANGED from the recorded hops, OWNS from the notify/owner reads
  type Cell = { layer: number; r: number; c: number; from: () => THREE.Vector3; local: THREE.Vector3; delay: number; hex: THREE.Color };
  const cells: Cell[] = [];
  const fromV = new THREE.Vector3();
  const mid = (e: Edge) => () => fromV.copy(main.pos[e.a]).add(main.pos[e.b]).multiplyScalar(0.5).applyMatrix4(main.group.matrixWorld);
  const cellLocal = (layer: number, r: number, c: number) =>
    planeOff(layer).add(new THREE.Vector3(-S / 2 + (c + 0.5) * cs, S / 2 - (r + 0.5) * cs, 0.02));
  for (const e of edges) {
    const r = ord.get(ids[e.a])!, c = ord.get(ids[e.b])!;
    const layer = e.changed ? 1 : 0;
    cells.push({ layer, r, c, from: mid(e), local: cellLocal(layer, r, c), delay: 0, hex: layer ? C.ember : e.data ? C.sky : C.mint });
  }
  for (const o of d.owns) {
    for (const id of o.ids) {
      const i = at(id);
      if (i < 0) continue;
      cells.push({ layer: 2, r: ord.get(o.team)!, c: ord.get(id)!, from: () => fromV.copy(main.pos[i]).applyMatrix4(main.group.matrixWorld), local: cellLocal(2, ord.get(o.team)!, ord.get(id)!), delay: 0, hex: C.iris });
    }
  }
  cells.forEach((c, i) => { c.delay = (i / Math.max(1, cells.length)) * 0.62; });
  const gCell = keep(new THREE.PlaneGeometry(cs * 0.9, cs * 0.9));
  const cellMesh = new THREE.InstancedMesh(gCell, keep(new THREE.MeshBasicMaterial({ color: "#ffffff", toneMapped: false, transparent: true, depthWrite: false })), cells.length);
  cellMesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cells.length * 3), 3).setUsage(THREE.DynamicDrawUsage);
  cellMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  cellMesh.frustumCulled = false;
  root.add(cellMesh);
  const symRow = ord.get(symptom) ?? 0;
  rowBar.position.copy(cellLocal(0, symRow, 0)).setX(0);
  rowBar.position.z += 0.01;
  const matLabelAt = [
    planeOff(0).add(new THREE.Vector3(-S / 2 + 0.6, -S / 2 - 0.12, 0)),
    planeOff(1).add(new THREE.Vector3(-S / 2 + 0.5, S / 2 + 0.12, 0)),
    planeOff(2).add(new THREE.Vector3(S / 2 - 0.3, S / 2 + 0.12, 0)),
  ];
  const moreLabelAt = planeOff(2).add(new THREE.Vector3(0.05 * ghostN + S / 2, 0.04 * ghostN + S / 2 + 0.2, -0.13 * ghostN));
  const rowLabelAt = cellLocal(0, symRow, N - 1).setX(S / 2 + 0.1);

  /* proof path, the rejected probe, the asked-for path that returned 0 rows */
  const tube = (chain: string[], r: number, m: THREE.Material) => {
    const pts = chain.map((id) => home[at(id)]).filter(Boolean);
    if (pts.length < 2) return null;
    const g = keep(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts, false, "centripetal"), 80, r, 8, false));
    const mesh = new THREE.Mesh(g, m);
    main.group.add(mesh);
    return { mesh, g, curve: new THREE.CatmullRomCurve3(pts, false, "centripetal") };
  };
  const proofMat = basic(HEX.mint, 0);
  const proof = tube(payChain, 0.03, proofMat);
  const probeMat = basic("#e9e6ff", 0);
  const probe = tube(recChain, 0.022, probeMat);
  const askMat = keep(new THREE.LineDashedMaterial({ color: HEX.ember, dashSize: 0.14, gapSize: 0.1, transparent: true, opacity: 0, toneMapped: false }));
  const askGeo = keep(new THREE.BufferGeometry().setFromPoints([home[at("D-rec-12")] ?? new THREE.Vector3(), home[at(symptom)] ?? new THREE.Vector3()]));
  const ask = new THREE.Line(askGeo, askMat);
  ask.computeLineDistances();
  main.group.add(ask);

  /* blast ripple rings at the symptom */
  const ringGeo = keep(new THREE.RingGeometry(0.96, 1, 96));
  const rings = [0, 1, 2].map(() => { const m = new THREE.Mesh(ringGeo, basic(HEX.amber, 0, true)); main.group.add(m); return m; });

  /* pipes (scene 5): one instanced cylinder per failure-flow edge, radius = capacity */
  const pipeEdges = edges.map((e, i) => (e.changed ? -1 : i)).filter((i) => i >= 0);
  const pipeMat = keep(new THREE.MeshStandardMaterial({ color: "#ffffff", metalness: 0.55, roughness: 0.3 }));
  const pipes = new THREE.InstancedMesh(gCyl, pipeMat, pipeEdges.length);
  pipes.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(pipeEdges.length * 3), 3).setUsage(THREE.DynamicDrawUsage);
  pipes.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  pipes.frustumCulled = false;
  main.group.add(pipes);
  const ePay = edgeIdx(payChain[1] ?? "", payChain[2] ?? "");
  const eEmail = edgeIdx(emailChain[1] ?? "", emailChain[2] ?? "");

  /* cut stubs (scene 6): each cut edge in the branch snaps into two retracting halves */
  const cutList = [...cutSet];
  const stubs = new THREE.InstancedMesh(gCyl, basic(HEX.ember, 1), Math.max(1, cutList.length * 2));
  stubs.count = cutList.length * 2;
  stubs.frustumCulled = false;
  branch.group.add(stubs);

  /* people (scene 7): the recorded who-fixes ranking and escalation tree around the failing component */
  const pIds = [...d.people.map((p) => p.id), ...d.tree.flatMap((t) => [t.from, t.to])].filter((x, i, a) => a.indexOf(x) === i);
  const score = new Map(d.people.map((p) => [p.id, p.score]));
  const maxS = Math.max(1, ...d.people.map((p) => p.score));
  const ranked = [...d.people].sort((a, b) => b.score - a.score).map((p) => p.id);
  const center = home[at(d.failing)] ?? new THREE.Vector3();
  const pHome = pIds.map((id, i) => {
    const r = score.has(id) ? 1.45 : 2.35;
    const a = Math.PI * 0.5 + (i / pIds.length) * Math.PI * 2;
    return new THREE.Vector3(center.x + Math.cos(a) * r, center.y + Math.sin(a) * r * 0.78, center.z + 0.5 + Math.sin(a * 2) * 0.3);
  });
  const pPos = pHome.map((p) => p.clone());
  const pMat = keep(new THREE.MeshStandardMaterial({ color: "#ffffff", metalness: 0.3, roughness: 0.35 }));
  const people = new THREE.InstancedMesh(gSphere, pMat, Math.max(1, pIds.length));
  people.count = pIds.length;
  people.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(1, pIds.length) * 3), 3).setUsage(THREE.DynamicDrawUsage);
  people.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  people.frustumCulled = false;
  main.group.add(people);
  const treeGeo = keep(new THREE.BufferGeometry());
  const treePos = new Float32Array(Math.max(1, d.tree.length + pIds.length) * 6);
  treeGeo.setAttribute("position", new THREE.BufferAttribute(treePos, 3).setUsage(THREE.DynamicDrawUsage));
  const treeCol = new Float32Array(treePos.length);
  treeGeo.setAttribute("color", new THREE.BufferAttribute(treeCol, 3).setUsage(THREE.DynamicDrawUsage));
  const treeLines = new THREE.LineSegments(treeGeo, lineMat());
  treeLines.frustumCulled = false;
  main.group.add(treeLines);

  /* read-only reads and the one write-back (scene 8) */
  const orbPos = new THREE.Vector3(-1.4, 4.1, 1.4);
  const orb = new THREE.Mesh(keep(new THREE.IcosahedronGeometry(0.42, 1)), keep(new THREE.MeshBasicMaterial({ color: HEX.iris, wireframe: true, transparent: true, opacity: 0, toneMapped: false })));
  orb.position.copy(orbPos);
  main.group.add(orb);
  const pointGeo = keep(new THREE.BufferGeometry().setFromPoints([orbPos, orbPos.clone()]));
  const pointMat = keep(new THREE.LineDashedMaterial({ color: "#d9d4ff", dashSize: 0.12, gapSize: 0.09, transparent: true, opacity: 0, toneMapped: false }));
  const pointer = new THREE.Line(pointGeo, pointMat);
  main.group.add(pointer);
  const readIds = ["D-pay-417", d.failing, symptom].filter((x) => at(x) >= 0);
  const beamGeo = keep(new THREE.BufferGeometry());
  const beamPos = new Float32Array(readIds.length * 2 * 6);
  beamGeo.setAttribute("position", new THREE.BufferAttribute(beamPos, 3).setUsage(THREE.DynamicDrawUsage));
  const beamCol = new Float32Array(beamPos.length);
  beamGeo.setAttribute("color", new THREE.BufferAttribute(beamCol, 3).setUsage(THREE.DynamicDrawUsage));
  const beams = new THREE.LineSegments(beamGeo, lineMat());
  beams.frustumCulled = false;
  main.group.add(beams);
  const dPay = home[at("D-pay-417")] ?? new THREE.Vector3();
  const wb = {
    inc: dPay.clone().add(new THREE.Vector3(0.55, -1.35, 0.9)),
    act: dPay.clone().add(new THREE.Vector3(-0.6, -2.0, 0.4)),
    pm: dPay.clone().add(new THREE.Vector3(1.6, -2.15, 1.1)),
    dec: dPay.clone().add(new THREE.Vector3(0.6, -2.75, 1.5)),
  };
  const goldMat = basic(HEX.gold, 0);
  const wbTubes = ([[dPay, wb.inc], [wb.inc, wb.act], [wb.pm, wb.inc], [wb.dec, wb.pm]] as const).map(([a, b]) => {
    const g = keep(new THREE.TubeGeometry(new THREE.LineCurve3(a, b), 12, 0.026, 8, false));
    const m = new THREE.Mesh(g, goldMat);
    main.group.add(m);
    return g;
  });
  const wbNodes = new THREE.InstancedMesh(gOcta, keep(new THREE.MeshStandardMaterial({ color: HEX.gold, metalness: 0.4, roughness: 0.3, emissive: HEX.gold, emissiveIntensity: 0.25 })), 4);
  wbNodes.frustumCulled = false;
  wbNodes.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  main.group.add(wbNodes);
  const wbList = [wb.inc, wb.act, wb.pm, wb.dec];

  /* scratch */
  const tmpC2 = new THREE.Vector3();
  const tmpA = new THREE.Vector3();
  const tmpB = new THREE.Vector3();
  const tmpC = new THREE.Color();
  const tmpD = new THREE.Color();
  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const sv = new THREE.Vector3();
  const look = new THREE.Vector3();
  const nodeC = ids.map(() => new THREE.Color());
  const nodeG = new Float32Array(ids.length);
  const nodeGC = ids.map(() => new THREE.Color());
  const nodeS = new Float32Array(ids.length);

  const oDir = new THREE.Vector3();
  const oMid = new THREE.Vector3();
  const oScale = new THREE.Vector3();
  const oQ = new THREE.Quaternion();
  const orient = (a: THREE.Vector3, b: THREE.Vector3, r: number, out: THREE.Matrix4) => {
    oDir.subVectors(b, a);
    const len = Math.max(1e-4, oDir.length());
    oQ.setFromUnitVectors(UP, oDir.multiplyScalar(1 / len));
    oMid.addVectors(a, b).multiplyScalar(0.5);
    return out.compose(oMid, oQ, oScale.set(r, len, r));
  };

  /** Writes one layer's nodes, edges and glow from per-node colour/glow/scale arrays. */
  function drawLayer(L: Layer, edgeK: (e: Edge, i: number, out: THREE.Color) => number, gs: number) {
    for (let i = 0; i < ids.length; i++) {
      const k = kind[i];
      const s = radius[i] * nodeS[i];
      m4.compose(L.pos[i], q.identity(), tmpA.set(s, s, s));
      L.meshes[k].setMatrixAt(L.slot[i], m4);
      L.meshes[k].setColorAt(L.slot[i], nodeC[i]);
      if (nodeS[i] > 0.02) L.glow.addV(L.pos[i], nodeGC[i], nodeG[i], radius[i] * 9 * gs * Math.min(1, nodeS[i]));
    }
    for (const k of ["svc", "deploy", "data"] as Kind[]) {
      L.meshes[k].instanceMatrix.needsUpdate = true;
      if (L.meshes[k].instanceColor) L.meshes[k].instanceColor!.needsUpdate = true;
    }
    edges.forEach((e, i) => {
      const a = L.pos[e.a], b = L.pos[e.b];
      seg(L.linePos, i * 6, a.x, a.y, a.z, b.x, b.y, b.z);
      const k = edgeK(e, i, tmpD);
      for (let j = 0; j < 2; j++) { L.lineCol[i * 6 + j * 3] = tmpD.r * k; L.lineCol[i * 6 + j * 3 + 1] = tmpD.g * k; L.lineCol[i * 6 + j * 3 + 2] = tmpD.b * k; }
    });
    (L.lines.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (L.lines.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  /** The 2D screen position of a point in a group's space; opacity 0 hides it. */
  function label(ui: Ui, key: string, p: THREE.Vector3, space: THREE.Object3D | null, opacity: number, cam: THREE.Camera, size: { width: number; height: number }, dy = 0) {
    if (opacity <= 0.01) { ui.at(key, 0, 0, 0); return; }
    tmpA.copy(p);
    if (space) tmpA.applyMatrix4(space.matrixWorld);
    tmpA.project(cam);
    if (tmpA.z > 1) { ui.at(key, 0, 0, 0); return; }
    ui.at(key, (tmpA.x * 0.5 + 0.5) * size.width, (-tmpA.y * 0.5 + 0.5) * size.height + dy, opacity);
  }

  function tick(p: Pose, time: number, cam: THREE.PerspectiveCamera, size: { width: number; height: number }, still: boolean, ui: Ui) {
    const t = still ? 2.4 : time;

    /* camera: fit the pose's focus box to this aspect, orbit a little */
    const aspect = size.width / Math.max(1, size.height);
    const tanH = Math.tan(THREE.MathUtils.degToRad(cam.fov / 2));
    const dist = Math.max(p.h / 2 / tanH, p.w / 2 / (tanH * aspect)) + 1.2;
    const yaw = p.yaw + (still ? 0 : Math.sin(t * 0.11) * 0.035);
    const pitch = p.pitch + (still ? 0 : Math.sin(t * 0.07) * 0.018);
    look.set(p.cx, p.cy, 0);
    cam.position.set(look.x + Math.sin(yaw) * Math.cos(pitch) * dist, look.y + Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist);
    cam.lookAt(look);
    cam.updateMatrixWorld();
    glowMat.uniforms.uScale.value = (size.height * (cam.userData.dpr ?? 1)) / (2 * tanH);

    /* graph roots */
    main.group.position.set(p.gx, p.gy, 0);
    main.group.scale.setScalar(p.gs);
    const br = p.branch;
    branch.group.visible = br > 0.01;
    branch.group.position.set(p.gx + (3.3 * 2) * smooth(br), p.gy, -0.6 * (1 - br));
    branch.group.scale.setScalar(p.gs);
    root.updateMatrixWorld();

    /* node positions: fly in from their source (scene 1), then the committed layout */
    for (let i = 0; i < ids.length; i++) {
      const delay = (i / ids.length) * 0.55;
      const k = smooth((p.assemble - delay) / 0.45);
      const s = SRC[srcOf(i)];
      main.pos[i].lerpVectors(s, home[i], k);
      main.pos[i].y += Math.sin(Math.PI * k) * 0.8;
      nodeS[i] = k < 1 ? 0.3 + 0.7 * k : 1;
      if (p.assemble <= delay) nodeS[i] = 0;
    }

    /* main layer colours: base, dimming, the scene's highlights */
    const unplug = p.plug;
    const pulse = still ? 1 : 0.6 + 0.4 * Math.sin(t * 5);
    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      const base = kind[i] === "deploy" ? C.deploy : kind[i] === "data" ? C.data : C.svc;
      nodeC[i].copy(base);
      nodeGC[i].copy(C.white);
      nodeG[i] = 0.1;
      let lit = 0;
      // blast radius (yellow): BFS frontier hop by hop
      const h = hopsOf.get(id);
      if (h !== undefined && p.blast > 0) {
        const k = clamp01((p.bfs - h + 1) / 0.5) * p.blast;
        if (k > 0) { nodeC[i].lerp(C.amber, k); nodeGC[i].copy(C.amber); nodeG[i] = 0.55 * k; lit = Math.max(lit, k); }
      }
      if (id === symptom) {
        const a = p.alert * (1 - p.payOk);
        nodeC[i].lerp(C.ember, Math.max(a, p.blast > 0 ? p.blast : 0));
        nodeGC[i].copy(C.ember).lerp(C.mint, p.payOk);
        nodeG[i] = Math.max(nodeG[i], a * 0.9 * pulse + p.payOk * 0.6);
        lit = Math.max(lit, p.alert, p.payOk);
        if (p.payOk > 0) nodeC[i].lerp(C.mint, p.payOk * 0.8);
      }
      if (kind[i] === "deploy") {
        nodeG[i] = Math.max(nodeG[i], 0.35 * p.suspects);
        nodeGC[i].copy(C.iris);
        lit = Math.max(lit, p.suspects);
        if (id === "D-rec-12") {
          const flash = Math.sin(Math.PI * clamp01(p.recOut * 1.4)) * (1 - p.recOut * 0.3);
          nodeC[i].lerp(C.dark, p.recOut);
          nodeGC[i].copy(C.ember);
          nodeG[i] = p.suspects * 0.35 * (1 - p.recOut) + flash * 0.8;
          lit = Math.max(0, lit - p.recOut);
        }
        if (id === "D-email-88") {
          nodeC[i].lerp(C.dark, p.emailOut);
          if (p.pipes > 0) { nodeGC[i].copy(C.ember); nodeG[i] = Math.max(nodeG[i] * (1 - p.emailOut), 0.5 * p.flow * (1 - p.emailOut)); }
          lit = Math.max(lit * (1 - p.emailOut), p.pipes * (1 - p.emailOut));
        }
        if (id === "D-pay-417") {
          // the cause (red), once proved
          nodeC[i].lerp(C.ember, p.payOk);
          nodeGC[i].copy(C.iris).lerp(C.ember, p.payOk);
          nodeG[i] = Math.max(nodeG[i], 0.95 * p.payOk);
        }
      }
      if (id === "email") { nodeC[i].lerp(C.dark, p.emailOut * 0.8); if (p.pipes > 0) lit = Math.max(lit, p.pipes * (1 - p.emailOut)); }
      if (onPay.has(id) && id !== symptom && kind[i] !== "deploy") {
        const k = clamp01((p.pay * (payChain.length - 1) - payChain.indexOf(id) + 0.6) / 0.6);
        nodeC[i].lerp(C.mint, k * 0.85);
        nodeGC[i].copy(C.mint);
        nodeG[i] = Math.max(nodeG[i], 0.6 * k);
        lit = Math.max(lit, k);
      }
      if (recChain.includes(id) && kind[i] !== "deploy" && p.rec > 0) {
        const k = clamp01((p.rec * (recChain.length - 1) - recChain.indexOf(id) + 0.6) / 0.6) * (1 - p.recOut * 0.8);
        nodeGC[i].copy(C.white);
        nodeG[i] = Math.max(nodeG[i], 0.45 * k);
        lit = Math.max(lit, k);
      }
      if (id === d.failing && (p.people > 0 || p.reads > 0)) lit = Math.max(lit, p.people, p.reads);
      if (readIds.includes(id) && p.reads > 0) { nodeG[i] = Math.max(nodeG[i], 0.5 * p.reads); lit = Math.max(lit, p.reads); }
      // dim what is not part of the scene
      const dim = p.dim * (1 - lit);
      nodeC[i].lerp(C.dark, dim);
      nodeG[i] *= 1 - dim * 0.8;
      // FalkorDB off: no answers, nothing lit
      nodeC[i].lerp(C.grey, unplug * 0.85);
      nodeG[i] *= 1 - unplug;
      // the end card: a calm, lit graph
      if (p.end > 0) { nodeGC[i].lerp(onPay.has(id) ? C.mint : C.iris, p.end); nodeG[i] = Math.max(nodeG[i], p.end * (onPay.has(id) ? 0.7 : 0.22)); }
    }
    main.glow.reset();
    drawLayer(main, (e, i, out) => {
      const appear = Math.min(nodeS[e.a], nodeS[e.b]);
      out.copy(e.changed ? C.iris : e.data ? C.sky : C.white);
      let k = (e.changed ? 0.32 : 0.2) * (appear >= 1 ? 1 : appear * appear);
      const ha = hopsOf.get(ids[e.a]), hb = hopsOf.get(ids[e.b]);
      if (p.blast > 0 && hb !== undefined && (ids[e.a] === symptom || ha !== undefined)) {
        const kk = clamp01((p.bfs - hb + 1) / 0.5) * p.blast;
        out.lerp(C.amber, kk); k = Math.max(k, 0.75 * kk);
      }
      k *= 1 - p.dim * 0.75 * (k > 0.4 ? 0.3 : 1);
      k *= 1 - p.pipes * 0.85;
      k *= 1 - unplug * 0.7;
      if (p.end > 0) { out.lerp(C.iris, p.end * 0.6); k = Math.max(k, 0.24 * p.end); }
      void i;
      return k;
    }, p.gs);

    /* the proof path (mint), the probe that dead-ends, the asked-for path with 0 rows */
    if (proof) {
      const n = proof.g.index ? proof.g.index.count : 0;
      const draw = Math.max(p.pay, p.end);
      proof.g.setDrawRange(0, Math.floor((n * draw) / 6) * 6);
      proofMat.opacity = 0.95 * (1 - unplug * 0.85) * (1 - p.pipes * 0.7) * (1 - p.branch * 0.6) * (1 - p.people * 0.4);
      if (p.pay > 0 && p.pay < 1) { proof.curve.getPointAt(Math.min(0.999, p.pay), tmpB); main.glow.addV(tmpB, C.mint, 1, 0.55 * p.gs); }
    }
    if (probe) {
      const n = probe.g.index ? probe.g.index.count : 0;
      probe.g.setDrawRange(0, Math.floor((n * p.rec) / 6) * 6);
      probeMat.opacity = 0.85 * (1 - p.recOut * 0.8) * (p.rec > 0 ? 1 : 0) * (p.pipes > 0 ? 1 - p.pipes : 1);
      if (p.rec > 0 && p.rec < 1) { probe.curve.getPointAt(Math.min(0.999, p.rec), tmpB); main.glow.addV(tmpB, C.white, 0.9, 0.45 * p.gs); }
    }
    askMat.opacity = 0.8 * p.recOut * (1 - p.pipes) * (1 - p.branch) * (1 - p.people) * (1 - p.model) * (1 - unplug) * (1 - p.end);
    ask.visible = askMat.opacity > 0.01;

    /* ripple rings: one per BFS hop */
    const sPos = main.pos[at(symptom)] ?? tmpB.set(0, 0, 0);
    rings.forEach((r, k) => {
      const x = p.bfs - k;
      const m = r.material as THREE.MeshBasicMaterial;
      if (x <= 0 || p.blast <= 0) { r.visible = false; return; }
      r.visible = true;
      r.position.copy(sPos);
      r.quaternion.copy(cam.quaternion);
      r.scale.setScalar(0.25 + x * 1.15);
      m.opacity = p.blast * 0.55 * Math.max(0, 1 - x / 2.2);
    });

    /* pipes: radius = capacity; liquid particles carry flow along the gate's two paths */
    pipes.visible = p.pipes > 0.01;
    if (pipes.visible) {
      pipeEdges.forEach((ei, j) => {
        const e = edges[ei];
        const r = p.pipes * (0.006 + 0.045 * e.cap);
        pipes.setMatrixAt(j, orient(main.pos[e.a], main.pos[e.b], r, m4));
        tmpC.copy(PIPE);
        if (ei === ePay) tmpC.lerp(C.mint, p.flow);
        if (ei === eEmail) tmpC.copy(C.svc).lerp(C.ember, Math.max(p.flow * 0.5, p.emailOut));
        pipes.setColorAt(j, tmpC.multiplyScalar(1 - unplug * 0.6));
      });
      pipes.instanceMatrix.needsUpdate = true;
      pipes.instanceColor!.needsUpdate = true;
      const run = (ei: number, n: number, speed: number, c: THREE.Color, k: number, sz: number) => {
        if (ei < 0) return;
        const e = edges[ei];
        for (let j = 0; j < n; j++) {
          const f = (t * speed + j / n) % 1;
          tmpB.lerpVectors(main.pos[e.a], main.pos[e.b], f);
          main.glow.addV(tmpB, c, k * Math.sin(Math.PI * f), sz * p.gs);
        }
      };
      run(ePay, 11, 0.55, C.mint, p.flow * 0.9, 0.42);
      run(eEmail, 1, 0.18, C.ember, p.flow * 0.8 * (1 - p.emailOut * 0.6), 0.2);
      run(edgeIdx("D-pay-417", payChain[1] ?? ""), 6, 0.55, C.mint, p.flow * 0.6, 0.3);
    }

    /* people: the recorded who-fixes ranking orbits the failing component; the MSF tree draws */
    people.visible = p.people > 0.01;
    treeLines.visible = people.visible;
    if (people.visible) {
      pIds.forEach((id, i) => {
        const k = smooth((p.people - (i / pIds.length) * 0.5) / 0.5);
        const rank = ranked.indexOf(id);
        pPos[i].lerpVectors(center, pHome[i], k);
        if (rank === 0) pPos[i].z += 0.9 * p.rank;
        const sc = score.get(id) ?? 0;
        const rad = (0.08 + 0.07 * (sc / maxS)) * k * (rank === 0 ? 1 + 0.45 * p.rank : 1);
        people.setMatrixAt(i, m4.compose(pPos[i], q.identity(), tmpA.set(rad, rad, rad)));
        tmpC.copy(C.person);
        if (rank === 0) tmpC.lerp(C.mint, p.rank);
        else if (rank > 0) tmpC.lerp(C.iris, p.rank * 0.5);
        else tmpC.lerp(C.svc, 0.5);
        people.setColorAt(i, tmpC);
        const g = rank === 0 ? 0.35 + 0.65 * p.rank : rank > 0 ? (0.15 + 0.4 * (sc / maxS)) * (0.5 + 0.5 * p.rank) : 0.12;
        main.glow.addV(pPos[i], rank === 0 ? tmpD.copy(C.iris).lerp(C.mint, p.rank) : C.iris, g * k, rad * 9 * p.gs);
      });
      people.instanceMatrix.needsUpdate = true;
      people.instanceColor!.needsUpdate = true;
      // spokes to the failing component, then the escalation tree, strongest tie first
      let o = 0;
      pIds.forEach((id, i) => {
        if (!score.has(id)) return;
        seg(treePos, o * 6, center.x, center.y, center.z, pPos[i].x, pPos[i].y, pPos[i].z);
        const k = 0.12 * p.people * (1 - p.tree * 0.5);
        treeCol.fill(0, o * 6, o * 6 + 6);
        for (let j = 0; j < 2; j++) { treeCol[o * 6 + j * 3] = C.iris.r * k; treeCol[o * 6 + j * 3 + 1] = C.iris.g * k; treeCol[o * 6 + j * 3 + 2] = C.iris.b * k; }
        o++;
      });
      d.tree.forEach((e, j) => {
        const a = pPos[pIds.indexOf(e.from)], b = pPos[pIds.indexOf(e.to)];
        if (!a || !b) return;
        const k = clamp01(p.tree * d.tree.length - j);
        tmpB.lerpVectors(a, b, k);
        seg(treePos, o * 6, a.x, a.y, a.z, tmpB.x, tmpB.y, tmpB.z);
        const c = tmpD.copy(C.gold).lerp(C.iris, j / Math.max(1, d.tree.length));
        const kk = k > 0 ? 0.9 : 0;
        for (let jj = 0; jj < 2; jj++) { treeCol[o * 6 + jj * 3] = c.r * kk; treeCol[o * 6 + jj * 3 + 1] = c.g * kk; treeCol[o * 6 + jj * 3 + 2] = c.b * kk; }
        if (k > 0 && k < 1) main.glow.addV(tmpB, C.gold, 0.9, 0.3 * p.gs);
        o++;
      });
      treeGeo.setDrawRange(0, o * 2);
      (treeGeo.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      (treeGeo.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
    }

    /* the model points; read-only beams rise from the plate; one golden write; a second read-only re-read */
    const om = orb.material as THREE.MeshBasicMaterial;
    om.opacity = 0.75 * p.model;
    orb.visible = p.model > 0.01;
    orb.rotation.set(t * 0.3, t * 0.45, 0);
    if (p.model > 0) main.glow.addV(orbPos, C.iris, 0.5 * p.model, 2.2 * p.gs);
    const dp = main.pos[at("D-pay-417")];
    if (dp) {
      tmpB.lerpVectors(orbPos, dp, 0.92 * p.point);
      (pointGeo.getAttribute("position") as THREE.BufferAttribute).setXYZ(1, tmpB.x, tmpB.y, tmpB.z);
      (pointGeo.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      pointer.computeLineDistances();
      pointMat.opacity = 0.85 * p.point * p.model;
      pointer.visible = pointMat.opacity > 0.01;
    }
    beams.visible = p.reads > 0.01 || p.reread > 0.01;
    if (beams.visible) {
      readIds.forEach((id, j) => {
        const top = main.pos[at(id)];
        const yb = plateY + 0.15;
        const k = p.reads;
        tmpB.set(top.x, yb + (top.y - yb) * k, top.z);
        seg(beamPos, j * 6, top.x, yb, top.z, tmpB.x, tmpB.y, tmpB.z);
        const kk = 0.55 * Math.max(p.reads * (1 - unplug), 0);
        for (let jj = 0; jj < 2; jj++) { beamCol[j * 6 + jj * 3] = C.iris.r * kk; beamCol[j * 6 + jj * 3 + 1] = C.iris.g * kk; beamCol[j * 6 + jj * 3 + 2] = C.iris.b * kk; }
        for (let s = 0; s < 4; s++) {
          const f = (t * 0.6 + s / 4 + j * 0.13) % 1;
          main.glow.add(top.x, yb + (top.y - yb) * f * k, top.z, C.iris, 0.7 * p.reads, 0.22 * p.gs);
        }
      });
      // the re-read: a mint beam into the written incident
      const n = readIds.length;
      const yb = plateY + 0.15;
      tmpB.set(wb.pm.x, yb + (wb.pm.y - yb) * p.reread, wb.pm.z);
      seg(beamPos, n * 6, wb.pm.x, yb, wb.pm.z, tmpB.x, tmpB.y, tmpB.z);
      const kr = 0.8 * p.reread;
      for (let jj = 0; jj < 2; jj++) { beamCol[n * 6 + jj * 3] = C.mint.r * kr; beamCol[n * 6 + jj * 3 + 1] = C.mint.g * kr; beamCol[n * 6 + jj * 3 + 2] = C.mint.b * kr; }
      beamGeo.setDrawRange(0, (n + 1) * 2);
      (beamGeo.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      (beamGeo.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
    }
    goldMat.opacity = p.write > 0 ? 0.95 * (1 - unplug * 0.7) * (1 - p.end * 0.3) : 0;
    wbTubes.forEach((g) => { const n = g.index ? g.index.count : 0; g.setDrawRange(0, Math.floor((n * p.write) / 6) * 6); });
    wbNodes.visible = p.write > 0.01;
    wbList.forEach((pt, i) => {
      const k = smooth((p.write - i * 0.15) / 0.4);
      const s = 0.1 * k;
      wbNodes.setMatrixAt(i, m4.compose(pt, q.identity(), tmpA.set(s, s, s)));
      main.glow.addV(pt, C.gold, 0.5 * k * (1 - unplug), 0.9 * p.gs);
    });
    wbNodes.instanceMatrix.needsUpdate = true;
    main.glow.commit();

    /* the GRAPH.COPY branch: same graph, iris-tinted; the cut snaps, the protected side goes quiet */
    if (branch.group.visible) {
      branch.mat.opacity = 0.92 * br;
      branch.glow.reset();
      for (let i = 0; i < ids.length; i++) {
        branch.pos[i].copy(home[i]);
        nodeS[i] = 1;
        const id = ids[i];
        nodeC[i].copy(kind[i] === "data" ? C.data : C.svc).lerp(C.iris, 0.25);
        nodeGC[i].copy(C.iris);
        nodeG[i] = 0.16 * br;
        if (quiet.has(id)) { nodeC[i].lerp(C.amber, 0.6 * (1 - p.contained)).lerp(C.mint, 0.5 * p.contained); nodeGC[i].copy(C.amber).lerp(C.mint, p.contained); nodeG[i] = 0.4 * br; }
        if (protect.has(id)) { nodeGC[i].copy(C.mint); nodeG[i] = (0.3 + 0.6 * p.contained) * br; }
        if (id === d.failing) { nodeC[i].copy(C.ember); nodeGC[i].copy(C.ember); nodeG[i] = 0.8 * br; }
      }
      drawLayer(branch, (e, i, out) => {
        out.copy(e.changed ? C.iris : e.data ? C.sky : C.white).lerp(C.iris, 0.35);
        if (cutSet.has(i)) { out.copy(C.ember); return 0.9 * br * (1 - p.cut); }
        if (quiet.has(ids[e.b]) && (quiet.has(ids[e.a]) || ids[e.a] === d.failing)) { out.lerp(C.amber, 1 - p.contained); return 0.38 * br * (1 - 0.5 * p.contained); }
        return 0.18 * br;
      }, p.gs);
      // the snapped halves retract toward their ends, with a spark
      cutList.forEach((ei, j) => {
        const e = edges[ei];
        const a = branch.pos[e.a], b = branch.pos[e.b];
        const gap = 0.5 - 0.42 * smooth(p.cut * 1.2);
        const show = p.cut > 0.02 ? 1 : 0;
        tmpB.lerpVectors(a, b, gap);
        stubs.setMatrixAt(j * 2, orient(a, tmpB, 0.028 * show, m4));
        sv.lerpVectors(a, b, 1 - gap);
        stubs.setMatrixAt(j * 2 + 1, orient(sv, b, 0.028 * show, m4));
        const spark = Math.sin(Math.PI * clamp01(p.cut * 1.3)) * br;
        tmpB.lerpVectors(a, b, 0.5);
        branch.glow.addV(tmpB, C.ember, spark, 0.9 * p.gs);
      });
      stubs.instanceMatrix.needsUpdate = true;
      (stubs.material as THREE.MeshBasicMaterial).opacity = br * (1 - p.contained * 0.5);
      branch.glow.commit();
    }

    /* world: sources, streams, tenant boxes, the plate, the matrices */
    worldGlow.reset();
    srcMat.opacity = p.sources;
    tiles.forEach((m, i) => {
      m.visible = p.sources > 0.01;
      m.rotation.set(0, Math.sin(t * 0.4 + i) * 0.25, 0);
      worldGlow.addV(m.position, i === 1 ? C.white : i === 2 ? C.sky : i === 4 ? C.person : i === 3 ? C.gold : C.ember, 0.5 * p.sources, 1.6);
    });
    if (p.stream > 0.01) {
      for (let sI = 0; sI < 5; sI++) {
        for (let j = 0; j < 9; j++) {
          const f = (t * 0.32 + j / 9 + sI * 0.07) % 1;
          // a fixed target per particle: a node this source feeds (docs and people feed nodes not drawn here)
          const list = srcTargets[sI];
          const tgt = home[list[(j * 5 + sI) % list.length]];
          tmpB.lerpVectors(SRC[sI], tgt, f);
          tmpB.y += Math.sin(Math.PI * f) * 0.6;
          worldGlow.addV(tmpB, sI === 2 ? C.sky : sI === 4 ? C.person : sI === 3 ? C.gold : sI === 0 ? C.ember : C.white, 0.55 * p.stream * Math.sin(Math.PI * f), 0.26);
        }
      }
    }
    (box.material as THREE.MeshBasicMaterial).opacity = 0.45 * p.tenant * (1 - p.matrix);
    others.forEach((b, i) => {
      (b.material as THREE.MeshBasicMaterial).opacity = 0.35 * p.others;
      if (p.others > 0.01) for (const dot of otherDots[i]) worldGlow.addV(dot, i === 1 ? C.iris : C.white, 0.4 * p.others, 0.22);
    });
    const py = plateY - 2.6 * smooth(unplug);
    plate.position.y = py;
    plateEdge.position.y = py;
    (plate.material as THREE.MeshBasicMaterial).opacity = p.plate * (1 - unplug);
    (plateEdge.material as THREE.MeshBasicMaterial).opacity = 0.55 * p.plate * (1 - unplug) * (1 + 0.6 * p.reads);
    plate.visible = plateEdge.visible = p.plate * (1 - unplug) > 0.01;
    if (plate.visible) for (let i = 0; i < 7; i++) worldGlow.add(-5.4 + i * 1.8, py + 0.1, 2.55, C.iris, 0.18 * p.plate * (1 - unplug) * (1 + p.reads), 1.6);

    // matrices: the deck peels out of the graph; cells fly from their edge to (row, column)
    deck.visible = p.matrix > 0.01;
    cellMesh.visible = deck.visible;
    if (deck.visible) {
      const m = smooth(p.matrix);
      deck.position.set(2.7 - 2.2 * (1 - m), 0.15, -0.3);
      deck.rotation.set(-0.06, -0.5 - 0.7 * (1 - m), 0);
      deck.scale.setScalar(0.6 + 0.4 * m);
      deck.updateMatrixWorld();
      planeMats.forEach((pm, i) => { pm.opacity = (i % 2 === 0 ? 0.88 : 0.75) * smooth(p.matrix * 1.6 - Math.floor(i / 2) * 0.3); });
      gridMats.forEach((gm, i) => { gm.opacity = 0.07 * smooth(p.matrix * 1.6 - i * 0.3); });
      ghostMat.opacity = 0.32 * m;
      (rowBar.material as THREE.MeshBasicMaterial).opacity = 0.22 * p.row;
      cells.forEach((c, i) => {
        const k = smooth((p.cells - c.delay) / 0.38);
        tmpA.copy(c.local).applyMatrix4(deck.matrixWorld);
        const from = c.from();
        sv.lerpVectors(from, tmpA, k);
        sv.z += Math.sin(Math.PI * k) * 0.8;
        const s = k >= 0.98 ? 1 : 0.0001;
        m4.compose(sv, deck.quaternion, tmpB.set(s * deck.scale.x, s * deck.scale.x, 1));
        cellMesh.setMatrixAt(i, m4);
        const hot = c.layer === 0 && c.r === symRow ? p.row : 0;
        cellMesh.setColorAt(i, tmpC.copy(c.hex).lerp(C.white, hot * 0.6).multiplyScalar(m));
        if (k > 0.01 && k < 0.98) worldGlow.addV(sv, c.hex, 0.8 * m, 0.3);
        if (hot > 0 && k >= 0.98) worldGlow.addV(sv, C.mint, 0.7 * hot, 0.42);
      });
      cellMesh.instanceMatrix.needsUpdate = true;
      cellMesh.instanceColor!.needsUpdate = true;
    }
    worldGlow.commit();

    /* fixed overlays of the last scene */
    ui.at("ov:a4", -1, -1, smooth((unplug - 0.45) / 0.5) * (1 - p.end));
    ui.at("ov:ladder", -1, -1, p.ladder);
    ui.at("ov:end", -1, -1, p.end);

    /* labels */
    const L = (key: string, pnt: THREE.Vector3, space: THREE.Object3D | null, o: number, dy = 0) => label(ui, key, pnt, space, o, cam, size, dy);
    SRC.forEach((s, i) => L(`src:${i}`, tmpC2.copy(s).setY(s.y - 0.62), null, p.sources));
    L("box:main", tmpC2.set(-5.6, 3.62, 2.3), null, p.tenant * (1 - p.matrix) * (p.sources > 0.02 || p.others > 0.02 ? 1 : 0));
    others.forEach((b, i) => L(`box:${i}`, tmpC2.copy(b.position).setY(b.position.y - 1.1), null, p.others));
    L("plate", tmpC2.set(-6.2, py - 0.15, 2.6), null, p.plate * (1 - unplug) * (p.reads > 0 || p.sources > 0 ? 1 : 0));
    for (let k = 0; k < 3; k++) L(`mat:${k}`, tmpC2.copy(matLabelAt[k]), deck, deck.visible ? smooth(p.matrix * 1.6 - k * 0.3) : 0, k === 0 ? 2 : -34);
    L("mat:more", tmpC2.copy(moreLabelAt), deck, deck.visible ? p.matrix * (1 - p.row) : 0, -6);
    L("mat:row", tmpC2.copy(rowLabelAt), deck, deck.visible ? p.row : 0);
    const node = (id: string) => main.pos[at(id)] ?? tmpC2.set(0, 0, 0);
    const nl = (key: string, id: string, o: number) => { if (at(id) < 0) return; L(key, tmpC2.copy(node(id)).setY(node(id).y - radius[at(id)] - 0.12), main.group, o, 4); };
    const sceneBlast = p.blast * (1 - p.suspects);
    nl("n:checkout", symptom, Math.max(p.alert * (1 - p.pipes) * (1 - p.branch) * (1 - p.people) * (1 - p.model), 0));
    nl("n:frontend", "frontend", sceneBlast * clamp01(p.bfs - 0.6));
    nl("n:frontend-proxy", "frontend-proxy", sceneBlast * clamp01(p.bfs - 1.6));
    const sus = p.suspects * (1 - p.branch) * (1 - p.people) * (1 - p.model) * (1 - unplug) * (1 - p.end);
    nl("n:D-rec-12", "D-rec-12", sus * (1 - p.recOut));
    nl("n:D-email-88", "D-email-88", sus * (1 - p.pipes));
    nl("n:D-pay-417", "D-pay-417", sus);
    nl("n:payment", d.failing, Math.max(p.people, sus * p.payOk * (1 - p.pipes)));
    nl("n:email", "email", p.pipes * (1 - p.branch) * (1 - p.people));
    const rec = node("D-rec-12");
    L("rec0", tmpC2.copy(rec).lerp(node(symptom), 0.45).setY(rec.y + 0.35), main.group, p.recOut * (1 - p.pipes) * (1 - p.branch) * (1 - p.people) * (1 - p.model) * (1 - unplug) * (1 - p.end));
    const pmid = node(payChain[1] ?? symptom);
    L("pay1", tmpC2.copy(pmid).lerp(node(symptom), 0.5).setY(pmid.y - 0.45), main.group, p.payOk * (1 - p.pipes) * (1 - p.branch) * (1 - p.people) * (1 - p.model) * (1 - unplug) * (1 - p.end));
    L("gauge", tmpC2.copy(node(emailChain[1] ?? "email")).lerp(node(symptom), 0.5).setY(node("email").y + 0.55), main.group, p.flow * (1 - p.branch) * (1 - p.people));
    L("full", tmpC2.copy(node(payChain[1] ?? symptom)).lerp(node(symptom), 0.55).setY(node(symptom).y - 0.9), main.group, p.flow * (1 - p.branch) * (1 - p.people));
    L("live", tmpC2.set(0, 3.7, 0), main.group, br);
    L("branch", tmpC2.set(0, 3.7, 0), branch.group, br);
    if (cutList.length) L("cut", tmpC2.copy(branch.pos[edges[cutList[0]].a]).setY(branch.pos[edges[cutList[0]].a].y - 0.75), branch.group, br * p.cut * (1 - p.contained * 0.4));
    L("verdict", tmpC2.set(1.5, -4.0, 0), branch.group, br * p.contained);
    ranked.slice(0, 3).forEach((id, i) => { const j = pIds.indexOf(id); if (j >= 0) L(`p:${i}`, tmpC2.copy(pPos[j]).setY(pPos[j].y - 0.28), main.group, p.people * (i === 0 ? 1 : p.rank) * (1 - p.tree * 0.0)); });
    L("tree", tmpC2.copy(center).setY(center.y + 2.6), main.group, p.tree > 0 ? smooth(p.tree * 3) * p.people : 0);
    L("model", tmpC2.copy(orbPos).setY(orbPos.y + 0.65), main.group, p.model * (1 - unplug));
    L("ro", tmpC2.set(node(symptom).x + 0.4, plateY + 0.9, node(symptom).z + 0.4), main.group, p.reads * (1 - unplug));
    L("write", tmpC2.copy(wb.inc).setX(wb.inc.x + 0.2).setY(wb.inc.y + 0.32), main.group, smooth(p.write * 2) * (1 - p.reread * 0.0) * (1 - unplug) * (1 - p.end));
    L("reread", tmpC2.copy(wb.pm).setY(wb.pm.y - 0.35), main.group, p.reread * (1 - unplug) * (1 - p.end));
  }

  return {
    root,
    tick,
    everything: () => {
      for (const g of [main.glow, branch.glow, worldGlow]) g.prime();
      const hidden: THREE.Object3D[] = [];
      root.traverse((o) => { if (!o.visible) { hidden.push(o); o.visible = true; } });
      return () => hidden.forEach((o) => { o.visible = false; });
    },
    dispose: () => { disposables.forEach((x) => x.dispose()); },
  };
}
