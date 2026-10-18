"""Mutation check for the safety invariants: break one invariant at a time in a scratch copy of the package and
prove that a test notices. A mutant that survives means that invariant is not actually protected by the suite.

Each mutant is an exact source replacement that must match exactly once, so a mutant can't silently go stale
after a refactor; a mismatch is reported as an error. The listed tests must pass on the unmutated code first.

    uv run python scripts/mutation_check.py            # all mutants → docs/audit/mutation.json
    uv run python scripts/mutation_check.py M-G5 M-RO  # a subset

Needs `make up && make seed` (most of the killing tests are live). Copies live under tmp/mutants/ and are removed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tmp" / "mutants"
OUT = ROOT / "docs" / "audit" / "mutation.json"
S = "tests/live/test_scenarios_v2.py::"
R4 = "tests/live/test_review4_live.py::"
R5 = "tests/live/test_review5_live.py::"


@dataclass(frozen=True)
class Mutant:
    id: str
    invariant: str
    file: str            # relative to backend/faultline
    old: str
    new: str
    tests: tuple[str, ...]
    also: tuple[tuple[str, str, str], ...] = ()   # further (file, old, new) sites when the invariant has two guards


RO_CALL = "res = g.ro_query(t.text, params=params, timeout=timeout)"


MUTANTS = [
    Mutant("M-G2", "G2: no path, no claim (a suspect with no causal path is eliminated)", "agent/gate.py",
           'verdicts[change] = Verdict(change, target, [], None, "eliminated",',
           'verdicts[change] = Verdict(change, target, [], None, "candidate",',
           (S + "test_s1_hero_confirms_payment_rejects_email_by_flow_and_rec_by_path",)),
    Mutant("M-G5", "G5: a suspect whose max flow cannot carry the observed impact is eliminated", "agent/gate.py",
           "        if carriers:\n            out.append((c, b, max(carriers)))",
           "        if False:\n            out.append((c, b, max(carriers)))",
           (S + "test_s2_confirms_cutover_and_rejects_fx_by_flow",
            S + "test_s1_hero_confirms_payment_rejects_email_by_flow_and_rec_by_path")),
    Mutant("M-G6-MODEL", "G6: an elimination an investigator (a model) asserted never clears a rival; only the graph eliminates",
           "agent/gate.py",
           'h["status"] in ("open", "confirmed")\n                or (h["status"] == "eliminated" and h.get("status_by") == "investigator")))',
           'h["status"] in ("open", "confirmed")))',
           ("tests/live/test_model_cannot_move_g6.py",)),
    Mutant("M-TOOL-ELIM", "the investigator's tool refuses to eliminate a competitor (elimination is the gate's)", "agent/loop.py",
           '        if status == "eliminated":\n            return {"error": "eliminating a competitor is the gate\'s:',
           '        if False:\n            return {"error": "eliminating a competitor is the gate\'s:',
           ("tests/live/test_model_cannot_move_g6.py",),
           also=(("agent/loop.py", '        if status != "unresolved":',
                  '        if status not in ("unresolved", "eliminated"):'),)),
    Mutant("M-G1", "G1: the cause must have been seen in a graph result of this run", "agent/gate.py",
           'g1_ok = cause_id in g1["seen"] and not unknown_ev and bool(evidence_ids)',
           "g1_ok = True",
           ("tests/live/test_gate_s2.py",)),
    Mutant("M-HASH-APPROVE", "approval is bound to the exact plan hash (choosing ≠ approving)", "graph/writes.py",
           "(a:Action {id: $aid}) \"\n    \"WHERE a.status = 'chosen' AND a.plan_hash = $hash AND i.stage = 'AWAITING_APPROVAL' \"\n    # the incident",
           "(a:Action {id: $aid}) \"\n    \"WHERE a.status = 'chosen' AND i.stage = 'AWAITING_APPROVAL' \"\n    # the incident",
           ("tests/live/test_actions.py::test_stale_plan_hash_is_refused_and_approval_is_idempotent",)),
    Mutant("M-HASH-EXEC", "execute refuses a stored action that no longer matches its approved plan hash", "actions/act.py",
           'if plan_hash({k: v for k, v in spec.items() if k != "plan_hash"}) != act["plan_hash"]:',
           "if False:",
           ("tests/live/test_actions.py",)),
    Mutant("M-UNKNOWN", "verification that cannot read a channel is UNKNOWN, never success", "actions/act.py",
           'verdict, why = "UNKNOWN", f"GitHub could not be read',
           'verdict, why = "APPLIED", f"GitHub could not be read',
           ("tests/live/test_actions.py",)),
    Mutant("M-UNKNOWN-WB", "write-back never records success for an UNKNOWN verification", "actions/act.py",
           'if act["verdict"] == "APPLIED":\n        precedents = precedents_for(c, cause)',
           'if act["verdict"] in ("APPLIED", "UNKNOWN"):\n        precedents = precedents_for(c, cause)',
           ("tests/live/test_actions.py",)),
    Mutant("M-REORDER", "learned remediation ordering only reorders enabled options (disabled ones never move)",
           "actions/act.py",
           'slots = [i for i, o in enumerate(opts) if o["enabled"] and o["kind"] != "open_issue"]',
           'slots = [i for i, o in enumerate(opts) if o["kind"] != "open_issue"]',
           ("tests/test_remedy_residue.py",)),
    Mutant("M-G4ORIGIN", "a bystander change is not confirmed when the anomaly shows only at the symptom (G4 origin)",
           "agent/gate.py",
           '"G4 origin", True if (on_symptom or before) else False,',
           '"G4 origin", True,',
           ("tests/live/test_gate_bench_regressions.py",)),
    Mutant("M-G5MULT", "a suspect's own G5 bound counts every failure path (min(1, k × maxFlow)) (impact_bound)",
           "mcp_server/tools.py",
           "flow = min(1.0, max(ks.get(ids[0], 1), 1) * raw)", "flow = raw",
           ("tests/graph/test_g5_bound_property.py::test_reconvergent_paths_break_the_plain_bound",)),
    Mutant("M-G5ALONE", "joint G5 eliminates a suspect only when another suspect can carry the impact ALONE (never on "
           "the strength of a group whose members are each insufficient: that choice is order-dependent)",
           "agent/gate.py",
           "        carriers = [alone[o] for o in candidates if o != c and alone[o] >= need - 1e-12]",
           "        carriers = [j for j in [joint([t for o in candidates if o != c for t in _flat(candidates[o])])]"
           " if j >= need - 1e-12]",
           ("tests/agent/test_g5_eliminations.py",)),
    Mutant("M-SUSSELF", "a change on the alerting component itself is always a suspect (Q-SUS-1 keeps the symptom row)",
           "graph/templates/upstream_suspects.cypher",
           "found + [{id: sym.id, hops: 0}] AS ups", "found AS ups",
           ("tests/live/test_gate_bench_regressions.py",)),
    Mutant("M-RO", "every template read goes through GRAPH.RO_QUERY", "graph/ro.py",
           RO_CALL,
           RO_CALL.replace("ro_query", "query"),   # the read-write command
           ("tests/graph/test_ro_wrapper.py", "tests/mcpserver/test_guard_blocks_writes.py")),
    Mutant("M-A4", "FAULTLINE_DISABLE_GRAPH=true makes every read fail loudly (ablation arm A4; two guards, both removed)",
           "graph/ro.py",
           "if settings.faultline_disable_graph:  # checked on every call (ablation arm A4)",
           "if False:  # mutated",
           ("tests/graph/test_ro_wrapper.py",),
           also=(("graph/client.py", "def _disabled_guard() -> None:\n    if settings.faultline_disable_graph:",
                  "def _disabled_guard() -> None:\n    if False:"),)),
    Mutant("M-LINT", "templates may not contain write clauses", "graph/templates/__init__.py",
           "if _WRITE.search(m_code):",
           "if False:",
           ("tests/graph/test_template_lint.py",)),
    Mutant("M-GUARD", "guarded text2cypher rejects write keywords", "graph/guard.py",
           "w = WRITE_RE.search(m)",
           "w = None",
           ("tests/mcpserver/test_guard_blocks_writes.py",)),
    Mutant("M-CITE", "the brain's citation guard refuses ids no tool call of the question returned", "brain/ask.py",
           'return {"ok": not unseen, "cited": ids,',
           'return {"ok": True, "cited": ids,',
           ("tests/brain/test_citation_guard.py",)),
    Mutant("M-TENANT", "tenant names are validated (no cross-tenant or injected graph names)", "graph/tenant.py",
           "if not isinstance(t, str) or not TENANT_RE.fullmatch(t):",
           "if False:",
           ("tests/graph/test_tenant_names.py", "tests/isolation")),
    Mutant("M-G7CORR", "G7: a code/data specialist naming another change than the cause downgrades confidence",
           "agent/gate.py", "    if agree:\n", "    if True:\n",
           ("tests/agent/test_gate_decide.py",)),
    Mutant("M-STAGE-TOOLS", "a tool outside the stage whitelist is refused, logged and recorded", "agent/loop.py",
           "        if name not in allowed:\n", "        if False:\n",
           ("tests/agent/test_toolbox_whitelist.py",)),
    Mutant("M-SPEC-CLAIM", "two dispatches of the same specialist work item never both run it (W-CLAIM-1): "
           "every caller wins the claim (claim_epoch returns an epoch to everyone)",
           "graph/writes.py",
           "    return int(r[0][1]) if r and r[0][0] == agent else 0\n", "    return 1\n",
           ("tests/live/test_specialists.py::test_two_dispatches_of_the_same_work_item_never_both_run_it",)),
    Mutant("M-STORM-MERGE", "alert grouping links two alerts only over edges that can carry an alert-worthy rise (a grouping "
           "that joins every edge in the region merges unrelated faults into one incident)",
           "graph/templates/storm_edges.cypher",
           "WHERE cap * excess >= $carry_min", "WHERE cap >= 0",
           ("tests/live/test_alert_storm.py::test_s14_two_groups_and_each_gate_decides_its_own_cause",)),
    Mutant("M-STORM-OPEN", "only OPEN incidents absorb new alerts (a resolved incident's origin never attaches one)",
           "graph/templates/storm_origins.cypher",
           "WHERE NOT i.stage IN $terminal AND i.resolved_at IS NULL", "WHERE size($terminal) > 0",
           ("tests/live/test_alert_storm.py::test_a_resolved_incident_never_absorbs_a_new_alert",)),
    Mutant("M-PRIMARY-CARRY", "a target is a consequence of another alert only when a failure can cross the edges between "
           "them (Q-PRIMARY-1 uses the grouping's carry rule)",
           "graph/templates/primary_symptoms.cypher",
           " AND all(x IN relationships(p) WHERE id(x) IN carrying)", "",
           ("tests/live/test_alert_storm.py::test_ungrouped_storm_is_escalated_not_blamed_on_one_change",)),
    Mutant("M-VERIFY-ALLOW", "verification allows the share of a symptom another OPEN incident still owns (without it, "
           "S14's real payment fix reads NOT_APPLIED because the concurrent fraud fault still leaks into checkout)",
           "actions/act.py",
           'share = a["allowance"]  # what other open incidents still own',
           'share = 0.0  # what other open incidents still own',
           ("tests/live/test_alert_storm.py::test_the_real_fix_is_applied_once_the_other_incidents_share_is_allowed",)),
    Mutant("M-VERIFY-OWN", "the allowance never covers this incident's own fault (counting its own confirmed origin turns "
           "a fix that does not contain it into APPLIED)",
           "graph/templates/verify_allowance.cypher",
           "WHERE i.id <> $inc AND NOT i.stage IN $terminal", "WHERE NOT i.stage IN $terminal",
           ("tests/live/test_alert_storm.py::test_a_failed_fix_stays_not_applied_while_another_incident_is_open",),
           also=(("graph/templates/verify_allowance.cypher",
                  "WHERE NOT c.id IN my_causes AND NOT o.id IN my_origins AND NOT o.id IN my_reach",
                  "WHERE size(my_causes) > 0"),)),
    Mutant("M-VERIFY-MAXFLOW", "the allowance is an upper bound under the telemetry model: the other origin's path transfer "
           "over uncut edges (sum of cap products), never the bottleneck max flow over the full topology (which "
           "over-states a multi-hop leak and lets a partial fix hide its own residual inside the allowance)",
           "graph/templates/verify_allowance.cypher",
           "WITH x, o, t, paths, hops, CASE WHEN paths > 1000 OR uncapped > 0 THEN null ELSE walk END AS transfer,",
           "CALL {algo:maxflow}({sourceNodes: [o], targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], "
           "capacityProperty: 'cap'}) YIELD maxFlow\n"
           "WITH x, o, t, paths, hops, CASE WHEN maxFlow > 1.0 THEN 1.0 ELSE maxFlow END AS transfer,",
           ("tests/live/test_alert_storm.py::test_a_partial_fix_that_leaves_our_own_leak_stays_not_applied",)),
    Mutant("M-VERDICT-UNCOND", "a verdict is written only while its intent is PENDING and leased to the writer: "
           "an unconditional verdict lets a late reconciler or a stalled execute job overwrite the settled outcome",
           "graph/writes.py",
           "\"MATCH (a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem AND it.state = 'PENDING' AND "
           "($owner IS NULL OR it.lease_by = $owner) \"\n    \"SET a.verdict",
           "\"MATCH (a:Action {id: $aid}) \"\n    \"SET a.verdict",
           (R4 + "test_the_job_settles_first_and_the_reconciler_writes_nothing",
            R4 + "test_a_takeover_between_execute_and_verify_stops_the_job")),
    Mutant("M-REPAIR-FIXTURE", "a data repair is executed and verified on its incident's own warehouse fixture: "
           "without re-establishing the recorded mode and sources digest, a healthy-mode run in between makes a patch "
           "that fixes nothing verify APPLIED",
           "actions/act.py",
           "    if warehouse.fixture_state() != {\"mode\": fx[\"mode\"], \"sources_sha256\": fx[\"sources_sha256\"]}:\n"
           "        set_pipeline_mode(fx[\"mode\"], restore_transforms=False, rebuild=False)\n"
           "    now = warehouse.fixture_state()\n"
           "    if now[\"sources_sha256\"] != fx[\"sources_sha256\"]:",
           "    if False:\n"
           "        set_pipeline_mode(fx[\"mode\"], restore_transforms=False, rebuild=False)\n"
           "    now = warehouse.fixture_state()\n"
           "    if False:",
           (R5 + "test_an_unrelated_patch_never_verifies_applied_after_a_healthy_switch",
            R5 + "test_sources_that_cannot_be_reestablished_make_the_verdict_unknown")),
    Mutant("M-SQL-ACCEPT", "an LLM-authored transform must be one plain CTAS of its own target: a "
           "validator that accepts anything lets `COPY … TO` write files from the build",
           "repair.py",
           "    try:\n        kinds = warehouse.statement_types(sql)",
           "    return\n    try:\n        kinds = warehouse.statement_types(sql)",
           ("tests/test_review5_units.py::test_the_validator_refuses_anything_but_one_plain_ctas[copy-to]",)),
    Mutant("M-SESS-PREFIX", "brain session ids are server-issued (sess-…) and never take another node's id: "
           "unprefixed client sessions make a second node with a component's id",
           "brain/ask.py",
           'return session if session.startswith("sess-") else f"sess-{session}"',
           "return session",
           (R4 + "test_a_session_can_never_take_a_component_id",),
           also=(("graph/writes.py", 'if not SESSION_RE.fullmatch(session or ""):', "if False:"),
                 ("graph/writes.py", '"OPTIONAL MATCH (x:Node {id: $session}) WHERE NOT x:Session "\n    '
                                     '"WITH count(x) AS clash WHERE clash = 0 "\n    ', ""))),
    Mutant("M-FUTURE-BRANCH", "each containment candidate's future is read on its own GRAPH.COPY branch with ITS cut edges "
           "removed: a branch that keeps them predicts every flag fails, and the plan buries the working lever",
           "mcp_server/tools.py",
           "removed = writes.remove_flow_edges(db.select_graph(name), cuts)  # this candidate's own cuts",
           "removed = 0",
           ("tests/live/test_futures.py::test_each_candidate_has_its_own_predicted_future",)),
    Mutant("M-FUTURE-CLASS", "learned ordering never lifts an option the futures predict will not contain above one they "
           "predict will (history reorders within a predicted-future class only)",
           "actions/act.py",
           "key=lambda t: (future_class(opts[t[0]]), t[2], -t[1])", "key=lambda t: (t[2], -t[1])",
           ("tests/test_futures_units.py::test_history_never_lifts_an_option_across_a_predicted_future_class",)),
    Mutant("M-G4-UPSTREAM", "a suspect whose whole anomaly an earlier upstream fault accounts for (strict lower bound) "
           "is not the origin (deep bench: without the G4 rules a look-alike downstream of an unchanged break was confirmed in "
           "16 of 20 worlds)",
           "agent/gate.py",
           "                    if v.targets and all(expl.values()):",
           "                    if False:",
           ("tests/live/test_gate_upstream.py",)),
    Mutant("M-G4-UPSTREAM-SLACK", "elimination takes no slack: a surplus at the suspect may be its own fault (adversarial "
           "review: two causes in a chain)",
           "graph/templates/gate_upstream.cypher",
           "  AND carried IS NOT NULL AND sex <= carried\n",
           "  AND carried IS NOT NULL AND sex <= carried * 1.25\n",
           ("tests/live/test_gate_upstream.py",)),
    Mutant("M-N0-UNMEASURED", "the negative proof requires every alerting symptom to be measured (N0, found by the "
           "robustness eval: deleted telemetry was read as 'no incident')",
           "agent/gate.py",
           'checks.append(Check("N0 every symptom measured", not unmeasured,',
           'checks.append(Check("N0 every symptom measured", True,',
           ("tests/live/test_negative_proof_missing.py",)),
    Mutant("M-WORLD-SEED", "verification's post-action telemetry keeps the world's base error rates (found by the futures "
           "eval: re-drawing them from the noise seed read a contained fault as not contained)",
           "actions/act.py",
           "seed=int(at_ms % 10_000), base_seed=int(world_seed),", "seed=int(at_ms % 10_000),",
           ("tests/live/test_futures.py::test_verification_records_whether_the_prediction_came_true",)),
    Mutant("M-WHO-PAGES", "who_fixes reads every page of its projection: stopping after the first silently "
           "drops the pairs of a busy component, the LIMIT-100 truncation the Cypher move fixed",
           "mcp_server/tools.py",
           "        if not page.truncated:\n            break\n        after = (page.rows[-1][\"a\"], page.rows[-1][\"b\"])",
           "        break",
           ("tests/live/test_who_fixes_cypher.py::test_pairs_are_paged_disjoint_and_complete_on_the_busiest_component",)),
    Mutant("M-OVERRIDE-ANY", "only an INTENTIONAL reviewer answer takes a decision out of G8 for that change: "
           "honouring any answer would let \"accidental\" or \"discuss\" silently waive a violation",
           "agent/rules.py",
           'row["overridden"] = bool(o and o.get("verdict") == "intentional" and row.get("violated"))',
           'row["overridden"] = bool(o and row.get("violated"))',
           ("tests/live/test_decision_override.py::test_accidental_keeps_the_violation_and_names_the_answer",)),
    Mutant("M-LEARN-UNVERIFIED", "the graph learns a failure link only from a fix VERIFIED APPLIED: learning from an "
           "unverified or failed rollback turns a wrong human guess into a wrong edge",
           "memory/edges.py",
           'if a is None or a["kind"] != "rollback_deploy" or a["verdict"] != "APPLIED":',
           'if a is None or a["kind"] != "rollback_deploy":',
           ("tests/live/test_learned_edges.py::test_a_wrong_human_guess_verifies_not_applied_and_teaches_nothing",)),
    Mutant("M-EDGE-APPROVE-RECHECK", "approving a learned link re-checks, in the write itself, that its fix is still APPLIED, the "
           "approver is an active person and the graph still has no path",
           "graph/writes.py",
           '    "MATCH (who:Person) WHERE who.id = $by AND who.active "\n', "",
           ("tests/live/test_learned_edges.py::test_approval_re_checks_at_write_time",),
           also=(("graph/writes.py", '    "WHERE NOT (a)-[:PROPAGATES_TO*1..8]->(b) "\n', ""),)),
]


def _copy(m: Mutant) -> Path:
    dst = WORK / m.id
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    shutil.copytree(ROOT / "backend", dst / "backend", ignore=shutil.ignore_patterns("__pycache__"))
    for p in ROOT.iterdir():  # code that resolves repo paths from __file__ (data/, pipeline/, …) still finds them
        if p.name not in ("backend", "tmp", ".git", ".venv", "node_modules"):
            (dst / p.name).symlink_to(p)
    for file, old, new in ((m.file, m.old, m.new), *m.also):
        f = dst / "backend" / "faultline" / file
        src = f.read_text()
        n = src.count(old)
        if n != 1:
            raise RuntimeError(f"{m.id}: mutation site matches {n} times in {file} (stale mutant; update it)")
        f.write_text(src.replace(old, new))
    return dst


MUTANT_MEM_MB = 2500  # a mutant that makes code run away (an infinite loop growing a list) dies alone, never the host


def _capped() -> list[str]:
    """systemd user scope with MemoryMax and no swap, when available (a crash there is ERROR, never a kill)."""
    import shutil

    if shutil.which("systemd-run") and subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"],
                                                      capture_output=True).returncode == 0:
        return ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={MUTANT_MEM_MB}M",
                "-p", "MemorySwapMax=0", "--"]
    return []


PYTEST_TIMEOUT_S = 900
TIMED_OUT = -9  # neither 0 (survived) nor 1 (killed): a run that hits the timeout is recorded as ERROR


def _pytest(pythonpath: Path, tests: tuple[str, ...]) -> tuple[int, str]:
    """One pytest run in its own capped scope (`_capped`, per mutant and per baseline). A run that exceeds the timeout
    is killed and reported as TIMED_OUT (→ ERROR for that mutant); it never aborts the remaining mutants."""
    env = {**os.environ, "PYTHONPATH": str(pythonpath), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        p = subprocess.run(_capped() + [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-W",
                                        "ignore", *tests], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=PYTEST_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return TIMED_OUT, f"timed out after {PYTEST_TIMEOUT_S} s; " + " ".join(out.splitlines()[-2:])[:300]
    tail = [ln for ln in p.stdout.splitlines() if ln.startswith(("FAILED", "ERROR")) or " passed" in ln or " failed" in ln]
    return p.returncode, "; ".join(tail[-3:])[:400]


def run(ids: list[str] | None = None) -> dict:
    """Run the mutants (all, or `ids`) and return the summary; the eval harness records it in latest.json."""
    chosen = [m for m in MUTANTS if not ids or m.id in ids]
    rows = []
    for m in chosen:
        t0 = time.perf_counter()
        base_rc, base_tail = _pytest(ROOT / "backend", m.tests)
        if base_rc != 0:
            rows.append({"id": m.id, "invariant": m.invariant, "status": "ERROR", "detail": f"baseline failed: {base_tail}"})
            print(f"{m.id:15} ERROR    baseline tests fail: {base_tail}")
            continue
        try:
            dst = _copy(m)
        except RuntimeError as e:
            rows.append({"id": m.id, "invariant": m.invariant, "status": "ERROR", "detail": str(e)})
            print(f"{m.id:15} ERROR    {e}")
            continue
        try:
            rc, tail = _pytest(dst / "backend", m.tests)
        finally:
            shutil.rmtree(dst, ignore_errors=True)
        # pytest exit 1 = tests ran and failed. Anything else (2 interrupted, 4 usage, 5 nothing collected) is not a
        # kill: the mutant broke collection or the test selection, which proves nothing about the invariant.
        status = "KILLED" if rc == 1 else ("SURVIVED" if rc == 0 else "ERROR")
        rows.append({"id": m.id, "invariant": m.invariant, "file": f"backend/faultline/{m.file}", "tests": list(m.tests),
                     "status": status, "detail": tail, "s": round(time.perf_counter() - t0, 1)})
        print(f"{m.id:15} {status:8} {m.invariant}  ({tail})")
    killed = sum(r["status"] == "KILLED" for r in rows)
    out = {"mutants": len(rows), "killed": killed, "survived": sum(r["status"] == "SURVIVED" for r in rows),
           "errors": sum(r["status"] == "ERROR" for r in rows), "rows": rows}
    if not ids:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nmutation check: {killed}/{len(rows)} killed")
    return out


def main(argv: list[str]) -> int:
    out = run(argv)
    return 0 if out["killed"] == out["mutants"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
