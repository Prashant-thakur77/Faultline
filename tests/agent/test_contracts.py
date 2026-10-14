"""Specialist contracts: exactly one typed object; prose, fences, schema errors and ungrounded
reports are rejected, retried once, then recorded as `insufficient`."""

import json
import types

import anyio
import pytest

from faultline.agent import contracts as C
from faultline.agent import specialists as S


def _good(**over):
    rep = {"contract_version": "1", "role": "code", "incident_id": "inc-1", "status": "complete",
           "suspect_ids": ["dep-9"], "evidence": [{"evidence_id": "ev_0123456789", "tool": "diff_summary",
                                                   "observations": ["code_on_target=true", "id=dep-9"]}],
           "unknowns": [], "limits": ["no function-level code graph"]}
    rep.update(over)
    return rep


def test_specialist_rejects_prose():
    with pytest.raises(C.ContractError, match="prose"):
        C.parse_report("The deploy dep-9 looks like the culprit to me.", role="code", incident_id="inc-1")
    with pytest.raises(C.ContractError, match="prose"):
        C.parse_report("Here is my report: " + json.dumps(_good()), role="code", incident_id="inc-1")


def test_specialist_rejects_fences_lists_and_non_objects():
    with pytest.raises(C.ContractError, match="fences"):
        C.parse_report("```json\n" + json.dumps(_good()) + "\n```", role="code", incident_id="inc-1")
    for bad in ([_good()], 42, None, "{not json}"):
        with pytest.raises(C.ContractError):
            C.parse_report(bad, role="code", incident_id="inc-1")


def test_contract_schema_is_strict():
    assert C.parse_report(json.dumps(_good()), role="code", incident_id="inc-1").suspect_ids == ["dep-9"]
    for bad in (_good(verdict="guilty"), _good(evidence=[]), _good(contract_version="2"), _good(role="oracle"),
                _good(evidence=[{"evidence_id": "ev_0123456789", "tool": "x", "observations": ["no equals sign"]}])):
        with pytest.raises(C.ContractError):
            C.parse_report(bad, role="code", incident_id="inc-1")
    with pytest.raises(C.ContractError, match="role mismatch"):
        C.parse_report(_good(), role="change", incident_id="inc-1")
    with pytest.raises(C.ContractError, match="incident mismatch"):
        C.parse_report(_good(), role="code", incident_id="inc-2")
    ins = C.insufficient("code", "inc-1", "nothing to inspect")
    assert ins.status == "insufficient" and not ins.suspect_ids and not ins.evidence


def test_observations_are_rederived_from_payloads():
    payload = {"rows": [{"id": "dep-9", "code_on_target": True, "chain": ["dep-9", "svc"], "w": 0.5}], "inspectable": True}
    have = C.flatten(payload)
    assert {C.obs("id", "dep-9"), C.obs("code_on_target", True), C.obs("chain", ["dep-9", "svc"]), C.obs("chain", "svc"),
            C.obs("w", 0.5), C.obs("inspectable", True)} <= have


class _FakeRO:
    def __init__(self, seen, evidence, payloads):
        self.seen, self.evidence, self.payloads = seen, evidence, payloads

    def run(self, tid, params):
        if tid == "Q-GATE-G1":
            return types.SimpleNamespace(rows=[{"seen": [i for i in params["ids"] if i in self.seen],
                                                "evidence": [e for e in params["evidence"] if e in self.evidence]}])
        if tid == "Q-EV-PAYLOAD":
            return types.SimpleNamespace(rows=[{"id": i, "payload": self.payloads.get(i)} for i in params["ids"]])
        raise AssertionError(tid)


def test_validation_against_the_run_rejects_unseen_suspects_foreign_evidence_and_invented_observations():
    rep = C.parse_report(_good(), role="code", incident_id="inc-1")
    payload = json.dumps({"rows": [{"id": "dep-9", "code_on_target": True}]})
    assert C.validate_against_run(rep, _FakeRO({"dep-9"}, {"ev_0123456789"}, {"ev_0123456789": payload}), "run-1") is rep
    with pytest.raises(C.ContractError, match="not seen"):
        C.validate_against_run(rep, _FakeRO(set(), {"ev_0123456789"}, {"ev_0123456789": payload}), "run-1")
    with pytest.raises(C.ContractError, match="not produced by this run"):
        C.validate_against_run(rep, _FakeRO({"dep-9"}, set(), {}), "run-1")
    lying = json.dumps({"rows": [{"id": "dep-9", "code_on_target": False}]})
    with pytest.raises(C.ContractError, match="observations not in the payload"):
        C.validate_against_run(rep, _FakeRO({"dep-9"}, {"ev_0123456789"}, {"ev_0123456789": lying}), "run-1")


def test_dispatch_rejects_a_prose_answer_retries_once_then_records_insufficient(monkeypatch):
    calls, done = [], []

    class Prose(S.Specialist):
        role = "code"

        async def run(self, ctx):
            calls.append(1)
            return "I think dep-9 did it."

    monkeypatch.setattr(S.writes, "claim_epoch", lambda g, **kw: 1)
    monkeypatch.setattr(S.writes, "complete_specialist_task", lambda g, **kw: done.append(kw) or True)
    run = types.SimpleNamespace(run_id="run-1", inc="inc-1", tenant="acme", graph="tenant_acme", g=lambda: None)
    out = anyio.run(lambda: S.dispatch(None, run, {"suspects": [], "symptoms": []}, roles=("code",),
                                       registry={"code": Prose}))
    d = out["code"]
    assert len(calls) == 2 and d.attempts == 2 and len(d.rejected) == 2 and "prose" in d.rejected[0]
    assert d.report.status == "insufficient" and not d.report.suspect_ids
    assert done[0]["status"] == "insufficient" and done[0]["names"] == [] and done[0]["report"]["rejected"] == d.rejected


def test_dispatch_runs_nothing_when_another_dispatch_owns_the_work_item(monkeypatch):
    ran = []

    class Never(S.Specialist):
        role = "code"

        async def run(self, ctx):  # pragma: no cover
            ran.append(1)

    monkeypatch.setattr(S.writes, "claim_epoch", lambda g, **kw: 0)
    monkeypatch.setattr(S, "RO", lambda t, g: types.SimpleNamespace(
        run=lambda tid, p: types.SimpleNamespace(rows=[{"owner": "code-specialist-other"}])))
    run = types.SimpleNamespace(run_id="run-1", inc="inc-1", tenant="acme", graph="tenant_acme", g=lambda: None)
    out = anyio.run(lambda: S.dispatch(None, run, {"suspects": [], "symptoms": []}, roles=("code",),
                                       registry={"code": Never}))
    assert not ran and out["code"].skipped and out["code"].owner == "code-specialist-other" and out["code"].report is None


def test_work_item_id_is_stable_for_the_same_run_role_and_scope():
    p = {"suspects": [{"id": "b"}, {"id": "a"}], "symptoms": ["s"]}
    assert S.work_item("run-1", "code", p) == S.work_item("run-1", "code", {"suspects": [{"id": "a"}, {"id": "b"}],
                                                                           "symptoms": ["s"]})
    assert S.work_item("run-1", "code", p) != S.work_item("run-1", "data", p)
    assert S.work_item("run-1", "code", p) != S.work_item("run-1", "code", {**p, "symptoms": ["t"]})
