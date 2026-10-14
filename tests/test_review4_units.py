"""Review round 4, unit level (no FalkorDB): the warehouse mode gate (M4), SSE slots under a burst (M7), job handles
(m9 + the UI's GET /api/jobs/{job}), generic errors (m12), brain sessions and tool-argument errors (M1, m10), the hosted
MCP rate limit (m5) and session scoping (M2), and the secret-scan patterns (m11)."""

from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultline import api, scenario
from faultline.brain import ask as brain_ask
from faultline.graph.errors import GraphError

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ M4: one warehouse, one mode at a time
def _gate(log: list, build_s: float = 0.15) -> scenario.ModeGate:
    def build(mode: str) -> None:
        log.append(("build-start", mode))
        time.sleep(build_s)
        log.append(("build-end", mode))
    return scenario.ModeGate(build)


def _run(gate: scenario.ModeGate, mode: str, log: list, hold_s: float = 0.3) -> None:
    lease = gate.reserve(mode)
    try:
        lease.ready()
        log.append(("read-start", mode))
        time.sleep(hold_s)  # the run's investigation reads the warehouse
        log.append(("read-end", mode))
    finally:
        lease.release()


def test_concurrent_runs_needing_different_modes_never_interleave():
    """S2 (mode incident) and S4D (mode healthy) started together: the second build starts only after the first run
    stopped reading; nothing is read while another mode is being built."""
    log: list = []
    gate = _gate(log)
    ts = [threading.Thread(target=_run, args=(gate, m, log)) for m in ("incident", "healthy")]
    for t in ts:
        t.start()
        time.sleep(0.02)
    for t in ts:
        t.join(10)
    first, second = log[0][1], [m for _, m in log if m != log[0][1]][0]
    kinds = [(k, m) for k, m in log]
    assert kinds == [("build-start", first), ("build-end", first), ("read-start", first), ("read-end", first),
                     ("build-start", second), ("build-end", second), ("read-start", second), ("read-end", second)]
    assert first != second


