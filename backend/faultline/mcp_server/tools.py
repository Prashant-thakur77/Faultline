"""Graph tool implementations (plain functions; `server.py` exposes each as an MCP tool).

Every tool: validates inputs, runs exactly one read template through `RO.run` (GRAPH.RO_QUERY +
TIMEOUT + LIMIT), computes any numbers in code (weights.yaml), and returns
{rows, via, cypher, params, ms, digest, served_by, truncated, evidence_id}. Failures return
{"error": "<kind>: <message>"}: loud, never an empty result standing in for a failure.
When an agent run is bound, the call is recorded as (:ToolCall)-[:SAW]->(n) + (:Evidence) in one
atomic engine write (graph/writes.record_tool_call).
"""

from __future__ import annotations

import functools
import time
import hashlib
import re
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError, model_validator

from ..agent.weights import tier_weights_param, weights
from ..graph import client, writes
from ..graph.algo.maxflow import CutMismatch
from ..graph.errors import GraphError, GraphNotReady, GraphUnavailable
from ..graph.ro import RO, QueryResult
from ..graph.templates import load
from . import context

Id = Field(..., min_length=1, max_length=160)


def _ev_id(template: str, params: dict, digest: str) -> str:
    h = hashlib.sha256(f"{template}|{sorted(params.items())}|{digest}".encode()).hexdigest()
    return f"ev_{h[:10]}"


def _combine(results: list[QueryResult], rows: list[dict]) -> QueryResult:
    """One evidence item for a tool that answers with several templates: every sub-query's id, Cypher and params,
    a digest over all their digests (so the evidence id changes when any part changes) and truncation if any."""
    keys: list[str] = []  # a template run more than once (impact_bound's per-source Q-GATE-3) keeps every run's params
    for r in results:
        n = sum(1 for k in keys if k.split("#")[0] == r.template_id)
        keys.append(r.template_id if n == 0 else f"{r.template_id}#{n + 1}")
    return QueryResult(
        template_id="+".join(r.template_id for r in results),
        cypher="\n;\n".join(f"// {k}\n{r.cypher}" for k, r in zip(keys, results)),
        params={k: r.params for k, r in zip(keys, results)},
        header=[], rows=rows, ms=sum(r.ms for r in results),
        digest=hashlib.sha256("|".join(r.digest for r in results).encode()).hexdigest(),
        seen_ids=set().union(*(r.seen_ids for r in results)), truncated=any(r.truncated for r in results),
        served_by=results[0].served_by if results else "")


def _strings(obj: Any, out: set[str] | None = None) -> set[str]:
    """Every string value inside a tool result (rows / extra), recursively."""
    out = set() if out is None else out
    if isinstance(obj, str):
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            _strings(v, out)
    return out


def _envelope(r: QueryResult, *, tool: str, via: str, kind: str, about: list[str], summary: str,
              extra: dict | None = None, value: float | None = None, baseline: float | None = None,
              ratio: float | None = None) -> dict:
    b = context.current()
    ev = _ev_id(r.template_id, r.params, r.digest)
    out = {"rows": r.rows, "via": via, "template": r.template_id, "cypher": r.cypher, "params": r.params,
           "ms": round(r.ms, 2), "digest": r.digest, "served_by": r.served_by, "truncated": r.truncated,
           "evidence_id": ev}
    if extra:
        out.update(extra)
    if b.run_id and b.record:
        g = client.engine().select_graph(b.graph)
        tc_id = b.next_call_id()
        out["tool_call_id"] = tc_id   # the agent that made the call links it to its task (MADE)
        out["grounded_ids"] = writes.record_tool_call(
            g, run_id=b.run_id, tenant=b.tenant, tc_id=tc_id, tool=tool, template=r.template_id,
            cypher=r.cypher, params=r.params, digest=r.digest, rows=len(r.rows), ms=r.ms, truncated=r.truncated,
            # SAW only what the graph returned: an `about` id the caller supplied counts as seen only if it came back
            # in the result (a model must not ground a citation by merely asking about an id)
            served_by=r.served_by, seen_ids=sorted(r.seen_ids | (set(about) & _strings([r.rows, extra or {}]))),
            ev_id=ev, kind=kind, about=about,
            summary=summary, value=value, baseline=baseline, ratio=ratio,
            payload={"rows": r.rows, **{k: v for k, v in (extra or {}).items() if k not in ("rows",)}})
    return out


def _guard(fn: Callable[..., dict]) -> Callable[..., dict]:
    @functools.wraps(fn)  # keeps the real signature so MCP derives the right input schema
    def wrapper(**kwargs: Any) -> dict:
        try:
            return fn(**kwargs)
        except ValidationError as e:
            return {"error": f"invalid arguments: {e.errors()[0]['msg']}"}
        except GraphUnavailable as e:  # never the engine's host, port or account in a client's answer
            return {"error": "unavailable: " + re.sub(r"\s+at [\w.-]+:\d+", "", str(e)).split(": invalid username")[0]}
        except GraphError as e:
            return {"error": f"{type(e).__name__}: {e}"}
        except CutMismatch as e:
            return {"error": f"cut mismatch (fail loudly): {e}"}
    return wrapper


def _ro() -> RO:
    b = context.current()
    return RO(b.tenant, b.graph)


# ------------------------------------------------------------------ seeds and context
class _Text(BaseModel):
    text: str = Field(..., min_length=2, max_length=120)
    labels: list[str] | None = None


_FIND = {"Service": "Q-FIND-SERVICE", "Table": "Q-FIND-TABLE", "Runbook": "Q-FIND-RUNBOOK", "Decision": "Q-FIND-DECISION"}


def _ft_query(text: str) -> str:
    """Full-text query string: alphanumeric tokens with prefix matching."""
    toks = ["".join(ch for ch in t if ch.isalnum()) for t in text.lower().split()]
    toks = [t for t in toks if len(t) >= 2][:6]
    if not toks:
        raise ValueError("no searchable tokens")
    return " | ".join(f"{t}*" for t in toks)


_FIND_VEC = {"Incident": "Q-FIND-INCIDENT-VEC", "Runbook": "Q-FIND-RUNBOOK-VEC"}


@_guard
def find_entities(text: str, labels: list[str] | None = None) -> dict[str, Any]:
    """Seed entities by name and meaning (tier 1), in ONE query: full-text over Service/Table/Runbook/Decision names
    unioned with the FalkorDB vector index over Incident/Runbook embeddings (similarity ≥ memory.find_min_similarity);
    the engine merges them, one row per entity with its best score and every index that found it (Q-FIND-HYBRID)."""
    a = _Text(text=text, labels=labels)
    if a.labels and not set(a.labels) & (set(_FIND) | set(_FIND_VEC)):
        return {"error": "invalid arguments: no supported labels"}
    q = _ft_query(a.text)
    params: dict[str, Any] = {"text": q, "labels": sorted(set(a.labels or []))}
    note = ""
    qv = None
    if not a.labels or set(a.labels) & set(_FIND_VEC):
        try:
            from ..memory.embed import embed

            qv = embed([a.text])[0]
        except Exception as e:  # noqa: BLE001  (model missing: say so; full-text still answers)
            note = f"vector seed unavailable ({type(e).__name__}); full-text only"
    if qv is None:
        r = _ro().run("Q-FIND-TEXT", params)
    else:
        r = _ro().run("Q-FIND-HYBRID", {**params, "q": qv, "floor": float(weights()["memory"]["find_min_similarity"])})
    for row in r.rows:
        if row.get("status") is None:
            row.pop("status", None)  # only decisions carry a status
    return _envelope(r, tool="find_entities", via=f"db.idx.fulltext.queryNodes('{q}') ∪ db.idx.vector.queryNodes"
                     + (" (full-text only)" if qv is None else ""), kind="lookup", about=[x["id"] for x in r.rows[:5]],
                     extra={"note": note} if note else None,
                     summary=f"{len(r.rows)} matches for {a.text!r}" + (f" ({note})" if note else ""))


# words that carry no topic: kept out of knowledge search's full-text lists, where they would match every document
KNOW_STOP = frozenset("""
a an and are as at be been but by can could did do does for from had has have how if in into is it its of on or our
should so than that the their them then there these they this to was we were what when where which who whom whose why
will with would you your about after before during any all ever us me my not no does doing done just also only very
""".split())


def _kq_query(text: str) -> str:
    """Full-text query for knowledge search: topic words only (stopwords dropped), prefix-matched from four letters,
    any of them ('|'). Empty when the text has no topic word (the full-text lists then stay off)."""
    toks = ["".join(ch for ch in t if ch.isalnum()) for t in text.lower().split()]
    toks = list(dict.fromkeys(t for t in toks if len(t) >= 3 and t not in KNOW_STOP))[:8]
    return " | ".join(f"{t}*" if len(t) >= 4 else t for t in toks)


@_guard
def search_knowledge(text: str) -> dict[str, Any]:
    """What the organisation's documents say (track T3): ADRs, runbooks, incident-channel chats, issues and
    postmortems, searched in ONE query (Q-KNOW-1) by meaning (vecf32 over document text chunks, postmortems and
    runbooks) and by words (full-text), the lists fused by reciprocal rank inside FalkorDB. Each hit comes with the
    passage that matched and the ids it concerns (components, decisions, incidents, who decided). A document's text is
    credited to the decision or runbook it produced."""
    a = _Text(text=text)
    w = weights()["brain"]
    note = ""
    try:
        from ..memory.embed import embed_one

        qv = embed_one(a.text)
    except Exception as e:  # noqa: BLE001 (model missing: say so; the full-text lists still answer)
        qv, note = None, f"vector lists unavailable ({type(e).__name__}); full-text only"
    kq = _kq_query(a.text)
    if qv is None and not kq:
        return {"error": "invalid arguments: no topic words and no vector model"}
    r = _ro().run("Q-KNOW-1", {"q": qv, "text": kq, "floor": float(w["knowledge_min_similarity"]),
                               "k": int(w["knowledge_rrf_k"])})
    return _envelope(r, tool="search_knowledge", kind="lookup", about=[x["id"] for x in r.rows[:5]],
                     via="vecf32 + full-text over document chunks, postmortems, runbooks and decisions, "
                         "reciprocal-rank fused in the engine, then 1-2 hops", extra={"note": note} if note else None,
                     summary=f"{len(r.rows)} sources for {a.text!r}" + (f" ({note})" if note else ""))


class _IdArg(BaseModel):
    id: str = Id


# Generic words that are never a misspelt component: they still resolve EXACTLY (a service literally named "search"
# is found), but are never fuzzy-matched ("check" → checkout, "flags" → flagd, "current" → currency were real misses).
FUZZY_STOP = frozenset("""
check checks checking current currently flag flags audit audits auditing event events metric metrics search searches
order orders ordering status state states data info error errors alert alerts alerting change changes changed deploy
deploys deployed config configs setting settings issue issues problem problems incident incidents outage outages
caused cause causes depend depends affect affects affected owner owners owned report reports dashboard dashboards
latency traffic request requests queue queues table tables service services system systems server servers
logs log logging cache caches update updates release releases version versions failure failures failed failing
""".split())


def _name_words(text: str) -> list[str]:
    """The words of `text` a component's name or id could start with: split on anything not a letter or digit, two
    letters or more, generic words (FUZZY_STOP) dropped, cut to a 5-letter prefix ("calculates" → "calcu")."""
    out = [w[:5] for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 2 and w not in FUZZY_STOP]
    return list(dict.fromkeys(out))[:12]


@_guard
def resolve_entity(text: str, fuzzy: bool = True, by_name: bool = False) -> dict[str, Any]:
    """Resolve a component by its id, ignoring case and hyphens ("productcatalog" → product-catalog). Tier 1.
    With fuzzy (default) and no exact match, a misspelling resolves in the engine (FLEX Jaro-Winkler) unless the
    text is a generic word or differs too much in length; fuzzy=false asks for exact matches only. With by_name,
    the components whose name or id words begin with the text's words ("shipping quote calculator" → quote, "valkey"
    → cache), most words matched first (`matched`), in one query (Q-FIND-NAME)."""
    a = _Text(text=text)
    if by_name:
        words = _name_words(a.text)
        if not words:
            return {"error": "invalid arguments: no words to match a name with"}
        r = _ro().run("Q-FIND-NAME", {"words": words})
        return _envelope(r, tool="resolve_entity", via="name / id words (prefix match)", kind="lookup",
                         about=[x["id"] for x in r.rows],
                         summary=f"{len(r.rows)} components named like {a.text!r}"
                                 + (f" (best: {r.rows[0]['id']}, {r.rows[0]['matched']} words)" if r.rows else ""))
    raw = a.text.strip().lower()
    norm = "".join(ch for ch in raw if ch.isalnum() or ch in "._")
    ro = _ro()
    r = ro.run("Q-FIND-ID", {"id": raw, "norm": norm})
    via = "id match (case/hyphen-insensitive)"
    w = weights()["brain"]
    if (fuzzy and not r.rows and len(norm) >= int(w["fuzzy_min_len"]) and norm not in FUZZY_STOP
            and raw not in FUZZY_STOP):  # misspelt: FalkorDB FLEX Jaro-Winkler, in the engine
        fz = ro.run("Q-FIND-FUZZY", {"norm": norm, "min": float(w["fuzzy_min"]), "ratio": float(w["fuzzy_len_ratio"])})
        r = _combine([r, fz], [{**x, "sim": round(float(x["sim"]), 3)} for x in fz.rows])
        via = f"id match, then flex.text.jaroWinkler ≥ {w['fuzzy_min']} (length ratio ≥ {w['fuzzy_len_ratio']})"
    return _envelope(r, tool="resolve_entity", via=via, kind="lookup", about=[x["id"] for x in r.rows],
                     summary=f"{len(r.rows)} ids for {a.text!r}" + (f" (fuzzy: {r.rows[0]['id']} at {r.rows[0]['sim']})"
                                                                     if r.rows and r.rows[0].get("via") == "fuzzy" else ""))


@_guard
def service_context(id: str, now: int) -> dict[str, Any]:
    """Owner team, current on-call, runbooks and active decisions for a service/table/transform/KPI."""
    a = _IdArg(id=id)
    r = _ro().run("Q-CTX-1", {"id": a.id, "now": int(now)})
    return _envelope(r, tool="service_context", via=f"(:Team)-[:OWNS]->({a.id}), ON_CALL, RUNBOOK_FOR, CONSTRAINS",
                     kind="context", about=[a.id], summary=f"context of {a.id}")


CUT_MAX_EDGES = 100  # candidate edges in a containment region (the old Q-CUT-2 LIMIT): more → refuse, never cut blind


# ------------------------------------------------------------------ scope and impact (algo.BFS / SSpaths)
@_guard
def upstream_scope(symptom_id: str) -> dict[str, Any]:
    """Everything the symptom depends on, with hop distance (algo.SSpaths over DEPENDS_ON)."""
    a = _IdArg(id=symptom_id)
    r = _ro().run("Q-LIN-1", {"symptom": a.id})
    return _envelope(r, tool="upstream_scope", via=f"({a.id})-[:DEPENDS_ON*1..8]->(upstream)", kind="lineage",
                     about=[a.id], summary=f"{len(r.rows)} upstream nodes")


@_guard
def blast_radius(id: str) -> dict[str, Any]:
    """What breaks if this fails: algo.BFS over PROPAGATES_TO, ranked by impact inside the engine (Q-BLAST-3: the
    faultline.impact UDF scores tier × 1/(1+hops) × traffic from algo.SSpaths, with the weights.yaml tier weights)."""
    a = _IdArg(id=id)
    r = _ro().run("Q-BLAST-3", {"id": a.id, "tw": tier_weights_param()})
    return _envelope(r, tool="blast_radius", via=f"algo.BFS(({a.id}), 8, 'PROPAGATES_TO') + algo.SSpaths, "
                     "ranked by faultline.impact", kind="blast", about=[a.id], summary=f"{len(r.rows)} impacted nodes")


@_guard
def chokepoints() -> dict[str, Any]:
    """Single points of failure: algo.betweenness over service calls (seeded, deterministic)."""
    r = _ro().run("Q-CHOKE-1", {})
    return _envelope(r, tool="chokepoints", via="algo.betweenness(Service/Datastore, CALLS, seed 42)", kind="centrality",
                     about=[x["id"] for x in r.rows[:3]], summary="top chokepoints")


# ------------------------------------------------------------------ changes
class _Window(BaseModel):
    onset: int
    window_min: int = Field(30, ge=1, le=24 * 60)


