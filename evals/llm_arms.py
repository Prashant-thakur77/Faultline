"""LLM comparison arms. They run only with ANTHROPIC_API_KEY AND an approved budget.

A0  LLM-only: the alert/report, raw telemetry dumps (per-minute error rates of every service, as text) and the
    change list with titles and diff facts. No retrieval, no graph.
A1  Vector-RAG: A0 + the top-k chunks (same bge-small embeddings) over runbooks, postmortems, ADRs and a TEXT
    description of the topology and lineage. Similarity is computed here in numpy ON PURPOSE: this arm is the
    "embeddings find" comparator, not the product, and it must not use FalkorDB.
A3L The product with the LLM investigator (graph tools via MCP; the gate decides).

The model must answer JSON {"cause": "<change id>" | "none", "why": "..."}. Grading is the same as the keyless arms.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# claude-opus-5-5 list price (USD per million tokens). The estimate below stays an upper bound through its conservative
# tokens-per-trial assumptions, not through the price.
PRICE_PER_MTOK = {"in": 4.0, "out": 20.0}

# v1 (the recorded 2026-10-16 run): "a change id or none" only, and no data-plane evidence. The M18 audit found that made
# S12 unanswerable (its truth is NOT_CONFIDENT with an inferred origin) and starved S2/S4D of the evidence the product
# reads. v2 (PREREGISTRATION amendment 2026-10-16): the answer can say "an incident no listed change explains, starting
# at <component>", and data scenarios carry the warehouse comparison and invariant results. Default v2; results record it.
PROMPT_VERSION = int(os.environ.get("FAULTLINE_LLM_PROMPT", "2"))

ASK_V2 = ("You are on call. Given the alert, telemetry, data-plane evidence and the changes below, decide what happened. "
          "Answer ONLY with JSON: {\"cause\": \"<change id>\" or \"none\", \"incident\": true or false, "
          "\"origin\": \"<component id>\" or null, \"why\": \"<one sentence>\"}. "
          "Name a change only if the evidence shows it caused the incident. If there is an incident but no listed change "
          "explains it, answer cause \"none\", incident true and the component where it most likely started as origin. "
          "If the evidence shows nothing is wrong, answer cause \"none\", incident false.")

ASK = ("You are on call. Given the alert, telemetry and the changes below, name the single change that caused the "
       "incident, or 'none' if nothing in the data shows an incident. Answer ONLY with JSON: "
       '{"cause": "<change id or none>", "why": "<one sentence>"}')


def _world_text(sid: str) -> tuple[str, dict]:
    """Prepare the scenario world (clean room) and dump what an LLM-only operator would have: alert, report,
    per-minute error rates around onset for every service, and the change list with titles and facts."""
    from faultline import scenario
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy

    p = scenario.prepare(sid, set_mode=True)
    try:
        return evidence_text(p, p.scenario), {"graph": p.graph}
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def evidence_text(p, s: dict) -> str:
    """The A0 evidence for a prepared world `p` (its clean room still exists) and its definition `s`: alerts, report,
    per-minute error rates around onset for every simulated component (RO templates on the world's graph), the change
    list with kind, target, time and title, diff facts and (v2) the data plane. Shared with evals/llm_deep.py so the
    LLM sees the same evidence on every bench."""
    from faultline.graph.ro import RO
    from faultline.sim.telemetry import sim_view

    ro = RO(p.tenant, p.graph)
    view = sim_view(ro)   # the simulator's components (paged; on acme identical to Q-SIM-1's one read)
    svc = sorted({r["src"] for r in view} | {r["dst"] for r in view})
    lines = []
    for t in svc:
        rows = ro.run("Q-MW-1", {"target": t, "metric": "error_rate", "since": p.onset_ms - 20 * 60_000,
                                 "until": p.onset_ms + 60_000}).rows
        if rows:
            lines.append(f"{t}: " + " ".join(f"{r['value']:.3f}" for r in rows[-21:]))
    changes = [f"- {c['change']} ({c.get('kind', 'deploy')} on {c['target']}, {c['at']} before onset): {c.get('title', '')}"
               for c in s.get("inject", [])]
    facts = [f"- {f['change']} sets {f['key']} = {f['value']} ({f.get('file', '')})" for f in s.get("facts", [])]
    data = _data_plane_text(s) if PROMPT_VERSION >= 2 and s.get("pipeline_mode") else ""
    return (f"ALERTS: {', '.join(a['metric'] + ' on ' + a['target'] for a in s.get('alerts', []))}\n"
            f"REPORT: {s.get('report', '')}\n\nERROR RATE PER MINUTE (last value = onset):\n" + "\n".join(lines)
            + data
            + "\n\nCHANGES IN THE WINDOW:\n" + ("\n".join(changes) or "- none") + ("\n\nDIFF FACTS:\n" + "\n".join(facts) if facts else ""))


def _data_plane_text(s: dict) -> str:
    """v2: what the product's data specialist reads for a data incident, as text: daily revenue / orders / AOV against the
    committed healthy baseline, and the pipeline invariant suite's result (warehouse in the scenario's mode)."""
    from faultline import scenario, warehouse

    with scenario.WAREHOUSE.use(s["pipeline_mode"]):
        cmp = warehouse.compare_to_baseline(10)["comparisons"]
        inv = warehouse.run_invariants()
    lines = [f"{c['day']}: revenue {c['revenue_usd']} (baseline {c['baseline_revenue_usd']}, ratio {c['revenue_ratio']}), "
             f"orders {c['order_count']} (baseline {c['baseline_order_count']}), AOV {c['aov_median_usd']} "
             f"(baseline {c['baseline_aov_median_usd']})" for c in cmp]
    fails = "; ".join(f"{f.name}: {f.message[:160]}" for f in inv.failures[:8]) or "none"
    return ("\n\nDATA PLANE (warehouse marts.fct_revenue vs the healthy baseline, newest first):\n" + "\n".join(lines)
            + f"\nPIPELINE INVARIANTS: {inv.passed}/{inv.total} passed; failures: {fails}")


def _corpus() -> list[tuple[str, str]]:
    """Text chunks for A1: runbooks, ADRs, chats/issues, postmortems and a textual topology + lineage."""
    import yaml

    chunks = [(p.stem, p.read_text()[:2000]) for p in sorted((ROOT / "data/gen/docs").glob("*.md"))]
    pm = json.loads((ROOT / "data/gen/embeddings/postmortem.json").read_text())["items"]
    chunks += [(x["id"], x["text"]) for x in pm]
    topo = yaml.safe_load((ROOT / "data/topology/otel-demo.yaml").read_text())
    for c in topo["calls"]:
        chunks.append((f"call-{c['client']}-{c['server']}", f"{c['client']} calls {c['server']} ({c['rps']} rps); "
                       f"{c.get('why', 'synchronous call; errors propagate') if c['cap'] < 1 else 'synchronous call; errors propagate'}"))
    return chunks


def _topk(query: str, k: int = 8) -> list[str]:
    import numpy as np  # comparator arm only (see module docstring)

    from faultline.memory.embed import embed

    chunks = _corpus()
    vecs = np.array(embed([t for _, t in chunks]))
    q = np.array(embed([query])[0])
    sims = vecs @ q / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(q) + 1e-9)
    return [f"[{chunks[i][0]}] {chunks[i][1][:600]}" for i in np.argsort(-sims)[:k]]


def _ask(text: str, model: str) -> tuple[dict, dict]:
    from anthropic import Anthropic

    from faultline.config import settings

    api = Anthropic(api_key=settings.anthropic_api_key, max_retries=3)
    # current models take no sampling parameters and always think; thinking counts against max_tokens, so leave room.
    # A one-line JSON verdict: low effort keeps the comparison cheap without changing what the model is asked.
    ask = ASK_V2 if PROMPT_VERSION >= 2 else ASK
    resp = api.messages.create(model=model, max_tokens=16000, output_config={"effort": "low"},
                               messages=[{"role": "user", "content": ask + "\n\n" + text}])
    raw = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        ans = json.loads(m.group(0)) if m else {"cause": None, "why": raw[:200], "_unparsed": True}
    except json.JSONDecodeError:   # keep the paid-for usage; the caller decides how an unparseable answer is graded
        ans = {"cause": None, "why": raw[:200], "_unparsed": True}
    return ans, {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}


def arm_a0(sid: str, model: str) -> dict:
    t0 = time.perf_counter()
    text, _ = _world_text(sid)
    ans, usage = _ask(text, model)
    return _result(sid, ans, usage, t0)


def arm_a1(sid: str, model: str) -> dict:
    t0 = time.perf_counter()
    text, _ = _world_text(sid)
    ctx = "\n\n".join(_topk(text[:2000]))
    ans, usage = _ask(text + "\n\nRETRIEVED CONTEXT (top-k by embedding similarity):\n" + ctx, model)
    return _result(sid, ans, usage, t0)


def arm_a3l(sid: str, model: str) -> dict:
    """The product with the LLM investigator: the same run, gate and grading as arm A3, only the investigator differs."""
    from faultline.agent.loop import LLMInvestigator
    from harness import _graph_arm

    return _graph_arm(sid, nomem=False, investigator=LLMInvestigator(model=model))


def _result(sid: str, ans: dict, usage: dict, t0: float) -> dict:
    outcome, cause, inferred = outcome_of(ans)
    from harness import grade  # the same grader as every keyless arm (imported late: the harness imports this module)

    return {"outcome": outcome, "cause": cause, "inferred": inferred, "why": ans.get("why", "")[:300],
            **grade(sid, outcome, cause, inferred=inferred), "prompt_version": PROMPT_VERSION,
            "usage": usage, "seconds": round(time.perf_counter() - t0, 2), "tool_calls": 0}


def outcome_of(ans: dict) -> tuple[str, str | None, str | None]:
    """(outcome, cause, inferred origin) from the model's JSON answer: a named change → CONFIRMED; v2: no change and an
    incident → NOT_CONFIDENT (with the origin it names); else NO_INCIDENT. Shared with evals/llm_deep.py."""
    cause = ans.get("cause")
    cause = None if cause in (None, "", "none", "None") else str(cause)
    inferred = None
    if cause:
        outcome = "CONFIRMED"
    elif PROMPT_VERSION >= 2 and ans.get("incident") is True:   # v2: an incident no listed change explains
        outcome, inferred = "NOT_CONFIDENT", (str(ans["origin"]) if ans.get("origin") else None)
    else:
        outcome = "NO_INCIDENT"
    return outcome, cause, inferred


def estimate(n_scenarios: int, n: int, arms: list[str]) -> dict:
    """Pre-run cost estimate (printed; a human approves before anything is spent)."""
    per = {"A0": (6_000, 300), "A1": (11_000, 300), "A3L": (160_000, 6_000)}  # tokens in/out per trial (upper bound)
    tin = sum(per[a][0] for a in arms) * n_scenarios * n
    tout = sum(per[a][1] for a in arms) * n_scenarios * n
    usd = tin / 1e6 * PRICE_PER_MTOK["in"] + tout / 1e6 * PRICE_PER_MTOK["out"]
    return {"trials": len(arms) * n_scenarios * n, "input_tokens": tin, "output_tokens": tout, "usd_upper_bound": round(usd, 2)}


ARMS = {"A0": arm_a0, "A1": arm_a1, "A3L": arm_a3l}
