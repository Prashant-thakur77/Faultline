"""Does the portable skill (skills/no-path-no-claim) reach the full gate's verdicts? (M15 #5)

For each scenario, the product runs on a clean room (deterministic investigator); then the skill's four read-only
queries (the files in skills/no-path-no-claim/queries/, run verbatim as any agent with only a FalkorDB connection
would) decide on the same room. Compared: the change the skill names (exactly one survivor) vs the change the gate
confirmed, and, per suspect, the skill's G2/G5 verdict vs the gate's elimination by G2/G5.

    PYTHONPATH=backend uv run python scripts/skill_check.py [--scenarios S1,S2,…] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline import scenario  # noqa: E402
from faultline.agent.loop import BaselineInvestigator  # noqa: E402
from faultline.graph import client  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402

Q = ROOT / "skills" / "no-path-no-claim" / "queries"
SCENARIOS = ["S1", "S1b", "S2", "S3", "S3b", "S12", "S4S", "S4D"]
SLACK = 0.8
MIN = 60_000


def _q(name: str) -> str:
    return "\n".join(ln for ln in (Q / name).read_text().splitlines() if not ln.strip().startswith("//"))


def skill(graph: str, onset: int, symptom: str) -> dict:
    """The skill, exactly as SKILL.md describes it, over a read-only connection."""
    g = client.engine().select_graph(graph)
    ro = g.ro_query
    sus = ro(_q("1_suspects.cypher"), {"onset": onset, "window_ms": 30 * MIN}).result_set
    obs = ro(_q("3_observed.cypher"), {"symptom": symptom, "onset": onset, "base_since": onset - 30 * MIN,
                                         "base_until": onset - 5 * MIN, "until": onset + 10 * MIN}).result_set
    observed = obs[0][2] if obs else None
    verdicts = {}
    for change, _kind, comp, _at in sus:
        path = ro(_q("2_path.cypher"), {"change": change, "symptom": symptom}).result_set
        if not path:
            verdicts[change] = "G2"
            continue
        if comp == symptom:
            verdicts[change] = "pass"
            continue
        flow = ro(_q("4_flow.cypher"), {"component": comp, "symptom": symptom}).result_set
        mf = float(flow[0][0]) if flow and flow[0][0] is not None else 0.0
        verdicts[change] = "pass" if observed is not None and mf >= SLACK * float(observed) else "G5"
    survivors = sorted(c for c, v in verdicts.items() if v == "pass")
    return {"observed": observed, "verdicts": verdicts, "named": survivors[0] if len(survivors) == 1 else None,
            "survivors": survivors}


def run(scenarios: list[str]) -> dict:
    rows = []
    for sid in scenarios:
        p, r = anyio.run(lambda: scenario.run(sid, BaselineInvestigator(), set_mode=sid in ("S2", "S4D"), keep=True))
        try:
            s = skill(p.graph, p.onset_ms, p.symptoms[0])
        finally:
            gcopy.delete_if_exists(client.engine(), p.graph)
        gate = r.cause_id if r.outcome == "CONFIRMED" else None
        per = []
        for v in r.sweep or []:
            reason = v["reason"].split(":")[0]
            if v["status"] == "eliminated" and reason in ("G2", "G5") and v["change"] in s["verdicts"]:
                per.append(s["verdicts"][v["change"]] == reason)
        rows.append({"scenario": sid, "gate": gate, "gate_outcome": r.outcome, "skill": s["named"],
                     "skill_survivors": s["survivors"], "agree": gate == s["named"], "per_suspect_agree": per,
                     "skill_verdicts": s["verdicts"]})
    per_all = [x for r in rows for x in r["per_suspect_agree"]]
    with_cause = [r for r in rows if r["gate"]]
    return {"scenarios": len(rows), "agree": sum(r["agree"] for r in rows),
            "cause_scenarios": len(with_cause), "named_same": sum(r["agree"] for r in with_cause),
            "abstain_scenarios": len(rows) - len(with_cause), "abstain_same": sum(r["agree"] for r in rows if not r["gate"]),
            # the skill eliminating the gate's confirmed cause would be its worst error: counted on its own
            "cause_eliminated": sum(1 for r in with_cause if r["skill_verdicts"].get(r["gate"]) in ("G2", "G5")),
            "suspect_checks": len(per_all), "suspect_agree": sum(per_all), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run(a.scenarios.split(","))
    for x in r["rows"]:
        print(f"{x['scenario']}: gate {x['gate_outcome']} {x['gate']} | skill {x['skill']} (survivors {x['skill_survivors']})"
              f" | agree {x['agree']}")
    print(f"skill vs gate: {r['agree']}/{r['scenarios']} scenarios name the same cause (or both none); "
          f"{r['suspect_agree']}/{r['suspect_checks']} G2/G5 eliminations agree")
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
