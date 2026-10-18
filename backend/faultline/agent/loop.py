"""Agent v2 run loop: ALERT → RECALL → LOCALIZE → BLAST → HYPOTHESIZE → INVESTIGATE → GATE.

* Deterministic stages run as code through graph tools called over MCP (in-memory transport, so tool
  selection through MCP is literal) and are recorded in FalkorDB as ToolCalls/Evidence/StageEvents.
* INVESTIGATE is driven by an Investigator: `LLMInvestigator` (Anthropic, pinned model ids) or
  `BaselineInvestigator` (deterministic rule-based policy for keyless runs/tests). Either can only
  PROPOSE a cause; `confirm_root_cause` runs the deterministic competitor sweep + Gate v2.
* Per-stage tool whitelists (agent/phases.py): a call outside the whitelist returns an error, logged.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from mcp.client import Client
from pydantic import create_model

from ..config import settings
from ..graph import client as gclient
from ..graph import writes
from ..graph.ro import RO
from ..graph.tenant import tenant_graph
from ..mcp_server import context
from ..mcp_server.server import build_server
from . import crew, datatools, phases, specialists
from .gate import Gate, GateResult, summarize
from .score import Score, rank, score
from .state import Stage, ordinal
from .weights import weights

GRAPH_TOOL_NAMES = None  # filled lazily from the MCP server's tool list
log = logging.getLogger("faultline.agent")


# ---------------------------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------------------------
@dataclass
class RunResult:
    run_id: str
    incident_id: str
    graph: str
    outcome: str                     # CONFIRMED | NOT_CONFIDENT | NO_INCIDENT | UNKNOWN_ESCALATED | FAILED
    cause_id: str | None = None
    confident: bool = False
    gate: dict | None = None
    sweep: list[dict] = field(default_factory=list)
    suspects: list[dict] = field(default_factory=list)
    tool_calls: int = 0
    gate_attempts: int = 0
    investigator: str = ""
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None
    trace: str | None = None
    post_gate: dict | None = None
    recall: dict | None = None
    inferred: dict | None = None
    residue: dict | None = None      # advisory residue check after a passed gate (never changes the outcome)
    note: dict | None = None         # the shared note this run left for other agents (share_notes runs only)
    specialists: dict | None = None  # per-role contract summaries (the full contracts live on the run's Task nodes)


# ---------------------------------------------------------------------------------------------
# toolbox
# ---------------------------------------------------------------------------------------------
class ToolBox:
    """One place every tool call goes through: whitelist check, MCP for graph tools, recorded evidence."""

    def __init__(self, run: "RunState", mcp: Client, graph_tools: dict[str, dict]):
        self.run, self.mcp, self.graph_tools = run, mcp, graph_tools
        self.stage = Stage.INTAKE
        self.calls = 0
        self.refusals = 0
        self.log: list[dict] = []
        self.made: dict[str, list[str]] = {}   # caller ("crew" or "<role> specialist") → ToolCall ids it made (MADE edges)

    async def call(self, name: str, args: dict | None = None, *, stage: Stage | None = None,
                   only: list[str] | None = None, caller: str | None = None) -> dict:
        """`only` narrows (never widens) the stage whitelist for one caller: the model's offered list, or a
        specialist's role list. A refused call returns an error, is logged and is recorded in the run."""
        args = dict(args or {})
        st = stage or self.stage
        allowed = phases.stage_toolset(st)
        if only is not None:
            allowed = [t for t in allowed if t in only]
        if name not in allowed:
            out = {"error": f"tool {name!r} not allowed in stage {st.value}" + (f" for the {caller}" if caller else "")}
            self.refused(name, st, out["error"])
        elif name in self.graph_tools:
            res = await self.mcp.call_tool(name, args)
            out = res.structured_content or {"error": (res.content[0].text if res.content else "empty MCP result")}
        elif name in datatools.TOOLS:
            out = datatools.TOOLS[name](**args)
        elif name in self.run.workflow:
            out = self.run.workflow[name](**args)
        else:
            out = {"error": f"unknown tool {name!r}"}
        self.calls += 1
        if isinstance(out, dict) and out.get("tool_call_id"):
            self.made.setdefault(caller or "crew", []).append(out["tool_call_id"])
        self.log.append({"stage": st.value, "tool": name, "args": args, "caller": caller,
                         "error": out.get("error") if isinstance(out, dict) else None})
        return out

    def take(self, caller: str | None = None) -> list[str]:
        """The ToolCall ids `caller` made since the last take (a specialist links them with MADE). Without a caller:
        every call that is not a specialist's (the crew step's own calls, and the lead's model calls)."""
        if caller is not None:
            return self.made.pop(caller, [])
        keys = [k for k in self.made if not k.endswith(" specialist")]
        return [i for k in keys for i in self.made.pop(k)]

    def refused(self, name: str, st: Stage, error: str) -> None:
        log.warning("run %s: refused %s in %s: %s", self.run.run_id, name, st.value, error)
        self.refusals += 1
        writes.record_refused_call(self.run.g(), run=self.run.run_id, tenant=self.run.tenant,
                                   tc_id=f"{self.run.run_id}-refused{self.refusals:03d}-{uuid.uuid4().hex[:4]}",
                                   tool=name, stage=st.value, error=error)


