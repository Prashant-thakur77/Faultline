"""Whitelists of labels and relationship types (docs/design/graph_model_sketch.md).
The seeder and writes format these into Cypher; anything else is rejected."""

NODE_LABELS = frozenset({
    # data lineage
    "KPI", "Dashboard", "Table", "Column", "Transform", "Job",
    # services
    "Service", "Endpoint", "Datastore", "ExternalDependency",
    # change
    "Repo", "File", "Commit", "PR", "Deploy", "FeatureFlag", "ChangeFact",
    # incidents
    "Alert", "Incident", "Symptom", "Hypothesis", "Evidence", "GateRun", "MetricWindow", "Anomaly", "Baseline",
    # people and knowledge
    "Person", "Team", "Runbook", "Decision", "Postmortem", "Doc",
    # a reviewer's answer to a contradicted decision for one change (M15 #3)
    "Override",
    # a learned failure edge awaiting human approval (M15 #4)
    "EdgeProposal",
    # a recorded "break the graph" diff (M15 #2), in audit_<t>
    "PlaygroundRun",
    # obligations (M12 obligation clock): what we promised, and to whom
    "SLO", "Customer",
    # company-brain question routing: worded examples of each question kind, matched by vector + full-text index
    "IntentExemplar",
    # actions and coordination
    "Intent", "Action", "Approval", "Remediation", "Task", "Agent", "Session", "Turn",
    "Run", "StageEvent", "ToolCall", "ForgetReceipt", "Rearm", "Meta", "RunIndex", "LlmSpend",
    # on-call (M19): a page to one person about one incident, a standing approval (contract) and its uses, a hand-off
    "Page", "Contract", "ContractUse", "Handoff",
    # the Telegram on-call bot: a processed update (idempotency), a typed-phrase consent waiting for its phrase, a chat
    "BotUpdate", "BotProposal", "BotChat",
    # public-mode paging safety: a per-channel hourly budget / per-recipient cooldown, and which graphs hold pages
    "DeliveryBudget", "PageGraph",
    # learning (M21, in the on-call home graph): a trusted operator action, the preference, guideline and knowledge gap
    # recomputed from those events in Cypher (each derived node keeps DERIVED_FROM edges to its events)
    "LearnEvent", "Preference", "Guideline", "KnowledgeGap",
    # company rules as data (M20 #6): a change-freeze Policy (weekly wall-clock window, fixed UTC offset) the preflight
    # gate evaluates in the engine with temporal accessors
    "Policy",
    # shared agent notes (T2, in agentmem_<t>): a lead one agent leaves for others about components, and its author
    "Note", "Author",
    # document text (T3): a paragraph chunk of a Doc's body, PART_OF it, with a vecf32 embedding
    "Chunk",
})

REL_TYPES = frozenset({
    "CALLS", "READS", "WRITES", "DERIVES_FROM", "OF", "COMPUTED_FROM", "SHOWS", "EMITS", "CONSUMES",
    "PROPAGATES_TO", "DEPENDS_ON", "EXPOSES", "GATES", "CHANGED", "CONTAINS", "TOUCHES", "PART_OF",
    "AUTHORED", "COMMITTED", "OWNS", "OWNED_AT", "MEMBER_OF", "REPORTS_TO", "ON_CALL", "COLLABORATES",
    "FIRED_ON", "HAS_SYMPTOM", "AFFECTED", "HYPOTHESIZES", "BLAMES", "SUPPORTS", "REFUTES", "ABOUT",
    "CAUSED", "PRECEDENT_FOR", "RESOLVED_BY", "ATTEMPTED", "RESOLVED", "DOCUMENTS", "DERIVED_FROM", "RUNBOOK_FOR",
    "CONSTRAINS", "SUPERSEDES", "CITES", "DECIDED", "PRODUCED", "ASSERTS", "VIOLATES", "FOR",
    "HAS_INTENT", "APPROVED", "EXECUTED", "CLAIMED_BY", "HANDED_OFF_TO", "HAS_TURN", "HAS_GATE_RUN",
    "HAS_STAGE", "HAS_TOOL_CALL", "SAW", "RECALLED", "PRODUCED_EVIDENCE", "HAS_HYPOTHESIS", "HAS_RUN", "HAS_ALERT", "BASELINE_OF", "WINDOW_OF", "KNOWS_ABOUT", "HAS_PLAN", "HAS_ACTION",
    # specialist work items: Run → Task, Task → named suspect
    "HAS_TASK", "NAMES",
    # the crew (M17): Task → the ToolCalls its agent MADE, Task → the next step's Task
    "MADE", "NEXT",
    # alert-storm correlation (M14 #2): Alert → the Incident INTAKE opened with it or attached it to
    "DEGRADES",
    # decision override (M15 #3): Override → the Decision it answers, and → the change it is about
    "OVERRIDES", "FOR_CHANGE",
    # learned edges (M15 #4): Incident → the EdgeProposal a verified fix produced
    "HAS_PROPOSAL",
    # on-call (M19): Page → Person it PAGES (and FOR its Incident), Page → the Page it ESCALATED_TO, Person → the Page
    # they ACKED; Incident → Person in its escalation order (ESCALATES_TO, from the algo.MSF tree); Contract → the
    # Person who GRANTED it, the component it COVERS and each ContractUse it was USED_IN; Handoff FROM → TO a Person
    "PAGES", "ESCALATED_TO", "ACKED", "ESCALATES_TO", "GRANTED_BY", "COVERS", "USED_IN", "FROM", "TO",
    # learning (M21): Person -[:DID]-> LearnEvent; Person -[:RESPONDED {score, n, acks, approvals, fixes, mtta_ms,
    # last_at}]-> the component of an incident family (recomputed from the person's ack/approve/verified events)
    "DID", "RESPONDED",
    # change freeze (M20 #6): Policy -[:FREEZES]-> the component it freezes (Person -[:DECIDED]-> Policy names who)
    "FREEZES",
    # shared agent notes (T2): Author -[:WROTE]-> Note -[:ABOUT]-> component; Note -[:REPLY_TO {stance}]-> Note
    "WROTE", "REPLY_TO",
})


