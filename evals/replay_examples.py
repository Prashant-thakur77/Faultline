"""Replay the gate verdicts of every committed examples/<run>/ (§12.2 "replay gate verdicts").

For each recorded incident run, re-run its scenario on a fresh GRAPH.COPY clean room of the golden graph with the
deterministic investigator, read the new run's GateRuns from the graph (Q-INC-GATES) and compare them with the
committed gate_runs.json: every recorded verdict (cause, sweep|confirm, passed, confident) must reproduce, and for
the confirm run, every check present in both must have the same result. For the preflight record (S6) the same PR is
preflighted again on a clean room: verdict, risk and contradicted decisions must reproduce.

    PYTHONPATH=backend uv run python evals/replay_examples.py          # prints "replay gate verdicts k/k"
"""

from __future__ import annotations

import json
import sys
import uuid
from collections import Counter
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))

EXAMPLES = ROOT / "examples"


def _verdicts(gates: list[dict]) -> Counter:
    return Counter((g["cause"], g["origin"], bool(g["passed"]), bool(g["confident"])) for g in gates)


def _confirm_checks(gates: list[dict]) -> dict[str, bool | None]:
    conf = [g for g in gates if g["origin"] == "confirm"]
    if not conf:
        return {}
    checks = conf[-1]["checks"]
    checks = json.loads(checks) if isinstance(checks, str) else checks
    return {c["name"]: c["passed"] for c in checks}


def replay_incident(d: Path, man: dict) -> dict:
    from faultline import scenario
    from faultline.agent.loop import BaselineInvestigator
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.ro import RO

    sid = man.get("base_scenario") or man["scenario"]
    s = scenario.load(sid)
    rec = json.loads((d / "gate_runs.json").read_text())
    p, res = anyio.run(lambda: scenario.run(sid, BaselineInvestigator(), set_mode=bool(s.get("pipeline_mode")), keep=True))
    try:
        new = RO(p.tenant, p.graph).run("Q-INC-GATES", {"inc": p.incident_id}).rows
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    want, got = _verdicts(rec), _verdicts(new)
    matched = sum((want & got).values())
    cw, cg = _confirm_checks(rec), _confirm_checks(new)
    diff_checks = sorted(k for k in set(cw) & set(cg) if cw[k] != cg[k])
    return {"run": d.name, "scenario": sid, "recorded": sum(want.values()), "matched": matched,
            "missing": sorted(map(list, (want - got).elements())), "extra": sorted(map(list, (got - want).elements())),
            "confirm_check_diffs": diff_checks, "outcome": res.outcome,
            "ok": matched == sum(want.values()) == sum(got.values()) and not diff_checks}


def replay_preflight(d: Path, man: dict) -> dict:
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.preflight.engine import PreflightIn, run

    rec = json.loads((d / "preflight.json").read_text())
    room = f"eval_acme_replay_{uuid.uuid4().hex[:8]}"
    db = gclient.engine()
    gcopy.copy_graph(db, "golden_acme", room)
    try:
        r = run("acme", PreflightIn(**rec["input"]), graph=room)
    finally:
        gcopy.delete_if_exists(db, room)
    want = (rec["result"]["verdict"], rec["result"]["risk"], sorted(x["id"] for x in rec["result"]["decision_links"]))
    got = (r["verdict"], r["risk"], sorted(x["id"] for x in r["decision_links"]))
    return {"run": d.name, "scenario": man.get("scenario"), "recorded": 1, "matched": int(want == got),
            "recorded_verdict": list(want), "replayed_verdict": list(got), "ok": want == got}


def run_all(dirs: list[Path] | None = None) -> dict:
    from faultline import scenario

    out = []
    try:
        for d in dirs or sorted(p for p in EXAMPLES.iterdir() if (p / "manifest.json").exists()):
            man = json.loads((d / "manifest.json").read_text())
            if man.get("kind") == "preflight":
                out.append(replay_preflight(d, man))
            elif (d / "gate_runs.json").exists():
                out.append(replay_incident(d, man))
    finally:
        scenario.set_pipeline_mode("incident")  # S2 replays rebuild the data fixture; leave the default one
    return {"runs": out, "recorded": sum(r["recorded"] for r in out), "matched": sum(r["matched"] for r in out),
            "ok": all(r["ok"] for r in out)}


def main() -> int:
    dirs = [Path(x) for x in sys.argv[1:]] or None
    res = run_all(dirs)
    for r in res["runs"]:
        if not r["ok"]:
            print(f"  {r['run']}: {json.dumps({k: v for k, v in r.items() if k not in ('run',)})}", file=sys.stderr)
    print(f"replay gate verdicts {res['matched']}/{res['recorded']} ({len(res['runs'])} runs"
          + ("" if res["ok"] else f"; {sum(not r['ok'] for r in res['runs'])} differ") + ")")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
