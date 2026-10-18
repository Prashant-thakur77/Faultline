"""Faultline API v2 (FastAPI). Reads go through FalkorDB read-only templates (graph/ro.py); writes through
graph/writes.py; the only process state is the handle of an in-flight background run. Fails loudly: FalkorDB
down or a graph not ready → 503 with the reason (the UI shows a banner), never fake data. Public demo mode
(FAULTLINE_PUBLIC) adds run tokens, clean-room forget/preflight and no anonymous LLM (SECURITY.md).

Routes (full contract: docs/API.md)
  status · tenants · scenarios · POST scenarios/{sid}/run · incidents · incidents/{inc} · incidents/{inc}/events (SSE)
  graph · incidents/{inc}/blast · incidents/{inc}/plan · POST incidents/{inc}/choose · POST incidents/{inc}/approve
  POST incidents/{inc}/reject · incidents/{inc}/contrast · memory/overview · brain/decisions[/{did}]
  brain/ownership[/{cid}] · brain/guardrails
  POST brain/ask · brain/history · POST memory/forget · GET|POST preflight
  templates/{tid} · POST templates/{tid}/profile · POST templates/{tid}/run · POST demo/rearm
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import logging
import threading
import time
import uuid
from collections import defaultdict
from typing import Any

import anyio
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import __version__
from .config import settings
from .graph import client as gclient
from .graph import copy as gcopy
from .graph import writes
from .graph.algo import registry
from .graph.errors import GraphError, GraphNotReady, GraphUnavailable
from .graph.ro import RO, profile
from .graph.templates import catalogue, load
from .graph.tenant import audit_graph, check_tenant, graph_belongs_to, tenant_graph

app = FastAPI(title="Faultline", version="0.2.0")
_ORIGINS = [o.strip() for o in settings.faultline_cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])

_jobs: dict[str, dict] = {}            # in-flight background runs (handles only; state lives in the graph)
_jobs_lock = threading.Lock()          # the MAX_RUNNING check, eviction and insertion are one critical section
_rate: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()
_streams: dict[str, int] = defaultdict(int)  # open SSE streams per client (and "*" = all)
_streams_lock = threading.Lock()
MAX_RUNNING = 4                              # concurrent scenario runs (each copies a graph)
MAX_STREAMS_PER_CLIENT, MAX_STREAMS = 3, 50
_PRIVATE = ("token_sha",)  # job handle fields never returned to a client
log = logging.getLogger("faultline.api")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _limit(key: str, n: int, per_s: float, global_n: int | None = None) -> None:
    """Sliding-window rate limit per key (per IP), plus an optional global cap for the same route."""
    now = time.time()
    with _rate_lock:  # sync routes run in a thread pool
        if len(_rate) > 10_000:  # bound memory: drop idle keys
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > 3600]:
                _rate.pop(k, None)
        for k, cap in ((key, n), (f"global:{key.split(':')[0]}", global_n)):
            if cap is None:
                continue
            recent = [t for t in _rate[k] if now - t <= per_s]
            if len(recent) >= cap:
                _rate[k] = recent
                raise HTTPException(429, f"rate limit: {cap} per {int(per_s)}s" + (" (all visitors)" if k.startswith("global:") else "")
                                    + "; the recorded replays (/replay) need no quota")
            _rate[k] = recent + [now]


def _key_ok(request: Request, header: str, expected: str) -> bool:
    import hmac

    return bool(expected) and hmac.compare_digest(request.headers.get(header, "").encode(), expected.encode())


def _run_token_ok(request: Request, tenant: str, loc: dict) -> None:
    """Public demo: only the visitor who started a run (holder of its token) may choose/approve its actions."""
    if not settings.faultline_public:
        return
    import hashlib

    rows = RO(tenant, loc["graph"]).run("Q-RUN-TOKEN", {"run": loc["run"]}).rows
    sha = (rows[0]["token_sha"] if rows else None) or ""
    given = request.headers.get("x-faultline-run-token", "")
    if not sha or not given or hashlib.sha256(given.encode()).hexdigest() != sha:
        raise HTTPException(403, "this incident belongs to another visitor's run (X-Faultline-Run-Token required)")


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError):  # bad tenant / id / params → 422, never 500
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=422, content={"detail": str(exc)[:300]})


@app.exception_handler(GraphError)
async def _graph_exc(request: Request, exc: GraphError):  # FalkorDB down / not ready anywhere → 503 (fail loudly)
    from fastapi.responses import JSONResponse

    e = _graph_error(exc)
    return JSONResponse(status_code=e.status_code, content={"detail": e.detail})


def _graph_error(e: Exception) -> HTTPException:
    """Never the raw engine error to a client (it can name hosts, ports, graph internals): a generic message plus a
    request id, and the detail in the server log under that id. GraphNotReady messages are our own ("run make seed")."""
    rid = uuid.uuid4().hex[:12]
    if isinstance(e, GraphNotReady):
        return HTTPException(503, f"graph not ready: {e}")
    log.error("request %s: %s: %s", rid, type(e).__name__, e)
    if isinstance(e, GraphUnavailable):
        why = " (graph disabled: FAULTLINE_DISABLE_GRAPH)" if settings.faultline_disable_graph else ""
        return HTTPException(503, f"FalkorDB unavailable{why} (request id {rid})")
    return HTTPException(500, f"graph query failed (request id {rid})")


def _engine_raw(e: BaseException) -> bool:
    """An error that carries the engine's own text (hosts, ports, query internals): never shown to a client."""
    import redis

    return isinstance(e, (GraphError, redis.exceptions.RedisError, OSError))


def _client_error_text(e: BaseException) -> str:
    """What a client may see of a failed job, a stage note or a run-index note: one policy for all of them
    (public_errors.client_text): our own messages as they are (budget, warehouse busy, no cause...); anything carrying
    the engine's, the OS's or a subprocess's text as a generic message + request id (the detail goes to the log)."""
    from .public_errors import client_text

    return client_text(e)


def _public_error(e: BaseException, status: int = 500, what: str = "internal error") -> HTTPException:
    """Any other server-side failure shown to a client: generic text + request id; the detail goes to the log."""
    rid = uuid.uuid4().hex[:12]
    log.error("request %s: %s: %s", rid, type(e).__name__, e)
    return HTTPException(status, f"{what} (request id {rid})")


# ------------------------------------------------------------------ engine self-observability (M14 #4)
@app.get("/api/engine")
def engine_panel(request: Request, tenant: str = "acme") -> dict:
    """What FalkorDB reports about this tenant's graphs: memory per graph (GRAPH.MEMORY USAGE), queries running and
    waiting now (GRAPH.INFO), and the slow log mapped back to template ids (GRAPH.SLOWLOG). Never graph content."""
    from .agent.weights import weights
    from .graph import engine_info

    _limit(f"engine:{_ip(request)}", 30, 60, global_n=600 if settings.faultline_public else None)

    try:
        out = engine_info.tenant_report(check_tenant(tenant))
    except GraphError as e:
        raise _graph_error(e) from e
    w = weights()["engine"]
    out["limits"] = {"max_waiting": int(w["max_waiting"]), "slow_template_ms": float(w["slow_template_ms"])}
    out["slow_templates_over_budget"] = sorted({x["template"] for g in out["graphs"].values() for x in g["slow"]
                                                if x["template"] and x["ms"] > float(w["slow_template_ms"])})
    return out


@app.get("/api/engine/insight")
def engine_insight(request: Request, tenant: str = "acme") -> dict:
    """FalkorDB observing itself (M20 #8): per graph of this tenant its memory (GRAPH.MEMORY USAGE) and its telemetry
    stream (6.0: every query's wait / execution / report ms, plan-cache use, write and timeout flags) aggregated per
    template id, plus engine load and limits. Read-only, rate-limited, public-safe: ids and numbers only, never query
    text or parameters. Response shape: docs/API.md."""
    from .graph import engine_info

    _limit(f"insight:{_ip(request)}", 20, 60, global_n=300 if settings.faultline_public else None)
    try:
        return engine_info.insight(check_tenant(tenant))
    except GraphError as e:
        raise _graph_error(e) from e


# ------------------------------------------------------------------ status

def _github_real() -> bool:
    from .actions import github as gh

    return gh.is_real()

@app.get("/api/status")
def status(tenant: str = "acme") -> dict:
    t = check_tenant(tenant)
    meta = registry.resolved_meta()
    out: dict[str, Any] = {"engine": meta, "tenant": t, "graph": tenant_graph(t), "acl": "ro_user" if gclient.ro_acl_enabled() else "default_user",
                           "graph_disabled": settings.faultline_disable_graph,
                           # the specialists are deterministic graph workers today; the configured specialist model is unused until
                           # LLM specialists ship, so it is not advertised (no claim the code does not back)
                           "models": {"orchestrator": settings.anthropic_model if settings.anthropic_api_key else "deterministic investigator (no LLM key)",
                                      "specialists": "deterministic graph workers (no LLM)"},
                           "llm_configured": bool(settings.anthropic_api_key), "templates": len(catalogue()),
                           "version": __version__,
                           # which outside world approvals act on, so a client can tell before it approves
                           "github": "real" if _github_real() else "simulated"}
    try:
        ro = RO(t)
        out["ready"] = ro.require_ready()
        out["counts"] = ro.run("Q-COUNT-1", {}).rows[0]
        out["llm_budget"] = _llm_spend(t)
        out["constraints"] = _constraints_view(ro)
        out["status"] = "ok"
    except GraphError as e:
        out["status"], out["reason"] = "unavailable", _graph_error(e).detail
    if out["status"] == "ok":  # FLEX powers fuzzy resolution and hidden coupling: a missing library is shown loudly
        from .graph import udf

        try:
            libs = udf.udf_status(gclient.engine().connection)
            out["udf"] = {k: ("loaded" if v["state"] == "loaded" else "missing") for k, v in libs.items()}
            out["udf_detail"] = libs
        except Exception as e:  # noqa: BLE001 - the engine refused GRAPH.UDF: report it, never claim loaded
            out["udf"] = {k: "missing" for k in udf.UDF_LIBS}
            out["udf_detail"] = {"error": _public_error(e, what="GRAPH.UDF LIST failed").detail}
    return out


def _constraints_view(ro: RO) -> dict:
    """The engine-enforced invariants (M20) as the engine reports them (Q-SCHEMA-5, db.constraints) next to the ones
    graph/constraints.py declares: operational, still building, and any declared one the graph does not have."""
    from .graph import constraints as gc

    r = ro.run("Q-SCHEMA-5", {})
    have = {gc.key_of([x["type"], x["label"], x["properties"], x["entitytype"], x["status"]]): x["status"] for x in r.rows}
    declared = gc.by_key()
    return {"declared": len(declared), "present": len(r.rows),
            "operational": sum(1 for v in have.values() if v == "OPERATIONAL"),
            "pending": sum(1 for v in have.values() if v in gc.PENDING),
            "missing": [f"{k[0]} {k[1]} {k[2]}({', '.join(k[3])})" for k in sorted(declared) if k not in have],
            "rows": r.rows, "template": r.template_id, "graph": ro.graph_name}


# ------------------------------------------------------------------ scenarios and runs
@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    import yaml

    from .scenario import SCENARIOS

    return [{"id": s["id"], "name": s["name"], "tenant": s["tenant"], "report": s.get("report", "")}
            for s in yaml.safe_load(SCENARIOS.read_text())]


class RunIn(BaseModel):
    llm: str = Field("baseline", pattern="^(baseline|anthropic)$")


def _run_groups(job: str, sid: str, p, inv, audit, token_sha: str | None, ledgers: list[str] | None = None,
                trusted: bool = False) -> str:
    """A scenario whose alerts INTAKE split into several incidents (alert storm + concurrent fault): every incident is
    investigated in turn, then the later intake rounds (scenario.investigate_all, the same loop as run_all). Each
    incident gets its own RunIndex row (so /api/incidents, plan, SSE and approval address it like any other) and the
    job's run token; the job lists them all under `incidents`. Returns the ledger state (settled | failed).
    `ledgers` (live-LLM jobs): the job's reservation covers its FIRST incident; every further incident reserves its
    own estimate before it starts (appended here, settled by the caller). A reservation the hour's budget cannot hold
    stops the job before that incident. Whatever stops the loop, every incident not yet investigated is indexed
    FAILED with the reason, never left RUNNING."""
    from . import scenario

    entries: list[dict] = []
    _jobs[job]["incidents"] = entries
    started: list[str] = []

    def opened(k: int, grps: list) -> None:
        g = gclient.engine().select_graph(p.graph)
        for grp in grps:
            writes.index_run(audit, run=grp.run_id, inc=grp.incident_id, graph=p.graph, scenario=sid, tenant=p.tenant,
                             investigator=inv.name)
            if token_sha:
                writes.set_run_token(g, run=grp.run_id, token_sha=token_sha)
            entries.append({"incident": grp.incident_id, "run": grp.run_id, "symptoms": list(grp.symptoms),
                            "intake_round": k, "outcome": "RUNNING"})
        if "incident" not in _jobs[job]:  # the first incident stays the job's headline (unchanged response shape)
            _jobs[job].update(incident=grps[0].incident_id, run=grps[0].run_id, graph=p.graph)

    def start(grp) -> None:
        if ledgers is not None and ledgers and started:  # a live-LLM job: one estimate per incident, not per job
            try:
                ledgers.append(_reserve_llm("run", f"{job}-{len(started) + 1}", p.tenant))
            except HTTPException as e:
                raise RuntimeError(f"{grp.incident_id} not investigated: {e.detail}") from None
        started.append(grp.incident_id)

    def done(grp, res) -> None:
        writes.index_run(audit, run=grp.run_id, inc=grp.incident_id, graph=p.graph, scenario=sid, tenant=p.tenant,
                         investigator=inv.name, outcome=res.outcome, cause=res.cause_id)
        for e in entries:
            if e["incident"] == grp.incident_id:
                e.update(outcome=res.outcome, cause=res.cause_id, error=res.error)
        _after_run(p.tenant, {"graph": p.graph, "run": grp.run_id, "scenario": sid}, grp.incident_id, res)

    from .actions import oncall

    try:
        results = anyio.run(lambda: scenario.investigate_all(p, inv, on_open=opened, on_start=start, on_done=done,
                                                             oncall_home=oncall.home_graph(p.tenant),
                                                             oncall_external=trusted))
    except Exception as e:
        _fail_pending(entries, sid, p, inv, audit, _client_error_text(e))
        raise
    errors = [f"{r.incident_id}: {r.error}" for r in results if r.error]
    _jobs[job].update(state="done", outcome=results[0].outcome if results else None,
                      error="; ".join(errors) or None)
    return "failed" if errors else "settled"


def _fail_pending(entries: list[dict], sid: str, p, inv, audit, why: str) -> None:
    """The job stopped: every incident still RUNNING is indexed FAILED with the reason (and its stage set to FAILED in
    its graph), so nothing reads as in progress forever. Best effort per incident: a write that fails here (FalkorDB
    down) is logged, and the job's own error still surfaces."""
    import logging

    from .agent.state import Stage, ordinal

    log = logging.getLogger("faultline.jobs")
    g = None
    for e in entries:
        if e.get("outcome") != "RUNNING":
            continue
        e.update(outcome="FAILED", error=f"job stopped before this incident finished: {why}"[:400])
        try:
            writes.index_run(audit, run=e["run"], inc=e["incident"], graph=p.graph, scenario=sid, tenant=p.tenant,
                             investigator=inv.name, outcome="FAILED")
            g = g or gclient.engine().select_graph(p.graph)
            writes.advance_stage(g, inc=e["incident"], run=e["run"], stage=Stage.FAILED.value, ord_=ordinal(Stage.FAILED),
                                 note=e["error"], force=True)
        except Exception as w:  # noqa: BLE001 - keep marking the others; the job error is raised by the caller
            log.error("could not mark %s FAILED: %s", e["incident"], w)


def _run_job(job: str, sid: str, llm: str, ledger_id: str | None = None, token_sha: str | None = None,
             lease=None, gc_now: bool = False, trusted: bool = False) -> None:
    """`lease`: the job's hold on the warehouse (data scenarios), reserved by the request on the public demo (refused
    there with 429 when another mode is in use) or here otherwise (waits); released when the job ends."""
    from . import scenario
    from .agent.loop import BaselineInvestigator, LLMInvestigator

    inv = BaselineInvestigator() if llm == "baseline" else LLMInvestigator()
    state = "failed"
    ledgers = [ledger_id] if ledger_id else []
    try:
        if gc_now:
            _gc_graphs_safely(scenario.load(sid)["tenant"])
        if lease is None:
            mode = scenario.load(sid).get("pipeline_mode")
            lease = scenario.WAREHOUSE.reserve(mode) if mode else None
        p = scenario.prepare(sid, tag=job, lease=lease, origin="api")
        audit = gclient.engine().select_graph(audit_graph(p.tenant))
        if len(p.groups) > 1:
            state = _run_groups(job, sid, p, inv, audit, token_sha, ledgers, trusted=trusted)
            return
        writes.index_run(audit, run=p.run_id, inc=p.incident_id, graph=p.graph, scenario=sid, tenant=p.tenant,
                         investigator=inv.name)
        if token_sha:  # written by the job itself, so the token works however long prepare took
            writes.set_run_token(gclient.engine().select_graph(p.graph), run=p.run_id, token_sha=token_sha)
        _jobs[job].update(incident=p.incident_id, run=p.run_id, graph=p.graph)
        from .agent.loop import run_incident

        from .actions import oncall

        res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                             symptoms=p.symptoms, investigator=inv, graph=p.graph, run_id=p.run_id,
                                             window_min=p.scenario.get("window_min"),
                                             oncall_home=oncall.home_graph(p.tenant), oncall_external=trusted,
                                             share_notes=True))
        writes.index_run(audit, run=p.run_id, inc=p.incident_id, graph=p.graph, scenario=sid, tenant=p.tenant,
                         investigator=inv.name, outcome=res.outcome, cause=res.cause_id)
        state = "settled" if not res.error else "failed"
        # a standing contract acts BEFORE the job reads done: "done" means nothing more will happen without a human
        _after_run(p.tenant, {"graph": p.graph, "run": p.run_id, "scenario": sid}, p.incident_id, res)
        _jobs[job].update(state="done", outcome=res.outcome, error=res.error)
    except Exception as e:  # recorded and surfaced (generic text + request id to clients), never swallowed
        unavailable = isinstance(e, (GraphUnavailable, GraphNotReady))
        _jobs[job].update(state="failed", error=_client_error_text(e), unavailable=unavailable)
    finally:  # cost the run on the global ledger (upper-bound prices), also a failed run's partial usage. The usage is
        # the investigator's total over every incident of the job: it settles the first reservation, the others settle
        # at zero, so the hour's spend is the real total and no reservation stays in flight
        if lease is not None:
            lease.release()
        for i, lid in enumerate(ledgers):
            _settle_llm(lid, (getattr(inv, "usage", None) or {}) if i == 0 else {}, state)


# ------------------------------------------------------------------ the live-LLM budget: ONE global ledger
def _ledger_tenant() -> str:
    """The operator scope whose audit graph holds the spend ledger for EVERY tenant (one hourly budget, not one per
    tenant). Ledger rows carry only run ids, tenant names and dollars, never tenant data."""
    return check_tenant(settings.faultline_tenant)


