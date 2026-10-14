"""Live: the single action path on the hero incident (simulated GitHub, keyless).
choose → approve(plan hash) → execute → verify (3-valued, 2nd channel) → write-back → verified n/m."""

import json
from pathlib import Path

import anyio
import pytest

from faultline import scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes

pytestmark = pytest.mark.live


@pytest.fixture
def hero():
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    assert res.outcome == "CONFIRMED" and res.post_gate
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    s = scenario.load("S1")
    eff = scenario.effects_of(s, p.onset_ms)
    yield p, res, c, gh.client(p.graph), eff  # each run's graph has its own simulated world
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def _flag_option(res):
    return next(o for o in res.post_gate["options"] if o["kind"] == "flip_flag" and o["enabled"])


def test_full_loop_applied_and_writeback_verified(hero):
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    assert spec["branch"].startswith("faultline/fix-") and "Faultline-Idem:" in spec["commit"]
    assert act.approve(c, o["id"], spec["plan_hash"], "p-030")["mine"]
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom="checkout", onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "APPLIED" and v["channels"]["github_main"]["ok"] and v["channels"]["telemetry"]["ok"]
    wb = act.write_back(c, o["id"], cause=res.cause_id, confident=True, precedents=[])
    assert wb["verified"] == "7/7"


def test_stale_plan_hash_is_refused_and_approval_is_idempotent(hero):
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    assert act.approve(c, o["id"], "0" * 64, "p-030") is None            # stale hash → 409
    first = act.approve(c, o["id"], spec["plan_hash"], "p-030")
    assert first and first["state"] == "PENDING"
    assert act.approve(c, o["id"], spec["plan_hash"], "p-030") is None  # not 'chosen' any more → no second intent
    n = c.g().ro_query("MATCH (it:Intent {idem:$i}) RETURN count(it)", {"i": spec["idem"]}).result_set[0][0]
    assert n == 1


def test_execute_requires_approval(hero):
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    act.choose(c, o["id"], hub)
    with pytest.raises(PermissionError):
        act.execute(c, o["id"], hub)