# ---------------------------------------------------------------------------------------------
# run state + workflow tools (the only tools that change incident state; validated in code)
# ---------------------------------------------------------------------------------------------
class RunState:
    def __init__(self, tenant: str, graph: str, run_id: str, incident_id: str, onset_ms: int, symptoms: list[str],
                 window_min: int | None = None, oncall_home: str | None = None, oncall_external: bool = False):
        self.tenant, self.graph, self.run_id, self.inc = tenant, graph, run_id, incident_id
        # trusted run (security review): its pages may leave the in-app pager and a standing contract may act for it.
        # False for an anonymous public-demo run: in-app pages only, and no contract is ever considered
        self.oncall_external = bool(oncall_external)
        # on-call (M19): where standing contracts live (the tenant graph for API runs). None = paging off (benches,
        # CLI and eval clean rooms keep their recorded behaviour; nothing is paged and no contract can apply)
        self.oncall_home = oncall_home
        self.paged: dict | None = None
        self.onset_ms, self.symptoms = onset_ms, symptoms
        self.gate = Gate(tenant, run_id, incident_id, graph, window_min)
        self.swept: list[dict] | None = None
        self.attempts = 0
        self.max_attempts = int(weights()["gate"]["max_attempts"])
        self.result: GateResult | None = None
        self.no_incident: GateResult | None = None
        self.finished = False
        self.summary = ""
        self.workflow: dict[str, Callable[..., dict]] = {
            "record_hypothesis": self.record_hypothesis, "update_hypothesis": self.update_hypothesis,
            "confirm_root_cause": self.confirm_root_cause, "declare_no_incident": self.declare_no_incident,
            "finish": self.finish, "propose_repair": self.propose_repair,
        }
        self.repair_proposal: dict | None = None

    def g(self):
        return gclient.engine().select_graph(self.graph)

    def stage(self, s: Stage, note: str = "") -> None:
        writes.advance_stage(self.g(), inc=self.inc, run=self.run_id, stage=s.value, ord_=ordinal(s), note=note,
                             force=s in (Stage.NO_INCIDENT, Stage.UNKNOWN_ESCALATED, Stage.FAILED))

    # --- workflow tools -----------------------------------------------------------------------
    def propose_repair(self, file: str, new_content: str, reasoning: str) -> dict:
        """Data incidents (live mode): propose the full new content of ONE allowlisted pipeline transform. It is
        only a proposal: it becomes the data_repair option after the gate, a human approves the exact diff, and
        the warehouse rebuild + invariants + KPI decide whether it worked."""
        from .. import repair

        try:
            patch = repair.propose_patch(file, new_content, reasoning)
        except (ValueError, FileNotFoundError) as e:
            return {"error": f"rejected: {e}"}
        self.repair_proposal = {"file": file, "new_content": new_content, "reasoning": reasoning[:500]}
        return {"accepted_as_proposal": True, "diff": patch.diff[:4000]}

    def record_hypothesis(self, cause_id: str, reason: str = "") -> dict:
        """Register a candidate cause (a change id from a tool result)."""
        try:
            writes.upsert_hypothesis(self.g(), inc=self.inc, hid=f"hyp-{self.inc}-{cause_id}", cause=cause_id,
                                     status="open", reason=reason, origin="investigator")
        except writes.WriteError as e:
            return {"error": str(e)}
        return {"ok": True, "hypothesis_id": f"hyp-{self.inc}-{cause_id}"}

    def update_hypothesis(self, cause_id: str, status: str, evidence_ids: list[str], reason: str = "") -> dict:
        """Mark a hypothesis unresolved (which can only lower the gate's confidence). Eliminating a competitor is not
        the investigator's to do: the deterministic competitor sweep and the gate eliminate a change only when
        FalkorDB shows it has no causal path (G2) or cannot carry the impact (G5). A model that could eliminate a
        rival with any evidence id would move G6, so the model proposes and the graph decides."""
        if status == "eliminated":
            return {"error": "eliminating a competitor is the gate's: it happens only when FalkorDB shows no causal path "
                             "(G2) or not enough flow (G5). Record what you measured; mark it 'unresolved' if you "
                             "believe it cannot be ruled out; confirm_root_cause lets the gate decide."}
        if status != "unresolved":
            return {"error": "status must be unresolved (confirmation and elimination happen only via the gate)"}
        writes.upsert_hypothesis(self.g(), inc=self.inc, hid=f"hyp-{self.inc}-{cause_id}", cause=cause_id,
                                 status=status, reason=reason, refutes=[], origin="investigator")
        return {"ok": True}

    def confirm_root_cause(self, cause_id: str, evidence_ids: list[str]) -> dict:
        """Ask the Evidence Gate to accept a cause. The gate decides; rejections explain what failed."""
        if self.swept is None:
            self.swept = [v.__dict__ for v in self.gate.sweep()]
        verdict = next((v for v in self.swept if v["change"] == cause_id), None)
        if verdict and verdict["status"] == "eliminated":
            # already rejected (and recorded as a GateRun) by the deterministic competitor sweep: no attempt spent
            return {"accepted": False, "confident": False, "rejected_by": "competitor sweep",
                    "report": f"REJECTED {cause_id} by the competitor sweep: {verdict['reason']}",
                    "attempts_left": self.max_attempts - self.attempts}
        if self.attempts >= self.max_attempts:
            return {"error": f"gate attempt budget ({self.max_attempts}) exhausted; finish with an inferred report"}
        self.attempts += 1
        res = self.gate.confirm(cause_id, list(evidence_ids), attempt=self.attempts)
        if res.passed and (self.result is None or (res.confident and not self.result.confident)):
            self.result = res
        return {"accepted": res.passed, "confident": res.confident, "gate_run_id": res.gate_run_id,
                "report": summarize(res), "attempts_left": self.max_attempts - self.attempts}

    def declare_no_incident(self, evidence_ids: list[str]) -> dict:
        """Ask the gate to accept 'no incident' (needs normal measurements + a complete negative path proof)."""
        res = self.gate.declare_no_incident(list(evidence_ids))
        if res.passed:
            self.no_incident = res
            self.finished = True
        return {"accepted": res.passed, "report": summarize(res)}

    def finish(self, summary: str) -> dict:
        """End the investigation with a short summary (the report is generated from the graph)."""
        self.summary, self.finished = summary[:4000], True
        return {"ok": True}


# ---------------------------------------------------------------------------------------------
# investigators
# ---------------------------------------------------------------------------------------------
class Investigator(Protocol):
    name: str

    async def investigate(self, box: ToolBox, run: RunState, packet: dict) -> dict: ...


class BaselineInvestigator:
    """Deterministic, rule-based investigator (keyless). Measures what the graph says can be measured in
    the symptom's scope, then proposes suspects in score order. It knows nothing incident-specific."""

    name = "baseline-policy (deterministic, no LLM)"

    async def investigate(self, box: ToolBox, run: RunState, packet: dict) -> dict:
        # the five specialists in parallel (claimed work items, typed contracts recorded on the run's Tasks)
        reports = await specialists.dispatch(box, run, packet)
        # cite the measurements they recorded (what G4/G5 and the no-incident proof read), then let the gate decide
        evidence = specialists.measurement_evidence(reports)
        for s in packet["suspects"]:
            out = await box.call("confirm_root_cause", {"cause_id": s["id"], "evidence_ids": evidence})
            if out.get("accepted"):
                break
            if "error" in out:
                break
        if run.result is None:
            await box.call("declare_no_incident", {"evidence_ids": evidence})
        await box.call("finish", {"summary": "deterministic baseline investigation"})
        return {"evidence": evidence, "specialists": {r: d.summary() for r, d in reports.items()}}


