"""globex product checks (graph-level; no simulator needed):

S8  recurring family: a NEW incident with the recommender-latency symptom recalls precedents from that family
    (vector seed → shared Symptom) and the family's derived runbook comes first (procedural memory).
S11 owner gone: the sole/top committer of `pricing` is inactive → bus factor warning; who_fixes still pages an
    ACTIVE person (harmonic over who touched it, resolved it, is on call) and MSF gives the escalation tree.
"""

from __future__ import annotations

import uuid

from faultline.agent.weights import weights
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO
from faultline.ingest.clock import ANCHOR_MS
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

NOW = ANCHOR_MS + 2 * 3_600_000


def s8() -> dict:
    db = gclient.engine()
    graph = f"eval_globex_s8_{uuid.uuid4().hex[:6]}"
    gcopy.copy_graph(db, "golden_globex", graph)
    try:
        g = db.select_graph(graph)
        inc, run = "inc-s8-probe", "run-s8-probe"
        writes.open_incident(g, inc=inc, run=run, tenant="globex", title="Recommendations slow again after a deploy",
                             report="Recommendation rail is timing out", onset=NOW,
                             symptoms=[{"id": "sym-latency-recommender", "kind": "latency", "target": "recommender"}],
                             models="", mode="eval")
        from faultline.scenario import embed_incident

        embed_incident(g, inc, "Recommendation rail is timing out", ["latency recommender"])
        ro = RO("globex", graph)
        family = next(f["incidents"] for f in ro.run("Q-MEM-6", {"inc": ""}).rows
                      if any(i in f["incidents"] for i in [r["id"] for r in ro.run("Q-MEM-1", {
                          "current": inc, "now": NOW, "half_life_ms": 30 * 86_400_000.0,
                          "w_recency": float(weights()["memory"]["recall_recency_w"])}).rows][:1]))
        tok = context.bind("globex", run_id=run, graph=graph)
        try:
            rec = T.similar_incidents(incident_id=inc, now=NOW)
            writes.record_recall(g, inc=inc, rows=rec["rows"])
            rb = T.runbook_for(ids=["recommender", "sym-latency-recommender"])
        finally:
            context.unbind(tok)
        prec = [r["id"] for r in rec["rows"]]
        return {"precedents": len(prec), "precedents_in_family": sum(1 for p in prec if p in family),
                "family_size": len(family), "first_runbook": rb["rows"][0]["id"] if rb["rows"] else None,
                "first_runbook_derived": bool(rb["rows"]) and rb["rows"][0]["source"] == "derived",
                "first_runbook_support": rb["rows"][0].get("support") if rb["rows"] else None}
    finally:
        gcopy.delete_if_exists(db, graph)


def s11() -> dict:
    tok = context.bind("globex", record=False)
    try:
        bus = T.bus_factor(target_id="pricing")
        who = T.who_fixes(target_id="pricing", now=NOW, since=NOW - 30 * 86_400_000)
        top = [w["person"] for w in who.get("rows", [])[:3]]
        esc = T.escalation_tree(person_ids=top) if top else {"rows": []}
        people = {r["id"]: r for r in RO("globex").run("Q-ORG-PEOPLE", {"ids": top}).rows}
    finally:
        context.unbind(tok)
    return {"bus_factor": bus.get("bus_factor"), "top_contributor_inactive": bus.get("top_contributor_inactive"),
            "paged_first": top[0] if top else None, "paged_first_active": bool(top) and bool(people[top[0]]["active"]),
            "escalation_edges": len(esc.get("rows", [])), "managers_in_tree": len(esc.get("managers") or [])}
