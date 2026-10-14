"""Context packs: graph context vs vector RAG vs recency, per token (PREREGISTRATION amendment 2026-10-14, M16.1).

For each world with grader truth, the product's `context_pack` builds its candidate pool and its pack (G). The same
pool, serialised identically, is also packed by vector similarity to the input (V: the product's embedding model,
cosine, plus a one-paragraph topology description) and by recency (R: the window's changes and the alert newest first,
then the topology description). Each pack is cut to 500 / 1,000 / 2,000 tokens (characters / 4). Metric: recall of the
truth items (cause change, cause component, chain nodes; on the scenarios also the violated decisions, any responder
and any fix target), and pack build time.

Worlds: the scenarios with a confirmed cause (truth from data/scenarios/*.truth.json), the confirmed-cause worlds of the
held-out gate bench (seed 20261015) and the cause categories of the fresh deep bench (seed 20261016); bench truth is the
generator's (oracle over the topology config).

    PYTHONPATH=backend uv run python evals/context_eval.py [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if __import__("importlib.util").util.find_spec("gate_bench") is None:
    sys.path.insert(0, str(ROOT / "evals"))

import deep_bench  # noqa: E402
import gate_bench  # noqa: E402
from faultline import scenario  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.mcp_server import context as mcpctx  # noqa: E402
from faultline.mcp_server import tools as T  # noqa: E402

BUDGETS = (500, 1000, 2000)
CHARS_PER_TOKEN = 4
SCENARIOS = ("S1", "S1b", "S2", "S3", "S3b", "S12")


def tokens(text: str) -> int:
    return max(1, -(-len(text) // CHARS_PER_TOKEN))


def greedy(items: list[dict], budget: int) -> list[dict]:
    out, used = [], 0
    for it in items:
        if used + it["tokens"] <= budget:
            out.append(it)
            used += it["tokens"]
    return out


def topology_item(ro: RO) -> dict:
    """The flat text a vector-RAG stack would carry about the topology: one line of failure-flow edges."""
    rows = ro.run("Q-SIM-1", {}).rows
    text = "topology (failure flows server → client): " + ", ".join(f"{r['src']}→{r['dst']}" for r in rows)
    return {"kind": "topology", "text": text, "ids": sorted({x for r in rows for x in (r["src"], r["dst"])}),
            "tokens": tokens(text)}


def vector_pack(pool: list[dict], query: str, topo: dict, budget: int) -> list[dict]:
    from faultline.memory.embed import embed

    vecs = embed([query] + [it["text"] for it in pool])
    q = vecs[0]

    def cos(a, b):
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0

    ranked = [it for _, it in sorted(zip([cos(q, v) for v in vecs[1:]], pool), key=lambda t: -t[0])]
    # the topology paragraph is always carried when it fits (a vector stack's system context)
    return greedy([topo] + ranked, budget) if topo["tokens"] <= budget else greedy(ranked, budget)


def window_items(ro: RO, onset: int, window_min: int) -> list[dict]:
    """Every change in the window (Q-SUS-2), serialised without graph distance: what a recency stack sees. (The first
    two runs mistakenly drew R's changes from the graph pool, i.e. only changes upstream of the alert: the graph had
    already filtered them. PREREGISTRATION defines R as the window's changes.)"""
    out = []
    for x in ro.run("Q-SUS-2", {"onset": onset, "window_ms": window_min * 60_000}).rows:
        text = f"change {x['deploy']} ({x['kind']}) on {x['target']}, {round((onset - int(x['at'] or onset)) / 60_000)} min before"
        out.append({"kind": "change", "text": text, "ids": [x["deploy"], x["target"]], "tokens": tokens(text), "at": x["at"]})
    return out


def recency_pack(window: list[dict], pool: list[dict], topo: dict, budget: int) -> list[dict]:
    changes = sorted(window, key=lambda it: -(it.get("at") or 0))
    alerts = [it for it in pool if it["kind"] == "alert"]
    return greedy(changes + alerts + [topo], budget)


def recall(pack: list[dict], truth: dict) -> dict:
    # correction 5: the topology paragraph lists every service id, so it would score component/chain recall for free;
    # only retrieved items count (the paragraph still spends its tokens)
    ids = {i for it in pack if it["kind"] != "topology" for i in it["ids"]}
    text = " ".join(it["text"] for it in pack)
    order = [it for it in pack if it["kind"] == "change"]
    rank = next((i + 1 for i, it in enumerate(order) if truth["cause"] in it["ids"]), None)
    out = {"cause": truth["cause"] in ids, "component": truth["component"] in ids, "rr": round(1 / rank, 4) if rank else 0.0,
           "chain": round(sum(n in ids for n in truth["chain"]) / len(truth["chain"]), 4) if truth["chain"] else None}
    if truth.get("decisions"):
        out["decisions"] = round(sum(d in ids or d in text for d in truth["decisions"]) / len(truth["decisions"]), 4)
    if truth.get("responders"):
        out["responder"] = any(p in ids for p in truth["responders"])
    if truth.get("fix_targets"):
        out["fix_target"] = any(f in ids for f in truth["fix_targets"])
    return out


def _worlds() -> list[dict]:
    out = []
    for sid in SCENARIOS:
        t = json.loads((ROOT / "data" / "scenarios" / f"{sid}.truth.json").read_text())
        if t.get("outcome") != "CONFIRMED":
            continue
        out.append({"id": sid, "source": "scenario", "spec": None, "sid": sid,
                    "truth": {"cause": t["cause"], "component": None, "chain": list(t.get("path_contains") or []),
                              "decisions": list(t.get("violates") or []), "responders": list(t.get("owners_any_of") or []),
                              "fix_targets": list(t.get("fix_targets_any_of") or [])}})
    for c in gate_bench.generate(seed=20261015):
        if c["expected"]["outcome"] == "CONFIRMED":
            out.append({"id": c["id"], "source": "gate_bench", "spec": c["spec"], "sid": c["spec"]["id"],
                        "truth": {"cause": c["expected"]["cause"], "component": c["origin"],
                                  "chain": [c["origin"], c["symptom"]] if c["origin"] != c["symptom"] else [c["origin"]]}})
    topo = gate_bench.Topo()
    dist = deep_bench.visible_dist(topo)
    for c in deep_bench.generate(seed=deep_bench.FRESH_SEED):
        if c["category"] not in ("deep_onpath", "symptom_decoy"):
            continue
        chain, x = [c["origin"]], c["origin"]   # one canonical shortest visible chain origin → symptom (oracle)
        while x != c["symptom"]:
            x = sorted(m for m, km in dist[x].items() if km == 1 and dist[m].get(c["symptom"]) == dist[x][c["symptom"]] - 1)[0]
            chain.append(x)
        out.append({"id": c["id"], "source": "deep_bench", "spec": c["spec"], "sid": c["spec"]["id"],
                    "truth": {"cause": c["expected"]["cause"], "component": c["origin"], "chain": chain}})
    return out


def busy_spec(w: dict, k: int) -> dict:
    """Addendum 1: k extra deploys in the window on components drawn with a seeded stream (world id)."""
    import copy
    import random

    import yaml

    spec = copy.deepcopy(w["spec"]) if w["spec"] else copy.deepcopy(
        next(s for s in yaml.safe_load((ROOT / "data" / "scenarios" / "scenarios.yaml").read_text()) if s["id"] == w["sid"]))
    rnd = random.Random(f"{w['id']}:busy:{k}")
    comps = sorted(gate_bench.Topo().nodes)
    # addendum 2: the cause's deploy time is drawn like the others (still before its effect at -2m), so recency
    # gains nothing from the generator always deploying the cause 3 minutes before onset
    cause = w["truth"]["cause"]
    spec["inject"] = [{**x, "at": f"-{rnd.randint(3, 29)}m"} if x["change"] == cause else x for x in spec["inject"]]
    spec["inject"] = list(spec["inject"]) + [
        {"change": f"D-{rnd.randrange(16**8):08x}", "target": (c := rnd.choice(comps)), "kind": "deploy",   # opaque, like real ones
         "at": f"-{rnd.randint(1, 29)}m", "title": f"{c}: change"} for i in range(k)]
    return spec


def run_world(w: dict, busy: int = 0) -> dict:
    spec = busy_spec(w, busy) if busy else w["spec"]
    p = scenario.prepare(w["sid"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=spec)
    try:
        truth = dict(w["truth"])
        if truth["component"] is None:   # scenarios: the cause's component, read from the scenario spec (grader side)
            truth["component"] = next((x["target"] for x in p.scenario["inject"] if x["change"] == truth["cause"]), None)
        text = p.scenario.get("report") or p.scenario.get("name") or ""
        token = mcpctx.bind(p.tenant, run_id=None, graph=p.graph)
        try:
            t0 = time.perf_counter()
            res = T.context_pack(text=text, targets=list(p.symptoms), at=p.onset_ms, budget_tokens=max(BUDGETS),
                                 window_min=p.scenario.get("window_min"),   # the same window the product's run gets
                                 rank="distance")   # G: graph distance only (the ablation since addendum 5)
            ms = (time.perf_counter() - t0) * 1000
            if "error" in res:
                raise RuntimeError(res["error"])
            pool = res["pool"]
            ga = T.context_pack(text=text, targets=list(p.symptoms), at=p.onset_ms, budget_tokens=max(BUDGETS),
                                window_min=p.scenario.get("window_min"), rank="anomaly")   # addendum 5
            if "error" in ga:
                raise RuntimeError(ga["error"])
            topo = topology_item(RO(p.tenant, p.graph))
            from faultline.agent.weights import weights
            window = window_items(RO(p.tenant, p.graph), p.onset_ms,
                                  int(p.scenario.get("window_min") or weights()["gate"]["window_min"]))
            row = {"id": w["id"], "source": w["source"], "busy": busy, "ms": round(ms, 1), "pool": len(pool), "budgets": {}}
            for b in BUDGETS:
                g = T.pack_items(pool, b)
                row["budgets"][str(b)] = {"G": recall(g, truth), "GA": recall(T.pack_items(ga["pool"], b), truth),
                                          "V": recall(vector_pack(pool, text, topo, b), truth),
                                          "R": recall(recency_pack(window, pool, topo, b), truth)}
        finally:
            mcpctx.unbind(token)
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    return row


def summarise(rows: list[dict]) -> dict:
    out: dict = {"worlds": len(rows), "by_source": {s: sum(r["source"] == s for r in rows) for s in sorted({r["source"] for r in rows})},
                 "ms_p50": round(statistics.median(r["ms"] for r in rows), 1),
                 "ms_p95": round(sorted(r["ms"] for r in rows)[max(0, math.ceil(0.95 * len(rows)) - 1)], 1), "budgets": {}}
    for b in BUDGETS:
        per = {}
        for arm in ("G", "GA", "V", "R"):
            rs = [r["budgets"][str(b)][arm] for r in rows]
            m = {"cause": round(sum(x["cause"] for x in rs) / len(rs), 4), "mrr": round(statistics.mean(x["rr"] for x in rs), 4),
                 "component": round(sum(bool(x["component"]) for x in rs) / len(rs), 4),
                 "chain": round(statistics.mean(x["chain"] for x in rs if x["chain"] is not None), 4)}
            for k in ("decisions", "responder", "fix_target"):
                xs = [x[k] for x in rs if k in x]
                if xs:
                    m[k] = round(sum(float(v) for v in xs) / len(xs), 4)
            per[arm] = m
        out["budgets"][str(b)] = per
    return out


BUSY = (0, 10, 30, 100)   # addenda 1 and 4: extra deploys in the window


def run(progress: bool = True, busy: tuple[int, ...] = BUSY) -> dict:
    t0 = time.perf_counter()
    out: dict = {"busy": {}}
    worlds = _worlds()
    for k in busy:
        rows = []
        for w in worlds:
            rows.append(run_world(w, k))
            if progress:
                g = rows[-1]["budgets"]["500"]
                print(f"[context] busy={k} {w['id']}: G cause={g['G']['cause']} V={g['V']['cause']} R={g['R']['cause']} "
                      f"({rows[-1]['ms']} ms)", file=sys.stderr, flush=True)
        out["busy"][str(k)] = {**summarise(rows), "rows": rows}
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run()
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in r["busy"].items()}, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