class LLMInvestigator:
    """Anthropic tool-use loop over the investigation whitelist. The model suggests; the gate decides."""

    def __init__(self, model: str | None = None, max_turns: int = 30):
        self.model = model or settings.anthropic_model
        self.max_turns = max_turns
        self.name = f"anthropic:{self.model}"
        self.usage = {"input_tokens": 0, "output_tokens": 0, "turns": 0}
        self.offered: list[list[str]] = []  # the tool list of each model call (per-stage whitelist, for tests/trace)

    async def investigate(self, box: ToolBox, run: RunState, packet: dict) -> dict:
        from anthropic import Anthropic

        from .prompts_v2 import SYSTEM_PROMPT

        api = Anthropic(api_key=settings.anthropic_api_key, max_retries=4)
        # specialists first (parallel, typed contracts); the model reads their contracts, not their prose
        reports = await specialists.dispatch(box, run, packet)
        spec = {r: d.summary() for r, d in reports.items()}
        packet = {**packet, "specialists": spec}
        messages: list[dict] = [{"role": "user", "content": "INCIDENT CONTEXT (from the graph):\n" + json.dumps(packet, default=str)[:30000]}]
        for _ in range(self.max_turns):
            if run.finished:
                break
            # per-call whitelist: recomputed from the stage the investigation is in for EVERY model call
            offered = phases.llm_toolset(box.stage)
            tools = tool_schemas(box, offered)
            self.offered.append(list(offered))
            # no sampling parameters (current models reject them); thinking is always on and counts against
            # max_tokens, so the turn gets room; effort is explicit because its default differs by model
            resp = api.messages.create(model=self.model, max_tokens=16000, output_config={"effort": "medium"},
                                       system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                                       tools=tools, messages=messages)
            self.usage["input_tokens"] += resp.usage.input_tokens
            self.usage["output_tokens"] += resp.usage.output_tokens
            self.usage["turns"] += 1
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                messages.append({"role": "user", "content": "Continue with tool calls; end with finish(...)."})
                continue
            results = []
            for u in uses:
                out = await box.call(u.name, dict(u.input or {}), only=offered, caller="model")
                results.append({"type": "tool_result", "tool_use_id": u.id,
                                "content": json.dumps(out, default=str)[:9000]})
                # GATE is reached only when the gate accepts with confidence; from then on the model is offered
                # only the gate's tools (no more evidence gathering for an accepted cause)
                if u.name == "confirm_root_cause" and run.result is not None and run.result.passed and run.result.confident:
                    box.stage = Stage.GATE
            messages.append({"role": "user", "content": results})
        return {"usage": self.usage, "specialists": spec}


def tool_schemas(box: ToolBox, names: list[str]) -> list[dict]:
    out = []
    for n in names:
        if n in box.graph_tools:
            t = box.graph_tools[n]
            out.append({"name": n, "description": t["description"][:900], "input_schema": t["input_schema"]})
            continue
        fn = datatools.TOOLS.get(n) or box.run.workflow.get(n)
        if fn is None:
            continue
        out.append({"name": n, "description": (inspect.getdoc(fn) or n)[:900], "input_schema": _schema(fn)})
    return out


def _schema(fn: Callable) -> dict:
    sig = inspect.signature(inspect.unwrap(fn))
    fields = {}
    for p in sig.parameters.values():
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else Any
        if isinstance(ann, str):
            ann = {"str": str, "int": int, "float": float, "list[str]": list[str], "str | None": str | None}.get(ann, Any)
        fields[p.name] = (ann, ... if p.default is inspect.Parameter.empty else p.default)
    model = create_model(f"{fn.__name__}_args", **fields)
    s = model.model_json_schema()
    s.pop("title", None)
    return s


# ---------------------------------------------------------------------------------------------
# after the gate: contain → route → plan → AWAITING_APPROVAL (deterministic, graph-backed)
# ---------------------------------------------------------------------------------------------
async def infer_upstream(box: ToolBox, run: RunState, scope: list[dict], symptoms: list[str], onset_ms: int,
                         window_min: int) -> dict | None:
    """Abstention path (S12): no change explains the symptom. Measure the symptom's upstream services/datastores;
    the graph picks the upstream-most anomalous node no change touched (Q-INFER-1). It is reported as INFERRED
    (confident=false); the gate never confirms it, but containment around it can still be offered."""
    anomalous = set()
    for n in [n for n in scope if n.get("label") in ("Service", "Datastore") and (n.get("hops") or 9) <= 3][:12]:
        m = await box.call("metric_window", {"target_id": n["id"], "onset_ms": onset_ms})
        if m.get("anomalous"):
            anomalous.add(n["id"])
    for s in symptoms:
        anomalous.add(s)
    roots = RO(run.tenant, run.graph).run("Q-INFER-1", {"anomalous": sorted(anomalous), "symptoms": list(symptoms),
                                                        "since": onset_ms - window_min * 60_000}).rows
    if len(roots) != 1:  # none, or ambiguous: do not guess
        return None
    root = roots[0]["id"]
    path = await box.call("causal_paths", {"from_id": root, "to_id": symptoms[0]})
    if not path.get("rows"):
        return None
    writes.upsert_hypothesis(run.g(), inc=run.inc, hid=f"hyp-{run.inc}-{root}", cause=root, status="unresolved", score=0.0,
                             reason=f"inferred: {root} is the upstream-most anomalous node and no change in the window "
                                    f"touched it (no change-based cause; not confirmed)", origin="code")
    return {"id": root, "chain": path["rows"][0]["chain"], "anomalous": sorted(anomalous),
            "evidence_id": path.get("evidence_id")}


def obligation_urgency(clock: dict) -> dict:
    """The escalation's urgency from the obligation clock's verdict (computed in the tool from template numbers and
    weights.yaml). A clock that failed is said out loud (urgent None = unknown), never read as "not urgent"."""
    if "error" in clock:
        return {"urgent": None, "reason": f"obligation clock unavailable: {clock['error']}", "page_within_min": None,
                "breach": None, "evidence_id": None}
    u = clock.get("urgent")  # None = unknown (every SLO unmeasured): kept as None, never read as "not urgent"
    return {"urgent": None if u is None else bool(u), "reason": clock.get("reason", ""),
            "page_within_min": clock.get("page_within_min"), "breach": clock.get("breach"),
            "evidence_id": clock.get("evidence_id")}


def protect_entries(prot, target: str) -> tuple[list[str], str | None]:
    """The entry services containment protects (Q-PROTECT-1 rows: ranked tier-1 first, then revenue path, each row
    carrying the reachable total and its tier-1 count). When more are reachable than one read returns, the plan
    protects the top-ranked ones and SAYS that more exist. It fails loudly only when the cap would drop a tier-1
    entry (a cut that leaves one unprotected must never look complete)."""
    rows = prot.rows
    total = int(rows[0]["total"]) if rows else 0
    tier1 = int(rows[0]["tier1"] or 0) if rows else 0
    entry = [r["id"] for r in rows]
    if prot.truncated or total > len(entry):
        kept1 = sum(1 for r in rows if r.get("tier") == 1)
        if tier1 > kept1:
            raise RuntimeError(f"Q-PROTECT-1: {tier1} tier-1 entry services reachable from {target}, more than one "
                               f"read protects ({kept1} of {len(entry)} kept); refusing a partial protected set")
        return entry, (f"{total} entry services reachable from {target}: protecting the {len(entry)} ranked first "
                       f"(all {tier1} tier-1, then the revenue path); {total - len(entry)} more are not in the cut's "
                       "protected set (Q-PROTECT-1)")
    return entry, None


