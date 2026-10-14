// Generates public/brand/contours.svg: our own topographic contour art for page backgrounds. A smooth height field
// (a few broad hills and a low ridge, deterministic) is offset across a diagonal fault, so every contour line breaks
// where it crosses it: a fault line on a map. Run: node scripts/gen-contours.mjs (re-run only to change the art).
import { writeFileSync, mkdirSync } from "node:fs";
import { contours } from "d3-contour";
import { geoPath } from "d3-geo";

const W = 1600, H = 1000, S = 6;          // drawing size, grid step (px per cell)
const nx = Math.ceil(W / S) + 1, ny = Math.ceil(H / S) + 1;
const hills = [
  [380, 300, 260, 1.0], [1150, 260, 300, 0.85], [820, 720, 340, 0.9], [1420, 820, 220, 0.6], [180, 820, 200, 0.55],
  [640, 120, 180, 0.45],
];
// the fault: a line from (1000, -50) to (560, 1050); points to its right are shifted along it and dropped
const fx0 = 1000, fy0 = -50, fx1 = 560, fy1 = 1050;
const fdx = fx1 - fx0, fdy = fy1 - fy0, flen = Math.hypot(fdx, fdy);
const side = (x, y) => ((x - fx0) * fdy - (y - fy0) * fdx) / flen;   // signed distance to the fault
function base(x, y) {
  let h = 0;
  for (const [cx, cy, r, a] of hills) h += a * Math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r));
  h += 0.18 * Math.sin(x / 210 + y / 330) + 0.12 * Math.cos(x / 120 - y / 260) + 0.06 * Math.sin((x + y) / 75);
  return h;
}
const values = new Float64Array(nx * ny);
for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
  const x = i * S, y = j * S;
  const d = side(x, y);
  // across the fault the ground has slipped: sampled from 70 px along the fault and dropped a little
  const k = d > 0 ? 1 : 0;
  values[j * nx + i] = base(x + k * 70 * fdx / flen, y + k * 70 * fdy / flen) - k * 0.07;
}
const levels = Array.from({ length: 26 }, (_, k) => -0.25 + k * 0.06);
const rings = contours().size([nx, ny]).thresholds(levels)(values);
const path = geoPath(null);
const round = (d) => d.replace(/(\d+\.\d)\d+/g, "$1");
const scale = `scale(${S})`;
let body = "";
rings.forEach((r, k) => {
  const d = path(r);
  if (!d) return;
  const major = k % 5 === 0;   // every fifth line is an index contour, as on survey maps
  body += `<path d="${round(d)}" stroke-width="${((major ? 1.3 : 0.75) / S).toFixed(3)}" opacity="${major ? 0.9 : 0.55}"/>`;
});
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice">` +
  `<g fill="none" stroke="#fff" stroke-linejoin="round" transform="${scale}" vector-effect="non-scaling-stroke">${body}</g>` +
  `<path d="M ${fx0} ${fy0} L ${fx1} ${fy1}" stroke="#fff" stroke-width="1.2" stroke-dasharray="2 7" opacity="0.6" fill="none"/></svg>`;
mkdirSync("public/brand", { recursive: true });
writeFileSync("public/brand/contours.svg", svg);
console.log(`contours.svg: ${rings.length} levels, ${(svg.length / 1024).toFixed(0)} KiB`);
