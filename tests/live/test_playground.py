"""Live, M15 #2: break the graph. One change to a GRAPH.COPY of the hero room, the product run on both rooms, the
decision diff. Pins what each change does, and that no change ever makes the product blame the wrong deploy."""

import pytest
from fastapi.testclient import TestClient

from faultline import api, playground
from faultline.graph import client

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def runs():
    return {k: playground.run(k) for k in ("cut_proof_path", "email_critical", "top_responder_leaves")}


def test_removing_the_proof_path_withdraws_the_claim_and_blames_nobody(runs):
    r = runs["cut_proof_path"]
    assert r["before"]["outcome"] == "CONFIRMED" and r["before"]["proof_path"]
    assert r["after"]["cause"] is None and r["after"]["outcome"] != "CONFIRMED" and r["after"]["proof_path"] == []
    sus = {d["decision"]: d for d in r["diff"] if d["decision"].startswith("suspect ")}
    real = next(d for d in sus.values() if d["before"]["status"] == "candidate")
    assert real["after"]["reason"].startswith("G2") and "Q-GATE-1" in real["templates"]
    assert r["applied"]["deleted"] == 1


def test_another_check_holds_when_one_is_moved(runs):
    """Raising the email call's capacity takes G5 away from the decoy; G4 origin still eliminates it."""
    r = runs["email_critical"]
    assert r["before"]["cause"] == r["after"]["cause"] is not None
    moved = [d for d in r["diff"] if d["changed"]]
    assert len(moved) == 1 and moved[0]["before"]["reason"].startswith("G5") and moved[0]["after"]["reason"].startswith("G4")


def test_the_top_responder_leaving_changes_who_is_paged(runs):
    r = runs["top_responder_leaves"]
    gone = r["before"]["who_fixes"][0]
    assert r["applied"]["deactivated"] == 1 and gone not in r["after"]["who_fixes"]
    assert r["before"]["cause"] == r["after"]["cause"]          # the people graph never moves the verdict


def test_both_rooms_are_deleted(runs):
    assert not [g for g in client.engine().list_graphs() if "_play" in g or "play_" in g]


def test_api_menu_and_unknown_kind():
    with TestClient(api.app) as c:
        m = c.get("/api/playground").json()
        assert len(m["perturbations"]) == len(playground.perturbations()) >= 5
        assert all(p["expect"] and p["algorithm"] for p in m["perturbations"])
        assert c.post("/api/playground/drop_everything").status_code == 404


def test_a_run_is_recorded_in_the_audit_graph_and_the_public_demo_serves_it(monkeypatch):
    """Prejudge 2026-10-13: the diff is a FalkorDB record (audit_<t> PlaygroundRun), and the public demo serves the
    recorded diff instead of copying rooms again."""
    from faultline.config import settings
    from faultline.graph.ro import RO

    with TestClient(api.app) as c:
        fresh = c.post("/api/playground/email_critical").json()
        assert fresh["cached"] is False
        rec = RO("acme", "audit_acme").run("Q-PLAY-LAST", {"kind": "email_critical"}).rows
        assert rec and '"changed"' in rec[0]["result"]
        monkeypatch.setattr(settings, "faultline_public", True)
        served = c.post("/api/playground/email_critical").json()
        assert served["cached"] is True and served["changed"] == fresh["changed"]
