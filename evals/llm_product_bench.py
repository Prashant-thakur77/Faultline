"""The product with the LLM driving (arm A3L) on the decisive bench: does FalkorDB's gate keep a strong model honest?

Same 40 worlds as `evals/decisive_bench.py` (seed 20261121) and as the LLM-alone arm in `evals/llm_deep.py`. Each
world is built in its own GRAPH.COPY clean room exactly as for the product (scenario.prepare(spec=…)) and investigated
by `LLMInvestigator` (claude-opus-5-5 proposes and calls the graph tools through the stage whitelist; the
deterministic gate decides), then graded with the bench's own rules (gate_bench.grade / detail): right cause,
confident wrong blame, abstained. Shared notes are off, as in every eval arm. Pre-registered in
evals/PREREGISTRATION.md (addendum 2026-10-18, 14:16 IST).

Spending is opt-in and bounded: a paid run needs --approved-budget-usd; the script stops before any world that could
take the measured spend (list price, llm_arms.PRICE_PER_MTOK) above it, assuming the next world costs as much as the
most expensive one so far. Each world's result is written to evals/results/llm_product.json as it completes;
--resume continues an interrupted run.

    PYTHONPATH=backend scripts/memguard.sh 3000 uv run python evals/llm_product_bench.py \\
        --approved-budget-usd 12 --reason "…" [--limit N] [--resume]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

import anyio  # noqa: E402

import decisive_bench  # noqa: E402
import deep_bench  # noqa: E402
import gate_bench  # noqa: E402
import llm_arms  # noqa: E402
from faultline import scenario  # noqa: E402
from faultline.agent.loop import LLMInvestigator, run_incident  # noqa: E402
from faultline.config import settings  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402

OUTS = {"decisive": ROOT / "evals" / "results" / "llm_product.json",
        "deep": ROOT / "evals" / "results" / "llm_product_deep.json"}
FIX_OUT = ROOT / "evals" / "results" / "llm_product_deep_fix.json"   # --ids re-runs after a fix


def usd(tin: int, tout: int) -> float:
    return tin / 1e6 * llm_arms.PRICE_PER_MTOK["in"] + tout / 1e6 * llm_arms.PRICE_PER_MTOK["out"]


def run_world(case: dict, model: str) -> dict:
    t0 = time.perf_counter()
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    inv = LLMInvestigator(model=model)
    try:
        res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                             symptoms=p.symptoms, investigator=inv, graph=p.graph, run_id=p.run_id,
                                             window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    blamed = res.cause_id if res.outcome == "CONFIRMED" else None
    got = {"outcome": res.outcome, "cause": blamed, "error": res.error,
           "sweep": {v["change"]: f"{v['status']}: {v['reason']}" for v in res.sweep}}
    exp = case["expected"]
    usage = dict(inv.usage)
    abstained = blamed is None and res.outcome in gate_bench.ABSTAIN_OK
    # the bench's own "ok": abstain where no single cause is expected; the cause (or, where the bench allows it, an
    # abstention) where one is
    ok = abstained if exp.get("cause") is None else (
        blamed == exp["cause"] or (case["category"] in deep_bench.ABSTAIN_FINE and abstained))
    return {"id": case["id"], "category": case["category"], "outcome": res.outcome, "blamed": blamed,
            "expected": exp.get("cause"), "error": res.error, "ok": ok,
            "wrong_confident": blamed is not None and (exp["outcome"] != "CONFIRMED" or blamed != exp["cause"]),
            "abstained": abstained,
            **gate_bench.detail(exp, res.outcome, blamed, got["sweep"]), **gate_bench.grade(exp, got),
            "tool_calls": res.tool_calls, "usage": usage,
            "usd": round(usd(usage.get("input_tokens", 0), usage.get("output_tokens", 0)), 4),
            "seconds": round(time.perf_counter() - t0, 1)}


def summarize(rows: list[dict]) -> dict:
    def block(rs: list[dict]) -> dict:
        return {"cases": len(rs), "ok": sum(bool(r.get("ok")) for r in rs),
                "right_cause": sum(bool(r["right_cause"]) for r in rs),
                "wrong_confident": sum(bool(r["wrong_confident"]) for r in rs),
                "abstained": sum(bool(r["abstained"]) for r in rs), "errors": sum(1 for r in rs if r.get("error"))}
    cats = sorted({r["category"] for r in rows})
    return {"all": block(rows), "by_category": {c: block([r for r in rows if r["category"] == c]) for c in cats},
            "usd": round(sum(r["usd"] for r in rows), 4),
            "tool_calls_median": sorted(r["tool_calls"] for r in rows)[len(rows) // 2] if rows else None,
            "seconds_median": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-budget-usd", type=float, required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--limit", type=int, default=0, help="only the first N worlds (a smoke run)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--model", default=settings.anthropic_model)
    ap.add_argument("--bench", choices=sorted(OUTS), default="decisive")
    ap.add_argument("--categories", default="", help="comma list: only these categories (deep bench)")
    ap.add_argument("--ids", default="", help="comma list: only these world ids (a re-run after a fix; own result file)")
    a = ap.parse_args()
    OUT = FIX_OUT if a.ids else OUTS[a.bench]
    if not settings.anthropic_api_key:
        print("no ANTHROPIC_API_KEY configured; nothing run", file=sys.stderr)
        return 2
    cases = decisive_bench.generate() if a.bench == "decisive" else deep_bench.generate(seed=deep_bench.FRESH_SEED)
    if a.categories:
        keep = {c.strip() for c in a.categories.split(",") if c.strip()}
        cases = [c for c in cases if c["category"] in keep]
    if a.ids:
        want = {i.strip() for i in a.ids.split(",") if i.strip()}
        cases = [c for c in cases if c["id"] in want]
    if a.limit:
        cases = cases[: a.limit]
    prev = json.loads(OUT.read_text()) if (a.resume and OUT.exists()) else None
    rows: list[dict] = list(prev["rows"]) if prev else []
    done = {r["id"] for r in rows}
    out = {"bench": a.bench, "seed": decisive_bench.SEED if a.bench == "decisive" else deep_bench.FRESH_SEED,
           "categories": sorted({c["category"] for c in cases}), "model": a.model, "arm": "A3L (LLMInvestigator + gate)",
           "price_per_mtok": llm_arms.PRICE_PER_MTOK, "approved_budget_usd": a.approved_budget_usd, "reason": a.reason,
           "started": (prev or {}).get("started") or time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}
    spent = sum(r["usd"] for r in rows)
    worst = max((r["usd"] for r in rows), default=0.5)    # before any measurement, assume an expensive world
    for c in cases:
        if c["id"] in done:
            continue
        if spent + worst > a.approved_budget_usd:
            out["stopped"] = f"budget: spent ${spent:.2f}, the next world could cost ${worst:.2f}"
            print(out["stopped"], file=sys.stderr)
            break
        r = run_world(c, a.model)
        rows.append(r)
        spent += r["usd"]
        worst = max(worst if len(rows) > 1 else 0.0, r["usd"])
        out["summary"] = summarize(rows)
        out["complete"] = len(rows) == len(cases)
        OUT.write_text(json.dumps(out, indent=2) + "\n")
        print(f"[{len(rows)}/{len(cases)}] {r['id']} {r['category']}: {r['outcome']} blamed={r['blamed']} "
              f"expected={r['expected']} wrong={r['wrong_confident']} ${r['usd']:.3f} (total ${spent:.2f})",
              file=sys.stderr, flush=True)
    out["summary"] = summarize(rows)
    out["complete"] = len(rows) == len(cases)
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
