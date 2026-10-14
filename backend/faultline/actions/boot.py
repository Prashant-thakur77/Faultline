"""Process boot epochs for intent leases (review round 5, M1).

Every process that can hold an intent lease (the API's execute jobs and reconcilers, a reconciler run from a script or
a test) has a boot id, `BOOT_ID`, fixed at import. A lease records the boot that holds it (`Intent.lease_boot`). The
process heartbeats its boot in each tenant's audit graph (`(:Boot {id, seen_at})`, engine clock) and ends it on a
clean shutdown. A boot with no heartbeat for weights.yaml `actions.boot_stale_s`, or ended, is dead: a reconciler may
take its leases at once instead of waiting for the lease to expire (`actions.intent_lease_s`).

Why a heartbeat and not "every other boot is dead": two live processes (the API and `make eval`, or a test) may both
hold leases; only a process that stopped beating is presumed gone. A SIGKILLed API is therefore taken over about
`boot_stale_s` after its last beat (its own heartbeat thread dies with it), a cleanly stopped one at once.

The boot registry lives in FalkorDB like every other piece of state; the only process state is the id itself.
"""

from __future__ import annotations

import logging
import os
import uuid

from ..graph import client as gclient
from ..graph import writes
from ..graph.errors import GraphError, GraphNotReady
from ..graph.tenant import audit_graph, check_tenant

BOOT_ID = f"boot-{uuid.uuid4().hex[:12]}"
log = logging.getLogger("faultline.boot")


def _w() -> dict:
    from ..agent.weights import weights

    return weights()["actions"]


def stale_ms() -> int:
    return int(_w()["boot_stale_s"]) * 1000


def beat(tenant: str, role: str = "api") -> None:
    """Record that this boot is alive (audit_<tenant>, engine clock). Errors propagate (callers log them)."""
    g = gclient.engine().select_graph(audit_graph(check_tenant(tenant)))
    writes.boot_beat(g, boot=BOOT_ID, pid=os.getpid(), role=role)


def end(tenant: str) -> None:
    """A clean shutdown: this boot's leases are open to the next reconciler at once."""
    g = gclient.engine().select_graph(audit_graph(check_tenant(tenant)))
    writes.boot_end(g, boot=BOOT_ID)


def prune(tenant: str, keep_days: float = 2.0) -> None:
    g = gclient.engine().select_graph(audit_graph(check_tenant(tenant)))
    writes.boot_prune(g, keep_ms=int(keep_days * 86_400_000))


def live(tenant: str) -> list[str] | None:
    """Boots alive now (Q-BOOT-LIVE on the engine clock), this one included when it beat recently. None when it cannot
    be told (no audit graph yet, a truncated list, or an error): the caller then honours lease expiry only."""
    from ..graph.ro import RO

    try:
        res = RO(check_tenant(tenant), audit_graph(tenant)).run("Q-BOOT-LIVE", {"stale_ms": stale_ms()})
    except GraphNotReady:
        return None
    except GraphError as e:
        log.warning("boot liveness unreadable for %s: %s", tenant, e)
        return None
    if res.truncated:
        return None
    return sorted({r["boot"] for r in res.rows} | {BOOT_ID})


__all__ = ["BOOT_ID", "beat", "end", "live", "prune", "stale_ms"]
