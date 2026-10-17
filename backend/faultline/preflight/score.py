"""Preflight risk, shared by the live gate and the retroactive backtest.

`gather` reads a PR's graph facts through the RO wrapper (templates only); `score` turns them into a risk and a
verdict with `weights.yaml` (preflight section). The live MCP tool (`mcp_server.tools.preflight_change`) and the
backtest (`evals/backtest.py`) both call these two functions, so the backtest scores exactly like production.

`as_of` (epoch ms) switches the time-dependent reads to their as-of twins, so nothing after that instant leaks in:
- Q-PRE-2 → Q-PRE-2-ASOF: incidents count only if opened before `as_of`; the owning team comes from the
  OWNED_AT window covering `as_of`; runbooks must be valid at `as_of`.
- Q-ORG-BUS → Q-ORG-BUS-ASOF: commits authored before `as_of`; "active" means a team membership covering `as_of`.
Not time-versioned in the graph, so read as they are now: topology (Q-PRE-1 blast and revenue over PROPAGATES_TO,
Q-CHOKE-ALL betweenness over CALLS) and decisions (Q-DEC-1). Q-DEC-1 only fires on a PR's ChangeFacts, which
the preflight engine extracts from config diffs at review time; historical PRs carry none, so on them the decision
term is 0 by construction (the backtest reports how many PRs had any).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..agent.rules import apply_override, violated
from ..agent.weights import weights
from ..graph.ro import RO, QueryResult

TERMS = ("blast", "revenue", "betweenness", "past_incidents", "decision", "bus_factor", "uncertainty")
WEIGHT_KEY = {t: f"w_{t}" for t in TERMS}


@dataclass
class Facts:
    pr: str
    impact: QueryResult                     # Q-PRE-1 (the live tool's evidence envelope wraps this result)
    comps: list[dict]                       # Q-PRE-2 / Q-PRE-2-ASOF rows, one per changed component
    decisions: list[dict] = field(default_factory=list)       # Q-DEC-1 rows, each with "violated"
    chokepoints: dict[str, float] = field(default_factory=dict)  # Q-CHOKE-ALL id → betweenness
    bus: dict[str, int] = field(default_factory=dict)          # changed component → bus factor
    as_of: int | None = None

    @property
    def changed(self) -> list[str]:
        return sorted({c["changed"] for c in self.comps})


@dataclass
class Assessment:
    risk: float
    verdict: str
    terms: dict[str, tuple[float, str]]     # term → (value in [0, 1], why)
    parts: dict[str, float]                 # term → weighted contribution
    would: list[dict]
    changed: list[str]
    impacted: list[str]
    revenue_tier1: list[str]
    past: dict[str, list[str]]
    gaps: list[str]


def gather(ro: RO, pr: str, *, as_of: int | None = None, chokepoints: dict[str, float] | None = None) -> Facts:
    """Read everything the score needs. Returns early (no further reads) when the PR maps to no component.
    `chokepoints` lets a batch caller reuse one Q-CHOKE-ALL result (it takes no parameters)."""
    # as of a time, the topology as it was then (edges a later PR introduced are not there yet: M14 #7)
    imp = ro.run("Q-PRE-1", {"pr": pr}) if as_of is None else ro.run("Q-PRE-1-ASOF", {"pr": pr, "as_of": int(as_of)})
    comps = (ro.run("Q-PRE-2", {"pr": pr}) if as_of is None else
             ro.run("Q-PRE-2-ASOF", {"pr": pr, "as_of": int(as_of)})).rows
    f = Facts(pr=pr, impact=imp, comps=comps, as_of=as_of)
    if not f.changed:
        return f
    f.decisions = ro.run("Q-DEC-1", {"change": pr}).rows
    for d in f.decisions:
        d["violated"] = violated(d["op"], d["actual"], d["expected"])
        apply_override(d)  # the same rule as G8: an intentional override for this PR is not a violation
    if chokepoints is None:
        chokepoints = {x["id"]: float(x["score"] or 0) for x in ro.run("Q-CHOKE-ALL", {}).rows}
    f.chokepoints = chokepoints
    for c in f.changed:
        r = (ro.run("Q-ORG-BUS", {"target": c}) if as_of is None else
             ro.run("Q-ORG-BUS-ASOF", {"target": c, "as_of": int(as_of)}))
        f.bus[c] = int((r.rows or [{"bus_factor": 0}])[0]["bus_factor"] or 0)
    return f


def verdict_of(risk: float, decision_violated: bool, thresholds: dict) -> str:
    v = "block" if risk >= thresholds["block"] else ("require_review" if risk >= thresholds["require_review"] else "allow")
    return "require_review" if v == "allow" and decision_violated else v  # a contradicted decision is never "allow"


def score(f: Facts, *, without: Iterable[str] = (), overrides: dict[str, tuple[float, str]] | None = None) -> Assessment:
    """weights.yaml risk for gathered facts. `without` zeroes the named terms' weights (ablation only; the live
    tool never passes it). `overrides` replaces named terms' (value, reason) with the same weights and thresholds (a
    pre-registered backtest variant, e.g. preflight v2's max-flow exposure; the live tool never passes it).
    Requires at least one changed component (callers check `f.changed`)."""
    w = weights()["preflight"]
    off = set(without)
    if off - set(TERMS):
        raise ValueError(f"unknown preflight terms: {sorted(off - set(TERMS))}")
    changed = f.changed
    if not changed:
        raise ValueError(f"{f.pr} maps to no component: nothing to score")
    imp, comps, dec, chk, bus = f.impact.rows, f.comps, f.decisions, f.chokepoints, f.bus
    top = max(chk.values(), default=0.0) or 1.0
    impacted = sorted({r["impacted"] for r in imp} - set(changed))
    rev = [r["impacted"] for r in imp if r["revenue"] and r["impacted"] not in changed]
    rev1 = sorted({r["impacted"] for r in imp if r["revenue"] and r["tier"] == 1 and r["impacted"] not in changed})
    past = {c["changed"]: c["past_incidents"] for c in comps}
    gaps = [c["changed"] for c in comps if not c["team"] or not c["runbooks"]]
    terms = {
        "blast": (min(1.0, len(impacted) / 10), f"a failure reaches {len(impacted)} components: {', '.join(impacted[:6])}"),
        "revenue": (1.0 if rev1 else (0.5 if rev else 0.0), f"reaches revenue path: {', '.join(rev1 or sorted(set(rev))[:4])}"),
        "betweenness": (max(chk.get(c, 0.0) / top for c in changed),
                        f"chokepoint score {max(chk.get(c, 0.0) for c in changed):.1f} (top {top:.1f})"),
        "past_incidents": (min(1.0, max(len(v) for v in past.values()) / 5),
                           "changes here caused " + ", ".join(f"{len(v)} incidents ({c})" for c, v in past.items() if v)),
        "decision": (1.0 if any(d["violated"] for d in dec) else (0.5 if any(d["violated"] is None for d in dec) else 0.0),
                     "; ".join(f"violates {d['decision']} ({d['rule_key']} {d['op']} {d['expected']}, PR sets {d['actual']})"
                               for d in dec if d["violated"]) or "no active decision contradicted"),
        "bus_factor": (1.0 if min(bus.values()) <= 1 else 0.0, "bus factor " + ", ".join(f"{c}={b}" for c, b in bus.items())),
        "uncertainty": (len(gaps) / len(changed), f"missing owner or runbook: {', '.join(gaps)}" if gaps else "owners and runbooks present"),
    }
    for k, tv in (overrides or {}).items():
        if k not in terms:
            raise ValueError(f"unknown preflight term to override: {k}")
        terms[k] = tv
    parts = {k: (0.0 if k in off else float(w[WEIGHT_KEY[k]])) * v for k, (v, _) in terms.items()}
    risk = round(sum(parts.values()), 4)
    th = w["thresholds"]
    violated_any = terms["decision"][0] == 1.0 and "decision" not in off
    verdict = verdict_of(risk, violated_any, th)
    would = []
    for k, part in sorted(parts.items(), key=lambda kv: -kv[1]):
        if part <= 0:
            continue
        alt = verdict_of(risk - part, violated_any and k != "decision", th)
        if alt != verdict:
            would.append({"term": k, "verdict": alt, "if": f"{k.replace('_', ' ')} were not a factor ({terms[k][1]})"})
    return Assessment(risk, verdict, terms, parts, would, changed, impacted, rev1, past, gaps)


# ---- change freeze (M20 #6) --------------------------------------------------------------------------------------
# The instant a change-freeze window is evaluated at (epoch ms). None = the ENGINE clock (timestamp() inside
# Q-PRE-FREEZE): the product never sets it. tests/conftest.py pins it to a fixed weekday so a weekend run of the suite
# does not change verdicts that have nothing to do with a freeze; the freeze tests pass their own instants.
FREEZE_AT: int | None = None
SEVERITY = {"allow": 0, "require_review": 1, "block": 2}


def freezes(ro: RO, changed: Iterable[str], at: int | None = None) -> QueryResult:
    """Change-freeze policies in force on the changed components at `at` (Q-PRE-FREEZE: FalkorDB turns the instant
    into each policy's local wall clock and tests .dayOfWeek / .hour / .minute against its weekly window)."""
    return ro.run("Q-PRE-FREEZE", {"components": sorted(set(changed)), "at": FREEZE_AT if at is None else int(at)})


def apply_freeze(verdict: str, rows: list[dict]) -> str:
    """A freeze only ever tightens: a policy in force with effect `block` blocks; `require_review` lifts an allow. Not a
    score term (the risk and the backtest are untouched): the policy is cited, with the local time FalkorDB evaluated."""
    out = verdict
    for r in rows:
        eff = "block" if r.get("effect") == "block" else "require_review"
        if SEVERITY[eff] > SEVERITY[out]:
            out = eff
    return out


__all__ = ["Facts", "Assessment", "TERMS", "gather", "score", "verdict_of", "freezes", "apply_freeze", "FREEZE_AT"]
