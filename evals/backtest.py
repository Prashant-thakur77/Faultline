"""Retroactive preflight backtest: would the pre-deploy gate have flagged the PRs that caused past incidents, and
how many PRs would it have flagged to get there (the alert-fatigue cost)?

For every merged historical PR, the production preflight (`faultline.preflight.score.gather` + `score`, the same
functions `preflight_change` calls) is evaluated **as of the PR's `merged_at`**: past incidents count only if they
were opened before the merge, ownership, runbooks, commit counts and team membership are read as of that instant
(Q-PRE-2-ASOF, Q-ORG-BUS-ASOF). Read-only: every read goes through the RO wrapper on the golden graph; nothing is
written. A PR is *incident-causing* when its deploy CAUSED an incident in the graph's history (Q-PRE-HIST); the
labels come from the graph, never from `*.truth.json`.

Variants (same gathered facts, scored with `weights.yaml` unchanged):
- `full`              the gate as it ships;
- `no_past_incidents` the past-incidents term weighted 0: structure only (blast, revenue, betweenness, bus factor,
                      uncertainty), to show how much of the result comes from the graph's memory of incidents;
- `leaky_now`         scored on today's graph (no as-of): what the numbers would look like WITH future leakage.
                      Reported only as a contrast; it is not a result.

Honest limits: the data is synthetic. Incident causes are drawn from per-archetype component lists, so a component
that caused incidents before is, by construction, likely to cause the next one: the past-incidents term is partly
self-fulfilling here, which is why the structure-only ablation is reported next to it. Historical PRs carry no
ChangeFacts (only file touches), so the decision term (Q-DEC-1) cannot fire on them. Topology is not
time-versioned and is read as it is now. Datastore config changes that caused incidents shipped without a PR, so
they are outside this population.

    PYTHONPATH=backend uv run python -m evals.backtest [--tenant acme] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.tenant import golden_graph, tenant_graph  # noqa: E402
from faultline.preflight import score as P  # noqa: E402

TENANTS = ("acme", "globex")
VARIANTS = {"full": (), "no_past_incidents": ("past_incidents",)}
VERDICTS = ("block", "require_review", "allow")
SEGMENTS = ("all", "first_third", "last_third")
PAGE = 100  # Q-PRE-HIST's LIMIT


# ------------------------------------------------------------------ metrics (arithmetic on returned numbers)
def auroc(pos: list[float], neg: list[float]) -> float | None:
    """P(risk of a random causing PR > risk of a random other PR), ties 0.5 (Mann-Whitney)."""
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else (0.5 if p == n else 0.0) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def metrics(rows: list[dict], variant: str) -> dict:
    """rows: {causing: bool, verdict: {variant: str}, risk: {variant: float | None}}. An unscorable PR (risk None)
    keeps production's require_review verdict in the rates and is left out of AUROC."""
    n = len(rows)
    pos = [r for r in rows if r["causing"]]
    neg = [r for r in rows if not r["causing"]]
    conf = {lab: {v: sum(1 for r in grp if r["verdict"][variant] == v) for v in VERDICTS}
            for lab, grp in (("causing", pos), ("other", neg))}
    flagged = lambda grp: sum(1 for r in grp if r["verdict"][variant] != "allow")  # noqa: E731
    blocks = conf["causing"]["block"] + conf["other"]["block"]
    reviews = conf["causing"]["require_review"] + conf["other"]["require_review"]
    return {"prs": n, "causing": len(pos), "base_rate": _rate(len(pos), n),
            "catch_rate": _rate(flagged(pos), len(pos)), "block_catch_rate": _rate(conf["causing"]["block"], len(pos)),
            "block_rate": _rate(blocks, n), "review_rate": _rate(reviews, n), "flag_rate": _rate(blocks + reviews, n),
            "false_flag_rate": _rate(flagged(neg), len(neg)), "precision": _rate(flagged(pos), blocks + reviews),
            "auroc": auroc([r["risk"][variant] for r in pos if r["risk"][variant] is not None],
                           [r["risk"][variant] for r in neg if r["risk"][variant] is not None]), "confusion": conf}


