"""Specialists dispatched in parallel from INVESTIGATE, with W-CLAIM-1 work-item claims (each item runs once).

    reports = await dispatch(box, run, packet)

For each role, in one anyio task group:
1. claim the work item `spec-<run>-<role>-<scope>` with W-CLAIM-1 (one atomic conditional write). Exactly one dispatch
   wins a work item; any other dispatch of the same item (a retry, a second worker) records `skipped` and runs nothing;
2. run the specialist (its tools go through the run's ToolBox: stage + role whitelist, MCP, recorded evidence);
3. accept exactly one contract: `parse_report` rejects prose, fences and schema errors, `validate_against_run` rejects
   unseen suspects, foreign evidence and observations missing from the payload. One retry, then `insufficient`;
   a specialist that crashes (any other exception) is recorded `insufficient` with the error, and the run goes on;
   a graph outage (GraphUnavailable, or a GraphTimeout, raised directly or reported by a tool) is NOT a crash: it
   propagates and fails the run loudly, never an `insufficient` that would read like a finding;
4. complete the work item with the contract (Task NAMES suspects, CITES evidence), only if this dispatch still owns it.

Gate G7 reads those Task edges from the graph (Q-GATE-CORR); nothing here decides a cause.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio

from ...graph import writes
from ...graph.errors import GraphTimeout, GraphUnavailable
from ...graph.ro import RO
from ..contracts import ROLES, ContractError, SpecialistReport, insufficient, parse_report, validate_against_run
from .base import Specialist, SpecialistCtx
from .change import ChangeSpecialist
from .code import CodeSpecialist
from .data import DataSpecialist
from .telemetry import TelemetrySpecialist
from .topology import TopologySpecialist

if TYPE_CHECKING:  # pragma: no cover
    from ..loop import RunState, ToolBox

log = logging.getLogger("faultline.specialists")

REGISTRY: dict[str, type[Specialist]] = {
    "topology": TopologySpecialist, "telemetry": TelemetrySpecialist, "data": DataSpecialist,
    "change": ChangeSpecialist, "code": CodeSpecialist,
}
MAX_ATTEMPTS = 2  # one answer + one retry, then status="insufficient"
# evidence the deterministic investigator cites to the gate: the measurements (what G4/G5 and N1 read)
MEASUREMENT_TOOLS = ("metric_window", "get_metric_history", "compare_to_baseline", "anomalous_row_share")


@dataclass
class Dispatched:
    role: str
    task: str
    agent: str
    report: SpecialistReport | None = None
    skipped: bool = False                 # another dispatch owns this work item; nothing ran here
    owner: str | None = None
    attempts: int = 0
    rejected: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        r = self.report
        return {"role": self.role, "task": self.task, "skipped": self.skipped, "owner": self.owner,
                "status": r.status if r else None, "suspect_ids": r.suspect_ids if r else [],
                "evidence": [{"evidence_id": e.evidence_id, "tool": e.tool, "observations": e.observations[:6]}
                             for e in (r.evidence if r else [])][:12],
                "unknowns": r.unknowns[:8] if r else [], "limits": r.limits if r else [], "rejected": self.rejected}


def work_item(run_id: str, role: str, packet: dict) -> str:
    """Deterministic work-item id: the same run, role and suspect scope is the same item (so a re-dispatch is a no-op)."""
    scope = json.dumps({"suspects": sorted(s["id"] for s in packet.get("suspects") or []),
                        "symptoms": sorted(packet.get("symptoms") or [])}, sort_keys=True)
    return f"spec-{run_id}-{role}-{hashlib.sha256(scope.encode()).hexdigest()[:8]}"


async def _one(role: str, box: "ToolBox", run: "RunState", packet: dict, dispatch_id: str,
               registry: dict[str, type[Specialist]]) -> Dispatched:
    task, agent = work_item(run.run_id, role, packet), f"{role}-specialist-{dispatch_id}"
    out = Dispatched(role, task, agent)
    g = run.g()
    epoch = writes.claim_epoch(g, task=task, agent=agent, role=f"specialist:{role}", kind="specialist", tenant=run.tenant,
                               run=run.run_id)
    if not epoch:
        rows = RO(run.tenant, run.graph).run("Q-TASK-1", {"ids": [task]}).rows
        out.skipped, out.owner = True, (rows[0]["owner"] if rows else None)
        log.info("specialist %s: work item %s already claimed by %s; not run", role, task, out.owner)
        return out
    out.owner = agent
    spec = registry[role]()
    # each tool call renews the claim's lease (a slow specialist is not reaped while it works)
    ctx = SpecialistCtx(role, box, run, packet, renew=lambda: writes.renew_task(g, task=task, agent=agent, n=epoch))
    report: SpecialistReport | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        out.attempts = attempt
        try:
            raw = await spec.run(ctx)
            report = validate_against_run(parse_report(raw, role=role, incident_id=run.inc), RO(run.tenant, run.graph), run.run_id)
            break
        except ContractError as e:
            out.rejected.append(f"attempt {attempt}: {e}"[:400])
            log.warning("specialist %s: contract rejected (attempt %d): %s", role, attempt, e)
        except (GraphUnavailable, GraphTimeout) as e:  # an outage is not a finding: fail the run loudly
            log.error("specialist %s: graph outage, failing the run: %s", role, e)
            raise
        except Exception as e:  # noqa: BLE001 - one specialist crashing must not abort the run (cancellation still propagates)
            crash = f"{type(e).__name__}: {e}"[:300]
            out.rejected.append(f"attempt {attempt}: crashed: {crash}"[:400])
            log.error("specialist %s crashed (attempt %d): %s", role, attempt, crash)
            report = insufficient(role, run.inc, f"specialist crashed: {crash}", limits=list(getattr(spec, "limits", [])))
            break
    if report is None:
        report = insufficient(role, run.inc, f"contract rejected {MAX_ATTEMPTS} times: {out.rejected[-1]}",
                              limits=list(getattr(spec, "limits", [])))
    out.report = report
    ok = writes.complete_specialist_task(
        g, task=task, agent=agent, run=run.run_id, role=role, status=report.status, names=report.suspect_ids,
        cites=[e.evidence_id for e in report.evidence], unknowns=report.unknowns, limits=report.limits,
        report={"contract": report.model_dump(), "attempts": out.attempts, "rejected": out.rejected},
        tool_calls=box.take(f"{role} specialist") if box is not None else [], n=epoch)
    if not ok:  # the claim moved (handoff) while we ran: our result is not the record
        raise writes.WriteError(f"specialist {role}: lost work item {task} before completing it")
    return out


async def dispatch(box: "ToolBox", run: "RunState", packet: dict, *, roles: tuple[str, ...] = ROLES,
                   registry: dict[str, type[Specialist]] | None = None, dispatch_id: str | None = None) -> dict[str, Dispatched]:
    """Run the specialists in parallel. Returns one Dispatched per role (skipped ones carry no report)."""
    reg = registry or REGISTRY
    did = dispatch_id or uuid.uuid4().hex[:8]
    results: dict[str, Dispatched] = {}

    async def go(role: str) -> None:
        results[role] = await _one(role, box, run, packet, did, reg)

    async with anyio.create_task_group() as tg:
        for role in roles:
            tg.start_soon(go, role)
    return {r: results[r] for r in roles}


def measurement_evidence(reports: dict[str, Dispatched]) -> list[str]:
    """Measurement evidence ids the reports cite (telemetry first, then data), in a stable order, without duplicates."""
    out: list[str] = []
    for role in ("telemetry", "data"):
        d = reports.get(role)
        for e in (d.report.evidence if d and d.report else []):
            if e.tool in MEASUREMENT_TOOLS and e.evidence_id not in out:
                out.append(e.evidence_id)
    return out


__all__ = ["dispatch", "Dispatched", "REGISTRY", "work_item", "measurement_evidence", "MEASUREMENT_TOOLS"]
