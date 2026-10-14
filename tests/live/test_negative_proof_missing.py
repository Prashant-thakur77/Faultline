"""Live: absence of data is not absence of an anomaly (N0, found by evals/robustness.py). A generated control world
(no fault) is NO_INCIDENT; the same world with its alerting symptom's error-rate windows deleted must not be: the
negative proof cannot measure the symptom, so the run abstains or escalates instead of declaring "no incident".
The second test is a world where that bug happened (it fails without N0: mutant M-N0-UNMEASURED)."""

import sys
import uuid
from pathlib import Path

import anyio
import pytest

from faultline import scenario
from faultline.agent.loop import BaselineInvestigator, run_incident
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes

pytestmark = pytest.mark.live
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))


def _run(case: dict, drop_symptom: bool) -> str:
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    try:
        if drop_symptom:
            writes.perturb_model(gclient.engine().select_graph(p.graph), drop_windows=[case["symptom"]])
        r = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                           symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                           run_id=p.run_id, window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    return r.outcome


def test_a_control_with_its_symptom_unmeasured_is_not_declared_no_incident(db):
    import gate_bench

    case = next(c for c in gate_bench.generate(seed=20261015) if c["expected"]["outcome"] == "NO_INCIDENT")
    assert _run(case, drop_symptom=False) == "NO_INCIDENT"
    assert _run(case, drop_symptom=True) in ("UNKNOWN_ESCALATED", "NOT_CONFIDENT")


def test_a_real_fault_with_its_symptom_unmeasured_is_not_declared_no_incident(db):
    """gb034 (a G5 world with a real fault): with the robustness eval's seeded 20% telemetry loss, which removes the
    symptom's windows, the remaining cited measurements are all in band. Without N0 this read as NO_INCIDENT."""
    import gate_bench
    import robustness

    case = next(c for c in gate_bench.generate(seed=20261015) if c["id"] == "gb034")
    r = robustness._run(case, "missing", 0.2)
    assert r["outcome"] != "NO_INCIDENT" and not r["wrong_confident"], r
