"""Eval harness. Every trial runs on a fresh GRAPH.COPY clean room; grading reads the truth files
(here, never in the product) and the final graph state / run result.

Arms (keyless unless noted):
  N   naive recency baseline: blame the change closest to onset, from the scenario's change list as FILES (no
      graph). This is also A4's "ungated guess". Ties are scored fractionally (1/k), never by list order.
  A2  graph tools, memory OFF (golden_<t>_nomem), deterministic investigator.
  A3  graph + memory (the product), deterministic investigator.
  A4  FalkorDB OFF (FAULTLINE_DISABLE_GRAPH=true at run time): the product must confirm nothing.
  A0/A1/A3L  LLM arms (Anthropic): need ANTHROPIC_API_KEY and an approved budget; skipped with a printed note.

Product checks (not arms): S5 bad fix rejected, S6 preflight block, S9 unknown → reconciled, S10 forget flips the
answer, S13 concurrency, S14 alert storm (evals/storm.py: grouping, attach-or-open, both causes, ungrouped control),
S1b cold vs warm, the retroactive preflight backtest (evals/backtest.py), the gate bench
(evals/gate_bench.py, generated cases), the SIGKILL chaos check (evals/chaos.py) and the scale benchmark
(evals/scale.py: the recorded `make scale` run, else its reduced 1k variant).
Graph-arm trials are also graded on the truth fields beyond the cause (grade_detail: blast radius, path, violated
decisions, responder in top 3, correct fix target).

    PYTHONPATH=backend uv run python evals/harness.py --arms N,A2,A3,A4 --n 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

from faultline import scenario  # noqa: E402
from faultline.agent.loop import BaselineInvestigator  # noqa: E402
from faultline.config import settings  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402

RESULTS = ROOT / "evals" / "results"
TRUTH = ROOT / "data" / "scenarios"
SCENARIOS = ["S1", "S2", "S3", "S4D", "S4S", "S12", "S1b", "S3b"]


def truth(sid: str) -> dict:
    return json.loads((TRUTH / f"{sid}.truth.json").read_text())


def _distractors(t: dict) -> list[str]:
    d = t.get("distractors") or []
    return list(d.keys()) if isinstance(d, dict) else list(d)


def grade(sid: str, outcome: str, cause: str | None, top1: float | None = None, inferred: str | None = None) -> dict:
    t = truth(sid)
    want = t["outcome"]
    if want == "NOT_CONFIDENT":  # abstention with an inferred, unconfirmed origin (S12): never blame a change
        return {"top1": None, "outcome_correct": outcome == "NOT_CONFIDENT" and cause is None and inferred == t.get("inferred"),
                "false_blame": cause is not None, "abstention_correct": cause is None and outcome not in ("NO_INCIDENT", "FAILED")}
    if want == "NO_INCIDENT":
        return {"top1": None, "outcome_correct": outcome == "NO_INCIDENT", "false_blame": cause is not None,
                "abstention_correct": outcome == "NO_INCIDENT" and cause is None}
    hit = top1 if top1 is not None else (1.0 if cause == t["cause"] else 0.0)
    return {"top1": hit, "outcome_correct": outcome == want and cause == t["cause"],
            "false_blame": bool(cause) and cause in _distractors(t), "abstention_correct": None}


# ------------------------------------------------------------------ arms
def arm_naive(sid: str) -> dict:
    s = scenario.load(sid)
    changes = [(abs(scenario.rel_ms(c["at"], 0)), c["change"]) for c in s.get("inject", [])]
    if not changes:
        return {"outcome": "NO_INCIDENT", "cause": None, "ranking": [], **grade(sid, "NO_INCIDENT", None)}
    best = min(d for d, _ in changes)
    tied = sorted(c for d, c in changes if d == best)
    ranking = [[c, round(d / 60_000, 2)] for d, c in sorted(changes)]  # minutes from onset, closest first
    t = truth(sid)
    frac = (1.0 / len(tied) if t.get("cause") in tied else 0.0) if t["outcome"] == "CONFIRMED" else None
    cause = tied[0]
    g = grade(sid, "CONFIRMED", cause, frac)
    g["false_blame"] = any(c in _distractors(t) for c in tied) if t["outcome"] == "CONFIRMED" else True
    return {"outcome": "CONFIRMED", "cause": cause, "tied": tied, "ranking": ranking, **g, "tool_calls": 0, "seconds": 0.0}


def _graph_arm(sid: str, nomem: bool, disable: bool = False, no_g5: bool = False, investigator=None) -> dict:
    """no_g5 (arm A3-noG5, eval process only): flow_slack → 0, so every suspect with a path passes the max-flow
    sufficiency check; shows what algo.maxFlow decides. The product never runs with this."""
    t0 = time.perf_counter()
    if no_g5:
        from faultline.agent.weights import weights as _w

        saved = _w()["gate"]["flow_slack"]
        _w()["gate"]["flow_slack"] = 0.0
        try:
            return _graph_arm(sid, nomem, disable, investigator=investigator)
        finally:
            _w()["gate"]["flow_slack"] = saved
    p = scenario.prepare(sid, set_mode=True, nomem=nomem)
    from faultline.agent.loop import run_incident

    settings.faultline_disable_graph = disable
    try:
        res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                             symptoms=p.symptoms, investigator=investigator or BaselineInvestigator(), graph=p.graph,
                                             run_id=p.run_id, window_min=p.scenario.get("window_min")))
        detail = _run_detail(p, res)
    finally:
        settings.faultline_disable_graph = False
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    checks = {c["name"]: c["passed"] for c in (res.gate or {}).get("checks", [])}
    t = truth(sid)
    swept = {v["change"]: v for v in res.sweep}
    rejected = None
    if isinstance(t.get("distractors"), dict):
        rejected = all(swept.get(d, {}).get("status") == "eliminated" and swept[d]["reason"].startswith(gate)
                       for d, gate in t["distractors"].items())
    elif t.get("distractors"):
        rejected = all(swept.get(d, {}).get("status") == "eliminated" for d in t["distractors"])
    confirmed = res.outcome in ("CONFIRMED", "NOT_CONFIDENT")
    if res.outcome == "FAILED":  # nothing ran (e.g. FalkorDB off): nothing was rejected either
        rejected = None
    return {"outcome": res.outcome, "cause": res.cause_id if confirmed else None,
            **grade(sid, res.outcome, res.cause_id if confirmed else None, inferred=(res.inferred or {}).get("id")),
            "distractors_rejected": rejected, "grounded": checks.get("G1 grounded"), "tool_calls": res.tool_calls,
            "gate_attempts": res.gate_attempts, "precedents": len((res.recall or {}).get("precedents", [])),
            "seconds": round(time.perf_counter() - t0, 2), "error": res.error, "confident": res.confident,
            "usage": getattr(res, "usage", None),
            "sweep": [{"change": v["change"], "status": v["status"], "reason": v["reason"]} for v in res.sweep],
            "chain": (res.gate or {}).get("chain"), "detail": detail, **grade_detail(sid, detail, (res.gate or {}).get("chain"))}


def _run_detail(p, res) -> dict:
    """What the run produced beyond the cause, read from its result and its graph (RO templates) before the clean room
    is deleted: blast radius (the BLAST stage's recorded blast_radius result), the top 3 of who_fixes, the decisions G8
    attached, and the options the plan offered (with the edge each flag cuts, Q-FLAGS-1)."""
    from faultline.graph.ro import RO

    out: dict = {"blast": None, "who_top3": [], "violations": sorted(v["decision"] for v in (res.gate or {}).get("violations") or []),
                 "options": [], "gate_ran": bool(res.gate) and res.outcome in ("CONFIRMED", "NOT_CONFIDENT")}
    if settings.faultline_disable_graph or res.outcome == "FAILED":
        return out
    ro = RO(p.tenant, p.graph)
    row = ro.run("Q-EV-TOOL", {"run": p.run_id, "tool": "blast_radius"}).rows
    if row and row[0]["payload"]:
        out["blast"] = sorted({r["id"] for r in json.loads(row[0]["payload"]).get("rows", [])})
    pg = res.post_gate or {}
    out["who_top3"] = [w["person"] for w in (pg.get("who_fixes") or [])[:3]]
    cuts = {r["flag"]: [r["cuts_src"], r["cuts_dst"]] for r in ro.run("Q-FLAGS-1", {}).rows if r["cuts_src"]}
    out["options"] = [{"kind": o["kind"], "target": o["target"], "enabled": o["enabled"],
                       **({"cuts": cuts.get(o["target"])} if o["kind"] == "flip_flag" else {})} for o in pg.get("options") or []]
    return out


def _in_order(want: list[str], chain: list[str]) -> bool:
    it = iter(chain)
    return all(any(x == y for y in it) for x in want)


def grade_detail(sid: str, d: dict, chain: list[str] | None) -> dict:
    """The fields of the truth file beyond the cause. Graded only when the truth file has the field; a run that
    produced nothing for it (e.g. FalkorDB off) is a miss, never skipped. Correct target: the FIRST enabled
    production-changing option (what the plan offers first) rolls back / repairs a listed change or flips a listed
    flag; a plan with no enabled production-changing option is `fix_offered: false` and is not counted in the rate."""
    t = truth(sid)
    g: dict = {}
    if t.get("blast_radius") is not None:
        want, got = set(t["blast_radius"]), set(d.get("blast") or [])
        g["blast_precision"] = round(len(want & got) / len(got), 4) if got else 0.0
        g["blast_recall"] = round(len(want & got) / len(want), 4) if want else 1.0
    if t.get("path_contains"):
        g["path_contains_ok"] = _in_order(t["path_contains"], chain or [])
    if "violates" in t:  # only a gate that ran can say "no decision violated"
        g["violates_ok"] = bool(d.get("gate_ran")) and sorted(d.get("violations") or []) == sorted(t["violates"])
    if t.get("owners_any_of"):
        g["responder_top3"] = any(p_ in t["owners_any_of"] for p_ in d.get("who_top3") or [])
    if t.get("fix_targets_any_of"):
        fixes = [o for o in d.get("options") or [] if o["enabled"] and o["kind"] != "open_issue"]
        g["fix_offered"] = bool(fixes)
        g["target_correct"] = (fixes[0]["target"] in t["fix_targets_any_of"]) if fixes else None
    return g


def arm_vector(sid: str) -> dict:
    """V (comparator, keyless): "embeddings find it". Embed the window's change titles with the same local model,
    rank them by cosine distance to the incident's own vector INSIDE FalkorDB (vec.cosineDistance), blame the
    nearest. No graph traversal, no gate; like N it cannot abstain."""
    from faultline.graph import writes
    from faultline.graph.ro import RO
    from faultline.memory.embed import embed

    t0 = time.perf_counter()
    p = scenario.prepare(sid, set_mode=True)
    try:
        g = gclient.engine().select_graph(p.graph)
        win = int(p.scenario.get("window_min") or 30)
        changes = RO(p.tenant, p.graph).run("Q-SUS-2", {"onset": p.onset_ms, "window_ms": win * 60_000}).rows
        titles = {c["deploy"]: next((x.get("title", "") for x in p.scenario.get("inject", []) if x["change"] == c["deploy"]),
                                    c["deploy"]) or c["deploy"] for c in changes}
        if not titles:
            return {"outcome": "NO_INCIDENT", "cause": None, "ranking": [], **grade(sid, "NO_INCIDENT", None), "tool_calls": 0,
                    "seconds": round(time.perf_counter() - t0, 2)}
        ids = sorted(titles)
        writes.set_vectors(g, "Deploy", [{"id": i, "embedding": v} for i, v in zip(ids, embed([titles[i] for i in ids]))])
        rows = RO(p.tenant, p.graph).run("Q-CONTRAST-VEC", {"inc": p.incident_id, "ids": ids}).rows
        rows = [(r["change"], r["distance"]) for r in rows]
        cause = rows[0][0]
        t = truth(sid)
        g_ = grade(sid, "CONFIRMED", cause)
        if t["outcome"] != "CONFIRMED":
            g_["false_blame"] = True
        return {"outcome": "CONFIRMED", "cause": cause, "ranking": [[r[0], round(float(r[1]), 4)] for r in rows],
                **g_, "tool_calls": 0, "seconds": round(time.perf_counter() - t0, 2)}
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def arm_telemetry(sid: str) -> dict:
    """T (comparator, keyless; PREREGISTRATION amendment 2026-10-13): "a plain anomaly heuristic already solves it".
    Among the window's changes (the list arm N and V read), blame the one whose own component shows the largest measured
    excess: peak error rate since onset minus its pre-onset mean, from its MetricWindows. No topology, no gate; ties
    are scored 1/k like N; it never abstains."""
    from faultline.agent.weights import weights
    from faultline.graph.ro import RO

    t0 = time.perf_counter()
    p = scenario.prepare(sid, set_mode=True)
    try:
        ro = RO(p.tenant, p.graph)
        win = int(p.scenario.get("window_min") or 30)
        changes = ro.run("Q-SUS-2", {"onset": p.onset_ms, "window_ms": win * 60_000}).rows
        if not changes:
            return {"outcome": "NO_INCIDENT", "cause": None, "ranking": [], **grade(sid, "NO_INCIDENT", None),
                    "tool_calls": 0, "seconds": round(time.perf_counter() - t0, 2)}
        iw = weights()["intake"]
        base_since, base_until = p.onset_ms - int(iw["baseline_min"]) * 60_000, p.onset_ms - int(iw["baseline_gap_min"]) * 60_000
        excess = {}
        for c in changes:
            base = [r["value"] for r in ro.run("Q-MW-1", {"target": c["target"], "metric": "error_rate",
                                                          "since": base_since, "until": base_until}).rows]
            after = [r["value"] for r in ro.run("Q-MW-1", {"target": c["target"], "metric": "error_rate",
                                                           "since": p.onset_ms, "until": p.onset_ms + 10 * 60_000}).rows]
            excess[c["deploy"]] = round(max(after) - sum(base) / len(base), 5) if base and after else 0.0
        best = max(excess.values())
        tied = sorted(c for c, v in excess.items() if v == best)
        t = truth(sid)
        frac = (1.0 / len(tied) if t.get("cause") in tied else 0.0) if t["outcome"] == "CONFIRMED" else None
        g_ = grade(sid, "CONFIRMED", tied[0], frac)
        g_["false_blame"] = any(c in _distractors(t) for c in tied) if t["outcome"] == "CONFIRMED" else True
        return {"outcome": "CONFIRMED", "cause": tied[0], "tied": tied,
                "ranking": sorted(([c, v] for c, v in excess.items()), key=lambda x: -x[1]), **g_, "tool_calls": 0,
                "seconds": round(time.perf_counter() - t0, 2)}
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


ARMS = {"N": arm_naive, "V": arm_vector, "T": arm_telemetry, "A2": lambda s: _graph_arm(s, nomem=True), "A3": lambda s: _graph_arm(s, nomem=False),
        "A4": lambda s: _graph_arm(s, nomem=False, disable=True),
        "A3-noG5": lambda s: _graph_arm(s, nomem=False, no_g5=True)}


# ------------------------------------------------------------------ product checks
def checks() -> dict:
    out: dict = {"engine_pressure": []}   # engine memory after each heavy check, and any mid-eval compaction
    import concurrency  # evals/concurrency.py

    out["S13"] = concurrency.run("acme", workers=16, rounds=100, readers=4)
    for first, repeat in (("S1", "S1b"), ("S3", "S3b")):  # N = 3 trials each (T2 go/no-go: >= 2 scenarios, N >= 3)
        trials = [_cold_vs_warm(first, repeat) for _ in range(3)]
        out[f"{repeat}_cold_vs_warm"] = {**trials[0], "trials": len(trials),
                                         "all_trials_gate_identical": all(t["gate_verdicts_identical"] for t in trials)}
    out["S6"] = _preflight()
    out["S5"], out["S9"] = _bad_fix_and_unknown()
    out["S10"] = _forget()
    import globex_checks

    out["S8"], out["S11"] = globex_checks.s8(), globex_checks.s11()
    out["S7"] = _isolation()
    import storm  # evals/: S14 alert storm, grouped at INTAKE by algo.WCC, plus the ungrouped control

    out["S14"], out["S14_ungrouped"] = storm.run(), storm.ungrouped_control()
    sys.path.insert(0, str(ROOT / "scripts"))
    import profile_templates

    out["profile"] = profile_templates.collect()
    out["scaling"] = _distractor_scaling()
    import brain_eval

    out["brain"] = brain_eval.run()
    out["backtest"] = _backtest()
    import gate_bench  # evals/: ~100 generated gate cases on clean rooms → "gate verdicts k/k"

    out["gate_bench"] = gate_bench.run()  # the development set: its first run found the bugs fixed in M13
    out["gate_bench_heldout"] = gate_bench.run(seed=20261015)  # fresh cases generated after those fixes: never tuned on
    _relieve_engine("gate_bench", out["engine_pressure"])
    import chaos  # evals/: kill -9 between execute and verify → the reconciler settles the intent exactly once

    out["chaos"] = chaos.run()
    import contention  # evals/: 24 responders approve at once (same plan, then different plans) → one approval lands

    out["contention"] = contention.run()
    import futures_eval  # evals/: each containment candidate's predicted future (Q-FUTURE-1) vs the simulated world

    out["futures"] = futures_eval.run(progress=False)
    _relieve_engine("futures", out["engine_pressure"])
    import mismatch_eval  # evals/: the gate on a WRONG graph (perturbed caps, hidden and stale edges) + arm T on the bench

    out["mismatch"] = mismatch_eval.run(progress=False)
    _relieve_engine("mismatch", out["engine_pressure"])
    import learning_eval  # evals/: a verified fix teaches the graph a missing link; the next incident is then proved

    out["learning"] = learning_eval.run(progress=False)
    _relieve_engine("learning", out["engine_pressure"])
    import context_eval  # evals/: context packs (M16.1): graph vs vector RAG vs recency, per token, busy windows

    ce = context_eval.run(progress=False)
    out["context_eval"] = {"seconds": ce["seconds"], "busy": {k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                                                             for k, v in ce["busy"].items()}}
    _relieve_engine("context_eval", out["engine_pressure"])
    import ladder  # evals/: the FalkorDB capability ladder (maxFlow / SPpaths removed one at a time) on the held-out worlds

    import deep_bench  # evals/: multi-hop causes and downstream look-alikes; dev seed (found the G4-upstream gap) + fresh

    out["deep_bench"] = {"dev": deep_bench.run(seed=deep_bench.SEED, progress=False),
                         "fresh": deep_bench.run(seed=deep_bench.FRESH_SEED, progress=False)}
    for v in out["deep_bench"].values():
        v.pop("rows", None)   # per-case rows stay in the bench's own run, not the run file
    _relieve_engine("deep_bench", out["engine_pressure"])
    out["ladder"] = ladder.run(progress=False)
    _relieve_engine("ladder", out["engine_pressure"])
    import robustness  # evals/: one knob at a time (duplicates, missing telemetry, noise, intermittent) → breaking points

    out["robustness"] = robustness.run(progress=False)
    _relieve_engine("robustness", out["engine_pressure"])
    import perf_vs_flat  # evals/: the gate's lookups in FalkorDB vs DuckDB recursive SQL; alert freshness; depth curve

    out["perf_vs_flat"] = perf_vs_flat.run(gate_detail=out["gate_bench_heldout"]["cases_detail"],
                                           t_rows=out["mismatch"]["arm_t"]["rows"], progress=False)
    _relieve_engine("perf_vs_flat", out["engine_pressure"])
    sys.path.insert(0, str(ROOT / "scripts"))
    import skill_check  # scripts/: the portable no-path-no-claim skill (4 read-only queries) vs the full gate

    sk = skill_check.run(skill_check.SCENARIOS)
    out["skill"] = {k: sk[k] for k in ("scenarios", "agree", "cause_scenarios", "named_same", "abstain_scenarios",
                                       "abstain_same", "cause_eliminated", "suspect_checks", "suspect_agree")} | {
        "rows": [{k: r[k] for k in ("scenario", "gate", "skill", "agree")} for r in sk["rows"]]}
    import scale  # evals/: the recorded `make scale` run (scale.json) on the pinned engine, else the reduced 1k variant

    out["scale"] = scale.for_harness()
    import mutation_check  # scripts/: break each safety invariant in a scratch copy; a test must notice

    m = mutation_check.run()
    out["mutation"] = {k: m[k] for k in ("mutants", "killed", "survived", "errors")} | {
        "rows": [{k: r.get(k) for k in ("id", "invariant", "status", "tests")} for r in m["rows"]]}
    return out


EVAL_MAX_START_PRESSURE = 0.35  # the engine keeps ~3 MB per deleted world copy; shedding starts at 0.85
EVAL_COMPACT_AT = 0.5           # between heavy checks: above this, `make compact` (graphs kept) before the next one


def _relieve_engine(after: str, log: list[dict]) -> None:
    """Record engine memory after a heavy check and compact when it is above EVAL_COMPACT_AT: the ~2,000 world copies
    of a full eval would otherwise reach the API's shedding limit. Fails loudly."""
    import subprocess

    from faultline.graph import client
    from faultline.graph.engine_info import memory_pressure

    f = memory_pressure()["fraction"]
    entry: dict = {"after": after, "fraction": None if f is None else round(f, 3)}
    if f is not None and f > EVAL_COMPACT_AT:
        r = subprocess.run(["make", "-s", "compact"], cwd=ROOT, capture_output=True, text=True, timeout=600)
        client.reset_connections()
        if r.returncode:
            raise SystemExit(f"`make compact` failed mid-eval (after {after}): {(r.stderr or r.stdout)[-800:]}")
        entry["compacted_to"] = round(memory_pressure()["fraction"], 3)
    log.append(entry)


def _check_engine_headroom() -> None:
    """Fail in seconds, not 40 minutes in: FalkorDB keeps the memory of deleted graphs (a `make scale` 10k graph holds
    ~2 GB until restart), and the API sheds new graph copies above its memory limit, which chaos needs."""
    from faultline.graph.engine_info import memory_pressure

    m = memory_pressure()
    if m["fraction"] is not None and m["fraction"] > EVAL_MAX_START_PRESSURE:
        raise SystemExit(f"FalkorDB is already at {m['fraction']:.0%} of maxmemory before the eval; run `make compact` "
                         "(rewrite the AOF and restart the pinned engine; graphs are kept) and retry")


def _backtest() -> dict:
    """Retroactive preflight backtest on acme and globex (evals/backtest.py): each historical PR scored by the
    production preflight as of its merge time, read-only on the golden graphs."""
    import backtest

    return backtest.run_all()


def _distractor_scaling(ks: tuple[int, ...] = (0, 5, 20)) -> list[dict]:
    """S1 with k extra deploys in the SAME minute on other services (deterministic choice). The product must not
    blame a decoy; when a decoy is a plausible synchronous dependency with no measurement against it, the honest
    result is a lower-confidence claim or an escalation, never a wrong confident one. Naive recency is 1/(k+2)."""
    from faultline.agent.loop import run_incident
    from faultline.graph import writes
    from faultline.ingest.otel_topology import load_topology

    services = sorted(s_["id"] for s_ in load_topology()["services"] if s_["id"] not in ("payment", "email", "recommendation"))
    out = []
    for k in ks:
        p = scenario.prepare("S1", set_mode=False)
        try:
            g = gclient.engine().select_graph(p.graph)
            for i, svc in enumerate(services[:k]):
                writes.inject_change(g, id=f"D-decoy-{i:02d}", target=svc, at=p.onset_ms - 3 * 60_000, title=f"{svc}: routine",
                                     tenant=p.tenant)
            res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                                 symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                                 run_id=p.run_id, window_min=p.scenario.get("window_min")))
            wrong_confident = res.outcome == "CONFIRMED" and res.cause_id != truth("S1")["cause"]
            out.append({"decoys": k, "outcome": res.outcome, "cause": res.cause_id, "correct": res.cause_id == truth("S1")["cause"],
                        "confident": res.confident, "wrong_confident": wrong_confident,
                        "eliminated": sum(1 for v in res.sweep if v["status"] == "eliminated"),
                        "naive_top1": round(1 / (k + 2), 4)})
        finally:
            gcopy.delete_if_exists(gclient.engine(), p.graph)
    return out


