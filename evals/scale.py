"""Scale benchmark (M14 #5): the product's own code paths on deterministic synthetic tenants of ~1k / 10k / 50k services.

    make scale                                                          # all sizes → evals/results/scale.json
    PYTHONPATH=backend uv run python evals/scale.py --sizes 1k --profile-n 5   # the reduced variant

Per size (tenant `scale<k>`, graphs `golden_scale<k>` + one `eval_scale<k>_*` clean room; evals/scale_world.py):
1. seed: the globex generators per unit (seed 42 + u), namespaced, through graph/writes' UNWIND … MERGE batches;
   seed time (generation vs writes), node/edge counts, GRAPH.MEMORY USAGE (graph/engine_info.memory), GRAPH.COPY time.
2. a planted incident on the clean room: a true cause (a deploy on a component whose failure reaches the alerting
   symptom synchronously), designated distractors (no path → G2; best-effort path only → G5; a healthy synchronous
   path → G4 origin; a change on a GLOBAL platform hub, classified the same way) and ambient changes in proportion to
   the tenant (globex's deploy rate per unit, spread over the window). Expected verdicts are decided HERE from the world
   config before anything runs (grader side, like evals/gate_bench.py), never from the engine or the gate.
   Telemetry is written by the world (same model as sim/telemetry.py) for the components the investigation can
   measure; the product reads windows only by target id (indexed), so unmeasured components need none.
3. the product end to end: intake (Q-ALERT-1) → `run_incident` with the deterministic investigator (recall, blast,
   hypotheses, five specialists, the competitor sweep, the gate, containment, routing, plan): verdict + wall time; then
   `Gate.sweep()` alone, timed R times; `preflight.engine.run` on two PRs (the cause's component, the global hub).
4. PROFILE (graph/ro.profile, engine ms) and RO.run (wall ms, truncation flag) N times each for the hero templates
   (Q-GATE-1, Q-GATE-3, Q-GATE-MULT, Q-SUS-1/2, Q-BLAST-1/2, Q-CUT-1/2, Q-NEG-1) on the incident's own params and on
   the hub's, plus every other template the run executed; GRAPH.SLOWLOG of the clean room, mapped to template ids.
Graphs are deleted afterwards (`--keep` keeps them). A size whose estimated memory does not fit the machine is skipped
and reported as such, never silently shrunk.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import scale_world as W  # noqa: E402

OUT = ROOT / "evals" / "results" / "scale.json"
SEED = 20261013
EFFECT = 0.45                 # the cause's own error rate from onset − 2 min (gate bench draws 0.25–0.6)
PROFILE_N = 20                # runs per template instance (nearest-rank p95 = the 19th fastest of 20)
SWEEP_REPEAT = 3
DEFAULT_MB_PER_SERVICE = 0.05  # GRAPH.MEMORY USAGE per service measured at 10k (487 MB); refined by each smaller size run
MAX_INSTANCES = 6             # distinct param sets profiled per template (the hero and the hub first)
WORK_MIN = 11 * 60            # globex deploys happen between 08:00 and 19:00 (ingest/history day plan)
HERO = ("Q-GATE-1", "Q-GATE-3", "Q-GATE-MULT", "Q-SUS-1", "Q-SUS-2", "Q-BLAST-1", "Q-BLAST-2", "Q-CUT-1", "Q-CUT-2",
        "Q-NEG-1")
EXPECT_REASON = {"G2": "G2", "G5": "G5", "origin": "G4 origin"}
SCRATCH = {"Q-RANK-1", "Q-ORG-HARM", "Q-ORG-MSF"}   # run on a temporary projection graph (scripts/profile_templates.py)


# ------------------------------------------------------------------ pure helpers (unit-tested)
def pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q = 0.95 → the ceil(0.95·n)-th smallest), as scripts/profile_templates.py."""
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[max(0, math.ceil(q * len(xs)) - 1)], 3)


def stats(xs: list[float]) -> dict:
    return {"n": len(xs), "p50": round(statistics.median(xs), 3) if xs else None, "p95": pct(xs, 0.95),
            "max": round(max(xs), 3) if xs else None}


def ambient_count(units: int, window_min: int) -> int:
    """Changes expected in the window at globex's deploy rate (mean deploys/day per 200-service unit over the working
    day), in proportion to the tenant: ~0.4 per unit per 30 minutes."""
    per_day = statistics.fmean(W.load_spec()["history"]["deploys_per_day"])
    return round(per_day * units * window_min / WORK_MIN)


