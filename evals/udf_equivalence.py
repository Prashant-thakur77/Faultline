"""Engine = the documented formulas: what FalkorDB now computes inside one query against the previous Python code.

blast_radius (Q-BLAST-3), notify_set (Q-NOTIFY-2) and find_entities (Q-FIND-HYBRID) used to fetch graph facts and
score, sum, merge and sort them in Python. They are now one read-only query each, ranked inside FalkorDB by the
`faultline` UDF library. This script runs the previous Python code (kept here, as the oracle) and the product's tools
side by side and counts identical answers:

* every node of both tenants' graphs: the blast radius (ids, hops, impact, order) and the notify list (teams, impact,
  nearest hop, owned nodes, on-call, priority, order; a random 30% of calls pass three priority ids);
* entity search over the brain's own and paraphrased questions plus up to 150 node names per tenant, with five label
  filters in rotation, on both tenants;
* the containment min-cut (Q-CUT-3: algo.maxFlow and the residual cut in one query) for every component with a
  failure-flow edge, protecting its two highest-impact reachable nodes plus two random ones, against the Python
  routine graph/algo/maxflow.py::min_cut over Q-CUT-1 + Q-CUT-2 (cut edges and order, max-flow, source side).

    PYTHONPATH=backend uv run python evals/udf_equivalence.py [--out evals/results/udf_equivalence.json]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.agent.weights import tier_weight, weights  # noqa: E402
from faultline.graph.algo.maxflow import CutMismatch, min_cut  # noqa: E402
from faultline.graph import client, udf  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.mcp_server import context  # noqa: E402
from faultline.mcp_server import tools as T  # noqa: E402

TENANTS = ("acme", "globex")
FIND = {"Service": "Q-FIND-SERVICE", "Table": "Q-FIND-TABLE", "Runbook": "Q-FIND-RUNBOOK", "Decision": "Q-FIND-DECISION"}
FIND_VEC = {"Incident": "Q-FIND-INCIDENT-VEC", "Runbook": "Q-FIND-RUNBOOK-VEC"}
LABEL_SETS = [None, ["Service"], ["Runbook"], ["Incident", "Runbook"], ["Decision", "Table"]]


# ------------------------------------------------------------------ the previous Python code (the oracle)
def old_impact(tier, hops: int, traffic: float) -> float:
    return round(tier_weight(tier) * (1.0 / (1 + hops)) * math.log1p(max(traffic, 0.0) + 1.0), 4)


def old_blast(ro: RO, nid: str) -> list[tuple]:
    reach = ro.run("Q-BLAST-1", {"id": nid})
    hops = {r["id"]: r for r in ro.run("Q-BLAST-2", {"id": nid}).rows}
    rows = []
    for r in reach.rows:
        h = hops.get(r["id"], {})
        rows.append({**r, "hops": h.get("hops"),
                     "impact": old_impact(r.get("tier"), int(h.get("hops") or 1), float(h.get("max_cap") or 0) * 100)})
    rows.sort(key=lambda x: (-x["impact"], x["id"]))
    return [(x["id"], x["hops"], x["impact"]) for x in rows]


# the owners + on-call read the previous notify_set ran (Q-NOTIFY-1, retired; kept verbatim for the oracle only)
OLD_NOTIFY_OWNERS = (
    "MATCH (t:Team)-[:OWNS]->(n:Node) WHERE n.id IN $ids "
    "WITH t, collect(DISTINCT n.id) AS owns_impacted "
    "RETURN t.id AS team, t.name AS name, owns_impacted, "
    "[x IN [(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= $now AND $now < oc.to | p] WHERE x.active | x.id] AS oncall "
    "ORDER BY size(owns_impacted) DESC, team LIMIT 20")


def old_notify(ro: RO, tenant: str, nid: str, now: int, pri: list[str]) -> list[tuple]:
    blast = {r["id"]: r for r in ro.run("Q-BLAST-2", {"id": nid}).rows if r["id"] != nid}
    rows = []
    g = client.engine().select_graph(f"tenant_{tenant}")
    res = g.ro_query(OLD_NOTIFY_OWNERS, {"ids": sorted(blast), "now": now})
    cols = [c[1] if isinstance(c, (list, tuple)) else c for c in res.header]
    for t in [dict(zip(cols, r)) for r in res.result_set]:
        mine = [n for n in t["owns_impacted"] if n in blast]
        rows.append({**t, "impact": round(sum(tier_weight(blast[n]["tier"]) * float(blast[n]["max_cap"] or 0)
                                              / (1 + int(blast[n]["hops"])) for n in mine), 4),
                     "nearest_hops": min((int(blast[n]["hops"]) for n in mine), default=None),
                     "priority": [n for n in t["owns_impacted"] if n in set(pri)]})
    rows.sort(key=lambda x: (not x["priority"], -x["impact"], x["team"]))
    return [(x["team"], x["impact"], x["nearest_hops"], sorted(x["owns_impacted"]), sorted(x["oncall"]),
             sorted(x["priority"])) for x in rows[:20]]


def old_find(ro: RO, text: str, labels: list[str] | None, qv: list[float] | None) -> list[tuple]:
    q = T._ft_query(text)
    rows = []
    for label, tid in FIND.items():
        if not labels or label in labels:
            rows += [{**r, "via": "fulltext"} for r in ro.run(tid, {"text": q}).rows]
    floor = float(weights()["memory"]["find_min_similarity"])
    for label, tid in FIND_VEC.items():
        if qv is not None and (not labels or label in labels):
            rows += [{"id": r["id"], "label": r["label"], "score": round(float(r["similarity"]), 4), "via": "vector"}
                     for r in ro.run(tid, {"q": qv}).rows if float(r["similarity"]) >= floor]
    best: dict[str, dict] = {}
    for r in rows:
        b = best.get(r["id"])
        if b is None:
            best[r["id"]] = {**r, "via": [r["via"]]}
        else:
            b["via"] = sorted(set(b["via"]) | {r["via"]})
            b["score"] = max(float(b["score"]), float(r["score"]))
    merged = sorted(best.values(), key=lambda r: (-float(r["score"]), r["id"]))[:20]
    return [(x["id"], x["label"], x["score"], x["via"], x.get("status")) for x in merged]


def old_cut(ro: RO, f: str, prot: list[str]):
    try:
        flow = ro.run("Q-CUT-1", {"failing": f, "protect": prot})
        cand = ro.run("Q-CUT-2", {"failing": f})
        if cand.truncated:
            return "refused: region too large"
        row = flow.rows[0]
        edges = [(e["u"], e["v"], f"{e['u']}>{e['v']}") for e in cand.rows]
        cap = {f"{e['u']}>{e['v']}": float(e["cut_cost"]) for e in cand.rows}
        fl = {f"{u}>{v}": float(x) for (u, v), x in zip(row["flow_edges"], row["flows"])}
        cut, side = min_cut({f}, edges, cap, fl, float(row["max_flow"]), targets=set(prot))
        dom = {f"{e['u']}>{e['v']}": e["domain"] for e in cand.rows}
        return [(u, v, cap[eid], dom[eid]) for u, v, eid in cut], float(row["max_flow"]), sorted(side)
    except CutMismatch:
        return "refused: cut mismatch"


def new_cut(f: str, prot: list[str]):
    out = T.containment_cut(failing_id=f, protect_ids=prot)
    if "error" in out:
        return "refused: " + ("region too large" if "truncated" in out["error"] else "cut mismatch")
    return ([(c["u"], c["v"], c["cut_cost"], c["domain"]) for c in out["rows"]], float(out["max_flow"]),
            sorted(out["source_side"]))


# ------------------------------------------------------------------ the run
def node_ids(tenant: str) -> list[str]:
    g = client.engine().select_graph(f"tenant_{tenant}")
    return sorted(r[0] for r in g.ro_query("MATCH (n:Node) RETURN n.id").result_set)


def texts() -> list[str]:
    out: set[str] = set()
    for f in ("questions.truth.json", "paraphrases.truth.json"):   # the dev sets only: the blind sets stay unread
        for q in json.loads((ROOT / "data" / "brain" / f).read_text()).get("questions", []):
            if isinstance(q, dict) and (q.get("question") or q.get("q")):
                out.add(str(q.get("question") or q.get("q"))[:120])
    for t in TENANTS:
        g = client.engine().select_graph(f"tenant_{t}")
        out |= {r[0][:120] for r in g.ro_query("MATCH (n:Node) WHERE n.name IS NOT NULL RETURN n.name LIMIT 150").result_set}
    return sorted(x for x in out if len(x) >= 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "udf_equivalence.json"))
    a = ap.parse_args()
    t0 = time.time()
    loaded = udf.load_udfs(client.engine().connection)
    from faultline.memory.embed import embed_one

    rnd = random.Random(20261018)
    res = {k: {"k": 0, "n": 0, "first_diff": None} for k in ("blast", "notify", "find", "cut")}

    def tally(kind: str, same: bool, what: str) -> None:
        res[kind]["n"] += 1
        res[kind]["k"] += int(same)
        if not same and res[kind]["first_diff"] is None:
            res[kind]["first_diff"] = what

    corpus = texts()
    for tenant in TENANTS:
        ro = RO(tenant)
        ids = node_ids(tenant)
        tok = context.bind(tenant, record=False)
        try:
            for nid in ids:
                new = [(x["id"], x["hops"], x["impact"]) for x in T.blast_radius(id=nid)["rows"]]
                tally("blast", new == old_blast(ro, nid), f"{tenant}/{nid}")
                pri = sorted(rnd.sample(ids, 3)) if rnd.random() < 0.3 else []
                got = T.notify_set(target_id=nid, now=0, priority_ids=pri)["rows"]
                new = [(x["team"], x["impact"], x["nearest_hops"], sorted(x["owns_impacted"]), sorted(x["oncall"]),
                        sorted(x.get("priority", []))) for x in got]
                tally("notify", new == old_notify(ro, tenant, nid, 0, pri), f"{tenant}/{nid}")
            flow_nodes = {r[0] for r in client.engine().select_graph(f"tenant_{tenant}").ro_query(
                "MATCH (n:Node)-[:PROPAGATES_TO]->() RETURN DISTINCT n.id").result_set}
            for nid in sorted(flow_nodes):
                reach = [x["id"] for x in T.blast_radius(id=nid)["rows"] if x["id"] != nid]
                if reach:
                    prot = sorted(set(reach[:2] + rnd.sample(reach, min(2, len(reach)))))
                    tally("cut", new_cut(nid, prot) == old_cut(ro, nid, prot), f"{tenant}/{nid}/{prot}")
            for i, text in enumerate(corpus):
                labels = LABEL_SETS[i % len(LABEL_SETS)]
                got = T.find_entities(text=text, labels=labels)
                if "error" in got:
                    continue
                qv = embed_one(text) if (not labels or set(labels) & set(FIND_VEC)) else None
                new = [(x["id"], x["label"], x["score"], x["via"], x.get("status")) for x in got["rows"]]
                tally("find", new == old_find(ro, text, labels, qv), f"{tenant}/{text!r}/{labels}")
        finally:
            context.unbind(tok)
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "udf": loaded, "tenants": list(TENANTS),
           "texts": len(corpus), "seconds": round(time.time() - t0, 1), **res}
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: f"{v['k']}/{v['n']}" for k, v in res.items()}))
    return 0 if all(v["k"] == v["n"] for v in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
