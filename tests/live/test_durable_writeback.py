"""Live (M20 #5): on the pinned engine (appendonly yes, appendfsync everysec) the hero write-back is fsynced before
VERIFY counts it, and a WAITAOF that cannot be satisfied in time comes back as a timeout (ok False), which the
write-back turns into UNKNOWN."""

import anyio
import pytest

from faultline import scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy

pytestmark = pytest.mark.live


def test_waitaof_on_the_writing_connection_and_its_timeout(db, scratch):
    with gclient.engine_session(scratch.name) as (g, conn):
        g.query("CREATE (:Probe {x: 1})")
        ok = gclient.wait_aof(conn, timeout_ms=2000)
        assert ok["ok"] and ok["local"] == 1, ok
        late = gclient.wait_aof(conn, timeout_ms=50, numreplicas=1)     # no replica exists: the engine times out
        assert not late["ok"] and late["replicas"] == 0 and "timed out" in late["error"]


@pytest.mark.parametrize("fail", [False, True], ids=["durable", "not-on-disk"])
def test_hero_write_back_is_on_disk_before_it_is_counted(fail, monkeypatch):
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    try:
        c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
        hub = gh.client(p.graph)
        eff = scenario.effects_of(scenario.load("S1"), p.onset_ms)
        o = next(x for x in res.post_gate["options"] if x["kind"] == "flip_flag" and x["enabled"])
        spec = act.choose(c, o["id"], hub)
        act.approve(c, o["id"], spec["plan_hash"], "p-030")
        act.execute(c, o["id"], hub)
        v = act.verify(c, o["id"], hub, symptom="checkout", onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 300_000)
        assert v["verdict"] == "APPLIED"
        if fail:   # the engine's own timeout reply, as WAITAOF gives it when the fsync does not happen in time
            real = gclient.wait_aof
            monkeypatch.setattr(act.gclient, "wait_aof", lambda conn, timeout_ms: real(conn, timeout_ms=50, numreplicas=1))
        wb = act.write_back(c, o["id"], cause=res.cause_id, confident=True, precedents=[])
        if fail:
            assert wb["verified"] == "0/7" and "durability UNKNOWN" in wb["reread_error"] and not wb["durable"]["ok"]
        else:
            assert wb["verified"] == "7/7" and wb["durable"]["ok"] and wb["durable"]["local"] == 1, wb
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