def _llm_spend(tenant: str | None = None) -> dict:
    """Live-LLM spend in the last hour on the global ledger (Q-LLM-SPEND): settled costs plus in-flight reservations.
    `tenant` is accepted for the status payload only; the budget is global."""
    lt = _ledger_tenant()
    try:
        row = RO(lt, audit_graph(lt)).run("Q-LLM-SPEND", {"since": int(time.time() * 1000) - 3_600_000}).rows[0]
    except GraphNotReady:  # no ledger graph yet: nothing was ever reserved (an outage still raises)
        row = {"usd": 0.0, "reserved": 0.0, "runs": 0}
    limit = float(settings.faultline_llm_budget_usd_per_hour)
    used = float(row["usd"])
    return {"usd_last_hour": round(used, 4), "reserved_usd": round(float(row.get("reserved") or 0.0), 4),
            "runs_last_hour": int(row["runs"]), "usd_per_hour_limit": limit, "scope": "global",
            "replay_only": used + float(settings.faultline_llm_reserve_usd_run) > limit}


def _reserve_llm(kind: str, run: str, tenant: str) -> str:
    """Reserve the estimate for one live-LLM run/question before it starts (check + reserve in one query): 429 when
    the hour's budget cannot hold it, so concurrent requests cannot all pass the same remaining budget."""
    lt = _ledger_tenant()
    est = float(settings.faultline_llm_reserve_usd_run if kind == "run" else settings.faultline_llm_reserve_usd_ask)
    lid = f"llm-{kind}-{run}"
    try:
        ok = writes.reserve_llm(gclient.engine().select_graph(audit_graph(lt)), id=lid, run=run, tenant=tenant, kind=kind,
                                est_usd=est, limit_usd=float(settings.faultline_llm_budget_usd_per_hour),
                                since=int(time.time() * 1000) - 3_600_000)
    except GraphError as e:
        raise _graph_error(e) from e
    if not ok:
        spend = _llm_spend()
        raise HTTPException(429, f"hourly LLM budget spent (${spend['usd_last_hour']} of ${spend['usd_per_hour_limit']}, "
                                 f"including in-flight reservations): replay only for now; the deterministic investigator still runs")
    return lid


def _settle_llm(lid: str, usage: dict, state: str) -> None:
    import logging

    tin, tout = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    lt = _ledger_tenant()
    try:
        writes.settle_llm(gclient.engine().select_graph(audit_graph(lt)), id=lid, tin=tin, tout=tout, state=state,
                          usd=tin / 1e6 * settings.faultline_llm_usd_per_mtok_in + tout / 1e6 * settings.faultline_llm_usd_per_mtok_out)
    except Exception as e:  # noqa: BLE001 - the reservation stays on the ledger (charged at the estimate): fail safe
        logging.getLogger("faultline.budget").error("settling %s failed (reservation kept): %s", lid, e)


def _shed_load() -> None:
    """Load shedding from the engine's own state before anything copies a graph: queries waiting (GRAPH.INFO) and
    memory (INFO memory used_memory over maxmemory, weights.yaml engine.max_memory_fraction) → 429. An engine that
    cannot be asked is unavailable (503), never "fine"."""
    from .graph import engine_info

    try:
        engine_info.check_capacity()
    except engine_info.EngineOverloaded as e:
        raise HTTPException(429, str(e)) from e
    except GraphError as e:
        raise _graph_error(e) from e


def _job_view(job: str, j: dict) -> dict:
    out = {"job": job, **{k: v for k, v in j.items() if k not in _PRIVATE}}
    if "incidents" in out:
        out["incidents"] = [dict(e) for e in out["incidents"]]  # a snapshot: the job thread keeps appending
    return out


_run_count = [0]


@app.post("/api/scenarios/{sid}/run")
def run_scenario(sid: str, body: RunIn, request: Request) -> dict:
    import hashlib
    import secrets

    from . import scenario
    from .agent.weights import weights

    # 25 runs/hour per visitor on the public demo (judges often share one address); the global cap and MAX_RUNNING
    # still bound the engine
    _limit(f"run:{_ip(request)}", 25 if settings.faultline_public else 30, 3600,
           global_n=200 if settings.faultline_public else None)
    if body.llm == "anthropic" and not settings.anthropic_api_key:
        raise HTTPException(503, "live LLM unavailable: ANTHROPIC_API_KEY not configured (use llm=baseline or watch the replay)")
    if body.llm == "anthropic" and settings.faultline_public and not _key_ok(request, "x-faultline-llm-key", settings.faultline_llm_key):
        raise HTTPException(403, "the live LLM needs the operator's key on the public demo (no anonymous spend)")
    try:
        scn = scenario.load(sid)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    _shed_load()  # a run copies a graph and issues many queries
    job = uuid.uuid4().hex[:8]
    ledger_id = _reserve_llm("run", job, scn["tenant"]) if body.llm == "anthropic" else None  # last check before starting
    # capability for choose/approve on this job's runs (only its hash is stored, in the graph and on the job handle);
    # a multi-incident job writes the same hash on every incident's run as INTAKE opens it (also later rounds)
    token = secrets.token_urlsafe(24)
    token_sha = hashlib.sha256(token.encode()).hexdigest()
    lease = None
    try:
        with _jobs_lock:  # check, evict and insert atomically: a burst cannot pass MAX_RUNNING together
            if sum(1 for j in _jobs.values() if j.get("state") == "running") >= MAX_RUNNING:
                raise HTTPException(429, f"{MAX_RUNNING} runs are in progress; try again in a few seconds")
            if settings.faultline_public and scn.get("pipeline_mode"):  # never wait in a request: refuse instead
                try:
                    lease = scenario.WAREHOUSE.reserve(scn["pipeline_mode"], wait=False)
                except scenario.WarehouseBusy as e:
                    raise HTTPException(429, f"{sid} needs the shared data warehouse: {e}") from e
            extra = len(_jobs) - 199  # in-memory handles only: drop the oldest finished ones, never a running one
            for k in [k for k, j in _jobs.items() if j.get("state") != "running"][:max(0, extra)]:
                _jobs.pop(k)
            _jobs[job] = {"state": "running", "scenario": sid, "started_at": time.time(), "tenant": scn["tenant"],
                          "token_sha": token_sha}
            _run_count[0] += 1
            gc_now = _run_count[0] % max(1, int(weights()["engine"]["gc_every_runs"])) == 0
        # a trusted run (off the public demo, or started with the approver key) may page external channels and use
        # a standing contract; an anonymous public run pages in-app only (security review, M19)
        trusted = (not settings.faultline_public) or _key_ok(request, "x-faultline-approver-key",
                                                             settings.faultline_approver_key)
        threading.Thread(target=_run_job, args=(job, sid, body.llm, ledger_id, token_sha, lease, gc_now, trusted),
                         daemon=True).start()
    except BaseException:  # nothing ran: the reservation at zero, the warehouse lease and the job handle are released
        if ledger_id:
            _settle_llm(ledger_id, {}, "failed")
        if lease is not None:
            lease.release()
        with _jobs_lock:
            if _jobs.get(job, {}).get("state") == "running" and "incident" not in _jobs[job]:
                _jobs.pop(job, None)
        raise
    for _ in range(100):  # wait until the incident exists in the graph (prepare is fast)
        if _jobs[job].get("incident") or _jobs[job]["state"] != "running":
            break
        time.sleep(0.05)
    if _jobs[job].get("error") and not _jobs[job].get("incident"):  # FalkorDB down/not ready → 503 like every route
        raise HTTPException(503 if _jobs[job].get("unavailable") else 500, _jobs[job]["error"])
    out = _job_view(job, _jobs[job])
    # the token was generated before the job started and the job writes its hash on every run it opens, so it is
    # returned even when prepare outlasts this wait; the UI keys it by job and picks up incidents opened later (late
    # intake rounds) from GET /api/jobs/{job}
    out["run_token"] = token
    return out


@app.get("/api/jobs/{job}")
def job_status(job: str, request: Request, tenant: str = "acme") -> dict:
    """A run job's incidents (including those later intake rounds opened after the run response), tenant-bound. The
    run token is echoed back (`run_token`, `token_valid`) only to a caller who presents the job's own token
    (X-Faultline-Run-Token), so the UI can store it for every incident of its own job; never to anyone else."""
    import hashlib
    import hmac

    t = check_tenant(tenant)
    if not (len(job) == 8 and all(ch in "0123456789abcdef" for ch in job)):
        raise HTTPException(422, "bad job id")
    with _jobs_lock:
        j = _jobs.get(job)
        snap = dict(j) if j else None
    if snap is None or snap.get("tenant") != t:
        raise HTTPException(404, f"unknown job {job} for tenant {t}")
    out = _job_view(job, snap)
    given = request.headers.get("x-faultline-run-token", "")
    ok = bool(given) and hmac.compare_digest(hashlib.sha256(given.encode()).hexdigest(), snap.get("token_sha") or "")
    out["token_valid"] = ok
    if ok:
        out["run_token"] = given
    return out


@app.get("/api/tenants")
def tenants() -> list[dict]:
    """Seeded tenants (one graph each), with whether their graph is ready. Read from FalkorDB, never a fixed list."""
    from .graph.tenant import check_tenant as _ct

    out = []
    try:
        names = sorted(n for n in gclient.engine().list_graphs() if n.startswith("tenant_"))
    except GraphError as e:
        raise _graph_error(e) from e
    for n in names:
        t = n.removeprefix("tenant_")
        try:
            _ct(t)
            meta = RO(t).run("Q-META-1", {}).rows
            out.append({"tenant": t, "graph": n, "ready": bool(meta and meta[0].get("ready"))})
        except (ValueError, GraphError):
            continue
    return out


def _stored_json(text: str | None, default: Any = None) -> Any:
    """A JSON payload stored on an evidence or tool-call node. Payloads written before writes.capped_json could be cut
    mid-string; one unreadable payload is reported as such instead of failing the whole response."""
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"unreadable": True, "reason": "the stored payload is not valid JSON (cut by an older version)"}


@app.get("/api/incidents")
def incidents(tenant: str = "acme", all: bool = False) -> list[dict]:  # noqa: A002 - the query parameter's name
    """Recent runs from the audit index, each with `available` (its run graph still exists). The live demo collects
    older run graphs, so by default only runs that can still be opened are listed (`all=true` lists every run)."""
    try:
        rows = RO(check_tenant(tenant), audit_graph(tenant)).run("Q-RUNS-1", {}).rows
    except GraphNotReady:
        return []
    except GraphError as e:
        raise _graph_error(e) from e
    live = set(gclient.engine().list_graphs())
    for r in rows:
        r["available"] = not r.get("graph") or r["graph"] in live
    return rows if all else [r for r in rows if r["available"]]


def _collected_text(inc: str) -> str:
    from .agent.weights import weights

    w = weights()["engine"]
    return (f"incident {inc}'s run graph was collected: the live demo keeps the {int(w['keep_recent_runs'])} most recent "
            f"runs and any run touched in the last {int(w['gc_touched_ttl_min'])} minutes; start a new run")


def _locate(inc: str, tenant: str) -> dict:
    rows = RO(tenant, audit_graph(tenant)).run("Q-RUNS-2", {"inc": inc}).rows
    if not rows:
        raise HTTPException(404, f"unknown incident {inc}")
    if rows[0].get("graph") and not gcopy.exists(gclient.engine(), rows[0]["graph"]):
        raise HTTPException(410, _collected_text(inc))  # gone for good: the UI says so instead of retrying
    return rows[0]


@app.get("/api/incidents/{inc}")
def incident(inc: str, tenant: str = "acme") -> dict:
    from .agent import report

    t = check_tenant(tenant)
    try:
        loc = _locate(inc, t)
        ro = RO(t, loc["graph"])
        view = {"incident": ro.run("Q-INC-1", {"inc": inc}).rows[0], "run": loc,
                "stages": ro.run("Q-RUN-1", {"run": loc["run"]}).rows,
                "tool_calls": [{**c, "params": json.loads(c["params"]) if c.get("params") else None}
                               for c in ro.run("Q-RUN-2", {"run": loc["run"]}).rows],
                "hypotheses": ro.run("Q-HYP-1", {"inc": inc}).rows,
                "gate_runs": [{**g, "checks": json.loads(g["checks"])} for g in ro.run("Q-INC-GATES", {"inc": inc}).rows],
                "crew": _crew_view(ro, loc["run"])}
        if loc.get("outcome") not in (None, "RUNNING"):
            view["report"] = report.build(t, loc["graph"], inc, loc["outcome"]).model_dump()
        return view
    except GraphError as e:
        raise _graph_error(e) from e


@app.get("/api/brain/subgraph")
def brain_subgraph(ids: str, tenant: str = "acme") -> dict:
    """A brain answer drawn as a graph (M17, Q-BRAIN-SUB): how the ids it cites connect within 2 hops of the domain
    graph. `ids`: comma-separated node ids from the answer's citations (at most 12)."""
    t = check_tenant(tenant)
    wanted = [i for i in dict.fromkeys(x.strip() for x in ids.split(",")) if i]
    if not 1 <= len(wanted) <= 12 or not all(re.fullmatch(r"[A-Za-z0-9_.:@-]{1,160}", i) for i in wanted):
        raise HTTPException(422, "ids: 1-12 comma-separated node ids")
    try:
        r = RO(t).run("Q-BRAIN-SUB", {"ids": wanted})
    except GraphError as e:
        raise _graph_error(e) from e
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict] = {}
    for row in r.rows:
        for n in row["nodes"]:
            nodes.setdefault(n["id"], {**n, "cited": n["id"] in wanted})
        for e in row["rels"]:
            edges.setdefault((e["source"], e["target"], e["rel"]), e)
    for i in wanted:   # a cited id with no connection still shows, alone
        nodes.setdefault(i, {"id": i, "label": None, "name": i, "cited": True})
    return {"template": "Q-BRAIN-SUB", "cypher": r.cypher, "params": r.params, "truncated": r.truncated,
            "nodes": list(nodes.values()), "edges": list(edges.values())}


@app.get("/api/incidents/{inc}/provenance")
def incident_provenance(inc: str, tenant: str = "acme") -> dict:
    """Why the agent believes its verdict (M17, Q-PROV-1): the confirmed cause's supporting evidence, the tool call that
    produced each piece, the agent that made the call, and what each call saw, as nodes and edges for a graph view.
    An evidence item no agent's step claims was read by the gate itself (its checks bypass the crew's ToolBox)."""
    t = check_tenant(tenant)
    try:
        loc = _locate(inc, t)
        r = RO(t, loc["graph"]).run("Q-PROV-1", {"inc": inc})
    except GraphError as e:
        raise _graph_error(e) from e
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(nid: str, kind: str, label: str, **extra: Any) -> None:
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, **extra})

    for row in r.rows:
        verdict = f"verdict:{row['hypothesis']}"
        node(verdict, "verdict", f"{row['blames']} confirmed", blames=row["blames"])
        node(row["evidence"], "evidence", row["tool"] or "evidence", template=row["template"], summary=row["summary"])
        edges.add((row["evidence"], verdict, "SUPPORTS"))
        call = row.get("tool_call")
        if call:
            node(call, "call", row["tool"] or "call", template=row["template"], ms=row["ms"])
            edges.add((call, row["evidence"], "PRODUCED_EVIDENCE"))
            for s in row.get("saw") or []:
                node(f"node:{s}", "seen", s)
                edges.add((call, f"node:{s}", "SAW"))
            if row.get("task"):
                agent = row.get("agent") or row["task"]
                node(f"agent:{agent}", "agent", row.get("role") or agent, task=row["task"], task_kind=row.get("task_kind"))
                edges.add((f"agent:{agent}", call, "MADE"))
            else:
                node("agent:gate", "agent", "gate (its own checks)", task=None, task_kind="gate")
                edges.add(("agent:gate", call, "MADE"))
    return {"incident": inc, "template": "Q-PROV-1", "cypher": r.cypher, "params": r.params,
            "nodes": list(nodes.values()), "edges": [{"source": a, "target": b, "rel": k} for a, b, k in sorted(edges)]}


def _crew_view(ro: RO, run: str) -> dict:
    """The run's crew (M17): the roster (who does what, with which tools) and every recorded step and specialist work
    item from the graph (Q-CREW-1), each with the tool calls it made in time order. Records, not locks; the gate's own
    reads are on the gate runs, which the Gatekeeper's lane shows."""
    from .agent import crew

    steps = []
    for r in ro.run("Q-CREW-1", {"run": run}).rows:
        calls = sorted((c for c in r.get("calls") or [] if c), key=lambda c: (c.get("at") or 0, c.get("id") or ""))
        steps.append({**r, "calls": calls})
    return {"roster": crew.roster(), "steps": steps, "template": "Q-CREW-1"}


def _stream_slot(ip: str):
    """Take one SSE slot for this client AND one of the global ones, at check time under a lock (a burst of requests
    cannot all pass the same count). Returns an idempotent release, called when the stream ends (or never starts)."""
    with _streams_lock:
        if _streams[ip] >= MAX_STREAMS_PER_CLIENT or _streams["*"] >= MAX_STREAMS:
            raise HTTPException(429, f"too many open event streams ({MAX_STREAMS_PER_CLIENT} per visitor, "
                                     f"{MAX_STREAMS} in total)")
        _streams[ip] += 1
        _streams["*"] += 1
    done = [False]

    def release() -> None:
        with _streams_lock:
            if done[0]:
                return
            done[0] = True
            _streams[ip] -= 1
            _streams["*"] -= 1
            if _streams[ip] <= 0:
                _streams.pop(ip, None)

    return release


@app.get("/api/incidents/{inc}/events")
async def incident_events(inc: str, request: Request, tenant: str = "acme") -> EventSourceResponse:
    """Graph-derived event stream. Capped per client and globally; `retry:` tells EventSource how long to wait;
    `done` only on a real terminal, `paused` while waiting for a human, `idle` before closing an idle stream."""
    t = check_tenant(tenant)
    loc = _locate(inc, t)
    ro = RO(t, loc["graph"])
    release = _stream_slot(_ip(request))
    terminal = ("NO_INCIDENT", "UNKNOWN_ESCALATED", "FAILED", "RESOLVED")

    async def gen():
        try:
            yield {"event": "hello", "retry": 5000, "data": json.dumps({"incident": inc})}
            seen: set[str] = set()
            idle = 0
            while idle < 240:
                if await request.is_disconnected():
                    return
                batch = []
                try:
                    for kind, tid, params in (("stage", "Q-RUN-1", {"run": loc["run"]}),
                                              ("tool_call", "Q-RUN-2", {"run": loc["run"]}),
                                              ("gate_run", "Q-INC-GATES", {"inc": inc})):
                        for row in await asyncio.to_thread(lambda tid=tid, params=params: ro.run(tid, params).rows):
                            key = f"{kind}:{row['id']}:{row.get('evidence_id', '')}"
                            if key not in seen:
                                seen.add(key)
                                if kind == "gate_run":
                                    row = {**row, "checks": json.loads(row["checks"])}
                                batch.append({"event": kind, "data": json.dumps(row, default=str)})
                    inc_rows = await asyncio.to_thread(lambda: ro.run("Q-INC-1", {"inc": inc}).rows)
                except GraphError:
                    inc_rows = None
                if not inc_rows:  # the run graph was collected (or never held the incident): say so once and stop,
                    gone = not await asyncio.to_thread(gcopy.exists, gclient.engine(), loc["graph"])
                    if gone or inc_rows is not None:  # so the client does not reconnect forever
                        yield {"event": "collected", "data": json.dumps(
                            {"reason": _collected_text(inc) if gone else f"incident {inc} is not in its run graph"})}
                        return
                    raise GraphUnavailable("the incident's run graph could not be read")
                for b in sorted(batch, key=lambda x: json.loads(x["data"]).get("at") or 0):
                    yield b
                idle = 0 if batch else idle + 1
                stage = inc_rows[0]["stage"]
                if stage in terminal and not batch and idle > 2:
                    yield {"event": "done", "data": json.dumps({"stage": stage})}
                    return
                if stage == "AWAITING_APPROVAL" and not batch and idle == 3:
                    yield {"event": "paused", "data": json.dumps({"stage": stage})}
                await asyncio.sleep(0.5)
            yield {"event": "idle", "data": json.dumps({"reason": "no new events for 120 s; reconnect to resume"})}
        finally:
            release()

    from starlette.background import BackgroundTask

    # also released when the response ends without ever iterating the generator (client gone before the first event)
    return EventSourceResponse(gen(), background=BackgroundTask(release))


