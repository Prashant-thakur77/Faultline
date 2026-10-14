"""The crew (M17): each stage of an incident is a work item claimed by a named, least-privilege agent, completed with
what it did, and handed to the next agent, all recorded in FalkorDB:

    (:Run)-[:HAS_TASK]->(:Task {kind:'crew'})-[:CLAIMED_BY {at, n}]->(:Agent)   the step and who did it
    (:Task)-[:MADE]->(:ToolCall)                                                the graph calls this agent made
    (:Task)-[:NEXT]->(:Task)                                                    the hand-off order between steps

The roster is the single source for who does what: its tools are the stage whitelists in phases.py (the ToolBox enforces
them), its write rights are the ones in graph/writes.py it reaches. The agents here are deterministic code; only the
lead investigator may use a language model (LLMInvestigator), and the Gatekeeper never does: a model may propose,
a read-only query decides. The step context manager is synchronous so the API's approval job uses it too.

Crew Tasks are RECORDS, not locks: a step does its work whether or not its record could be claimed (a resumed job),
nothing waits on them, and the reaper never reopens them. What serialises work is elsewhere and unchanged: the
specialists' W-CLAIM-1 work items (fenced by epoch), the Intent lease for the one action (the Operator's real task),
and the gate, which runs as code in every run and is never skippable. Crew records never vote in G7 (Q-GATE-CORR reads
specialist tasks only).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator

from ..graph import client as gclient
from ..graph import writes
from ..graph.ro import RO
from . import phases
from .state import Stage

log = logging.getLogger("faultline.crew")

CREW_LEASE_MS = 30 * 60_000


@dataclass(frozen=True)
class Member:
    key: str
    name: str
    job: str
    stages: tuple[Stage, ...]
    writes: str          # what it may change, and through which write path
    model: str = "none"  # "none" (deterministic code) or "optional" (a model may drive it; the gate still decides)

    def tools(self) -> list[str]:
        return sorted({t for s in self.stages for t in phases.stage_toolset(s)})


ROSTER: tuple[Member, ...] = (
    Member("triage", "Triage", "groups the alert storm into independent incidents (algo.WCC)", (Stage.INTAKE,),
           "opens incidents and attaches alerts (intake writes)"),
    Member("historian", "Historian", "recalls past incidents and runbooks that share the symptoms", (Stage.RECALL,),
           "records what was recalled (W-RECALL)"),
    Member("cartographer", "Cartographer", "maps the symptoms' upstream scope, context and blast radius",
           (Stage.LOCALIZE, Stage.BLAST), "none (read-only)"),
    Member("profiler", "Profiler", "lists the changes upstream of the symptoms in the window and ranks them in code",
           (Stage.HYPOTHESIZE,), "open hypotheses (W-HYP)"),
    Member("lead", "Lead investigator", "dispatches the five specialists and proposes a cause to the gate",
           (Stage.INVESTIGATE,), "hypothesis status, through the gate only", model="optional"),
    Member("gatekeeper", "Gatekeeper", "decides: path, flow, time, origin, rivals, agreement, contradictions (G1–G8)",
           (Stage.GATE, Stage.CONTRADICTION), "gate runs (W-GATE)"),
    Member("containment", "Containment", "finds the smallest cut (algo.maxFlow) and tries each option on a GRAPH.COPY",
           (Stage.CONTAIN,), "none (clean rooms are scratch graphs)"),
    Member("dispatcher", "Dispatcher", "finds who fixes it, the escalation path, obligations and who to notify",
           (Stage.ROUTE,), "none (read-only)"),
    Member("planner", "Planner", "turns the cut into options from the fixed action enum, each with a plan hash",
           (Stage.PLAN,), "plan and options (W-PLAN)"),
    Member("operator", "Operator", "executes the one approved action, intent first (the only holder of execute_action)",
           (Stage.EXECUTE,), "intent and action (W-INTENT, the single write tool)"),
    Member("auditor", "Auditor", "verifies the action through a second channel and re-reads the write-back",
           (Stage.VERIFY, Stage.WRITEBACK), "verdict and write-back (W-WB), re-read on a separate RO connection"),
    Member("librarian", "Librarian", "files the incident into memory so the next one starts warm", (Stage.LEARN,),
           "family and consolidation (W-LEARN)"),
)
BY_KEY = {m.key: m for m in ROSTER}
INVESTIGATORS = ("topology", "telemetry", "data", "change", "code")  # the specialists (agent/specialists), dispatched by the lead


def agent_id(key: str) -> str:
    return f"crew-{key}"


@dataclass
class Step:
    """What a crew step did, filled in by its caller; completed when the `with` block ends."""
    member: Member
    stage: Stage
    task: str
    summary: str = ""
    tool_calls: list[str] = field(default_factory=list)
    owned: bool = True
    epoch: int = 0


@contextmanager
def step(*, tenant: str, graph: str, run_id: str, key: str, stage: Stage,
         made: Callable[[], list[str]] | None = None, tag: str = "") -> Iterator[Step]:
    """Claim `crew-<run>-<key>-<stage>`, run the block, complete it (done, or failed if the block raised; the error
    still propagates), handing off from the run's previous crew step. `made` returns the tool-call ids recorded in
    the block (the ToolBox collects them)."""
    m = BY_KEY[key]
    g = gclient.engine().select_graph(graph)
    task = f"crew-{run_id}-{key}-{stage.value.lower()}" + (f"-{tag}" if tag else "")   # tag: the action, after approval
    prev = RO(tenant, graph).run("Q-CREW-LAST", {"run": run_id}).rows   # the last completed crew step of this run
    st = Step(m, stage, task)
    st.epoch = writes.claim_epoch(g, task=task, agent=agent_id(key), role=f"crew:{key}", kind="crew", tenant=tenant,
                                  lease_ms=CREW_LEASE_MS, run=run_id)
    st.owned = st.epoch > 0
    if not st.owned:  # the same run's step is already held (a resumed job): do the work, record nothing twice
        log.warning("crew %s: step %s already claimed; not recorded again", key, task)
    failed: BaseException | None = None
    try:
        yield st
    except BaseException as e:  # noqa: BLE001 - recorded, then re-raised unchanged
        failed = e
        raise
    finally:
        if st.owned:
            calls = st.tool_calls + (made() if made else [])
            summary = st.summary or (f"failed: {type(failed).__name__}: {failed}" if failed else "")
            ok = writes.complete_crew_step(
                g, task=task, agent=agent_id(key), n=st.epoch, run=run_id, role=key, stage=stage.value,
                stages=[s.value for s in m.stages], summary=summary, tool_calls=calls,
                prev=prev[0]["task"] if prev else None, failed=failed is not None)
            if not ok:
                log.error("crew %s: step %s record not closed (its claim moved)", key, task)


class Shift:
    """Linear crew steps for straight-line code (the run loop): `begin` ends the current step and claims the next one;
    `end(failed=...)` closes the last. Equivalent to nesting `step(...)` blocks, without re-indenting the loop."""

    def __init__(self, tenant: str, graph: str, run_id: str, made: Callable[[], list[str]] | None = None):
        self.tenant, self.graph, self.run_id, self.made = tenant, graph, run_id, made
        self._cm = None
        self.cur: Step | None = None

    def begin(self, key: str, stage: Stage, tag: str = "") -> Step:
        self.end()
        if self.made:
            self.made()   # calls made between steps belong to no step
        self._cm = step(tenant=self.tenant, graph=self.graph, run_id=self.run_id, key=key, stage=stage, made=self.made,
                        tag=tag)
        self.cur = self._cm.__enter__()
        return self.cur

    def note(self, text: str) -> None:
        if self.cur is not None:
            self.cur.summary = text

    def end(self, failed: BaseException | None = None) -> None:
        cm, self._cm, self.cur = self._cm, None, None
        if cm is None:
            return
        if failed is None:
            cm.__exit__(None, None, None)
        else:
            try:
                cm.__exit__(type(failed), failed, failed.__traceback__)
            except BaseException:  # noqa: BLE001 - the step re-raises the failure; the caller already handles it
                pass


def roster() -> list[dict]:
    """The roster as data (API, docs/AGENTS.md): who does what, with which tools, and what it may write."""
    return [{"key": m.key, "id": agent_id(m.key), "name": m.name, "job": m.job, "stages": [s.value for s in m.stages],
             "tools": m.tools(), "writes": m.writes, "model": m.model} for m in ROSTER]


__all__ = ["ROSTER", "BY_KEY", "INVESTIGATORS", "Member", "Step", "Shift", "step", "roster", "agent_id", "CREW_LEASE_MS"]
