"use client";

import { Component, useCallback, useEffect, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { BASE_PATH } from "@/lib/site";

/**
 * The hero's 3D piece: a solid, glossy black cube of 27 blocks. Click it (or press
 * Enter/Space) and it splits: nine blocks fly out into the S1 incident graph and the gate's decision plays (checkout
 * alerts; D-rec-12 has no path, G2; D-email-88's edge carries 0.02, G5; a light draws D-pay-417 → payment → checkout;
 * the cause glows, the symptom turns mint); the other eighteen drift out as the rest of the tenant graph. Click again
 * and it closes. The ids and checks are the hero scenario's (public/replay/s1-hero); the layout is illustrative.
 * Leans toward the pointer; drag to turn it. Reduced motion: no tweening, a still frame. No WebGL: nothing.
 */
type V3 = [number, number, number];
const NODES: Record<string, { p: V3; s: number }> = {
  rec: { p: [-2.35, 1.3, 0.3], s: 0.58 },
  email: { p: [-2.55, 0.05, -0.55], s: 0.58 },
  pay: { p: [-2.2, -1.25, 0.55], s: 0.62 },
  srec: { p: [-0.05, 1.35, -0.4], s: 0.7 },
  semail: { p: [0.15, 0.2, 0.75], s: 0.7 },
  spay: { p: [-0.1, -1.1, -0.15], s: 0.74 },
  cart: { p: [0.45, -0.25, -1.3], s: 0.6 },
  front: { p: [2.25, 0.95, 0.15], s: 0.78 },
  check: { p: [2.1, -0.65, -0.3], s: 0.92 },
};
const ROLES = Object.keys(NODES);
/** Each role's real node: the three suspect deploys and the incident's services (ids from the S1 scenario). */
const ROLE_ID: Record<string, string> = {
  rec: "D-rec-12", email: "D-email-88", pay: "D-pay-417", srec: "recommendation", semail: "email", spay: "payment",
  cart: "cart", front: "frontend", check: "checkout",
};
const SUSPECT_OF: Record<string, string> = { "D-rec-12": "recommendation", "D-email-88": "email", "D-pay-417": "payment" };   // CHANGED
/** The recorded hero run's failure-flow graph (public/replay/s1-hero/graph.json, written from FalkorDB). */
export type GraphData = { nodes: { id: string; label: string; betweenness?: number | null }[]; edges: { source: string; target: string; cap?: number; domain?: string }[] };
const EDGES: [string, string][] = [
  ["rec", "srec"], ["email", "semail"], ["pay", "spay"], ["srec", "front"], ["semail", "check"],
  ["spay", "check"], ["check", "front"], ["cart", "spay"], ["cart", "check"],
];
const PROOF = ["pay", "spay", "check"];
const LOOP = 8.5;   // seconds of the decision, replayed while open
const BLOCK = 0.76;   // a cube block's edge
const GAP = 0.8;      // block spacing in the closed cube (thin seams)
const EMBER = new THREE.Color("#ff6b2c");
const MINT = new THREE.Color("#5ef0b4");
const smooth = (x: number) => x * x * x * (x * (x * 6 - 15) + 10);
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Decision timeline while open: 0 alert · 1.3 G2 · 2.2 G5 · 3.0–4.8 the proof draws · 4.8 proved · 7.6–8.5 reset. */
function phase(t: number) {
  const k = t % LOOP;
  const draw = clamp01((k - 3.0) / 1.8);
  const fade = k > 7.6 ? 1 - (k - 7.6) / 0.9 : 1;
  return { draw: draw * fade, g2: k > 1.3 && k < 7.9, g5: k > 2.2 && k < 7.9, proved: k > 4.8 && k < 7.9, fade };
}
const FINAL = { draw: 1, g2: true, g5: true, proved: true, fade: 1 };

/** Deterministic pseudo-random numbers, so the scatter is the same on every visit. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function Environment() {
  const get = useThree((st) => st.get);
  useEffect(() => {
    const { gl, scene } = get();
    const pm = new THREE.PMREMGenerator(gl);
    const env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 0.85;
    return () => { scene.environment = null; env.dispose(); pm.dispose(); };
  }, [get]);
  return null;
}

type Place = (k: string, x: number, y: number, show: boolean, proved: boolean, text?: string) => void;
type Control = { open: boolean; openedAt: number; hover: boolean; drag: { x: number; y: number } };   // hover: the pointer is over the canvas
type Piece = { mesh: THREE.Mesh; from: THREE.Vector3; to: THREE.Vector3; scaleTo: number; delay: number; spin: THREE.Vector3; role?: string; id?: string; info?: string };
type World = {
  root: THREE.Group;
  pieces: Piece[];
  byRole: Record<string, Piece>;
  mats: Record<string, THREE.MeshPhysicalMaterial>;
  dustMat: THREE.MeshPhysicalMaterial;
  edgeMat: THREE.MeshStandardMaterial;
  faintMat: THREE.MeshBasicMaterial;
  proof: THREE.TubeGeometry;
  proofMat: THREE.MeshBasicMaterial;
  curve: THREE.CatmullRomCurve3;
  pulse: THREE.Mesh;
  e: number;   // 0 = closed cube, 1 = split into the graph
  h: number;   // 0..1, the pointer is over the closed cube (its seams widen a little: it can open)
  ray: THREE.Raycaster;
};

/**
 * The scene, built once, outside React's render (three.js objects are mutated every frame). With the recorded graph,
 * the 27 blocks are real nodes: the 3 suspect deploys and the 24 non-table nodes of the incident's failure-flow graph
 * (its 8 warehouse tables are left out); the edges are its recorded edges. Without it, the same shapes, unnamed.
 */
function buildWorld(data: GraphData | null): { world: World; dispose: () => void } {
  const root = new THREE.Group();
  const v = (k: string) => new THREE.Vector3(...NODES[k].p);
  const disposables: { dispose: () => void }[] = [];
  const keep = <T extends { dispose: () => void }>(x: T) => (disposables.push(x), x);
  const block = keep(new RoundedBoxGeometry(BLOCK, BLOCK, BLOCK, 3, 0.1));
  const glossy = () => keep(new THREE.MeshPhysicalMaterial({ color: "#0c0c0e", metalness: 0.5, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.16, emissive: "#000000" }));
  const dustMat = glossy();
  const mats: World["mats"] = {};
  for (const k of ROLES) mats[k] = glossy();

  const roleOf = new Map(Object.entries(ROLE_ID).map(([r, id]) => [id, r]));
  const graphNodes = (data?.nodes ?? []).filter((n) => n.label !== "Table");
  const others = graphNodes.filter((n) => !roleOf.has(n.id));
  const real = !!data && graphNodes.length + 3 === 27 && others.length === 18;
  const maxB = Math.max(1, ...graphNodes.map((n) => n.betweenness ?? 0));

  // 27 cells; nine of them carry the incident's roles (spread through the cube so the split reads as an explosion)
  const cells: THREE.Vector3[] = [];
  for (const x of [-1, 0, 1]) for (const y of [-1, 0, 1]) for (const z of [-1, 0, 1]) cells.push(new THREE.Vector3(x, y, z).multiplyScalar(GAP));
  const roleCell = [6, 2, 0, 16, 13, 9, 11, 24, 18];   // rec, email, pay, srec, semail, spay, cart, front, check
  const rand = rng(417);
  const pieces: Piece[] = [];
  const byRole: Record<string, Piece> = {};
  const at = new Map<string, THREE.Vector3>();   // node id -> its place in the open graph
  let o = 0;
  cells.forEach((from, i) => {
    const r = roleCell.indexOf(i);
    const role = r >= 0 ? ROLES[r] : undefined;
    let to: THREE.Vector3;
    let scaleTo: number;
    let id: string | undefined;
    let info: string | undefined;
    if (role) {
      to = v(role);
      scaleTo = NODES[role].s / BLOCK;
      id = ROLE_ID[role];
      const n = graphNodes.find((x) => x.id === id);
      info = id.startsWith("D-") ? `${id} · deploy · suspect` : `${id} · ${n?.label ?? "Service"}${n?.betweenness != null ? ` · betweenness ${n.betweenness}` : ""}`;
    } else {
      // the rest of the incident's graph: a loose shell around it, sized by betweenness (from FalkorDB)
      const n = real ? others[o++] : undefined;
      const dir = from.clone().add(new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5)).normalize();
      to = dir.multiplyScalar(3.2 + rand() * 1.3).multiply(new THREE.Vector3(1.15, 0.8, 0.9));
      const b = n?.betweenness ?? 0;
      scaleTo = n ? 0.28 + 0.34 * Math.log1p(b) / Math.log1p(maxB) : 0.26 + rand() * 0.16;
      id = n?.id;
      info = n ? `${n.id} · ${n.label}${n.betweenness != null ? ` · betweenness ${n.betweenness}` : ""}` : undefined;
    }
    if (id) at.set(id, to);
    const mesh = new THREE.Mesh(block, role ? mats[role] : dustMat);
    mesh.position.copy(from);
    root.add(mesh);
    const p: Piece = { mesh, from, to, scaleTo, delay: rand() * 0.22, spin: new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).multiplyScalar(5), role, id, info };
    pieces.push(p);
    if (role) byRole[role] = p;
  });

  // edges appear once the cube has split: the recorded ones (bright inside the incident, faint around it) and the
  // suspects' CHANGED links; without data, the illustrative incident edges
  const edgeMat = keep(new THREE.MeshStandardMaterial({ color: "#2e3035", metalness: 0.85, roughness: 0.35, transparent: true, opacity: 0 }));
  const faintMat = keep(new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0 }));
  const tube = (a: THREE.Vector3, b: THREE.Vector3, r: number, m: THREE.Material) => root.add(new THREE.Mesh(keep(new THREE.TubeGeometry(new THREE.LineCurve3(a, b), 1, r, 6, false)), m));
  if (real) {
    const links: [string, string][] = [...Object.entries(SUSPECT_OF), ...data!.edges.map((e) => [e.source, e.target] as [string, string])];
    for (const [a, b] of links) {
      const pa = at.get(a), pb = at.get(b);
      if (!pa || !pb) continue;   // an edge to a table
      if (roleOf.has(a) && roleOf.has(b)) tube(pa, pb, 0.016, edgeMat);
      else tube(pa, pb, 0.006, faintMat);
    }
  } else {
    for (const [a, b] of EDGES) tube(v(a), v(b), 0.016, edgeMat);
  }
  const curve = new THREE.CatmullRomCurve3(PROOF.map(v), false, "centripetal");
  const proof = keep(new THREE.TubeGeometry(curve, 96, 0.04, 10, false));
  const proofMat = keep(new THREE.MeshBasicMaterial({ color: "#ffffff", toneMapped: false, transparent: true }));
  root.add(new THREE.Mesh(proof, proofMat));
  const pulse = new THREE.Mesh(keep(new THREE.SphereGeometry(0.09, 20, 20)), keep(new THREE.MeshBasicMaterial({ color: "#ffffff", toneMapped: false })));
  root.add(pulse);
  return {
    world: { root, pieces, byRole, mats, dustMat, edgeMat, faintMat, proof, proofMat, curve, pulse, e: 0, h: 0, ray: new THREE.Raycaster() },
    dispose: () => disposables.forEach((d) => d.dispose()),
  };
}

