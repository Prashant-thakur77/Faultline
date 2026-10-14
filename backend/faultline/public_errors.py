"""What a client may see of a failure (review round 4 m12, round 5 minor 7).

One policy for every client-visible text: HTTP errors, job errors, StageEvent notes and run-index notes (the UI and
the SSE stream show those verbatim). Our own messages (a refused precondition, a busy warehouse, a budget, a lost
lease…) are shown as they are. Anything that can carry the engine's or the OS's own text (hosts, ports, file paths,
query internals, subprocess stderr) becomes a generic message with a request id, and the detail goes to the server
log under that id.
"""

from __future__ import annotations

import logging
import subprocess
import uuid

log = logging.getLogger("faultline.errors")

# exception types whose message is written by this codebase (shown as `Type: message`)
_OWN = (PermissionError, ValueError, KeyError, LookupError, TimeoutError)


def _rid(e: BaseException, what: str) -> str:
    rid = uuid.uuid4().hex[:12]
    log.error("request %s: %s: %s: %s", rid, what, type(e).__name__, e)
    return rid


def _raw(e: BaseException) -> bool:
    """An error that can carry the engine's, the OS's or a tool's own text: never shown to a client."""
    import redis

    from .actions.github import GitHubError
    from .graph.errors import GraphError, GraphNotReady

    if isinstance(e, GraphNotReady):
        return False
    if isinstance(e, (PermissionError, TimeoutError)) and e.errno is None:  # raised by our own preconditions
        return False
    return isinstance(e, (GraphError, redis.exceptions.RedisError, OSError, subprocess.SubprocessError, GitHubError))


def client_text(e: BaseException, what: str | None = None) -> str:
    """The client-visible text of `e` (at most 400 characters)."""
    from .config import settings
    from .graph.errors import GraphError, GraphNotReady, GraphUnavailable

    if isinstance(e, GraphNotReady):
        return f"graph not ready: {e}"[:400]
    if isinstance(e, GraphUnavailable):
        why = " (graph disabled: FAULTLINE_DISABLE_GRAPH)" if settings.faultline_disable_graph else ""
        return f"FalkorDB unavailable{why} (request id {_rid(e, 'FalkorDB unavailable')})"
    if isinstance(e, GraphError):
        return f"graph query failed (request id {_rid(e, 'graph query failed')})"
    if _raw(e):
        label = what or ("GitHub request failed" if type(e).__name__ == "GitHubError" else "FalkorDB error"
                         if "redis" in type(e).__module__ else "internal error")
        return f"{label} (request id {_rid(e, label)})"
    if isinstance(e, _OWN) or (isinstance(e, RuntimeError) and type(e).__module__.startswith("faultline")) \
            or type(e) is RuntimeError:  # (an OS-raised PermissionError/TimeoutError carries an errno: raw, above)
        return f"{type(e).__name__}: {e}"[:400]
    label = what or "internal error"
    return f"{label} (request id {_rid(e, label)})"


__all__ = ["client_text"]
