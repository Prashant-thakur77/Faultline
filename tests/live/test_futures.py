"""Live: futures (M14 #1) on the hero incident. Every containment candidate gets its own GRAPH.COPY branch and a
predicted outcome from Q-FUTURE-1 (measured excess × path transfer); the options carry it, are ordered by it, and
verification records whether it came true. Also: the simulated world keeps its base rates across verification."""

import json

import anyio
import pytest

from faultline import scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent.datatools import band_from, in_band
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO
from faultline.sim.telemetry import simulate

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def hero():
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    assert res.outcome == "CONFIRMED" and res.post_gate
    yield p, res
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def _fut(res) -> dict:
    return {x["key"]: x for x in res.post_gate["futures"]["rows"]}


def test_each_candidate_has_its_own_predicted_future(hero):
    """S1: payment fails into checkout (service edge) and raw_orders (data edge, feeding the revenue KPI)."""
    _, res = hero
    f = _fut(res)
    assert set(f) == {"payment|checkout", "payment|raw.raw_orders", "min_cut", "remove_origin", "no_change"}
    assert f["payment|checkout"]["predicted"] == "contains"
    assert f["payment|checkout"]["exposed"] == ["kpi.exec_revenue"]          # the data path still carries the fault
    assert f["payment|raw.raw_orders"]["predicted"] == "does_not_contain"     # the user-facing symptoms stay out
    assert f["min_cut"]["predicted"] == "contains" and f["min_cut"]["exposed"] == []
    assert f["remove_origin"]["predicted"] == "contains" and f["remove_origin"]["exposed"] == []
    assert f["no_change"]["predicted"] == "does_not_contain"
    nc = {s["id"]: s for s in f["no_change"]["symptoms"]}
    assert nc["checkout"]["residual"] > 0.3 and nc["checkout"]["ok"] is False
    assert f["payment|checkout"]["removed_edges"] == 1 and f["payment|checkout"]["branch"].startswith("whatif_")
    assert f["no_change"]["branch"] is None                                   # nothing to cut: no branch


def test_branches_are_deleted(hero):
    assert not [g for g in gclient.engine().list_graphs() if g.startswith("whatif_")]


def test_the_excess_is_what_the_graph_measured(hero):
    """Q-FUTURE-1's origin excess = peak since onset − pre-onset mean of payment's own windows (Q-MW-1)."""
    p, res = hero
    ro = RO(p.tenant, p.graph)
    base = [r["value"] for r in ro.run("Q-MW-1", {"target": "payment", "metric": "error_rate",
                                                  "since": p.onset_ms - 30 * 60_000, "until": p.onset_ms - 5 * 60_000}).rows]
    peak = max(r["value"] for r in ro.run("Q-MW-1", {"target": "payment", "metric": "error_rate", "since": p.onset_ms,
                                                     "until": p.onset_ms + 10 * 60_000}).rows)
    got = _fut(res)["no_change"]["origin_excess"]
    assert got == pytest.approx(peak - sum(base) / len(base), abs=1e-6)


def test_options_carry_their_future_in_order_and_in_the_graph(hero):
    p, res = hero
    opts = res.post_gate["options"]
    assert opts[0]["kind"] == "rollback_deploy" and opts[0]["future"]["predicted"] == "contains"
    flag = next(o for o in opts if o["kind"] == "flip_flag" and o["enabled"])
    assert flag["future"]["key"] == "payment|checkout" and "leaves kpi.exec_revenue exposed" in flag["reason"]
    issue = next(o for o in opts if o["kind"] == "open_issue")
    assert issue["future"]["predicted"] == "does_not_contain"
    no_lever = next(o for o in opts if o["kind"] == "flip_flag" and not o["enabled"])
    assert "future" not in no_lever                                           # not offered, not simulated
    stored = {a["id"]: a for a in RO(p.tenant, p.graph).run("Q-ACT-1", {"inc": p.incident_id}).rows}
    assert json.loads(stored[flag["id"]]["future"])["predicted"] == "contains"
    assert stored[no_lever["id"]]["future"] is None