const tmp = new THREE.Vector3();
const arc = new THREE.Vector3();

/** One frame: split progress, each block's flight, pose, the decision, and where each label goes. */
function tick(w: World, st: { clock: THREE.Clock; pointer: THREE.Vector2; camera: THREE.Camera; size: { width: number; height: number } },
              dt: number, still: boolean, c: Control, place: Place) {
  const t = st.clock.elapsedTime;
  const target = c.open ? 1 : 0;
  w.e = still ? target : w.e + (target - w.e) * (1 - Math.exp(-dt * 2.6));
  if (Math.abs(target - w.e) < 0.001) w.e = target;
  w.h += ((!c.open && c.hover && !still ? 1 : 0) - w.h) * (1 - Math.exp(-dt * 8));
  const breathe = 1 + 0.06 * w.h;

  for (const p of w.pieces) {
    const k = smooth(clamp01((w.e - p.delay) / (1 - 0.22)));
    p.mesh.position.lerpVectors(p.from, p.to, k);
    // a little outward arc mid-flight, and a tumble that settles
    arc.copy(p.from).normalize().multiplyScalar(Math.sin(Math.PI * k) * 0.9);
    p.mesh.position.add(arc);
    if (k === 0) p.mesh.position.multiplyScalar(breathe);
    const tumble = Math.sin(Math.PI * k);
    p.mesh.rotation.set(p.spin.x * tumble, p.spin.y * tumble + (k === 1 && !still ? Math.sin(t * 0.6 + p.delay * 20) * 0.12 : 0), p.spin.z * tumble);
    p.mesh.scale.setScalar(THREE.MathUtils.lerp(1, p.scaleTo, k));
  }

  // the open graph is wider than the cube: step back a little as it splits
  w.root.scale.setScalar(THREE.MathUtils.lerp(1, 0.84, smooth(w.e)));

  // pose: the closed cube turns slowly to show three faces; the open graph sways; both lean toward the pointer
  const g = w.root;
  const yaw = (still ? -0.6 : c.open ? Math.sin(t * 0.22) * 0.32 - 0.25 : t * 0.25 - 0.6) + st.pointer.x * 0.22 + c.drag.x;
  const pitch = (still ? 0.35 : c.open ? Math.sin(t * 0.17) * 0.06 + 0.1 : 0.42) - st.pointer.y * 0.12 + c.drag.y;
  if (still) { g.rotation.set(pitch, yaw, 0); }
  else {
    // unwrap the closed cube's running yaw so opening does not spin back through several turns
    const ry = g.rotation.y;
    const want = c.open ? yaw + Math.round((ry - yaw) / (Math.PI * 2)) * Math.PI * 2 : yaw;
    g.rotation.y += (want - ry) * 0.06;
    g.rotation.x += (pitch - g.rotation.x) * 0.06;
  }

  // the decision plays once the cube is open
  const vis = smooth(clamp01((w.e - 0.82) / 0.18));
  const ph = still ? (c.open ? FINAL : { draw: 0, g2: false, g5: false, proved: false, fade: 1 }) : c.open ? phase(t - c.openedAt) : { draw: 0, g2: false, g5: false, proved: false, fade: 1 };
  w.edgeMat.opacity = vis;
  w.faintMat.opacity = 0.06 * vis;
  const count = w.proof.index ? w.proof.index.count : 0;
  const draw = ph.draw * vis;
  w.proof.setDrawRange(0, Math.floor((count * draw) / 6) * 6);
  w.proofMat.opacity = 0.95 * ph.fade;
  w.pulse.visible = draw > 0 && draw < 1;
  w.curve.getPointAt(Math.min(0.999, draw), w.pulse.position);

  const n = w.mats;
  const alert = 0.5 + 0.5 * Math.sin(t * 5);
  n.check.emissive.copy(ph.proved ? MINT : EMBER);
  n.check.emissiveIntensity = vis * (ph.proved ? 0.28 : still ? 0.3 : 0.12 + 0.26 * alert);
  n.pay.emissive.copy(EMBER);
  n.pay.emissiveIntensity = ph.proved ? 0.32 * vis : 0;
  n.spay.emissive.set("#ffffff");
  n.spay.emissiveIntensity = draw > 0.45 ? 0.08 * ph.fade : 0;
  for (const k of ["rec", "email"] as const) {
    const out = k === "rec" ? ph.g2 : ph.g5;
    n[k].color.set(out ? "#050506" : "#0c0c0e");
    n[k].roughness = out ? 0.7 : 0.28;
  }
  w.dustMat.roughness = 0.28 + 0.35 * vis;   // the wider graph steps back once open

  const show: Record<string, boolean> = { rec: ph.g2, email: ph.g5, pay: ph.proved, check: true };
  for (const k of Object.keys(show)) {
    w.byRole[k].mesh.getWorldPosition(tmp);
    tmp.y -= NODES[k].s * 0.75;
    tmp.project(st.camera);
    place(k, (tmp.x * 0.5 + 0.5) * st.size.width, (-tmp.y * 0.5 + 0.5) * st.size.height, show[k] && vis > 0.95, ph.proved);
  }

  // open: the block under the pointer names itself (real id, kind, betweenness)
  let named: Piece | undefined;
  if (vis > 0.95 && c.hover && !still) {
    w.ray.setFromCamera(st.pointer, st.camera);
    const hit = w.ray.intersectObjects(w.pieces.map((p) => p.mesh), false)[0];
    named = hit ? w.pieces.find((p) => p.mesh === hit.object && p.info) : undefined;
  }
  if (named) {
    named.mesh.getWorldPosition(tmp);
    tmp.y += named.mesh.scale.y * BLOCK * 0.7;
    tmp.project(st.camera);
    place("hover", (tmp.x * 0.5 + 0.5) * st.size.width, (-tmp.y * 0.5 + 0.5) * st.size.height - 26, true, false, named.info);
  } else place("hover", 0, 0, false, false);
}

