/**
 * The explainer's choreography as a pure function: (scene, seconds into it) → a pose of named scalars that the
 * three.js world applies. No state and no randomness, so a recorder that seeks to (scene, t) always gets the same
 * frame. Scene changes blend from the pose the viewer last saw (see `blend`), so jumping around never pops.
 */

export const POSE_KEYS = [
  // camera: the box of the world to frame (centre, size), and a gentle orbit
  "cx", "cy", "w", "h", "yaw", "pitch",
  // the tenant graph's root transform, and how far its unlit parts recede
  "gx", "gy", "gs", "dim",
  // 1 · sources stream into one graph per tenant
  "assemble", "sources", "stream", "tenant", "others", "plate",
  // 2 · sparse matrices
  "matrix", "cells", "row",
  // 3 · blast radius
  "alert", "bfs", "blast",
  // 4 · suspects and paths
  "suspects", "rec", "recOut", "pay", "payOk",
  // 5 · pipes and max flow
  "pipes", "flow", "emailOut",
  // 6 · min-cut on a copy
  "branch", "cut", "contained",
  // 7 · who fixes it
  "people", "rank", "tree",
  // 8 · read-only, one write
  "model", "point", "reads", "write", "reread",
  // 9 · pull the plug
  "plug", "ladder", "end",
] as const;
export type PoseKey = (typeof POSE_KEYS)[number];
export type Pose = Record<PoseKey, number>;

export const newPose = (): Pose => Object.fromEntries(POSE_KEYS.map((k) => [k, 0])) as Pose;

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
/** 0 before a, 1 after b, a smooth (quintic) step between. */
export function ramp(t: number, a: number, b: number): number {
  const x = clamp01((t - a) / (b - a));
  return x * x * x * (x * (x * 6 - 15) + 10);
}

type Cam = { cx: number; cy: number; w: number; h: number; yaw: number; pitch: number };
/** Per scene: the framing on a wide screen, and on a narrow (portrait) one, where only the part that matters fits. */
const CAM: { wide: Cam; narrow: Cam }[] = [
  { wide: { cx: 0.2, cy: 0.1, w: 19.5, h: 9.6, yaw: 0.1, pitch: 0.08 }, narrow: { cx: -0.2, cy: 0, w: 11.5, h: 9, yaw: 0.1, pitch: 0.08 } },
  { wide: { cx: 0.2, cy: 0.1, w: 13.6, h: 8.2, yaw: -0.08, pitch: 0.06 }, narrow: { cx: 2.4, cy: 0.3, w: 6.2, h: 7, yaw: -0.08, pitch: 0.06 } },
  { wide: { cx: 2.0, cy: 0.5, w: 9.6, h: 6.2, yaw: -0.1, pitch: 0.1 }, narrow: { cx: 2.4, cy: 0.6, w: 6.4, h: 6, yaw: -0.1, pitch: 0.1 } },
  { wide: { cx: -1.9, cy: 0.45, w: 8.6, h: 5.8, yaw: 0.16, pitch: 0.08 }, narrow: { cx: -2.0, cy: 0.4, w: 6.6, h: 5.6, yaw: 0.16, pitch: 0.08 } },
  { wide: { cx: -1.4, cy: -0.2, w: 9.2, h: 6, yaw: 0.26, pitch: 0.16 }, narrow: { cx: -1.8, cy: -0.3, w: 6.8, h: 5.6, yaw: 0.24, pitch: 0.16 } },
  { wide: { cx: 0, cy: -0.1, w: 14.5, h: 6.6, yaw: 0, pitch: 0.12 }, narrow: { cx: 2.6, cy: -0.2, w: 7, h: 6, yaw: 0, pitch: 0.12 } },
  { wide: { cx: -2.3, cy: -0.5, w: 7.6, h: 5.4, yaw: -0.14, pitch: 0.1 }, narrow: { cx: -2.4, cy: -0.5, w: 6, h: 5.4, yaw: -0.14, pitch: 0.1 } },
  { wide: { cx: -0.8, cy: 0.1, w: 12.5, h: 10.4, yaw: 0.12, pitch: 0.16 }, narrow: { cx: -2.4, cy: 0, w: 7.4, h: 10, yaw: 0.12, pitch: 0.16 } },
  { wide: { cx: 0.2, cy: -0.6, w: 13.5, h: 9.6, yaw: 0, pitch: 0.18 }, narrow: { cx: 0.2, cy: -0.6, w: 11.5, h: 9.6, yaw: 0, pitch: 0.18 } },
];

