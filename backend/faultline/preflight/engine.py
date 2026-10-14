"""Mode B: preflight a pull request against the tenant graph.

1. Ingest the PR (an observed object): (:PR)-[:TOUCHES]->(:File) for files the graph knows (one query).
2. ChangeFacts from changed config files (deterministic extractor; pydantic-validated) → (:PR)-[:ASSERTS]->(:ChangeFact).
3. `preflight_change` (MCP tool, recorded under its own Run): BFS impact, betweenness, past incidents, Q-DEC-1
   contradictions, bus factor, guardrail gaps → risk (weights.yaml) → allow | require_review | block.
"""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field

from ..graph import client, writes
from ..graph.ro import RO
from ..graph.tenant import check_tenant, tenant_graph
from ..mcp_server import context
from ..mcp_server import tools as T
from .facts import ChangedFile, extract


class PreflightIn(BaseModel):
    repo: str = Field(..., pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    number: int = Field(..., ge=1)
    title: str = Field("", max_length=300)
    author: str = Field("", max_length=80)
    head_sha: str = Field("", max_length=64)
    files: list[ChangedFile] = Field(..., min_length=1, max_length=200)


class PRRef(BaseModel):
    repo: str = Field(..., pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    number: int = Field(..., ge=1)


def fetch(ref: PRRef, hub) -> PreflightIn:
    """Build the preflight input from the PR itself (GitHub REST, or the simulated world when keyless): changed files
    with before/after contents for config files. A GitHubError propagates: the caller says GitHub could not be read."""
    d = hub.pr_files(ref.repo, ref.number)
    if not d["files"]:
        raise ValueError(f"{ref.repo}#{ref.number} changes no files")
    return PreflightIn(repo=ref.repo, number=ref.number, title=(d.get("title") or "")[:300],
                       author=(d.get("author") or "")[:80], head_sha=(d.get("head_sha") or "")[:64],
                       files=[ChangedFile(**f) for f in d["files"]])


def pr_node_id(repo: str, number: int) -> str:
    return f"pr:{repo}#{number}"


def run(tenant: str, pr: PreflightIn, graph: str | None = None) -> dict:
    """`graph`: evaluate on a clean-room copy (public, unkeyed calls) instead of recording into the tenant graph."""
    t0 = time.perf_counter()
    tenant = check_tenant(tenant)
    graph = graph or tenant_graph(tenant)
    g = client.engine().select_graph(graph)
    pid = pr_node_id(pr.repo, pr.number)
    run_id = f"pre-{uuid.uuid4().hex[:10]}"
    writes.open_aux_run(g, run=run_id, tenant=tenant, mode="preflight", text=f"{pid} {pr.title}")
    file_ids = [f"file:{f.path}" for f in pr.files]
    known = writes.ingest_pr(g, tenant=tenant, pr=pid, repo=pr.repo, number=pr.number, title=pr.title, author=pr.author,
                             sha=pr.head_sha, files=file_ids)
    rows = RO(tenant, graph).run("Q-PRE-3", {"files": file_ids}).rows
    comp_of = {r["file"].removeprefix("file:"): r["component"] for r in rows if r["component"]}
    facts, notes = extract(pr.files, comp_of)
    for f in facts:
        writes.assert_change_fact(g, change=pid, key=f.key, value=f.value, about=f.about, file=f.file)
    unknown = sorted({f.path for f in pr.files} - set(comp_of))
    token = context.bind(tenant, run_id=run_id, graph=graph)
    try:
        out = T.preflight_change(pr_id=pid)
    finally:
        context.unbind(token)
    if "error" in out:
        return {"pr": pid, "run_id": run_id, "verdict": "require_review", "risk": None, "error": out["error"],
                "facts": [f.model_dump() for f in facts], "notes": notes, "unknown_files": unknown}
    return {"pr": pid, "run_id": run_id, "verdict": out["verdict"], "risk": out["risk"], "thresholds": out["thresholds"],
            "terms": out["terms"], "would_change_if": out["would_change_if"], "reviewers": out["reviewers"],
            "decision_links": out["decision_links"], "reversals": out.get("reversals") or [],
            "assessment": out["rows"][0], "facts": [f.model_dump() for f in facts],
            "notes": notes, "unknown_files": unknown, "known_files": known,
            "evidence": {k: out.get(k) for k in ("evidence_id", "template", "cypher", "params", "served_by", "digest", "ms")},
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


__all__ = ["run", "PreflightIn", "PRRef", "fetch", "pr_node_id"]
