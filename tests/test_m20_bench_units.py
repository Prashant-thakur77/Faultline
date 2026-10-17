"""Unit (no engine, no NetworkX): the M20 Wave B benches compute what they claim (tenants_bench, the scale tail and
merge, algo10k's answer checks) and their report keys are claim-tagged."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import algo10k as A  # noqa: E402
import report  # noqa: E402
import scale  # noqa: E402
import tenants_bench as T  # noqa: E402
from faultline.graph.tenant import check_tenant, graph_belongs_to  # noqa: E402


# ------------------------------------------------------------------ tenants_bench
def test_bench_tenants_are_valid_tenants_with_their_own_graph():
    t = T.tenant_id(7)
    assert t == "dens0007" and check_tenant(t) == t
    assert graph_belongs_to(T.graph_of(t), t) and not graph_belongs_to(T.graph_of(t), T.tenant_id(8))
    assert not T.graph_of(t).startswith("tenant_")   # a running API's tenant discovery never lists bench graphs


def test_percentiles_are_nearest_rank_with_p99():
    xs = list(range(1, 201))
    st = T.lat_stats([float(x) for x in xs])
    assert st["p50"] == 100 and st["p95"] == 190 and st["p99"] == 198 and st["max"] == 200
    assert T.pct([], 0.99) is None and T.lat_stats([])["n"] == 0
    sk = T.quantile_sketch([float(x) for x in xs], points=4)
    assert sk == [50.0, 100.0, 150.0, 200.0]


def test_memory_guard_refuses_a_step_over_the_ceiling_or_the_host():
    ok, why = T.step_allowed(used_mb=1000, mb_per_tenant=10, new=100, host_avail_mb=8000)
    assert ok and why == ""
    ok, why = T.step_allowed(used_mb=1500, mb_per_tenant=10, new=100, host_avail_mb=8000)
    assert not ok and "ceiling" in why            # 1500 + 1.2 * 10 * 100 = 2700 > 2500
    ok, why = T.step_allowed(used_mb=500, mb_per_tenant=10, new=100, host_avail_mb=2500)
    assert not ok and "MemAvailable" in why       # 2500 - 1200 < 2000


def test_acl_rules_are_the_shipped_ro_line_retargeted():
    tpl = (ROOT / "deploy" / "users.acl.template").read_text()
    toks = T.ro_rule_tokens(tpl, "dens0042", "pw")
    assert ">pw" in toks and "resetchannels" in toks and "-@all" in toks and "+graph.ro_query" in toks
    assert "~eval_dens0042_*" in toks and "~tenant_dens0042" in toks
    assert not any("acme" in t for t in toks) and not any("${" in t for t in toks)
    assert not any(t in ("+graph.query", "+@all", "~*") for t in toks)
    with pytest.raises(ValueError):
        T.ro_rule_tokens("user default off\n", "dens0001", "pw")


def test_workers_split_into_at_most_eight_processes():
    assert T.split_workers(1) == [1]
    assert T.split_workers(8) == [1] * 8
    assert T.split_workers(64) == [8] * 8
    assert T.split_workers(32) == [4] * 8
    assert sum(T.split_workers(13)) == 13 and len(T.split_workers(13)) == 8


def test_error_classes():
    assert T.error_class(Exception("NOPERM this user has no permissions")) == "noperm"
    assert T.error_class(Exception("Q-GATE-1: Query timed out")) == "timeout"
    assert T.error_class(Exception("Max pending queries exceeded")) == "queue_full"
    assert T.error_class(Exception("something else")) == "other"
    assert T.wilson_hi(0, 1000) == pytest.approx(0.0038, abs=1e-4) and T.wilson_hi(0, 0) is None


# ------------------------------------------------------------------ scale: tail, merge
def test_scale_tail_stats_and_engine_time_from_bytes_replies():
    st = scale.tail_stats([float(x) for x in range(1, 201)])
    assert st == {"n": 200, "p50": 100.0, "p95": 190.0, "p99": 198.0, "max": 200.0}

    class Res:
        _raw_stats = [b"Cached execution: 1", b"Query internal execution time: 0.412000 milliseconds"]
    assert scale.engine_ms(Res()) == pytest.approx(0.412)
    with pytest.raises(ValueError):
        scale.engine_ms(type("R", (), {"_raw_stats": []})())


def test_scale_merge_keeps_other_sizes_only_on_the_same_engine():
    old = {"digest": "d", "sizes": {"1k": {"services": 1000}, "10k": {"services": 10000}}, "started": "2026-10-17T10",
           "finished": "2026-10-17T11", "reason": "a"}
    new = {"digest": "d", "sizes": {"3k": {"services": 3000}}, "started": "2026-10-17T12", "finished": "2026-10-17T13",
           "reason": "b"}
    m = scale.merge_runs(old, new)
    assert list(m["sizes"]) == ["1k", "3k", "10k"] and m["started"] == "2026-10-17T10" and m["finished"] == "2026-10-17T13"
    assert [i["reason"] for i in m["invocations"]] == ["a", "b"]
    assert list(scale.merge_runs({**old, "digest": "other"}, new)["sizes"]) == ["3k"]
    assert scale.prior_per_service(old) is None
    assert scale.prior_per_service({"sizes": {"1k": {"services": 1000, "memory_mb": 42}}}) == pytest.approx(0.042)


def test_scale_tail_keys_and_bytes_per_element():
    v = {"services": 10000, "nodes": 300, "edges": 700, "memory_mb": 1, "engine_used_mb_seed_delta": 2.0,
         "tail": {"Q-GATE-1": {"engine_ms": {"n": 200, "p50": 1.0, "p95": 2.0, "p99": 3.0, "max": 4.0},
                               "wall_ms": {"p50": 1.5, "p99": 3.5}, "errors": 0}}}
    k = report.scale_tail_keys("scale.10k", v)
    assert k["scale.10k.tail.Q-GATE-1.engine_ms_p99"] == 3.0 and k["scale.10k.tail.Q-GATE-1.runs"] == 200
    assert k["scale.10k.bytes_per_elem"] == round(2**20 / 1000) and k["scale.10k.used_bytes_per_elem"] == round(2 * 2**20 / 1000)
    md = "\n".join(report.scale_tail_markdown({"sizes": {"10k": v}}))
    assert "<!-- claim:scale.10k.tail.Q-GATE-1.engine_ms_p99 -->3.0<!-- /claim -->" in md


# ------------------------------------------------------------------ algo10k: answer checks
def test_top_k_breaks_ties_by_id_and_partitions_ignore_labels():
    assert A.top_k({"b": 1.0, "a": 1.0, "c": 2.0}, 2) == ["c", "a"]
    assert A.partition({"x": 1, "y": 1, "z": 7}) == {frozenset({"x", "y"}), frozenset({"z"})}
    assert A.partition({"x": "p", "y": "p", "z": "q"}) == A.partition({"x": 0, "y": 0, "z": 5})
    assert A.rel_close(1.0, 1.0 + 1e-9) and not A.rel_close(1.0, 1.01)


def test_sppaths_compare_needs_same_weights_and_same_unique_paths():
    f = [(["d", "a", "s"], 2.0), (["d", "b", "s"], 3.0)]
    assert A.compare_paths(f, [(["d", "a", "s"], 2.0), (["d", "b", "s"], 3.0)])["equal"]
    assert not A.compare_paths(f, [(["d", "c", "s"], 2.0), (["d", "b", "s"], 3.0)])["equal"]   # unique weight, other path
    tie = [(["d", "a", "s"], 2.0), (["d", "b", "s"], 2.0)]
    assert A.compare_paths(tie, [(["d", "b", "s"], 2.0), (["d", "a", "s"], 2.0)])["equal"]       # ties: weights decide
    assert not A.compare_paths(f, [(["d", "a", "s"], 2.0)])["equal"]


def test_sspaths_compare_checks_every_target_below_the_largest_returned_weight():
    falkor = [(["h", "a"], 1.0), (["h", "a", "b"], 2.0), (["h", "c"], 3.0)]
    dist = {"h": 0.0, "a": 1.0, "b": 2.0, "c": 3.0, "d": 5.0}
    hops = {"h": 0, "a": 1, "b": 2, "c": 1, "d": 3}
    r = A.compare_sspaths(falkor, dist, hops, "h")
    assert r["equal"] and r["targets_checked"] == 2 and r["nx_reachable"] == 4   # c is at the boundary, d beyond it
    r = A.compare_sspaths([(["h", "c"], 3.0)], dist, hops, "h")
    assert not r["equal"] and r["missing"] == ["a", "b"]
    r = A.compare_sspaths([(["h", "a"], 1.5), (["h", "c"], 3.0)], dist, hops, "h")
    assert not r["equal"] and r["wrong"] == ["a"]


def test_every_procedure_has_a_criterion_and_a_call_with_registry_placeholders():
    assert set(A.CALLS) == set(A.CRITERIA) == set(report.ALGO_ORDER)
    assert all("{algo:" in q and "algo." not in q.replace("{algo:", "") for q in A.CALLS.values())
    tg = {"cause_component": "c", "symptom": "s", "hub": "h", "deploy_on_cause": "d1", "deploy_on_hub": "d2"}
    wp = A.workload_params(tg, 42)
    assert set(wp) == set(A.CALLS) and [t for t, _, _ in wp["maxflow"]] == ["single", "joint"]
    assert wp["betweenness"][0][2] == {"n": 42} and wp["maxflow"][1][2]["srcs"] == ["c", "h"]


# ------------------------------------------------------------------ report keys
def _fake_tenants() -> dict:
    lat = {"n": 10, "p50": 1.0, "p95": 2.0, "p99": 3.0, "max": 4.0, "mean": 1.2}
    return {"machine": {"cpus": 20}, "config": {"THREAD_COUNT": 20, "MAX_QUEUED_QUERIES": 50, "maxmemory_mb": 3500.0},
            "density": {"n": 300, "used_mb_at_n": 2100.0, "steps": [{"concurrent_activity": False}],
                        "stopped": [{"kind": "product", "before_total": 150, "reason": "ceiling"}],
                        "kinds": {"product": {"n": 100, "mb_per_tenant": 14.2, "copy_ms": lat, "copy_raw_ms": lat,
                                              "source": {"nodes": 1949, "edges": 5946, "graph_memory_usage_mb": 2}},
                                  "small": {"n": 200, "mb_per_tenant": 2.9, "copy_ms": lat, "copy_raw_ms": lat,
                                            "source": {"nodes": 500, "edges": 900, "graph_memory_usage_mb": 0}}}},
            "isolation": {"users": 300, "cross_tenant": {"probes": 1000, "denied": 1000, "leaks": 0, "other_errors": 0},
                          "own_graph": {"probes": 1000, "ok": 1000}, "app_layer": {"probes": 1000, "refused": 1000},
                          "forbidden_denied": 300, "forbidden_allowed": 0, "forbidden_probes": 300,
                          "sample_graphs_intact": 50, "sample": 50},
            "params": {"per_template": 48, "gate1_with_path": 12},
            "concurrency": [{"investigators": 64, "qps": 9000.0, "steps_per_s": 3000.0, "queries": 135000,
                             "latency_ms": lat, "per_template": {"Q-GATE-1": lat}, "error_total": 0,
                             "engine_cpu_cores": 9.5, "client_cpu_cores_max": 0.9, "processes": 8}]}


def test_tenants_keys_and_markdown_are_claim_tagged():
    k = report.tenants_keys(_fake_tenants())
    assert k["tenants.n"] == 300 and k["tenants.product.mb_per_tenant"] == 14.2 and k["tenants.small.n"] == 200
    assert k["tenants.acl.leaks"] == 0 and k["tenants.acl.leak.n"] == 1000 and k["tenants.acl.leak.ci_hi"] > 0
    assert k["tenants.c64.p99_ms"] == 3.0 and k["tenants.c64.Q-GATE-1.p99_ms"] == 3.0
    assert k["tenants.product.stopped_before"] == 150
    md = "\n".join(report.tenants_markdown(k))
    assert "<!-- claim:tenants.c64.p99_ms -->3.0<!-- /claim -->" in md
    assert "<!-- claim:tenants.acl.leaks -->0<!-- /claim -->" in md and "150<!-- /claim --> (memory guard)" in md
    assert report.tenants_keys({}) == {} and report.tenants_markdown({}) == []


def test_algo10k_keys_name_multi_instance_procedures_by_tag():
    e = {"p50": 2.0, "p95": 3.0, "p99": 4.0}
    def w(proc, tag, equal=True):
        return {"procedure": proc, "tag": tag, "instance": f"{proc} {tag}", "criterion": A.CRITERIA[proc], "equal": equal,
                "equal_on_projection": equal, "falkor": {"engine_ms": e, "wall_ms": {"p50": 2.5}},
                "falkor_projection": {"engine_ms": e, "wall_ms": {"p50": 2.4}},
                "nx": {"ms": {"p50": 25.0}, "runs": 5, "graph_bytes": 2**20, "algo_peak_bytes": None,
                       "input": {"nodes": 10, "edges": 20}}}
    x = {"services": 10000, "graph": {"nodes": 1, "edges": 2}, "runs": 20, "networkx": "3.7",
         "procedures": {"pagerank": "algo.pageRank", "maxflow": "algo.maxFlow", "cdlp": "algo.labelPropagation"},
         "workloads": [w("pagerank", "all"), w("maxflow", "single"), w("maxflow", "joint", False), w("cdlp", "all", None)],
         "memory": {"falkordb": {"nodes": 5, "edges": 5, "bytes": 2**21, "graph_memory_usage_mb": 1},
                    "networkx": {"bytes": 2**22}, "falkordb_bytes_per_elem": 1.0, "networkx_bytes_per_elem": 2.0,
                    "ratio_nx_over_falkordb": 2.0}}
    k = report.algo10k_keys(x)
    assert k["algo10k.pagerank.x_wall"] == 10.0 and k["algo10k.pagerank.x_engine"] == 12.5
    assert k["algo10k.maxflow.joint.equal"] is False and "algo10k.maxflow.single.falkor_ms_p99" in k
    assert k["algo10k.comparable"] == 3 and k["algo10k.same"] == 2 and k["algo10k.cdlp.equal"] is None
    assert k["algo10k.mem.falkordb_mb"] == 2.0 and k["algo10k.mem.networkx_mb"] == 4.0
    md = "\n".join(report.algo10k_markdown(k, x))
    assert "<!-- claim:algo10k.pagerank.x_wall -->10.0<!-- /claim -->" in md and "not traced (slow)" in md
    assert "| n/a |" in md and report.algo10k_keys({}) == {}
