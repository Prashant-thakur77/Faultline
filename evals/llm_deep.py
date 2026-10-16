"""LLM-only arm (A0, prompt v2) on the deep and decisive benches (PREREGISTRATION addendum 2026-10-16, item 1).

The fair prompt-v2 rerun (evals/llm_arms.py) showed claude-opus-5-5 alone matching the gate on the 8 hand-written
scenarios. The measured gap is on the adversarial benches, where telemetry heuristics name innocent changes; this
script puts the same LLM, with the same evidence and prompt as A0 v2, on those worlds:
  deep      the headline deep bench (seed 20261016, 140 worlds; evals/deep_bench.py, the worlds behind deep.fresh.all.*)
  decisive  the decisive bench (seed 20261121, 40 worlds; evals/decisive_bench.py)
Each world is built in its own clean room exactly as for the product (scenario.prepare(spec=…)), its evidence is
rendered by llm_arms.evidence_text (alerts, report, per-minute error rates of every simulated component read through
RO templates, the change list with kind/target/time/title, diff facts if any), then the clean room is deleted. The
answer is llm_arms.ASK_V2 through llm_arms._ask, mapped to an outcome by llm_arms.outcome_of, and graded with the
bench's own rules (right cause, any wrong named change, abstained), so the numbers sit next to Faultline, T and T+ on
the same worlds.

Spending is opt-in and bounded: --dry-run renders every prompt (clean rooms created and deleted, no API call) and
prints the estimate at the list price; a paid run needs --approved-budget-usd at or above the estimate and stops before
any world that would take the measured spend above it. Each world's result is written to evals/results/llm_deep.json
as it completes (--resume continues an interrupted run).

    PYTHONPATH=backend scripts/memguard.sh 3000 uv run python evals/llm_deep.py --bench deep --dry-run
    PYTHONPATH=backend scripts/memguard.sh 3000 uv run python evals/llm_deep.py --bench deep \\
        --approved-budget-usd 7 --reason "…"                                      # paid: owner's session only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import gate_bench  # noqa: E402
import llm_arms  # noqa: E402

MODEL = "claude-opus-5-5"
BENCHES = ("deep", "decisive")
OUT = ROOT / "evals" / "results" / "llm_deep.json"
DRY = ROOT / "evals" / "results" / "llm_deep_dryrun.json"
# Input tokens from the rendered prompt: the recorded A0 v2 trials (same renderer) measured 1.66–1.71 characters per
# token on this numbers-heavy text; 1.6 rounds toward more tokens. Output: the recorded A0 v2 maximum was 654 tokens
# (thinking included, effort low); 1,500 per world is the conservative allowance.
CHARS_PER_TOKEN = 1.6
OUT_TOKENS_EST = 1_500
RELIEVE_EVERY = 35   # clean rooms between engine-pressure checks (harness._relieve_engine compacts above its threshold)
HINT_WORDS = ("bad", "broken", "break", "bug", "fix", "revert", "rollback", "roll back", "cause", "culprit", "decoy",
              "lookalike", "look-alike", "faulty", "innocent", "guilty", "root")


def cases_for(bench: str) -> list[dict]:
    if bench == "deep":
        import deep_bench

        return deep_bench.generate(seed=deep_bench.FRESH_SEED)
    if bench == "decisive":
        import decisive_bench

        return decisive_bench.generate()
    raise ValueError(f"unknown bench {bench!r} (one of {', '.join(BENCHES)})")


def bench_seed(bench: str) -> int:
    import decisive_bench
    import deep_bench

    return deep_bench.FRESH_SEED if bench == "deep" else decisive_bench.SEED


def title_problems(case: dict) -> list[str]:
    """Does anything the LLM reads about a change hint at the answer? Every title must be the one neutral template
    (`<target>: change`, the same for the cause and the look-alikes) and no title, report or name may carry a hint
    word. The ids are opaque random hex by construction (the generators' own seeded stream)."""
    spec = case["spec"]
    out = []
    for c in spec.get("inject", []):
        if c.get("title", "") != f"{c['target']}: change":
            out.append(f"{c['change']}: title {c.get('title')!r} is not the neutral template")
        if not re.fullmatch(r"D-[0-9a-f]{8}", c["change"]):
            out.append(f"{c['change']}: change id is not opaque")
    for field, text in (("report", spec.get("report", "")), ("name", spec.get("name", "")),
                        *(("title", c.get("title", "")) for c in spec.get("inject", []))):
        low = text.lower()
        hits = [w for w in HINT_WORDS if re.search(rf"\b{re.escape(w)}\b", low)]
        if hits:
            out.append(f"{field} {text!r} contains {hits}")
    return out


def render(case: dict) -> str:
    """The world's A0 v2 evidence, from its own clean room (created, read through RO templates, deleted)."""
    from faultline import scenario
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy

    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    try:
        return llm_arms.evidence_text(p, case["spec"])
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def prompt_of(text: str) -> str:
    """Exactly what _ask sends (the v2 instruction, a blank line, the evidence)."""
    return (llm_arms.ASK_V2 if llm_arms.PROMPT_VERSION >= 2 else llm_arms.ASK) + "\n\n" + text


def est_tokens(prompt: str) -> tuple[int, int]:
    return int(len(prompt) / CHARS_PER_TOKEN) + 1, OUT_TOKENS_EST


def usd(tin: float, tout: float) -> float:
    return tin / 1e6 * llm_arms.PRICE_PER_MTOK["in"] + tout / 1e6 * llm_arms.PRICE_PER_MTOK["out"]


def grade(case: dict, bench: str, outcome: str, cause: str | None) -> dict:
    """The bench's own rules: right cause (worlds with a cause), any named change that is not the expected cause
    (the rule the bench uses for T's wrong blames), abstained (no change named, NOT_CONFIDENT), and deep's `ok`."""
    exp = case["expected"]
    has_cause = exp["outcome"] == "CONFIRMED" and exp.get("cause") is not None
    named = outcome != "UNPARSED" and cause is not None
    row = {"has_cause": has_cause,
           "right_cause": has_cause and named and cause == exp["cause"],
           "wrong_confident": named and cause != exp.get("cause"),
           "abstained": not named and outcome in gate_bench.ABSTAIN_OK,
           "no_incident": outcome == "NO_INCIDENT", "unparsed": outcome == "UNPARSED",
           "named_unknown": named and cause not in {c["change"] for c in case["spec"].get("inject", [])}}
    if bench == "deep":
        import deep_bench

        row["ok"] = (row["abstained"] if exp["cause"] is None else
                     (row["right_cause"] or (case["category"] in deep_bench.ABSTAIN_FINE and row["abstained"])))
    return row


def summary(rows: list[dict]) -> dict:
    out = {"cases": len(rows), "cause_cases": sum(r["has_cause"] for r in rows)}
    for m in ("right_cause", "wrong_confident", "abstained", "no_incident", "unparsed", "named_unknown", "ok"):
        if rows and m in rows[0]:
            out[m] = sum(bool(r[m]) for r in rows)
    return out


def summarize_bench(b: dict) -> dict:
    rows = list(b["worlds"].values())
    cats = sorted({r["category"] for r in rows})
    tin = [r["usage"]["input_tokens"] for r in rows if r.get("usage")]
    tout = [r["usage"]["output_tokens"] for r in rows if r.get("usage")]
    return {"all": summary(rows), "by_category": {c: summary([r for r in rows if r["category"] == c]) for c in cats},
            "tokens_in_median": statistics.median(tin) if tin else None,
            "tokens_out_median": statistics.median(tout) if tout else None,
            "seconds_median": statistics.median([r["seconds"] for r in rows]) if rows else None,
            "cost_usd": round(usd(sum(tin), sum(tout)), 4)}


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n")
    os.replace(tmp, path)   # atomic: an interrupted run never leaves a half-written side file


def dry_run(bench: str, cases: list[dict]) -> dict:
    """Render every world's prompt (clean rooms created and deleted), estimate tokens and cost; no API call."""
    import harness

    pressure: list[dict] = []
    worlds = {}
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        prompt = prompt_of(render(c))
        tin, tout = est_tokens(prompt)
        worlds[c["id"]] = {"category": c["category"], "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                           "chars": len(prompt), "est_in": tin, "est_out": tout}
        if (i + 1) % RELIEVE_EVERY == 0:
            harness._relieve_engine(f"llm-deep-dry-{bench}-{i + 1}", pressure)
    tin = sum(w["est_in"] for w in worlds.values())
    tout = sum(w["est_out"] for w in worlds.values())
    return {"bench": bench, "seed": bench_seed(bench), "model": MODEL, "prompt_version": llm_arms.PROMPT_VERSION,
            "worlds": worlds, "n": len(worlds), "est_input_tokens": tin, "est_output_tokens": tout,
            "est_usd": round(usd(tin, tout), 2), "price_per_mtok": llm_arms.PRICE_PER_MTOK,
            "chars_per_token": CHARS_PER_TOKEN, "out_tokens_per_world": OUT_TOKENS_EST,
            "chars_median": statistics.median(w["chars"] for w in worlds.values()) if worlds else None,
            "render_seconds": round(time.perf_counter() - t0, 1), "engine_pressure": pressure,
            "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def paid_run(bench: str, cases: list[dict], approved: float, reason: str, resume: bool, out: Path) -> int:
    import harness

    from faultline.config import settings

    if not settings.anthropic_api_key:
        print("llm_deep: no ANTHROPIC_API_KEY configured; nothing spent", file=sys.stderr)
        return 2
    side = _load(out)
    if side and (side.get("model") != MODEL or side.get("prompt_version") != llm_arms.PROMPT_VERSION):
        print(f"llm_deep: {out} holds model {side.get('model')} / prompt v{side.get('prompt_version')}; refusing to mix",
              file=sys.stderr)
        return 2
    side = side or {"model": MODEL, "prompt_version": llm_arms.PROMPT_VERSION, "benches": {}}
    b = side["benches"].get(bench)
    if b and b.get("worlds") and not resume:
        print(f"llm_deep: {bench} already has {len(b['worlds'])} worlds in {out}; pass --resume to continue",
              file=sys.stderr)
        return 2
    b = b or {"seed": bench_seed(bench), "worlds": {}, "runs": []}
    todo = [c for c in cases if c["id"] not in b["worlds"]]
    dry = (_load(DRY).get(bench) or {}).get("worlds", {})
    # the estimate for exactly the worlds this invocation will run (rendered fresh below; the dry run's sizes if known)
    est = sum(usd(dry[c["id"]]["est_in"], dry[c["id"]]["est_out"]) if c["id"] in dry else
              usd(*est_tokens(prompt_of("x" * 4_000))) for c in todo)
    print(f"llm_deep: {bench}: {len(todo)} worlds to run (of {len(cases)}), estimate ${est:.2f} at "
          f"${llm_arms.PRICE_PER_MTOK['in']}/${llm_arms.PRICE_PER_MTOK['out']} per MTok; approved ${approved:.2f}",
          file=sys.stderr)
    if est > approved:
        print("llm_deep: the estimate exceeds the approved budget; nothing spent", file=sys.stderr)
        return 3
    run_log = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason, "approved_usd": approved,
               "resume": resume, "worlds": 0, "spent_usd": 0.0}
    b["runs"].append(run_log)
    side["benches"][bench] = b
    _save(out, side)
    spent, pressure = 0.0, []
    for i, c in enumerate(todo):
        prompt_text = render(c)
        prompt = prompt_of(prompt_text)
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        next_cost = usd(*est_tokens(prompt))
        if spent + next_cost > approved:
            print(f"llm_deep: stopping before {c['id']}: spent ${spent:.2f} + next ≤ ${next_cost:.2f} would pass the "
                  f"approved ${approved:.2f}; --resume continues", file=sys.stderr)
            break
        t0 = time.perf_counter()
        try:
            ans, usage = llm_arms._ask(prompt_text, MODEL)
        except Exception as e:   # API / network: keep everything so far, resume later
            run_log["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            _save(out, side)
            print(f"llm_deep: API error at {c['id']} ({run_log['error']}); saved; --resume continues", file=sys.stderr)
            return 4
        outcome, cause, inferred = llm_arms.outcome_of(ans)
        if ans.get("_unparsed"):
            outcome, cause, inferred = "UNPARSED", None, None
        cause = cause.strip() if cause else cause
        spent += usd(usage["input_tokens"], usage["output_tokens"])
        row = {"id": c["id"], "category": c["category"], "outcome": outcome, "cause": cause, "inferred": inferred,
               "why": str(ans.get("why", ""))[:300], **grade(c, bench, outcome, cause), "usage": usage,
               "seconds": round(time.perf_counter() - t0, 2), "prompt_sha256": sha,
               "matches_dry_run": (dry.get(c["id"]) or {}).get("prompt_sha256") == sha if dry else None}
        b["worlds"][c["id"]] = row
        run_log["worlds"] += 1
        run_log["spent_usd"] = round(spent, 4)
        b["complete"] = len(b["worlds"]) == len(cases)
        _save(out, side)
        print(f"[llm-deep] {bench} {c['id']} {c['category']}: {outcome} {cause or ''} right={row['right_cause']} "
              f"wrong={row['wrong_confident']} ${spent:.2f}", file=sys.stderr, flush=True)
        if (i + 1) % RELIEVE_EVERY == 0:
            harness._relieve_engine(f"llm-deep-{bench}-{i + 1}", pressure)
    run_log["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    run_log["engine_pressure"] = pressure
    b["complete"] = len(b["worlds"]) == len(cases)
    b["summary"] = summarize_bench(b)
    _save(out, side)
    print(json.dumps(b["summary"], indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bench", choices=BENCHES, required=True)
    ap.add_argument("--dry-run", action="store_true", help="render every prompt and print the estimate; no API call")
    ap.add_argument("--approved-budget-usd", type=float, help="required for a paid run: the owner-approved ceiling")
    ap.add_argument("--limit", type=int, help="only the first N worlds of the bench (in generator order)")
    ap.add_argument("--resume", action="store_true", help="continue a run: skip worlds already in the side file")
    ap.add_argument("--reason", help="why this run (logged in the side file); required for a paid run")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    cases = cases_for(a.bench)
    bad = {c["id"]: p for c in cases for p in [title_problems(c)] if p}
    if bad:   # a hint in the text the LLM reads would make the comparison unfair to every arm: refuse
        print(f"llm_deep: {len(bad)} worlds carry a hint in a title/report: {json.dumps(bad)[:800]}", file=sys.stderr)
        return 5
    if a.limit:
        cases = cases[:a.limit]
    if a.dry_run:
        r = dry_run(a.bench, cases)
        allr = _load(DRY)
        allr[a.bench] = r | {"titles_checked": len(cases_for(a.bench)), "title_problems": 0, "limit": a.limit}
        _save(DRY, allr)
        print(json.dumps({k: v for k, v in r.items() if k not in ("worlds", "engine_pressure")}, indent=1))
        print(f"\npaid command (owner's session; estimate ${r['est_usd']:.2f}):\n  PYTHONPATH=backend scripts/memguard.sh "
              f"3000 uv run python evals/llm_deep.py --bench {a.bench}"
              + (f" --limit {a.limit}" if a.limit else "")
              + f" --approved-budget-usd {max(1, -(-r['est_usd'] // 1)):.0f} --reason \"<why>\"")
        return 0
    if a.approved_budget_usd is None or not a.reason:
        print("llm_deep: a paid run needs --approved-budget-usd and --reason (use --dry-run for the estimate)",
              file=sys.stderr)
        return 2
    return paid_run(a.bench, cases, a.approved_budget_usd, a.reason, a.resume, Path(a.out))


if __name__ == "__main__":
    raise SystemExit(main())
