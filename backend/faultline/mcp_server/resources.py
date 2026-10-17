"""MCP resources and prompts (registered next to the tools by `server.register_tools`).

Resources (read-only, tenant-bound exactly like the tools: the tenant comes from the session binding or the HTTP
bearer key via `context.current()`, never from the URI):
* `faultline://schema`  : the live schema of the bound tenant's graph (Q-SCHEMA-1..5 through GRAPH.RO_QUERY: labels,
  relationship types, indexes and the engine-enforced constraints);
* `faultline://queries` : the linted template catalogue (id, purpose, returns, params, LIMIT, file);
* `faultline://weights` : weights.yaml verbatim (every score and gate number the product computes comes from it).

Prompts steer a client to the right tools and state the one rule: no path, no claim.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..agent.weights import WEIGHTS_PATH
from ..graph.ro import RO
from ..graph.schema_introspect import introspect
from ..graph.templates import catalogue, mask_strings
from . import context

RULE = ("Rule: no path, no claim. Name a cause, an impact or an owner only when a Faultline tool result shows it "
        "(a graph path, a flow bound or a row), and cite that result's evidence_id. If no tool shows it, say it is "
        "not in the graph.")

_PARAM = re.compile(r"\$([A-Za-z_]\w*)")


def schema_resource() -> str:
    """The live schema of this tenant's graph: labels with counts, property keys and indexes; relationship types
    with counts and (from-label, to-label) pairs; the engine-enforced constraints. Read-only (db.meta.stats, bounded
    scans, db.indexes, db.constraints)."""
    b = context.current()
    ro = RO(b.tenant, b.graph)
    schema, results = introspect(ro)
    cons = ro.run("Q-SCHEMA-5", {})   # the engine-enforced invariants (M20): UNIQUE / MANDATORY, with their status
    results = [*results, cons]
    schema = {**schema, "constraints": cons.rows}
    return json.dumps({"tenant": b.tenant, **schema, "served_by": results[0].served_by,
                       "queries": [{"template": r.template_id, "ms": round(r.ms, 2), "digest": r.digest,
                                    "truncated": r.truncated} for r in results]}, indent=1, sort_keys=True, default=str)


def queries_catalogue() -> list[dict[str, Any]]:
    out = []
    for tid, t in sorted(catalogue().items()):
        if t.internal:   # product-only reads (Telegram ids, consents, contract offers) are not offered to MCP clients
            continue
        params = sorted(set(_PARAM.findall(mask_strings(t.display))))
        out.append({"id": tid, "purpose": t.purpose, "returns": t.returns, "params": params, "limit": t.limit,
                    "file": t.path})
    return out


def queries_resource() -> str:
    """The read-only Cypher template catalogue: every product read is one of these (id, purpose, params, LIMIT).
    Name one as `failed_template` when run_cypher_readonly is the last resort."""
    context.current()  # bound like the tools (raises on an invalid binding)
    return json.dumps({"templates": queries_catalogue()}, indent=1)


def weights_resource() -> str:
    """weights.yaml verbatim: every gate threshold, score weight and preflight term the product computes in code."""
    context.current()
    return WEIGHTS_PATH.read_text()


def investigate_incident(symptom: str) -> str:
    """Investigate an incident from its symptom, proving the cause through the graph."""
    s = _arg("symptom", symptom)
    return (
        f"Investigate the incident whose symptom is: {s}\n\n{RULE}\n\n"
        "1. resolve_entity / find_entities: turn the symptom into graph ids; service_context for owner, on-call, "
        "runbooks and active decisions.\n"
        "2. similar_incidents, incident_families, runbook_for: has this happened before, and what fixed it?\n"
        "3. upstream_scope, then upstream_suspects (onset, window) for candidate changes; window_changes shows the "
        "look-alikes that are not upstream.\n"
        "4. For each suspect: causal_paths(change -> symptom). An empty result rejects the suspect. Then "
        "impact_bound(suspects, symptom, observed_share): an insufficient suspect cannot be the whole cause.\n"
        "5. blast_radius on the cause's target, containment_cut(failing, protect) for the smallest cut, "
        "connectivity_check to confirm it isolates the failure.\n"
        "6. owners_of, bus_factor and notify_set: who fixes it and who to tell; alert_coverage for why alerts missed it.\n"
        "Read faultline://schema (or call graph_schema) and use run_cypher_readonly only when no tool answers. "
        "These tools are read-only: propose the containment; a human approves the exact action in Faultline."
    )


def preflight_pr(pr_id: str) -> str:
    """Pre-deploy gate for a pull request: what it can break, which decisions it contradicts, who should review."""
    p = _arg("pr_id", pr_id)
    return (
        f"Assess pull request {p} before it merges.\n\n{RULE}\n\n"
        f"1. preflight_change(pr_id={p!r}): the verdict (allow / require_review / block), each weighted risk term "
        "with its reason, would_change_if, and the suggested reviewers.\n"
        f"2. decision_check(change_id={p!r}) for active decisions its facts contradict; trace_decision on each one "
        "to show the current head and its sources.\n"
        "3. blast_radius on the changed components; people_who_worked_on and bus_factor to explain the reviewers.\n"
        "Report the verdict and risk exactly as returned: scores come from weights.yaml in code "
        "(faultline://weights), never from you."
    )


def ask_brain(question: str) -> str:
    """Answer a company-brain question (who owns, knows or decided what) from the graph, with citations."""
    q = _arg("question", question, 400)
    return (
        f"Answer from Faultline's company brain: {q}\n\n{RULE}\n\n"
        "1. resolve_entity / find_entities to find the ids the question is about.\n"
        "2. The specific tools: people_who_worked_on, owners_of, decisions_about, trace_decision, missing_guardrails, "
        "service_context, blast_radius, runbook_for, owner_at, component_timeline, beliefs_at, knowledge_health, "
        "session_history.\n"
        "3. Only if no tool answers: read faultline://schema (or graph_schema) and faultline://queries, then "
        "run_cypher_readonly naming the template that could not answer.\n"
        "Cite every node id in [brackets], and only ids that appeared in a tool result. If nothing in the graph "
        "supports an answer, say so."
    )


PROMPTS = (investigate_incident, preflight_pr, ask_brain)
RESOURCES = (
    ("faultline://schema", "schema", schema_resource, "application/json"),
    ("faultline://queries", "queries", queries_resource, "application/json"),
    ("faultline://weights", "weights", weights_resource, "application/yaml"),
)


def _arg(name: str, value: str, max_len: int = 160) -> str:
    v = (value or "").strip()
    if not v or len(v) > max_len:
        raise ValueError(f"{name} must be 1..{max_len} characters")
    return v


def register(server) -> None:
    for uri, name, fn, mime in RESOURCES:
        server.resource(uri, name=name, description=(fn.__doc__ or "").strip(), mime_type=mime)(fn)
    for fn in PROMPTS:
        server.prompt(name=fn.__name__, description=(fn.__doc__ or "").strip())(fn)
