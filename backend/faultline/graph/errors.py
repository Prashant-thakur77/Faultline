"""Graph-layer errors. Each one is fail-loud: callers surface it, never substitute data."""


class GraphError(RuntimeError):
    """Base class."""


class GraphUnavailable(GraphError):
    """FAULTLINE_DISABLE_GRAPH is set, or FalkorDB is unreachable."""


class GraphTimeout(GraphError):
    """The query exceeded its TIMEOUT. A timeout is never an empty result (three-valued verdicts)."""


class GraphNotReady(GraphError):
    """The tenant graph has no (:Meta {ready:true}); a half-seeded graph is never served."""


class GraphQueryError(GraphError):
    """The engine rejected the query (syntax, permission, write under RO_QUERY)."""