function Scene({ still, control, place, data }: { still: boolean; control: React.RefObject<Control>; place: Place; data: GraphData | null }) {
  const group = useRef<THREE.Group>(null);
  const world = useRef<World | null>(null);
  const invalidate = useThree((st) => st.invalidate);
  useEffect(() => {
    const { world: w, dispose } = buildWorld(data);
    const host = group.current;
    host?.add(w.root);
    world.current = w;
    invalidate();
    return () => { host?.remove(w.root); dispose(); world.current = null; };
  }, [invalidate, data]);
  useFrame((st, dt) => { if (world.current) tick(world.current, st, Math.min(dt, 0.05), still, control.current, place); });
  return <group ref={group} />;
}

/**
 * Keeps the page smooth on any GPU: after a warm-up, if frames run slower than ~30 fps it drops the pixel ratio to 1;
 * if they are still slow, it asks for low-power mode (render on demand: on pointer moves and during the split).
 */
function PerfWatch({ onLow }: { onLow: () => void }) {
  const acc = useRef({ n: 0, sum: 0, warm: 0, stepped: false, done: false });
  useFrame((st, dt) => {
    const a = acc.current;
    if (a.done) return;
    if (a.warm < 30) { a.warm++; return; }   // the first frames include shader compiles and the environment map
    a.n++; a.sum += dt;
    if (a.n < 60) return;
    const avg = a.sum / a.n;
    a.n = 0; a.sum = 0;
    if (avg <= 1 / 30) return;
    if (!a.stepped && st.viewport.dpr > 1) { st.setDpr(1); a.stepped = true; a.warm = 15; return; }
    a.done = true;
    onLow();
  });
  return null;
}

