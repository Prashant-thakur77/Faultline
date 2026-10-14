"""Live S14 (M14 #2): one fault's alert storm plus an unrelated concurrent fault. INTAKE groups the alerts with algo.WCC
over the failure-carrying projection, each incident's gate decides its own cause, late alerts attach to the incident
whose confirmed origin reaches them. Grading is shared with the harness (evals/storm.py) and reads the truth file there."""

import copy
import sys
from contextlib import contextmanager
from pathlib import Path

import anyio
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))  # evals only: never the repo's backend/
import storm  # noqa: E402

from faultline import scenario  # noqa: E402
from faultline.actions import act  # noqa: E402
from faultline.actions import github as gh  # noqa: E402
from faultline.agent.gate import Gate  # noqa: E402
from faultline.agent.loop import BaselineInvestigator  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph import writes  # noqa: E402
from faultline.graph.algo import registry  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def s14():
    p, results = anyio.run(lambda: scenario.run_all("S14", BaselineInvestigator(), keep=True, set_mode=False))
    yield p, results, storm.grade(p, results)
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_s14_two_groups_and_each_gate_decides_its_own_cause(s14):
    p, results, g = s14
    assert not [r.error for r in results if r.error]
    assert g["groups_correct"] and g["incidents_opened"] == 2, g
    assert not g["cross_fault_merge"], g
    assert g["causes_found"] == 2 and g["all_distractors_rejected"], g["incidents"]


def test_s14_late_alerts_attach_to_the_incident_whose_origin_reaches_them(s14):
    p, results, g = s14
    assert g["alerts_placed_ok"] and not g["multi_placed"], g
    assert g["attach_rounds"] == 1 and not p.intake[1].opened  # nothing new opened: every late alert attached


def test_every_placement_cites_the_wcc_grouping_evidence(s14):
    p, _, g = s14
    ro = RO(p.tenant, p.graph)
    placed = storm.placements(p)
    ev = sorted({x["evidence"] for xs in placed.values() for x in xs})
    assert ev == sorted(g["grouping_evidence"])
    rows = ro.run("Q-EV-1", {"ids": ev}).rows
    assert len(rows) == 2 and all(registry.name("wcc") in r["cypher"] and "Q-STORM-WCC" in r["template"] for r in rows)


def _payment(p, results, g):
    """The incident truth names first (the payment storm), its intake group and an action context."""
    res = next(r for r in results if r.cause_id == g["incidents"][0]["cause"])
    grp = next(x for x in p.groups if x.incident_id == res.incident_id)
    return res, grp, act.Ctx(p.tenant, p.graph, res.incident_id, res.run_id)