async def propose_measured_repair(box: ToolBox, run: RunState, res: GateResult, shift: "crew.Shift | None" = None) -> dict | None:
    """T1: a keyless run proposes the data repair its own measurements support, for a gate-confirmed data cutover.
    Every read is a tool call with its Cypher receipt in the run: change_details says the cause is a data cutover;
    repair_targets (Q-REPAIR-TARGETS) joins the row-share measurements this run recorded anomalous to the Transform
    the lineage graph says WRITES each table, nearest the cause first along the proof path; unit_shift_check asks
    the warehouse whether that column's anomaly is one segment's unit shift (recorded as Evidence); read_transform
    fetches the SQL; agent/unit_shift.scoped_fix wraps the output column in a CASE scoped to that segment, and the
    same propose_repair workflow tool a model uses records it. It only enables the data_repair option: a human
    approves the exact diff, and the rebuild, the invariant suite and the KPI decide whether it worked. No model,
    no scenario text; the reasoning cites every evidence id."""
    from . import unit_shift

    detail = await box.call("change_details", {"deploy_id": res.cause_id})
    if detail.get("error") or not detail.get("rows") or detail["rows"][0].get("kind") != "data_cutover":
        return None
    targets = await box.call("repair_targets", {"chain": list(res.chain or [])[:20]})
    if targets.get("error"):
        log.warning("run %s: repair_targets: %s", run.run_id, targets["error"])
        return None
    for m in targets.get("rows") or []:   # engine order: the anomalous table nearest the cause first
        try:
            day = json.loads(m.get("params") or "{}").get("day")
        except ValueError:
            day = None
        column = m["column"].rsplit(".", 1)[-1]
        if not day:
            continue
        chk = await box.call("unit_shift_check", {"table": m["table"], "column": column, "day": day})
        hit = chk.get("shift") if not chk.get("error") else None
        if not hit:
            continue
        src = await box.call("read_transform", {"name": m["transform"]})
        if src.get("error"):
            continue
        new = unit_shift.scoped_fix(src["sql"], column, hit["segment"], hit["value"], hit["power"],
                                    since_day=hit["since_day"] if hit.get("existed_before") else None,
                                    ts_expr=chk.get("time_column"))
        if new is None:
            log.info("run %s: %s defines %s in a shape the scoped fix does not rewrite", run.run_id, src["file"], column)
            continue
        why = unit_shift.explain(hit, m["table"], column, src["file"],
                                 [m["evidence"], targets["evidence_id"], chk["evidence_id"], src["evidence_id"]],
                                 dated="TIMESTAMP '" in new)
        out = run.propose_repair(file=src["file"], new_content=new, reasoning=why)
        if out.get("error"):
            log.warning("run %s: measured repair refused: %s", run.run_id, out["error"])
            continue
        if shift:
            shift.note(f"measured repair: {src['file']} scoped to {hit['segment']} = {hit['value']!r} (10^{hit['power']})")
        return {"file": src["file"], "table": m["table"], "column": column, "shift": hit, "evidence": chk["evidence_id"]}
    return None