def test_s5_bad_fix_is_not_applied_and_writes_no_success(hero):
    """Rolling back the innocent same-minute email deploy does not bring checkout back: NOT_APPLIED."""
    p, res, c, hub, eff = hero
    aid = f"act-{c.inc}-bad"
    writes.record_option(c.g(), inc=c.inc, aid=aid, kind="rollback_deploy", option="roll back D-email-88", enabled=True,
                         reason="forced bad plan (S5)", target="email",
                         preview={"repo": act.INFRA_REPO, "path": act.DEPLOYS_PATH, "service": "email", "revert": "D-email-88"})
    spec = act.choose(c, aid, hub)
    act.approve(c, aid, spec["plan_hash"], "p-030")
    act.execute(c, aid, hub)
    v = act.verify(c, aid, hub, symptom="checkout", onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "NOT_APPLIED" and "out of band" in v["explanation"]
    wb = act.write_back(c, aid, cause=res.cause_id, confident=True, precedents=[])
    assert wb["written"] is None
    assert c.g().ro_query("MATCH (pm:Postmortem {id:$p}) RETURN count(pm)", {"p": f"pm-{c.inc}"}).result_set[0][0] == 0
    assert c.g().ro_query("MATCH (it:Intent {idem:$i}) RETURN it.state", {"i": spec["idem"]}).result_set[0][0] == "FAILED"


def test_s9_github_timeout_is_unknown_and_escalated(hero):
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    hub.fail_next = "timeout"  # the verification read of main HEAD times out
    v = act.verify(c, o["id"], hub, symptom="checkout", onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "UNKNOWN" and v["explanation"]
    wb = act.write_back(c, o["id"], cause=res.cause_id, confident=True, precedents=[])
    assert wb["not_applied"]["stage"] == "UNKNOWN_ESCALATED" and wb["not_applied"]["intent"] == "PENDING"


def test_unknown_without_explanation_is_a_programming_error(hero):
    p, res, c, hub, eff = hero
    with pytest.raises(writes.WriteError):
        writes.record_verdict(c.g(), aid="x", verdict="UNKNOWN", why="  ", channels={})


def test_only_fix_branches_can_be_touched():
    hub = gh.SimGitHub()
    hub.seed("o/r", "f", "x")
    with pytest.raises(gh.GitHubError):
        hub.create_branch("o/r", "main-hotfix")


def _world(p, eff):
    return lambda inc: {"symptom": "checkout", "onset_ms": p.onset_ms, "effects": eff, "at_ms": p.onset_ms + 5 * 60_000}


def test_reconciler_resolves_s9_unknown_once_github_is_readable(hero):
    """S9 continued: verification timed out (UNKNOWN, intent PENDING); later the reconciler finds the change at main
    HEAD by its idem key, re-verifies through both channels and writes back."""
    from faultline.actions import reconcile

    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    hub.fail_next = "timeout"
    assert act.verify(c, o["id"], hub, symptom="checkout", onset_ms=p.onset_ms, effects=eff,
                      at_ms=p.onset_ms + 5 * 60_000)["verdict"] == "UNKNOWN"
    act.write_back(c, o["id"], cause=res.cause_id, confident=True)
    # too young: left alone
    assert reconcile.reconcile(c.tenant, c.graph, hub, _world(p, eff), older_than_ms=10 * 60_000) == []
    out = reconcile.reconcile(c.tenant, c.graph, hub, _world(p, eff), older_than_ms=0)
    assert [(x["found"], x["verdict"], x["writeback"]) for x in out] == [("at_main", "APPLIED", "7/7")]
    st = c.g().ro_query("MATCH (i:Incident {id:$i}) MATCH (it:Intent {idem:$d}) RETURN i.stage, it.state",
                        {"i": c.inc, "d": spec["idem"]}).result_set[0]
    assert st == ["RESOLVED", "COMMITTED"]
    assert reconcile.reconcile(c.tenant, c.graph, hub, _world(p, eff), older_than_ms=0) == []  # idempotent


def test_reconciler_voids_an_approval_that_never_reached_github(hero):
    """Crash between approve and execute: nothing at main HEAD ⇒ NOT_APPLIED, intent FAILED, no success write-back."""
    from faultline.actions import reconcile

    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    out = reconcile.reconcile(c.tenant, c.graph, hub, _world(p, eff), older_than_ms=0)
    assert [(x["found"], x["verdict"]) for x in out] == [("absent", "NOT_APPLIED")]
    st = c.g().ro_query("MATCH (it:Intent {idem:$d}) RETURN it.state", {"d": spec["idem"]}).result_set[0][0]
    assert st == "FAILED"
    assert c.g().ro_query("MATCH (pm:Postmortem {id:$p}) RETURN count(pm)", {"p": f"pm-{c.inc}"}).result_set[0][0] == 0


def test_reconciler_keeps_pending_while_github_is_unreadable(hero):
    from faultline.actions import reconcile

    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    hub.fail_next = "timeout"
    out = reconcile.reconcile(c.tenant, c.graph, hub, _world(p, eff), older_than_ms=0)
    assert [(x["found"], x["verdict"]) for x in out] == [("unreadable", "UNKNOWN")]
    st = c.g().ro_query("MATCH (it:Intent {idem:$d}) RETURN it.state", {"d": spec["idem"]}).result_set[0][0]
    assert st == "PENDING"


# The test (not the product) knows the repair: it plays the specialist that proposes a patch in live mode.
_CENTS_FIX = (Path(__file__).resolve().parents[2] / "pipeline" / "transforms" / "stg_orders.sql").read_text().replace(
    "    CAST(amount AS DOUBLE) AS amount,",
    "    CASE WHEN payment_processor = 'cloudpay_v2' AND CAST(order_ts AS TIMESTAMP) >= TIMESTAMP '2026-08-07 00:00:00'\n"
    "         THEN CAST(amount AS DOUBLE) / 100.0 ELSE CAST(amount AS DOUBLE) END AS amount,")


@pytest.mark.slow
def test_s2_data_repair_is_gated_applied_and_verified_by_rebuild():
    from faultline import repair

    path = Path(__file__).resolve().parents[2] / "pipeline" / "transforms" / "stg_orders.sql"
    original = path.read_text()
    p, res = anyio.run(lambda: scenario.run("S2", BaselineInvestigator(), set_mode=True, keep=True))
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    try:
        assert res.outcome == "CONFIRMED" and res.cause_id == "D-cutover-1"
        o = next(o for o in res.post_gate["options"] if o["kind"] == "data_repair")
        assert not o["enabled"]  # keyless: nobody authored a patch, so it is not offered
        with pytest.raises(ValueError):  # repairs may only touch allowlisted transforms
            act.propose_data_repair(c, file="pipeline/run.py", new_content="x", reasoning="nope")
        act.propose_data_repair(c, file="pipeline/transforms/stg_orders.sql", new_content=_CENTS_FIX,
                                reasoning="normalise cloudpay_v2 integer cents to dollars after the cutover")
        hub = gh.client(p.graph)
        spec = act.choose(c, o["id"], hub)
        assert spec["diff"].startswith("--- a/pipeline/transforms/stg_orders.sql")
        act.approve(c, o["id"], spec["plan_hash"], "p-030")
        act.execute(c, o["id"], hub)
        v = act.verify(c, o["id"], hub, symptom="kpi.exec_revenue", onset_ms=p.onset_ms, effects=[], at_ms=p.onset_ms)
        assert v["verdict"] == "APPLIED", v
        assert v["channels"]["file"]["ok"] and v["channels"]["warehouse"]["ok"]
        assert act.write_back(c, o["id"], cause=res.cause_id, confident=True)["verified"] == "7/7"
    finally:
        path.write_text(original)
        repair.cleanup_backups()
        scenario.set_pipeline_mode("incident")
        gcopy.delete_if_exists(gclient.engine(), p.graph)


@pytest.mark.slow
def test_s2_wrong_data_repair_is_not_applied_and_reverted():
    from faultline import repair

    path = Path(__file__).resolve().parents[2] / "pipeline" / "transforms" / "stg_orders.sql"
    original = path.read_text()
    p, res = anyio.run(lambda: scenario.run("S2", BaselineInvestigator(), set_mode=True, keep=True))
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    try:
        o = next(o for o in res.post_gate["options"] if o["kind"] == "data_repair")
        act.propose_data_repair(c, file="pipeline/transforms/stg_orders.sql",
                                new_content=original.replace("-- stg_orders: cleaned order stream.",
                                                             "-- stg_orders: cleaned order stream (touched)."),
                                reasoning="a cosmetic change that cannot fix the KPI")
        hub = gh.client(p.graph)
        spec = act.choose(c, o["id"], hub)
        act.approve(c, o["id"], spec["plan_hash"], "p-030")
        act.execute(c, o["id"], hub)
        v = act.verify(c, o["id"], hub, symptom="kpi.exec_revenue", onset_ms=p.onset_ms, effects=[], at_ms=p.onset_ms)
        assert v["verdict"] == "NOT_APPLIED" and "reverted" in v["explanation"]
        assert path.read_text() == original
        assert act.write_back(c, o["id"], cause=res.cause_id, confident=True)["written"] is None
    finally:
        path.write_text(original)
        repair.cleanup_backups()
        scenario.set_pipeline_mode("incident")
        gcopy.delete_if_exists(gclient.engine(), p.graph)


# ---------------------------------------------------------------- safety envelope (review M5)
def _options(res, kind):
    return [o for o in res.post_gate["options"] if o["kind"] == kind and o["enabled"]]


def test_rechoosing_voids_the_previous_choice(hero):
    """choose A → choose B → approve A with A's hash is refused (409): only the CURRENT choice can be approved."""
    p, res, c, hub, eff = hero
    a = _flag_option(res)
    b = _options(res, "rollback_deploy")[0]
    spec_a = act.choose(c, a["id"], hub)
    spec_b = act.choose(c, b["id"], hub)
    assert act.approve(c, a["id"], spec_a["plan_hash"], "p-030") is None
    assert act.approve(c, b["id"], spec_b["plan_hash"], "p-030")["mine"]


def test_approval_is_exclusive_and_moves_to_execute(hero):
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    assert act.approve(c, o["id"], spec["plan_hash"], "p-030")
    st = c.g().ro_query("MATCH (i:Incident {id:$i}) RETURN i.stage", {"i": c.inc}).result_set[0][0]
    assert st == "EXECUTE"
    with pytest.raises(ValueError):  # no re-choice once approved
        act.choose(c, _options(res, "rollback_deploy")[0]["id"], hub)


def test_execute_refuses_a_stale_diff(hero):
    """The world moved after approval (someone edited flags.json at main): executing the old diff is refused."""
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    hub.seed(act.INFRA_REPO, act.FLAGS_PATH, spec["before"].replace('"on"', '"on" ', 1))  # any out-of-band edit
    with pytest.raises(PermissionError, match="changed at main"):
        act.execute(c, o["id"], hub)


def test_execute_refuses_another_runs_intent(hero):
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    with pytest.raises(PermissionError, match="belongs to run"):
        act.execute(act.Ctx(c.tenant, c.graph, c.inc, "run-someone-else"), o["id"], hub)


def test_flag_already_off_at_main_is_not_offered(hero):
    """GitHub main (not the graph mirror) decides whether a flag lever is still available: no no-op PRs."""
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    doc = json.loads(hub.files[act.INFRA_REPO]["main"][act.FLAGS_PATH])
    doc["flags"][o["target"]]["state"] = "off"
    hub.seed(act.INFRA_REPO, act.FLAGS_PATH, json.dumps(doc, indent=2, sort_keys=True) + "\n")
    cut = res.post_gate["cut"]
    opts = act.build_options(c, cause=res.cause_id, cut=cut, hub=hub)
    f = next(x for x in opts if x["kind"] == "flip_flag" and x["target"] == o["target"])
    assert not f["enabled"] and "already off at GitHub main" in f["reason"] and "drift" in f["reason"]
    with pytest.raises(ValueError, match="change nothing"):
        act.render(c, {"kind": "flip_flag", "preview": json.dumps(f["args"])}, hub)


def test_open_issue_tracks_but_never_resolves(hero):
    p, res, c, hub, eff = hero
    o = _options(res, "open_issue")[0]
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom="checkout", onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "APPLIED" and v["channels"]["github_issue"]["ok"]
    wb = act.write_back(c, o["id"], cause=res.cause_id, confident=True)
    assert wb["written"] is None and wb["tracked"]["stage"] == "UNKNOWN_ESCALATED"
    assert c.g().ro_query("MATCH (pm:Postmortem {id:$p}) RETURN count(pm)", {"p": f"pm-{c.inc}"}).result_set[0][0] == 0


def test_rejected_fix_is_remembered_and_option_disabled(hero):
    """S5 continued: the failed attempt is linked (RESOLVED_BY, verdict NOT_APPLIED) for future fix history, the
    option is disabled, and the incident returns to AWAITING_APPROVAL so a human can choose again."""
    p, res, c, hub, eff = hero
    aid = f"act-{c.inc}-bad"
    writes.record_option(c.g(), inc=c.inc, aid=aid, kind="rollback_deploy", option="roll back D-email-88", enabled=True,
                         reason="forced bad plan (S5)", target="D-email-88",
                         preview={"repo": act.INFRA_REPO, "path": act.DEPLOYS_PATH, "service": "email", "revert": "D-email-88"})
    spec = act.choose(c, aid, hub)
    act.approve(c, aid, spec["plan_hash"], "p-030")
    act.execute(c, aid, hub)
    act.verify(c, aid, hub, symptom=["checkout", "frontend"], onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 5 * 60_000)
    act.write_back(c, aid, cause=res.cause_id, confident=True)
    row = c.g().ro_query("MATCH (i:Incident {id:$i})-[:ATTEMPTED]->(a:Action {id:$a}) RETURN i.stage, a.verdict, a.enabled",
                         {"i": c.inc, "a": aid}).result_set[0]
    assert row == ["AWAITING_APPROVAL", "NOT_APPLIED", False]
    o = _flag_option(res)  # a human can now choose the right fix
    spec2 = act.choose(c, o["id"], hub)
    assert act.approve(c, o["id"], spec2["plan_hash"], "p-030")


def test_reconciler_treats_any_github_error_as_unknown(hero, monkeypatch):
    """Not only timeouts: a 5xx (any GitHubError) while reading main ⇒ UNKNOWN, intent stays PENDING, escalated."""
    from faultline.actions import reconcile

    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)

    def boom(*a, **k):
        raise gh.GitHubError("gh api repos/…/contents failed: HTTP 502")

    monkeypatch.setattr(hub, "get_file", boom)
    out = reconcile.reconcile(c.tenant, c.graph, hub, _world(p, eff), older_than_ms=0)
    assert [(x["found"], x["verdict"]) for x in out] == [("unreadable", "UNKNOWN")]
    st = c.g().ro_query("MATCH (i:Incident {id:$i}) MATCH (it:Intent {idem:$d}) RETURN i.stage, it.state",
                        {"i": c.inc, "d": spec["idem"]}).result_set[0]
    assert st == ["UNKNOWN_ESCALATED", "PENDING"]


def test_execute_refuses_an_action_tampered_with_after_approval(hero):
    """Approval binds the exact plan: if the stored spec changes after approve (a different file, a different
    target), execute refuses before touching GitHub. (Found by scripts/mutation_check.py: M-HASH-EXEC survived.)"""
    p, res, c, hub, eff = hero
    o = _flag_option(res)
    spec = act.choose(c, o["id"], hub)
    assert act.approve(c, o["id"], spec["plan_hash"], "p-030")
    tampered = json.dumps({**spec, "file": "flags/other.json"})
    c.g().query("MATCH (a:Action {id:$a}) SET a.spec = $s", {"a": o["id"], "s": tampered})  # test-only tamper
    with pytest.raises(PermissionError, match="plan hash"):
        act.execute(c, o["id"], hub)
    assert hub.find_pr(spec["args"]["repo"], spec["branch"]) is None                  # nothing reached GitHub