# ------------------------------------------------------------------ graph view + Cypher panel
@app.get("/api/graph")
def graph_view(tenant: str = "acme", incident: str | None = None, focus: str | None = None) -> dict:
    """The failure-flow graph. Large tenants are scoped: pass `focus` (a node id) to get its upstream scope + blast
    radius; an unscoped view that hits the template LIMIT says so (`truncated`), it never pretends to be whole."""
    t = check_tenant(tenant)
    try:
        graph = _locate(incident, t)["graph"] if incident else tenant_graph(t)
        ro = RO(t, graph)
        if focus:
            ids = {focus} | {r["id"] for r in ro.run("Q-BLAST-1", {"id": focus}).rows} | \
                  {r["id"] for r in ro.run("Q-LIN-1", {"symptom": focus}).rows if (r.get("hops") or 0) <= 3}
            res = ro.run("Q-VIEW-2", {"ids": sorted(ids)})
        else:
            res = ro.run("Q-VIEW-1", {})
        rows, truncated = res.rows, res.truncated
        betweenness = {r["id"]: r["score"] for r in ro.run("Q-CHOKE-ALL", {}).rows}
    except GraphError as e:
        raise _graph_error(e) from e
    nodes: dict[str, dict] = {}
    for r in rows:
        nodes.setdefault(r["src"], {"id": r["src"], "label": r["src_label"], "tier": r["src_tier"], "betweenness": betweenness.get(r["src"])})
        nodes.setdefault(r["dst"], {"id": r["dst"], "label": r["dst_label"], "tier": r["dst_tier"], "betweenness": betweenness.get(r["dst"])})
    return {"graph": graph, "focus": focus, "truncated": truncated, "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
            "edges": [{"source": r["src"], "target": r["dst"], "cap": r["cap"], "domain": r["domain"]} for r in rows]}


@app.get("/api/incidents/{inc}/blast")
def incident_blast(inc: str, tenant: str = "acme") -> dict:
    """Blast radius of each symptom on the incident's graph: algo.BFS + hops, impact ranked in code."""
    from .mcp_server import context
    from .mcp_server import tools as T

    t = check_tenant(tenant)
    loc = _locate(inc, t)
    targets = RO(t, loc["graph"]).run("Q-INC-1", {"inc": inc}).rows[0]["targets"]
    token = context.bind(t, run_id=None, graph=loc["graph"])
    try:
        out = {s: T.blast_radius(id=s) for s in targets}
    finally:
        context.unbind(token)
    bad = [v["error"] for v in out.values() if "error" in v]
    if bad:
        raise _public_error(RuntimeError("; ".join(bad)), 503, "blast radius unavailable")
    return {"graph": loc["graph"], "blast": {s: {"rows": v["rows"], "template": v["template"], "via": v["via"]} for s, v in out.items()}}


def _actx(inc: str, tenant: str):
    from .actions import act

    loc = _locate(inc, tenant)
    return act.Ctx(tenant, loc["graph"], inc, loc["run"]), loc


@app.get("/api/incidents/{inc}/plan")
def incident_plan(inc: str, tenant: str = "acme") -> dict:
    """Containment, routing and the action options, all read from the graph (what the agent recorded)."""
    t = check_tenant(tenant)
    c, loc = _actx(inc, t)
    ro = c.ro()
    out: dict[str, Any] = {"stage": ro.run("Q-INC-1", {"inc": inc}).rows[0]["stage"]}
    # notify_set (who to tell, not who fixes it) and owner_at (owner when the change shipped) are ROUTE results too
    for tool in ("containment_cut", "whatif", "who_fixes", "bus_factor", "escalation_tree", "notify_set", "owner_at",
                 "learned_preferences", "learned_responders"):
        rows = ro.run("Q-EV-TOOL", {"run": loc["run"], "tool": tool}).rows
        out[tool] = ({**rows[0], "payload": _stored_json(rows[0]["payload"]),
                      "params": json.loads(rows[0]["params"]) if rows[0]["params"] else None} if rows else None)
    out["options"] = [{**a, "preview": json.loads(a["preview"]) if a["preview"] else None,
                       "spec": json.loads(a["spec"]) if a["spec"] else None,
                       "channels": json.loads(a["channels"]) if a["channels"] else None,
                       "learned": json.loads(a["learned"]) if a.get("learned") else None}
                      for a in ro.run("Q-ACT-1", {"inc": inc}).rows]
    out["learned"] = _plan_learned(out["options"], out.get("learned_preferences"), out.get("learned_responders"),
                                   ((out.get("who_fixes") or {}).get("payload") or {}).get("rows") or [])
    # memory: what RECALL found (RECALLED edges) and what those precedents teach about each fix kind
    out["memory"] = {"recalled": ro.run("Q-MEM-4", {"inc": inc}).rows, "fix_history": ro.run("Q-MEM-5", {"inc": inc}).rows}
    return out


def _plan_learned(options: list[dict], prefs: dict | None, resp: dict | None, who_rows: list[dict] | None = None) -> dict:
    """The plan's learning summary (M21) from what the run recorded: which options learning moved (their rank without
    learning vs their place), which are against an active guideline, which carry a contract suggestion, and the
    learned responders paged first (the recorded learned_* tool calls carry the Cypher)."""
    from .memory import learning

    if prefs is None and resp is None:
        return {"consulted": False, "note": "learning not consulted for this run (no on-call home)"}
    payload = (prefs or {}).get("payload") or {}
    rp = (resp or {}).get("payload") or {}
    pv = learning.plan_view({**payload, "rows": payload.get("rows") or [], "evidence_id": (prefs or {}).get("evidence_id")}
                            if prefs else None)
    # the plan's own order (Q-ACT-1 orders by the integer rank each option was recorded with, never by the id string)
    moved = [o["id"] for i, o in enumerate(options, 1)
             if (o.get("learned") or {}).get("rank_without_learning") not in (None, o.get("rank") or i)]
    return {"consulted": True, "family": payload.get("family"), "n_family": payload.get("n_family"),
            "applies": pv.get("applies"), "pref_min_n": int(learning.w()["pref_min_n"]), "moved": moved,
            "flagged": [o["id"] for o in options if ((o.get("learned") or {}).get("guideline") or {}).get("needs_override")],
            "suggested": [o["id"] for o in options if (o.get("learned") or {}).get("contract_suggestion")],
            "guidelines": payload.get("guidelines") or [], "suggestions": payload.get("suggestions") or [],
            "responders": rp.get("rows") or [], "first_wave": [p["person"] for p in learning.first_wave(
                {**rp, "evidence_id": (resp or {}).get("evidence_id")})] if resp else [],
            # who_fixes as recorded (algo.HarmonicCentrality), blended with the learned responders (learn.w_resp)
            "who_fixes_blended": learning.blend_who(list(who_rows or [])[:10], rp if resp else None)[:5],
            "evidence": {"preferences": (prefs or {}).get("evidence_id"), "responders": (resp or {}).get("evidence_id")}}


class ChooseIn(BaseModel):
    action_id: str = Field(..., max_length=120)


@app.post("/api/incidents/{inc}/choose")
def incident_choose(inc: str, body: ChooseIn, request: Request, tenant: str = "acme") -> dict:
    """Step 1: choose an option → the server renders the EXACT action and its plan hash."""
    from .actions import act
    from .actions import github as gh

    _limit(f"choose:{_ip(request)}", 20, 60)
    c, loc = _actx(inc, check_tenant(tenant))
    _run_token_ok(request, c.tenant, loc)
    try:
        return act.choose(c, body.action_id, gh.client(c.graph))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e)) from e
    except gh.GitHubError as e:
        raise HTTPException(502, f"GitHub: {e}") from e


class ApproveIn(BaseModel):
    action_id: str = Field(..., max_length=120)
    plan_hash: str = Field(..., min_length=64, max_length=64)
    approver: str = Field(..., min_length=1, max_length=60)
    # M21: approving an option an ACTIVE learned guideline is against needs an explicit override: its id and why
    override_guideline: str | None = Field(default=None, pattern=r"^gl-[0-9a-f]{6,40}$")
    override_reason: str | None = Field(default=None, min_length=3, max_length=300)


def _world(c, loc: dict) -> dict | None:
    """The second verification channel's inputs for an incident: the simulated world of its scenario."""
    from . import scenario

    if not loc.get("scenario"):
        return None
    s = scenario.load(loc["scenario"])
    inc = c.ro().run("Q-INC-1", {"inc": c.inc}).rows[0]
    onset = int(inc["onset_at"])  # this incident's onset (a later intake round's incident starts at its own first page)
    eff = scenario.effects_of(s, scenario.scenario_onset(s))  # the world's effects are relative to the scenario onset
    # what CONTAIN protected (recorded params of the containment_cut call) is checked for collateral
    cut = c.ro().run("Q-EV-TOOL", {"run": loc["run"], "tool": "containment_cut"}).rows
    prm = (json.loads(cut[0]["params"]) or {}) if cut and cut[0]["params"] else {}
    protect = prm.get("protect") or prm.get("protect_ids") or []
    return {"symptom": sorted(inc["targets"]), "onset_ms": onset, "effects": eff, "at_ms": onset + 5 * 60_000,
            "protect": protect, "world_seed": int(s.get("seed", 42))}


def _reconcile(tenant: str, graph: str) -> list[dict]:
    """Intent reconciliation for one graph (before every execute and at API start)."""
    from .actions import github as gh
    from .actions.reconcile import reconcile

    def world(inc: str) -> dict | None:
        try:
            c, loc = _actx(inc, tenant)
        except HTTPException:
            return None
        return _world(c, loc)

    from .actions import oncall

    # an intent the reconciler settles without a verified fix pages a human (idempotent per outcome)
    return reconcile(tenant, graph, gh.client(graph), world, oncall_home=oncall.home_graph(tenant))


@app.on_event("startup")
def _startup_udfs() -> None:
    """Load the pinned UDF libraries (FLEX) like `make up` does (idempotent); a failure is logged loudly and
    /api/status then reports the library as missing, never silently."""
    import logging

    from .graph import udf

    try:
        logging.getLogger("faultline.udf").info("UDFs loaded: %s", udf.load_udfs(gclient.engine().connection))
    except Exception as e:  # noqa: BLE001 - engine down / pinned file changed: surfaced in the log and in /api/status
        logging.getLogger("faultline.udf").error("UDF load failed: %s", e)


def _configured_tenants() -> list[str]:
    """Every seeded tenant (a tenant_<t> graph in FalkorDB), plus the configured default."""
    names = {settings.faultline_tenant}
    names |= {g.removeprefix("tenant_") for g in gclient.engine().list_graphs() if g.startswith("tenant_")}
    out = []
    for t in sorted(names):
        try:
            out.append(check_tenant(t))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ graphs in use, collection, periodic reconcile
_acting: dict[str, int] = defaultdict(int)  # graph → execute jobs / reconcilers working on it right now
_gc_lock = threading.RLock()                 # the collector's last check and its delete vs. registering work on a graph


def _work_enter(graph: str) -> None:
    with _gc_lock:
        _acting[graph] += 1


def _work_leave(graph: str) -> None:
    with _gc_lock:
        _acting[graph] -= 1
        if _acting[graph] <= 0:
            _acting.pop(graph, None)


@contextlib.contextmanager
def _working_on(graph: str):
    """Mark a graph as in use (an execute job, a reconciler): the collector never deletes it meanwhile."""
    _work_enter(graph)
    try:
        yield
    finally:
        _work_leave(graph)


def _pending_graphs(tenant: str) -> list[str]:
    """The graphs a reconciler should look at for this tenant: every indexed run's graph and every API clean room
    (`eval_<t>_api_*`) that still exists."""
    names = set(gclient.engine().list_graphs())
    try:
        indexed = {r["graph"] for r in RO(tenant, audit_graph(tenant)).run("Q-RUNS-1", {}).rows if r.get("graph")}
    except GraphNotReady:  # no run was ever indexed for this tenant
        indexed = set()
    return sorted(g for g in indexed | {n for n in names if n.startswith(f"eval_{tenant}_api_")} if g in names)


_reconcile_lock = threading.Lock()  # one reconcile pass at a time (startup, periodic)


def _reconcile_all(trigger: str) -> int:
    """Reconcile PENDING intents in every graph of every seeded tenant (fail loudly in the log, never raise). Skipped
    when another pass is running. Returns how many intents were looked at."""
    rlog = logging.getLogger("faultline.reconcile")
    if not _reconcile_lock.acquire(blocking=False):
        rlog.info("%s reconcile skipped: another pass is running", trigger)
        return 0
    n = 0
    try:
        try:
            tenants = _configured_tenants()
        except GraphError as e:
            rlog.warning("%s reconcile skipped: %s", trigger, e)
            return 0
        for tenant in tenants:
            try:
                graphs = _pending_graphs(tenant)
            except GraphError as e:
                rlog.warning("%s reconcile skipped for %s: %s", trigger, tenant, e)
                continue
            for gname in graphs:
                try:
                    with _working_on(gname):
                        if not gcopy.exists(gclient.engine(), gname):  # collected meanwhile: nothing to reconcile
                            continue
                        for o in _reconcile(tenant, gname):
                            n += 1
                            rlog.warning("%s reconcile: %s", trigger, o)
                except Exception as e:  # noqa: BLE001 - surfaced in the log; the incident's own stage shows the state
                    rlog.error("%s reconcile %s failed: %s", trigger, gname, e)
    finally:
        _reconcile_lock.release()
    return n


@app.on_event("startup")
def _startup_learning_homes() -> None:
    """M21: every tenant's on-call home graph exists and carries the learning indexes before the first request, so
    GET /api/learned (and every other learned-state read) never writes. Logged, never blocks startup."""
    from .memory import learning

    try:
        learning.ensure_homes(_configured_tenants())
    except GraphError as e:
        log.warning("learning homes not prepared at startup: %s", e)


@app.on_event("startup")
def _startup_reconcile() -> None:
    """Reconcile PENDING intents in every graph that has runs, for EVERY tenant (fail loudly in the log, never block
    startup). A lease held by a boot that is still alive (a predecessor killed seconds ago keeps its heartbeat for up
    to actions.boot_stale_s) is left to the periodic reconciler."""
    _reconcile_all("startup")


_ops_stop = threading.Event()
_ops_state: dict[str, threading.Thread | None] = {"thread": None}


def _ops_loop(stop: threading.Event) -> None:
    """The API's background housekeeping. Every actions.boot_heartbeat_s it heartbeats this boot
    in every tenant's audit graph (so its intent leases are known to be alive); every actions.reconcile_every_s it
    reconciles every graph with PENDING intents. The first periodic pass runs once a killed predecessor's heartbeat is
    stale (boot_stale_s + one heartbeat after startup), so a crashed execute job's intent is settled about a minute
    after a restart instead of waiting for the next approval."""
    from .actions import boot
    from .agent.weights import weights

    w = weights()["actions"]
    hb, every, stale = float(w["boot_heartbeat_s"]), float(w["reconcile_every_s"]), float(w["boot_stale_s"])
    next_reconcile = time.monotonic() + stale + hb
    next_prune = time.monotonic() + 3600.0
    olog = logging.getLogger("faultline.ops")
    while not stop.is_set():
        try:
            tenants = _configured_tenants()
        except GraphError as e:
            olog.warning("heartbeat skipped: %s", e)
            tenants = []
        for t in tenants:
            try:
                boot.beat(t, "api")
            except Exception as e:  # noqa: BLE001 - the leases then fall back to expiry; logged, never fatal
                olog.warning("boot heartbeat for %s failed: %s", t, e)
        if time.monotonic() >= next_prune:
            for t in tenants:
                try:
                    boot.prune(t)
                except Exception as e:  # noqa: BLE001
                    olog.warning("boot prune for %s failed: %s", t, e)
            next_prune = time.monotonic() + 3600.0
        if time.monotonic() >= next_reconcile:
            _reconcile_all("periodic")
            next_reconcile = time.monotonic() + every
        stop.wait(hb)


@app.on_event("startup")
def _startup_ops() -> None:
    """Start the heartbeat + periodic reconciler thread (once per process)."""
    th = _ops_state["thread"]
    if th is not None and th.is_alive():
        return
    _ops_stop.clear()
    th = threading.Thread(target=_ops_loop, args=(_ops_stop,), name="faultline-ops", daemon=True)
    _ops_state["thread"] = th
    th.start()


@app.on_event("shutdown")
def _shutdown_ops() -> None:
    """A clean stop: end the heartbeat thread and mark this boot ended, so the next process may take over its intent
    leases at once (a killed process is taken over once its heartbeat is stale)."""
    from .actions import boot

    _ops_stop.set()
    th = _ops_state["thread"]
    if th is not None:
        th.join(timeout=5)
    try:
        tenants = _configured_tenants()
    except GraphError:
        return
    for t in tenants:
        try:
            boot.end(t)
        except Exception as e:  # noqa: BLE001
            log.warning("ending boot for %s failed: %s", t, e)


def _gc_hold(tenant: str, graph: str) -> str | None:
    """Why the collector must keep this run graph (Q-GC-HOLD, engine clock), or None: a PENDING intent, a live lease,
    anything recorded within engine.gc_touched_ttl_min, or an incident in a non-terminal stage touched within
    engine.gc_open_max_idle_h. A graph that cannot be read is kept (never delete what we cannot judge)."""
    from .agent.state import TERMINALS
    from .agent.weights import weights

    w = weights()["engine"]
    try:
        rows = RO(tenant, graph).run("Q-GC-HOLD", {"terminal": sorted(x.value for x in TERMINALS)}).rows
    except GraphError as e:
        log.warning("collector kept %s: unreadable (%s)", graph, e)
        return "unreadable"
    r = rows[0] if rows else {}
    if r.get("pending"):
        return f"{r['pending']} PENDING intent(s)"
    if r.get("leased"):
        return "a live intent lease"
    last, now = r.get("last_at"), r.get("now")
    idle_ms = (int(now) - int(last)) if (last is not None and now is not None) else None
    if idle_ms is not None and idle_ms < float(w["gc_touched_ttl_min"]) * 60_000:
        return "touched recently"
    if r.get("open") and idle_ms is not None and idle_ms < float(w["gc_open_max_idle_h"]) * 3_600_000:
        return f"{r['open']} incident(s) in a non-terminal stage"
    return None


def gc_run_graphs(tenant: str) -> dict:
    """The live stack collects its own run graphs. Deletes this tenant's API clean
    rooms (`eval_<t>_api_…`, only ones the API made) except: the graphs of the weights.yaml engine.keep_recent_runs
    most recent indexed runs, any graph a running job uses, any graph an execute job or reconciler is working on
    (`_acting`, checked under the collector's lock right before each delete), and any graph Q-GC-HOLD holds (a PENDING
    intent, a live lease, recent activity, an open incident). Then the simulated GitHub worlds of deleted graphs and
    stale public brain copies. Eval harness / CLI clean rooms (other prefixes) are never touched here (`make gc`)."""
    from .actions import github as gh
    from .agent.weights import weights
    from .brain import scratch as brain_scratch

    t = check_tenant(tenant)
    n = int(weights()["engine"]["keep_recent_runs"])
    try:
        rows = RO(t, audit_graph(t)).run("Q-RUNS-1", {}).rows
    except GraphNotReady:
        rows = []
    keep: list[str] = []
    for r in rows:  # newest first
        if r.get("graph") and r["graph"] not in keep and len(keep) < n:
            keep.append(r["graph"])
    with _jobs_lock:
        running = [(k, j.get("graph")) for k, j in _jobs.items() if j.get("state") == "running"]
    prefix = f"eval_{t}_api_"
    db = gclient.engine()
    candidates = sorted(g for g in db.list_graphs() if g.startswith(prefix) and g not in keep
                        and not any(g == used or g.endswith(f"_{k}") for k, used in running))
    deleted, held = [], {}
    for g in candidates:
        why = _gc_hold(t, g)
        if why:
            held[g] = why
            continue
        with _gc_lock:
            if _acting.get(g):
                held[g] = "in use by an execute job or reconciler"
                continue
            gcopy.delete_if_exists(db, g)
        gh.reset_sim(g)
        deleted.append(g)
    gh.prune_sims(set(db.list_graphs()))
    return {"tenant": t, "deleted": deleted, "kept": keep, "held": held, "brain": brain_scratch.gc(t)}