async def post_gate(box: ToolBox, run: RunState, res: GateResult | None, onset_ms: int, target: str | None = None,
                    symptoms: list[str] | None = None, shift: "crew.Shift | None" = None) -> dict:
    from ..actions import act
    from ..actions import github as gh

    cause_id = res.cause_id if res is not None else None
    change = (RO(run.tenant, run.graph).run("Q-CHANGE-1", {"id": cause_id}).rows or [{"target": cause_id, "at": None}])[0] \
        if cause_id else {"target": target, "at": None}
    target = target or change["target"]
    entry, protect_note = protect_entries(RO(run.tenant, run.graph).run("Q-PROTECT-1", {"target": target}), target)
    blast = {r["id"]: r for r in (await box.call("blast_radius", {"id": target}, stage=Stage.BLAST)).get("rows", [])}
    protect = entry + sorted(i for i, r in blast.items() if r.get("label") == "KPI")
    # CONTAIN: min-cut between the failing component and what must be protected, tried on a GRAPH.COPY branch
    box.stage = Stage.CONTAIN
    run.stage(Stage.CONTAIN, note=protect_note or "")  # a capped protected set is said in the plan's timeline
    if shift:
        shift.begin("containment", Stage.CONTAIN)
    # algo.WCC first: if the failing component cannot reach anything protected, there is nothing to cut
    conn = await box.call("connectivity_check", {"target_id": target, "protect_ids": protect})
    if "error" in conn:
        raise RuntimeError(f"connectivity_check failed: {conn['error']}")
    linked = bool(conn.get("linked"))  # decided by the WCC query
    cut = await box.call("containment_cut", {"failing_id": target, "protect_ids": protect}) if linked else \
        {"rows": [], "max_flow": 0.0, "note": "WCC: failing component is not connected to anything protected"}
    cut_rows = cut.get("rows", [])
    keep = [r["id"] for r in RO(run.tenant, run.graph).run("Q-KEEP-1", {"exclude": [target] + protect}).rows]
    wi = await box.call("whatif", {"failing_id": target, "cut_edges": [[c["u"], c["v"]] for c in cut_rows],
                                   "protect_ids": protect, "keep_connected_ids": keep}) if cut_rows else {}
    # FUTURES: every containment candidate on its own GRAPH.COPY branch (each single min-cut edge, the whole cut,
    # removing the origin's fault, changing nothing), each predicted back in band or not by VERIFY's own rule
    # (Q-FUTURE-1: the measured excess × path transfer over what the candidate leaves). build_options attaches each
    # option's future, says it in the reason and orders by it; verification later records whether it came true.
    # the whole cut, removal and no change first (a plan always shows them); every single edge after them. Caps are
    # the tool's: what it cannot simulate it lists as "unknown" with the reason, never drops
    cands = ([{"key": "min_cut", "cut_edges": [[e["u"], e["v"]] for e in cut_rows]}] if len(cut_rows) > 1 else []) \
        + [{"key": "remove_origin", "removes_origin": True}, {"key": "no_change"}] \
        + [{"key": act.edge_key(e["u"], e["v"]), "cut_edges": [[e["u"], e["v"]]]} for e in cut_rows]
    fut = await box.call("futures", {"origin_id": target, "onset": onset_ms, "now": onset_ms + 10 * 60_000,
                                     "candidates": cands, "symptom_ids": list(symptoms or []),
                                     "protect_ids": protect, "keep_connected_ids": keep}) if symptoms else {}
    # ROUTE: who fixes it, bus factor, who to loop in
    if shift:
        shift.note(f"min-cut of {len(cut_rows)} edge(s) between {target} and {len(protect)} protected node(s); "
                   f"{len(cands)} option(s) tried on clean rooms")
    box.stage = Stage.ROUTE
    run.stage(Stage.ROUTE)
    if shift:
        shift.begin("dispatcher", Stage.ROUTE)
    who = await box.call("who_fixes", {"target_id": target, "now": onset_ms, "since": onset_ms - 30 * 86_400_000})
    bus = await box.call("bus_factor", {"target_id": target})
    top = [w["person"] for w in who.get("rows", [])[:3]]
    esc = await box.call("escalation_tree", {"person_ids": top}) if top else {}
    # obligation clock: which SLOs burn and which customers the failure reaches (Q-OBL-SLO / Q-OBL-CUST). It decides
    # one thing: whether this pages now (urgent) and, if so, that owners of obligated nodes are told first. It never
    # touches the gate or which cause was confirmed.
    clock = await box.call("obligation_clock", {"target_id": target, "now": onset_ms})
    urgency = obligation_urgency(clock)
    notify = await box.call("notify_set", {"target_id": target, "now": onset_ms}
                            | ({"priority_ids": clock.get("obligated") or []} if urgency["urgent"] else {}))
    # who owned it when the change shipped: after a handover, the old team holds the context (OWNED_AT history)
    owned = await box.call("owner_at", {"target_id": target, "at": int(change.get("at") or onset_ms)})
    learned_resp = None
    if run.oncall_home is not None:  # the escalation order Q-PAGE-NEXT follows: the algo.MSF tree, ranked in Cypher
        writes.record_escalation_order(run.g(), inc=run.inc, edges=esc.get("rows", []) if "error" not in esc else [],
                                       fallback=top, via="algo.MSF")
        # M21: who actually answers this component's pages (RESPONDED, recomputed from trusted acks, approvals and
        # verified fixes in the on-call home graph); the top one joins the first wave. Off for benches, CLI and evals
        from ..memory import learning

        learned_resp = await box.call("learned_responders", {"target_id": target, "now": learning.now_ms()})
    # PLAN: options from the fixed enum, then wait for a human
    if shift:
        shift.note(f"fixer {top[0] if top else 'unknown'}; bus factor {bus.get('bus_factor')}; "
                   f"{len(notify.get('rows', []))} to notify" + ("; urgent (obligations at risk)" if urgency["urgent"] else ""))
    box.stage = Stage.PLAN
    run.stage(Stage.PLAN)
    if shift:
        shift.begin("planner", Stage.PLAN)
    # the measured data repair (T1): proposed from this run's own evidence when nobody (no model) authored one
    if run.repair_proposal is None and res is not None and res.passed:
        await propose_measured_repair(box, run, res, shift)
    hub = gh.client(run.graph)
    c = act.Ctx(run.tenant, run.graph, run.inc, run.run_id)
    act.ensure_infra_repo(c, hub)
    # learned ordering (Q-REM-1): how each fix kind fared on past incidents sharing a symptom; it only reorders
    remedy = await box.call("remedy_stats", {"incident_id": run.inc})
    # M21: what the team taught it about this family (preferences, guidelines, contract suggestions), from the on-call
    # home graph; it only reorders within a predicted-future class and annotates. Off without an on-call home
    learned = None
    if run.oncall_home is not None:
        from ..memory import learning

        learned = await box.call("learned_preferences", {"family_id": target, "now": learning.now_ms()})
    options = act.build_options(c, cause=cause_id, cut=cut_rows, hub=hub, whatif={"verdict": wi.get("verdict")} if wi else None,
                                reviewers=top, remedy=remedy, futures=fut if fut and "error" not in fut else None,
                                origin=target, symptoms=list(symptoms or []),
                                learned=learned if learned is not None and "error" not in learned else None)
    if run.repair_proposal and any(o["kind"] == "data_repair" for o in options):
        rp = act.propose_data_repair(c, file=run.repair_proposal["file"], new_content=run.repair_proposal["new_content"],
                                     reasoning=run.repair_proposal["reasoning"])
        options = [{**o, "enabled": True, "args": rp, "reason": f"proposed patch to {rp['file']}: {rp['reasoning'][:200]}"}
                   if o["id"] == rp["id"] else o for o in options]
    if shift:
        shift.note(f"{len(options)} option(s), {sum(1 for o in options if o.get('enabled'))} enabled; awaiting two-step approval")
        shift.end()
    # on-call: a standing contract (only for a gate-CONFIRMED cause) or the pages; decided before the incident becomes
    # approvable, written right after it is (a page always points at an incident someone can act on)
    # an option against an ACTIVE guideline (M21) needs a human's explicit override: a standing contract never takes it
    unflagged = [o for o in options if not ((o.get("learned") or {}).get("guideline") or {}).get("needs_override")]
    match = _contract_match(run, cause_id, unflagged) if run.oncall_home is not None and run.oncall_external else (
        {"match": None, "why": "an anonymous demo run: standing contracts act only for keyed runs and alerts",
         "queries": []} if run.oncall_home is not None else None)
    note = "two-step approval required: choose an option, then approve its plan hash"
    if match and match.get("match"):
        note = (f"standing contract {match['match']['id']} covers {match['match']['option_text']}: it runs without paging "
                "a human (verification still runs; anything but APPLIED pages one at once)")
    # last: the incident only becomes approvable once every option exists in the graph
    run.stage(Stage.AWAITING_APPROVAL, note=note)
    if run.oncall_home is not None:
        run.paged = _page_after_plan(run, cause_id=cause_id, target=target, who=who, notify=notify, urgency=urgency,
                                     match=match, change=change, learned_resp=learned_resp)
    fix_history = RO(run.tenant, run.graph).run("Q-MEM-5", {"inc": run.inc}).rows
    return {"fix_history": fix_history, "target": target, "protect": protect, "protect_note": protect_note,
            "cut": cut_rows, "max_flow": cut.get("max_flow"),
            "whatif": {k: wi.get(k) for k in ("verdict",)} | ((wi.get("rows") or [{}])[0] if wi else {}),
            "futures": {"rows": fut.get("rows", []), "evidence_id": fut.get("evidence_id"), "error": fut.get("error")}
                       if fut else None,
            "who_fixes": who.get("rows", [])[:5], "bus_factor": bus.get("bus_factor"),
            "top_contributor_inactive": bus.get("top_contributor_inactive"), "escalation": esc.get("rows", []),
            "notify": notify.get("rows", []),
            "urgency": urgency,
            "obligations": {k: clock.get(k) for k in ("customers", "revenue_at_risk", "customers_reached", "breach",
                                                      "evidence_id", "error")} | {"slos": clock.get("rows", [])},
            "owner_at_change": {k: owned.get(k) for k in ("owner_then", "owner_now", "changed_hands")}
                               | {"knew_it_then": [p["person"] for p in owned.get("knew_it_then") or []][:5],
                                  "at": int(change.get("at") or onset_ms)},
            "remedy": act.remedy_summary(remedy, options),
            "learned": _learned_summary(options, learned, who, learned_resp),
            "options": options, "oncall": run.paged}


