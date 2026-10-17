"""Unit (no engine): the scale benchmark's generator is deterministic and well-formed, and its runner computes what it
claims (percentiles, growth shapes, grading, the planted incident's expectations, the world telemetry, report keys)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import report  # noqa: E402
import scale  # noqa: E402
import scale_world as W  # noqa: E402
from faultline.graph.tenant import check_tenant, eval_graph, golden_graph, graph_belongs_to  # noqa: E402
from faultline.ingest.globex import topology  # noqa: E402

ONSET = 1_792_033_200_000


# ------------------------------------------------------------------ generator
def test_unit_bundles_are_deterministic():
    assert W.bundle_hash(W.unit_bundle(3, "scale1k")) == W.bundle_hash(W.unit_bundle(3, "scale1k"))
    assert W.bundle_hash(W.unit_bundle(3, "scale1k")) != W.bundle_hash(W.unit_bundle(4, "scale1k"))


def test_unit_zero_is_globex_and_other_units_are_namespaced():
    u0 = {r["id"] for r in W.unit_bundle(0, "scale1k").nodes["Service"]}
    assert u0 == {s["id"] for s in topology.generate(42).services}
    b = W.unit_bundle(2, "scale1k")
    assert all(r["id"].endswith("-u002") for r in b.nodes["Service"])
    assert all(r["id"].startswith("file:u002/") and r["path"].startswith("u002/") for r in b.nodes["File"])
    assert all(r["id"] == "file:" + r["path"] for r in b.nodes["File"])          # preflight's file:<path> convention
    assert {r["tenant"] for rows in b.nodes.values() for r in rows if "tenant" in r} == {"scale1k"}
    dep = b.nodes["Deploy"][0]
    assert dep["target_id"].endswith("-u002") and dep["actor_id"].endswith("-u002")
    flag = next(r for r in b.nodes["FeatureFlag"] if r.get("cuts_src"))
    assert flag["cuts_src"].endswith("-u002") and flag["cuts_dst"].endswith("-u002")


def test_ids_are_unique_and_every_edge_has_both_endpoints():
    seen: dict[str, str] = {}
    vector_only = {"Incident", "Postmortem", "Runbook"}   # the embeddings producer repeats these ids with a vector
    for _, b in W.bundles(1000, "scale1k"):
        for label, rows in b.nodes.items():
            for r in rows:
                assert seen.setdefault(r["id"], label) == label or label in vector_only, r["id"]
        for (_, sl, dl), rows in b.edges.items():
            for e in rows:
                assert e["src"] in seen and e["dst"] in seen, e
    assert sum(1 for lb in seen.values() if lb == "Service") == 1000


def test_federation_goes_from_units_to_the_global_platform_with_spec_caps():
    assert W.federation_calls(0) == []
    calls = W.federation_calls(7)
    spec = W.load_spec()
    assert {c.server for c in calls} == set(W.platform_anchors())
    for c in calls:
        assert c.client == c.server + "-u007" and c.rps >= 1
        cc = spec["callee_caps"].get(c.server)
        assert c.cap == (float(cc["cap"]) if cc else 1.0)


def test_world_is_acyclic_and_hubs_fan_in_grows_with_size():
    w = W.world(1000)
    for n in w.components()[:300]:
        assert n not in w.reach(n)
    assert w.units == 5 and len(w.components()) == 5 * (200 + 6)
    fan_in = sum(1 for cl, sv, _, _ in w.calls if sv == "auth-service")
    assert fan_in >= w.units - 1


@pytest.mark.parametrize("label", list(W.SIZES))
def test_scale_tenants_have_their_own_graphs(label):
    t = W.tenant_for(label)
    assert check_tenant(t) == t and t not in ("acme", "globex")
    assert graph_belongs_to(golden_graph(t), t) and not graph_belongs_to(golden_graph(t), "globex")
    assert graph_belongs_to(eval_graph(t, "scale", "bench", label, 1), t)


def test_unit_count_follows_the_size():
    assert [W.n_units(n) for n in W.SIZES.values()] == [5, 15, 25, 50, 125, 250]
    with pytest.raises(ValueError):
        W.tenant_for("7k")


# ------------------------------------------------------------------ runner metrics
def test_percentiles_and_stats_are_nearest_rank():
    xs = list(range(1, 21))
    assert scale.pct(xs, 0.95) == 19 and scale.pct(xs, 0.5) == 10 and scale.pct([], 0.5) is None
    assert scale.stats([3.0, 1.0, 2.0]) == {"n": 3, "p50": 2.0, "p95": 3.0, "max": 3.0}


def test_growth_exponent_and_shape():
    g = scale.growth([(1000, 1.0), (10000, 10.0), (25000, 100.0), (50000, 100.0)])
    assert [x["shape"] for x in g] == ["linear", "superlinear", "flat"]
    assert g[0]["exponent"] == 1.0 and g[0]["size_x"] == 10.0
    assert scale.growth([(1000, None), (10000, 5.0)]) == []


def test_ambient_changes_scale_with_units():
    a1, a50 = scale.ambient_count(5, 30), scale.ambient_count(50, 30)
    assert a1 == 2 and a50 == 20


def test_grade_requires_cause_and_each_distractor_gate():
    exp = {"outcome": "CONFIRMED", "cause": "D-c", "eliminated": {"D-g2": "G2", "D-o": "G4 origin"}, "ambient": ["D-a"]}
    ok = {"outcome": "CONFIRMED", "cause": "D-c", "sweep": {"D-c": "candidate: G5", "D-g2": "eliminated: G2: no path",
                                                           "D-o": "eliminated: G4 origin: in band", "D-a": "eliminated: G2: x"}}
    assert scale.grade(exp, ok) == {"correct": True, "why": [], "ambient_left_candidate": []}
    bad = {**ok, "sweep": {**ok["sweep"], "D-o": "eliminated: G5: max flow", "D-a": "candidate: G5"}}
    g = scale.grade(exp, bad)
    assert not g["correct"] and g["ambient_left_candidate"] == ["D-a"] and "D-o" in g["why"][0]
    assert not scale.grade(exp, {**ok, "outcome": "NOT_CONFIDENT", "cause": None})["correct"]


def test_analyse_names_the_dominant_template_and_collects_truncation_and_errors():
    def size(label, n, gate1, sus1, trunc=False, err=None):
        inst = {"instance": "hub", "truncated": trunc, "rows": 100, **({"error": err} if err else {})}
        return {"label": label, "services": n, "memory_mb": n / 20, "seed": {"seed_s": n / 200},
                "sweep_ms": {"p50": n / 10},
                "templates": {"Q-GATE-1": {"engine_ms_p50": gate1, "engine_ms_p95": gate1, "instances": [inst]},
                              "Q-SUS-1": {"engine_ms_p50": sus1, "engine_ms_p95": sus1, "instances": []}},
                "run": {"truncated_calls": [{"tool": "chokepoints", "template": "Q-CHOKE-1", "rows": 10}]}}
    a = scale.analyse({"1k": size("1k", 1000, 1.0, 5.0), "10k": size("10k", 10000, 50.0, 6.0, trunc=True, err="Timeout")})
    assert a["dominant"] == {"1k": {"template": "Q-SUS-1", "instance": None, "engine_ms_p95": 5.0},
                             "10k": {"template": "Q-GATE-1", "instance": None, "engine_ms_p95": 50.0}}
    assert a["growth"]["Q-GATE-1"]["steps"][0]["shape"] == "superlinear"
    assert {"size": "10k", "template": "Q-GATE-1", "instance": "hub", "rows": 100} in a["truncated"]
    assert any(t["template"] == "Q-CHOKE-1" for t in a["truncated"])
    assert a["errors"] == [{"size": "10k", "template": "Q-GATE-1", "instance": "hub", "error": "Timeout"}]


def test_planted_incident_expectations_come_from_the_world_config():
    w = W.world(1000)
    p1, p2 = scale.plan_incident(w, ONSET, 30), scale.plan_incident(w, ONSET, 30)
    assert p1 == p2                                                     # deterministic
    c, t = p1["cause_target"], p1["symptom"]
    assert scale._visible(w, c, t) and w.unit_of[c] == p1["home_unit"] == 2
    for cid, d in p1["distractors"].items():
        r, s = w.reach(d["target"]), w.reach(d["target"], sync_only=True)
        want = "G2" if t not in r else ("G5" if t not in s else "origin")
        assert d["category"] == want and p1["expected"]["eliminated"][cid] == scale.EXPECT_REASON[want]
    cone = set(w.upstream(c, 8)) | w.reach(c) | {c, t}
    assert not cone & set(p1["ambient"].values())                     # ambient changes stay out of the cause's cone
    assert len(p1["ambient"]) == scale.ambient_count(w.units, 30)
    assert p1["hub"] in W.platform_anchors() and w.unit_of[p1["hub"]] == 0
    assert all(x["at"] < ONSET for x in p1["inject"])


def test_world_series_shows_the_fault_at_the_cause_and_symptom_only_after_onset():
    w = W.world(1000)
    plan = scale.plan_incident(w, ONSET, 30)
    s = scale.world_series(w, plan, ONSET)
    assert set(s) == set(plan["monitored"]) and all(len(v) == 36 for v in s.values())
    for n in (plan["cause_target"], plan["symptom"]):
        before = [v for at, _, v in s[n] if at <= ONSET - 5 * 60_000]
        after = [v for at, _, v in s[n] if at >= ONSET - 60_000]
        assert max(before) < 0.02 and min(after) > 0.2
    g2 = plan["distractors"][plan["roles"]["g2"]]["target"]
    assert max(v for _, _, v in s[g2]) < 0.02
    assert s == scale.world_series(w, plan, ONSET)                       # deterministic


def test_change_ids_titles_and_order_never_single_out_the_cause():
    import re

    w = W.world(1000)
    plan = scale.plan_incident(w, ONSET, 30)
    cause = plan["expected"]["cause"]
    assert cause == plan["roles"]["cause"] and set(plan["roles"].values()) - {cause} == set(plan["distractors"])
    ids = [x["change"] for x in plan["inject"]]
    assert len(set(ids)) == len(ids) and all(re.fullmatch(r"D-[0-9a-f]{10}", i) for i in ids)
    assert all(x["title"] == f"{x['target']}: change" for x in plan["inject"])
    assert plan["inject"] == sorted(plan["inject"], key=lambda x: (x["at"], x["change"]))
    assert scale.plan_incident(w, ONSET, 30) == plan                    # deterministic


# ------------------------------------------------------------------ report keys
def _fake_scale() -> dict:
    tpl = {tid: {"engine_ms_p50": 1.5, "engine_ms_p95": 2.5, "wall_ms_p50": 3.0, "instances": []} for tid in scale.HERO}
    size = {"services": 1000, "units": 5, "nodes": 29131, "edges": 107528, "memory_mb": 42, "copy_ms": 344.2,
            "seed": {"seed_s": 4.0}, "incident": {"ambient": 2}, "templates": tpl, "sweep_ms": {"p50": 160.0, "p95": 170.0},
            "run": {"outcome": "CONFIRMED", "correct": True, "seconds": 1.2, "swept": 7, "why": []}}
    return {"profile_runs": 20, "sizes": {"1k": size, "50k": {"skipped": "not enough memory"}},
            "analysis": {"dominant": {"1k": {"template": "Q-GATE-3"}}, "growth": {}, "truncated": [], "errors": []}}


def test_report_summary_and_markdown_are_claim_tagged():
    sc = _fake_scale()
    s = report.scale_summary(sc)
    assert s["scale.1k.correct"] is True and s["scale.1k.Q-GATE-MULT.engine_ms_p95"] == 2.5
    assert s["scale.50k.skipped"] is True and s["scale.largest_services"] == 1000 and s["scale.1k.dominant"] == "Q-GATE-3"
    md = "\n".join(report.scale_markdown(sc))
    assert "<!-- claim:scale.1k.sweep_ms_p50 -->160.0<!-- /claim -->" in md
    assert "<!-- claim:scale.1k.Q-SUS-1.engine_ms_p50 -->1.5<!-- /claim -->" in md
    assert "50k | not run: not enough memory" in md
    assert any("50k was not run" in n for n in report.scale_notes(sc))
    assert report.scale_summary({}) == {} and report.scale_markdown({}) == []