def _gc_graphs_safely(tenant: str) -> None:
    try:
        out = gc_run_graphs(tenant)
        if out["deleted"] or out["brain"]:
            log.info("collected %d run graphs and %d brain copies of %s", len(out["deleted"]), len(out["brain"]), tenant)
    except Exception as e:  # noqa: BLE001 - collection is housekeeping: logged loudly, never fails a run
        log.error("graph collection for %s failed: %s", tenant, e)


@app.on_event("startup")
def _startup_gc() -> None:
    try:
        tenants = _configured_tenants()
    except GraphError as e:
        log.warning("graph collection skipped: %s", e)
        return
    for t in tenants:
        _gc_graphs_safely(t)


def _act_job(c, loc: dict, aid: str) -> None:
    """EXECUTE → VERIFY → WRITEBACK → (LEARN) → RESOLVED | AWAITING_APPROVAL (fix did not take) | UNKNOWN_ESCALATED.
    The approval query already moved the incident to EXECUTE (exclusive) and leased the intent to this job (`c.owner`);
    the lease is renewed before every step (and right after the warehouse hold is taken, which can wait), execute
    refuses on an expired lease, and every verdict, write-back and stage write below is conditional on the intent
    (PENDING and leased to this job until this job settles it) in the same query. If the reconciler took the intent
    over or settled it first (IntentNotPending), this job stops and writes nothing more: whatever that writer recorded
    stands. A failure before anything outside the graph was touched fails the intent and the stage in ONE query (the
    reconciler can never resurrect it); one after the external change is UNKNOWN for a human; one after a committed
    write-back is reported on the final stage, never turned into FAILED. Notes carry client-safe text only."""
    from . import scenario
    from .actions import act
    from .actions import github as gh
    from .agent.state import Stage, ordinal

    from .agent import crew

    hub = gh.client(c.graph)
    g = c.g()
    committed = executed = verified_ok = touched = False
    kind = None
    shift = crew.Shift(c.tenant, c.graph, c.run)   # Operator → Auditor → Librarian, recorded as crew steps
    err: BaseException | None = None

    def stage(st: Stage, note: str = "", force: bool = False, settled: bool = False) -> bool:
        return writes.advance_stage(g, inc=c.inc, run=c.run, stage=st.value, ord_=ordinal(st), note=note, force=force,
                                    aid=aid, owner=c.owner, settled=settled)

    try:
        stage(Stage.EXECUTE, f"executing {aid}", force=True)  # the approval set the stage; this records the event
        shift.begin("operator", Stage.EXECUTE, tag=aid)
        try:
            _reconcile(c.tenant, c.graph)  # settle OLDER intents in this graph first (this one is leased: skipped)
        except Exception as e:  # noqa: BLE001 - a stuck old intent must not block this approval
            stage(Stage.EXECUTE, f"reconciler error (older intents left as they were): {_client_error_text(e)}"[:400],
                  force=True)
        cause = (c.ro().run("Q-CAUSE-1", {"inc": c.inc}).rows or [{}])[0].get("cause")
        kind = next((a["kind"] for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid), None)
        w = _world(c, loc)
        if w is None or (not cause and kind != "open_issue"):  # check BEFORE touching the outside world
            raise act.NotExecuted("no second verification channel for this incident" if w is None
                                  else "no confirmed cause in the graph")
        act.renew(c, aid)
        # a data repair patches a transform and rebuilds the ONE warehouse: never while a data run reads it (M4); the
        # lease is renewed while waiting for the hold and again right after it is taken (the wait can be long)
        hold = scenario.WAREHOUSE.exclusive(heartbeat=lambda: act.renew(c, aid)) if kind == "data_repair" \
            else contextlib.nullcontext()
        with hold:
            act.renew(c, aid)
            touched = True
            act.execute(c, aid, hub)
            executed = True
            shift.note(f"executed {kind} {aid}: intent recorded first, idempotency key, the single write tool")
            act.renew(c, aid)
            stage(Stage.VERIFY)
            shift.begin("auditor", Stage.VERIFY, tag=aid)
            v = act.verify(c, aid, hub, **w)
        if v["verdict"] == "APPLIED":  # M15 #4: a verified rollback may show a link the graph was missing (proposal only)
            from .memory import edges

            try:
                edges.propose(c, aid, onset_ms=int(w.get("onset_ms") or 0), symptoms=list(w.get("symptom") or []))
            except GraphError as e:  # a proposal is advisory: never turn a verified fix into a failed job
                logging.getLogger("faultline.learn").warning("edge proposal after %s failed: %s", aid, e)
        act.renew(c, aid)
        stage(Stage.WRITEBACK, f"verdict {v['verdict']}: {v['explanation'][:200]}")
        wb = act.write_back(c, aid, cause=cause, confident=True)
        committed = bool(wb.get("written") or wb.get("tracked"))
        shift.note(f"second channel: {v['verdict']}; write-back re-read on a separate RO connection: {wb.get('verified', 'n/a')}")
        if wb.get("tracked"):
            stage(Stage.UNKNOWN_ESCALATED, f"handed to humans: {v['explanation'][:200]}", force=True, settled=True)
            return
        if v["verdict"] == "NOT_APPLIED":
            stage(Stage.AWAITING_APPROVAL, f"fix did not take ({v['explanation'][:200]}); option disabled, choose another",
                  force=True, settled=True)
            return
        if v["verdict"] == "UNKNOWN":
            stage(Stage.UNKNOWN_ESCALATED, f"verification UNKNOWN: {v['explanation'][:200]}; intent left PENDING for the "
                                           "reconciler", force=True)
            return
        note = f"write-back verified {wb['verified']}" + (f" ({wb['reread_error']})" if wb.get("reread_error") else "")
        n, m = (int(x) for x in wb["verified"].split("/"))
        if n != m:  # the success write is committed but could not be fully re-read: a human checks it, never "RESOLVED"
            stage(Stage.UNKNOWN_ESCALATED, note + "; second-channel re-read incomplete, escalated", force=True, settled=True)
            return
        verified_ok = True  # success written AND fully re-read (n == m): the only path that may end RESOLVED
        try:  # T2: leave the verified outcome as a note other agents recall (agentmem_<t>; a lead, never evidence)
            from .memory import notes as agent_notes

            done = act._action(c, aid)
            target = (c.ro().run("Q-CHANGE-1", {"id": cause}).rows or [{}])[0].get("target")
            principal = f"faultline:{c.run}"   # the investigation's own author: the fix answers its verdict note
            parent = agent_notes.last_note(c.tenant, principal) or ""
            left = agent_notes.leave_note(
                c.tenant, principal=principal, about=[target, *list(w.get("symptom") or [])], kind="observation",
                reply_to=parent, stance="confirms",
                text=f"{cause} caused {c.inc}; fixed by {done['option']} ({done.get('external_ref') or 'no ref'}), "
                     f"verified {v['verdict']} on a second channel; write-back re-read {wb['verified']}.")
            shift.note(f"left note {left['id']} for other agents about {', '.join(left['about'])}")
        except Exception as e:  # noqa: BLE001 - a note is advisory: logged and shown, never a failed fix
            logging.getLogger("faultline.notes").warning("verdict note after %s not written: %s", aid, e)
            note += f"; note for other agents skipped: {_client_error_text(e)}"[:160]
        try:  # LEARN: family (labelPropagation) → derived runbook; decay
            from .memory.learn import learn

            shift.begin("librarian", Stage.LEARN, tag=aid)
            lr = learn(c.tenant, c.graph, c.inc, c.run)
            rb = lr.get("runbook") or {}
            shift.note(f"family of {len(lr['family'])} incident(s)" + (f"; runbook {rb['runbook']} support {rb['support']}" if rb else ""))
            stage(Stage.LEARN, f"family of {len(lr['family'])} incidents"
                  + (f"; runbook {rb['runbook']} now supported by {rb['support']}" if rb else ""), settled=True)
        except Exception as e:  # noqa: BLE001
            note += f"; LEARN skipped: {_client_error_text(e)}"[:200]
        stage(Stage.RESOLVED, note, settled=True)
    except writes.IntentNotPending as e:  # settled or taken over by another writer: never overwrite its verdict/stage
        err = e
        logging.getLogger("faultline.act").warning("%s/%s: %s; leaving it to that writer", c.inc, aid, e)
    except Exception as e:  # recorded in the graph, surfaced in the UI (client-safe text; the detail is logged)
        err = e
        why = _client_error_text(e)[:380]
        settled = False
        untouched = (not touched) or (isinstance(e, act.NotExecuted) and not executed)
        if verified_ok:
            st, note, settled = Stage.RESOLVED, "write-back verified; a later step failed: " + why, True
        elif committed:  # something was written but not fully verified: a human checks it, never a green RESOLVED
            st, note, settled = Stage.UNKNOWN_ESCALATED, "committed, but a later step failed before verification: " + why, True
        elif untouched:  # nothing outside the graph changed: the intent FAILS with the stage, in one query
            mismatch = isinstance(e, act.WorldMismatch)
            st = Stage.UNKNOWN_ESCALATED if mismatch else Stage.FAILED
            note = (f"not executed: {why}; the incident's data cannot be re-established, a human decides" if mismatch
                    else f"not executed: {why}")
            try:
                if mismatch:  # the verdict a human sees: UNKNOWN with the reason (never success)
                    writes.record_verdict(g, aid=aid, verdict="UNKNOWN", why=note, channels={"fixture": {"ok": None}},
                                          owner=c.owner)
                if writes.fail_untouched(g, inc=c.inc, run=c.run, aid=aid, owner=c.owner, stage=st.value,
                                         ord_=ordinal(st), why=why, note=note):
                    return
            except writes.IntentNotPending:
                logging.getLogger("faultline.act").warning("%s/%s settled elsewhere after a failure: %s", c.inc, aid, why)
                return
            except Exception:  # noqa: BLE001 - fall through to the owner-bound stage write below
                pass
            # the intent is no longer ours (or the write failed): only the owner-bound, PENDING-only stage write
        elif executed or touched:  # the outside world may have changed: never FAILED, never success → UNKNOWN for a human
            if kind == "data_repair":
                try:
                    from . import repair

                    spec = json.loads(next(a["spec"] for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid))
                    repair.mark_unverified(spec["file"], {"incident": c.inc, "action": aid, "why": why})
                except Exception:  # noqa: BLE001 - a courtesy marker; the verdict below is what counts
                    pass
            try:  # both writes are conditional on the intent: a no-op (IntentNotPending) when another writer has it
                writes.record_verdict(g, aid=aid, verdict="UNKNOWN", why=f"after the change was executed: {why}",
                                      channels={}, owner=c.owner)
                writes.write_back_not_applied(g, inc=c.inc, aid=aid, stage=Stage.UNKNOWN_ESCALATED.value, owner=c.owner)
            except writes.IntentNotPending:
                logging.getLogger("faultline.act").warning("%s/%s settled elsewhere after a failure: %s", c.inc, aid, why)
                return
            except Exception:  # noqa: BLE001
                pass
            st, note = Stage.UNKNOWN_ESCALATED, "executed, then verification failed: " + why + "; intent left for the reconciler"
        else:
            st, note = Stage.FAILED, why
        # owner-bound and, unless this job settled the intent itself, only while it is still PENDING (else a no-op)
        stage(st, note, force=True, settled=settled)
    finally:  # an intent this job leaves PENDING (UNKNOWN) goes to the reconciler without waiting for the lease
        try:
            shift.end(failed=err)
        except Exception:  # noqa: BLE001 - the crew record is a log of the job; it never changes the job's outcome
            logging.getLogger("faultline.crew").warning("%s/%s: crew step not recorded", c.inc, aid)
        try:
            writes.release_intent(g, aid=aid, owner=c.owner)
        except Exception:  # noqa: BLE001 - the lease then simply expires
            pass


def _act_job_tracked(c, loc: dict, aid: str) -> None:
    """The execute job, registered as working on its graph (the collector skips it) until it ends."""
    try:
        _act_job(c, loc, aid)
        _page_after_approval(c, aid)
        from .memory import learning

        learning.on_verified(c, aid)   # M21: a trusted approval verified APPLIED and RESOLVED (best effort)
    finally:
        _work_leave(c.graph)


def _page_after_approval(c, aid: str) -> None:
    """After the execute job of an APPROVED action: RESOLVED resolves the incident's open pages; UNKNOWN_ESCALATED,
    NOT_APPLIED (back to AWAITING_APPROVAL) or FAILED pages a human at once (oncall.page_after_approval, idempotent
    per outcome, so the reconciler settling the same outcome later pages nobody twice). Best effort: never fails
    the job, logged loudly."""
    from .actions import oncall

    try:
        out = oncall.page_after_approval(c.tenant, c.graph, c.inc, c.run, aid)
        if out and out.get("pages"):
            log.warning("%s/%s: %s after approval; paged %s", c.inc, aid, out["what"], ", ".join(out["people"]))
    except Exception as e:  # noqa: BLE001 - the stage still says it; logged loudly
        log.error("paging after the approval of %s/%s failed: %s", c.inc, aid, e)


def _after_run(tenant: str, loc: dict, inc: str, res) -> None:
    """After an investigation: when a standing contract covered its plan (agent.loop matched it before paging), act
    under it. Never raises into the run job (its result stands); a failure pages a human."""
    paged = ((getattr(res, "post_gate", None) or {}).get("oncall") or {}) if res is not None else {}
    if not paged.get("contract"):
        return
    try:
        _contract_job(tenant, loc, inc, paged)
    except Exception as e:  # noqa: BLE001 - logged, and a human is paged so the incident is never left alone
        log.error("acting under contract on %s failed: %s", inc, e)
        _page_humans_after_contract(tenant, loc, inc, paged, f"acting under the contract failed ({_client_error_text(e)})")


def _page_humans_after_contract(tenant: str, loc: dict, inc: str, paged: dict, why: str) -> list[str]:
    """The contract did not end in a verified fix: page the same people a normal run would have, urgent, at once, and
    supersede the informational notices."""
    from .actions import oncall

    g = gclient.engine().select_graph(loc["graph"])
    writes.settle_pages(g, inc=inc, status="superseded", detail=f"superseded: {why}"[:500], now=oncall.now_ms(),
                        kinds=("contract_notice",))
    cid = (paged.get("contract") or {}).get("id")
    return oncall.write_pages(tenant=tenant, graph=loc["graph"], inc=inc, people=paged.get("people") or [], kind="page",
                              urgency="urgent", title=f"Contract {cid} did not fix {inc}",
                              detail=f"Handled under standing contract {cid}, but {why}. A human must decide now.")


def _contract_job(tenant: str, loc: dict, inc: str, paged: dict) -> dict:
    """Act under a standing contract: render the exact action (choose), check it still binds the contract's params,
    consume one use in ONE guarded write (W_CONTRACT_USE), approve as `contract:<id>` with an intent lease, then the
    same execute → verify (second channel) → write-back job a human approval runs. Anything but a verified, resolved
    fix pages a human at once; the use records the verdict."""
    from .actions import act, contracts, oncall
    from .actions import github as gh
    from .actions.boot import BOOT_ID

    m = paged["contract"]
    home = oncall.home_graph(tenant)
    c = act.Ctx(tenant, loc["graph"], inc, loc["run"])
    if gh.is_real() and not m.get("real_ok"):  # the same authority a human approval needs (_approver_ok's rule)
        _page_humans_after_contract(tenant, loc, inc, paged, "this contract was granted without the authority real "
                                                             "GitHub needs (the approver key); a human must approve")
        return {"acted": False}
    if _world(c, loc) is None:  # no second channel to verify with: never act unverifiable under a contract
        _page_humans_after_contract(tenant, loc, inc, paged, "this incident has no second verification channel")
        return {"acted": False}
    try:
        spec = act.choose(c, m["option"], gh.client(c.graph))
    except (ValueError, KeyError, gh.GitHubError) as e:
        _page_humans_after_contract(tenant, loc, inc, paged, f"the covered action could not be rendered ({_client_error_text(e)})")
        return {"acted": False}
    if contracts.params_hash(spec["kind"], contracts.action_params(spec["kind"], spec["args"])) != m["params_hash"]:
        _page_humans_after_contract(tenant, loc, inc, paged, "the rendered action no longer matches the contract's parameters")
        return {"acted": False}
    use = contracts.use(home=home, match=m, inc=inc, graph=c.graph, aid=m["option"])
    if use is None:  # exhausted, expired or revoked since the match: the guarded write refused
        _page_humans_after_contract(tenant, loc, inc, paged, "the contract was exhausted, expired or revoked before it was used")
        return {"acted": False}
    c.owner = f"{BOOT_ID}:contract-{uuid.uuid4().hex[:12]}"
    _work_enter(c.graph)
    try:
        ok = act.approve(c, m["option"], spec["plan_hash"], f"contract:{m['id']}")
        if ok is None or not ok.get("mine"):
            contracts.give_back(home=home, uid=use["use"])   # consumed, never executed: the use is returned
            _page_humans_after_contract(tenant, loc, inc, paged, "the covered action could not be approved (the incident "
                                                                 "moved on or another run owns its idempotency key)")
            return {"acted": False}
        _act_job(c, loc, m["option"])
    finally:
        _work_leave(c.graph)
    row = next((a for a in c.ro().run("Q-ACT-1", {"inc": inc}).rows if a["id"] == m["option"]), {})
    stage = (c.ro().run("Q-INC-1", {"inc": inc}).rows or [{}])[0].get("stage")
    if not row.get("verdict") and stage == "FAILED":   # refused before touching anything: the use is returned
        contracts.give_back(home=home, uid=use["use"])
        verdict = "NOT_EXECUTED"
    else:
        verdict = row.get("verdict") or "UNKNOWN"
        contracts.settle_use(home=home, uid=use["use"], verdict=verdict)
    if verdict == "APPLIED" and stage == "RESOLVED":
        oncall.settle_resolved(tenant, c.graph, inc)
        return {"acted": True, "verdict": verdict}
    # the same after-approval page a human approval gets (one key per outcome: the reconciler never pages it twice);
    # the informational notices are superseded first
    writes.settle_pages(gclient.engine().select_graph(c.graph), inc=inc, status="superseded",
                        detail=f"superseded: verification said {verdict} under contract {m['id']}", now=oncall.now_ms(),
                        kinds=("contract_notice",))
    oncall.page_after_approval(tenant, c.graph, inc, c.run, m["option"])
    return {"acted": True, "verdict": verdict}


def _approver_ok(request: Request) -> None:
    """With REAL GitHub, approving merges into a real repo: require the operator's approver key."""
    import hmac

    from .actions import github as gh

    if not gh.is_real():
        return
    key = settings.faultline_approver_key
    if not key:
        raise HTTPException(503, "approvals against real GitHub need FAULTLINE_APPROVER_KEY configured on the server")
    if not hmac.compare_digest(request.headers.get("x-faultline-approver-key", "").encode(), key.encode()):
        raise HTTPException(403, "approver key required for real GitHub")