def _learned_summary(options: list[dict], learned: dict | None, who: dict, resp: dict | None) -> dict:
    """What learning changed in this incident (M21): the plan (moved, flagged, suggested) and who_fixes blended with
    the learned responders (display and paging order; the recorded who_fixes ranking is unchanged)."""
    from ..memory import learning

    out = learning.plan_summary(options, learned)
    if resp is not None:
        out["responders"] = {"rows": (resp.get("rows") or [])[:5], "evidence_id": resp.get("evidence_id"),
                             "error": resp.get("error"), "first_wave": [p["person"] for p in learning.first_wave(resp)]}
        out["who_fixes_blended"] = learning.blend_who((who.get("rows") or [])[:10] if "error" not in who else [], resp)[:5]
    return out


def _contract_match(run: RunState, cause_id: str | None, options: list[dict]) -> dict:
    """Does a standing contract in the on-call home graph cover this plan? Never without a gate-CONFIRMED cause
    (post_gate gets `cause_id` only from a confident gate pass; an inferred origin passes None)."""
    from ..actions import contracts

    family = contracts.family_of(RO(run.tenant, run.graph), run.inc) if cause_id else None
    return contracts.match_plan(tenant=run.tenant, home=run.oncall_home, family=family, options=options)


def _page_after_plan(run: RunState, *, cause_id: str | None, target: str, who: dict, notify: dict, urgency: dict,
                     match: dict | None, change: dict, learned_resp: dict | None = None) -> dict:
    """Page the owner team's on-call for the failing component and the on-call of every team that owns something in
    its blast radius (who_fixes / notify_set, recorded above), urgent unless the obligation clock says otherwise. With
    a standing contract the same people get an informational notice instead (nobody is woken). M21: the learned
    responder for the component (learned_responders, recorded above) is paged first, in addition to the rota."""
    from ..actions import oncall
    from ..memory import learning

    people = oncall.recipients(who if "error" not in who else None, notify if "error" not in notify else None, target,
                               learned=learning.first_wave({**(learned_resp or {}), "target": target})
                               if learned_resp is not None and "error" not in learned_resp else None)
    people = people or _first_of_escalation_order(run)
    urg = oncall.urgency_of(urgency.get("urgent"))
    inc_title = (RO(run.tenant, run.graph).run("Q-INC-1", {"inc": run.inc}).rows or [{}])[0].get("title") or run.inc
    cause_line = (f"The gate confirmed {cause_id} (on {target}) as the cause." if cause_id else
                  f"No cause confirmed by the gate; the inferred origin {target} is NOT confirmed.")
    if match and match.get("match"):
        m = match["match"]
        detail = (f"{cause_line} Handled under standing contract {m['id']} granted by {m['granted_by_name'] or m['granted_by']}: "
                  f"{m['option_text']} runs without waking anyone; verification still runs and anything but APPLIED "
                  "pages a human at once.")
        ids = oncall.write_pages(tenant=run.tenant, graph=run.graph, inc=run.inc, people=people, kind="contract_notice",
                                 urgency=urg, title=f"Handled under contract: {inc_title}", detail=detail)
        return {"pages": ids, "people": people, "urgency": urg, "kind": "contract_notice", "contract": m,
                "queries": match.get("queries"), "reason": urgency.get("reason")}
    detail = (f"{cause_line} {urgency.get('reason') or ''} Open the incident to approve the smallest containment."
              ).replace("  ", " ")
    ids = oncall.write_pages(tenant=run.tenant, graph=run.graph, inc=run.inc, people=people, kind="page", urgency=urg,
                             title=f"{inc_title} ({run.inc})", detail=detail)
    return {"pages": ids, "people": people, "urgency": urg, "kind": "page", "contract": None,
            "why_no_contract": (match or {}).get("why"), "queries": (match or {}).get("queries"),
            "reason": urgency.get("reason")}


def _first_of_escalation_order(run: RunState) -> list[dict]:
    """Nobody is on call for the owner team or the blast radius: page the first person of the incident's escalation
    order (Q-PAGE-NEXT), so a human is always told."""
    rows = RO(run.tenant, run.graph).run("Q-PAGE-NEXT", {"inc": run.inc}).rows
    return [{"person": rows[0]["person"], "team": "", "evidence": "",
             "reason": "nobody is on call for the failing component or its blast radius: first of the escalation order "
                       f"({rows[0]['via']})"}] if rows else []


async def page_unrouted(box: ToolBox, run: RunState, symptoms: list[str], onset_ms: int, why: str) -> dict | None:
    """An incident the gate could not route (escalated with no cause, or accepted without confidence) still pages a
    human: the on-call of each symptom component's owner team (who_fixes on the symptom, ROUTE tools), urgent, with
    the escalation order of their algo.MSF tree. Off unless the run has an on-call home."""
    from ..actions import oncall

    if run.oncall_home is None or not symptoms:
        return None
    people: list[dict] = []
    tops: list[str] = []
    for s in symptoms[:4]:
        who = await box.call("who_fixes", {"target_id": s, "now": onset_ms, "since": onset_ms - 30 * 86_400_000},
                             stage=Stage.ROUTE)
        if "error" in who:
            continue
        people += [p for p in oncall.recipients(who, None, s) if p["person"] not in {x["person"] for x in people}]
        tops += [w["person"] for w in who.get("rows", [])[:3] if w["person"] not in tops]
    if tops:
        esc = await box.call("escalation_tree", {"person_ids": tops}, stage=Stage.ROUTE)
        writes.record_escalation_order(run.g(), inc=run.inc, edges=esc.get("rows", []) if "error" not in esc else [],
                                       fallback=tops, via="algo.MSF")
    people = people or _first_of_escalation_order(run)
    if not people:
        log.error("run %s: %s has nobody on call and no escalation order: nobody could be paged", run.run_id, run.inc)
        return {"pages": [], "people": [], "urgency": "urgent", "kind": "page", "why": "no on-call found for the symptoms"}
    inc_title = (RO(run.tenant, run.graph).run("Q-INC-1", {"inc": run.inc}).rows or [{}])[0].get("title") or run.inc
    ids = oncall.write_pages(tenant=run.tenant, graph=run.graph, inc=run.inc, people=people, kind="page", urgency="urgent",
                             title=f"{inc_title} ({run.inc})", detail=f"{why} A human must look at it.")
    run.paged = {"pages": ids, "people": people, "urgency": "urgent", "kind": "page", "contract": None, "why": why}
    return run.paged


