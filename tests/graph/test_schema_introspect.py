"""Schema introspection without a database: the template lint allowlist for the schema procedures, the static
relationship-type scan of templates, the drift rules, the MCP resources/prompts content and the phase placement."""

import re

import pytest

from faultline.agent import phases
from faultline.graph import schema_model as M
from faultline.graph.schema_introspect import drift, lifecycle, rels_in, template_rel_usage
from faultline.graph.templates import TemplateLintError, catalogue, lint
from faultline.mcp_server import resources as R
from faultline.mcp_server import tools as T


# ------------------------------------------------------------------ templates and lint
def test_schema_templates_load_and_are_bounded():
    cat = catalogue()
    for tid in ("Q-SCHEMA-1", "Q-SCHEMA-2", "Q-SCHEMA-3", "Q-SCHEMA-4"):
        assert tid in cat and cat[tid].limit <= 100
    assert "db.meta.stats()" in cat["Q-SCHEMA-1"].display
    assert "LIMIT 100000" in cat["Q-SCHEMA-2"].display  # bounded edge scan
    assert "LIMIT 20000" in cat["Q-SCHEMA-3"].display   # bounded node scan


def test_call_allowlist_admits_only_the_read_schema_procedures():
    lint("T", "CALL db.meta.stats() YIELD nodeCount RETURN nodeCount LIMIT 1", "single-row", ())
    lint("T", "CALL db.indexes() YIELD label RETURN label ORDER BY label LIMIT 5", "rows", ())
    for bad in ("CALL db.idx.fulltext.createNodeIndex('L', 'p') YIELD x RETURN x ORDER BY x LIMIT 1",
                "CALL db.idx.fulltext.drop('L') YIELD x RETURN x ORDER BY x LIMIT 1",
                "CALL dbms.procedures() YIELD name RETURN name ORDER BY name LIMIT 5"):
        with pytest.raises(TemplateLintError):
            lint("T", bad, "rows", ())


# ------------------------------------------------------------------ which templates read which relationship types
def test_rels_in_reads_patterns_algo_configs_and_type_tests():
    q = ("MATCH (a)-[r:PROPAGATES_TO|DEPENDS_ON*1..3]->(b)<-[:CHANGED|:GATES]-(d) "
         "WHERE a.name CONTAINS 'x' AND type(r) = 'OWNS' AND a.note = '[:FAKE_REL]' "
         "CALL algo.WCC({relationshipTypes: ['CALLS']}) YIELD node RETURN node")
    assert rels_in(q) == {"PROPAGATES_TO", "DEPENDS_ON", "CHANGED", "GATES", "OWNS", "CALLS"}
    assert rels_in("RETURN [x IN labels(n) WHERE x <> 'Node'][0] AS l, {src: 1} AS m") == set()


def test_template_usage_matches_known_templates():
    use = template_rel_usage()
    assert "Q-GATE-1" in use["PROPAGATES_TO"] and "Q-GATE-1" in use["CHANGED"]
    assert "Q-ORG-HARM" in use["KNOWS_ABOUT"]
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", r) for r in use)


# ------------------------------------------------------------------ drift rules
def _schema(labels: dict[str, int], rels: dict[str, int]) -> dict:
    return {"labels": [{"label": k, "n": v, "sampled": v, "keys": [], "indexes": []} for k, v in labels.items()],
            "relationships": [{"type": k, "n": v, "pairs": []} for k, v in rels.items()]}


def _seeded_rels() -> dict[str, int]:
    return {r: 1 for r in M.REL_TYPES - M.RUNTIME_RELS - M.RESERVED_RELS}


def test_schema_model_drift_sets_are_consistent():
    assert M.RUNTIME_RELS <= M.REL_TYPES and M.RESERVED_RELS <= M.REL_TYPES
    assert not M.RUNTIME_RELS & M.RESERVED_RELS
    assert M.BASE_LABEL not in M.NODE_LABELS
    assert lifecycle("KNOWS_ABOUT") == "scratch" and lifecycle("HAS_ALERT") == "reserved"
    assert lifecycle("CONSUMES") == "seed" and lifecycle("FOR") == "seed"  # obligations (M12): seeded, no longer reserved
    assert lifecycle("HAS_TOOL_CALL") == "runtime" and lifecycle("PROPAGATES_TO") == "seed"
    assert lifecycle("NOPE") == "UNDECLARED"


