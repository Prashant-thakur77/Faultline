"""INTAKE: which alerts are one incident (alert-storm correlation).

One intake round reads the symptom alerts that fired in a window and that no incident holds yet, and asks the graph how
they group (`group_alerts`: a scratch projection of the alerting components plus the PROPAGATES_TO edges that can carry
a failure between them, `algo.WCC`, and bounded reachability from every OPEN incident's confirmed origin). This module
only APPLIES that decision, one atomic write per step:

  * an alert the query attached to an open incident gets (:Alert)-[:DEGRADES {how:'attached', hops}]->(:Incident);
  * the remaining alerts of each component open ONE new incident (its symptoms are those alerts' targets) and are
    linked to it with DEGRADES {how:'opened'}.

Every DEGRADES edge carries the id of the group_alerts evidence item (its Cypher and params) that decided it. The round
runs under its own Run (mode 'intake'), because no incident exists yet when the grouping is decided.

Only incidents with a gate-CONFIRMED origin absorb late alerts (Q-STORM-ORIGINS). An open NOT_CONFIDENT incident
(hypothesis 'unresolved': the gate passed with a downgrade, or an inferred upstream-most root with no change) does not,
by design: its origin is not proven, and attaching would put a possibly independent fault's pages inside an incident
whose cause may be wrong, where no gate looks at them again. Leaving them unattached opens a new incident that its own
gate investigates; the worst case is a visible duplicate incident for one fault, never a fault hidden in another.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..graph import client, writes
from ..graph.errors import GraphError
from ..mcp_server import context
from ..mcp_server import tools as T
from ..text import joined
from . import crew
from .state import Stage


@dataclass
class Opened:
    """An incident this round opened: its id, run, symptom targets (sorted), alerts (first fired first) and onset (the
    round's onset, or for a later round the first alert of this incident's group)."""
    incident_id: str
    run_id: str
    symptoms: list[str]
    alerts: list[dict]
    onset_ms: int | None = None


@dataclass
class Round:
    run_id: str
    evidence_id: str | None
    opened: list[Opened] = field(default_factory=list)
    attached: dict[str, list[str]] = field(default_factory=dict)  # incident → alert ids attached this round
    groups: list[dict] = field(default_factory=list)              # the group_alerts rows, as decided by the graph


def intake_round(*, tenant: str, graph: str, since: int, until: int, onset: int | None, ids: list[tuple[str, str]],
                 title: str, report: str, round_run: str, mode: str = "scenario", embed=None,
                 stage_note: str = "") -> Round:
    """Group the open alerts in [since, until] and attach or open. `ids` = (incident id, run id) for each incident this
    round may open, in group order (the graph orders groups by first alert); more groups than ids fails loudly.
    `onset` = every new incident's onset (the onset round); None = each new incident's onset is the first alert of
    its own group (a later round: its G3 window and alert windows start at its own first page, not at the first
    round's onset). `embed(g, inc, alerts)` stores the new incident's vector (memory), if given."""
    g = client.engine().select_graph(graph)
    writes.open_aux_run(g, run=round_run, tenant=tenant, mode="intake", text=f"alerts {since}..{until}")
    token = context.bind(tenant, run_id=round_run, graph=graph)
    try:
        out = T.group_alerts(since=int(since), until=int(until))
    finally:
        context.unbind(token)
    if "error" in out:
        raise GraphError(f"group_alerts: {out['error']}")
    ev = out.get("evidence_id")
    rnd = Round(round_run, ev, groups=list(out["rows"]))
    fresh = []
    for grp in out["rows"]:
        by_inc: dict[str, list[dict]] = {}
        for a in grp["alerts"]:
            for x in a["attach"]:
                by_inc.setdefault(x["incident"], []).append({"alert": a["id"], "how": "attached", "hops": x["hops"]})
        for inc, links in sorted(by_inc.items()):
            writes.link_alerts(g, inc=inc, links=links, evidence=ev)
            rnd.attached.setdefault(inc, []).extend(x["alert"] for x in links)
        rest = [a for a in grp["alerts"] if not a["attach"]]
        if rest:
            fresh.append((grp["group"], rest))
    if len(fresh) > len(ids):
        raise GraphError(f"intake opened {len(fresh)} incident groups but only {len(ids)} incident ids were provided")
    for (k, rest), (inc, run) in zip(fresh, ids):
        targets = sorted({a["target"] for a in rest})
        inc_onset = int(onset) if onset is not None else min(int(a["fired_at"]) for a in rest)
        # a symptom's kind is the metric of the first alert that fired on its target (alerts are first-fired first)
        symptoms = [{"id": f"sym-{kind}-{t}", "kind": kind, "target": t}
                    for t in targets for kind in [next(a["metric"] for a in rest if a["target"] == t)]]
        writes.open_incident(g, inc=inc, run=run, tenant=tenant, title=title, report=report, onset=inc_onset,
                             symptoms=symptoms, models="", mode=mode)
        writes.link_alerts(g, inc=inc, links=[{"alert": a["id"], "how": "opened"} for a in rest], evidence=ev)
        if embed is not None:
            embed(g, inc, rest)
        note = f"alerts: {joined(a['id'] for a in rest)}"
        if len(out["rows"]) > 1 or rnd.attached:
            note += f"; group {k} of {len(out['rows'])} (algo.WCC, evidence {ev})"
        writes.advance_stage(g, inc=inc, run=run, stage="INTAKE", ord_=1, note=note + stage_note)
        # the crew's first step: Triage opened this incident from its group (the WCC call is the one it made)
        with crew.step(tenant=tenant, graph=graph, run_id=run, key="triage", stage=Stage.INTAKE) as st:
            st.tool_calls = [out["tool_call_id"]] if out.get("tool_call_id") else []
            st.summary = (f"opened {inc} from {len(rest)} alert(s) on {', '.join(targets)}"
                          + (f"; group {k} of {len(out['rows'])} (algo.WCC)" if len(out["rows"]) > 1 else ""))
        rnd.opened.append(Opened(inc, run, targets, rest, inc_onset))
    return rnd


__all__ = ["intake_round", "Opened", "Round"]
