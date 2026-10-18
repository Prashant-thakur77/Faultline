"""Summaries for evals/results/latest.json (the ONLY source of numbers in README/docs/blog; check_claims enforces it)
and the generated evals/RESULTS.md (never hand-edited)."""

from __future__ import annotations

import re
import statistics
import sys
from collections import defaultdict


def _mean(xs: list) -> float | None:
    xs = [float(x) for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval (95 %) for k successes in n independent cases; None when n is 0."""
    import math

    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(max(0.0, (c - h) / d), 4), round(min(1.0, (c + h) / d), 4)


def wilson_keys(prefix: str, k: float, n: int) -> dict:
    """{prefix}.k / .n / .ci_lo / .ci_hi: a count with its denominator and 95 % Wilson interval (as rates 0–1)."""
    ci = wilson(k, n)
    if ci is None:
        return {}
    return {f"{prefix}.k": k, f"{prefix}.n": n, f"{prefix}.ci_lo": ci[0], f"{prefix}.ci_hi": ci[1]}


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 3)


def with_llm_trials(out: dict) -> dict:
    """The run plus the LLM arms' trials from evals/results/llm_arms.json (run separately, with an approved budget, so a
    paid run never replaces the keyless suite). Same grader, same keys (arm.<A0|A1|A3L>.*)."""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parent / "results" / "llm_arms.json"
    if not p.exists():
        return out
    side = json.loads(p.read_text())
    extra = [t for t in side.get("trials", []) if t["arm"] not in out["arms"]]
    arms = out["arms"] + [a for a in side.get("arms", []) if a not in out["arms"]]
    return {**out, "arms": arms, "trials": out["trials"] + extra, "llm_side": {k: side.get(k) for k in ("model", "scenarios",
                                                                                                            "started", "finished")}}


def summarize(out: dict) -> dict:
    out = with_llm_trials(out)
    s: dict = {}
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for t in out["trials"]:
        by_arm[t["arm"]].append(t)
    for arm, ts in by_arm.items():
        p = f"arm.{arm}"
        s[f"{p}.trials"] = len(ts)
        s[f"{p}.top1"] = _mean([t["top1"] for t in ts])
        # on scenarios with a true cause only (top1 is None where there is no cause to find): labelled so in RESULTS/README
        s[f"{p}.false_blame_rate"] = _mean([1.0 if t["false_blame"] else 0.0 for t in ts if t["top1"] is not None])
        s[f"{p}.abstention_correct_rate"] = _mean([1.0 if t["abstention_correct"] else 0.0 for t in ts
                                                    if t["abstention_correct"] is not None])
        s[f"{p}.outcome_correct_rate"] = _mean([1.0 if t["outcome_correct"] else 0.0 for t in ts])
        # only arms whose runs record a confidence (the graph arms); N/V/T/A0/A1 always commit and record none (numbers audit)
        s[f"{p}.confident_rate"] = (_mean([1.0 if t.get("confident") else 0.0 for t in ts if t.get("top1") is not None])
                                    if any("confident" in t for t in ts) else None)
        s[f"{p}.confirmed_causes"] = sum(1 for t in ts if t.get("cause") and t["outcome"] in ("CONFIRMED", "NOT_CONFIDENT"))
        if arm != "N":
            s[f"{p}.grounded_rate"] = _mean([1.0 if t.get("grounded") else 0.0 for t in ts if t.get("grounded") is not None])
            s[f"{p}.distractors_rejected_rate"] = _mean([1.0 if t["distractors_rejected"] else 0.0 for t in ts
                                                         if t.get("distractors_rejected") is not None])
            s[f"{p}.tool_calls_mean"] = _mean([t.get("tool_calls") for t in ts])
            secs = [t["seconds"] for t in ts if t.get("seconds") is not None]
            s[f"{p}.seconds_p50"], s[f"{p}.seconds_p95"] = _pct(secs, 0.5), _pct(secs, 0.95)
        for sid in sorted({t["scenario"] for t in ts}):
            st = [t for t in ts if t["scenario"] == sid]
            s[f"{p}.{sid}.outcome_correct_rate"] = _mean([1.0 if t["outcome_correct"] else 0.0 for t in st])
            if arm in DETAIL_ARMS:
                s.update({f"{p}.{sid}.{k}": v for k, v in detail_rates(st).items() if v is not None})
        if arm in DETAIL_ARMS:
            s.update({f"{p}.{k}": v for k, v in detail_rates(ts).items()})
    import re

    flow = re.compile(r"max flow ([0-9.]+) < needed ([0-9.]+) \(observed ([0-9.]+)")
    for t in (x for x in out["trials"] if x["arm"] == "A3" and x["trial"] == 1):
        for v in t.get("sweep") or []:
            m = flow.search(v["reason"])
            if m and v["status"] == "eliminated":
                k = f"{t['scenario'].lower()}.{v['change']}"
                s[f"{k}.max_flow"], s[f"{k}.needed"], s[f"{k}.observed"] = (float(m.group(1)), float(m.group(2)),
                                                                           float(m.group(3)))
            elif v["status"] == "eliminated":
                s[f"{t['scenario'].lower()}.{v['change']}.rejected_by"] = v["reason"].split(":")[0]
        if t.get("chain"):
            s[f"{t['scenario'].lower()}.chain"] = " → ".join(t["chain"])
    s.update({f"repo.{k}": v for k, v in (out.get("repo") or {}).items()})
    c = out.get("checks") or {}
    if "S13" in c:
        x = c["S13"]
        s.update({"s13.workers": x["workers"], "s13.rounds": x["rounds"], "s13.rounds_one_owner": x["rounds_with_exactly_one_owner"],
                  "s13.lost_updates": x["lost_updates"], "s13.ro_p50_ms_during_writes": x["ro_read_ms"]["during_writes"]["p50"],
                  "s13.ro_p95_ms_during_writes": x["ro_read_ms"]["during_writes"]["p95"], "s13.claims_per_s": x["claims_per_s"]})
    if "S1b_cold_vs_warm" in c:
        x = c["S1b_cold_vs_warm"]
        s.update({"memory.trials": x.get("trials", 1), "memory.all_trials_gate_identical": x.get("all_trials_gate_identical"),
                  "memory.gate_verdicts_identical": x["gate_verdicts_identical"], "memory.cold_tool_calls": x["cold"]["tool_calls"],
                  "memory.warm_tool_calls": x["warm"]["tool_calls"], "memory.cold_prior": x["cold"]["prior_payment"],
                  "memory.warm_prior": x["warm"]["prior_payment"], "memory.warm_top_precedent_is_s1": x["warm"]["top_precedent_is_s1"],
                  "memory.derived_runbook_first": x["warm"]["derived_runbook_first"], "s1.writeback": x["s1_writeback"],
                  "memory.cold_true_cause_rank": x["cold"].get("true_cause_rank"),
                  "memory.warm_true_cause_rank": x["warm"].get("true_cause_rank"),
                  "memory.suspects": x["warm"].get("suspects")})
    if "S3b_cold_vs_warm" in c:
        x = c["S3b_cold_vs_warm"]
        s.update({"memory.s3b.trials": x.get("trials", 1), "memory.s3b.all_trials_gate_identical": x.get("all_trials_gate_identical"),
                  "memory.s3b.gate_verdicts_identical": x["gate_verdicts_identical"],
                  "memory.s3b.cold_prior": x["cold"]["prior"], "memory.s3b.warm_prior": x["warm"]["prior"],
                  "memory.s3b.warm_top_precedent_is_first": x["warm"]["top_precedent_is_first"],
                  "memory.s3b.cold_tool_calls": x["cold"]["tool_calls"], "memory.s3b.warm_tool_calls": x["warm"]["tool_calls"]})
    if "S6" in c:
        s.update({"s6.verdict": c["S6"]["verdict"], "s6.risk": c["S6"]["risk"]})
    if "S5" in c:
        s.update({"s5.verdict": c["S5"]["verdict"], "s5.success_written": c["S5"]["success_written"]})
    if "S9" in c:
        s.update({"s9.verdict": c["S9"]["verdict"], "s9.success_written": c["S9"]["success_written"],
                  "s9.reconciled": c["S9"].get("reconciled")})
    if "S10" in c:
        s.update({f"s10.{k}": v for k, v in c["S10"].items()})
    for tid, x in (c.get("profile") or {}).items():
        if x.get("engine_ms_p50") is not None:
            s[f"profile.{tid}.engine_ms_p50"] = x["engine_ms_p50"]
        if x.get("engine_ms_p95") is not None:
            s[f"profile.{tid}.engine_ms_p95"] = x["engine_ms_p95"]
    if c.get("gate_bench_heldout"):
        h = c["gate_bench_heldout"]
        s.update({"gate_bench_heldout.cases": h["cases"], "gate_bench_heldout.correct": h["correct"],
                  "gate_bench_heldout.seed": h["seed"]})
    if c.get("gate_bench"):
        b = c["gate_bench"]
        s.update({"gate_bench.cases": b["cases"], "gate_bench.correct": b["correct"],
                  "gate_bench.abstain_inferred_origin": b.get("abstain_inferred_origin")})
        for cat, x in b["by_category"].items():
            s[f"gate_bench.{cat}.cases"], s[f"gate_bench.{cat}.correct"] = x["cases"], x["correct"]
    if c.get("S14"):  # alert-storm correlation (evals/storm.py): groups, placements, causes, and the ungrouped control
        x = c["S14"]
        s.update({f"s14.{kk}": x[kk] for kk in ("incidents_expected", "incidents_opened", "groups_correct", "alerts_placed_k",
                                                 "alerts_placed_n", "cross_fault_merge", "causes_found", "causes_expected",
                                                 "all_distractors_rejected")})
        u = c.get("S14_ungrouped") or {}
        s.update({f"s14.ungrouped.{kk}": u.get(kk) for kk in ("outcome", "causes_found", "confident_misattribution")} if u else {})
    if c.get("chaos"):
        x = c["chaos"]
        s.update({"chaos.ok": x.get("ok"), "chaos.exactly_once": x.get("exactly_once"),
                  "chaos.prs_after_reconcile": (x.get("final") or {}).get("prs"),
                  "chaos.writeback": (x.get("final") or {}).get("writeback"),
                  "chaos.control_merged_prs": (x.get("control_naive_retry") or {}).get("merged_prs")})
    if c.get("contention"):
        x = c["contention"]
        sp, dp = x.get("same_plan") or {}, x.get("different_plans") or {}
        s.update({"contention.ok": x.get("ok"), "contention.responders": x.get("responders"),
                  "contention.same.accepted": sp.get("accepted"), "contention.same.refused": sp.get("refused"),
                  "contention.same.intents": sp.get("intents"), "contention.same.prs": sp.get("prs"),
                  "contention.same.operator_steps": sp.get("operator_steps"),
                  "contention.diff.options": dp.get("options"), "contention.diff.accepted": dp.get("accepted"),
                  "contention.diff.refused": dp.get("refused"), "contention.diff.intents": dp.get("intents")})
    for x in c.get("scaling") or []:
        for kk in ("outcome", "correct", "confident", "wrong_confident", "naive_top1"):
            s[f"scaling.k{x['decoys']}.{kk}"] = x[kk]
    if c.get("brain"):
        for kk in ("questions", "correct", "answerable", "unanswerable", "unanswerable_honest", "guard_ok", "ms_p50",
                   "knowledge_unchanged"):
            s[f"brain.{kk}"] = c["brain"][kk]
    if c.get("mutation"):
        for kk in ("mutants", "killed", "survived", "errors"):
            s[f"mutation.{kk}"] = c["mutation"][kk]
    # a later full `make mutants` run (docs/audit/mutation.json, written only by a full run) supersedes the eval run's
    import json
    from pathlib import Path

    audit = Path(__file__).resolve().parents[1] / "docs" / "audit" / "mutation.json"
    if audit.exists():
        m = json.loads(audit.read_text())
        if m.get("mutants", 0) >= int(s.get("mutation.mutants") or 0):
            for kk in ("mutants", "killed", "survived", "errors"):
                s[f"mutation.{kk}"] = m[kk]
    for k in ("S7", "S8", "S11"):
        if k in c:
            s.update({f"{k.lower()}.{kk}": vv for kk, vv in c[k].items()})
    s.update(backtest_summary(c.get("backtest") or {}))
    sc = current_scale(c)
    s.update(scale_summary(sc))
    s["scale.started"] = sc.get("started")
    s.update(futures_summary(c.get("futures") or {}))
    s.update(mismatch_summary(c.get("mismatch") or {}))
    s.update({f"learning.{k}": v for k, v in (c.get("learning") or {}).items() if k not in ("rows", "seconds")})
    s.update(ladder_summary(c.get("ladder") or {}))
    s.update(robustness_summary(c.get("robustness") or {}))
    s.update(perf_summary(c.get("perf_vs_flat") or {}))
    s.update(deep_summary(c.get("deep_bench") or {}))
    s.update(context_summary(c.get("context_eval") or {}))
    s.update({f"skill.{k}": v for k, v in (c.get("skill") or {}).items() if k != "rows"})
    s.update(live_summary(live_bench()))
    # what one decision costs in model tokens, per LLM arm (recorded usage; the graph's own check costs none)
    for arm in ("A0", "A1", "A3L"):
        toks = sorted(int((t.get("usage") or {}).get("input_tokens", 0)) + int((t.get("usage") or {}).get("output_tokens", 0))
                      for t in out["trials"] if t["arm"] == arm and t.get("usage"))
        if toks:
            s[f"arm.{arm}.tokens_median"] = toks[len(toks) // 2]
    s.update(audit_summary(out, s))
    return s


# ------------------------------------------------------------------ numbers audit (PREREGISTRATION 2026-10-16)
def _key_arm(arm: str) -> str:
    return arm.replace("+", "plus")   # claim tags allow [A-Za-z0-9_.-] only


def _truth_of(sid: str) -> dict:
    import json
    from pathlib import Path

    return json.loads((Path(__file__).resolve().parents[1] / "data" / "scenarios" / f"{sid}.truth.json").read_text())


def _strict(t: dict, tr: dict) -> dict:
    """Tie-aware per-trial grading: a tie is never a verdict; wrong blame counted over ALL scenarios (controls too)."""
    tied = t.get("tied") or ([t["cause"]] if t.get("cause") else [])
    blamed = bool(t.get("cause"))
    if tr["outcome"] == "CONFIRMED":
        oc = bool(t.get("outcome_correct")) and len(tied) <= 1
        wrong = blamed and tied != [tr["cause"]]
    else:
        oc, wrong = bool(t.get("outcome_correct")), blamed
    return {"oc": oc, "wrong": wrong}


def audit_summary(out: dict, s: dict) -> dict:
    """New keys only (existing keys keep their meaning):
      arm.<A>.outcome_correct.{k,n,ci_lo,ci_hi}            over trials (as published)
      arm.<A>.scen.n                                      distinct scenarios (the effective N: trials are identical copies)
      arm.<A>.scen.<metric>.{k,n,ci_lo,ci_hi}             per distinct scenario: outcome_correct, outcome_correct_strict
                                                          (a tie is never correct), false_blame (cause scenarios),
                                                          abstention (no-cause scenarios), wrong_blame (any blame of a
                                                          wrong change on ANY scenario, controls included)
      arm.<A>.outcome_correct_strict_rate                 per trial, ties never correct
      arm.<A>.distractors_rejected_any_gate.{k,n,...}     per distinct cause scenario: every look-alike eliminated, by any gate
      gate_bench[_heldout].correct_strict(.k/n/ci)        bystander changes accepted NOT_CONFIDENT counted wrong
      deep.<run>.all.arm_t_wrong                          arm T's (fractional) wrong blames: T always blames"""
    from collections import defaultdict

    k: dict = {}
    trials = with_llm_trials(out)["trials"]
    by = defaultdict(list)
    for t in trials:
        by[t["arm"]].append(t)
    for arm, ts in by.items():
        p = f"arm.{_key_arm(arm)}"
        k.update(wilson_keys(f"{p}.outcome_correct", sum(1 for t in ts if t["outcome_correct"]), len(ts)))
        scen: dict[str, list[dict]] = defaultdict(list)
        for t in ts:
            scen[t["scenario"]].append(t)
        tr = {sid: _truth_of(sid) for sid in scen}
        st = {sid: [_strict(t, tr[sid]) for t in xs] for sid, xs in scen.items()}
        k[f"{p}.scen.n"] = len(scen)
        k[f"{p}.outcome_correct_strict_rate"] = round(sum(x["oc"] for v in st.values() for x in v) / len(ts), 4)
        k.update(wilson_keys(f"{p}.scen.outcome_correct", sum(all(t["outcome_correct"] for t in xs) for xs in scen.values()),
                             len(scen)))
        k.update(wilson_keys(f"{p}.scen.outcome_correct_strict", sum(all(x["oc"] for x in v) for v in st.values()), len(scen)))
        k.update(wilson_keys(f"{p}.scen.wrong_blame", sum(any(x["wrong"] for x in v) for v in st.values()), len(scen)))
        cause = [sid for sid in scen if tr[sid]["outcome"] == "CONFIRMED"]
        other = [sid for sid in scen if tr[sid]["outcome"] != "CONFIRMED"]
        k.update(wilson_keys(f"{p}.scen.false_blame", sum(any(t["false_blame"] for t in scen[sid]) for sid in cause), len(cause)))
        k.update(wilson_keys(f"{p}.scen.abstention", sum(all(t["abstention_correct"] for t in scen[sid]) for sid in other),
                             len(other)))
        if any(t.get("sweep") is not None for t in ts):
            def all_rejected(sid: str, xs: list[dict]) -> bool:
                d = tr[sid].get("distractors") or []
                d = list(d.keys()) if isinstance(d, dict) else list(d)
                return all(all(any(v["change"] == x and v["status"] == "eliminated" for v in (t.get("sweep") or []))
                               for x in d) for t in xs)
            cs = [sid for sid in cause if tr[sid].get("distractors")]
            k.update(wilson_keys(f"{p}.distractors_rejected_any_gate", sum(all_rejected(sid, scen[sid]) for sid in cs), len(cs)))
    c = out.get("checks") or {}
    for name in ("gate_bench", "gate_bench_heldout"):
        b = c.get(name) or {}
        if b.get("cases_detail"):
            strict = sum(1 for r in b["cases_detail"] if r["correct"] and not (
                r["expected"]["outcome"] != "CONFIRMED" and r.get("accepted_not_confident")))
            k[f"{name}.correct_strict"] = strict
            k[f"{name}.bystander_not_confident"] = b.get("abstain_bystander_not_confident")
            k.update(wilson_keys(f"{name}.correct_strict", strict, b["cases"]))
            k.update(wilson_keys(f"{name}.correct", b["correct"], b["cases"]))
    for run, d in (c.get("deep_bench") or {}).items():
        if "arm_t" in d["all"]:
            k[f"deep.{run}.all.arm_t_wrong"] = round(d["all"]["cases"] - d["all"]["arm_t"], 2)
            k[f"deep.{run}.all.arm_t_abstained"] = 0   # T cannot abstain (by definition)
            k.update(wilson_keys(f"deep.{run}.all.abstained", d["all"]["abstained"], d["all"]["cases"]))
    lad = (c.get("ladder") or {}).get("rungs") or {}
    for rung, v in lad.items():
        b = v.get("buckets") or {}
        if b.get("confirm_cases"):
            k.update(wilson_keys(f"ladder.{rung}.b.right_cause", b["right_cause"], b["confirm_cases"]))
    k.update(side_summaries(s))
    return k


def _kn(s: dict, p: str, pct: bool = True) -> str:
    """'k/n (95 % CI lo–hi %)' from the wilson keys of prefix p; '—' when absent."""
    if s.get(f"{p}.n") is None:
        return "—"
    lo, hi = s[f"{p}.ci_lo"], s[f"{p}.ci_hi"]
    k = s[f"{p}.k"]
    k = int(k) if float(k).is_integer() else k
    return f"{k}/{s[f'{p}.n']} ({lo * 100:.0f}–{hi * 100:.0f} %)" if pct else f"{k}/{s[f'{p}.n']}"


def audit_markdown(out: dict, s: dict) -> list[str]:
    arms = with_llm_trials(out)["arms"]
    L = ["", "## Per distinct scenario, with 95 % intervals (numbers audit)", "",
         "Each scenario counts once (its identical trials are one case). Strict: a tie between changes is never a "
         "correct verdict (arms N and T break ties alphabetically in the trial field above, which credited T with S2 "
         "where both changes measure 0.0). Wrong blame: any blame of a change that is not the cause, on any of the 8 "
         "scenarios, controls included (the false-blame column above counts only the 5 with a cause).", "",
         "| arm | scenarios | outcome correct | strict (ties never correct) | wrong blame, any scenario | abstention (no-cause scenarios) |",
         "|---|---|---|---|---|---|"]
    for arm in arms:
        p = f"arm.{_key_arm(arm)}"
        L.append(f"| {arm} | {s.get(f'{p}.scen.n')} | {_kn(s, f'{p}.scen.outcome_correct')} | "
                 f"{_kn(s, f'{p}.scen.outcome_correct_strict')} | {_kn(s, f'{p}.scen.wrong_blame')} | "
                 f"{_kn(s, f'{p}.scen.abstention')} |")
    if s.get("arm.A3-noG5.distractors_rejected_any_gate.n"):
        L += ["", f"Look-alikes rejected by any gate, per scenario with a look-alike: A3 "
                  f"{_kn(s, 'arm.A3.distractors_rejected_any_gate', False)}, A3-noG5 "
                  f"{_kn(s, 'arm.A3-noG5.distractors_rejected_any_gate', False)} (the strict column above requires the "
                  "gate the truth file names, so A3-noG5's S1 look-alike, rejected by G4 origin, counts as not rejected there)."]
    for name, label in (("gate_bench", "development"), ("gate_bench_heldout", "second seed")):
        if s.get(f"{name}.correct_strict") is not None:
            L += ["", f"Gate bench, {label}: {_kn(s, f'{name}.correct')} by outcome; {_kn(s, f'{name}.correct_strict')} when "
                      f"an abstain case where the gate accepted a bystander change NOT_CONFIDENT "
                      f"({s.get(f'{name}.bystander_not_confident')} such cases) counts as wrong."]
    L += side_markdown(s)
    L += new_benches_markdown(s)
    L += faultbench_otel_markdown(s)
    L += oncall_markdown(s)
    L += learn_markdown(s)
    L += graphrag_markdown(s)
    L += tenants_markdown(s)   # tenant density + concurrency
    L += algo10k_markdown(s)
    return L


