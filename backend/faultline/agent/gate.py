"""Evidence Gate v2: "no path, no claim" (docs/design/scenario_numbers.md §1).

The model may PROPOSE a cause; this module DECIDES, using only read-only graph queries and numbers
computed in code. Every evaluation is written as a (:GateRun) (rejections are first-class).

Checks
  G1 grounded      cause seen in a graph result this run; cited evidence produced by this run (Q-GATE-G1)
  G2 path          algo.SPpaths cause → every primary symptom over CHANGED|GATES|PROPAGATES_TO (Q-GATE-1)
  G3 time          cause inside the window before onset; earlier upstream changes ⇒ unresolved (Q-GATE-2)
  G4 quantitative  ≥1 cited anomalous measurement ABOUT a node on the G2 chain (Q-GATE-4)
  G4 origin        that anomaly shows before the alerting symptom, unless the change is on it ⇒ else confident=false
  G5 sufficiency   joint algo.maxFlow fixpoint per independent alert (Q-GATE-3, Q-GATE-OBS)
  G6 competitors   no other open hypothesis; unresolved ones ⇒ confident=false (Q-HYP-1)
  G7 agreement     cited evidence from ≥2 independent channels ABOUT the chain ⇒ else confident=false (Q-GATE-7)
  G7 correlation   the change specialist and the code or data specialist NAME the same Deploy, which CHANGED a node of
                   the chain (specialist contracts on the run's Tasks, Q-GATE-CORR); disagreement ⇒ confident=false.
                   Both G7 checks are downgrade-only: confidence needs both, a claim never fails on them
  G8 contradiction active decisions the cause violates are attached (Q-DEC-1); never blocks
Before any confirmation the deterministic competitor sweep runs G2 + joint G5 on every change in the
window (Q-SUS-2) and every open hypothesis, so distractors are rejected on every run, whatever the
model chose to test.
"""

from __future__ import annotations

import logging

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable, Any

from ..graph import client, writes
from ..graph.errors import GraphError
from ..graph.ro import RO
from ..graph.tenant import tenant_graph
from ..mcp_server import context
from ..mcp_server import tools as T
from ..text import joined
from .weights import weights

log = logging.getLogger(__name__)

QUANT_KINDS = ("metric", "profile", "baseline_comparison", "row_share", "error_rate")
# G7 correlation: the change channel vs the artefact channels (code; data for data incidents)
CORR_ROLES = ("change", "code", "data")
ARTEFACT_ROLES = ("code", "data")


def correlate(cause: str, rows: list[dict], cause_has_code: bool = True) -> tuple[bool | None, str]:
    """G7 structural correlation over Q-GATE-CORR rows (one per specialist report of this run).
    True  = the change specialist and at least one complete code/data specialist both name the cause that way.
    False = a complete code/data specialist that could inspect the cause names other changes (or none): the channels
            disagree → confident=false. Rivals the gate eliminated still count: G7 must stay independent of the
            gate's own verdicts (review M13/M14, finding M2).
    None  = not evaluable, stated as such: no reports, the change specialist never examined the cause, no code/data
            specialist completed, or the cause has no code artefact (no commits, no diff facts: a config, flag or data
            change) and no data specialist inspected it. None is never a pass and never lowers confidence."""
    if not rows:
        return None, "no specialist reports in this run: correlation not evaluable"
    change = [r for r in rows if r["role"] == "change"]
    if not any(r["via"] for r in change):
        return None, f"the change specialist did not name {cause} via CHANGED into the chain: correlation not evaluable"
    art = [r for r in rows if r["role"] in ARTEFACT_ROLES and r["status"] == "complete"]
    if not art:
        held = sorted({r["role"] for r in rows if r["role"] in ARTEFACT_ROLES})
        return None, (f"not evaluable: no code or data specialist could inspect a change ({', '.join(held) or 'none'} "
                      f"insufficient); a strict reading would downgrade")
    agree = [r for r in art if r["via"]]
    if agree:
        return True, "; ".join(f"change and {r['role']} specialists both name {cause} (CHANGED → {', '.join(sorted(set(r['via'])))})"
                               for r in agree)
    judges = art if cause_has_code else [r for r in art if r["role"] == "data"]
    if not judges:
        return None, (f"not evaluable: {cause} has no commits or diff facts the code specialist could inspect, and no data "
                      "specialist inspected it (a config or flag change)")
    return False, "specialists disagree: change names " + cause + "; " + "; ".join(
        f"{r['role']} names {', '.join(sorted(set(r['named']))) or 'no change'}" for r in judges) + " → confident=false"


@dataclass
class Check:
    name: str
    passed: bool | None          # None = not applicable / could not be evaluated (never counts as a pass)
    detail: str
    template: str | None = None
    params: dict | None = None
    evidence_ids: list[str] = field(default_factory=list)
    downgrade_only: bool = False  # G6 unresolved / G7 / G3-earlier: lowers confidence, does not reject
    attach_only: bool = False     # G8: attached for the plan and the report; never rejects, never downgrades


@dataclass
class GateResult:
    cause_id: str
    passed: bool
    confident: bool
    checks: list[Check]
    chain: list[str] = field(default_factory=list)
    gate_run_id: str = ""
    violations: list[dict] = field(default_factory=list)

    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.passed is False and not c.downgrade_only]

    def as_dict(self) -> dict:
        return {"cause_id": self.cause_id, "passed": self.passed, "confident": self.confident, "chain": self.chain,
                "gate_run_id": self.gate_run_id, "violations": self.violations,
                "checks": [asdict(c) for c in self.checks]}