def _leave_run_note(tenant: str, run_id: str, result: RunResult, symptoms: list[str]) -> dict:
    """The run's outcome as a shared note (T2) for the next agent: a verdict when the gate confirmed a cause, a
    hand-off when it did not. About the proof chain's components and the symptoms that exist in the memory graph.
    A failure to write is reported in the result, never a failed run (a note is advisory)."""
    from ..memory import notes

    chain = list((result.gate or {}).get("chain") or [])
    if result.outcome == "CONFIRMED":
        kind = "verdict"
        text = (f"The gate confirmed {result.cause_id} as the cause of {', '.join(symptoms)} (proof path "
                f"{' → '.join(chain)}); containment planned, a human approves the fix.")
    elif result.outcome == "NOT_CONFIDENT":
        kind = "handoff"
        who = result.cause_id or (result.inferred or {}).get("id") or "a suspect"
        text = (f"Not confident about {', '.join(symptoms)}: {who} was accepted without confidence; nothing is "
                "blamed, a human decides.")
    elif result.outcome == "UNKNOWN_ESCALATED":
        kind = "handoff"
        text = f"No cause of {', '.join(symptoms)} passed the gate; escalated to a human."
    else:
        return {"skipped": result.outcome}
    try:
        out = notes.leave_note(tenant, principal=f"faultline:{run_id}", text=text, about=chain + list(symptoms),
                               kind=kind)
        return {"id": out["id"], "kind": kind, "about": out["about"]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:300], "kind": kind}