def growth(rows: list[tuple[int, float | None]]) -> list[dict]:
    """Between consecutive sizes: the size ratio, the time ratio and the empirical exponent log(t ratio)/log(n ratio)
    (1 = linear; > 1.3 is flagged superlinear, < 0.3 flat)."""
    out = []
    pts = [(n, t) for n, t in rows if t is not None and t > 0]
    for (n0, t0), (n1, t1) in zip(pts, pts[1:]):
        k = math.log(t1 / t0) / math.log(n1 / n0) if n1 != n0 else None
        out.append({"from": n0, "to": n1, "size_x": round(n1 / n0, 2), "time_x": round(t1 / t0, 2),
                    "exponent": round(k, 2) if k is not None else None,
                    "shape": None if k is None else ("superlinear" if k > 1.3 else "flat" if k < 0.3 else
                                                     "sublinear" if k < 0.8 else "linear")})
    return out


def analyse(sizes: dict) -> dict:
    """Which template dominates per size, how each hero template grows, and every truncation/timeout seen."""
    order = sorted((s for s in sizes.values() if s.get("templates")), key=lambda s: s["services"])
    out: dict = {"dominant": {}, "growth": {}, "truncated": [], "errors": [], "slowlog_top": {}}
    for s in order:
        hero = {tid: x for tid, x in s["templates"].items() if tid in HERO and x.get("engine_ms_p95") is not None}
        if hero:
            tid = max(hero, key=lambda t: hero[t]["engine_ms_p95"])
            out["dominant"][s["label"]] = {"template": tid, "instance": hero[tid].get("instance"),
                                           "engine_ms_p95": hero[tid]["engine_ms_p95"]}
        for tid, x in s["templates"].items():
            for inst in x.get("instances", []):
                if inst.get("truncated"):
                    out["truncated"].append({"size": s["label"], "template": tid, "instance": inst["instance"],
                                             "rows": inst.get("rows")})
                if inst.get("error"):
                    out["errors"].append({"size": s["label"], "template": tid, "instance": inst["instance"],
                                          "error": inst["error"]})
        for tc in s.get("run", {}).get("truncated_calls", []):
            out["truncated"].append({"size": s["label"], "template": tc["template"], "instance": f"run: {tc['tool']}",
                                     "rows": tc.get("rows")})
        if s.get("slowlog"):
            out["slowlog_top"][s["label"]] = s["slowlog"][0]
    for tid in sorted({t for s in order for t in s["templates"]} & set(HERO)):
        pts = [(s["services"], s["templates"].get(tid, {}).get("engine_ms_p50")) for s in order]
        out["growth"][tid] = {"engine_ms_p50": {s["label"]: s["templates"].get(tid, {}).get("engine_ms_p50") for s in order},
                              "steps": growth(pts)}
    sweep = [(s["services"], (s.get("sweep_ms") or {}).get("p50")) for s in order]
    out["growth"]["sweep"] = {"ms_p50": {s["label"]: (s.get("sweep_ms") or {}).get("p50") for s in order},
                              "steps": growth(sweep)}
    mem = [(s["services"], s.get("memory_mb")) for s in order]
    out["growth"]["memory"] = {"mb": {s["label"]: s.get("memory_mb") for s in order}, "steps": growth(mem)}
    seed = [(s["services"], (s.get("seed") or {}).get("seed_s")) for s in order]
    out["growth"]["seed"] = {"s": {s["label"]: (s.get("seed") or {}).get("seed_s") for s in order}, "steps": growth(seed)}
    return out


def grade(exp: dict, got: dict) -> dict:
    """gate_bench's rule (outcome, blamed change, each designated distractor eliminated by its gate), plus: no ambient
    change may be blamed (covered by the cause check) and the report lists any ambient change left a candidate."""
    why = []
    if got["outcome"] != exp["outcome"]:
        why.append(f"outcome {got['outcome']} (expected {exp['outcome']})")
    if got["cause"] != exp["cause"]:
        why.append(f"blamed {got['cause']} (expected {exp['cause']})")
    for d, gate in exp["eliminated"].items():
        v = got["sweep"].get(d, "absent")
        if not v.startswith(f"eliminated: {gate}"):
            why.append(f"{d}: {v[:140]} (expected eliminated by {gate})")
    left = sorted(d for d, v in got["sweep"].items() if d in exp.get("ambient", []) and v.startswith("candidate"))
    return {"correct": not why, "why": why, "ambient_left_candidate": left}