/** The target pose for `scene` at `t` seconds into it (written into `o`, no allocation). */
export function target(scene: number, t: number, narrow: boolean, o: Pose): Pose {
  for (const k of POSE_KEYS) o[k] = 0;
  const c = CAM[Math.max(0, Math.min(CAM.length - 1, scene))][narrow ? "narrow" : "wide"];
  o.cx = c.cx; o.cy = c.cy; o.w = c.w; o.h = c.h; o.yaw = c.yaw; o.pitch = c.pitch;
  o.gs = 1; o.assemble = 1; o.plate = 1;
  // what earlier scenes settled stays settled
  if (scene > 3) { o.recOut = 1; o.payOk = 1; o.pay = 1; o.suspects = 1; }
  if (scene === 4) o.blast = 0.3;
  switch (scene) {
    case 0:
      o.plate = ramp(t, 0, 1.2);
      o.sources = ramp(t, 0, 0.8) * (1 - ramp(t, 5.8, 6.8));
      o.stream = ramp(t, 0.2, 0.8) * (1 - ramp(t, 5.0, 6.0));
      o.assemble = Math.min(1, Math.max(0, (t - 0.6) / 4.2));
      o.tenant = ramp(t, 3.4, 4.6);
      o.others = ramp(t, 4.4, 5.6);
      break;
    case 1:
      o.gx = -3.7 * ramp(t, 0, 1.4); o.gy = 0.2 * ramp(t, 0, 1.4); o.gs = 1 - 0.45 * ramp(t, 0, 1.4);
      o.dim = 0.55 * ramp(t, 0.6, 1.6);
      o.matrix = ramp(t, 0.5, 1.9);
      o.cells = Math.min(1, Math.max(0, (t - 1.6) / 2.8));
      o.row = ramp(t, 5.2, 6.0);
      break;
    case 2:
      o.alert = ramp(t, 0.1, 0.5);
      o.bfs = Math.max(0, Math.min(4, (t - 0.9) * 1.05));
      o.blast = 1;
      o.dim = 0.35 * ramp(t, 0.6, 1.4);
      break;
    case 3:
      o.alert = 1;
      o.blast = 0.3 * (1 - ramp(t, 0, 0.8));
      o.suspects = ramp(t, 0, 0.7);
      o.dim = 0.45 * ramp(t, 0, 0.8);
      o.rec = Math.min(1, Math.max(0, (t - 0.8) / 1.9));
      o.recOut = ramp(t, 2.9, 3.4);
      o.pay = Math.min(1, Math.max(0, (t - 4.2) / 1.9));
      o.payOk = ramp(t, 6.1, 6.7);
      break;
    case 4:
      o.alert = 1;
      o.dim = 0.5;
      o.pipes = ramp(t, 0.2, 1.5);
      o.flow = ramp(t, 1.3, 2.1);
      o.emailOut = ramp(t, 4.6, 5.2);
      break;
    case 5:
      o.gx = -3.3 * ramp(t, 0.2, 1.8); o.gs = 1 - 0.42 * ramp(t, 0.2, 1.8);
      o.branch = ramp(t, 0.5, 2.4);
      o.cut = ramp(t, 3.0, 3.7);
      o.contained = ramp(t, 4.3, 5.1);
      o.dim = 0.3;
      break;
    case 6:
      o.dim = 0.62 * ramp(t, 0, 0.8);
      o.people = ramp(t, 0.2, 1.4);
      o.rank = ramp(t, 1.7, 2.8);
      o.tree = Math.min(1, Math.max(0, (t - 3.2) / 1.8));
      break;
    case 7:
      o.dim = 0.4;
      o.model = ramp(t, 0.1, 0.9);
      o.point = ramp(t, 0.9, 1.8);
      o.reads = ramp(t, 1.8, 2.8);
      o.write = Math.min(1, Math.max(0, (t - 3.7) / 1.1));
      o.reread = ramp(t, 5.1, 5.8);
      break;
    case 8: {
      const back = ramp(t, 6.2, 7.2);
      o.plug = ramp(t, 0.3, 1.5) * (1 - back);
      o.ladder = ramp(t, 3.4, 4.0) * (1 - back);
      o.end = back;
      o.dim = 0.55 * back;
      o.model = 1 - ramp(t, 0, 0.6);
      o.pay = 1; o.payOk = 1; o.recOut = 1;
      break;
    }
  }
  return o;
}

/** How long a scene change blends from the last pose shown into the new scene's pose. */
export const BLEND_S = 0.9;

/** out = lerp(from, to, k) for every key. */
export function blend(from: Pose, to: Pose, k: number, out: Pose): Pose {
  for (const key of POSE_KEYS) out[key] = from[key] + (to[key] - from[key]) * k;
  return out;
}