def segment(rows: list[dict], lo: int, hi: int) -> dict[str, list[dict]]:
    """first / last third of the merge-time window [lo, hi]."""
    span = max(1, hi - lo)
    return {"all": rows, "first_third": [r for r in rows if r["merged_at"] < lo + span / 3],
            "last_third": [r for r in rows if r["merged_at"] >= lo + 2 * span / 3]}


# ------------------------------------------------------------------ the run (reads only)
def history(ro: RO) -> list[dict]:
    """Every merged PR in merge order (keyset pages of Q-PRE-HIST)."""
    out: list[dict] = []
    after, after_id = -1, ""
    while True:
        r = ro.run("Q-PRE-HIST", {"after": after, "after_id": after_id})
        out += r.rows
        if len(r.rows) < PAGE and not r.truncated:
            return out
        after, after_id = r.rows[-1]["merged_at"], r.rows[-1]["pr"]


def flow_exposure(tenant: str, graph: str, ro: RO, rows: list[dict], chk: dict) -> int:
    """Preflight v2 (PREREGISTRATION amendment 2026-10-13, M15 #6), a reported variant: blast = min(1, algo.maxFlow
    from the changed components into the revenue-path and tier-1 nodes) instead of a count of reached components, and
    uncertainty counts a changed component with no owner, or with neither a past incident nor a runbook. Read as of
    each merge: algo.maxFlow cannot filter edges by time, so the PRs are grouped by topology epoch (the dated calls,
    Q-TOPO-EPOCHS) and each epoch gets one GRAPH.COPY branch with the later calls dropped. Returns the epoch count."""
    import bisect
    import uuid

    from faultline.graph import writes
    from faultline.graph.tenant import eval_graph

    cuts = [int(r["at"]) for r in ro.run("Q-TOPO-EPOCHS", {}).rows]
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(bisect.bisect_right(cuts, r["merged_at"]), []).append(r)
    db = gclient.engine()
    for k, grp in sorted(groups.items()):
        branch = eval_graph(tenant, f"flow{uuid.uuid4().hex[:6]}", "flow", f"e{k}", 1)
        try:
            gcopy.copy_graph(db, graph, branch)
            writes.drop_future_edges(db.select_graph(branch), grp[0]["merged_at"])
            bro = RO(tenant, branch)
            for r in grp:
                f = P.gather(ro, r["pr"], as_of=r["merged_at"], chokepoints=chk)
                if not f.changed:
                    r["verdict"]["flow_exposure"], r["risk"]["flow_exposure"] = "require_review", None
                    continue
                fl = (bro.run("Q-PRE-FLOW", {"pr": r["pr"]}).rows or [{"flow": 0.0}])[0]["flow"] or 0.0
                gaps = [c["changed"] for c in f.comps if not c["team"] or (not c["past_incidents"] and not c["runbooks"])]
                s = P.score(f, overrides={
                    "blast": (min(1.0, float(fl)), f"max flow {float(fl):.3f} into the revenue path and tier-1 nodes"),
                    "uncertainty": (len(gaps) / len(f.changed), f"no owner, or no incident record and no runbook: {gaps}")})
                r["verdict"]["flow_exposure"], r["risk"]["flow_exposure"] = s.verdict, s.risk
        finally:
            gcopy.delete_if_exists(db, branch)
    return len(groups)