@app.post("/api/incidents/{inc}/approve")
def incident_approve(inc: str, body: ApproveIn, request: Request, tenant: str = "acme") -> dict:
    """Step 2: approve the exact action by its plan hash (409 if stale or not awaiting approval), then execute,
    verify (second channel) and write back in the background."""
    _limit(f"approve:{_ip(request)}", 10, 60)
    _approver_ok(request)
    c, loc = _actx(inc, check_tenant(tenant))
    _run_token_ok(request, c.tenant, loc)
    from .actions.boot import BOOT_ID

    c.owner = f"{BOOT_ID}:act-{uuid.uuid4().hex[:12]}"  # the execute job's intent lease (set by the approval query)
    _work_enter(c.graph)  # registered BEFORE the graph is re-checked: the collector cannot delete it from here on
    started = False
    try:
        if not gcopy.exists(gclient.engine(), c.graph):
            raise HTTPException(410, _collected_text(inc))
        override = _guideline_check(c, body.action_id, body.override_guideline, body.override_reason)
        res = _approve_checked(c, body, inc, override)   # the override is written with the Approval (one query)
        from .memory import learning

        # learned before the execute job starts: its verified fix is learned only if this approval was (M21)
        res["learned"] = learning.on_approve(c, body.action_id, body.approver, key=_approver_key_given(request),
                                             override=override)
        threading.Thread(target=_act_job_tracked, args=(c, loc, body.action_id), daemon=True).start()
        started = True
        _ack_by_approval(c, body.approver)
    finally:
        if not started:
            _work_leave(c.graph)
    if override:
        res["override"] = override
    return res


def _guideline_check(c, aid: str, override_id: str | None, override_reason: str | None, *,
                     can_override: bool = True) -> dict | None:
    """M21: an option an ACTIVE learned guideline is against (same family and action kind, read fresh from the on-call
    home graph, Q-LEARN-GUIDE) is approved only with an explicit override naming that guideline and why: 409 with the
    guideline otherwise. Stricter, never weaker: no guideline ⇒ nothing changes. Returns the override, or None."""
    from .memory import learning

    a = next((x for x in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if x["id"] == aid), None)
    if a is None:
        return None
    fam, _ = learning.family_of(c.ro(), c.run, c.inc)
    active = learning.active_guidelines(c.tenant, fam, a["kind"]) if fam else []
    if not active:
        return None
    ids = [g["id"] for g in active]
    if not can_override or override_id not in ids or not (override_reason or "").strip():
        g = active[0]
        how = ("approve it in the web UI with override_guideline and override_reason" if not can_override else
               f"send override_guideline={g['id']} and an override_reason")
        raise HTTPException(409, f"{a['option']} is against active guideline {g['id']} (\"{g['text'][:200]}\", "
                                 f"promoted by {g.get('decided_by_name') or g.get('decided_by')}): {how}")
    return {"id": override_id, "reason": " ".join((override_reason or "").split())[:300],
            "text": next(g["text"] for g in active if g["id"] == override_id)}


def _approver_checked(c, person: str) -> dict:
    """Q-APPROVER-1 (M19 fix: it reads ON_CALL): the approver must be an active person (else 422) who is on call for,
    or a member of, a team that owns a component this incident impacts (else 403, with the graph's reason)."""
    from .actions import oncall

    who = oncall.approver_check(c.ro(), run=c.run, inc=c.inc, person=person)
    if who is None:
        raise HTTPException(422, f"approver {person!r} is not an active person in this tenant's graph")
    if not who["eligible"]:
        raise HTTPException(403, f"approver {person!r} may not approve on {c.inc}: {who['reason']} (Q-APPROVER-1)")
    return who


def _ack_by_approval(c, approver: str) -> None:
    """Approving is acknowledging: the incident's pages stop escalating (best effort; never fails the approval)."""
    from .actions import oncall

    try:
        oncall.on_approval(c.tenant, c.graph, c.inc, approver)
    except Exception as e:  # noqa: BLE001 - the pages stay open (visible, still escalating); logged
        log.warning("acknowledging the pages of %s on approval failed: %s", c.inc, e)


def _approve_checked(c, body: "ApproveIn", inc: str, override: dict | None = None) -> dict:
    from .actions import act

    who = _approver_checked(c, body.approver)  # decided by the graph, with the reason shown on the approval
    res = act.approve(c, body.action_id, body.plan_hash, body.approver, override=override)
    if res is None:
        raise HTTPException(409, "plan hash does not match the current chosen action, or the incident is not awaiting approval")
    if not res["mine"]:
        raise HTTPException(409, "an intent with this idempotency key already exists (another run owns it)")
    return {"approved": True, **res, "approver": who}


# ------------------------------------------------------------------ reject + read-only UI views
# Reject (a human refuses the exact chosen action, with a reason), then read-only, tenant-bound GETs for the
# naive-vs-Faultline contrast, the Memory tab and the Brain widgets. The GETs only call existing MCP tools (bound with record=False: nothing is written) or catalogue
# templates through the RO wrapper; no decision is made here.
class RejectIn(BaseModel):
    action_id: str = Field(..., max_length=120)
    plan_hash: str = Field(..., min_length=64, max_length=64)
    approver: str = Field(..., min_length=1, max_length=60)
    reason: str = Field(..., min_length=3, max_length=500)


@app.post("/api/incidents/{inc}/reject")
def incident_reject(inc: str, body: RejectIn, request: Request, tenant: str = "acme") -> dict:
    """Reject the exact chosen action (by its plan hash) with a reason: the option is disabled for good, the rejection
    is recorded on the action and as a stage event, and the incident stays AWAITING_APPROVAL for another choice.
    Same guards as approve: rate limit, approver key on real GitHub, run token in public mode, approver decided by the
    graph (422), 409 when stale or not awaiting approval. Nothing outside the graph is touched."""
    from .actions import act
    from .graph.writes import WriteError

    _limit(f"reject:{_ip(request)}", 10, 60)
    _approver_ok(request)
    c, loc = _actx(inc, check_tenant(tenant))
    _run_token_ok(request, c.tenant, loc)
    who = _approver_checked(c, body.approver)
    try:
        res = act.reject(c, body.action_id, body.plan_hash, body.approver, body.reason)
    except WriteError as e:
        raise HTTPException(422, str(e)) from e
    if res is None:
        raise HTTPException(409, "plan hash does not match the current chosen action, or the incident is not awaiting approval")
    from .memory import learning

    learned = learning.on_reject(c, body.action_id, body.approver, body.reason, key=_approver_key_given(request))
    return {"rejected": True, **res, "reason": " ".join(body.reason.split())[:500], "approver": who, "learned": learned}


def _qr(r) -> dict:
    """A template result as the UI's Cypher panel needs it (template id + params re-run it read-only)."""
    return {"rows": r.rows, "template": r.template_id, "params": r.params, "ms": round(r.ms, 2), "truncated": r.truncated,
            "digest": r.digest}


def _tool(tenant: str, graph: str | None, name: str, **kw: Any) -> dict:
    """Call an existing MCP tool bound to one tenant's graph WITHOUT recording (external read). A tool error is a
    loud 503 when FalkorDB is unavailable, else it is returned in the section as {"error": …} (never empty rows)."""
    from .mcp_server import context
    from .mcp_server import tools as T

    token = context.bind(tenant, record=False, graph=graph)
    try:
        out = getattr(T, name)(**kw)
    finally:
        context.unbind(token)
    err = out.get("error") if isinstance(out, dict) else None
    if err and (err.startswith("unavailable") or "GraphNotReady" in err):
        raise _public_error(RuntimeError(f"{name}: {err}"), 503, f"{name}: FalkorDB unavailable")
    return out


def _now_ms() -> int:
    return int(time.time() * 1000)


@app.get("/api/incidents/{inc}/contrast")
def incident_contrast(inc: str, tenant: str = "acme") -> dict:
    """Naive recency vs the gate, from what the run already recorded (nothing is recomputed): the run's
    window_changes result (Q-SUS-2 orders by time, newest first, so naive recency blames its first row and any
    change at the same instant), the run's pageRank result (rank_causes) and the hypotheses with their gate status."""
    t = check_tenant(tenant)
    loc = _locate(inc, t)
    ro = RO(t, loc["graph"])
    onset = ro.run("Q-INC-1", {"inc": inc}).rows[0].get("onset_at")

    def recorded(tool: str) -> dict | None:
        rows = ro.run("Q-EV-TOOL", {"run": loc["run"], "tool": tool}).rows
        if not rows:
            return None
        payload = _stored_json(rows[0]["payload"], {})
        return {"rows": payload.get("rows") or [], "template": rows[0]["template"], "evidence_id": rows[0]["evidence_id"],
                "params": json.loads(rows[0]["params"]) if rows[0]["params"] else {}, "summary": rows[0]["summary"]}

    wc, rank = recorded("window_changes"), recorded("rank_causes")
    hyps = {h["cause"]: h for h in ro.run("Q-HYP-1", {"inc": inc}).rows}
    confirmed = (ro.run("Q-CAUSE-1", {"inc": inc}).rows or [{}])[0].get("cause")
    pr = {r["id"]: r.get("norm", r.get("score")) for r in (rank or {}).get("rows", [])}
    changes = []
    for r in (wc or {}).get("rows", []):  # recorded order (Q-SUS-2: at DESC, deploy)
        h = hyps.get(r["deploy"])
        changes.append({**r, "before_onset_ms": (onset - r["at"]) if onset is not None and r.get("at") is not None else None,
                        "pagerank": pr.get(r["target"]), "gate_status": h["status"] if h else None,
                        "gate_reason": h["reason"] if h else None, "confirmed": r["deploy"] == confirmed})
    first_at = changes[0]["at"] if changes else None
    naive = [c["deploy"] for c in changes if c["at"] == first_at] if changes else []
    return {"graph": loc["graph"], "onset_at": onset, "confirmed": confirmed, "outcome": loc.get("outcome"),
            "naive": naive, "changes": changes,
            "window_changes": {k: v for k, v in wc.items() if k != "rows"} if wc else None,
            "rank_causes": {k: v for k, v in rank.items() if k != "rows"} if rank else None,
            "unavailable": None if wc else "this run recorded no window_changes result, so there is nothing to contrast"}


@app.get("/api/memory/overview")
def memory_overview(tenant: str = "acme", incident: str | None = None) -> dict:
    """Memory tab: incident families (algo.labelPropagation, incident_families), every runbook in effect with its
    support and DERIVED_FROM postmortems (Q-MEM-RB) and, for one incident, its recall (similar_incidents: similarity,
    recency, salience) and what RECALL linked during its run (Q-MEM-4). An agent-run incident is read from its run's
    graph; a seeded one from the tenant graph."""
    t = check_tenant(tenant)
    graph = tenant_graph(t)
    onset = None
    if incident:
        try:
            graph = _locate(incident, t)["graph"]
        except HTTPException:  # not an agent run: a seeded (historical) incident of the tenant graph
            pass
        rows = RO(t, graph).run("Q-INC-1", {"inc": incident}).rows
        if not rows:
            raise HTTPException(404, f"unknown incident {incident} in {graph}")
        onset = rows[0].get("onset_at") or rows[0].get("opened_at")
    out: dict[str, Any] = {"graph": graph, "incident": incident,
                           "families": _tool(t, graph, "incident_families", incident_id=incident or "-"),
                           "runbooks": _qr(RO(t, graph).run("Q-MEM-RB", {}))}
    if incident:
        out["recall"] = _tool(t, graph, "similar_incidents", incident_id=incident, now=int(onset or _now_ms()))
        out["recalled"] = _qr(RO(t, graph).run("Q-MEM-4", {"inc": incident}))
    return out


@app.get("/api/notes")
def agent_notes_route(tenant: str = "acme", focus: str = "", text: str = "") -> dict:
    """Shared agent notes (T2), read-only: what agents (Faultline's own runs, MCP clients) noted about a component or
    near it, and by meaning (the `recall_notes` MCP tool: Q-NOTE-RECALL on agentmem_<tenant>, ranked in the engine)."""
    if len(text) > 200 or len(focus) > 120:
        raise HTTPException(400, "text is at most 200 characters and focus at most 120")
    if not text.strip() and not focus:
        raise HTTPException(400, "give focus, text or both")
    out = _tool(check_tenant(tenant), None, "recall_notes", text=text, focus_id=focus, include_private=False)
    if out.get("error"):
        raise HTTPException(400, out["error"])
    return {k: out.get(k) for k in ("rows", "via", "template", "cypher", "params", "ms", "served_by", "note")}


class ContextPackReq(BaseModel):
    text: str = Field(min_length=1, max_length=2000)   # the tool's CTX_MAX_TEXT
    targets: list[str] = Field(default_factory=list, max_length=5)
    at: int | None = None
    budget_tokens: int = Field(default=1000, ge=50, le=8000)
    window_min: int | None = Field(default=None, ge=1, le=1440)
    rank: str = Field(default="anomaly", pattern="^(distance|anomaly)$")


@app.post("/api/context_pack")
def context_pack_route(req: ContextPackReq, tenant: str = "acme") -> dict:
    """Context engineering for any agent (M16.1): the graph's smallest provenance-carrying context for an alert or a
    question, packed to a token budget (the `context_pack` MCP tool, read-only, not recorded)."""
    out = _tool(check_tenant(tenant), None, "context_pack", text=req.text, targets=req.targets,
                at=req.at if req.at is not None else _now_ms(), budget_tokens=req.budget_tokens, window_min=req.window_min,
                rank=req.rank)
    if out.get("error"):
        raise HTTPException(400, out["error"])
    return {k: out.get(k) for k in ("rows", "tokens", "budget", "seeds", "via", "truncated_sources", "notes", "template",
                                    "evidence_id", "served_by")}


@app.get("/api/brain/decisions")
def brain_decisions(tenant: str = "acme") -> dict:
    """Decision tracer picker: every decision, its status, what it constrains and what supersedes it (Q-DEC-LIST)."""
    return _qr(RO(check_tenant(tenant)).run("Q-DEC-LIST", {}))


@app.get("/api/brain/decisions/{did}")
def brain_decision_trace(did: str, tenant: str = "acme") -> dict:
    """Decision tracer: trace_decision (head through SUPERSEDES + the head's sources, Q-DEC-2/Q-DEC-3) and the whole
    SUPERSEDES chain the decision belongs to (Q-DEC-CHAIN)."""
    t = check_tenant(tenant)
    tr = _tool(t, None, "trace_decision", decision_id=did)
    if not tr.get("error") and not tr.get("rows"):
        raise HTTPException(404, f"unknown decision {did}")
    return {"trace": tr, "chain": _qr(RO(t).run("Q-DEC-CHAIN", {"id": did}))}


@app.get("/api/brain/ownership")
def brain_ownership(tenant: str = "acme") -> dict:
    """Ownership map: every team with the components it owns now and its active members (Q-OWN-MAP)."""
    return _qr(RO(check_tenant(tenant)).run("Q-OWN-MAP", {}))


@app.get("/api/brain/ownership/{cid}")
def brain_owner_at(cid: str, tenant: str = "acme", at: int | None = None) -> dict:
    """One component's ownership history (owner_at: OWNED_AT periods, owner then vs now, who knew it then)."""
    return _tool(check_tenant(tenant), None, "owner_at", target_id=cid, at=int(at) if at is not None else _now_ms())


@app.get("/api/brain/guardrails")
def brain_guardrails(tenant: str = "acme") -> dict:
    """Guardrails: missing_guardrails (revenue-path services with no owner or runbook) and knowledge_health (stale
    runbooks, handovers without a runbook, decisions at risk, likely missing edges), both as of now."""
    t = check_tenant(tenant)
    return {"missing_guardrails": _tool(t, None, "missing_guardrails"),
            "knowledge_health": _tool(t, None, "knowledge_health", now=_now_ms())}


class AskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    llm: str = Field("baseline", pattern="^(baseline|anthropic)$")
    user: str | None = Field(None, pattern=r"^[A-Za-z0-9_.@-]{1,80}$")
    session: str | None = Field(None, pattern=r"^[A-Za-z0-9_.@-]{1,120}$")


@app.post("/api/brain/ask")
def brain_ask(body: AskIn, request: Request, tenant: str = "acme") -> dict:
    """Company brain: tier 1 seeds → tier 2 templates → tier 3 guarded text2cypher (LLM mode). Every [id] in the
    answer passed the citation guard (seen by a tool call of this question's run)."""
    from .brain.ask import ask

    _limit(f"brain:{_ip(request)}", 30, 60, global_n=600 if settings.faultline_public else None)
    if body.llm == "anthropic" and not settings.anthropic_api_key:
        raise HTTPException(503, "live LLM unavailable: ANTHROPIC_API_KEY not configured (use llm=baseline)")
    if body.llm == "anthropic" and settings.faultline_public and not _key_ok(request, "x-faultline-llm-key", settings.faultline_llm_key):
        raise HTTPException(403, "the live LLM needs the operator's key on the public demo (no anonymous spend)")
    from .brain import scratch as brain_scratch
    from .graph.engine_info import EngineOverloaded
    from .graph.writes import SessionError

    t = check_tenant(tenant)
    usage: dict = {}  # filled by the LLM answerer as it goes, so a failed question is still costed
    lid = _reserve_llm("ask", uuid.uuid4().hex[:10], t) if body.llm == "anthropic" else None
    state = "failed"
    try:
        if _brain_in_scratch(request):  # a visitor's question records in a bounded brain copy, never the live graph
            with brain_scratch.use(t) as gname:
                out = ask(body.question, t, body.llm, user=body.user, session=body.session, usage=usage, graph=gname).as_dict()
        else:
            out = ask(body.question, t, body.llm, user=body.user, session=body.session, usage=usage).as_dict()
        state = "settled"
        from .memory import learning

        # M21: a question the graph could not answer becomes a KnowledgeGap; a public visitor's question never does
        gap = learning.on_gap(t, out, body.user, trusted_=not _brain_in_scratch(request))
        out["knowledge_gap"] = {"event": gap["event"]} if gap else None
        return out
    except SessionError as e:  # another user's session (or an id no session may take): refused, not a server error
        raise HTTPException(403, str(e)) from e
    except EngineOverloaded as e:  # a new brain copy would not fit (load shedding, like every other graph copy)
        raise HTTPException(429, str(e)) from e
    except GraphError as e:
        raise _graph_error(e) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    finally:
        if lid:
            _settle_llm(lid, usage, state)


def _operator(request: Request) -> bool:
    """The operator on the public demo: holds the admin key or the live-LLM key."""
    return _key_ok(request, "x-faultline-admin-key", settings.faultline_admin_key) or \
        _key_ok(request, "x-faultline-llm-key", settings.faultline_llm_key)


def _brain_in_scratch(request: Request) -> bool:
    """Public demo, not the operator: brain runs, tool calls, evidence and turns go to the tenant's brain scratch copy."""
    return settings.faultline_public and not _operator(request)


@app.get("/api/brain/history")
def brain_history(user: str, request: Request, tenant: str = "acme") -> dict:
    """A user's persistent session history (T2), read back from the graph the questions were recorded in (on the
    public demo: the current brain copy, so a visitor's history lasts as long as that copy, brain.scratch_ttl_min)."""
    import re as _re

    from .brain import scratch as brain_scratch

    if not _re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", user):
        raise HTTPException(422, "bad user id")
    t = check_tenant(tenant)
    try:
        graph = brain_scratch.current(t) if _brain_in_scratch(request) else None
        if _brain_in_scratch(request) and graph is None:
            return {"user": user, "turns": []}
        return {"user": user, "turns": RO(t, graph).run("Q-SESS-1", {"user": user}).rows}
    except GraphError as e:
        raise _graph_error(e) from e