def _isolation() -> dict:
    """S7: run the isolation test module and report its counts from a JUnit report (the tests are the check)."""
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    with tempfile.NamedTemporaryFile(suffix=".xml") as f:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/isolation", "-p", "no:warnings", "-m", "live",
                            f"--junitxml={f.name}"], cwd=ROOT, capture_output=True, text=True,
                           env={**__import__("os").environ, "PYTHONPATH": "backend"})
        root = ET.parse(f.name).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    total, skipped = int(suite.get("tests", 0)), int(suite.get("skipped", 0))
    failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    return {"passed": total - failed - skipped, "failed": failed, "skipped": skipped, "ok": r.returncode == 0}


def _cold_vs_warm(first: str = "S1", repeat: str = "S1b") -> dict:
    """Cold (repeat scenario on a fresh golden copy) vs warm (same scenario right after `first` was resolved, written
    back and learned in the SAME graph). Memory may only reorder: gate verdicts must be identical."""
    from faultline.actions import act
    from faultline.actions import github as gh
    from faultline.memory.learn import learn

    t = truth(repeat)
    comp = next(c["target"] for c in scenario.load(repeat)["inject"] if c["change"] == t["cause"])
    pc, cold = anyio.run(lambda: scenario.run(repeat, BaselineInvestigator(), set_mode=False, keep=False))
    p1, r1 = anyio.run(lambda: scenario.run(first, BaselineInvestigator(), set_mode=False, keep=True))
    hub = gh.client(p1.graph)
    c = act.Ctx(p1.tenant, p1.graph, p1.incident_id, p1.run_id)
    o = next(o for o in r1.post_gate["options"] if o["enabled"] and o["kind"] != "open_issue")
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    act.verify(c, o["id"], hub, symptom=p1.symptoms, onset_ms=p1.onset_ms,
               effects=scenario.effects_of(p1.scenario, p1.onset_ms), at_ms=p1.onset_ms + 300_000)
    wb = act.write_back(c, o["id"], cause=r1.cause_id, confident=True)
    learn(p1.tenant, p1.graph, p1.incident_id, p1.run_id)
    pw, warm = anyio.run(lambda: scenario.run(repeat, BaselineInvestigator(), set_mode=False, keep=True, graph=p1.graph))
    gcopy.delete_if_exists(gclient.engine(), p1.graph)

    def v(r):
        return (r.outcome, r.cause_id, sorted((x["name"], x["passed"]) for x in r.gate["checks"]))

    def rank_of(r) -> int | None:   # where the true cause sat in the investigation order (1 = first); reads truth: evals only
        ids = [x["id"] for x in r.suspects or []]
        return ids.index(t["cause"]) + 1 if t["cause"] in ids else None

    return {"pair": f"{first}->{repeat}", "fix": o["kind"],
            "cold": {"outcome": cold.outcome, "tool_calls": cold.tool_calls, "seconds": cold.seconds,
                     "true_cause_rank": rank_of(cold), "suspects": len(cold.suspects or []),
                     "prior_payment" if comp == "payment" else "prior": round(cold.recall["prior"].get(comp, 0.0), 4),
                     "top_precedent": (cold.recall["precedents"] or [None])[0]},
            "warm": {"outcome": warm.outcome, "tool_calls": warm.tool_calls, "seconds": warm.seconds,
                     "true_cause_rank": rank_of(warm), "suspects": len(warm.suspects or []),
                     "prior_payment" if comp == "payment" else "prior": round(warm.recall["prior"].get(comp, 0.0), 4),
                     "top_precedent_is_s1" if first == "S1" else "top_precedent_is_first":
                         (warm.recall["precedents"] or [None])[0] == p1.incident_id,
                     "derived_runbook_first": bool(warm.recall["runbooks"])
                     and warm.recall["runbooks"][0].startswith("rb-derived-")},
            "gate_verdicts_identical": v(cold) == v(warm), "s1_writeback" if first == "S1" else "first_writeback": wb.get("verified")}


