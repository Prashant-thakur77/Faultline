"""Engine-only writes. The model never holds this connection; every write is one atomic query.

Seed helpers (`upsert_nodes`, `upsert_edges`, `set_vectors`, `apply_schema`, `ensure_constraints`,
`mark_ready`) are used by scripts/seed.py. Labels and relationship types are formatted into the
Cypher text from `schema_model` whitelists (code constants), never from caller input; every value is
a parameter. Batches of 300 rows, per-query TIMEOUT, idempotent MERGE.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from falkordb import Graph

from .schema_model import check_label, check_rel

BATCH = 300
SESSION_RE = re.compile(r"^sess-[A-Za-z0-9_.@-]{1,120}$")  # server-issued brain session ids
WRITE_TIMEOUT_MS = 5_000  # within the default TIMEOUT_MAX (5000) and ours (10000)
SCHEMA_PATH = Path(__file__).with_name("schema.cypher")


class WriteError(RuntimeError):
    """A write did not do what it had to (dangling edge endpoints, constraint not operational…)."""


class IntentNotPending(WriteError):
    """An intent-bound write found the intent no longer PENDING, or leased by another writer (the reconciler or another
    execute): it was settled or taken over elsewhere, so this writer must stop without writing a verdict or a stage."""


class SessionError(WriteError):
    """A brain session id that is not server-issued (`sess-…`), collides with an existing node id, or belongs to
    another user."""


# An intent-bound write (W_EXECUTED, W_VERDICT, W_WB_*) proceeds only while the intent is PENDING and leased by this
# writer: `it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner)` ($owner null: any writer, for direct calls
# outside the API job and the reconciler, which always pass their lease owner). Inside each single query.


def _batches(rows: list[Any], n: int = BATCH) -> Iterable[list[Any]]:
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    """FalkorDB properties are scalars or lists of scalars; maps become canonical JSON strings."""
    out: dict[str, Any] = {}
    for k, v in props.items():
        if v is None:
            continue
        if isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v)):
            out[k] = json.dumps(v, sort_keys=True, separators=(",", ":"))
        else:
            out[k] = v
    return out


def apply_schema(g: Graph) -> dict[str, Any]:
    """Apply schema.cypher; tolerate 'already indexed'. Then the engine-enforced invariants of graph/constraints.py
    (M20 #1: every path that applies the schema, i.e. seed, every GRAPH.COPY, the on-call home graph and the scale
    worlds, gets them). Returns {created, existing, constraints}."""
    created = existing = 0
    rebuilt = _drop_drifted_vector_indexes(g)   # M20 #3: options (efRuntime…) changed in schema.cypher → rebuild
    for line in SCHEMA_PATH.read_text().splitlines():
        stmt = line.strip()
        if not stmt or stmt.startswith("//"):
            continue
        try:
            g.query(stmt, timeout=WRITE_TIMEOUT_MS)
            created += 1
        except Exception as e:
            msg = str(e).lower()
            if "already" in msg and ("index" in msg or "exists" in msg):
                existing += 1
            else:
                raise WriteError(f"schema statement failed: {stmt}: {e}") from e
    for label in rebuilt:   # never hand out a graph whose rebuilt vector index is still a partial one
        wait_index_operational(g, label)
    out: dict[str, Any] = {"created": created, "existing": existing, "constraints": ensure_constraints(g)}
    if rebuilt:
        out["vector_indexes_rebuilt"] = rebuilt
    return out


def wait_index_operational(g: Graph, label: str, deadline_s: float = 120.0) -> None:
    """Index builds over existing nodes are asynchronous on 6.0.2 (db.indexes status "[Indexing] i/n: UNDER
    CONSTRUCTION"); a vector query meanwhile reads a partial index and silently misses neighbours (found measuring
    recall, M20 #3). Wait until every index of `label` is OPERATIONAL."""
    end = time.time() + deadline_s
    while True:
        st = [r[1] for r in g.ro_query("CALL db.indexes() YIELD label, status RETURN label, status",
                                       timeout=WRITE_TIMEOUT_MS).result_set if r[0] == label]
        if st and all(x == "OPERATIONAL" for x in st):
            return
        if time.time() > end:
            raise WriteError(f"{g.name}: the index on {label} is not operational after {deadline_s:.0f} s: {st}")
        time.sleep(0.05)


_VEC_LINE = re.compile(r"^CREATE VECTOR INDEX FOR \(n:(\w+)\) ON \(n\.embedding\) OPTIONS \{(.*)\}\s*$")
_VEC_TUNED = ("M", "efConstruction", "efRuntime")   # HNSW options that only a rebuild changes (vectors stay on nodes)


def schema_vector_options() -> dict[str, dict[str, Any]]:
    """label → the HNSW options schema.cypher asks for (M, efConstruction, efRuntime; ints)."""
    out: dict[str, dict[str, Any]] = {}
    for line in SCHEMA_PATH.read_text().splitlines():
        m = _VEC_LINE.match(line.strip())
        if m:
            opts = dict(re.findall(r"(\w+)\s*:\s*'?([\w.]+)'?", m.group(2)))
            out[m.group(1)] = {k: int(opts[k]) for k in _VEC_TUNED if k in opts}
    return out


def _drop_drifted_vector_indexes(g: Graph) -> list[str]:
    """A vector index whose HNSW options differ from schema.cypher (e.g. the default efRuntime 10 before M20 #3) is
    dropped, so the CREATE that follows rebuilds it with the schema's options. The embeddings stay on the nodes."""
    want = schema_vector_options()
    try:
        rows = g.ro_query("CALL db.indexes() YIELD label, types, options RETURN label, types, options",
                          timeout=WRITE_TIMEOUT_MS).result_set
    except Exception as e:  # noqa: BLE001 - a graph that does not exist yet has no index to migrate
        if "empty key" in str(e).lower():
            return []
        raise
    dropped = []
    for label, types, options in rows:
        if label not in want or "VECTOR" not in ((types or {}).get("embedding") or []):
            continue
        have = (options or {}).get("embedding") or {}
        if any(int(have.get(k, -1)) != v for k, v in want[label].items()):
            check_label(label)
            g.query(f"DROP VECTOR INDEX FOR (n:{label}) ON (n.embedding)", timeout=WRITE_TIMEOUT_MS)
            dropped.append(label)
    return dropped


VECTOR_LABELS = ("Incident", "Runbook", "Postmortem", "IntentExemplar")


def rebuild_vector_index(g: Graph, label: str, *, ef_runtime: int, m: int = 16, ef_construction: int = 200) -> None:
    """Eval clean rooms only (evals/vector_recall.py): rebuild one vector index with the given HNSW options, to measure
    recall@10 against an exact scan at several efRuntime values. Options are validated ints; the label a fixed set."""
    if not g.name.startswith("eval_"):
        raise WriteError(f"refusing to rebuild a vector index outside an eval clean room: {g.name}")
    if label not in VECTOR_LABELS:
        raise WriteError(f"no vector index on {label!r}")
    ef_runtime, m, ef_construction = int(ef_runtime), int(m), int(ef_construction)
    if not (1 <= ef_runtime <= 10_000 and 2 <= m <= 512 and 1 <= ef_construction <= 10_000):
        raise WriteError("HNSW options out of range")
    try:
        g.query(f"DROP VECTOR INDEX FOR (n:{label}) ON (n.embedding)", timeout=WRITE_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001 - no index yet is fine; anything else is not
        if "no such index" not in str(e).lower() and "unable to drop" not in str(e).lower():
            raise WriteError(f"vector index drop failed on {label}: {e}") from e
    g.query(f"CREATE VECTOR INDEX FOR (n:{label}) ON (n.embedding) OPTIONS {{dimension:384, similarityFunction:'cosine', "
            f"M:{m}, efConstruction:{ef_construction}, efRuntime:{ef_runtime}}}", timeout=WRITE_TIMEOUT_MS)
    wait_index_operational(g, label)


def _constraint_violators(g: Graph, c: Any) -> list[str]:
    """Up to 5 records breaking constraint `c` (label and properties are code constants from graph/constraints.py)."""
    if c.kind == "MANDATORY":
        miss = " OR ".join(f"x.{p} IS NULL" for p in c.props)
        pat = f"(x:{c.label})" if c.entity == "NODE" else f"()-[x:{c.label}]->()"
        q = f"MATCH {pat} WHERE {miss} RETURN coalesce(x.id, x.k, toString(id(x))) LIMIT 5"
    else:
        cols = ", ".join(f"x.{p}" for p in c.props)
        q = f"MATCH (x:{c.label}) WITH [{cols}] AS k, count(x) AS n WHERE n > 1 RETURN toString(k) LIMIT 5"
    try:
        return [str(r[0]) for r in g.ro_query(q, timeout=WRITE_TIMEOUT_MS).result_set]
    except Exception as e:  # noqa: BLE001 - the audit is a diagnostic for the error message only
        return [f"(audit query failed: {e})"]


def ensure_constraints(g: Graph, deadline_s: float = 30.0) -> dict[str, Any]:
    """Create every constraint of graph/constraints.py that `g` lacks (async on 6.0: PENDING → OPERATIONAL), then wait
    until all are OPERATIONAL. A constraint that ends FAILED (data already violates it) is dropped again and raises
    WriteError naming it and up to 5 violators: the data must be fixed, never the constraint. Idempotent: on a graph that
    has them (a GRAPH.COPY carries constraints) this is one db.constraints() read. Returns {total, created, operational}."""
    from .constraints import CONSTRAINTS, PENDING, RETIRED, STATUS_QUERY, by_key, key_of

    def status() -> dict:
        return {key_of(r): str(r[4]) for r in g.ro_query(STATUS_QUERY, timeout=WRITE_TIMEOUT_MS).result_set}

    have = status()
    for c in RETIRED:   # created once by an earlier version and no longer wanted (graph/constraints.py says why)
        if c.key in have:
            g.execute_command("GRAPH.CONSTRAINT", "DROP", g.name, *c.args())
    created = 0
    for c in CONSTRAINTS:
        if c.key in have and have[c.key] != "FAILED":
            continue
        if have.get(c.key) == "FAILED":  # left over from an earlier attempt on bad data: drop it and try again
            g.execute_command("GRAPH.CONSTRAINT", "DROP", g.name, *c.args())
        try:
            g.execute_command("GRAPH.CONSTRAINT", "CREATE", g.name, *c.args())
            created += 1
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise WriteError(f"constraint {c.describe()} could not be created on {g.name}: {e}") from e
    want = by_key()
    end = time.time() + deadline_s
    while True:
        have = status()
        mine = {k: v for k, v in have.items() if k in want}
        if not any(v in PENDING for v in mine.values()) or time.time() > end:
            break
        time.sleep(0.05)
    failed = [want[k] for k, v in mine.items() if v == "FAILED"]
    for c in failed:
        bad = _constraint_violators(g, c)
        try:
            g.execute_command("GRAPH.CONSTRAINT", "DROP", g.name, *c.args())
        except Exception:  # noqa: BLE001 - the error below is what matters
            pass
        raise WriteError(f"{g.name}: the data violates {c.describe()} ({c.why}); violators: {', '.join(bad) or '?'}")
    missing = [want[k].describe() for k in want if mine.get(k) != "OPERATIONAL"]
    if missing:
        raise WriteError(f"{g.name}: constraints not operational after {deadline_s:.0f} s: {'; '.join(missing)}")
    return {"total": len(CONSTRAINTS), "created": created, "operational": len(mine)}


# M20 #11: the high-volume label whose low-cardinality strings FalkorDB stores once (intern(): one shared copy per
# distinct string, GRAPH.INFO ObjectPool). Measured on 6.0.2 at 100k MetricWindow nodes: GRAPH.MEMORY total 67 → 48 MB,
# attributes 40 → 21 MB, equality matches unchanged. The value must be WRITTEN through intern(): a later
# `SET n.p = intern(n.p)` interns nothing (6.0.2 skips a SET to an equal value).
INTERNED: dict[str, tuple[str, ...]] = {"MetricWindow": ("target_id", "metric", "kind", "source")}


def upsert_nodes(g: Graph, label: str, rows: list[dict[str, Any]]) -> int:
    check_label(label)
    if any(not isinstance(r.get("id"), str) or not r["id"] for r in rows):
        raise WriteError(f"{label}: every row needs a non-empty string id")
    keys = INTERNED.get(label, ())
    # Every node also carries :Node (indexed on id) so cross-label id lookups in templates use an index. Interned keys
    # are set from r.i (string values only); a key a row lacks keeps the node's current value (coalesce).
    q = (f"UNWIND $rows AS r MERGE (n:{label}:Node {{id: r.id}}) SET n += r.props"
         + "".join(f", n.{k} = coalesce(intern(r.i.{k}), n.{k})" for k in keys) + " RETURN count(n)")
    n = 0
    for chunk in _batches(rows):
        payload = []
        for r in chunk:
            props = _clean({k: v for k, v in r.items() if k != "embedding"})
            inter = {k: props.pop(k) for k in keys if isinstance(props.get(k), str)}
            payload.append({"id": r["id"], "props": props, **({"i": inter} if keys else {})})
        n += g.query(q, {"rows": payload}, timeout=WRITE_TIMEOUT_MS).result_set[0][0]
    return n


def set_vectors(g: Graph, label: str, rows: list[dict[str, Any]], prop: str = "embedding") -> int:
    """Write embeddings with vecf32() so the vector index sees them (plain lists are invisible to it)."""
    check_label(label)
    if prop not in ("embedding",):
        raise WriteError(f"unsupported vector property {prop!r}")
    q = f"UNWIND $rows AS r MATCH (n:{label} {{id: r.id}}) SET n.embedding = vecf32(r.v) RETURN count(n)"
    n = 0
    for chunk in _batches(rows):
        n += g.query(q, {"rows": [{"id": r["id"], "v": [float(x) for x in r[prop]]} for r in chunk]},
                     timeout=WRITE_TIMEOUT_MS).result_set[0][0]
    if n != len(rows):
        raise WriteError(f"{label}: wrote {n}/{len(rows)} vectors (missing nodes)")
    return n


def upsert_edges(g: Graph, rel: str, src_label: str, dst_label: str, rows: list[dict[str, Any]]) -> int:
    """MERGE (a)-[e:REL {k}]->(b) SET e += props. `k` (props['key'], default '') lets several
    edges of one type exist between the same pair (e.g. ON_CALL rota periods). Dangling endpoints
    fail loudly."""
    check_rel(rel), check_label(src_label), check_label(dst_label)
    q = (
        f"UNWIND $rows AS r MATCH (a:{src_label} {{id: r.src}}) MATCH (b:{dst_label} {{id: r.dst}}) "
        f"MERGE (a)-[e:{rel} {{k: r.k}}]->(b) SET e += r.props RETURN count(e)"
    )
    n = 0
    for chunk in _batches(rows):
        payload = []
        for r in chunk:
            props = _clean(dict(r.get("props") or {}))
            payload.append({"src": r["src"], "dst": r["dst"], "k": str(props.pop("key", "")), "props": props})
        n += g.query(q, {"rows": payload}, timeout=WRITE_TIMEOUT_MS).result_set[0][0]
    if n != len(rows):
        raise WriteError(f"{rel}({src_label}->{dst_label}): matched {n}/{len(rows)} rows (dangling endpoints)")
    return n


def mark_ready(g: Graph, data_hash: str, engine: str, tenant: str) -> None:
    g.query(
        "MERGE (m:Meta {id:'meta'}) SET m.ready = true, m.data_hash = $h, m.seeded_at = timestamp(), "
        "m.engine = $e, m.tenant = $t",
        {"h": data_hash, "e": engine, "t": tenant},
        timeout=WRITE_TIMEOUT_MS,
    )


def unmark_ready(g: Graph) -> None:
    g.query("MATCH (m:Meta) SET m.ready = false", timeout=WRITE_TIMEOUT_MS)


def normalise_flow_props(g: Graph) -> int:
    """Every relationship type that the gate's path query walks gets w=1 and cap=1.0 unless set
    (smoke: SPpaths weightProp must exist on every traversed rel type)."""
    res = g.query(
        "MATCH ()-[r:CHANGED|GATES]->() SET r.w = coalesce(r.w, 1), r.cap = coalesce(r.cap, 1.0) RETURN count(r)",
        timeout=WRITE_TIMEOUT_MS,
    )
    # call share on service/datastore failure edges (server a → client b): the share of b's incoming traffic that
    # calls a, the same quantity the telemetry simulator propagates with (Q-SIM-2). G4 upstream's strict lower bound
    # reads it; an edge without one (data plane, learned link) is unusable for elimination
    g.query(W_SHARE, timeout=WRITE_TIMEOUT_MS)
    return res.result_set[0][0]


W_SHARE = (
    "MATCH (a:Node)-[r:PROPAGATES_TO]->(b:Node) WHERE (a:Service OR a:Datastore) AND (b:Service OR b:Datastore) "
    "MATCH (b)-[c:CALLS]->(a) "
    "WITH a, b, r, c "
    "MATCH ()-[ci:CALLS]->(b) "
    "WITH r, c, sum(ci.rps) AS in_rps "
    "SET r.share = CASE WHEN in_rps > 0 AND toFloat(c.rps) / in_rps < 1.0 THEN toFloat(c.rps) / in_rps ELSE 1.0 END "
    "RETURN count(r)"
)


def counts(g: Graph) -> dict[str, dict[str, int]]:
    """Nodes per label and edges per type, from db.meta.stats (O(1) engine counters, exact; a full MATCH scan nearly
    hit the write timeout at 25k services: scale bench finding)."""
    row = g.ro_query("CALL db.meta.stats() YIELD labels, relTypes RETURN labels, relTypes", timeout=WRITE_TIMEOUT_MS).result_set[0]
    labels, rels = row[0] or {}, row[1] or {}
    nodes = {k: int(v) for k, v in labels.items() if k != "Node" and int(v) > 0}
    return {"nodes": dict(sorted(nodes.items())), "edges": {k: int(v) for k, v in sorted(rels.items()) if int(v) > 0}}


def append_audit(g: Graph, kind: str, props: dict[str, Any]) -> None:
    """Append-only audit graph rows (re-arm log, forget receipts). Label from a fixed whitelist."""
    if kind not in ("Rearm", "ForgetReceipt", "PlaygroundRun"):
        raise WriteError(f"unsupported audit kind {kind!r}")
    g.query(f"CREATE (a:{kind}) SET a += $p, a.at = timestamp()", {"p": _clean(props)}, timeout=WRITE_TIMEOUT_MS)


# ---------------------------------------------------------------------------------------------
# Run state (engine; the model never holds this connection). One atomic query each.
# ---------------------------------------------------------------------------------------------

W_TOOL_CALL = (
    "MERGE (run:Run:Node {id: $run}) ON CREATE SET run.created_at = timestamp(), run.tenant = $tenant "
    "CREATE (tc:ToolCall:Node {id: $tc_id, tool: $tool, template: $template, at: timestamp(), ms: $ms, "
    "rows: $rows, truncated: $truncated, served_by: $served_by}) "
    "MERGE (run)-[:HAS_TOOL_CALL {k: $tc_id}]->(tc) "
    "MERGE (e:Evidence:Node {id: $ev_id}) ON CREATE SET e.kind = $kind, e.source = 'falkordb', "
    "e.transport = 'GRAPH.RO_QUERY', e.tool = $tool, e.template = $template, e.cypher = $cypher, "
    "e.params = $params, e.digest = $digest, e.value = $value, e.baseline = $baseline, e.ratio = $ratio, "
    "e.summary = $summary, e.payload = $payload, e.at = timestamp() "
    "MERGE (tc)-[:PRODUCED_EVIDENCE {k: ''}]->(e) "
    "WITH tc, e "
    # SAW = returned by the graph (seen); ABOUT = what the evidence is about (may include caller-supplied ids)
    "UNWIND (CASE WHEN size($ids) = 0 THEN [null] ELSE $ids END) AS sid "
    "OPTIONAL MATCH (n:Node {id: sid}) "
    "FOREACH (_ IN CASE WHEN n IS NULL OR n:ToolCall OR n:Evidence OR NOT n.id IN $seen THEN [] ELSE [1] END | "
    "  MERGE (tc)-[:SAW {k: ''}]->(n)) "
    "FOREACH (_ IN CASE WHEN n IS NULL OR NOT n.id IN $about THEN [] ELSE [1] END | "
    "  MERGE (e)-[:ABOUT {k: ''}]->(n)) "
    "RETURN sum(CASE WHEN n IS NOT NULL AND n.id IN $seen THEN 1 ELSE 0 END) AS confirmed"
)

PAYLOAD_CAP = 20000   # characters of JSON kept per stored payload (evidence, tool calls, specialist reports)


def capped_json(obj: Any, cap: int = PAYLOAD_CAP) -> str:
    """Canonical JSON of `obj`, never longer than `cap` and always valid JSON. A payload that does not fit keeps as
    many leading `rows` as fit (with `rows_truncated` saying how many were dropped); anything else becomes a marker
    with the size and the start of the text. Cutting the JSON text itself would store an unterminated string."""
    s = json.dumps(obj, sort_keys=True, default=str)
    if len(s) <= cap:
        return s
    if isinstance(obj, dict) and isinstance(obj.get("rows"), list):
        rows = obj["rows"]

        def fit(n: int) -> str:
            return json.dumps({**obj, "rows": rows[:n], "rows_truncated": len(rows) - n}, sort_keys=True, default=str)

        lo, hi = 0, len(rows)
        while lo < hi:   # the largest prefix of rows that fits
            mid = (lo + hi + 1) // 2
            if len(fit(mid)) <= cap:
                lo = mid
            else:
                hi = mid - 1
        t = fit(lo)
        if len(t) <= cap:
            return t
    return json.dumps({"truncated": True, "chars": len(s), "head": s[: cap // 2]}, default=str)


def record_tool_call(g: Graph, *, run_id: str, tenant: str, tc_id: str, tool: str, template: str, cypher: str,
                     params: dict, digest: str, rows: int, ms: float, truncated: bool, served_by: str,
                     seen_ids: list[str], ev_id: str, kind: str, about: list[str], summary: str = "",
                     value: float | None = None, baseline: float | None = None, ratio: float | None = None,
                     payload: Any = None) -> int:
    """Write the tool call, its Evidence (W-EV-1) and the SAW/ABOUT edges in ONE atomic query.
    Returns how many returned ids were confirmed as real nodes (G1 grounding reads SAW edges)."""
    res = g.query(W_TOOL_CALL, {
        "run": run_id, "tenant": tenant, "tc_id": tc_id, "tool": tool, "template": template, "ms": round(ms, 2),
        "rows": rows, "truncated": truncated, "served_by": served_by, "ev_id": ev_id, "kind": kind,
        "cypher": cypher, "params": json.dumps(params, sort_keys=True, default=str), "digest": digest,
        "value": value, "baseline": baseline, "ratio": ratio, "summary": summary[:500],
        "seen": sorted(set(seen_ids))[:500], "about": sorted(set(about)),
        "ids": sorted(set(sorted(set(seen_ids))[:500]) | set(about)),
        "payload": capped_json(payload) if payload is not None else None,
    }, timeout=WRITE_TIMEOUT_MS)
    return int(res.result_set[0][0]) if res.result_set else 0


W_OPEN_INCIDENT = (
    "MERGE (i:Incident:Node {id: $inc}) "
    "ON CREATE SET i.title = $title, i.report = $report, i.stage = 'INTAKE', i.opened_at = timestamp(), "
    "i.onset_at = $onset, i.tenant = $tenant, i.salience_base = 1.0, i.salience = 1.0, i.confident = false "
    "MERGE (run:Run:Node {id: $run}) ON CREATE SET run.created_at = timestamp(), run.tenant = $tenant, "
    "run.models = $models, run.mode = $mode "
    "MERGE (i)-[:HAS_RUN {k: $run}]->(run) "
    "WITH i UNWIND $symptoms AS s "
    "MATCH (target:Node {id: s.target}) "
    "MERGE (sy:Symptom:Node {id: s.id}) ON CREATE SET sy.kind = s.kind, sy.target_id = s.target "
    "MERGE (i)-[:HAS_SYMPTOM {k: ''}]->(sy) "
    "MERGE (i)-[:AFFECTED {k: 'symptom:' + s.target}]->(target) SET target.status_incident = $inc "
    "RETURN count(sy) AS symptoms"
)


def open_incident(g: Graph, *, inc: str, run: str, tenant: str, title: str, report: str, onset: int,
                  symptoms: list[dict[str, str]], models: str, mode: str) -> int:
    """Create the Incident, its Run and Symptom nodes in one query; every symptom target must exist."""
    n = g.query(W_OPEN_INCIDENT, {"inc": inc, "run": run, "tenant": tenant, "title": title[:200],
                                  "report": report[:2000], "onset": int(onset), "symptoms": symptoms,
                                  "models": models, "mode": mode}, timeout=WRITE_TIMEOUT_MS).result_set
    got = int(n[0][0]) if n else 0
    if got != len(symptoms):
        raise WriteError(f"incident {inc}: {got}/{len(symptoms)} symptom targets exist in the graph")
    return got


W_STAGE = (
    "MATCH (i:Incident {id: $inc}) MATCH (run:Run {id: $run}) "
    "WITH i, run WHERE $force OR coalesce(i.stage_ord, 0) < $ord "
    "SET i.stage = $stage, i.stage_ord = $ord "
    "CREATE (se:StageEvent:Node {id: $se, stage: $stage, ord: $ord, at: timestamp(), note: $note}) "
    "MERGE (run)-[:HAS_STAGE {k: $se}]->(se) "
    "RETURN i.stage"
)


W_STAGE_OWNED = (
    "MATCH (i:Incident {id: $inc}) MATCH (run:Run {id: $run}) "
    "MATCH (i)-[:HAS_PLAN]->(a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem "
    # the action's stages move only for the writer that holds the intent's lease, and (before that writer settled the
    # intent itself) only while it is still PENDING: a reconciler that took the intent over is never overwritten
    "WITH i, run, it WHERE ($force OR coalesce(i.stage_ord, 0) < $ord) AND ($owner IS NULL OR it.lease_by = $owner) "
    "AND ($settled OR it.state = 'PENDING') "
    "SET i.stage = $stage, i.stage_ord = $ord "
    "CREATE (se:StageEvent:Node {id: $se, stage: $stage, ord: $ord, at: timestamp(), note: $note}) "
    "MERGE (run)-[:HAS_STAGE {k: $se}]->(se) "
    "RETURN i.stage"
)


def advance_stage(g: Graph, *, inc: str, run: str, stage: str, ord_: int, note: str = "", force: bool = False,
                  aid: str | None = None, owner: str | None = None, settled: bool = False) -> bool:
    """Forward-only in the graph itself: the write is a no-op unless the new stage is later
    (terminals pass force=True). Returns whether the stage changed. Every event gets its own id (audit trail).
    With `aid` (an approved action's execute/verify/write-back stages) the move is also bound to its intent, in the
    same query: only the lease owner moves it, and only while the intent is PENDING unless `settled` (the stages the
    owner writes after it settled the intent itself: RESOLVED, back to AWAITING_APPROVAL, tracked)."""
    import uuid

    se = f"{run}-se-{stage}-{ord_}-{uuid.uuid4().hex[:6]}"
    params = {"inc": inc, "run": run, "stage": stage, "ord": int(ord_), "se": se, "note": note[:500], "force": bool(force)}
    if aid is None:
        return bool(g.query(W_STAGE, params, timeout=WRITE_TIMEOUT_MS).result_set)
    return bool(g.query(W_STAGE_OWNED, {**params, "aid": aid, "owner": owner, "settled": bool(settled)},
                        timeout=WRITE_TIMEOUT_MS).result_set)


W_CHUNKS = (
    "UNWIND $rows AS r MATCH (d:Doc {id: r.doc}) "
    "MERGE (c:Chunk {id: r.id}) SET c.doc = r.doc, c.ord = r.ord, c.text = r.text, c.digest = r.digest, "
    "c.embedding = vecf32(r.v) "
    "MERGE (c)-[:PART_OF]->(d) RETURN count(c)"
)
W_CHUNKS_STALE = "MATCH (c:Chunk) WHERE c.doc IN $docs AND NOT c.id IN $ids DETACH DELETE c RETURN count(c)"


def upsert_chunks(g: Graph, rows: list[dict[str, Any]], *, docs: list[str]) -> int:
    """Document chunks (ingest/chunks.py) with their vecf32 embeddings, each PART_OF its Doc; idempotent. Chunks of
    `docs` that are no longer produced (the document shrank) are removed. Returns the chunks written."""
    n = 0
    for batch in _batches(rows):
        n += g.query(W_CHUNKS, {"rows": [{**{k: r[k] for k in ("id", "doc", "ord", "text", "digest")},
                                          "v": [float(x) for x in r["v"]]} for r in batch]},
                     timeout=WRITE_TIMEOUT_MS).result_set[0][0]
    if n != len(rows):
        raise WriteError(f"Chunk: wrote {n}/{len(rows)} (a chunk's Doc is missing)")
    g.query(W_CHUNKS_STALE, {"docs": docs, "ids": [r["id"] for r in rows]}, timeout=WRITE_TIMEOUT_MS)
    return n


# ------------------------------------------------------------------ shared agent notes (T2, agentmem_<tenant>)
W_NOTE = (
    # ONE query, so every condition and the write are atomic together: every `about` id is a node of the graph,
    # the reply target exists, and the author is under its daily quota on the ENGINE clock (concurrent writers cannot
    # both take the last slot). A reply keeps the note it answers alive at least as long as itself. A private note is
    # seen only by its author; only a note the author can see may be replied to.
    "OPTIONAL MATCH (p:Note {id: $reply_to}) "
    "WITH p "
    "MATCH (x:Node) WHERE x.id IN $about "
    "WITH p, collect(DISTINCT x) AS targets "
    "WHERE size(targets) = size($about) AND ($reply_to = '' OR (p IS NOT NULL AND "
    "(coalesce(p.visibility, 'shared') = 'shared' OR p.agent = $principal))) "
    "MERGE (a:Author {id: $principal}) "
    "WITH p, targets, a, size([(a)-[:WROTE]->(r:Note) WHERE r.created_at >= timestamp() - 86400000 | r]) AS used "
    "WHERE used < $quota "
    "CREATE (n:Note {id: $id, agent: $principal, name: $name, session: $session, kind: $kind, text: $text, "
    "visibility: $visibility, created_at: timestamp(), expires_at: timestamp() + $ttl_ms, embedding: vecf32($vec)}) "
    "CREATE (a)-[:WROTE]->(n) "
    "FOREACH (x IN targets | CREATE (n)-[:ABOUT]->(x)) "
    "FOREACH (q IN CASE WHEN p IS NULL THEN [] ELSE [p] END | CREATE (n)-[:REPLY_TO {stance: $stance}]->(q) "
    "SET q.expires_at = CASE WHEN q.expires_at < n.expires_at THEN n.expires_at ELSE q.expires_at END) "
    "RETURN n.id AS id, used + 1 AS used, n.created_at AS created_at, n.expires_at AS expires_at"
)


def write_note(g: Graph, *, id: str, principal: str, name: str, session: str, kind: str, text: str, about: list[str],
               vec: list[float], ttl_ms: int, quota: int, reply_to: str = "", stance: str = "adds",
               private: bool = False) -> dict | None:
    """W-NOTE-1 on agentmem_<tenant> (`g` is client.mem_graph: the mem_<tenant> ACL user, that key only). Returns the
    written note's id, the author's count today and its times, or None when a condition refused it (an unknown id,
    unknown reply target, or the quota): the caller reads which one, read-only."""
    rows = g.query(W_NOTE, {"id": id, "principal": principal, "name": name, "session": session, "kind": kind,
                            "text": text, "about": sorted(set(about)), "vec": [float(v) for v in vec],
                            "ttl_ms": int(ttl_ms), "quota": int(quota), "reply_to": reply_to or "", "stance": stance,
                            "visibility": "private" if private else "shared"},
                   timeout=WRITE_TIMEOUT_MS).result_set
    if not rows:
        return None
    nid, used, created, expires = rows[0]
    return {"id": nid, "used": int(used), "created_at": int(created), "expires_at": int(expires)}


W_HYPOTHESIS = (
    "MATCH (i:Incident {id: $inc}) MATCH (c:Node {id: $cause}) "
    "MERGE (h:Hypothesis:Node {id: $hid}) "
    "ON CREATE SET h.incident_id = $inc, h.cause_id = $cause, h.created_at = timestamp(), h.origin = $origin "
    "SET h.status = $status, h.score = coalesce($score, h.score, 0.0), h.reason = $reason, h.updated_at = timestamp() "
    "MERGE (i)-[:HYPOTHESIZES {k: ''}]->(h) MERGE (h)-[:BLAMES {k: ''}]->(c) "
    "WITH h UNWIND (CASE WHEN size($supports) = 0 THEN [null] ELSE $supports END) AS sid "
    "OPTIONAL MATCH (e:Evidence {id: sid}) "
    "FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (e)-[:SUPPORTS {k: ''}]->(h)) "
    "WITH DISTINCT h UNWIND (CASE WHEN size($refutes) = 0 THEN [null] ELSE $refutes END) AS rid "
    "OPTIONAL MATCH (e2:Evidence {id: rid}) "
    "FOREACH (_ IN CASE WHEN e2 IS NULL THEN [] ELSE [1] END | MERGE (e2)-[:REFUTES {k: ''}]->(h)) "
    "RETURN DISTINCT h.id"
)


def upsert_hypothesis(g: Graph, *, inc: str, hid: str, cause: str, status: str, score: float | None = None,
                      reason: str = "", supports: list[str] | None = None, refutes: list[str] | None = None,
                      origin: str = "model") -> None:
    if status not in ("open", "eliminated", "confirmed", "unresolved"):
        raise WriteError(f"bad hypothesis status {status!r}")
    # score None keeps the HYPOTHESIZE score (the gate and the investigator change a status, never the ranking score;
    # before 2026-10-13 their default 0.0 overwrote it and every suspect read "score 0.00" after the gate)
    r = g.query(W_HYPOTHESIS, {"inc": inc, "hid": hid, "cause": cause, "status": status,
                               "score": None if score is None else float(score),
                               "reason": reason[:1000], "supports": supports or [], "refutes": refutes or [],
                               "origin": origin}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"hypothesis {hid}: incident {inc} or cause {cause} not found")


W_GATE_RUN = (
    "MATCH (i:Incident {id: $inc}) "
    "CREATE (gr:GateRun:Node {id: $gid, incident_id: $inc, cause_id: $cause, passed: $passed, confident: $confident, "
    "checks: $checks, at: timestamp(), attempt: $attempt, origin: $origin}) "
    "MERGE (i)-[:HAS_GATE_RUN {k: $gid}]->(gr) RETURN gr.id"
)


def record_gate_run(g: Graph, *, inc: str, gid: str, cause: str, passed: bool, confident: bool, checks: list[dict],
                    attempt: int, origin: str) -> None:
    r = g.query(W_GATE_RUN, {"inc": inc, "gid": gid, "cause": cause, "passed": bool(passed), "confident": bool(confident),
                             "checks": json.dumps(checks, sort_keys=True, default=str), "attempt": int(attempt),
                             "origin": origin}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"gate run {gid}: incident {inc} not found")


W_DATA_EVIDENCE = (
    "MERGE (run:Run:Node {id: $run}) "
    "CREATE (tc:ToolCall:Node {id: $tc_id, tool: $tool, at: timestamp(), ms: $ms, rows: $rows, served_by: $served_by}) "
    "MERGE (run)-[:HAS_TOOL_CALL {k: $tc_id}]->(tc) "
    "MERGE (e:Evidence:Node {id: $ev_id}) ON CREATE SET e.kind = $kind, e.source = $source, e.transport = $transport, "
    "e.tool = $tool, e.params = $params, e.digest = $digest, e.value = $value, e.baseline = $baseline, "
    "e.ratio = $ratio, e.band = $band, e.summary = $summary, e.payload = $payload, e.anomalous = $anomalous, "
    "e.at = timestamp() "
    "MERGE (tc)-[:PRODUCED_EVIDENCE {k: ''}]->(e) "
    "WITH e UNWIND (CASE WHEN size($about) = 0 THEN [null] ELSE $about END) AS aid "
    "OPTIONAL MATCH (n:Node {id: aid}) "
    "FOREACH (_ IN CASE WHEN n IS NULL THEN [] ELSE [1] END | MERGE (e)-[:ABOUT {k: ''}]->(n)) "
    "RETURN count(n)"
)


def record_external_evidence(g: Graph, *, run: str, tc_id: str, tool: str, ev_id: str, kind: str, source: str,
                             transport: str, params: dict, payload: Any, digest: str, about: list[str], summary: str,
                             ms: float, rows: int, value: float | None = None, baseline: float | None = None,
                             ratio: float | None = None, band: float | None = None, anomalous: bool | None = None) -> int:
    """Evidence observed in a system under observation (warehouse, pipeline, GitHub, simulator) is
    recorded in FalkorDB BEFORE anything uses it. Payload is stored as canonical JSON (truncated)."""
    body = capped_json(payload)
    r = g.query(W_DATA_EVIDENCE, {
        "run": run, "tc_id": tc_id, "tool": tool, "ev_id": ev_id, "kind": kind, "source": source,
        "transport": transport, "params": json.dumps(params, sort_keys=True, default=str), "digest": digest,
        "value": value, "baseline": baseline, "ratio": ratio, "band": band, "summary": summary[:500],
        "payload": body, "about": sorted(set(about)), "ms": round(ms, 2), "rows": rows, "anomalous": anomalous,
        "served_by": f"{source} via {transport}",
    }, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


W_VIOLATES = (
    "MATCH (c:Node {id: $cause}) MATCH (d:Decision {id: $decision}) "
    "MERGE (c)-[v:VIOLATES {k: $inc}]->(d) SET v.at = timestamp(), v.actual = $actual, v.expected = $expected "
    "RETURN count(v)"
)


W_OVERRIDE = (
    "MATCH (d:Decision {id: $decision}) MATCH (c:Node {id: $change}) "
    "MERGE (o:Override:Node {id: $oid}) "
    "ON CREATE SET o.created_at = timestamp() "
    "SET o.change_id = $change, o.decision_id = $decision, o.verdict = $verdict, o.by = $by, o.why = $why, o.actual = $actual, "
    "o.plan_hash = $hash, o.at = timestamp() "
    "MERGE (o)-[:OVERRIDES {k: ''}]->(d) MERGE (o)-[:FOR_CHANGE {k: ''}]->(c) RETURN o.id"
)


def record_override(g: Graph, *, decision: str, change: str, verdict: str, by: str, why: str, plan_hash: str,
                    actual: str) -> str:
    """A reviewer's answer to a contradiction for one change (M15 #3), one query: (:Override)-[:OVERRIDES]->(:Decision)
    and -[:FOR_CHANGE]->(change). One override per (decision, change): a later answer replaces the earlier one. It
    is bound to `actual`, the value the change asserted when it was given (Q-DEC-1's actual_text); `;` in the reason
    becomes `,` so the reason can never be read as another G8 part."""
    if verdict not in ("intentional", "accidental", "discuss"):
        raise WriteError(f"bad override verdict {verdict!r}")
    if not why.strip():
        raise WriteError("an override needs a reason")
    oid = "ovr-" + hashlib.sha256(f"{decision}|{change}".encode()).hexdigest()[:12]
    r = g.query(W_OVERRIDE, {"decision": decision, "change": change, "oid": oid, "verdict": verdict, "by": by,
                             "why": why[:500].replace(";", ","), "hash": plan_hash, "actual": actual},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"decision {decision} or change {change} not found")
    return oid


W_EDGE_PROPOSAL = (
    "MATCH (i:Incident {id: $inc}) MATCH (a:Node {id: $src}) MATCH (b:Node {id: $dst}) "
    "MERGE (p:EdgeProposal:Node {id: $pid}) "
    "ON CREATE SET p.status = 'proposed', p.created_at = timestamp() "
    "SET p.src = $src, p.dst = $dst, p.cap = $cap, p.incident_id = $inc, p.action_id = $aid, p.change_id = $change, "
    "p.plan_hash = $hash, p.why = $why "
    "MERGE (i)-[:HAS_PROPOSAL {k: $pid}]->(p) RETURN p.id, p.status"
)

# one query: the proposal must still be 'proposed' with the same plan hash, its fix still verified APPLIED, the
# approver an active person, and the graph must still have no path from src to dst (re-checked at write time);
# the edge pair is written and the proposal marked approved together. Otherwise nothing.
W_EDGE_APPROVE = (
    "MATCH (p:EdgeProposal {id: $pid}) WHERE p.status = 'proposed' AND p.plan_hash = $hash "
    "MATCH (x:Action) WHERE x.id = p.action_id AND x.verdict = 'APPLIED' "
    "MATCH (who:Person) WHERE who.id = $by AND who.active "
    # (WHERE, not an inline {id: p.src}: right after a MATCH that form errors with an index and is silently empty
    #  without one on 6.0.2, docs/upstream/18)
    "MATCH (a:Node) WHERE a.id = p.src MATCH (b:Node) WHERE b.id = p.dst "
    # (a bound variable inside a MERGE property map is "not found" on 6.0.2: the key is projected first)
    "WITH p, a, b, 'learned:' + p.id AS key "
    "WHERE NOT (a)-[:PROPAGATES_TO*1..8]->(b) "
    "MERGE (a)-[e:PROPAGATES_TO {k: key}]->(b) "
    "SET e.learned = true, e.cap = p.cap, e.w = 1, e.cut_cost = 1.0, e.domain = 'learned', e.via_endpoint = '', "
    "e.from_incident = p.incident_id, e.approved_by = $by, e.cap_why = 'learned from a verified fix: ' + p.why, "
    "e.valid_from = timestamp() "
    "MERGE (b)-[d:DEPENDS_ON {k: key}]->(a) "
    "SET d.learned = true, d.cap = p.cap, d.w = 1, d.cut_cost = 1.0, d.domain = 'learned', d.via_endpoint = '' "
    "SET p.status = 'approved', p.approved_by = $by, p.approved_at = timestamp() "
    "RETURN p.id, e.cap"
)


def propose_edge(g: Graph, *, inc: str, src: str, dst: str, cap: float, aid: str, change: str, why: str) -> dict:
    """A learned failure edge, PROPOSED only (M15 #4): written by memory/edges.py after a verified fix showed that
    `src` reaches `dst` where the graph has no path. Nothing reads a proposal as an edge; approve_edge makes it one."""
    pid = "edge-" + hashlib.sha256(f"{inc}|{src}|{dst}".encode()).hexdigest()[:12]
    plan = json.dumps({"src": src, "dst": dst, "cap": round(float(cap), 6), "inc": inc, "aid": aid, "change": change},
                      sort_keys=True)
    h = hashlib.sha256(plan.encode()).hexdigest()
    r = g.query(W_EDGE_PROPOSAL, {"inc": inc, "src": src, "dst": dst, "cap": round(float(cap), 6), "pid": pid, "aid": aid,
                                  "change": change, "hash": h, "why": why[:300]}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"incident {inc} or nodes {src}/{dst} not found")
    return {"id": pid, "plan_hash": h, "status": r[0][1], "src": src, "dst": dst, "cap": round(float(cap), 6)}


def approve_edge(g: Graph, *, pid: str, plan_hash: str, by: str) -> bool:
    """Approve exactly the proposal reviewed (plan hash) and write the learned edge pair, one query."""
    return bool(g.query(W_EDGE_APPROVE, {"pid": pid, "hash": plan_hash, "by": by}, timeout=WRITE_TIMEOUT_MS).result_set)


def record_violation(g: Graph, *, inc: str, cause: str, decision: str, actual: Any, expected: Any) -> None:
    g.query(W_VIOLATES, {"inc": inc, "cause": cause, "decision": decision, "actual": str(actual),
                         "expected": str(expected)}, timeout=WRITE_TIMEOUT_MS)


# ---------------------------------------------------------------------------------------------
# Scenario injection (engine; used by the simulator/scenario runner, never by the model).
# ---------------------------------------------------------------------------------------------

W_INJECT_CHANGE = (
    "MATCH (t:Node {id: $target}) "
    "MERGE (d:Deploy:Node {id: $id}) SET d.kind = $kind, d.at = $at, d.sha = $sha, d.actor_id = $actor, "
    "d.title = $title, d.tenant = $tenant "
    "MERGE (d)-[c:CHANGED {k: ''}]->(t) SET c.at = $at, c.w = 1, c.cap = 1.0 "
    "RETURN d.id"
)


def inject_change(g: Graph, *, id: str, target: str, at: int, kind: str = "deploy", sha: str = "", actor: str = "",
                  title: str = "", tenant: str = "") -> None:
    r = g.query(W_INJECT_CHANGE, {"id": id, "target": target, "at": int(at), "kind": kind, "sha": sha,
                                  "actor": actor, "title": title, "tenant": tenant}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"inject_change {id}: target {target} not found")


W_ALERT = (
    "MATCH (t:Node {id: $target}) "
    "MERGE (a:Alert:Node {id: $id}) SET a.metric = $metric, a.fired_at = $at, a.severity = $severity, a.target_id = $target "
    "MERGE (a)-[:FIRED_ON {k: ''}]->(t) RETURN a.id"
)


def raise_alert(g: Graph, *, id: str, target: str, metric: str, at: int, severity: str = "page") -> None:
    r = g.query(W_ALERT, {"id": id, "target": target, "metric": metric, "at": int(at), "severity": severity},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"alert {id}: target {target} not found")


W_DEGRADES = (
    "MATCH (i:Incident {id: $inc}) "
    "UNWIND $links AS l "
    "MATCH (a:Alert {id: l.alert}) "
    "MERGE (a)-[d:DEGRADES {k: ''}]->(i) "
    "ON CREATE SET d.how = l.how, d.hops = l.hops, d.evidence = $ev, d.at = timestamp() "
    "RETURN count(d)"
)


def link_alerts(g: Graph, *, inc: str, links: list[dict[str, Any]], evidence: str) -> int:
    """INTAKE's decision, applied in ONE query: each alert DEGRADES the incident it was grouped into (how='opened')
    or attached to (how='attached', hops from the confirmed origin), with the group_alerts evidence id that decided it.
    Idempotent (MERGE): a re-run never links an alert twice to the same incident."""
    if not links:
        return 0
    if any(x.get("how") not in ("opened", "attached") or not x.get("alert") for x in links):
        raise WriteError(f"incident {inc}: every alert link needs an id and how in (opened, attached)")
    rows = [{"alert": x["alert"], "how": x["how"], "hops": x.get("hops")} for x in links]
    r = g.query(W_DEGRADES, {"inc": inc, "links": rows, "ev": evidence}, timeout=WRITE_TIMEOUT_MS).result_set
    n = int(r[0][0]) if r else 0
    if n != len(rows):
        raise WriteError(f"incident {inc}: linked {n}/{len(rows)} alerts (incident or alert missing)")
    return n


W_RUN_INDEX = (
    "MERGE (x:RunIndex:Node {id: $run}) SET x.incident = $inc, x.graph = $graph, x.scenario = $scenario, "
    "x.tenant = $tenant, x.investigator = $investigator, x.started_at = coalesce(x.started_at, timestamp()), "
    "x.outcome = $outcome, x.cause = $cause, x.updated_at = timestamp() RETURN x.id"
)


# The live-LLM spend ledger: ONE graph for every tenant (api._ledger), so the hourly budget is global. A run or a brain
# question first RESERVES an estimate; the check and the reservation are one query, so concurrent callers cannot all
# pass the same remaining budget (FalkorDB runs one write query at a time per graph). Settling replaces the estimate
# with what was actually used (also for failed runs: their partial usage).
W_LLM_RESERVE = (
    "MATCH (x:LlmSpend) WHERE coalesce(x.spent_at, x.reserved_at) >= $since "
    "WITH coalesce(sum(CASE WHEN x.usd IS NULL THEN x.reserved_usd ELSE x.usd END), 0.0) AS used "
    "WHERE used + $est <= $limit "
    "CREATE (r:LlmSpend:Node {id: $id, run: $run, tenant: $tenant, kind: $kind, reserved_usd: $est, "
    "reserved_at: timestamp(), state: 'reserved'}) "
    "RETURN r.id, used"
)

W_LLM_SETTLE = (
    "MATCH (r:LlmSpend {id: $id}) SET r.llm_input_tokens = $tin, r.llm_output_tokens = $tout, r.usd = $usd, "
    "r.spent_at = timestamp(), r.state = $state RETURN r.id"
)


def reserve_llm(ledger: Graph, *, id: str, run: str, tenant: str, kind: str, est_usd: float, limit_usd: float,
                since: int) -> bool:
    """Reserve `est_usd` of the hourly live-LLM budget in one atomic query; False when it would not fit."""
    r = ledger.query(W_LLM_RESERVE, {"id": id, "run": run, "tenant": tenant, "kind": kind, "est": round(float(est_usd), 6),
                                     "limit": float(limit_usd), "since": int(since)}, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r)


def settle_llm(ledger: Graph, *, id: str, tin: int, tout: int, usd: float, state: str = "settled") -> None:
    """What the run or question actually cost (state 'failed' keeps a failed run's partial usage on the ledger)."""
    if state not in ("settled", "failed"):
        raise ValueError(f"bad ledger state {state!r}")
    r = ledger.query(W_LLM_SETTLE, {"id": id, "tin": int(tin), "tout": int(tout), "usd": round(float(usd), 6),
                                    "state": state}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"no LLM reservation {id!r} to settle")


def index_run(audit: Graph, *, run: str, inc: str, graph: str, scenario: str, tenant: str, investigator: str,
              outcome: str = "RUNNING", cause: str | None = None) -> None:
    """The audit graph indexes runs (which graph holds which incident); it survives re-arm."""
    audit.query(W_RUN_INDEX, {"run": run, "inc": inc, "graph": graph, "scenario": scenario, "tenant": tenant,
                              "investigator": investigator, "outcome": outcome, "cause": cause}, timeout=WRITE_TIMEOUT_MS)


W_CHANGE_FACT = (
    "MATCH (c:Node {id: $change}) MATCH (n:Node {id: $about}) "
    "MERGE (f:ChangeFact:Node {id: $fid}) SET f.key = $key, f.value = $value, f.file_id = $file "
    "MERGE (c)-[:ASSERTS {k: ''}]->(f) MERGE (f)-[:ABOUT {k: ''}]->(n) RETURN f.id"
)


W_PR = (
    "MERGE (pr:PR:Node {id: $pr}) SET pr.repo = $repo, pr.number = $number, pr.title = $title, "
    "pr.author_id = $author, pr.head_sha = $sha, pr.ingested_at = timestamp(), pr.tenant = $tenant "
    "WITH pr OPTIONAL MATCH (pr)-[:ASSERTS]->(old:ChangeFact) DETACH DELETE old "
    "WITH DISTINCT pr OPTIONAL MATCH (pr)-[t:TOUCHES]->(:File) DELETE t "
    "WITH DISTINCT pr UNWIND (CASE WHEN size($files) = 0 THEN [null] ELSE $files END) AS fid "
    "OPTIONAL MATCH (f:File {id: fid}) "
    "FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | MERGE (pr)-[:TOUCHES {k: f.id}]->(f)) "
    "RETURN count(f)"
)


def ingest_pr(g: Graph, *, tenant: str, pr: str, repo: str, number: int, title: str, author: str, sha: str,
              files: list[str]) -> int:
    """Ingest a pull request (an observed object) for preflight: the PR node and TOUCHES edges to KNOWN files, in one
    query; facts from a previous push are replaced. Returns how many files the graph knows."""
    r = g.query(W_PR, {"pr": pr, "repo": repo, "number": int(number), "title": title[:300], "author": author,
                       "sha": sha, "files": files, "tenant": tenant}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


def assert_change_fact(g: Graph, *, change: str, key: str, value: Any, about: str, file: str = "") -> None:
    """A typed fact a change asserts (extracted from its diff: pydantic-validated by preflight, injected by scenarios)."""
    fid = f"cf-{change}-{key}"
    r = g.query(W_CHANGE_FACT, {"change": change, "about": about, "fid": fid, "key": key, "value": value, "file": file},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"change fact {fid}: change {change} or target {about} not found")


def build_scratch(g: Graph, *, nodes: list[str], edges: list[tuple[str, str]], rel: str = "DEPENDS_ON") -> int:
    """Project a subgraph into an (empty, tenant-scoped) scratch graph for an algorithm run."""
    check_rel(rel)
    g.query("UNWIND $ids AS i MERGE (:Node {id: i})", {"ids": sorted(set(nodes))}, timeout=WRITE_TIMEOUT_MS)
    r = g.query(f"UNWIND $e AS e MATCH (a:Node {{id: e[0]}}) MATCH (b:Node {{id: e[1]}}) MERGE (a)-[:{rel}]->(b) RETURN count(*)",
                {"e": [list(x) for x in edges]}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


def build_scratch_typed(g: Graph, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], rel: str) -> int:
    """Project nodes (with id + props) and weighted edges into an empty scratch graph (one rel type)."""
    check_rel(rel)
    g.query("UNWIND $n AS r MERGE (x:Node {id: r.id}) SET x += r.props", {"n": [{"id": n["id"], "props": _clean(
        {k: v for k, v in n.items() if k != "id"})} for n in nodes]}, timeout=WRITE_TIMEOUT_MS)
    r = g.query(f"UNWIND $e AS e MATCH (a:Node {{id: e.a}}) MATCH (b:Node {{id: e.b}}) MERGE (a)-[x:{rel}]->(b) SET x.w = e.w RETURN count(x)",
                {"e": edges}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


def perturb_model(g: Graph, *, caps: list[list] | None = None, delete: list[list[str]] | None = None,
                  add: list[list] | None = None, delete_all_from: str | None = None,
                  deactivate: list[str] | None = None, learned: list[dict] | None = None,
                  drop_windows: list[str] | None = None) -> dict:
    """Model-mismatch eval only (evals/mismatch_eval.py, never a tenant graph): make the graph the product reads WRONG
    about the world that already produced its telemetry. `caps` [[u, v, cap]] rewrites PROPAGATES_TO.cap; `delete`
    [[u, v]] removes an edge (and its DEPENDS_ON twin) the world still has; `add` [[u, v, cap]] creates one it has not.
    The "break the graph" playground (playground.py) uses the same writer on its GRAPH.COPY twin, plus
    `delete_all_from` (every failure edge out of one node) and `deactivate` (people set inactive). Each operation is
    one query, atomic on its own."""
    if not g.name.startswith("eval_"):
        raise WriteError(f"refusing to perturb a graph outside an eval clean room: {g.name}")
    out = {"caps": 0, "deleted": 0, "added": 0}
    if caps:
        r = g.query("UNWIND $c AS c MATCH (a:Node {id: c[0]})-[p:PROPAGATES_TO]->(b:Node {id: c[1]}) SET p.cap = c[2] "
                    "RETURN count(p)", {"c": caps}, timeout=WRITE_TIMEOUT_MS).result_set
        out["caps"] = int(r[0][0]) if r else 0
    if delete:
        r = g.query("UNWIND $e AS e MATCH (a:Node {id: e[0]})-[p:PROPAGATES_TO]->(b:Node {id: e[1]}) "
                    "OPTIONAL MATCH (b)-[d:DEPENDS_ON]->(a) DELETE p, d RETURN count(p)", {"e": delete},
                    timeout=WRITE_TIMEOUT_MS).result_set
        out["deleted"] = int(r[0][0]) if r else 0
    if add:
        r = g.query("UNWIND $e AS e MATCH (a:Node {id: e[0]}), (b:Node {id: e[1]}) "
                    "CREATE (a)-[p:PROPAGATES_TO {k: '', w: 1, cap: e[2], rps: 10, cut_cost: 0.1, domain: 'service', "
                    "via_endpoint: '', cap_why: 'model-mismatch eval: an edge the world does not have'}]->(b) "
                    "CREATE (b)-[:DEPENDS_ON {k: '', w: 1, cap: e[2], rps: 10, cut_cost: 0.1, domain: 'service', via_endpoint: ''}]->(a) "
                    "RETURN count(p)", {"e": add}, timeout=WRITE_TIMEOUT_MS).result_set
        out["added"] = int(r[0][0]) if r else 0
    if delete_all_from:
        r = g.query("MATCH (a:Node {id: $id})-[p:PROPAGATES_TO]->(b:Node) OPTIONAL MATCH (b)-[d:DEPENDS_ON]->(a) "
                    "DELETE p, d RETURN count(p)", {"id": delete_all_from}, timeout=WRITE_TIMEOUT_MS).result_set
        out["deleted"] += int(r[0][0]) if r else 0
    if learned:  # learning eval: carry approved learned edges into the next room (the tenant graph keeps them)
        r = g.query("UNWIND $e AS e MATCH (a:Node {id: e.src}), (b:Node {id: e.dst}) "
                    "WITH e, a, b, 'learned:' + e.id AS key "
                    "MERGE (a)-[p:PROPAGATES_TO {k: key}]->(b) SET p += e.props "
                    "MERGE (b)-[d:DEPENDS_ON {k: key}]->(a) SET d += e.props RETURN count(p)",
                    {"e": learned}, timeout=WRITE_TIMEOUT_MS).result_set
        out["learned"] = int(r[0][0]) if r else 0
    if drop_windows:  # robustness eval: telemetry that never arrived for these components
        r = g.query("MATCH (w:MetricWindow) WHERE w.target_id IN $ids AND w.metric = 'error_rate' DETACH DELETE w RETURN count(w)", {"ids": drop_windows},
                    timeout=WRITE_TIMEOUT_MS).result_set
        out["dropped_windows"] = int(r[0][0]) if r else 0
    if deactivate:
        r = g.query("UNWIND $ids AS i MATCH (p:Person {id: i}) SET p.active = false RETURN count(p)", {"ids": deactivate},
                    timeout=WRITE_TIMEOUT_MS).result_set
        out["deactivated"] = int(r[0][0]) if r else 0
    return out


def drop_future_edges(g: Graph, at: int) -> int:
    """An as-of branch (eval clean rooms / what-if branches only): delete every failure edge pair introduced after `at`
    (valid_from > at), so a whole-graph algorithm reads the topology as it was then. One query."""
    if not g.name.startswith(("eval_", "whatif_")):
        raise WriteError(f"refusing to drop edges outside a branch: {g.name}")
    r = g.query("MATCH ()-[p:PROPAGATES_TO|DEPENDS_ON]->() WHERE p.valid_from > $at DELETE p RETURN count(p)",
                {"at": int(at)}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


def remove_flow_edges(g: Graph, edges: list[tuple[str, str]]) -> int:
    """What-if branch only (never a tenant graph): delete PROPAGATES_TO/DEPENDS_ON between the given pairs."""
    if not g.name.startswith("whatif_"):
        raise WriteError(f"refusing to cut edges outside a what-if branch: {g.name}")
    r = g.query("UNWIND $e AS e MATCH (a:Node {id: e[0]})-[p:PROPAGATES_TO]->(b:Node {id: e[1]}) "
                "OPTIONAL MATCH (b)-[d:DEPENDS_ON]->(a) DELETE p, d RETURN count(p)",
                {"e": [list(x) for x in edges]}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


# ---------------------------------------------------------------------------------------------
# Plan → approval → intent → action → verdict → write-back (engine; one atomic query each)
# ---------------------------------------------------------------------------------------------

W_OPTION = (
    "MATCH (i:Incident {id: $inc}) "
    "MERGE (a:Action:Node {id: $aid}) SET a.kind = $kind, a.option = $option, a.enabled = $enabled, a.reason = $reason, "
    "a.target_id = $target, a.preview = $preview, a.future = CASE WHEN $keep_future THEN a.future ELSE $future END, "
    "a.learned = CASE WHEN $keep_future THEN a.learned ELSE $learned END, a.status = coalesce(a.status, 'option'), "
    # the option's place in the plan as an integer (Q-ACT-1 orders by it: an id string sorts act-…-10 before act-…-2)
    "a.rank = CASE WHEN $rank IS NULL THEN a.rank ELSE $rank END, "
    "a.incident_id = $inc "
    "MERGE (i)-[:HAS_PLAN {k: $aid}]->(a) RETURN a.id"
)


def record_option(g: Graph, *, inc: str, aid: str, kind: str, option: str, enabled: bool, reason: str, target: str,
                  preview: dict, future: dict | None = None, keep_future: bool = False, learned: dict | None = None,
                  rank: int | None = None) -> None:
    """One plan option; `future` is its predicted outcome (futures tool), kept so VERIFY can say whether it came true.
    `keep_future`: re-recording the SAME option (propose_data_repair enabling it) keeps the future (and the learned
    annotations) already stored; otherwise the given ones replace them (a rebuilt plan never inherits another option's
    future by slot id). `learned` (M21): what learning said about the option (preference, guideline, suggestion).
    `rank`: its 1-based place in the plan (None keeps the stored one; an option added later without one, a human-named
    fix, sorts after the plan)."""
    g.query(W_OPTION, {"inc": inc, "aid": aid, "kind": kind, "option": option, "enabled": bool(enabled), "reason": reason,
                       "target": target, "preview": json.dumps(preview, sort_keys=True, default=str),
                       "future": json.dumps(future, sort_keys=True, default=str) if future else None,
                       "keep_future": bool(keep_future),
                       "learned": json.dumps(learned, sort_keys=True, default=str) if learned else None,
                       "rank": int(rank) if rank is not None else None},
            timeout=WRITE_TIMEOUT_MS)


W_CHOOSE = (
    "MATCH (i:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) "
    "WHERE a.enabled AND i.stage = 'AWAITING_APPROVAL' AND a.status IN ['option', 'chosen'] "
    # exactly one chosen option per incident: a re-choice voids the previous choice (and its plan hash)
    "FOREACH (o IN [(i)-[:HAS_PLAN]->(x:Action) WHERE x.id <> $aid AND x.status = 'chosen' | x] | "
    "SET o.status = 'option', o.plan_hash = null, o.spec = null) "
    "SET a.status = 'chosen', a.spec = $spec, a.plan_hash = $hash, a.idem = $idem, a.chosen_at = timestamp() "
    "RETURN a.id"
)


def choose_action(g: Graph, *, inc: str, aid: str, spec: dict, plan_hash: str, idem: str) -> bool:
    r = g.query(W_CHOOSE, {"inc": inc, "aid": aid, "spec": json.dumps(spec, sort_keys=True, default=str),
                           "hash": plan_hash, "idem": idem}, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r)


W_APPROVE = (
    "MATCH (i:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) "
    "WHERE a.status = 'chosen' AND a.plan_hash = $hash AND i.stage = 'AWAITING_APPROVAL' "
    # the incident leaves AWAITING_APPROVAL in the SAME query: a second approval (or a re-choice) cannot race it
    "SET i.stage = 'EXECUTE', i.stage_ord = $exec_ord "
    "CREATE (ap:Approval:Node {id: $apid, approver_id: $approver, plan_hash: $hash, choice: a.option, at: timestamp()}) "
    "MERGE (it:Intent {idem: a.idem}) ON CREATE SET it.state = 'PENDING', it.action_type = a.kind, it.args = a.spec, "
    "it.created_at = timestamp(), it.created_by_run = $run, it.created_boot = $boot, it.world = $world, "
    # the execute job holds a lease from the start: the reconciler (Q-INTENT-1) skips the intent while it is leased and
    # its holder's process boot is alive (lease_boot: a restarted API may take a dead boot's lease at once)
    "it.lease_by = $owner, it.lease_boot = CASE WHEN $owner IS NULL THEN null ELSE $boot END, "
    "it.lease_until = CASE WHEN $owner IS NULL THEN null ELSE timestamp() + $lease_ms END "
    "MERGE (ap)-[:APPROVED {k: ''}]->(it) MERGE (i)-[:HAS_INTENT {k: ''}]->(it) "
    "SET a.status = 'approved', a.approval_id = ap.id, ap.via = $via, ap.tg_user = $tg_user, "
    # an approval past an ACTIVE learned guideline (M21) carries the override on the Approval and the Action, in this
    # same query, whoever approved (learning records it only for trusted approvers; this is the incident's own record)
    "ap.override_guideline = $override_guideline, ap.override_reason = $override_reason, "
    "a.override_guideline = $override_guideline, a.override_reason = $override_reason "
    "RETURN it.state AS state, it.created_by_run = $run AS mine, it.idem AS idem"
)


def approve_action(g: Graph, *, inc: str, aid: str, plan_hash: str, approver: str, run: str, owner: str | None = None,
                   lease_ms: int = 0, boot: str | None = None, world: str | None = None, via: str = "web",
                   tg_user: str | None = None, override: dict | None = None) -> dict | None:
    """Two-step approval: only succeeds if the hash matches the CURRENT chosen action and the incident awaits
    approval (else None → HTTP 409). Creates the Approval and the idempotent Intent in the same query; with `owner`
    the new intent is leased to the execute job for `lease_ms` (renewed by `renew_intent`). `override` ({id, reason}:
    the approval goes past an active learned guideline) is written on the Approval and the Action in the same query."""
    apid = f"ap-{aid}-{plan_hash[:8]}"
    from ..agent.state import Stage, ordinal

    r = g.query(W_APPROVE, {"inc": inc, "aid": aid, "hash": plan_hash, "approver": approver, "run": run, "apid": apid,
                            "exec_ord": ordinal(Stage.EXECUTE), "owner": owner, "lease_ms": int(lease_ms),
                            "boot": boot, "world": world, "via": via, "tg_user": tg_user,
                            "override_guideline": (override or {}).get("id"),
                            "override_reason": ((override or {}).get("reason") or None)},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"state": r[0][0], "mine": bool(r[0][1]), "idem": r[0][2], "approval_id": apid} if r else None


W_REJECT = (
    "MATCH (i:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) MATCH (run:Run {id: $run}) "
    # only the CURRENT chosen action, by the plan hash the human saw, while the incident awaits approval
    "WHERE a.status = 'chosen' AND a.plan_hash = $hash AND i.stage = 'AWAITING_APPROVAL' "
    # the option is disabled for good (W_CHOOSE needs enabled, W_APPROVE needs 'chosen'); the incident stays
    # AWAITING_APPROVAL so a human picks another option; the rejection is a stage event in the same query
    # a.reason (why the option was offered or disabled) is kept; the rejection has its own fields
    "SET a.status = 'rejected', a.enabled = false, a.rejected_by = $approver, a.reject_reason = $reason, "
    "a.rejected_at = timestamp() "
    "CREATE (se:StageEvent:Node {id: $se, stage: i.stage, ord: i.stage_ord, at: timestamp(), note: $note}) "
    "MERGE (run)-[:HAS_STAGE {k: $se}]->(se) "
    "RETURN a.id, a.status, a.rejected_at, i.stage"
)


def reject_action(g: Graph, *, inc: str, aid: str, plan_hash: str, approver: str, reason: str, run: str) -> dict | None:
    """Reject the exact chosen action (by its plan hash). One atomic query: the action becomes 'rejected' (disabled,
    with reason, approver and time), a StageEvent records it on the run, and the incident stays AWAITING_APPROVAL.
    None ⇒ not the current chosen action, a stale hash, or not awaiting approval (HTTP 409). No Intent exists before
    approval, so nothing outside the graph is touched."""
    import uuid

    reason = " ".join(reason.split())[:500]
    if len(reason) < 3:
        raise WriteError("a rejection needs a reason (at least 3 characters)")
    se = f"{run}-se-REJECT-{uuid.uuid4().hex[:6]}"
    r = g.query(W_REJECT, {"inc": inc, "aid": aid, "hash": plan_hash, "approver": approver, "reason": reason,
                           "run": run, "se": se, "note": f"option {aid} rejected by {approver}: {reason}"[:500]},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"action_id": r[0][0], "status": r[0][1], "rejected_at": r[0][2], "stage": r[0][3]} if r else None


W_REJECT_EXHAUSTED = (
    "MATCH (i:Incident {id: $inc}) MATCH (run:Run {id: $run}) WHERE i.stage = 'AWAITING_APPROVAL' "
    "OPTIONAL MATCH (i)-[:HAS_PLAN]->(o:Action) WHERE o.enabled = true AND o.status IN ['option', 'chosen'] "
    "WITH i, run, count(o) AS live WHERE live = 0 "
    "SET i.stage = 'UNKNOWN_ESCALATED', i.stage_ord = $ord, i.escalation_reason = $why "
    "CREATE (se:StageEvent:Node {id: $se, stage: 'UNKNOWN_ESCALATED', ord: $ord, at: timestamp(), note: $why}) "
    "MERGE (run)-[:HAS_STAGE {k: $se}]->(se) "
    "RETURN i.stage"
)


def escalate_if_no_option_left(g: Graph, *, inc: str, run: str, why: str) -> bool:
    """After a rejection: when no enabled option is left, the incident needs a human (UNKNOWN_ESCALATED, with the
    reason), instead of AWAITING_APPROVAL forever. One conditional query (a no-op while any option remains)."""
    import uuid

    from ..agent.state import Stage, ordinal

    se = f"{run}-se-ESCALATE-{uuid.uuid4().hex[:6]}"
    r = g.query(W_REJECT_EXHAUSTED, {"inc": inc, "run": run, "ord": ordinal(Stage.UNKNOWN_ESCALATED), "se": se,
                                     "why": why[:500]}, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r)


W_EXECUTED = (
    "MATCH (a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem AND it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner) "
    "SET a.status = 'executed', a.external_ref = $ref, a.executed_at = timestamp(), a.execution = $detail "
    "MERGE (it)-[:EXECUTED {k: ''}]->(a) RETURN a.id"
)


def record_execution(g: Graph, *, aid: str, ref: str, detail: dict, owner: str | None = None) -> None:
    """Record the external change on the action, only while its intent is PENDING and leased by `owner`
    (IntentNotPending otherwise: another writer settled or took over the intent)."""
    r = g.query(W_EXECUTED, {"aid": aid, "ref": ref, "detail": json.dumps(detail, sort_keys=True, default=str),
                             "owner": owner}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise IntentNotPending(f"execution of {aid} not recorded: its intent is no longer PENDING or is leased by another writer")


W_VERDICT = (
    # conditional on the intent, in the same query: a verdict never lands on an intent another writer already settled
    # (COMMITTED / FAILED) or took over (lease), so a reconciler and an in-flight execute cannot overwrite each other
    "MATCH (a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem AND it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner) "
    "SET a.verdict = $verdict, a.explanation = $why, a.channels = $channels, "
    "a.verified_at = timestamp() RETURN a.id"
)


def record_verdict(g: Graph, *, aid: str, verdict: str, why: str, channels: dict, owner: str | None = None) -> None:
    """The 3-valued verdict, written only while the action's intent is PENDING and leased by `owner`
    (IntentNotPending otherwise; nothing is written)."""
    if verdict not in ("APPLIED", "NOT_APPLIED", "UNKNOWN"):
        raise WriteError(f"bad verdict {verdict!r}")
    if verdict == "UNKNOWN" and not why.strip():
        raise WriteError("UNKNOWN requires an explanation")
    r = g.query(W_VERDICT, {"aid": aid, "verdict": verdict, "why": why[:2000], "owner": owner,
                            "channels": json.dumps(channels, sort_keys=True, default=str)}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise IntentNotPending(f"verdict {verdict} for {aid} not written: its intent is no longer PENDING or is leased "
                               "by another writer")


# Intent leases (on the engine clock, with process boot epochs): the execute job leases its intent at approval
# and renews it at every step; the reconciler claims an intent (atomically) before it settles it. Every time comparison
# runs on the ENGINE clock (timestamp(), the clock that wrote created_at and lease_until), never on a caller's clock.
# A lease also names the process boot that holds it (lease_boot): a boot with no recent heartbeat in the audit graph
# ($live, read by the caller through Q-BOOT-LIVE) is dead, and its leases may be taken over at once.
W_INTENT_CLAIM = (
    "MATCH (it:Intent {idem: $idem}) WHERE it.state = 'PENDING' "
    "AND ((it.lease_by IS NULL AND it.created_at < timestamp() - $grace_ms) "
    "OR (it.lease_by IS NOT NULL AND (coalesce(it.lease_until, 0) < timestamp() "
    "OR ($live IS NOT NULL AND it.lease_boot IS NOT NULL AND NOT it.lease_boot IN $live)))) "
    "SET it.lease_by = $owner, it.lease_boot = $boot, it.lease_until = timestamp() + $lease_ms RETURN it.idem"
)
W_INTENT_RENEW = (
    "MATCH (a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem AND it.state = 'PENDING' AND it.lease_by = $owner "
    "SET it.lease_until = timestamp() + $lease_ms RETURN it.idem"
)
W_INTENT_RELEASE = (
    "MATCH (a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem AND it.lease_by = $owner "
    "SET it.lease_until = 0 RETURN it.idem"
)
# A failure BEFORE anything outside the graph was touched: the intent becomes FAILED and the
# incident's stage moves in the SAME query, so a reconciler can never resurrect the incident from a PENDING intent.
W_INTENT_FAIL_UNTOUCHED = (
    "MATCH (i:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) MATCH (run:Run {id: $run}) "
    "MATCH (it:Intent) WHERE it.idem = a.idem AND it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner) "
    "SET it.state = 'FAILED', it.failed_at = timestamp(), it.failure = $why, a.status = 'failed', "
    "i.stage = $stage, i.stage_ord = $ord "
    "CREATE (se:StageEvent:Node {id: $se, stage: $stage, ord: $ord, at: timestamp(), note: $note}) "
    "MERGE (run)-[:HAS_STAGE {k: $se}]->(se) "
    "RETURN it.idem"
)


def claim_intent(g: Graph, *, idem: str, owner: str, lease_ms: int, boot: str, live: list[str] | None,
                 grace_ms: int = 0) -> bool:
    """The reconciler takes a PENDING intent when (engine clock) it was never leased and is older than `grace_ms`, or
    its lease expired, or its lease's boot is not in `live` (None: cannot tell, expiry only). One query; False ⇒ held."""
    return bool(g.query(W_INTENT_CLAIM, {"idem": idem, "owner": owner, "lease_ms": int(lease_ms), "boot": boot,
                                         "live": live, "grace_ms": int(grace_ms)}, timeout=WRITE_TIMEOUT_MS).result_set)


def renew_intent(g: Graph, *, aid: str, owner: str, lease_ms: int) -> bool:
    """Heartbeat: extend this owner's lease while the intent is PENDING (False ⇒ settled or taken over elsewhere)."""
    return bool(g.query(W_INTENT_RENEW, {"aid": aid, "owner": owner, "lease_ms": int(lease_ms)},
                        timeout=WRITE_TIMEOUT_MS).result_set)


def release_intent(g: Graph, *, aid: str, owner: str) -> bool:
    """End this owner's lease now (an intent left PENDING goes to the reconciler without waiting for the lease)."""
    return bool(g.query(W_INTENT_RELEASE, {"aid": aid, "owner": owner}, timeout=WRITE_TIMEOUT_MS).result_set)


def fail_untouched(g: Graph, *, inc: str, run: str, aid: str, owner: str | None, stage: str, ord_: int, why: str,
                   note: str) -> bool:
    """Nothing outside the graph was touched and the action cannot proceed: intent FAILED, action failed and the stage
    moved, in one query, only while the intent is PENDING and leased to `owner` (False ⇒ settled or taken elsewhere)."""
    import uuid

    se = f"{run}-se-{stage}-{ord_}-{uuid.uuid4().hex[:6]}"
    return bool(g.query(W_INTENT_FAIL_UNTOUCHED, {"inc": inc, "run": run, "aid": aid, "owner": owner, "stage": stage,
                                                  "ord": int(ord_), "why": why[:500], "note": note[:500], "se": se},
                        timeout=WRITE_TIMEOUT_MS).result_set)


# Process boots (audit graph): each process that can hold an intent lease heartbeats its boot id; a clean shutdown
# ends it. Liveness is read back through Q-BOOT-LIVE (engine clock).
W_BOOT_BEAT = (
    "MERGE (b:Boot {id: $boot}) ON CREATE SET b.started_at = timestamp(), b.pid = $pid, b.role = $role "
    "SET b.seen_at = timestamp() RETURN b.id"
)
W_BOOT_END = "MATCH (b:Boot {id: $boot}) SET b.ended_at = timestamp() RETURN b.id"
W_BOOT_PRUNE = "MATCH (b:Boot) WHERE b.seen_at < timestamp() - $keep_ms DELETE b RETURN count(b)"


def boot_beat(g: Graph, *, boot: str, pid: int, role: str) -> None:
    g.query(W_BOOT_BEAT, {"boot": boot, "pid": int(pid), "role": role}, timeout=WRITE_TIMEOUT_MS)


def boot_end(g: Graph, *, boot: str) -> None:
    g.query(W_BOOT_END, {"boot": boot}, timeout=WRITE_TIMEOUT_MS)


def boot_prune(g: Graph, *, keep_ms: int) -> None:
    g.query(W_BOOT_PRUNE, {"keep_ms": int(keep_ms)}, timeout=WRITE_TIMEOUT_MS)


# Content epoch: re-arm and an operator's forget stamp the tenant graph; brain scratch copies
# inherit the stamp and are stale once it differs. A scratch copy is also stamped with its birth (engine clock).
W_META_EPOCH = "MATCH (m:Meta) SET m.epoch = $epoch RETURN m.epoch"
W_META_SCRATCH_BORN = "MATCH (m:Meta) SET m.scratch_born = timestamp() RETURN m.scratch_born"


def set_epoch(g: Graph, epoch: str) -> None:
    g.query(W_META_EPOCH, {"epoch": epoch}, timeout=WRITE_TIMEOUT_MS)


def stamp_scratch_born(g: Graph) -> None:
    g.query(W_META_SCRATCH_BORN, {}, timeout=WRITE_TIMEOUT_MS)


W_FLAG_STATE = (
    "MATCH (f:FeatureFlag {id: $flag}) SET f.state = $state, f.changed_by = $why, f.changed_at = timestamp() RETURN f.id"
)


def set_flag_state(g: Graph, *, flag: str, state: str, why: str) -> None:
    """Scenario world injection: a flag changed out of band (e.g. re-enabled after a follow-up fix)."""
    if state not in ("on", "off"):
        raise WriteError(f"flag state {state!r} not in on/off")
    if not g.query(W_FLAG_STATE, {"flag": flag, "state": state, "why": why[:200]}, timeout=WRITE_TIMEOUT_MS).result_set:
        raise WriteError(f"unknown feature flag {flag!r}")


W_AUX_RUN = (
    "MERGE (run:Run:Node {id: $run}) ON CREATE SET run.created_at = timestamp(), run.tenant = $tenant, "
    "run.mode = $mode, run.question = $q RETURN run.id"
)


def open_aux_run(g: Graph, *, run: str, tenant: str, mode: str, text: str) -> None:
    """A brain question, a preflight or an INTAKE round (alert grouping) gets its own Run: its tool calls (and SAW
    edges) are its evidence."""
    if mode not in ("brain", "preflight", "intake"):
        raise WriteError(f"unknown run mode {mode!r}")
    g.query(W_AUX_RUN, {"run": run, "tenant": tenant, "mode": mode, "q": text[:500]}, timeout=WRITE_TIMEOUT_MS)


def open_brain_run(g: Graph, *, run: str, tenant: str, question: str) -> None:
    open_aux_run(g, run=run, tenant=tenant, mode="brain", text=question)


W_WB_TRACKED = (
    "MATCH (inc:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) "
    "MATCH (it:Intent) WHERE it.idem = a.idem AND a.verdict = 'APPLIED' AND a.kind = 'open_issue' AND it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner) "
    "SET it.state = 'COMMITTED', inc.stage = 'UNKNOWN_ESCALATED', inc.stage_ord = $ord, inc.tracked_by = a.external_ref "
    "RETURN inc.stage, it.state"
)


def _intent_lost(g: Graph, aid: str, owner: str | None) -> bool:
    """After an intent-bound write matched nothing: was it because the intent is settled or leased elsewhere? (Read
    on the engine connection, only to name the refusal; the refusal itself was decided inside the write query.)"""
    r = g.ro_query("MATCH (a:Action {id: $aid}) MATCH (it:Intent) WHERE it.idem = a.idem "
                   "RETURN it.state, it.lease_by LIMIT 1", {"aid": aid}, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r) and (r[0][0] != "PENDING" or (owner is not None and r[0][1] != owner))


def write_back_tracked(g: Graph, *, inc: str, aid: str, owner: str | None = None) -> dict:
    """An issue was opened (and found again by its idem key). That hands the incident to humans; it does NOT resolve
    it: no postmortem, no decision, no precedent, nothing learned as a fix."""
    from ..agent.state import Stage, ordinal

    r = g.query(W_WB_TRACKED, {"inc": inc, "aid": aid, "ord": ordinal(Stage.UNKNOWN_ESCALATED), "owner": owner},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        if _intent_lost(g, aid, owner):
            raise IntentNotPending(f"tracked write-back for {inc}/{aid} not written: intent settled or leased elsewhere")
        raise WriteError(f"tracked write-back refused for {inc}/{aid}")
    return {"stage": r[0][0], "intent": r[0][1]}


W_CLAIM = (
    "MERGE (t:Task:Node {id: $task}) ON CREATE SET t.state = 'open', t.created_at = timestamp(), t.kind = $kind, "
    "t.tenant = $tenant, t.run = $run "
    "WITH t WHERE t.state = 'open' "
    "SET t.state = 'claimed', t.owner = $agent, t.claimed_at = timestamp(), t.lease_until = timestamp() + $lease_ms, "
    "t.n = coalesce(t.n, 0) + 1 "
    "MERGE (a:Agent:Node {id: $agent}) ON CREATE SET a.role = $role "
    "MERGE (t)-[c:CLAIMED_BY {k: $agent}]->(a) ON CREATE SET c.at = timestamp() "
    "SET c.n = t.n "
    "RETURN t.owner AS owner, t.n AS n"
)


LEASE_MS = 120_000   # a claim is held this long; past it the reaper may reopen the task (a crashed worker's claim)


def claim_epoch(g: Graph, *, task: str, agent: str, role: str = "worker", kind: str = "work", tenant: str = "",
                lease_ms: int = LEASE_MS, run: str = "") -> int:
    """W-CLAIM-1: atomic conditional claim in ONE query (open → claimed, with a lease on the engine clock). Returns the
    claim's epoch `t.n` (1 for the first claim, +1 after each reap and re-claim) for the single winner, 0 otherwise.
    A completion that passes its epoch is refused once the task has been reaped and claimed again (fencing), even when
    the new claimant has the same agent id."""
    r = g.query(W_CLAIM, {"task": task, "agent": agent, "role": role, "kind": kind, "tenant": tenant,
                          "lease_ms": int(lease_ms), "run": run}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][1]) if r and r[0][0] == agent else 0


def claim_task(g: Graph, *, task: str, agent: str, role: str = "worker", kind: str = "work", tenant: str = "",
               lease_ms: int = LEASE_MS, run: str = "") -> bool:
    """W-CLAIM-1 as a yes/no (see claim_epoch). True only for the single winner."""
    return claim_epoch(g, task=task, agent=agent, role=role, kind=kind, tenant=tenant, lease_ms=lease_ms, run=run) > 0


W_RENEW = (
    "MATCH (t:Task {id: $task}) WHERE t.state = 'claimed' AND t.owner = $agent AND t.n = $n "
    "SET t.lease_until = timestamp() + $lease_ms RETURN t.id"
)


def renew_task(g: Graph, *, task: str, agent: str, n: int, lease_ms: int = LEASE_MS) -> bool:
    """Extend a held claim's lease (one conditional query; the engine clock). False once it was reaped or taken."""
    return bool(g.query(W_RENEW, {"task": task, "agent": agent, "n": int(n), "lease_ms": int(lease_ms)},
                        timeout=WRITE_TIMEOUT_MS).result_set)


W_REAP = (
    "MATCH (t:Task) WHERE t.run = $run AND t.kind = $kind AND t.state = 'claimed' AND t.lease_until IS NOT NULL "
    "AND t.lease_until < timestamp() "
    "WITH t ORDER BY t.lease_until LIMIT 100 "
    "SET t.state = 'open', t.reaped_from = t.owner, t.owner = null, t.reaped_at = timestamp(), "
    "t.reaps = coalesce(t.reaps, 0) + 1 "
    "RETURN t.id"
)


def reap_expired(g: Graph, *, run: str, kind: str) -> list[str]:
    """W-REAP-1: reopen the claims of ONE run and kind whose lease ran out on the engine clock (one query; never
    another run's tasks). A reopened task can be claimed again at epoch n+1; the old owner's late completion then
    writes nothing, because completion requires `state = 'claimed' AND owner = me AND n = my epoch`. Crew step
    records are never reaped (they are records, not locks)."""
    if not run or kind == "crew":
        raise WriteError("reap_expired needs a run, and never reaps crew records")
    return [r[0] for r in g.query(W_REAP, {"run": run, "kind": kind}, timeout=WRITE_TIMEOUT_MS).result_set]


W_CREW_DONE = (
    "MATCH (t:Task {id: $task}) WHERE t.state = 'claimed' AND t.owner = $agent AND t.n = $n "
    "MERGE (run:Run:Node {id: $run}) ON CREATE SET run.created_at = timestamp() "
    "SET t.state = $state, t.done_at = timestamp(), t.role = $role, t.stage = $stage, t.stages = $stages, t.run = $run, "
    "t.summary = $summary, t.status = $state, t.result = $state "
    "MERGE (run)-[:HAS_TASK {k: $task}]->(t) "
    "WITH t "
    "OPTIONAL MATCH (prev:Task {id: $prev}) WHERE prev.run = $run "
    "FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | MERGE (prev)-[:NEXT {k: ''}]->(t)) "
    "WITH DISTINCT t "
    "UNWIND (CASE WHEN size($tcs) = 0 THEN [null] ELSE $tcs END) AS tcid "
    "OPTIONAL MATCH (tc:ToolCall {id: tcid}) "
    "FOREACH (_ IN CASE WHEN tc IS NULL THEN [] ELSE [1] END | MERGE (t)-[:MADE {k: ''}]->(tc)) "
    "RETURN t.id, count(tc)"
)


def complete_crew_step(g: Graph, *, task: str, agent: str, n: int, run: str, role: str, stage: str, stages: list[str],
                       summary: str, tool_calls: list[str], prev: str | None = None, failed: bool = False) -> bool:
    """W-CREW-1: a crew step's record is closed in ONE query: its Task becomes done (or failed), hangs off the Run,
    links the tool calls its agent MADE, and follows the run's previous step (NEXT). Only the claim's owner, at its
    epoch, can close it. HANDED_OFF_TO stays reserved for ownership transfers of one task (W-HANDOFF)."""
    r = g.query(W_CREW_DONE, {
        "task": task, "agent": agent, "n": int(n), "run": run, "role": role, "stage": stage, "stages": stages,
        "summary": summary[:600], "state": "failed" if failed else "done", "tcs": sorted(set(tool_calls))[:400],
        "prev": prev or "",
    }, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r)


W_HANDOFF = (
    "MATCH (t:Task {id: $task}) WHERE t.state = 'claimed' AND t.owner = $from "
    "MATCH (a:Agent {id: $from}) "
    "MERGE (b:Agent:Node {id: $to}) ON CREATE SET b.role = $role "
    "SET t.owner = $to, t.handed_at = timestamp() "
    "MERGE (a)-[h:HANDED_OFF_TO {k: $task}]->(b) ON CREATE SET h.at = timestamp() "
    "MERGE (t)-[c:CLAIMED_BY {k: $to}]->(b) ON CREATE SET c.at = timestamp() SET c.n = t.n "
    "RETURN t.owner"
)


def hand_off(g: Graph, *, task: str, from_agent: str, to_agent: str, role: str = "worker") -> bool:
    """Only the current owner can hand a task off (one query; a stale owner's handoff is a no-op)."""
    r = g.query(W_HANDOFF, {"task": task, "from": from_agent, "to": to_agent, "role": role}, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r) and r[0][0] == to_agent


W_TASK_DONE = (
    "MATCH (t:Task {id: $task}) WHERE t.state = 'claimed' AND t.owner = $agent "
    "SET t.state = 'done', t.done_at = timestamp(), t.result = $result RETURN t.id"
)


def complete_task(g: Graph, *, task: str, agent: str, result: str = "") -> bool:
    return bool(g.query(W_TASK_DONE, {"task": task, "agent": agent, "result": result[:500]}, timeout=WRITE_TIMEOUT_MS).result_set)


W_SPECIALIST_DONE = (
    "MATCH (t:Task {id: $task}) WHERE t.state = 'claimed' AND t.owner = $agent AND ($n = 0 OR t.n = $n) "
    "MERGE (run:Run:Node {id: $run}) ON CREATE SET run.created_at = timestamp() "
    "SET t.state = 'done', t.done_at = timestamp(), t.role = $role, t.status = $status, t.result = $status, "
    "t.run = $run, t.report = $report, t.unknowns = $unknowns, t.limits = $limits "
    "MERGE (run)-[:HAS_TASK {k: $task}]->(t) "
    "WITH t "
    "UNWIND (CASE WHEN size($names) = 0 THEN [null] ELSE $names END) AS nid "
    "OPTIONAL MATCH (n:Node {id: nid}) "
    "FOREACH (_ IN CASE WHEN n IS NULL OR n:Evidence OR n:ToolCall THEN [] ELSE [1] END | MERGE (t)-[:NAMES {k: ''}]->(n)) "
    "WITH DISTINCT t "
    "UNWIND (CASE WHEN size($cites) = 0 THEN [null] ELSE $cites END) AS eid "
    "OPTIONAL MATCH (e:Evidence {id: eid}) "
    "FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (t)-[:CITES {k: ''}]->(e)) "
    "WITH DISTINCT t "
    "UNWIND (CASE WHEN size($tcs) = 0 THEN [null] ELSE $tcs END) AS tcid "
    "OPTIONAL MATCH (tc:ToolCall {id: tcid}) "
    "FOREACH (_ IN CASE WHEN tc IS NULL THEN [] ELSE [1] END | MERGE (t)-[:MADE {k: ''}]->(tc)) "
    "RETURN t.id, count(tc)"
)


def complete_specialist_task(g: Graph, *, task: str, agent: str, run: str, role: str, status: str, names: list[str],
                             cites: list[str], report: dict, unknowns: list[str] | None = None,
                             limits: list[str] | None = None, tool_calls: list[str] | None = None, n: int = 0) -> bool:
    """A specialist's validated contract lands on its claimed work item in ONE query: the Task becomes
    done, hangs off the Run (HAS_TASK), NAMES the suspects the contract names and CITES the evidence it cites. Only the
    claim's owner can complete it (a stale or losing dispatch writes nothing). Gate G7 reads these edges (Q-GATE-CORR)."""
    if status not in ("complete", "insufficient"):
        raise WriteError(f"bad specialist status {status!r}")
    r = g.query(W_SPECIALIST_DONE, {
        "task": task, "agent": agent, "run": run, "role": role, "status": status,
        "names": sorted(set(names)), "cites": sorted(set(cites)),
        "report": capped_json(report),
        "unknowns": [u[:300] for u in (unknowns or [])][:20], "limits": [x[:300] for x in (limits or [])][:20],
        "tcs": sorted(set(tool_calls or []))[:400], "n": int(n),
    }, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r)


W_REFUSED_CALL = (
    "MERGE (run:Run:Node {id: $run}) ON CREATE SET run.created_at = timestamp(), run.tenant = $tenant "
    "CREATE (tc:ToolCall:Node {id: $tc_id, tool: $tool, template: '', at: timestamp(), ms: 0.0, rows: 0, "
    "truncated: false, served_by: 'refused', refused: true, stage: $stage, error: $error}) "
    "MERGE (run)-[:HAS_TOOL_CALL {k: $tc_id}]->(tc) "
    "RETURN tc.id"
)


def record_refused_call(g: Graph, *, run: str, tenant: str, tc_id: str, tool: str, stage: str, error: str) -> None:
    """A tool call refused by the per-stage whitelist is logged in the run like any other call, with
    refused=true and no evidence: the trace shows what the model tried and why it was stopped."""
    g.query(W_REFUSED_CALL, {"run": run, "tenant": tenant, "tc_id": tc_id, "tool": tool[:80], "stage": stage,
                             "error": error[:300]}, timeout=WRITE_TIMEOUT_MS)


W_COUNTER = "MERGE (c:Task:Node {id: $id}) ON CREATE SET c.n = 0, c.state = 'counter' SET c.n = c.n + 1 RETURN c.n"


def bump_counter(g: Graph, *, counter: str) -> int:
    """Lost-update probe for S13: read-modify-write inside one query."""
    return int(g.query(W_COUNTER, {"id": counter}, timeout=WRITE_TIMEOUT_MS).result_set[0][0])


W_TURN = (
    # a session id never shares its id with another node (Node.id is not unique across labels): refused in the query
    "OPTIONAL MATCH (x:Node {id: $session}) WHERE NOT x:Session "
    "WITH count(x) AS clash WHERE clash = 0 "
    "MERGE (s:Session:Node {id: $session}) ON CREATE SET s.user = $user, s.created_at = timestamp(), s.seq = 0, "
    "s.tenant = $tenant "
    "WITH s WHERE s.user = $user "
    "SET s.seq = s.seq + 1, s.updated_at = timestamp() "
    "CREATE (t:Turn:Node {id: $session + '-t' + toString(s.seq), seq: s.seq, role: $role, text: $text, at: timestamp(), "
    "refs: $refs}) "
    "MERGE (s)-[:HAS_TURN {k: t.id}]->(t) "
    "RETURN t.id, t.seq"
)


def append_turn(g: Graph, *, session: str, user: str, role: str, text: str, refs: list[str] | None = None,
                tenant: str = "") -> dict:
    """Persistent session history (T2): one turn, numbered atomically within its session (one query). A session
    belongs to one user; another user's write to it is refused. Session ids are server-issued (`sess-…`, SESSION_RE)
    and never collide with another node's id (checked in the same query)."""
    if role not in ("user", "assistant"):
        raise WriteError(f"bad role {role!r}")
    if not SESSION_RE.fullmatch(session or ""):
        raise SessionError(f"session id {session!r} is not server-issued (sess-…)")
    r = g.query(W_TURN, {"session": session, "user": user, "role": role, "text": text[:4000], "refs": refs or [],
                         "tenant": tenant}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise SessionError(f"session {session} belongs to another user or collides with an existing node id")
    return {"turn": r[0][0], "seq": int(r[0][1])}


W_MEM_FORGET = (
    "MATCH (doc:Doc {id: $doc}) "
    "OPTIONAL MATCH (doc)-[:PRODUCED]->(n) WHERE n.id IN $owned "
    "WITH doc, collect(DISTINCT n) AS owned "
    # re-checked inside the delete (TOCTOU): every approved id is still produced by this doc and by NO other doc; if
    # another doc produced one of them since the dry run, nothing is deleted (the receipt no longer matches)
    "WITH doc, owned, [x IN owned WHERE size([(x)<-[:PRODUCED]-(d:Doc) | d]) = 1] AS sole "
    "WHERE size(owned) = size($owned) AND size(sole) = size($owned) "
    "WITH doc, owned, reduce(r = 0, x IN owned | r + size([(x)-[e]-() | e])) AS rels "
    "UNWIND (owned + [doc]) AS gone "
    "DETACH DELETE gone "
    "RETURN size(owned) AS nodes, rels"
)


def forget_doc(g: Graph, *, doc: str, owned: list[str]) -> dict:
    """W-MEM-3: delete a Doc and ONLY the nodes it alone produced (the ids the approved dry run listed), in one query.
    Refused (nothing deleted) when the doc is gone or any listed node is no longer produced by this doc alone."""
    owned = sorted(set(owned))
    r = g.query(W_MEM_FORGET, {"doc": doc, "owned": owned}, timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"forget refused: document {doc} not found, or a node it alone produced at the dry run now has "
                         "another producer (nothing deleted; run the dry run again)")
    return {"nodes": int(r[0][0]), "relationships": int(r[0][1])}


W_TURN_REDACT = (
    # turns whose answer cited a forgotten id: the text is replaced and the forgotten ids are dropped from refs
    "MATCH (t:Turn) WHERE any(r IN coalesce(t.refs, []) WHERE r IN $ids) "
    "SET t.text = $note, t.refs = [r IN t.refs WHERE NOT r IN $ids], t.redacted_at = timestamp() "
    "RETURN count(t)"
)


def redact_turns(g: Graph, *, ids: list[str], note: str) -> int:
    """After a forget: redact every session turn that cited a forgotten id (one query). A turn that quotes the
    forgotten text without citing an id cannot be found this way and survives (docs/HONEST_LIMITS.md)."""
    if not ids:
        return 0
    r = g.query(W_TURN_REDACT, {"ids": sorted(set(ids)), "note": note[:300]}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


W_RUN_TOKEN = "MATCH (run:Run {id: $run}) SET run.token_sha = $sha RETURN run.id"


def set_run_token(g: Graph, *, run: str, token_sha: str) -> None:
    """Public demo: only the holder of this run's token may choose/approve its actions (the hash is stored, never the token)."""
    if not g.query(W_RUN_TOKEN, {"run": run, "sha": token_sha}, timeout=WRITE_TIMEOUT_MS).result_set:
        raise WriteError(f"run {run} not found")


W_RECALL = (
    "MATCH (cur:Incident {id: $inc}) "
    "UNWIND $rows AS r MATCH (p:Incident {id: r.id}) WHERE p.id <> cur.id "
    "MERGE (cur)-[e:RECALLED {k: r.id}]->(p) SET e.similarity = r.similarity, e.recency = r.recency, "
    "e.salience = r.salience, e.at = timestamp(), e.shared = r.shared "
    "SET p.last_used = timestamp() "
    "RETURN count(e)"
)


def record_recall(g: Graph, *, inc: str, rows: list[dict[str, Any]]) -> int:
    """RECALLED edges from the current incident to the structurally confirmed precedents it recalled
    (and touch last_used: recall is a use, so decay is slowed by being useful)."""
    if not rows:
        return 0
    rows = [{"id": r["id"], "similarity": float(r["similarity"]), "recency": float(r.get("recency") or 0.0),
             "salience": float(r.get("salience") or 1.0), "shared": [str(x) for x in r.get("shared") or []]} for r in rows]
    return int(g.query(W_RECALL, {"inc": inc, "rows": rows}, timeout=WRITE_TIMEOUT_MS).result_set[0][0])


W_MEM_CONSOLIDATE = (
    "MATCH (i:Incident)-[:RESOLVED_BY]->(a:Action) "
    "WHERE i.id IN $incidents AND a.verdict = 'APPLIED' AND a.kind = $kind AND a.target_id = $target "
    "MATCH (pm:Postmortem)-[:DOCUMENTS]->(i) "
    "MATCH (i)-[:HAS_SYMPTOM]->(s:Symptom) "
    "WITH collect(DISTINCT pm) AS pms, collect(DISTINCT s) AS syms, count(DISTINCT i) AS n "
    "WHERE n >= $min "
    "MERGE (r:Runbook:Node {id: $rid}) "
    "ON CREATE SET r.valid_from = timestamp(), r.created_at = timestamp() "
    "SET r.title = $title, r.body = $body, r.source = 'derived', r.steps = [$kind + ': ' + $target], "
    "r.support_count = n, r.salience = 1.0, r.updated_at = timestamp(), r.tenant = $tenant "
    "FOREACH (pm IN pms | MERGE (r)-[:DERIVED_FROM {k: pm.id}]->(pm)) "
    "FOREACH (s IN syms | MERGE (r)-[:RUNBOOK_FOR {k: s.id}]->(s)) "
    "RETURN r.id, n, size(pms)"
)


def consolidate_family(g: Graph, *, tenant: str, rid: str, incidents: list[str], kind: str, target: str, min_support: int,
                       title: str, body: str) -> dict | None:
    """W-MEM-2: a derived Runbook from APPLIED actions only (≥ min_support incidents), DERIVED_FROM their
    postmortems and RUNBOOK_FOR their symptoms, in one query. None when support is below the threshold."""
    r = g.query(W_MEM_CONSOLIDATE, {"incidents": incidents, "kind": kind, "target": target, "min": int(min_support),
                                    "rid": rid, "title": title[:200], "body": body[:2000], "tenant": tenant},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"runbook": r[0][0], "support": int(r[0][1]), "postmortems": int(r[0][2])} if r else None


W_MEM_DECAY = (
    "MATCH (i:Incident) WHERE i.last_used IS NOT NULL AND i.salience_base IS NOT NULL "
    "WITH i, size([(i)-[:RESOLVED_BY]->(a:Action) WHERE a.verdict = 'APPLIED' | a]) > 0 AS pinned "
    "SET i.salience = CASE WHEN pinned THEN i.salience_base "
    "ELSE i.salience_base * exp(-0.6931471805599453 * toFloat($now - i.last_used) / $half_life_ms) END "
    "RETURN sum(CASE WHEN pinned THEN 1 ELSE 0 END) AS pinned, sum(CASE WHEN pinned THEN 0 ELSE 1 END) AS decayed"
)


def decay(g: Graph, *, now_ms: int, half_life_days: float) -> dict:
    """W-MEM-1: salience halves every half-life since last use; incidents that led to an APPLIED fix never decay."""
    r = g.query(W_MEM_DECAY, {"now": int(now_ms), "half_life_ms": float(half_life_days) * 86_400_000},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"pinned": int(r[0][0] or 0), "decayed": int(r[0][1] or 0)} if r else {"pinned": 0, "decayed": 0}


W_WB_1 = (
    "MATCH (inc:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) MATCH (cause:Node {id: $cause}) "
    "MATCH (it:Intent) WHERE it.idem = a.idem AND a.verdict = 'APPLIED' AND it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner) "
    "SET inc.stage = 'WRITEBACK', inc.stage_ord = $wb_ord, inc.resolved_at = timestamp(), inc.confident = $confident, "
    "it.state = 'COMMITTED' "
    "MERGE (pm:Postmortem:Node {id: $pmid}) SET pm.summary = $summary, pm.url = $pmurl, pm.incident_id = $inc, "
    "pm.at = timestamp() "
    "MERGE (dec:Decision:Node {id: $did}) SET dec.title = $dtitle, dec.status = 'active', dec.decided_at = timestamp(), "
    "dec.kind = 'incident' "
    "MERGE (cause)-[:CAUSED {k: ''}]->(inc) "
    "MERGE (inc)-[:RESOLVED_BY {k: $aid}]->(a) "
    "MERGE (pm)-[:DOCUMENTS {k: ''}]->(inc) "
    "MERGE (dec)-[:CITES {k: $pmid}]->(pm) "
    "MERGE (inc)-[:AFFECTED {k: 'cause:' + cause.id}]->(cause) "
    "FOREACH (pid IN $precedents | MERGE (p:Incident:Node {id: pid}) MERGE (p)-[:PRECEDENT_FOR {k: ''}]->(inc)) "
    "FOREACH (fid IN CASE WHEN a.kind = 'flip_flag' THEN [a.target_id] ELSE [] END | "
    "MERGE (f:FeatureFlag:Node {id: fid}) SET f.state = 'off', f.changed_by = a.id, f.changed_at = timestamp()) "
    "RETURN inc.id, pm.id, dec.id"
)


def write_back_applied(g: Graph, *, inc: str, cause: str, aid: str, confident: bool, summary: str, pmurl: str,
                       precedents: list[str], owner: str | None = None) -> dict:
    """W-WB-1: success write-back in ONE query, only when the action's verdict is APPLIED (else nothing is written)."""
    pmid, did = f"pm-{inc}", f"DEC-{inc}"
    from ..agent.state import Stage, ordinal

    r = g.query(W_WB_1, {"wb_ord": ordinal(Stage.WRITEBACK), "inc": inc, "cause": cause, "aid": aid, "confident": bool(confident), "pmid": pmid,
                         "summary": summary[:2000], "pmurl": pmurl, "did": did,
                         "dtitle": f"Remediation of {inc}: {summary[:120]}", "precedents": precedents, "owner": owner},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        if _intent_lost(g, aid, owner):
            raise IntentNotPending(f"write-back for {inc}/{aid} not written: intent settled or leased elsewhere")
        raise WriteError(f"write-back refused for {inc}: action {aid} is not APPLIED (or ids missing)")
    return {"incident": r[0][0], "postmortem": r[0][1], "decision": r[0][2]}


W_WB_2 = (
    "MATCH (inc:Incident {id: $inc})-[:HAS_PLAN]->(a:Action {id: $aid}) "
    "MATCH (it:Intent) WHERE it.idem = a.idem AND a.verdict IN ['NOT_APPLIED', 'UNKNOWN'] AND it.state = 'PENDING' AND ($owner IS NULL OR it.lease_by = $owner) "
    "SET inc.stage = $stage, inc.stage_ord = $ord, "
    "it.state = CASE a.verdict WHEN 'NOT_APPLIED' THEN 'FAILED' ELSE it.state END, "
    "a.status = CASE a.verdict WHEN 'NOT_APPLIED' THEN 'failed' ELSE a.status END, "
    "a.enabled = CASE a.verdict WHEN 'NOT_APPLIED' THEN false ELSE a.enabled END "
    # the attempt is memory too (ATTEMPTED, never RESOLVED_BY): fix history shows what did NOT work
    "MERGE (inc)-[:ATTEMPTED {k: $aid}]->(a) "
    "RETURN inc.stage, it.state"
)


def write_back_not_applied(g: Graph, *, inc: str, aid: str, stage: str, owner: str | None = None) -> dict:
    """W-WB-2: NOT_APPLIED / UNKNOWN: no success, no postmortem, no decision. NOT_APPLIED: the intent FAILS, the
    option is disabled and the incident goes back to AWAITING_APPROVAL (a human chooses again). UNKNOWN: the
    intent stays PENDING for the reconciler and the incident is escalated."""
    from ..agent.state import Stage, ordinal

    r = g.query(W_WB_2, {"inc": inc, "aid": aid, "stage": stage, "ord": ordinal(Stage(stage)), "owner": owner},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        if _intent_lost(g, aid, owner):
            raise IntentNotPending(f"write-back (not applied) for {inc}/{aid} not written: intent settled or leased elsewhere")
        raise WriteError(f"write-back (not applied) refused for {inc}/{aid}")
    return {"stage": r[0][0], "intent": r[0][1]}


# ---------------------------------------------------------------------------------------------
# On-call (M19): pages, acks, escalation, standing contracts
# and hand-offs. One atomic query each; every condition that makes a write safe (still unacked, still active, uses
# below max, not expired) is checked inside the same query that writes. `$now` is the caller's wall clock (epoch ms):
# the escalation tick and the contract checks compare against the same clock the page or grant was written with.
# ---------------------------------------------------------------------------------------------
PAGE_OPEN = ("sent", "delivery_failed")       # a human still has to acknowledge it
PAGE_KINDS = ("page", "escalation", "report", "contract_notice")

W_ESCALATION_ORDER = (
    # the escalation tree's edges in Q-ORG-MSF order (strongest tie first) → one ESCALATES_TO edge per person, ranked by
    # the first tree edge that names them (computed here, in Cypher, from the algo.MSF result the caller passes)
    "MATCH (i:Incident {id: $inc}) "
    "UNWIND range(0, size($edges) - 1) AS k "
    "UNWIND [$edges[k].from, $edges[k].to] AS pid "
    "WITH i, pid, min(k) AS rank, max($edges[k].w) AS w "
    "MATCH (p:Person {id: pid}) "
    "MERGE (i)-[r:ESCALATES_TO {k: pid}]->(p) SET r.rank = rank, r.w = w, r.via = $via "
    "RETURN count(r)"
)

W_ESCALATION_FALLBACK = (
    # no tree edge (one responder, no ties): the people in the order the caller's graph tool ranked them
    "MATCH (i:Incident {id: $inc}) "
    "UNWIND range(0, size($people) - 1) AS k "
    "WITH i, k, $people[k] AS pid "
    "MATCH (p:Person {id: pid}) "
    "MERGE (i)-[r:ESCALATES_TO {k: pid}]->(p) SET r.rank = $offset + k, r.w = 0.0, r.via = $via "
    "RETURN count(r)"
)


def record_escalation_order(g: Graph, *, inc: str, edges: list[dict], fallback: list[str], via: str) -> int:
    """The incident's escalation order (Q-PAGE-NEXT reads it): the algo.MSF escalation tree's edges ranked in Cypher;
    when the tree has no edge, the fallback people (who_fixes order) instead. Idempotent (MERGE per person)."""
    n = 0
    if edges:
        rows = [{"from": str(e["from"]), "to": str(e["to"]), "w": float(e.get("w") or 0.0)} for e in edges]
        r = g.query(W_ESCALATION_ORDER, {"inc": inc, "edges": rows, "via": via}, timeout=WRITE_TIMEOUT_MS).result_set
        n = int(r[0][0]) if r else 0
    if n == 0 and fallback:
        r = g.query(W_ESCALATION_FALLBACK, {"inc": inc, "people": [str(p) for p in fallback], "offset": 0,
                                            "via": "who_fixes"}, timeout=WRITE_TIMEOUT_MS).result_set
        n = int(r[0][0]) if r else 0
    return n


W_PAGE_CREATE = (
    "MATCH (i:Incident {id: $inc}) "
    "UNWIND $pages AS x "
    "MATCH (p:Person {id: x.person}) "
    "MERGE (pg:Page:Node {id: x.id}) "
    "ON CREATE SET pg.tenant = $tenant, pg.incident = $inc, pg.kind = x.kind, pg.urgency = x.urgency, pg.sent_at = $now, "
    "pg.ack_due_at = $now + x.window_ms, pg.status = 'sent', pg.attempt = x.attempt, pg.detail = x.detail, "
    "pg.deep_link = x.deep_link, pg.channel = 'in_app', pg.channels = ['in_app'], pg.team = x.team, pg.reason = x.reason, "
    "pg.evidence = x.evidence, pg.person = p.id, pg.batch = $batch "
    "MERGE (pg)-[:PAGES {k: ''}]->(p) "
    "MERGE (pg)-[:FOR {k: ''}]->(i) "
    "RETURN pg.id, pg.status, pg.batch = $batch AS fresh"
)


def create_pages(g: Graph, *, tenant: str, inc: str, pages: list[dict], now: int) -> list[dict]:
    """Pages for one incident, in one query (MERGE by page id: a retried run, or a reconciler settling the same outcome
    again, never pages twice). Each page dict: id, person, kind, urgency, window_ms, attempt, detail, deep_link, team,
    reason, evidence. Returns [{id, fresh}] for every page that exists now (`fresh`: created by THIS call, so only those
    are delivered); a person or incident missing from the graph writes nothing for it (the caller compares)."""
    import uuid

    for x in pages:
        if x["kind"] not in PAGE_KINDS:
            raise WriteError(f"bad page kind {x['kind']!r}")
    rows = [{"id": x["id"], "person": x["person"], "kind": x["kind"], "urgency": x["urgency"],
             "window_ms": int(x["window_ms"]), "attempt": int(x.get("attempt") or 1), "detail": str(x.get("detail") or "")[:1000],
             "deep_link": str(x.get("deep_link") or ""), "team": x.get("team") or "", "reason": str(x.get("reason") or "")[:500],
             "evidence": x.get("evidence") or ""} for x in pages]
    if not rows:
        return []
    r = g.query(W_PAGE_CREATE, {"tenant": tenant, "inc": inc, "pages": rows, "now": int(now), "batch": uuid.uuid4().hex},
                timeout=WRITE_TIMEOUT_MS).result_set
    return [{"id": row[0], "fresh": bool(row[2])} for row in r]


W_PAGE_NOTE = (
    # an informational page with no incident in this graph (a hand-off report): PAGES only
    "MATCH (p:Person {id: $person}) "
    "MERGE (pg:Page:Node {id: $id}) "
    "ON CREATE SET pg.tenant = $tenant, pg.incident = $inc, pg.kind = $kind, pg.urgency = 'normal', pg.sent_at = $now, "
    "pg.ack_due_at = $now, pg.status = 'sent', pg.attempt = 1, pg.detail = $detail, pg.deep_link = $deep_link, "
    "pg.channel = 'in_app', pg.channels = ['in_app'], pg.team = '', pg.reason = $reason, pg.person = p.id "
    "MERGE (pg)-[:PAGES {k: ''}]->(p) "
    "RETURN pg.id"
)


def create_note_page(g: Graph, *, tenant: str, pid: str, person: str, kind: str, detail: str, reason: str, now: int,
                     inc: str = "", deep_link: str = "") -> str | None:
    if kind not in ("report", "contract_notice"):
        raise WriteError(f"a note page is a report or a contract notice, not {kind!r}")
    r = g.query(W_PAGE_NOTE, {"tenant": tenant, "id": pid, "person": person, "kind": kind, "detail": detail[:2000],
                              "reason": reason[:500], "now": int(now), "inc": inc, "deep_link": deep_link},
                timeout=WRITE_TIMEOUT_MS).result_set
    return r[0][0] if r else None


W_PAGE_DELIVERY = (
    "MATCH (pg:Page {id: $id}) "
    "SET pg.delivery = $delivery, pg.channels = $channels, pg.channel = $channel, pg.delivered_at = $now, "
    "pg.status = CASE WHEN $failed AND pg.status = 'sent' THEN 'delivery_failed' ELSE pg.status END "
    "RETURN pg.status"
)


def record_delivery(g: Graph, *, pid: str, delivery: dict, now: int) -> str | None:
    """What each channel did with a page (in-app always; external ones as configured). A page whose every external
    channel failed reads delivery_failed (still in the in-app pager, still escalating); an acked page keeps its status."""
    ext = {k: v for k, v in delivery.items() if k != "in_app"}
    failed = bool(ext) and not any(v.get("ok") for v in ext.values())
    chans = ["in_app"] + sorted(ext)
    r = g.query(W_PAGE_DELIVERY, {"id": pid, "delivery": json.dumps(delivery, sort_keys=True, default=str),
                                  "channels": chans, "channel": ",".join(chans), "failed": failed, "now": int(now)},
                timeout=WRITE_TIMEOUT_MS).result_set
    return r[0][0] if r else None


W_PAGE_ACK = (
    "MATCH (pg:Page {id: $id}) "
    "WHERE pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN ['page', 'escalation'] "
    "MATCH (p:Person {id: $by}) WHERE p.active "
    "SET pg.status = 'acked', pg.acked_at = $now, pg.acked_by = p.id, pg.ack_via = $via "
    "MERGE (p)-[ak:ACKED {k: $id}]->(pg) SET ak.at = $now, ak.via = $via, ak.tg_user = $tg_user, pg.ack_tg_user = $tg_user "
    "WITH pg, p "
    "OPTIONAL MATCH (pg)-[:FOR]->(i:Incident) "
    # the incident is acknowledged: its other open pages (other teams told at the same time) are superseded
    "FOREACH (o IN [(i)<-[:FOR]-(x:Page) WHERE x.id <> $id AND x.status IN ['sent', 'delivery_failed'] | x] | "
    "SET o.status = 'superseded', o.detail = $superseded) "
    "RETURN pg.id, pg.incident, p.id, p.name"
)


W_PAGE_ACK_ANON = (
    # the holder of the incident's run token (a demo visitor, not a person of the graph): the page is acknowledged with
    # who acted (via run_token), no (:Person)-[:ACKED]-> edge, and MTTA (Q-ONCALL-STATS) counts only people's acks
    "MATCH (pg:Page {id: $id}) "
    "WHERE pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN ['page', 'escalation'] "
    "SET pg.status = 'acked', pg.acked_at = $now, pg.acked_by = null, pg.ack_via = $via, pg.ack_actor = $actor "
    "WITH pg "
    "OPTIONAL MATCH (pg)-[:FOR]->(i:Incident) "
    "FOREACH (o IN [(i)<-[:FOR]-(x:Page) WHERE x.id <> $id AND x.status IN ['sent', 'delivery_failed'] | x] | "
    "SET o.status = 'superseded', o.detail = $superseded) "
    "RETURN pg.id, pg.incident"
)


def ack_page_anonymous(g: Graph, *, pid: str, via: str, actor: str, now: int) -> dict | None:
    r = g.query(W_PAGE_ACK_ANON, {"id": pid, "via": via, "actor": actor[:80], "now": int(now),
                                  "superseded": f"acknowledged by {actor} on page {pid}"}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"page": r[0][0], "incident": r[0][1], "by": None, "name": actor, "at": int(now), "via": via} if r else None


def ack_page(g: Graph, *, pid: str, by: str, via: str, now: int, tg_user: str | None = None) -> dict | None:
    """(:Person)-[:ACKED {at, via}]->(:Page), only while the page still waits for an ack (None ⇒ already acked,
    escalated, resolved or not a page that needs an ack: HTTP 409). The incident's other open pages are superseded in
    the same query, and escalation stops (Q-PAGE-OVERDUE skips an incident with an acked page)."""
    r = g.query(W_PAGE_ACK, {"id": pid, "by": by, "via": via, "now": int(now), "tg_user": tg_user,
                             "superseded": f"acknowledged by {by} on page {pid}"}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"page": r[0][0], "incident": r[0][1], "by": r[0][2], "name": r[0][3], "at": int(now), "via": via} if r else None


W_PAGE_ESCALATE = (
    # (FalkorDB 6.0.2 drops the row when a MATCH whose WHERE holds a pattern comprehension is followed by another
    # MATCH: both MATCHes first, every comprehension in the WITH)
    "MATCH (who:Person {id: $person}) WHERE who.active "
    "MATCH (i:Incident {id: $inc}) "
    "WITH i, who, [(i)<-[:FOR]-(o:Page) WHERE o.id IN $overdue AND o.status IN ['sent', 'delivery_failed'] "
    "AND ($force OR o.ack_due_at <= $now) | o] AS olds "
    # acknowledged = a page sent at or after the oldest overdue one was acked (an earlier wave does not count)
    "WITH i, who, olds, reduce(m = $now, o IN olds | CASE WHEN o.sent_at < m THEN o.sent_at ELSE m END) AS since "
    "WITH i, who, olds, size([(i)<-[:FOR]-(a:Page) WHERE a.status = 'acked' AND a.sent_at >= since | a]) AS acked "
    "WHERE acked = 0 AND size(olds) > 0 "
    "MERGE (pg:Page:Node {id: $id}) "
    "ON CREATE SET pg.tenant = $tenant, pg.incident = $inc, pg.kind = 'escalation', pg.urgency = $urgency, "
    "pg.sent_at = $now, pg.ack_due_at = $now + $window_ms, pg.status = 'sent', pg.attempt = $attempt, "
    "pg.detail = $detail, pg.deep_link = $deep_link, pg.channel = 'in_app', pg.channels = ['in_app'], pg.team = '', "
    "pg.reason = $reason, pg.evidence = $evidence, pg.person = who.id "
    "MERGE (pg)-[:PAGES {k: ''}]->(who) "
    "MERGE (pg)-[:FOR {k: ''}]->(i) "
    "FOREACH (o IN olds | SET o.status = 'escalated', o.escalated_at = $now MERGE (o)-[:ESCALATED_TO {k: ''}]->(pg)) "
    "RETURN pg.id, size(olds)"
)

W_PAGE_EXHAUSTED = (
    "MATCH (i:Incident {id: $inc}) "
    "WITH i, [(i)<-[:FOR]-(o:Page) WHERE o.id IN $overdue AND o.status IN ['sent', 'delivery_failed'] "
    "AND ($force OR o.ack_due_at <= $now) | o] AS olds "
    "WITH i, olds, reduce(m = $now, o IN olds | CASE WHEN o.sent_at < m THEN o.sent_at ELSE m END) AS since "
    "WITH i, olds, size([(i)<-[:FOR]-(a:Page) WHERE a.status = 'acked' AND a.sent_at >= since | a]) AS acked "
    "WHERE acked = 0 AND size(olds) > 0 "
    "FOREACH (o IN olds | SET o.status = 'escalated', o.escalated_at = $now, o.detail = $detail) "
    "RETURN size(olds)"
)


def escalate_pages(g: Graph, *, tenant: str, inc: str, overdue: list[str], page: dict | None, now: int,
                   force: bool = False) -> dict | None:
    """Escalate an unacknowledged incident in ONE query: the overdue pages (still unacked, deadline passed, and no page
    of the incident acked meanwhile) become 'escalated' and each gets (:Page)-[:ESCALATED_TO]->(new page); the new
    escalation page goes to `page['person']`. `page` None: nobody is left to page; the overdue pages are marked
    escalated with the reason. None ⇒ nothing to escalate (acked or escalated by someone else meanwhile)."""
    if page is None:
        r = g.query(W_PAGE_EXHAUSTED, {"inc": inc, "overdue": overdue, "now": int(now), "force": bool(force),
                                       "detail": "escalation order exhausted: nobody left to page; a human must pick this up"},
                    timeout=WRITE_TIMEOUT_MS).result_set
        return {"page": None, "escalated": int(r[0][0])} if r else None
    r = g.query(W_PAGE_ESCALATE, {"tenant": tenant, "inc": inc, "overdue": overdue, "now": int(now), "force": bool(force),
                                  "id": page["id"],
                                  "person": page["person"], "urgency": page["urgency"], "window_ms": int(page["window_ms"]),
                                  "attempt": int(page["attempt"]), "detail": str(page.get("detail") or "")[:1000],
                                  "deep_link": str(page.get("deep_link") or ""), "reason": str(page.get("reason") or "")[:500],
                                  "evidence": page.get("evidence") or ""}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"page": r[0][0], "escalated": int(r[0][1])} if r else None


W_PAGES_SETTLE = (
    "MATCH (i:Incident {id: $inc})<-[:FOR]-(pg:Page) "
    "WHERE pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN $kinds "
    "SET pg.status = $status, pg.settled_at = $now, pg.detail = $detail "
    "RETURN collect(pg.id)"
)


def settle_pages(g: Graph, *, inc: str, status: str, detail: str, now: int,
                 kinds: tuple[str, ...] = ("page", "escalation", "contract_notice")) -> list[str]:
    """The incident's open pages become `resolved` (it was fixed) or `superseded` (a later page replaces them)."""
    if status not in ("resolved", "superseded"):
        raise WriteError(f"pages settle as resolved or superseded, not {status!r}")
    r = g.query(W_PAGES_SETTLE, {"inc": inc, "status": status, "detail": detail[:500], "now": int(now),
                                 "kinds": list(kinds)}, timeout=WRITE_TIMEOUT_MS).result_set
    return list(r[0][0]) if r else []


# Standing approvals (contracts): granted in two steps like an action (choose the scope → an OFFER bound to a hash;
# approve that exact hash → active), used under one guarded write, revoked by a human. They live in the tenant's
# on-call home graph (the tenant graph; an eval's own room), never in a scenario's clean room.
W_CONTRACT_OFFER = (
    "MERGE (c:Contract:Node {id: $id}) "
    "ON CREATE SET c.status = 'offered', c.tenant = $tenant, c.family = $family, c.action_kind = $kind, "
    "c.params_hash = $params_hash, c.params = $params, c.max_uses = $max_uses, c.uses = 0, c.days = $days, "
    "c.expires_at = $expires_at, c.offered_at = $now, c.offer_expires_at = $now + $ttl_ms, c.hash = $hash, "
    "c.source_incident = $inc, c.source_graph = $graph, c.source_action = $aid, c.covers = $covers, c.quote = $quote "
    "RETURN c.id, c.status, c.hash, c.offer_expires_at"
)


def offer_contract(g: Graph, *, cid: str, tenant: str, family: str, kind: str, params_hash: str, params: dict,
                   max_uses: int, days: float, expires_at: int, now: int, ttl_ms: int, hash_: str, inc: str, graph: str,
                   aid: str, covers: str, quote: str) -> dict:
    r = g.query(W_CONTRACT_OFFER, {"id": cid, "tenant": tenant, "family": family, "kind": kind, "params_hash": params_hash,
                                   "params": json.dumps(params, sort_keys=True, default=str), "max_uses": int(max_uses),
                                   "days": float(days), "expires_at": int(expires_at), "now": int(now), "ttl_ms": int(ttl_ms),
                                   "hash": hash_, "inc": inc, "graph": graph, "aid": aid, "covers": covers,
                                   "quote": quote[:500]}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"id": r[0][0], "status": r[0][1], "hash": r[0][2], "offer_expires_at": r[0][3]}


W_CONTRACT_GRANT = (
    # single use, bound to the hash, before the offer expires: an offer becomes active exactly once
    "MATCH (c:Contract {id: $id}) "
    "WHERE c.status = 'offered' AND c.hash = $hash AND c.offer_expires_at > $now AND c.expires_at > $now "
    "MATCH (p:Person {id: $by}) WHERE p.active "
    "SET c.status = 'active', c.granted_at = $now, c.granted_by = p.id, c.real_ok = $real_ok "
    "MERGE (c)-[:GRANTED_BY {k: ''}]->(p) "
    "WITH c "
    "OPTIONAL MATCH (n:Node {id: $covers}) "
    "FOREACH (x IN CASE WHEN n IS NULL THEN [] ELSE [n] END | MERGE (c)-[:COVERS {k: ''}]->(x)) "
    "RETURN c.id, c.status, c.granted_at, c.expires_at"
)


def grant_contract(g: Graph, *, cid: str, hash_: str, by: str, covers: str, now: int, real_ok: bool = False) -> dict | None:
    """Step 2: approve the exact offer (by its hash). None ⇒ unknown, stale hash, expired offer, already granted, or
    not an active person (HTTP 409). `real_ok`: granted with the authority real GitHub needs (the approver key, or
    TELEGRAM_APPROVE_REAL); a contract without it never acts while GitHub is real."""
    r = g.query(W_CONTRACT_GRANT, {"id": cid, "hash": hash_, "by": by, "covers": covers, "now": int(now),
                                   "real_ok": bool(real_ok)}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"id": r[0][0], "status": r[0][1], "granted_at": r[0][2], "expires_at": r[0][3]} if r else None


W_CONTRACT_USE = (
    # THE guarded use (a conditional update): active, same family + action + params, uses < max_uses, not
    # expired, granted by a person still active; increments and records the use in the same query. The use is MERGEd by
    # its deterministic id (contract, graph, incident, action): a retry finds it and never counts it twice
    "MATCH (c:Contract {id: $id})-[:GRANTED_BY]->(p:Person) "
    "OPTIONAL MATCH (c)-[:USED_IN]->(old:ContractUse {id: $uid}) "
    "WITH c, p, old "
    "WHERE old IS NOT NULL OR (c.status = 'active' AND c.family = $family AND c.action_kind = $kind "
    "AND c.params_hash = $params_hash AND c.uses < c.max_uses AND c.expires_at > $now AND p.active) "
    "MERGE (u:ContractUse:Node {id: $uid}) "
    "ON CREATE SET u.contract = c.id, u.incident = $inc, u.graph = $graph, u.action = $aid, u.at = $now, "
    "u.verdict = 'pending', u.batch = $batch "
    "WITH c, u, u.batch = $batch AS fresh "
    "WITH c, u, fresh, CASE WHEN fresh THEN c.uses + 1 ELSE c.uses END AS n "
    "SET c.uses = n, c.last_used_at = CASE WHEN fresh THEN $now ELSE c.last_used_at END, "
    "c.status = CASE WHEN fresh AND n >= c.max_uses THEN 'exhausted' ELSE c.status END "
    "MERGE (c)-[r:USED_IN {k: $uid}]->(u) ON CREATE SET r.at = $now, r.verdict = 'pending' "
    "WITH c, u, fresh "
    "OPTIONAL MATCH (i:Incident {id: $inc}) "
    "FOREACH (x IN CASE WHEN i IS NULL THEN [] ELSE [i] END | MERGE (u)-[:FOR {k: ''}]->(x)) "
    "RETURN c.id, c.uses, c.max_uses, c.status, u.id, fresh"
)


def use_contract(g: Graph, *, cid: str, family: str, kind: str, params_hash: str, uid: str, inc: str, graph: str,
                 aid: str, now: int) -> dict | None:
    """One use of a standing approval, or None (exhausted, expired, revoked, a different family/action/params, or its
    grantor left): the caller then pages a human instead of acting."""
    import uuid

    r = g.query(W_CONTRACT_USE, {"id": cid, "family": family, "kind": kind, "params_hash": params_hash, "uid": uid,
                                 "inc": inc, "graph": graph, "aid": aid, "now": int(now), "batch": uuid.uuid4().hex},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"contract": r[0][0], "uses": r[0][1], "max_uses": r[0][2], "status": r[0][3], "use": r[0][4],
            "fresh": bool(r[0][5])} if r else None


W_CONTRACT_USE_RETURN = (
    # the use was consumed but the action never ran (NOT_EXECUTED): give it back, once (only a still-pending use)
    "MATCH (c:Contract)-[r:USED_IN]->(u:ContractUse {id: $uid}) "
    "WHERE u.verdict = 'pending' "
    "WITH c, r, u, c.uses - 1 AS n "
    "SET c.uses = n, u.verdict = 'NOT_EXECUTED', u.settled_at = $now, r.verdict = 'NOT_EXECUTED', "
    "c.status = CASE WHEN c.status = 'exhausted' AND n < c.max_uses AND c.expires_at > $now THEN 'active' ELSE c.status END "
    "RETURN c.uses, c.status"
)


def give_back_contract_use(g: Graph, *, uid: str, now: int) -> dict | None:
    r = g.query(W_CONTRACT_USE_RETURN, {"uid": uid, "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"uses": r[0][0], "status": r[0][1]} if r else None


W_CONTRACT_USE_VERDICT = (
    "MATCH (c:Contract)-[r:USED_IN]->(u:ContractUse {id: $uid}) "
    "SET u.verdict = $verdict, u.settled_at = $now, r.verdict = $verdict "
    "RETURN u.id"
)


def contract_use_verdict(g: Graph, *, uid: str, verdict: str, now: int) -> bool:
    if verdict not in ("APPLIED", "NOT_APPLIED", "UNKNOWN", "NOT_EXECUTED"):
        raise WriteError(f"bad contract-use verdict {verdict!r}")
    return bool(g.query(W_CONTRACT_USE_VERDICT, {"uid": uid, "verdict": verdict, "now": int(now)},
                        timeout=WRITE_TIMEOUT_MS).result_set)


W_CONTRACT_REVOKE = (
    "MATCH (c:Contract {id: $id}) WHERE c.status IN ['active', 'offered'] "
    "SET c.status = 'revoked', c.revoked_at = $now, c.revoked_by = $by "
    "RETURN c.id, c.status"
)


def revoke_contract(g: Graph, *, cid: str, by: str, now: int) -> bool:
    return bool(g.query(W_CONTRACT_REVOKE, {"id": cid, "by": by[:80], "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set)


W_SHIFT_HANDOFF = (
    "MATCH (f:Person {id: $from}) WHERE f.active "
    "MATCH (t:Person {id: $to}) WHERE t.active "
    "CREATE (h:Handoff:Node {id: $id, at: $now, from_shift: $from_shift, note: $note, tenant: $tenant, incident: $inc, "
    "from_person: f.id, to_person: t.id}) "
    "MERGE (h)-[:FROM {k: ''}]->(f) "
    "MERGE (h)-[:TO {k: ''}]->(t) "
    "WITH h "
    "OPTIONAL MATCH (i:Incident {id: $inc}) "
    "FOREACH (x IN CASE WHEN i IS NULL THEN [] ELSE [i] END | MERGE (h)-[:COVERS {k: ''}]->(x)) "
    "RETURN h.id, h.at"
)


def hand_off_shift(g: Graph, *, hid: str, tenant: str, from_: str, to: str, note: str, from_shift: str, inc: str,
                   now: int) -> dict | None:
    """(:Handoff)-[:FROM]->(outgoing), -[:TO]->(incoming), -[:COVERS]->(incident, when it is in this graph). None ⇒ a
    person is unknown or inactive."""
    r = g.query(W_SHIFT_HANDOFF, {"id": hid, "tenant": tenant, "from": from_, "to": to, "note": note[:2000],
                            "from_shift": from_shift[:200], "inc": inc, "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"id": r[0][0], "at": r[0][1]} if r else None


# The Telegram on-call bot (actions/telegram_bot.py): state that must outlive one webhook call lives in the on-call
# home graph. An update is processed once (its update_id); a typed-phrase consent (approve / grant) is a single-use,
# expiring proposal bound to the plan or contract hash; a chat is linked to a person and may mute information notices.
W_BOT_UPDATE = (
    "MERGE (u:BotUpdate:Node {id: $id}) "
    "ON CREATE SET u.at = $now, u.chat = $chat, u.user = $user, u.kind = $kind, u.batch = $batch "
    "RETURN u.batch = $batch AS fresh"
)


def claim_bot_update(g: Graph, *, uid: str, chat: str, user: str, kind: str, now: int) -> bool:
    """True the first time this update (or digest key) is seen; False for a redelivery (do nothing)."""
    import uuid

    r = g.query(W_BOT_UPDATE, {"id": uid, "chat": chat, "user": user, "kind": kind[:40], "now": int(now),
                               "batch": uuid.uuid4().hex}, timeout=WRITE_TIMEOUT_MS).result_set
    return bool(r and r[0][0])


W_BOT_CHAT = (
    "MERGE (c:BotChat:Node {id: $id}) "
    "ON CREATE SET c.linked_at = $now "
    "SET c.chat = $chat, c.user = $user, c.person = $person, c.seen_at = $now, c.title = $title "
    "RETURN c.id"
)


def link_bot_chat(g: Graph, *, chat: str, user: str, person: str, title: str, now: int) -> str | None:
    r = g.query(W_BOT_CHAT, {"id": f"tgchat-{chat}", "chat": chat, "user": user, "person": person, "title": title[:120],
                             "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set
    return r[0][0] if r else None


W_BOT_MUTE = "MATCH (c:BotChat {id: $id}) SET c.muted_until = $until RETURN c.muted_until"


def mute_bot_chat(g: Graph, *, chat: str, until: int) -> bool:
    return bool(g.query(W_BOT_MUTE, {"id": f"tgchat-{chat}", "until": int(until)}, timeout=WRITE_TIMEOUT_MS).result_set)


W_BOT_PROPOSAL = (
    "CREATE (p:BotProposal:Node {id: $id, kind: $kind, chat: $chat, user: $user, person: $person, tenant: $tenant, "
    "graph: $graph, incident: $inc, action: $action, hash: $hash, prefix: $prefix, created_at: $now, "
    "expires_at: $expires_at, status: 'open', detail: $detail}) "
    "RETURN p.id"
)


def create_bot_proposal(g: Graph, *, pid: str, kind: str, chat: str, user: str, person: str, tenant: str, graph: str,
                        inc: str, action: str, hash_: str, now: int, ttl_ms: int, detail: str = "") -> str:
    if kind not in ("approve", "grant"):
        raise WriteError(f"bad proposal kind {kind!r}")
    r = g.query(W_BOT_PROPOSAL, {"id": pid, "kind": kind, "chat": chat, "user": user, "person": person, "tenant": tenant,
                                 "graph": graph, "inc": inc, "action": action, "hash": hash_, "prefix": hash_[:6],
                                 "now": int(now), "expires_at": int(now) + int(ttl_ms), "detail": detail[:500]},
                timeout=WRITE_TIMEOUT_MS).result_set
    return r[0][0]


W_BOT_PROPOSAL_USE = (
    # single use, before it expires, by the user it was made for, in the chat it was made in: one guarded write
    "MATCH (p:BotProposal {id: $id}) "
    "WHERE p.status = 'open' AND p.expires_at > $now AND p.chat = $chat AND p.user = $user "
    "SET p.status = 'used', p.used_at = $now "
    "RETURN p.id"
)


def use_bot_proposal(g: Graph, *, pid: str, chat: str, user: str, now: int) -> bool:
    return bool(g.query(W_BOT_PROPOSAL_USE, {"id": pid, "chat": chat, "user": user, "now": int(now)},
                        timeout=WRITE_TIMEOUT_MS).result_set)


W_PAGE_TG = (
    "MATCH (pg:Page {id: $id}) "
    "SET pg.tg_chat = coalesce($chat, pg.tg_chat), pg.tg_message_id = coalesce($mid, pg.tg_message_id), "
    "pg.tg_digest = $digest "
    "RETURN pg.id"
)


def record_page_message(g: Graph, *, pid: str, chat: str | None, mid: int | None, digest: str) -> bool:
    """Which Telegram message shows this page (so it is edited in place) and a digest of what it shows (so an
    unchanged card is never re-sent)."""
    return bool(g.query(W_PAGE_TG, {"id": pid, "chat": chat, "mid": mid, "digest": digest},
                        timeout=WRITE_TIMEOUT_MS).result_set)


# Public-mode paging safety (security review): which incidents may leave the building, a per-channel hourly budget and a
# per-recipient cooldown, and the durable index of graphs that hold pages (so escalation never depends on a list cap).
W_INCIDENT_PAGING = "MATCH (i:Incident {id: $inc}) SET i.page_external = $external RETURN i.id"


def set_incident_paging(g: Graph, *, inc: str, external: bool) -> bool:
    """May this incident's pages go to external channels (a keyed or non-public run), or in-app only."""
    return bool(g.query(W_INCIDENT_PAGING, {"inc": inc, "external": bool(external)}, timeout=WRITE_TIMEOUT_MS).result_set)


W_BUDGET_TAKE = (
    "MERGE (b:DeliveryBudget:Node {id: $id}) "
    "ON CREATE SET b.n = 0, b.channel = $channel, b.hour = $hour, b.created_at = $now "
    "WITH b WHERE b.n < $cap "
    "SET b.n = b.n + 1 "
    "RETURN b.n"
)


def take_delivery_budget(g: Graph, *, channel: str, hour: int, cap: int, now: int) -> bool:
    """One send of `channel` in this hour, if the hourly cap allows it (one MERGE, so concurrent senders share it)."""
    return bool(g.query(W_BUDGET_TAKE, {"id": f"budget|{channel}|{hour}", "channel": channel, "hour": int(hour),
                                        "cap": int(cap), "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set)


W_COOLDOWN_TAKE = (
    "MERGE (b:DeliveryBudget:Node {id: $id}) "
    "ON CREATE SET b.last = 0, b.channel = $channel, b.created_at = $now "
    "WITH b WHERE $now - b.last >= $cooldown_ms "
    "SET b.last = $now "
    "RETURN b.last"
)


def take_recipient_cooldown(g: Graph, *, channel: str, recipient: str, cooldown_ms: int, now: int) -> bool:
    return bool(g.query(W_COOLDOWN_TAKE, {"id": f"cooldown|{channel}|{recipient}", "channel": channel,
                                          "cooldown_ms": int(cooldown_ms), "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set)


W_PAGE_GRAPH = (
    "MERGE (x:PageGraph:Node {id: $graph}) "
    "ON CREATE SET x.first_at = $now "
    "SET x.last_at = $now, x.tenant = $tenant "
    "RETURN x.id"
)


def index_page_graph(g: Graph, *, graph: str, tenant: str, now: int) -> None:
    g.query(W_PAGE_GRAPH, {"graph": graph, "tenant": tenant, "now": int(now)}, timeout=WRITE_TIMEOUT_MS)


W_PAGE_GRAPH_DROP = "MATCH (x:PageGraph) WHERE x.id IN $graphs DELETE x RETURN count(x)"


def drop_page_graphs(g: Graph, *, graphs: list[str]) -> int:
    r = g.query(W_PAGE_GRAPH_DROP, {"graphs": list(graphs)}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


W_BOT_PRUNE_UPDATES = "MATCH (n:BotUpdate) WHERE n.at < $before WITH n LIMIT 1000 DELETE n RETURN count(*)"
W_BOT_PRUNE_PROPOSALS = "MATCH (n:BotProposal) WHERE n.expires_at < $before WITH n LIMIT 1000 DELETE n RETURN count(*)"
W_BOT_PRUNE_BUDGET = (
    "MATCH (n:DeliveryBudget) WHERE n.hour IS NOT NULL AND n.created_at < $before WITH n LIMIT 1000 DELETE n "
    "RETURN count(*)"
)


def prune_bot_state(g: Graph, *, updates_before: int, proposals_before: int, budget_before: int) -> int:
    """TTL clean-up: processed bot updates (and digest claims), expired consents and old hourly budget counters (the
    per-recipient cooldown counters, one per person and channel, are kept). Three single queries, 1000 nodes each."""
    n = 0
    for q, before in ((W_BOT_PRUNE_UPDATES, updates_before), (W_BOT_PRUNE_PROPOSALS, proposals_before),
                      (W_BOT_PRUNE_BUDGET, budget_before)):
        r = g.query(q, {"before": int(before)}, timeout=WRITE_TIMEOUT_MS).result_set
        n += int(r[0][0]) if r else 0
    return n



# ------------------------------------------------------------------ learning (M21): events, then derived state in Cypher
# Every learned item lives in the tenant's on-call home graph (oncall_<t>) and is derived from (:LearnEvent) nodes, each
# a TRUSTED operator action (memory/learning.py decides trust; anonymous public-demo actions are never recorded). The
# derived state (Preference, RESPONDED, Guideline, KnowledgeGap) is recomputed from the events by ONE aggregate query
# each, recency decay included as an expression (0.5 ^ (age / half-life)); each derived node keeps DERIVED_FROM edges
# (or an `events` list on a RESPONDED edge) to the events it came from, so forgetting a person's events and recomputing
# removes their influence.
LEARN_KINDS = ("choose", "approve", "reject", "override", "grant", "revoke", "ack", "escalate_now", "handoff",
               "verified", "gap")

W_LEARN_EVENT = (
    "MERGE (e:LearnEvent:Node {id: $id}) "
    "ON CREATE SET e += $props, e.recorded_at = timestamp() "
    "WITH e "
    "OPTIONAL MATCH (p:Person {id: $person}) "
    "FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | SET e.person_name = x.name MERGE (x)-[:DID {k: ''}]->(e)) "
    "WITH e "
    "OPTIONAL MATCH (c:Node {id: $family}) "
    "FOREACH (x IN CASE WHEN c IS NULL OR $family = '' THEN [] ELSE [c] END | MERGE (e)-[:ABOUT {k: ''}]->(x)) "
    "RETURN e.id, e.at, e.recorded_at"
)


def learn_event(g: Graph, *, eid: str, kind: str, person: str, family: str | None, at: int, **props: Any) -> dict:
    """One trusted operator action as a (:LearnEvent), idempotent by id (a retried hook records it once), linked
    (:Person)-[:DID]->(e) when the person exists and -[:ABOUT]->(the family's component). Props are scalars."""
    if kind not in LEARN_KINDS:
        raise WriteError(f"bad learn event kind {kind!r}")
    body = _clean({**props, "kind": kind, "person": person, "family": family or "", "at": int(at)})
    r = g.query(W_LEARN_EVENT, {"id": eid, "person": person or "", "family": family or "", "props": body},
                timeout=WRITE_TIMEOUT_MS).result_set
    if not r:
        raise WriteError(f"learn event {eid} not written")
    return {"id": r[0][0], "at": r[0][1]}


_LN2 = "0.6931471805599453"
W_LEARN_PREFS = (
    # one family: drop its preferences, then rebuild them from its approve/reject events with recency decay, the
    # family totals for the Beta-smoothed preference and DERIVED_FROM edges to every event used (provenance)
    "OPTIONAL MATCH (old:Preference) WHERE old.family = $family "
    "DETACH DELETE old "
    "WITH count(*) AS gone "
    "MATCH (e:LearnEvent) WHERE e.family = $family AND e.kind IN ['approve', 'reject'] AND e.action_kind IS NOT NULL "
    f"WITH e, exp(-{_LN2} * toFloat($now - e.at) / $half_life_ms) AS w "
    "WITH e.action_kind AS kind, sum(CASE WHEN e.kind = 'approve' THEN w ELSE 0.0 END) AS a, "
    "sum(CASE WHEN e.kind = 'reject' THEN w ELSE 0.0 END) AS r, "
    "sum(CASE WHEN e.kind = 'approve' THEN 1 ELSE 0 END) AS na, sum(CASE WHEN e.kind = 'reject' THEN 1 ELSE 0 END) AS nr, "
    "max(CASE WHEN e.kind = 'approve' THEN e.at END) AS last_at, max(e.at) AS last_any, collect(e.id) AS evs "
    "WITH collect({kind: kind, a: a, r: r, na: na, nr: nr, last_at: last_at, last_any: last_any, evs: evs}) AS rows, "
    "sum(a) AS ta, sum(na) AS tna, sum(na + nr) AS tn "
    "UNWIND rows AS x "
    "CREATE (p:Preference:Node {id: 'pref|' + $family + '|' + x.kind, family: $family, action_kind: x.kind, "
    "approvals: x.a, rejections: x.r, others: ta - x.a, n_approve: toInteger(x.na), n_reject: toInteger(x.nr), "
    "n_family_approve: toInteger(tna), n_family: toInteger(tn), last_at: x.last_at, last_event_at: x.last_any, "
    "computed_at: $now, half_life_ms: $half_life_ms, events: x.evs[0..50]}) "
    "WITH p, x "
    "UNWIND x.evs AS eid "
    "MATCH (e:LearnEvent) WHERE e.id = eid "
    "MERGE (p)-[:DERIVED_FROM {k: eid}]->(e) "
    "RETURN count(DISTINCT p), count(e)"
)


def learn_recompute_prefs(g: Graph, *, family: str, now: int, half_life_ms: float) -> dict:
    """Recompute one family's Preference nodes from its approve/reject events (one query; none left ⇒ none kept)."""
    r = g.query(W_LEARN_PREFS, {"family": family, "now": int(now), "half_life_ms": float(half_life_ms)},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"family": family, "preferences": int(r[0][0]) if r else 0, "edges": int(r[0][1]) if r else 0}


W_LEARN_RESPONDED = (
    # one person and one family's component: the decayed sum of their acks, approvals and verified fixes, written on
    # ONE RESPONDED edge with the counts, the mean ack delay, the last response and the events it came from; no event
    # left ⇒ no edge
    "MATCH (p:Person {id: $person}) "
    "MATCH (c:Node {id: $family}) "
    "OPTIONAL MATCH (e:LearnEvent) WHERE e.person = $person AND e.family = $family AND e.kind IN ['ack', 'approve', 'verified'] "
    f"WITH p, c, e, CASE WHEN e IS NULL THEN 0.0 ELSE exp(-{_LN2} * toFloat($now - e.at) / $half_life_ms) END AS w "
    "WITH p, c, sum(w * CASE e.kind WHEN 'ack' THEN $w_ack WHEN 'approve' THEN $w_approve WHEN 'verified' THEN $w_fix "
    "ELSE 0.0 END) AS score, count(e) AS n, sum(CASE WHEN e.kind = 'ack' THEN 1 ELSE 0 END) AS acks, "
    "sum(CASE WHEN e.kind = 'approve' THEN 1 ELSE 0 END) AS approvals, "
    "sum(CASE WHEN e.kind = 'verified' THEN 1 ELSE 0 END) AS fixes, "
    "avg(CASE WHEN e.kind = 'ack' THEN e.ack_ms END) AS mtta, max(e.at) AS last_at, collect(e.id) AS evs, "
    "count(DISTINCT e.incident) AS incidents "
    "MERGE (p)-[r:RESPONDED {k: $family}]->(c) "
    "SET r.score = score, r.n = n, r.acks = toInteger(acks), r.approvals = toInteger(approvals), "
    "r.fixes = toInteger(fixes), r.mtta_ms = mtta, r.last_at = last_at, r.computed_at = $now, "
    "r.half_life_ms = $half_life_ms, r.events = evs[0..50], r.incidents = incidents "
    "WITH r, n "
    "FOREACH (x IN CASE WHEN n = 0 THEN [r] ELSE [] END | DELETE x) "
    "RETURN n"
)


def learn_recompute_responder(g: Graph, *, person: str, family: str, now: int, half_life_ms: float, w_ack: float,
                              w_approve: float, w_fix: float) -> int:
    """Recompute (person)-[:RESPONDED]->(family component) from the person's events (one query). Returns the number
    of events it now rests on (0: the edge is gone). A person or component missing from the graph writes nothing."""
    r = g.query(W_LEARN_RESPONDED, {"person": person, "family": family, "now": int(now),
                                    "half_life_ms": float(half_life_ms), "w_ack": float(w_ack),
                                    "w_approve": float(w_approve), "w_fix": float(w_fix)},
                timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


W_LEARN_GUIDELINE = (
    # a rejection's reason becomes a PROPOSED guideline for its family and action kind (never active by itself)
    "MATCH (e:LearnEvent {id: $event}) WHERE e.kind = 'reject' "
    "MERGE (gd:Guideline:Node {id: $gid}) "
    "ON CREATE SET gd.text = $text, gd.family = e.family, gd.action_kind = e.action_kind, gd.source = 'rejection', "
    "gd.by = e.person, gd.by_name = e.person_name, gd.at = e.at, gd.status = 'proposed', gd.incident = e.incident, "
    "gd.graph = e.graph, gd.option = e.option, gd.source_event = e.id "
    "MERGE (gd)-[:DERIVED_FROM {k: e.id}]->(e) "
    "WITH gd "
    "OPTIONAL MATCH (c:Node) WHERE c.id = gd.family AND NOT c:LearnEvent "
    "FOREACH (x IN CASE WHEN c IS NULL THEN [] ELSE [c] END | MERGE (gd)-[:ABOUT {k: ''}]->(x)) "
    "RETURN gd.id, gd.status"
)


def learn_guideline(g: Graph, *, event: str, gid: str, text: str) -> dict | None:
    r = g.query(W_LEARN_GUIDELINE, {"event": event, "gid": gid, "text": text[:500]}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"id": r[0][0], "status": r[0][1]} if r else None


W_LEARN_GUIDELINE_SET = (
    # promote (proposed → active) or dismiss (proposed|active → dismissed), by an active person, only from the stated
    # statuses (a stale click is a no-op → HTTP 409)
    "MATCH (p:Person {id: $by}) WHERE p.active "
    "MATCH (gd:Guideline {id: $id}) WHERE gd.status IN $from "
    "SET gd.status = $to, gd.decided_by = p.id, gd.decided_by_name = p.name, gd.decided_at = $now "
    "RETURN gd.id, gd.status, gd.decided_at"
)


def learn_set_guideline(g: Graph, *, gid: str, action: str, by: str, now: int) -> dict | None:
    if action not in ("promote", "dismiss"):
        raise WriteError(f"bad guideline action {action!r}")
    frm, to = (["proposed"], "active") if action == "promote" else (["proposed", "active"], "dismissed")
    r = g.query(W_LEARN_GUIDELINE_SET, {"id": gid, "by": by, "from": frm, "to": to, "now": int(now)},
                timeout=WRITE_TIMEOUT_MS).result_set
    return {"id": r[0][0], "status": r[0][1], "decided_at": r[0][2]} if r else None


W_LEARN_GAP = (
    # one question (normalised text): how often trusted users asked it without an answer, when, and the components it
    # was about (ABOUT, so knowledge health can name the owning team); a dismissed gap re-opens when asked again
    "MERGE (k:KnowledgeGap:Node {id: $gid}) "
    "ON CREATE SET k.first_at = $now "
    "WITH k "
    "OPTIONAL MATCH (e:LearnEvent) WHERE e.kind = 'gap' AND e.gap = $gid "
    "WITH k, count(e) AS n, max(e.at) AS last_at, min(e.at) AS first_at, collect(e) AS evs "
    "SET k.n = n, k.last_at = last_at, k.first_at = coalesce(first_at, k.first_at), k.text = $text, "
    "k.intent = $intent, k.reason = $reason, k.about = $about, k.events = [x IN evs | x.id][0..50], "
    "k.status = CASE WHEN k.dismissed_at IS NOT NULL AND k.dismissed_at >= last_at THEN 'dismissed' ELSE 'open' END "
    "FOREACH (x IN evs | MERGE (k)-[:DERIVED_FROM {k: x.id}]->(x)) "
    "WITH k, n "
    "OPTIONAL MATCH (a:Node) WHERE a.id IN $about AND NOT a:LearnEvent AND NOT a:KnowledgeGap "
    "FOREACH (x IN CASE WHEN a IS NULL OR n = 0 THEN [] ELSE [a] END | MERGE (k)-[:ABOUT {k: x.id}]->(x)) "
    "WITH DISTINCT k, n "
    "FOREACH (x IN CASE WHEN n = 0 THEN [k] ELSE [] END | DETACH DELETE x) "
    "RETURN n"
)


def learn_recompute_gap(g: Graph, *, gid: str, text: str, intent: str, reason: str, about: list[str], now: int) -> int:
    r = g.query(W_LEARN_GAP, {"gid": gid, "text": text[:500], "intent": intent or "", "reason": reason[:300],
                              "about": sorted(set(about))[:10], "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set
    return int(r[0][0]) if r else 0


W_LEARN_GAP_DISMISS = (
    "MATCH (k:KnowledgeGap {id: $id}) WHERE k.status = 'open' "
    "SET k.status = 'dismissed', k.dismissed_at = $now, k.dismissed_by = $by "
    "RETURN k.id, k.status"
)


def learn_dismiss_gap(g: Graph, *, gid: str, by: str, now: int) -> dict | None:
    r = g.query(W_LEARN_GAP_DISMISS, {"id": gid, "by": by, "now": int(now)}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"id": r[0][0], "status": r[0][1]} if r else None


W_LEARN_FORGET = (
    # forget a person's learned influence (the approved dry-run list only): their events and the guidelines their
    # rejections proposed, in one query; the derived state is then recomputed (learn_recompute_*), one query each
    "MATCH (e:LearnEvent) WHERE e.person = $person AND e.id IN $ids "
    "OPTIONAL MATCH (gd:Guideline) WHERE gd.source_event = e.id "
    "WITH collect(DISTINCT e) AS evs, collect(DISTINCT gd) AS gds "
    "WITH evs, gds, size(evs) AS n_e, size(gds) AS n_g, reduce(r = 0, x IN evs | r + size([(x)-[k]-() | k])) AS rels "
    "FOREACH (x IN gds | DETACH DELETE x) "
    "FOREACH (x IN evs | DETACH DELETE x) "
    "RETURN n_e, n_g, rels"
)


def learn_forget(g: Graph, *, person: str, ids: list[str]) -> dict:
    r = g.query(W_LEARN_FORGET, {"person": person, "ids": sorted(set(ids))}, timeout=WRITE_TIMEOUT_MS).result_set
    return {"events": int(r[0][0]), "guidelines": int(r[0][1]), "relationships": int(r[0][2])} if r else \
        {"events": 0, "guidelines": 0, "relationships": 0}