class ForgetIn(BaseModel):
    doc_id: str = Field(..., pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    token: str | None = Field(None, min_length=64, max_length=64)
    approver: str | None = Field(None, min_length=1, max_length=60)
    question: str | None = Field(None, min_length=3, max_length=300)   # asked before and after (default: from the doc)


def _forget_question(doc: dict) -> str:
    """The question whose answer should change once the document is forgotten (asked before and after)."""
    title = str(doc.get("title") or doc.get("id") or "")[:200]
    kind = doc.get("kind")
    return (f"What did we decide about {title}?" if kind == "adr" else
            f"Which runbook covers {title}?" if kind == "runbook" else f"What do we know about {title}?")


def _ask_on_copy(t: str, source: str, question: str) -> dict:
    """Ask the company brain on a throwaway GRAPH.COPY of `source`: never on the graph being forgotten from, where the
    question's SAW edges would change the relationship counts the forget token is bound to (review M17 H5)."""
    from .brain.ask import ask

    db = gclient.engine()
    room = f"eval_{t}_ask_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, source, room)
    try:
        a = ask(question, t, graph=room)
        return {"answer": a.answer, "citations": sorted(set(a.citations)), "intent": a.intent}
    finally:
        gcopy.delete_if_exists(db, room)


def _flip(before: dict, after: dict, question: str) -> dict:
    return {"question": question, "before": before, "after": after,
            "no_longer_cited": sorted(set(before["citations"]) - set(after["citations"])),
            "answer_changed": before["answer"] != after["answer"]}


@app.post("/api/memory/forget")
def memory_forget(body: ForgetIn, request: Request, tenant: str = "acme") -> dict:
    """Forget with a receipt: without `token` → dry run (what would be deleted, and the receipt token); with the
    token + approver → delete exactly that set, write the receipt to audit_<tenant>, prove the vectors are gone."""
    from .memory import forget

    _limit(f"forget:{_ip(request)}", 10, 60)
    t = check_tenant(tenant)
    try:
        if not body.token:
            return {"dry_run": True, **forget.dry_run(t, body.doc_id)}
        if not body.approver:
            raise HTTPException(422, "approver required to execute a forget")
        doc = forget.dry_run(t, body.doc_id)["doc"]
        question = body.question or _forget_question(doc)
        before = _ask_on_copy(t, tenant_graph(t), question)   # the same question, before
        if settings.faultline_public and not _key_ok(request, "x-faultline-admin-key", settings.faultline_admin_key):
            # public demo: the live tenant graph is immutable to visitors; forget runs on a clean-room copy
            _shed_load()
            room = f"eval_{t}_forget_{uuid.uuid4().hex[:8]}"
            db = gclient.engine()
            gcopy.copy_graph(db, tenant_graph(t), room)
            try:
                out = {"dry_run": False, "clean_room": True, **forget.execute(t, body.doc_id, body.token, body.approver, graph=room)}
                try:
                    out["flip"] = _flip(before, _ask_on_copy(t, room, question), question)
                except GraphError as e:   # the forget stands; only the demonstration failed, and it says so
                    out["flip"] = {"question": question, "error": _client_error_text(e)}
                return out
            finally:
                gcopy.delete_if_exists(db, room)
        out = {"dry_run": False, "clean_room": False, **forget.execute(t, body.doc_id, body.token, body.approver)}
        from .brain import scratch as brain_scratch

        brain_scratch.invalidate(t)  # brain copies still hold what was forgotten: retire them now
        try:
            out["flip"] = _flip(before, _ask_on_copy(t, tenant_graph(t), question), question)   # … and after
        except GraphError as e:
            out["flip"] = {"question": question, "error": _client_error_text(e)}
        return out
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    except GraphError as e:
        raise _graph_error(e) from e


@app.get("/api/preflight")
def preflight_last(pr: str, tenant: str = "acme") -> dict:
    """The latest recorded preflight of a PR (read from the graph: its Run's preflight_change evidence)."""
    if not 3 <= len(pr) <= 200:
        raise HTTPException(422, "bad pr id")
    try:
        rows = RO(check_tenant(tenant)).run("Q-PRE-LAST", {"pr": pr}).rows
    except GraphError as e:
        raise _graph_error(e) from e
    if not rows:
        raise HTTPException(404, f"no preflight recorded for {pr}")
    from .preflight.comment import render

    r = rows[0]
    payload = _stored_json(r["payload"], {})
    facts = RO(check_tenant(tenant)).run("Q-PRE-FACTS", {"pr": pr}).rows
    res = {"pr": pr, "run_id": r["run"], **{k: v for k, v in payload.items() if k != "rows"},
           "assessment": (payload.get("rows") or [{}])[0], "facts": facts, "notes": [], "unknown_files": [],
           "evidence": {"evidence_id": r["evidence_id"], "template": "preflight_change", "cypher": r["cypher"],
                        "params": json.loads(r["params"]) if r["params"] else None},
           "at": r["at"], "recorded": True}
    res["comment"] = render(res)
    return res


class OverrideIn(BaseModel):
    change: str = Field(min_length=1, max_length=160)
    verdict: str = Field(pattern="^(intentional|accidental|discuss)$")
    why: str = Field(min_length=3, max_length=500)
    plan_hash: str | None = Field(default=None, max_length=64)
    approver: str | None = Field(default=None, max_length=80)
    incident: str | None = Field(default=None, max_length=120)  # the change lives in this incident's graph


@app.post("/api/decisions/{decision}/override")
def decision_override(decision: str, body: OverrideIn, request: Request, tenant: str = "acme") -> dict:
    """A reviewer answers a contradiction for ONE change (M15 #3), in two steps like an action: without `plan_hash`
    it returns the contradiction as the graph holds it now and the hash binding {decision, change, verdict, why, the
    asserted value}; with that hash and an approver it writes the Override (one query). An intentional override stops
    G8 and preflight reporting that decision as violated for that change; accidental and discuss keep the violation."""
    import hashlib

    from .agent.rules import violated

    _limit(f"override:{_ip(request)}", 20, 60)
    t = check_tenant(tenant)
    # the graph that holds the change: an incident's room (its scenario change exists only there, and the run token
    # guards it like choose/approve), or the tenant graph (preflight PRs, history)
    if body.incident:
        loc = _locate(body.incident, t)
        _run_token_ok(request, t, loc)
        graph = loc.get("graph") or tenant_graph(t)
    else:
        graph = tenant_graph(t)
    rows = RO(t, graph).run("Q-DEC-ONE", {"change": body.change, "decision": decision}).rows
    if not rows:
        raise HTTPException(404, f"{body.change} asserts nothing that decision {decision} constrains")
    row = rows[0]
    if not violated(row["op"], row["actual"], row["expected"]):
        raise HTTPException(409, f"{body.change} does not contradict {decision} ({row['rule_key']} {row['actual']}); nothing to override")
    canon = json.dumps({"decision": decision, "change": body.change, "verdict": body.verdict, "why": body.why.strip(),
                        "actual": row["actual_text"], "tenant": t, "graph": graph}, sort_keys=True)
    plan_hash = hashlib.sha256(canon.encode()).hexdigest()
    view = {"decision": decision, "change": body.change, "verdict": body.verdict, "why": body.why.strip(),
            "contradiction": {k: row[k] for k in ("title", "rule_key", "op", "expected", "actual", "about")},
            "current_override": row.get("override"), "plan_hash": plan_hash}
    if body.plan_hash is None:
        return view | {"step": "review: approve this exact override by sending the plan_hash back with an approver"}
    _approver_ok(request)
    if settings.faultline_public and not _key_ok(request, "x-faultline-approver-key", settings.faultline_approver_key):
        raise HTTPException(403, "on the public demo an override needs the approver key (it changes what G8 and preflight report)")
    if body.plan_hash != plan_hash:
        raise HTTPException(409, "stale or edited override: the plan hash no longer matches (re-review it)")
    if not body.approver or not RO(t, graph).run("Q-PERSON-1", {"person": body.approver}).rows:
        raise HTTPException(422, f"approver {body.approver!r} is not an active person in this tenant's graph")
    oid = writes.record_override(gclient.engine().select_graph(graph), decision=decision, change=body.change,
                                 verdict=body.verdict, by=body.approver, why=body.why.strip(), plan_hash=plan_hash,
                                 actual=row["actual_text"])
    return view | {"step": "recorded", "override": oid}


class HumanFixIn(BaseModel):
    change: str = Field(min_length=1, max_length=160)
    by: str = Field(min_length=1, max_length=60)
    why: str = Field(min_length=3, max_length=300)


class EdgeApproveIn(BaseModel):
    plan_hash: str = Field(min_length=64, max_length=64)
    approver: str = Field(min_length=1, max_length=60)


@app.post("/api/incidents/{inc}/human-fix")
def incident_human_fix(inc: str, body: HumanFixIn, request: Request, tenant: str = "acme") -> dict:
    """M15 #4: after the gate escalated or did not confirm, a human names the change they believe caused it. It
    becomes an enabled rollback option (then choose → approve → execute → verify as any action); the gate's own
    verdict is unchanged."""
    from .memory import edges

    _limit(f"humanfix:{_ip(request)}", 10, 60)
    c, loc = _actx(inc, check_tenant(tenant))
    _run_token_ok(request, c.tenant, loc)
    try:
        return edges.human_fix_option(c, change=body.change, by=body.by, why=body.why)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/incidents/{inc}/edge-proposals")
def incident_edge_proposals(inc: str, request: Request, tenant: str = "acme") -> dict:
    """M15 #4: the failure links a VERIFIED fix of this incident showed the graph was missing (proposed by the execute
    job right after an APPLIED verification; nothing is an edge until approved). Read-only (Q-EDGE-PROPOSALS)."""
    c, loc = _actx(inc, check_tenant(tenant))
    return {"incident": inc, "proposals": c.ro().run("Q-EDGE-PROPOSALS", {"inc": c.inc}).rows}


@app.post("/api/incidents/{inc}/edge-proposals/{pid}/approve")
def incident_edge_approve(inc: str, pid: str, body: EdgeApproveIn, request: Request, tenant: str = "acme") -> dict:
    """Approve exactly the reviewed proposal (plan hash): one query writes the learned PROPAGATES_TO pair."""
    from .memory import edges

    _limit(f"edgeapprove:{_ip(request)}", 10, 60)
    _approver_ok(request)
    c, loc = _actx(inc, check_tenant(tenant))
    _run_token_ok(request, c.tenant, loc)
    if not edges.approve(c, pid, body.plan_hash, body.approver):
        raise HTTPException(409, "stale or already-approved proposal (the plan hash must match the proposal as reviewed)")
    return {"approved": pid, "by": body.approver}


_play_lock = threading.Lock()


@app.get("/api/playground")
def playground_menu() -> dict:
    """Break the graph (M15 #2): the fixed menu of graph changes and the decision each should move."""
    from . import playground

    return {"scenario": playground.scenario_id(), "perturbations": playground.menu()}


@app.post("/api/playground/{kind}")
def playground_run(kind: str, request: Request) -> dict:
    """Apply one menu change to a GRAPH.COPY of the scenario's clean room, run the product on both rooms, return the
    decision diff with the templates that decide each one. Both rooms are deleted afterwards. One at a time; rate-
    limited like scenario runs (it copies graphs and runs the product twice)."""
    from . import playground

    if kind not in playground.perturbations():
        raise HTTPException(404, f"unknown perturbation {kind!r}; see GET /api/playground")
    _limit(f"play:{_ip(request)}", 12 if settings.faultline_public else 30, 3600,
           global_n=100 if settings.faultline_public else None)
    t = "acme"  # the playground's scenario tenant (data/scenarios/playground.yaml → S1)
    if settings.faultline_public:  # deterministic: a recorded diff is served, no rooms copied (engine memory)
        last = RO(t, audit_graph(t)).run("Q-PLAY-LAST", {"kind": kind}).rows
        if last:
            return json.loads(last[0]["result"]) | {"cached": True, "recorded_at": last[0]["at"]}
    _shed_load()
    if not _play_lock.acquire(blocking=False):
        raise HTTPException(429, "a playground run is in progress; try again in a few seconds")
    try:
        res = playground.run(kind)
        writes.append_audit(gclient.engine().select_graph(audit_graph(t)), "PlaygroundRun",
                            {"kind": kind, "result": json.dumps(res, default=str, sort_keys=True)})
        return res | {"cached": False}
    except GraphError as e:
        raise _graph_error(e) from e
    finally:
        _play_lock.release()


@app.post("/api/preflight")
def preflight(body: dict, request: Request, tenant: str = "acme") -> dict:
    """Mode B pre-deploy gate: ingest the PR's changed files, extract facts, decide allow/require_review/block from
    graph queries + weights.yaml. Optional FAULTLINE_PREFLIGHT_KEY guards it when the API is public."""
    import hmac

    from pydantic import ValidationError

    from .preflight.comment import render
    from .preflight.engine import PreflightIn, run

    _limit(f"preflight:{_ip(request)}", 30, 60, global_n=600 if settings.faultline_public else None)
    key = settings.faultline_preflight_key
    keyed = bool(key) and hmac.compare_digest(request.headers.get("authorization", "").removeprefix("Bearer ").encode(), key.encode())
    if key and not keyed and not settings.faultline_public:
        raise HTTPException(401, "preflight key required")
    t = check_tenant(tenant)
    try:
        if "files" not in body and {"repo", "number"} <= set(body):  # fetch the PR itself by {repo, number}
            from .actions import github as gh
            from .preflight.engine import PRRef, fetch

            ref = PRRef.model_validate(body)
            # only repos the tenant graph knows, unless the caller holds the preflight key: an anonymous visitor must
            # never make the server read an arbitrary repo with the operator's GitHub auth
            if not keyed and not RO(t).run("Q-PRE-REPO", {"repo": ref.repo, "suffix": "/" + ref.repo}).rows[0]["known"]:
                raise HTTPException(403, f"{ref.repo} is not a repository this tenant's graph knows; send the PR's files, "
                                         "or present the preflight key to fetch it")
            try:
                pr = fetch(ref, gh.client(tenant_graph(t)))
            except gh.GitHubError as e:
                raise HTTPException(502, f"GitHub could not be read: {e}") from e
        else:
            pr = PreflightIn.model_validate(body)
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, str(e.errors()[0]["msg"]) if isinstance(e, ValidationError) else str(e)) from e
    if settings.faultline_public and not keyed:  # visitors' PRs are assessed on a clean-room copy, never recorded
        _shed_load()
        room = f"eval_{t}_preflight_{uuid.uuid4().hex[:8]}"
        db = gclient.engine()
        gcopy.copy_graph(db, tenant_graph(t), room)
        try:
            res = {**run(t, pr, graph=room), "recorded": False}
        finally:
            gcopy.delete_if_exists(db, room)
    else:
        res = {**run(t, pr), "recorded": True}
    return {**res, "comment": render(res)}


@app.get("/api/templates/{tid}")
def template(tid: str) -> dict:
    try:
        t = load(tid)
    except KeyError as e:
        raise HTTPException(404, f"unknown template {tid}") from e
    return {"id": t.id, "purpose": t.purpose, "cypher": t.display, "file": t.path, "limit": t.limit, "internal": t.internal,
            "home": t.home}


def _runnable(tid: str):
    """A template a client may run or profile: known, and not internal (Telegram ids, consents and contract offers are
    read only by the product itself; security review M19 #4)."""
    try:
        t = load(tid)
    except KeyError as e:
        raise HTTPException(404, f"unknown template {tid}") from e
    if t.internal:
        raise HTTPException(403, f"{tid} is internal: the product reads it, clients cannot run it")
    return t


class TemplateParams(BaseModel):
    params: dict = Field(default_factory=dict)
    incident: str | None = None
    tenant: str = "acme"
    # which of the tenant's own durable graphs to read (default: the template's `// home:`); an incident's clean room
    # is chosen with `incident` instead. Never a graph name: only these four words
    graph: str | None = Field(default=None, pattern="^(tenant|oncall|audit|agentmem)$")


def _template_graph(t: str, tmpl, body: "TemplateParams") -> str:
    """Where a re-run or a profile reads: the incident's run graph when `incident` is given (as before), else the
    tenant graph the caller names (`graph`: tenant, oncall, audit or agentmem), else the template's home graph: learned state,
    pages and contracts live in oncall_<t>, the run index and receipts in audit_<t>, so a re-run of them on tenant_<t>
    returned nothing."""
    from .actions import oncall

    if body.incident:
        graph = _locate(body.incident, t)["graph"]
    else:
        home = body.graph or tmpl.home
        if home == "agentmem":  # shared agent notes (made on first use, like the on-call home)
            from .memory import notes

            graph = notes.ensure_memory_graph(t)
        else:
            graph = oncall.home_graph(t) if home == "oncall" else audit_graph(t) if home == "audit" else tenant_graph(t)
    if not graph_belongs_to(graph, t):
        raise HTTPException(403, "graph does not belong to tenant")
    return graph


@app.post("/api/templates/{tid}/profile")
def template_profile(tid: str, body: TemplateParams, request: Request) -> dict:
    _limit(f"profile:{_ip(request)}", 30, 60, global_n=60)
    t = check_tenant(body.tenant)
    tmpl = _runnable(tid)
    try:
        graph = _template_graph(t, tmpl, body)
        return {"id": tid, **profile(t, tid, body.params, graph)}
    except KeyError as e:
        raise HTTPException(404, f"unknown template {tid}") from e
    except GraphError as e:
        raise _graph_error(e) from e


@app.post("/api/templates/{tid}/run")
def template_run(tid: str, body: TemplateParams, request: Request) -> dict:
    _limit(f"rerun:{request.client.host if request.client else '-'}", 30, 60)
    t = check_tenant(body.tenant)
    tmpl = _runnable(tid)
    try:
        graph = _template_graph(t, tmpl, body)
        r = RO(t, graph).run(tid, body.params)
        return {"rows": r.rows, "ms": round(r.ms, 2), "digest": r.digest, "truncated": r.truncated, "served_by": r.served_by,
                "cypher": r.cypher, "graph": graph, "home": tmpl.home}
    except KeyError as e:
        raise HTTPException(404, f"unknown template {tid}") from e
    except GraphError as e:
        raise _graph_error(e) from e


# ------------------------------------------------------------------ demo
_AUDIT_SALT = settings.faultline_audit_salt or uuid.uuid4().hex + uuid.uuid4().hex


