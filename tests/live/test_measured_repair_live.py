"""Live (T1, M23): a keyless run proposes the data repair its own measurements support, and the world verifies it.

S2 (the cross-domain data incident) with the deterministic investigator: after the gate confirms the data cutover,
`unit_shift_check` finds that one segment of the anomalous column is a power of ten off (recorded as Evidence), the
transform the graph says WRITES that table gets its column scoped by a CASE, and the data_repair option is enabled
with that exact diff and a reasoning line that cites the evidence. Nothing is applied without the two-step approval;
the verification is the rebuild, the invariant suite and the KPI, and the write-back follows only APPLIED.
"""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from faultline import repair, scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
STG = "pipeline/transforms/stg_orders.sql"


@pytest.fixture(scope="module")
def s2():
    pristine = (ROOT / STG).read_text()
    p, res = anyio.run(lambda: scenario.run("S2", BaselineInvestigator(), set_mode=True, keep=True))
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    yield p, res, c, gh.client(p.graph)
    (ROOT / STG).write_text(pristine)
    repair.cleanup_backups()
    scenario.set_pipeline_mode("incident")
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_the_measured_repair_is_proposed_from_evidence_and_scoped_to_the_segment(s2):
    p, res, c, hub = s2
    assert res.outcome == "CONFIRMED" and res.cause_id == "D-cutover-1"
    o = next(o for o in res.post_gate["options"] if o["kind"] == "data_repair")
    assert o["enabled"], o["reason"]
    args = o["args"]
    assert args["file"] == STG
    assert "CASE WHEN payment_processor = 'cloudpay_v2' THEN (CAST(amount AS DOUBLE)) / 100 ELSE CAST(amount AS DOUBLE) END AS amount," in args["after"]
    added = [x for x in args["diff"].splitlines() if x.startswith("+") and not x.startswith("+++")]
    removed = [x for x in args["diff"].splitlines() if x.startswith("-") and not x.startswith("---")]
    assert args["after"].count("CASE WHEN") == 1 and len(added) == 1 and len(removed) == 1   # one line, nothing else
    assert "10^2 unit shift" in args["reasoning"] and "Evidence: ev_" in args["reasoning"]
    # the measurement is in the graph as this run's evidence, anomalous, about the table, the column and the segment
    rows = RO(p.tenant, p.graph).run("Q-EV-1", {"ids": [x.strip() for x in args["reasoning"].split("Evidence:")[1].split(",")]}).rows
    us = next(r for r in rows if r["kind"] == "unit_shift")
    assert us["anomalous"] and {"staging.stg_orders", "staging.stg_orders.amount", "staging.stg_orders.payment_processor"} <= set(us["about"])
    assert float(us["value"]) > 90


@pytest.mark.slow
def test_the_measured_repair_verifies_applied_through_the_rebuild_and_writes_back(s2):
    p, res, c, hub = s2
    o = next(o for o in res.post_gate["options"] if o["kind"] == "data_repair")
    spec = act.choose(c, o["id"], hub)
    assert spec["diff"].startswith("--- a/" + STG) and spec["args"]["fixture"]["mode"] == "incident"
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom="kpi.exec_revenue", onset_ms=p.onset_ms, effects=[], at_ms=p.onset_ms)
    assert v["verdict"] == "APPLIED", v
    assert v["channels"]["file"]["ok"] and v["channels"]["warehouse"]["ok"]
    assert act.write_back(c, o["id"], cause=res.cause_id, confident=True)["verified"] == "7/7"