def side_markdown(s: dict) -> list[str]:
    L: list[str] = []
    if s.get("seeds.scen.seeds"):
        L += ["", f"## Scenario suite across {s['seeds.scen.seeds']} world seeds (evals/scenario_seeds.py)", "",
              "Each trial is a different telemetry world (base rates and noise); S2 and S4D have no simulated telemetry "
              "and run once. Strict grading; wrong blame on any scenario.", "",
              "| arm | trials | outcome correct | right cause (cause scenarios) | wrong blame | abstention (no-cause) |",
              "|---|---|---|---|---|---|"]
        for arm in ("N", "V", "T", "Tplus", "A3", "A3-noG5"):
            p = f"seeds.scen.{arm}"
            if s.get(f"{p}.trials"):
                L.append(f"| {arm} | {s[f'{p}.trials']} | {_kn(s, f'{p}.outcome_correct')} | {_kn(s, f'{p}.right_cause')} | "
                         f"{_kn(s, f'{p}.wrong_blame')} | {_kn(s, f'{p}.abstention')} |")
    for kind, title in (("gate", "Gate bench"), ("deep", "Deep bench")):
        p = f"seeds.{kind}"
        if s.get(f"{p}.cases"):
            L += ["", f"## {title} on {s[f'{p}.seeds']} new seeds (evals/seed_bench.py, never generated before)", "",
                  "| | right cause (worlds with a cause) | wrong blames, all worlds (Faultline: confident; T, T+: any) | abstained |",
                  "|---|---|---|---|",
                  f"| Faultline | {_kn(s, f'{p}.right_cause')} | {_kn(s, f'{p}.wrong_confident')} | {s[f'{p}.abstained']} |",
                  f"| telemetry only (T) | {_kn(s, f'{p}.T.right_strict')} (fractional {s[f'{p}.T.right_frac']}) | "
                  f"{_kn(s, f'{p}.T.wrong_any')} | {s[f'{p}.T.abstained']} |",
                  f"| thresholded telemetry (T+) | {_kn(s, f'{p}.Tplus.right_strict')} (fractional "
                  f"{s[f'{p}.Tplus.right_frac']}) | {_kn(s, f'{p}.Tplus.wrong_any')} | {s[f'{p}.Tplus.abstained']} |", "",
                  f"Strict verdicts (a bystander accepted NOT_CONFIDENT on a no-cause world counted wrong): "
                  f"{_kn(s, f'{p}.correct_strict')}; runs that ended NOT_CONFIDENT having accepted some change: "
                  f"{s.get(f'{p}.accepted_nc.any')}"
                  + (f" (the true cause {s.get('seeds.deep.accepted_nc.expected_cause')}, a bystander with no fault of its "
                     f"own {s.get('seeds.deep.accepted_nc.bystander')}, all in abstain_downstream: "
                     f"{s.get('seeds.deep.abstain_downstream.bystander_nc')} of {s.get('seeds.deep.abstain_downstream.cases')})"
                     if kind == "deep" else "") + "."]
    if s.get("decisive.full.g5_only.cases") is not None:
        L += ["", "## Decisive bench: look-alikes with their own fault (evals/decisive_bench.py)", "",
              "| rung | category | worlds | right cause | wrong-confident | abstained |", "|---|---|---|---|---|---|"]
        for rung in ("full", "no_maxflow", "no_sppaths", "neither"):
            for cat in ("g5_only", "anomalous_no_path"):
                p = f"decisive.{rung}.{cat}"
                if s.get(f"{p}.cases") is not None:
                    L.append(f"| {rung} | {cat} | {s[f'{p}.cases']} | {s[f'{p}.right_cause']} | {s[f'{p}.wrong_confident']} | "
                             f"{s[f'{p}.abstained']} |")
        for arm in ("T", "Tplus"):
            L.append("")
            L.append(f"{arm} on the same worlds: " + "; ".join(
                f"{cat} right {s.get(f'decisive.{arm}.{cat}.right_strict')} (fractional {s.get(f'decisive.{arm}.{cat}.right_frac')}), "
                f"wrong {s.get(f'decisive.{arm}.{cat}.wrong_frac')}" for cat in ("g5_only", "anomalous_no_path")) + ".")
    if s.get("world.cases"):
        L += ["", "## Independent-parameter worlds (evals/world_bench.py; not blind)", "",
              "| | right cause (worlds with a cause) | wrong blames, all worlds (Faultline: confident; T, T+: any) | abstained |",
              "|---|---|---|---|",
              f"| Faultline | {_kn(s, 'world.right_cause')} | {_kn(s, 'world.wrong_confident')} | {s['world.abstained']} |",
              f"| T | {_kn(s, 'world.T.right_strict')} | {_kn(s, 'world.T.wrong_any')} | {s['world.T.abstained']} |",
              f"| T+ | {_kn(s, 'world.Tplus.right_strict')} | {_kn(s, 'world.Tplus.wrong_any')} | {s['world.Tplus.abstained']} |",
              "", f"Runs that ended NOT_CONFIDENT having accepted a change: the true cause {s.get('world.accepted_nc.expected_cause')}, "
                  f"a bystander with no fault of its own {s.get('world.accepted_nc.bystander')} (all in worlds where an unchanged "
                  f"component broke: {s.get('world.unchanged.bystander_nc')} of {s.get('world.unchanged.cases')}).",
              "", "By world kind (Faultline): " + "; ".join(
                  f"{c} {s.get(f'world.{c}.cases')} worlds, verdict right {s.get(f'world.{c}.verdict_ok')}, wrong "
                  f"{s.get(f'world.{c}.wrong_confident')}, abstained {s.get(f'world.{c}.abstained')}"
                  for c in ("cause", "unchanged", "quiet")) + "."]
    if s.get("curve.points"):
        L += ["", "## Robustness curves (evals/robustness.py --curves, the 100 second-seed worlds)", "",
              f"Baseline: correct {s['curve.baseline.correct']}, right cause {s['curve.baseline.right_cause']}/"
              f"{s['curve.baseline.cause_cases']}, wrong-confident {s['curve.baseline.wrong_confident']}. Highest "
              f"wrong-confident at any point: {s['curve.wrong_confident_max']}.", "",
              "| knob | level | correct | right cause | wrong-confident | abstained |", "|---|---|---|---|---|---|"]
        for knob in ("noise", "missing", "effect"):
            lvls = sorted({k[len(f"curve.{knob}."):-len(".correct")] for k in s
                           if k.startswith(f"curve.{knob}.") and k.endswith(".correct")}, key=float)
            for lv in lvls:
                p = f"curve.{knob}.{lv}"
                L.append(f"| {knob} | {lv} | {s[f'{p}.correct']} | {s[f'{p}.right_cause']} | {s[f'{p}.wrong_confident']} | "
                         f"{s[f'{p}.abstained']} |")
    if s.get("ctx.busy30.b1000.TR.mrr") is not None:
        L += ["", "## Context ranking with a telemetry-only comparator (evals/context_eval.py, side run)", "",
              f"TR ranks every change in the window by its measured excess, with no graph. Rerun reproduces the run's "
              f"G/GA/V/R exactly: {s.get('ctx.rerun_reproduces_run')}.", "",
              "| busy deploys | budget | GA (product) | G (distance) | V | R | TR (telemetry, no graph) |", "|---|---|---|---|---|---|---|"]
        for busy in ("0", "10", "30", "100"):
            for b in ("500", "1000"):
                cells = []
                for arm in ("GA", "G", "V", "R", "TR"):
                    m = s.get(f"ctx.busy{busy}.b{b}.{arm}.mrr")
                    lo, hi = s.get(f"ctx.busy{busy}.b{b}.{arm}.mrr_ci_lo"), s.get(f"ctx.busy{busy}.b{b}.{arm}.mrr_ci_hi")
                    cells.append("—" if m is None else (f"{m} ({lo}–{hi})" if lo is not None else f"{m}"))
                L.append(f"| {busy} | {b} | " + " | ".join(cells) + " |")
    if s.get("brain_para.questions"):
        L += ["", "## Company brain on paraphrased questions (not a blind set)", "",
              f"Original wording: {_kn(s, 'brain_orig.correct')} correct, citation precision "
              f"{s.get('brain_orig.citation_precision_mean')}. Paraphrased: {_kn(s, 'brain_para.correct')} correct "
              f"({s.get('brain_para.intent_correct')} routed to the expected intent; {s.get('brain_para.cites_ok')} with "
              f"every expected citation whatever the intent label), citation precision "
              f"{s.get('brain_para.citation_precision_mean')}."]
    if s.get("brain_blind.s2.hybrid.questions"):
        L += ["", "## Company brain on blind sets (written by agents that never saw the router)", "",
              "| Router | Set 1 | Set 2 |", "|---|---|---|"]
        for lab, name in (("keyword_router", "keyword (before)"), ("graph_intents", "graph-native only"), ("hybrid", "hybrid (shipped)")):
            cells = [_kn(s, f"brain_blind.s{n}.{lab}.correct") if s.get(f"brain_blind.s{n}.{lab}.questions") else "not scored"
                     for n in ("1", "2")]
            L.append(f"| {name} | " + " | ".join(cells) + " |")
        L += ["", "Set 1 informed the hybrid's design (it is no longer blind for the hybrid); set 2 was written before the "
              "hybrid was scored, under the pre-registered rule in evals/PREREGISTRATION.md."]
    return L


def _side(name: str) -> dict:
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parent / "results" / name
    return json.loads(p.read_text()) if p.exists() else {}


def side_summaries(s: dict) -> dict:
    """The phase-2 side files (each written by its own script, with a `reason`; PREREGISTRATION 2026-10-16)."""
    k: dict = {}
    sc = _side("scenario_seeds.json")
    if sc:
        from collections import defaultdict

        by = defaultdict(list)
        for t in sc["trials"]:
            by[t["arm"]].append(t)
        for arm, ts in by.items():
            p = f"seeds.scen.{_key_arm(arm)}"
            k[f"{p}.trials"] = len(ts)
            k.update(wilson_keys(f"{p}.outcome_correct", sum(1 for t in ts if t["outcome_correct_strict"]), len(ts)))
            k.update(wilson_keys(f"{p}.wrong_blame", sum(1 for t in ts if t["wrong_blame_any"]), len(ts)))
            cause = [t for t in ts if t["top1"] is not None]
            other = [t for t in ts if t["top1"] is None]
            k.update(wilson_keys(f"{p}.right_cause", sum(1 for t in cause if t["outcome_correct_strict"]), len(cause)))
            k.update(wilson_keys(f"{p}.abstention", sum(1 for t in other if t["abstention_correct"]), len(other)))
        k["seeds.scen.seeds"] = len(sc["seeds"])
    sb = _side("seed_bench.json") or {}
    for kind in ("gate", "deep"):
        pooled = sb.get(f"{kind}_pooled") if sb else None
        if not pooled:
            continue
        p = f"seeds.{kind}"
        k[f"{p}.seeds"] = len(sb[kind])
        for m in ("cases", "cause_cases", "correct", "correct_strict", "right_cause", "wrong_confident", "abstained", "ok"):
            if m in pooled:
                k[f"{p}.{m}"] = pooled[m]
        # every run that ended NOT_CONFIDENT having accepted some change (cause or bystander; split below for deep)
        k[f"{p}.accepted_nc.any"] = pooled.get("bystander_not_confident")
        k.update(wilson_keys(f"{p}.right_cause", pooled["right_cause"], pooled["cause_cases"]))
        k.update(wilson_keys(f"{p}.wrong_confident", pooled["wrong_confident"], pooled["cases"]))
        k.update(wilson_keys(f"{p}.correct_strict", pooled["correct_strict"], pooled["cases"]))
        for arm in ("t", "tplus"):
            a = pooled[arm]
            q = f"{p}.{'T' if arm == 't' else 'Tplus'}"
            k.update({f"{q}.{m}": a[m] for m in ("right_strict", "right_frac", "wrong_any", "wrong_frac", "abstained")})
            k.update(wilson_keys(f"{q}.right_strict", a["right_strict"], pooled["cause_cases"]))
            k.update(wilson_keys(f"{q}.wrong_any", a["wrong_any"], pooled["cases"]))
    if sb.get("deep"):   # not-confident acceptances on the new deep seeds (rows + the deterministic generator)
        import deep_bench
        import seed_bench

        acc = {"expected_cause": 0, "other_faulty_change": 0, "bystander": 0}
        for seed, v in sb["deep"].items():
            for kk, n in seed_bench.classify_acceptances(v["rows"], deep_bench.generate(seed=int(seed))).items():
                acc[kk] += n
        k.update({f"seeds.deep.accepted_nc.{kk}": n for kk, n in acc.items()})
        k.update(wilson_keys("seeds.deep.accepted_nc.bystander", acc["bystander"], sb["deep_pooled"]["cases"]))
        ad = [r for v in sb["deep"].values() for r in v["rows"] if r["category"] == "abstain_downstream"]
        k["seeds.deep.abstain_downstream.cases"] = len(ad)
        k["seeds.deep.abstain_downstream.bystander_nc"] = sum(1 for r in ad if r["accepted_not_confident"])
    hd = _side("deep_fresh_detail.json")
    if hd:   # the headline deep bench re-run with rows: reproduction check + its not-confident acceptances
        a = hd["all"]
        k["deep.fresh.detail.reproduces_run"] = all(s.get(f"deep.fresh.all.{m}") == a[m]
                                                    for m in ("cases", "right_cause", "wrong_confident", "abstained"))
        k.update({f"deep.fresh.accepted_nc.{kk}": n for kk, n in a["acceptances"].items()})
        k.update(wilson_keys("deep.fresh.accepted_nc.bystander", a["acceptances"]["bystander"], a["cases"]))
        ad = hd["by_category"].get("abstain_downstream") or {}
        k["deep.fresh.abstain_downstream.bystander_nc"] = (ad.get("acceptances") or {}).get("bystander")
    fb = (sb or {}).get("deep_fresh_baselines")
    if fb:   # T and T+ on the headline deep bench's 140 worlds (comparators; the product's numbers are the run's)
        for arm in ("t", "tplus"):
            x, q = fb[arm], f"deep.fresh.all.{'T' if arm == 't' else 'Tplus'}"
            k.update({f"{q}.{m}": x[m] for m in ("right_strict", "right_frac", "wrong_any", "wrong_frac", "abstained")})
            k.update(wilson_keys(f"{q}.right_strict", x["right_strict"], fb["cause_cases"]))
            k.update(wilson_keys(f"{q}.wrong_any", x["wrong_any"], fb["cases"]))
            k.update(wilson_keys(f"{q}.abstained", x["abstained"], fb["cases"]))
    dc = _side("decisive_bench.json")
    if dc:
        for rung, v in dc["rungs"].items():
            for cat, x in v["by_category"].items():
                for m in ("cases", "right_cause", "wrong_confident", "abstained"):
                    k[f"decisive.{rung}.{cat}.{m}"] = x[m]
        for arm, v in dc["arms"].items():
            for cat, x in v.items():
                for m in ("right_strict", "right_frac", "wrong_frac"):
                    k[f"decisive.{'T' if arm == 't' else 'Tplus'}.{cat}.{m}"] = x[m]
    for name, prefix in (("world_bench.json", "world"), ("world_bench_globex.json", "world_globex")):
        wb = _side(name)
        if wb:
            k.update(_world_keys(prefix, wb))
    k.update(_seeds2_keys(sb))
    k.update(_deep_fresh_hop_keys())
    k.update(llm_deep_keys())
    k.update(llm_product_keys())
    k.update(faultbench_otel_keys())
    k.update(udf_equivalence_keys())
    k.update(oncall_keys())
    k.update(learn_keys())
    k.update(tenants_keys())   # tenant density + concurrency
    k.update(algo10k_keys())
    k.update(t2_keys())
    k.update(vector_recall_keys())
    k.update(graphrag_keys())   # GraphRAG-SDK comparison (PREREGISTRATION 2026-10-17 23:35 IST)
    rc = _side("robustness_curves.json")
    if rc:
        for knob, levels in rc["curves"].items():
            for lv, x in levels.items():
                for m in ("correct", "right_cause", "wrong_confident", "abstained"):
                    k[f"curve.{knob}.{lv}.{m}"] = x[m]
        for m in ("correct", "right_cause", "wrong_confident", "abstained", "cause_cases"):
            k[f"curve.baseline.{m}"] = rc["baseline"][m]
        k["curve.points"] = sum(len(v) for v in rc["curves"].values())
        k["curve.wrong_confident_max"] = max(x["wrong_confident"] for v in rc["curves"].values() for x in v.values())
    ce = _side("context_eval.json")
    if ce:
        same = True
        for busy, v in ce["busy"].items():
            for b, arms in v["budgets"].items():
                for arm, m in arms.items():
                    if arm != "TR" and s.get(f"ctx.busy{busy}.b{b}.{arm}.mrr") not in (None, m["mrr"]):
                        same = False
                    k[f"ctx.busy{busy}.b{b}.{arm}.mrr_ci_lo"] = m.get("mrr_ci_lo")
                    k[f"ctx.busy{busy}.b{b}.{arm}.mrr_ci_hi"] = m.get("mrr_ci_hi")
                    if arm == "TR":
                        k.update({f"ctx.busy{busy}.b{b}.TR.{mm}": m[mm] for mm in ("cause", "mrr")})
        k["ctx.rerun_reproduces_run"] = same   # the side rerun must reproduce the run's G, GA, V and R exactly
        import random
        import statistics as st

        for busy, v in ce["busy"].items():   # paired bootstrap on the same worlds: GA minus each comparator (seed 0)
            rows = v.get("rows") or []
            for b in ("500", "1000"):
                for other in ("TR", "V", "G"):
                    diffs = [r["rr"][b]["GA"] - r["rr"][b][other] for r in rows if other in r["rr"].get(b, {})]
                    if not diffs:
                        continue
                    rnd = random.Random(0)
                    means = sorted(st.fmean(rnd.choices(diffs, k=len(diffs))) for _ in range(2000))
                    q = f"ctx.busy{busy}.b{b}.GA_minus_{other}"
                    k[f"{q}.mrr_diff"] = round(st.fmean(diffs), 4)
                    k[f"{q}.ci_lo"], k[f"{q}.ci_hi"] = round(means[50], 4), round(means[1949], 4)
    bp = _side("brain_paraphrase.json")
    if bp:
        for name, x in (("brain_para", bp["paraphrase"]), ("brain_orig", bp["original"])):
            for m in ("questions", "correct", "cites_ok", "intent_correct", "citation_precision_mean", "unanswerable_honest",
                      "unanswerable"):
                k[f"{name}.{m}"] = x.get(m)
            k.update(wilson_keys(f"{name}.correct", x["correct"], x["questions"]))
    bh = _side("brain_heldout.json")   # blind sets: each router version scored once per set (evals/brain_heldout.py)
    for r in (bh or {}).get("runs", []):
        q = f"brain_blind.s{r.get('set', '1')}.{r['label'].replace('-', '_')}"
        k[f"{q}.correct"], k[f"{q}.questions"] = r["correct"], r["questions"]
        k.update(wilson_keys(f"{q}.correct", r["correct"], r["questions"]))
    return k


def _world_keys(p: str, wb: dict) -> dict:
    """world.* (acme) / world_globex.* (addendum 2026-10-16 item 3): the independent-parameter world bench."""
    import seed_bench
    import world_bench

    k: dict = {}
    a = wb["all"]
    for m in ("cases", "cause_cases", "right_cause", "wrong_confident", "abstained", "verdict_ok"):
        k[f"{p}.{m}"] = a[m]
    k[f"{p}.accepted_nc.any"] = a.get("bystander_not_confident")
    cases = world_bench.generate(n=wb.get("n", world_bench.N_WORLDS), seed=wb["seed"], tenant=wb.get("tenant", "acme"))
    acc = seed_bench.classify_acceptances(wb["rows"], cases)
    k.update({f"{p}.accepted_nc.{kk}": n for kk, n in acc.items()})
    k[f"{p}.unchanged.bystander_nc"] = sum(1 for r in wb["rows"] if r["category"] == "unchanged" and r["accepted_not_confident"])
    k.update(wilson_keys(f"{p}.right_cause", a["right_cause"], a["cause_cases"]))
    k.update(wilson_keys(f"{p}.wrong_confident", a["wrong_confident"], a["cases"]))
    if p != "world":   # newer prefixes also carry the abstention interval
        k.update(wilson_keys(f"{p}.abstained", a["abstained"], a["cases"]))
        k[f"{p}.seed"], k[f"{p}.tenant"] = wb["seed"], wb.get("tenant")
    for cat, x in wb["by_category"].items():
        for m in ("cases", "right_cause", "wrong_confident", "abstained", "verdict_ok"):
            k[f"{p}.{cat}.{m}"] = x[m]
    for arm in ("t", "tplus"):
        x = a[arm]
        q = f"{p}.{'T' if arm == 't' else 'Tplus'}"
        k.update({f"{q}.{m}": x[m] for m in ("right_strict", "right_frac", "wrong_any", "wrong_frac", "abstained")})
        k.update(wilson_keys(f"{q}.right_strict", x["right_strict"], a["cause_cases"]))
        k.update(wilson_keys(f"{q}.wrong_any", x["wrong_any"], a["cases"]))
    return k


def _pooled_deep_keys(p: str, pooled: dict) -> dict:
    """Faultline, T and T+ on a pool of deep-bench worlds (seed_bench.summary shape), each count with its Wilson 95 %."""
    k: dict = {}
    for m in ("cases", "cause_cases", "correct", "correct_strict", "right_cause", "wrong_confident", "abstained", "ok"):
        if m in pooled:
            k[f"{p}.{m}"] = pooled[m]
    k[f"{p}.accepted_nc.any"] = pooled.get("bystander_not_confident")
    k.update(wilson_keys(f"{p}.right_cause", pooled["right_cause"], pooled["cause_cases"]))
    k.update(wilson_keys(f"{p}.wrong_confident", pooled["wrong_confident"], pooled["cases"]))
    k.update(wilson_keys(f"{p}.abstained", pooled["abstained"], pooled["cases"]))
    k.update(wilson_keys(f"{p}.correct_strict", pooled["correct_strict"], pooled["cases"]))
    for arm in ("t", "tplus"):
        a = pooled[arm]
        q = f"{p}.{'T' if arm == 't' else 'Tplus'}"
        k.update({f"{q}.{m}": a[m] for m in ("right_strict", "right_frac", "wrong_any", "wrong_frac", "abstained")})
        k.update(wilson_keys(f"{q}.right_strict", a["right_strict"], pooled["cause_cases"]))
        k.update(wilson_keys(f"{q}.wrong_any", a["wrong_any"], pooled["cases"]))
        k.update(wilson_keys(f"{q}.abstained", a["abstained"], pooled["cases"]))
    return k


def _deep_fresh_hop_keys() -> dict:
    """deep.fresh.hops.<k>.cause_cases: the headline deep worlds that have a cause, per hop count (the right_cause
    denominator; hops.<k>.cases counts causeless worlds too), and deep.fresh.nohops.*: worlds with a cause but no hop
    count (weak_link). Hops come from the seeded generator, joined to deep_fresh_detail.json by world id."""
    import deep_bench

    d = _side("deep_fresh_detail.json")
    if not (d and d.get("rows") and d.get("seed") is not None):
        return {}
    hops = {w["id"]: w["hops"] for w in deep_bench.generate(seed=int(d["seed"]))}
    k: dict = {}
    for r in d["rows"]:
        if not r.get("has_cause"):
            continue
        h = hops.get(r["id"])
        p = f"deep.fresh.hops.{h}" if h is not None else "deep.fresh.nohops"
        k[f"{p}.cause_cases"] = k.get(f"{p}.cause_cases", 0) + 1
        if h is None:
            k[f"{p}.right_cause"] = k.get(f"{p}.right_cause", 0) + int(bool(r.get("right_cause")))
    return k


def _seeds2_keys(sb: dict) -> dict:
    """seeds2.deep.* (addendum 2026-10-16 item 2: 8 more deep-bench seeds) and seedsall.deep.* (those plus the three
    earlier new seeds): pooled, per category, with the not-confident acceptances split as for seeds.deep."""
    import deep_bench
    import seed_bench

    s2 = _side("seed_bench2.json")
    if not (s2 and s2.get("deep")):
        return {}
    rows2 = [r for v in s2["deep"].values() for r in v["rows"]]
    k = _pooled_deep_keys("seeds2.deep", seed_bench.summary(rows2))
    k["seeds2.deep.seeds"] = len(s2["deep"])
    k["seeds2.deep.complete"] = bool(s2.get("complete"))
    for cat in sorted({r["category"] for r in rows2}):
        x = seed_bench.summary([r for r in rows2 if r["category"] == cat])
        for m in ("cases", "cause_cases", "right_cause", "wrong_confident", "abstained", "ok"):
            k[f"seeds2.deep.{cat}.{m}"] = x[m]
        for arm in ("t", "tplus"):
            k[f"seeds2.deep.{cat}.{'T' if arm == 't' else 'Tplus'}.wrong_any"] = x[arm]["wrong_any"]
            k[f"seeds2.deep.{cat}.{'T' if arm == 't' else 'Tplus'}.right_strict"] = x[arm]["right_strict"]
    acc = {"expected_cause": 0, "other_faulty_change": 0, "bystander": 0}
    for seed, v in s2["deep"].items():
        for kk, n in seed_bench.classify_acceptances(v["rows"], deep_bench.generate(seed=int(seed))).items():
            acc[kk] += n
    k.update({f"seeds2.deep.accepted_nc.{kk}": n for kk, n in acc.items()})
    k.update(wilson_keys("seeds2.deep.accepted_nc.bystander", acc["bystander"], len(rows2)))
    rows1 = [r for v in (sb or {}).get("deep", {}).values() for r in v["rows"]]
    if rows1:
        k.update(_pooled_deep_keys("seedsall.deep", seed_bench.summary(rows1 + rows2)))
        k["seedsall.deep.seeds"] = len(s2["deep"]) + len(sb["deep"])
    return k


