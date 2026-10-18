"""Forget with a receipt (S10): dry run → a human approves the exact receipt → W-MEM-3 deletes the
Doc and only what it alone produced → receipt into audit_<tenant> → proof: the forgotten vectors no longer come
back from the vector index, and the question re-asked no longer cites what was forgotten.

The receipt token binds the approval to the exact set the dry run showed (same idea as the plan hash).

Review round 4, m3:
* a dry run whose list (Q-FORGET-1, LIMIT 100) is truncated fails loudly (ForgetRefused): a partial list would make
  the receipt approve, and the delete remove, a different set from what the doc alone produced;
* the delete re-checks, inside its own query, that every listed node is still produced by this doc alone (another doc
  may have produced one since the dry run): if not, nothing is deleted (TOCTOU);
* session turns that CITED a forgotten id (Turn.refs) are redacted in the same graph; a turn that quotes the forgotten
  text without citing an id cannot be found that way and survives.
"""

from __future__ import annotations

import hashlib
import json

from ..graph import client, writes
from ..graph.ro import RO
from ..graph.tenant import audit_graph, check_tenant, tenant_graph


class ForgetRefused(PermissionError):
    """The forget cannot be done as approved (list truncated, or the set changed since the dry run): nothing deleted."""


def _token(tenant: str, doc: str, owned: list[dict]) -> str:
    body = json.dumps({"tenant": tenant, "doc": doc, "owned": [(o["id"], o["label"], o["rels"]) for o in owned]},
                      sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def dry_run(tenant: str, doc: str, graph: str | None = None) -> dict:
    tenant = check_tenant(tenant)
    ro = RO(tenant, graph)
    d = ro.run("Q-DOC-1", {"doc": doc}).rows
    if not d:
        raise KeyError(f"unknown document {doc}")
    res = ro.run("Q-FORGET-1", {"doc": doc})
    if res.truncated:
        raise ForgetRefused(f"{doc} alone produced more nodes than the dry run can list ({len(res.rows)}+); forgetting "
                            "it would delete a set nobody approved, so it is refused (forget its parts first)")
    owned = res.rows
    return {"doc": d[0], "owned": owned, "nodes": len(owned) + 1, "relationships": sum(o["rels"] for o in owned),
            "vectors": sum(1 for o in owned if o["has_vector"]),
            "kept": sorted(set(d[0]["produced"]) - {o["id"] for o in owned}),  # also produced by another doc: kept
            "token": _token(tenant, doc, owned)}


def execute(tenant: str, doc: str, token: str, approver: str, graph: str | None = None) -> dict:
    """`graph`: a clean-room copy (public demo) instead of the tenant graph; the receipt says which graph."""
    tenant = check_tenant(tenant)
    graph = graph or tenant_graph(tenant)
    plan = dry_run(tenant, doc, graph)
    if plan["token"] != token:
        raise PermissionError("the dry-run receipt no longer matches the graph; run the dry run again")
    g = client.engine().select_graph(graph)
    # capture the forgotten vectors (for the proof) before deleting
    ro0 = RO(tenant, graph)
    vecs = [(o["id"], writes.check_label(o["label"]), ro0.run("Q-VEC-1", {"id": o["id"]}).rows[0]["embedding"])
            for o in plan["owned"] if o["has_vector"]]
    try:
        done = writes.forget_doc(g, doc=doc, owned=[o["id"] for o in plan["owned"]])
    except writes.WriteError as e:  # the set changed between the dry run re-read and the delete: nothing deleted
        raise ForgetRefused(str(e)) from e
    redacted = writes.redact_turns(g, ids=[doc] + [o["id"] for o in plan["owned"]],
                                   note=f"[redacted: this answer cited {doc}, which was forgotten]")
    if graph == tenant_graph(tenant):  # a new content epoch: every brain scratch copy (any process) is stale now
        import time
        import uuid

        writes.set_epoch(g, f"{int(time.time())}-{uuid.uuid4().hex[:8]}")
    ro = RO(tenant, graph)
    still = []
    for nid, label, v in vecs:
        hits = ro.run("Q-FORGET-2", {"label": label, "vec": [float(x) for x in v]}).rows
        if any(h["id"] == nid for h in hits):
            still.append(nid)
    receipt = {"tenant": tenant, "graph": graph, "doc": doc, "approver": approver, "token": token, "nodes": done["nodes"] + 1,
               "relationships": done["relationships"], "vectors": len(vecs), "vectors_still_found": len(still),
               "forgotten_ids": json.dumps([o["id"] for o in plan["owned"]]), "kept_ids": json.dumps(plan["kept"]),
               "turns_redacted": redacted}
    writes.append_audit(client.engine().select_graph(audit_graph(tenant)), "ForgetReceipt", receipt)
    return {**receipt, "forgotten_ids": [o["id"] for o in plan["owned"]], "kept_ids": plan["kept"],
            "proof": {"vector_requery": "none found" if not still else f"STILL FOUND: {still}"}}


__all__ = ["dry_run", "execute"]