# ------------------------------------------------------------------ the planted incident (grader side, world config)
def _visible(w: W.World, c: str, t: str) -> bool:
    """A fault at c clearly shows at t: a synchronous direct call with call share ≥ 0.4 (gate bench's rule)."""
    return any(sv == c and cap >= 1.0 and share >= 0.4 for sv, cap, share in w.fail_in.get(t, ()))


def plan_incident(w: W.World, onset: int, window_min: int, seed: int = SEED) -> dict:
    rnd = random.Random(seed)
    U = w.units
    home = U // 2
    c, t = W.ns("card-gateway", home), W.ns("order-orchestrator", home)   # globex's card_gateway archetype
    if not _visible(w, c, t):
        roots = [(x, y) for x in w.components() if w.unit_of[x] == home
                 for y, cap in w.fail_out.get(x, ()) if _visible(w, x, y)]
        c, t = rnd.choice(sorted(roots))
    any_c = w.reach(c)
    comps = w.components()
    unit = [d for d in comps if w.unit_of[d] == home and d not in (c, t) and d not in any_c]
    reach = {d: w.reach(d) for d in unit}
    sync = {d: w.reach(d, sync_only=True) for d in unit}

    def classify(d: str, r: set[str], s: set[str]) -> str | None:
        if t not in r:
            return "G2"
        if t not in s:
            return "G5"
        return "origin"

    # opaque ids from their own seeded stream, one title template for every change and injects in id order (as in the
    # gate bench, review round 5, minor 9): no tie-break by id, title or ingest order can favour the cause. The grader
    # keeps the role of each id in `roles`; the draw stream above is untouched, so the planted incident is the same.
    ids_rnd = random.Random(seed ^ 0x5CA1E)

    def opaque() -> str:
        return "D-" + "".join(ids_rnd.choice("0123456789abcdef") for _ in range(10))

    cause_id = opaque()
    other = W.ns("recommender", (home + 1) % U) if U > 1 else None
    dist: dict[str, tuple[str, str]] = {}           # role → (target, expected category)
    if other and t not in w.reach(other):
        dist["g2"] = (other, "G2")
    weak = sorted(d for d in unit if t in reach[d] and t not in sync[d])
    if weak:
        dist["g5"] = (rnd.choice(weak), "G5")
    healthy = sorted(d for d in unit if t in sync[d])
    if healthy:
        dist["origin"] = (rnd.choice(healthy), "origin")
    hubs = sorted(W.platform_anchors(), key=lambda a: (-len(w.reach(a)), a))
    hub = next((h for h in hubs if h not in any_c and h not in (c, t)), None)
    if hub:
        dist["hub"] = (hub, classify(hub, w.reach(hub), w.reach(hub, sync_only=True)))
    roles = {"cause": cause_id} | {role: opaque() for role in sorted(dist)}
    dist = {roles[role]: v for role, v in dist.items()}
    # ambient changes stay out of the cause's own dependency cone: an EARLIER change there is a legitimate unresolved
    # alternative root (G3 "earlier upstream" withholds confidence by design; the gate bench covers that case), so the
    # expected verdict would not be unambiguous. The first 1k trial hit exactly this (DECISIONS 2026-10-13, scale bench).
    taken = {c, t} | any_c | {x for x, _ in dist.values()} | set(w.upstream(c, 8))
    k = ambient_count(U, window_min)
    pool = [d for d in comps if d not in taken]
    ambient = {opaque(): x for x in sorted(rnd.sample(pool, min(k, len(pool))))}
    inject = [{"change": cause_id, "target": c, "at": onset - 3 * 60_000, "title": f"{c}: change"}]
    inject += [{"change": cid, "target": x, "at": onset - 3 * 60_000, "title": f"{x}: change"}
               for cid, (x, _) in dist.items()]
    inject += [{"change": cid, "target": x, "at": onset - rnd.randint(1, window_min - 1) * 60_000,
                "title": f"{x}: change"} for cid, x in ambient.items()]
    inject.sort(key=lambda x: (x["at"], x["change"]))
    monitored = sorted({c, t} | any_c | {x["target"] for x in inject} | set(w.upstream(t, 3)))
    return {"home_unit": home, "cause_target": c, "symptom": t, "hub": hub, "roles": roles,
            "distractors": {cid: {"target": x, "category": cat} for cid, (x, cat) in sorted(dist.items())},
            "ambient": ambient, "inject": inject, "monitored": monitored, "degraded": sorted(any_c),
            "expected": {"outcome": "CONFIRMED", "cause": cause_id,
                         "eliminated": {cid: EXPECT_REASON[cat] for cid, (_, cat) in dist.items()},
                         "ambient": sorted(ambient)}}