def test_drift_passes_on_a_declared_graph_and_reports_write_only():
    rep = drift({"tenant_a": _schema({"Service": 3, "Agent": 0}, _seeded_rels())})
    assert rep["ok"], rep["failures"]
    unread = M.REL_TYPES - set(template_rel_usage())
    assert set(rep["write_only"]) == unread & set(_seeded_rels())
    assert "Agent" in rep["labels_absent"] and set(rep["reserved_absent"]) == set(M.RESERVED_RELS)


def test_drift_fails_loudly_on_undeclared_label_or_type_even_with_zero_count():
    rep = drift({"tenant_a": _schema({"Service": 3, "Ghost": 0}, {**_seeded_rels(), "HAUNTS": 0})})
    assert not rep["ok"]
    assert any("Ghost" in f for f in rep["failures"]) and any("HAUNTS" in f for f in rep["failures"])
    assert rep["graphs"]["tenant_a"] == {"undeclared_labels": ["Ghost"], "undeclared_rels": ["HAUNTS"]}


def test_drift_fails_on_a_declared_seed_type_absent_everywhere():
    rels = _seeded_rels()
    rels.pop("PROPAGATES_TO")
    rep = drift({"tenant_a": _schema({"Service": 1}, rels), "tenant_b": _schema({"Service": 1}, {"OWNS": 1})})
    assert not rep["ok"] and any("PROPAGATES_TO" in f for f in rep["failures"])
    # present in ANY checked graph is enough
    rep = drift({"tenant_a": _schema({"Service": 1}, rels), "tenant_b": _schema({"Service": 1}, {"PROPAGATES_TO": 2})})
    assert rep["ok"], rep["failures"]


def test_reserved_type_showing_up_is_reported_not_hidden():
    rep = drift({"tenant_a": _schema({"Service": 1}, {**_seeded_rels(), "HAS_ALERT": 4})})
    assert rep["ok"] and rep["reserved_present"] == ["HAS_ALERT"]


# ------------------------------------------------------------------ MCP resources and prompts (content)
def test_queries_resource_lists_every_template_with_params():
    cat = {q["id"]: q for q in R.queries_catalogue()}
    assert set(cat) == set(catalogue())
    assert {"cause", "symptom"} <= set(cat["Q-GATE-1"]["params"])
    assert cat["Q-SCHEMA-1"]["params"] == [] and cat["Q-SCHEMA-1"]["file"] == "schema_stats.cypher"


def test_weights_resource_is_weights_yaml_verbatim():
    from faultline.agent.weights import WEIGHTS_PATH

    assert R.weights_resource() == WEIGHTS_PATH.read_text()


ARG_WORDS = {"pr_id", "change_id", "observed_share", "would_change_if", "evidence_id", "require_review"}


@pytest.mark.parametrize("fn,arg", [(R.investigate_incident, "checkout error rate up"),
                                    (R.preflight_pr, "PR-7"), (R.ask_brain, "who knows payments?")])
def test_prompts_state_the_rule_and_name_only_real_tools(fn, arg):
    text = fn(arg)
    assert "no path, no claim" in text and arg in text
    named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text)) - ARG_WORDS
    assert named and named <= set(T.TOOLS), named - set(T.TOOLS)


@pytest.mark.parametrize("fn", [R.investigate_incident, R.preflight_pr, R.ask_brain])
def test_prompts_reject_empty_or_oversized_arguments(fn):
    for bad in ("", "   ", "x" * 1000):
        with pytest.raises(ValueError):
            fn(bad)


def test_graph_schema_is_hosted_and_offered_with_text2cypher():
    assert "graph_schema" in T.TOOLS and "graph_schema" not in phases.INTERNAL_TOOLS
    inv = phases.investigation_toolset()
    assert inv.index("graph_schema") < inv.index("run_cypher_readonly")