def _preflight() -> dict:
    from faultline.preflight.engine import PreflightIn, run

    before = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}}, indent=2)
    bad = json.dumps({"client": {"timeout_ms": 5000, "retries": 0}}, indent=2)
    room = f"eval_acme_preflight_{uuid.uuid4().hex[:8]}"  # a fresh clean room from the golden graph, never the tenant
    db = gclient.engine()
    gcopy.copy_graph(db, "golden_acme", room)
    try:
        r = run("acme", PreflightIn(repo="eval/demo-app", number=9900, title="S6", author="eval",
                                    files=[{"path": "src/payment/config.json", "before": before, "after": bad}]), graph=room)
    finally:
        gcopy.delete_if_exists(db, room)
    return {"verdict": r["verdict"], "risk": r["risk"], "decisions": sorted(d["id"] for d in r["decision_links"]),
            "reviewers": len(r["reviewers"])}


def _bad_fix_and_unknown() -> tuple[dict, dict]:
    from faultline.actions import act, reconcile
    from faultline.actions import github as gh
    from faultline.graph import writes

    out = []
    for kind in ("S5", "S9"):
        p, r = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
        hub = gh.client(p.graph)
        c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
        eff = scenario.effects_of(p.scenario, p.onset_ms)
        if kind == "S5":
            aid = f"act-{c.inc}-bad"
            writes.record_option(c.g(), inc=c.inc, aid=aid, kind="rollback_deploy", option="roll back the same-minute deploy",
                                 enabled=True, reason="forced bad plan (S5)", target="D-email-88",
                                 preview={"repo": act.INFRA_REPO, "path": act.DEPLOYS_PATH, "service": "email",
                                          "revert": "D-email-88"})
        else:
            aid = next(o for o in r.post_gate["options"] if o["kind"] == "flip_flag" and o["enabled"])["id"]
        spec = act.choose(c, aid, hub)
        act.approve(c, aid, spec["plan_hash"], "p-030")
        act.execute(c, aid, hub)
        if kind == "S9":
            hub.fail_next = "timeout"
        v = act.verify(c, aid, hub, symptom=p.symptoms, onset_ms=p.onset_ms, effects=eff, at_ms=p.onset_ms + 300_000)
        wb = act.write_back(c, aid, cause=r.cause_id, confident=True)
        res = {"verdict": v["verdict"], "success_written": bool(wb.get("written")),
               "stage": c.g().ro_query("MATCH (i:Incident {id:$i}) RETURN i.stage", {"i": c.inc}).result_set[0][0]}
        if kind == "S9":
            rec = reconcile.reconcile(c.tenant, c.graph, hub,
                                      lambda inc: {"symptom": p.symptoms, "onset_ms": p.onset_ms, "effects": eff,
                                                   "at_ms": p.onset_ms + 300_000}, older_than_ms=0)
            res["reconciled"] = [(x["found"], x["verdict"], x["writeback"]) for x in rec]
        gcopy.delete_if_exists(gclient.engine(), p.graph)
        out.append(res)
    return out[0], out[1]


