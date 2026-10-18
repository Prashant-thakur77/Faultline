"""Shared agent notes (track T2: memory and coordination across agents), kept in FalkorDB.

Any agent (Faultline's own investigator, Claude Desktop through MCP, a teammate's bot) can leave a short note about
components ("payment's p99 doubled after the 14:02 config push; not proven"), and any other agent can recall it by
meaning and by graph distance, then confirm, refute or add to it with a reply. The memory lives in its own graph,
`agentmem_<tenant>`: a GRAPH.COPY of the tenant's golden topology plus the notes, so a recall ranks notes by vector
similarity AND by hops from the component asked about in one read-only query (Q-NOTE-RECALL), which a vector store
alone cannot do.

Isolation is the engine's, not the code's: notes are written by the `mem_<tenant>` ACL user, whose only key is
agentmem_<tenant>; reads go through the tenant's read-only user. A note is a lead, never evidence: Q-NOTE-RECALL has
no `seen` column, so nothing in a note can satisfy the gate's G1, and the gate never reads agentmem_<tenant>.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from ..agent.weights import weights
from ..graph import client, writes
from ..graph import copy as gcopy
from ..graph.ro import RO, QueryResult
from ..graph.tenant import check_tenant, golden_graph, memory_graph

KINDS = ("lead", "observation", "hypothesis", "handoff", "verdict")
STANCES = ("confirms", "refutes", "adds")

_ready: set[str] = set()
_lock = threading.Lock()


class NoteRefused(ValueError):
    """The graph refused the note (an `about` id not in the graph, unknown reply target or quota); the message says which."""

    def __init__(self, msg: str, unknown: list[str] | None = None):
        super().__init__(msg)
        self.unknown = unknown or []


def ensure_memory_graph(tenant: str) -> str:
    """agentmem_<tenant> exists: made once as a GRAPH.COPY of golden_<tenant> (components and their PROPAGATES_TO
    edges, with the schema's Note indexes and constraints), by the engine user. Idempotent."""
    t = check_tenant(tenant)
    name = memory_graph(t)
    if name in _ready:
        return name
    with _lock:
        db = client.engine()
        if not gcopy.exists(db, name):
            gcopy.copy_graph(db, golden_graph(t), name)
        writes.apply_schema(db.select_graph(name))  # Note indexes on a golden built before they existed
        _ready.add(name)
    return name


def _cfg() -> dict[str, Any]:
    return weights()["notes"]


def remember(tenant: str, *, principal: str, text: str, about: list[str], kind: str = "lead", name: str = "",
             session: str = "", reply_to: str = "", stance: str = "adds") -> dict[str, Any]:
    """Write one note (W-NOTE-1, atomic with its checks) as `principal` (the authenticated MCP key, or the process).
    `name` is how the agent calls itself (shown, never trusted for quotas)."""
    from .embed import embed_one

    w = _cfg()
    t = check_tenant(tenant)
    text = " ".join(str(text).split())
    if not 3 <= len(text) <= int(w["max_chars"]):
        raise ValueError(f"text must be 3..{w['max_chars']} characters")
    ids = sorted({str(i) for i in about})
    if not 1 <= len(ids) <= int(w["max_about"]):
        raise ValueError(f"about must name 1..{w['max_about']} node ids")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if stance not in STANCES:
        raise ValueError(f"stance must be one of {', '.join(STANCES)}")
    ensure_memory_graph(t)
    nid = f"note-{uuid.uuid4().hex[:12]}"
    out = writes.write_note(client.mem_graph(t), id=nid, principal=principal, name=name[:60], session=session[:80],
                            kind=kind, text=text, about=ids, vec=embed_one(text),
                            ttl_ms=int(float(w["ttl_days"]) * 86_400_000), quota=int(w["quota_per_day"]),
                            reply_to=reply_to, stance=stance)
    if out is None:
        why = RO(t, memory_graph(t)).run("Q-NOTE-REFUSED", {"about": ids, "reply_to": reply_to, "principal": principal})
        r = why.rows[0] if why.rows else {}
        if r.get("unknown_about"):
            raise NoteRefused(f"not in this graph: {', '.join(r['unknown_about'])}", r["unknown_about"])
        if not r.get("reply_ok", True):
            raise NoteRefused(f"no note {reply_to!r} to reply to")
        raise NoteRefused(f"daily note quota reached ({r.get('used')}/{w['quota_per_day']} in the last 24 h)")
    return {**out, "tenant": t, "graph": memory_graph(t), "about": ids, "kind": kind,
            **({"reply_to": reply_to, "stance": stance} if reply_to else {})}


def last_note(tenant: str, principal: str) -> str | None:
    """The newest note `principal` wrote (Q-NOTE-LAST), so a later step of the same run can reply to it."""
    t = check_tenant(tenant)
    ensure_memory_graph(t)
    rows = RO(t, memory_graph(t)).run("Q-NOTE-LAST", {"principal": principal}).rows
    return rows[0]["id"] if rows else None


def leave_note(tenant: str, *, principal: str, text: str, about: list[str], kind: str, reply_to: str = "",
               stance: str = "adds") -> dict[str, Any]:
    """Faultline's own note for the next agent (an investigation's verdict or hand-off, a verified fix), about the ids
    that exist in the memory graph: a scenario-only id (a change made inside a clean room) is dropped and the write
    retried once; nothing left raises NoteRefused."""
    ids = sorted({i for i in about if i})
    try:
        return remember(tenant, principal=principal, name="faultline", text=text, about=ids, kind=kind,
                        reply_to=reply_to, stance=stance)
    except NoteRefused as e:
        rest = [i for i in ids if i not in set(e.unknown)]
        if not e.unknown or not rest:
            raise
        return remember(tenant, principal=principal, name="faultline", text=text, about=rest, kind=kind,
                        reply_to=reply_to, stance=stance)


def recall(tenant: str, *, text: str = "", focus: str = "") -> QueryResult:
    """Q-NOTE-RECALL: notes by meaning (`text`) and by graph distance (`focus`), ranked in the engine."""
    from .embed import embed_one

    w = _cfg()
    t = check_tenant(tenant)
    if not text.strip() and not focus:
        raise ValueError("give text, focus or both")
    ensure_memory_graph(t)
    q = embed_one(text) if text.strip() else None
    return RO(t, memory_graph(t)).run("Q-NOTE-RECALL", {
        "focus": focus, "q": q, "hops": int(w["near_hops"]), "floor": float(w["min_similarity"]),
        "w": [float(w["w_meaning"]), float(w["w_near"]), float(w["w_fresh"]), float(w["fresh_tau_min"])]})


__all__ = ["KINDS", "STANCES", "NoteRefused", "ensure_memory_graph", "last_note", "leave_note", "recall", "remember"]
