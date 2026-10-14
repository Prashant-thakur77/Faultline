"""Memory that changes the answer (PREREGISTRATION amendment 2026-10-13, M15 #4), sequential.

The held-out gate-bench worlds (seed 20261015) whose true cause is on a different component than the symptom (a
multi-hop path exists). For each:
  incident 1  the world's telemetry is generated from the TRUE topology; then one PROPAGATES_TO edge on the
              cause → symptom path (seeded choice) is deleted from the graph the product reads. The product runs.
  human fix   the eval plays the human: it names the true cause (memory/edges.py::human_fix_option), the rollback
              goes through choose → approve(plan hash) → execute → verify on the simulated TRUE world (a copy of the
              room taken before the edge was hidden: the product's graph is wrong, the world is not). If verification
              says APPLIED, the product proposes learned edges (Q-LEARN-GAP) and the eval approves each, two-step.
  incident 2  a fresh room of the same world (new change and alert ids, same effect, true telemetry), the same edge
              hidden, and the approved learned edges carried in (the tenant graph keeps them; eval rooms are copies of
              golden, so they are written in with writes.perturb_model(learned=…)). The product runs.
  control     incident 2 again, nothing learned.
Graded with the bench's own grader on remapped ids. Wrong-confident = a confirmed blame of another change than the
true cause, or of a change where none should be blamed.

    PYTHONPATH=backend uv run python evals/learning_eval.py [--out FILE]
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
import time
import uuid
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if __import__("importlib.util").util.find_spec("gate_bench") is None:
    sys.path.insert(0, str(ROOT / "evals"))

import gate_bench  # noqa: E402
from faultline import scenario  # noqa: E402
from faultline.actions import act  # noqa: E402
from faultline.actions import github as gh  # noqa: E402
from faultline.agent.loop import BaselineInvestigator, run_incident  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph import writes  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.tenant import eval_graph  # noqa: E402
from faultline.memory import edges  # noqa: E402

SEED = 20261015
HUMAN = "p-030"   # an active acme person plays the reviewer (act-level approval; the API checks authority)


def _run(p):
    return anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                          symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                          run_id=p.run_id, window_min=p.scenario.get("window_min")))


def _got(r) -> dict:
    blamed = r.cause_id if r.outcome == "CONFIRMED" else None
    return {"outcome": r.outcome, "cause": blamed, "sweep": {v["change"]: f"{v['status']}: {v['reason']}" for v in r.sweep}}


def _wrong_confident(exp: dict, got: dict) -> bool:
    return got["cause"] is not None and (exp["outcome"] != "CONFIRMED" or got["cause"] != exp["cause"])


def _hidden_edge(p, case: dict) -> tuple[str, str] | None:
    chain = RO(p.tenant, p.graph).run("Q-GATE-1", {"cause": case["expected"]["cause"], "symptom": case["symptom"]}).rows
    ch = chain[0]["chain"] if chain else []
    hops = [(ch[i], ch[i + 1]) for i in range(1, len(ch) - 1)]  # component → component hops (not the CHANGED hop)
    if not hops:
        return None
    return random.Random(f"{int(case['spec']['seed']) ^ 0x1EA}:hide").choice(hops)


def _respec(case: dict, fresh: bool = False) -> tuple[dict, dict]:
    """Incident 2 of the same world: new change and alert ids, the same targets, effect and distractors. `fresh`: a
    different world seed (other base rates and noise), the topology, effect and hidden edge unchanged."""
    spec, rnd = copy.deepcopy(case["spec"]), random.Random(f"{case['spec']['seed']}:second")
    if fresh:
        spec["seed"] = (int(spec["seed"]) * 7919 + 13) % 9_973 + 1
    ids = {x["change"]: "D-" + "".join(rnd.choice("0123456789abcdef") for _ in range(8)) for x in spec["inject"]}
    for x in spec["inject"]:
        x["change"] = ids[x["change"]]
    for e in spec.get("effects", []):
        if e.get("change"):
            e["change"] = ids[e["change"]]
    for a in spec["alerts"]:
        a["id"] = "al-" + "".join(rnd.choice("0123456789abcdef") for _ in range(8))
    exp = copy.deepcopy(case["expected"])
    exp["cause"] = ids.get(exp["cause"], exp["cause"])
    exp["eliminated"] = {ids[k]: v for k, v in exp["eliminated"].items()}
    return spec, exp


def _second(case: dict, hide: tuple[str, str], learned: list[dict], fresh: bool = False) -> dict:
    spec, exp = _respec(case, fresh)
    p = scenario.prepare(spec["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=spec)
    try:
        writes.perturb_model(gclient.engine().select_graph(p.graph), delete=[list(hide)], learned=learned or None)
        r = _run(p)
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    got = _got(r)
    return {"outcome": r.outcome, "blamed": got["cause"], "wrong_confident": _wrong_confident(exp, got),
            "chain": list((r.gate or {}).get("chain") or []), **gate_bench.grade(exp, got)}


def wrong_guess(case: dict) -> dict:
    """The human names a decoy (the first eliminated distractor): the rollback must verify NOT_APPLIED on the true
    world and teach nothing."""
    db = gclient.engine()
    decoy = sorted(case["expected"]["eliminated"])[0]
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    world = eval_graph(p.tenant, f"w{uuid.uuid4().hex[:6]}", "world", "bench", 1)
    try:
        hide = _hidden_edge(p, case)
        gcopy.copy_graph(db, p.graph, world)
        writes.perturb_model(db.select_graph(p.graph), delete=[list(hide)])
        _run(p)
        c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
        hub = gh.client(p.graph)
        act.ensure_infra_repo(c, hub)
        try:
            opt = edges.human_fix_option(c, change=decoy, by=HUMAN, why="learning eval: a wrong guess")
        except ValueError as e:
            return {"decoy": decoy, "verdict": None, "proposals": 0, "error": str(e)}
        spec = act.choose(c, opt["id"], hub)
        act.approve(c, opt["id"], spec["plan_hash"], HUMAN)
        act.execute(c, opt["id"], hub)
        v = act.verify(c, opt["id"], hub, symptom=p.symptoms, onset_ms=p.onset_ms,
                       effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 300_000,
                       world_seed=int(p.scenario.get("seed", 42)), world_graph=world)
        props = edges.propose(c, opt["id"], onset_ms=p.onset_ms, symptoms=p.symptoms)
        return {"decoy": decoy, "verdict": v["verdict"], "proposals": len(props)}
    finally:
        gcopy.delete_if_exists(db, p.graph)
        gcopy.delete_if_exists(db, world)


def run_case(case: dict) -> dict | None:
    t0 = time.perf_counter()
    db = gclient.engine()
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    world = eval_graph(p.tenant, f"w{uuid.uuid4().hex[:6]}", "world", "bench", 1)
    learned: list[dict] = []
    try:
        hide = _hidden_edge(p, case)
        if hide is None:
            return None
        gcopy.copy_graph(db, p.graph, world)  # the TRUE world, kept apart: verification simulates over it
        writes.perturb_model(db.select_graph(p.graph), delete=[list(hide)])
        r1 = _run(p)
        got1 = _got(r1)
        out = {"id": case["id"], "category": case["category"], "hidden": list(hide), "incident1": {
            "outcome": r1.outcome, "blamed": got1["cause"], "wrong_confident": _wrong_confident(case["expected"], got1)}}
        fix = {"verdict": None, "proposals": [], "approved": 0}
        try:
            c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
            hub = gh.client(p.graph)
            act.ensure_infra_repo(c, hub)
            opt = edges.human_fix_option(c, change=case["expected"]["cause"], by=HUMAN, why="learning eval: the human names the cause")
            spec = act.choose(c, opt["id"], hub)
            act.approve(c, opt["id"], spec["plan_hash"], HUMAN)
            act.execute(c, opt["id"], hub)
            v = act.verify(c, opt["id"], hub, symptom=p.symptoms, onset_ms=p.onset_ms,
                           effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 300_000,
                           world_seed=int(p.scenario.get("seed", 42)), world_graph=world)
            fix["verdict"] = v["verdict"]
            for prop in edges.propose(c, opt["id"], onset_ms=p.onset_ms, symptoms=p.symptoms):
                fix["proposals"].append({k: prop[k] for k in ("id", "src", "dst", "cap")})
                if edges.approve(c, prop["id"], prop["plan_hash"], HUMAN):
                    fix["approved"] += 1
            if fix["approved"]:
                rows = db.select_graph(p.graph).ro_query(
                    "MATCH (a)-[e:PROPAGATES_TO]->(b) WHERE e.learned RETURN a.id, b.id, e.k, properties(e)").result_set
                learned = [{"id": k.removeprefix("learned:"), "src": a, "dst": b, "props": dict(pr)} for a, b, k, pr in rows]
        except (ValueError, KeyError) as e:  # e.g. the incident is in a stage a human fix cannot reopen
            fix["error"] = str(e)
        out["human_fix"] = fix
    finally:
        gcopy.delete_if_exists(db, p.graph)
        gcopy.delete_if_exists(db, world)
    out["wrong_guess"] = wrong_guess(case)
    out["incident2_learned"] = _second(case, hide, learned)
    out["incident2_control"] = _second(case, hide, [])
    out["incident2_fresh"] = _second(case, hide, learned, fresh=True)
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def run(seed: int = SEED, progress: bool = True) -> dict:
    t0 = time.perf_counter()
    cases = [c for c in gate_bench.generate(seed=seed)
             if c["expected"]["outcome"] == "CONFIRMED" and c["origin"] != c["symptom"]]
    rows = []
    for case in cases:
        r = run_case(case)
        if r is None:
            continue
        rows.append(r)
        if progress:
            print(f"[learning] {r['id']} hid {'→'.join(r['hidden'])}: i1 {r['incident1']['outcome']}, fix "
                  f"{r['human_fix'].get('verdict')}, proposals {len(r['human_fix']['proposals'])}, "
                  f"i2 learned {r['incident2_learned']['outcome']}/{r['incident2_learned']['correct']}, "
                  f"control {r['incident2_control']['outcome']}/{r['incident2_control']['correct']}", file=sys.stderr, flush=True)
    n = len(rows)
    s = {"seed": seed, "cases": n,
         "i1_wrong_confident": sum(r["incident1"]["wrong_confident"] for r in rows),
         "i1_abstained": sum(1 for r in rows if r["incident1"]["blamed"] is None),
         "fix_applied": sum(1 for r in rows if r["human_fix"].get("verdict") == "APPLIED"),
         "proposals": sum(len(r["human_fix"]["proposals"]) for r in rows),
         "approved": sum(r["human_fix"]["approved"] for r in rows),
         "i2_learned_correct": sum(r["incident2_learned"]["correct"] for r in rows),
         "i2_learned_wrong_confident": sum(r["incident2_learned"]["wrong_confident"] for r in rows),
         "i2_control_correct": sum(r["incident2_control"]["correct"] for r in rows),
         "i2_control_wrong_confident": sum(r["incident2_control"]["wrong_confident"] for r in rows),
         "i2_fresh_correct": sum(r["incident2_fresh"]["correct"] for r in rows),
         "i2_fresh_wrong_confident": sum(r["incident2_fresh"]["wrong_confident"] for r in rows),
         "wrong_guess_not_applied": sum(1 for r in rows if r["wrong_guess"]["verdict"] == "NOT_APPLIED"),
         "wrong_guess_proposals": sum(r["wrong_guess"]["proposals"] for r in rows),
         "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
