"""Break the graph (M15 #2): a judge picks ONE change to the graph and sees which decisions flip, with the queries.

The hero incident (S1) is prepared on a clean room, copied with GRAPH.COPY, and one perturbation from a fixed menu is
applied to the copy (a single `writes.py` query, eval clean rooms only). The product then runs on BOTH rooms with the
same deterministic investigator, and every decision is diffed: outcome, blamed change, each suspect's gate verdict,
the proof path, the min-cut, who fixes it, the escalation tree and the offered options. Nothing is computed here
that the product does not compute itself; this module only prepares, perturbs, runs twice and compares. Both rooms
are deleted at the end.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import anyio
import yaml

from . import scenario
from .graph import client
from .graph import copy as gcopy
from .graph import writes
from .graph.tenant import eval_graph

CONFIG = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "playground.yaml"


@dataclass(frozen=True)
class Perturbation:
    label: str
    what: str            # what changes in the graph, in one line
    expect: str          # which decision should move, and which algorithm decides it
    algorithm: str
    apply: dict


@lru_cache(maxsize=1)
def _config() -> tuple[str, dict[str, Perturbation]]:
    """The menu is scenario config (data/scenarios/playground.yaml), never code: no scenario literal in the package."""
    cfg = yaml.safe_load(CONFIG.read_text())
    return cfg["scenario"], {k: Perturbation(**v) for k, v in cfg["perturbations"].items()}


def scenario_id() -> str:
    return _config()[0]


def perturbations() -> dict[str, Perturbation]:
    return _config()[1]


# which templates make each decision (the UI opens their Cypher next to the diff)
DECIDED_BY = {"outcome": ["Q-GATE-1", "Q-GATE-3", "Q-GATE-ORIGIN"], "cause": ["Q-GATE-1", "Q-GATE-3", "Q-GATE-G1"],
              "proof_path": ["Q-GATE-1"], "min_cut": ["Q-CUT-3"], "who_fixes": ["Q-ORG-KNOWS", "Q-ORG-HARM"],
              "escalation": ["Q-ORG-COLLAB-W", "Q-ORG-MSF"], "options": ["Q-LEVER-1", "Q-LEVER-PATH", "Q-FUTURE-1"]}
GATE_TEMPLATE = {"G2": "Q-GATE-1", "G5": "Q-GATE-3", "G4": "Q-GATE-ORIGIN", "G1": "Q-GATE-G1"}


def menu() -> list[dict]:
    return [{"id": k, "label": p.label, "what": p.what, "expect": p.expect, "algorithm": p.algorithm}
            for k, p in perturbations().items()]


def _run(p: scenario.Prepared | object, graph: str, run_id: str):
    from .agent.loop import BaselineInvestigator, run_incident

    return anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                          symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=graph,
                                          run_id=run_id, window_min=p.scenario.get("window_min")))


def _decisions(r) -> dict:
    pg = r.post_gate or {}
    return {
        "outcome": r.outcome,
        "cause": r.cause_id if r.outcome == "CONFIRMED" else None,
        "accepted": r.cause_id,
        "suspects": {v["change"]: {"status": v["status"], "reason": v["reason"]} for v in (r.sweep or [])},
        "proof_path": list((r.gate or {}).get("chain") or []),
        "min_cut": [f"{c['u']} → {c['v']}" for c in pg.get("cut") or []],
        "who_fixes": [w["person"] for w in (pg.get("who_fixes") or [])[:3]],
        "escalation": [f"{e['from']} – {e['to']}" for e in (pg.get("escalation") or [])[:3]],
        "options": [f"{o['kind']} {o['target']}" + ("" if o["enabled"] else " (disabled)") for o in pg.get("options") or []],
    }


def _diff(a: dict, b: dict) -> list[dict]:
    rows = []
    for k in ("outcome", "cause", "proof_path", "min_cut", "who_fixes", "escalation", "options"):
        rows.append({"decision": k, "before": a[k], "after": b[k], "changed": a[k] != b[k], "templates": DECIDED_BY[k]})
    for c in sorted(set(a["suspects"]) | set(b["suspects"])):
        x, y = a["suspects"].get(c), b["suspects"].get(c)
        gates = {g for v in (x, y) if v for g in GATE_TEMPLATE if v["reason"].startswith(g)}
        rows.append({"decision": f"suspect {c}", "before": x, "after": y,
                     "changed": (x or {}).get("status") != (y or {}).get("status") or (x or {}).get("reason") != (y or {}).get("reason"),
                     "templates": sorted(GATE_TEMPLATE[g] for g in gates)})
    return rows


def run(kind: str) -> dict:
    """Prepare S1, copy it, apply `kind` to the copy, run the product on both, diff. Raises KeyError for an unknown kind."""
    pert = perturbations()[kind]
    sid = scenario_id()
    t0 = time.perf_counter()
    db = client.engine()
    p = scenario.prepare(sid, tag=uuid.uuid4().hex[:8], set_mode=False)
    twin = eval_graph(p.tenant, f"play{uuid.uuid4().hex[:6]}", "play", sid.lower(), 1)
    try:
        gcopy.copy_graph(db, p.graph, twin)
        args = dict(pert.apply)
        if args.pop("deactivate_top_responder", False):
            first = _run(p, p.graph, p.run_id)  # who fixes it first on the untouched room
            top = ((first.post_gate or {}).get("who_fixes") or [{}])[0].get("person")
            args["deactivate"] = [top] if top else []
            gcopy.delete_if_exists(db, p.graph)            # the probe wrote its run; start the baseline clean
            gcopy.copy_graph(db, twin, p.graph)
        applied = writes.perturb_model(db.select_graph(twin), **args)
        # the prepared run id in both rooms: the clean room's evidence belongs to it (they are separate graphs)
        before = _run(p, p.graph, p.run_id)
        after = _run(p, twin, p.run_id)
    finally:
        gcopy.delete_if_exists(db, twin)
        gcopy.delete_if_exists(db, p.graph)
    a, b = _decisions(before), _decisions(after)
    diff = _diff(a, b)
    return {"scenario": sid, "perturbation": {"id": kind, **menu_entry(kind)}, "applied": applied,
            "before": a, "after": b, "diff": diff, "changed": [d["decision"] for d in diff if d["changed"]],
            "seconds": round(time.perf_counter() - t0, 2)}


def menu_entry(kind: str) -> dict:
    return next(m for m in menu() if m["id"] == kind)


__all__ = ["menu", "perturbations", "run", "scenario_id"]