def llm_product_keys() -> dict:
    """llm_product.<decisive|deep>.<all|category>.* (addenda 2026-10-18 14:16 and 14:31 IST): the product with the LLM
    driving (LLMInvestigator + the gate), from evals/results/llm_product.json and llm_product_deep.json (paid,
    owner-approved; the deep run covers the two_causes_chain and weak_link worlds only)."""
    k: dict = {}
    for bench, name in (("decisive", "llm_product.json"), ("deep", "llm_product_deep.json"),
                        ("deep_fix", "llm_product_deep_fix.json")):
        x = _side(name)
        if not x or not x.get("rows"):
            continue
        rows, p = x["rows"], f"llm_product.{bench}"
        k.update({f"{p}.model": x.get("model"), f"{p}.complete": bool(x.get("complete")),
                  f"{p}.usd": round(sum(r["usd"] for r in rows), 2),
                  f"{p}.tool_calls_median": (x.get("summary") or {}).get("tool_calls_median")})
        groups = {"all": rows, **{c: [r for r in rows if r["category"] == c] for c in sorted({r["category"] for r in rows})}}
        for g, rs in groups.items():
            q = f"{p}.{g}"
            k[f"{q}.cases"] = len(rs)
            for m in ("right_cause", "wrong_confident", "abstained", "ok"):
                if m in rs[0]:
                    k[f"{q}.{m}"] = sum(bool(r[m]) for r in rs)
            k.update(wilson_keys(f"{q}.right_cause", k[f"{q}.right_cause"], len(rs)))
            k.update(wilson_keys(f"{q}.wrong_confident", k[f"{q}.wrong_confident"], len(rs)))
    return k


def llm_deep_keys() -> dict:
    """llm_deep.<bench>.<all|category>.* (addendum 2026-10-16 item 1: the LLM alone on the deep and decisive benches),
    from evals/results/llm_deep.json (a paid run, owner-approved); the dry run's estimate as llm_deep_dry.<bench>.*."""
    k: dict = {}
    for bench, d in (_side("llm_deep_dryrun.json") or {}).items():
        k[f"llm_deep_dry.{bench}.worlds"] = d["n"]
        k[f"llm_deep_dry.{bench}.est_usd"] = d["est_usd"]
        k[f"llm_deep_dry.{bench}.est_input_tokens"] = d["est_input_tokens"]
    side = _side("llm_deep.json")
    for bench, b in (side.get("benches") or {}).items():
        rows = list(b.get("worlds", {}).values())
        if not rows:
            continue
        p = f"llm_deep.{bench}"
        k[f"{p}.model"], k[f"{p}.prompt_version"] = side.get("model"), side.get("prompt_version")
        k[f"{p}.complete"] = bool(b.get("complete"))
        groups = {"all": rows, **{c: [r for r in rows if r["category"] == c] for c in sorted({r["category"] for r in rows})}}
        for g, rs in groups.items():
            q = f"{p}.{g}"
            cc = sum(1 for r in rs if r["has_cause"])
            k[f"{q}.cases"], k[f"{q}.cause_cases"] = len(rs), cc
            for m in ("right_cause", "wrong_confident", "abstained", "no_incident", "unparsed", "named_unknown", "ok"):
                if m in rs[0]:
                    k[f"{q}.{m}"] = sum(bool(r[m]) for r in rs)
            k.update(wilson_keys(f"{q}.right_cause", k[f"{q}.right_cause"], cc))
            k.update(wilson_keys(f"{q}.wrong_confident", k[f"{q}.wrong_confident"], len(rs)))
            k.update(wilson_keys(f"{q}.abstained", k[f"{q}.abstained"], len(rs)))
        tin = [r["usage"]["input_tokens"] for r in rows if r.get("usage")]
        tout = [r["usage"]["output_tokens"] for r in rows if r.get("usage")]
        k[f"{p}.tokens_in_median"] = statistics.median(tin) if tin else None
        k[f"{p}.tokens_out_median"] = statistics.median(tout) if tout else None
        k[f"{p}.seconds_median"] = statistics.median([r["seconds"] for r in rows])
        k[f"{p}.prompts_match_dry_run"] = all(r.get("matches_dry_run") for r in rows)
        sp = sum(x.get("spent_usd", 0.0) for x in b.get("runs", []))
        k[f"{p}.cost_usd"] = round(sp, 2)
    return k


OTEL_ARMS = (("faultline", "faultline"), ("faultline_prefix", "faultline_prefix"), ("t", "T"), ("tplus", "Tplus"), ("n", "N"))


def udf_equivalence_keys(x: dict | None = None) -> dict:
    """udf.eq.*: what FalkorDB now computes in one query (ranking by our `faultline` UDF library, the min-cut) against
    the previous Python code
    (evals/udf_equivalence.py → evals/results/udf_equivalence.json): identical answers / calls, per tool."""
    x = _side("udf_equivalence.json") if x is None else x
    if not x:
        return {}
    k = {"udf.eq.texts": x.get("texts")}
    for tool in ("blast", "notify", "find", "cut"):
        v = x.get(tool) or {}
        k[f"udf.eq.{tool}.k"], k[f"udf.eq.{tool}.n"] = v.get("k"), v.get("n")
        # the calls whose previous-code answer was not empty: an empty answer equal to an empty answer proves little
        k[f"udf.eq.{tool}.nonempty_k"], k[f"udf.eq.{tool}.nonempty"] = v.get("nonempty_k"), v.get("nonempty")
    k["udf.eq.notify.with_oncall"] = (x.get("notify") or {}).get("with_oncall")
    k["udf.eq.cut.refused"] = (x.get("cut") or {}).get("refused")
    return k


def faultbench_otel_keys(x: dict | None = None, dry: dict | None = None) -> dict:
    """otel.* (PREREGISTRATION addendum 2026-10-16 23:00 IST): FaultBench-OTel, fault injection into the real
    OpenTelemetry Demo with real telemetry (evals/faultbench_otel.py → evals/results/faultbench_otel.json). Right cause
    over the detected fault windows; wrong blames and abstentions over every scored window (fault + control); blame-free
    controls over the controls; each with its Wilson 95 % interval."""
    x = _side("faultbench_otel.json") if x is None else x
    dry = _side("faultbench_otel_llm_dryrun.json") if dry is None else dry
    k: dict = {}
    if dry:
        k["otel.llm_dry.windows"], k["otel.llm_dry.est_usd"] = dry.get("n"), dry.get("est_usd")
    if not x or not x.get("rows"):
        return k
    # windows set aside for an infrastructure failure: excluded rows still in place, plus earlier recordings moved aside
    k["otel.excluded"] = sum(1 for r in x["rows"] if r.get("excluded")) + len(x.get("excluded_windows") or [])
    rows = [r for r in x["rows"] if not r.get("excluded")]
    scored = [r for r in rows if r.get("detected")]
    faults = [r for r in scored if r["kind"] == "fault"]
    ctl = [r for r in scored if r["kind"] == "control"]
    k.update({"otel.demo": x.get("demo"), "otel.seed": x.get("seed"), "otel.windows": len(rows),
              "otel.fault_windows": sum(r["kind"] == "fault" for r in rows), "otel.detected": len(faults),
              "otel.controls": len(ctl), "otel.scored": len(scored),
              "otel.faults": len({r["fault"] for r in rows if r["kind"] == "fault"})})
    for arm, name in OTEL_ARMS:
        p = f"otel.{name}"
        rc = sum(r[arm]["right_cause"] for r in faults)
        wr = sum(r[arm]["wrong"] for r in scored)
        ab = sum(r[arm]["abstained"] for r in scored)
        bf = sum(r[arm]["blame_free"] for r in ctl)
        k.update({f"{p}.right_cause": rc, f"{p}.wrong": wr, f"{p}.abstained": ab, f"{p}.control_blame_free": bf,
                  f"{p}.wrong_fault": sum(r[arm]["wrong"] for r in faults),
                  f"{p}.wrong_control": sum(r[arm]["wrong"] for r in ctl)})
        k.update(wilson_keys(f"{p}.right_cause", rc, len(faults)))
        k.update(wilson_keys(f"{p}.wrong", wr, len(scored)))
        k.update(wilson_keys(f"{p}.abstained", ab, len(scored)))
        k.update(wilson_keys(f"{p}.control_blame_free", bf, len(ctl)))
        if not arm.startswith("faultline"):
            k[f"{p}.right_frac"] = round(sum(r[arm].get("right_frac", 0.0) for r in faults), 2)
    for flag in sorted({r["fault"] for r in rows if r["kind"] == "fault"}):
        rs = [r for r in rows if r["kind"] == "fault" and r["fault"] == flag]
        d = [r for r in rs if r.get("detected")]
        q = f"otel.fault.{flag}"
        k[f"{q}.windows"], k[f"{q}.detected"] = len(rs), len(d)
        for arm, name in OTEL_ARMS:
            for m in ("right_cause", "wrong", "abstained"):
                k[f"{q}.{name}.{m}"] = sum(r[arm][m] for r in d)
    acc = [(r, c) for r in scored for c in r.get("accepted_nc") or []]   # accepted NOT_CONFIDENT: the cause or a bystander
    k["otel.accepted_nc.cause"] = sum(1 for r, c in acc if c == r.get("cause"))
    k["otel.accepted_nc.bystander"] = sum(1 for r, c in acc if c != r.get("cause"))
    for arm in ("faultline", "faultline_prefix"):   # fault windows the product called NO_INCIDENT (a miss, not an abstention)
        k[f"otel.{arm}.no_incident_fault"] = sum(r[arm]["no_incident"] for r in faults)
    # what the gate's sweep did with each decoy (every recorded change but the cause) in the shipped product, and with
    # T+'s wrong picks: the graph's share of the work on a real system (G2 = no causal path; G4 = origin test)
    def step(why: str) -> str:
        m = re.match(r"eliminated: (G\d)", why or "")
        return m.group(1) if m else ("candidate" if (why or "").startswith("candidate") else "not_swept")
    decoys: dict[str, int] = {}
    tplus_wrong: dict[str, int] = {}
    for r in scored:
        sweep = {c: w for inc in (r.get("product") or {}).get("incidents") or [] for c, w in (inc.get("sweep") or {}).items()}
        for ch in r.get("changes") or []:
            if ch["change"] != r.get("cause"):
                s_ = step(sweep.get(ch["change"], ""))
                decoys[s_] = decoys.get(s_, 0) + 1
        if r["tplus"]["wrong"]:
            for pick in r["tplus"].get("tied") or []:
                if pick != r.get("cause"):
                    s_ = step(sweep.get(pick, ""))
                    tplus_wrong[s_] = tplus_wrong.get(s_, 0) + 1
    k["otel.gate.decoys"] = sum(decoys.values())
    for s_ in ("G2", "G4", "G5", "candidate", "not_swept"):
        k[f"otel.gate.decoys.{s_}"] = decoys.get(s_, 0)
        k[f"otel.gate.tplus_wrong_picks.{s_}"] = tplus_wrong.get(s_, 0)
    k["otel.gate.tplus_wrong_picks"] = sum(tplus_wrong.values())
    # windows whose end-of-slot container snapshot shows a restarted or OOM-killed container (the stack as it ran)
    k["otel.windows_after_restart"] = sum(1 for r in rows if any(h.get("restarts") or h.get("oom")
                                                                 for h in (r.get("health") or {}).values()))
    return k


def oncall_keys(x: dict | None = None) -> dict:
    """oncall.* (PREREGISTRATION addendum 2026-10-17): the scripted on-call night (evals/oncall_night.py →
    evals/results/oncall_night.json): each pre-registered step's pass flag, who was paged and woken, the escalation, the
    contract's use, the negative cases that fired (expected 0), and MTTA / MTTR read back from the graph."""
    x = _side("oncall_night.json") if x is None else x
    if not x or not x.get("steps"):
        return {}
    st, inc = x["steps"], x.get("incidents") or {}
    stats = x.get("stats") or {}
    p = "oncall.night"
    k: dict = {f"{p}.steps_passed": x.get("passed"), f"{p}.steps": x.get("total"),
               f"{p}.negatives": x.get("negatives"), f"{p}.negatives_fired": x.get("negatives_fired"),
               f"{p}.seconds": x.get("seconds"), f"{p}.channels": ",".join(x.get("channels") or []),
               f"{p}.ack_window_min": x.get("ack_window_min"),
               f"{p}.inc1.pages": (inc.get("1") or {}).get("pages"),
               f"{p}.inc1.people_woken": len((inc.get("1") or {}).get("woken") or []),
               f"{p}.escalations": (st.get("2_no_ack_escalates") or {}).get("escalations"),
               f"{p}.inc2.people_woken": len((inc.get("2") or {}).get("woken") or []),
               f"{p}.inc2.notices": (inc.get("2") or {}).get("notices"),
               f"{p}.inc2.verdict": (inc.get("2") or {}).get("verdict"),
               f"{p}.contract.uses": (st.get("5_same_fault_under_contract") or {}).get("uses"),
               f"{p}.pages": stats.get("pages"), f"{p}.people_paged": stats.get("people_paged"),
               f"{p}.handled_under_contract": stats.get("handled_under_contract"),
               f"{p}.mtta_ms": stats.get("mtta_ms"), f"{p}.mttr_ms": stats.get("mttr_ms"),
               f"{p}.mtta_matches_pages": stats.get("mtta_ms") is not None and stats.get("mtta_ms") == x.get("mtta_expected_ms"),
               f"{p}.acked_incidents": stats.get("acked_incidents"), f"{p}.scripted_ack_ms": x.get("scripted_ack_ms")}
    for name, v in st.items():
        k[f"{p}.step.{name}"] = bool(v.get("pass"))
    if x.get("earlier_runs"):
        k[f"{p}.first_run.steps_passed"] = x["earlier_runs"][0]["passed"]
        k[f"{p}.first_run.negatives_fired"] = x["earlier_runs"][0]["negatives_fired"]
        k[f"{p}.runs"] = len(x["earlier_runs"]) + 1
        k[f"{p}.runs_all_negatives_held"] = all(int(r.get("negatives_fired") or 0) == 0 for r in x["earlier_runs"]) \
            and x.get("negatives_fired") == 0
    return k


def oncall_markdown(s: dict) -> list[str]:
    p = "oncall.night"
    if s.get(f"{p}.steps") is None:
        return []
    L = ["", "## On-call: a scripted on-call night (evals/oncall_night.py)", "",
         "The real API in-process, the keyless investigator, clean rooms; the on-call home graph is its own copy of "
         f"golden_acme. Delivery channels: {s[f'{p}.channels']} (none external configured). Pre-registered steps "
         f"passed: {s[f'{p}.steps_passed']} of {s[f'{p}.steps']}; negative cases where a contract fired: "
         f"{s[f'{p}.negatives_fired']} of {s[f'{p}.negatives']}.", "",
         "| step | pass |", "|---|---|"]
    for k in sorted(x for x in s if x.startswith(f"{p}.step.")):
        L.append(f"| {k.removeprefix(f'{p}.step.')} | {'yes' if s[k] else 'NO'} |")
    L += ["", f"Incident 1 paged {s[f'{p}.inc1.people_woken']} people (the failing component's owner on-call and the "
              f"on-call of every team owning something in its blast radius), escalated {s[f'{p}.escalations']} time(s) "
              f"after the {s[f'{p}.ack_window_min']}-minute urgent window, and stopped at the ack. The same fault again "
              f"woke {s[f'{p}.inc2.people_woken']} people ({s[f'{p}.inc2.notices']} contract notices) and was verified "
              f"{s[f'{p}.inc2.verdict']} under the contract. Over the night: {s[f'{p}.pages']} pages to "
              f"{s[f'{p}.people_paged']} people; MTTA {s[f'{p}.mtta_ms']} ms over {s[f'{p}.acked_incidents']} acknowledged "
              f"incident(s) (read back from the graph; equal to the mean computed from the pages the API returned = "
              f"{s[f'{p}.mtta_matches_pages']}; incident 1's scripted acknowledgement was {s[f'{p}.scripted_ack_ms']} ms); "
              f"MTTR {s[f'{p}.mttr_ms']} ms (in-process wall clock, not a production figure)."]
    if s.get(f"{p}.first_run.steps_passed") is not None:
        L += ["", f"This is run {s[f'{p}.runs']} (every run is kept in evals/results/oncall_night.json). The first passed "
                  f"{s[f'{p}.first_run.steps_passed']} of {s[f'{p}.steps']} steps (its one failure a harness set-up "
                  "check); the second passed every step before approval was made to count as the acknowledgement; the "
                  "third passed every step but read the night's numbers from every graph of the tenant; the fourth read "
                  "them from the night's own graphs; this one runs on the product after the security review's fixes "
                  "(PREREGISTRATION amendments 1–4, 2026-10-17). No contract fired in a negative case in any run: "
                  f"{s[f'{p}.runs_all_negatives_held']}."]
    return L


def learn_keys(x: dict | None = None) -> dict:
    """learn.* (PREREGISTRATION addendum 2026-10-17): the learning night (evals/learning_night.py →
    evals/results/learning_night.json): each pre-registered step's pass flag; cold vs warm top option (Wilson 95 %);
    where the plan's top changed and where the contract suggestion first appeared; guideline override codes; MTTA
    before and after the responder was learned; what forgetting a person deleted; knowledge gaps; recency-aware recall."""
    x = _side("learning_night.json") if x is None else x
    if not x or not x.get("steps"):
        return {}
    st, ph = x["steps"], x.get("phases") or {}
    ch, rt = ph.get("choices") or {}, ph.get("routing") or {}
    cold, warm, plans = ch.get("cold") or [], ch.get("warm") or [], ch.get("learning") or []
    k: dict = {"learn.night.steps_passed": x.get("passed"), "learn.night.steps": x.get("total"),
               "learn.night.seconds": x.get("seconds"),
               "learn.choices.scenarios": ",".join(sorted({c["scenario"] for c in cold})),
               "learn.choices.cold_trials": len(cold), "learn.choices.warm_trials": len(warm),
               "learn.choices.cold_top_rollback": sum(1 for c in cold if c["top"] == "rollback_deploy"),
               "learn.choices.warm_top_flag": sum(1 for c in warm if c["top"] == "flip_flag"),
               "learn.choices.learning_plans": len(plans),
               "learn.choices.flip_at_plan": next((p["plan"] for p in plans if p["top"] == "flip_flag"), None),
               "learn.choices.pref_min_n": (x.get("weights") or {}).get("pref_min_n"),
               "learn.choices.why_line": (warm[0].get("line") if warm else None),
               "learn.suggest.k": (x.get("weights") or {}).get("contract_suggest_k"),
               "learn.suggest.first_at_plan": next((p["plan"] for p in plans if p["suggested"]), None),
               "learn.suggest.before_k": sum(1 for p in plans if p["suggested"]
                                             and p["plan"] <= int((x.get("weights") or {}).get("contract_suggest_k") or 0)),
               "learn.routing.incidents": len(rt.get("incidents") or []),
               "learn.routing.mtta_before_ms": rt.get("mtta_before_ms"), "learn.routing.mtta_after_ms": rt.get("mtta_after_ms"),
               "learn.routing.mtta_before_min": round(rt["mtta_before_ms"] / 60_000, 1) if rt.get("mtta_before_ms") else None,
               "learn.routing.mtta_after_min": round(rt["mtta_after_ms"] / 60_000, 1) if rt.get("mtta_after_ms") else None,
               "learn.routing.first_wave_from": next((i for i, r in enumerate(rt.get("incidents") or [], 1)
                                                      if r.get("learned_first")), None),
               "learn.routing.oncall_paged_every_incident": all(r.get("oncall_paged") for r in rt.get("incidents") or []),
               "learn.routing.resp_min_n": (x.get("weights") or {}).get("resp_min_n")}
    k.update(wilson_keys("learn.choices.cold_top_rollback", k["learn.choices.cold_top_rollback"], len(cold)))
    k.update(wilson_keys("learn.choices.warm_top_flag", k["learn.choices.warm_top_flag"], len(warm)))
    fg = ph.get("forget") or {}
    k.update({"learn.forget.events": (fg.get("dry_run") or {}).get("n_events"),
              "learn.forget.events_left": (fg.get("receipt") or {}).get("events_left"),
              "learn.forget.preferences_still_citing": (fg.get("receipt") or {}).get("preferences_still_citing"),
              "learn.forget.receipt_in_audit": fg.get("receipt_in_audit"),
              "learn.forget.top_after": (st.get("forget_reverts_and_receipts") or {}).get("top_after")})
    gp = ph.get("gaps") or {}
    k.update({"learn.gaps.count": len(gp.get("gaps") or []),
              "learn.gaps.asked_max": max([int(g["n"]) for g in gp.get("gaps") or []] or [0]),
              "learn.gaps.answered_not_gap": all(not q["gap"] for q in gp.get("asked") or [] if q["kind"] != "gap")})
    rc = ph.get("recall") or {}
    pairs = rc.get("pairs") or []
    ages = rc.get("ages") or {}
    with_prec = [v for v in ages.values() if v.get("0.0", {}).get("top")]
    k.update({"learn.recall.trials": len(pairs), "learn.recall.warm_top_first": sum(1 for p in pairs if p["warm_top_is_first"]),
              "learn.recall.gate_identical": sum(1 for p in pairs if p["gate_identical"]),
              "learn.recall.pairs": ",".join(sorted({p["pair"] for p in pairs})),
              "learn.recall.scenarios_with_precedents": len(with_prec),
              "learn.recall.top_changed": sum(1 for v in with_prec if v.get("top_changed"))})
    for sid, v in ages.items():
        for wr, row in v.items():
            if isinstance(row, dict) and row.get("age_days") is not None:
                k[f"learn.recall.{sid.lower()}.w{wr.replace('.', '')}.top_age_days"] = row["age_days"]
    for name, v in st.items():
        k[f"learn.night.step.{name}"] = bool(v.get("pass"))
    if x.get("earlier_runs"):
        k["learn.night.runs"] = len(x["earlier_runs"]) + 1
    return k


def _vcfg(cfg: str) -> str:
    """'10' → 'ef10'; 'm32_efc400_ef100' stays (claim keys never start with a digit)."""
    return f"ef{cfg}" if cfg.isdigit() else cfg


def vector_recall_keys(x: dict | None = None) -> dict:
    """vector.*: evals/vector_recall.py → evals/results/vector_recall.json: the HNSW index's recall@10 against
    an exact cosine scan, per set (seeded Incident / Postmortem / Runbook / IntentExemplar vectors of acme and globex, and
    a 2,040-incident history) and per configuration (efRuntime 10…200 at M 16 / efConstruction 200; M 32 /
    efConstruction 400), the minimum over sets, the default and the configuration chosen for schema.cypher."""
    x = _side("vector_recall.json") if x is None else x
    if not x or not x.get("sets"):
        return {}
    k: dict = {}
    sets = x["sets"]
    for name, st in sets.items():
        k[f"vector.{name}.vectors"], k[f"vector.{name}.queries"] = st["vectors"], st["queries"]
        for cfg, v in st["recall"].items():
            k[f"vector.recall_at_10.{name}.{_vcfg(cfg)}"] = v
    for cfg in x.get("configs") or []:
        k[f"vector.recall_at_10.min.{_vcfg(cfg)}"] = min(s["recall"][cfg] for s in sets.values())
    k["vector.recall_at_10.default"] = k.get(f"vector.recall_at_10.min.{_vcfg(str(x.get('default', '10')))}")
    if x.get("chosen"):
        k["vector.recall_at_10.tuned"] = k.get(f"vector.recall_at_10.min.{_vcfg(x['chosen'])}")
        k["vector.chosen"] = _vcfg(x["chosen"])
    sch = x.get("schema") or {}
    if sch:
        k["vector.schema"] = f"M {sch.get('M')}, efConstruction {sch.get('efConstruction')}, efRuntime {sch.get('efRuntime')}"
    k["vector.sets"], k["vector.queries"] = len(sets), sum(s["queries"] for s in sets.values())
    return k