def world_series(w: W.World, plan: dict, onset: int, seed: int = SEED, before_min: int = 30,
                 after_min: int = 5) -> dict[str, list[tuple[int, int, float]]]:
    """Per-minute error rate of every monitored component: the sim/telemetry.py model (seeded base 0.2–0.8%, Gaussian
    noise, the cause's own effect, propagation err(v) = own + (1 − own)(1 − Π(1 − share·cap·excess(u)))), relaxed to a
    fixed point over the components the cause can reach (elsewhere the excess is noise only and is not propagated)."""
    rnd = random.Random(seed)
    nodes = plan["monitored"]
    deg = [plan["cause_target"]] + plan["degraded"]
    calc = sorted(set(nodes) | set(deg))
    base = {n: round(0.002 + random.Random(f"{seed}:{n}").random() * 0.006, 5) for n in calc}
    hot = set(deg)
    out: dict[str, list[tuple[int, int, float]]] = {n: [] for n in nodes}
    for m in range(before_min + after_min + 1):
        at = onset - before_min * 60_000 + m * 60_000
        own = {n: base[n] + rnd.gauss(0, base[n] * 0.15) for n in calc}
        if at >= onset - 2 * 60_000:
            own[plan["cause_target"]] = max(own[plan["cause_target"]], EFFECT)
        err = dict(own)
        for _ in range(len(deg) + 1):
            changed = False
            for n in sorted(hot - {plan["cause_target"]}):
                ok = 1.0
                for u, cap, share in w.fail_in.get(n, ()):
                    if u in hot:
                        ok *= 1.0 - share * cap * max(0.0, err[u] - base[u])
                new = own[n] + (1 - own[n]) * (1 - ok)
                if abs(new - err[n]) > 1e-9:
                    err[n], changed = new, True
            if not changed:
                break
        for n in nodes:
            out[n].append((at, round((at - onset) / 60_000), round(max(0.0, min(1.0, err[n])), 5)))
    return out


# ------------------------------------------------------------------ engine side
def _engine():
    from faultline.graph import client

    return client.engine()


def engine_memory() -> dict:
    """FalkorDB's own INFO memory: used_memory and the headroom under maxmemory (None = no limit configured)."""
    info = _engine().connection.info("memory")
    used = float(info.get("used_memory", 0)) / 2**20
    cap = float(info.get("maxmemory", 0)) / 2**20
    return {"used_mb": round(used, 1), "maxmemory_mb": round(cap, 1) if cap else None,
            "headroom_mb": round(cap - used, 1) if cap else None, "policy": info.get("maxmemory_policy")}


def _settled_used_mb(timeout_s: float = 20.0) -> float:
    """used_memory once FalkorDB's asynchronous GRAPH.DELETE has finished freeing (two readings within 1 MB)."""
    last, end = engine_memory()["used_mb"], time.time() + timeout_s
    while time.time() < end:
        time.sleep(1.0)
        now = engine_memory()["used_mb"]
        if abs(now - last) < 1.0:
            return now
        last = now
    return last


def mem_available_mb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def meta_counts(graph: str) -> dict:
    """Node and edge counts per label / type from db.meta.stats (the engine's own counters, constant time)."""
    r = _engine().select_graph(graph).ro_query("CALL db.meta.stats()")
    row = dict(zip([h[1] if isinstance(h, (list, tuple)) else h for h in r.header], r.result_set[0]))
    labels = {k: int(v) for k, v in dict(row["labels"]).items() if k != "Node" and int(v)}
    rels = {k: int(v) for k, v in dict(row["relTypes"]).items() if int(v)}
    return {"nodes": labels, "edges": rels, "nodes_total": int(row["nodeCount"]), "edges_total": int(row["relCount"])}


