#!/usr/bin/env node
/**
 * Builds the static replay bundles under public/replay/<name>/ from the recorded runs in
 * ../examples/<name>/ (exports generated from the graph), so /replay/<name> works with
 * the backend off (GitHub Pages).
 *
 * Copied verbatim: events.jsonl, gate_runs.json, tool_calls.json, hypotheses.json,
 * report.json (+ plan.json, blast.json, incident.json, graph.json, report.md when an export has
 * them). The export's own manifest.json is embedded as `recorded` in public/…/manifest.json.
 *
 * Snapshotted from the live API (fails loudly if it is down, unless --no-live):
 *   templates.json  every Cypher template the run cites (GET /api/templates/{id}), so the
 *                   replay's Cypher panel shows the exact query text;
 *   graph.json      the tenant's failure-flow graph (GET /api/graph?tenant=…), labelled as a
 *                   tenant snapshot, only when the export has no graph.json of its own.
 *
 * Usage: node scripts/export-replay.mjs [--no-live] [--api http://localhost:8400] [name…]
 */
import { copyFile, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const examples = path.resolve(frontend, "..", "examples");
const outRoot = path.join(frontend, "public", "replay");

const args = process.argv.slice(2);
const noLive = args.includes("--no-live");
const apiIdx = args.indexOf("--api");
const API = (apiIdx >= 0 ? args[apiIdx + 1] : process.env.FAULTLINE_API_URL ?? "http://localhost:8400").replace(/\/$/, "");
const names = args.filter((a, i) => !a.startsWith("--") && args[i - 1] !== "--api");
const RUNS = names.length ? names : ["s1-hero", "s2-data-incident"];
const TENANT = process.env.FAULTLINE_TENANT ?? "acme";

const REQUIRED = ["events.jsonl", "gate_runs.json", "tool_calls.json", "hypotheses.json", "report.json"];
const OPTIONAL = ["plan.json", "blast.json", "incident.json", "graph.json", "report.md"];
// examples/<run>/manifest.json (written by scripts/record_demo.py) is kept as `recorded` in ours.
const RECORDED_MANIFEST = "manifest.json";

const exists = async (p) => !!(await stat(p).catch(() => null));

async function getJson(url) {
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new Error(`API unreachable at ${API} (${e.message}). Start the backend or pass --no-live.`);
  }
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status} ${await res.text()}`);
  return res.json();
}

function templateIds(events, gateRuns, toolCalls, report, plan) {
  const ids = new Set(["Q-CTX-1"]);
  if (plan) {
    for (const k of ["containment_cut", "whatif", "futures", "who_fixes", "bus_factor", "escalation_tree"]) if (plan[k]?.template) ids.add(plan[k].template);
    if (plan.memory) ["Q-MEM-4", "Q-MEM-5"].forEach((t) => ids.add(t));
  }
  for (const e of events) if (e.template) ids.add(e.template);
  for (const t of toolCalls) if (t.template) ids.add(t.template);
  for (const g of gateRuns) for (const c of g.checks ?? []) if (c.template) ids.add(c.template);
  for (const ev of report.evidence ?? []) if (ev.template) ids.add(ev.template);
  // a tool that ran several templates records them joined ("Q-GATE-3+Q-GATE-MULT", a repeat as "Q-X#2"): snapshot each
  return [...new Set([...ids].flatMap((id) => id.split("+")).map((id) => id.split("#")[0]))].sort();
}

const index = [];
for (const name of RUNS) {
  const src = path.join(examples, name);
  const dst = path.join(outRoot, name);
  for (const f of REQUIRED) {
    if (!(await exists(path.join(src, f)))) throw new Error(`${src}/${f} is missing: not a complete recorded run`);
  }
  await mkdir(dst, { recursive: true });
  const files = [];
  for (const f of [...REQUIRED, ...OPTIONAL]) {
    if (await exists(path.join(src, f))) {
      await copyFile(path.join(src, f), path.join(dst, f));
      files.push(f);
    }
  }
  const events = (await readFile(path.join(src, "events.jsonl"), "utf8"))
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
  const gateRuns = JSON.parse(await readFile(path.join(src, "gate_runs.json"), "utf8"));
  const toolCalls = JSON.parse(await readFile(path.join(src, "tool_calls.json"), "utf8"));
  const report = JSON.parse(await readFile(path.join(src, "report.json"), "utf8"));
  const plan = (await exists(path.join(src, "plan.json"))) ? JSON.parse(await readFile(path.join(src, "plan.json"), "utf8")) : null;

  const snapshot = { api: API, at: new Date().toISOString(), templates: false, graph: null };
  if (!noLive) {
    const templates = {};
    // a recording can cite a template the catalogue has since renamed: keep the text the previous export snapshotted
    // (the query the run actually ran), and say so; only a template nobody has is left out, loudly
    const prevPath = path.join(dst, "templates.json");
    const previous = (await exists(prevPath)) ? JSON.parse(await readFile(prevPath, "utf8")) : {};
    for (const id of templateIds(events, gateRuns, toolCalls, report, plan)) {
      try {
        templates[id] = await getJson(`${API}/api/templates/${encodeURIComponent(id)}`);
      } catch (e) {
        if (!/HTTP 404/.test(e.message)) throw e;
        if (previous[id]) {
          templates[id] = previous[id];
          console.warn(`replay/${name}: ${id} is no longer in the catalogue; kept the text snapshotted when it was recorded`);
        } else {
          console.warn(`replay/${name}: ${id} is no longer in the catalogue and no earlier snapshot has it; left out`);
        }
      }
    }
    await writeFile(path.join(dst, "templates.json"), JSON.stringify(templates, null, 2) + "\n");
    files.push("templates.json");
    snapshot.templates = true;
    if (!files.includes("graph.json")) {
      const g = await getJson(`${API}/api/graph?tenant=${encodeURIComponent(TENANT)}`);
      await writeFile(path.join(dst, "graph.json"), JSON.stringify(g, null, 2) + "\n");
      files.push("graph.json");
      snapshot.graph = `tenant snapshot: GET /api/graph?tenant=${TENANT} (${g.graph})`;
    } else {
      snapshot.graph = "graph.json from the recorded export";
    }
  }
  const recorded = (await exists(path.join(src, RECORDED_MANIFEST)))
    ? JSON.parse(await readFile(path.join(src, RECORDED_MANIFEST), "utf8"))
    : null;
  const manifest = {
    name,
    recorded,
    incident: report.incident_id,
    outcome: report.outcome,
    cause: report.cause_id,
    events: events.length,
    files,
    snapshot,
  };
  await writeFile(path.join(dst, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  index.push(manifest);
  console.log(`replay/${name}: ${files.length} files, ${events.length} events${snapshot.templates ? "" : " (no live snapshot)"}`);
}
await writeFile(path.join(outRoot, "index.json"), JSON.stringify(index, null, 2) + "\n");
console.log(`wrote ${path.relative(frontend, path.join(outRoot, "index.json"))}`);
