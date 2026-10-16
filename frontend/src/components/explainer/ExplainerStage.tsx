"use client";

import { Component, useEffect, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import type { ExplainerClock } from "./clock";
import type { ExplainerData } from "./data";
import { buildWorld, type Ui, type World } from "./world";

/**
 * The one Canvas. The world is built once per data load, outside React; the frame loop steps the explainer's own
 * clock (dt capped at 50 ms, so a stall never skips a beat), applies the pose and positions the HTML labels.
 * `still`: reduced motion, render on demand, one frame per scene. `running` false: off screen, no frames at all.
 */
export type StageProps = {
  data: ExplainerData;
  clock: ExplainerClock;
  still: boolean;
  running: boolean;
  ui: Ui;
  /** the scene, so a still frame re-renders when it changes */
  scene: number;
  onFail: (why: string) => void;
};

function Environment() {
  const get = useThree((st) => st.get);
  useEffect(() => {
    const { gl, scene } = get();
    const pm = new THREE.PMREMGenerator(gl);
    const env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 0.7;
    return () => { scene.environment = null; env.dispose(); pm.dispose(); };
  }, [get]);
  return null;
}

function Scene({ data, clock, still, ui, scene }: Omit<StageProps, "running" | "onFail">) {
  const host = useRef<THREE.Group>(null);
  const world = useRef<World | null>(null);
  const time = useRef(0);
  const last = useRef(0);
  const invalidate = useThree((st) => st.invalidate);
  const warm = useRef(false);
  useEffect(() => {
    const w = buildWorld(data);
    const g = host.current;
    g?.add(w.root);
    world.current = w;
    warm.current = false;
    invalidate();
    return () => { g?.remove(w.root); w.dispose(); world.current = null; };
  }, [data, invalidate]);
  // a still frame per scene change
  useEffect(() => { if (still) invalidate(); }, [still, scene, invalidate]);
  useFrame((st, delta) => {
    const w = world.current;
    if (!w) return;
    if (!warm.current) {
      // first frame (the environment map exists by now): one warm-up render with every part shown, hidden ones
      // too, so shaders link and buffers upload here and no scene pays for it mid-animation
      warm.current = true;
      const undo = w.everything();
      try { st.gl.render(st.scene, st.camera); } finally { undo(); }
    }
    // frame time for the recorder's perf check (wall clock between rendered frames)
    const now = performance.now();
    if (last.current && !still) {
      const f = clock.frames[clock.scene];
      if (f.length < 4000) f.push(now - last.current);
    }
    last.current = now;
    const dt = still ? 0 : Math.min(delta, 0.05);
    time.current += dt;
    const cam = st.camera as THREE.PerspectiveCamera;
    cam.userData.dpr = st.viewport.dpr;
    const narrow = st.size.width / Math.max(1, st.size.height) < 0.95;
    if (clock.narrow !== narrow) clock.setNarrow(narrow);
    const pose = clock.step(dt);
    w.tick(pose, time.current, cam, st.size, still, ui);
    const info = st.gl.info;
    clock.setGpu(info.programs?.length ?? 0, info.render.calls, info.render.triangles, info.memory.geometries);
  });
  return <group ref={host} />;
}

/** Keeps it smooth on a weaker GPU: after a warm-up, frames slower than ~50 fps drop the pixel ratio to 1. */
function PerfWatch() {
  const acc = useRef({ n: 0, sum: 0, warm: 0, done: false });
  useFrame((st, dt) => {
    const a = acc.current;
    if (a.done) return;
    if (a.warm < 40) { a.warm++; return; }
    a.n++; a.sum += dt;
    if (a.n < 90) return;
    const avg = a.sum / a.n;
    a.n = 0; a.sum = 0;
    if (avg > 1 / 50 && st.viewport.dpr > 1) { st.setDpr(1); a.done = true; }
  });
  return null;
}

class Boundary extends Component<{ children: React.ReactNode; onFail: (why: string) => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: unknown) { this.props.onFail(e instanceof Error ? e.message : String(e)); }
  render() { return this.state.failed ? null : this.props.children; }
}

export default function ExplainerStage(props: StageProps) {
  const { still, running, onFail } = props;
  return (
    <Boundary onFail={onFail}>
      <Canvas dpr={[1, 1.5]} camera={{ position: [0, 0.6, 16], fov: 34, near: 0.1, far: 120 }}
              frameloop={!running ? "never" : still ? "demand" : "always"}
              gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
              onCreated={({ gl }) => {
                gl.toneMapping = THREE.ACESFilmicToneMapping;
                gl.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); onFail("the WebGL context was lost"); });
              }}>
        <Environment />
        <ambientLight intensity={0.25} />
        <directionalLight position={[5, 8, 6]} intensity={1.5} />
        <directionalLight position={[-7, 2, -5]} intensity={0.45} color="#c9c3ff" />
        <Scene {...props} />
        {still ? null : <PerfWatch />}
      </Canvas>
    </Boundary>
  );
}