def _ip_hash(ip: str) -> str:
    """Keyed hash of a client IP for the audit graph (HMAC-SHA256 with FAULTLINE_AUDIT_SALT or a per-process random
    salt): an unsalted hash of an IPv4 address is reversible by enumerating all 2^32 of them."""
    import hashlib
    import hmac

    return hmac.new(_AUDIT_SALT.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


@app.post("/api/demo/rearm")
def rearm(request: Request, tenant: str = "acme") -> dict:
    """Re-arm the tenant graph from its golden copy (copy-then-swap). Sheds load first (a re-arm copies a whole graph),
    retires the brain copies, resets the tenant graph's simulated world and puts the warehouse transforms back to
    pristine. The swap IS the re-arm: a failed audit write afterwards is reported as
    "re-armed (audit write failed)", never as a failed re-arm."""
    ip = request.client.host if request.client else "-"
    _limit(f"rearm:{ip}", 1, 60)
    _limit("rearm:global", 20, 3600)
    _shed_load()
    try:
        from . import scenario
        from .actions import github as gh
        from .brain import scratch as brain_scratch

        t = check_tenant(tenant)
        out = gcopy.rearm(gclient.engine(), t, reason="api", ip_hash=_ip_hash(ip))
    except GraphError as e:
        raise _graph_error(e) from e
    out["status"] = "re-armed" if out.get("audit") == "written" else "re-armed (audit write failed)"
    for what, step in (("brain", lambda: brain_scratch.invalidate(t)),  # copies of the old tenant graph are retired
                       ("sim", lambda: None if gh.is_real() else gh.reset_sim(tenant_graph(t))),
                       ("warehouse", lambda: scenario.restore_warehouse(timeout=2.0))):
        try:
            res = step()
            if what == "warehouse":
                out["warehouse"] = res
        except Exception as e:  # noqa: BLE001 - the tenant graph is re-armed; a follow-up step is reported, not raised
            out.setdefault("followups_failed", []).append(f"{what}: {_client_error_text(e)}")
    return out




# ------------------------------------------------------------------ M19: real on-call (pages, acks, escalation, contracts)
# Every read below is a catalogue template through the RO wrapper (actions/oncall.py, actions/contracts.py); every
# write is one atomic query in graph/writes.py. Public mode keeps its rules: acking needs the page's signed token, the
# run token of the page's incident or the approver key; granting/revoking a contract and writing a hand-off change what
# every visitor's later incidents do, so on the public demo they need the approver key.
class AckIn(BaseModel):
    token: str | None = Field(default=None, max_length=200)
    by: str | None = Field(default=None, min_length=1, max_length=60)   # with the approver key: who acknowledges
    now: int | None = Field(default=None, ge=0, le=4_102_444_800_000)   # scripted clock (tests, evals); refused in public


def _approver_key_given(request: Request) -> bool:
    return _key_ok(request, "x-faultline-approver-key", settings.faultline_approver_key)


def _now_param(now: int | None) -> int:
    """`now` overrides the clock for scripted tests and evals only; refused on the public demo."""
    from .actions import oncall

    if now is None:
        return oncall.now_ms()
    if settings.faultline_public:
        raise HTTPException(403, "the clock cannot be overridden on the public demo")
    return int(now)


def _page_in_tenant(t: str, pid: str) -> tuple[str, dict]:
    from .actions import oncall

    if not re.fullmatch(r"pg-[0-9a-f]{6,40}", pid):
        raise HTTPException(422, "bad page id")
    hit = oncall.locate_page(t, pid)
    if hit is None:
        raise HTTPException(404, f"unknown page {pid} for tenant {t}")
    return hit


def _page_run_token_ok(request: Request, t: str, graph: str, inc: str | None) -> bool:
    """The visitor who started the run that opened this page's incident (its run token) may act on its pages."""
    import hashlib

    given = request.headers.get("x-faultline-run-token", "")
    if not given or not inc:
        return False
    try:
        loc = _locate(inc, t)
    except HTTPException:
        return False
    rows = RO(t, graph).run("Q-RUN-TOKEN", {"run": loc["run"]}).rows
    sha = (rows[0]["token_sha"] if rows else None) or ""
    import hmac

    return bool(sha) and hmac.compare_digest(hashlib.sha256(given.encode()).hexdigest(), sha)


def _with_ack_token(t: str, row: dict, request: Request, *, detail: bool = False) -> dict:
    """In-app acks: off the public demo the operator's console gets each page's signed token (as it may approve without
    a key there); on the public demo only the holder of the incident's run token does, and only on GET /api/pages/{id}
    (`detail`), never in a list."""
    from .actions import oncall

    if row.get("kind") in ("page", "escalation") and row.get("status") in ("sent", "delivery_failed"):
        if not settings.faultline_public or (detail and _page_run_token_ok(request, t, row.get("graph") or "",
                                                                           row.get("incident"))):
            return {**row, "ack_token": oncall.page_token(t, row["id"])}
    return row


@app.get("/api/oncall/now")
def oncall_now(tenant: str = "acme", at: int | None = None) -> dict:
    """Who is on call per team at `at` (default now): Q-ONCALL-NOW on the tenant graph's ON_CALL rota."""
    from .actions import oncall

    return oncall.oncall_now(check_tenant(tenant), at)


@app.get("/api/pages")
def pages(request: Request, tenant: str = "acme", status: str | None = None, incident: str | None = None) -> dict:
    """The pager inbox across the tenant graph and its run graphs (Q-PAGES in each), newest first, with the delivery
    channels and whether each is configured. `status`: a comma list, or `open` (sent + delivery_failed)."""
    from .actions import channels, oncall

    _limit(f"pages:{_ip(request)}", 60, 60, global_n=1200 if settings.faultline_public else None)
    _shed_load()   # a listing reads every graph that holds pages
    t = check_tenant(tenant)
    sts = [] if not status else (["sent", "delivery_failed"] if status == "open" else
                                 [x.strip() for x in status.split(",") if x.strip()])
    if any(x not in ("sent", "delivery_failed", "acked", "escalated", "resolved", "superseded") for x in sts):
        raise HTTPException(422, "status must be open or a comma list of page statuses")
    if incident is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", incident):
        raise HTTPException(422, "bad incident id")
    graphs = None
    if incident:
        loc = _locate(incident, t)
        graphs = [loc["graph"]]
    out = oncall.list_pages(t, statuses=sts, incident=incident or "", graphs=graphs)
    out["rows"] = [_with_ack_token(t, r, request) for r in out["rows"]]
    out["channels"] = channels.configured()
    out["ack_tokens"] = oncall.token_policy()
    return out


@app.get("/api/pages/{pid}")
def page_detail(pid: str, request: Request, tenant: str = "acme") -> dict:
    """One page for the phone view: the page, its incident's one-liner (stage, confirmed cause), the proof chain the
    gate accepted (G2, Q-GATE-1), who fixes it (who_fixes as recorded at ROUTE), the obligation clock's breach and the
    escalation chain (Q-PAGE-CHAIN). All read from the graph."""
    from .actions import oncall

    _limit(f"page:{_ip(request)}", 60, 60, global_n=1200 if settings.faultline_public else None)
    _shed_load()
    t = check_tenant(tenant)
    graph, row = _page_in_tenant(t, pid)
    ro = RO(t, graph)
    page = {**oncall.page_view(row), "graph": graph}
    out: dict[str, Any] = {"page": _with_ack_token(t, page, request, detail=True)}
    if page.get("ack_token"):
        out["ack_token"] = page["ack_token"]
    chain = ro.run("Q-PAGE-CHAIN", {"page": pid})
    out["chain"] = {"rows": [{**x, "person": {"id": x["person"], "name": x["person_name"]}} for x in chain.rows],
                    "template": chain.template_id, "params": chain.params, "ms": round(chain.ms, 2)}
    inc = row.get("incident")
    out["incident"], out["proof"], out["who_fixes"], out["obligations"] = None, None, None, None
    if inc:
        inc_row = (ro.run("Q-INC-1", {"inc": inc}).rows or [{}])[0]
        cause = (ro.run("Q-CAUSE-1", {"inc": inc}).rows or [{}])[0].get("cause")
        gates = ro.run("Q-INC-GATES", {"inc": inc}).rows
        passed = next((g for g in reversed(gates) if g["passed"]), None)
        line = (f"{inc_row.get('title') or inc}: the gate confirmed {cause} as the cause" if cause else
                f"{inc_row.get('title') or inc}: no cause confirmed by the gate (stage {inc_row.get('stage')})")
        out["incident"] = {"id": inc, "title": inc_row.get("title"), "line": line, "stage": inc_row.get("stage"),
                           "cause": cause, "onset_at": inc_row.get("onset_at"), "targets": inc_row.get("targets")}
        if passed:
            g2 = next((c for c in json.loads(passed["checks"] or "[]") if c.get("name") == "G2 path"), None)
            if g2 and g2.get("passed"):  # the first proven chain the gate accepted (" ; " between chains)
                first = str(g2.get("detail") or "").split(" ; ")[0].split(" (learned link")[0]
                nodes = [x.strip() for x in first.split("→") if x.strip()]
                out["proof"] = {"nodes": nodes, "rels": [], "template": g2.get("template") or "Q-GATE-1",
                                "params": g2.get("params"), "gate_run": passed["id"]}
        try:
            run = _locate(inc, t)["run"]
        except HTTPException:
            run = None
        for tool, key in (("who_fixes", "who_fixes"), ("obligation_clock", "obligations")):
            ev = ro.run("Q-EV-TOOL", {"run": run, "tool": tool}).rows if run else []
            if ev:
                payload = _stored_json(ev[0]["payload"], {})
                out[key] = ({"rows": payload.get("rows", [])[:5], "template": ev[0]["template"],
                             "evidence_id": ev[0]["evidence_id"]} if tool == "who_fixes" else
                            {"breach": payload.get("breach"), "urgent": payload.get("urgent"),
                             "reason": payload.get("reason"), "template": ev[0]["template"],
                             "evidence_id": ev[0]["evidence_id"]})
    return out


@app.post("/api/pages/{pid}/ack")
def page_ack(pid: str, body: AckIn, request: Request, tenant: str = "acme") -> dict:
    """Acknowledge a page: (:Person)-[:ACKED {at, via}]->(:Page) in one write; escalation of its incident stops and
    the incident's other open pages are superseded. Accepted credentials: the page's signed token (its deep link), the
    approver key (then `by` may name who acknowledges), or the run token of the page's incident. 409 when the page no
    longer waits for an ack."""
    from .actions import oncall

    _limit(f"ack:{_ip(request)}", 30, 60)
    t = check_tenant(tenant)
    graph, row = _page_in_tenant(t, pid)
    if oncall.token_ok(t, pid, body.token):
        via = "token"
    elif _approver_key_given(request):
        via = "approver_key"
    elif _page_run_token_ok(request, t, graph, row.get("incident")):
        via = "run_token"
    else:
        raise HTTPException(403, "acknowledging a page needs its signed token (the page link), the run token of its "
                                 "incident, or the approver key")
    now = _now_param(body.now)
    if via == "token" or (via == "approver_key" and body.by):
        # the page's own link went to the paged person; the approver key may name who acknowledges
        by = body.by if via == "approver_key" else row["person"]
        res = oncall.ack(t, graph, pid, by, via, now=now)
    else:   # the holder of the run token or of the approver key without a name: recorded as who acted, not as the paged
        # person, and left out of MTTA (security review M19 #11)
        by = None
        res = oncall.ack_anonymous(t, graph, pid, via, "run-token holder" if via == "run_token" else "approver-key holder",
                                   now=now)
    if res is None:
        raise HTTPException(409, f"page {pid} is {row.get('status')}" + (f" (or {by!r} is not an active person)" if by else "")
                            + ": nothing to acknowledge")
    from .memory import learning

    learned = learning.on_ack(t, graph, res, via=via, key=via == "approver_key") if res.get("by") else None
    return {"acked": True, **res, "by": ({"id": res["by"], "name": res["name"]} if res.get("by") else
                                         {"id": None, "name": res["name"]}), "graph": graph, "learned": learned}


class TickIn(BaseModel):
    now: int | None = Field(default=None, ge=0, le=4_102_444_800_000)
    incident: str | None = Field(default=None, max_length=160)   # scripted runs: only this incident's graph


@app.post("/api/oncall/tick")
def oncall_tick(request: Request, body: TickIn | None = None, tenant: str = "acme") -> dict:
    """One escalation pass now (the background tick runs every weights.yaml oncall.tick_every_s): Q-PAGE-OVERDUE →
    Q-PAGE-NEXT → one write per incident. `now` (scripted tests and evals only) is refused on the public demo."""
    from .actions import oncall

    _limit(f"tick:{_ip(request)}", 30, 60)
    if settings.faultline_public and not _approver_key_given(request):   # the background tick runs anyway
        raise HTTPException(403, "on the public demo an on-demand escalation tick needs the approver key")
    t = check_tenant(tenant)
    now = _now_param(body.now if body else None)
    graphs = None
    if body and body.incident:  # a scripted clock must never escalate another run's pages: scope it to one incident
        graphs = [_locate(body.incident, t)["graph"]]
    return {"tenant": t, "now": now, "escalated": oncall.tick(t, graphs=graphs, now=now)}


class ContractIn(BaseModel):
    step: str = Field(pattern="^(choose|approve)$")
    scope: dict | None = None
    hash: str | None = Field(default=None, min_length=64, max_length=64)
    approver: str | None = Field(default=None, min_length=1, max_length=60)
    approver_key: str | None = Field(default=None, max_length=200)
    action_id: str | None = Field(default=None, max_length=120)


@app.post("/api/incidents/{inc}/contract")
def incident_contract(inc: str, body: ContractIn, request: Request, tenant: str = "acme") -> dict:
    """A standing approval for repeats, in two steps like an action. choose {scope: {max_uses, days}} → the exact grant
    and its hash (an offer; nothing is active); approve {hash, approver} → the contract, only if this incident's action
    was verified APPLIED, the approver may approve on it (Q-APPROVER-1) and the hash is the offer's (single use,
    before it expires). On the public demo approving needs the approver key."""
    from .actions import contracts, oncall

    _limit(f"contract:{_ip(request)}", 10, 60)
    c, loc = _actx(inc, check_tenant(tenant))
    _run_token_ok(request, c.tenant, loc)
    home = oncall.home_graph(c.tenant)
    if body.step == "choose":
        scope = body.scope or {}
        try:
            max_uses, days = int(scope.get("max_uses", 3)), float(scope.get("days", 7))
            return contracts.offer(tenant=c.tenant, graph=c.graph, inc=inc, home=home, max_uses=max_uses, days=days,
                                   action_id=body.action_id)
        except (TypeError, ValueError) as e:
            raise HTTPException(409 if isinstance(e, contracts.ContractRefused) else 422, str(e)) from e
    if not body.hash or not body.approver:
        raise HTTPException(422, "approve needs the hash from the choose step and an approver")
    _approver_ok(request)
    if settings.faultline_public and not (_approver_key_given(request) or (
            body.approver_key and settings.faultline_approver_key
            and _key_ok_value(body.approver_key, settings.faultline_approver_key))):
        raise HTTPException(403, "on the public demo a standing contract needs the approver key (it changes what later "
                                 "incidents do for every visitor)")
    offer = contracts.offer_row(c.tenant, home, body.hash)
    if offer is None or offer.get("source_incident") != inc:
        raise HTTPException(409, "no offer with this hash for this incident (choose the scope first)")
    who = _approver_checked(c, body.approver)
    from .actions import github as gh

    # _approver_ok above refused a real-GitHub grant without the approver key: this grant carries that authority
    granted = contracts.grant(tenant=c.tenant, home=home, hash_=body.hash, by=body.approver, real_ok=gh.is_real())
    if granted is None:
        raise HTTPException(409, "stale, expired or already-granted offer: choose the scope again")
    from .memory import learning

    ok, _ = learning.trusted(c.tenant, c.graph, inc, key=_approver_key_given(request))
    learning.on_note(c.tenant, "grant", body.approver, key_parts=[granted["id"]], family=granted.get("family"),
                     trusted_=ok, contract=granted["id"], action_kind=granted.get("action_kind"),
                     params_hash=granted.get("params_hash"), incident=inc, graph=c.graph)
    return {"granted": True, "contract": granted, "approver": who}


def _key_ok_value(given: str, expected: str) -> bool:
    import hmac

    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


@app.get("/api/contracts")
def contracts_list(tenant: str = "acme") -> dict:
    """The tenant's standing approvals (Q-CONTRACTS on the on-call home graph): scope, uses, status at now, revocation."""
    from .actions import contracts, oncall

    t = check_tenant(tenant)
    return contracts.listing(t, oncall.home_graph(t))


class RevokeIn(BaseModel):
    by: str | None = Field(default=None, max_length=80)


@app.post("/api/contracts/{cid}/revoke")
def contract_revoke(cid: str, request: Request, body: RevokeIn | None = None, tenant: str = "acme") -> dict:
    """Revoke a standing approval now (one write; a later incident is paged as usual). Public demo: approver key."""
    from .actions import contracts, oncall

    _limit(f"revoke:{_ip(request)}", 10, 60)
    t = check_tenant(tenant)
    if not re.fullmatch(r"ct-[0-9a-f]{16}", cid):
        raise HTTPException(422, "bad contract id")
    if settings.faultline_public and not _approver_key_given(request):
        raise HTTPException(403, "on the public demo revoking a contract needs the approver key")
    by = (body.by if body and body.by else None) or ("approver_key" if _approver_key_given(request) else "operator")
    if not contracts.revoke(home=oncall.home_graph(t), cid=cid, by=by):
        raise HTTPException(409, f"contract {cid} is unknown or no longer active")
    from .memory import learning

    learning.on_note(t, "revoke", by, key_parts=[cid], trusted_=not settings.faultline_public or _approver_key_given(request),
                     contract=cid)
    return {"revoked": True, "id": cid, "by": by}


@app.get("/api/oncall/report")
def oncall_report(request: Request, tenant: str = "acme", since: int | None = Query(default=None, alias="from"),
                  until: int | None = Query(default=None, alias="to")) -> dict:
    """The shift (morning) report for [from, to) (default: the last 12 hours): incidents, pages, acks, approved actions
    and verdicts, contract uses and hand-offs (Q-SHIFT-REPORT in every graph of the tenant)."""
    from .actions import oncall

    _limit(f"oncall-report:{_ip(request)}", 20, 60, global_n=400 if settings.faultline_public else None)
    _shed_load()
    t = check_tenant(tenant)
    to = oncall.now_ms() if until is None else int(until)
    frm = to - 12 * 3_600_000 if since is None else int(since)
    if frm > to:
        raise HTTPException(422, "from must not be after to")
    return oncall.report(t, since=frm, until=to)


class HandoffIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    to: str = Field(min_length=1, max_length=60)
    incident: str | None = Field(default=None, max_length=160)
    from_: str | None = Field(default=None, alias="from", max_length=60)


@app.post("/api/handoffs")
def handoff(body: HandoffIn, request: Request, tenant: str = "acme") -> dict:
    """Hand the shift over: (:Handoff)-[:FROM]->(outgoing), -[:TO]->(incoming), -[:COVERS]->(incident) in the tenant
    graph, plus a report page to the incoming person. `from` defaults to who is on call now for the incoming person's
    team (Q-HANDOFF-FROM). Public demo: approver key."""
    from .actions import oncall

    _limit(f"handoff:{_ip(request)}", 10, 60)
    t = check_tenant(tenant)
    if settings.faultline_public and not _approver_key_given(request):
        raise HTTPException(403, "on the public demo a hand-off needs the approver key (it is written to the tenant graph)")
    try:
        out = oncall.hand_off(t, from_=body.from_, to=body.to, note=body.note, inc=body.incident or "")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    from .memory import learning

    learning.on_note(t, "handoff", out["from"], key_parts=[out["id"]], trusted_=True, to=out["to"],
                     incident=out.get("incident"), handoff=out["id"])
    return {"handoff": out}


def _sha256_hex(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode()).hexdigest()


@app.get("/api/oncall/stats")
def oncall_stats(request: Request, tenant: str = "acme", days: float = Query(default=7, gt=0, le=90)) -> dict:
    """MTTA (first page → first ack), MTTR (opened → RESOLVED), people paged and incidents handled under a standing
    contract over the last `days` (Q-ONCALL-STATS per graph, durations computed in Cypher)."""
    from .actions import oncall

    _limit(f"oncall-stats:{_ip(request)}", 20, 60, global_n=400 if settings.faultline_public else None)
    _shed_load()
    t = check_tenant(tenant)
    since = oncall.now_ms() - int(days * 86_400_000)
    return {"days": days, **oncall.stats(t, since=since)}


# ------------------------------------------------------------------ what Faultline learned (M21, T2), in the on-call home
@app.get("/api/learned")
def learned(request: Request, tenant: str = "acme") -> dict:
    """Everything Faultline learned from the people using it: preferences (per family and action kind, decayed),
    guidelines (proposed / active / dismissed), learned responders (RESPONDED), knowledge gaps, contract suggestions and
    the recent learning events, each section with the FalkorDB query that produced it. Read-only."""
    from .memory import learning

    _limit(f"learned:{_ip(request)}", 60, 60, global_n=1200 if settings.faultline_public else None)
    try:
        return learning.state(check_tenant(tenant))
    except GraphError as e:
        raise _graph_error(e) from e


def _learn_admin(request: Request, who: str | None, what: str) -> str:
    """Changing learned state: on the public demo only with the approver key (visitors can never poison or erase
    it); the person acting must be an active person of the tenant (checked by the write, or here)."""
    _limit(f"learn-admin:{_ip(request)}", 20, 60)
    if settings.faultline_public and not _approver_key_given(request):
        raise HTTPException(403, f"on the public demo {what} needs the approver key")
    if not who:
        raise HTTPException(422, f"{what} needs `by` (an active person of this tenant)")
    return who


class GuidelineIn(BaseModel):
    action: str = Field(pattern="^(promote|dismiss)$")
    by: str = Field(min_length=1, max_length=60)


@app.post("/api/learned/guidelines/{gid}")
def learned_guideline(gid: str, body: GuidelineIn, request: Request, tenant: str = "acme") -> dict:
    """Promote a proposed guideline (an option against it then needs an explicit override to be approved) or dismiss
    one (it disappears from plans). One conditional write; 409 when the guideline is not in a status that allows it or
    `by` is not an active person."""
    from .memory import learning

    if not re.fullmatch(r"gl-[0-9a-f]{6,40}", gid):
        raise HTTPException(422, "bad guideline id")
    by = _learn_admin(request, body.by, f"{body.action} a guideline")
    t = check_tenant(tenant)
    before = learning.guideline(t, gid)
    if before is None:
        raise HTTPException(404, f"unknown guideline {gid}")
    after = learning.set_guideline(t, gid, body.action, by)
    if after is None:
        raise HTTPException(409, f"guideline {gid} is {before['status']}, or {by!r} is not an active person: cannot "
                                 f"{body.action} it")
    return {"guideline": after, "action": body.action, "before": before["status"], "by": by,
            "template": "Q-LEARN-GUIDE-1"}


class GapDismissIn(BaseModel):
    by: str = Field(min_length=1, max_length=60)


@app.post("/api/learned/gaps/{gid}/dismiss")
def learned_gap_dismiss(gid: str, body: GapDismissIn, request: Request, tenant: str = "acme") -> dict:
    """Dismiss a knowledge gap (it re-opens if a trusted user asks the question again). 409 when not open."""
    from .memory import learning

    if not re.fullmatch(r"kg-[0-9a-f]{6,40}", gid):
        raise HTTPException(422, "bad gap id")
    by = _learn_admin(request, body.by, "dismissing a knowledge gap")
    res = learning.dismiss_gap(check_tenant(tenant), gid, by)
    if res is None:
        raise HTTPException(409, f"knowledge gap {gid} is unknown or not open")
    return {"gap": res, "by": by}


class LearnForgetIn(BaseModel):
    person: str = Field(pattern=r"^[A-Za-z0-9_.@:-]{1,80}$")
    token: str | None = Field(default=None, min_length=64, max_length=64)
    approver: str | None = Field(default=None, min_length=1, max_length=60)


@app.post("/api/learned/forget")
def learned_forget(body: LearnForgetIn, request: Request, tenant: str = "acme") -> dict:
    """Forget a person's learned influence, with a receipt (T2: memory with receipts). Without `token`: the dry run
    (every learning event they contributed, the guidelines they proposed, what will be recomputed, and the receipt
    token). With the token and an approver: exactly that set is deleted (one write), every preference, responder edge
    and knowledge gap it fed is recomputed in Cypher, a ForgetReceipt is written to audit_<tenant>, and the proof
    re-reads that none of their events is left and no preference still cites one."""
    from .memory import learning

    t = check_tenant(tenant)
    try:
        if not body.token:
            _limit(f"learn-forget:{_ip(request)}", 20, 60)
            return {"dry_run": True, **learning.forget_dry_run(t, body.person)}
        approver = _learn_admin(request, body.approver, "forgetting a person's learned influence")
        if not RO(t, learning.home(t)).run("Q-PERSON-1", {"person": approver}).rows:
            raise HTTPException(422, f"approver {approver!r} is not an active person in this tenant's graph")
        return {"dry_run": False, **learning.forget_execute(t, body.person, body.token, approver)}
    except learning.ForgetRefused as e:
        raise HTTPException(409, str(e)) from e
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    except GraphError as e:
        raise _graph_error(e) from e


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    """The Telegram on-call bot (actions/telegram_bot.py): authenticated by the secret Telegram echoes
    (X-Telegram-Bot-Api-Secret-Token, constant-time), then every update is handled once (update_id recorded in the
    graph), only for users the operator mapped to a person (TELEGRAM_PEOPLE), rate-limited per chat. The bot is just
    another client: approving goes through Q-APPROVER-1 and the plan hash like the web UI, by a typed phrase. Always
    200 once authenticated (Telegram retries anything else); the body never carries a secret."""
    from .actions import channels, telegram_bot

    if not channels.telegram_secret_ok(request.headers.get("x-telegram-bot-api-secret-token", "")):
        raise HTTPException(403, "bad or missing webhook secret")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True, "ignored": "not json"}
    if not isinstance(update, dict):
        return {"ok": True, "ignored": "not an update"}
    try:
        out = await anyio.to_thread.run_sync(telegram_bot.handle, update)
    except Exception as e:  # noqa: BLE001 - never a 500 to Telegram (it would retry); the detail goes to the log
        rid = uuid.uuid4().hex[:12]
        log.error("telegram update failed (request %s): %s", rid, type(e).__name__)
        out = {"error": f"internal (request id {rid})"}
    return {"ok": True, **out}


