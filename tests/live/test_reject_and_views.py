"""Live (M13 workstream C): POST /reject over HTTP on the hero scenario, and the read-only GETs behind the UI's
naive-vs-Faultline toggle, Memory tab and Brain widgets. Keyless; every S1 run happens in its own graph copy."""

import time

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy

pytestmark = pytest.mark.live
REASON = "prefer a rollback over a flag flip during the freeze"


def _wait(client, inc, stages, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(f"{inc} did not reach {stages} (last {st})")


@pytest.fixture(scope="module")
def hero():
    api._rate.clear()
    with TestClient(api.app) as client:
        r = client.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
        inc, graph = r["incident"], r["graph"]
        try:
            assert _wait(client, inc, {"AWAITING_APPROVAL", "FAILED", "UNKNOWN_ESCALATED"}) == "AWAITING_APPROVAL"
            yield client, inc
        finally:
            gcopy.delete_if_exists(gclient.engine(), graph)


def _reject(client, inc, aid, plan_hash, approver="p-030", reason=REASON):
    return client.post(f"/api/incidents/{inc}/reject",
                       json={"action_id": aid, "plan_hash": plan_hash, "approver": approver, "reason": reason})


def test_rejected_option_is_recorded_and_cannot_be_approved(hero):
    client, inc = hero
    api._rate.clear()
    plan = client.get(f"/api/incidents/{inc}/plan").json()
    opt = next(o for o in plan["options"] if o["enabled"] and o["kind"] != "open_issue")
    spec = client.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()

    assert _reject(client, inc, opt["id"], spec["plan_hash"], reason="no").status_code == 422          # reason too short
    assert _reject(client, inc, opt["id"], spec["plan_hash"], reason="   x   ").status_code == 422     # blank after trim
    assert _reject(client, inc, opt["id"], spec["plan_hash"], approver="not-a-person").status_code == 422
    assert _reject(client, inc, opt["id"], "0" * 64).status_code == 409                              # stale hash

    ok = _reject(client, inc, opt["id"], spec["plan_hash"])
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["rejected"] and body["status"] == "rejected" and body["stage"] == "AWAITING_APPROVAL"
    assert body["approver"]["id"] == "p-030" and body["reason"] == REASON

    # re-read from the graph: the option is disabled with who/why/when, and the incident still awaits a human
    after = client.get(f"/api/incidents/{inc}/plan").json()
    o = next(x for x in after["options"] if x["id"] == opt["id"])
    assert o["status"] == "rejected" and o["enabled"] is False
    assert o["rejected_by"] == "p-030" and o["reject_reason"] == REASON and isinstance(o["rejected_at"], int)
    assert o["reason"] == opt["reason"]                                       # why it was offered: kept
    assert after["stage"] == "AWAITING_APPROVAL"
    notes = [s["note"] for s in client.get(f"/api/incidents/{inc}").json()["stages"]]
    assert any(f"{opt['id']} rejected by p-030" in (n or "") for n in notes)

    # a rejected option can be neither approved (same hash), re-chosen nor rejected again
    assert client.post(f"/api/incidents/{inc}/approve",
                       json={"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": "p-030"}).status_code == 409
    assert client.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).status_code == 409
    assert _reject(client, inc, opt["id"], spec["plan_hash"]).status_code == 409

    # the human can still choose another offered option
    other = next((x for x in after["options"] if x["enabled"]), None)
    assert other is not None, "no other option left after the rejection"
    assert client.post(f"/api/incidents/{inc}/choose", json={"action_id": other["id"]}).status_code == 200


def test_contrast_reads_the_runs_recorded_suspects(hero):
    client, inc = hero
    c = client.get(f"/api/incidents/{inc}/contrast").json()
    assert c["unavailable"] is None and c["changes"] and c["naive"]
    deploys = [x["deploy"] for x in c["changes"]]
    assert set(c["naive"]) <= set(deploys)
    ats = [x["at"] for x in c["changes"]]
    assert ats == sorted(ats, reverse=True)                          # Q-SUS-2 order: newest first
    assert all(x["at"] == ats[0] for x in c["changes"] if x["deploy"] in c["naive"])
    conf = [x for x in c["changes"] if x["confirmed"]]
    assert len(conf) == 1 and conf[0]["deploy"] == c["confirmed"] and conf[0]["gate_status"] == "confirmed"
    assert c["window_changes"]["template"] == "Q-SUS-2" and c["window_changes"]["evidence_id"]
    assert all(x["before_onset_ms"] >= 0 for x in c["changes"])


