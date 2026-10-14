"""Specialist base: a role, its own tool whitelist (agent/phases.py SPECIALIST_TOOLS) and one typed contract out.

A specialist calls tools ONLY through the run's ToolBox (`ctx.call`), so every call is phase-whitelisted (INVESTIGATE),
role-whitelisted, sent over MCP for graph tools and recorded in FalkorDB as a ToolCall + Evidence before anything uses
it. It returns exactly one `SpecialistReport` (agent/contracts.py); it never confirms, eliminates or scores a cause
(the sweep and the gate own hypotheses, so a report cannot move G6, and numbers come from code).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, Callable

from ...graph.errors import GraphTimeout, GraphUnavailable
from .. import phases
from ..contracts import EvidenceRef, SpecialistReport, ref

log = logging.getLogger("faultline.specialists")

if TYPE_CHECKING:  # pragma: no cover
    from ..loop import RunState, ToolBox


@dataclass
class SpecialistCtx:
    role: str
    box: "ToolBox"
    run: "RunState"
    packet: dict
    renew: Callable[[], bool] | None = None   # extends this work item's claim lease (called on every tool call)

    @property
    def incident_id(self) -> str:
        return self.run.inc

    @property
    def suspects(self) -> list[dict]:
        return list(self.packet.get("suspects") or [])

    async def call(self, name: str, args: dict | None = None) -> dict:
        """Through the ToolBox: the INVESTIGATE whitelist intersected with this role's whitelist. A tool that reports
        the graph unavailable or timed out raises (GraphUnavailable / GraphTimeout): an outage fails the run loudly,
        it is never an 'insufficient' report that reads like a finding."""
        if self.renew is not None and not self.renew():   # reaped and re-claimed meanwhile: this result won't be the record
            log.warning("%s specialist: work item lease lost before calling %s", self.role, name)
        out = await self.box.call(name, args or {}, only=phases.specialist_toolset(self.role), caller=f"{self.role} specialist")
        raise_if_outage(name, out)
        return out


def raise_if_outage(tool: str, out: dict) -> None:
    """Tool envelopes report graph failures as strings: the MCP guard ("unavailable: …" for GraphUnavailable,
    "GraphTimeout: …"), the warehouse/data tools ("unavailable: …" for any graph error). Turn those back into the
    fail-loud exceptions; every other error (bad arguments, not found) stays a result the specialist reasons about."""
    err = out.get("error") if isinstance(out, dict) else None
    if not isinstance(err, str):
        return
    if err.startswith("GraphTimeout:") or (err.startswith("unavailable:") and "timed out" in err.lower()):
        raise GraphTimeout(f"{tool}: {err}")
    if err.startswith("unavailable:"):
        raise GraphUnavailable(f"{tool}: {err}")


class Specialist:
    role: str = ""
    limits: list[str] = []

    async def run(self, ctx: SpecialistCtx) -> Any:  # returns a SpecialistReport (anything else is rejected)
        raise NotImplementedError

    def report(self, ctx: SpecialistCtx, *, evidence: list[EvidenceRef | None], suspect_ids: list[str],
               unknowns: list[str], complete: bool | None = None) -> SpecialistReport:
        ev = [e for e in evidence if e is not None]
        done = bool(ev) if complete is None else (complete and bool(ev))
        return SpecialistReport(contract_version="1", role=self.role, incident_id=ctx.incident_id,  # type: ignore[arg-type]
                                status="complete" if done else "insufficient",
                                suspect_ids=list(dict.fromkeys(suspect_ids)) if done else [],
                                evidence=ev, unknowns=unknowns[:20], limits=list(self.limits))


__all__ = ["Specialist", "SpecialistCtx", "ref", "raise_if_outage"]
