"""Unit (no engine): the eval pieces added in M13 workstream B grade what they claim to grade.

* harness.grade_detail: blast precision/recall, ordered path, violated decisions, responder in top 3, correct target;
* report: the new summary keys, sections and the generated NAIVE_VS_FAULTLINE table (numbers claim-tagged);
* gate_bench: deterministic generation, category sizes, the fast variant is a subset, intake vectors precomputed,
  expected labels consistent with the topology config, and the grading rule;
* run_artefacts: every committed example re-reads consistently (the judge-check "write-back re-read" line).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "scripts"))

import gate_bench  # noqa: E402
import harness  # noqa: E402
import report  # noqa: E402
import run_artefacts  # noqa: E402

S1_TRUTH = json.loads((ROOT / "data/scenarios/S1.truth.json").read_text())


def _detail(**kw):
    d = {"blast": list(S1_TRUTH["blast_radius"]), "who_top3": ["p-017", "p-099", "p-098"], "violations": ["ADR-013", "ADR-012"],
         "gate_ran": True, "options": [{"kind": "flip_flag", "target": "paymentGate", "enabled": True, "cuts": ["payment", "checkout"]},
                                       {"kind": "open_issue", "target": "D-pay-417", "enabled": True}]}
    d.update(kw)
    return d


def test_grade_detail_all_correct():
    g = harness.grade_detail("S1", _detail(), ["D-pay-417", "payment", "checkout"])
    assert g == {"blast_precision": 1.0, "blast_recall": 1.0, "path_contains_ok": True, "violates_ok": True,
                 "responder_top3": True, "fix_offered": True, "target_correct": True}


def test_grade_detail_misses():
    blast = S1_TRUTH["blast_radius"][:6] + ["ad", "cart"]
    g = harness.grade_detail("S1", _detail(blast=blast, who_top3=["p-099"], violations=["ADR-012"],
                                           options=[{"kind": "rollback_deploy", "target": "D-email-88", "enabled": True},
                                                    {"kind": "flip_flag", "target": "paymentGate", "enabled": True}]),
                             ["D-pay-417", "checkout", "payment"])
    assert g["blast_precision"] == round(6 / 8, 4) and g["blast_recall"] == round(6 / len(S1_TRUTH["blast_radius"]), 4)
    assert g["path_contains_ok"] is False  # order matters: payment must come before checkout
    assert g["violates_ok"] is False and g["responder_top3"] is False
    assert g["target_correct"] is False  # the FIRST offered production-changing fix is graded


def test_grade_detail_nothing_produced_is_a_miss_and_no_fix_is_not_graded():
    g = harness.grade_detail("S1", {"blast": None, "who_top3": [], "violations": [], "gate_ran": False, "options": []}, None)
    assert g["blast_precision"] == 0.0 and g["blast_recall"] == 0.0 and g["path_contains_ok"] is False
    assert g["violates_ok"] is False and g["responder_top3"] is False
    assert g["fix_offered"] is False and g["target_correct"] is None
    # a scenario whose truth has none of the fields is not graded at all
    assert harness.grade_detail("S12", _detail(), None) == {}


def _out():
    def trial(sid, arm, **kw):
        return {"scenario": sid, "arm": arm, "trial": 1, "outcome": "CONFIRMED", "cause": kw.pop("cause", None), "top1": 1.0,
                "false_blame": False, "abstention_correct": None, "outcome_correct": True, "confident": True, **kw}

    sweep = [{"change": "D-email-88", "status": "eliminated", "reason": "G5: max flow 0.0200 < needed 0.2433 (observed 0.3041 × 0.8)"},
             {"change": "D-rec-12", "status": "eliminated", "reason": "G2: no path to any primary symptom"}]
    a3 = trial("S1", "A3", cause="D-pay-417", sweep=sweep, chain=["D-pay-417", "payment", "checkout"], detail=_detail(),
               distractors_rejected=True, grounded=True, tool_calls=30, seconds=0.4,
               **harness.grade_detail("S1", _detail(), ["D-pay-417", "payment", "checkout"]))
    n = trial("S1", "N", cause="D-email-88", top1=0.5, ranking=[["D-email-88", 3.0], ["D-pay-417", 3.0], ["D-rec-12", 4.0]])
    v = trial("S1", "V", cause="D-pay-417", ranking=[["D-pay-417", 0.35], ["D-email-88", 0.41], ["D-rec-12", 0.49]])
    bench = {"cases": 3, "correct": 2, "abstain_inferred_origin": 0, "by_category": {"G2": {"cases": 2, "correct": 1},
                                                                                   "control": {"cases": 1, "correct": 1}},
             "failures": [{"id": "gb001", "category": "G2", "symptom": "payment", "origin": "payment", "why": ["outcome x"],
                           "got": {"outcome": "UNKNOWN_ESCALATED"}}]}
    chaos = {"ok": True, "exactly_once": True, "final": {"prs": 1, "verdict": "APPLIED", "writeback": "7/7", "stage": "RESOLVED"},
             "control_naive_retry": {"merged_prs": 2}}
    return {"started": "a", "finished": "b", "n": 1, "arms": ["N", "V", "A3"], "skipped_arms": [], "scenarios": ["S1"],
            "investigator": "baseline", "engine": "6.0.2", "trials": [n, v, a3], "repo": {},
            "checks": {"gate_bench": bench, "chaos": chaos,
                       "profile": {"Q-GATE-1": {"runs": 20, "rows": 1, "engine_ms_p50": 0.07, "engine_ms_p95": 0.11}}}}


def test_report_summary_and_sections():
    out = _out()
    s = report.summarize(out)
    assert s["arm.A3.blast_recall"] == 1.0 and s["arm.A3.responder_top3_rate"] == 1.0 and s["arm.A3.target_correct_rate"] == 1.0
    assert s["arm.A3.S1.path_contains_rate"] == 1.0
    assert s["gate_bench.correct"] == 2 and s["gate_bench.G2.cases"] == 2 and s["chaos.exactly_once"] is True
    assert s["profile.Q-GATE-1.engine_ms_p95"] == 0.11
    md = report.markdown(out, s, "run_x.json")
    for head in ("## Graded beyond the cause", "## Gate bench", "engine ms p95", "SIGKILL chaos"):
        assert head in md
    assert "Q-SUS-1" in md  # the change-on-a-leaf-symptom failure is explained in "What didn't work"


def test_naive_vs_table_ranks_and_tags():
    out = _out()
    s = report.summarize(out)
    doc = report.naive_vs_markdown(out, "run_x.json", s)
    row = next(x for x in doc.splitlines() if x.startswith("| S1 "))
    assert "| 1, tied with 1 (D-email-88) |" in row and "| 1 (D-pay-417) |" in row
    assert "<!-- claim:s1.D-email-88.max_flow -->0.02<!-- /claim -->" in row
    assert "naive 1 rank inversion(s) in 1, vector 0 rank inversion(s) in 1; Faultline 0" in doc
    import check_claims

    bare = [ln for ln in doc.splitlines() if check_claims.NUM.findall(check_claims.TAG.sub(" ", ln))]
    assert bare == []


def test_gate_bench_generation_is_deterministic_and_sized():
    a, b = gate_bench.generate(), gate_bench.generate()
    assert [c["spec"] for c in a] == [c["spec"] for c in b]
    assert len(a) == sum(gate_bench.PLAN.values()) == 100
    for cat, n in gate_bench.PLAN.items():
        assert sum(c["category"] == cat for c in a) == n
    fast = gate_bench.select(a, gate_bench.FAST)
    assert len(fast) == 20 and all(c in a for c in fast)


def test_gate_bench_labels_follow_the_topology_config():
    topo = gate_bench.Topo()
    for c in gate_bench.generate():
        t, ids = c["symptom"], {x["change"]: x["target"] for x in c["spec"]["inject"]}
        for change, gate in c["expected"]["eliminated"].items():
            d = ids[change]
            if gate == "G2":
                assert t not in topo.any[d]
            elif gate == "G5":
                assert t in topo.any[d] and t not in topo.sync[d]
            else:
                assert gate == "G4 origin" and t in topo.sync[d]
            if gate != "G2":
                assert d not in topo.any[c["origin"]]  # the distractor's own component stays healthy
        assert all(x["at"] == "-3m" for x in c["spec"]["inject"])  # same-minute look-alikes


def test_gate_bench_incident_names_do_not_leak_the_category():
    for c in gate_bench.generate():
        assert c["category"] not in c["spec"]["name"] and "gate_bench" not in c["spec"]["name"]


def test_gate_bench_reports_bystander_acceptance_apart_from_true_abstention():
    rows = [{"correct": True, "got": {"accepted_not_confident": None}},          # escalated / origin inferred
            {"correct": True, "got": {"accepted_not_confident": "D-gb1-d1"}},    # a bystander accepted, not confident
            {"correct": False, "got": {"accepted_not_confident": None}}]
    assert gate_bench.abstention_split(rows) == {"abstain_true": 1, "abstain_bystander_not_confident": 1}


def test_gate_bench_intake_vectors_are_precomputed():
    from faultline.memory.embed import _precomputed, incident_text

    have = _precomputed()
    for c in gate_bench.generate():
        text = incident_text(c["spec"]["report"], [f"error_rate {c['symptom']}"])
        assert text in have, f"{text!r}: run data/gen/embed.py --scenarios-only"


def test_gate_bench_grading_rule():
    exp = {"outcome": "CONFIRMED", "cause": "D-x", "eliminated": {"D-y": "G5"}}
    ok = {"outcome": "CONFIRMED", "cause": "D-x", "sweep": {"D-y": "eliminated: G5: max flow 0.02 < needed 0.2"}}
    assert gate_bench.grade(exp, ok)["correct"]
    wrong_gate = {**ok, "sweep": {"D-y": "eliminated: G4 origin: measured in band"}}
    assert not gate_bench.grade(exp, wrong_gate)["correct"]
    abst = {"outcome": "NOT_CONFIDENT", "cause": None, "eliminated": {}}
    assert gate_bench.grade(abst, {"outcome": "UNKNOWN_ESCALATED", "cause": None, "sweep": {}})["correct"]
    assert not gate_bench.grade(abst, {"outcome": "CONFIRMED", "cause": "D-z", "sweep": {}})["correct"]


def test_committed_examples_reread_consistently():
    dirs = sorted(p for p in (ROOT / "examples").iterdir() if p.is_dir())
    res = [run_artefacts.check(d) for d in dirs]
    assert all(r["ok"] for r in res), [r for r in res if not r["ok"]]
    names = {d.name for d in dirs}
    assert {"s1-hero", "s2-data-incident", "s4-no-incident", "s5-bad-fix", "s6-preflight-block"} <= names
    for d in dirs:
        for f in ("transcript.jsonl", "verify.txt", "cost.json"):
            assert (d / f).exists(), (d.name, f)
        assert json.loads((d / "cost.json").read_text())["tokens"] == {"input": 0, "output": 0}
    s5 = ROOT / "examples" / "s5-bad-fix"
    for f in ("remediation_rejected.json", "data_bad_fix_rejected.json"):
        r = json.loads((s5 / f).read_text())
        assert r["verdict"] == "NOT_APPLIED" and r["success_written"] is False and r["environment_restored"] is True
    assert (ROOT / "examples" / "s1-hero" / "pr.md").exists()
    assert "verified 7/7" in (ROOT / "examples" / "s1-hero" / "verify.txt").read_text()


def test_robustness_knobs_transform_only_their_own_part_of_the_spec():
    import robustness

    case = gate_bench.generate(seed=20261015)[3]
    n_alerts = len(case["spec"]["alerts"])
    dup = robustness._spec(case, "duplicates", 5)
    assert len(dup["alerts"]) == 5 * n_alerts and len({a["id"] for a in dup["alerts"]}) == len(dup["alerts"])
    assert {a["target"] for a in dup["alerts"]} == {a["target"] for a in case["spec"]["alerts"]}
    assert robustness._spec(case, "noise", 4)["noise"] == 0.6 and "noise" not in case["spec"]  # deep copy, base untouched
    inter = robustness._spec(case, "intermittent", 1)["effects"]
    assert all(e.get("until") for e in inter) and len(inter) == 5 * len(case["spec"]["effects"])
    starts = sorted(int(e["from"][:-1]) for e in inter if e["target"] == case["spec"]["effects"][0]["target"])
    assert all(b - a == 2 for a, b in zip(starts, starts[1:]))  # one minute on, one minute off


def test_ladder_switch_restores_the_gate_weights():
    import ladder
    from faultline.agent.weights import weights

    before = dict(weights()["gate"])
    with ladder._switched(ladder.RUNGS["neither"]):
        assert weights()["gate"]["flow_slack"] == 0.0 and weights()["gate"]["ablate_g2_connectivity"] is True
    assert weights()["gate"] == before


def test_ladder_and_robustness_summary_keys():
    lad = {"seed": 1, "cases": 2, "rungs": {"full": {"cases": 2, "correct": 2, "wrong_confident": 0, "abstained": 1}}}
    rob = {"seed": 1, "baseline": {"cases": 2, "correct": 2, "wrong_confident": 0, "abstained": 1},
           "knobs": {"missing": {"breaking_point": 0.2, "levels": {"0.2": {"correct": 1, "wrong_confident": 0, "abstained": 2}}}}}
    s = {**report.ladder_summary(lad), **report.robustness_summary(rob)}
    assert s["ladder.full.correct"] == 2 and s["robustness.missing.0.2.correct"] == 1
    assert s["robustness.missing.breaking_point"] == 0.2 and s["robustness.baseline.abstained"] == 1
    md = "\n".join(report.ladder_markdown(lad, s) + report.robustness_markdown(rob))
    assert "20% missing" in md and "| full product | 2 | n/a | 1 | 0 | n/a | n/a |" in md
    assert report.ladder_summary({}) == {} and report.robustness_summary({}) == {}


def test_perf_summary_keys_and_depth_caveat():
    import perf_vs_flat

    assert perf_vs_flat.pct([3.0, 1.0, 2.0, 4.0], 50) == 2.0 and perf_vs_flat.pct([1.0] * 19 + [9.0], 95) == 1.0
    st = {"p50": 1.0, "p95": 2.0, "n": 20}
    x = {"lookups": {"acme": {"edges": 5, "lookups": {"reach_set": {
             "template": "Q-BLAST-1", "instances": 2, "equal": 2, "non_empty": 2, "falkordb_roundtrip_ms": st,
             "falkordb_engine_ms": st, "duckdb_sql_ms": st}}}},
         "freshness": {"alert": {"writes": 3, "write_to_visible_ms": st, "first_read_saw_it": 3}},
         "depth": {"groups": {"0": {"cases": 2, "gate_correct": 2, "arm_t_score": 1.5},
                              "no true cause": {"cases": 1, "gate_correct": 1, "arm_t_score": 0.0}}}}
    s = report.perf_summary(x)
    assert s["perf.acme.reach_set.equal"] == 2 and s["perf.acme.reach_set.sql_p95"] == 2.0
    assert s["perf.fresh.alert.p50_ms"] == 1.0 and s["perf.depth.no_true_cause.cases"] == 1
    assert s["perf.acme.reach_set.non_empty"] == 2
    md = "\n".join(report.perf_markdown(x))
    assert "no true cause two or more hops" in md and "| acme (5 edges) | reach_set (Q-BLAST-1) | 2/2 (2 non-empty) |" in md
    assert "not replication lag" in md
    x["depth"]["groups"]["2"] = {"cases": 1, "gate_correct": 1, "arm_t_score": 0.0}
    assert "two or more hops" not in "\n".join(report.perf_markdown(x))
    assert report.perf_summary({}) == {} and report.perf_markdown({}) == []


def test_robustness_notes_name_breaking_points_and_the_failed_expectation():
    rob = {"baseline": {"cases": 2, "correct": 2}, "knobs": {
        "missing": {"breaking_point": 0.2, "levels": {"0.2": {"correct": 1, "wrong_confident": 0, "abstained": 2}}},
        "noise": {"breaking_point": None, "levels": {}}}}
    lad = {"rungs": {"full": {"wrong_confident": 0}, "neither": {"wrong_confident": 0}}}
    n = report.robustness_notes(rob, lad, {"depth": {"groups": {"0": {}, "1": {}}}})
    assert len(n) == 3 and "`missing`" in n[0] and "expectation was wrong" in n[1] and "two or more hops" in n[2]
    lad["rungs"]["neither"]["wrong_confident"] = 3
    assert len(report.robustness_notes(rob, lad, {})) == 1


def test_bench_detail_and_buckets_place_every_case_once():
    exp = {"outcome": "CONFIRMED", "cause": "D-1", "eliminated": {"D-2": "G5", "D-3": "G2"}}
    d = gate_bench.detail(exp, "CONFIRMED", "D-1", {"D-1": "candidate: path", "D-2": "eliminated: G4 origin: x",
                                                    "D-3": "eliminated: G2: no path"})
    assert d == {"right_cause": True, "decoys_by": {"D-2": "G4 origin", "D-3": "G2"}}
    assert gate_bench.detail(exp, "NOT_CONFIDENT", None, {})["decoys_by"] == {"D-2": "absent", "D-3": "absent"}
    cases = [{"id": i, "expected": exp if i != "e" else {"outcome": "NOT_CONFIDENT", "cause": None}} for i in "abcde"]
    rows = [{"id": "a", "correct": True, "wrong_confident": False, "right_cause": True, "abstained": False, "decoys_by": {"D-2": "G5"}},
            {"id": "b", "correct": False, "wrong_confident": False, "right_cause": True, "abstained": False, "decoys_by": {"D-2": "G4 origin"}},
            {"id": "c", "correct": False, "wrong_confident": False, "right_cause": False, "abstained": True, "decoys_by": {}},
            {"id": "d", "correct": False, "wrong_confident": True, "right_cause": False, "abstained": False, "decoys_by": {}},
            {"id": "e", "correct": False, "wrong_confident": False, "right_cause": False, "abstained": False, "decoys_by": {}}]
    b = gate_bench.buckets(rows, cases)
    assert (b["correct"], b["right_cause_other_gate"], b["abstained_not_correct"], b["wrong_confident"], b["other"]) == (1, 1, 1, 1, 1)
    assert b["right_cause"] == 2 and b["confirm_cases"] == 4 and b["decoys_eliminated_by"] == {"G4 origin": 1, "G5": 1}


def test_g2_connectivity_ablation_refuses_a_product_graph(monkeypatch):
    import pytest

    from faultline.mcp_server import tools

    class _RO:
        graph_name = "tenant_acme"

    monkeypatch.setattr(tools, "_ro", lambda: _RO())
    with pytest.raises(RuntimeError, match="eval-only"):
        tools._g2_connectivity_ablation("D-1", "checkout")


def test_deep_bench_generation_and_report():
    import deep_bench

    cs = deep_bench.generate(seed=deep_bench.SEED)
    assert len(cs) == 140 and cs == deep_bench.generate(seed=deep_bench.SEED)   # deterministic
    for c in cs:
        targets = {x["target"] for x in c["spec"]["inject"]}
        faults = {e["target"]: e for e in c["spec"]["effects"]}
        if c["category"] in ("two_causes_chain", "weak_link", "late_upstream", "noisy_upstream"):
            s, u = c["symptom"], c["lookalike"]
            assert s in targets and s in faults and u in faults and c["spec"]["alerts"][0]["target"] == s
            assert (u in targets) == (c["category"] != "noisy_upstream")
            assert faults[u]["from"] == ("0m" if c["category"] == "late_upstream" else "-2m")
            assert c["expected"]["cause"] is None if c["category"] == "two_causes_chain" else c["expected"]["cause"]
            continue
        if c["category"] == "abstain_downstream":
            assert c["expected"]["cause"] is None and c["origin"] not in targets   # nothing changed where it broke
        else:
            assert c["expected"]["outcome"] == "CONFIRMED" and c["origin"] in targets and c["lookalike"] in targets
        if c["category"] == "symptom_decoy":
            assert c["lookalike"] == c["symptom"]
    v = {"cases": 2, "ok": 2, "right_cause": 2, "correct": 2, "wrong_confident": 0, "abstained": 0, "arm_t": 1.5}
    x = {"fresh": {"seed": 1, "all": {**v, "buckets": {"decoys_eliminated_by": {"G4 upstream": 2}}},
                   "by_category": {"deep_onpath": v}, "by_hops": {"2": v}}}
    s = report.deep_summary(x)
    assert s["deep.fresh.deep_onpath.right_cause"] == 2 and s["deep.fresh.hops.2.arm_t"] == 1.5
    assert s["deep.fresh.decoys_by.G4_upstream"] == 2
    assert "| fresh (1) | deep_onpath | 2 | 2 | 2 | 0 | 0 | 1.5 |" in "\n".join(report.deep_markdown(x))