@_guard
def upstream_suspects(symptom_id: str, onset: int, window_min: int = 30) -> dict[str, Any]:
    """Changes in the window on the symptom or anything upstream of it, with hop distance."""
    a, w = _IdArg(id=symptom_id), _Window(onset=onset, window_min=window_min)
    r = _ro().run("Q-SUS-1", {"symptom": a.id, "onset": w.onset, "window_ms": w.window_min * 60_000})
    return _envelope(r, tool="upstream_suspects", via=f"(:Deploy)-[:CHANGED]->(upstream of {a.id})", kind="change",
                     about=[a.id] + [x["deploy"] for x in r.rows], summary=f"{len(r.rows)} upstream changes")


@_guard
def window_changes(onset: int, window_min: int = 30) -> dict[str, Any]:
    """Every change in the window anywhere (where look-alike distractors enter)."""
    w = _Window(onset=onset, window_min=window_min)
    r = _ro().run("Q-SUS-2", {"onset": w.onset, "window_ms": w.window_min * 60_000})
    return _envelope(r, tool="window_changes", via="(:Deploy)-[:CHANGED]->() in window", kind="change",
                     about=[x["deploy"] for x in r.rows], summary=f"{len(r.rows)} changes in window")


# ------------------------------------------------------------------ gate algorithms
def _g2_connectivity_ablation(change: str, symptom: str) -> dict[str, Any]:
    """The FalkorDB ladder's rung (c) (PREREGISTRATION 2026-10-13): what G2 would be with mere connectivity instead
    of a directed causal path: the change's component and the symptom in one weakly connected component of the failure
    edges (algo.WCC, Q-WHATIF-2). Reached only when weights' gate.ablate_g2_connectivity is set by an eval."""
    ro = _ro()
    if not ro.graph_name.startswith("eval_"):  # never in the product: a stray weights key must not weaken G2 silently
        raise RuntimeError(f"gate.ablate_g2_connectivity is an eval-only switch; refused on graph {ro.graph_name!r}")
    targets = sorted({x["target"] for x in ro.run("Q-CHANGE-1", {"id": change}).rows if x.get("target")})
    r = ro.run("Q-WHATIF-2", {"ids": sorted({*targets, symptom})})
    comp = {x["id"]: x["componentId"] for x in r.rows}
    tgt = next((x for x in targets if x == symptom or (x in comp and comp.get(x) == comp.get(symptom))), None)
    same = tgt is not None
    r.rows = [{"chain": [change, tgt, symptom] if tgt != symptom else [change, symptom], "rels": [], "weight": 0,
               "hops": 1, "learned_from": []}] if same else []
    via = f"(ablation) {change}: {'connected to' if same else 'not connected to'} {symptom}"
    return _envelope(r, tool="causal_paths", via=via, kind="path", about=[change, symptom], summary=via,
                     value=float(len(r.rows)), extra={"learned_hops": [], "ablation": "g2_connectivity"})


@_guard
def causal_paths(from_id: str, to_id: str) -> dict[str, Any]:
    """THE load-bearing query: algo.SPpaths cause → symptom over CHANGED|GATES|PROPAGATES_TO. Empty = no path, no claim."""
    a, b = _IdArg(id=from_id), _IdArg(id=to_id)
    if weights()["gate"].get("ablate_g2_connectivity"):  # EVAL ONLY (evals/ladder.py rung c); never set in the product
        return _g2_connectivity_ablation(a.id, b.id)
    r = _ro().run("Q-GATE-1", {"cause": a.id, "symptom": b.id})
    via = " → ".join(r.rows[0]["chain"]) if r.rows else f"no path {a.id} → {b.id} (≤ {weights()['gate']['max_len']} hops)"
    learned = []
    if r.rows:  # a hop that is a learned link is named, with the incident whose verified fix taught it
        ch, lf = r.rows[0]["chain"], r.rows[0].get("learned_from") or []
        learned = [{"from": ch[i], "to": ch[i + 1], "incident": lf[i]} for i in range(min(len(lf), len(ch) - 1)) if lf[i]]
        if learned:
            via += " (learned link: " + ", ".join(f"{x['from']} → {x['to']} from {x['incident']}" for x in learned) + ")"
    return _envelope(r, tool="causal_paths", via=via, kind="path", about=[a.id, b.id],
                     summary=via, value=float(len(r.rows)), extra={"learned_hops": learned})


CTX_MAX_BUDGET = 8000
CTX_MAX_TEXT = 2000
CTX_MAX_SUSPECTS = 8
CTX_TOP_CHANGES = 5       # changes in the top tier; the rest follow owners and decisions (a busy window must not crowd them out)
CTX_PEOPLE_DAYS = 30      # who-fixes history window: the same 30 days the loop's who_fixes call uses (agent/loop.py)
CTX_CHARS_PER_TOKEN = 4     # one rule for every pack (PREREGISTRATION 2026-10-14: tokens = characters / 4)