def t2_keys(x: dict | None = None) -> dict:
    """t2.* : the T2 go/no-go checklist fixed before the hackathon as run by evals/t2_gonogo.py (evals/results/t2_gonogo.json)."""
    x = _side("t2_gonogo.json") if x is None else x
    if not x or not x.get("items"):
        return {}
    it = x["items"]
    k: dict = {"t2.green": x.get("green"), "t2.items": x.get("total")}
    for name, v in it.items():
        k[f"t2.{name}.green"] = bool(v.get("green"))
    s13 = it.get("s13_concurrency") or {}
    k.update({"t2.s13.rounds_one_owner": s13.get("rounds_with_exactly_one_owner"), "t2.s13.rounds": s13.get("rounds"),
              "t2.s13.lost_updates": s13.get("lost_updates"), "t2.s13.workers": s13.get("workers")})
    s7 = (it.get("s7_isolation") or {}).get("isolation_suite") or {}
    k.update({"t2.s7.passed": s7.get("passed"), "t2.s7.failed": s7.get("failed"),
              "t2.s7.acl_users_ok": ((it.get("s7_isolation") or {}).get("through_ro_acl_users") or {}).get("ok")})
    live = ((it.get("s10_forget_receipt") or {}).get("live_url") or {})
    k.update({"t2.s10.live_dry_run_status": (live.get("forget_dry_run") or {}).get("status"),
              "t2.s10.live_learned_status": live.get("learned_endpoint_status"),
              "t2.session.sessions": len((it.get("session_turns") or {}).get("sessions") or []),
              "t2.session.turns": (it.get("session_turns") or {}).get("turns")})
    return k


def learn_markdown(s: dict) -> list[str]:
    p = "learn.night"
    if s.get(f"{p}.steps") is None:
        return []
    L = ["", "## Learning from the people who use it (evals/learning_night.py)", "",
         "The real API in-process, the keyless investigator, clean rooms, off the public demo (trusted runs); what is "
         "learned lives in a fresh copy of golden_acme per phase. Pre-registered steps passed: "
         f"{s[f'{p}.steps_passed']} of {s[f'{p}.steps']}.", "", "| step | pass |", "|---|---|"]
    for key in sorted(x for x in s if x.startswith(f"{p}.step.")):
        L.append(f"| {key.removeprefix(f'{p}.step.')} | {'yes' if s[key] else 'NO'} |")
    L += ["", f"Choices ({s['learn.choices.scenarios']}, N = 3 each): the top option was the rollback in "
              f"{s['learn.choices.cold_top_rollback']} of {s['learn.choices.cold_trials']} cold runs and the flag flip in "
              f"{s['learn.choices.warm_top_flag']} of {s['learn.choices.warm_trials']} warm runs after the on-call approved "
              f"the flag on {s['learn.choices.learning_plans']} incidents; the top changed on plan "
              f"{s['learn.choices.flip_at_plan']} (after learn.pref_min_n = {s['learn.choices.pref_min_n']} choices). The "
              f"standing-approval suggestion first appeared on plan {s['learn.suggest.first_at_plan']} (K = "
              f"{s['learn.suggest.k']}; shown before K: {s['learn.suggest.before_k']}). Paging: the responder who answers was "
              f"paged in the first wave from incident {s['learn.routing.first_wave_from']} on; MTTA "
              f"{s['learn.routing.mtta_before_min']} min before → {s['learn.routing.mtta_after_min']} min after (scripted "
              f"clock: a check of the mechanism, not a response-time claim); the rota on-call was paged on every incident: "
              f"{s['learn.routing.oncall_paged_every_incident']}. Forgetting the on-call's influence deleted "
              f"{s['learn.forget.events']} events, left {s['learn.forget.events_left']}, and the plan's top went back to "
              f"{s['learn.forget.top_after']}. Knowledge gaps: {s['learn.gaps.count']}. Recall (S1→S1b, S3→S3b, N = 3): "
              f"warm top precedent = the first incident in {s['learn.recall.warm_top_first']} of {s['learn.recall.trials']}, "
              f"gate verdicts identical in {s['learn.recall.gate_identical']} of {s['learn.recall.trials']}."]
    if s.get("t2.items"):
        L += ["", f"T2 go/no-go (evals/t2_gonogo.py): {s['t2.green']} of {s['t2.items']} green."]
    return L


def graphrag_keys(x: dict | None = None, audit: dict | None = None) -> dict:
    """graphrag.* (PREREGISTRATION addendum 2026-10-17 23:35 IST): the company brain (fl) against FalkorDB's
    GraphRAG-SDK (sdk) on the same questions (evals/graphrag_sdk_arm.py → evals/results/graphrag_sdk.json): per set
    and arm, correct k/n (Wilson 95 %), honest refusals, sources named, fabricated ids, latency, tokens and US$; the
    SDK's ingestion cost and graph size; paired outcomes; whether the run meets the pre-registered clean criteria."""
    if x is None:
        x, audit = _side("graphrag_sdk.json"), _side("graphrag_sdk_audit.json") if audit is None else audit
    if not x or not x.get("sets"):
        return {}
    cfg, ing, kg, me = x.get("config") or {}, x.get("ingest") or {}, x.get("kg") or {}, x.get("meter") or {}
    cost = ing.get("cost") or {}
    labels, rels = kg.get("labels") or {}, kg.get("relationships") or {}
    deleted = x.get("graphs_deleted") or {}
    k: dict = {"graphrag.model": cfg.get("model"), "graphrag.sdk_version": cfg.get("sdk_version"),
               "graphrag.cap_usd": cfg.get("cap_usd"),
               "graphrag.corpus.docs": len((x.get("corpus") or {}).get("docs") or []),
               "graphrag.corpus.documents": (x.get("corpus") or {}).get("documents"),
               "graphrag.corpus.facts_docs": (x.get("corpus") or {}).get("facts_docs"),
               "graphrag.corpus.words": (x.get("corpus") or {}).get("words"),
               "graphrag.corpus.chunks": x.get("chunks"),
               "graphrag.ingest.seconds": ing.get("seconds"), "graphrag.ingest.s_per_doc": ing.get("s_per_doc"),
               "graphrag.ingest.usd": cost.get("usd"), "graphrag.ingest.tokens_in": cost.get("in"),
               "graphrag.ingest.tokens_out": cost.get("out"), "graphrag.ingest.calls": cost.get("calls"),
               "graphrag.ingest.doc_errors": len(ing.get("doc_errors") or []),
               "graphrag.ingest.step_failures": x.get("step_failures"),
               "graphrag.kg.entities": labels.get("__Entity__"), "graphrag.kg.chunks": labels.get("Chunk"),
               "graphrag.kg.relates": rels.get("RELATES"),
               "graphrag.usd_total": round(me["spent_usd"], 4) if me.get("spent_usd") is not None else None,
               "graphrag.calls": me.get("calls"), "graphrag.refused": me.get("refused"),
               "graphrag.truncated": me.get("truncated"), "graphrag.transport_retries": me.get("transport_retries"),
               "graphrag.stopped": bool(x.get("stopped")),
               "graphrag.graphs_deleted": bool(deleted) and all(deleted.values())}
    for s, v in x["sets"].items():
        p = f"graphrag.{s}"
        k.update({f"{p}.questions": v["questions"], f"{p}.answerable": v["answerable"],
                  f"{p}.unanswerable": v["unanswerable"],
                  f"{p}.run": bool((v.get("sdk") or {}).get("complete"))})
        for arm in ("fl", "sdk"):
            a = v.get(arm) or {}
            if not a.get("complete"):
                k[f"{p}.{arm}.answered"] = a.get("answered", 0)
                continue
            for m in ("correct", "answerable_correct", "unanswerable_honest", "unanswerable_honest_strict",
                      "names_sources", "answers_with_fabricated_ids", "false_abstain", "ms_p50", "ms_p95",
                      "precision_mean", "correct_textrule", "correct_ids_only", "answers_with_name_mapping", "errors",
                      "usd", "usd_per_question", "tokens_in", "tokens_out"):
                if m in a:
                    k[f"{p}.{arm}.{m}"] = a[m]
            k[f"{p}.{arm}.s_p50"] = round(a["ms_p50"] / 1000, 2) if a.get("ms_p50") is not None else None
            k.update(wilson_keys(f"{p}.{arm}.correct", a["correct"], v["questions"]))
        for m, val in (v.get("paired") or {}).items():
            k[f"{p}.paired.{m}"] = val
        if (v.get("sdk") or {}).get("complete"):
            for kind, e in (v.get("by_kind") or {}).items():
                k.update({f"{p}.kind.{kind}.{m}": e[m] for m in ("n", "fl", "sdk")})
    for sk in x.get("skipped_sets") or []:
        k[f"graphrag.{sk['set']}.skipped_projection_usd"] = sk.get("projection_usd")
    au = audit or {}   # post hoc, NOT pre-registered: credited answers with a wrong or missing key claim
    for arm in ("fl", "sdk") if au else ():
        a, s = au[arm], au["set"]
        k[f"graphrag.{s}.audit.{arm}.wrong_claim"] = len(a["wrong_or_missing_key_claim"])
        k[f"graphrag.{s}.audit.{arm}.wrong_claim_ids"] = ",".join(w["id"] for w in a["wrong_or_missing_key_claim"]) or "none"
        k[f"graphrag.{s}.audit.{arm}.credited_and_right"] = a["credited"] - len(a["wrong_or_missing_key_claim"])
    n_chunks = k["graphrag.kg.chunks"] or k["graphrag.corpus.chunks"] or 0
    prim = x["sets"].get("s2") or {}
    k["graphrag.clean"] = bool(not x.get("stopped") and not me.get("refused") and not k["graphrag.ingest.doc_errors"]
                               and n_chunks and (x.get("step_failures") or 0) <= 0.05 * n_chunks
                               and (prim.get("sdk") or {}).get("complete") and not (prim.get("sdk") or {}).get("errors")
                               and k["graphrag.graphs_deleted"])
    return k


def graphrag_markdown(s: dict) -> list[str]:
    if s.get("graphrag.s2.questions") is None:
        return []
    L = ["", "## Company brain vs FalkorDB's GraphRAG-SDK, same questions (evals/graphrag_sdk_arm.py)", "",
         f"GraphRAG-SDK {s['graphrag.sdk_version']} with its default ingestion and retrieval, on "
         f"{s['graphrag.model']}, built its own graph in FalkorDB from the brain's {s['graphrag.corpus.documents']} "
         f"source documents and its facts as {s['graphrag.corpus.facts_docs']} text documents "
         f"({s['graphrag.corpus.words']} words): {s['graphrag.kg.entities']} entities, {s['graphrag.kg.relates']} "
         f"relationships, {s['graphrag.kg.chunks']} chunks, in {s['graphrag.ingest.seconds']} s "
         f"(US${round(s['graphrag.ingest.usd'] or 0, 4)}). Total model spend US${s['graphrag.usd_total']} of a US${s['graphrag.cap_usd']} cap. "
         f"Clean by the pre-registered criteria: {s['graphrag.clean']}.", ""]
    for sid, title in (("s2", "Blind set 2 (primary)"), ("orig", "Original 33 (secondary)")):
        p = f"graphrag.{sid}"
        if s.get(f"{p}.questions") is None:
            continue
        if not s.get(f"{p}.run"):
            L += [f"{title}: not run by the SDK (projected US${s.get(f'{p}.skipped_projection_usd')} over the cap)."
                  if s.get(f"{p}.skipped_projection_usd") is not None else f"{title}: SDK incomplete.", ""]
            continue
        n = s[f"{p}.questions"]
        L += [f"**{title}** ({n} questions, {s[f'{p}.unanswerable']} unanswerable)", "",
              "| | Faultline brain | GraphRAG-SDK |", "|---|---|---|"]
        row = lambda lab, m: L.append(f"| {lab} | {s.get(f'{p}.fl.{m}')} | {s.get(f'{p}.sdk.{m}')} |")  # noqa: E731
        L.append(f"| correct of {n} [95 % CI] | {_kn(s, f'{p}.fl.correct')} | {_kn(s, f'{p}.sdk.correct')} |")
        row("answerable correct", "answerable_correct")
        row(f"unanswerable declined (of {s[f'{p}.unanswerable']})", "unanswerable_honest")
        row("… declined and nothing cited", "unanswerable_honest_strict")
        row(f"answers naming a source id (of {s[f'{p}.answerable']})", "names_sources")
        row("answers with a non-existent id", "answers_with_fabricated_ids")
        row("false refusals on answerable questions", "false_abstain")
        row("citation precision (mean)", "precision_mean")
        L.append(f"| latency p50 / p95 ms | {s.get(f'{p}.fl.ms_p50')} / {s.get(f'{p}.fl.ms_p95')} | "
                 f"{s.get(f'{p}.sdk.ms_p50')} / {s.get(f'{p}.sdk.ms_p95')} |")
        L.append(f"| model US$ (per question) | 0 | {s.get(f'{p}.sdk.usd')} ({s.get(f'{p}.sdk.usd_per_question')}) |")
        L += ["", f"Paired: both right {s.get(f'{p}.paired.both')}, brain only {s.get(f'{p}.paired.fl_only')}, SDK only "
                  f"{s.get(f'{p}.paired.sdk_only')}, neither {s.get(f'{p}.paired.neither')} (exact McNemar p "
                  f"{s.get(f'{p}.paired.mcnemar_p')}). Symmetry checks: the SDK's text rule on the brain's answers "
                  f"{s.get(f'{p}.fl.correct_textrule')}/{n}; the SDK with written ids only (no name mapping) "
                  f"{s.get(f'{p}.sdk.correct_ids_only')}/{n}.", ""]
        kinds = sorted({x.split(".")[3] for x in s if x.startswith(f"{p}.kind.")})
        if kinds:
            L += ["By question kind (brain / SDK of n): " + "; ".join(
                f"{kd} {s[f'{p}.kind.{kd}.fl']}/{s[f'{p}.kind.{kd}.sdk']} of {s[f'{p}.kind.{kd}.n']}" for kd in kinds) + ".", ""]
        if s.get(f"{p}.audit.sdk.wrong_claim") is not None:
            L += [f"Post hoc, not pre-registered (evals/results/graphrag_sdk_audit.json): credited answers that also state "
                  f"something wrong or leave out the key fact: SDK {s[f'{p}.audit.sdk.wrong_claim']} "
                  f"({s[f'{p}.audit.sdk.wrong_claim_ids']}), brain {s[f'{p}.audit.fl.wrong_claim']}. Credited and right: "
                  f"SDK {s[f'{p}.audit.sdk.credited_and_right']}/{n}, brain {s[f'{p}.audit.fl.credited_and_right']}/{n}.", ""]
    return L


def faultbench_otel_markdown(s: dict) -> list[str]:
    if s.get("otel.scored") is None:
        return []
    L = ["", "## FaultBench-OTel: the real OpenTelemetry Demo, real telemetry (evals/faultbench_otel.py)", "",
         f"Real services (OpenTelemetry Demo {s['otel.demo']}, trimmed to fit one laptop), real per-minute server error "
         "rates from its span metrics in Prometheus, the demo's own flagd fault flags as causes, and our own decoy changes "
         f"(a real harmless flag flip and recorded no-op deploys). {s['otel.faults']} faults, {s['otel.fault_windows']} "
         f"fault windows ({s['otel.detected']} paged by the pre-registered page rule) and {s['otel.controls']} no-fault "
         "control windows, one machine. Topology and failure-edge capacities from data/topology/otel-demo.yaml.", "",
         "Faultline is the current product; *as registered* is the product before the zero-baseline fix this bench found "
         "(PREREGISTRATION amendment 2026-10-16 23:45 IST), run on the same windows.", "",
         "| arm | right cause (detected fault windows) | wrong blames (all scored windows) | abstained | missed as NO_INCIDENT | "
         "blame-free controls |", "|---|---|---|---|---|---|"]
    label = {"faultline": "Faultline", "faultline_prefix": "Faultline as registered", "T": "T", "Tplus": "T+",
             "N": "N (recency)"}
    for _, name in OTEL_ARMS:
        p = f"otel.{name}"
        L.append(f"| {label[name]} | {_kn(s, f'{p}.right_cause')} | {_kn(s, f'{p}.wrong')} | {_kn(s, f'{p}.abstained')} | "
                 f"{s.get(f'{p}.no_incident_fault', '—')} | {_kn(s, f'{p}.control_blame_free')} |")
    L += ["", "| fault | windows | paged | Faultline right / wrong / abstained | as registered | T | T+ | N |",
          "|---|---|---|---|---|---|---|---|"]
    for flag in sorted({k.split(".")[2] for k in s if k.startswith("otel.fault.") and k.endswith(".windows")}):
        q = f"otel.fault.{flag}"
        cell = lambda a: f"{s[f'{q}.{a}.right_cause']} / {s[f'{q}.{a}.wrong']} / {s[f'{q}.{a}.abstained']}"  # noqa: E731
        L.append(f"| {flag} | {s[f'{q}.windows']} | {s[f'{q}.detected']} | {cell('faultline')} | "
                 f"{cell('faultline_prefix')} | {cell('T')} | {cell('Tplus')} | {cell('N')} |")
    if s.get("otel.accepted_nc.bystander") is not None:
        L += ["", f"Runs that ended NOT_CONFIDENT having accepted a change without confidence (an abstention by outcome, "
                  f"reported apart as on every bench): the true cause {s['otel.accepted_nc.cause']}, an innocent change "
                  f"{s['otel.accepted_nc.bystander']}."]
    if s.get("otel.llm_dry.est_usd") is not None:
        L += ["", f"The LLM alone on these windows was built and estimated only (no API call): {s['otel.llm_dry.windows']} "
                  f"windows, about ${s['otel.llm_dry.est_usd']} at list price."]
    return L


def new_benches_markdown(s: dict) -> list[str]:
    """RESULTS.md sections for addendum 2026-10-16 (more deep seeds, globex world bench, the LLM on the adversarial
    benches)."""
    L: list[str] = []
    for p, title in (("seeds2.deep", f"Deep bench on {s.get('seeds2.deep.seeds')} more seeds (evals/seed_bench.py --seeds2)"),
                     ("seedsall.deep", f"Deep bench, all {s.get('seedsall.deep.seeds')} non-headline seeds pooled")):
        if not s.get(f"{p}.cases"):
            continue
        L += ["", f"## {title}", "",
              f"{s[f'{p}.cases']} worlds, {s[f'{p}.cause_cases']} with a cause."
              + ("" if p != "seeds2.deep" or s.get("seeds2.deep.complete") else " Partial: not every pre-registered seed has run."), "",
              "| | right cause (worlds with a cause) | wrong blames, all worlds (Faultline: confident; T, T+: any) | abstained |",
              "|---|---|---|---|",
              f"| Faultline | {_kn(s, f'{p}.right_cause')} | {_kn(s, f'{p}.wrong_confident')} | {_kn(s, f'{p}.abstained')} |",
              f"| telemetry only (T) | {_kn(s, f'{p}.T.right_strict')} | {_kn(s, f'{p}.T.wrong_any')} | {_kn(s, f'{p}.T.abstained')} |",
              f"| thresholded telemetry (T+) | {_kn(s, f'{p}.Tplus.right_strict')} | {_kn(s, f'{p}.Tplus.wrong_any')} | "
              f"{_kn(s, f'{p}.Tplus.abstained')} |"]
        if p == "seeds2.deep":
            cats = sorted({kk.split(".")[2] for kk in s if kk.startswith("seeds2.deep.") and kk.endswith(".T.wrong_any")
                           and kk.count(".") == 4})
            L += ["", "| category | worlds | Faultline right | Faultline wrong-confident | abstained | T right | T wrong | T+ wrong |",
                  "|---|---|---|---|---|---|---|---|"]
            for c in cats:
                q = f"seeds2.deep.{c}"
                na = not s[f"{q}.cause_cases"]   # no cause in this category: "right cause" does not apply
                L.append(f"| {c} | {s[f'{q}.cases']} | {'n/a' if na else s[f'{q}.right_cause']} | {s[f'{q}.wrong_confident']} | "
                         f"{s[f'{q}.abstained']} | {'n/a' if na else s[f'{q}.T.right_strict']} | {s[f'{q}.T.wrong_any']} | "
                         f"{s[f'{q}.Tplus.wrong_any']} |")
            L += ["", f"Runs that ended NOT_CONFIDENT having accepted a change: the true cause "
                      f"{s.get('seeds2.deep.accepted_nc.expected_cause')}, a bystander with no fault of its own "
                      f"{s.get('seeds2.deep.accepted_nc.bystander')}."]
    if s.get("world_globex.cases"):
        p = "world_globex"
        L += ["", f"## Independent-parameter worlds on the second tenant (globex, 200 services; evals/world_bench.py "
                  f"--tenant globex, seed {s.get('world_globex.seed')}; not blind)", "",
              "| | right cause (worlds with a cause) | wrong blames, all worlds (Faultline: confident; T, T+: any) | abstained |",
              "|---|---|---|---|",
              f"| Faultline | {_kn(s, f'{p}.right_cause')} | {_kn(s, f'{p}.wrong_confident')} | {_kn(s, f'{p}.abstained')} |",
              f"| T | {_kn(s, f'{p}.T.right_strict')} | {_kn(s, f'{p}.T.wrong_any')} | {s[f'{p}.T.abstained']} |",
              f"| T+ | {_kn(s, f'{p}.Tplus.right_strict')} | {_kn(s, f'{p}.Tplus.wrong_any')} | {s[f'{p}.Tplus.abstained']} |",
              "", "By world kind (Faultline): " + "; ".join(
                  f"{c} {s.get(f'{p}.{c}.cases')} worlds, verdict right {s.get(f'{p}.{c}.verdict_ok')}, wrong "
                  f"{s.get(f'{p}.{c}.wrong_confident')}, abstained {s.get(f'{p}.{c}.abstained')}"
                  for c in ("cause", "unchanged", "quiet")) + ".",
              "", f"Runs that ended NOT_CONFIDENT having accepted a change: the true cause "
                  f"{s.get(f'{p}.accepted_nc.expected_cause')}, a bystander with no fault of its own "
                  f"{s.get(f'{p}.accepted_nc.bystander')}."]
    benches = [b for b in ("deep", "decisive") if s.get(f"llm_deep.{b}.all.cases")]
    if benches or s.get("llm_deep_dry.deep.est_usd") is not None:
        L += ["", "## The LLM alone on the adversarial benches (evals/llm_deep.py; A0 v2 evidence and prompt)", ""]
        if not benches:
            L.append("Built and dry-run; the paid run waits for the owner's approval. Estimate at list price: "
                     + "; ".join(f"{b} {s.get(f'llm_deep_dry.{b}.worlds')} worlds, ${s.get(f'llm_deep_dry.{b}.est_usd')}"
                                 for b in ("deep", "decisive") if s.get(f"llm_deep_dry.{b}.est_usd") is not None) + ".")
        for b in benches:
            p = f"llm_deep.{b}.all"
            fl = ({"rc": _kn(s, "deep.fresh.all.right_cause"), "wc": _kn(s, "deep.fresh.all.wrong_confident"),
                   "ab": _kn(s, "deep.fresh.all.abstained")} if b == "deep" else
                  {"rc": f"{(s.get('decisive.full.g5_only.right_cause') or 0) + (s.get('decisive.full.anomalous_no_path.right_cause') or 0)}/40",
                   "wc": f"{(s.get('decisive.full.g5_only.wrong_confident') or 0) + (s.get('decisive.full.anomalous_no_path.wrong_confident') or 0)}/40",
                   "ab": f"{(s.get('decisive.full.g5_only.abstained') or 0) + (s.get('decisive.full.anomalous_no_path.abstained') or 0)}/40"})
            L += [f"**{b}** ({s[f'{p}.cases']} worlds, {s[f'{p}.cause_cases']} with a cause"
                  + ("" if s.get(f"llm_deep.{b}.complete") else "; partial") + f"; {s.get(f'llm_deep.{b}.model')}, "
                  f"prompt v{s.get(f'llm_deep.{b}.prompt_version')}; median {s.get(f'llm_deep.{b}.tokens_in_median')} input / "
                  f"{s.get(f'llm_deep.{b}.tokens_out_median')} output tokens, {s.get(f'llm_deep.{b}.seconds_median')} s per world; "
                  f"cost ${s.get(f'llm_deep.{b}.cost_usd')})", "",
                  "| | right cause | wrong blames (any named innocent change) | abstained |", "|---|---|---|---|",
                  f"| LLM alone | {_kn(s, f'{p}.right_cause')} | {_kn(s, f'{p}.wrong_confident')} | {_kn(s, f'{p}.abstained')} |",
                  f"| Faultline | {fl['rc']} | {fl['wc']} | {fl['ab']} |"]
            if b == "deep":
                L += [f"| T | {_kn(s, 'deep.fresh.all.T.right_strict')} | {_kn(s, 'deep.fresh.all.T.wrong_any')} | "
                      f"{_kn(s, 'deep.fresh.all.T.abstained')} |",
                      f"| T+ | {_kn(s, 'deep.fresh.all.Tplus.right_strict')} | {_kn(s, 'deep.fresh.all.Tplus.wrong_any')} | "
                      f"{_kn(s, 'deep.fresh.all.Tplus.abstained')} |"]
            cats = sorted({kk.split(".")[2] for kk in s if kk.startswith(f"llm_deep.{b}.") and kk.endswith(".cause_cases")
                           and kk.split(".")[2] != "all"})
            L += ["", "| category | worlds | LLM right | LLM wrong | LLM abstained | LLM no incident |", "|---|---|---|---|---|---|"]
            for c in cats:
                q = f"llm_deep.{b}.{c}"
                L.append(f"| {c} | {s[f'{q}.cases']} | {s[f'{q}.right_cause'] if s[f'{q}.cause_cases'] else 'n/a'} | {s[f'{q}.wrong_confident']} | "
                         f"{s[f'{q}.abstained']} | {s[f'{q}.no_incident']} |")
            L.append("")
    return L