def prepare(tenant: str, graph: str, w: W.World, plan: dict, onset: int, tag: str):
    """Inject the planted incident into the clean room and open it through the product's intake (Q-ALERT-1)."""
    from faultline import scenario
    from faultline.graph import writes
    from faultline.graph.ro import RO

    g = _engine().select_graph(graph)
    for c in plan["inject"]:
        writes.inject_change(g, id=c["change"], target=c["target"], at=c["at"], kind="deploy", title=c["title"],
                             tenant=tenant)
    series = world_series(w, plan, onset)
    rows, edges = [], {}
    for n, pts in series.items():
        for at, minute, v in pts:
            wid = f"mw-{n}-error_rate-{at}"
            rows.append({"id": wid, "target_id": n, "metric": "error_rate", "minute": minute, "at": at, "value": v,
                         "kind": "live"})
            edges.setdefault(w.label[n], []).append({"src": wid, "dst": n})
    writes.upsert_nodes(g, "MetricWindow", rows)
    for lbl, pairs in sorted(edges.items()):
        writes.upsert_edges(g, "WINDOW_OF", "MetricWindow", lbl, pairs)
    writes.raise_alert(g, id=f"al-scale-{plan['symptom']}", target=plan["symptom"], metric="error_rate", at=onset)
    alerts = RO(tenant, graph).run("Q-ALERT-1", {"since": onset - 5 * 60_000, "until": onset + 60_000}).rows
    symptoms = sorted({a["target"] for a in alerts})
    if not symptoms:
        raise RuntimeError("no alert fired around onset")
    inc, run = f"inc-scale-{tag}", f"run-scale-{tag}"
    report = f"{plan['symptom']} errors are elevated"
    writes.open_incident(g, inc=inc, run=run, tenant=tenant, title="scale benchmark incident", report=report, onset=onset,
                         symptoms=[{"id": f"sym-{next(a['metric'] for a in alerts if a['target'] == s)}-{s}", "kind":
                                    next(a["metric"] for a in alerts if a["target"] == s), "target": s} for s in symptoms],
                         models="", mode="scenario")
    scenario.embed_incident(g, inc, report, scenario.symptom_texts(alerts, symptoms))
    writes.advance_stage(g, inc=inc, run=run, stage="INTAKE", ord_=1, note=f"alerts: {[a['id'] for a in alerts]}")
    return {"incident": inc, "run": run, "symptoms": symptoms, "windows": len(rows)}


def run_product(tenant: str, graph: str, p: dict, onset: int, window_min: int):
    from faultline.agent.loop import BaselineInvestigator, run_incident

    return anyio.run(lambda: run_incident(tenant=tenant, incident_id=p["incident"], onset_ms=onset, symptoms=p["symptoms"],
                                          investigator=BaselineInvestigator(), graph=graph, run_id=p["run"],
                                          window_min=window_min))


def time_sweep(tenant: str, graph: str, p: dict, window_min: int, repeat: int) -> dict:
    from faultline.agent.gate import Gate

    ms, verdicts = [], None
    for _ in range(repeat):
        t0 = time.perf_counter()
        v = Gate(tenant, p["run"], p["incident"], graph, window_min=window_min).sweep()
        ms.append((time.perf_counter() - t0) * 1000)
        verdicts = {x.change: x.status for x in v}
    return {**stats(ms), "changes": len(verdicts or {}),
            "eliminated": sum(1 for s in (verdicts or {}).values() if s == "eliminated")}


def _files_of(component: str, w: W.World) -> list[str]:
    """Repo-relative paths of a component's files, from the generator (the world), never from FalkorDB."""
    u = w.unit_of[component]
    local = component.removesuffix(W.suffix(u))
    g = W.history._generated(W.unit_seed(u))[0]
    return [W.ns(f, u).removeprefix("file:") for f in sorted(g.files.get(local, []))[:2]]


def preflight(tenant: str, graph: str, w: W.World, components: list[str]) -> list[dict]:
    from faultline.preflight.engine import PreflightIn, run
    from faultline.preflight.facts import ChangedFile

    out = []
    for i, comp in enumerate(components, start=1):
        files = _files_of(comp, w)
        if not files:
            continue
        t0 = time.perf_counter()
        r = run(tenant, PreflightIn(repo="scale/bench", number=900 + i, title=f"scale bench change to {comp}",
                                    author="bench", head_sha="0" * 40, files=[ChangedFile(path=f) for f in files]),
                graph=graph)
        out.append({"component": comp, "verdict": r["verdict"], "risk": r.get("risk"), "error": r.get("error"),
                    "ms": round((time.perf_counter() - t0) * 1000, 1), "template_ms": (r.get("evidence") or {}).get("ms"),
                    "terms": r.get("terms")})
    return out


def _run_params(tenant: str, graph: str, run_id: str, inc: str) -> tuple[list[tuple[str, dict]], list[dict], bool]:
    """(template, params) pairs the run executed (recorded evidence + gate-check params), the truncated tool calls, and
    whether the run's call list itself was cut at Q-RUN-2's LIMIT."""
    from faultline.graph.ro import RO

    ro = RO(tenant, graph)
    calls = ro.run("Q-RUN-2", {"run": run_id})
    pairs: list[tuple[str, dict]] = []
    for tc in calls.rows:
        if not (tc["template"] and tc["params"]):
            continue
        params = json.loads(tc["params"])
        parts = tc["template"].split("+")
        for tid in parts:
            p = params.get(tid) if len(parts) > 1 else params
            if isinstance(p, dict):
                pairs.append((tid, p))
    for gr in ro.run("Q-INC-GATES", {"inc": inc}).rows:
        for c in json.loads(gr["checks"]):
            if c.get("template") and c.get("params") is not None:
                pairs.append((c["template"], c["params"]))
    return pairs, _truncated_calls(tenant, graph, run_id), calls.truncated