def test_memory_overview_for_a_run_incident(hero):
    client, inc = hero
    m = client.get("/api/memory/overview", params={"incident": inc}).json()
    assert m["graph"].startswith("tenant_acme") or "acme" in m["graph"]
    fam = m["families"]
    assert "error" not in fam and fam["template"] == "Q-MEM-6" and fam["rows"]
    assert fam["rows"][0]["mine"] is True and inc in fam["rows"][0]["incidents"]
    rb = m["runbooks"]
    assert rb["template"] == "Q-MEM-RB" and rb["rows"]
    derived = [r for r in rb["rows"] if r["source"] == "derived"]
    assert derived and all(r["support"] >= 1 and r["derived_from"] for r in derived)
    assert rb["rows"][: len(derived)] == derived                     # derived runbooks first
    rec = m["recall"]
    assert "error" not in rec and rec["rows"]
    assert {"similarity", "recency", "salience", "shared"} <= set(rec["rows"][0])
    assert m["recalled"]["template"] == "Q-MEM-4" and m["recalled"]["rows"]


def test_memory_overview_tenant_level_and_seeded_incident():
    with TestClient(api.app) as client:
        m = client.get("/api/memory/overview").json()
        assert m["graph"] == "tenant_acme" and "recall" not in m
        assert m["families"]["rows"] and not any(r["mine"] for r in m["families"]["rows"])
        seeded = m["families"]["rows"][0]["incidents"][0]
        one = client.get("/api/memory/overview", params={"incident": seeded}).json()
        assert one["graph"] == "tenant_acme" and one["families"]["rows"][0]["mine"] is True
        assert client.get("/api/memory/overview", params={"incident": "inc-does-not-exist"}).status_code == 404
        assert client.get("/api/memory/overview", params={"tenant": "no such"}).status_code == 422


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_brain_widgets_read_the_tenant_graph(tenant):
    with TestClient(api.app) as client:
        q = {"tenant": tenant}
        dec = client.get("/api/brain/decisions", params=q).json()
        assert dec["template"] == "Q-DEC-LIST" and dec["rows"]
        sup = next(d for d in dec["rows"] if d["superseded_by"])            # every seeded tenant has a superseded ADR
        tr = client.get(f"/api/brain/decisions/{sup['id']}", params=q).json()
        assert tr["trace"]["rows"][0]["head"] != sup["id"]
        chain = [d["id"] for d in tr["chain"]["rows"]]
        assert sup["id"] in chain and tr["trace"]["rows"][0]["head"] in chain and len(chain) >= 2
        assert client.get("/api/brain/decisions/ADR-does-not-exist", params=q).status_code == 404

        own = client.get("/api/brain/ownership", params=q).json()
        assert own["template"] == "Q-OWN-MAP" and own["rows"] and all(r["owns"] for r in own["rows"])
        comp = own["rows"][0]["owns"][0]
        at = client.get(f"/api/brain/ownership/{comp}", params=q).json()
        assert "error" not in at and at["owner_now"] == own["rows"][0]["team"]

        g = client.get("/api/brain/guardrails", params=q).json()
        assert "error" not in g["missing_guardrails"] and g["missing_guardrails"]["template"] == "Q-GAP-1"
        kh = g["knowledge_health"]
        assert "error" not in kh and {"Q-KH-1", "Q-KH-2", "Q-KH-3", "Q-COUPLE-1"} <= set(kh["templates"])


def test_views_are_tenant_bound():
    """A globex read never sees an acme decision (isolation through the API, not just the tools)."""
    with TestClient(api.app) as client:
        acme = {d["id"]: d["title"] for d in client.get("/api/brain/decisions").json()["rows"]}
        globex = {d["id"]: d["title"] for d in client.get("/api/brain/decisions", params={"tenant": "globex"}).json()["rows"]}
        assert all(acme.get(k) != v for k, v in globex.items())


def test_rejecting_every_option_escalates_to_a_human():
    """When no enabled option is left after a rejection, the incident must not wait in AWAITING_APPROVAL forever:
    it moves to UNKNOWN_ESCALATED with the reason (a second conditional query; a no-op while options remain)."""
    api._rate.clear()
    with TestClient(api.app) as client:
        r = client.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
        inc, graph = r["incident"], r["graph"]
        try:
            assert _wait(client, inc, {"AWAITING_APPROVAL", "FAILED", "UNKNOWN_ESCALATED"}) == "AWAITING_APPROVAL"
            live = [o for o in client.get(f"/api/incidents/{inc}/plan").json()["options"] if o["enabled"]]
            assert len(live) >= 2
            for n, opt in enumerate(live, 1):
                api._rate.clear()
                spec = client.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()
                body = _reject(client, inc, opt["id"], spec["plan_hash"]).json()
                last = n == len(live)
                assert body["stage"] == ("UNKNOWN_ESCALATED" if last else "AWAITING_APPROVAL")
                assert body.get("escalated", False) is last
            view = client.get(f"/api/incidents/{inc}").json()
            assert view["incident"]["stage"] == "UNKNOWN_ESCALATED"
            assert any("every offered option was rejected" in (s["note"] or "") for s in view["stages"])
            assert client.post(f"/api/incidents/{inc}/choose", json={"action_id": live[0]["id"]}).status_code == 409
        finally:
            gcopy.delete_if_exists(gclient.engine(), graph)