def _ctx_item(kind: str, text: str, ids: list[str], rank: tuple, template: str) -> dict:
    return {"kind": kind, "text": text, "ids": sorted({i for i in ids if i}), "rank": list(rank), "template": template,
            "tokens": max(1, -(-len(text) // CTX_CHARS_PER_TOKEN))}


def pack_items(pool: list[dict], budget_tokens: int) -> list[dict]:
    """Greedy by rank: the highest-ranked items that fit the budget, in rank order (pure; unit-tested)."""
    out, used = [], 0
    for it in sorted(pool, key=lambda x: x["rank"]):
        if used + it["tokens"] <= budget_tokens:
            out.append(it)
            used += it["tokens"]
    return out


@_guard
def context_pack(text: str, targets: list[str] | None = None, at: int | None = None,
                 budget_tokens: int = 1000, window_min: int | None = None, rank: str = "anomaly") -> dict[str, Any]:
    """Context engineering for any agent (hybrid GraphRAG for operations): the smallest provenance-carrying
    context an LLM needs about an alert or question. Entry points are the alerting nodes plus hybrid matches of the text
    (full-text and the vecf32 index); the graph then expands them along typed edges: changes in the window upstream of
    the alert (Q-SUS-1, SSpaths over DEPENDS_ON; ranked by the error-rate excess measured on the changed component, then
    path distance: rank="anomaly", the default by the pre-registered rule; rank="distance" ignores telemetry), their causal
    paths to it (Q-GATE-1, SPpaths), owners, on-call,
    runbooks and constraining decisions (Q-CTX-1, Q-DEC-ABOUT), and similar past incidents. Items are ranked by graph
    distance and packed to `budget_tokens` (characters / 4); every item carries the node ids and the template that
    produced it, so a citation can be checked. Returns the pack and the whole candidate pool."""
    text = (text or "").strip()
    if not 1 <= len(text) <= CTX_MAX_TEXT:
        return {"error": f"invalid arguments: text must be 1..{CTX_MAX_TEXT} characters"}
    if len(targets or []) > 5:
        return {"error": "invalid arguments: at most 5 targets"}
    if rank not in ("distance", "anomaly"):
        return {"error": "invalid arguments: rank must be 'distance' or 'anomaly'"}
    budget = max(50, min(int(budget_tokens), CTX_MAX_BUDGET))
    now = int(at) if at is not None else int(time.time() * 1000)
    win = max(1, min(int(window_min or weights()["gate"]["window_min"]), 24 * 60))   # the incident's own window, as the run uses
    ro = _ro()
    parts: list = []
    pool: list[dict] = []
    notes: list[str] = []
    # 1. entry points: the alerting nodes (each must exist in this tenant's graph: a caller's id is never echoed back
    #    as if the graph had returned it), else the best hybrid matches of the text that are components
    tg = []
    for x in targets or []:
        tid = _IdArg(id=x).id
        r = ro.run("Q-FIND-ID", {"id": tid.lower(), "norm": "".join(ch for ch in tid.lower() if ch.isalnum() or ch in "._")})
        parts.append(r)
        hit = next((y["id"] for y in r.rows if y["id"] == tid), None)
        if hit is None:
            return {"error": f"unknown target {tid!r} in this tenant's graph"}
        tg.append(hit)
    tg = sorted(set(tg))
    seeds = list(tg)
    try:
        q = _ft_query(text[:120])
    except ValueError as e:   # nothing searchable in the text: say so; the graph tiers still answer from the targets
        q, _ = None, notes.append(f"full-text entry skipped ({e})")
    matched: list[tuple[str, str]] = []
    for label, tid in (_FIND.items() if q else []):
        r = ro.run(tid, {"text": q})
        parts.append(r)
        if not tg:
            seeds += [x["id"] for x in r.rows if x.get("label") in ("Service", "Table", "Datastore", "KPI")][:2]
        matched += [(label, x["id"]) for x in r.rows[:3] if label in ("Decision", "Runbook")]
    if not seeds:
        return {"error": "no entry point: no target given and nothing in the text matched a component"}
    seeds = sorted(set(seeds))[:5]
    for s in seeds:
        pool.append(_ctx_item("alert", f"alerting: {s}", [s], (0, 0, s), "Q-FIND-ID" if s in tg else "Q-FIND-SERVICE"))
    for k, (label, mid) in enumerate(matched):   # decisions and runbooks the text names (full-text)
        pool.append(_ctx_item("match", f"{label.lower()} {mid} matches the question (full-text)", [mid], (4, 50 + k, mid),
                              _FIND[label]))
    # 2. changes in the window upstream of each alerting node (Q-SUS-1 per node); deduplicated to the nearest alerting
    #    node, measured and RANKED IN THE ENGINE (Q-CTX-RANK): rank="anomaly" puts changes on components that broke first
    raw: list[dict] = []
    for s in seeds:
        r = ro.run("Q-SUS-1", {"symptom": s, "onset": now, "window_ms": win * 60_000})
        parts.append(r)
        raw += [{"deploy": x["deploy"], "kind": x["kind"], "target": x["target"], "at": x["at"], "hops": x["hops"],
                 "symptom": s} for x in r.rows]
    iw = weights()["intake"]
    a_since = now - int(iw["alert_lead_min"]) * 60_000
    ranked: list[dict] = []
    if raw:
        r = ro.run("Q-CTX-RANK", {"sus": raw, "rank": rank, "floor": float(weights()["gate"]["err_abs_min"]),
                                  "since": a_since, "until": now + int(iw["alert_lag_min"]) * 60_000,
                                  "base_since": a_since - int(iw["baseline_min"]) * 60_000,
                                  "base_until": a_since - int(iw["baseline_gap_min"]) * 60_000})
        parts.append(r)
        ranked = r.rows
    exc = {x["target"]: (None if x["excess"] is None else float(x["excess"])) for x in ranked}
    for i, x in enumerate(ranked):   # the top few first; the long tail after owners and decisions (context eval)
        mins = round((now - int(x["at"] or now)) / 60_000)
        e = exc.get(x["target"])
        meas = "no error-rate windows" if e is None else f"error-rate excess {e:+.3f}"
        pool.append({**_ctx_item("change", f"change {x['deploy']} ({x['kind']}) on {x['target']} ({meas}), {x['hops']} "
                                           f"hop(s) upstream of {x['symptom']}, {mins} min before", [x["deploy"], x["target"]],
                                 (1, i, x["deploy"]) if i < CTX_TOP_CHANGES else (4, 100 + i, x["deploy"]), "Q-CTX-RANK"),
                         "at": x["at"]})
    # 3. causal paths for the nearest suspects (the gate's own path query)
    chains: list[list[str]] = []
    for i, x in enumerate(ranked[:CTX_MAX_SUSPECTS]):
        r = ro.run("Q-GATE-1", {"cause": x["deploy"], "symptom": x["symptom"]})
        parts.append(r)
        if r.rows:
            ch = r.rows[0]["chain"]
            chains.append(ch)
            pool.append(_ctx_item("path", "causal path: " + " → ".join(ch), ch, (2, i, x["deploy"]), "Q-GATE-1"))
    # 4. owners, on-call, runbooks and decisions for the alerting nodes and the nearest suspects' components
    comps = list(dict.fromkeys(seeds + [x["target"] for x in ranked[:3]]))
    for j, cid in enumerate(comps):
        r = ro.run("Q-CTX-1", {"id": cid, "now": now})
        parts.append(r)
        for x in r.rows:
            bits = [f"owner team {x['team']}" if x.get("team") else "", f"on-call {', '.join(x['oncall'])}" if x.get("oncall") else "",
                    f"runbooks {', '.join(x['runbooks'])}" if x.get("runbooks") else ""]
            if any(bits):
                pool.append(_ctx_item("context", f"{cid}: " + "; ".join(b for b in bits if b),
                                      [cid, x.get("team"), *(x.get("oncall") or []), *(x.get("runbooks") or [])],
                                      (3, j, cid), "Q-CTX-1"))
    # 4b. who can fix it: recent authors, past resolvers and on-call around the nearest suspects' components (Q-ORG-1)
    for j, cid in enumerate(dict.fromkeys(x["target"] for x in ranked[:3])):
        r = ro.run("Q-ORG-1", {"target": cid, "now": now, "since": now - CTX_PEOPLE_DAYS * 86_400_000})
        parts.append(r)
        for x in r.rows:
            people = list(dict.fromkeys((x.get("oncall") or []) + (x.get("past_resolvers") or []) + (x.get("recent_authors") or [])))[:6]
            if people:
                pool.append(_ctx_item("people", f"who can fix {cid}: " + ", ".join(people) +
                                      (f" (team {x['team']})" if x.get("team") else ""), [cid, x.get("team"), *people],
                                      (3, 50 + j, cid), "Q-ORG-1"))
    # 5. decisions constraining the alerting nodes and the chain's nodes
    order = list(dict.fromkeys(comps + [n for ch in chains for n in ch[1:]]))[:100]
    seen_dec: set[str] = set()
    if order:   # one query for every component (Q-CTX-DEC: in force at `at`, filtered in the engine)
        r = ro.run("Q-CTX-DEC", {"ids": order, "now": now})
        parts.append(r)
        for x in r.rows:   # in the engine's order: the nearest component first
            if x["id"] in seen_dec:
                continue
            seen_dec.add(x["id"])
            pool.append(_ctx_item("decision", f"decision {x['id']} constrains {x['component']}: {x.get('title') or ''}",
                                  [x["id"], x["component"]], (4, int(x["position"]), x["id"]), "Q-CTX-DEC"))
    # 6. similar past incidents and runbooks by meaning (the vecf32 index), lowest tier
    try:
        from ..memory.embed import embed

        qv = embed([text[:512]])[0]
    except Exception as e:  # noqa: BLE001 (model missing: said in the result; the graph tiers still answer)
        qv = None
        notes.append(f"vector tier unavailable ({type(e).__name__}); no similar incidents")
    if qv is not None:
        floor = float(weights()["memory"]["find_min_similarity"])
        for lab, tid in _FIND_VEC.items():
            r = ro.run(tid, {"q": qv})
            parts.append(r)
            hits = [y for y in r.rows if float(y["similarity"]) >= floor]
            past = {}
            if lab == "Incident" and hits:   # what happened last time, not a bare id (Q-CTX-INC: cause, fix, resolver)
                pr = ro.run("Q-CTX-INC", {"ids": [y["id"] for y in hits][:20]})
                parts.append(pr)
                past = {y["id"]: y for y in pr.rows}
                def _before(h: dict | None) -> bool:   # as of `at`: only incidents that started before it (never this one)
                    when = (h or {}).get("onset_at") or (h or {}).get("opened_at")
                    return when is not None and int(when) < now
                hits = [y for y in hits if _before(past.get(y["id"]))]
            for k, x in enumerate(hits):
                sim = float(x["similarity"])
                h = past.get(x["id"])
                if h:
                    from ..memory.learning import ago

                    when = h.get("onset_at") or h.get("opened_at")
                    line = (f"past incident {x['id']} \"{h.get('title') or ''}\": last seen {ago(now - int(when))}"
                            f"; caused by {h.get('cause') or 'unknown'}"
                            + (f" on {h['cause_target']}" if h.get("cause_target") else "")
                            + (f"; fixed by {h['fix_kind']} {h.get('fix_target') or ''}"
                               + (", verified" if h.get("fix_verdict") == "APPLIED" else f" ({h.get('fix_verdict') or '?'})")
                               if h.get("fix_kind") else "")
                            + (f"; resolved by {', '.join(h['resolvers'])}" if h.get("resolvers") else "") + f" (similarity {sim:.2f})")
                    ids = [x["id"], h.get("cause"), h.get("cause_target"), h.get("fix_target"), *(h.get("resolvers") or [])]
                else:
                    line, ids = f"similar {lab.lower()} {x['id']} (similarity {sim:.2f})", [x["id"]]
                pool.append(_ctx_item("similar", line, ids, (5, k, x["id"]), tid))
    pack = pack_items(pool, budget)
    res = _combine(parts, pack)
    used = sum(x["tokens"] for x in pack)
    # fail loudly: a source cut at its LIMIT (e.g. more than 20 changes upstream of the alert, Q-SUS-1) is named, never hidden
    truncated = sorted({r.template_id for r in parts if r.truncated})
    via = (f"{len(pack)}/{len(pool)} items, {used}/{budget} tokens" + (f"; TRUNCATED sources: {', '.join(truncated)}"
                                                                      if truncated else "")
           + (f"; {'; '.join(notes)}" if notes else ""))
    return _envelope(res, tool="context_pack", via=via, kind="context", about=seeds,
                     summary=f"context pack for {', '.join(seeds) or text[:60]!r}" + ("; incomplete (truncated)" if truncated else ""),
                     extra={"pool": pool, "tokens": used, "budget": budget, "seeds": seeds, "truncated_sources": truncated,
                            "notes": notes})


@_guard
def upstream_explained(suspect_ids: list[str], onset: int, mode: str = "strict") -> dict[str, Any]:
    """G4 upstream (deep bench + adversarial review): for the suspects' changed components, the anomalous components
    upstream that account for their anomaly. mode="strict" (sweep ELIMINATION, Q-GATE-UPSTREAM): the upstream fault
    started first and its measured excess × the best single path's cap × call share covers the whole excess, no
    slack. mode="bound" (confirm DOWNGRADE only, Q-GATE-UPSTREAM-UB): the generous upper bound (summed paths × caps,
    × gate.upstream_slack); it may only make the gate less confident, never eliminate."""
    if mode not in ("strict", "bound"):
        return {"error": "invalid arguments: mode must be 'strict' or 'bound'"}
    if len(suspect_ids) > IMPACT_MAX_IDS:
        return {"error": f"invalid arguments: at most {IMPACT_MAX_IDS} component ids (got {len(suspect_ids)}); split the set"}
    ids = sorted({_IdArg(id=s).id for s in suspect_ids})
    g, iw = weights()["gate"], weights()["intake"]
    since = int(onset) - int(iw["alert_lead_min"]) * 60_000
    p = {"ids": ids, "since": since, "until": int(onset) + int(iw["alert_lag_min"]) * 60_000,
         "base_since": since - int(iw["baseline_min"]) * 60_000, "base_until": since - int(iw["baseline_gap_min"]) * 60_000,
         "min_excess": float(g["err_abs_min"])}
    if mode == "bound":
        p["slack"] = float(g["upstream_slack"])
    r = _ro().run("Q-GATE-UPSTREAM" if mode == "strict" else "Q-GATE-UPSTREAM-UB", p)
    if r.truncated:
        return {"error": f"{r.template_id} truncated: too many upstream components to judge; nothing is eliminated"}
    via = ("; ".join(f"{x['s']} carried from {x['u']} (excess {x['u_excess']:.4f} → {x['s_excess']:.4f})" for x in r.rows[:6])
           or f"no anomalous component upstream accounts for {', '.join(ids)}")
    return _envelope(r, tool="upstream_explained", via=via, kind="upstream", about=ids, summary=f"{mode}: {via}",
                     value=float(len(r.rows)), extra={"mode": mode})


@_guard
def impact_bound(suspect_ids: list[str], symptom_id: str, observed_share: float) -> dict[str, Any]:
    """Max-flow sufficiency bound (gate G5): the largest share of the symptom the suspect set can explain
    (algo.maxFlow over PROPAGATES_TO.cap). Verdict computed in code with flow_slack from weights.yaml.
    More than IMPACT_MAX_IDS suspects is refused (never silently cut). The bound is unknown (flow_share None, verdict
    "unknown": never "insufficient") when the path multiplicity it needs is incomplete: Q-GATE-MULT truncated, or a
    source's path count at the SPpaths cap while the capped bound is still below 1."""
    if len(suspect_ids) > IMPACT_MAX_IDS:
        return {"error": f"invalid arguments: at most {IMPACT_MAX_IDS} suspect ids per bound (got {len(suspect_ids)}); "
                         "split the set"}
    ids = [_IdArg(id=s).id for s in suspect_ids]
    sym = _IdArg(id=symptom_id).id
    if not 0.0 <= float(observed_share) <= 1.0:
        return {"error": "invalid arguments: observed_share must be in [0,1]"}
    ro = _ro()
    unknown = ""
    if sym in ids:  # a change on the symptom component itself carries all of it (max flow undefined when s = t)
        r = ro.run("Q-GATE-3", {"sources": [x for x in ids if x != sym], "symptom": sym})
        raw = flow = 1.0
        ks: dict[str, int] = {}
    else:
        r = ro.run("Q-GATE-3", {"sources": ids, "symptom": sym})
        raw = float(r.rows[0]["max_flow"]) if r.rows else 0.0
        m = ro.run("Q-GATE-MULT", {"sources": ids, "symptom": sym})
        ks = {x["source"]: int(x["paths"]) for x in m.rows}
        parts = [r, m]
        if raw <= 0:
            flow = 0.0
        elif len(ids) == 1:  # a request can meet the fault once per path: the sound bound is k × maxFlow
            flow = min(1.0, max(ks.get(ids[0], 1), 1) * raw)
        else:  # several sources: union bound Σ k_s × maxFlow({s}) (never a summed path count times the joint flow)
            per = {x: ro.run("Q-GATE-3", {"sources": [x], "symptom": sym}) for x in ids}
            parts += list(per.values())  # the evidence carries every per-source run the union bound summed
            flow = min(1.0, sum(max(ks.get(x, 1), 1) * float(q.rows[0]["max_flow"]) for x, q in per.items() if q.rows))
        capped = sorted(x for x, k in ks.items() if k >= MULT_PATH_CAP)
        if raw > 0 and m.truncated:
            unknown = "Q-GATE-MULT truncated: the path multiplicity of some suspects is missing"
        elif raw > 0 and capped and flow < 1.0:
            unknown = f"path count of {capped} at the SPpaths cap ({MULT_PATH_CAP}): the multiplicity may be larger"
        r = _combine(parts, r.rows)  # the evidence carries every query: re-running it reproduces the bound
    slack = float(weights()["gate"]["flow_slack"])
    need = float(observed_share) * slack
    share: float | None = None if unknown else flow
    verdict = "unknown" if share is None else ("sufficient" if flow >= need - 1e-12 else "insufficient")
    k_note = max(ks.values(), default=1)
    return _envelope(r, tool="impact_bound", via=f"algo.maxFlow({ids} → {sym}, cap) × path multiplicity", kind="flow",
                     about=ids + [sym],
                     summary=(f"bound unknown ({unknown}); max flow {raw:.4f} vs needed {need:.4f}" if unknown else
                              f"bound {flow:.4f} (max flow {raw:.4f}, up to {k_note} path(s)) vs needed {need:.4f} ({verdict})"),
                     value=share, baseline=need,
                     extra={"flow_share": share, "max_flow": raw, "multiplicity": ks, "observed_share": float(observed_share),
                            "slack": slack, "needed": need, "verdict": verdict,
                            **({"unknown_reason": unknown} if unknown else {})})


IMPACT_MAX_IDS = 20
MULT_PATH_CAP = 100  # Q-GATE-MULT's SPpaths pathCount


@_guard
def reachable_from_changes(now: int, window_min: int, anomalous_ids: list[str]) -> dict[str, Any]:
    """Negative proof (no-incident): anomalous nodes reachable from any change in the window
    (algo.SSpaths). Three-valued: a change whose path count hit the cap makes the proof UNKNOWN."""
    w = _Window(onset=now, window_min=window_min)
    ids = [_IdArg(id=s).id for s in anomalous_ids][:100]
    ro = _ro()
    r = ro.run("Q-NEG-1", {"now": w.onset, "window_ms": w.window_min * 60_000, "anomalous_ids": ids})
    counts = ro.run("Q-NEG-2", {"now": w.onset, "window_ms": w.window_min * 60_000})
    cap = int(weights()["gate"]["sspaths_path_count"])
    truncated = [x["change"] for x in counts.rows if int(x["paths"]) >= cap] or ([] if not counts.truncated else ["*"])
    verdict = "UNKNOWN" if truncated else ("reachable" if r.rows else "none_reachable")
    return _envelope(r, tool="reachable_from_changes", via="algo.SSpaths(change, CHANGED|GATES|PROPAGATES_TO)",
                     kind="path", about=ids, summary=f"negative proof: {verdict}", value=float(len(r.rows)),
                     extra={"verdict": verdict, "possibly_truncated": truncated})


@_guard
def containment_cut(failing_id: str, protect_ids: list[str]) -> dict[str, Any]:
    """Smallest containment, in ONE read-only query (Q-CUT-3): algo.maxFlow (cut_cost) from the failing component to
    the protected set, then the min-cut inside FalkorDB: residual reachability over every candidate edge of the region,
    and the edges that leave it. Fails loudly if the cut's capacity is not the max-flow or a protected node is not cut
    off."""
    f = _IdArg(id=failing_id).id
    prot = [_IdArg(id=p).id for p in protect_ids][:10]
    r = _ro().run("Q-CUT-3", {"failing": f, "protect": prot, "max_edges": CUT_MAX_EDGES})
    if not r.rows:
        return {"error": f"containment: {f} or protected set {prot} not found in the graph"}
    row = r.rows[0]
    if int(row["candidates"]) >= CUT_MAX_EDGES:
        return {"error": "candidate edge set truncated; containment region too large to cut safely"}
    max_flow = float(row["max_flow"])
    if row["protected_on_source_side"]:
        raise CutMismatch(f"targets {row['protected_on_source_side']} reachable in the residual graph; cut is not separating")
    if abs(float(row["cut_total"]) - max_flow) > 1e-6 * max(1.0, max_flow):
        raise CutMismatch(f"cut capacity {row['cut_total']} != maxFlow {max_flow}; the engine's cut does not match its flow")
    side = row["source_side"]
    r.rows = list(row["cut"])
    return _envelope(r, tool="containment_cut", via=f"algo.maxFlow({f} → {prot}, cut_cost) + residual min-cut in the engine",
                     kind="flow", about=[f] + prot + [c["u"] for c in r.rows], value=max_flow,
                     summary=f"cut {[(c['u'], c['v']) for c in r.rows]} total {row['max_flow']}",
                     extra={"max_flow": max_flow, "source_side": sorted(side)})


@_guard
def connectivity_check(target_id: str | None = None, protect_ids: list[str] | None = None) -> dict[str, Any]:
    """Connected components of the failure-flow graph (algo.WCC). With target_id + protect_ids: is the failing
    component connected to anything protected? (`linked`; no → containment has nothing to cut)."""
    if target_id is None:
        r = _ro().run("Q-CONN-1", {})
        return _envelope(r, tool="connectivity_check", via="algo.WCC(PROPAGATES_TO)", kind="topology", about=[],
                         summary=f"{len(r.rows)} components")
    a = _IdArg(id=target_id)
    prot = [_IdArg(id=p).id for p in (protect_ids or [])][:50]
    r = _ro().run("Q-CONN-2", {"target": a.id, "protect": prot})
    linked = bool(r.rows and r.rows[0]["protected_in_component"])
    return _envelope(r, tool="connectivity_check", via="algo.WCC(PROPAGATES_TO)", kind="topology", about=[a.id] + prot,
                     summary=f"{a.id} {'is' if linked else 'is NOT'} connected to a protected node", extra={"linked": linked})


# ------------------------------------------------------------------ lineage, people, decisions
@_guard
def column_lineage(column_id: str) -> dict[str, Any]:
    """Column-level lineage chains for a field (DERIVES_FROM, ≤ 6 hops)."""
    a = _IdArg(id=column_id)
    r = _ro().run("Q-COL-1", {"column": a.id})
    return _envelope(r, tool="column_lineage", via=f"({a.id})-[:DERIVES_FROM*1..6]->()", kind="lineage",
                     about=[a.id], summary=f"{len(r.rows)} column chains")


@_guard
def owners_of(target_id: str, now: int, since: int) -> dict[str, Any]:
    """Deterministic who-fixes candidates: owner team, recent authors, past resolvers, current on-call."""
    a = _IdArg(id=target_id)
    r = _ro().run("Q-ORG-1", {"target": a.id, "now": int(now), "since": int(since)})
    return _envelope(r, tool="owners_of", via=f"OWNS/AUTHORED/RESOLVED/ON_CALL around {a.id}", kind="people",
                     about=[a.id], summary=f"candidates for {a.id}")


@_guard
def bus_factor(target_id: str) -> dict[str, Any]:
    """Bus factor (decided in the graph, Q-ORG-BUS): the fewest ACTIVE people covering > 50% of commits."""
    a = _IdArg(id=target_id)
    r = _ro().run("Q-ORG-BUS", {"target": a.id})
    row = r.rows[0] if r.rows else {"bus_factor": 0, "total": 0, "top_contributor_inactive": False}
    factor = int(row["bus_factor"] or 0)
    return _envelope(r, tool="bus_factor", via=f"(:Person)-[:COMMITTED]->({a.id})", kind="people", about=[a.id],
                     summary=f"bus factor {factor}", value=float(factor),
                     extra={"bus_factor": factor, "total_commits": int(row["total"] or 0),
                            "top_contributor_inactive": bool(row["top_contributor_inactive"])})


class _Priority(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


@_guard
def notify_set(target_id: str, now: int, priority_ids: list[str] | None = None) -> dict[str, Any]:
    """Who to NOTIFY (not who fixes it): the teams that own something in the failing component's blast radius
    (algo.SSpaths hops + bottleneck cap), each with the impacted nodes they own, its weighted impact and who is on
    call now. Deduplicated by team; every row carries the nodes (the path) that put the team on the list.
    `priority_ids` (optional): nodes whose owners are told FIRST, e.g. the SLO'd and customer-facing nodes the
    obligation_clock returned when it pages; every row then names which of them it owns. Otherwise ranked by impact."""
    a = _AtArg(id=target_id, at=now)
    pri = {_IdArg(id=i).id for i in _Priority(ids=priority_ids or []).ids}
    # one query: the blast radius, the owning teams, their summed impact (faultline.capImpact) and the order
    r = _ro().run("Q-NOTIFY-2", {"id": a.id, "now": a.at, "tw": tier_weights_param(), "priority": sorted(pri)})
    if not pri:
        for row in r.rows:
            row.pop("priority", None)
    return _envelope(r, tool="notify_set", via=f"algo.SSpaths({a.id}, PROPAGATES_TO) → (:Team)-[:OWNS]->(impacted), "
                     "summed by faultline.capImpact",
                     kind="people", about=[a.id] + [x["team"] for x in r.rows[:5]],
                     summary=f"{len(r.rows)} teams to notify: " + ", ".join(x["team"] for x in r.rows[:4])
                     + (" (owners of obligated nodes first)" if pri else "")
                     + (" (capped at 20 teams: more may need notifying)" if r.truncated else ""),
                     extra={"priority_ids": sorted(pri)} if pri else None)


class _ChainWindow(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=20)
    since: int = Field(..., ge=0, le=4_102_444_800_000)
    until: int = Field(..., ge=0, le=4_102_444_800_000)

    @model_validator(mode="after")
    def _ordered(self) -> "_ChainWindow":
        if self.since > self.until:
            raise ValueError("since must be <= until")
        return self


@_guard
def alert_coverage(chain: list[str], since: int, until: int) -> dict[str, Any]:
    """Why alerts missed it: along the proven causal chain, which hops had an alert (and when) and which were silent."""
    a = _ChainWindow(ids=chain, since=since, until=until)
    ids = [_IdArg(id=c).id for c in a.ids]
    r = _ro().run("Q-CHAIN-MON", {"chain": ids, "since": a.since, "until": a.until})
    silent = [x["id"] for x in r.rows if not x["alerts"]]
    return _envelope(r, tool="alert_coverage", via="(:Alert)-[:FIRED_ON]->(hop) along the G2 chain", kind="coverage",
                     about=ids, summary=f"{len(ids) - len(silent)}/{len(ids)} hops alerted; silent: {', '.join(silent) or 'none'}")


# ------------------------------------------------------------------ company brain over time
class _AtArg(BaseModel):
    id: str = Id
    at: int = Field(..., ge=0, le=4_102_444_800_000)  # epoch ms, before 2100


def _at(ro: RO, target_id: str, at: int | None, incident_id: str | None) -> _AtArg:
    """The time anchor: an explicit epoch-ms `at`, or an incident's onset (opened_at) read from the graph."""
    if at is None and incident_id:
        row = (ro.run("Q-INC-1", {"inc": _IdArg(id=incident_id).id}).rows or [{}])[0]
        at = row.get("onset_at") or row.get("opened_at")
        if at is None:
            raise ValueError(f"not found: incident {incident_id} has no onset in this tenant's graph")
    if at is None:
        raise ValueError("give `at` (epoch ms) or `incident_id`")
    return _AtArg(id=target_id, at=int(at))


@_guard
def owner_at(target_id: str, at: int | None = None, incident_id: str | None = None) -> dict[str, Any]:
    """Who owned a component at time `at` (epoch ms) or at an incident's onset (`incident_id`) vs who owns it now,
    from the OWNED_AT history. When ownership has changed since, also returns the people from the then-owning team
    who worked on it: they hold the context."""
    ro = _ro()
    try:
        a = _at(ro, target_id, at, incident_id)
    except ValueError as e:
        return {"error": str(e)}
    r = ro.run("Q-OWN-AT", {"id": a.id, "at": a.at})
    then = next((x for x in r.rows if x["covers_at"]), None)
    now = next((x for x in r.rows if x["current"]), None)
    changed = bool(then and now and then["team"] != now["team"])
    knew: list[dict] = []
    if changed:
        knew = ro.run("Q-OWN-PEOPLE", {"id": a.id, "team": then["team"], "since": then["since"],
                                       "until": then["until"] if then["until"] is not None else a.at + 1}).rows
    if then is None:
        summary = f"no team owned {a.id} at {a.at} in the recorded history"
    elif changed:
        summary = f"{a.id} was owned by {then['team']} then and is owned by {now['team']} now"
    else:
        summary = f"{a.id} was owned by {then['team']} then, and still is"
    return _envelope(r, tool="owner_at", via=f"(:Team)-[:OWNED_AT {{from, to}}]->({a.id})", kind="people",
                     about=[a.id] + [x["team"] for x in r.rows] + [p["person"] for p in knew], summary=summary,
                     extra={"owner_then": then and then["team"], "owner_now": now and now["team"], "changed_hands": changed,
                            "knew_it_then": knew, "at": a.at})


@_guard
def component_timeline(target_id: str, since: int = 0, until: int = 4_102_444_800_000) -> dict[str, Any]:
    """A component's history, newest first: deploys that changed it, incidents that touched it (and in what role),
    alerts on it, ownership changes, decisions that constrain it and runbook reviews."""
    a = _IdArg(id=target_id)
    lo, hi = _AtArg(id=a.id, at=since).at, _AtArg(id=a.id, at=until).at
    r = _ro().run("Q-TIMELINE-1", {"id": a.id, "since": lo, "until": hi})
    kinds: dict[str, int] = {}
    for x in r.rows:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    return _envelope(r, tool="component_timeline", via=f"CHANGED / AFFECTED / FIRED_ON / OWNED_AT / CONSTRAINS / RUNBOOK_FOR → {a.id}",
                     kind="timeline", about=[a.id], extra={"counts": kinds},
                     summary=f"{len(r.rows)} events on {a.id}" + (" (truncated)" if r.truncated else "") + ": "
                     + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))


@_guard
def topology_at(target_id: str, at: int) -> dict[str, Any]:
    """Versioned topology: what a component could break at time `at` (epoch ms) versus now, read in the
    graph: its failure reach over only the calls that existed then (`valid_from` ≤ at), its reach now (algo.BFS),
    the components added since, and each call introduced after `at` inside today's reach with the PR that
    introduced it. A preflight or postmortem question: "would this change have reached checkout back then?"."""
    a = _AtArg(id=target_id, at=at)
    r = _ro().run("Q-TOPO-AT", {"id": a.id, "at": a.at})
    if not r.rows:
        return {"error": f"not found: {a.id} is not a node in this tenant's graph"}
    x = r.rows[0]
    return _envelope(r, tool="topology_at", via=f"PROPAGATES_TO valid_from ≤ at vs algo.BFS now, from {a.id}",
                     kind="timeline", about=[a.id] + list(x["added"])[:20],
                     extra={"then": len(x["then_reach"]), "now": len(x["now_reach"]), "added": x["added"],
                            "calls_since": x["calls_since"]},
                     summary=f"{a.id} reached {len(x['then_reach'])} components then, {len(x['now_reach'])} now"
                             + (f"; added since: {', '.join(x['added'][:5])}" if x["added"] else "; nothing added since")
                             + (f" (calls introduced by {', '.join(sorted({c['pr'] for c in x['calls_since'] if c['pr']})[:3])})"
                                if x["calls_since"] else ""))


@_guard
def beliefs_at(target_id: str, at: int | None = None, incident_id: str | None = None) -> dict[str, Any]:
    """As-of view: what the graph held true about a component at time `at` (epoch ms) or at an incident's onset
    (`incident_id`): the owning team, who was on call for it, the decisions in force (decided by then and not yet
    superseded) and the runbooks in effect."""
    ro = _ro()
    try:
        a = _at(ro, target_id, at, incident_id)
    except ValueError as e:
        return {"error": str(e)}
    r = ro.run("Q-ASOF-1", {"id": a.id, "at": a.at})
    row = r.rows[0] if r.rows else {}
    return _envelope(r, tool="beliefs_at", via="OWNED_AT / ON_CALL windows, Decision decided_at minus SUPERSEDES, Runbook validity",
                     kind="asof", about=[a.id], extra={"at": a.at},
                     summary=f"at {a.at}: owner {row.get('owner') or 'none'}, decisions {row.get('decisions') or 'none'}")


@_guard
def hidden_coupling(component_ids: list[str] | None = None, min_incidents: int | None = None) -> dict[str, Any]:
    """Edges the graph is probably missing: component pairs where incidents caused by one repeatedly hit the other,
    yet there is no PROPAGATES_TO path between them. Optionally only pairs touching `component_ids`. A finding to
    confirm, never a cause: the gate still needs a path ("no path, no claim")."""
    if len(component_ids or []) > 50:
        return {"error": "invalid arguments: at most 50 component_ids"}
    ids = [_IdArg(id=c).id for c in (component_ids or [])]
    k = int(min_incidents if min_incidents is not None else weights()["knowledge"]["coupling_min"])
    if not 2 <= k <= 100:
        return {"error": "min_incidents must be 2..100"}
    r = _ro().run("Q-COUPLE-1", {"from": ids, "min_incidents": k})
    for x in r.rows:
        x["strength"] = round(float(x["strength"]), 3)
        x["suggest"] = (f"add PROPAGATES_TO {x['cause']} → {x['hit']}: {x['co_failures']} incidents caused at {x['cause']} hit "
                        f"{x['hit']} (overlap {x['strength']})" + (" (they are adjacent, but failure is only modelled flowing the other way)"
                                          if x["adjacent"] else " (no direct relationship recorded at all)"))
    return _envelope(r, tool="hidden_coupling", via="(:Incident)-[:AFFECTED {role}]->() co-failure minus PROPAGATES_TO*1..8",
                     kind="gap", about=sorted({x["cause"] for x in r.rows} | {x["hit"] for x in r.rows}),
                     summary=f"{len(r.rows)} likely missing edges (≥ {k} co-failures, no path)")


@_guard
def knowledge_health(now: int) -> dict[str, Any]:
    """Company brain: where the organisation's knowledge has decayed. Runbooks not reviewed for
    `knowledge.stale_days` (weights.yaml) or written before the current owner took over; components that changed
    hands with no runbook reviewed since (and who from the previous team to ask); active decisions whose components
    changed owner after the decision, or that incident causes have violated."""
    t = _AtArg(id="now", at=now).at
    ro = _ro()
    stale_days = int(weights()["knowledge"]["stale_days"])
    rb = ro.run("Q-KH-1", {"now": t, "stale_days": stale_days})
    ho = ro.run("Q-KH-2", {})
    dec = ro.run("Q-KH-3", {})
    cpl = ro.run("Q-COUPLE-1", {"from": [], "min_incidents": int(weights()["knowledge"]["coupling_min"])})
    orph = ro.run("Q-DEC-ORPHAN", {})   # active decisions whose deciders have all left
    findings = (
        [{"kind": "stale_runbook", "id": x["component"], "ref": x["runbook"], "tier": x["tier"],
          "why": (f"runbook {x['runbook']} predates the current owner {x['owner']}" if x["predates_owner"]
                  else f"runbook {x['runbook']} not reviewed for {x['age_days']} days")} for x in rb.rows]
        + [{"kind": "handover_without_runbook", "id": x["component"], "ref": x["previous_owner"], "tier": x["tier"],
            "ask": x["ask"],
            "why": f"moved from {x['previous_owner']} to {x['owner']}; no runbook reviewed since"
                   + (f"; ask {', '.join(x['ask'][:3])}" if x["ask"] else "; nobody from the previous team who worked on it is left")}
           for x in ho.rows]
        + [{"kind": "decision_at_risk", "id": x["decision"], "ref": x["decision"], "tier": None,
            "why": "; ".join(s for s in (
                f"violated by {x['violations']} incident cause(s)" if x["violations"] else "",
                f"owner changed since it was decided: {', '.join(x['owner_changed_since'])}" if x["owner_changed_since"] else "",
            ) if s)} for x in dec.rows]
        + [{"kind": "missing_edge", "id": x["cause"], "ref": x["hit"], "tier": None,
            "why": f"{x['co_failures']} incidents caused at {x['cause']} also hit {x['hit']}, but the graph has no failure path "
                   f"{x['cause']} → {x['hit']}"} for x in cpl.rows]
        + [{"kind": "decision_deciders_left", "id": x["decision"], "ref": x["decision"], "tier": None,
            "deciders": list(x["deciders"]),
            "why": f"everyone who decided it has left ({', '.join(x['deciders'])}); nobody who made the call can explain it"
                   + (f"; it constrains {', '.join(x['constrains'])}" if x["constrains"] else "")} for x in orph.rows])
    for f, x in zip(findings, rb.rows + ho.rows + dec.rows + cpl.rows + orph.rows):
        f["owner"] = x.get("owner")
    rb = _combine([rb, ho, dec, cpl, orph], findings)
    about = sorted({f["id"] for f in findings} | {f["ref"] for f in findings} | {f["owner"] for f in findings if f["owner"]}
                   | {p for f in findings for p in f.get("ask", []) + f.get("deciders", [])})
    return _envelope(rb, tool="knowledge_health", via="Runbook.reviewed_at vs OWNED_AT handovers; VIOLATES history; co-failure without a path",
                     kind="gap", about=about, extra={"stale_days": stale_days,
                                                     "templates": ["Q-KH-1", "Q-KH-2", "Q-KH-3", "Q-COUPLE-1", "Q-DEC-ORPHAN"]},
                     summary=f"{len(findings)} knowledge-health findings" + (" (truncated)" if rb.truncated else ""))


@_guard
def people_who_worked_on(target_id: str) -> dict[str, Any]:
    """Company brain: who has worked on a component (commit counts, incidents they resolved there, teams)."""
    a = _IdArg(id=target_id)
    r = _ro().run("Q-BRAIN-WHO", {"target": a.id})
    return _envelope(r, tool="people_who_worked_on", via=f"(:Person)-[:COMMITTED]->({a.id}), RESOLVED, MEMBER_OF",
                     kind="people", about=[a.id] + [x["person"] for x in r.rows[:5]], summary=f"{len(r.rows)} people on {a.id}")


class _Question(BaseModel):
    text: str = Field(..., min_length=3, max_length=500)


# Slot words: a literal date or incident id says WHEN a question is about, not what kind of question it is. Both are
# replaced by the words the IntentExemplar texts use for them (data/brain/intent_exemplars.yaml), so "on <YYYY-MM-DD>"
# and "during <incident id>" read like the exemplars' "on a past date" / "during an incident". A date is an ISO date or
# month, or a month name with its year ("April 2026", "March 3, 2026"). Nothing else is rewritten.
_SLOT_DATE = re.compile(r"\b20\d\d-\d\d(?:-\d\d)?\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
                        r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
                        r"(?:\s+\d{1,2}(?:st|nd|rd|th)?,?)?\s+20\d\d\b", re.I)
_SLOT_INCIDENT = re.compile(r"\b(?:[a-z]{1,4}-)?inc-[a-z0-9-]+\b", re.I)
_WORD = re.compile(r"[a-z0-9]+")


def route_text(text: str) -> str:
    """The text a question is routed on: its slot values (dates, incident ids) replaced by slot words."""
    return " ".join(_SLOT_INCIDENT.sub("an incident", _SLOT_DATE.sub("a past date", text)).split())


@_guard
def route_question(text: str) -> dict[str, Any]:
    """Company brain: which kind of question this is (people, decision, gaps, blast, context, owner_then, asof,
    history, knowledge, obligations), decided in FalkorDB: the question's nearest IntentExemplar nodes by meaning
    (vector index) fused with its full-text matches over the exemplar texts, one row per kind, ranked in the engine.
    `routed` is the first row's kind when it clears brain.route_min_similarity and is not a refusal kind, else null:
    the question is then not one the graph can answer. `question_words` are the question's words that occur in an
    answerable exemplar (Q-BRAIN-VOCAB): how it is asked, not what it is about. Without the embedding model it routes
    by full-text only and says so (`mode`, `note`)."""
    a = _Question(text=text)
    norm = route_text(a.text)
    words = list(dict.fromkeys(t for t in _WORD.findall(norm.lower()) if len(t) >= 2))[:24]
    if not words:
        return {"error": "invalid arguments: the question has no words to route on"}
    w = weights()["brain"]
    ft = " | ".join(words)   # alphanumeric tokens only: nothing the full-text query syntax could read as an operator
    try:
        from ..memory.embed import embed

        qv, note = embed([norm])[0], ""
    except Exception as e:  # noqa: BLE001  (model missing: say so; the full-text index still routes)
        qv, note = None, f"vector route unavailable ({type(e).__name__}); routed by full-text only"
    if qv is not None:
        r = _ro().run("Q-BRAIN-INTENT", {"text": ft, "q": qv, "k": int(w["route_k"]), "w_ft": float(w["route_ft_weight"]),
                                         "min_sim": float(w["route_min_similarity"])})
        mode, via = "vector+fulltext", (f"db.idx.vector.queryNodes(IntentExemplar) + {w['route_ft_weight']} × "
                                        f"db.idx.fulltext.queryNodes(IntentExemplar), similarity ≥ {w['route_min_similarity']}")
    else:
        r = _ro().run("Q-BRAIN-INTENT-FT", {"text": ft, "min_ft": float(w["route_ft_min"])})
        mode, via = "fulltext", f"db.idx.fulltext.queryNodes(IntentExemplar), score ≥ {w['route_ft_min']}"
    vocab = _ro().run("Q-BRAIN-VOCAB", {"words": words})   # how the question is asked, not what it is about
    top = r.rows[0] if r.rows else None
    routed = top["intent"] if top and top["answerable"] else None
    extra = {"routed": routed, "mode": mode, "routed_text": norm, "question_words": [x["word"] for x in vocab.rows],
             **({"note": note} if note else {})}
    r = _combine([r, vocab], r.rows)
    best = (f"{top['intent']} at {float(top['vsim'] if top['vsim'] is not None else top['score']):.3f}" if top else "no match")
    return _envelope(r, tool="route_question", via=via, kind="lookup", about=[], extra=extra,
                     summary=f"routed to {routed}" if routed else f"not routed (best: {best})")


@_guard
def missing_guardrails() -> dict[str, Any]:
    """Company brain: revenue-path services with no owning team or no current runbook (a set difference)."""
    r = _ro().run("Q-GAP-1", {})
    return _envelope(r, tool="missing_guardrails", via="(:Service {revenue_path}) minus OWNS / RUNBOOK_FOR",
                     kind="gap", about=[x["id"] for x in r.rows], summary=f"{len(r.rows)} revenue-path services lack a guardrail")


@_guard
def decisions_about(target_id: str) -> dict[str, Any]:
    """Company brain: every decision constraining a component, and what superseded it; who decided each one; and
    the policies that govern it (a change freeze), with who decided them (`policies`)."""
    a = _IdArg(id=target_id)
    ro = _ro()
    r = ro.run("Q-DEC-ABOUT", {"id": a.id})
    who = ro.run("Q-DEC-PEOPLE", {"target": a.id})   # who decided each one, and are they still here
    pol = ro.run("Q-POLICY-ABOUT", {"id": a.id})
    deciders: dict[str, list[dict]] = {}
    for p in who.rows:
        if p.get("person"):
            deciders.setdefault(p["decision"], []).append({k: p[k] for k in ("person", "name", "active", "on_owning_team")})
    policies: dict[str, dict] = {}
    for x in pol.rows:
        e = policies.setdefault(x["policy"], {k: x[k] for k in ("policy", "title", "status", "decided_at", "url")} | {"deciders": []})
        if x.get("person"):
            e["deciders"].append({k: x[k] for k in ("person", "name", "active")})
    people = sorted({p["person"] for p in who.rows + pol.rows if p.get("person")})
    res = _combine([r, who, pol], r.rows)
    return _envelope(res, tool="decisions_about", kind="decision",
                     via=f"(:Decision)-[:CONSTRAINS]->({a.id}), SUPERSEDES, (:Policy)-->({a.id}), (:Person)-[:DECIDED]->",
                     about=[a.id] + [x["id"] for x in r.rows] + sorted(policies) + people,
                     summary=f"{len(r.rows)} decisions and {len(policies)} policies about {a.id}",
                     extra={"deciders": deciders, "policies": list(policies.values()),
                            "templates": ["Q-DEC-ABOUT", "Q-DEC-PEOPLE", "Q-POLICY-ABOUT"]})


class _User(BaseModel):
    user: str = Field(..., pattern=r"^[A-Za-z0-9_.@-]{1,80}$")


# ------------------------------------------------------------------ shared agent notes (T2: memory across agents)
class _Remember(BaseModel):
    text: str = Field(..., min_length=3, max_length=500)
    about: list[str] = Field(..., min_length=1, max_length=10)
    kind: str = Field("lead", pattern="^(lead|observation|hypothesis|handoff|verdict)$")
    agent_name: str = Field("", max_length=60)
    reply_to: str = Field("", max_length=40, pattern=r"^(note-[0-9a-f]{12})?$")
    stance: str = Field("adds", pattern="^(confirms|refutes|adds)$")
    private: bool = False


def _principal(b: context.Binding) -> str:
    """Who writes, for the quota and the record: the hosted bearer key's id, the agent run, or this process."""
    return b.caller or (f"faultline:{b.run_id}" if b.run_id else "local")


@_guard
def remember(text: str, about: list[str], kind: str = "lead", agent_name: str = "", reply_to: str = "",
             stance: str = "adds", private: bool = False) -> dict[str, Any]:
    """Leave a note for other agents (track T2: shared memory). `about`: 1-10 ids of nodes in the graph (components,
    decisions, incidents, people); `kind`: lead | observation | hypothesis | handoff | verdict; `reply_to` (a note id) with
    `stance` confirms | refutes | adds answers another agent's note. Written in ONE atomic query to the tenant's
    agentmem graph by an ACL user that can touch only that graph (the graph the gate reads stays read-only), under a
    daily quota per caller. `private`: only this caller will see it (its own memory beside the shared one). A note is
    a lead for people and agents, never evidence: the evidence gate does not read it."""
    from ..memory import notes

    a = _Remember(text=text, about=[_IdArg(id=i).id for i in about], kind=kind, agent_name=agent_name,
                  reply_to=reply_to, stance=stance, private=private)
    b = context.current()
    try:
        out = notes.remember(b.tenant, principal=_principal(b), name=a.agent_name, session=b.run_id or "",
                             text=a.text, about=a.about, kind=a.kind, reply_to=a.reply_to, stance=a.stance,
                             private=a.private)
    except notes.NoteRefused as e:
        return {"error": f"refused: {e}"}
    except ValueError as e:
        return {"error": f"invalid arguments: {e}"}
    return {**out, "via": "W-NOTE-1 (atomic: the about ids exist, reply target exists, quota on the engine clock)",
            "note": "a lead for other agents; never evidence for the gate"}


class _Recall(BaseModel):
    text: str = Field("", max_length=200)
    focus_id: str = Field("", max_length=120)


@_guard
def recall_notes(text: str = "", focus_id: str = "", include_private: bool = True) -> dict[str, Any]:
    """What other agents noted (track T2): notes recalled by meaning (`text`, the vecf32 index) and by graph distance
    (`focus_id`: notes about that component or one within two PROPAGATES_TO hops), unexpired, ranked inside FalkorDB
    (faultline.noteScore: similarity, nearness, freshness), each with its components and its replies (confirms,
    refutes, adds). Shared notes plus the caller's own private ones (`include_private`). One read-only query on the
    agentmem graph. Leads only: nothing here grounds a claim."""
    from ..memory import notes

    a = _Recall(text=text, focus_id=_IdArg(id=focus_id).id if focus_id else "")
    if not a.text.strip() and not a.focus_id:
        return {"error": "invalid arguments: give text, focus_id or both"}
    b = context.current()
    try:
        r = notes.recall(b.tenant, text=a.text, focus=a.focus_id, viewer=_principal(b) if include_private else "")
    except GraphNotReady:   # no agent has left a note in this tenant yet: an empty answer, said plainly
        return {"rows": [], "note": "no agent has left a note in this tenant yet", "template": "Q-NOTE-RECALL"}
    # about=[]: a note naming a component must never mark that component as seen (G1 grounds on graph facts only)
    return _envelope(r, tool="recall_notes", kind="notes", about=[],
                     via="db.idx.vector.queryNodes(Note) ∪ (focus)-[:PROPAGATES_TO*0..2]-()<-[:ABOUT]-(:Note), "
                     "ranked by faultline.noteScore",
                     summary=f"{len(r.rows)} notes" + (f" near {a.focus_id}" if a.focus_id else ""),
                     extra={"note": "leads left by agents; never evidence"})


@_guard
def session_history(user: str) -> dict[str, Any]:
    """Persistent session history (T2): this user's recent turns across sessions, newest first, with the node ids
    each answer cited (refs). On the hosted MCP server a caller reads only its own sessions (user = its key id)."""
    a = _User(user=user)
    caller = context.current().caller
    if caller is not None and a.user != caller:  # hosted: never another user's (a visitor's) text
        return {"error": f"session_history on the hosted server returns only the caller's own sessions (user {caller!r})"}
    r = _ro().run("Q-SESS-1", {"user": a.user})
    refs = list(dict.fromkeys(x for row in r.rows for x in (row.get("refs") or [])))
    return _envelope(r, tool="session_history", via="(:Session {user})-[:HAS_TURN]->(:Turn)", kind="session",
                     about=refs[:20], summary=f"{len(r.rows)} turns for {a.user}")


@_guard
def preflight_change(pr_id: str) -> dict[str, Any]:
    """Pre-deploy gate for an ingested PR: what its components can break (BFS), how central they are (betweenness),
    past incidents their changes caused, active decisions its facts contradict (Q-DEC-1), bus factor and missing
    guardrails → risk from weights.yaml → allow / require_review / block, with reasons and what would change it."""
    from ..preflight import score as P  # the scoring the retroactive backtest shares (evals/backtest.py)

    a = _IdArg(id=pr_id)
    f = P.gather(_ro(), a.id)
    if not f.changed:
        return {"error": f"{a.id} touches no file the graph maps to a component: cannot assess (uncertainty), human review"}
    s = P.score(f)
    imp, dec = f.impact, f.decisions
    from ..agent.rules import reversals

    rev = reversals(_ro().run("Q-DEC-REV", {"change": a.id}).rows)
    # change freezes: FalkorDB evaluates each policy's weekly window on the wall clock (Q-PRE-FREEZE); a freeze
    # in force only tightens the verdict and is cited with its policy and the local time the engine evaluated
    frz = P.freezes(_ro(), s.changed)
    verdict = P.apply_freeze(s.verdict, frz.rows)
    would = s.would + ([{"term": "freeze", "verdict": s.verdict,
                         "if": "it merged outside " + ", ".join(sorted({r["policy"] for r in frz.rows}))}]
                       if verdict != s.verdict else [])
    reviewers = sorted({p for c in f.comps for p in c["reviewers"]})
    imp.rows = [{"changed": s.changed, "impacted": s.impacted, "revenue_tier1": s.revenue_tier1, "decisions": dec,
                 "past_incidents": s.past, "bus_factor": f.bus, "gaps": s.gaps, "reviewers": reviewers}]
    return _envelope(imp, tool="preflight_change", via="BFS(PROPAGATES_TO) + betweenness + Q-DEC-1 + COMMITTED/OWNS",
                     kind="preflight", about=[a.id] + s.changed + [d["decision"] for d in dec],
                     summary=f"{verdict} (risk {s.risk})" + (f"; frozen by {', '.join(sorted({r['policy'] for r in frz.rows}))}"
                                                             if frz.rows else ""), value=s.risk,
                     extra={"verdict": verdict, "risk": s.risk, "thresholds": weights()["preflight"]["thresholds"],
                            "score_verdict": s.verdict,
                            "freeze": {"rows": frz.rows, "template": frz.template_id, "cypher": frz.cypher,
                                       "params": frz.params, "served_by": frz.served_by},
                            "terms": {k: {"value": round(v, 4), "weighted": round(s.parts[k], 4), "why": why}
                                      for k, (v, why) in s.terms.items()},
                            "would_change_if": would, "reviewers": reviewers,
                            "decision_links": [{"id": d["decision"], "title": d["title"], "url": d["url"]} for d in dec if d["violated"]],
                            # the reversal guard: loud in the comment, never a score term (the backtest is untouched)
                            "reversals": rev})


@_guard
def trace_decision(decision_id: str) -> dict[str, Any]:
    """A decision's current head through SUPERSEDES, its cited sources, and who decided it and the head (`deciders`:
    each person, still active or not, still on a team owning what it constrains or not)."""
    a = _IdArg(id=decision_id)
    ro = _ro()
    head = ro.run("Q-DEC-2", {"id": a.id})
    if not head.rows:
        return _envelope(head, tool="trace_decision", via="not documented", kind="decision", about=[], summary="unknown decision")
    h = head.rows[0]["head"]
    src = ro.run("Q-DEC-3", {"id": h})
    who = ro.run("Q-DEC-WHO", {"ids": sorted({a.id, h})})
    deciders: dict[str, list[dict]] = {}
    for p in who.rows:
        deciders.setdefault(p["decision"], []).append({k: p[k] for k in ("person", "name", "active", "on_owning_team")})
    rows = [{**head.rows[0], **(src.rows[0] if src.rows else {})}]
    res = _combine([head, src, who], rows)
    return _envelope(res, tool="trace_decision", via=f"{a.id} <-[:SUPERSEDES*]- {h}, (:Person)-[:DECIDED]->",
                     kind="decision", about=[a.id, h] + sorted({p["person"] for p in who.rows}),
                     summary=f"head {h}", extra={"deciders": deciders})


@_guard
def decision_check(change_id: str) -> dict[str, Any]:
    """Active, non-superseded decisions the change's asserted facts are constrained by (G8; violation decided in code)."""
    a = _IdArg(id=change_id)
    from ..agent.rules import apply_override, violated

    from ..agent.rules import reversals

    r = _ro().run("Q-DEC-1", {"change": a.id})
    for row in r.rows:
        row["violated"] = violated(row["op"], row["actual"], row["expected"])  # None = cannot decide (surfaced)
        apply_override(row)  # a reviewer's "intentional" override for this change
    rev = reversals(_ro().run("Q-DEC-REV", {"change": a.id}).rows)   # reinstates a reversed decision (annotation)
    return _envelope(r, tool="decision_check", via=f"({a.id})-[:ASSERTS]->(:ChangeFact)-[:ABOUT]->()<-[:CONSTRAINS]-(:Decision)",
                     kind="decision", about=[a.id] + [x["decision"] for x in r.rows] + [x["reversed"] for x in rev],
                     summary=f"{sum(1 for x in r.rows if x.get('violated'))} violations"
                             + (f", {sum(1 for x in r.rows if x['overridden'])} overridden as intentional"
                                if any(x["overridden"] for x in r.rows) else "")
                             + (f"; reinstates {', '.join(x['reversed'] for x in rev)} (reversed by "
                                f"{', '.join(sorted({x['head'] for x in rev}))})" if rev else ""),
                     extra={"reversals": rev})


@_guard
def change_details(deploy_id: str) -> dict[str, Any]:
    """Change specialist: one change as the graph records it: kind, time, actor, title, sha, the component it CHANGED
    and the typed facts its diff ASSERTS (key, value)."""
    a = _IdArg(id=deploy_id)
    r = _ro().run("Q-CHANGE-2", {"id": a.id})
    if not r.rows:
        return {"error": f"not found: no change {a.id} in the graph"}
    t = r.rows[0].get("target")
    return _envelope(r, tool="change_details", via=f"({a.id})-[:CHANGED]->({t}), ASSERTS → (:ChangeFact)", kind="change",
                     about=[a.id] + ([t] if t else []),
                     summary=f"{a.id}: {r.rows[0].get('kind')} of {t}, {len(r.rows[0].get('facts') or [])} asserted facts")


@_guard
def diff_summary(deploy_id: str) -> dict[str, Any]:
    """Code specialist: what the graph knows about a change's code: the commits it CONTAINS, the files they TOUCH and the
    component each file is PART_OF, the PRs holding those commits, the commit authors and the facts its diff ASSERTS;
    code_on_target / facts_on_target say whether that code lands on the component the change CHANGED. Limits: the
    graph has no function-level code (a file path is the finest grain) and no diff text; a change with no commits or
    facts in the graph has no inspectable code."""
    a = _IdArg(id=deploy_id)
    r = _ro().run("Q-CODE-1", {"id": a.id})
    if not r.rows:
        return {"error": f"not found: no change {a.id} in the graph"}
    row = r.rows[0]
    for k in ("commits", "files", "file_components", "prs", "authors"):  # comprehension rows repeat per path
        row[k] = sorted(set(row.get(k) or []))
    inspectable = bool(row["commits"] or row["facts"])
    return _envelope(r, tool="diff_summary", via=f"({a.id})-[:CONTAINS]->(:Commit)-[:TOUCHES]->(:File)-[:PART_OF]->(), ASSERTS",
                     kind="code", about=[a.id] + ([row["target"]] if row.get("target") else []),
                     extra={"inspectable": inspectable},
                     summary=(f"{a.id}: {len(row['commits'])} commits, {len(row['files'])} files, {len(row['facts'])} facts; "
                              f"code on {row.get('target')}: {bool(row['code_on_target'] or row['facts_on_target'])}")
                     if inspectable else f"{a.id}: no commits or diff facts in the graph (code not inspectable)")


@_guard
def rank_causes(incident_id: str, node_ids: list[str]) -> dict[str, Any]:
    """Algorithmic cause ranking: algo.pageRank over the dependency subgraph of the incident (projected by the
    engine into a tenant-scoped scratch graph, ranked read-only, then deleted). Internal tool (writes a scratch graph)."""
    from ..graph import copy as gcopy
    from ..graph.tenant import scratch_graph

    b = context.current()
    ids = sorted({_IdArg(id=i).id for i in node_ids})[:100]
    src = _ro().run("Q-RANK-SRC", {"ids": ids})
    name = scratch_graph(b.tenant, f"{incident_id}_rank")
    db = client.engine()
    gcopy.delete_if_exists(db, name)
    try:
        writes.build_scratch(db.select_graph(name), nodes=ids, edges=[(r["src"], r["dst"]) for r in src.rows])
        r = RO(b.tenant, name).run("Q-RANK-1", {})
    finally:
        gcopy.delete_if_exists(db, name)
    top = max((x["score"] for x in r.rows), default=0.0) or 1.0
    r.rows = [{**x, "norm": round(x["score"] / top, 4)} for x in r.rows]
    return _envelope(r, tool="rank_causes", via=f"algo.pageRank(Node, DEPENDS_ON) on {name}", kind="rank",
                     about=[x["id"] for x in r.rows[:3]], summary=f"pageRank over {len(ids)} nodes, {len(src.rows)} edges")


def _scratch_run(name: str, nodes: list[dict], edges: list[dict], rel: str, template: str) -> QueryResult:
    """Engine projects a scratch graph, the algorithm runs read-only on it, the scratch graph is deleted."""
    from ..graph import copy as gcopy

    b = context.current()
    db = client.engine()
    gcopy.delete_if_exists(db, name)
    try:
        writes.build_scratch_typed(db.select_graph(name), nodes=nodes, edges=edges, rel=rel)
        return RO(b.tenant, name).run(template, {})
    finally:
        gcopy.delete_if_exists(db, name)


def _scratch_runs(name: str, nodes: list[dict], edges: list[dict], rel: str, templates: list[str]) -> list[QueryResult]:
    """Like _scratch_run, with several read templates on the same projection before it is deleted."""
    from ..graph import copy as gcopy

    b = context.current()
    db = client.engine()
    gcopy.delete_if_exists(db, name)
    try:
        writes.build_scratch_typed(db.select_graph(name), nodes=nodes, edges=edges, rel=rel)
        ro = RO(b.tenant, name)
        return [ro.run(t, {}) for t in templates]
    finally:
        gcopy.delete_if_exists(db, name)


MIN_COLLAB = 0.5     # a COLLABORATES tie at least this strong joins the who_fixes projection (Q-ORG-KNOWS)
KNOWS_PAGES = 20     # × 100 pairs per Q-ORG-KNOWS page


@_guard
def who_fixes(target_id: str, now: int, since: int) -> dict[str, Any]:
    """Who fixes it: people ranked by algo.HarmonicCentrality over a symmetric KNOWS_ABOUT projection of the target's
    code (recent commits), incidents (resolvers), on-call and collaborators; every person comes with reasons. The
    projection's pairs (Q-ORG-KNOWS, keyset-paged so a busy component is never silently cut) and each person's reasons
    (Q-ORG-WHO) are computed in Cypher; this function only moves rows into the scratch graph and words the reasons."""
    from ..graph.tenant import scratch_graph

    a = _IdArg(id=target_id)
    b = context.current()
    ro = _ro()
    params = {"target": a.id, "now": int(now), "since": int(since)}
    who = ro.run("Q-ORG-WHO", params)
    if who.truncated:
        raise GraphError(f"Q-ORG-WHO truncated: more people connected to {a.id} than one read returns")
    if not who.rows:
        if not ro.run("Q-ORG-TEAM", params).rows:
            return {"error": f"not found: {a.id} is not a component in this tenant's graph"}
        return {"error": f"nobody active is connected to {a.id} (owner, authors, resolvers, on-call): escalate via the tree"}
    pages, after = [], ("", "")
    for _ in range(KNOWS_PAGES):
        page = ro.run("Q-ORG-KNOWS", params | {"min_collab": MIN_COLLAB, "after_a": after[0], "after_b": after[1]})
        pages.append(page)
        if not page.truncated:
            break
        after = (page.rows[-1]["a"], page.rows[-1]["b"])
    else:
        raise GraphError(f"Q-ORG-KNOWS: more than {KNOWS_PAGES} pages of who_fixes pairs around {a.id}")
    pairs = [x for page in pages for x in page.rows]
    kinds = {a.id: "component"} | {x["person"]: "person" for x in who.rows}
    for x in pairs:
        kinds.setdefault(x["a"], x["a_kind"])
        kinds.setdefault(x["b"], x["b_kind"])
    nodes = [{"id": i, "kind": k} for i, k in sorted(kinds.items())]
    edges = [{"a": x["a"], "b": x["b"], "w": 1.0} for x in pairs] + [{"a": x["b"], "b": x["a"], "w": 1.0} for x in pairs]
    r = _scratch_run(scratch_graph(b.tenant, f"who_{a.id}_{b.run_id or 'ext'}"), nodes, edges, "KNOWS_ABOUT", "Q-ORG-HARM")
    info = {x["person"]: x for x in who.rows}
    ranked = []
    for row in r.rows:  # Q-ORG-HARM's order (score DESC, id)
        p = info.get(row["id"])
        if p is None:
            continue
        team = p["team"]
        reasons = ([f"authored {p['commits']} recent commit(s) on {a.id}"] if p["commits"] else []) \
            + ([f"resolved {', '.join(p['resolved'][:3])} on {a.id}"] if p["resolved"] else []) \
            + ([f"on call for {team} now"] if p["oncall"] else []) \
            + ([f"member of owner team {team}"] if p["member"] and not p["oncall"] else [])
        ranked.append({"person": p["person"], "name": p["name"], "score": round(float(row["score"]), 4),
                       "teams": p["teams"], "reasons": reasons, "oncall": bool(p["oncall"])})
    res = _combine([who, *pages, r], ranked[:10])
    # who is on call for the owner team at `now` (Q-ORG-WHO's on-call column, every one of them, not only the top 10):
    # the on-call pager pages them first (actions/oncall.recipients)
    oncall_now = [x["person"] for x in who.rows if x["oncall"]]
    return _envelope(res, tool="who_fixes", via=f"algo.HarmonicCentrality(KNOWS_ABOUT) around {a.id}", kind="people",
                     about=[a.id] + [x["person"] for x in ranked[:3]],
                     summary="; ".join(f"{x['person']} ({', '.join(x['reasons'][:2])})" for x in ranked[:3]),
                     extra={"oncall_now": oncall_now, "owner_team": (who.rows[0]["team"] if who.rows else None),
                            "target": a.id})


@_guard
def escalation_tree(person_ids: list[str]) -> dict[str, Any]:
    """Who to loop in, in what order: algo.MSF (maximum collaboration weight) over the responders and their managers.
    The pair weights (Q-ORG-COLLAB-W) and the tree's order (Q-ORG-MSF) are computed in Cypher."""
    from ..graph.tenant import scratch_graph

    b = context.current()
    ids = sorted({_IdArg(id=p).id for p in person_ids})[:20]
    ro = _ro()
    mgr = ro.run("Q-ORG-MGR", {"ids": ids})
    everyone = sorted(set(ids) | {m["manager"] for m in mgr.rows})
    w = ro.run("Q-ORG-COLLAB-W", {"ids": everyone})
    if mgr.truncated or w.truncated:
        raise GraphError("escalation_tree: managers or ties truncated at the template LIMIT")
    r = _scratch_run(scratch_graph(b.tenant, f"esc_{b.run_id or 'ext'}"), [{"id": p, "kind": "person"} for p in everyone],
                     [{"a": x["a"], "b": x["b"], "w": x["w"]} for x in w.rows], "COLLABORATES", "Q-ORG-MSF")
    res = _combine([mgr, w, r], [{"from": x["from"], "to": x["to"], "w": x["w"]} for x in r.rows])
    return _envelope(res, tool="escalation_tree", via="algo.MSF(COLLABORATES, maximize) over responders + managers",
                     kind="people", about=everyone[:5], summary=f"{len(r.rows)} escalation edges over {len(everyone)} people",
                     extra={"managers": mgr.rows, "people": everyone})


class _AlertWindow(BaseModel):
    since: int = Field(..., ge=0)
    until: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "_AlertWindow":
        if self.until < self.since:
            raise ValueError("until must not be before since")
        if self.until - self.since > 6 * 3_600_000:
            raise ValueError("an intake window is at most 6 hours")
        return self


@_guard
def group_alerts(since: int, until: int) -> dict[str, Any]:
    """Alert-storm correlation (INTAKE): which symptom alerts firing in [since, until] (epoch ms) that no incident holds
    yet are ONE incident. The engine projects the alerting components plus the PROPAGATES_TO edges among them and their
    upstream (6 hops) that can carry an alert-worthy rise (criticality × the source's measured excess ≥ gate.err_abs_min,
    Q-STORM-EDGES) into a scratch graph; algo.WCC groups them, one component = one incident (Q-STORM-WCC). An alert whose
    target an OPEN incident's confirmed origin reaches over those edges attaches to the nearest such incident
    (Q-STORM-ORIGINS, Q-STORM-ATTACH); the rest of its component opens a new one. Internal tool (writes a scratch graph)."""
    from ..agent.state import TERMINALS
    from ..graph.tenant import scratch_graph

    a = _AlertWindow(since=since, until=until)
    b = context.current()
    w = weights()
    ro = _ro()
    alerts = ro.run("Q-ALERT-1", {"since": a.since, "until": a.until})
    if alerts.truncated:
        raise GraphError("Q-ALERT-1 truncated: more open alerts in the window than one intake round reads")
    if not alerts.rows:
        r = _combine([alerts], [])
        return _envelope(r, tool="group_alerts", via="no open symptom alert in the window", kind="grouping", about=[],
                         summary="0 alerts: nothing to group", extra={"groups": 0, "attached": 0, "alerts": []})
    targets = sorted({x["target"] for x in alerts.rows})
    iw = w["intake"]
    edges = ro.run("Q-STORM-EDGES", {"targets": targets, "since": a.since, "until": a.until,
                                     "base_since": a.since - int(iw["baseline_min"]) * 60_000,
                                     "base_until": a.since - int(iw["baseline_gap_min"]) * 60_000,
                                     "carry_min": float(w["gate"]["err_abs_min"])})
    origins = ro.run("Q-STORM-ORIGINS", {"terminal": sorted(s.value for s in TERMINALS)})
    for q in (edges, origins):
        if q.truncated:  # a partial projection could split one storm into two incidents: fail loudly
            raise GraphError(f"{q.template_id} truncated: the storm is larger than one intake projection reads")
    on: dict[str, list] = {}
    for x in alerts.rows:
        on.setdefault(x["target"], []).append(x)
    origin_of: dict[str, list[str]] = {}
    for o in origins.rows:
        origin_of.setdefault(o["origin"], []).append(o["incident"])
    ids = sorted(set(targets) | {e["src"] for e in edges.rows} | {e["dst"] for e in edges.rows} | set(origin_of))
    nodes = [{"id": n, "alerts": [x["id"] for x in on.get(n, [])] or None,
              "first_at": min((int(x["fired_at"]) for x in on.get(n, [])), default=None),
              "origin_of": sorted(set(origin_of.get(n, []))) or None} for n in ids]
    # algo.WCC fails on a one-node graph on 6.0.2 (LAGr_ConnectedComponents -1000, docs/upstream/15): an isolated anchor
    # node with no alerts keeps every projection at >= 2 nodes; Q-STORM-WCC returns only components that hold alerts
    nodes.append({"id": "_intake_anchor", "kind": "anchor"})
    flows = [{"a": e["src"], "b": e["dst"], "w": float(e["carry"])} for e in edges.rows]
    name = scratch_graph(b.tenant, f"storm_{b.run_id or 'ext'}_{a.since}")
    wcc, att = _scratch_runs(name, nodes, flows, "PROPAGATES_TO", ["Q-STORM-WCC", "Q-STORM-ATTACH"])
    if wcc.truncated or att.truncated:
        raise GraphError("Q-STORM-WCC/Q-STORM-ATTACH truncated: too many alert groups for one intake round")
    meta = {x["id"]: x for x in alerts.rows}
    attach: dict[str, list[dict]] = {}
    for x in att.rows:
        attach.setdefault(x["alert"], []).append({"incident": x["incident"], "hops": int(x["hops"])})
    rows = []
    for k, grp in enumerate(wcc.rows, 1):
        members = sorted(grp["alerts"], key=lambda i: (int(meta[i]["fired_at"]), i))  # intake order: first fired first
        rows.append({"group": k, "targets": sorted(grp["targets"]),
                     "alerts": [{"id": i, "target": meta[i]["target"], "metric": meta[i]["metric"],
                                 "fired_at": meta[i]["fired_at"], "attach": attach.get(i, [])} for i in members]})
    r = _combine([alerts, edges, origins, wcc, att], rows)
    n_att = sum(1 for g_ in rows for x in g_["alerts"] if x["attach"])
    return _envelope(r, tool="group_alerts", via=f"algo.WCC over the failure-carrying alert projection on {name}",
                     kind="grouping", about=sorted(meta)[:50],
                     summary=f"{len(alerts.rows)} alerts → {len(rows)} group(s): "
                             + " | ".join(", ".join(g_["targets"]) for g_ in rows) + f"; {n_att} attach to open incidents",
                     extra={"groups": len(rows), "attached": n_att, "edges": len(edges.rows), "scratch": name})


@_guard
def whatif(failing_id: str, cut_edges: list[list[str]], protect_ids: list[str], keep_connected_ids: list[str]) -> dict[str, Any]:
    """What-if on a GRAPH.COPY branch: remove the proposed cut edges, then read what the failing component still
    reaches (algo.BFS) and whether the protected entry is still connected to the services that must keep working
    (algo.WCC). The branch is deleted afterwards. Internal tool (writes a branch graph)."""
    from ..graph import copy as gcopy
    from ..graph.tenant import whatif_graph

    b = context.current()
    f = _IdArg(id=failing_id).id
    cuts = [(_IdArg(id=u).id, _IdArg(id=v).id) for u, v in cut_edges][:10]
    prot = [_IdArg(id=p).id for p in protect_ids][:10]
    keep = [_IdArg(id=k).id for k in keep_connected_ids][:20]
    before = _ro().run("Q-WHATIF-1", {"failing": f}).rows
    db = client.engine()
    name = whatif_graph(b.tenant, f"{b.run_id or 'ext'}_{abs(hash(tuple(cuts))) % 10**8}")
    gcopy.delete_if_exists(db, name)
    try:
        gcopy.copy_graph(db, b.graph, name)
        removed = writes.remove_flow_edges(db.select_graph(name), cuts)
        branch = RO(b.tenant, name)
        after = branch.run("Q-WHATIF-1", {"failing": f})
        comp = {r["id"]: r["componentId"] for r in branch.run("Q-WHATIF-2", {"ids": prot + keep}).rows}
    finally:
        gcopy.delete_if_exists(db, name)
    reach_before = set(before[0]["reached"]) if before else set()
    reach_after = set(after.rows[0]["reached"]) if after.rows else set()
    entry = prot[0] if prot else None
    connected = {k: (entry is not None and comp.get(k) is not None and comp.get(k) == comp.get(entry)) for k in keep}
    protected_reached = sorted(set(prot) & reach_after)
    after.rows = [{"removed_edges": removed, "reach_before": sorted(reach_before), "reach_after": sorted(reach_after),
                   "no_longer_reached": sorted(reach_before - reach_after), "protected_still_reached": protected_reached,
                   "still_connected": connected}]
    verdict = "contains" if not protected_reached else "does_not_contain"
    return _envelope(after, tool="whatif", via=f"GRAPH.COPY → cut {cuts} → algo.BFS + algo.WCC on {name}", kind="whatif",
                     about=[f] + prot, summary=f"{verdict}: protected still reached {protected_reached}; connected {connected}",
                     extra={"verdict": verdict, "branch": name})


class _FutureArg(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    cut_edges: list[list[str]] = Field(default_factory=list, max_length=500)
    removes_origin: bool = False


FUTURE_MAX = 8        # candidates simulated per plan; the rest are listed "unknown: not simulated"
FUTURE_MAX_CUTS = 10  # cut edges per candidate branch
FUTURE_MAX_SYMS = 30  # symptoms one prediction reads (Q-FUTURE-1 LIMIT 50 covers symptoms + protected)
FUTURE_MAX_PROT = 20


@_guard
def futures(origin_id: str, onset: int, now: int, candidates: list[dict], symptom_ids: list[str],
            protect_ids: list[str], keep_connected_ids: list[str]) -> dict[str, Any]:
    """Futures: the predicted outcome of each containment candidate BEFORE anyone approves one. A candidate
    that cuts edges gets its own GRAPH.COPY branch with them removed; one that cuts nothing reads the run graph
    (removing the origin's fault, or changing nothing, leaves the topology as it is). On each, Q-FUTURE-1 predicts the
    origin's residual at every symptom and protected node (measured excess × path transfer over what is left: the
    gate's upper-bound model, never the scenario's injected effect), and Q-WHATIF-2 (algo.WCC) says which services
    lose their path to the protected entry. A symptom is predicted back in band by VERIFY's own rule (`in_band` on
    its baseline windows): `contains` when every symptom is, `does_not_contain` when one is not, `unknown` when a
    residual is unmeasured. Branches are deleted afterwards. Internal tool (writes branch graphs)."""
    from ..agent.datatools import ABS_TOL, band_from, in_band
    from ..graph import copy as gcopy
    from ..graph.tenant import whatif_graph

    b = context.current()
    o = _IdArg(id=origin_id).id
    every = [_FutureArg(**x) for x in candidates]
    cands = every[:FUTURE_MAX]
    syms = [_IdArg(id=s).id for s in symptom_ids]
    too_many_syms = len(syms) > FUTURE_MAX_SYMS  # a prediction that skipped a symptom could be a false assurance
    syms = syms[:FUTURE_MAX_SYMS]
    prot_all = [_IdArg(id=p).id for p in protect_ids]
    prot = prot_all[:FUTURE_MAX_PROT]
    keep = [_IdArg(id=k).id for k in keep_connected_ids][:20]
    iw = weights()["intake"]
    params = {"origin": o, "targets": sorted(set(syms + prot)), "since": int(onset), "until": int(now),
              "base_since": int(onset) - int(iw["baseline_min"]) * 60_000,
              "base_until": int(onset) - int(iw["baseline_gap_min"]) * 60_000}
    if not cands:
        raise ValueError("futures needs at least one candidate")
    db = client.engine()
    results, rows = [], []
    def unknown_row(cand: _FutureArg, why: str) -> dict:
        return {"key": cand.key, "cuts": cand.cut_edges, "removed_edges": 0, "removes_origin": cand.removes_origin,
                "assumed": False, "predicted": "unknown", "line": f"unknown: {why}", "origin": o, "origin_excess": None,
                "symptoms": [], "protected_residual": {}, "exposed": [], "loses_entry_path": [], "branch": None}

    for cand in every[FUTURE_MAX:]:  # said, never silently dropped
        rows.append(unknown_row(cand, f"not simulated (more than {FUTURE_MAX} candidates in one plan)"))
    for cand in cands:
        if too_many_syms:
            rows.append(unknown_row(cand, f"more than {FUTURE_MAX_SYMS} symptoms; one prediction reads at most that many"))
            continue
        if len(cand.cut_edges) > FUTURE_MAX_CUTS:
            rows.append(unknown_row(cand, f"{len(cand.cut_edges)} cut edges (a branch cuts at most {FUTURE_MAX_CUTS})"))
            continue
        cuts = [(_IdArg(id=u).id, _IdArg(id=v).id) for u, v in cand.cut_edges]
        p = params | {"removes_origin": bool(cand.removes_origin)}
        removed, comp = 0, {}
        if cuts:
            name = whatif_graph(b.tenant, f"{b.run_id or 'ext'}_fut_{hashlib.sha256(repr(sorted(cuts)).encode()).hexdigest()[:10]}")
            gcopy.delete_if_exists(db, name)
            try:
                gcopy.copy_graph(db, b.graph, name)
                removed = writes.remove_flow_edges(db.select_graph(name), cuts)  # this candidate's own cuts
                branch = RO(b.tenant, name)
                r = branch.run("Q-FUTURE-1", p)
                if keep and prot:
                    wcc = branch.run("Q-WHATIF-2", {"ids": prot[:1] + keep})
                    results.append(wcc)
                    comp = {x["id"]: x["componentId"] for x in wcc.rows}
            finally:
                gcopy.delete_if_exists(db, name)
        else:
            name = b.graph
            r = _ro().run("Q-FUTURE-1", p)
        results.append(r)
        if r.truncated:
            rows.append(unknown_row(cand, "Q-FUTURE-1 truncated at its LIMIT"))
            continue
        by = {x["target"]: x for x in r.rows}
        per, bad, unknown = [], [], []
        for t in syms:
            x = by.get(t)
            vals = [float(v) for v in (x or {}).get("base_vals") or []]
            if x is None or x["residual"] is None or not vals:
                unknown.append(t)
                per.append({"id": t, "residual": None if x is None else x["residual"], "ok": None,
                            "why": "no row" if x is None else "no baseline windows" if not vals else
                                   "excess unmeasured" if x["excess"] is None else
                                   "more paths than the bound reads" if (x["paths"] or 0) > 1000 else "an edge without cap"})
                continue
            base, band = sum(vals) / len(vals), band_from(vals)
            res = float(x["residual"])
            ok = in_band(base + res, base, band)
            per.append({"id": t, "residual": round(res, 6), "baseline": round(base, 5), "band": band,
                        "predicted": round(base + res, 5), "ok": ok, "paths": x["paths"], "transfer": x["transfer"],
                        "is_origin": x["is_origin"]})
            if not ok:
                bad.append(t)
        predicted = "does_not_contain" if bad else "unknown" if unknown else "contains"
        assumed = bool(cand.removes_origin)  # residual 0 by assumption (the gate's cause is the cause), not a measurement
        lost = sorted(k for k in keep if comp and comp.get(k) != comp.get(prot[0])) if comp else []
        prot_res = {t: by[t]["residual"] for t in prot if t in by and t not in syms}
        # protected nodes the origin can still reach with a residual worth naming (the symptoms decide `predicted`;
        # an exposed protected node is said and orders options, it never flips the prediction)
        exposed = sorted(t for t, v in prot_res.items() if v is not None and float(v) >= ABS_TOL)
        excess = next((x["excess"] for x in r.rows), None)
        line = ("contains if the confirmed cause is the cause (removing the origin's fault; assumed, not measured)"
                if predicted == "contains" and assumed else
                "contains: every symptom predicted back in band" if predicted == "contains" else
                "does not contain: " + ", ".join(f"{d['id']} residual {d['residual']:.4f} over its band"
                                                  for d in per if d["ok"] is False) if predicted == "does_not_contain"
                else "unknown: " + ", ".join(f"{d['id']} ({d['why']})" for d in per if d["ok"] is None))
        rows.append({"key": cand.key, "cuts": [list(c) for c in cuts], "removed_edges": removed,
                     "removes_origin": cand.removes_origin, "assumed": assumed, "predicted": predicted, "line": line,
                     "origin": o, "origin_excess": excess, "symptoms": per, "protected_residual": prot_res,
                     "exposed": exposed, "exposed_scope": (f"read on {len(prot)} of {len(prot_all)} protected nodes"
                                                           if len(prot_all) > len(prot) else None),
                     "loses_entry_path": lost, "branch": name if cuts else None})
    if not results:  # nothing simulated (every candidate over a cap): the rows say why
        return {"rows": rows, "futures": {x["key"]: {k: x[k] for k in ("predicted", "line", "exposed", "loses_entry_path")}
                                          for x in rows}, "summary": "; ".join(f"{x['key']}: {x['predicted']}" for x in rows)}
    r = _combine(results, rows) if len(results) > 1 else results[0]
    r.rows = rows
    return _envelope(r, tool="futures",
                     via=f"per candidate: GRAPH.COPY branch with its cut edges removed → Q-FUTURE-1 (measured excess × "
                         f"path transfer) + algo.WCC; origin {o}", kind="whatif", about=[o] + syms + prot,
                     summary="; ".join(f"{x['key']}: {x['predicted']}" for x in rows),
                     extra={"futures": {x["key"]: {k: x[k] for k in ("predicted", "line", "exposed", "loses_entry_path")}
                                        for x in rows}})


@_guard
def similar_incidents(incident_id: str, now: int) -> dict[str, Any]:
    """Recall: past incidents near this one in the FalkorDB vector index AND sharing a Symptom node with it
    (vector seed → structural confirmation). Similarity, recency (half-life from weights.yaml) and salience are
    separate columns, all computed in the query."""
    from ..memory.learning import ago

    a = _IdArg(id=incident_id)
    m = weights()["memory"]
    hl = float(m["half_life_days"]) * 86_400_000
    r = _ro().run("Q-MEM-1", {"current": a.id, "now": int(now), "half_life_ms": hl,
                              "w_recency": float(m["recall_recency_w"])})
    for x in r.rows:   # what an agent can act on (recent-work recall): when it was last seen and what fixed it
        fixes = sorted(set(x.get("fixes") or []))
        x["line"] = (f"last seen {ago(x.get('age_ms'))}; "
                     + (f"fixed by {', '.join(fixes)}, verified APPLIED" if fixes else "no verified fix recorded")
                     + f" (similarity {float(x['similarity']):.2f}, recency {float(x['recency']):.2f})")
    return _envelope(r, tool="similar_incidents", via="db.idx.vector.queryNodes(Incident.embedding) → shared (:Symptom) "
                     f"→ ranked by similarity and recency (w_recency {float(m['recall_recency_w'])})",
                     kind="recall", about=[a.id] + [x["id"] for x in r.rows],
                     summary=f"{len(r.rows)} structurally confirmed precedents: " + ", ".join(x["id"] for x in r.rows[:3]))


@_guard
def incident_families(incident_id: str) -> dict[str, Any]:
    """Incident families: algo.labelPropagation over incidents, symptoms and the components their causes changed
    (read-only on the tenant graph). The family that holds `incident_id` comes first (mine=true)."""
    a = _IdArg(id=incident_id)
    r = _ro().run("Q-MEM-6", {"inc": a.id})
    mine = next((x for x in r.rows if x["mine"]), None)
    return _envelope(r, tool="incident_families", via="algo.labelPropagation(Incident, Symptom, Deploy, component)",
                     kind="recall", about=[a.id], summary=f"{len(r.rows)} families; {a.id} is in "
                     + (f"one of {mine['size']}" if mine else "none yet"))


@_guard
def runbook_for(ids: list[str]) -> dict[str, Any]:
    """Current runbooks for components/symptoms (procedural memory; derived runbooks first)."""
    xs = [_IdArg(id=i).id for i in ids][:20]
    r = _ro().run("Q-MEM-3", {"ids": xs})
    return _envelope(r, tool="runbook_for", via="(:Runbook)-[:RUNBOOK_FOR]->(component|symptom)", kind="recall",
                     about=xs[:5], summary=f"{len(r.rows)} runbooks")


class _RepairTargets(BaseModel):
    chain: list[str] = Field(default_factory=list, max_length=20)


@_guard
def repair_targets(chain: list[str] | None = None) -> dict[str, Any]:
    """Where a measured data repair can be applied, for the run this call belongs to (ONE query, Q-REPAIR-TARGETS):
    the row-share measurements the run recorded anomalous, each joined to the Transform the lineage graph says WRITES
    that table (a source table nobody builds is left out), ordered nearest the confirmed cause first along the
    gate's proof path (`chain`). The loop asks `unit_shift_check` about the first one; a human still approves the
    exact diff."""
    a = _RepairTargets(chain=chain or [])
    b = context.current()
    if not b.run_id:
        return {"error": "invalid arguments: repair_targets needs a run to read the measurements of"}
    chain_ids = [_IdArg(id=c).id for c in a.chain]
    r = _ro().run("Q-REPAIR-TARGETS", {"run": b.run_id, "chain": chain_ids})
    return _envelope(r, tool="repair_targets", kind="lineage",
                     via="(:Run)-[:HAS_TOOL_CALL]->()-[:PRODUCED_EVIDENCE]->(:Evidence {anomalous})-[:ABOUT]->(:Table)<-[:WRITES]-(:Transform)",
                     about=[x["table"] for x in r.rows] + [x["transform"] for x in r.rows],
                     summary=(f"{len(r.rows)} anomalous tables a transform builds; nearest the cause: {r.rows[0]['table']} "
                              f"(written by {r.rows[0]['transform']})" if r.rows else "no anomalous table a transform builds"))


class _RunbooksAbout(BaseModel):
    component_id: str = Id
    symptom_kinds: list[str] = Field(default_factory=list, max_length=8)


@_guard
def runbooks_about(component_id: str, symptom_kinds: list[str] | None = None) -> dict[str, Any]:
    """Company brain: which runbook to follow for a component, in ONE query (Q-RUNBOOK-ABOUT): the current runbooks
    written for it or for one of its symptoms, then those for a component one failure hop away (`dist` 1). Runbooks
    for a symptom kind in `symptom_kinds` (latency, error_rate, lag, kpi_jump) rank first; derived runbooks (learned
    from fixes that worked) carry how often they worked (`worked`)."""
    a = _RunbooksAbout(component_id=component_id, symptom_kinds=symptom_kinds or [])
    kinds = sorted({k for k in a.symptom_kinds if re.fullmatch(r"[a-z_]{2,20}", k)})
    r = _ro().run("Q-RUNBOOK-ABOUT", {"id": a.component_id, "kinds": kinds})
    near = sum(1 for x in r.rows if x["dist"])
    return _envelope(r, tool="runbooks_about", kind="recall", about=[a.component_id] + [x["id"] for x in r.rows[:5]],
                     via=f"(:Runbook)-[:RUNBOOK_FOR]->({a.component_id} | its Symptom | one PROPAGATES_TO hop)",
                     summary=f"{len(r.rows) - near} runbooks for {a.component_id}, {near} one hop away")


# ------------------------------------------------------------------ learned remediation ordering + residue (advisory)
class _Remedy(BaseModel):
    incident_id: str = Id
    symptom_ids: list[str] | None = Field(None, max_length=20)
    incident_ids: list[str] | None = Field(None, max_length=50)


@_guard
def remedy_stats(incident_id: str, symptom_ids: list[str] | None = None,
                 incident_ids: list[str] | None = None) -> dict[str, Any]:
    """Learned remediation ordering: how each fix kind fared on past incidents that share a Symptom node with this
    one (default: the incident's own symptoms, read with Q-INC-SYM) or are listed in `incident_ids` (recalled
    precedents, a labelPropagation family). Successes = RESOLVED_BY an APPLIED action, failures = a NOT_APPLIED
    action, rate = (s+1)/(s+f+2): all computed in Cypher (Q-REM-1). Per kind (target '*'), and per flag for
    flip_flag. It may only REORDER options; it never adds or removes one and never touches the gate."""
    a = _Remedy(incident_id=incident_id, symptom_ids=symptom_ids, incident_ids=incident_ids)
    ro = _ro()
    syms = [_IdArg(id=s).id for s in a.symptom_ids] if a.symptom_ids is not None else \
        [r["id"] for r in ro.run("Q-INC-SYM", {"inc": a.incident_id}).rows]
    incs = [_IdArg(id=i).id for i in (a.incident_ids or [])]
    r = ro.run("Q-REM-1", {"inc": a.incident_id, "symptoms": syms, "incidents": incs})
    basis = "past incidents sharing a symptom with this one" + (" or listed as its precedents" if incs else "")
    top = r.rows[0] if r.rows else None
    return _envelope(r, tool="remedy_stats", via="(this)-[:HAS_SYMPTOM]->(:Symptom)<-[:HAS_SYMPTOM]-(past)"
                     "-[:RESOLVED_BY|ATTEMPTED]->(:Action) → (s+1)/(s+f+2)", kind="remedy", about=[a.incident_id],
                     summary=(f"{len(r.rows)} fix-kind outcomes on {basis}; best {top['kind']} {top['successes']}/{top['n']}"
                              if top else f"no fix outcomes recorded on {basis}"),
                     extra={"symptoms": syms, "precedents": incs, "basis": basis})


@_guard
def residue_check(incident_id: str, cause_id: str) -> dict[str, Any]:
    """Residue check (ADVISORY; never changes a gate outcome): of the components this incident's runs measured
    anomalous (the same Evidence.anomalous the gate reads), which are downstream of the confirmed cause over the
    G2 relation set (CHANGED|GATES|PROPAGATES_TO, ≤ 8 hops; Q-RESIDUE-1)? Those that are not are listed as
    "another fault may be active"."""
    a, c = _IdArg(id=incident_id), _IdArg(id=cause_id)
    r = _ro().run("Q-RESIDUE-1", {"inc": a.id, "cause": c.id})
    explained = [x["id"] for x in r.rows if x["explained"]]
    rest = [x["id"] for x in r.rows if not x["explained"]]
    n = len(r.rows)
    verdict = "no_measurements" if not n else ("residue" if rest else "explained")
    summary = (f"no anomalous measurement recorded for {a.id}" if not n else
               f"the confirmed cause {c.id} explains {len(explained)} of {n} anomalous components"
               + (f"; another fault may be active: {', '.join(rest)}" if rest else ""))
    if r.truncated:
        summary += " (measurement list truncated at the template LIMIT: the count is a lower bound)"
    return _envelope(r, tool="residue_check", via=f"({c.id})-[:CHANGED|GATES|PROPAGATES_TO*1..8]->(measured anomalous)",
                     kind="residue", about=[c.id] + rest, summary=summary,
                     extra={"advisory": True, "verdict": verdict, "explained": explained, "unexplained": rest,
                            "k": len(explained), "n": n, "summary": summary})


# ------------------------------------------------------------------ obligation clock
def breach_minutes(row: dict, w: dict | None = None) -> float | None:
    """Minutes until an SLO's error budget runs out at the current burn: remaining × window minutes / burn (numbers
    from code, weights.yaml `obligation`). 0 when the budget is already spent and still burning. None when there is no
    current measurement, or the burn is sustainable (≤ sustainable_burn: the promise holds as the window rolls)."""
    w = w or weights()["obligation"]
    burn, remaining = row.get("burn"), row.get("budget_remaining")
    if burn is None or remaining is None or float(burn) <= float(w["sustainable_burn"]):
        return None
    return round(max(0.0, float(remaining)) * int(row["window_days"]) * 1440 / float(burn), 1)


def slo_status(row: dict, w: dict | None = None) -> str:
    w = w or weights()["obligation"]
    if row.get("burn") is None:
        return "unmeasured"
    if float(row["budget_remaining"]) <= 0:
        return "breached"
    return "burning" if float(row["burn"]) > float(w["sustainable_burn"]) else "within_budget"


def clock_verdict(slos: list[dict], customers: list[dict], w: dict | None = None) -> dict:
    """The one decision the clock makes: page now (urgent) when the soonest projected SLO breach is under
    `obligation.page_within_min`; None (unknown) when every SLO in the blast radius is unmeasured. Deterministic,
    from the numbers the templates returned."""
    w = w or weights()["obligation"]
    page = float(w["page_within_min"])
    timed = [s for s in slos if s.get("breach_in_min") is not None]
    soonest = min(timed, key=lambda s: (s["breach_in_min"], s["slo"])) if timed else None
    unmeasured = [s for s in slos if s.get("burn") is None]
    # urgent is None (unknown) when every SLO in the blast radius is unmeasured: no current telemetry is not "fine"
    urgent: bool | None = bool(soonest and soonest["breach_in_min"] < page)
    revenue = float(customers[0]["revenue_at_risk"]) if customers else 0.0
    n_customers = int(customers[0]["customers_reached"]) if customers else 0
    if soonest is None and slos and len(unmeasured) == len(slos):
        urgent = None
        reason = (f"unmeasured: none of the {len(slos)} SLO{'s' if len(slos) != 1 else ''} in the blast radius has current "
                  "telemetry, so the time to breach is unknown")
    elif soonest is None:
        reason = ("no SLO in the blast radius is burning faster than its budget allows" if slos
                  else "no SLO covers the failing component or its blast radius")
        if unmeasured:
            reason += f" ({len(unmeasured)} of {len(slos)} unmeasured)"
    else:
        reason = (f"{soonest['slo']} ({soonest['service']}) runs out of error budget in ~{soonest['breach_in_min']:.0f} min "
                  f"at {float(soonest['burn']):.1f}x burn ({float(soonest['budget_remaining']):.0%} of budget left)")
        reason += f"; under the {page:.0f}-min paging line" if urgent else f"; beyond the {page:.0f}-min paging line"
    if n_customers:
        reason += f"; {n_customers} customer{'s' if n_customers != 1 else ''} reached, {revenue:,.0f} MRR at risk"
    return {"urgent": urgent, "reason": reason, "page_within_min": page,
            "breach": {k: soonest[k] for k in ("slo", "service", "breach_in_min", "burn", "budget_remaining")} if soonest else None,
            "revenue_at_risk": revenue, "customers_reached": n_customers}


@_guard
def obligation_clock(target_id: str, now: int) -> dict[str, Any]:
    """Who are we failing, and how long until we break a promise? For the failing component and its blast radius
    (algo.BFS over PROPAGATES_TO): every SLO with its current error rate, burn rate and budget remaining (Q-OBL-SLO,
    from the MetricWindow telemetry, in Cypher) and the time to breach (code, weights.yaml `obligation`); every
    customer reached through the failure, counted once however many paths reach them, with the nearest path, and
    the revenue at risk = sum of their MRR (Q-OBL-CUST). `urgent` = the soonest breach is under the paging line."""
    a = _AtArg(id=target_id, at=now)
    w = weights()["obligation"]
    ro = _ro()
    slo = ro.run("Q-OBL-SLO", {"id": a.id, "now": a.at, "current_since": a.at - int(w["current_min"]) * 60_000})
    cust = ro.run("Q-OBL-CUST", {"id": a.id})
    slos = [{**r, "breach_in_min": breach_minutes(r, w), "status": slo_status(r, w)} for r in slo.rows]
    verdict = clock_verdict(slos, cust.rows, w)
    obligated = sorted({s["service"] for s in slos} | {n for c in cust.rows for n in c["through"]})
    head = _combine([slo, cust], slos)
    summary = verdict["reason"] + (" (URGENT: page now)" if verdict["urgent"] else "")
    if head.truncated:
        summary += " (truncated at the template LIMIT: more SLOs or customers may be affected)"
    return _envelope(head, tool="obligation_clock", via=f"algo.BFS(({a.id}), 8, 'PROPAGATES_TO') → (:SLO)-[:FOR]->(n), "
                     "(:MetricWindow)-[:WINDOW_OF]->(n), (:Customer)-[:CONSUMES]->(n)", kind="obligation",
                     about=[a.id] + [s["slo"] for s in slos[:3]] + [c["customer"] for c in cust.rows[:3]], summary=summary,
                     value=verdict["breach"]["breach_in_min"] if verdict["breach"] else None,
                     extra={**verdict, "customers": cust.rows, "obligated": obligated, "now": a.at})


# ------------------------------------------------------------------ schema introspection
@_guard
def graph_schema() -> dict[str, Any]:
    """The live schema of this tenant's graph: node labels with counts, property keys per label (bounded sample,
    with how many nodes carry each) and indexes; relationship types with counts and their (from-label, to-label)
    pairs. db.meta.stats + bounded scans + db.indexes, all GRAPH.RO_QUERY. Read it before writing
    run_cypher_readonly; it is a map of the graph, never evidence for a claim (no path, no claim)."""
    from ..graph.schema_introspect import introspect

    schema, results = introspect(_ro())
    head = _combine(results, schema["labels"])
    t = schema["totals"]
    return _envelope(head, tool="graph_schema", via="db.meta.stats + bounded edge/node scans + db.indexes", kind="schema",
                     about=[], summary=(f"{t['labels_present']} labels, {t['rel_types_present']} relationship types, "
                                        f"{t['nodes']} nodes, {t['edges']} edges"),
                     extra={"relationships": schema["relationships"], "totals": t, "complete": schema["complete"],
                            "queries": [{"template": r.template_id, "cypher": r.cypher, "ms": round(r.ms, 2),
                                         "digest": r.digest, "truncated": r.truncated} for r in results]})


class _T2C(BaseModel):
    query: str = Field(..., min_length=10, max_length=4000)
    failed_template: str = Field(..., pattern=r"^Q-[A-Z0-9-]+$")
    reason: str = Field(..., min_length=10, max_length=300)


@_guard
def run_cypher_readonly(query: str, failed_template: str, reason: str) -> dict[str, Any]:
    """LAST RESORT. Read-only Cypher when no template answers. Name the template that could not answer
    (`failed_template`) and why. Guarded: no writes, comments, GRAPH.* or non-allowlisted CALLs; bounded
    variable-length paths (≤8); LIMIT ≤ 100; EXPLAIN-checked; GRAPH.RO_QUERY as the read-only user, 3 s timeout.
    Recorded as evidence via 'text2cypher'."""
    from ..graph.guard import GuardError

    a = _T2C(query=query, failed_template=failed_template, reason=reason)
    try:
        load(a.failed_template)
    except KeyError:
        return {"error": f"unknown template {a.failed_template}: try the templates first"}
    try:
        r = _ro().run_guarded(a.query)
    except GuardError as e:
        return {"error": f"guard rejected the query: {e}"}
    return _envelope(r, tool="run_cypher_readonly", via="text2cypher", kind="text2cypher", about=[],
                     summary=f"text2cypher ({len(r.rows)} rows) after {a.failed_template}: {a.reason[:80]}",
                     extra={"failed_template": a.failed_template, "reason": a.reason})


# ------------------------------------------------------------------ on-call, read-only
class _OnCallNow(BaseModel):
    at: int | None = Field(None, ge=0, le=4_102_444_800_000)


@_guard
def oncall_now(at: int | None = None) -> dict[str, Any]:
    """Who is on call now (or at epoch-ms `at`): every team with the active person whose ON_CALL shift covers that
    time and the shift window (Q-ONCALL-NOW). A team nobody covers comes back with person null."""
    a = _OnCallNow(at=at)
    t = int(time.time() * 1000) if a.at is None else int(a.at)
    r = _ro().run("Q-ONCALL-NOW", {"now": t})
    covered = sum(1 for x in r.rows if x["person"])
    return _envelope(r, tool="oncall_now", via="(:Person)-[:ON_CALL {from, to}]->(:Team)", kind="people",
                     about=[x["team"] for x in r.rows[:5]],
                     summary=f"{covered} of {len(r.rows)} teams have someone on call at {t}", extra={"at": t})


class _Pages(BaseModel):
    status: str = Field("open", pattern=r"^(open|all|sent|delivery_failed|acked|escalated|resolved|superseded)$")
    incident_id: str | None = Field(None, min_length=1, max_length=160)


@_guard
def pages(status: str = "open", incident_id: str | None = None) -> dict[str, Any]:
    """The pager of this graph: pages to people about incidents (Q-PAGES), newest first, each with who it PAGES, its
    status (sent, delivery_failed, acked, escalated, resolved, superseded), its ack deadline, who acknowledged it and the
    page it ESCALATED_TO. status 'open' = still waiting for an ack; 'all' = every page."""
    a = _Pages(status=status, incident_id=incident_id)
    sts = [] if a.status == "all" else (["sent", "delivery_failed"] if a.status == "open" else [a.status])
    r = _ro().run("Q-PAGES", {"incident": a.incident_id or "", "statuses": sts, "now": int(time.time() * 1000)})
    overdue = sum(1 for x in r.rows if x["overdue"])
    return _envelope(r, tool="pages", via="(:Page)-[:PAGES]->(:Person), (:Page)-[:FOR]->(:Incident)", kind="oncall",
                     about=[x["id"] for x in r.rows[:5]],
                     summary=f"{len(r.rows)} {a.status} page(s)" + (f", {overdue} past their ack deadline" if overdue else ""))


class _Stats(BaseModel):
    days: float = Field(7.0, gt=0, le=90)


@_guard
def oncall_stats(days: float = 7.0) -> dict[str, Any]:
    """On-call numbers of this graph over the last `days`, computed in Cypher (Q-ONCALL-STATS): pages sent and people
    paged, MTTA (first page to first ack, per incident) and MTTR (opened to RESOLVED, per incident), and incidents
    resolved under a standing contract (nobody paged)."""
    a = _Stats(days=days)
    r = _ro().run("Q-ONCALL-STATS", {"since": int(time.time() * 1000) - int(a.days * 86_400_000)})
    row = r.rows[0] if r.rows else {}
    acked, resolved = int(row.get("acked_incidents") or 0), int(row.get("resolved_incidents") or 0)
    mtta = round(float(row.get("ack_ms_sum") or 0) / acked) if acked else None
    mttr = round(float(row.get("resolve_ms_sum") or 0) / resolved) if resolved else None
    return _envelope(r, tool="oncall_stats", via="(:Page)-[:PAGES]->(:Person), (:Person)-[:ACKED]->(:Page), StageEvents",
                     kind="oncall", about=[], summary=(f"{int(row.get('pages') or 0)} page(s) to {len(row.get('people') or [])} "
                                                       f"person(s); MTTA {mtta} ms over {acked}, MTTR {mttr} ms over "
                                                       f"{resolved}; {int(row.get('under_contract') or 0)} under contract"),
                     extra={"days": a.days, "mtta_ms": mtta, "mttr_ms": mttr, "people_paged": len(row.get("people") or []),
                            "handled_under_contract": int(row.get("under_contract") or 0)})


# ------------------------------------------------------------------ learning, read-only, from the on-call home graph
class _Learned(BaseModel):
    family_id: str = Id
    now: int | None = Field(None, ge=0, le=4_102_444_800_000)


def _learn_ro() -> tuple[RO, str]:
    from ..memory import learning

    b = context.current()
    g = learning.home(b.tenant, ensure=False)
    return RO(b.tenant, g), g


@_guard
def learned_preferences(family_id: str, now: int | None = None) -> dict[str, Any]:
    """What the team taught Faultline about one incident family (the component its confirmed cause changed): per
    action kind, the recency-decayed, Beta-smoothed preference from trusted approvals and rejections (Q-LEARN-PREF),
    the guidelines rejections proposed and humans promoted (Q-LEARN-GUIDE), and exact fixes approved and verified
    APPLIED often enough to suggest a standing approval (Q-LEARN-SUGGEST, minus those an active contract already covers,
    Q-CONTRACT-MATCH). PLAN reads it to reorder options within one predicted-future class; it never adds, removes or
    enables an option and never touches the gate."""
    from ..memory import learning

    a = _Learned(family_id=family_id, now=now)
    t = int(time.time() * 1000) if a.now is None else int(a.now)
    ro, g = _learn_ro()
    hl = learning.half_life_ms()
    k = int(weights()["learn"]["contract_suggest_k"])
    prefs = ro.run("Q-LEARN-PREF", {"family": a.family_id, "now": t, "half_life_ms": hl})
    guides = ro.run("Q-LEARN-GUIDE", {"family": a.family_id, "statuses": ["proposed", "active"]})
    sugg = ro.run("Q-LEARN-SUGGEST", {"family": a.family_id, "k": k})
    covered = [ro.run("Q-CONTRACT-MATCH", {"family": a.family_id, "kind": x["action_kind"], "params_hash": x["params_hash"],
                                           "now": t}) for x in sugg.rows]
    suggestions = [{**x, "covered": bool(c.rows), "covered_by": c.rows[0]["id"] if c.rows else None}
                   for x, c in zip(sugg.rows, covered)]
    res = _combine([prefs, guides, sugg, *covered], prefs.rows)
    n_family = max([int(x.get("n_family") or 0) for x in prefs.rows] or [0])
    return _envelope(res, tool="learned_preferences", kind="learned", about=[a.family_id],
                     via=f"(:Preference)/(:Guideline) recomputed from trusted (:LearnEvent)s in {g}, decay half-life "
                         f"{float(weights()['learn']['half_life_days']):g} d",
                     summary=(f"{n_family} recorded choice(s) for {a.family_id}: " +
                              ", ".join(f"{x['action_kind']} {float(x['pref']):.2f}" for x in prefs.rows[:3])
                              if prefs.rows else f"nothing learned yet for {a.family_id}")
                     + (f"; {len(guides.rows)} guideline(s)" if guides.rows else "")
                     + (f"; {sum(1 for x in suggestions if not x['covered'])} contract suggestion(s)" if suggestions else ""),
                     extra={"family": a.family_id, "now": t, "half_life_ms": hl, "home": g, "n_family": n_family,
                            "guidelines": guides.rows, "suggestions": suggestions})


class _LearnedTarget(BaseModel):
    target_id: str = Id
    now: int | None = Field(None, ge=0, le=4_102_444_800_000)


@_guard
def learned_responders(target_id: str, now: int | None = None) -> dict[str, Any]:
    """Who actually responds when this component's incidents page: active people with a RESPONDED edge to it,
    recomputed from their trusted acknowledgements, approvals and verified fixes with recency decay (Q-LEARN-RESP),
    each with its counts, mean ack delay and last response. ROUTE reads it: the top learned responder (learn.resp_min_n
    responses) is paged in the first wave, before the rota, who is still paged."""
    from ..memory import learning

    a = _LearnedTarget(target_id=target_id, now=now)
    t = int(time.time() * 1000) if a.now is None else int(a.now)
    ro, g = _learn_ro()
    r = ro.run("Q-LEARN-RESP", {"target": a.target_id, "now": t, "half_life_ms": learning.half_life_ms()})
    return _envelope(r, tool="learned_responders", kind="people", about=[a.target_id] + [x["person"] for x in r.rows[:3]],
                     via=f"(:Person)-[:RESPONDED]->(component) in {g}, recomputed from trusted acks, approvals and fixes",
                     summary=("; ".join(f"{x['person']} {float(x['score']):.2f} ({x['n']} response(s))" for x in r.rows[:3])
                              if r.rows else f"no learned responder for {a.target_id} yet"),
                     extra={"target": a.target_id, "now": t, "home": g})


class _Gaps(BaseModel):
    status: str = Field("open", pattern=r"^(open|dismissed|all)$")


@_guard
def knowledge_gaps(status: str = "open") -> dict[str, Any]:
    """What the company brain could not answer: questions trusted users asked that were refused or found nothing
    documented, how often and when (Q-KGAP-1), with the teams owning what each was about: who should document it."""
    a = _Gaps(status=status)
    ro, g = _learn_ro()
    sts = ["open", "dismissed"] if a.status == "all" else [a.status]
    r = ro.run("Q-KGAP-1", {"statuses": sts})
    return _envelope(r, tool="knowledge_gaps", kind="knowledge", about=[x["id"] for x in r.rows[:5]],
                     via=f"(:KnowledgeGap) recomputed from trusted unanswered brain questions in {g}",
                     summary=f"{len(r.rows)} {a.status} knowledge gap(s)" + (
                         f"; most asked: {r.rows[0]['text'][:60]!r} ({r.rows[0]['n']}×)" if r.rows else ""),
                     extra={"home": g})


@_guard
def learned_state() -> dict[str, Any]:
    """What Faultline has learned from the people using it: how many trusted learning events of each kind, from
    how many people (Q-LEARN-COUNTS), and the most recent ones (Q-LEARN-EVENTS). Read-only; trusted actors only."""
    ro, g = _learn_ro()
    counts = ro.run("Q-LEARN-COUNTS", {})
    recent = ro.run("Q-LEARN-EVENTS", {})
    res = _combine([counts, recent], recent.rows)
    return _envelope(res, tool="learned_state", kind="learned", about=[x["id"] for x in recent.rows[:5]],
                     via=f"(:LearnEvent) in {g}",
                     summary=(", ".join(f"{x['kind']} {x['n']}" for x in counts.rows) or "nothing learned yet"),
                     extra={"counts": counts.rows, "home": g})


TOOLS: dict[str, Callable[..., dict]] = {f.__name__: f for f in (
    run_cypher_readonly, preflight_change, session_history, notify_set, alert_coverage, owner_at, component_timeline,
    beliefs_at, topology_at, knowledge_health, hidden_coupling, resolve_entity, people_who_worked_on, missing_guardrails, decisions_about,
    route_question,
    similar_incidents, incident_families, runbook_for, runbooks_about, repair_targets,
    remedy_stats, residue_check, obligation_clock,
    whatif, futures,
    who_fixes, escalation_tree,
    rank_causes, group_alerts,
    find_entities, service_context, upstream_scope, blast_radius, chokepoints, upstream_suspects, window_changes,
    causal_paths, impact_bound, upstream_explained, context_pack, reachable_from_changes, containment_cut, connectivity_check, column_lineage,
    owners_of, bus_factor, trace_decision, decision_check,
    change_details, diff_summary,
    graph_schema,
    oncall_now, pages, oncall_stats,
    learned_preferences, learned_responders, knowledge_gaps, learned_state,
    remember, recall_notes, search_knowledge,
)}
