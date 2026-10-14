"""org_gen: deterministic synthetic org (no FalkorDB)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import yaml

from faultline.graph.schema_model import NODE_LABELS, REL_TYPES
from faultline.ingest import org_gen
from faultline.ingest.clock import ROTA_END_MS, ROTA_START_MS, WEEK_MS


def _canon(b) -> str:
    return json.dumps({"n": {k: v for k, v in sorted(b.nodes.items())},
                       "e": {"|".join(k): v for k, v in sorted(b.edges.items())}}, sort_keys=True)


def _rows(b, rel):
    return [r for (t, _, _), rows in b.edges.items() if t == rel for r in rows]


B = org_gen.build()
PEOPLE = {p["id"]: p for p in B.nodes["Person"]}


def test_deterministic():
    assert _canon(org_gen.build()) == _canon(org_gen.build(42)) == _canon(B)
    assert _canon(org_gen.build(7)) != _canon(B)


def test_whitelisted_and_tenant_scoped():
    assert set(B.nodes) <= NODE_LABELS
    for rel, src, dst in B.edges:
        assert rel in REL_TYPES and src in NODE_LABELS and dst in NODE_LABELS
    for rows in B.nodes.values():
        for r in rows:
            assert r["tenant"] == "acme" and isinstance(r["id"], str)


def test_people_and_teams():
    assert len(PEOPLE) == 40 and sorted(PEOPLE) == [f"p-{i:03d}" for i in range(1, 41)]
    assert len({p["name"] for p in PEOPLE.values()}) == 40
    assert [t["id"] for t in B.nodes["Team"]] == [f"team-{k}" for k in (
        "payments", "checkout", "catalog", "storefront", "platform", "data", "growth", "assistant")]
    assert all(t["name"] for t in B.nodes["Team"])


def test_exactly_four_inactive_with_valid_to():
    inactive = [p for p in PEOPLE.values() if not p["active"]]
    assert len(inactive) == 4
    assert all(isinstance(p.get("valid_to"), int) for p in inactive)
    assert all("valid_to" not in p for p in PEOPLE.values() if p["active"])
    member_to = {r["src"]: r["props"].get("to") for r in _rows(B, "MEMBER_OF")}
    assert all(member_to[p["id"]] == p["valid_to"] for p in inactive)


def test_every_component_has_exactly_one_current_owner():
    topo = yaml.safe_load(org_gen.TOPOLOGY_PATH.read_text())
    comps = [s["id"] for s in topo["services"]] + [d["id"] for d in topo["datastores"]]
    transforms, kpis = org_gen.data_components()
    owns = Counter(r["dst"] for r in _rows(B, "OWNS"))
    for c in comps + transforms + kpis:
        assert owns[c] == 1, c
    assert set(owns) == set(comps + transforms + kpis)
    # OWNS points at the right label
    labels = {(dst, r["dst"]) for (rel, _, dst), rows in B.edges.items() if rel == "OWNS" for r in rows}
    assert ("Service", "payment") in labels and ("Datastore", "astronomy-db") in labels
    assert ("Transform", "fct_revenue.sql") in labels and ("KPI", "kpi.exec_revenue") in labels


def test_ownership_history_contiguous_and_ends_at_current_owner():
    current = {r["dst"]: r["src"] for r in _rows(B, "OWNS")}
    periods = defaultdict(list)
    for r in _rows(B, "OWNED_AT"):
        periods[r["dst"]].append((r["props"]["from"], r["props"].get("to"), r["src"], r["props"]["key"]))
    changed = [c for c, ps in periods.items() if len(ps) > 1]
    assert len(changed) >= 2
    for c, ps in periods.items():
        ps.sort()
        assert ps[-1][1] is None and ps[-1][2] == current[c]  # open period = current owner
        assert all(p[1] is not None for p in ps[:-1])
        for a, b in zip(ps, ps[1:]):
            assert a[1] == b[0]  # contiguous
        assert len({p[3] for p in ps}) == len(ps)  # key distinct per period


def test_rota_contiguous_non_overlapping_and_only_present_members():
    member_of = {r["src"]: r["dst"] for r in _rows(B, "MEMBER_OF")}
    by_team = defaultdict(list)
    for r in _rows(B, "ON_CALL"):
        p = r["props"]
        by_team[r["dst"]].append((p["from"], p["to"], r["src"], p["key"]))
    assert len(by_team) == 8
    for team, periods in by_team.items():
        periods.sort()
        assert periods[0][0] == ROTA_START_MS and periods[-1][1] == ROTA_END_MS
        for a, b in zip(periods, periods[1:]):
            assert a[1] == b[0], team
        for frm, to, pid, _ in periods:
            assert 0 < to - frm <= WEEK_MS
            assert member_of[pid] == team
            vt = PEOPLE[pid].get("valid_to")
            assert vt is None or vt >= to, (pid, team)
        assert len({p[3] for p in periods}) == len(periods)
        assert len({p[2] for p in periods}) >= 3  # it actually rotates


def test_reports_to_is_a_tree_rooted_at_one_vp():
    mgr = {}
    for r in _rows(B, "REPORTS_TO"):
        assert r["src"] not in mgr
        mgr[r["src"]] = r["dst"]
    roots = [p for p in PEOPLE if p not in mgr]
    assert len(roots) == 1 and PEOPLE[roots[0]]["role"] == "vp"
    for p in PEOPLE:
        seen, cur = set(), p
        while cur in mgr:
            assert cur not in seen
            seen.add(cur)
            cur = mgr[cur]
        assert cur == roots[0]
    for p, m in mgr.items():
        role, mrole = PEOPLE[p]["role"], PEOPLE[m]["role"]
        assert (role, mrole) in {("engineer", "lead"), ("lead", "director"), ("director", "vp")}
    assert sum(1 for p in PEOPLE.values() if p["role"] == "director") == 2


def test_collaborates_symmetric_and_weighted():
    w = {(r["src"], r["dst"]): r["props"]["w"] for r in _rows(B, "COLLABORATES")}
    assert w
    for (a, b), x in w.items():
        assert a != b and w[(b, a)] == x and 0 < x <= 1
