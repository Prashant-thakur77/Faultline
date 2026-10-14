"""Schema introspection of a live tenant graph, and which templates read which relationship types.

* `introspect(ro)`: runs Q-SCHEMA-1..4 through the read-only wrapper (GRAPH.RO_QUERY + TIMEOUT + LIMIT) and
  assembles labels (counts, sampled property keys, indexes) and relationship types (counts, endpoint pairs).
  Every count comes from the engine (db.meta.stats, bounded scans); this module only reshapes rows.
* `template_rel_usage()`: static scan of `templates/*.cypher` for the relationship types each template reads
  (relationship patterns and quoted type names in algo configs / `type(r)` tests).
* `drift(live)`: name-set comparison of live graphs against `schema_model` (undeclared labels/types fail loudly).

Used by the `graph_schema` MCP tool and resource, scripts/gen_graph_schema.py and scripts/check_schema_drift.py.
"""

from __future__ import annotations

import re
from typing import Any

from . import schema_model as M
from .ro import RO, QueryResult
from .templates import catalogue, mask_strings

SCHEMA_TEMPLATES = ("Q-SCHEMA-1", "Q-SCHEMA-2", "Q-SCHEMA-3", "Q-SCHEMA-4")
REL_SCAN_CAP = 100_000   # mirrors the literal edge cap in schema_rel_pairs.cypher
NODE_SCAN_CAP = 20_000   # mirrors the literal node cap in schema_props.cypher


def introspect(ro: RO) -> tuple[dict[str, Any], list[QueryResult]]:
    """Live schema of `ro`'s graph. Returns (schema, the four QueryResults, for provenance)."""
    stats, pairs, props, idx = (ro.run(t, {}) for t in SCHEMA_TEMPLATES)
    if not stats.rows:
        raise ValueError("db.meta.stats returned no row")
    s = stats.rows[0]
    label_counts: dict[str, int] = {k: int(v) for k, v in (s.get("labels") or {}).items()}
    rel_counts: dict[str, int] = {k: int(v) for k, v in (s.get("relTypes") or {}).items()}
    keys_by_label = {r["label"]: r for r in props.rows if r.get("label")}
    idx_by_label: dict[str, list[dict]] = {}
    for r in idx.rows:
        for p in r.get("properties") or []:
            idx_by_label.setdefault(r["label"], []).append(
                {"property": p, "types": list((r.get("types") or {}).get(p) or []), "entity": r.get("entitytype"),
                 "status": r.get("status")})
    labels = []
    for name in sorted((set(label_counts) | set(keys_by_label)) - {M.BASE_LABEL}):
        kr = keys_by_label.get(name, {})
        labels.append({"label": name, "n": label_counts.get(name, 0), "sampled": int(kr.get("sampled") or 0),
                       "keys": [{"key": k["key"], "n": int(k["n"])} for k in kr.get("keys") or []],
                       "indexes": idx_by_label.get(name, [])})
    pairs_by_type = {r["type"]: r for r in pairs.rows}
    rels = []
    for name in sorted(set(rel_counts) | set(pairs_by_type)):
        pr = pairs_by_type.get(name, {})
        rels.append({"type": name, "n": rel_counts.get(name, 0),
                     "pairs": [{"src": p["src"], "dst": p["dst"], "n": int(p["n"])} for p in pr.get("pairs") or []]})
    sampled_edges = sum(int(r.get("sampled") or 0) for r in pairs.rows)
    sampled_nodes = sum(int(r.get("sampled") or 0) for r in props.rows)
    schema = {
        "labels": labels,
        "relationships": rels,
        "totals": {"nodes": int(s.get("nodeCount") or 0), "edges": int(s.get("relCount") or 0),
                   "labels_present": sum(1 for x in labels if x["n"] > 0),
                   "rel_types_present": sum(1 for x in rels if x["n"] > 0),
                   "property_keys": int(s.get("propertyKeyCount") or 0)},
        "complete": {"pairs": not pairs.truncated and sampled_edges == int(s.get("relCount") or 0),
                     "keys": not props.truncated and sampled_nodes == int(s.get("nodeCount") or 0),
                     "edges_scanned": sampled_edges, "nodes_scanned": sampled_nodes,
                     "edge_cap": REL_SCAN_CAP, "node_cap": NODE_SCAN_CAP},
        "graph": ro.graph_name,
    }
    return schema, [stats, pairs, props, idx]


# ------------------------------------------------------------------ static: which templates read which rel types
_REL_PATTERN = re.compile(r"\[\s*\w*\s*:\s*([A-Za-z_]\w*(?:\s*\|\s*:?\s*[A-Za-z_]\w*)*)")
_QUOTED = re.compile(r"'([A-Z][A-Z0-9_]*)'|\"([A-Z][A-Z0-9_]*)\"")


