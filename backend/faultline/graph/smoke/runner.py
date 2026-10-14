"""FalkorDB engine smoke suite (results: docs/FALKORDB_COMPAT.md).

Runs every engine behaviour Faultline depends on against one FalkorDB instance and returns one
record per item: {"id", "item", "critical", "ok", "notes", "syntax"}. `ok` is True/False, or None
for "observed, informational". Every probe runs on a throwaway `smoke_<hex>` graph that is
deleted afterwards. Nothing here is imported by the product; it exists to pin an engine and to
resolve procedure names/forms into `graph/algo/resolved.json`.

Usage:  python -m faultline.graph.smoke.runner --port 6391 --tag 6.0.2 --out docs/audit/smoke_6.0.2.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from falkordb import FalkorDB

Result = dict[str, Any]


def _short(e: BaseException, n: int = 160) -> str:
    return f"{type(e).__name__}: {str(e)[:n]}"


class Smoke:
    def __init__(self, host: str, port: int, username: str | None = None, password: str | None = None):
        self.db = FalkorDB(host=host, port=port, username=username, password=password)
        self.conn = self.db.connection
        self.results: list[Result] = []
        self.resolved: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def graph(self, edges: list[list[Any]] | None = None, rel: str = "R"):
        name = f"smoke_{uuid.uuid4().hex[:8]}"
        g = self.db.select_graph(name)
        try:
            if edges:
                # Fixed relationship type literal from code (never from input).
                g.query(
                    "UNWIND $e AS e MERGE (a:N {id:e[0]}) MERGE (b:N {id:e[1]}) "
                    f"MERGE (a)-[r:{rel}]->(b) SET r.cap = e[2], r.w = 1",
                    {"e": edges},
                )
            else:
                g.query("CREATE (:N {id:'seed'})")
            yield g
        finally:
            try:
                g.delete()
            except Exception:
                pass

    def record(self, id_: str, item: str, critical: bool, ok: bool | None, notes: str = "", syntax: str = ""):
        self.results.append(
            {"id": id_, "item": item, "critical": critical, "ok": ok, "notes": notes, "syntax": syntax}
        )

    def probe(self, id_: str, item: str, critical: bool, fn: Callable[[], tuple[bool | None, str, str]]):
        try:
            ok, notes, syntax = fn()
        except Exception as e:  # a crashing probe is a failed item, recorded verbatim
            ok, notes, syntax = False, _short(e), ""
        self.record(id_, item, critical, ok, notes, syntax)

    # ------------------------------------------------------------------ 1 names
    def p_names(self):
        def run():
            procs: list[str] = []
            try:
                with self.graph() as g:
                    rows = g.ro_query("CALL dbms.procedures() YIELD name RETURN name").result_set
                    procs = sorted(r[0] for r in rows)
            except Exception as e:
                procs = [f"<dbms.procedures failed: {_short(e, 80)}>"]
            algos = [p for p in procs if p.lower().startswith("algo.")]
            return None, f"{len(procs)} procedures; algo.*: {', '.join(algos)}", "CALL dbms.procedures() YIELD name"

        self.probe("1a", "Procedure listing (dbms.procedures)", False, run)

    # ------------------------------------------------------------------ algorithms
    def p_bfs(self):
        def run():
            edges = [["a", "b", 1], ["b", "c", 1], ["a", "d", 1]]
            tried = []
            for name in ("algo.BFS", "algo.bfs"):
                try:
                    with self.graph(edges) as g:
                        q1 = f"MATCH (s:N {{id:'a'}}) CALL {name}(s, 1, 'R') YIELD nodes RETURN [n IN nodes | n.id] AS ids"
                        q2 = f"MATCH (s:N {{id:'a'}}) CALL {name}(s, 2, 'R') YIELD nodes RETURN [n IN nodes | n.id] AS ids"
                        d1 = sorted(g.ro_query(q1).result_set[0][0])
                        d2 = sorted(g.ro_query(q2).result_set[0][0])
                    ok = set(d1) >= {"b", "d"} and "c" not in d1 and set(d2) >= {"b", "c", "d"}
                    self.resolved["bfs"] = {"name": name, "form": "positional(node, depth, relType)"}
                    return ok, f"depth1={d1} depth2={d2}", f"CALL {name}(s, depth, 'REL') YIELD nodes, edges"
                except Exception as e:
                    tried.append(f"{name}: {_short(e, 90)}")
            return False, "; ".join(tried), ""

        self.probe("2", "algo.BFS (chain a→b→c, a→d)", True, run)

    def p_sppaths(self):
        def run():
            # Diamond: s→a→t (w 1+1), s→b→t (w 1+5)
            name = f"smoke_{uuid.uuid4().hex[:8]}"
            g = self.db.select_graph(name)
            try:
                g.query(
                    "UNWIND $e AS e MERGE (x:N {id:e[0]}) MERGE (y:N {id:e[1]}) MERGE (x)-[r:R]->(y) SET r.w=e[2]",
                    {"e": [["s", "a", 1], ["a", "t", 1], ["s", "b", 1], ["b", "t", 5]]},
                )
                q = (
                    "MATCH (s:N {id:'s'}), (t:N {id:'t'}) "
                    "CALL algo.SPpaths({sourceNode: s, targetNode: t, relTypes: ['R'], weightProp: 'w', "
                    "relDirection: 'outgoing', maxLen: 6, pathCount: $k}) YIELD path, pathWeight "
                    "RETURN [n IN nodes(path) | n.id] AS chain, pathWeight ORDER BY pathWeight"
                )
                one = g.ro_query(q, {"k": 1}).result_set
                two = g.ro_query(q, {"k": 2}).result_set
                notes = f"k=1 → {one}; k=2 → {two}"
                # weightProp optional?
                try:
                    noweight = g.ro_query(
                        "MATCH (s:N {id:'s'}), (t:N {id:'t'}) CALL algo.SPpaths({sourceNode: s, targetNode: t, "
                        "relTypes: ['R'], maxLen: 6, pathCount: 1}) YIELD path RETURN length(path)"
                    ).result_set
                    notes += f"; without weightProp → {noweight}"
                except Exception as e:
                    notes += f"; without weightProp → error {_short(e, 80)}"
                # maxLen honoured
                ml = g.ro_query(
                    "MATCH (s:N {id:'s'}), (t:N {id:'t'}) CALL algo.SPpaths({sourceNode: s, targetNode: t, "
                    "relTypes: ['R'], weightProp: 'w', maxLen: 1, pathCount: 1}) YIELD path RETURN count(path)"
                ).result_set
                notes += f"; maxLen 1 → {ml}"
                # no path → empty result (the negative proof)
                np = g.ro_query(
                    "MATCH (s:N {id:'t'}), (t:N {id:'s'}) CALL algo.SPpaths({sourceNode: s, targetNode: t, "
                    "relTypes: ['R'], weightProp: 'w', relDirection: 'outgoing', maxLen: 6, pathCount: 1}) "
                    "YIELD path RETURN count(path)"
                ).result_set
                notes += f"; reverse (no path) → {np}"
                ok = (
                    bool(one) and one[0][0] == ["s", "a", "t"] and len(two) == 2
                    and ml[0][0] == 0 and np[0][0] == 0
                )
                self.resolved["sppaths"] = {"name": "algo.SPpaths", "form": "map"}
                return ok, notes, "CALL algo.SPpaths({sourceNode, targetNode, relTypes, weightProp, relDirection, maxLen, pathCount}) YIELD path, pathWeight, pathCost"
            finally:
                g.delete()

        self.probe("3", "algo.SPpaths (diamond; weightProp, maxLen, pathCount, no-path)", True, run)

    def p_sspaths(self):
        def run():
            with self.graph([["s", "a", 1], ["s", "b", 1], ["a", "c", 1]]) as g:
                q = (
                    "MATCH (s:N {id:'s'}) CALL algo.SSpaths({sourceNode: s, relTypes: ['R'], weightProp: 'w', "
                    "relDirection: 'outgoing', maxLen: $ml, pathCount: $pc}) YIELD path "
                    "RETURN last(nodes(path)).id AS reached ORDER BY reached"
                )
                r1 = [x[0] for x in g.ro_query(q, {"ml": 1, "pc": 1000}).result_set]
                r2 = [x[0] for x in g.ro_query(q, {"ml": 2, "pc": 1000}).result_set]
                try:
                    r0 = [x[0] for x in g.ro_query(q, {"ml": 2, "pc": 0}).result_set]
                except Exception as e:
                    r0 = [f"error {_short(e, 60)}"]
            ok = sorted(set(r1)) == ["a", "b"] and "c" in r2
            self.resolved["sspaths"] = {"name": "algo.SSpaths", "form": "map", "pathCount": 1000, "note": "pathCount is a global top-k over all targets; 0 = min-weight ties only; full result ⇒ possibly truncated ⇒ UNKNOWN"}
            return ok, f"maxLen1 pc1000 → {r1}; maxLen2 pc1000 → {r2}; maxLen2 pc0 (min-weight ties only) → {r0}", "CALL algo.SSpaths({sourceNode, relTypes, weightProp, relDirection, maxLen, pathCount:1000}) YIELD path"

        self.probe("4", "algo.SSpaths (reachability; pathCount semantics)", True, run)

    def p_pagerank(self):
        def run():
            edges = [[f"l{i}", "hub", 1] for i in range(4)]
            tried = []
            for name in ("algo.pageRank", "algo.PageRank"):
                try:
                    with self.graph(edges) as g:
                        rows = g.ro_query(
                            f"CALL {name}('N', 'R') YIELD node, score RETURN node.id, score ORDER BY score DESC"
                        ).result_set
                    ok = rows[0][0] == "hub"
                    self.resolved["pagerank"] = {"name": name, "form": "positional(label, relType)"}
                    return ok, f"top={rows[0]}", f"CALL {name}('Label', 'REL') YIELD node, score"
                except Exception as e:
                    tried.append(f"{name}: {_short(e, 90)}")
            return False, "; ".join(tried), ""

        self.probe("5", "algo.pageRank (star → hub highest)", True, run)

    def p_betweenness(self):
        def run():
            edges = [["a", "b", 1], ["b", "c", 1], ["c", "d", 1], ["d", "e", 1]]
            with self.graph(edges) as g:
                q = (
                    "CALL algo.betweenness({nodeLabels:['N'], relationshipTypes:['R'], samplingSize: 64, "
                    "samplingSeed: 42}) YIELD node, score RETURN node.id, score ORDER BY score DESC, node.id"
                )
                a = g.ro_query(q).result_set
                b = g.ro_query(q).result_set
            ok = a[0][0] == "c" and a == b
            self.resolved["betweenness"] = {"name": "algo.betweenness", "form": "map", "samplingSeed": 42}
            return ok, f"top={a[0]}; deterministic={a == b}", "CALL algo.betweenness({nodeLabels, relationshipTypes, samplingSize, samplingSeed:42}) YIELD node, score"

        self.probe("6", "algo.betweenness (path a-b-c-d-e; seeded determinism)", True, run)

    def p_harmonic(self):
        def run():
            # symmetric star centred on c
            edges = []
            for leaf in ("x", "y", "z"):
                edges += [["c", leaf, 1], [leaf, "c", 1]]
            tried = []
            for name in ("algo.HarmonicCentrality", "algo.harmonicCentrality"):
                try:
                    with self.graph(edges) as g:
                        rows = g.ro_query(
                            f"CALL {name}({{nodeLabels:['N'], relationshipTypes:['R']}}) YIELD node, score, reachable "
                            "RETURN node.id, score, reachable ORDER BY score DESC, node.id"
                        ).result_set
                    ok = rows[0][0] == "c"
                    self.resolved["harmonic"] = {"name": name, "form": "map"}
                    return ok, f"top={rows[0]}", f"CALL {name}({{nodeLabels, relationshipTypes}}) YIELD node, score, reachable"
                except Exception as e:
                    tried.append(f"{name}: {_short(e, 90)}")
            return False, "; ".join(tried), ""

        self.probe("7", "algo.HarmonicCentrality (symmetric star → centre)", True, run)

    def p_wcc(self):
        def run():
            edges = [["a", "b", 1], ["c", "d", 1]]
            tried = []
            for name in ("algo.WCC", "algo.wcc"):
                try:
                    with self.graph(edges) as g:
                        rows = g.ro_query(
                            f"CALL {name}({{nodeLabels:['N'], relationshipTypes:['R']}}) YIELD node, componentId "
                            "RETURN componentId, collect(node.id) ORDER BY componentId"
                        ).result_set
                    ok = len(rows) == 2
                    self.resolved["wcc"] = {"name": name, "form": "map"}
                    return ok, f"components={[sorted(r[1]) for r in rows]}", f"CALL {name}({{nodeLabels, relationshipTypes}}) YIELD node, componentId"
                except Exception as e:
                    tried.append(f"{name}: {_short(e, 90)}")
            return False, "; ".join(tried), ""

        self.probe("8", "algo.WCC (two disjoint pairs → 2 components)", True, run)

    def p_cdlp(self):
        def run():
            edges = []
            for tri in (("a", "b", "c"), ("x", "y", "z")):
                for i in range(3):
                    u, v = tri[i], tri[(i + 1) % 3]
                    edges += [[u, v, 1], [v, u, 1]]
            tried = []
            for name in ("algo.labelPropagation", "algo.CDLP"):
                try:
                    with self.graph(edges) as g:
                        rows = g.ro_query(
                            f"CALL {name}({{nodeLabels:['N'], relationshipTypes:['R'], maxIterations: 10}}) "
                            "YIELD node, communityId RETURN communityId, collect(node.id) ORDER BY communityId"
                        ).result_set
                    ok = len(rows) == 2
                    self.resolved["cdlp"] = {"name": name, "form": "map"}
                    return ok, f"communities={[sorted(r[1]) for r in rows]}", f"CALL {name}({{nodeLabels, relationshipTypes, maxIterations}}) YIELD node, communityId"
                except Exception as e:
                    tried.append(f"{name}: {_short(e, 90)}")
            return False, "; ".join(tried), ""

        self.probe("9", "algo.labelPropagation (two triangles → 2 communities)", True, run)

    def p_maxflow(self):
        def run():
            edges = [["s", "a", 10], ["s", "b", 10], ["a", "c", 1], ["b", "c", 2], ["c", "t", 10]]
            forms = {
                "map_nodes": (
                    "MATCH (s:N {id:'s'}), (t:N {id:'t'}) CALL algo.maxFlow({sourceNodes:[s], targetNodes:[t], "
                    "relationshipTypes:['R'], capacityProperty:'cap'}) YIELD nodes, edges, edgeFlows, maxFlow "
                    "RETURN [n IN nodes | n.id], [e IN edges | [startNode(e).id, endNode(e).id]], edgeFlows, maxFlow"
                ),
                "map_ids": (
                    "CALL algo.maxFlow({sourceNodes:['s'], targetNodes:['t'], relationshipTypes:['R'], "
                    "capacityProperty:'cap'}) YIELD maxFlow RETURN maxFlow"
                ),
                "pos_ids": "CALL algo.maxFlow('s', 't', {relationshipTypes:['R'], capacityProperty:'cap'}) YIELD maxFlow RETURN maxFlow",
            }
            notes, winner, detail = [], None, None
            with self.graph(edges) as g:
                for form, q in forms.items():
                    try:
                        row = g.ro_query(q).result_set[0]
                        notes.append(f"{form}: ok")
                        if winner is None:
                            winner, detail = form, row
                    except Exception as e:
                        notes.append(f"{form}: {_short(e, 70)}")
                # multi-source / multi-target (joint G5, 2-target cut)
                try:
                    g.query("MERGE (x:N {id:'x'}) WITH x MATCH (c:N {id:'c'}) MERGE (x)-[r:R]->(c) SET r.cap = 4, r.w = 1")
                    ms = g.ro_query(
                        "MATCH (s:N {id:'s'}), (x:N {id:'x'}), (t:N {id:'t'}) CALL algo.maxFlow({sourceNodes:[s, x], "
                        "targetNodes:[t], relationshipTypes:['R'], capacityProperty:'cap'}) YIELD maxFlow RETURN maxFlow"
                    ).result_set[0][0]
                    notes.append(f"multi-source [s,x] → {ms} (expect 7)")
                    mt = g.ro_query(
                        "MATCH (s:N {id:'s'}), (a:N {id:'a'}), (t:N {id:'t'}) CALL algo.maxFlow({sourceNodes:[s], "
                        "targetNodes:[a, t], relationshipTypes:['R'], capacityProperty:'cap'}) YIELD maxFlow RETURN maxFlow"
                    ).result_set[0][0]
                    notes.append(f"multi-target [a,t] → {mt}")
                    multi_ok = abs(float(ms) - 7) < 1e-9 and float(mt) >= 10
                except Exception as e:
                    notes.append(f"multi-source/target: {_short(e, 70)}")
                    multi_ok = False
            if winner != "map_nodes" or detail is None:
                return False, "; ".join(notes), ""
            nodes, edge_pairs, flows, mf = detail
            notes.insert(0, f"maxFlow={mf!r} ({type(mf).__name__}); edges={edge_pairs}; edgeFlows={flows}")
            # min-cut via residual reachability, computed in code from capacities + edgeFlows
            cap = {(u, v): c for u, v, c in edges}
            flow = {tuple(p): f for p, f in zip(edge_pairs, flows)}
            from faultline.graph.algo.maxflow import min_cut  # sanctioned in-code routine

            cut, _ = min_cut({"s"}, [(u, v, f"{u}>{v}") for u, v, _ in edges],
                             {f"{u}>{v}": float(c) for (u, v), c in cap.items()},
                             {f"{u}>{v}": float(f) for (u, v), f in flow.items()}, float(mf))
            cut_set = sorted((u, v) for u, v, _ in cut)
            notes.append(f"min-cut(in code)={cut_set}")
            ok = abs(float(mf) - 3) < 1e-9 and cut_set == [("a", "c"), ("b", "c")] and multi_ok
            self.resolved["maxflow"] = {"name": "algo.maxFlow", "form": "map_nodes"}
            return ok, "; ".join(notes), "CALL algo.maxFlow({sourceNodes:[nodes], targetNodes:[nodes], relationshipTypes, capacityProperty}) YIELD nodes, edges, edgeFlows, maxFlow"

        self.probe("10", "algo.maxFlow (fixture → 3; forms; edgeFlows; min-cut {a→c,b→c})", True, run)

    def p_msf(self):
        def run():
            name = f"smoke_{uuid.uuid4().hex[:8]}"
            g = self.db.select_graph(name)
            try:
                g.query(
                    "UNWIND $e AS e MERGE (x:P {id:e[0]}) MERGE (y:P {id:e[1]}) MERGE (x)-[r:K]->(y) SET r.w = e[2]",
                    {"e": [["a", "b", 1], ["b", "c", 2], ["a", "c", 3]]},
                )
                rows = g.ro_query(
                    "CALL algo.MSF({nodeLabels:['P'], relationshipTypes:['K'], objective:'maximize', "
                    "weightAttribute:'w'}) YIELD edges, nodes RETURN [e IN edges | e.w] AS ws"
                ).result_set
            finally:
                g.delete()
            ws = sorted(w for r in rows for w in r[0])
            ok = ws == [2, 3]
            self.resolved["msf"] = {"name": "algo.MSF", "form": "map"}
            return ok, f"tree edge weights={ws}", "CALL algo.MSF({nodeLabels, relationshipTypes, objective:'maximize', weightAttribute}) YIELD edges, nodes"

        self.probe("11", "algo.MSF (triangle 1,2,3 maximize → {2,3})", True, run)

    # ------------------------------------------------------------------ RO / timeouts
    def p_algo_under_ro(self):
        algo = [r for r in self.results if r["id"] in {"2", "3", "4", "5", "6", "7", "8", "9", "10", "11"}]
        ok_all = len(algo) == 10 and all(r["ok"] for r in algo)  # every probe above ran via ro_query
        self.record("12", "All algo.* above executed under GRAPH.RO_QUERY", True, ok_all,
                    "every algorithm probe used ro_query", "GRAPH.RO_QUERY g \"CALL algo.…\"")

    def p_ro_rejects_write(self):
        def run():
            with self.graph() as g:
                try:
                    g.ro_query("CREATE (:X {id:'x'})")
                    return False, "write accepted under RO_QUERY", ""
                except Exception as e:
                    return True, _short(e, 100), "GRAPH.RO_QUERY rejects CREATE"

        self.probe("13", "GRAPH.RO_QUERY rejects writes", True, run)

    def p_timeout(self):
        def run():
            with self.graph() as g:
                slow = "UNWIND range(1, 50000000) AS x WITH x WHERE x % 7 = 0 RETURN count(x)"
                t0 = time.perf_counter()
                cut_off, msg = False, ""
                try:
                    g.ro_query(slow, timeout=200)
                except Exception as e:
                    cut_off, msg = "timed out" in str(e).lower(), _short(e, 80)
                ms = (time.perf_counter() - t0) * 1000
                raw_ok = True
                try:
                    self.conn.execute_command("GRAPH.RO_QUERY", g.name, "RETURN 1", "TIMEOUT", 500)
                except Exception as e:
                    raw_ok, msg = False, msg + f"; raw TIMEOUT form: {_short(e, 60)}"
                over = ""
                try:
                    g.ro_query("RETURN 1", timeout=999999)
                    over = "timeout > TIMEOUT_MAX accepted"
                except Exception as e:
                    over = f"timeout > TIMEOUT_MAX → {_short(e, 70)}"
            ok = cut_off and ms < 2000 and raw_ok
            return ok, f"slow query cut off={cut_off} after {ms:.0f} ms ({msg}); {over}", "ro_query(q, params, timeout=ms) / GRAPH.RO_QUERY g q TIMEOUT ms"

        self.probe("14", "Per-query TIMEOUT on RO_QUERY cuts off a slow query", True, run)

    # ------------------------------------------------------------------ indexes
    def p_fulltext(self):
        def run():
            name = f"smoke_{uuid.uuid4().hex[:8]}"
            g = self.db.select_graph(name)
            try:
                g.query("UNWIND $n AS n CREATE (:Service {id: n, name: n})", {"n": ["payment", "paywall", "checkout"]})
                g.query("CREATE FULLTEXT INDEX FOR (s:Service) ON (s.name)")
                time.sleep(0.5)
                rows = g.ro_query(
                    "CALL db.idx.fulltext.queryNodes('Service', 'pay*') YIELD node, score RETURN node.id, score ORDER BY score DESC, node.id"
                ).result_set
                got = sorted(r[0] for r in rows)
                notes = f"pay* → {got}"
                # range + fulltext on the same attribute (#3248)
                g.query("CREATE INDEX FOR (s:Service) ON (s.name)")
                time.sleep(0.3)
                rows2 = g.ro_query("CALL db.idx.fulltext.queryNodes('Service', 'pay*') YIELD node RETURN count(node)").result_set
                notes += f"; with range index on same attr → {rows2[0][0]} rows"
                # multi-property
                try:
                    g.query("CREATE (:Runbook {id:'r1', title:'payment timeout', body:'raise retries'})")
                    g.query("CREATE FULLTEXT INDEX FOR (r:Runbook) ON (r.title, r.body)")
                    time.sleep(0.3)
                    mp = g.ro_query("CALL db.idx.fulltext.queryNodes('Runbook', 'retries') YIELD node RETURN count(node)").result_set[0][0]
                    notes += f"; multi-property → {mp}"
                except Exception as e:
                    notes += f"; multi-property: {_short(e, 60)}"
                proc = ""
                try:
                    g.query("CALL db.idx.fulltext.createNodeIndex('Service', 'id')")
                    proc = "procedure form accepted"
                except Exception as e:
                    proc = f"procedure form: {_short(e, 60)}"
                notes += f"; {proc}"
            finally:
                g.delete()
            ok = got == ["payment", "paywall"]
            return ok, notes, "CREATE FULLTEXT INDEX FOR (n:L) ON (n.p); CALL db.idx.fulltext.queryNodes('L', 'pay*') YIELD node, score"

        self.probe("15", "Full-text DDL + queryNodes prefix (and #3248 check)", True, run)

    def p_vector(self):
        def run():
            name = f"smoke_{uuid.uuid4().hex[:8]}"
            g = self.db.select_graph(name)
            try:
                g.query("CREATE VECTOR INDEX FOR (i:Incident) ON (i.embedding) OPTIONS {dimension:384, similarityFunction:'cosine'}")
                base = [0.0] * 384
                v_near = base.copy()
                v_near[0], v_near[1] = 1.0, 0.1
                v_far = base.copy()
                v_far[5] = 1.0
                g.query("CREATE (:Incident {id:'near', embedding: vecf32($a)}), (:Incident {id:'far', embedding: vecf32($b)})",
                        {"a": v_near, "b": v_far})
                q = base.copy()
                q[0] = 1.0
                rows = g.ro_query(
                    "CALL db.idx.vector.queryNodes('Incident', 'embedding', 2, vecf32($q)) YIELD node, score RETURN node.id, score",
                    {"q": q},
                ).result_set
                bare = ""
                try:
                    g.ro_query("CALL db.idx.vector.queryNodes('Incident', 'embedding', 2, $q) YIELD node RETURN count(node)", {"q": q})
                    bare = "bare list accepted"
                except Exception as e:
                    bare = f"bare list rejected ({_short(e, 50)})"
                try:
                    g.query("CREATE VECTOR INDEX FOR (r:Runbook) ON (r.embedding)")
                    noopt = "index without OPTIONS accepted"
                except Exception as e:
                    noopt = f"OPTIONS required ({_short(e, 50)})"
            finally:
                g.delete()
            order = [r[0] for r in rows]
            scores = {r[0]: r[1] for r in rows}
            direction = "distance (lower = closer)" if scores.get("near", 0) < scores.get("far", 0) else "similarity (higher = closer)"
            ok = bool(rows) and order[0] == "near"
            return ok, f"results={rows}; score is {direction}; {bare}; {noopt}", "CREATE VECTOR INDEX … OPTIONS {dimension:384, similarityFunction:'cosine'}; db.idx.vector.queryNodes('L','p',k,vecf32($q)) YIELD node, score"

        self.probe("16", "Vector index (384, cosine) + vecf32 + queryNodes", True, run)

    def p_copy(self):
        def run():
            src = f"smoke_{uuid.uuid4().hex[:8]}"
            dst = src + "_copy"
            g = self.db.select_graph(src)
            notes = []
            try:
                g.query("CREATE INDEX FOR (n:N) ON (n.id)")
                g.query("CREATE FULLTEXT INDEX FOR (s:Service) ON (s.name)")
                g.query("CREATE VECTOR INDEX FOR (i:Incident) ON (i.embedding) OPTIONS {dimension:4, similarityFunction:'cosine'}")
                g.query("CREATE (:N {id:'a'}), (:Service {id:'s', name:'payment'}), (:Incident {id:'i', embedding: vecf32([1,0,0,0])})")
                c = g.copy(dst)
                notes.append("client Graph.copy ok")
                n = c.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
                idx = c.ro_query("CALL db.indexes() YIELD label, properties, types RETURN label, properties, types").result_set
                notes.append(f"copied nodes={n}; indexes={idx}")
                ft = c.ro_query("CALL db.idx.fulltext.queryNodes('Service', 'pay*') YIELD node RETURN count(node)").result_set[0][0]
                vec = c.ro_query("CALL db.idx.vector.queryNodes('Incident','embedding',1,vecf32([1,0,0,0])) YIELD node RETURN count(node)").result_set[0][0]
                notes.append(f"fulltext works on copy={ft == 1}; vector works on copy={vec == 1}")
                try:
                    self.conn.execute_command("GRAPH.COPY", src, dst)
                    notes.append("copy onto existing dest ACCEPTED (unexpected)")
                    dest_guard = False
                except Exception as e:
                    notes.append(f"copy onto existing dest rejected ({_short(e, 50)})")
                    dest_guard = True
                ok = n == 3 and dest_guard and ft == 1 and vec == 1
            finally:
                for name in (src, dst):
                    try:
                        self.db.select_graph(name).delete()
                    except Exception:
                        pass
            return ok, "; ".join(notes), "Graph.copy(dest) / GRAPH.COPY src dest"

        self.probe("17", "GRAPH.COPY (dest must not exist; indexes carried?)", True, run)

    def p_constraint(self):
        def run():
            name = f"smoke_{uuid.uuid4().hex[:8]}"
            g = self.db.select_graph(name)
            notes = []
            try:
                g.query("CREATE INDEX FOR (i:Intent) ON (i.idem)")
                reply = self.conn.execute_command("GRAPH.CONSTRAINT", "CREATE", name, "UNIQUE", "NODE", "Intent", "PROPERTIES", 1, "idem")
                notes.append(f"create → {reply}")
                status = None
                for _ in range(40):
                    rows = g.ro_query("CALL db.constraints() YIELD type, label, properties, status RETURN type, label, status").result_set
                    status = rows[0][2] if rows else None
                    if status in ("OPERATIONAL", "FAILED"):
                        break
                    time.sleep(0.1)
                notes.append(f"status={status}")
                g.query("CREATE (:Intent {idem:'k1'})")
                try:
                    g.query("CREATE (:Intent {idem:'k1'})")
                    notes.append("duplicate CREATE accepted")
                    dup_rejected = False
                except Exception as e:
                    notes.append(f"duplicate CREATE rejected ({_short(e, 50)})")
                    dup_rejected = True
                # MERGE race: 16 threads MERGE the same idem
                barrier = threading.Barrier(16)
                errs: list[str] = []

                def worker():
                    gg = self.db.select_graph(name)
                    barrier.wait()
                    try:
                        gg.query("MERGE (i:Intent {idem:'race'}) ON CREATE SET i.state='PENDING'")
                    except Exception as e:  # noqa: BLE001
                        errs.append(type(e).__name__)

                ts = [threading.Thread(target=worker) for _ in range(16)]
                [t.start() for t in ts]
                [t.join() for t in ts]
                cnt = g.ro_query("MATCH (i:Intent {idem:'race'}) RETURN count(i)").result_set[0][0]
                notes.append(f"16× MERGE race → {cnt} node(s), {len(errs)} errors")
                ok = status == "OPERATIONAL" and dup_rejected and cnt == 1
            finally:
                g.delete()
            return ok, "; ".join(notes), "GRAPH.CONSTRAINT CREATE g UNIQUE NODE Intent PROPERTIES 1 idem (async → poll db.constraints())"

        self.probe("18", "Unique constraint on Intent.idem (+ MERGE race)", False, run)

    def p_cypher_features(self):
        def run():
            checks = {
                "pattern predicate in WHERE": "MATCH (a:N {id:'a'}) WHERE NOT (a)<-[:R]-(:N) RETURN a.id",
                "pow()": "RETURN pow(0.5, 2)",
                "^ operator": "RETURN 0.5 ^ 2",
                "last(nodes(p)), relationships(p), id(r), startNode(r)": (
                    "MATCH p=(a:N {id:'a'})-[r:R]->(b) RETURN last(nodes(p)).id, size(relationships(p)), id(r) >= 0, startNode(r).id"
                ),
                "reduce()": "MATCH p=(a:N {id:'a'})-[:R*1..2]->(c) RETURN reduce(t = 0, r IN relationships(p) | t + r.cap) ORDER BY 1 LIMIT 1",
                "FOREACH write": "MATCH (a:N {id:'a'}) FOREACH (x IN [1] | SET a.touched = true) RETURN a.touched",
                "UNWIND of empty list + RETURN": "UNWIND [] AS x RETURN count(x)",
                "EXISTS subquery": "MATCH (a:N {id:'a'}) WHERE EXISTS { MATCH (a)-[:R]->(:N) } RETURN a.id",
                # obligation clock (Q-OBL-CUST): nearest failure path, bounded, zero-length when the node is the source
                "shortestPath() in WITH (bounded *0..8)": (
                    "MATCH (a:N {id:'a'}) UNWIND ['a', 'c'] AS t MATCH (b:N {id:t}) "
                    "WITH b, shortestPath((a)-[:R*0..8]->(b)) AS p RETURN collect([b.id, [x IN nodes(p) | x.id]])"
                ),
                # obligation clock: algo.BFS yields NO row when nothing is reachable (c is a sink); an aggregating
                # CALL { } subquery keeps the source row so the failing component's own SLO/customers still count
                "CALL {} subquery keeps the row when algo.BFS yields none": (
                    "MATCH (s:N {id:'c'}) CALL { WITH s CALL algo.BFS(s, 8, 'R') YIELD nodes UNWIND nodes AS x "
                    "RETURN collect(x) AS r } RETURN s.id, size(r)"
                ),
            }
            res, fails = [], []
            with self.graph([["a", "b", 2], ["b", "c", 3]]) as g:
                for label, q in checks.items():
                    try:
                        fn = g.query if "FOREACH" in label else g.ro_query
                        out = fn(q).result_set
                        res.append(f"{label}: {out[0] if out else []}")
                    except Exception as e:
                        fails.append(label)
                        res.append(f"{label}: ERROR {_short(e, 50)}")
            essential = {"pattern predicate in WHERE", "last(nodes(p)), relationships(p), id(r), startNode(r)", "reduce()", "FOREACH write",
                         "shortestPath() in WITH (bounded *0..8)", "CALL {} subquery keeps the row when algo.BFS yields none"}
            return not (essential & set(fails)), " | ".join(res), ""

        self.probe("19", "Cypher features (pattern predicates, pow/^, path fns, reduce, FOREACH, EXISTS, shortestPath, CALL {} subquery)", False, run)

    def p_explain_profile(self):
        def run():
            with self.graph([["a", "b", 1]]) as g:
                ex = g.explain("MATCH (n:N) RETURN n LIMIT 5")
                pr = g.profile("MATCH (n:N) RETURN n LIMIT 5")
            return True, f"explain → {type(ex).__name__}: {str(ex)[:90]!r}; profile → {str(pr)[:120]!r}", "Graph.explain(q) / Graph.profile(q)"

        self.probe("20", "GRAPH.EXPLAIN / GRAPH.PROFILE via client", False, run)

    def p_config(self):
        def run():
            out = []
            ok = True
            keys = (("TIMEOUT_MAX", 5000), ("TIMEOUT_DEFAULT", 2000), ("RESULTSET_SIZE", 1000), ("MAX_QUEUED_QUERIES", 50))
            before = {}
            try:
                for k, _ in keys:  # the probe runs on the shared engine: remember what it found and put it back
                    before[k] = self.conn.execute_command("GRAPH.CONFIG", "GET", k)[1]
                for k, v in keys:
                    try:
                        self.conn.execute_command("GRAPH.CONFIG", "SET", k, v)
                        got = self.conn.execute_command("GRAPH.CONFIG", "GET", k)
                        out.append(f"{k}={got}")
                    except Exception as e:
                        ok = False
                        out.append(f"{k}: {_short(e, 60)}")
            finally:
                for k, v in before.items():
                    self.conn.execute_command("GRAPH.CONFIG", "SET", k, v)
            return ok, "; ".join(out) + " (restored afterwards)", "GRAPH.CONFIG SET <key> <value>"

        self.probe("21", "Runtime GRAPH.CONFIG (TIMEOUT_MAX/DEFAULT, RESULTSET_SIZE, MAX_QUEUED_QUERIES)", True, run)

    def p_acl(self):
        def run():
            user, pw = f"ro_smoke{uuid.uuid4().hex[:4]}", uuid.uuid4().hex
            allowed, other = f"tenant_smk{uuid.uuid4().hex[:4]}", f"tenant_oth{uuid.uuid4().hex[:4]}"
            notes = []
            for gname in (allowed, other):
                self.db.select_graph(gname).query("CREATE (:N {id:'x'})")
            try:
                self.conn.execute_command(
                    "ACL", "SETUSER", user, "on", f">{pw}", "resetkeys", "resetchannels", "-@all",
                    "+GRAPH.RO_QUERY", "+GRAPH.EXPLAIN", "+PING", "+HELLO", "+CLIENT|SETNAME", f"~{allowed}", "~scratch_smk_*", "~whatif_smk_*", "~eval_smk_*",
                )
                import redis
                from falkordb import Graph

                kw = self.conn.connection_pool.connection_kwargs
                rconn = redis.Redis(host=kw.get("host", "localhost"), port=kw.get("port"), username=user, password=pw)
                gr = Graph(rconn, allowed)
                r = gr.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
                notes.append(f"RO on own tenant → {r}")
                read_ok = r == 1
                try:
                    gr.query("CREATE (:Z)")
                    notes.append("GRAPH.QUERY on own tenant ALLOWED")
                    write_denied = False
                except Exception as e:
                    notes.append(f"GRAPH.QUERY denied ({_short(e, 40)})")
                    write_denied = True
                try:
                    Graph(rconn, other).ro_query("MATCH (n) RETURN count(n)")
                    notes.append("other tenant key ALLOWED")
                    other_denied = False
                except Exception as e:
                    notes.append(f"other tenant denied ({_short(e, 40)})")
                    other_denied = True
                try:
                    rconn.execute_command("GRAPH.LIST")
                    notes.append("GRAPH.LIST allowed")
                except Exception as e:
                    notes.append(f"GRAPH.LIST denied ({_short(e, 30)})")
                ok = read_ok and write_denied and other_denied
            finally:
                try:
                    self.conn.execute_command("ACL", "DELUSER", user)
                except Exception:
                    pass
                for gname in (allowed, other):
                    try:
                        self.db.select_graph(gname).delete()
                    except Exception:
                        pass
            return ok, "; ".join(notes), "ACL SETUSER ro_<t> on >pw resetkeys -@all +GRAPH.RO_QUERY +GRAPH.EXPLAIN +PING +HELLO ~tenant_<t> ~scratch_<t>_*  (connect with falkordb.Graph(redis.Redis(...)); FalkorDB() needs INFO)"

        self.probe("22", "ACL read-only tenant user (RO allowed; QUERY and other tenant denied)", True, run)

    def p_concurrency(self):
        def run():
            name = f"smoke_{uuid.uuid4().hex[:8]}"
            g = self.db.select_graph(name)
            try:
                g.query("CREATE (:Agent {id:'w0'})")
                g.query("UNWIND range(1, 16) AS i CREATE (:Agent {id:'w' + toString(i)})")
                rounds, winners_ok, lat = 10, 0, []
                stop = threading.Event()

                def reader():
                    rg = self.db.select_graph(name)
                    while not stop.is_set():
                        t0 = time.perf_counter()
                        rg.ro_query("MATCH (t:Task) RETURN count(t)")
                        lat.append((time.perf_counter() - t0) * 1000)

                rt = threading.Thread(target=reader)
                rt.start()
                for rnd in range(rounds):
                    barrier = threading.Barrier(16)
                    owners: list[Any] = []

                    def claim(agent: str, task: str = f"task-{rnd}"):
                        gg = self.db.select_graph(name)
                        barrier.wait()
                        res = gg.query(
                            "MERGE (t:Task {id:$task}) ON CREATE SET t.state='open' "
                            "WITH t WHERE t.state = 'open' SET t.state='claimed', t.owner=$agent "
                            "WITH t MATCH (a:Agent {id:$agent}) MERGE (t)-[:CLAIMED_BY]->(a) RETURN t.owner",
                            {"task": task, "agent": agent},
                        ).result_set
                        if res:
                            owners.append(res[0][0])

                    ts = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(1, 17)]
                    [t.start() for t in ts]
                    [t.join() for t in ts]
                    final = g.ro_query("MATCH (t:Task {id:$t})-[:CLAIMED_BY]->(a) RETURN count(a)", {"t": f"task-{rnd}"}).result_set[0][0]
                    if len(owners) == 1 and final == 1:
                        winners_ok += 1
                stop.set()
                rt.join()
            finally:
                g.delete()
            p50 = statistics.median(lat) if lat else -1
            p95 = sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else -1
            return winners_ok == rounds, f"{winners_ok}/{rounds} rounds with exactly 1 owner; RO read p50={p50:.2f} ms p95={p95:.2f} ms over {len(lat)} reads", "W-CLAIM-1 conditional claim"

        self.probe("23", "Concurrency: 16 claimers × 10 rounds → 1 owner; RO reads during writes", True, run)

    def p_schema_introspection(self):
        def run():
            with self.graph([["a", "b", 1], ["b", "c", 2]]) as g:
                g.query("CREATE INDEX FOR (n:Empty) ON (n.id)")  # registers a label that has no nodes
                g.query("MATCH (a:N {id:'a'}) CREATE (a)-[:S]->(:M {id:'m', extra:1})")

                def ro(q: str) -> list:
                    return g.ro_query(q, timeout=2000).result_set

                labels = sorted(r[0] for r in ro("CALL db.labels() YIELD label RETURN label"))
                rels = sorted(r[0] for r in ro("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"))
                keys = sorted(r[0] for r in ro("CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey"))
                st = ro("CALL db.meta.stats() YIELD labels, relTypes, nodeCount, relCount RETURN labels, relTypes, nodeCount, relCount")[0]
                idx = ro("CALL db.indexes() YIELD label, properties, types RETURN label, properties, types ORDER BY label")
                procs = {r[0]: r[1] for r in ro("CALL dbms.procedures() YIELD name, mode RETURN name, mode")}
                scan_l = {r[0]: r[1] for r in ro("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*)")}
                scan_r = {r[0]: r[1] for r in ro("MATCH ()-[r]->() RETURN type(r), count(*)")}
            lab, rt = dict(st[0]), dict(st[1])
            exact = ({k: v for k, v in lab.items() if v} == scan_l and {k: v for k, v in rt.items() if v} == scan_r
                     and st[2] == sum(scan_l.get(x, 0) for x in ("N", "M")) and st[3] == sum(scan_r.values()))
            modes = {n: procs.get(n) for n in ("db.labels", "db.relationshipTypes", "db.propertyKeys", "db.meta.stats", "db.indexes")}
            ok = (labels == ["Empty", "M", "N"] and rels == ["R", "S"] and {"id", "cap", "w", "extra"} <= set(keys)
                  and lab.get("Empty") == 0 and exact and any(r[0] == "Empty" for r in idx)
                  and all(m == "READ" for m in modes.values()))
            return (ok, f"under RO_QUERY: db.labels={labels}; db.relationshipTypes={rels}; db.propertyKeys={keys}; "
                        f"db.meta.stats labels={lab} relTypes={rt} nodes={st[2]} edges={st[3]} (equals full scan: {exact}; "
                        f"index-only label listed with 0); db.indexes labels={[r[0] for r in idx]}; modes={modes}",
                    "CALL db.meta.stats() YIELD labels, relTypes, nodeCount, relCount, propertyKeyCount; "
                    "CALL db.indexes() YIELD label, properties, types, entitytype, status; db.labels() / "
                    "db.relationshipTypes() / db.propertyKeys() (no counts)")

        self.probe("24", "Schema introspection under RO_QUERY (db.labels/relationshipTypes/propertyKeys/meta.stats/indexes)", False, run)

    def run_all(self) -> list[Result]:
        for p in (self.p_names, self.p_bfs, self.p_sppaths, self.p_sspaths, self.p_pagerank, self.p_betweenness,
                  self.p_harmonic, self.p_wcc, self.p_cdlp, self.p_maxflow, self.p_msf, self.p_algo_under_ro,
                  self.p_ro_rejects_write, self.p_timeout, self.p_fulltext, self.p_vector, self.p_copy,
                  self.p_constraint, self.p_cypher_features, self.p_explain_profile, self.p_config, self.p_acl,
                  self.p_concurrency, self.p_schema_introspection):
            p()
        return self.results


def engine_module_version(conn) -> int | None:
    """The graph module version (e.g. 60002 for 6.0.2), robust to RESP2/RESP3 reply shapes."""
    for mod in conn.execute_command("MODULE", "LIST"):
        items = mod.items() if isinstance(mod, dict) else zip(mod[::2], mod[1::2])
        d = {(k.decode() if isinstance(k, bytes) else k): v for k, v in items}
        name = d.get("name")
        if (name.decode() if isinstance(name, bytes) else name) == "graph":
            return int(d.get("ver"))
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--tag", required=True, help="engine tag, e.g. 6.0.2")
    ap.add_argument("--digest", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    s = Smoke(a.host, a.port)
    module = s.conn.execute_command("MODULE", "LIST")
    module_ver = engine_module_version(s.conn)
    t0 = time.time()
    results = s.run_all()
    payload = {
        "tag": a.tag, "digest": a.digest, "module": str(module)[:300], "module_ver": module_ver,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - t0, 1),
        "results": results, "resolved": s.resolved,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(payload, indent=2, default=str))
    crit = [r for r in results if r["critical"]]
    failed_crit = [r for r in crit if not r["ok"]]
    print(f"{a.tag}: critical {sum(1 for r in crit if r['ok'])}/{len(crit)}, all ok {sum(1 for r in results if r['ok'])}/{len(results)}")
    for r in results:
        mark = "PASS" if r["ok"] else ("info" if r["ok"] is None else "FAIL")
        print(f"  [{mark}] {r['id']:>3} {r['item']}")
    return 1 if failed_crit else 0


if __name__ == "__main__":
    raise SystemExit(main())
