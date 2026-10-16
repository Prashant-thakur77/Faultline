import { BLEND_S, blend, newPose, ramp, target, type Pose } from "./timeline";

export type PlayState = "playing" | "paused" | "done";

/**
 * The explainer's own clock: advanced only by rendered frames (dt capped), so a hidden tab or an off-screen stage
 * never makes it jump, and auto-play is deterministic in content. React hears about scene and play-state changes
 * (a few times a minute); progress and pose are read by the frame loop and written straight to the DOM.
 */
export class ExplainerClock {
  scene = 0;
  t = 0;
  state: PlayState = "paused";
  readonly from: Pose = newPose();
  readonly to: Pose = newPose();
  readonly pose: Pose = newPose();
  /** frame times (ms) per scene, for the recorder's perf check */
  frames: number[][];
  private sinceSwitch = BLEND_S;
  /** timeline seconds per wall second (the recorder stretches a scene to its narration line) */
  private rate = 1;
  /** true: stop at the end of the current scene instead of moving on (the recorder chooses each next scene) */
  private hold = false;
  private listeners = new Set<() => void>();
  onProgress: ((scene: number, t: number) => void) | null = null;
  /** renderer counters for the recorder (programs compiled, draw calls of the last frame) */
  gpu: { programs: number; calls: number; triangles: number; geometries: number } = { programs: 0, calls: 0, triangles: 0, geometries: 0 };

  constructor(readonly durations: number[], public narrow = false) {
    this.frames = durations.map(() => []);
    target(0, 0, narrow, this.pose);
    Object.assign(this.from, this.pose);
  }

  /** Portrait framing (the camera fits a narrower box). */
  setNarrow(n: boolean) { this.narrow = n; }
  /** Called every frame with (scene, seconds into it), to paint progress straight into the DOM. */
  setProgress(cb: ((scene: number, t: number) => void) | null) { this.onProgress = cb; }
  setGpu(programs: number, calls: number, triangles: number, geometries: number) {
    this.gpu.programs = programs; this.gpu.calls = calls; this.gpu.triangles = triangles; this.gpu.geometries = geometries;
  }
  resetFrames() { this.frames = this.durations.map(() => []); }

  subscribe(cb: () => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }
  private emit() { this.listeners.forEach((cb) => cb()); }

  /** Jump to a scene (0-based), blending from what is on screen now. */
  go(n: number) {
    const s = Math.max(0, Math.min(this.durations.length - 1, Math.round(n)));
    Object.assign(this.from, this.pose);
    this.scene = s;
    this.t = 0;
    this.sinceSwitch = 0;
    if (this.state === "done") this.state = "paused";
    this.emit();
    this.onProgress?.(this.scene, this.t);
  }

  /** Jump to an exact moment, with no blend: the same frame every time (recorder, reduced motion). */
  seek(n: number, t: number) {
    this.scene = Math.max(0, Math.min(this.durations.length - 1, Math.round(n)));
    this.t = Math.max(0, Math.min(this.durations[this.scene], t));
    this.sinceSwitch = BLEND_S;
    target(this.scene, this.t, this.narrow, this.pose);
    Object.assign(this.from, this.pose);
    this.emit();
    this.onProgress?.(this.scene, this.t);
  }

  /** Play scene n (0-based) once, over `seconds` of wall time, then hold its last frame. */
  playScene(n: number, seconds: number) {
    this.go(n);
    this.rate = seconds > 0 ? this.durations[this.scene] / seconds : 1;
    this.hold = true;
    this.state = "playing";
    this.emit();
  }

  play() {
    this.rate = 1;
    this.hold = false;
    if (this.state === "done") { this.seek(0, 0); }
    this.state = "playing";
    this.emit();
  }
  pause() {
    if (this.state !== "playing") return;
    this.state = "paused";
    this.emit();
  }

  /** One rendered frame: advance (if playing), auto-advance scenes, compute the pose. */
  step(dt: number): Pose {
    if (this.state === "playing") {
      this.t += dt * this.rate;
      if (this.t >= this.durations[this.scene]) {
        if (this.scene < this.durations.length - 1 && !this.hold) {
          const over = this.t - this.durations[this.scene];
          this.go(this.scene + 1);
          this.t = over;
          this.sinceSwitch = over;
        } else {
          this.t = this.durations[this.scene];
          this.state = "done";
          this.emit();
        }
      }
    }
    this.sinceSwitch += dt;
    target(this.scene, this.t, this.narrow, this.to);
    blend(this.from, this.to, ramp(this.sinceSwitch, 0, BLEND_S), this.pose);
    this.onProgress?.(this.scene, this.t);
    return this.pose;
  }
}