@dataclass
class Verdict:
    """Competitor sweep outcome for one change."""
    change: str
    target: str
    path: list[str]
    flow: float | None
    status: str          # eliminated | unresolved | candidate
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)  # every component the change touched (target = the first)


class Gate:
    def __init__(self, tenant: str, run_id: str, incident_id: str, graph: str | None = None,
                 window_min: int | None = None):
        self.tenant, self.run_id, self.inc = tenant, run_id, incident_id
        self.graph = graph or tenant_graph(tenant)
        self.ro = RO(tenant, self.graph)
        self.w = weights()["gate"]
        self.window_min = int(window_min or self.w["window_min"])

    # ------------------------------------------------------------------ helpers
    def _g(self):
        return client.engine().select_graph(self.graph)

    def incident(self) -> dict:
        rows = self.ro.run("Q-INC-1", {"inc": self.inc}).rows
        if not rows or rows[0]["id"] is None:
            raise GraphError(f"incident {self.inc} not found")
        return rows[0]

    def change_targets(self, cause: str) -> list[str]:
        return [r["target"] for r in self.ro.run("Q-CHANGE-1", {"id": cause}).rows] or [cause]

    def primary_symptoms(self, targets: list[str]) -> list[list[str]]:
        """Group alerting targets into independent alerts: a target another alerting target can carry an alert-worthy
        rise into (PROPAGATES_TO edges with criticality × measured excess ≥ err_abs_min, the same rule INTAKE's algo.WCC
        grouping uses) is that one's consequence. Returns [[primary, *consequences], ...]."""
        onset, iw = int(self.incident()["onset_at"]), weights()["intake"]
        since = onset - int(iw["alert_lead_min"]) * 60_000  # the onset intake window and its baseline (group_alerts)
        res = self.ro.run("Q-PRIMARY-1", {"targets": sorted(set(targets)), "since": since,
                                          "until": onset + int(iw["alert_lag_min"]) * 60_000,
                                          "base_since": since - int(iw["baseline_min"]) * 60_000,
                                          "base_until": since - int(iw["baseline_gap_min"]) * 60_000,
                                          "carry_min": float(self.w["err_abs_min"])})
        if res.truncated:
            raise GraphError("Q-PRIMARY-1 truncated: too many alerting targets to group")
        return [[r["primary"], *r["consequences"]] for r in res.rows]  # grouped in Q-PRIMARY-1

    def observed_share(self, symptom: str) -> tuple[float | None, list[str]]:
        """Baseline-corrected error share (service) or anomalous-row share (data), from evidence this run
        recorded ABOUT the symptom or its upstream scope. None = not measured (G5 cannot pass)."""
        scope = [symptom] + [r["id"] for r in self.ro.run("Q-LIN-1", {"symptom": symptom}).rows]
        rows = self.ro.run("Q-GATE-OBS", {"run": self.run_id, "ids": scope}).rows
        best, evs = None, []
        for r in rows:
            v = r["value"]
            if v is None:
                continue
            if r["kind"] == "error_rate":
                b = float(r["baseline"] or 0.0)
                share = max(0.0, (float(v) - b) / (1.0 - b)) if b < 1 else 0.0
            else:  # row_share
                share = float(v)
            if best is None or share > best:
                best, evs = share, [r["evidence"]]
        return best, evs

    def _hyp_ids_by_cause(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for h in self.ro.run("Q-HYP-1", {"inc": self.inc}).rows:
            out.setdefault(h["cause"], []).append(h["id"])
        return out

    def flow(self, sources: list[str], symptom: str) -> float:
        if not sources:
            return 0.0
        if symptom in sources:  # a change ON the symptom component can carry all of it (max flow is undefined: s = t)
            return 1.0
        # plain joint max flow: used only for "the OTHER suspects can carry it", deliberately NOT inflated by path
        # multiplicity, so an elimination never rests on an overestimate (a suspect's own upper bound, k × maxFlow,
        # comes from impact_bound)
        rows = self.ro.run("Q-GATE-3", {"sources": sources, "symptom": symptom}).rows
        return float(rows[0]["max_flow"]) if rows else 0.0

    def _write_gate_run(self, cause: str, passed: bool, confident: bool, checks: list[Check], attempt: int,
                        origin: str) -> str:
        gid = f"gr-{self.inc}-{uuid.uuid4().hex[:8]}"
        writes.record_gate_run(self._g(), inc=self.inc, gid=gid, cause=cause, passed=passed, confident=confident,
                               checks=[asdict(c) for c in checks], attempt=attempt, origin=origin)
        return gid

    # ------------------------------------------------------------------ competitor sweep
    def sweep(self, window_min: int | None = None) -> list[Verdict]:
        """Deterministic: every change in the window + every open hypothesis through G2 and joint G5.
        Writes a Hypothesis (origin=sweep) and a GateRun per competitor."""
        inc = self.incident()
        window = int(window_min or self.window_min)
        token = context.bind(self.tenant, run_id=self.run_id, graph=self.graph)
        try:
            changes = T.window_changes(onset=int(inc["onset_at"]), window_min=window)
            if "error" in changes:
                raise GraphError(changes["error"])
            if changes.get("truncated"):  # confirm() withholds confidence ("G6 sweep complete"); log it here too
                log.warning("sweep: window_changes truncated for %s; competitors beyond the limit are not checked", self.inc)
            ids = sorted({r["deploy"] for r in changes["rows"]})
            ids += sorted({h["cause"] for h in self.ro.run("Q-HYP-1", {"inc": self.inc}).rows
                           if h["status"] == "open" and h["cause"] not in ids})
            groups = self.primary_symptoms(list(inc["targets"]))
            verdicts: dict[str, Verdict] = {}
            reach: dict[str, set[str]] = {}  # change → the primary symptoms it has a causal path to
            for change in ids:
                targets = self.change_targets(change)  # all of them: G5 and the origin test use every target
                target = targets[0]
                paths = [T.causal_paths(from_id=change, to_id=g[0]) for g in groups]
                reach[change] = {g[0] for g, p in zip(groups, paths) if p.get("rows")}
                chain = next((p["rows"][0]["chain"] for p in paths if p.get("rows")), [])
                evs = [p.get("evidence_id") for p in paths if p.get("evidence_id")]
                if not chain:
                    verdicts[change] = Verdict(change, target, [], None, "eliminated",
                                               "G2: no path to any primary symptom (no path, no claim)", evs,
                                               targets=targets)
                else:
                    verdicts[change] = Verdict(change, target, chain, None, "candidate", "G2 path exists", evs,
                                               targets=targets)
            # joint G5 per independent alert group, every group judged against the SAME candidate set (the G2
            # survivors), never against what an earlier group left: a suspect is eliminated by flow only when it is
            # eliminated in EVERY group it has a path to, and all of those were measured (g5_cross_group). So the
            # verdicts do not depend on the order of the groups
            cands = {v.change: v for v in verdicts.values() if v.status == "candidate"}
            # "the others can carry it" may only lean on suspects the origin test below will NOT refute: one
            # measured in band while another is anomalous is no carrier (review M13/M14: phase order)
            pre = {r["id"]: r for r in self.ro.run("Q-GATE-ORIGIN", {"run": self.run_id,
                                                                    "ids": sorted({t for v in cands.values()
                                                                                   for t in v.targets})}).rows} if cands else {}
            refuted = {t for t, r in pre.items() if not r["anomalous"]} if any(r["anomalous"] for r in pre.values()) else set()
            # G4 upstream, strict lower bound (no slack; the upstream fault must have started first): a component whose
            # whole excess another component's own fault upstream accounts for is no carrier for G5 either
            upstream: dict[str, list[dict]] = {}
            up_ev: list[str] = []
            up_params: dict[str, dict] = {}   # target → the exact params of the call that judged it (replayable record)
            cand_targets = sorted({t for v in cands.values() for t in v.targets})
            for i in range(0, len(cand_targets), 20):   # the tool's per-call bound (IMPACT_MAX_IDS)
                up = T.upstream_explained(suspect_ids=cand_targets[i:i + 20], onset=int(inc["onset_at"]), mode="strict")
                if "error" in up:
                    raise GraphError(f"G4 upstream: {up['error']}")
                up_ev += [up["evidence_id"]] if up.get("evidence_id") else []
                up_params.update({t: up.get("params") or {} for t in cand_targets[i:i + 20]})
                for r in up["rows"]:
                    if r["u"] != r["s"]:
                        upstream.setdefault(r["s"], []).append(r)
            refuted |= set(upstream)
            measured: dict[str, dict] = {}  # primary symptom → {need, obs, bounds, eliminated: {change: (bound, joint)}}
            for g in groups:
                sym = g[0]
                obs, obs_ev = self.observed_share(sym)
                if obs is None or not cands:
                    continue  # unmeasured: no group-level elimination by flow; confirm() will demand a measurement
                need = obs * float(self.w["flow_slack"])
                bounds: dict[str, float | None] = {}
                for c, v in sorted(cands.items()):
                    single = T.impact_bound(suspect_ids=v.targets, symptom_id=sym, observed_share=obs)
                    bounds[c] = single.get("flow_share")  # None if the bound could not be computed
                    v.evidence_ids += [single.get("evidence_id")] + obs_ev
                carriers = lambda srcs, sym=sym: self.flow([x for x in srcs if x not in refuted], sym)  # noqa: E731
                elim = g5_eliminations({c: v.targets for c, v in cands.items()}, bounds, need, carriers)
                measured[sym] = {"need": need, "obs": obs, "bounds": bounds, "eliminated": {c: (b, j) for c, b, j in elim}}
            for c in g5_cross_group({c: reach[c] for c in cands}, {sym: set(m["eliminated"]) for sym, m in measured.items()}):
                v = verdicts[c]
                v.status = "eliminated"
                parts = []
                for sym in sorted(reach[c]):
                    b, joint = measured[sym]["eliminated"][c]
                    parts.append(f"max flow {b:.4f} < needed {measured[sym]['need']:.4f} (observed {measured[sym]['obs']:.4f} × "
                                 f"{self.w['flow_slack']})" + (f" to {sym}" if len(reach[c]) > 1 else "")
                                 + f"; another suspect alone can carry {joint:.4f}")
                v.flow = measured[sorted(reach[c])[0]]["bounds"][c]
                v.reason = "G5: " + "; ".join(parts)
            live = [v for v in verdicts.values() if v.status == "candidate"]
            if measured:
                # origin test: if some suspect's own component was MEASURED anomalous this run, a suspect whose own
                # component was measured IN BAND is not the origin (it has a path and capacity, but nothing broke
                # there). Run once over the G5 survivors (it does not depend on the group)
                meas = {r["id"]: r for r in self.ro.run("Q-GATE-ORIGIN", {"run": self.run_id,
                                                                         "ids": sorted({t for v in live
                                                                                        for t in v.targets})}).rows}
                hot = sorted(t for t, r in meas.items() if r["anomalous"])
                if hot:
                    for v in live:  # every target measured, none anomalous (an unmeasured target may be the origin)
                        rs = [meas.get(t) for t in v.targets]
                        if rs and all(r is not None and not r["anomalous"] for r in rs):
                            v.status = "eliminated"
                            v.reason = (f"G4 origin: {', '.join(v.targets)} measured in band this run while "
                                        f"{', '.join(hot)} is anomalous; a path and capacity alone do not make it the origin")
                            v.evidence_ids += [e for r in rs for e in r["evidence"]]
                    live = [v for v in verdicts.values() if v.status == "candidate"]
            if live:
                # G4 upstream (strict elimination; deep bench + adversarial review): computed before G5 on every G2
                # candidate (`upstream` below); applied here to the survivors
                for v in live:
                    expl = {t: next((r for r in upstream.get(t, []) if r["u"] not in v.targets), None) for t in v.targets}
                    if v.targets and all(expl.values()):
                        v.status = "eliminated"
                        v.reason = "G4 upstream: " + "; ".join(
                            f"{t}'s excess {r['s_excess']:.4f} is covered by {r['u']}'s own fault upstream, which started "
                            f"first (excess {r['u_excess']:.4f} × best-path cap×share {r['transfer']:.3f} = "
                            f"{r['carried']:.4f}, {r['hops']} hop(s))" for t, r in expl.items()) + "; not the origin"
                        v.evidence_ids += up_ev
                live = [v for v in verdicts.values() if v.status == "candidate"]
            for v in live:  # say what the flow check actually found for the survivors (not the G2 note)
                syms = [s_ for s_ in sorted(reach[v.change]) if s_ in measured] or sorted(measured)
                if not syms:
                    continue
                m = measured[syms[0]]
                v.flow = m["bounds"].get(v.change)
                if v.flow is not None:
                    v.reason = f"G5: max flow {v.flow:.4f} ≥ needed {m['need']:.4f} (observed {m['obs']:.4f} × {self.w['flow_slack']})" \
                        if v.flow >= m["need"] - 1e-12 else f"G5: max flow {v.flow:.4f} < needed {m['need']:.4f} alone"
            multi: set[str] = set()  # only jointly sufficient in some group: every one of them unresolved
            for sym, m in sorted(measured.items()):
                multi |= set(g5_jointly_sufficient({v.change: v.targets for v in live},
                                                   {v.change: m["bounds"].get(v.change) for v in live}, m["need"],
                                                   lambda srcs, sym=sym: self.flow(srcs, sym)))
            for c in sorted(multi):
                verdicts[c].status, verdicts[c].reason = "unresolved", \
                    "G5: only jointly sufficient (multi-cause) → confident=false"
            g = self._g()
            existing = self._hyp_ids_by_cause()
            for v in verdicts.values():
                status = {"eliminated": "eliminated", "unresolved": "unresolved", "candidate": "open"}[v.status]
                for hid in existing.get(v.change, [f"hyp-{self.inc}-{v.change}"]):
                    writes.upsert_hypothesis(g, inc=self.inc, hid=hid, cause=v.change, status=status, reason=v.reason,
                                             refutes=[e for e in v.evidence_ids if e] if status == "eliminated" else [],
                                             origin="sweep")
                checks = [Check("G2 path", bool(v.path), " → ".join(v.path) or v.reason, "Q-GATE-1",
                                {"cause": v.change, "symptom": groups[0][0]}, evidence_ids=[e for e in v.evidence_ids if e])]
                if v.flow is not None:
                    checks.append(Check("G5 sufficiency", not (v.status == "eliminated" and v.reason.startswith("G5")),
                                        v.reason if v.reason.startswith("G5") else f"max flow {v.flow:.4f}", "Q-GATE-3",
                                        {"sources": v.targets or [v.target], "symptom": groups[0][0]}))
                if v.reason.startswith("G4 upstream"):
                    checks.append(Check("G4 upstream", False, v.reason, "Q-GATE-UPSTREAM",
                                        up_params.get((v.targets or [v.target])[0]) or {"ids": v.targets},
                                        evidence_ids=list(up_ev)))
                self._write_gate_run(v.change, v.status == "candidate", False, checks, 0, "sweep")
            return sorted(verdicts.values(), key=lambda v: (v.status != "candidate", v.change))
        finally:
            context.unbind(token)

    # ------------------------------------------------------------------ confirm
    def confirm(self, cause_id: str, evidence_ids: list[str], attempt: int = 1) -> GateResult:
        inc = self.incident()
        token = context.bind(self.tenant, run_id=self.run_id, graph=self.graph)
        try:
            checks: list[Check] = []
            groups = self.primary_symptoms(list(inc["targets"]))
            primaries = [grp[0] for grp in groups]
            if not primaries and inc["targets"]:  # grouping found none (e.g. a carrying cycle): never pass G2/G5
                primaries = sorted(inc["targets"])  # vacuously; demand a path and flow to every symptom instead
            # G1 grounded
            g1 = self.ro.run("Q-GATE-G1", {"run": self.run_id, "ids": [cause_id], "evidence": evidence_ids}).rows[0]
            unknown_ev = sorted(set(evidence_ids) - set(g1["evidence"]))
            g1_ok = cause_id in g1["seen"] and not unknown_ev and bool(evidence_ids)
            checks.append(Check("G1 grounded", g1_ok,
                                "cause seen in a graph result this run; all cited evidence produced by this run"
                                if g1_ok else f"cause seen={cause_id in g1['seen']}; unknown evidence={unknown_ev or 'none cited'}",
                                "Q-GATE-G1", {"run": self.run_id, "ids": [cause_id], "evidence": evidence_ids}))
            # G2 path to every primary symptom
            chains, learned = {}, []
            for sym in primaries:
                p = T.causal_paths(from_id=cause_id, to_id=sym)
                chains[sym] = p["rows"][0]["chain"] if p.get("rows") else []
                learned += p.get("learned_hops") or []
            missing = [s for s, c in chains.items() if not c]
            chain = next((c for c in chains.values() if c), [])
            checks.append(Check("G2 path", not missing,
                                (" ; ".join(" → ".join(c) for c in chains.values() if c)
                                 + ("".join(f" (learned link: {x['from']} → {x['to']} from {x['incident']})" for x in learned)))
                                if not missing
                                else f"no path, no claim: {cause_id} ↛ {missing} (≤ {self.w['max_len']} hops)",
                                "Q-GATE-1", {"cause": cause_id, "symptom": primaries[0] if primaries else None}))
            # G3 time
            onset = int(inc["onset_at"])
            t = self.ro.run("Q-GATE-2", {"cause": cause_id, "onset": onset, "window_ms": self.window_min * 60_000}).rows
            g3p = {"cause": cause_id, "onset": onset, "window_ms": self.window_min * 60_000}
            if not t:
                checks.append(Check("G3 time", False, f"{cause_id} is not a change with a timestamp", "Q-GATE-2", g3p))
            else:
                checks.append(Check("G3 time", bool(t[0]["in_window"]),
                                    f"change {(onset - int(t[0]['cause_at'])) / 60_000:.1f} min before onset (window {self.window_min} min)",
                                    "Q-GATE-2", g3p))
                if t[0]["earlier_upstream_changes"]:
                    checks.append(Check("G3 earlier upstream", False,
                                        f"earlier upstream changes on the path: {t[0]['earlier_upstream_changes']}",
                                        "Q-GATE-2", g3p, downgrade_only=True))
            # G4 quantitative on the chain
            q = self.ro.run("Q-GATE-4", {"run": self.run_id, "evidence": evidence_ids, "chain": chain}).rows
            anomalous = [r for r in q if r["anomalous"]]
            checks.append(Check("G4 quantitative", bool(anomalous),
                                "; ".join(f"{r['evidence']} on {r['about']}" for r in anomalous[:4])
                                or "no cited anomalous measurement ABOUT a node on the causal chain",
                                "Q-GATE-4", {"run": self.run_id, "evidence": evidence_ids, "chain": chain},
                                evidence_ids=[r["evidence"] for r in anomalous]))
            # G4 origin (downgrade-only): the anomaly must show BEFORE the alerting symptom (on the changed component or
            # a hop after it), unless the change is on the alerting component itself. An anomaly only at the symptom
            # fits a bystander change on a healthy path as well as it fits the real origin (gate bench finding).
            # The anomaly must sit AT the changed component, or in its own data output: a data-plane node reached from
            # it without crossing another service/datastore. An anomaly on another component in between (even an
            # unchanged real origin) does not single this change out (review M13/M14). S2: the cutover's corrupt rows
            # show in the tables payment writes, while payment's error rate stays in band.
            upstream = [n for n in chain[1:] if n not in primaries]
            on_symptom = len(chain) >= 2 and chain[1] in primaries
            label = {r["id"]: r["label"] for r in self.ro.run("Q-LABELS-1", {"ids": chain[1:]}).rows}
            own = origin_scope(chain, primaries, label)
            before = [r for r in anomalous if r["about"] in own and r["about"] in upstream]
            in_band = sorted({r["about"] for r in q if r["about"] in upstream and r["anomalous"] is False})
            checks.append(Check(
                "G4 origin", True if (on_symptom or before) else False,
                ("the change is on the alerting component itself" if on_symptom else
                 "; ".join(f"{r['evidence']} on {r['about']}" for r in before[:4]) if before else
                 ("measured in band before the symptom: " + ", ".join(in_band) if in_band else
                  "nothing at the changed component or its own data output was measured anomalous") + "; the anomaly "
                 "does not single out this change (a bystander on a healthy path, or a degraded component further "
                 "along, would fit as well) → confident=false"),
                "Q-GATE-4", {"run": self.run_id, "evidence": evidence_ids, "chain": chain},
                evidence_ids=[r["evidence"] for r in before], downgrade_only=True))
            # G4 upstream, downgrade only (deep bench + adversarial review): if an anomalous component upstream could
            # carry the changed components' whole excess even under the GENEROUS upper bound, this change may be an
            # innocent look-alike downstream of the real break: not confident. An upper bound may only ever make the
            # gate more careful; the strict version is what eliminates, in the sweep
            ub = T.upstream_explained(suspect_ids=self.change_targets(cause_id)[:20], onset=int(inc["onset_at"]), mode="bound")
            ub_rows = [r for r in ub.get("rows", []) if r["u"] not in self.change_targets(cause_id)]
            checks.append(Check(
                "G4 upstream", "error" not in ub and not ub_rows,
                (f"could not be checked ({ub['error']}) → confident=false" if "error" in ub else
                 "; ".join(f"{r['s']}'s excess {r['s_excess']:.4f} could be carried from anomalous {r['u']} upstream "
                           f"(excess {r['u_excess']:.4f}, upper-bound transfer {r['transfer']:.2f})" for r in ub_rows[:3])
                 + " → it may be a look-alike downstream of the real break → confident=false" if ub_rows else
                 "no anomalous component upstream can carry the changed component's excess"),
                "Q-GATE-UPSTREAM-UB", ub.get("params") or {"ids": self.change_targets(cause_id)[:20]},
                evidence_ids=[ub["evidence_id"]] if ub.get("evidence_id") else [], downgrade_only=True))
            # G5 sufficiency per independent alert (joint with other open suspects)
            targets = self.change_targets(cause_id)
            hyps = self.ro.run("Q-HYP-1", {"inc": self.inc}).rows
            others = sorted({t for h in hyps if h["cause"] != cause_id and h["status"] in ("open", "unresolved")
                             for t in self.change_targets(h["cause"])})
            g5_parts, g5_ok, g5_ev, g5_unknown = [], True, [], False
            for sym in primaries:
                obs, obs_ev = self.observed_share(sym)
                if obs is None:
                    g5_ok = False
                    g5_parts.append(f"{sym}: impact not measured (record error_rate or anomalous_row_share evidence)")
                    continue
                need = obs * float(self.w["flow_slack"])
                single = T.impact_bound(suspect_ids=targets, symptom_id=sym, observed_share=obs)
                g5_ev += obs_ev + [single.get("evidence_id")]
                if single.get("flow_share") is None:  # the bound could not be computed: unknown, never "0 < needed"
                    g5_unknown = True
                    g5_parts.append(f"{sym}: flow bound could not be computed "
                                    f"({single.get('error') or single.get('unknown_reason') or 'no result'})")
                    continue
                f = float(single["flow_share"])
                if f >= need - 1e-12:
                    g5_parts.append(f"{sym}: max flow {f:.4f} ≥ needed {need:.4f}")
                else:
                    g5_ok = False
                    rest = self.flow(others, sym) if others else 0.0
                    joint = self.flow(targets + others, sym) if others else f
                    tail = (f"; the other suspects {others} can carry {rest:.4f}" if rest >= need - 1e-12
                            else (f"; only jointly sufficient with {others} (multi-cause)" if joint >= need - 1e-12 else ""))
                    g5_parts.append(f"{sym}: max flow {f:.4f} < needed {need:.4f}" + tail)
            checks.append(Check("G5 sufficiency", None if (g5_unknown and g5_ok) else g5_ok, "; ".join(g5_parts), "Q-GATE-3",
                                {"sources": targets, "symptom": primaries[0] if primaries else None},
                                evidence_ids=[e for e in g5_ev if e]))
            # G6 competitors. Only the graph eliminates: an elimination asserted by an investigator (a model) instead
            # of by the sweep or the gate does not count, so whatever a model proposes cannot move G6
            # A rival the gate already confirmed is a competitor too: a second cause never passes beside a first one
            open_ = sorted(h["cause"] for h in hyps if h["cause"] != cause_id and (
                h["status"] in ("open", "confirmed")
                or (h["status"] == "eliminated" and h.get("status_by") == "investigator")))
            unresolved = sorted(h["cause"] for h in hyps if h["cause"] != cause_id and h["status"] == "unresolved")
            checks.append(Check("G6 competitors", not open_,
                                f"open (or already confirmed) competitors must be eliminated or unresolved: {open_}" if open_
                                else "every competitor eliminated with evidence", "Q-HYP-1", {"inc": self.inc}))
            if unresolved:
                checks.append(Check("G6 unresolved", False, f"unresolved competitors: {unresolved} → confident=false",
                                    "Q-HYP-1", {"inc": self.inc}, downgrade_only=True))
            # the sweep saw every change in the window? A truncated change list means some competitors were never
            # checked: say so and withhold confidence, never silently (scale bench finding: limit hit above ~22k services)
            inc_row = self.incident()
            seen = T.window_changes(onset=int(inc_row["onset_at"]), window_min=self.window_min)
            if "error" in seen:  # could not re-read the window: completeness unknown, never assumed
                checks.append(Check("G6 sweep complete", False, f"the window could not be re-read ({seen['error']}): "
                                    "completeness of the sweep unknown → confident=false", None, None, downgrade_only=True))
            elif seen.get("truncated"):
                checks.append(Check("G6 sweep complete", False,
                                    f"more changes in the window than the sweep reads ({len(seen.get('rows') or [])} shown): "
                                    "some competitors were never checked → confident=false", seen.get("template"),
                                    seen.get("params"), downgrade_only=True))
            # G7 independent channels about the chain
            g7p = {"run": self.run_id, "evidence": evidence_ids + [e for e in g5_ev if e], "chain": chain}
            ch = self.ro.run("Q-GATE-7", g7p).rows
            sources = sorted({r["source"] for r in ch if r["source"]})
            checks.append(Check("G7 agreement", len(sources) >= 2,
                                f"independent channels on the chain: {joined(sources)}", "Q-GATE-7", g7p,
                                downgrade_only=True))
            # G7 structural correlation: change + code/data specialists name the same Deploy via CHANGED
            cp = {"run": self.run_id, "cause": cause_id, "chain": chain, "roles": list(CORR_ROLES)}
            corr = self.ro.run("Q-GATE-CORR", cp).rows
            art = (self.ro.run("Q-CAUSE-ART", {"cause": cause_id}).rows or [{"commits": 0, "facts": 0}])[0]
            c_ok, c_detail = correlate(cause_id, corr, cause_has_code=bool(art["commits"] or art["facts"]))
            checks.append(Check("G7 correlation", c_ok, c_detail, "Q-GATE-CORR", cp, downgrade_only=True))
            # G8 contradiction (attach, never blocks)
            violations = []
            dc = T.decision_check(change_id=cause_id)
            accepted = [r for r in dc.get("rows", []) if r.get("overridden")]  # intentional, reviewer-recorded
            for row in dc.get("rows", []):
                if row.get("violated"):
                    violations.append(row)
                    writes.record_violation(self._g(), inc=self.inc, cause=cause_id, decision=row["decision"],
                                            actual=row["actual"], expected=row["expected"])
            checks.append(Check("G8 contradiction", None if not violations else False,
                                ("; ".join(f"violates {v['decision']}: {v['rule_key']} {v['op']} {v['expected']} (actual {v['actual']})"
                                           + (f" ({v['override']['verdict']}: {v['override']['why']})" if v.get("override") else "")
                                           for v in violations) or "no active decision violated")
                                + "".join(f"; accepted deviation from {a['decision']} ({a['rule_key']} {a['actual']}): "
                                          f"marked intentional by {a['override']['by']}: {a['override']['why']}" for a in accepted)
                                + "".join(f"; reinstates {r['reversed']}, reversed by {r['head']}" for r in dc.get("reversals") or []),
                                "Q-DEC-1",
                                {"change": cause_id}, downgrade_only=True, attach_only=True))
            passed, confident = decide(checks)
            gid = self._write_gate_run(cause_id, passed, confident, checks, attempt, "confirm")
            if passed:
                for hid in self._hyp_ids_by_cause().get(cause_id, [f"hyp-{self.inc}-{cause_id}"]):
                    writes.upsert_hypothesis(self._g(), inc=self.inc, hid=hid, cause=cause_id,
                                             status="confirmed" if confident else "unresolved",
                                             reason="gate passed" + ("" if confident else " (not confident)"),
                                             supports=[e for c in checks for e in c.evidence_ids], origin="gate")
            return GateResult(cause_id, passed, confident, checks, chain, gid, violations)
        finally:
            context.unbind(token)

    # ------------------------------------------------------------------ no incident
    def declare_no_incident(self, evidence_ids: list[str], window_min: int | None = None) -> GateResult:
        """Accept NO_INCIDENT only with a three-valued negative proof: no cited measurement is anomalous,
        and no anomalous node is reachable from any change in the window (algo.SSpaths), with the
        reachability result complete (not truncated). Timeouts/unknowns ⇒ rejected (UNKNOWN), never 'safe'."""
        inc = self.incident()
        token = context.bind(self.tenant, run_id=self.run_id, graph=self.graph)
        try:
            checks = []
            g1 = self.ro.run("Q-GATE-G1", {"run": self.run_id, "ids": [], "evidence": evidence_ids}).rows[0]
            unknown_ev = sorted(set(evidence_ids) - set(g1["evidence"]))
            checks.append(Check("G1 grounded", bool(evidence_ids) and not unknown_ev,
                                f"unknown evidence: {unknown_ev}" if unknown_ev else "cited evidence produced by this run",
                                "Q-GATE-G1", {"run": self.run_id, "ids": [], "evidence": evidence_ids}))
            scope = list(inc["targets"])
            for t in list(inc["targets"]):
                scope += [r["id"] for r in self.ro.run("Q-LIN-1", {"symptom": t}).rows]
            q = self.ro.run("Q-GATE-4", {"run": self.run_id, "evidence": evidence_ids, "chain": sorted(set(scope))}).rows
            quant = [r for r in q]
            anomalous = [r["evidence"] for r in q if r["anomalous"]]
            # N0: absence of data is not absence of an anomaly. Every alerting symptom must itself be measured by cited
            # evidence; otherwise the negative proof is UNKNOWN (escalated), never "no incident" (evals/robustness.py)
            unmeasured = sorted(set(inc["targets"]) - {r["about"] for r in q})
            checks.append(Check("N0 every symptom measured", not unmeasured,
                                f"no cited measurement of symptom(s) {unmeasured}: telemetry missing, cannot prove normal"
                                if unmeasured else f"all {len(inc['targets'])} symptom(s) measured",
                                "Q-GATE-4", {"run": self.run_id, "evidence": evidence_ids, "chain": sorted(set(scope))},
                                evidence_ids=list(evidence_ids)))
            checks.append(Check("N1 measurements normal", bool(quant) and not anomalous,
                                f"anomalous cited evidence: {anomalous}" if anomalous
                                else ("no quantitative evidence cited" if not quant else f"{len(quant)} measurements in band"),
                                "Q-GATE-4", {"run": self.run_id, "evidence": evidence_ids, "chain": sorted(set(scope))},
                                evidence_ids=list(evidence_ids)))
            neg = T.reachable_from_changes(now=int(inc["onset_at"]), window_min=int(window_min or self.window_min),
                                           anomalous_ids=sorted({r["about"] for r in q if r["anomalous"]}))
            verdict = neg.get("verdict", "UNKNOWN") if "error" not in neg else "UNKNOWN"
            checks.append(Check("N2 negative path proof", verdict == "none_reachable",
                                f"no anomalous node reachable from any change in the window ({verdict})"
                                if verdict == "none_reachable" else f"negative proof {verdict}: {neg.get('error') or neg.get('rows')}",
                                "Q-NEG-1", (neg.get("params") or {}),
                                evidence_ids=[neg.get("evidence_id")] if neg.get("evidence_id") else []))
            passed = all(c.passed for c in checks)
            gid = self._write_gate_run("NO_INCIDENT", passed, passed, checks, 1, "no_incident")
            return GateResult("NO_INCIDENT", passed, passed, checks, [], gid)
        finally:
            context.unbind(token)


COMPONENT_LABELS = {"Service", "Datastore", "ExternalDependency"}


def origin_scope(chain: list[str], primaries: list[str], label: dict[str, str]) -> list[str]:
    """G4 origin: the nodes whose anomaly singles out the change on `chain` ([change, target, …, symptom]): the
    changed component itself, plus its own data output, the data-plane nodes after it before any other component or
    an alerting symptom. An anomaly on another component in between (even an unchanged real origin) does not count."""
    own = chain[1:2]
    for n in chain[2:]:
        if n in primaries or label.get(n) in COMPONENT_LABELS:
            break
        own.append(n)
    return own


def _flat(targets: str | list[str]) -> list[str]:
    return [targets] if isinstance(targets, str) else list(targets)


def g5_eliminations(candidates: dict[str, str | list[str]], bounds: dict[str, float | None], need: float,
                    joint: Callable[[list[str]], float]) -> list[tuple[str, float, float]]:
    """The joint G5 eliminations. `candidates` = change → its target(s); `bounds` = change → its own upper bound
    (k × maxFlow; None = unknown, never eliminated); `joint(targets)` = plain max flow of a set of targets.
    A suspect goes only if its own bound cannot carry `need` AND another suspect can carry it ALONE. When every suspect
    fails alone but some group of them suffices, which of them is the cause is contingent: eliminating one on the
    strength of the others depends on the order they are looked at (review: A, B, C each insufficient, any pair
    enough), so none goes and `g5_jointly_sufficient` marks them unresolved (multi-cause) instead. A suspect sufficient
    alone is never eliminated (its own bound is at least its plain flow), so the result is order-independent.
    Returns (change, its bound, the largest carrier's flow alone), lowest bound first, then id."""
    alone = {c: joint(_flat(t)) for c, t in candidates.items()}
    out: list[tuple[str, float, float]] = []
    for c in candidates:
        b = bounds.get(c)
        if b is None or b >= need - 1e-12:
            continue
        carriers = [alone[o] for o in candidates if o != c and alone[o] >= need - 1e-12]
        if carriers:
            out.append((c, b, max(carriers)))
    return sorted(out, key=lambda x: (x[1], x[0]))


def g5_cross_group(reach: dict[str, set[str]], eliminated_in: dict[str, set[str]]) -> list[str]:
    """Across independent alert groups: `reach` = change → the primary symptoms it has a causal
    path to; `eliminated_in` = MEASURED primary → the changes G5 eliminates there (each group judged against the same
    candidate set). A change is eliminated only when every primary it reaches was measured and eliminated it there:
    a suspect that explains one group is never dropped because it cannot carry another, and the result is the same
    whatever order the groups are looked at in. Sorted."""
    return sorted(c for c, syms in reach.items()
                  if syms and all(s in eliminated_in and c in eliminated_in[s] for s in syms))


def g5_jointly_sufficient(live: dict[str, str | list[str]], bounds: dict[str, float | None], need: float,
                          joint: Callable[[list[str]], float]) -> list[str]:
    """The suspects left standing that no single one can explain but all of them together can: every one is marked
    unresolved ("only jointly sufficient (multi-cause)" → confident=false), none is singled out. Empty when one suspect
    is sufficient alone, or when even all of them together cannot carry `need`."""
    if not live or any((bounds.get(c) or 0.0) >= need - 1e-12 for c in live):
        return []
    return sorted(live) if joint([t for ts in live.values() for t in _flat(ts)]) >= need - 1e-12 else []


def decide(checks: list[Check]) -> tuple[bool, bool]:
    """passed = every hard check is True (None never counts as a pass); confident = passed and no downgrade-only check
    is False. G8 is attached for the plan and never blocks or downgrades."""
    hard = [c for c in checks if not c.downgrade_only and not c.attach_only]
    passed = all(c.passed is True for c in hard)
    confident = passed and all(c.passed is not False for c in checks
                               if c.downgrade_only and not c.attach_only and c.name != "G8 contradiction")
    return passed, confident


def summarize(result: GateResult) -> str:
    """Compact, model-facing summary of a gate result (what failed and what to do next)."""
    lines = [f"{'ACCEPTED' if result.passed else 'REJECTED'} {result.cause_id} "
             f"(confident={result.confident}, gate run {result.gate_run_id})"]
    for c in result.checks:
        mark = "✓" if c.passed else ("–" if c.passed is None else ("!" if c.downgrade_only else "✗"))
        lines.append(f"  {mark} {c.name}: {c.detail}")
    return "\n".join(lines)


def to_json(result: GateResult) -> str:
    return json.dumps(result.as_dict(), default=str)


def _log_band(ratio: float | None, band: float) -> bool:
    return bool(ratio) and abs(math.log(ratio)) > math.log(band)


__all__ = ["Gate", "GateResult", "Check", "Verdict", "summarize", "to_json", "decide", "correlate", "QUANT_KINDS",
           "g5_eliminations", "g5_jointly_sufficient", "g5_cross_group"]
_ = Any