def _truncated_calls(tenant: str, graph: str, run_id: str) -> list[dict]:
    from faultline.graph.ro import RO

    return [{"tool": r["tool"], "template": r["template"], "rows": r["rows"]}
            for r in RO(tenant, graph).run("Q-RUN-TRUNC", {"run": run_id}).rows]


def hero_params(plan: dict, p: dict, onset: int, window_ms: int, protect: list[str]) -> list[tuple[str, str, dict]]:
    """(template, instance, params): the hero templates on the incident's own ids and on the global hub's."""
    c, t, hub = plan["cause_target"], plan["symptom"], plan["hub"]
    out = [("Q-GATE-1", "cause→symptom", {"cause": plan["roles"]["cause"], "symptom": t}),
           ("Q-GATE-3", "cause→symptom", {"sources": [c], "symptom": t}),
           ("Q-GATE-MULT", "cause→symptom", {"sources": [c], "symptom": t}),
           ("Q-SUS-1", "symptom", {"symptom": t, "onset": onset, "window_ms": window_ms}),
           ("Q-SUS-2", "window", {"onset": onset, "window_ms": window_ms}),
           ("Q-BLAST-1", "cause", {"id": c}), ("Q-BLAST-2", "cause", {"id": c}),
           ("Q-CUT-1", "cause→protect", {"failing": c, "protect": protect}), ("Q-CUT-2", "cause", {"failing": c}),
           ("Q-NEG-1", "window", {"now": onset, "window_ms": window_ms, "anomalous_ids": [t]})]
    if hub:
        out += [("Q-GATE-1", "hub→symptom", {"cause": plan["roles"]["hub"], "symptom": t}),
                ("Q-GATE-3", "hub→symptom", {"sources": [hub], "symptom": t}),
                ("Q-GATE-MULT", "hub→symptom", {"sources": [hub], "symptom": t}),
                ("Q-BLAST-1", "hub", {"id": hub}), ("Q-BLAST-2", "hub", {"id": hub}),
                ("Q-CUT-2", "hub", {"failing": hub})]
    return out


def profile_all(tenant: str, graph: str, instances: list[tuple[str, str, dict]], n: int) -> dict:
    from faultline.graph.ro import RO, profile

    ro = RO(tenant, graph)
    out: dict[str, dict] = {}
    for tid, inst, params in instances:
        if tid in SCRATCH or tid == "T2C":
            continue
        x = out.setdefault(tid, {"instances": []})
        if len(x["instances"]) >= MAX_INSTANCES or any(i["params"] == params for i in x["instances"]):
            continue
        eng, wall, rows, trunc, err = [], [], None, False, None
        for _ in range(n):
            try:
                eng.append(profile(tenant, tid, params, graph)["engine_ms"])
                r = ro.run(tid, params)
                wall.append(r.ms)
                rows, trunc = len(r.rows), trunc or r.truncated
            except Exception as e:  # noqa: BLE001 - a TIMEOUT or engine error is a finding, recorded as such
                err = f"{type(e).__name__}: {str(e)[:160]}"
                break
        x["instances"].append({"instance": inst, "params": params, "runs": len(eng), "rows": rows, "truncated": trunc,
                               "engine_ms_p50": stats(eng)["p50"], "engine_ms_p95": pct(eng, 0.95),
                               "wall_ms_p50": stats(wall)["p50"], "wall_ms_p95": pct(wall, 0.95),
                               **({"error": err} if err else {})})
    for tid, x in out.items():   # the headline per template = its slowest instance (by engine p95)
        ok = [i for i in x["instances"] if i.get("engine_ms_p95") is not None]
        if ok:
            worst = max(ok, key=lambda i: i["engine_ms_p95"])
            x.update({k: worst[k] for k in ("engine_ms_p50", "engine_ms_p95", "wall_ms_p50", "wall_ms_p95", "rows")})
            x["instance"] = worst["instance"]
        x["truncated"] = any(i["truncated"] for i in x["instances"])
        x["errors"] = sum(1 for i in x["instances"] if i.get("error"))
    return dict(sorted(out.items()))