# ------------------------------------------------------------------ the public deployment (evals/live_bench.py)
def live_bench() -> dict:
    """evals/results/live_bench.json: measured over HTTPS against the live deployment (not part of `make eval`)."""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parent / "results" / "live_bench.json"
    return json.loads(p.read_text()) if p.exists() else {}


def live_summary(x: dict) -> dict:
    """latest.json keys: live.* (status, page loads, hero runs end to end, S2, brain, preflight, MCP auth)."""
    if not x:
        return {}
    h, st = x.get("hero") or {}, x.get("status") or {}
    return {"live.at": x.get("at"), "live.engine": st.get("engine"), "live.templates": st.get("templates"),
            "live.version": st.get("version"), "live.api_status_ms_p50": (x.get("api_status_ms") or {}).get("p50"),
            "live.api_status_ms_p95": (x.get("api_status_ms") or {}).get("p95"), "live.pages": len(x.get("pages") or {}),
            "live.pages_ok": x.get("pages_ok"), "live.pages_ttfb_p50": x.get("pages_ttfb_p50"),
            "live.pages_load_max_p50": x.get("pages_load_max_p50"), "live.hero.n": h.get("n"),
            "live.hero.cause_correct": h.get("cause_correct"), "live.hero.resolved": h.get("resolved"),
            "live.hero.applied": h.get("applied"), "live.hero.verdict_ms_p50": h.get("verdict_ms_p50"),
            "live.hero.verdict_ms_max": h.get("verdict_ms_max"), "live.hero.act_ms_p50": h.get("act_ms_p50"),
            "live.hero.total_ms_p50": h.get("total_ms_p50"), "live.s2.cause_correct": (x.get("s2") or {}).get("cause_correct"),
            "live.s2.verdict_ms": (x.get("s2") or {}).get("verdict_ms"), "live.brain.n": (x.get("brain") or {}).get("n"),
            "live.brain.ok": (x.get("brain") or {}).get("ok"), "live.brain.ms_p50": (x.get("brain") or {}).get("ms_p50"),
            "live.preflight.decision": (x.get("preflight") or {}).get("decision"),
            "live.preflight.ms": (x.get("preflight") or {}).get("ms"), "live.mcp_unauthenticated": x.get("mcp_unauthenticated_http")}


def live_markdown(x: dict) -> list[str]:
    if not x:
        return []
    h, st, b, pf, s2 = x["hero"], x["status"], x["brain"], x["preflight"], x.get("s2") or {}
    L = ["", "## The public deployment, measured over HTTPS (evals/live_bench.py)", "",
         f"Measured {x['at']} against {x['base']} (engine {st['engine']}, release {st['version']}, {st['templates']} templates, "
         f"read path `{st['acl']}`), from outside the server; network latency to the server is included.", "",
         "| what | result |", "|---|---|",
         f"| hero incident (S1), {h['n']} runs | right cause {h['cause_correct']}/{h['n']}, resolved {h['resolved']}/{h['n']}, "
         f"verified APPLIED {h['applied']}/{h['n']} |",
         f"| time to a gate verdict (S1) | p50 {h['verdict_ms_p50']} ms, max {h['verdict_ms_max']} ms |",
         f"| choose + approve to verified write-back | p50 {h['act_ms_p50']} ms |",
         f"| alert to RESOLVED, end to end | p50 {h['total_ms_p50']} ms |",
         f"| data incident (S2) to its verdict | {s2.get('verdict_ms')} ms, right cause = {s2.get('cause_correct')} |",
         f"| company brain | {b['ok']}/{b['n']} answered, p50 {b['ms_p50']} ms |",
         f"| preflight on a PR that must block | decision `{pf['decision']}`, {pf['ms']} ms |",
         f"| /api/status | p50 {x['api_status_ms']['p50']} ms, p95 {x['api_status_ms']['p95']} ms |",
         f"| pages ({len(x['pages'])}) | {x['pages_ok']}/{len(x['pages'])} load; time to first byte p50 {x['pages_ttfb_p50']} ms |",
         f"| hosted MCP without a key | HTTP {x['mcp_unauthenticated_http']} (refused) |"]
    return L


# ------------------------------------------------------------------ learned edges (evals/learning_eval.py)
def learning_markdown(x: dict) -> list[str]:
    if not x:
        return []
    return ["", "## Memory that changes the answer: a verified fix teaches the graph (evals/learning_eval.py)", "",
            f"{x['cases']} held-out bench worlds with a multi-hop cause path; one edge on that path is hidden from the graph "
            "the product reads (the world keeps it). PREREGISTRATION amendment 2026-10-13 (with its addendum).", "",
            "| step | result |", "|---|---|",
            f"| incident 1 on the wrong graph | {x['i1_abstained']} abstained, {x['i1_wrong_confident']} wrong-confident |",
            f"| human names the true cause; rollback verified on the true world | {x['fix_applied']} APPLIED; "
            f"{x['proposals']} links proposed, {x['approved']} approved (two-step) |",
            f"| human names a decoy instead (wrong guess) | {x['wrong_guess_not_applied']} NOT_APPLIED; "
            f"{x['wrong_guess_proposals']} links proposed |",
            f"| incident 2, same world, with the learned links | {x['i2_learned_correct']}/{x['cases']} correct, "
            f"{x['i2_learned_wrong_confident']} wrong-confident |",
            f"| incident 2, nothing learned (control) | {x['i2_control_correct']}/{x['cases']} correct, "
            f"{x['i2_control_wrong_confident']} wrong-confident |"]


# ------------------------------------------------------------------ FalkorDB ladder + robustness
LADDER_LABEL = {"full": "full product", "no_maxflow": "`algo.maxFlow` off (G5 slack 0)",
                "no_sppaths": "`algo.SPpaths` → mere connectivity (`algo.WCC`)", "neither": "both off"}
ROBUST_LABEL = {"duplicates": "every alert repeated ×{}", "missing": "error-rate windows deleted for {:.0%} of components",
                "noise": "per-minute noise ×{}", "intermittent": "cause's effect intermittent (1 min on / 1 min off)"}


BUCKET_KEYS = ("correct", "right_cause_other_gate", "abstained_not_correct", "wrong_confident", "other", "right_cause",
               "confirm_cases")


def _bucket_keys(prefix: str, s: dict) -> dict:
    bk = s.get("buckets") or {}
    out = {f"{prefix}.{k}": bk[k] for k in BUCKET_KEYS if k in bk}
    out.update({f"{prefix}.decoys_by.{g.replace(' ', '_')}": n for g, n in (bk.get("decoys_eliminated_by") or {}).items()})
    return out


def ladder_summary(x: dict) -> dict:
    """latest.json keys: ladder.<rung>.{cases,correct,wrong_confident,abstained}, ladder.<rung>.b.<bucket>,
    ladder.<rung>.b.decoys_by.<gate>"""
    out = {}
    for r, v in (x.get("rungs") or {}).items():
        out.update({f"ladder.{r}.{k}": v[k] for k in ("cases", "correct", "wrong_confident", "abstained")})
        out.update(_bucket_keys(f"ladder.{r}.b", v))
    return out


def robustness_summary(x: dict) -> dict:
    """latest.json keys: robustness.baseline.*, robustness.<knob>.<level>.* (+ .b.<bucket>), robustness.<knob>.breaking_point"""
    if not x:
        return {}
    out = {f"robustness.baseline.{k}": x["baseline"][k] for k in ("cases", "correct", "wrong_confident", "abstained")}
    out.update(_bucket_keys("robustness.baseline.b", x["baseline"]))
    for knob, v in x["knobs"].items():
        out[f"robustness.{knob}.breaking_point"] = v["breaking_point"]
        for lvl, s in v["levels"].items():
            out.update({f"robustness.{knob}.{lvl}.{k}": s[k] for k in ("correct", "wrong_confident", "abstained")})
            out.update(_bucket_keys(f"robustness.{knob}.{lvl}.b", s))
    return out


def _bucket_cells(v: dict) -> str:
    bk = v.get("buckets") or {}
    if not bk:
        return f"{v['correct']} | n/a | {v['abstained']} | {v['wrong_confident']} | n/a | n/a"
    return (f"{bk['correct']} | {bk['right_cause_other_gate']} | {bk['abstained_not_correct']} | {bk['wrong_confident']} | "
            f"{bk['other']} | {bk['right_cause']}/{bk['confirm_cases']}")


BUCKET_HEAD = ("| correct (strict) | right cause, a decoy eliminated by another gate | abstained (not expected) | "
               "wrong-confident | other | right cause blamed |")


def ladder_markdown(x: dict, s: dict) -> list[str]:
    if not x:
        return []
    L = ["", "## FalkorDB capability ladder (evals/ladder.py)", "",
         f"The {x['cases']} held-out gate-bench worlds (seed {x['seed']}); one FalkorDB capability removed at a time "
         "(PREREGISTRATION amendment 2026-10-13, item 3). Strict correct = the expected outcome and cause AND every "
         "expected decoy eliminated by the expected gate; the other columns say where the rest went. Pre-registered "
         "expectation: wrong-confident rises when G2 or G5 is removed.", "",
         "| rung " + BUCKET_HEAD, "|---|---|---|---|---|---|---|"]
    L += [f"| {LADDER_LABEL.get(r, r)} | {_bucket_cells(v)} |" for r, v in x["rungs"].items()]
    L += ["", "Decoys eliminated, by gate: " + "; ".join(
        f"{LADDER_LABEL.get(r, r)}: " + ", ".join(f"{g} {n}" for g, n in ((v.get('buckets') or {}).get('decoys_eliminated_by') or {}).items())
        for r, v in x["rungs"].items()) + "."]
    rest = [(lbl, s.get(k)) for lbl, k in (
        ("alert grouping off (S14, every alert in one incident): causes confirmed", "s14.ungrouped.causes_found"),
        ("learned links off: incident 2 correct (learning control)", "learning.i2_control_correct"),
        ("recall memory off (A2): top-1 on the scenarios", "arm.A2.top1"),
        ("FalkorDB off (A4): confirmed causes on the scenarios", "arm.A4.confirmed_causes")) if s.get(k) is not None]
    if rest:
        L += ["", "Rungs measured by their own evals: " + "; ".join(f"{a} = {b}" for a, b in rest) + "."]
    return L


def robustness_markdown(x: dict) -> list[str]:
    if not x:
        return []
    b = x["baseline"]
    L = ["", "## Robustness: where it breaks (evals/robustness.py)", "",
         f"The {b['cases']} held-out gate-bench worlds (seed {x['seed']}), one knob at a time (PREREGISTRATION amendment "
         "2026-10-13, item 5). Breaking point = the first setting where correct drops by 5 or more or wrong-confident "
         "is above 0. The noise knob scales the per-minute noise on base error rates of a few tenths of a percent, "
         "against injected effects of tens of percent, so even ×4 is a mild stress.", "",
         "| setting " + BUCKET_HEAD, "|---|---|---|---|---|---|---|",
         f"| unperturbed | {_bucket_cells(b)} |"]
    for knob, v in x["knobs"].items():
        for lvl, r in v["levels"].items():
            n = float(lvl) if knob == "missing" else lvl
            L.append(f"| {ROBUST_LABEL.get(knob, knob + ' {}').format(n)} | {_bucket_cells(r)} |")
    def bp(k: str, v) -> str:
        return "none in the tested range" if v is None else (f"{float(v):.0%} missing" if k == "missing" else f"×{v}")

    L += ["", "Breaking points: " + "; ".join(f"{k} {bp(k, v['breaking_point'])}" for k, v in x["knobs"].items()) + "."]
    return L


DEEP_KEYS = ("cases", "ok", "right_cause", "correct", "wrong_confident", "abstained", "arm_t")


def deep_summary(x: dict) -> dict:
    """latest.json keys: deep.<dev|fresh>.{all,<category>,hops.<k>}.{cases,right_cause,correct,wrong_confident,abstained,arm_t}"""
    out: dict = {}
    for run, d in x.items():
        out.update({f"deep.{run}.all.{k}": d["all"][k] for k in DEEP_KEYS if k in d["all"]})   # older runs: no "ok"
        cc = (d["all"].get("buckets") or {}).get("confirm_cases")   # worlds that have a cause (right_cause's denominator)
        if cc is not None:
            out[f"deep.{run}.all.cause_cases"] = cc
            out.update(wilson_keys(f"deep.{run}.all.right_cause", d["all"]["right_cause"], cc))
            out.update(wilson_keys(f"deep.{run}.all.wrong_confident", d["all"]["wrong_confident"], d["all"]["cases"]))
        for cat, v in d["by_category"].items():
            out.update({f"deep.{run}.{cat}.{k}": v[k] for k in DEEP_KEYS if k in v})
        for h, v in d["by_hops"].items():
            out.update({f"deep.{run}.hops.{h}.{k}": v[k] for k in DEEP_KEYS if k in v})
        out.update({f"deep.{run}.decoys_by.{g.replace(' ', '_')}": n
                    for g, n in (d["all"].get("buckets") or {}).get("decoys_eliminated_by", {}).items()})
    return out


def deep_markdown(x: dict) -> list[str]:
    if not x:
        return []
    L = ["", "## Deep bench: multi-hop causes, look-alikes and adversarial worlds (evals/deep_bench.py)", "",
         "Generated worlds (PREREGISTRATION amendment 2026-10-14, addenda 1–2). Cause categories: the cause 1–4 visible "
         "hops upstream of the alert, with a look-alike deploy on a component between them (deep_onpath) or on the "
         "alerting component (symptom_decoy). Adversarial categories: look-alikes below an UNCHANGED break "
         "(abstain_downstream), two genuine causes in a chain, a weakly linked concurrent fault, a later upstream fault, "
         "an unchanged upstream fault next to a real cause. ok = the expected cause, or an abstention where the "
         "pre-registration allows one; wrong-confident = any confident blame of another change (the safety metric). "
         "G4 upstream eliminates only under a strict lower bound (best single path, cap × call share, no slack, the "
         "upstream fault first); the development seed's runs found the gap and then the first version's unsafety. "
         "On the fresh seed, the 60 worlds of the first three categories were first run with the first-shipped rule "
         "(all correct, run_0025) before the redesign; the 80 adversarial worlds were added after it, and the "
         "redesign was developed on the development seed and the reviewer's worlds. Arm T = telemetry only.",
         "", "| seed | category | cases | ok | right cause | wrong-confident | abstained | arm T |",
         "|---|---|---|---|---|---|---|---|"]
    for run, d in x.items():
        for cat, v in d["by_category"].items():
            L.append(f"| {run} ({d['seed']}) | {cat} | {v['cases']} | {v.get('ok', 'n/a')} | {v['right_cause']} | "
                     f"{v['wrong_confident']} | {v['abstained']} | {v['arm_t']} |")
    for run, d in x.items():
        L += ["", f"Decoys eliminated ({run}): " + ", ".join(
            f"{g} {n}" for g, n in (d['all'].get('buckets') or {}).get('decoys_eliminated_by', {}).items()) + "."]
    return L


def context_summary(x: dict) -> dict:
    """latest.json keys: ctx.busy<k>.{worlds,ms_p50,ms_p95}, ctx.busy<k>.b<budget>.<G|V|R>.<metric>"""
    out: dict = {}
    for k, v in (x.get("busy") or {}).items():
        out.update({f"ctx.busy{k}.{m}": v[m] for m in ("worlds", "ms_p50", "ms_p95")})
        for b, arms in v["budgets"].items():
            for arm, ms in arms.items():
                out.update({f"ctx.busy{k}.b{b}.{arm}.{m}": val for m, val in ms.items()})
    return out


def context_markdown(x: dict) -> list[str]:
    if not x:
        return []
    L = ["", "## Context packs: graph vs vector RAG vs recency, per token (evals/context_eval.py)", "",
         "The same candidate items, serialised identically, packed four ways to the same budget (characters / 4): GA = the "
         "product's `context_pack` (upstream changes ranked by the anomaly measured on the changed component, then path "
         "distance; causal paths, owners, decisions, past incidents), G = the same with graph distance only (ablation), V = cosine similarity to the alert text with the product's embedding model plus a "
         "topology paragraph, R = the window's changes newest first. Recall of the grader's truth items "
         "(PREREGISTRATION amendment 2026-10-14 and its addendum; busy = extra deploys in the window).", "",
         "| busy | budget | arm | cause | cause MRR | chain | decisions | responder |", "|---|---|---|---|---|---|---|---|"]
    for k, v in (x.get("busy") or {}).items():
        for b, arms in v["budgets"].items():
            for arm, ms in arms.items():
                L.append(f"| {k} | {b} | {arm} | {ms['cause']} | {ms.get('mrr', 'n/a')} | {ms['chain']} | {ms.get('decisions', 'n/a')} | "
                         f"{ms.get('responder', 'n/a')} |")
    first = next(iter((x.get("busy") or {}).values()), None)
    if first:
        L += ["", f"Worlds per setting: {first['worlds']} ({', '.join(f'{s} {n}' for s, n in first['by_source'].items())}); "
                  f"pack build p50 {first['ms_p50']} ms, p95 {first['ms_p95']} ms."]
    return L


def perf_summary(x: dict) -> dict:
    """latest.json keys: perf.<graph>.<lookup>.{equal,instances,falkordb_rt_p50,falkordb_rt_p95,falkordb_engine_p50,
    falkordb_engine_p95,sql_p50,sql_p95}, perf.<graph>.edges, perf.fresh.*, perf.depth.<hops>.{cases,gate_correct,arm_t_score}"""
    out: dict = {}
    for gname, gx in (x.get("lookups") or {}).items():
        out[f"perf.{gname}.edges"] = gx["edges"]
        cp = gx.get("context_pack")
        if cp:
            out.update({f"perf.{gname}.pack.ms_p50": cp["ms"]["p50"], f"perf.{gname}.pack.ms_p95": cp["ms"]["p95"],
                        f"perf.{gname}.pack.alerts": cp["alerts"], f"perf.{gname}.pack.pool_p50": cp["pool_p50"]})
        for k, v in gx["lookups"].items():
            p = f"perf.{gname}.{k}"
            out.update({f"{p}.equal": v["equal"], f"{p}.instances": v["instances"], f"{p}.non_empty": v["non_empty"],
                        f"{p}.falkordb_rt_p50": v["falkordb_roundtrip_ms"]["p50"],
                        f"{p}.falkordb_rt_p95": v["falkordb_roundtrip_ms"]["p95"],
                        f"{p}.falkordb_engine_p50": v["falkordb_engine_ms"]["p50"],
                        f"{p}.falkordb_engine_p95": v["falkordb_engine_ms"]["p95"],
                        f"{p}.sql_p50": v["duckdb_sql_ms"]["p50"], f"{p}.sql_p95": v["duckdb_sql_ms"]["p95"]})
    for kind, f in (x.get("freshness") or {}).items():
        out.update({f"perf.fresh.{kind}.writes": f["writes"], f"perf.fresh.{kind}.p50_ms": f["write_to_visible_ms"]["p50"],
                    f"perf.fresh.{kind}.p95_ms": f["write_to_visible_ms"]["p95"],
                    f"perf.fresh.{kind}.first_read_saw_it": f["first_read_saw_it"]})
    for k, v in ((x.get("depth") or {}).get("groups") or {}).items():
        key = k.replace(" ", "_")
        out.update({f"perf.depth.{key}.{kk}": v[kk] for kk in ("cases", "gate_correct", "arm_t_score")})
    return out


def perf_markdown(x: dict) -> list[str]:
    if not x:
        return []
    L = ["", "## FalkorDB vs a flat store, freshness, depth (evals/perf_vs_flat.py)", "",
         "The gate's lookups as the product runs them (RO wrapper, real templates) vs DuckDB recursive SQL over the same "
         "edge table exported from the same graph; 20 timed runs per instance after a warm-up (PREREGISTRATION amendment "
         "2026-10-13, item 4). The SQL computes only reach sets and path lengths (the favourable comparator); Q-GATE-1 also "
         "returns the paths. Both graphs are small: every lookup is milliseconds on both sides, so the result is "
         "equality and engine time, not a speed race. Max flow has no SQL equivalent.", "",
         "| graph | lookup | equal | FalkorDB round trip p50 / p95 ms | FalkorDB engine p50 / p95 ms | DuckDB SQL p50 / p95 ms |",
         "|---|---|---|---|---|---|"]
    for gname, gx in (x.get("lookups") or {}).items():
        for k, v in gx["lookups"].items():
            rt, en, sq = v["falkordb_roundtrip_ms"], v["falkordb_engine_ms"], v["duckdb_sql_ms"]
            L.append(f"| {gname} ({gx['edges']} edges) | {k} ({v['template']}) | {v['equal']}/{v['instances']} "
                     f"({v['non_empty']} non-empty) | "
                     f"{rt['p50']} / {rt['p95']} | {en['p50']} / {en['p95']} | {sq['p50']} / {sq['p95']} |")
    fr = x.get("freshness") or {}
    if fr:
        what = {"alert": "an alert, seen by INTAKE's Q-ALERT-1", "window": "an error-rate window, seen by Q-MW-1"}
        L += ["", "**Freshness** (engine-user write → first sighting by the read-only query that consumes it, on a separate "
                  "connection pool; one server, so read-after-acknowledge latency, not replication lag): " + "; ".join(
                      f"{what.get(k, k)} {f['write_to_visible_ms']['p50']} ms p50 / {f['write_to_visible_ms']['p95']} ms p95 "
                      f"(first read saw it {f['first_read_saw_it']}/{f['writes']})" for k, f in fr.items()) + "."]
    d = (x.get("depth") or {}).get("groups")
    if d:
        L += ["", "**Depth** (held-out bench worlds, hop distance from the true cause's component to the symptom):", "",
              "| hops | cases | gate correct | arm T (telemetry only) score |", "|---|---|---|---|"]
        L += [f"| {k} | {v['cases']} | {v['gate_correct']} | {v['arm_t_score']} |" for k, v in d.items()]
        if not any(k.isdigit() and int(k) >= 2 for k in d):
            L += ["", "The generated bench has no true cause two or more hops from its symptom, so this curve cannot show "
                      "where multi-hop context starts to matter; the deep bench (below) covers 1–4 hops."]
    return L


def mutant_labels() -> dict:
    """Mutant id → the invariant's current description in scripts/mutation_check.py. A recorded run keeps the label
    it ran with; the report prints today's wording, keyed by the same id (the killed/survived result is unchanged)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "mutation_check.py"
    try:
        spec = importlib.util.spec_from_file_location("mutation_check", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("mutation_check", mod)   # dataclasses resolve their module by name
        spec.loader.exec_module(mod)
        return {m.id: m.invariant for m in mod.MUTANTS}
    except Exception:  # noqa: BLE001 - a report must still render without the script
        return {}


def robustness_notes(rob: dict, lad: dict, perf: dict) -> list[str]:
    """'What didn't work' lines derived from the ladder, robustness and depth results of this run."""
    notes = []
    for knob, v in (rob.get("knobs") or {}).items():
        if v.get("breaking_point") is not None:
            lvl = v["levels"][str(v["breaking_point"])]
            notes.append(f"Robustness breaks on `{knob}` at its first setting {v['breaking_point']}: correct "
                         f"{lvl['correct']}/{rob['baseline']['cases']} (from {rob['baseline']['correct']}), wrong-confident "
                         f"{lvl['wrong_confident']}, abstained {lvl['abstained']}.")
    rungs = lad.get("rungs") or {}
    if rungs and all(r["wrong_confident"] == rungs.get("full", {}).get("wrong_confident") for r in rungs.values()):
        notes.append("The pre-registered ladder expectation was wrong: removing `algo.maxFlow` or `algo.SPpaths` did not "
                     "raise wrong-confident blames (see the ladder table for where the strict-grade misses went).")
    groups = (perf.get("depth") or {}).get("groups") or {}
    if groups and not any(k.isdigit() and int(k) >= 2 for k in groups):
        notes.append("The held-out gate bench has no cause two or more hops from its symptom (the deep bench covers 1–4 "
                     "hops, in the same simulator).")
    return notes


