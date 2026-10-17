"""M20 #1 (unit): the declared engine constraints match what every writer in graph/writes.py sets.

For each MANDATORY node constraint, every W_* write query that CREATEs or MERGEs that label must set each mandatory
property, in the CREATE/MERGE map or with `<var>.<prop> =` in the same query (ON CREATE SET counts: the engine checks
at commit, verified on 6.0.2). Run nodes are always written as Run:Node (the old label-less writer could split a run).
"""

import re

from faultline.graph import constraints as C
from faultline.graph import writes


def _write_queries() -> dict[str, str]:
    return {k: v for k, v in vars(writes).items() if k.startswith("W_") and isinstance(v, str)}


def test_constraint_set_is_well_formed():
    keys = [c.key for c in C.CONSTRAINTS]
    assert len(keys) == len(set(keys))
    for c in C.CONSTRAINTS:
        assert c.kind in ("UNIQUE", "MANDATORY") and c.entity in ("NODE", "RELATIONSHIP") and c.props and c.why
        assert c.args()[:4] == [c.kind, c.entity, c.label, "PROPERTIES"] and c.args()[4] == len(c.props)
    must = {("MANDATORY", "Evidence"): {"kind", "source", "digest"}, ("MANDATORY", "Page"): {"ack_due_at"},
            ("MANDATORY", "Approval"): {"plan_hash"}, ("MANDATORY", "PROPAGATES_TO"): {"cap"},
            ("MANDATORY", "Node"): {"id"}, ("UNIQUE", "Run"): {"id"}, ("UNIQUE", "Intent"): {"idem"}}
    have = {(c.kind, c.label): set(c.props) for c in C.CONSTRAINTS}
    for k, props in must.items():          # the M20 brief: provenance, page deadline, plan hash, cap, ids
        assert props <= have.get(k, set()), k


def test_every_writer_of_a_constrained_label_sets_its_mandatory_properties():
    mandatory = {c.label: c.props for c in C.CONSTRAINTS if c.kind == "MANDATORY" and c.entity == "NODE"
                 and c.label != "Node"}
    checked = 0
    for name, q in _write_queries().items():
        for label, props in mandatory.items():
            for m in re.finditer(rf"(CREATE|MERGE)\s*\((\w+):{label}\b[^{{)]*(\{{[^}}]*\}})?", q):
                var, inline = m.group(2), m.group(3) or ""
                for p in props:
                    ok = re.search(rf"\b{p}\s*:", inline) or re.search(rf"\b{var}\.{p}\s*=", q)
                    assert ok, f"{name} writes :{label} without {p}"
                checked += 1
    assert checked >= 12                     # Evidence ×2, ToolCall ×3, Page ×3, Approval, GateRun, Action, …


def test_every_run_writer_uses_run_node():
    for name, q in _write_queries().items():
        for m in re.finditer(r"(MERGE|CREATE)\s*\(\w+:Run\b([:\w]*)", q):
            assert ":Node" in m.group(2), f"{name}: a Run must be written as Run:Node (one label set, one node per id)"


def test_flow_edge_writers_set_cap():
    for name, q in _write_queries().items():
        for m in re.finditer(r"(CREATE|MERGE)\s*\(\w+\)-\[(\w+):PROPAGATES_TO\s*(\{[^}]*\})?\]", q):
            var, inline = m.group(2), m.group(3) or ""
            assert "cap" in inline or re.search(rf"\b{var}\.cap\s*=|\b{var}\s*\+=", q), name


def test_unique_only_on_small_labels_and_retired_never_wanted():
    """6.0.2 makes every insert under a UNIQUE constraint cost O(label size) (docs/upstream/25): never UNIQUE over :Node."""
    assert not any(c.kind == "UNIQUE" and c.label == "Node" for c in C.CONSTRAINTS)
    assert not {c.key for c in C.RETIRED} & {c.key for c in C.CONSTRAINTS}


def test_key_of_reads_db_constraints_rows():
    row = ["MANDATORY", "Evidence", ["source", "kind", "digest", "id"], "NODE", "OPERATIONAL"]
    assert C.key_of(row) == ("MANDATORY", "NODE", "Evidence", ("digest", "id", "kind", "source"))
    assert C.key_of(row) in C.by_key()
