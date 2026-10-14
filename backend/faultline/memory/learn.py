"""LEARN: after a verified, APPLIED write-back the incident's family (algo.labelPropagation, Q-MEM-6) is
consolidated into a derived runbook when ≥ consolidate_min of its incidents were fixed the same way (Q-MEM-7 →
W-MEM-2), and salience decays (W-MEM-1). Steps come only from APPLIED actions. Everything is read and written in
FalkorDB; this module only sequences the calls."""

from __future__ import annotations

import hashlib
import time

from ..agent.weights import weights
from ..graph import client, writes
from ..graph.ro import RO
from ..mcp_server import context
from ..mcp_server import tools as T

MAX_FAMILY_PAGES = 50  # × 100 families per Q-MEM-6P page


def runbook_id(kind: str, target: str) -> str:
    """One derived runbook per procedure (fix kind + target) per tenant; later consolidations update it."""
    h = hashlib.sha256(f"{kind}|{target}".encode()).hexdigest()[:10]
    return f"rb-derived-{h}"


def _consolidate(g, ro: RO, tenant: str, members: list[str], min_support: int) -> dict | None:
    fixes = ro.run("Q-MEM-7", {"members": members}).rows
    top = next((f for f in fixes if f["n"] >= min_support), None)
    if not top:
        return None
    title = f"Derived: {top['kind'].replace('_', ' ')} {top['target']} (worked {top['n']}×)"
    body = (f"Consolidated from {top['n']} incidents in one family whose verified fix was {top['kind']} on "
            f"{top['target']}: {', '.join(top['incidents'][:8])}. Steps come only from APPLIED actions; check the "
            "gate's proof path before applying.")
    return writes.consolidate_family(g, tenant=tenant, rid=runbook_id(top["kind"], top["target"]),
                                     incidents=top["incidents"], kind=top["kind"], target=top["target"],
                                     min_support=min_support, title=title, body=body)


def consolidate_all(tenant: str, graph: str) -> list[dict]:
    """Seed-time LEARN over the whole history: every family with a repeatable APPLIED fix gets its runbook."""
    w = weights()["memory"]
    ro, g = RO(tenant, graph), client.engine().select_graph(graph)
    out = []
    # every family, keyset-paged (Q-MEM-6P), all pages read before the first write: consolidating a silently partial
    # set would skip runbooks without saying so, and a write between pages could move the later ones
    fams: list[dict] = []
    after = -1
    for _ in range(MAX_FAMILY_PAGES):
        page = ro.run("Q-MEM-6P", {"after": after})
        fams += page.rows
        if not page.truncated:
            break
        after = int(page.rows[-1]["communityId"])
    else:
        raise RuntimeError(f"Q-MEM-6P: more than {MAX_FAMILY_PAGES} pages of incident families (fail loudly)")
    seen: set[str] = set()
    for fam in fams:
        if seen & set(fam["incidents"]):  # the projection moved between pages: never consolidate an inconsistent read
            raise RuntimeError("Q-MEM-6P pages overlap: the family projection changed during the read (fail loudly)")
        seen |= set(fam["incidents"])
    # Q-MEM-6's order (largest family first): a later family that derives the same procedure updates its runbook
    for fam in sorted(fams, key=lambda f: (-int(f["size"]), int(f["communityId"]))):
        r = _consolidate(g, ro, tenant, fam["incidents"], int(w["consolidate_min"]))
        if r:
            out.append(r)
    return out


def learn(tenant: str, graph: str, inc: str, run_id: str | None = None, now_ms: int | None = None) -> dict:
    w = weights()["memory"]
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    token = context.bind(tenant, run_id=run_id, graph=graph, record=run_id is not None)
    try:
        fam = T.incident_families(incident_id=inc)
    finally:
        context.unbind(token)
    if "error" in fam:
        raise RuntimeError(f"incident_families failed: {fam['error']}")
    mine = next((f for f in fam.get("rows", []) if f["mine"]), None)
    out: dict = {"family": mine["incidents"] if mine else [], "families": len(fam.get("rows", [])), "runbook": None}
    g = client.engine().select_graph(graph)
    if mine:
        out["runbook"] = _consolidate(g, RO(tenant, graph), tenant, mine["incidents"], int(w["consolidate_min"]))
    out["decay"] = writes.decay(g, now_ms=now_ms, half_life_days=float(w["half_life_days"]))
    return out


__all__ = ["learn", "runbook_id"]
