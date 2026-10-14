#!/usr/bin/env node
/**
 * npm run evals:summary: copies the eval numbers the UI shows into public/evals/summary.json.
 *
 * Source: ../evals/results/latest.json (written by `make results`; never hand-edited). Only keys
 * under the prefixes below are copied, verbatim (no rounding, no derived numbers):
 *   s7.*      cross-tenant isolation tests (top-bar isolation badge)
 *   memory.*  cold vs warm recall on the same scenario (Memory tab)
 *   s8.*      families and the first derived runbook (Memory tab)
 * The file is static, so the live UI and the GitHub Pages replay site read the same numbers, and
 * `run` names the eval run they came from. Re-run after `make results`. Fails loudly (exit 1)
 * when latest.json is missing or has none of these keys.
 */
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = path.resolve(frontend, "..", "evals", "results", "latest.json");
const out = path.join(frontend, "public", "evals", "summary.json");
const PREFIXES = ["s7.", "memory.", "s8.", "deep.fresh.all.", "arm.A4.", "arm.A3.", "ctx.busy30.b1000.", "ctx.busy0.", "gate_bench_heldout.", "mutation.", "mismatch.all."];

let latest;
try {
  latest = JSON.parse(await readFile(src, "utf8"));
} catch (e) {
  console.error(`evals:summary FAILED: cannot read ${path.relative(frontend, src)}: ${e.message} (run make eval && make results)`);
  process.exit(1);
}
const values = Object.fromEntries(
  Object.entries(latest)
    .filter(([k]) => PREFIXES.some((p) => k.startsWith(p)))
    .sort(([a], [b]) => a.localeCompare(b)),
);
if (Object.keys(values).length === 0) {
  console.error(`evals:summary FAILED: ${path.relative(frontend, src)} has no ${PREFIXES.join(" / ")} keys`);
  process.exit(1);
}
const mtime = (await stat(src)).mtime.toISOString();
const doc = { source: "evals/results/latest.json", run: typeof latest.run === "string" ? latest.run : null, generated_from_mtime: mtime, values };
await mkdir(path.dirname(out), { recursive: true });
await writeFile(out, JSON.stringify(doc, null, 2) + "\n");
console.log(`evals:summary: ${Object.keys(values).length} values from ${doc.source} (${doc.run ?? "run unknown"}) → public/evals/summary.json`);
