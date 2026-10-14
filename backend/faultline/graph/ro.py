"""The read-only wrapper. Every product read goes through `RO.run(template_id, params)`:

GRAPH.RO_QUERY + per-query TIMEOUT (clamped to TIMEOUT_MAX) + literal LIMIT (sent as n+1 so
truncation is detected) → the exact Cypher, params, rows, timing, a sha256 digest of the rows, the
node ids seen (graph entities + the template's declared `seen` columns only), a truncation flag and
`served_by`. Errors are three-valued and loud: GraphUnavailable / GraphTimeout / GraphNotReady /
GraphQueryError, never an empty result standing in for a failure. The ablation switch is checked
on EVERY call.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import redis

from ..config import settings
from . import client
from .algo import registry
from .errors import GraphNotReady, GraphQueryError, GraphTimeout, GraphUnavailable
from .templates import load
from .tenant import check_tenant, graph_belongs_to, tenant_graph


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def to_plain(v: Any) -> Any:
    """falkordb Node/Edge/Path → plain JSON-able values. Graph entities are tagged with `_labels`
    (nodes) or `_type` (edges) so only real entities contribute seen ids."""
    if hasattr(v, "labels") and hasattr(v, "properties"):
        return {"_labels": [x for x in (v.labels or []) if x != "Node"], **dict(v.properties or {})}
    if hasattr(v, "relation") and hasattr(v, "properties"):
        return {"_type": v.relation, **dict(v.properties or {})}
    if hasattr(v, "nodes") and callable(getattr(v, "nodes")) and hasattr(v, "edges"):
        return {"_path": [to_plain(n) for n in v.nodes()], "_rels": [to_plain(e) for e in v.edges()]}
    if isinstance(v, list):
        return [to_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: to_plain(x) for k, x in v.items()}
    return v


def _entity_ids(v: Any, out: set[str]) -> None:
    """ids of real graph nodes inside a value (dicts tagged `_labels` by to_plain)."""
    if isinstance(v, dict):
        if "_labels" in v and isinstance(v.get("id"), str):
            out.add(v["id"])
        for x in v.values():
            _entity_ids(x, out)
    elif isinstance(v, list):
        for x in v:
            _entity_ids(x, out)


def _strings(v: Any, out: set[str]) -> None:
    if isinstance(v, str):
        out.add(v)
    elif isinstance(v, list):
        for x in v:
            _strings(x, out)


@dataclass
class QueryResult:
    template_id: str
    cypher: str
    params: dict
    header: list[str]
    rows: list[dict]
    ms: float
    digest: str
    seen_ids: set[str] = field(default_factory=set)
    truncated: bool = False
    served_by: str = ""

    def as_evidence(self) -> dict:
        return {"template": self.template_id, "cypher": self.cypher, "params": self.params,
                "rows": len(self.rows), "ms": round(self.ms, 2), "digest": self.digest,
                "truncated": self.truncated, "served_by": self.served_by}


def classify(e: Exception, tid: str) -> Exception:
    """Map driver/engine errors to the graph error taxonomy. Exception TYPE first, then exact text."""
    msg = str(e)
    if isinstance(e, (redis.ConnectionError, redis.TimeoutError, ConnectionError, OSError)):
        return GraphUnavailable(f"{tid}: FalkorDB unreachable: {msg}")
    if "Query timed out" in msg:
        return GraphTimeout(f"{tid}: {msg}")
    if "empty key" in msg.lower():
        return GraphNotReady(f"{tid}: graph does not exist (not seeded): {msg}")
    return GraphQueryError(f"{tid}: {msg}")


class RO:
    def __init__(self, tenant: str, graph_name: str | None = None, max_rows: int | None = None, fresh: bool = False):
        self.tenant = check_tenant(tenant)
        self.graph_name = graph_name or tenant_graph(tenant)
        if not graph_belongs_to(self.graph_name, self.tenant):
            raise ValueError(f"graph {self.graph_name!r} does not belong to tenant {self.tenant!r}")
        self.max_rows = max_rows or settings.falkordb_result_limit
        self.fresh = fresh  # every run() on its own new connection (the write-back re-read channel)

    def _served_by(self) -> str:
        meta = registry.resolved_meta()
        acl = f"ro_{self.tenant}" if client.ro_acl_enabled() else "default-user"
        return f"FalkorDB {meta.get('engine', '?')} · {self.graph_name} · GRAPH.RO_QUERY as {acl}"

    def run(self, template_id: str, params: dict | None = None, timeout_ms: int | None = None) -> QueryResult:
        if settings.faultline_disable_graph:  # checked on every call (ablation arm A4)
            raise GraphUnavailable("graph disabled (FAULTLINE_DISABLE_GRAPH=true)")
        t = load(template_id)
        params = dict(params or {})
        timeout = max(1, min(int(timeout_ms or settings.falkordb_timeout_ms), settings.falkordb_timeout_max_ms))
        g = client.ro_graph(self.tenant, self.graph_name, fresh=self.fresh)
        t0 = time.perf_counter()
        try:
            res = g.ro_query(t.text, params=params, timeout=timeout)
        except Exception as e:
            raise classify(e, template_id) from e
        finally:
            if self.fresh:
                g.client.close()
        ms = (time.perf_counter() - t0) * 1000
        header = [h[1] if isinstance(h, (list, tuple)) else str(h) for h in (res.header or [])]
        header = [h.decode() if isinstance(h, bytes) else h for h in header]
        rows = [dict(zip(header, [to_plain(c) for c in r])) for r in res.result_set]
        cap = min(t.limit, self.max_rows)
        truncated = len(rows) > cap
        rows = rows[:cap]
        seen: set[str] = set()
        _entity_ids(rows, seen)
        for row in rows:
            for col in t.seen:
                _strings(row.get(col), seen)
        digest = hashlib.sha256(canonical_json(rows).encode()).hexdigest()
        return QueryResult(template_id, t.display, params, header, rows, ms, digest, seen, truncated, self._served_by())

    def run_guarded(self, query: str, params: dict | None = None) -> QueryResult:
        """Text2cypher, last resort: guard → GRAPH.EXPLAIN plan check (read-only user) → GRAPH.RO_QUERY with a
        3 s timeout. Same result shape as templates (template id 'T2C'), so it is recorded and cited the same way."""
        from . import guard as G

        if settings.faultline_disable_graph:
            raise GraphUnavailable("graph disabled (FAULTLINE_DISABLE_GRAPH=true)")
        q = G.guard(query)
        params = dict(params or {})
        G.check_params(params)
        g = client.ro_graph(self.tenant, self.graph_name)
        try:
            plan = g.explain(q, params)
            G.check_plan(list(plan.plan) if hasattr(plan, "plan") else str(plan).splitlines())
        except G.GuardError:
            raise
        except Exception as e:
            raise classify(e, "T2C") from e
        t0 = time.perf_counter()
        try:
            res = g.ro_query(q + " ", params=params, timeout=G.TIMEOUT_MS)
        except Exception as e:
            raise classify(e, "T2C") from e
        ms = (time.perf_counter() - t0) * 1000
        header = [h[1] if isinstance(h, (list, tuple)) else str(h) for h in (res.header or [])]
        header = [h.decode() if isinstance(h, bytes) else h for h in header]
        rows = [dict(zip(header, [to_plain(c) for c in r])) for r in res.result_set][: G.MAX_LIMIT]
        rows, _dropped = G.redact_rows(rows)  # the private-data policy on what came back, whatever the query was
        seen: set[str] = set()
        _entity_ids(rows, seen)
        for row in rows:  # text2cypher has no declared seen columns: id-like columns only
            for k, v in row.items():
                if k == "id" or k.endswith("_id") or k.endswith(".id"):
                    _strings(v, seen)
        digest = hashlib.sha256(canonical_json(rows).encode()).hexdigest()
        return QueryResult("T2C", q, params, header, rows, ms, digest, seen, False, self._served_by())

    def require_ready(self) -> dict:
        """Parking pattern: never serve a half-seeded graph."""
        r = self.run("Q-META-1", {})
        if not r.rows or not r.rows[0].get("ready"):
            raise GraphNotReady(f"{self.graph_name} is not ready (no (:Meta {{ready:true}}))")
        return r.rows[0]


def profile(tenant: str, template_id: str, params: dict | None = None, graph: str | None = None) -> dict:
    """GRAPH.PROFILE of a *template* (engine connection; UI Cypher panel only, never the model).
    Templates are lint-guaranteed read-only (no writes, CALL allowlist), so profiling cannot write.
    The API rate-limits callers."""
    if settings.faultline_disable_graph:
        raise GraphUnavailable("graph disabled (FAULTLINE_DISABLE_GRAPH=true)")
    t = load(template_id)
    name = graph or tenant_graph(check_tenant(tenant))
    if not graph_belongs_to(name, check_tenant(tenant)):
        raise ValueError(f"graph {name!r} does not belong to tenant {tenant!r}")
    g = client.engine().select_graph(name)
    try:
        plan = g.profile(t.text, params or {})
    except Exception as e:
        raise classify(e, template_id) from e
    lines = list(plan.plan) if hasattr(plan, "plan") else str(plan).splitlines()
    ms = 0.0
    for ln in lines:
        m = re.search(r"Execution time: ([0-9.]+) ms", ln)
        if m:
            ms += float(m.group(1))
    return {"plan": lines, "engine_ms": round(ms, 4), "graph": name}