# ------------------------------------------------------------------ model mismatch (evals/mismatch_eval.py)
def mismatch_summary(m: dict) -> dict:
    """latest.json keys: mismatch.<variant>.{cases,correct,wrong_confident,abstained}, mismatch.baseline.*, mismatch.arm_t.*"""
    if not m:
        return {}
    out = {f"mismatch.baseline.{k}": m["baseline"][k] for k in ("cases", "correct", "wrong_confident", "abstained")}
    for v, x in (m.get("variants") or {}).items():
        out.update({f"mismatch.{v}.{k}": x[k] for k in ("cases", "correct", "wrong_confident", "abstained")})
        out[f"mismatch.{v}.flipped"] = len(x.get("flipped_from_correct") or [])
    out.update({f"mismatch.arm_t.{k}": m["arm_t"][k] for k in ("cases", "score", "confirm_cases", "confirm_score", "wrong_blame")})
    return out


def mismatch_markdown(m: dict) -> list[str]:
    if not m:
        return []
    L = ["", "## Model mismatch: the gate on a wrong graph (evals/mismatch_eval.py)", "",
         f"The {m['baseline']['cases']} held-out gate-bench worlds (seed {m['seed']}): telemetry generated from the TRUE "
         "topology, then the graph the product reads is perturbed (PREREGISTRATION amendment 2026-10-13). "
         "Wrong-confident = a confirmed blame of a change other than the expected cause, or any confirmed blame where "
         "no change should be blamed.", "",
         "| graph the product reads | correct | wrong-confident | abstained | flipped from correct |", "|---|---|---|---|---|",
         f"| as the world (bench) | {m['baseline']['correct']}/{m['baseline']['cases']} | {m['baseline']['wrong_confident']} | "
         f"{m['baseline']['abstained']} | n/a |"]
    label = {"caps": "every cap × U(0.5, 1.5)", "hidden": "one edge hidden", "stale": "one stale edge added",
             "all": "all three"}
    for v, x in (m.get("variants") or {}).items():
        L.append(f"| {label.get(v, v)} | {x['correct']}/{x['cases']} | {x['wrong_confident']} | {x['abstained']} | "
                 f"{', '.join(x.get('flipped_from_correct') or []) or 'none'} |")
    t = m["arm_t"]
    L += ["", f"**Arm T (telemetry only, no topology) on the same worlds:** {t['score']}/{t['cases']} (ties 1/k); "
              f"{t['confirm_score']}/{t['confirm_cases']} on the cases with a true cause; it cannot abstain, so it "
              f"blamed a change in {t['wrong_blame']} of the cases where no change should be blamed. By category: "
              + ", ".join(f"{k} {v}" for k, v in t["by_category"].items()) + "."]
    return L


# ------------------------------------------------------------------ futures (evals/futures_eval.py)
FUTURES_KEYS = ("candidates", "definite", "agree", "false_assurance", "conservative", "unknown", "predicted_contains",
                "predicted_not")


def futures_summary(f: dict) -> dict:
    """latest.json keys: futures.* (the scenario suite) and futures.bench.* (the held-out gate-bench worlds)."""
    if not f:
        return {}
    out = {f"futures.{k}": f[k] for k in FUTURES_KEYS + ("scenarios_read",) if k in f}
    b = f.get("bench") or {}
    out.update({f"futures.bench.{k}": b[k] for k in FUTURES_KEYS + ("cases", "scenarios_read", "seed") if k in b})
    for kind in ("cut", "remove_origin", "no_change"):  # per candidate kind: `cut` is the measured headline
        out.update({f"futures.{kind}.{k}": f[kind][k] for k in FUTURES_KEYS if kind in f})
        out.update({f"futures.bench.{kind}.{k}": b[kind][k] for k in FUTURES_KEYS if kind in b})
    return out


def futures_markdown(f: dict) -> list[str]:
    if not f:
        return []
    L = ["", "## Futures: predicted vs the simulated world (evals/futures_eval.py)", "",
         "Each containment candidate the plan read (each single min-cut edge, the whole cut, removing the origin's fault, "
         "changing nothing) is predicted by Q-FUTURE-1 on its own GRAPH.COPY branch (measured excess × path transfer), "
         "then applied to the simulated world with the scenario's own effects; VERIFY's band rule decides. A false "
         "assurance is a candidate predicted to contain that the world does not.", "",
         "| set: candidate kind | candidates | definite | agree | false assurance | conservative | unknown | predicted contains / not |",
         "|---|---|---|---|---|---|---|---|"]
    for name, x in (("scenarios", f), (f"gate-bench worlds (seed {(f.get('bench') or {}).get('seed')})", f.get("bench"))):
        if not x:
            continue
        for kind, label in (("cut", "cut edges (measured)"), ("remove_origin", "remove origin (assumed: true by construction)"),
                            ("no_change", "no change")):
            y = x.get(kind)
            if y:
                L.append(f"| {name}: {label} | {y['candidates']} | {y['definite']} | {y['agree']} | {y['false_assurance']} | "
                         f"{y['conservative']} | {y['unknown']} | {y['predicted_contains']} / {y['predicted_not']} |")
    unk = [f"{r['scenario']}" for r in f.get("rows", []) if any(c["predicted"] == "unknown" for c in r.get("candidates", []))]
    if unk:
        L += ["", f"Unknown predictions (not counted in agreement): {', '.join(unk)}: a symptom with no error-rate "
                  "telemetry (a KPI) has no baseline to predict against."]
    return L


# ------------------------------------------------------------------ scale benchmark (evals/scale.py)
SCALE_TEMPLATES = ("Q-GATE-1", "Q-GATE-3", "Q-GATE-MULT", "Q-SUS-1", "Q-SUS-2", "Q-BLAST-1", "Q-BLAST-2", "Q-CUT-1",
                   "Q-CUT-2", "Q-NEG-1")
SCALE_TOPK = {"Q-CHOKE-1", "Q-CHOKE-ALL", "Q-RANK-1", "Q-ORG-HARM"}   # ORDER BY score DESC LIMIT k: truncation is the point
SCALE_KEYS = ("services", "units", "nodes", "edges", "memory_mb", "copy_ms")


def scale_summary(sc: dict) -> dict:
    """latest.json keys for the scale benchmark: scale.<size>.* (sizes, seed, memory, verdict, sweep, hero templates)."""
    out: dict = {}
    sizes = sc.get("sizes") or {}
    done = [k for k, v in sizes.items() if not v.get("skipped") and v.get("run")]
    if not done:
        return out
    out["scale.sizes_run"] = len(done)
    out["scale.largest_services"] = max(sizes[k]["services"] for k in done)
    out["scale.all_correct"] = all(sizes[k]["run"].get("correct") for k in done)
    for k, v in sizes.items():
        p = f"scale.{k}"
        if v.get("skipped"):
            out[f"{p}.skipped"] = True
            continue
        if not v.get("run"):
            continue
        out.update({f"{p}.{kk}": v.get(kk) for kk in SCALE_KEYS if v.get(kk) is not None})
        out[f"{p}.seed_s"] = (v.get("seed") or {}).get("seed_s")
        r = v["run"]
        out.update({f"{p}.outcome": r.get("outcome"), f"{p}.correct": r.get("correct"), f"{p}.run_s": r.get("seconds"),
                    f"{p}.swept": r.get("swept"), f"{p}.ambient": (v.get("incident") or {}).get("ambient")})
        sw = v.get("sweep_ms") or {}
        out.update({f"{p}.sweep_ms_p50": sw.get("p50"), f"{p}.sweep_ms_p95": sw.get("p95")})
        out.update(scale_tail_keys(p, v))
        for tid in SCALE_TEMPLATES:
            x = (v.get("templates") or {}).get(tid) or {}
            for kk in ("engine_ms_p50", "engine_ms_p95", "wall_ms_p50"):
                if x.get(kk) is not None:
                    out[f"{p}.{tid}.{kk}"] = x[kk]
            if x.get("errors"):
                out[f"{p}.{tid}.errors"] = x["errors"]
        dom = ((sc.get("analysis") or {}).get("dominant") or {}).get(k)
        if dom:
            out[f"{p}.dominant"] = dom["template"]
    return out


def scale_tail_keys(p: str, v: dict) -> dict:
    """The gate path's tail per size (scale.<k>.tail.<tid>.engine_ms_p50/p95/p99/max, wall_ms_p50/p99) and bytes
    per node-or-edge, both from GRAPH.MEMORY USAGE (engine-rounded MB) and from the settled used_memory growth."""
    out: dict = {}
    for tid, x in (v.get("tail") or {}).items():
        q = f"{p}.tail.{tid}"
        e, wl = x.get("engine_ms") or {}, x.get("wall_ms") or {}
        out.update({f"{q}.engine_ms_{kk}": e[kk] for kk in ("p50", "p95", "p99", "max") if e.get(kk) is not None})
        out.update({f"{q}.wall_ms_{kk}": wl[kk] for kk in ("p50", "p99") if wl.get(kk) is not None})
        out[f"{q}.runs"] = e.get("n")
        if x.get("errors"):
            out[f"{q}.errors"] = x["errors"]
    elems = (v.get("nodes") or 0) + (v.get("edges") or 0)
    if elems and v.get("memory_mb"):
        out[f"{p}.bytes_per_elem"] = round(float(v["memory_mb"]) * 2**20 / elems)
    if elems and v.get("engine_used_mb_seed_delta"):
        out[f"{p}.used_mb_seed_delta"] = v["engine_used_mb_seed_delta"]
        out[f"{p}.used_bytes_per_elem"] = round(float(v["engine_used_mb_seed_delta"]) * 2**20 / elems)
    return out


SCALE_TAIL = ("Q-GATE-1", "Q-GATE-3", "Q-BLAST-1")


def scale_tail_markdown(sc: dict) -> list[str]:
    sizes = {k: v for k, v in (sc.get("sizes") or {}).items() if v.get("tail")}
    if not sizes:
        return []
    L = ["", "### The gate path's tail at each size (nearest-rank over the tail runs, engine-reported ms)", "",
         "| size | services | bytes per node-or-edge (GRAPH.MEMORY USAGE / used_memory growth) | "
         + " | ".join(f"{t} p50 / p95 / p99" for t in SCALE_TAIL) + " |", "|---|---|---|" + "---|" * len(SCALE_TAIL)]
    for k, v in sizes.items():
        p = f"scale.{k}"
        s = scale_tail_keys(p, v)
        mem = (_c(p + ".bytes_per_elem", s.get(p + ".bytes_per_elem")) + " / "
               + (_c(p + ".used_bytes_per_elem", s[p + ".used_bytes_per_elem"]) if p + ".used_bytes_per_elem" in s else "—"))
        cells = []
        for tid in SCALE_TAIL:
            q = f"{p}.tail.{tid}"
            cells.append(" / ".join(_c(f"{q}.engine_ms_{kk}", s.get(f"{q}.engine_ms_{kk}")) for kk in ("p50", "p95", "p99"))
                         if f"{q}.engine_ms_p50" in s else "—")
        L.append(f"| {k} | {_c(p + '.services', v.get('services'))} | {mem} | " + " | ".join(cells) + " |")
    L += ["", "Each read runs on every hero instance (the incident's own ids and the global hub's); the headline is the "
          "slowest instance by p99. GRAPH.MEMORY USAGE is rounded to whole MB by the engine and leaves out part of the "
          "index memory, so the used_memory growth across the seed is shown next to it (other work on a shared engine "
          "can move it)."]
    return L


# ------------------------------------------------------------------ tenant density + concurrency, algo10k
def tenants_keys(x: dict | None = None) -> dict:
    """tenants.* (PREREGISTRATION addendum 2026-10-17 21:10 IST, amended about 21:30): tenant graphs on one engine (product
    tenants = copies of golden_acme, small tenants = its failure-flow layer), MB per tenant, copy ms, ACL isolation,
    and the gate step's throughput and latency at 1/8/32/64 parallel investigators (evals/tenants_bench.py)."""
    x = _side("tenants_bench.json") if x is None else x
    k: dict = {}
    if not x or not (x.get("density") or {}).get("n"):
        return k
    d, iso, cfg = x["density"], x.get("isolation") or {}, x.get("config") or {}
    k.update({"tenants.n": d["n"], "tenants.threads": cfg.get("THREAD_COUNT"), "tenants.max_queued": cfg.get("MAX_QUEUED_QUERIES"),
              "tenants.maxmemory_mb": cfg.get("maxmemory_mb"), "tenants.cpus": (x.get("machine") or {}).get("cpus"),
              "tenants.used_mb_at_n": round(float(d.get("used_mb_at_n") or 0), 1),
              "tenants.concurrent_activity_steps": sum(1 for st in d.get("steps") or [] if st.get("concurrent_activity"))})
    for kind, v in (d.get("kinds") or {}).items():
        p = f"tenants.{kind}"
        k.update({f"{p}.n": v["n"], f"{p}.source_nodes": v["source"]["nodes"], f"{p}.source_edges": v["source"]["edges"],
                  f"{p}.graph_memory_usage_mb": v["source"].get("graph_memory_usage_mb")})
        if v.get("mb_per_tenant") is not None:
            k[f"{p}.mb_per_tenant"] = round(float(v["mb_per_tenant"]), 1)
        if v.get("rss_mb_per_tenant") is not None:
            k[f"{p}.rss_mb_per_tenant"] = round(float(v["rss_mb_per_tenant"]), 1)
        for kk in ("p50", "p95", "p99"):
            k[f"{p}.copy_ms_{kk}"] = (v.get("copy_ms") or {}).get(kk)
        k[f"{p}.copy_raw_ms_p50"] = (v.get("copy_raw_ms") or {}).get("p50")
    for st in d.get("stopped") or []:
        k[f"tenants.{st['kind']}.stopped_before"] = st["before_total"]
    ct, own, app = iso.get("cross_tenant") or {}, iso.get("own_graph") or {}, iso.get("app_layer") or {}
    if ct:
        k.update({"tenants.acl.users": iso.get("users"), "tenants.acl.cross.n": ct["probes"],
                  "tenants.acl.cross.denied": ct["denied"], "tenants.acl.leaks": ct["leaks"],
                  "tenants.acl.cross.other_errors": ct["other_errors"], "tenants.acl.own.ok": own.get("ok"),
                  "tenants.acl.own.n": own.get("probes"), "tenants.acl.forbidden.denied": iso.get("forbidden_denied"),
                  "tenants.acl.forbidden.allowed": iso.get("forbidden_allowed"), "tenants.acl.forbidden.n": iso.get("forbidden_probes"),
                  "tenants.acl.app.refused": app.get("refused"), "tenants.acl.app.n": app.get("probes"),
                  "tenants.acl.sample_intact": iso.get("sample_graphs_intact"), "tenants.acl.sample": iso.get("sample")})
        k.update(wilson_keys("tenants.acl.leak", ct["leaks"], ct["probes"]))
    pp = x.get("params") or {}
    if pp:
        k["tenants.pool.per_template"] = pp.get("per_template")
        k["tenants.pool.gate1_with_path"] = pp.get("gate1_with_path")
    for r in x.get("concurrency") or []:
        p = f"tenants.c{r['investigators']}"
        lm = r["latency_ms"]
        k.update({f"{p}.qps": r["qps"], f"{p}.steps_per_s": r["steps_per_s"], f"{p}.queries": r["queries"],
                  f"{p}.p50_ms": lm["p50"], f"{p}.p95_ms": lm["p95"], f"{p}.p99_ms": lm["p99"], f"{p}.max_ms": lm["max"],
                  f"{p}.errors": r["error_total"], f"{p}.engine_cpu_cores": r["engine_cpu_cores"],
                  f"{p}.client_cpu_max": r["client_cpu_cores_max"], f"{p}.processes": r["processes"]})
        for tid, st in (r.get("per_template") or {}).items():
            k[f"{p}.{tid}.p50_ms"], k[f"{p}.{tid}.p99_ms"] = st["p50"], st["p99"]
    return k


