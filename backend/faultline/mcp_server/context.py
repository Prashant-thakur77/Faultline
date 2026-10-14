"""Per-session binding: tenant (never a tool argument) and, for agent runs, the run id that tool
calls and evidence are recorded under. Stdio/HTTP sessions bind the tenant at connection level."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field

from ..config import settings
from ..graph.tenant import check_tenant, graph_belongs_to, tenant_graph


@dataclass
class Binding:
    tenant: str
    run_id: str | None = None          # set by the agent loop; None for external (judge) sessions
    record: bool = True                # record ToolCall/Evidence in the graph when a run is bound
    graph: str = ""                    # the tenant's graph to use (tenant_<t>, or an eval_<t>_* clean room)
    caller: str | None = None          # hosted HTTP: the bearer key's client id (scopes per-caller reads, e.g. sessions)
    seq: list[int] = field(default_factory=lambda: [0])

    def __post_init__(self) -> None:
        self.graph = self.graph or tenant_graph(self.tenant)
        if not graph_belongs_to(self.graph, self.tenant):
            raise ValueError(f"graph {self.graph!r} does not belong to tenant {self.tenant!r}")

    def next_call_id(self) -> str:
        key = self.run_id or "ext"
        with _SEQ_LOCK:  # specialists call tools concurrently; two calls must never share a ToolCall id
            _SEQ[key] = _SEQ.get(key, 0) + 1
            n = _SEQ[key]
        return f"{key}-tc{n:04d}"


_SEQ: dict[str, int] = {}  # per-run call counter (id generation only; all state lives in the graph)
_SEQ_LOCK = threading.Lock()
_binding: contextvars.ContextVar[Binding | None] = contextvars.ContextVar("faultline_binding", default=None)


def bind(tenant: str, run_id: str | None = None, record: bool = True, graph: str | None = None) -> contextvars.Token:
    return _binding.set(Binding(check_tenant(tenant), run_id, record, graph or ""))


def unbind(token: contextvars.Token) -> None:
    _binding.reset(token)


def current() -> Binding:
    """Explicit binding (agent runs, stdio) first; else the tenant bound to the HTTP bearer key; else the
    configured default tenant (stdio). External sessions never record run state."""
    b = _binding.get()
    if b is not None:
        return b
    from mcp.server.auth.middleware.auth_context import get_access_token

    tok = get_access_token()
    if tok is not None and (tok.claims or {}).get("tenant"):
        return Binding(check_tenant(tok.claims["tenant"]), record=False, caller=tok.client_id or "hosted")
    return Binding(check_tenant(settings.faultline_tenant))