def run_size(label: str, profile_n: int = PROFILE_N, keep: bool = False, progress: bool = True,
             prior_mb_per_service: float | None = None) -> dict:
    from faultline.agent.weights import weights
    from faultline.graph import copy as gcopy
    from faultline.graph import engine_info
    from faultline.graph.tenant import eval_graph, golden_graph
    from faultline.ingest.clock import ANCHOR_MS

    tenant, services = W.tenant_for(label), W.SIZES[label]
    U = W.n_units(services)
    res: dict = {"label": label, "tenant": tenant, "services": U * W.unit_services(), "units": U}
    db = _engine()
    avail = mem_available_mb()
    eng = engine_memory()
    res["engine_used_mb_before"] = eng["used_mb"]
    est = (prior_mb_per_service or DEFAULT_MB_PER_SERVICE) * res["services"]
    res["memory_estimate_mb"] = round(est, 1)
    room_for = [x for x in (avail, eng["headroom_mb"]) if x is not None]
    budget = min(room_for) if room_for else None
    if budget is not None:
        # the clean room plus one what-if branch must fit in the host AND under FalkorDB's maxmemory (noeviction: a write
        # past it fails), with headroom: the host is shared with the editor, other agents and the engine itself
        if 2.2 * est > 0.85 * budget:
            res["skipped"] = (f"estimated {est:.0f} MB per graph; a clean room and a what-if branch would need "
                              f"~{2.2 * est:.0f} MB; available: host {avail:.0f} MB, FalkorDB maxmemory headroom "
                              f"{eng['headroom_mb'] if eng['headroom_mb'] is not None else 'unlimited'} MB")
            return res
        copy_mode = 3.2 * est < 0.6 * budget   # golden + clean room + what-if branch, leaving room for other work
    else:
        copy_mode = True
    golden = golden_graph(tenant)
    tag = uuid.uuid4().hex[:8]
    room = eval_graph(tenant, "scale", "bench", label, 1) + f"_{tag}"
    window = int(weights()["gate"]["window_min"])
    onset = ANCHOR_MS + 3 * 3_600_000
    try:
        t0 = time.perf_counter()
        seeded_into = golden if copy_mode else room
        if progress:
            print(f"[{label}] seeding {seeded_into} ({U} units) …", file=sys.stderr, flush=True)
        res["seed"] = W.seed(services, tenant, seeded_into, progress=progress)
        res["clean_room"] = "GRAPH.COPY of the golden graph" if copy_mode else \
            "seeded directly into the clean room (no golden kept: a copy would not fit in memory)"
        mem = engine_info.memory(seeded_into)
        res["memory_mb"] = mem.get("total_graph_sz_mb")
        res["memory_detail"] = {k: v for k, v in mem.items() if not isinstance(v, dict)}
        cnt = meta_counts(seeded_into)   # db.meta.stats: O(1); a full MATCH ()-[r]->() count took 4.4 s at 25k
        res["nodes"], res["edges"] = cnt["nodes_total"], cnt["edges_total"]
        res["counts"] = {"nodes": cnt["nodes"], "edges": cnt["edges"]}
        if copy_mode:
            res["copy_ms"] = gcopy.copy_graph(db, golden, room, deadline_s=300)["ms"]
        w = W.world(services)
        plan = plan_incident(w, onset, window)
        res["incident"] = {k: plan[k] for k in ("home_unit", "cause_target", "symptom", "hub", "roles", "distractors",
                                                 "expected")}
        res["incident"]["ambient"] = len(plan["ambient"])
        res["incident"]["monitored"] = len(plan["monitored"])
        if progress:
            print(f"[{label}] planted: {plan['cause_target']} → {plan['symptom']}, {len(plan['distractors'])} distractors, "
                  f"{len(plan['ambient'])} ambient changes; running the product …", file=sys.stderr, flush=True)
        p = prepare(tenant, room, w, plan, onset, f"{label}-{tag}")
        r = run_product(tenant, room, p, onset, window)
        got = {"outcome": r.outcome, "cause": r.cause_id if r.outcome == "CONFIRMED" else None, "confident": r.confident,
               "sweep": {v["change"]: f"{v['status']}: {v['reason']}" for v in r.sweep}}
        pairs, tcs, calls_cut = _run_params(tenant, room, p["run"], p["incident"])
        pg = r.post_gate or {}
        res["run"] = {**got, **grade(plan["expected"], got), "seconds": r.seconds, "error": r.error,
                      "tool_calls": r.tool_calls, "swept": len(r.sweep), "windows_written": p["windows"],
                      "protect": pg.get("protect"), "cut": pg.get("cut"), "max_flow": pg.get("max_flow"),
                      "whatif": pg.get("whatif"), "options": [o.get("kind") for o in pg.get("options") or []],
                      "truncated_calls": tcs, "call_list_truncated": calls_cut}
        if progress:
            print(f"[{label}] run: {r.outcome} cause={r.cause_id} correct={res['run']['correct']} in {r.seconds}s",
                  file=sys.stderr, flush=True)
        res["sweep_ms"] = time_sweep(tenant, room, p, window, SWEEP_REPEAT)
        res["preflight"] = preflight(tenant, room, w, [plan["cause_target"]] + ([plan["hub"]] if plan["hub"] else []))
        protect = pg.get("protect") or []
        inst = hero_params(plan, p, onset, window * 60_000, protect)
        inst += [(tid, "run", params) for tid, params in pairs]
        if progress:
            print(f"[{label}] profiling templates ({profile_n} runs each) …", file=sys.stderr, flush=True)
        res["templates"] = profile_all(tenant, room, inst, profile_n)
        res["slowlog"] = [{k: s[k] for k in ("template", "ms", "command")} for s in engine_info.slowlog(room)[:10]]
        res["memory_mb_after_run"] = engine_info.memory(room).get("total_graph_sz_mb")
        res["wall_s"] = round(time.perf_counter() - t0, 1)
        return res
    finally:
        if not keep:
            for gname in (room, golden):
                gcopy.delete_if_exists(db, gname)
        res["kept"] = sorted(n for n in db.list_graphs() if n in (room, golden)) if keep else []
        # does deleting the graphs give the memory back? (engine-wide used_memory; other work can move it too)
        res["engine_used_mb_after_cleanup"] = _settled_used_mb() if not keep else engine_memory()["used_mb"]


