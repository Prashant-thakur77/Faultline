"""Graph naming and tenant validation. One graph per tenant; no tool input ever names a graph."""

from __future__ import annotations

import hashlib
import re

TENANT_RE = re.compile(r"^[a-z][a-z0-9]{1,30}$")
GRAPH_RE = re.compile(r"^(tenant|golden|audit|oncall|agentmem|scratch|whatif|eval|smoke)_[a-z0-9_]{1,80}$")


def check_tenant(t: str) -> str:
    if not isinstance(t, str) or not TENANT_RE.fullmatch(t):
        raise ValueError(f"invalid tenant {t!r}")
    return t


def _safe(kind: str, tenant: str, suffix: str) -> str:
    """Sanitise a suffix; if sanitising changed it or it is too long, append a hash of the raw
    suffix so distinct inputs (inc_ABC-1 vs inc_abc_1, long eval ids) never share a graph."""
    clean = re.sub(r"[^a-z0-9_]", "_", suffix.lower()).strip("_")
    if not clean:
        raise ValueError(f"empty {kind} suffix")
    base = f"{kind}_{check_tenant(tenant)}_"
    if clean != suffix or len(base) + len(clean) > 80:
        clean = f"{clean[: 80 - len(base) - 9]}_{hashlib.sha1(suffix.encode()).hexdigest()[:8]}"
    name = base + clean
    if not GRAPH_RE.fullmatch(name):
        raise ValueError(f"invalid graph name {name!r}")
    return name


def graph_belongs_to(name: str, tenant: str) -> bool:
    """True if `name` is one of tenant t's graphs (tenant_t, golden_t[_nomem], audit_t, oncall_t, agentmem_t,
    scratch_t_*, whatif_t_*, eval_t_*)."""
    t = check_tenant(tenant)
    if not GRAPH_RE.fullmatch(name):
        return False
    own = rf"(tenant|golden|audit)_{t}(_nomem)?|(oncall|agentmem)_{t}|(scratch|whatif|eval)_{t}_[a-z0-9_]+"
    return bool(re.fullmatch(own, name))


def tenant_graph(t: str) -> str:
    return f"tenant_{check_tenant(t)}"


def golden_graph(t: str, nomem: bool = False) -> str:
    return f"golden_{check_tenant(t)}" + ("_nomem" if nomem else "")


def audit_graph(t: str) -> str:
    return f"audit_{check_tenant(t)}"


def oncall_graph(t: str) -> str:
    """The tenant's durable on-call graph (M19): pages of real incidents, contracts, hand-offs and the bot's state. A
    copy of golden_<t> made once (people, rota, components); re-arm and seeding never replace it."""
    return f"oncall_{check_tenant(t)}"


def memory_graph(t: str) -> str:
    """Shared agent notes (T2): a GRAPH.COPY of the tenant's golden topology plus the notes agents leave about it,
    written only by the mem_<t> ACL user, so a note can never touch the graph the gate reads."""
    return f"agentmem_{check_tenant(t)}"


def scratch_graph(t: str, incident_id: str) -> str:
    return _safe("scratch", t, incident_id)


def whatif_graph(t: str, op_id: str) -> str:
    return _safe("whatif", t, op_id)


def eval_graph(t: str, run: str, arm: str, scenario: str, trial: int) -> str:
    return _safe("eval", t, f"{run}_{arm}_{scenario}_{int(trial)}")
