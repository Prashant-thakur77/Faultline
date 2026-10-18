"""Per-stage tool whitelists. The loop offers the model only these tools, recomputed for EVERY LLM call
from the stage it is in; a call to any other tool returns {"error": "tool … not allowed in stage …"}, is logged and is
recorded in the run as a refused ToolCall (never silently allowed). Specialists get a narrower list per role."""

from __future__ import annotations

from .state import Stage

# Internal tools (engine-written scratch/what-if graphs) are never hosted for judges.
INTERNAL_TOOLS = {"rank_causes", "whatif", "futures", "who_fixes", "escalation_tree", "group_alerts"}

PHASE_TOOLS: dict[Stage, list[str]] = {
    # group_alerts: which alerts are one incident (algo.WCC); run as code by agent/intake.py before an incident exists
    Stage.INTAKE: ["find_entities", "service_context", "group_alerts", "context_pack"],
    # memory first; recall_notes: what other agents left near the symptom (shared notes; leads, never evidence)
    Stage.RECALL: ["similar_incidents", "incident_families", "runbook_for", "session_history", "recall_notes"],
    Stage.LOCALIZE: ["find_entities", "service_context", "upstream_scope", "column_lineage"],
    Stage.BLAST: ["blast_radius", "chokepoints"],
    Stage.HYPOTHESIZE: ["upstream_suspects", "window_changes", "rank_causes", "record_hypothesis"],
    Stage.INVESTIGATE: [
        "causal_paths", "impact_bound", "upstream_scope", "metric_window",
        "get_metric_history", "compare_to_baseline", "profile_column", "baseline_columns", "anomalous_row_share", "run_sql",
        "list_transforms", "read_transform", "run_invariants", "change_details", "decision_check", "diff_summary",
        "update_hypothesis", "record_hypothesis", "graph_schema", "run_cypher_readonly", "propose_repair",
    ],
    Stage.GATE: ["confirm_root_cause", "declare_no_incident", "reachable_from_changes", "alert_coverage", "residue_check"],
    Stage.CONTRADICTION: ["decision_check", "trace_decision"],
    # futures: one GRAPH.COPY branch per containment candidate, each predicted back in band or not (Q-FUTURE-1)
    Stage.CONTAIN: ["containment_cut", "whatif", "futures", "connectivity_check", "blast_radius"],
    # obligation_clock: SLO burn, time to breach and customers reached; it decides urgency and who is told first
    # learned_responders (M21): who actually answers this component's pages; the top one joins the first wave
    Stage.ROUTE: ["who_fixes", "owners_of", "bus_factor", "escalation_tree", "notify_set", "owner_at", "obligation_clock",
                  "learned_responders"],
    # (CONTAIN also runs blast_radius on the cause's target to find what must be protected)
    # remedy_stats only reorders the options (Q-REM-1); learned_preferences (M21) blends the team's recent choices into
    # that order within one predicted-future class, flags options against an active guideline, suggests contracts
    Stage.PLAN: ["propose_plan", "remedy_stats", "learned_preferences"],
    Stage.AWAITING_APPROVAL: [],
    Stage.EXECUTE: ["execute_action"],
    Stage.VERIFY: ["verify_action"],
    Stage.WRITEBACK: ["write_back"],
    Stage.LEARN: ["consolidate"],
}
# The gate is entered FROM INVESTIGATE: confirm_root_cause / declare_no_incident are how an investigation asks for a
# verdict, and the incident only reaches GATE when the gate accepts. So these are callable in INVESTIGATE too.
GATE_ENTRY = ["confirm_root_cause", "declare_no_incident", "reachable_from_changes"]
ALWAYS = ["finish"]
# Advisory, post-verdict reads: driven by code after the gate has decided, never offered to the investigator
# (residue and alert coverage describe a verdict; they must not shape it)
POST_VERDICT = {"alert_coverage", "residue_check"}

# Specialists: each role's own whitelist, always a subset of INVESTIGATE's. Notes on the lists:
# data also gets upstream_scope (to ground its scope) and causal_paths (to tie an anomaly it measured to a change);
# no specialist gets update_hypothesis (hypotheses are owned by the sweep and the gate, so G6 cannot be moved by a
# report); telemetry has metric_window only (no separate compare_baseline tool: metric_window
# returns the pre-onset baseline and band itself).
SPECIALIST_TOOLS: dict[str, list[str]] = {
    "topology": ["causal_paths", "impact_bound", "upstream_scope"],
    "telemetry": ["metric_window"],
    "data": ["get_metric_history", "compare_to_baseline", "profile_column", "baseline_columns", "anomalous_row_share", "run_sql",
             "list_transforms", "read_transform", "run_invariants", "upstream_scope", "causal_paths"],
    "change": ["change_details", "decision_check"],
    "code": ["diff_summary"],
}


def allowed(stage: Stage) -> list[str]:
    return PHASE_TOOLS.get(stage, []) + ALWAYS


def stage_toolset(stage: Stage) -> list[str]:
    """What may be CALLED in a stage (enforced by ToolBox on every call, code or model)."""
    tools = PHASE_TOOLS.get(stage, []) + ([t for t in GATE_ENTRY if t not in PHASE_TOOLS.get(stage, [])]
                                          if stage == Stage.INVESTIGATE else [])
    return list(dict.fromkeys(tools)) + ALWAYS


def llm_toolset(stage: Stage) -> list[str]:
    """What is OFFERED to the model in a stage: the stage's whitelist minus the post-verdict advisory reads."""
    return [t for t in stage_toolset(stage) if t not in POST_VERDICT]


def investigation_toolset() -> list[str]:
    """The LLM investigator's list in INVESTIGATE (the only stage a model drives; the others run as code)."""
    return llm_toolset(Stage.INVESTIGATE)


def specialist_toolset(role: str) -> list[str]:
    if role not in SPECIALIST_TOOLS:
        raise KeyError(f"unknown specialist role {role!r}")
    inv = set(PHASE_TOOLS[Stage.INVESTIGATE])
    return [t for t in SPECIALIST_TOOLS[role] if t in inv]