# ------------------------------------------------------------------ the Telegram bot's entry points (M19)
# The bot is another client of the same paths: the person is the Telegram user's mapped person (TELEGRAM_PEOPLE, set by
# the operator), checked by Q-APPROVER-1 exactly as in the web UI; choosing renders the exact action and its plan hash;
# approving binds that hash and leases the intent like POST /approve. They raise HTTPException with the reason.
def bot_choose(t: str, inc: str, aid: str, person: str) -> dict:
    from .actions import act
    from .actions import github as gh

    c, loc = _actx(inc, t)
    who = _approver_checked(c, person)   # fail early: the same rule the approval applies
    _guideline_check(c, aid, None, None, can_override=False)   # M21: the bot cannot override an active guideline
    try:
        spec = act.choose(c, aid, gh.client(c.graph))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e)) from e
    except gh.GitHubError as e:
        raise HTTPException(502, f"GitHub: {_client_error_text(e)}") from e
    from .memory import learning

    learning.on_choose(c, aid, person, via="telegram")
    return {"spec": spec, "approver": who, "graph": c.graph, "run": c.run}


def bot_approve(t: str, inc: str, aid: str, plan_hash: str, person: str, tg_user: str) -> dict:
    from .actions import act
    from .actions import github as gh
    from .actions.boot import BOOT_ID

    if gh.is_real() and not settings.telegram_approve_real:
        raise HTTPException(403, "approving against real GitHub from Telegram is off on this server "
                                 "(TELEGRAM_APPROVE_REAL); approve in the web UI with the approver key")
    c, loc = _actx(inc, t)
    c.owner = f"{BOOT_ID}:act-tg-{uuid.uuid4().hex[:12]}"
    _work_enter(c.graph)
    started = False
    try:
        if not gcopy.exists(gclient.engine(), c.graph):
            raise HTTPException(410, _collected_text(inc))
        who = _approver_checked(c, person)
        _guideline_check(c, aid, None, None, can_override=False)   # M21: no override from the bot
        res = act.approve(c, aid, plan_hash, person, via="telegram", tg_user=tg_user)
        if res is None:
            raise HTTPException(409, "plan hash does not match the current chosen action, or the incident is not "
                                     "awaiting approval")
        if not res["mine"]:
            raise HTTPException(409, "an intent with this idempotency key already exists (another run owns it)")
        from .memory import learning

        learning.on_approve(c, aid, person, via="telegram")   # before the execute job (M21)
        threading.Thread(target=_act_job_tracked, args=(c, loc, aid), daemon=True).start()
        started = True
        _ack_by_approval(c, person)
    finally:
        if not started:
            _work_leave(c.graph)
    return {"approved": True, **res, "approver": who}


def bot_contract_offer(t: str, inc: str, person: str, max_uses: int, days: float) -> dict:
    from .actions import contracts, oncall

    c, loc = _actx(inc, t)
    _approver_checked(c, person)
    try:
        return contracts.offer(tenant=c.tenant, graph=c.graph, inc=inc, home=oncall.home_graph(c.tenant),
                               max_uses=max_uses, days=days)
    except contracts.ContractRefused as e:
        raise HTTPException(409, str(e)) from e


def bot_contract_grant(t: str, inc: str, hash_: str, person: str) -> dict:
    from .actions import contracts, oncall
    from .actions import github as gh

    if gh.is_real() and not settings.telegram_approve_real:
        raise HTTPException(403, "granting a standing contract against real GitHub from Telegram is off on this server "
                                 "(TELEGRAM_APPROVE_REAL); grant it in the web UI with the approver key")
    c, loc = _actx(inc, t)
    home = oncall.home_graph(c.tenant)
    offer = contracts.offer_row(c.tenant, home, hash_)
    if offer is None or offer.get("source_incident") != inc:
        raise HTTPException(409, "no offer with this hash for this incident")
    who = _approver_checked(c, person)
    granted = contracts.grant(tenant=c.tenant, home=home, hash_=hash_, by=person, real_ok=gh.is_real())
    if granted is None:
        raise HTTPException(409, "stale, expired or already-granted offer")
    return {"contract": granted, "approver": who}


def bot_brain(t: str, question: str, user: str) -> dict:
    """The company brain's own path (keyword routing → templates, every [id] through the citation guard); on the
    public demo it records in a bounded scratch copy, as a visitor's question does."""
    from .brain import scratch as brain_scratch
    from .brain.ask import ask

    if settings.faultline_public:
        with brain_scratch.use(t) as gname:
            return ask(question, t, "baseline", graph=gname).as_dict()
    return ask(question, t, "baseline").as_dict()


# ------------------------------------------------------------------ alert intake (Alertmanager v4 / generic JSON)
def _parse_alerts(body: dict) -> list[dict]:
    """Alertmanager v4 webhook ({alerts: [{status, labels: {service|job|alertname…, severity}, annotations: {summary},
    startsAt}]}) or a generic {service, metric, severity, summary} (or a list of them). Firing alerts only."""
    from datetime import datetime

    raw = body.get("alerts") if isinstance(body.get("alerts"), list) else [body]
    out = []
    for a in raw[:50]:
        if not isinstance(a, dict):
            continue
        if a.get("status") and a.get("status") != "firing":
            continue
        labels = a.get("labels") if isinstance(a.get("labels"), dict) else {}
        ann = a.get("annotations") if isinstance(a.get("annotations"), dict) else {}
        target = a.get("service") or labels.get("service") or labels.get("service_name") or labels.get("job") or labels.get("instance")
        metric = a.get("metric") or labels.get("metric") or labels.get("alertname") or "error_rate"
        at = None
        if a.get("startsAt"):
            try:
                at = int(datetime.fromisoformat(str(a["startsAt"]).replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                at = None
        if not target or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", str(target)):
            continue
        out.append({"target": str(target), "metric": re.sub(r"[^a-z0-9_]", "_", str(metric).lower())[:60] or "error_rate",
                    "severity": str(a.get("severity") or labels.get("severity") or "page")[:20],
                    "summary": str(a.get("summary") or ann.get("summary") or ann.get("description") or "")[:500],
                    "at": at})
    return out


@app.post("/api/alerts")
def alerts_intake(request: Request, body: Any = Body(...), tenant: str = "acme") -> dict:
    """Alert intake: the firing alerts become (:Alert)-[:FIRED_ON]->(component) in the tenant graph, INTAKE groups them
    (group_alerts, algo.WCC) into incidents, and each is investigated by the same run loop as a scenario, with
    on-call paging on (a background job). Nothing is simulated: the investigation reads the telemetry the graph holds,
    and with none it escalates to a human (paged). Needs FAULTLINE_ALERTS_KEY (bearer) when configured, always on the
    public demo."""
    import hashlib
    import secrets as _secrets

    from .actions import oncall

    _limit(f"alerts:{_ip(request)}", 30, 60)
    t = check_tenant(tenant)
    key = settings.faultline_alerts_key
    if key or settings.faultline_public:
        auth = request.headers.get("authorization", "")
        given = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-faultline-alerts-key", "")
        if not key or not _key_ok_value(given, key):
            raise HTTPException(401, "alert intake needs the bearer key (FAULTLINE_ALERTS_KEY)")
    alerts = _parse_alerts(body if isinstance(body, dict) else {"alerts": body if isinstance(body, list) else []})
    if not alerts:
        raise HTTPException(422, "no firing alert with a service/job label in the payload")
    graph = oncall.home_graph(t)   # the tenant's live graph: real incidents join its history (never a clean room)
    ro = RO(t, graph)
    known = [a for a in alerts if ro.run("Q-CTX-1", {"id": a["target"], "now": oncall.now_ms()}).rows]
    if not known:
        raise HTTPException(422, "none of the alerting services is a component of this tenant's graph: "
                                 + ", ".join(sorted({a["target"] for a in alerts}))[:300])
    _shed_load()
    job = uuid.uuid4().hex[:8]
    token = _secrets.token_urlsafe(24)
    token_sha = hashlib.sha256(token.encode()).hexdigest()
    with _jobs_lock:
        if sum(1 for j in _jobs.values() if j.get("state") == "running") >= MAX_RUNNING:
            raise HTTPException(429, f"{MAX_RUNNING} runs are in progress; try again in a few seconds")
        _jobs[job] = {"state": "running", "scenario": "alert", "started_at": time.time(), "tenant": t,
                      "token_sha": token_sha}
    threading.Thread(target=_alert_job, args=(job, t, known, token_sha), daemon=True).start()
    for _ in range(100):
        if _jobs[job].get("incident") or _jobs[job]["state"] != "running":
            break
        time.sleep(0.05)
    if _jobs[job].get("error") and not _jobs[job].get("incident"):
        raise HTTPException(503 if _jobs[job].get("unavailable") else 500, _jobs[job]["error"])
    out = _job_view(job, _jobs[job])
    out.update(run_token=token, alerts=len(known), ignored=[a["target"] for a in alerts if a not in known], graph=graph)
    return out


def _alert_job(job: str, t: str, alerts: list[dict], token_sha: str) -> None:
    from .actions import oncall
    from .agent.intake import intake_round
    from .agent.loop import BaselineInvestigator, run_incident
    from .agent.weights import weights

    inv = BaselineInvestigator()
    try:
        graph = oncall.home_graph(t)
        g = gclient.engine().select_graph(graph)
        now = oncall.now_ms()
        for a in alerts:
            aid = "al-" + _sha256_hex(f"{job}|{a['target']}|{a['metric']}")[:12]
            writes.raise_alert(g, id=aid, target=a["target"], metric=a["metric"], at=int(a["at"] or now),
                               severity=a["severity"])
        w = weights()["intake"]
        first = min(int(a["at"] or now) for a in alerts)
        ids = [(f"inc-alert-{job}-{k}", f"run-alert-{job}-{k}") for k in range(1, 21)]
        rnd = intake_round(tenant=t, graph=graph, since=first - int(w["alert_lead_min"]) * 60_000,
                           until=max(now, first) + int(w["alert_lag_min"]) * 60_000, onset=first, ids=ids,
                           title="; ".join(sorted({a["summary"] or f"{a['metric']} on {a['target']}" for a in alerts}))[:200],
                           report=" / ".join(a["summary"] for a in alerts if a["summary"])[:2000], round_run=f"run-alert-{job}-intake",
                           mode="alert")
        audit = gclient.engine().select_graph(audit_graph(t))
        entries = []
        for grp in rnd.opened:
            writes.index_run(audit, run=grp.run_id, inc=grp.incident_id, graph=graph, scenario="", tenant=t,
                             investigator=inv.name)
            writes.set_run_token(g, run=grp.run_id, token_sha=token_sha)
            entries.append({"incident": grp.incident_id, "run": grp.run_id, "symptoms": list(grp.symptoms),
                            "outcome": "RUNNING"})
        _jobs[job]["incidents"] = entries
        if not rnd.opened:
            _jobs[job].update(state="done", outcome="ATTACHED", attached=rnd.attached)
            return
        _jobs[job].update(incident=rnd.opened[0].incident_id, run=rnd.opened[0].run_id, graph=graph)
        for grp, e in zip(rnd.opened, entries):
            res = anyio.run(lambda grp=grp: run_incident(tenant=t, incident_id=grp.incident_id,
                                                         onset_ms=grp.onset_ms or first, symptoms=grp.symptoms,
                                                         investigator=inv, graph=graph, run_id=grp.run_id,
                                                         oncall_home=oncall.home_graph(t), oncall_external=True,
                                                         share_notes=True))
            writes.index_run(audit, run=grp.run_id, inc=grp.incident_id, graph=graph, scenario="", tenant=t,
                             investigator=inv.name, outcome=res.outcome, cause=res.cause_id)
            e.update(outcome=res.outcome, cause=res.cause_id, error=res.error)
            _after_run(t, {"graph": graph, "run": grp.run_id, "scenario": None}, grp.incident_id, res)
        _jobs[job].update(state="done", outcome=entries[0]["outcome"])
    except Exception as e:  # noqa: BLE001 - surfaced on the job (client-safe text), never swallowed
        _jobs[job].update(state="failed", error=_client_error_text(e),
                          unavailable=isinstance(e, (GraphUnavailable, GraphNotReady)))


# ------------------------------------------------------------------ the escalation tick (background)
_tick_stop = threading.Event()
_tick_state: dict[str, threading.Thread | None] = {"thread": None}


def _tick_loop(stop: threading.Event) -> None:
    from .actions import oncall
    from .agent.weights import weights

    every = float(weights()["oncall"]["tick_every_s"])
    tlog = logging.getLogger("faultline.oncall")
    while not stop.wait(every):
        try:
            tenants = _configured_tenants()
        except GraphError as e:
            tlog.warning("escalation tick skipped: %s", e)
            continue
        for t in tenants:
            try:
                for e in oncall.tick(t):
                    tlog.warning("escalated %s/%s → %s", e["graph"], e["incident"], e.get("to") or "nobody (exhausted)")
            except Exception as e:  # noqa: BLE001 - logged loudly; the next tick retries
                tlog.error("escalation tick for %s failed: %s", t, e)
            try:  # the morning digest on Telegram (TELEGRAM_DIGEST_HOUR; once a day, claimed in the graph) + TTL prune
                from .actions import telegram_bot

                telegram_bot.maybe_digest(t)
                telegram_bot.prune(t)
            except Exception as e:  # noqa: BLE001
                tlog.warning("telegram digest / prune for %s failed: %s", t, type(e).__name__)


@app.on_event("startup")
def _startup_tick() -> None:
    """Start the escalation tick (once per process)."""
    th = _tick_state["thread"]
    if th is not None and th.is_alive():
        return
    _tick_stop.clear()
    th = threading.Thread(target=_tick_loop, args=(_tick_stop,), name="faultline-oncall-tick", daemon=True)
    _tick_state["thread"] = th
    th.start()


@app.on_event("shutdown")
def _shutdown_tick() -> None:
    _tick_stop.set()