def tenants_markdown(s: dict) -> list[str]:
    if not s.get("tenants.n"):
        return []
    L = ["", "## Tenant density, isolation and concurrent investigators (evals/tenants_bench.py)", "",
         f"One pinned engine (maxmemory {_c('tenants.maxmemory_mb', s.get('tenants.maxmemory_mb'))} MB, THREAD_COUNT "
         f"{_c('tenants.threads', s.get('tenants.threads'))}, MAX_QUEUED_QUERIES {_c('tenants.max_queued', s.get('tenants.max_queued'))}"
         f"), shared with the product's own graphs; clients on the same {_c('tenants.cpus', s.get('tenants.cpus'))}-core laptop. "
         "MB per tenant is the settled growth of the engine's used_memory (GRAPH.MEMORY USAGE, shown for the source graph, "
         "rounds to whole MB and leaves out most index memory).", "",
         "| tenant kind | tenants | source graph (nodes / edges) | GRAPH.MEMORY USAGE of the source | MB per tenant (used_memory / RSS) | copy ms p50 / p95 / p99 | stopped before |",
         "|---|---|---|---|---|---|---|"]
    for kind, desc in (("product", "product (a copy of golden_acme)"), ("small", "small (golden_acme's failure-flow layer only)")):
        p = f"tenants.{kind}"
        if s.get(f"{p}.n") is None:
            continue
        L.append(f"| {desc} | {_c(p + '.n', s[p + '.n'])} | {_c(p + '.source_nodes', s.get(p + '.source_nodes'))} / "
                 f"{_c(p + '.source_edges', s.get(p + '.source_edges'))} | {_c(p + '.graph_memory_usage_mb', s.get(p + '.graph_memory_usage_mb'))} MB | "
                 f"{_c(p + '.mb_per_tenant', s.get(p + '.mb_per_tenant'))} / "
                 + (_c(p + ".rss_mb_per_tenant", s[p + ".rss_mb_per_tenant"]) if p + ".rss_mb_per_tenant" in s else "—")
                 + f" | {_c(p + '.copy_ms_p50', s.get(p + '.copy_ms_p50'))} / "
                 f"{_c(p + '.copy_ms_p95', s.get(p + '.copy_ms_p95'))} / {_c(p + '.copy_ms_p99', s.get(p + '.copy_ms_p99'))} | "
                 + (_c(p + ".stopped_before", s[p + ".stopped_before"]) + " (memory guard)" if s.get(p + ".stopped_before") else "—") + " |")
    if s.get("tenants.acl.cross.n"):
        L += ["", f"**Isolation** ({_c('tenants.acl.users', s.get('tenants.acl.users'))} ACL users, the shipped `ro_` rules): "
              f"cross-tenant reads denied {_c('tenants.acl.cross.denied', s['tenants.acl.cross.denied'])}/"
              f"{_c('tenants.acl.cross.n', s['tenants.acl.cross.n'])}, leaks {_c('tenants.acl.leaks', s['tenants.acl.leaks'])} "
              f"(95 % upper bound on the leak rate {_c('tenants.acl.leak.ci_hi', s.get('tenants.acl.leak.ci_hi'))}); own-graph "
              f"reads {_c('tenants.acl.own.ok', s.get('tenants.acl.own.ok'))}/{_c('tenants.acl.own.n', s.get('tenants.acl.own.n'))}; "
              f"forbidden commands denied {_c('tenants.acl.forbidden.denied', s.get('tenants.acl.forbidden.denied'))}/"
              f"{_c('tenants.acl.forbidden.n', s.get('tenants.acl.forbidden.n'))}; the RO wrapper refused "
              f"{_c('tenants.acl.app.refused', s.get('tenants.acl.app.refused'))}/{_c('tenants.acl.app.n', s.get('tenants.acl.app.n'))} "
              "cross-tenant handles before any engine call."]
    lv = sorted({int(kk.split(".")[1][1:]) for kk in s if kk.startswith("tenants.c") and kk.endswith(".qps")
                 and kk.split(".")[1][1:].isdigit()})
    if lv:
        L += ["", "| investigators | gate-step queries/s | p50 ms | p95 ms | p99 ms | max ms | errors | engine CPU cores | client CPU (max per process) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for m in lv:
            p = f"tenants.c{m}"
            L.append(f"| {m} | {_c(p + '.qps', s[p + '.qps'])} | {_c(p + '.p50_ms', s[p + '.p50_ms'])} | "
                     f"{_c(p + '.p95_ms', s[p + '.p95_ms'])} | {_c(p + '.p99_ms', s[p + '.p99_ms'])} | {_c(p + '.max_ms', s[p + '.max_ms'])} | "
                     f"{_c(p + '.errors', s[p + '.errors'])} | {_c(p + '.engine_cpu_cores', s[p + '.engine_cpu_cores'])} | "
                     f"{_c(p + '.client_cpu_max', s[p + '.client_cpu_max'])} |")
        L += ["", "A gate step is Q-GATE-1 (algo.SPpaths), Q-GATE-3 (algo.maxFlow) and Q-BLAST-1 (algo.BFS) on a random tenant, "
              "through the product's RO wrapper as that tenant's ACL user; latency is the client's wall time per read "
              "(network, queueing, engine and the wrapper's parsing)."]
    return L


ALGO_ORDER = ("bfs", "sppaths", "sspaths", "pagerank", "betweenness", "harmonic", "wcc", "cdlp", "maxflow", "msf")
ALGO_DETAIL = ("falkor_count", "nx_count", "max_abs_diff", "max_rel_error", "mean_rel_error", "mismatched", "paths",
               "targets_returned", "targets_checked", "nx_reachable", "largest_weight", "falkor_components",
               "nx_components", "falkor_communities", "nx_communities", "falkor_value", "nx_value", "falkor_edges",
               "nx_edges", "falkor_total", "nx_total")


def _algo_prefix(w: dict, counts: dict) -> str:
    return f"algo10k.{w['procedure']}" + (f".{w['tag']}" if counts.get(w["procedure"], 0) > 1 else "")


def algo10k_keys(x: dict | None = None) -> dict:
    """algo10k.* (PREREGISTRATION addendum 2026-10-17 21:10 IST): all 10 algo.* procedures at 10k services, and an
    eval-only NetworkX comparator on the same extracted input (evals/algo10k.py → evals/results/algo10k.json)."""
    x = _side("algo10k.json") if x is None else x
    if not x or not x.get("workloads"):
        return {}
    ws = x["workloads"]
    counts: dict = {}
    for w in ws:
        counts[w["procedure"]] = counts.get(w["procedure"], 0) + 1
    comp = [w for w in ws if w.get("equal") is not None]
    k: dict = {"algo10k.services": x.get("services"), "algo10k.nodes": (x.get("graph") or {}).get("nodes"),
               "algo10k.edges": (x.get("graph") or {}).get("edges"), "algo10k.runs": x.get("runs"),
               "algo10k.networkx": x.get("networkx"), "algo10k.procedures": len(counts), "algo10k.workloads": len(ws),
               "algo10k.comparable": len(comp), "algo10k.same": sum(1 for w in comp if w["equal"]),
               "algo10k.same_projection": sum(1 for w in comp if w.get("equal_on_projection")),
               "algo10k.errors": sum(1 for w in ws if (w.get("falkor") or {}).get("error"))}
    faster, faster_eng = [], []
    for w in ws:
        p = _algo_prefix(w, counts)
        f = w.get("falkor") or {}
        e, wl = f.get("engine_ms") or {}, f.get("wall_ms") or {}
        k.update({f"{p}.falkor_ms_{kk}": e.get(kk) for kk in ("p50", "p95", "p99")})
        k[f"{p}.falkor_wall_ms_p50"] = wl.get("p50")
        if f.get("error"):
            k[f"{p}.error"] = True
        pr = w.get("falkor_projection") or {}
        if pr:
            k[f"{p}.proj_ms_p50"] = (pr.get("engine_ms") or {}).get("p50")
            k[f"{p}.proj_wall_ms_p50"] = (pr.get("wall_ms") or {}).get("p50")
        k[f"{p}.equal"] = w.get("equal")
        if w.get("equal_on_projection") is not None:
            k[f"{p}.equal_projection"] = w["equal_on_projection"]
        for fld in ALGO_DETAIL:   # what the comparison found, next to the pre-registered pass/fail
            if isinstance(w.get(fld), (int, float)) and not isinstance(w.get(fld), bool):
                k[f"{p}.{fld}"] = round(float(w[fld]), 6) if isinstance(w[fld], float) else w[fld]
        if w.get("falkor_top") and w.get("nx_top"):
            ft, nt = w["falkor_top"], w["nx_top"]
            k[f"{p}.top_same_prefix"] = next((i for i, (a, b) in enumerate(zip(ft, nt)) if a != b), min(len(ft), len(nt)))
            k[f"{p}.top_overlap"] = len(set(ft) & set(nt))
            k[f"{p}.top_n"] = len(nt)
        nx = w.get("nx") or {}
        if nx:
            nx50 = (nx.get("ms") or {}).get("p50")
            k.update({f"{p}.nx_ms_p50": nx50, f"{p}.nx_runs": nx.get("runs"),
                      f"{p}.input_nodes": (nx.get("input") or {}).get("nodes"), f"{p}.input_edges": (nx.get("input") or {}).get("edges")})
            if nx.get("graph_bytes") is not None:
                k[f"{p}.nx_graph_mb"] = round(nx["graph_bytes"] / 2**20, 2)
            if nx.get("algo_peak_bytes") is not None:
                k[f"{p}.nx_peak_mb"] = round(nx["algo_peak_bytes"] / 2**20, 2)
            if nx50 and wl.get("p50"):
                k[f"{p}.x_wall"] = round(nx50 / wl["p50"], 1)
                faster.append(nx50 > wl["p50"])
            if nx50 and e.get("p50"):
                k[f"{p}.x_engine"] = round(nx50 / e["p50"], 1)
                faster_eng.append(nx50 > e["p50"])
    k["algo10k.faster_wall"] = sum(faster)
    k["algo10k.faster_engine"] = sum(faster_eng)
    k["algo10k.timed_pairs"] = len(faster)
    m = x.get("memory") or {}
    if m:
        k.update({"algo10k.mem.nodes": m["falkordb"]["nodes"], "algo10k.mem.edges": m["falkordb"]["edges"],
                  "algo10k.mem.falkordb_mb": round(m["falkordb"]["bytes"] / 2**20, 1),
                  "algo10k.mem.networkx_mb": round(m["networkx"]["bytes"] / 2**20, 1),
                  "algo10k.mem.falkordb_bytes_per_elem": m.get("falkordb_bytes_per_elem"),
                  "algo10k.mem.networkx_bytes_per_elem": m.get("networkx_bytes_per_elem"),
                  "algo10k.mem.ratio": m.get("ratio_nx_over_falkordb"),
                  "algo10k.mem.graph_memory_usage_mb": m["falkordb"].get("graph_memory_usage_mb")})
    return k


def algo10k_markdown(s: dict, x: dict | None = None) -> list[str]:
    x = _side("algo10k.json") if x is None else x
    if not x or not x.get("workloads"):
        return []
    ws = sorted(x["workloads"], key=lambda w: (ALGO_ORDER.index(w["procedure"]) if w["procedure"] in ALGO_ORDER else 99))
    counts: dict = {}
    for w in ws:
        counts[w["procedure"]] = counts.get(w["procedure"], 0) + 1
    L = ["", "## All 10 algo.* procedures at 10k services, against NetworkX (evals/algo10k.py)", "",
         f"Graph: the {_c('algo10k.services', s.get('algo10k.services'))}-service scale world "
         f"({_c('algo10k.nodes', s.get('algo10k.nodes'))} nodes, {_c('algo10k.edges', s.get('algo10k.edges'))} edges). FalkorDB: "
         f"{_c('algo10k.runs', s.get('algo10k.runs'))} runs per workload through GRAPH.RO_QUERY on the product graph and on a "
         "projection holding exactly the extracted input. NetworkX "
         f"{_c('algo10k.networkx', s.get('algo10k.networkx'))} (an eval-only comparator, never in the product) on that same "
         "input. Same answers by the pre-registered criterion; × = NetworkX p50 / FalkorDB wall p50 (the client-observed "
         "time, network and result parsing included).", "",
         "| procedure | workload | input nodes / edges | FalkorDB engine ms p50 / p95 / p99 | FalkorDB wall ms p50 | on the projection, engine ms p50 | NetworkX ms p50 | × | NetworkX graph / peak MB | same answers (product graph / projection) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    names = x.get("procedures") or {}
    for w in ws:
        p = _algo_prefix(w, counts)
        eq = s.get(f"{p}.equal")
        eqs = ("n/a" if eq is None else _c(p + ".equal", eq)) + (" / " + _c(p + ".equal_projection", s[p + ".equal_projection"])
                                                                   if p + ".equal_projection" in s else "")
        mb = (_c(p + ".nx_graph_mb", s.get(p + ".nx_graph_mb")) + " / "
              + (_c(p + ".nx_peak_mb", s[p + ".nx_peak_mb"]) if p + ".nx_peak_mb" in s else "not traced (slow)"))
        L.append(f"| `{names.get(w['procedure'], w['procedure'])}` | {w['instance']} | {_c(p + '.input_nodes', s.get(p + '.input_nodes'))} / "
                 f"{_c(p + '.input_edges', s.get(p + '.input_edges'))} | "
                 + (" / ".join(_c(f"{p}.falkor_ms_{kk}", s.get(f"{p}.falkor_ms_{kk}")) for kk in ("p50", "p95", "p99"))
                    if not s.get(p + ".error") else "error: " + str((w.get("falkor") or {}).get("error"))[:80])
                 + f" | {_c(p + '.falkor_wall_ms_p50', s.get(p + '.falkor_wall_ms_p50'))} | "
                 f"{_c(p + '.proj_ms_p50', s.get(p + '.proj_ms_p50')) if p + '.proj_ms_p50' in s else '—'} | "
                 f"{_c(p + '.nx_ms_p50', s.get(p + '.nx_ms_p50'))} | "
                 f"{_c(p + '.x_wall', s[p + '.x_wall']) if p + '.x_wall' in s else '—'} | {mb} | {eqs} |")
    L += ["", f"Same answers on {_c('algo10k.same', s.get('algo10k.same'))} of {_c('algo10k.comparable', s.get('algo10k.comparable'))} "
          f"comparable workloads (projection: {_c('algo10k.same_projection', s.get('algo10k.same_projection'))}). FalkorDB's engine "
          f"p50 is below NetworkX's on {_c('algo10k.faster_engine', s.get('algo10k.faster_engine'))} of "
          f"{_c('algo10k.timed_pairs', s.get('algo10k.timed_pairs'))} workloads, its client wall p50 on "
          f"{_c('algo10k.faster_wall', s.get('algo10k.faster_wall'))}: for whole-graph procedures the Python client's parsing of a "
          "10,000-row result dominates the wall time, while NetworkX returns an in-process dict. Criteria: "
          + "; ".join(f"{kk}: {v}" for kk, v in sorted({w['procedure']: w['criterion'] for w in ws}.items())) + "."]
    if s.get("algo10k.mem.falkordb_mb") is not None:
        L += ["", f"**The same graph in memory** (every workload's input together: {_c('algo10k.mem.nodes', s['algo10k.mem.nodes'])} "
              f"nodes, {_c('algo10k.mem.edges', s['algo10k.mem.edges'])} edges with their weights and capacities): FalkorDB "
              f"{_c('algo10k.mem.falkordb_mb', s['algo10k.mem.falkordb_mb'])} MB (engine used_memory growth, written by the product's "
              f"writers with the product schema's indexes; {_c('algo10k.mem.falkordb_bytes_per_elem', s.get('algo10k.mem.falkordb_bytes_per_elem'))} "
              f"bytes per node-or-edge) against NetworkX {_c('algo10k.mem.networkx_mb', s['algo10k.mem.networkx_mb'])} MB "
              f"(tracemalloc, a MultiDiGraph; {_c('algo10k.mem.networkx_bytes_per_elem', s.get('algo10k.mem.networkx_bytes_per_elem'))} "
              "bytes). FalkorDB's per-call working memory is not measured (the engine logs it only under a startup flag)."]
    return L


def current_scale(c: dict) -> dict:
    """The run's recorded scale check, or a later `make scale` (evals/results/scale.json) when that is newer (the
    10k rerun on the current gate supersedes the copy the run embedded)."""
    sc = c.get("scale") or {}
    newer = _side("scale.json")
    if newer and str(newer.get("started", "")) > str(sc.get("started", "")):
        return {**newer, "source": "evals/results/scale.json (make scale, newer than the run's copy)"}
    return sc


def scale_markdown(sc: dict) -> list[str]:
    sizes = {k: v for k, v in (sc.get("sizes") or {}).items()}
    done = [k for k, v in sizes.items() if not v.get("skipped") and v.get("run")]
    if not done:
        return []
    an = sc.get("analysis") or {}
    L = ["", "## Scale benchmark (evals/scale.py, synthetic federated tenants)", "",
         f"Source: {sc.get('source') or 'evals/results/scale.json'}. Each size is a federation of globex units (the "
         "existing generators, seed 42 + unit, ids namespaced; unit 0's platform is the global platform every other unit "
         "calls), seeded through the product's UNWIND MERGE writers into its own graph. A planted incident (a true cause, "
         "designated G2 / G5 / G4-origin distractors, a change on the global platform hub and ambient changes at globex's "
         "deploy rate) runs end to end through `run_incident` with the deterministic investigator on a clean room. "
         f"Engine ms = GRAPH.PROFILE, nearest-rank p50 / p95 of {sc.get('profile_runs')} runs; a template's headline is "
         "its slowest profiled instance (the incident's own ids or the hub's).", "",
         "| size | services | nodes | edges | memory MB | seed s | clean room | verdict | correct | run s | sweep ms p50 / p95 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in done:
        v, p = sizes[k], f"scale.{k}"
        sw = v.get("sweep_ms") or {}
        L.append(f"| {k} | {_c(p + '.services', v['services'])} | {_c(p + '.nodes', v.get('nodes'))} | "
                 f"{_c(p + '.edges', v.get('edges'))} | {_c(p + '.memory_mb', v.get('memory_mb'))} | "
                 f"{_c(p + '.seed_s', (v.get('seed') or {}).get('seed_s'))} | "
                 + ("GRAPH.COPY " + _c(p + ".copy_ms", v["copy_ms"]) + " ms" if v.get("copy_ms") is not None else "seeded directly")
                 + f" | {_c(p + '.outcome', v['run'].get('outcome'))} | {_c(p + '.correct', v['run'].get('correct'))} | "
                 f"{_c(p + '.run_s', v['run'].get('seconds'))} | {_c(p + '.sweep_ms_p50', sw.get('p50'))} / "
                 f"{_c(p + '.sweep_ms_p95', sw.get('p95'))} |")
    for k, v in sizes.items():
        if v.get("skipped"):
            L.append(f"| {k} | not run: {v['skipped']} | | | | | | | | | |")
    L += ["", "| template | " + " | ".join(f"{k} p50 / p95 (ms)" for k in done) + " | shape (last step) |",
          "|---|" + "---|" * (len(done) + 1)]
    for tid in SCALE_TEMPLATES:
        cells = []
        for k in done:
            x = (sizes[k].get("templates") or {}).get(tid) or {}
            p = f"scale.{k}.{tid}"
            if x.get("engine_ms_p50") is None:
                cells.append("error" if x.get("errors") else "—")
            else:
                cells.append(f"{_c(p + '.engine_ms_p50', x['engine_ms_p50'])} / {_c(p + '.engine_ms_p95', x['engine_ms_p95'])}"
                             + (" (trunc.)" if x.get("truncated") else ""))
        steps = ((an.get("growth") or {}).get(tid) or {}).get("steps") or []
        last = steps[-1] if steps else None
        L.append(f"| `{tid}` | " + " | ".join(cells) + " | "
                 + (f"{last['shape']} (×{last['time_x']} for ×{last['size_x']} services)" if last else "—") + " |")
    L += ["", "\"(trunc.)\" = the RO wrapper saw LIMIT n+1 rows for at least one instance. Growth shapes compare engine-ms p50 "
          "between consecutive sizes (exponent of the time ratio over the size ratio; above 1.3 is called superlinear)."]
    L += scale_tail_markdown(sc)
    return L


def scale_notes(sc: dict) -> list[str]:
    notes = []
    sizes = sc.get("sizes") or {}
    for k, v in sizes.items():
        if v.get("skipped"):
            notes.append(f"Scale benchmark: {k} was not run on this machine ({v['skipped']}).")
        elif v.get("run") and not v["run"].get("correct"):
            notes.append(f"Scale benchmark ({k}): the planted incident's verdict was wrong: {'; '.join(v['run'].get('why') or [])}.")
    an = sc.get("analysis") or {}
    trunc = sorted({(t["template"], t["instance"]) for t in an.get("truncated") or [] if t["template"] not in SCALE_TOPK})
    if trunc:
        notes.append("Scale benchmark: reads that hit their template LIMIT (rows beyond it are not seen): "
                     + ", ".join(f"{t} ({i})" for t, i in trunc) + ". Top-k reads by design ("
                     + ", ".join(sorted(SCALE_TOPK)) + ": highest scores first) are not listed.")
    for e in an.get("errors") or []:
        notes.append(f"Scale benchmark ({e['size']}): {e['template']} ({e['instance']}) failed: {e['error']}.")
    return notes


# ------------------------------------------------------------------ graded fields beyond the cause (harness.grade_detail)
DETAIL_ARMS = ("A2", "A3", "A4", "A3-noG5")
DETAIL_KEYS = ("blast_precision", "blast_recall", "path_contains_rate", "violates_rate", "responder_top3_rate",
               "fix_offered_rate", "target_correct_rate")


def detail_rates(ts: list[dict]) -> dict:
    """Means over the trials whose truth file has the field (None = no trial graded). target_correct is over the trials
    where the plan offered an enabled production-changing fix (fix_offered says how often that was)."""
    def b(k):
        return _mean([(1.0 if t[k] else 0.0) for t in ts if t.get(k) is not None])

    return {"blast_precision": _mean([t.get("blast_precision") for t in ts]), "blast_recall": _mean([t.get("blast_recall") for t in ts]),
            "path_contains_rate": b("path_contains_ok"), "violates_rate": b("violates_ok"),
            "responder_top3_rate": b("responder_top3"), "fix_offered_rate": b("fix_offered"),
            "target_correct_rate": b("target_correct")}


def detail_markdown(out: dict, s: dict) -> list[str]:
    arms = [a for a in out["arms"] if a in DETAIL_ARMS and any(s.get(f"arm.{a}.{k}") is not None for k in DETAIL_KEYS)]
    if not arms:
        return []
    L = ["", "## Graded beyond the cause", "",
         "From each trial's final graph state, against the truth file fields (graded only where the truth file has the "
         "field; a run that produced nothing for it counts as a miss). Blast radius: the BLAST stage's recorded "
         "`blast_radius` result vs the truth set (everything a failure at the cause's component reaches in the topology "
         "config). Path: the gate's proven chain contains the truth nodes in order. Violates: the decisions G8 attached "
         "equal the truth list (empty = none expected). Responder: one of who_fixes' top 3 is an owner-team member or a "
         "recent author of the component (truth `owners_any_of`). Target: the first enabled production-changing option "
         "rolls back / repairs the cause or flips the containment flag (truth `fix_targets_any_of`), over the trials "
         "where such an option was offered.", "",
         "| arm | scenario | blast precision | blast recall | path | violates | responder top-3 | fix offered | correct target |",
         "|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        sids = [sid for sid in out["scenarios"] if any(s.get(f"arm.{a}.{sid}.{k}") is not None for k in DETAIL_KEYS)]
        for sid in sids + ["all"]:
            p = f"arm.{a}" if sid == "all" else f"arm.{a}.{sid}"
            L.append(f"| {a} | {'**all**' if sid == 'all' else sid} | " + " | ".join(
                (_c(f"{p}.{k}", s[f"{p}.{k}"]) if sid == "all" and s.get(f"{p}.{k}") is not None
                 else str(_d(s.get(f"{p}.{k}")))) for k in DETAIL_KEYS) + " |")
    return L


def gate_bench_markdown(b: dict) -> list[str]:
    if not b:
        return []
    L = ["", "## Gate bench (generated cases, evals/gate_bench.py)", "",
         f"{_c('gate_bench.correct', b['correct'])}/{_c('gate_bench.cases', b['cases'])} gate verdicts correct on generated "
         "cases, each on its own clean-room copy of golden_acme. Expected verdicts come from the topology config, decided "
         "before the run (seeded, not filtered by outcome). This set was used for development: its first run exposed "
         "three gate bugs that were then fixed (a change on a component with nothing upstream was never proposed; a "
         "bystander change was confirmed when the anomaly showed only at the symptom; G5's bound ignored reconvergent "
         "paths).", "",
         "| category | what the case is | correct |", "|---|---|---|"]
    desc = {"G2": "true cause + same-minute distractors with no failure path → eliminated by G2",
            "G5": "true cause + a distractor reachable only through best-effort edges → eliminated by G5 (max flow)",
            "origin": "true cause + a healthy distractor with a synchronous path → eliminated by the origin test",
            "abstain": "a component degrades with no change on it (+ benign deploys) → no change blamed",
            "control": "benign deploys, nothing degraded → NO_INCIDENT"}
    for cat, x in b["by_category"].items():
        L.append(f"| {cat} | {desc.get(cat, cat)} | {_c(f'gate_bench.{cat}.correct', x['correct'])}/"
                 f"{_c(f'gate_bench.{cat}.cases', x['cases'])} |")
    h = b.get("_heldout")
    if h:
        L += ["", f"**Held-out:** {_c('gate_bench_heldout.correct', h['correct'])}/{_c('gate_bench_heldout.cases', h['cases'])} "
              f"on cases generated from a new seed ({_c('gate_bench_heldout.seed', h['seed'])}) after the fixes, never used "
              "for development."]
    if b.get("failures"):
        L += ["", "Failures (reported as they are):", ""]
        L += [f"- `{f['id']}` ({f['category']}; alert on {f['symptom']}, origin {f['origin']}): {'; '.join(f['why'])[:300]}"
              for f in b["failures"]]
    return L


def gate_bench_notes(b: dict) -> list[str]:
    notes = []
    fails = b.get("failures") or []
    leaf = [f for f in fails if f["category"] in ("G2", "G5", "origin") and f["symptom"] == f["origin"]
            and f["got"]["outcome"] != "CONFIRMED"]
    if leaf:
        notes.append(f"Gate bench: {len(leaf)} case(s) where the change is ON the alerting component itself were not "
                     "confirmed (escalated with no sweep): " + ", ".join(sorted({f['origin'] for f in leaf})) + ". These "
                     "components have no upstream dependencies, and the suspect search (Q-SUS-1) returns nothing when "
                     "the symptom has no upstream scope, so the change on the symptom itself is never proposed.")
    blame = [f for f in fails if f["category"] == "abstain" and f["got"]["outcome"] == "CONFIRMED"]
    if blame:
        notes.append(f"Gate bench: {len(blame)} no-change case(s) blamed a healthy same-window deploy that has a "
                     "synchronous path to the alert. The origin test only eliminates a measured-healthy suspect when "
                     "another suspect is measured anomalous; when the real origin has no change, nothing is hot and "
                     "the healthy upstream deploy passes G2–G5. A false blame the gate does not yet prevent.")
    return notes


def _truth(sid: str) -> dict:
    """Grader-only truth (evals/ may read it; the product never does)."""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "data" / "scenarios" / f"{sid}.truth.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _rank(ranking: list, cause: str) -> tuple[int, int] | None:
    """(rank of cause, how many others share its score) in a [[change, score], …] list (lower score = higher rank)."""
    d = {c: x for c, x in ranking}
    if cause not in d:
        return None
    return 1 + sum(1 for _, x in ranking if x < d[cause]), sum(1 for _, x in ranking if x == d[cause]) - 1


def _why(sid: str, v: dict, s: dict) -> str:
    """The sweep's reason for eliminating a look-alike, with its numbers claim-tagged from latest.json."""
    k = f"{sid.lower()}.{v['change']}"
    if v["reason"].startswith("G5") and s.get(f"{k}.max_flow") is not None:
        return (f"{v['change']}: G5, max flow {_c(f'{k}.max_flow', s[f'{k}.max_flow'])} < needed "
                f"{_c(f'{k}.needed', s[f'{k}.needed'])}")
    gate = v["reason"].split(":")[0]
    return f"{v['change']}: {gate}" + {"G2": " (no path to the symptom)", "G4 origin": " (measured healthy)"}.get(gate, "")


def naive_vs_markdown(out: dict, run_name: str, s: dict | None = None) -> str:
    """docs/NAIVE_VS_FAULTLINE.md: where naive recency or vector cosine ranks the real cause vs what Faultline did,
    generated from the run's first trial per arm (never hand-written)."""
    by: dict = defaultdict(dict)
    for t in out["trials"]:
        if t["trial"] == 1:
            by[t["scenario"]][t["arm"]] = t
    L = ["# Naive vs Faultline: rank inversions", "",
         f"> GENERATED by `evals/report.py` from `evals/results/{run_name}`. Do not edit by hand.", "",
         "Where does each method put the real cause? *Naive* ranks the window's changes by closeness to the onset (ties "
         "share a rank). *Vector* ranks them by cosine distance between each change title's embedding and the incident's "
         "(template Q-CONTRAST-VEC, computed in FalkorDB). Faultline does not rank to decide: the gate eliminates "
         "look-alikes with a path and a max-flow test, and abstains when nothing passes. A rank inversion is a look-alike "
         "ranked at or above the real cause.", "",
         "| scenario | real cause | naive: rank of the cause (its top pick) | vector: rank of the cause (its top pick) | "
         "Faultline (A3) | why the look-alikes lost (A3 sweep) |", "|---|---|---|---|---|---|"]
    inv = {"N": 0, "V": 0, "A3": 0}
    ranked = {"N": 0, "V": 0}
    graded = 0
    for sid in out["scenarios"]:
        row, cause = by.get(sid) or {}, _truth(sid).get("cause")
        cells = []
        for arm in ("N", "V"):
            t = row.get(arm)
            if not t or "ranking" not in t:
                cells.append("—" if not t else "not recorded in this run")
                continue
            if not t["ranking"]:
                cells.append("no change in the window")
                continue
            top = t["ranking"][0][0]
            r = _rank(t["ranking"], cause) if cause else None
            if not cause:
                cells.append(f"no real cause; blames {top}")
                continue
            ranked[arm] += 1
            if r is None:
                cells.append(f"not ranked ({top})")
                inv[arm] += 1
                continue
            cells.append(f"{r[0]}" + (f", tied with {r[1]}" if r[1] else "") + f" ({top})")
            inv[arm] += int(r[0] > 1 or r[1] > 0)
        a = row.get("A3") or {}
        if cause:
            graded += 1
            inv["A3"] += int(not (a.get("outcome") == "CONFIRMED" and a.get("cause") == cause))
        why = "; ".join(_why(sid, x, s or {}) for x in a.get("sweep") or [] if x["status"] == "eliminated")
        verdict = (a.get("outcome") or "—") + (f" {a['cause']}" if a.get("cause") else "")
        L.append(f"| {sid} | {cause or '— (none)'} | {cells[0]} | {cells[1]} | {verdict} | {why or '—'} |")
    def n_inv(arm: str) -> str:
        return f"{inv[arm]} rank inversion(s) in {ranked[arm]}" if ranked[arm] else "no ranking recorded"

    L += ["", f"On the {graded} scenarios with a real cause: naive {n_inv('N')}, vector {n_inv('V')}; Faultline "
          f"{inv['A3']} wrong or missing confirmed cause(s).", "",
          "On controls and abstentions (no real cause) naive and vector still name a change whenever one is in the window: "
          "neither can abstain. Honest note: vector similarity can rank the real cause first (the change titles are "
          "self-authored and descriptive); what it cannot do is reject the look-alike with a reason or say that no change "
          "caused the incident.", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ retroactive preflight backtest (evals/backtest.py)
VERDICTS = ("block", "require_review", "allow")
BT_KEYS = ("prs", "causing", "catch_rate", "block_rate", "review_rate", "flag_rate", "false_flag_rate", "precision", "auroc")
BT_VARIANTS = {"full": "the gate as it ships", "no_past_incidents": "past-incidents term weighted 0 (structure only)",
               "flow_exposure": "preflight v2, pre-registered and not adopted: algo.maxFlow exposure, as of each merge"}
BT_SEGMENTS = {"all": "whole history", "first_third": "first third", "last_third": "last third"}


def backtest_summary(bt: dict) -> dict:
    s: dict = {}
    for t, r in bt.items():
        p = f"backtest.{t}"
        s[f"{p}.prs"], s[f"{p}.causing_prs"] = r["prs"], r["causing_prs"]
        for v in BT_VARIANTS:
            for seg, m in (r["variants"].get(v) or {}).items():
                s.update({f"{p}.{v}.{seg}.{kk}": m[kk] for kk in BT_KEYS})
        for lab, row in r["variants"]["full"]["all"]["confusion"].items():
            s.update({f"{p}.full.confusion.{lab}.{verdict}": n for verdict, n in row.items()})
        s.update({f"{p}.leaky_now.all.{kk}": r["variants"]["leaky_now"]["all"][kk] for kk in ("catch_rate", "flag_rate", "auroc")})
        s.update({f"{p}.diag.{kk}": vv for kk, vv in r["diagnostics"].items()})
        for seg in ("first_third", "last_third"):
            s[f"{p}.memory_auroc_gain.{seg}"] = _sub(r["variants"]["full"][seg]["auroc"],
                                                     r["variants"]["no_past_incidents"][seg]["auroc"])
    return s


def _c(key: str, value) -> str:
    """A claim-tagged value (scripts/check_claims.py checks it against latest.json)."""
    return f"<!-- claim:{key} -->{_d(value)}<!-- /claim -->"


def backtest_markdown(bt: dict) -> list[str]:
    if not bt:
        return []
    L = ["", "## Preflight backtest (each historical PR scored as of its merge time)", "",
         "Every merged PR in the golden graphs, scored read-only by the production preflight (`preflight/score.py`, the "
         "functions `preflight_change` calls; `weights.yaml` unchanged) **as of its `merged_at`**: an incident counts only "
         "if it was opened before the merge; ownership, runbooks, commit counts and team membership are read as of the "
         "same instant. *Causing* = the PR's deploy CAUSED an incident in the graph's history. *Catch* = a causing PR got "
         "block or require_review; *flag* = any PR did (the alert-fatigue cost); *precision* = causing PRs among the "
         "flagged; AUROC = P(risk of a causing PR > risk of another PR), ties 0.5. Thirds split the merge-time window.", "",
         "| tenant | variant | history | PRs | causing | catch | block | review | flag | false flag | precision | AUROC |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t, r in bt.items():
        for v, vdesc in BT_VARIANTS.items():
            if v not in r["variants"]:  # a run recorded before this variant existed
                continue
            for seg, sdesc in BT_SEGMENTS.items():
                k = f"backtest.{t}.{v}.{seg}"
                L.append(f"| {t} | {vdesc} | {sdesc} | " + " | ".join(_c(f"{k}.{kk}", r["variants"][v][seg][kk]) for kk in BT_KEYS) + " |")
    L += ["", "Confusion (the gate as it ships, whole history):", "",
          "| tenant | PRs that were | block | require_review | allow |", "|---|---|---|---|---|"]
    for t, r in bt.items():
        for lab, row in r["variants"]["full"]["all"]["confusion"].items():
            L.append(f"| {t} | {lab} | " + " | ".join(_c(f"backtest.{t}.full.confusion.{lab}.{x}", row[x]) for x in VERDICTS) + " |")
    L += [""]
    for t, r in bt.items():
        d, lk, full = r["diagnostics"], r["variants"]["leaky_now"]["all"], r["variants"]["full"]["all"]
        gain = {seg: _c(f"backtest.{t}.memory_auroc_gain.{seg}", _sub(r["variants"]["full"][seg]["auroc"],
                                                                      r["variants"]["no_past_incidents"][seg]["auroc"]))
                for seg in ("first_third", "last_third")}
        dg = {kk: _c(f"backtest.{t}.diag.{kk}", vv) for kk, vv in d.items()}
        lk = {kk: _c(f"backtest.{t}.leaky_now.all.{kk}", lk[kk]) for kk in ("catch_rate", "flag_rate", "auroc")}
        L.append(f"- **{t}** ({r['graph']}): PRs that saw their own incident = {dg['self_leaks']} (must be 0); causing PRs "
                 f"whose components had an earlier incident = {dg['causing_with_prior_incidents']}/{r['causing_prs']}; PRs with "
                 f"ChangeFacts = {dg['prs_with_change_facts']}, decision term non-zero = {dg['decision_term_nonzero']}; "
                 f"unscorable = {dg['unscorable']}; truncated impact reads = {dg['impact_truncated']}. AUROC added by the "
                 f"past-incidents term (gate minus structure only): first third {gain['first_third']}, last third "
                 f"{gain['last_third']}. Contrast only, not a result: scored on today's graph (future leaking in), catch "
                 f"{lk['catch_rate']} / flag {lk['flag_rate']} / AUROC {lk['auroc']} vs as-of {full['catch_rate']} / "
                 f"{full['flag_rate']} / {full['auroc']}.")
    L += ["", "**Honest limits.** The history is synthetic. Incident causes are drawn from per-archetype component lists, so "
          "a component that caused incidents before is, by construction, likely to cause the next one: the past-incidents "
          "term is partly self-fulfilling here, which is why the structure-only row (blast, revenue, betweenness, bus factor, "
          "uncertainty) is reported next to it. Historical PRs carry no ChangeFacts (only file touches), so the decision term "
          "(Q-DEC-1) cannot fire and nothing is blocked for contradicting a decision. Topology is not time-versioned and is "
          "read as it is now. Incident-causing datastore config changes shipped without a PR and are outside this "
          "population. Weights and thresholds were not tuned on these results (pre-registered amendment, 2026-10-13)."]
    return L


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 4)


def backtest_notes(bt: dict) -> list[str]:
    notes = []
    for t, r in bt.items():
        full, struct = r["variants"]["full"]["all"], r["variants"]["no_past_incidents"]["all"]
        if (full["flag_rate"] or 0) >= 0.3:
            no_lift = (full["precision"] or 0) <= 1.1 * (full["base_rate"] or 0)
            notes.append(f"Preflight backtest ({t}): the gate flags {full['flag_rate']} of all historical PRs to catch "
                         f"{full['catch_rate']} of the incident-causing ones (precision {full['precision']} vs base rate "
                         f"{full['base_rate']}): a real alert-fatigue cost at the current thresholds"
                         + ("; at this threshold flagging is no better than flagging at random." if no_lift else "."))
        if struct["auroc"] is not None and struct["auroc"] < 0.65:
            notes.append(f"Preflight backtest ({t}): structure alone barely ranks causing PRs above the rest (AUROC "
                         f"{struct['auroc']}; with past incidents {full['auroc']}). Most of the separation comes from the "
                         "incident-memory term, which is partly self-fulfilling on this synthetic history.")
        if not full["block_rate"]:
            notes.append(f"Preflight backtest ({t}): nothing historical is blocked; without ChangeFacts the decision term cannot "
                         "fire, and the other terms alone stay under the block threshold.")
    if bt:
        notes.append("Preflight backtest: the as-of bus factor counts only earlier commits, but a person with no team "
                     "membership history (executives) keeps their current active flag, a small read of the present.")
    return notes


def _d(v):
    return "—" if v is None else v


ARM_DESC = {"N": "naive recency over the change files (also A4's ungated guess)",
            "V": "vector only: the change whose title embedding is nearest the incident's (cosine in FalkorDB)", "A2": "graph, memory off",
            "A3": "graph + memory (the product)", "A4": "FalkorDB off (the run cannot start: fails closed)",
            "A3-noG5": "the product with the max-flow sufficiency check (G5) switched off",
            "T": "telemetry only: the window's change whose own component shows the largest measured excess (no topology)",
            "A0": "LLM only (claude-opus-5-5, one trial): alert, raw service error rates, the change list (prompt v1: a change "
                  "id or none; no data-plane evidence)",
            "A1": "A0 plus vector-RAG context over runbooks, postmortems, ADRs and a text topology (prompt v1)",
            "A3L": "the product with the LLM investigator (claude-opus-5-5, one trial); the same gate decides"}


def markdown(out: dict, s: dict, run_name: str) -> str:
    out = with_llm_trials(out)
    L = ["# Results", "", f"> GENERATED by `evals/report.py` from `evals/results/{run_name}`. Do not edit by hand.", "",
         f"Run started {out['started']} (scenario trials done {out['finished']}; the checks below ran after that) · engine "
         f"FalkorDB {out['engine']} · keyless arms' investigator: {out['investigator']}"
         f" · N = {out['n']} per scenario per graph arm. The deterministic investigator makes those trials identical "
         "copies, so the effective N is the number of distinct scenarios (8, of which 5 have a cause); intervals below "
         "are Wilson 95 % over distinct scenarios. LLM arms A0, A1 and A3L come from `evals/results/llm_arms.json`.", ""]
    if out.get("skipped_arms"):
        L += [f"**Not run:** LLM arms {', '.join(out['skipped_arms'])} (need an API key and an approved budget).", ""]
    L += ["## Arms", "", "False blame is measured on the scenarios with a true cause only (the controls and no-incident scenarios "
          "have no cause to miss; what an arm does there is the abstention column).", "",
          "| arm | what it gets | top-1 | confident | false blame (on scenarios with a true cause) | abstention correct | outcome correct | confirmed causes | grounded | distractors rejected |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for arm in out["arms"]:
        p = f"arm.{arm}"
        L.append(f"| {arm} | {ARM_DESC.get(arm, arm)} | {s.get(f'{p}.top1')} | {_d(s.get(f'{p}.confident_rate'))} | {s.get(f'{p}.false_blame_rate')} | "
                 f"{s.get(f'{p}.abstention_correct_rate')} | {s.get(f'{p}.outcome_correct_rate')} | {s.get(f'{p}.confirmed_causes')} | "
                 f"{_d(s.get(f'{p}.grounded_rate'))} | {_d(s.get(f'{p}.distractors_rejected_rate'))} |")
    L += ["", "## Per scenario (outcome correct rate)", "", "| scenario | " + " | ".join(out["arms"]) + " |",
          "|---|" + "---|" * len(out["arms"])]
    for sid in out["scenarios"]:
        L.append(f"| {sid} | " + " | ".join(str(s.get(f"arm.{a}.{sid}.outcome_correct_rate")) for a in out["arms"]) + " |")
    L += audit_markdown(out, s)
    c = out.get("checks") or {}
    if c:
        L += ["", "## Product checks", ""]
        if "S13" in c:
            x = c["S13"]
            L.append(f"- **S13 concurrency**: {x['workers']} workers × {x['rounds']} rounds → {x['rounds_with_exactly_one_owner']}/"
                     f"{x['rounds']} rounds with exactly one owner, {x['lost_updates']} lost updates; RO read p50/p95 "
                     f"{x['ro_read_ms']['during_writes']['p50']}/{x['ro_read_ms']['during_writes']['p95']} ms during writes "
                     f"(quiet {x['ro_read_ms']['quiet']['p50']}/{x['ro_read_ms']['quiet']['p95']} ms).")
        if "S1b_cold_vs_warm" in c:
            x = c["S1b_cold_vs_warm"]
            L.append(f"- **Memory, S1b cold vs warm**: gate verdicts identical = {x['gate_verdicts_identical']}; family prior on the "
                     f"cause's component {x['cold']['prior_payment']} → {x['warm']['prior_payment']}; warm top precedent is the "
                     f"resolved S1 = {x['warm']['top_precedent_is_s1']}; derived runbook first = {x['warm']['derived_runbook_first']}; "
                     f"tool calls {x['cold']['tool_calls']} → {x['warm']['tool_calls']}.")
        if "S3b_cold_vs_warm" in c:
            x = c["S3b_cold_vs_warm"]
            L.append(f"- **Memory, S3b cold vs warm** (second scenario, fix: {x['fix']}): gate verdicts identical = "
                     f"{x['gate_verdicts_identical']}; prior on the cause's component {x['cold']['prior']} → {x['warm']['prior']}; "
                     f"warm top precedent is the resolved S3 = {x['warm']['top_precedent_is_first']}; tool calls "
                     f"{x['cold']['tool_calls']} → {x['warm']['tool_calls']}.")
        if "S6" in c:
            L.append(f"- **S6 preflight**: {c['S6']['verdict']} (risk {c['S6']['risk']}), contradicts {', '.join(c['S6']['decisions'])}.")
        if "S5" in c:
            L.append(f"- **S5 bad fix**: verdict {c['S5']['verdict']}, success written = {c['S5']['success_written']}, stage {c['S5']['stage']}.")
        if "S9" in c:
            L.append(f"- **S9 unknown verification**: verdict {c['S9']['verdict']}, success written = {c['S9']['success_written']}; "
                     f"reconciler → {c['S9'].get('reconciled')}.")
        if "S10" in c:
            x = c["S10"]
            L.append(f"- **S10 forget**: answer cited ADR-021 before = {x['before_cites_ADR-021']}, after = {x['after_cites_ADR-021']}; "
                     f"receipt {x['receipt_nodes']} nodes / {x['receipt_relationships']} relationships; vectors still found "
                     f"{x['vectors_still_found']}.")
        if "S7" in c:
            L.append(f"- **S7 isolation (globex vs acme)**: {c['S7']['passed']} checks passed, {c['S7']['failed']} failed, "
                     f"{c['S7']['skipped']} skipped (ACL user check skipped when ACL passwords are not configured).")
        if "S8" in c:
            x = c["S8"]
            L.append(f"- **S8 recurring family (globex)**: {x['precedents_in_family']}/{x['precedents']} recalled precedents are in "
                     f"the family (size {x['family_size']}); first runbook derived = {x['first_runbook_derived']} "
                     f"(support {x['first_runbook_support']}).")
        if "S11" in c:
            x = c["S11"]
            L.append(f"- **S11 owner gone (globex)**: bus factor {x['bus_factor']}, top contributor inactive = "
                     f"{x['top_contributor_inactive']}; first person paged is active = {x['paged_first_active']}; "
                     f"escalation tree edges {x['escalation_edges']}.")
        if c.get("S14"):
            L.append(f"- **S14 alert storm** (one fault's storm + an unrelated concurrent fault; INTAKE groups with algo.WCC over "
                     f"the edges that can carry an alert-worthy rise): incidents opened {_c('s14.incidents_opened', s.get('s14.incidents_opened'))}"
                     f" of {_c('s14.incidents_expected', s.get('s14.incidents_expected'))}, groups correct = "
                     f"{_c('s14.groups_correct', s.get('s14.groups_correct'))}; alerts placed on the right incident (opened + "
                     f"attached late) {_c('s14.alerts_placed_k', s.get('s14.alerts_placed_k'))}/"
                     f"{_c('s14.alerts_placed_n', s.get('s14.alerts_placed_n'))}; cross-fault merge = "
                     f"{_c('s14.cross_fault_merge', s.get('s14.cross_fault_merge'))}; causes confirmed "
                     f"{_c('s14.causes_found', s.get('s14.causes_found'))}/{_c('s14.causes_expected', s.get('s14.causes_expected'))},"
                     f" each incident's distractor rejected = {_c('s14.all_distractors_rejected', s.get('s14.all_distractors_rejected'))}."
                     + (f" Control, every alert in ONE incident: {_c('s14.ungrouped.outcome', s.get('s14.ungrouped.outcome'))}, causes "
                        f"confirmed {_c('s14.ungrouped.causes_found', s.get('s14.ungrouped.causes_found'))}, confident "
                        f"misattribution = {_c('s14.ungrouped.confident_misattribution', s.get('s14.ungrouped.confident_misattribution'))}."
                        if "s14.ungrouped.outcome" in s else ""))
        if "chaos" in c:
            x = c["chaos"]
            f = x.get("final") or {}
            L.append(f"- **SIGKILL chaos** (kill -9 between execute and verify, restart, reconcile): exactly once = "
                     f"{x.get('exactly_once')}; PRs for the idempotency key {f.get('prs')}, verdict {f.get('verdict')}, "
                     f"write-back {f.get('writeback')}, stage {f.get('stage')}; naive retry without the key merged "
                     f"{(x.get('control_naive_retry') or {}).get('merged_prs')} PRs (control).")
    L += detail_markdown(out, s)
    L += gate_bench_markdown({**(c.get("gate_bench") or {}), "_heldout": c.get("gate_bench_heldout")} if c.get("gate_bench") else {})
    L += scale_markdown(current_scale(c))
    L += futures_markdown(c.get("futures") or {})
    L += mismatch_markdown(c.get("mismatch") or {})
    L += learning_markdown(c.get("learning") or {})
    L += ladder_markdown(c.get("ladder") or {}, s)
    L += robustness_markdown(c.get("robustness") or {})
    L += perf_markdown(c.get("perf_vs_flat") or {})
    L += deep_markdown(c.get("deep_bench") or {})
    L += context_markdown(c.get("context_eval") or {})
    if c.get("scaling"):
        L += ["", "## Distractor scaling (S1 + k same-minute decoy deploys)", "",
              "| decoys | outcome | cause correct | confident | wrong confident claim | naive top-1 |", "|---|---|---|---|---|---|"]
        L += [f"| {x['decoys']} | {x['outcome']} | {x['correct']} | {x['confident']} | {x['wrong_confident']} | {x['naive_top1']} |"
              for x in c["scaling"]]
    if c.get("brain"):
        b = c["brain"]
        L += ["", "## Company brain (self-authored question set)", "",
              f"{b['correct']}/{b['questions']} correct: {b['answerable'] - len([f for f in b['failures'] if f['missing']])}"
              f"/{b['answerable']} answerable questions cite every expected node; {b['unanswerable_honest']}/{b['unanswerable']} "
              f"unanswerable questions answered honestly with no citations. Citation guard passed {b['guard_ok']}/{b['questions']}; "
              f"p50 {b['ms_p50']} ms; knowledge unchanged = {b['knowledge_unchanged']}. "
              "The questions are ours (no external benchmark)."]
    L += backtest_markdown(c.get("backtest") or {})
    L += live_markdown(live_bench())
    if c.get("mutation"):
        m = c["mutation"]
        L += ["", "## Safety invariants under mutation (scripts/mutation_check.py)", "",
              f"Each safety invariant was broken in a scratch copy of the package; {m['killed']}/{m['mutants']} mutants were "
              f"caught by a failing test ({m['survived']} survived, {m['errors']} errors).", "",
              "| mutant | invariant broken | result | caught by |", "|---|---|---|---|"]
        label = mutant_labels()   # the current wording of each invariant, by mutant id (the result is the recorded run's)
        L += [f"| {r['id']} | {label.get(r['id'], r['invariant'])} | {r['status']} | "
              f"{', '.join(t.split('::')[-1] for t in r['tests'] or [])} |" for r in m["rows"]]
    if c.get("profile"):
        timed = {k: v for k, v in c["profile"].items() if v.get("engine_ms_p50") is not None}
        runs = max((v.get("runs") or 0) for v in timed.values()) if timed else 0
        L += ["", f"## Query cost (GRAPH.PROFILE, engine ms, nearest-rank p50 / p95 of {runs})", "",
              "| template | engine ms p50 | engine ms p95 | rows |", "|---|---|---|---|"]
        L += [f"| `{k}` | {v['engine_ms_p50']} | {_d(v.get('engine_ms_p95'))} | {v['rows']} |"
              for k, v in sorted(timed.items(), key=lambda kv: -kv[1]['engine_ms_p50'])]
    L += ["", "## What didn't work / limits (derived from this run)", ""]
    notes = []
    if "S1b_cold_vs_warm" in c and c["S1b_cold_vs_warm"]["cold"]["tool_calls"] == c["S1b_cold_vs_warm"]["warm"]["tool_calls"]:
        notes.append("Warm memory did not reduce tool calls for the deterministic investigator: it measures every suspect "
                     "anyway. Memory changes ordering and the plan's evidence, not the amount of work here.")
    if s.get("arm.N.top1") not in (None, 0.0):
        notes.append(f"The naive recency baseline is not useless: top-1 {s['arm.N.top1']} (ties scored 1/k). It cannot abstain, "
                     f"so it blames a change on every control (abstention {s.get('arm.N.abstention_correct_rate')}).")
    if s.get("arm.A2.top1") == s.get("arm.A3.top1"):
        notes.append("Memory off (A2) and on (A3) reach the same root causes on these scenarios: the gate decides from fresh "
                     "evidence, by design. Memory's effect is in ordering, runbooks and the plan.")
    if out.get("skipped_arms"):
        notes.append("No LLM arm ran, so there is no LLM-vs-graph comparison in this run.")
    for x in c.get("scaling") or []:
        if not x["correct"] or not x["confident"]:
            notes.append(f"With {x['decoys']} same-minute decoys the product ended {x['outcome']} (confident={x['confident']}): "
                         "decoys on synchronous dependencies cannot be eliminated by structure alone without a measurement "
                         "against them; the gate refuses a confident claim rather than guessing.")
            break
    notes += backtest_notes(c.get("backtest") or {})
    notes += gate_bench_notes(c.get("gate_bench") or {})
    notes += scale_notes(current_scale(c))
    notes += robustness_notes(c.get("robustness") or {}, c.get("ladder") or {}, c.get("perf_vs_flat") or {})
    wrong = sorted({(t["scenario"], next((f"{o['kind']} {o['target']}" for o in (t.get("detail") or {}).get("options", [])
                                          if o["enabled"] and o["kind"] != "open_issue"), "?"))
                    for t in out["trials"] if t["arm"] == "A3" and t.get("target_correct") is False})
    if wrong:
        notes.append("Wrong first fix target (A3): " + "; ".join(f"{sid} offers {o} first" for sid, o in wrong) + ". On the "
                     "data incident the min-cut lever found is a service flag on the payment → checkout edge, which does "
                     "not touch the corrupted rows; the data repair that would stays disabled keyless (the deterministic "
                     "investigator cannot author SQL).")
    if s.get("arm.A3.fix_offered_rate") is not None and s["arm.A3.fix_offered_rate"] < 1.0:
        notes.append(f"Correct target is graded only where the plan offered an enabled production-changing fix (A3: "
                     f"{s['arm.A3.fix_offered_rate']} of graded trials).")
    notes.append("Trials are deterministic: N = 3 checks reproducibility, not statistical variance. All scenarios and "
                 "brain questions are self-authored.")
    L += [f"- {n}" for n in notes] or ["- (none recorded)"]
    L += run_history_markdown()
    return "\n".join(L) + "\n"


def run_history_markdown(results_dir=None) -> list[str]:
    """Every scored run kept in evals/results/, oldest first: the headline numbers of each, so a reader can see they
    are stable across runs (and where they moved), not one picked run. Read from the run files themselves."""
    import json
    from pathlib import Path

    d = Path(results_dir) if results_dir else Path(__file__).resolve().parent / "results"
    rows = []
    for p in sorted(d.glob("run_*.json")):
        try:
            out = json.loads(p.read_text())
            s = summarize(out)
        except Exception as e:  # an old run file that the current summary cannot read: said, not skipped silently
            rows.append(f"| {p.stem} | unreadable by the current report ({type(e).__name__}) | | | | | | |")
            continue
        c = out.get("checks") or {}
        mut = c.get("mutation") or {}
        gb = c.get("gate_bench") or {}
        rows.append(f"| {p.stem} | {(out.get('started') or '')[:16]} | {','.join(out.get('arms') or [])} | "
                    f"{len(out.get('scenarios') or [])} | "
                    + " | ".join(str(_d(s.get(f"arm.{a}.top1"))) for a in ("A3", "A3-noG5", "V", "N", "T"))
                    + f" | {mut.get('killed', '—')}/{mut.get('mutants', '—')} | {gb.get('correct', '—')}/{gb.get('cases', '—')} |")
    if not rows:
        return []
    return ["", "## Run history (every scored run in evals/results/, oldest first)", "",
            "Generated from the run files. All runs use the deterministic investigator; arms and checks were added over "
            "time (a dash means not run). The code between runs changed.", "",
            "| run | started | arms | scenarios | A3 top-1 | A3-noG5 | V | N | T | mutants | gate bench |",
            "|---|---|---|---|---|---|---|---|---|---|---|", *rows]
