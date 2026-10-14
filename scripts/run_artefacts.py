"""Run artefacts, derived from a run's graph export in examples/<run>/ (the export is the graph's record;
these are views of it, never a second source):

  transcript.jsonl  the run in order: stage changes, every investigator → tool call and its result, every gate verdict
                    (keyless runs have no model turns: the deterministic investigator's calls ARE the transcript)
  verify.txt        the action's 3-valued verdict per channel and the write-back `verified n/m` (or why there is none)
  pr.md             the exact approved change (branch, commit, diff, PR body, link) when an action was executed
  cost.json         model ids, tokens, US$, wall time (keyless: tokens 0, US$ 0)

Also `check(run_dir)`: re-read the committed artefacts and confirm they agree with the export (judge-check
"write-back re-read"). Works on any examples/<run>/ (incident runs and the preflight record).

    PYTHONPATH=backend uv run python scripts/run_artefacts.py [examples/<run> …]      # (re)write
    PYTHONPATH=backend uv run python scripts/run_artefacts.py --check                  # verify every example
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
WB = re.compile(r"write-back verified (\d+)/(\d+)")
KEYLESS_NOTE = ("deterministic investigator (keyless): no model turns; the transcript is the ordered stage changes, tool "
                "calls and gate verdicts recorded in the graph for this run")


def _load(d: Path, name: str):
    p = d / name
    if not p.exists():
        return None
    if name.endswith(".jsonl"):
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return json.loads(p.read_text())


def _events(d: Path) -> list[dict]:
    return _load(d, "events.jsonl") or []


def _manifest(d: Path) -> dict:
    return _load(d, "manifest.json") or {}


def _executed(plan: dict | None) -> list[dict]:
    return [o for o in (plan or {}).get("options", []) if o.get("status") in ("executed", "failed") or o.get("verdict")]


def _writeback(events: list[dict]) -> tuple[int, int] | None:
    for e in reversed(events):
        m = WB.search(e.get("note") or "") if e.get("type") == "stage" else None
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


# ------------------------------------------------------------------ writers
def transcript(d: Path) -> list[dict]:
    man, events = _manifest(d), _events(d)
    out = [{"seq": 0, "role": "meta", "investigator": man.get("investigator"), "model": man.get("model"),
            "scenario": man.get("scenario"), "incident": man.get("incident"), "run": man.get("run"),
            "note": KEYLESS_NOTE if not man.get("model") else "model turns are recorded as tool calls in the graph"}]
    stage = None
    for e in events:
        if e["type"] == "stage":
            stage = e["stage"]
            out.append({"role": "system", "stage": stage, "at": e.get("at"), "note": e.get("note") or ""})
        elif e["type"] == "tool_call":
            out.append({"role": "investigator", "stage": stage, "at": e.get("at"), "call": e["tool"],
                        "template": e.get("template"), "params": json.loads(e["params"]) if e.get("params") else None})
            out.append({"role": "tool", "stage": stage, "at": e.get("at"), "tool": e["tool"], "rows": e.get("rows"),
                        "ms": e.get("ms"), "evidence_id": e.get("evidence_id"), "summary": e.get("summary")})
        elif e["type"] == "gate_run":
            out.append({"role": "gate", "stage": stage, "at": e.get("at"), "gate_run": e.get("id"), "cause": e.get("cause"),
                        "origin": e.get("origin"), "passed": e.get("passed"), "confident": e.get("confident"),
                        "failed": [c["name"] + ": " + c["detail"] for c in e.get("checks") or [] if c.get("passed") is False]})
    for i, x in enumerate(out):
        x["seq"] = i
    return out


def verify_text(d: Path) -> str:
    man, events, plan = _manifest(d), _events(d), _load(d, "plan.json")
    if man.get("kind") == "preflight":
        return "\n".join([f"preflight run {man.get('run')} · {man.get('pr')} · scenario {man.get('scenario')}", "",
                          f"verdict: {man.get('verdict')} (risk {man.get('risk')}); contradicts {', '.join(man.get('decisions') or [])}",
                          "action: none (a preflight gates a PR; it executes nothing)",
                          "write-back: none written (verified 0/0)"]) + "\n"
    head = [f"run {man.get('run')} · incident {man.get('incident')} · scenario {man.get('scenario')} · "
            f"final stage {man.get('final_stage')}", ""]
    acts = _executed(plan)
    if not acts:
        why = {"NO_INCIDENT": "no incident (negative proof accepted): nothing to act on",
               "AWAITING_APPROVAL": "awaiting a human: no option was approved in this recording"}.get(
            man.get("final_stage"), "no action was approved in this run")
        return "\n".join(head + [f"action: none ({why})", "verdict: n/a", "write-back: none written (verified 0/0)"]) + "\n"
    lines = list(head)
    for o in acts:
        lines.append(f"action {o['id']} · {o['kind']} · {o['option']} · approval {o.get('approval_id')}")
        lines.append(f"  external ref: {o.get('external_ref')}")
        lines.append(f"  verdict: {o.get('verdict')} — {o.get('explanation')}")
        for name, ch in (o.get("channels") or {}).items():
            ok = {True: "ok", False: "NOT ok", None: "unreadable"}.get(ch.get("ok"), str(ch.get("ok")))
            lines.append(f"  channel {name}: {ok}" + (f" ({ch['served_by']})" if ch.get("served_by") else ""))
            for t, v in (ch.get("targets") or {}).items():
                lines.append(f"    {t}: {'ok' if v.get('ok') else ('n/a' if v.get('ok') is None else 'NOT ok')} "
                             + json.dumps({k: v[k] for k in v if k != 'ok'}, sort_keys=True))
            for k in ("invariants", "kpi_anomaly_ratio", "kpi_status", "error"):
                if ch.get(k) is not None:
                    lines.append(f"    {k}: {ch[k]}")
    wb = _writeback(events)
    applied = any(o.get("verdict") == "APPLIED" for o in acts)
    if wb:
        lines.append(f"write-back: verified {wb[0]}/{wb[1]} (re-read through a separate read-only connection)")
    elif applied:
        lines.append("write-back: no verified write-back recorded")
    else:
        lines.append("write-back: success NOT written (verdict was not APPLIED); verified 0/0")
    return "\n".join(lines) + "\n"


def pr_markdown(d: Path) -> str | None:
    acts = [o for o in _executed(_load(d, "plan.json")) if (o.get("spec") or {}).get("kind")]
    if not acts:
        return None
    man = _manifest(d)
    out = [f"# Receipt: the change Faultline executed for {man.get('incident')}", ""]
    for o in acts:
        s = o["spec"]
        out += [f"## {o['option']} ({o['kind']})", "",
                f"- **link:** {o.get('external_ref')}",
                f"- **verdict:** {o.get('verdict')} — {o.get('explanation')}",
                f"- **approval:** {o.get('approval_id')} (plan hash `{(o.get('plan_hash') or '')[:16]}…`)",
                f"- **idempotency key:** `{s.get('idem')}`" + (f" → branch `{s['branch']}`" if s.get("branch") else ""), ""]
        if s.get("commit"):
            out += ["**Commit message**", "", "```", s["commit"], "```", ""]
        if s.get("before") is not None and s.get("after") is not None:
            diff = "".join(difflib.unified_diff(s["before"].splitlines(keepends=True), s["after"].splitlines(keepends=True),
                                                fromfile=f"a/{s.get('file')}", tofile=f"b/{s.get('file')}"))
            out += ["**Diff**", "", "```diff", diff.rstrip("\n"), "```", ""]
        elif s.get("diff"):
            out += ["**Diff**", "", "```diff", s["diff"].rstrip("\n"), "```", ""]
        if s.get("pr_body") or s.get("body"):
            out += ["**PR / issue body**", "", "```", (s.get("pr_body") or s.get("body")).rstrip("\n"), "```", ""]
        if s.get("rollback"):
            out += [f"**Rollback:** {s['rollback']}", ""]
    if (man.get("github") or "").startswith("simulated"):
        out += ["_Keyless recording: the PR lives in the simulated GitHub of this run's clean room (labelled \"(simulated)\")._", ""]
    return "\n".join(out)


def cost(d: Path) -> dict:
    man, events = _manifest(d), _events(d)
    ats = [e["at"] for e in events if e.get("at")]
    stages = {e["stage"]: e["at"] for e in events if e.get("type") == "stage" and e.get("at")}
    first = min(ats) if ats else None
    decided = next((stages[s] for s in ("AWAITING_APPROVAL", "NO_INCIDENT", "UNKNOWN_ESCALATED", "FAILED") if s in stages), None)
    usage = man.get("usage") or {}
    return {"investigator": man.get("investigator"), "model_ids": [man["model"]] if man.get("model") else [],
            "keyless": not man.get("model"), "tokens": {"input": int(usage.get("input_tokens", 0)),
                                                        "output": int(usage.get("output_tokens", 0))},
            "usd": float(usage.get("usd", 0.0)), "tool_calls": sum(1 for e in events if e.get("type") == "tool_call"),
            "wall_s_to_decision": round((decided - first) / 1000, 3) if decided and first else man.get("wall_s"),
            "wall_s_total": round((max(ats) - first) / 1000, 3) if len(ats) > 1 else man.get("wall_s"),
            "note": "wall time from the graph's event timestamps (decision = AWAITING_APPROVAL or a terminal stage; total "
                    "includes the time a human took to approve)"}


def write(d: Path) -> list[str]:
    d = Path(d)
    files = []
    if (d / "events.jsonl").exists():
        (d / "transcript.jsonl").write_text("".join(json.dumps(x, default=str) + "\n" for x in transcript(d)))
        (d / "verify.txt").write_text(verify_text(d))
        files += ["transcript.jsonl", "verify.txt"]
        pr = pr_markdown(d)
        if pr:
            (d / "pr.md").write_text(pr)
            files.append("pr.md")
    if not (d / "cost.json").exists() or (d / "events.jsonl").exists():
        (d / "cost.json").write_text(json.dumps(cost(d), indent=2) + "\n")
        files.append("cost.json")
    return files


# ------------------------------------------------------------------ re-read check (judge-check)
def check(d: Path) -> dict:
    """Re-read a committed example: required files present; verify.txt and pr.md match what the export says; a
    RESOLVED run has an APPLIED action with every channel ok and a fully verified write-back; a rejected fix
    wrote no success. Returns {ok, writeback: (n, m) | None, problems}."""
    d = Path(d)
    man, problems = _manifest(d), []
    if man.get("kind") == "preflight":
        need = ["manifest.json", "cost.json", "preflight.json", "report.md", "transcript.jsonl", "verify.txt"]
    else:
        need = ["manifest.json", "cost.json", "events.jsonl", "gate_runs.json", "report.md", "transcript.jsonl", "verify.txt"]
    problems += [f"missing {f}" for f in need if not (d / f).exists()]
    wb = None
    if (d / "events.jsonl").exists() and not problems:
        if (d / "verify.txt").read_text() != verify_text(d):
            problems.append("verify.txt does not match the export (regenerate: scripts/run_artefacts.py)")
        pr = pr_markdown(d)
        if pr is not None and (not (d / "pr.md").exists() or (d / "pr.md").read_text() != pr):
            problems.append("pr.md missing or does not match the executed action")
        wb = _writeback(_events(d))
        acts = _executed(_load(d, "plan.json"))
        if man.get("final_stage") == "RESOLVED":
            ok_act = [o for o in acts if o.get("verdict") == "APPLIED"
                      and all(c.get("ok") is not False for c in (o.get("channels") or {}).values())]
            if not ok_act:
                problems.append("RESOLVED without an APPLIED action whose channels are all ok")
            if not wb or wb[0] != wb[1]:
                problems.append(f"RESOLVED without a fully verified write-back ({wb})")
        if wb and not any(o.get("verdict") == "APPLIED" for o in acts):
            problems.append("a success write-back is recorded but no action was verified APPLIED")
    for name in ("remediation_rejected.json", "data_bad_fix_rejected.json"):
        if (d / name).exists():
            r = json.loads((d / name).read_text())
            if r.get("verdict") != "NOT_APPLIED" or r.get("success_written") is not False or not r.get("environment_restored"):
                problems.append(f"{name}: expected NOT_APPLIED, no success written, environment restored")
    return {"run": d.name, "ok": not problems, "writeback": wb, "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    dirs = [Path(x) for x in a.runs] or sorted(p for p in EXAMPLES.iterdir() if p.is_dir())
    if a.check:
        res = [check(d) for d in dirs]
        n = sum(r["writeback"][0] for r in res if r["writeback"])
        m = sum(r["writeback"][1] for r in res if r["writeback"])
        bad = [r for r in res if not r["ok"]]
        for r in bad:
            print(f"  {r['run']}: {'; '.join(r['problems'])}", file=sys.stderr)
        print(f"{len(res) - len(bad)}/{len(res)} runs consistent; write-back verified {n}/{m}")
        return 0 if not bad and n == m else 1
    for d in dirs:
        print(d.name, write(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