def test_verification_records_whether_the_prediction_came_true(monkeypatch):
    import faultline.sim.telemetry as tel

    seen = []
    real = tel.simulate
    monkeypatch.setattr(tel, "simulate", lambda *a, **k: seen.append(k.get("base_seed")) or real(*a, **k))
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    try:
        c, hub = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id), gh.client(p.graph)
        o = next(o for o in res.post_gate["options"] if o["kind"] == "flip_flag" and o["enabled"])
        spec = act.choose(c, o["id"], hub)
        act.approve(c, o["id"], spec["plan_hash"], "p-030")
        act.execute(c, o["id"], hub)
        v = act.verify(c, o["id"], hub, symptom=p.symptoms, onset_ms=p.onset_ms,
                       effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 5 * 60_000)
        assert v["verdict"] == "APPLIED"
        assert seen[-1] == 42  # verification's windows use the world's base rates (scenario seed), not the noise seed
        pr = v["channels"]["prediction"]
        assert pr["predicted"] == "contains" and pr["observed"] == "contains" and pr["agrees"] is True
        assert pr["key"] == "payment|checkout" and pr["evidence_id"] == res.post_gate["futures"]["evidence_id"]
        from faultline.agent import report

        md = report.to_markdown(report.build(p.tenant, p.graph, p.incident_id, res.outcome))
        assert "## Futures" in md
        row = next(ln for ln in md.splitlines() if ln.startswith(f"| {o['option']} |"))
        assert "| contains |" in row and row.endswith("| APPLIED | yes |") and "kpi.exec_revenue exposed" in row
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_the_world_keeps_its_base_rates_after_an_action(hero):
    """Windows appended after an action with the world's seed: with the fault gone, every component is back in its
    own band for any noise seed (before the fix, the base rates were re-drawn from the noise seed)."""
    p, _ = hero
    g, ro = gclient.engine().select_graph(p.graph), RO(p.tenant, p.graph)
    for i, noise in enumerate((7, 1234, 9001)):
        at = p.onset_ms + (60 + 10 * i) * 60_000
        simulate(g, ro, onset_ms=p.onset_ms, effects=[], start_ms=at, minutes=3, seed=noise, base_seed=42)
        for t in ("checkout", "frontend", "payment", "email", "currency"):
            after = [r["value"] for r in ro.run("Q-MW-1", {"target": t, "metric": "error_rate", "since": at,
                                                           "until": at + 3 * 60_000}).rows]
            base_vals = [r["value"] for r in ro.run("Q-MW-1", {"target": t, "metric": "error_rate",
                                                               "since": p.onset_ms - 30 * 60_000,
                                                               "until": p.onset_ms - 5 * 60_000}).rows]
            base = sum(base_vals) / len(base_vals)
            assert len(after) == 3 and all(in_band(v, base, band_from(base_vals)) for v in after), (noise, t, after, base)


def test_caps_become_unknown_rows_with_the_reason(hero):
    """Review fix 5: what futures cannot simulate is listed as unknown with why, never dropped or half-read."""
    from faultline.mcp_server import context
    from faultline.mcp_server import tools as T

    p, _ = hero
    tok = context.bind(p.tenant, run_id=p.run_id, graph=p.graph, record=False)
    try:
        cands = [{"key": f"c{i}"} for i in range(T.FUTURE_MAX + 2)] + [
            {"key": "wide", "cut_edges": [["payment", f"x{i}"] for i in range(T.FUTURE_MAX_CUTS + 1)]}]
        cands = [cands[-1]] + cands[:-1]
        out = T.futures(origin_id="payment", onset=p.onset_ms, now=p.onset_ms + 600_000, candidates=cands,
                        symptom_ids=p.symptoms, protect_ids=[], keep_connected_ids=[])
        by = {x["key"]: x for x in out["rows"]}
        assert len(by) == len(cands)                                              # nothing dropped
        assert by["wide"]["predicted"] == "unknown" and "cut edges" in by["wide"]["line"]
        over = [k for k, x in by.items() if "not simulated" in x["line"]]
        assert len(over) == len(cands) - T.FUTURE_MAX and all(by[k]["predicted"] == "unknown" for k in over)
        many = T.futures(origin_id="payment", onset=p.onset_ms, now=p.onset_ms + 600_000, candidates=[{"key": "n"}],
                         symptom_ids=[f"s{i}" for i in range(T.FUTURE_MAX_SYMS + 1)], protect_ids=[], keep_connected_ids=[])
        assert many["rows"][0]["predicted"] == "unknown" and "symptoms" in many["rows"][0]["line"]
    finally:
        context.unbind(tok)