def run(labels: list[str], profile_n: int = PROFILE_N, keep: bool = False, progress: bool = True) -> dict:
    from faultline.graph.algo import registry

    meta = registry.resolved_meta()
    out: dict = {"engine": meta.get("engine"), "digest": meta.get("digest"),
                 "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "profile_runs": profile_n,
                 "seed": SEED, "machine": {"mem_available_mb": round(mem_available_mb() or 0), "cpus": _cpus()},
                 "sizes": {}}
    per_service = None
    for label in sorted(labels, key=lambda x: W.SIZES[x]):
        res = run_size(label, profile_n, keep, progress, per_service)
        out["sizes"][label] = res
        if res.get("memory_mb") and res.get("services"):
            per_service = float(res["memory_mb"]) / res["services"]
    out["analysis"] = analyse(out["sizes"])
    out["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def _cpus() -> int:
    import os

    return os.cpu_count() or 0


def for_harness() -> dict:
    """The harness's scale check: the recorded `make scale` run (evals/results/scale.json, raw JSON) when it was made on
    the pinned engine; otherwise the reduced 1k variant runs now. Either way the source is stated."""
    from faultline.graph.algo import registry

    if OUT.exists():
        rec = json.loads(OUT.read_text())
        if rec.get("digest") == registry.resolved_meta().get("digest"):
            return {**rec, "source": f"evals/results/{OUT.name} (make scale, finished {rec.get('finished')})"}
    return {**run(["1k"], profile_n=5, progress=False), "source": "reduced 1k variant run by the harness"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sizes", default=",".join(W.SIZES))
    ap.add_argument("--profile-n", type=int, default=PROFILE_N)
    ap.add_argument("--keep", action="store_true", help="keep the golden and clean-room graphs (default: delete)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    labels = [x.strip() for x in a.sizes.split(",") if x.strip()]
    for x in labels:
        W.tenant_for(x)
    out = run(labels, a.profile_n, a.keep, not a.quiet)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    for label, s in out["sizes"].items():
        if s.get("skipped"):
            print(f"{label}: skipped ({s['skipped']})")
            continue
        r = s.get("run", {})
        print(f"{label}: {s['services']} services, {s.get('nodes')} nodes / {s.get('edges')} edges, "
              f"{s.get('memory_mb')} MB, seed {s['seed']['seed_s']} s; verdict {r.get('outcome')} "
              f"{'correct' if r.get('correct') else 'WRONG'}; run {r.get('seconds')} s, sweep p50 "
              f"{(s.get('sweep_ms') or {}).get('p50')} ms")
    print(f"wrote {Path(a.out).relative_to(ROOT) if Path(a.out).is_relative_to(ROOT) else a.out}")
    return 0 if all(s.get("skipped") or s.get("run", {}).get("correct") for s in out["sizes"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
