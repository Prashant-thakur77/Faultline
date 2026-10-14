"""S7 cross-tenant isolation: an agent bound to globex can never see acme.

Four independent layers, each tested on its own:
(a) tenant binding: graph tools bound to globex answer acme ids with no rows / not found;
(b) database ACL: the read-only user of globex gets NOPERM on tenant_acme;
(c) text2cypher guard: raw GRAPH.* commands and write/unknown procedure CALLs are rejected before any query runs;
(d) RO wrapper / client / binding: a globex reader cannot even be pointed at an acme graph;
(e) end to end: the company-brain answer on globex cites no acme id.
Needs `make up && make seed TENANT=all` (acme and globex)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import redis
from falkordb import Graph

from faultline.config import settings
from faultline.graph import client
from faultline.graph import guard as G
from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO
from faultline.ingest import baselines, cross_domain, docs, history, lineage_to_graph, org_gen, otel_topology
from faultline.ingest.clock import ANCHOR_MS, DAY_MS
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
NOW = ANCHOR_MS
SINCE = ANCHOR_MS - 30 * DAY_MS
# acme ids the probes ask about (each is checked to exist in tenant_acme and not in tenant_globex below)
ACME_SERVICE, ACME_SYMPTOM_TARGET, ACME_INCIDENT, ACME_DECISION = "payment", "checkout", "inc-h005", "ADR-012"
NOPERM = re.compile(r"(?i)noperm|no permissions|perm|access")


def _acme_ids() -> set[str]:
    ids: set[str] = set()
    for m in (lineage_to_graph, otel_topology, cross_domain, baselines, org_gen, history, docs):
        for rows in m.build().nodes.values():
            ids |= {r["id"] for r in rows}
    return ids


ACME_IDS = _acme_ids()


def _strings(v: Any, out: set[str]) -> set[str]:
    if isinstance(v, str):
        out.add(v)
    elif isinstance(v, dict):
        for x in v.values():
            _strings(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _strings(x, out)
    return out


def _ready(tenant: str) -> RO:
    r = RO(tenant)
    try:
        r.require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"{tenant} not seeded: {e}")
    return r


@pytest.fixture(scope="module")
def tenants(db):
    return _ready("acme"), _ready("globex")


def test_probe_ids_exist_in_acme_and_not_in_globex(tenants):
    acme, globex = tenants
    assert acme.run("Q-FIND-ID", {"id": ACME_SERVICE, "norm": ACME_SERVICE}).rows[0]["id"] == ACME_SERVICE
    assert acme.run("Q-INC-1", {"inc": ACME_INCIDENT}).rows[0]["id"] == ACME_INCIDENT
    assert acme.run("Q-DEC-2", {"id": ACME_DECISION}).rows[0]["id"] == ACME_DECISION
    assert globex.run("Q-FIND-ID", {"id": ACME_SERVICE, "norm": ACME_SERVICE}).rows == []
    assert globex.run("Q-INC-1", {"inc": ACME_INCIDENT}).rows == []
    assert globex.run("Q-DEC-2", {"id": ACME_DECISION}).rows == []
    assert {ACME_SERVICE, ACME_INCIDENT, ACME_DECISION} <= ACME_IDS


# ------------------------------------------------------------------ (a) tool binding
PROBES: list[tuple[str, dict]] = [
    ("resolve_entity", {"text": ACME_SERVICE}),
    ("service_context", {"id": ACME_SERVICE, "now": NOW}),
    ("blast_radius", {"id": ACME_SERVICE}),
    ("causal_paths", {"from_id": ACME_SERVICE, "to_id": ACME_SYMPTOM_TARGET}),
    ("impact_bound", {"suspect_ids": [ACME_SERVICE], "symptom_id": ACME_SYMPTOM_TARGET, "observed_share": 0.5}),
    ("upstream_scope", {"symptom_id": ACME_SYMPTOM_TARGET}),
    ("owners_of", {"target_id": ACME_SERVICE, "now": NOW, "since": SINCE}),
    ("bus_factor", {"target_id": ACME_SERVICE}),
    ("people_who_worked_on", {"target_id": ACME_SERVICE}),
    ("decisions_about", {"target_id": ACME_SERVICE}),
    ("trace_decision", {"decision_id": ACME_DECISION}),
    ("similar_incidents", {"incident_id": ACME_INCIDENT, "now": NOW}),
    ("runbook_for", {"ids": [ACME_SERVICE, f"sym-error_rate-{ACME_SYMPTOM_TARGET}"]}),
]


@pytest.fixture
def on_globex(tenants):
    tok = context.bind("globex", record=False)
    yield
    context.unbind(tok)


@pytest.mark.parametrize("tool,args", PROBES, ids=[p[0] for p in PROBES])
def test_globex_tools_find_nothing_for_acme_ids(on_globex, tool, args):
    out = T.TOOLS[tool](**args)
    assert "error" not in out, out.get("error")
    assert out["rows"] == [], f"{tool} returned rows for an acme id on globex: {out['rows'][:3]}"
    assert out["served_by"].endswith(("as ro_globex", "as default-user")) and "tenant_globex" in out["served_by"]


def test_globex_families_and_search_never_surface_acme(on_globex):
    fam = T.TOOLS["incident_families"](incident_id=ACME_INCIDENT)
    assert "error" not in fam and fam["rows"], "globex has its own families"
    assert not any(r["mine"] for r in fam["rows"])
    for tool, args in (("incident_families", {"incident_id": ACME_INCIDENT}), ("find_entities", {"text": ACME_SERVICE}),
                       ("find_entities", {"text": ACME_DECISION}), ("chokepoints", {}), ("missing_guardrails", {}),
                       ("connectivity_check", {})):
        out = T.TOOLS[tool](**args)
        assert "error" not in out, (tool, out.get("error"))
        leaked = _strings(out["rows"], set()) & ACME_IDS
        assert not leaked, f"{tool} leaked acme ids: {sorted(leaked)[:10]}"


def test_who_fixes_for_an_acme_id_is_not_found(on_globex):
    out = T.TOOLS["who_fixes"](target_id=ACME_SERVICE, now=NOW, since=SINCE)
    assert "not found" in out.get("error", "")
    assert not (_strings(out.get("rows", []), set()) & ACME_IDS)


# ------------------------------------------------------------------ (b) database ACL
def test_configured_ro_globex_user_gets_noperm_on_tenant_acme(tenants):
    if not client.ro_acl_enabled():
        pytest.skip("ACL not configured here: FALKORDB_RO_PASSWORD is unset, so RO connections use the default user "
                    "(the shipped template rule is still checked by test_template_ro_globex_rule_denies_tenant_acme)")
    raw = Graph(client._ro_redis("globex", fresh=True), "tenant_acme")
    try:
        with pytest.raises(Exception, match=NOPERM):
            raw.ro_query("MATCH (n) RETURN count(n)")
    finally:
        raw.client.close()
    assert RO("globex").require_ready()["ready"] is True


def _template_rules() -> list[str]:
    line = next(ln for ln in (ROOT / "deploy" / "users.acl.template").read_text().splitlines()
                if ln.startswith("user ro_globex "))
    return line.split()[2:]  # drop "user ro_globex"


def test_template_ro_globex_rule_denies_tenant_acme(db, tenants):
    """The exact ro_globex rule shipped in deploy/users.acl.template, applied to a throwaway user (never touches a
    configured user): own tenant readable; tenant_acme and writes refused by the database."""
    user, pw = f"s7_ro_globex_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    rules = [f">{pw}" if r.startswith(">") else r for r in _template_rules()]
    assert "~tenant_globex" in rules and not any("acme" in r for r in rules)
    admin = db.connection
    try:
        admin.execute_command("ACL", "SETUSER", user, "reset", *rules)
    except redis.ResponseError as e:
        pytest.skip(f"cannot provision a throwaway ACL user here: {e}")
    conn = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port, username=user, password=pw,
                       single_connection_client=True, socket_timeout=10)
    try:
        assert Graph(conn, "tenant_globex").ro_query("MATCH (m:Meta) RETURN m.ready").result_set[0][0] is True
        with pytest.raises(Exception, match=NOPERM):
            Graph(conn, "tenant_acme").ro_query("MATCH (n) RETURN count(n)")
        with pytest.raises(Exception, match=NOPERM):
            Graph(conn, "golden_acme").ro_query("MATCH (n) RETURN count(n)")
        with pytest.raises(Exception, match=NOPERM):
            Graph(conn, "tenant_globex").query("CREATE (:Probe {id:'s7'})")
    finally:
        conn.close()
        admin.execute_command("ACL", "DELUSER", user)


# ------------------------------------------------------------------ (c) text2cypher guard
@pytest.mark.parametrize("query", [
    "GRAPH.QUERY tenant_acme 'MATCH (n) RETURN n'",
    "GRAPH.RO_QUERY tenant_acme 'MATCH (n) RETURN n'",
    "MATCH (n) RETURN n LIMIT 5; GRAPH.QUERY tenant_acme 'MATCH (n) DETACH DELETE n'",
    "CALL db.idx.fulltext.createNodeIndex('Service', 'name')",
    "CALL dbms.procedures() YIELD name RETURN name",
    "CALL algo.notARealProcedure() YIELD node RETURN node",
    "CALL db.idx.fulltext.drop('Service')",
    "MATCH (n:Service {id:'payment'}) SET n.tenant = 'globex' RETURN n",
])
def test_guard_rejects_cross_tenant_and_write_attempts(tenants, query):
    with pytest.raises(G.GuardError):
        G.guard(query)
    with pytest.raises(G.GuardError):
        RO("globex").run_guarded(query)


def test_text2cypher_tool_refuses_graph_command(on_globex):
    out = T.TOOLS["run_cypher_readonly"](query="GRAPH.QUERY tenant_acme 'MATCH (n) RETURN n'", failed_template="Q-FIND-ID",
                                        reason="probe a raw graph command against another tenant")
    assert "error" in out and "guard rejected" in out["error"]


def test_guarded_read_on_globex_sees_only_globex(on_globex):
    r = RO("globex").run_guarded("MATCH (n:Service) WHERE n.id IN ['payment', 'checkout', 'card-gateway'] RETURN n.id AS id")
    assert [row["id"] for row in r.rows] == ["card-gateway"]


# ------------------------------------------------------------------ (d) wrapper, client and binding
@pytest.mark.parametrize("graph", ["tenant_acme", "golden_acme", "audit_acme", "scratch_acme_x", "whatif_acme_y", "eval_acme_r_a_s_1"])
def test_globex_reader_cannot_target_acme_graphs(graph):
    with pytest.raises(ValueError):
        RO("globex", graph)
    with pytest.raises(ValueError):
        client.ro_graph("globex", graph)
    with pytest.raises(ValueError):
        context.bind("globex", graph=graph)


# ------------------------------------------------------------------ (e) company brain end to end
def test_brain_answer_on_globex_cites_no_acme_ids(tenants):
    from faultline.brain.ask import ask

    a = ask("What breaks if payment goes down?", "globex")
    cited = set(a.citations) | set(re.findall(r"\[([A-Za-z0-9][A-Za-z0-9_.:/-]{0,159})\]", a.answer))
    assert not cited & ACME_IDS, f"acme ids cited on globex: {sorted(cited & ACME_IDS)}"
    assert a.guard.get("ok", True)
    for step in a.steps:
        assert not step.get("error"), step
        addressed = {v for k, v in (step.get("args") or {}).items() if k in ("id", "target_id", "decision_id")}
        assert not addressed & ACME_IDS, f"{step['tool']} was pointed at an acme id: {addressed}"
