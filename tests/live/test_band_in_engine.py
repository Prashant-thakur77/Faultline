"""Live (M20 #4): the gate's band is computed in FalkorDB (Q-BASE-BAND / Q-MW-BAND: avg, stDevP, percentileCont) and
equals the Python reference `band_from` (4-place rounding) on:

* every healthy baseline series of both seeded tenants (acme, globex);
* the simulated error-rate windows of a scenario room, for every component and every onset minute it can have;
* zero-heavy, discrete series like real telemetry (FaultBench-OTel: healthy services report exactly 0 errors).

The verdict-level proof (identical gate verdicts on the scenario suite and the gate bench) is the replay and the
recorded gate bench (`evals/replay_examples.py`, `evals/gate_bench.py --check-recorded`), run in `make judge-check`.
"""

import uuid

import anyio
import pytest

from faultline import scenario
from faultline.agent import datatools as D
from faultline.agent.loop import BaselineInvestigator
from faultline.agent.weights import weights
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
MIN = 60_000


def _kf() -> dict:
    g = weights()["gate"]
    return {"k": float(g["band_k"]), "floor": float(g["band_floor"])}


def _engine(ro: RO, tid: str, params: dict) -> float:
    return round(float(ro.run(tid, {**params, **_kf()}).rows[0]["band"]), 4)


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_every_seeded_baseline_band_is_the_same_in_the_engine(db, tenant):
    golden = f"golden_{tenant}"
    if golden not in db.list_graphs():
        pytest.skip(f"{golden} not seeded")
    pairs = db.select_graph(golden).ro_query(
        "MATCH (w:MetricWindow {kind:'baseline'}) RETURN DISTINCT w.target_id, w.metric ORDER BY w.target_id, w.metric"
    ).result_set
    if not pairs:
        pytest.skip(f"{golden} has no healthy baseline series (a services-only tenant)")
    ro = RO(tenant, golden)
    for target, metric in pairs:
        series = ro.run("Q-BASE-1", {"target": target, "metric": metric})
        assert not series.truncated, (target, metric)          # the reference reads the whole series
        want = D.band_from([float(r["value"]) for r in series.rows])
        assert _engine(ro, "Q-BASE-BAND", {"target": target, "metric": metric}) == want, (target, metric)


def test_scenario_error_rate_bands_are_the_same_at_every_onset():
    p, _ = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    try:
        ro = RO(p.tenant, p.graph)
        targets = [r[0] for r in gclient.engine().select_graph(p.graph).ro_query(
            "MATCH (w:MetricWindow {kind:'live', metric:'error_rate'}) RETURN DISTINCT w.target_id ORDER BY w.target_id"
        ).result_set]
        assert targets
        compared = 0
        for t in targets:
            for onset in range(p.onset_ms - 10 * MIN, p.onset_ms + 6 * MIN, MIN):
                rows = ro.run("Q-MW-1", {"target": t, "metric": "error_rate", "since": onset - 30 * MIN, "until": onset}).rows
                base = [r["value"] for r in rows if r["at"] <= onset - 5 * MIN]
                if not base:
                    continue
                got = _engine(ro, "Q-MW-BAND", {"target": t, "metric": "error_rate", "since": onset - 30 * MIN,
                                                "until": onset - 5 * MIN})
                assert got == D.band_from(base), (t, onset)
                compared += 1
        assert compared >= 20
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


@pytest.mark.parametrize("values", [
    [0.0] * 25,                                       # a healthy service on real telemetry: exact zeros
    [0.0] * 24 + [0.02],                              # one nonzero window: floor
    [0.0, 0.02, 0.02, 0.04, 0.0, 1 / 30, 0.05, 0.0, 0.02, 0.02],   # discrete counts / calls
    [0.011, 0.0123, 0.0145, 0.0101, 0.0133, 0.012, 0.0117, 0.0109],
    [0.25, 0.75],                                     # high variation: band above the floor
], ids=["all-zero", "one-nonzero", "discrete", "noisy", "wide"])
def test_zero_heavy_and_discrete_series(db, values):
    name = f"scratch_acme_band_{uuid.uuid4().hex[:6]}"
    g = db.select_graph(name)
    try:
        g.query("UNWIND range(0, size($v) - 1) AS i CREATE (:MetricWindow {id: 'w' + toString(i), target_id: 'svc', "
                "metric: 'error_rate', kind: 'live', at: i * 60000, value: $v[i]})", {"v": values})
        ro = RO("acme", name)
        got = _engine(ro, "Q-MW-BAND", {"target": "svc", "metric": "error_rate", "since": 0, "until": 10 ** 9})
        assert got == D.band_from(values)
    finally:
        g.delete()


def test_metric_window_tool_uses_the_engine_band(monkeypatch):
    """The gate's own tool takes its band from Q-MW-BAND (the Python reference is not called on that path)."""
    p, _ = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    from faultline.mcp_server import context

    try:
        monkeypatch.setattr(D, "band_from", lambda v: (_ for _ in ()).throw(AssertionError("Python band used")))
        tok = context.bind(p.tenant, graph=p.graph)
        try:
            out = D.metric_window(target_id="checkout", onset_ms=p.onset_ms)
        finally:
            context.unbind(tok)
        assert "error" not in out, out
        assert out["band_engine"]["template"] == "Q-MW-BAND" and out["band"] >= _kf()["floor"]
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