def test_a_failed_fix_stays_not_applied_while_another_incident_is_open(s14):
    """The fraud incident is still open and owns a small share of the payment incident's symptoms (Q-VERIFY-ALLOW). A
    fix that does not contain the payment fault (rolling back an earlier, innocent change) must still be NOT_APPLIED:
    the allowance is a bound on the OTHER fault's share, never room for this incident's own."""
    p, results, g = s14
    res, grp, c = _payment(p, results, g)
    hub = gh.client(p.graph)
    causes = {w["cause"] for w in g["incidents"]}
    # an innocent change: one that changed a component of this incident's own symptoms earlier (history), not a cause
    rows = c.g().ro_query("MATCH (d:Node)-[:CHANGED]->(n:Node) WHERE n.id IN $s AND NOT d.id IN $causes "
                          "RETURN d.id, n.id ORDER BY d.id LIMIT 1", {"s": grp.symptoms, "causes": sorted(causes)}).result_set
    assert rows, "no historical change on the symptoms to roll back"
    wrong = {"change": rows[0][0], "target": rows[0][1]}
    aid = f"act-{c.inc}-bad"
    writes.record_option(c.g(), inc=c.inc, aid=aid, kind="rollback_deploy", option=f"roll back {wrong['change']}",
                         enabled=True, reason="forced bad plan (S5-style, concurrent fault open)", target=wrong["change"],
                         preview={"repo": act.INFRA_REPO, "path": act.DEPLOYS_PATH, "service": wrong["target"],
                                  "revert": wrong["change"]})
    spec = act.choose(c, aid, hub)
    act.approve(c, aid, spec["plan_hash"], "p-030")
    act.execute(c, aid, hub)
    v = act.verify(c, aid, hub, symptom=grp.symptoms, onset_ms=p.onset_ms,
                   effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "NOT_APPLIED" and "out of band" in v["explanation"], v
    per = v["channels"]["telemetry"]["targets"]
    other = next(r.incident_id for r in results if r.cause_id == g["incidents"][1]["cause"])
    assert any(x["allowance"] > 0 and [f["incidents"] for f in x["allowance_from"]] == [[other]] for x in per.values()), per
    assert "Q-VERIFY-ALLOW" in v["explanation"] and other in v["explanation"]
    assert act.write_back(c, aid, cause=res.cause_id, confident=True, precedents=[])["written"] is None


def _transfer(g, origin, symptom, cuts=frozenset()):
    """Test-side reference for the bound: the sum over origin → symptom paths (≤ 8 hops, no cut edge) of the product
    of the caps, read path by path and multiplied here (an independent check of Q-VERIFY-ALLOW's transfer)."""
    rows = g.ro_query("MATCH p = (o:Node {id: $o})-[:PROPAGATES_TO*1..8]->(t:Node {id: $t}) "
                      "RETURN [r IN relationships(p) | [startNode(r).id, endNode(r).id, r.cap]]",
                      {"o": origin, "t": symptom}).result_set
    total = 0.0
    for (edges,) in rows:
        if any((u, v) in cuts for u, v, _ in edges):
            continue
        prod = 1.0
        for _, _, cap in edges:
            prod *= cap
        total += prod
    return total


@contextmanager
def _branch(p, suffix):
    """A GRAPH.COPY of the scenario graph after both investigations (each test's world edits stay on its own copy)."""
    db = gclient.engine()
    name = f"{p.graph}_{suffix}"
    gcopy.delete_if_exists(db, name)
    gcopy.copy_graph(db, p.graph, name)
    try:
        yield db.select_graph(name), name
    finally:
        gcopy.delete_if_exists(db, name)
        gh.reset_sim(name)


def test_a_partial_fix_that_leaves_our_own_leak_stays_not_applied(s14):
    """Review M1: a partial fix while another incident is open. On a copy of the world the fraud fault reaches the
    payment symptoms over two weak hops (origin → queue at cap 0.1, queue → checkout at cap 0.2), and the payment
    fault has a bypass into the same queue (cap 0.2) that the flag does not cut. The flag flip removes the payment
    fault's main edge, but its residual leak still keeps checkout a couple of points above baseline.
    The fraud incident can cause at most excess × 0.1 × 0.2 there (path transfer); the bottleneck max flow (0.1) would
    allow five times that, enough to hide our own leak and read APPLIED. Verification must read NOT_APPLIED."""
    p, results, g = s14
    res, grp, _ = _payment(p, results, g)
    other = next(r for r in results if r.cause_id == g["incidents"][1]["cause"])
    gate = Gate(p.tenant, res.run_id, res.incident_id, p.graph)
    ours, theirs = gate.change_targets(res.cause_id)[0], gate.change_targets(other.cause_id)[0]
    sym = gate.primary_symptoms(grp.symptoms)[0][0]
    with _branch(p, "pf") as (gr, name):
        mid = gr.ro_query("MATCH (o:Node {id: $o})-[:PROPAGATES_TO]->(m:Node)-[:PROPAGATES_TO]->(t:Node {id: $t}) "
                          "RETURN m.id ORDER BY m.id LIMIT 1", {"o": theirs, "t": sym}).result_set[0][0]
        gr.query("MATCH (o:Node {id: $o})-[a:PROPAGATES_TO]->(m:Node {id: $m})-[b:PROPAGATES_TO]->(t:Node {id: $t}) "
                 "SET a.cap = 0.1, b.cap = 0.2", {"o": theirs, "m": mid, "t": sym})
        gr.query("MATCH (u:Node {id: $u}), (m:Node {id: $m}) "
                 "CREATE (u)-[:PROPAGATES_TO {k: '', cap: 0.2, w: 1, cut_cost: 0.4, domain: 'service'}]->(m), "
                 "(m)-[:CALLS {k: '', rps: 40}]->(u)", {"u": ours, "m": mid})
        c = act.Ctx(p.tenant, name, res.incident_id, res.run_id)
        hub = gh.client(name)
        act.ensure_infra_repo(c, hub)
        o = next(o for o in res.post_gate["options"] if o["enabled"] and o["kind"] == "flip_flag")
        spec = act.choose(c, o["id"], hub)
        act.approve(c, o["id"], spec["plan_hash"], "p-030")
        act.execute(c, o["id"], hub)
        v = act.verify(c, o["id"], hub, symptom=grp.symptoms, onset_ms=p.onset_ms,
                       effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 5 * 60_000)
        assert v["verdict"] == "NOT_APPLIED" and "out of band" in v["explanation"], v
        per = v["channels"]["telemetry"]["targets"]
        assert per[sym]["ok"] is False and per[sym]["allowance_from"][0]["origin"] == theirs, per[sym]
        assert abs(per[sym]["allowance_from"][0]["transfer"] - 0.02) < 1e-9          # 0.1 × 0.2, not the bottleneck
        assert other.incident_id in v["explanation"] and "Q-VERIFY-ALLOW" in v["explanation"]
        # the case discriminates: an allowance of max flow (0.1) × the same excess would have covered every symptom
        g2 = Gate(p.tenant, res.run_id, res.incident_id, name)
        assert abs(g2.flow([theirs], sym) - 0.1) < 1e-9
        for t, x in per.items():
            a = min(1.0, g2.flow([theirs], t)) * per[sym]["allowance_from"][0]["excess"]
            assert all(val <= x["baseline"] * x["band"] + a or val - x["baseline"] < 0.005 + a for val in x["after"]), (t, x)
        assert act.write_back(c, o["id"], cause=res.cause_id, confident=True)["written"] is None


def test_the_allowance_counts_shared_paths_once_and_never_an_origin_our_fault_feeds(s14):
    """Q-VERIFY-ALLOW's joint bound on a copy with more open incidents: one blaming a change on the queue (which the
    fraud origin feeds: the fraud paths into checkout all pass through it, so checkout's allowance is the queue's
    alone, never fraud + queue over the same edge), one more blaming another change on the fraud origin (one row
    for the origin, both incidents named), and one on a component the payment fault itself reaches (its excess
    holds our own leak: no allowance from it). An incident with no confirmed cause reads no allowance at all."""
    p, results, g = s14
    res, grp, _ = _payment(p, results, g)
    other = next(r for r in results if r.cause_id == g["incidents"][1]["cause"])
    gate = Gate(p.tenant, res.run_id, res.incident_id, p.graph)
    ours, theirs = gate.change_targets(res.cause_id)[0], gate.change_targets(other.cause_id)[0]
    sym = gate.primary_symptoms(grp.symptoms)[0][0]
    with _branch(p, "jt") as (gr, name):
        mid = gr.ro_query("MATCH (o:Node {id: $o})-[:PROPAGATES_TO]->(m:Node)-[:PROPAGATES_TO]->(t:Node {id: $t}) "
                          "RETURN m.id ORDER BY m.id LIMIT 1", {"o": theirs, "t": sym}).result_set[0][0]
        # a component the payment fault reaches that itself reaches a payment symptom (so only the rule excludes it)
        fed = gr.ro_query("MATCH (u:Node {id: $u})-[:PROPAGATES_TO*1..8]->(n:Node)-[:PROPAGATES_TO*1..8]->(t:Node) "
                          "WHERE t.id IN $syms AND n.id <> $s RETURN DISTINCT n.id ORDER BY n.id LIMIT 1",
                          {"u": ours, "s": sym, "syms": grp.symptoms}).result_set[0][0]
        made = {}
        for tag, target in (("mid", mid), ("dup", theirs), ("fed", fed)):
            inc, run, chg = f"inc-test-{tag}", f"run-test-{tag}", f"D-test-{tag}"
            writes.inject_change(gr, id=chg, target=target, at=p.onset_ms - 3 * 60_000, title="test change", tenant=p.tenant)
            writes.open_incident(gr, inc=inc, run=run, tenant=p.tenant, title="test", report="", onset=p.onset_ms,
                                 symptoms=[{"id": f"sym-error_rate-{target}", "kind": "error_rate", "target": target}],
                                 models="", mode="scenario")
            writes.upsert_hypothesis(gr, inc=inc, hid=f"hyp-{inc}-{chg}", cause=chg, status="confirmed", origin="gate")
            made[tag] = inc
        writes.open_incident(gr, inc="inc-test-none", run="run-test-none", tenant=p.tenant, title="test", report="",
                             onset=p.onset_ms, symptoms=[{"id": f"sym-error_rate-{sym}", "kind": "error_rate", "target": sym}],
                             models="", mode="scenario")
        targets = sorted(set(grp.symptoms) | {mid})
        kw = dict(onset_ms=p.onset_ms, since=p.onset_ms, until=p.onset_ms + 5 * 60_000, cut_edges=set())
        a = act.allowances(act.Ctx(p.tenant, name, res.incident_id, res.run_id), targets, **kw)
        origins = {r["origin"] for r in a["rows"]}
        assert fed not in origins and ours not in origins, a["rows"]
        assert origins == {mid, theirs}, a["rows"]
        at_sym = [r for r in a["rows"] if r["symptom"] == sym]
        assert [r["origin"] for r in at_sym] == [mid], at_sym                     # fraud's path passes through the queue
        assert abs(at_sym[0]["transfer"] - _transfer(gr, mid, sym)) < 1e-9
        at_mid = [r for r in a["rows"] if r["symptom"] == mid]
        assert [r["origin"] for r in at_mid] == [theirs]
        assert at_mid[0]["incidents"] == sorted([other.incident_id, made["dup"]])  # one row for the shared origin
        assert a["per_symptom"][sym]["allowance"] == pytest.approx(at_sym[0]["allowance"], abs=1e-6)
        none = act.allowances(act.Ctx(p.tenant, name, "inc-test-none", "run-test-none"), [sym], **kw)
        assert none["rows"] == [] and none["per_symptom"][sym]["allowance"] == 0.0


def test_the_real_fix_is_applied_once_the_other_incidents_share_is_allowed(s14):
    """The min-cut flag flip contains the payment fault, but checkout still carries the fraud fault's leak over the 2%
    queue edge. Verification allows an upper bound on the share the OPEN fraud incident can still cause (its origin's
    measured excess × its path transfer, the sum over uncut paths of the product of caps), says so in the explanation
    and the channel, and only then reads APPLIED. Without the allowance the same telemetry is out of band
    (in_plain_band false on at least one symptom)."""
    p, results, g = s14
    res, grp, c = _payment(p, results, g)
    hub = gh.client(p.graph)
    o = next(o for o in res.post_gate["options"] if o["enabled"] and o["kind"] == "flip_flag")
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom=grp.symptoms, onset_ms=p.onset_ms,
                   effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "APPLIED", v
    tel = v["channels"]["telemetry"]
    other = next(r for r in results if r.cause_id == g["incidents"][1]["cause"])
    leaned = [t for t, x in tel["targets"].items() if x.get("allowance") and not x["in_plain_band"]]
    assert leaned, tel["targets"]  # the allowance was load-bearing
    allow = tel["allowance"]
    assert allow["template"] == "Q-VERIFY-ALLOW" and allow["cypher"] and allow["params"]["inc"] == c.inc
    cuts = {tuple(x.split("|")) for x in allow["params"]["cuts"]}
    for t in leaned:
        rows = [r for r in allow["rows"] if r["symptom"] == t]
        assert [r["incidents"] for r in rows] == [[other.incident_id]] and rows[0]["cause"] == other.cause_id
        # the bound is the origin's path transfer over the uncut edges × its measured excess
        assert abs(rows[0]["transfer"] - _transfer(c.g(), rows[0]["origin"], t, cuts)) < 1e-9, rows[0]
        assert 0 < rows[0]["excess"] <= 1
        assert abs(rows[0]["allowance"] - rows[0]["transfer"] * rows[0]["excess"]) < 1e-9
    assert other.incident_id in v["explanation"] and "Q-VERIFY-ALLOW" in v["explanation"]
    assert act.write_back(c, o["id"], cause=res.cause_id, confident=True)["verified"] == "7/7"


def test_a_resolved_incident_never_absorbs_a_new_alert(s14):
    """Attach-or-open reads only OPEN incidents. The fraud-detection incident is resolved the product way (its first
    enabled fix approved, executed, verified APPLIED, written back): its stage is WRITEBACK, which is not terminal, but
    resolved_at is set. A fresh queue alert its origin reaches must then open a new incident instead of attaching to the
    closed one (the warm S1 → S1b memory path depends on this)."""
    p, results, g = s14
    res = next(r for r in results if r.cause_id == g["incidents"][1]["cause"])
    grp = next(x for x in p.groups if x.incident_id == res.incident_id)
    c = act.Ctx(p.tenant, p.graph, res.incident_id, res.run_id)
    hub = gh.client(p.graph)
    o = next(o for o in res.post_gate["options"] if o["enabled"] and o["kind"] != "open_issue")
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom=grp.symptoms, onset_ms=p.onset_ms,
                   effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "APPLIED", v
    assert act.write_back(c, o["id"], cause=res.cause_id, confident=True)["verified"]
    gr = gclient.engine().select_graph(p.graph)
    at = p.onset_ms + 5 * 60_000
    writes.raise_alert(gr, id="al-test-after-resolve", target="queue", metric="error_rate", at=at)
    rnd = scenario.intake_late(p, at - 60_000, at, k=9)
    assert not rnd.attached and [o.symptoms for o in rnd.opened] == [["queue"]]


def test_a_late_fault_whose_deploy_lands_after_the_first_onset_is_confirmed():
    """Review M6: a later intake round's incident starts at its OWN first page, not at the first round's onset. A variant
    of S14 (a generated spec, no truth read) where the second fault ships 2 minutes AFTER the payment storm's onset
    and pages 2 minutes later: measured from the first onset its deploy would sit after onset (G3 fails, so nothing
    could be confirmed); from its own first page it is 2 minutes before, and its gate confirms it."""
    s = copy.deepcopy(scenario.load("S14"))
    late = s["inject"][1]                                   # the second, unrelated change and its effect
    eff = next(e for e in s["effects"] if e.get("change") == late["change"])
    late["at"], eff["from"] = "+2m", "+2m"
    pay_targets = {"checkout", "frontend", "frontend-proxy", "mcp"}
    s["alerts"] = [a for a in s["alerts"] if a["target"] in pay_targets] + [
        {"id": "al-late-1", "target": eff["target"], "metric": "error_rate", "at": "4m"},
        {"id": "al-late-2", "target": "queue", "metric": "error_rate", "at": "4m"}]
    s["id"] = "S14LATE"
    p = scenario.prepare("S14LATE", spec=s, set_mode=False)
    try:
        assert len(p.groups) == 1                           # only the payment storm at onset
        results = anyio.run(lambda: scenario.investigate_all(p, BaselineInvestigator()))
        assert len(p.intake) == 2 and len(p.intake[1].opened) == 1, [r.opened for r in p.intake]
        grp = p.intake[1].opened[0]
        first_page = p.onset_ms + 4 * 60_000
        assert grp.onset_ms == first_page
        row = RO(p.tenant, p.graph).run("Q-INC-1", {"inc": grp.incident_id}).rows[0]
        assert int(row["onset_at"]) == first_page             # G3 and the Q-PRIMARY-1 windows read this
        res = next(r for r in results if r.incident_id == grp.incident_id)
        assert res.error is None, res.trace
        assert res.outcome == "CONFIRMED" and res.cause_id == late["change"] and res.confident, res.gate
        g3 = next(c for c in res.gate["checks"] if c["name"] == "G3 time")
        assert g3["passed"] and g3["params"]["onset"] == first_page
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_s1_two_alerts_stay_one_incident_with_checkout_primary():
    p = scenario.prepare("S1", set_mode=False)
    try:
        assert len(p.groups) == 1 and p.symptoms == ["checkout", "frontend"]
        assert Gate(p.tenant, p.run_id, p.incident_id, p.graph).primary_symptoms(p.symptoms) == [["checkout", "frontend"]]
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_ungrouped_storm_is_escalated_not_blamed_on_one_change():
    """Control: every onset alert in ONE incident. A gate that treats a target as a consequence only when a failure can
    actually cross the edge (Q-PRIMARY-1, same rule as the grouping) refuses to explain the payment storm with the
    fraud-detection change (it reaches checkout only over a 2% async edge), so nothing is confirmed."""
    c = storm.ungrouped_control()
    assert c["error"] is None
    assert c["causes_found"] == 0 and not c["confident_misattribution"], c
