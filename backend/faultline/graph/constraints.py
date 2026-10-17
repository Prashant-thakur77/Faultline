"""Engine-enforced invariants (M20 #1): FalkorDB refuses a record that would break the evidence contract.

Before M20 only the code kept these promises (and only `Intent.idem` was engine-enforced). With the set below FalkorDB
itself rejects, in the same query that tries it:

* an Evidence without provenance (kind, source, digest), a ToolCall without its tool and time;
* an Approval not bound to a plan hash and an approver, an Intent without its state;
* a Page without its deadline (`ack_due_at`) or recipient, a Contract without its hash;
* a failure-flow edge (PROPAGATES_TO) without a capacity: the min-cut and G5 would be undefined on it;
* an ON_CALL shift without its window, an OWNED_AT era without its start;
* two runs or two intents sharing one id (`Run.id`, `Intent.idem` are UNIQUE), a node without an id (`Node.id` is
  MANDATORY; not UNIQUE over every node, which 6.0.2 makes cost O(label size) per insert: see RETIRED).

Constraints are an engine command (`GRAPH.CONSTRAINT`), not Cypher, so they cannot live in schema.cypher. This module
is declarative only (the set, the command arguments, the status read); `graph/writes.ensure_constraints` applies them
(writes live in writes.py) and is called by `writes.apply_schema`, so every path that applies the schema gets them:
seed (golden), every GRAPH.COPY (tenant, eval clean rooms, what-if, futures: the copy also carries them, verified on
6.0.2), the on-call home graph and the scale worlds.

Verified on 6.0.2 (docs/FALKORDB_COMPAT.md, M20 rows): a MANDATORY property set by `MERGE … ON CREATE SET` or a later
`SET` in the same query passes (checked at commit); a batch with one bad row rolls back whole; UNIQUE needs the
exact-match (range) index that schema.cypher already creates; a constraint over data that violates it ends FAILED.
Engine messages: `mandatory constraint violation: node with label Evidence missing property digest`,
`unique constraint violation on node of type Node`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Constraint:
    kind: str            # UNIQUE | MANDATORY
    entity: str          # NODE | RELATIONSHIP
    label: str           # a label or a relationship type (code constant, never caller input)
    props: tuple[str, ...]
    why: str = ""

    @property
    def key(self) -> tuple[str, str, str, tuple[str, ...]]:
        return (self.kind, self.entity, self.label, tuple(sorted(self.props)))

    def args(self) -> list[Any]:
        """The arguments after `GRAPH.CONSTRAINT CREATE|DROP <graph>`."""
        return [self.kind, self.entity, self.label, "PROPERTIES", len(self.props), *self.props]

    def describe(self) -> str:
        what = f"({self.label})" if self.entity == "NODE" else f"[:{self.label}]"
        return f"{self.kind} {what} {', '.join(self.props)}"


CONSTRAINTS: tuple[Constraint, ...] = (
    # ids: a second Run with the same id (the label-less Run writer, M20) is refused instead of silently
    # splitting a run's tool calls. UNIQUE is only used on small labels: on 6.0.2 a UNIQUE check costs time proportional
    # to the label's size on every insert (see RETIRED), so `Node.id` (every node) is MANDATORY, not UNIQUE.
    Constraint("UNIQUE", "NODE", "Run", ("id",), "one run per id (its tool calls and stages hang off one node)"),
    Constraint("UNIQUE", "NODE", "Intent", ("idem",), "one intent per idempotency key (an action executes once)"),
    Constraint("MANDATORY", "NODE", "Node", ("id",), "every node of the model has an id"),
    # the evidence contract
    Constraint("MANDATORY", "NODE", "Evidence", ("id", "kind", "source", "digest"),
               "evidence provenance: what kind, from which source, with which digest"),
    Constraint("MANDATORY", "NODE", "ToolCall", ("id", "tool", "at"), "every tool call names its tool and time"),
    # approval and action
    Constraint("MANDATORY", "NODE", "Approval", ("id", "approver_id", "plan_hash"),
               "an approval binds an approver to the exact plan hash"),
    Constraint("MANDATORY", "NODE", "Intent", ("idem", "state"), "an intent always has a state"),
    Constraint("MANDATORY", "NODE", "Action", ("id", "kind"), "an action has a kind (one write tool per kind)"),
    Constraint("MANDATORY", "NODE", "GateRun", ("id", "incident_id", "passed"), "a gate run records its verdict"),
    Constraint("MANDATORY", "NODE", "Decision", ("id", "status"), "a decision is active or superseded, never unknown"),
    # on-call
    Constraint("MANDATORY", "NODE", "Page", ("id", "kind", "person", "status", "sent_at", "ack_due_at"),
               "a page has a recipient, a status and a deadline (escalation reads ack_due_at)"),
    Constraint("MANDATORY", "NODE", "Contract", ("id", "status", "hash"), "a standing approval is bound to its hash"),
    # relationships the decisions read
    Constraint("MANDATORY", "RELATIONSHIP", "PROPAGATES_TO", ("cap",),
               "a failure-flow edge has a capacity (the min-cut and G5 are undefined without it)"),
    Constraint("MANDATORY", "RELATIONSHIP", "ON_CALL", ("from", "to"), "an on-call shift has its window"),
    Constraint("MANDATORY", "RELATIONSHIP", "OWNED_AT", ("from",), "an ownership era has its start"),
)

# Constraints Faultline created once and no longer wants; ensure_constraints drops them wherever they still exist.
# UNIQUE (Node) id: on 6.0.2 every insert into a label with a UNIQUE constraint costs time proportional to the label's
# size, despite the supporting range index (1,000 MERGEs: 0.005 s without, 5.2 s with the constraint at 19k nodes;
# docs/upstream/25). Over :Node (every node) the 1k-service scale world's seed timed out. Measured 2026-10-17.
RETIRED: tuple[Constraint, ...] = (
    Constraint("UNIQUE", "NODE", "Node", ("id",), "retired: O(label size) per insert on 6.0.2 (docs/upstream/25)"),
)

PENDING = ("PENDING", "UNDER CONSTRUCTION")
STATUS_QUERY = ("CALL db.constraints() YIELD type, label, properties, entitytype, status "
                "RETURN type, label, properties, entitytype, status")


def key_of(row: list | tuple) -> tuple[str, str, str, tuple[str, ...]]:
    """A db.constraints() row [type, label, properties, entitytype, status] → Constraint.key."""
    return (str(row[0]), str(row[3]), str(row[1]), tuple(sorted(str(p) for p in row[2] or [])))


def by_key() -> dict[tuple[str, str, str, tuple[str, ...]], Constraint]:
    return {c.key: c for c in CONSTRAINTS}


__all__ = ["Constraint", "CONSTRAINTS", "RETIRED", "PENDING", "STATUS_QUERY", "key_of", "by_key"]