def rels_in(cypher: str) -> set[str]:
    """Relationship types a template's Cypher reads: `[r:A|B*1..3]` patterns (strings masked), plus quoted
    names that are declared relationship types (algo `relationshipTypes: ['X']`, `type(r) = 'X'`)."""
    out: set[str] = set()
    for m in _REL_PATTERN.finditer(mask_strings(cypher)):
        out |= {t.strip().lstrip(":").strip() for t in m.group(1).split("|")}
    for m in _QUOTED.finditer(cypher):
        name = m.group(1) or m.group(2)
        if name in M.REL_TYPES:
            out.add(name)
    return out


def template_rel_usage() -> dict[str, list[str]]:
    """rel type → sorted template ids that read it (every type found, declared or not)."""
    use: dict[str, set[str]] = {}
    for tid, t in catalogue().items():
        for rel in rels_in(t.display):
            use.setdefault(rel, set()).add(tid)
    return {k: sorted(v) for k, v in sorted(use.items())}


# ------------------------------------------------------------------ drift: live graphs vs schema_model
def drift(live: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """`live` = {graph name: introspect() schema}. Failures: labels / rel types in a graph (even with 0 nodes or
    edges: the engine registered them) that schema_model does not declare; declared rel types absent from every
    graph that are neither RUNTIME_RELS nor RESERVED_RELS; templates reading an undeclared rel type.
    Reported, not failing: write-only types (present, read by no template), reserved types now present, declared
    labels absent everywhere."""
    usage = template_rel_usage()
    known_labels: set[str] = set()
    present_labels: set[str] = set()
    known_rels: set[str] = set()
    present_rels: set[str] = set()
    per_graph = {}
    for g, s in live.items():
        kl = {x["label"] for x in s["labels"]}
        kr = {x["type"] for x in s["relationships"]}
        known_labels |= kl
        known_rels |= kr
        present_labels |= {x["label"] for x in s["labels"] if x["n"] > 0}
        present_rels |= {x["type"] for x in s["relationships"] if x["n"] > 0}
        per_graph[g] = {"undeclared_labels": sorted(kl - M.NODE_LABELS), "undeclared_rels": sorted(kr - M.REL_TYPES)}
    undeclared_labels = sorted(known_labels - M.NODE_LABELS)
    undeclared_rels = sorted(known_rels - M.REL_TYPES)
    declared_absent = sorted(M.REL_TYPES - present_rels - M.RUNTIME_RELS - M.RESERVED_RELS)
    template_undeclared = {r: ts for r, ts in usage.items() if r not in M.REL_TYPES}
    failures = []
    if undeclared_labels:
        failures.append(f"labels in the graph but not in schema_model.NODE_LABELS: {undeclared_labels}")
    if undeclared_rels:
        failures.append(f"relationship types in the graph but not in schema_model.REL_TYPES: {undeclared_rels}")
    if declared_absent:
        failures.append("declared relationship types absent from every graph and not listed in RUNTIME_RELS / "
                        f"RESERVED_RELS: {declared_absent}")
    if template_undeclared:
        failures.append(f"templates read relationship types not in schema_model.REL_TYPES: {template_undeclared}")
    return {
        "ok": not failures,
        "failures": failures,
        "graphs": per_graph,
        "write_only": sorted(present_rels - set(usage)),
        "runtime_absent": sorted((M.RUNTIME_RELS - present_rels)),
        "reserved_absent": sorted(M.RESERVED_RELS - present_rels),
        "reserved_present": sorted(M.RESERVED_RELS & present_rels),
        "labels_absent": sorted(M.NODE_LABELS - present_labels),
        "unread_declared": sorted(M.REL_TYPES - set(usage)),
        "usage": usage,
    }


def lifecycle(rel: str) -> str:
    """How a declared relationship type comes to exist: seeded, runtime-only, scratch-only or reserved."""
    if rel == "KNOWS_ABOUT":
        return "scratch"
    if rel in M.RUNTIME_RELS:
        return "runtime"
    if rel in M.RESERVED_RELS:
        return "reserved"
    return "seed" if rel in M.REL_TYPES else "UNDECLARED"


def tenants_in_engine() -> list[str]:
    """Tenants with a live `tenant_<t>` graph (GRAPH.LIST on the engine connection; ops scripts only)."""
    from . import client
    from .tenant import TENANT_RE

    out = []
    for name in client.engine().list_graphs():
        name = name.decode() if isinstance(name, bytes) else name
        if name.startswith("tenant_") and TENANT_RE.fullmatch(name[len("tenant_"):]):
            out.append(name[len("tenant_"):])
    return sorted(out)