class Boundary extends Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? null : this.props.children; }
}

function webgl(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export default function HeroGraph3D() {
  const reduced = useReducedMotion();
  const wrap = useRef<HTMLDivElement>(null);
  const control = useRef<Control>({ open: false, openedAt: 0, hover: false, drag: { x: 0, y: 0 } });
  const from = useRef<{ x: number; y: number; dx: number; dy: number; moved: boolean } | null>(null);
  const labels = useRef<Record<string, HTMLDivElement | null>>({});
  const clock = useRef<(() => number) | null>(null);
  const [ok] = useState(webgl);
  const [visible, setVisible] = useState(true);
  const [scrolling, setScrolling] = useState(false);   // pause rendering while the page scrolls: scrolling stays smooth
  const [low, setLow] = useState(false);               // low-power: render on demand
  const [busy, setBusy] = useState<number>(0);          // ms to keep rendering through the split / close animation
  const invalidate = useRef<(() => void) | null>(null);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const on = () => {
      setScrolling(true);
      clearTimeout(t);
      t = setTimeout(() => setScrolling(false), 180);
    };
    const main = document.getElementById("main");
    main?.addEventListener("scroll", on, { passive: true });
    window.addEventListener("scroll", on, { passive: true });
    return () => { main?.removeEventListener("scroll", on); window.removeEventListener("scroll", on); clearTimeout(t); };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const t = setTimeout(() => setBusy(0), busy);
    return () => clearTimeout(t);
  }, [busy]);
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<GraphData | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`${BASE_PATH}/replay/s1-hero/graph.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then((g: GraphData | null) => { if (live && g?.nodes && g?.edges) setData(g); })
      .catch(() => { /* the cube still works, unnamed */ });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.01 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // labels are positioned from the frame loop (projected block positions), outside React's render
  const place = useCallback<Place>((k, x, y, show, proved, text) => {
    const el = labels.current[k];
    if (!el) return;
    el.style.transform = `translate(-50%, 0) translate(${x}px, ${y}px)`;
    el.style.opacity = show ? "1" : "0";
    if (k === "check") el.dataset.state = proved ? "proved" : "alert";
    if (text !== undefined && el.textContent !== text) el.textContent = text;
  }, []);

  const toggle = () => {
    const c = control.current;
    c.open = !c.open;
    c.openedAt = clock.current ? clock.current() + 0.9 : 0;   // the decision starts as the blocks land
    setOpen(c.open);
    setBusy(c.open ? 10_000 : 3_000);   // low-power mode still animates the split and the decision
  };

  if (!ok) return null;
  // the floating labels repeat what the accessible name says: hidden from assistive tech
  const label = (k: string, text: string, tone: string) => (
    <div ref={(el) => { labels.current[k] = el; }} style={{ opacity: 0 }} aria-hidden
         className={"pointer-events-none absolute left-0 top-0 whitespace-nowrap rounded-[5px] border bg-black/70 px-1.5 py-0.5 font-mono text-[10.5px] backdrop-blur-sm transition-opacity duration-500 " + tone}>
      {text}
    </div>
  );
  return (
    <div ref={wrap} role="button" tabIndex={0} aria-pressed={open} data-cursor="ring" data-power={low ? "low" : "full"}
         aria-label={open
           ? "Click to close. The hero incident as a graph: D-rec-12 has no path to checkout (G2), D-email-88's edge carries 0.02 of the impact (G5), and the proof path D-pay-417 → payment → checkout lights up. Hover a block for its name. Press to close it back into a cube."
           : "Click the cube: a black cube of 27 blocks, the hero incident's nodes. Press to split it into the hero incident's graph and watch the gate decide."}
         className="relative h-full w-full cursor-pointer touch-pan-y select-none rounded-3xl outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
         onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
         onPointerEnter={() => { control.current.hover = true; invalidate.current?.(); }}
         onPointerLeave={() => { control.current.hover = false; }}
         onPointerDown={(e) => {
           e.currentTarget.setPointerCapture(e.pointerId);
           const d = control.current.drag;
           from.current = { x: e.clientX, y: e.clientY, dx: d.x, dy: d.y, moved: false };
         }}
         onPointerMove={(e) => {
           if (low) invalidate.current?.();
           const f = from.current;
           if (!f) return;
           if (Math.hypot(e.clientX - f.x, e.clientY - f.y) > 6) f.moved = true;
           control.current.drag.x = f.dx + (e.clientX - f.x) * 0.006;
           control.current.drag.y = THREE.MathUtils.clamp(f.dy + (e.clientY - f.y) * 0.004, -0.5, 0.5);
         }}
         onPointerUp={() => { if (from.current && !from.current.moved) toggle(); from.current = null; }}
         onPointerCancel={() => { from.current = null; }}>
      <Boundary>
        {/* the open graph fades out towards the edges instead of being cut off by the canvas */}
        <div className="absolute inset-0 [mask-image:radial-gradient(ellipse_70%_75%_at_50%_50%,#000_55%,transparent_100%)]">
        <Canvas dpr={[1, 1.5]} camera={{ position: [0, 0.3, 8.4], fov: 36 }}
                frameloop={reduced ? "demand" : !visible || scrolling ? "never" : low && !busy ? "demand" : "always"}
                gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
                onCreated={(st) => { clock.current = () => st.clock.elapsedTime; invalidate.current = st.invalidate; }}>
          <Environment />
          <ambientLight intensity={0.15} />
          <directionalLight position={[4, 6, 5]} intensity={1.6} />
          <directionalLight position={[-6, 1, -5]} intensity={0.35} color="#c9d0ff" />
          <Scene still={reduced} control={control} place={place} data={data} />
          {reduced ? null : <PerfWatch onLow={() => setLow(true)} />}
          {reduced ? <Invalidate dep={open} /> : null}
        </Canvas>
        </div>
      </Boundary>
      {label("rec", "G2 · no path to checkout", "border-white/15 text-zinc-400")}
      {label("email", "G5 · carries 0.02", "border-white/15 text-zinc-400")}
      {label("pay", "D-pay-417 · proved", "border-[#ff6b2c]/50 text-[#ffb08a]")}
      <div ref={(el) => { labels.current.check = el; }} style={{ opacity: 0 }} aria-hidden
           className="pointer-events-none absolute left-0 top-0 whitespace-nowrap rounded-[5px] border border-white/15 bg-black/70 px-1.5 py-0.5 font-mono text-[10.5px] text-zinc-300 backdrop-blur-sm transition-opacity duration-500 data-[state=proved]:border-[#5ef0b4]/50 data-[state=proved]:text-[#a9f7d6]">
        checkout
      </div>
      {label("hover", "", "border-white/25 text-zinc-100")}
      <p className="pointer-events-none absolute inset-x-0 bottom-3 flex items-center justify-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-zinc-500" aria-hidden>
        <span className={"size-1.5 rounded-full " + (open ? "bg-zinc-500" : "animate-pulse bg-white")} />
        {open ? "Click to close" : "Click the cube"}
      </p>
    </div>
  );
}

/** Reduced motion renders on demand: one fresh frame whenever the cube opens or closes. */
function Invalidate({ dep }: { dep: boolean }) {
  const invalidate = useThree((st) => st.invalidate);
  useEffect(() => { invalidate(); }, [dep, invalidate]);
  return null;
}
