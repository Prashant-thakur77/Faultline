"""judge-check: FalkorDB's own view after the test run. Fails if any product template sits in GRAPH.SLOWLOG above
engine.slow_template_ms (weights.yaml); prints memory per tenant graph (GRAPH.MEMORY USAGE).

The gate's hot path runs in eval_* clean rooms that runs delete when they finish, taking their slow logs with them, so
this check also runs ONE S1 clean room itself (deterministic investigator, no LLM) and reads that room's slow log
before deleting it. Clean rooms that still exist at check time are covered by tenant_report as well."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.agent.weights import weights  # noqa: E402
from faultline.graph import engine_info  # noqa: E402


def _clean_room_slowlog(sid: str = "S1") -> tuple[str, dict]:
    """Run one scenario in a fresh clean room (keyless) and read its slow log and memory before deleting the room."""
    import anyio

    from faultline import scenario
    from faultline.agent.loop import BaselineInvestigator, run_incident
    from faultline.graph import client
    from faultline.graph import copy as gcopy

    p = scenario.prepare(sid, set_mode=False)
    try:
        anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms, symptoms=p.symptoms,
                                       investigator=BaselineInvestigator(), graph=p.graph, run_id=p.run_id,
                                       window_min=p.scenario.get("window_min")))
        mem = engine_info.memory(p.graph)
        return p.graph, {"total_mb": mem.get("total_graph_sz_mb"), "slow": engine_info.slowlog(p.graph)[:10]}
    finally:
        gcopy.delete_if_exists(client.engine(), p.graph)


def main() -> int:
    budget = float(weights()["engine"]["slow_template_ms"])
    over, mem, worst = [], [], (0.0, None)
    graphs: dict[str, dict] = {}
    for t in ("acme", "globex"):
        graphs.update(engine_info.tenant_report(t)["graphs"])
    room, x = _clean_room_slowlog("S1")
    graphs[room] = x
    evals = 0
    for g, x in graphs.items():
        if g.startswith("eval_") and g != room:
            evals += 1  # existing clean rooms: slow log checked, memory not listed (there can be many)
        else:
            mem.append(f"{g} {x['total_mb']} MB" + (" (S1 clean room, read before deletion)" if g == room else ""))
        for s in x["slow"]:
            if s["template"] and s["ms"] > worst[0]:
                worst = (s["ms"], s["template"])
            if s["template"] and s["ms"] > budget:
                over.append(f"{s['template']} {s['ms']:.0f} ms on {g}")
    if evals:
        mem.append(f"{evals} other clean rooms checked")
    slowest = f"slowest template {worst[1]} {worst[0]:.0f} ms" if worst[1] else "no template in the slow log"
    print(f"{slowest} (budget {budget:.0f} ms); " + ", ".join(mem) + (f"; OVER: {', '.join(over)}" if over else ""))
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