def test_same_mode_runs_share_one_build_and_read_together():
    log: list = []
    gate = _gate(log)
    ts = [threading.Thread(target=_run, args=(gate, "incident", log)) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert [k for k, _ in log].count("build-start") == 1
    starts = [i for i, (k, _) in enumerate(log) if k == "read-start"]
    ends = [i for i, (k, _) in enumerate(log) if k == "read-end"]
    assert max(starts) < min(ends)  # all three read at once


def test_no_wait_reservation_of_another_mode_is_refused_with_a_clear_message():
    gate = _gate([])
    held = gate.reserve("incident")
    try:
        with pytest.raises(scenario.WarehouseBusy, match="mode 'incident'.*needs mode 'healthy'"):
            gate.reserve("healthy", wait=False)
        gate.reserve("incident", wait=False).release()  # the same mode is shared
    finally:
        held.release()
    gate.reserve("healthy", wait=False).release()


def test_a_data_repair_waits_for_runs_and_runs_wait_for_it():
    log: list = []
    gate = _gate(log, build_s=0.0)
    lease = gate.reserve("incident")
    lease.ready()
    done = threading.Event()

    def repair():
        with gate.exclusive(timeout=5):
            log.append(("repair", None))
        done.set()

    t = threading.Thread(target=repair)
    t.start()
    time.sleep(0.1)
    assert not done.is_set()  # the run still reads
    lease.release()
    t.join(5)
    assert done.is_set() and log[-1] == ("repair", None)


def test_a_reserved_but_never_built_lease_does_not_strand_joiners():
    """Round 5 (minor 4): the build passes to a remaining holder instead of leaving it an error."""
    log: list = []
    gate = _gate(log, build_s=0.0)
    a = gate.reserve("incident")
    b = gate.reserve("incident")
    a.release()  # the builder stopped before building
    b.ready(timeout=1)  # b builds instead of failing
    assert [k for k, _ in log] == ["build-start", "build-end"]
    b.release()


# ------------------------------------------------------------------ M7: SSE slots under a burst
def test_sse_slots_are_taken_at_check_time_under_a_burst():
    api._streams.clear()
    ok, refused = [], []
    barrier = threading.Barrier(12)

    def go():
        barrier.wait()
        try:
            ok.append(api._stream_slot("10.0.0.9"))
        except Exception as e:  # noqa: BLE001
            refused.append(e)

    ts = [threading.Thread(target=go) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert len(ok) == api.MAX_STREAMS_PER_CLIENT and len(refused) == 12 - api.MAX_STREAMS_PER_CLIENT
    assert all(getattr(e, "status_code", None) == 429 for e in refused)
    for rel in ok:
        rel()
        rel()  # idempotent: a second release (generator finally + background task) never double-counts
    assert api._streams.get("10.0.0.9", 0) == 0 and api._streams["*"] == 0
    api._stream_slot("10.0.0.9")()  # free again


# ------------------------------------------------------------------ m9 + UI token: job handles
@pytest.fixture
def client(monkeypatch):
    api._rate.clear()
    saved = dict(api._jobs)
    api._jobs.clear()
    monkeypatch.setattr(api, "_shed_load", lambda: None)
    monkeypatch.setattr(api, "_run_job", lambda *a, **k: None)  # the job thread does nothing: state stays "running"
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    yield TestClient(api.app)  # no lifespan: startup hooks (FalkorDB) do not run
    api._jobs.clear()
    api._jobs.update(saved)


def test_eviction_never_drops_a_running_job_and_max_running_is_enforced(client):
    for i in range(3):
        api._jobs[f"run{i:05d}"] = {"state": "running", "scenario": "S1", "tenant": "acme"}
    for i in range(197):
        api._jobs[f"done{i:04d}"] = {"state": "done", "scenario": "S1", "tenant": "acme"}
    r = client.post("/api/scenarios/S1/run", json={"llm": "baseline"})
    assert r.status_code == 200, r.text
    assert len(api._jobs) <= 200 and all(f"run{i:05d}" in api._jobs for i in range(3))
    assert "token_sha" not in r.json() and r.json()["run_token"]
    r2 = client.post("/api/scenarios/S1/run", json={"llm": "baseline"})  # 4 running now → refused
    assert r2.status_code == 429


def test_max_running_holds_under_a_burst(client):
    codes: list[int] = []
    barrier = threading.Barrier(10)

    def go():
        barrier.wait()
        codes.append(client.post("/api/scenarios/S1/run", json={"llm": "baseline"}).status_code)

    ts = [threading.Thread(target=go) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert codes.count(200) == api.MAX_RUNNING and codes.count(429) == 10 - api.MAX_RUNNING


def test_job_status_is_tenant_bound_and_echoes_the_token_only_to_its_holder(client):
    token = "tok-" + "x" * 20
    api._jobs["0badc0de"] = {"state": "done", "scenario": "S14", "tenant": "acme", "incident": "inc-a",
                             "token_sha": hashlib.sha256(token.encode()).hexdigest(),
                             "incidents": [{"incident": "inc-a"}, {"incident": "inc-a-r2-1"}]}
    assert client.get("/api/jobs/0badc0de?tenant=globex").status_code == 404
    assert client.get("/api/jobs/not-a-job?tenant=acme").status_code == 422
    anon = client.get("/api/jobs/0badc0de?tenant=acme").json()
    assert anon["token_valid"] is False and "run_token" not in anon and "token_sha" not in anon
    assert [x["incident"] for x in anon["incidents"]] == ["inc-a", "inc-a-r2-1"]
    wrong = client.get("/api/jobs/0badc0de?tenant=acme", headers={"X-Faultline-Run-Token": "nope"}).json()
    assert wrong["token_valid"] is False and "run_token" not in wrong
    mine = client.get("/api/jobs/0badc0de?tenant=acme", headers={"X-Faultline-Run-Token": token}).json()
    assert mine["token_valid"] is True and mine["run_token"] == token


# ------------------------------------------------------------------ m12: no raw engine errors to clients
def test_engine_errors_reach_clients_as_a_generic_message_with_a_request_id(monkeypatch, caplog):
    def boom(self, tid, params):
        raise GraphError("ResponseError: errMsg: Invalid input at falkordb-internal:6379 secret-graph")

    monkeypatch.setattr(api.RO, "run", boom)
    with caplog.at_level("ERROR", logger="faultline.api"):
        r = TestClient(api.app).get("/api/incidents?tenant=acme")
    assert r.status_code == 500
    assert "request id" in r.json()["detail"] and "6379" not in r.json()["detail"] and "secret" not in r.json()["detail"]
    rid = r.json()["detail"].split("request id ")[1].rstrip(")")
    assert any(rid in rec.getMessage() and "6379" in rec.getMessage() for rec in caplog.records)  # detail in the log


# ------------------------------------------------------------------ M1 / m10: brain sessions and tool arguments
def test_session_ids_are_server_issued():
    assert brain_ask.session_id("checkout", "u1", "brain-abc123") == "sess-checkout"
    assert brain_ask.session_id("sess-u1-s1", "u1", "brain-abc123") == "sess-u1-s1"
    assert brain_ask.session_id(None, "u1", "brain-0123456789") == "sess-u1-456789"
    assert brain_ask.session_id(None, None, "brain-abc123") is None
    with pytest.raises(ValueError):
        brain_ask.session_id("bad id with spaces", "u1", "brain-abc123")


def test_a_tool_call_with_a_bad_argument_name_is_a_clean_tool_error():
    s = brain_ask._Session("acme", "brain-test", graph="tenant_acme")
    out = s.call("blast_radius", ident="checkout")  # no such argument
    assert out["error"].startswith("invalid arguments for blast_radius") and s.steps[-1]["error"] == out["error"]


# ------------------------------------------------------------------ m5: hosted MCP rate limit
def test_mcp_rate_limit_keys_unauthenticated_requests_per_ip_and_stays_bounded():
    from faultline.mcp_server.http import RateLimit

    rl = RateLimit(app=None, per_min=3)
    scope = lambda ip, auth=None: {"type": "http", "client": (ip, 1),  # noqa: E731
                                   "headers": [(b"authorization", auth.encode())] if auth else []}
    now = 1000.0
    assert [rl.allow(rl._key(scope("1.1.1.1")), now) for _ in range(4)] == [True, True, True, False]
    assert rl.allow(rl._key(scope("2.2.2.2")), now)  # another IP has its own bucket
    assert rl._key(scope("1.1.1.1", "Bearer " + "k" * 30)).startswith("key-")  # a bearer key is keyed by key
    rl.MAX_KEYS = 50
    for i in range(500):
        rl.allow(f"ip:10.0.{i // 250}.{i % 250}", now + 61 + i)
    assert len(rl.hits) <= 50


# ------------------------------------------------------------------ M2: hosted session_history is the caller's own
def test_hosted_session_history_returns_only_the_callers_own_sessions(monkeypatch):
    from faultline.mcp_server import context
    from faultline.mcp_server import tools as T

    token = context._binding.set(context.Binding("acme", record=False, caller="key-abc12345"))
    try:
        out = T.session_history(user="visitor-123")
    finally:
        context._binding.reset(token)
    assert "only the caller's own" in out["error"]


# ------------------------------------------------------------------ m11: secret scan generic patterns
def test_secret_scan_catches_generic_passwords_and_faultline_keys(tmp_path):
    sample = tmp_path / "sample.txt"
    fake = "Zq3x9Lr2" + "Kp0vB7mN4sT8"  # built at run time: this source file must not itself look like a secret
    sample.write_text("\n".join([
        "FAULTLINE_ADMIN_KEY=" + fake,                      # 1 hit
        "FALKORDB_RO_" + "PASSWORD=" + fake,                # 2 hit
        "db_pass" + 'word = "' + fake + '"',                # 3 hit
        "FAULTLINE_ADMIN_KEY=<random>",                     # placeholder
        "password=settings.falkordb_engine_password or None",
        "FALKORDB_RO_PASSWORD=",
        "export GITHUB_TOKEN=$(gh auth token)",
    ]) + "\n")
    script = ('eval "$(sed -n "/^V=/p;/^GENERIC=/p;/^ENVSTYLE=/p" scripts/secret_scan.sh)"; '
              '{ grep -nEi -- "$GENERIC" "$1"; grep -nE -- "$ENVSTYLE" "$1"; } | cut -d: -f1 | sort -n | uniq')
    out = subprocess.run(["bash", "-c", script, "_", str(sample)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert out.stdout.split() == ["1", "2", "3"], out.stderr