def _forget() -> dict:
    from faultline.brain.ask import ask
    from faultline.memory import forget

    q = "What did we decide about catalog db migrations?"
    # start from the golden tenant: the receipt counts every relationship the forget removes, including SAW/ABOUT edges
    # earlier recorded tool calls left on the decision, so a used tenant made the count depend on history (15 vs 25)
    gcopy.rearm(gclient.engine(), "acme", reason="eval-forget-before")
    before = ask(q, "acme")
    plan = forget.dry_run("acme", "doc-adr-021")
    rec = forget.execute("acme", "doc-adr-021", plan["token"], "eval")
    after = ask(q, "acme")
    gcopy.rearm(gclient.engine(), "acme", reason="eval-forget")
    return {"before_cites_ADR-021": "[ADR-021]" in before.answer, "after_cites_ADR-021": "ADR-021" in after.answer,
            "receipt_nodes": rec["nodes"], "receipt_relationships": rec["relationships"],
            "vectors_still_found": rec["vectors_still_found"], "guard_ok_after": after.guard["ok"]}


def repo_facts() -> dict:
    """Counts of what the product is made of (read from the code, so README numbers stay checkable)."""
    from faultline.graph.algo import registry
    from faultline.graph.templates import catalogue
    from faultline.mcp_server import tools as T
    from faultline.agent.phases import INTERNAL_TOOLS

    from faultline.graph.ro import RO

    out = {"templates": len(catalogue()), "algorithms": len(registry.resolved()), "mcp_tools": len(T.TOOLS),
           "mcp_tools_hosted": len([t for t in T.TOOLS if t not in INTERNAL_TOOLS])}
    for tenant in ("acme", "globex"):  # tenant sizes, read from the graphs themselves
        counts = {r["label"]: r["n"] for r in RO(tenant).run("Q-COUNT-2", {}).rows} if gcopy.exists(
            gclient.engine(), f"tenant_{tenant}") else {}
        for label in ("Service", "Person", "Incident", "Team"):
            out[f"{tenant}.{label.lower()}s"] = counts.get(label, 0)
        if counts:
            out[f"{tenant}.families"] = len(RO(tenant).run("Q-MEM-6", {"inc": ""}).rows)
    return out


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="N,A2,A3,A4")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--no-checks", action="store_true")
    ap.add_argument("--approved-budget-usd", type=float, default=0.0)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--side-output", default="", help="write the trials here (LLM arms) instead of a new run + latest.json")
    a = ap.parse_args()
    arms = [x for x in a.arms.split(",") if x]
    import llm_arms

    from faultline.config import settings as _s

    llm = [x for x in arms if x in llm_arms.ARMS]
    if llm:
        est = llm_arms.estimate(len(a.scenarios.split(",")), a.n, llm)
        print(f"LLM arms {llm}: estimate {est}")
        if not (_s.anthropic_api_key and a.approved_budget_usd and est["usd_upper_bound"] <= a.approved_budget_usd):
            print("skipping LLM arms: need ANTHROPIC_API_KEY and --approved-budget-usd ≥ the estimate (a human approves spend)")
        else:
            for name in llm:
                ARMS[name] = (lambda nm: lambda sid: llm_arms.ARMS[nm](sid, a.model))(name)
    llm = [x for x in arms if x not in ARMS]
    arms = [x for x in arms if x in ARMS]
    _check_engine_headroom()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    trials: list[dict] = []
    for sid in a.scenarios.split(","):
        for arm in arms:
            for i in range(a.n if arm not in ("N", "T") else 1):  # N and T are deterministic arithmetic
                t = {"scenario": sid, "arm": arm, "trial": i + 1, **ARMS[arm](sid)}
                print(json.dumps({k: t[k] for k in ("scenario", "arm", "trial", "outcome", "cause", "top1")}))
                trials.append(t)
    scenario.set_pipeline_mode("incident")
    out = {"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": a.n, "arms": arms,
           "skipped_arms": llm, "scenarios": a.scenarios.split(","), "investigator": "baseline-policy (deterministic, no LLM)",
           "engine": json.loads((ROOT / "backend/faultline/graph/algo/resolved.json").read_text())["engine"],
           "trials": trials, "checks": {} if a.no_checks else checks(), "repo": repo_facts()}
    RESULTS.mkdir(parents=True, exist_ok=True)
    if a.side_output:  # a paid LLM run: merged into an existing side file, folded into latest.json by `make results`
        side = Path(a.side_output)
        prev = json.loads(side.read_text()) if side.exists() else {"trials": [], "arms": [], "scenarios": []}
        prev["trials"] = [x for x in prev["trials"] if not (x["arm"] in arms and x["scenario"] in a.scenarios.split(","))] + trials
        prev["arms"] = sorted(set(prev["arms"]) | set(arms))
        prev["scenarios"] = sorted(set(prev["scenarios"]) | set(a.scenarios.split(",")))
        prev.update({"model": a.model, "started": prev.get("started") or started, "finished": out["finished"]})
        side.write_text(json.dumps(prev, indent=2, default=str) + "\n")
        print(f"wrote {side} ({len(trials)} trials); run `make results` to fold it into latest.json")
        return 0
    k = 1 + max((int(p.stem.split("_")[1]) for p in RESULTS.glob("run_*.json")), default=0)
    path = RESULTS / f"run_{k:04d}.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    import report

    summary = report.summarize(out)
    (RESULTS / "latest.json").write_text(json.dumps({"run": path.name, **summary}, indent=2) + "\n")
    (ROOT / "evals" / "RESULTS.md").write_text(report.markdown(out, summary, path.name))
    (ROOT / "docs" / "NAIVE_VS_FAULTLINE.md").write_text(report.naive_vs_markdown(out, path.name, summary))
    print(f"wrote {path.relative_to(ROOT)}, evals/results/latest.json, evals/RESULTS.md, docs/NAIVE_VS_FAULTLINE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
