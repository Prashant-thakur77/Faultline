"""Telemetry simulator: the world the agent observes (never consulted by the agent directly).

Per-minute error rate for every service/datastore over [onset − baseline_min, onset + after_min]:
  * baseline: seeded noise around a per-service base error rate (0.2–0.8%);
  * injected effects (scenario config): a component's own error rate from a given time;
  * propagation: a request to v fails if one of its dependencies fails it:
        err(v) = own(v) + (1 − own(v)) · (1 − Π_{u→v} (1 − share(v calls u) · cap(u→v) · excess(u)))
    with excess(u) = err(u) − base(u), relaxed to a fixed point over the PROPAGATES_TO edge list
    (share = rps(v→u) / rps into v from the traffic matrix; cap = call criticality). The world is
    realistic (share-weighted); the gate's G5 bound uses criticality alone, an upper bound. This models the world; the agent's
    reasoning about it happens only through FalkorDB queries.
Writes (:MetricWindow {target_id, metric:'error_rate', minute, at, value, kind:'live'})-[:WINDOW_OF]->(target).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from falkordb import Graph

from ..graph import writes
from ..graph.ro import RO

MINUTE = 60_000


@dataclass
class Effect:
    target: str
    value: float          # the component's own error rate while active
    start_ms: int
    end_ms: int | None = None
    change: str | None = None  # the change that causes it (a rollback of that change removes the effect)


def _components(ro: RO) -> tuple[list[str], list[tuple[str, str, float]]]:
    res = ro.run("Q-SIM-1", {})
    if res.truncated:  # fail loudly: a partial topology would simulate a wrong world
        raise RuntimeError("simulator topology view truncated at the template LIMIT; this tenant is too large for "
                           "the simulator's view (scope it before simulating)")
    view = res.rows
    nodes = sorted({r["src"] for r in view} | {r["dst"] for r in view})
    edges = [(r["src"], r["dst"], float(r["cap"]) * min(1.0, float(r["rps"] or 0) / float(r["in_rps"] or 1))) for r in view]
    return nodes, edges


def simulate(g: Graph, ro: RO, *, onset_ms: int, effects: list[Effect], seed: int = 42, baseline_min: int = 30,
             after_min: int = 5, cut_edges: set[tuple[str, str]] | None = None, start_ms: int | None = None,
             minutes: int | None = None, base_seed: int | None = None, topology: RO | None = None,
             noise: float = 0.15) -> dict:
    """Generate and write windows. `cut_edges`: failure edges (u → v) a containment lever has cut in the
    world (from flags.json on the demo repo's default branch). `start_ms`/`minutes`: append windows after
    an action (verification) instead of the default [onset − baseline, onset + after] range.
    `seed` drives the per-minute noise; `base_seed` (default: `seed`) the per-service base error rates, which belong
    to the WORLD: windows appended after an action must pass the world's seed here, or the services' base rates
    shift by up to 0.6 points between the baseline and the check (found by the futures eval: a contained fault read
    as not contained). `topology`: read the world's topology from ANOTHER graph (the model-mismatch and learning
    evals: the graph the product reads is wrong on purpose, the world is not); windows are still written to `g`."""
    rnd = random.Random(seed)
    nodes, edges = _components(topology or ro)
    bs = seed if base_seed is None else base_seed
    base = {n: round(0.002 + random.Random(f"{bs}:{n}").random() * 0.006, 5) for n in nodes}
    edges = [(u, v, c) for u, v, c in edges if (u, v) not in (cut_edges or set())]
    start = start_ms if start_ms is not None else onset_ms - baseline_min * MINUTE
    span = minutes if minutes is not None else baseline_min + after_min + 1
    rows, edge_rows = [], []
    series: dict[str, list[tuple[int, float]]] = {n: [] for n in nodes}
    for m in range(span):
        t = start + m * MINUTE
        own = {n: base[n] + rnd.gauss(0, base[n] * noise) for n in nodes}  # noise: the world's (scenario `noise`)
        for e in effects:
            if e.target in own and e.start_ms <= t and (e.end_ms is None or t < e.end_ms):
                own[e.target] = max(own[e.target], e.value)
        err = dict(own)
        for _ in range(len(nodes)):  # fixed-point relaxation over the edge list (DAG depth ≤ nodes)
            changed = False
            for n in nodes:
                ok = 1.0
                for u, v, cap in edges:
                    if v == n:
                        ok *= 1.0 - cap * max(0.0, err[u] - base[u])
                new = own[n] + (1 - own[n]) * (1 - ok)
                if abs(new - err[n]) > 1e-9:
                    err[n], changed = new, True
            if not changed:
                break
        for n in nodes:
            wid = f"mw-{n}-error_rate-{t}"
            rows.append({"id": wid, "target_id": n, "metric": "error_rate", "minute": round((t - onset_ms) / MINUTE), "at": t,
                         "value": round(max(0.0, min(1.0, err[n])), 5), "kind": "live"})
            edge_rows.append({"src": wid, "dst": n})
            series[n].append((t, max(0.0, min(1.0, err[n]))))
    writes.upsert_nodes(g, "MetricWindow", rows)
    burns = _burn_alerts(g, ro, series, onset_ms) if start_ms is None else []
    targets = {r["id"]: r["target_id"] for r in rows}
    for lbl, pairs in _edges_by_target_label(ro, edge_rows, targets).items():
        writes.upsert_edges(g, "WINDOW_OF", "MetricWindow", lbl, pairs)
    return {"windows": len(rows), "components": len(nodes), "minutes": span, "cut_edges": sorted(cut_edges or []),
            "slo_burn_alerts": burns}


def _burn_alerts(g: Graph, ro: RO, series: dict[str, list[tuple[int, float]]], onset_ms: int) -> list[dict]:
    """The world's monitoring: an SLO-burn page fires at the first minute the trailing error rate, divided by the
    SLO's budget, crosses `obligation.fast_burn` (weights.yaml). It is a page about a budget, not a symptom: INTAKE
    (Q-ALERT-1) ignores it, while alert coverage and the obligation clock see it."""
    from ..agent.weights import weights

    w = weights()["obligation"]
    fast, k = float(w["fast_burn"]), int(w["burn_window_min"])
    out = []
    for slo in ro.run("Q-SIM-SLO", {}).rows:
        pts = series.get(slo["service"]) or []
        budget = float(slo["budget"] or 0)
        if budget <= 0:
            continue
        for i in range(k - 1, len(pts)):
            burn = sum(v for _, v in pts[i - k + 1:i + 1]) / k / budget
            if burn >= fast:
                t = pts[i][0]
                aid = f"al-burn-{slo['slo']}-{t}"
                writes.raise_alert(g, id=aid, target=slo["service"], metric="slo_burn", at=t)
                out.append({"id": aid, "slo": slo["slo"], "target": slo["service"], "at": t, "burn": round(burn, 2),
                            "minute": round((t - onset_ms) / MINUTE)})
                break
    return out


def _edges_by_target_label(ro: RO, edge_rows: list[dict], targets: dict[str, str]) -> dict[str, list[dict]]:
    res = ro.run("Q-LABELS-1", {"ids": sorted(set(targets.values()))})
    if res.truncated:
        raise RuntimeError("Q-LABELS-1 truncated: too many simulated components for one read")
    lbl = {r["id"]: r["label"] for r in res.rows}
    out: dict[str, list[dict]] = {}
    for e in edge_rows:
        out.setdefault(lbl[e["dst"]], []).append(e)
    return out