def check_label(label: str) -> str:
    if label not in NODE_LABELS:
        raise ValueError(f"label {label!r} not in schema_model.NODE_LABELS")
    return label


def check_rel(rel: str) -> str:
    if rel not in REL_TYPES:
        raise ValueError(f"relationship {rel!r} not in schema_model.REL_TYPES")
    return rel


# ---------------------------------------------------------------- schema drift (scripts/check_schema_drift.py)
# Every node also carries this base label (cross-label id lookups); it is structural, not a domain label.
BASE_LABEL = "Node"

# Relationship types created only at runtime (agent runs, actions, write-back, scratch projections), so a freshly
# seeded tenant graph may not contain them. Each one is written by graph/writes.py (or a scratch projection).
RUNTIME_RELS = frozenset({
    # shared agent notes (T2), written at runtime in agentmem_<t> only (Author -[:WROTE]-> Note, Note -[:REPLY_TO]-> Note)
    "WROTE", "REPLY_TO",
    # run state, evidence and coordination (agent runs, MCP tool calls)
    "HAS_RUN", "HAS_STAGE", "HAS_TOOL_CALL", "SAW", "PRODUCED_EVIDENCE", "HAS_GATE_RUN", "HYPOTHESIZES",
    "SUPPORTS", "REFUTES", "BLAMES", "RECALLED", "PRECEDENT_FOR", "CLAIMED_BY", "HANDED_OFF_TO", "HAS_TURN",
    # specialist reports: the claimed work item (Task) of a run, the suspects its contract NAMES, the evidence it CITES
    "HAS_TASK", "NAMES",
    # crew steps (M17): the tool calls each agent MADE, and the hand-off order between steps (NEXT)
    "MADE", "NEXT",
    # actions, approvals and write-back
    "HAS_PLAN", "HAS_INTENT", "APPROVED", "EXECUTED",
    # telemetry and change facts arriving at runtime (simulated alerts, preflight PR facts and decision checks)
    "FIRED_ON", "ASSERTS", "VIOLATES",
    # INTAKE: which incident an alert belongs to (opened with it, or attached to the nearest open confirmed origin)
    "DEGRADES",
    # a reviewer's override of a contradicted decision (written by graph/writes.py::record_override)
    "OVERRIDES", "FOR_CHANGE",
    # a learned-edge proposal after a verified fix (graph/writes.py::propose_edge)
    "HAS_PROPOSAL",
    # scratch projection only (who_fixes builds it in scratch_<t>_*, never in the tenant graph)
    "KNOWS_ABOUT",
    # on-call (M19): pages, acks, escalation order, standing contracts and hand-offs (graph/writes.py, W_PAGE_* etc.)
    "PAGES", "ESCALATED_TO", "ACKED", "ESCALATES_TO", "GRANTED_BY", "COVERS", "USED_IN", "FROM", "TO",
    # learning (M21, memory/learning.py → graph/writes.py W_LEARN_*): who did a learned action, who responds to a family
    "DID", "RESPONDED",
})

# Declared in the graph model but with no writer yet. Listed explicitly so the drift check can tell
# "reserved on purpose" from "declared and forgotten"; a reserved type that shows up in a graph is reported.
RESERVED_RELS = frozenset({
    "HAS_ACTION",      # Incident → Action; written as RESOLVED_BY / ATTEMPTED (and Intent -[:EXECUTED]-> Action) instead
    "HAS_ALERT",       # Incident → Alert; alerts attach to components (FIRED_ON) instead
    "HAS_HYPOTHESIS",  # → Hypothesis; written as Incident -[:HYPOTHESIZES]-> Hypothesis -[:BLAMES]-> suspect instead
})