# ---------------------------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------------------------
async def run_incident(*, tenant: str, incident_id: str, onset_ms: int, symptoms: list[str],
                       investigator: Investigator, graph: str | None = None, run_id: str | None = None,
                       window_min: int | None = None, oncall_home: str | None = None,
                       oncall_external: bool = False, share_notes: bool = False) -> RunResult:
    """`oncall_home`: page humans and honour standing contracts from that graph (the on-call graph for API runs);
    None keeps paging off. `oncall_external`: a trusted run (keyed, or off the public demo): its pages may go to
    external channels and a contract may act; otherwise in-app pages only and no contract. `share_notes` (API runs;
    off in every eval arm, so their tool counts stay as pre-registered): read the shared notes other agents left near
    the symptom at RECALL (leads shown to people, never gate input) and leave this run's verdict or hand-off as a
    note at the end (agentmem_<tenant>)."""
    graph = graph or tenant_graph(tenant)
    run_id = run_id or f"run-{uuid.uuid4().hex[:10]}"
    t0 = time.perf_counter()
    window = int(window_min or weights()["gate"]["window_min"])
    run = RunState(tenant, graph, run_id, incident_id, onset_ms, symptoms, window, oncall_home=oncall_home,
                   oncall_external=oncall_external)
    if oncall_home is not None:  # the incident carries whether its pages may leave the in-app pager (deliver reads it)
        writes.set_incident_paging(run.g(), inc=incident_id, external=bool(oncall_external) or graph == oncall_home)
    result = RunResult(run_id, incident_id, graph, "FAILED", investigator=investigator.name)
    token = context.bind(tenant, run_id=run_id, graph=graph)
    result_shift: crew.Shift | None = None
    try:
        async with Client(build_server()) as mcp:
            graph_tools = {t.name: {"description": t.description or "", "input_schema": t.input_schema}
                           for t in (await mcp.list_tools()).tools}
            box = ToolBox(run, mcp, graph_tools)
            shift = crew.Shift(tenant, graph, run_id, made=box.take)
            result_shift = shift
            # RECALL (memory first): vector seed → shared-symptom confirmation, then runbooks. Recall only ORDERS
            # the investigation (w_prior is the smallest weight); the gate still decides from fresh evidence.
            box.stage = Stage.RECALL
            run.stage(Stage.RECALL)
            shift.begin("historian", Stage.RECALL)
            rec = await box.call("similar_incidents", {"incident_id": incident_id, "now": onset_ms})
            precedents = rec.get("rows", [])
            writes.record_recall(run.g(), inc=incident_id, rows=precedents)
            shared = sorted({x for p in precedents for x in p.get("shared") or []})
            runbooks = (await box.call("runbook_for", {"ids": list(symptoms) + shared})).get("rows", [])
            prior_of_target = {r["target"]: float(r["prior"]) for r in
                               RO(tenant, graph).run("Q-MEM-8", {"inc": incident_id}).rows}  # max(sim × recency), in Cypher
            result.recall = {"precedents": [p["id"] for p in precedents], "runbooks": [r["id"] for r in runbooks],
                             "prior": dict(sorted(prior_of_target.items()))}
            shift.note(f"{len(precedents)} precedent(s), {len(runbooks)} runbook(s) recalled"
                       + (f"; prior on {', '.join(sorted(prior_of_target))}" if prior_of_target else ""))
            if share_notes and symptoms:  # T2: leads other agents left near the symptom; shown, never read by the gate
                led = await box.call("recall_notes", {"focus_id": symptoms[0]})
                result.recall["leads"] = [{k: x.get(k) for k in ("id", "agent", "name", "kind", "text", "about", "hops")}
                                          for x in (led.get("rows") or [])[:5]]
                if led.get("error"):
                    result.recall["leads_error"] = led["error"]
                shift.note(f"{len(result.recall['leads'])} lead(s) other agents left near {symptoms[0]} (never evidence)")
            # LOCALIZE: what the symptoms are, their upstream scope and context
            box.stage = Stage.LOCALIZE
            run.stage(Stage.LOCALIZE)
            shift.begin("cartographer", Stage.LOCALIZE)
            symptom_nodes, scope = [], []
            for s in symptoms:
                ctx = await box.call("service_context", {"id": s, "now": onset_ms})
                symptom_nodes += ctx.get("rows", [])
                up = await box.call("upstream_scope", {"symptom_id": s})
                scope += up.get("rows", [])
            # BLAST: what breaks, ranked in code
            box.stage = Stage.BLAST
            run.stage(Stage.BLAST)
            blast = {s: (await box.call("blast_radius", {"id": s})).get("rows", [])[:15] for s in symptoms}
            choke = (await box.call("chokepoints")).get("rows", [])[:5]
            shift.note(f"{len(scope)} upstream node(s) in scope; blast radius of {len(symptoms)} symptom(s): "
                       f"{sum(len(v) for v in blast.values())} node(s); top chokepoint {choke[0]['id'] if choke else 'none'}")
            # HYPOTHESIZE: changes upstream of the symptoms in the window, scored in code
            box.stage = Stage.HYPOTHESIZE
            run.stage(Stage.HYPOTHESIZE)
            shift.begin("profiler", Stage.HYPOTHESIZE)
            scored: dict[str, Score] = {}
            target_of: dict[str, str] = {}
            for s in symptoms:
                sus = await box.call("upstream_suspects", {"symptom_id": s, "onset": onset_ms, "window_min": window})
                for r in sus.get("rows", []):
                    sc = score(cause_id=r["deploy"], hops=r["hops"], at_ms=r["at"], onset_ms=onset_ms,
                               family_prior=prior_of_target.get(r["target"], 0.0))
                    target_of[r["deploy"]] = r["target"]
                    if r["deploy"] not in scored or sc.total > scored[r["deploy"]].total:
                        scored[r["deploy"]] = sc
            await box.call("window_changes", {"onset": onset_ms, "window_min": window})
            # algo.pageRank over the symptoms' dependency neighbourhood → w_rank term (investigation order)
            neighbourhood = sorted({n["id"] for n in scope} | set(symptoms) | set(target_of.values()))
            pr = await box.call("rank_causes", {"incident_id": incident_id, "node_ids": neighbourhood})
            prn = {x["id"]: x["norm"] for x in pr.get("rows", [])}
            for c, sc in list(scored.items()):
                old = sc
                scored[c] = score(cause_id=c, hops=old.hops, at_ms=onset_ms - int((old.minutes_before_onset or 0) * 60_000),
                                  onset_ms=onset_ms, pagerank_norm=prn.get(target_of[c], 0.0),
                                  family_prior=prior_of_target.get(target_of[c], 0.0))
            suspects = [{**s.as_dict(), "target": target_of[s.id]} for s in rank(list(scored.values()))]
            for s in suspects:
                writes.upsert_hypothesis(run.g(), inc=incident_id, hid=f"hyp-{incident_id}-{s['id']}", cause=s["id"],
                                         status="open", score=s["total"], reason=f"upstream change, {s['hops']} hop(s)"
                                         + (f"; memory prior +{s['prior']} (a recalled precedent changed {s['target']})"
                                            if s["prior"] else ""),
                                         origin="code")
            result.suspects = suspects
            shift.note(f"{len(suspects)} suspect change(s) ranked in code: " + ", ".join(s["id"] for s in suspects[:4])
                       if suspects else "no change upstream of the symptoms in the window")
            # INVESTIGATE (+ GATE inside confirm_root_cause)
            box.stage = Stage.INVESTIGATE
            run.stage(Stage.INVESTIGATE)
            shift.begin("lead", Stage.INVESTIGATE)
            packet = {"incident": incident_id, "onset_ms": onset_ms, "symptoms": symptoms,
                      "symptom_nodes": symptom_nodes, "scope": scope[:60], "blast": blast, "chokepoints": choke,
                      "suspects": suspects, "window_min": window,
                      "precedents": [{k: p.get(k) for k in ("id", "title", "similarity", "recency", "fixes", "cause_targets",
                                                             "postmortem")} for p in precedents],
                      "runbooks": [{k: r.get(k) for k in ("id", "title", "source", "for_ids")} for r in runbooks],
                      "rules": "Only ids seen in tool results exist. Confirm via confirm_root_cause; the gate decides."}
            inv = await investigator.investigate(box, run, packet)
            result.usage = inv.get("usage", {}) if isinstance(inv, dict) else {}
            result.specialists = inv.get("specialists") if isinstance(inv, dict) else None
            result.tool_calls, result.gate_attempts = box.calls, run.attempts
            result.sweep = run.swept or []
            spec_done = sum(1 for v in (result.specialists or {}).values() if isinstance(v, dict) and v.get("status") == "complete")
            shift.note(f"{investigator.name}: {len(result.specialists or {})} specialist(s) dispatched, {spec_done} complete; "
                       f"{run.attempts} cause(s) put to the gate")
            # the Gatekeeper's verdict (the gate runs happened when the lead proposed causes; this records the decision)
            shift.begin("gatekeeper", Stage.GATE)
            shift.note("accepted " + run.result.cause_id + (" (confident)" if run.result.confident else " (not confident)")
                       if run.result and run.result.passed else "negative proof accepted: no incident"
                       if run.no_incident is not None else "no cause passed the gate")
            if run.result and run.result.passed:
                run.stage(Stage.GATE, note=f"cause {run.result.cause_id} accepted (confident={run.result.confident})")
                await box.call("alert_coverage", {"chain": list(run.result.chain), "since": onset_ms - window * 60_000,
                                                  "until": onset_ms + 10 * 60_000}, stage=Stage.GATE)
                # residue (advisory, after the verdict is final): measured-anomalous components the cause cannot reach
                rc = await box.call("residue_check", {"incident_id": incident_id, "cause_id": run.result.cause_id},
                                    stage=Stage.GATE)
                result.residue = {k: rc.get(k) for k in ("verdict", "k", "n", "explained", "unexplained", "summary",
                                                         "evidence_id", "error") if k in rc}
                if run.result.violations:
                    run.stage(Stage.CONTRADICTION, note="; ".join(v["decision"] for v in run.result.violations))
                result.outcome = "CONFIRMED" if run.result.confident else "NOT_CONFIDENT"
                result.cause_id, result.confident, result.gate = run.result.cause_id, run.result.confident, run.result.as_dict()
                if run.result.confident:
                    result.post_gate = await post_gate(box, run, run.result, onset_ms, symptoms=symptoms, shift=shift)
                else:  # accepted without confidence: no plan, but a human must look (on-call only)
                    await page_unrouted(box, run, symptoms, onset_ms, f"The gate accepted {run.result.cause_id} without "
                                                                      "confidence; no containment was planned.")
            elif run.no_incident is not None:
                run.stage(Stage.NO_INCIDENT, note="negative proof accepted")
                result.outcome, result.gate = "NO_INCIDENT", run.no_incident.as_dict()
            else:
                inferred = await infer_upstream(box, run, scope, symptoms, onset_ms, window)
                if inferred:  # abstain from blaming a change; contain around the inferred origin; a human decides
                    result.outcome, result.inferred = "NOT_CONFIDENT", inferred
                    run.stage(Stage.GATE, note=f"no change explains the symptom; inferred upstream origin {inferred['id']} "
                                               f"({' → '.join(inferred['chain'])}), NOT confirmed")
                    result.post_gate = await post_gate(box, run, None, onset_ms, target=inferred["id"], symptoms=symptoms,
                                                       shift=shift)
                else:
                    run.stage(Stage.UNKNOWN_ESCALATED, note="no cause accepted by the gate; escalated to a human")
                    result.outcome = "UNKNOWN_ESCALATED"
                    await page_unrouted(box, run, symptoms, onset_ms, "No cause was accepted by the gate: escalated to a "
                                                                      "human.")
        if share_notes:
            result.note = _leave_run_note(tenant, run_id, result, symptoms)
            if result.note.get("id"):
                shift.note(f"left note {result.note['id']} for other agents ({result.note['kind']})")
        shift.end()
    except Exception as e:  # fail loudly, record the failure in the graph
        if result_shift is not None:
            try:
                result_shift.end(failed=e)
            except Exception:  # noqa: BLE001 - the run's own failure is what gets reported
                pass
        leaf = e
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        import traceback

        from ..public_errors import client_text

        # the stage note and the job's error are client-visible: our own messages as they are, anything carrying the
        # engine's or the OS's text as a generic message with a request id (the detail is logged under it)
        result.error = client_text(leaf)
        result.trace = "".join(traceback.format_exception(leaf))[-3000:]
        try:
            run.stage(Stage.FAILED, note=result.error[:400])
        except Exception:
            pass
    finally:
        context.unbind(token)
    result.seconds = round(time.perf_counter() - t0, 2)
    return result


__all__ = ["run_incident", "BaselineInvestigator", "LLMInvestigator", "RunResult", "ToolBox", "RunState"]
_ = gclient
