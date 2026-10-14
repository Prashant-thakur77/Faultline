"""Live: agent v2 end to end on the data scenarios with the deterministic investigator (keyless).
Grading reads the truth files here (tests/evals only; the product never reads them)."""

import json
from pathlib import Path

import anyio
import pytest

from faultline import scenario
from faultline.agent.loop import BaselineInvestigator

pytestmark = pytest.mark.live
TRUTH = Path(__file__).resolve().parents[2] / "data" / "scenarios"


def _run(sid):
    p, res = anyio.run(lambda: scenario.run(sid, BaselineInvestigator(), keep=False))
    return res, json.loads((TRUTH / f"{sid}.truth.json").read_text())


@pytest.fixture(scope="module", autouse=True)
def restore_fixture():
    yield
    scenario.set_pipeline_mode("incident")


def test_s2_confirms_cutover_and_rejects_fx_by_flow():
    res, truth = _run("S2")
    assert res.error is None and res.outcome == truth["outcome"] and res.cause_id == truth["cause"] and res.confident
    assert all(n in res.gate["chain"] for n in truth["path_contains"])
    sweep = {v["change"]: v for v in res.sweep}
    for d in truth["distractors"]:
        assert sweep[d]["status"] == "eliminated" and truth["distractor_rejected_by"] in sweep[d]["reason"]


def test_s4d_healthy_data_is_no_incident():
    res, truth = _run("S4D")
    assert res.error is None and res.outcome == truth["outcome"]


def test_s1_hero_confirms_payment_rejects_email_by_flow_and_rec_by_path():
    res, truth = _run("S1")
    assert res.error is None and res.outcome == truth["outcome"] and res.cause_id == truth["cause"] and res.confident
    assert all(n in res.gate["chain"] for n in truth["path_contains"])
    sweep = {v["change"]: v for v in res.sweep}
    for change, gate in truth["distractors"].items():
        assert sweep[change]["status"] == "eliminated" and sweep[change]["reason"].startswith(gate), sweep[change]
    assert {v["decision"] for v in res.gate["violations"]} == set(truth["violates"])


def test_s3_db_config_confirmed_and_unrelated_deploy_rejected_by_path():
    res, truth = _run("S3")
    assert res.error is None and res.outcome == truth["outcome"] and res.cause_id == truth["cause"] and res.confident
    assert all(n in res.gate["chain"] for n in truth["path_contains"])
    sweep = {v["change"]: v for v in res.sweep}
    for change, gate in truth["distractors"].items():
        assert sweep[change]["status"] == "eliminated" and sweep[change]["reason"].startswith(gate)
    assert {x["id"] for x in res.post_gate["options"]}  # a plan exists (containment around the datastore)


def test_s4s_benign_deploy_noisy_alert_is_no_incident():
    res, truth = _run("S4S")
    assert res.error is None and res.outcome == truth["outcome"]
    assert res.post_gate is None  # no plan, no action


def test_s12_no_change_explains_it_so_abstain_and_infer_the_origin():
    res, truth = _run("S12")
    assert res.error is None and res.outcome == truth["outcome"] and res.cause_id is None
    assert res.inferred["id"] == truth["inferred"] and truth["symptom"] in res.inferred["chain"]
    kinds = {o["kind"]: o["enabled"] for o in res.post_gate["options"]}
    assert "rollback_deploy" not in kinds and kinds["open_issue"]  # nothing to roll back; hand it to humans
