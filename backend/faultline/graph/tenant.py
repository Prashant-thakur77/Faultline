"""Graph naming and tenant validation. One graph per tenant; no tool input ever names a graph."""

from __future__ import annotations

import hashlib
import re

TENANT_RE = re.compile(r"^[a-z][a-z0-9]{1,30}$")
GRAPH_RE = re.compile(r"^(tenant|golden|audit|scratch|whatif|eval|smoke)_[a-z0-9_]{1,80}$")


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
    """True if `name` is one of tenant t's graphs (tenant_t, golden_t[_nomem], audit_t, scratch_t_*, whatif_t_*, eval_t_*)."""
    t = check_tenant(tenant)
    if not GRAPH_RE.fullmatch(name):
        return False
    return bool(re.fullmatch(rf"(tenant|golden|audit)_{t}(_nomem)?|(scratch|whatif|eval)_{t}_[a-z0-9_]+", name))


def tenant_graph(t: str) -> str:
    return f"tenant_{check_tenant(t)}"


def golden_graph(t: str, nomem: bool = False) -> str:
    return f"golden_{check_tenant(t)}" + ("_nomem" if nomem else "")


def audit_graph(t: str) -> str:
    return f"audit_{check_tenant(t)}"


def scratch_graph(t: str, incident_id: str) -> str:
    return _safe("scratch", t, incident_id)


def whatif_graph(t: str, op_id: str) -> str:
    return _safe("whatif", t, op_id)


def eval_graph(t: str, run: str, arm: str, scenario: str, trial: int) -> str:
    return _safe("eval", t, f"{run}_{arm}_{scenario}_{int(trial)}")
