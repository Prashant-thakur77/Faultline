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
import re
import time
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
PRICE_PER_MTOK = {"in": 15.0, "out": 75.0}  # conservative upper bound used for the pre-run estimate (USD)

ASK = ("You are on call. Given the alert, telemetry and the changes below, name the single change that caused the "
       "incident, or 'none' if nothing in the data shows an incident. Answer ONLY with JSON: "
       '{"cause": "<change id or none>", "why": "<one sentence>"}')


def _world_text(sid: str) -> tuple[str, dict]:
    """Prepare the scenario world (clean room) and dump what an LLM-only operator would have: alert, report,
    per-minute error rates around onset for every service, and the change list with titles and facts."""
    from faultline import scenario
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.ro import RO

    p = scenario.prepare(sid, set_mode=True)
    try:
        ro = RO(p.tenant, p.graph)
        svc = sorted({r["src"] for r in ro.run("Q-SIM-1", {}).rows} | {r["dst"] for r in ro.run("Q-SIM-1", {}).rows})
        lines = []
        for t in svc:
            rows = ro.run("Q-MW-1", {"target": t, "metric": "error_rate", "since": p.onset_ms - 20 * 60_000,
                                     "until": p.onset_ms + 60_000}).rows
            if rows:
                lines.append(f"{t}: " + " ".join(f"{r['value']:.3f}" for r in rows[-21:]))
        s = p.scenario
        changes = [f"- {c['change']} ({c.get('kind', 'deploy')} on {c['target']}, {c['at']} before onset): {c.get('title', '')}"
                   for c in s.get("inject", [])]
        facts = [f"- {f['change']} sets {f['key']} = {f['value']} ({f.get('file', '')})" for f in s.get("facts", [])]
        text = (f"ALERTS: {', '.join(a['metric'] + ' on ' + a['target'] for a in s.get('alerts', []))}\n"
                f"REPORT: {s.get('report', '')}\n\nERROR RATE PER MINUTE (last value = onset):\n" + "\n".join(lines)
                + "\n\nCHANGES IN THE WINDOW:\n" + ("\n".join(changes) or "- none") + ("\n\nDIFF FACTS:\n" + "\n".join(facts) if facts else ""))
        return text, {"graph": p.graph}
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


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
    resp = api.messages.create(model=model, max_tokens=400, temperature=0,
                               messages=[{"role": "user", "content": ASK + "\n\n" + text}])
    raw = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    ans = json.loads(m.group(0)) if m else {"cause": None, "why": raw[:200]}
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
    from faultline import scenario
    from faultline.agent.loop import LLMInvestigator

    t0 = time.perf_counter()
    p, res = anyio.run(lambda: scenario.run(sid, LLMInvestigator(model=model), set_mode=True, keep=False))
    confirmed = res.outcome in ("CONFIRMED", "NOT_CONFIDENT")
    return {"outcome": res.outcome, "cause": res.cause_id if confirmed else None, "usage": res.usage,
            "seconds": round(time.perf_counter() - t0, 2), "tool_calls": res.tool_calls, "error": res.error}


def _result(sid: str, ans: dict, usage: dict, t0: float) -> dict:
    cause = ans.get("cause")
    cause = None if cause in (None, "", "none", "None") else str(cause)
    return {"outcome": "CONFIRMED" if cause else "NO_INCIDENT", "cause": cause, "why": ans.get("why", "")[:300],
            "usage": usage, "seconds": round(time.perf_counter() - t0, 2), "tool_calls": 0}


def estimate(n_scenarios: int, n: int, arms: list[str]) -> dict:
    """Pre-run cost estimate (printed; a human approves before anything is spent)."""
    per = {"A0": (6_000, 300), "A1": (11_000, 300), "A3L": (160_000, 6_000)}  # tokens in/out per trial (upper bound)
    tin = sum(per[a][0] for a in arms) * n_scenarios * n
    tout = sum(per[a][1] for a in arms) * n_scenarios * n
    usd = tin / 1e6 * PRICE_PER_MTOK["in"] + tout / 1e6 * PRICE_PER_MTOK["out"]
    return {"trials": len(arms) * n_scenarios * n, "input_tokens": tin, "output_tokens": tout, "usd_upper_bound": round(usd, 2)}


ARMS = {"A0": arm_a0, "A1": arm_a1, "A3L": arm_a3l}