def run(tenant: str, graph: str | None = None) -> dict:
    t0 = time.perf_counter()
    if graph is None:
        graph = golden_graph(tenant) if gcopy.exists(gclient.engine(), golden_graph(tenant)) else tenant_graph(tenant)
    ro = RO(tenant, graph)
    prs = history(ro)
    if not prs:
        raise RuntimeError(f"{graph}: no merged PRs with merged_at (not seeded?)")
    chk = {x["id"]: float(x["score"] or 0) for x in ro.run("Q-CHOKE-ALL", {}).rows}  # static: one read for all PRs
    rows: list[dict] = []
    diag = {"unscorable": 0, "impact_truncated": 0, "prs_with_change_facts": 0, "decision_term_nonzero": 0,
            "self_leaks": 0, "causing_with_prior_incidents": 0}
    for p in prs:
        caused = set(p["caused"])
        row = {"pr": p["pr"], "merged_at": p["merged_at"], "causing": bool(caused), "verdict": {}, "risk": {}}
        facts = ro.run("Q-PRE-FACTS", {"pr": p["pr"]}).rows
        diag["prs_with_change_facts"] += bool(facts)
        for name, as_of in (("asof", p["merged_at"]), ("now", None)):
            f = P.gather(ro, p["pr"], as_of=as_of, chokepoints=chk)
            if not f.changed:  # production maps "cannot assess" to require_review (preflight/engine.py)
                diag["unscorable"] += name == "asof"
                for v in (VARIANTS if name == "asof" else ("leaky_now",)):
                    row["verdict"][v], row["risk"][v] = "require_review", None
                continue
            if name == "now":
                s = P.score(f)
                row["verdict"]["leaky_now"], row["risk"]["leaky_now"] = s.verdict, s.risk
                continue
            diag["impact_truncated"] += f.impact.truncated
            seen_past = {i for c in f.comps for i in c["past_incidents"]}
            diag["self_leaks"] += bool(seen_past & caused)  # must stay 0: a PR never sees the incident it caused
            diag["causing_with_prior_incidents"] += bool(caused and seen_past)
            for v, without in VARIANTS.items():
                s = P.score(f, without=without)
                row["verdict"][v], row["risk"][v] = s.verdict, s.risk
                if v == "full":
                    diag["decision_term_nonzero"] += s.terms["decision"][0] > 0
                    row["past_incidents_term"] = s.terms["past_incidents"][0]
        rows.append(row)
    diag["flow_epochs"] = flow_exposure(tenant, graph, ro, rows, chk)
    lo, hi = min(r["merged_at"] for r in rows), max(r["merged_at"] for r in rows)
    segs = segment(rows, lo, hi)
    out = {v: {seg: metrics(grp, v) for seg, grp in segs.items()} for v in (*VARIANTS, "leaky_now", "flow_exposure")}
    return {"tenant": tenant, "graph": graph, "prs": len(rows), "causing_prs": sum(r["causing"] for r in rows),
            "window_ms": [lo, hi], "variants": out, "diagnostics": diag,
            "seconds": round(time.perf_counter() - t0, 2)}


def run_all(tenants: tuple[str, ...] = TENANTS) -> dict:
    return {t: run(t) for t in tenants}


# ------------------------------------------------------------------ CLI
def _print(r: dict) -> None:
    print(f"\n{r['tenant']} ({r['graph']}): {r['prs']} merged PRs, {r['causing_prs']} incident-causing, {r['seconds']} s")
    print(f"  {'variant':<18} {'segment':<12} {'PRs':>5} {'cause':>5} {'catch':>6} {'block':>6} {'review':>6} {'flag':>6} "
          f"{'prec':>6} {'AUROC':>6}")
    for v, segs in r["variants"].items():
        for seg, m in segs.items():
            print(f"  {v:<18} {seg:<12} {m['prs']:>5} {m['causing']:>5} {m['catch_rate']!s:>6} {m['block_rate']!s:>6} "
                  f"{m['review_rate']!s:>6} {m['flag_rate']!s:>6} {m['precision']!s:>6} {m['auroc']!s:>6}")
    c = r["variants"]["full"]["all"]["confusion"]
    print(f"  confusion (full, all): causing {c['causing']}  other {c['other']}")
    print(f"  diagnostics: {r['diagnostics']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", choices=TENANTS, action="append")
    ap.add_argument("--json", type=Path, help="also write the raw result here (never evals/results/latest.json)")
    a = ap.parse_args()
    res = run_all(tuple(a.tenant or TENANTS))
    for r in res.values():
        _print(r)
    if a.json:
        if a.json.resolve().name == "latest.json":
            raise SystemExit("refusing to write latest.json: it is generated by `make eval` / `make results`")
        a.json.write_text(json.dumps(res, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
