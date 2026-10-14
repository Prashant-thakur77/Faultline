"""Forward-only incident stages. Terminals are sticky. The same rule is enforced in
the graph by the stage write itself (writes.advance_stage only moves forward)."""

from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    INTAKE = "INTAKE"
    RECALL = "RECALL"
    LOCALIZE = "LOCALIZE"
    BLAST = "BLAST"
    HYPOTHESIZE = "HYPOTHESIZE"
    INVESTIGATE = "INVESTIGATE"
    GATE = "GATE"
    CONTRADICTION = "CONTRADICTION"
    CONTAIN = "CONTAIN"
    ROUTE = "ROUTE"
    PLAN = "PLAN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    WRITEBACK = "WRITEBACK"
    LEARN = "LEARN"
    # terminals
    RESOLVED = "RESOLVED"
    NO_INCIDENT = "NO_INCIDENT"
    UNKNOWN_ESCALATED = "UNKNOWN_ESCALATED"
    FAILED = "FAILED"


ORDER: list[Stage] = [
    Stage.INTAKE, Stage.RECALL, Stage.LOCALIZE, Stage.BLAST, Stage.HYPOTHESIZE, Stage.INVESTIGATE, Stage.GATE,
    Stage.CONTRADICTION, Stage.CONTAIN, Stage.ROUTE, Stage.PLAN, Stage.AWAITING_APPROVAL, Stage.EXECUTE,
    Stage.VERIFY, Stage.WRITEBACK, Stage.LEARN, Stage.RESOLVED,
]
TERMINALS = frozenset({Stage.RESOLVED, Stage.NO_INCIDENT, Stage.UNKNOWN_ESCALATED, Stage.FAILED})
EXITS = frozenset({Stage.NO_INCIDENT, Stage.UNKNOWN_ESCALATED, Stage.FAILED})  # reachable from any non-terminal

# Mapping from the existing system's stages, kept for the ported tests/UI.
LEGACY = {
    "REPORTED": Stage.INTAKE, "CONTEXT_DISCOVERY": Stage.LOCALIZE, "LINEAGE_TRAVERSAL": Stage.BLAST,
    "HYPOTHESIS_GENERATION": Stage.HYPOTHESIZE, "EVIDENCE_COLLECTION": Stage.INVESTIGATE,
    "ROOT_CAUSE_CONFIRMED": Stage.GATE, "REPAIR_GENERATED": Stage.PLAN, "REPAIR_TESTING": Stage.EXECUTE,
    "VERIFIED": Stage.VERIFY, "WRITEBACK_COMPLETE": Stage.WRITEBACK,
}


def ordinal(s: Stage) -> int:
    if s in ORDER:
        return ORDER.index(s) + 1
    return 100  # exits sort after everything


def can_advance(current: Stage, target: Stage) -> bool:
    if current in TERMINALS:
        return False
    if target in EXITS:
        return True
    return ordinal(target) > ordinal(current)
