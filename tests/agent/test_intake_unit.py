"""INTAKE (alert-storm correlation, M14 #2) without a graph: the stage whitelist, input validation, the scenario's late
intake windows, and how intake_round APPLIES group_alerts' decision (attach vs open). The grouping itself is the
graph's (algo.WCC); see tests/live/test_alert_storm.py."""

import pytest

from faultline import scenario
from faultline.agent import intake
from faultline.agent.phases import INTERNAL_TOOLS, PHASE_TOOLS
from faultline.agent.state import Stage
from faultline.graph import writes
from faultline.graph.algo import registry
from faultline.graph.templates import load
from faultline.ingest.clock import ANCHOR_MS
from faultline.mcp_server import tools as T


def test_group_alerts_is_an_internal_intake_tool():
    assert "group_alerts" in PHASE_TOOLS[Stage.INTAKE] and "group_alerts" in INTERNAL_TOOLS
    assert "group_alerts" in T.TOOLS


def test_storm_templates_lint_and_wcc_comes_from_the_registry():
    wcc = load("Q-STORM-WCC")
    assert registry.name("wcc") in wcc.text and "{algo:" not in wcc.text
    for tid in ("Q-ALERT-1", "Q-STORM-EDGES", "Q-STORM-ORIGINS", "Q-STORM-ATTACH", "Q-INC-ALERTS", "Q-PRIMARY-1"):
        assert load(tid).limit <= 100
    # one rule for both notions: the incident boundary (WCC projection) and the primary alert inside an incident
    assert "$carry_min" in load("Q-STORM-EDGES").text and "$carry_min" in load("Q-PRIMARY-1").text


def test_group_alerts_rejects_a_reversed_or_huge_window():
    assert "error" in T.group_alerts(since=10, until=5)
    assert "error" in T.group_alerts(since=0, until=7 * 3_600_000)


def test_link_alerts_validates_before_writing():
    with pytest.raises(writes.WriteError):
        writes.link_alerts(None, inc="i", links=[{"alert": "a", "how": "merged"}], evidence="ev")
    assert writes.link_alerts(None, inc="i", links=[], evidence="ev") == 0


def test_late_intake_rounds_come_from_the_scenario_config():
    p = scenario.Prepared(scenario.load("S1"), "acme", "eval_acme_x", ANCHOR_MS, "i", "r", [])
    assert scenario.late_rounds(p) == []  # every S1 alert fires in the onset round
    s14 = scenario.load("S14")
    onset = scenario.rel_ms(s14["onset"], ANCHOR_MS)
    p = scenario.Prepared(s14, "acme", "eval_acme_x", onset, "i", "r", [])
    late = max(scenario.rel_ms(a["at"], onset) for a in s14["alerts"])
    assert scenario.late_rounds(p) == [(onset + 60_000 + 1, late + 60_000)]


class _G:
    def __init__(self):
        self.calls = []


def _patch(monkeypatch, rows):
    calls = []
    monkeypatch.setattr(intake.client, "engine", lambda: type("E", (), {"select_graph": lambda self, n: _G()})())
    monkeypatch.setattr(intake.writes, "open_aux_run", lambda g, **k: calls.append(("aux", k["run"])))
    monkeypatch.setattr(intake.writes, "open_incident", lambda g, **k: calls.append(("open", k["inc"], [s["target"] for s in k["symptoms"]])))
    monkeypatch.setattr(intake.writes, "link_alerts", lambda g, **k: calls.append(("link", k["inc"], [(x["alert"], x["how"]) for x in k["links"]])))
    monkeypatch.setattr(intake.writes, "advance_stage", lambda g, **k: calls.append(("stage", k["inc"])))
    monkeypatch.setattr(intake.T, "group_alerts", lambda **k: {"rows": rows, "evidence_id": "ev_x"})
    # the crew record of the Triage step is a live-graph write (tests/live/test_crew.py); a no-op here
    import contextlib
    import types
    monkeypatch.setattr(intake.crew, "step", lambda **k: contextlib.nullcontext(types.SimpleNamespace(tool_calls=[], summary="")))
    return calls


def _alert(i, target, attach=()):
    return {"id": i, "target": target, "metric": "error_rate", "fired_at": 1, "attach": list(attach)}


def test_intake_round_attaches_what_the_graph_attached_and_opens_one_incident_per_remaining_group(monkeypatch):
    rows = [{"group": 1, "targets": ["a", "b"], "alerts": [_alert("x1", "a", [{"incident": "old", "hops": 2}]), _alert("x2", "b")]},
            {"group": 2, "targets": ["c"], "alerts": [_alert("x3", "c")]}]
    calls = _patch(monkeypatch, rows)
    rnd = intake.intake_round(tenant="acme", graph="eval_acme_x", since=0, until=1, onset=1, ids=[("i1", "r1"), ("i2", "r2")],
                              title="t", report="r", round_run="rr")
    assert rnd.attached == {"old": ["x1"]}
    assert [(o.incident_id, o.symptoms) for o in rnd.opened] == [("i1", ["b"]), ("i2", ["c"])]
    assert ("link", "old", [("x1", "attached")]) in calls and ("link", "i1", [("x2", "opened")]) in calls
    assert ("open", "i1", ["b"]) in calls and not any(c[0] == "open" and "a" in c[2] for c in calls)


def test_intake_round_fails_loudly_when_it_cannot_name_every_group(monkeypatch):
    rows = [{"group": k, "targets": [t], "alerts": [_alert(f"x{k}", t)]} for k, t in ((1, "a"), (2, "b"))]
    _patch(monkeypatch, rows)
    with pytest.raises(Exception, match="incident ids"):
        intake.intake_round(tenant="acme", graph="eval_acme_x", since=0, until=1, onset=1, ids=[("i1", "r1")],
                            title="t", report="r", round_run="rr")
