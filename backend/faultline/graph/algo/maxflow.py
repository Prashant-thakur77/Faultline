"""Min-cut from FalkorDB's `algo.maxFlow` output.

`algo.maxFlow` returns the max-flow value and the edges carrying positive flow (`edges`, aligned
`edgeFlows`), but no explicit cut. The cut is recovered here by residual reachability over the
capacities of ALL candidate edges (Q-CUT-2, zero-flow edges included). This is the only graph
routine computed in Python (a deliberate exception); the flow itself always comes from
the engine.
"""

from __future__ import annotations

from collections import defaultdict, deque

EPS = 1e-9


class CutMismatch(AssertionError):
    """The recovered cut does not equal the engine's max-flow: inputs are misaligned. Fail loudly."""


def min_cut(
    sources: set[str],
    edges: list[tuple[str, str, str]],
    capacity: dict[str, float],
    flow: dict[str, float],
    max_flow: float,
    targets: set[str] | None = None,
) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Return (cut edges, source side S).

    edges: (u, v, edge_id) for every candidate edge; capacity/flow keyed by edge_id (missing flow = 0).
    targets: when given, every target must end up on the sink side (else the inputs are wrong).
    max_flow == 0 means the sources cannot reach the targets at all: the cut is empty.
    """
    if max_flow <= EPS:
        return [], set(sources)
    adj: dict[str, list[str]] = defaultdict(list)
    for u, v, eid in edges:
        c, f = capacity.get(eid, 0.0), flow.get(eid, 0.0)
        if c - f > EPS:
            adj[u].append(v)  # forward residual capacity
        if f > EPS:
            adj[v].append(u)  # backward residual (flow can be pushed back)
    side, queue = set(sources), deque(sources)
    while queue:
        x = queue.popleft()
        for y in adj[x]:
            if y not in side:
                side.add(y)
                queue.append(y)
    if targets and side & targets:
        raise CutMismatch(f"targets {sorted(side & targets)} reachable in the residual graph; cut is not separating")
    cut = [(u, v, eid) for u, v, eid in edges if u in side and v not in side and capacity.get(eid, 0.0) > EPS]
    total = sum(capacity[eid] for *_, eid in cut)
    if abs(total - max_flow) > 1e-6 * max(1.0, max_flow):
        raise CutMismatch(f"cut capacity {total} != maxFlow {max_flow}; check edges/edgeFlows alignment")
    return cut, side
