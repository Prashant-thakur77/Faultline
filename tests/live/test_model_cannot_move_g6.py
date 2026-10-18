"""Live: whatever an investigator (a model) does, it cannot remove a rival cause from the gate's way.

Found by the pre-registered LLM-driven run on the deep bench (2026-10-18): in a two-causes-in-a-chain world both
changes can carry the impact, so the deterministic investigator abstains; a model that marked the rival
"eliminated" (with any evidence id of the run) made G6 pass and the gate confirm one change. Now elimination is the
graph's alone (the sweep and the gate, by G2 or G5): the investigator tool refuses it, and G6 ignores an elimination
an investigator asserted even if one is written another way. No API key is needed: a scripted investigator does
what the model did.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import anyio
import pytest

from faultline import scenario
from faultline.agent.loop import run_incident
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))


class RivalEliminator:
    """Proposes one of two jointly sufficient changes after trying to eliminate the other, as the model did."""

    name = "scripted: eliminates the rival, then asks the gate"

    def __init__(self):
        self.refused: dict | None = None
        self.tool_wrote: list = []

    async def investigate(self, box, run, packet):
        from faultline.agent import specialists

        reports = await specialists.dispatch(box, run, packet)       # the measurements every investigator cites
        evidence = specialists.measurement_evidence(reports)
        swept = [v.__dict__ for v in run.gate.sweep()]
        cands = sorted(v["change"] for v in swept if v["status"] == "candidate")
        assert len(cands) == 2, swept
        for keep in cands:     # both orders: one of them passes every other check (as the model's choice did)
            rival = next(c for c in cands if c != keep)
            out = run.update_hypothesis(rival, "eliminated", evidence, "the model is sure")
            self.refused = self.refused or out
            # the tool must not have written an elimination, whatever it answered
            st = {h["cause"]: (h["status"], h.get("status_by"))
                  for h in RO(run.tenant, run.graph).run("Q-HYP-1", {"inc": run.inc}).rows}
            self.tool_wrote.append(st.get(rival))
            # even an elimination written around the tool (an investigator's, not the graph's) must not count
            writes.upsert_hypothesis(run.g(), inc=run.inc, hid=f"hyp-{run.inc}-{rival}", cause=rival,
                                     status="eliminated", reason="asserted, not shown", refutes=[], origin="investigator")
            got = await box.call("confirm_root_cause", {"cause_id": keep, "evidence_ids": evidence})
            if got.get("accepted"):
                break
        await box.call("finish", {"summary": "scripted"})


def test_a_model_cannot_eliminate_a_rival_and_win_g6(db):
    import deep_bench

    # db063: the world where the model's elimination made the gate confirm (every check but G6 passes for one change)
    case = next(c for c in deep_bench.generate(seed=deep_bench.FRESH_SEED) if c["id"] == "db063")
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    inv = RivalEliminator()
    try:
        res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                             symptoms=p.symptoms, investigator=inv, graph=p.graph, run_id=p.run_id,
                                             window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    assert inv.refused and "gate" in inv.refused.get("error", "")      # the tool refuses the elimination
    assert ("eliminated", "investigator") not in inv.tool_wrote          # and writes none
    assert res.outcome != "CONFIRMED" and not res.confident              # and G6 still sees the rival
