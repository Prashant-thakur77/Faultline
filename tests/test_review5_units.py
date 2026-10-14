"""Review round 5, unit level (no FalkorDB): the warehouse gate (fairness, file lock, re-entrant exclusive, builder
handoff, lease release on a failed start), the transform SQL validator and build sandbox (M4), pristine transforms,
per-patch backups and atomic writes (M3), scrubbed pipeline subprocesses, the client-visible error policy (minor 7),
simulated-world bookkeeping (minor 8), the gate bench's opaque ids (minor 9), the results label (minor 9) and the
CLI collector's in-flight exclusions (minor 5)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from faultline import repair, scenario, warehouse
from faultline.config import settings

ROOT = Path(__file__).resolve().parents[1]
STG = "pipeline/transforms/stg_orders.sql"
_CENTS_FIX = (ROOT / STG).read_text().replace(
    "    CAST(amount AS DOUBLE) AS amount,",
    "    CASE WHEN payment_processor = 'cloudpay_v2' AND CAST(order_ts AS TIMESTAMP) >= TIMESTAMP '2026-08-07 00:00:00'\n"
    "         THEN CAST(amount AS DOUBLE) / 100.0 ELSE CAST(amount AS DOUBLE) END AS amount,")


# ------------------------------------------------------------------ minor 4: the warehouse gate
def _gate(log: list, build_s: float = 0.05, lock_path: Path | None = None) -> scenario.ModeGate:
    def build(mode: str) -> None:
        log.append(("build", mode))
        time.sleep(build_s)
    return scenario.ModeGate(build, lock_path=lock_path)


def test_a_waiting_other_mode_blocks_later_joiners_of_the_current_mode():
    """FIFO: with an 'incident' run reading and a 'healthy' run waiting, a NEW 'incident' run queues behind the
    healthy one instead of joining (which could starve the healthy run forever)."""
    gate = _gate([])
    first = gate.reserve("incident")
    first.ready()
    order: list[str] = []

    def run(mode: str, tag: str) -> None:
        lease = gate.reserve(mode)
        order.append(tag)
        lease.ready()
        time.sleep(0.05)
        lease.release()

    t_h = threading.Thread(target=run, args=("healthy", "healthy"))
    t_h.start()
    time.sleep(0.1)
    t_i = threading.Thread(target=run, args=("incident", "late-incident"))
    t_i.start()
    time.sleep(0.1)
    assert order == []  # both wait: the late incident run does not jump the queue
    first.release()
    t_h.join(5)
    t_i.join(5)
    assert order == ["healthy", "late-incident"]


def test_a_waiting_repair_blocks_later_joiners():
    gate = _gate([])
    reader = gate.reserve("incident")
    reader.ready()
    got: list[str] = []

    def repair_job() -> None:
        with gate.exclusive(timeout=5):
            got.append("repair")

    t = threading.Thread(target=repair_job)
    t.start()
    time.sleep(0.1)
    with pytest.raises(scenario.WarehouseBusy):
        gate.reserve("incident", wait=False)  # same mode, but a repair waits first
    reader.release()
    t.join(5)
    assert got == ["repair"]
    gate.reserve("incident", wait=False).release()


def test_exclusive_is_reentrant_for_its_holder_and_beats_while_waiting(monkeypatch):
    gate = _gate([])
    reader = gate.reserve("incident")
    beats: list[int] = []
    done = threading.Event()
    real = time.monotonic
    t0 = real()
    # 30 s pass while the repair waits (the clock jumps after 0.1 s), so its lease heartbeat must run
    monkeypatch.setattr(scenario.time, "monotonic", lambda: real() + (31.0 if real() - t0 > 0.1 else 0.0))

    def repair_job() -> None:
        with gate.exclusive(timeout=60, heartbeat=lambda: beats.append(1)):
            with gate.exclusive(timeout=0):  # nested: no deadlock, no wait
                assert gate.held_alone_by_me()
            assert gate.held_alone_by_me()
        done.set()

    t = threading.Thread(target=repair_job)
    t.start()
    time.sleep(0.6)
    reader.release()
    t.join(5)
    assert done.is_set() and beats, "the waiting repair renewed its lease"
    assert not gate.held_alone_by_me()


def test_the_file_lock_keeps_another_process_out(tmp_path):
    lock = tmp_path / "faultline.duckdb.lock"
    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, os, time\n"
        f"fd = os.open({str(lock)!r}, os.O_RDWR | os.O_CREAT)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\nprint('held', flush=True)\ntime.sleep(30)\n")],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        gate = _gate([], lock_path=lock)
        with pytest.raises(scenario.WarehouseBusy, match="another process"):
            gate.reserve("incident", wait=False)
        with pytest.raises(scenario.WarehouseBusy, match="another process"):
            gate.reserve("incident", timeout=0.5)
    finally:
        holder.kill()
        holder.wait()
    gate = _gate([], lock_path=lock)
    lease = gate.reserve("incident", wait=False)  # free now
    probe_args = [sys.executable, "-c", (
        "import fcntl, os\n"
        f"fd = os.open({str(lock)!r}, os.O_RDWR)\n"
        "try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')\nexcept OSError:\n    print('busy')\n")]
    assert subprocess.run(probe_args, capture_output=True, text=True).stdout.strip() == "busy"  # held while leased
    lease.release()
    assert subprocess.run(probe_args, capture_output=True, text=True).stdout.strip() == "free"  # dropped when idle


def test_a_failed_job_start_releases_the_reserved_lease(monkeypatch):
    from fastapi.testclient import TestClient

    from faultline import api

    held = []

    class _Gate:
        def reserve(self, mode, wait=True, timeout=900.0):
            lease = type("L", (), {"released": False, "mode": mode})()
            lease.release = lambda: setattr(lease, "released", True)
            held.append(lease)
            return lease

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(settings, "faultline_public", True)
    monkeypatch.setattr(scenario, "WAREHOUSE", _Gate())
    monkeypatch.setattr(api, "_shed_load", lambda: None)
    monkeypatch.setattr(api.threading, "Thread", _Boom)
    api._rate.clear()
    before = dict(api._jobs)
    with pytest.raises(RuntimeError, match="new thread"):
        TestClient(api.app, raise_server_exceptions=True).post("/api/scenarios/S2/run", json={"llm": "baseline"})
    assert held and held[0].released
    assert api._jobs == before  # no stranded "running" handle either


# ------------------------------------------------------------------ M4: SQL validation and the build sandbox
@pytest.mark.parametrize("sql,why", [
    ("COPY (SELECT * FROM raw.raw_orders) TO '/tmp/x.csv'", "COPY"),
    ("CREATE OR REPLACE TABLE staging.stg_orders AS SELECT * FROM read_text('/etc/passwd')", "read_text"),
    ("CREATE OR REPLACE TABLE staging.stg_orders AS SELECT 1 AS a; SELECT 2", "exactly one statement"),
    ("CREATE OR REPLACE TABLE staging.stg_orders AS SELECT getenv('HOME') AS k", "getenv"),
    ("CREATE OR REPLACE TABLE staging.stg_orders AS SELECT * FROM '/etc/passwd'", "file name"),
    ("ATTACH '/tmp/other.db'", "ATTACH"),
    ("INSTALL httpfs", "LOAD|INSTALL"),
    ("CREATE OR REPLACE TABLE marts.fct_revenue AS SELECT 1 AS x", "builds staging.stg_orders"),
    ("CREATE OR REPLACE TABLE staging.stg_orders AS SELECT * FROM glob('/*')", "glob"),
    ("CREATE MACRO m(a) AS a", "only CREATE"),
    ("PRAGMA version", "only CREATE|PRAGMA"),
    ("SET enable_external_access = true", "SET"),
], ids=["copy-to", "read_text", "two-statements", "getenv", "from-file", "attach", "install", "other-target", "glob",
        "macro", "pragma", "set"])
def test_the_validator_refuses_anything_but_one_plain_ctas(sql, why):
    with pytest.raises(repair.SqlRejected, match=why):
        repair.validate_transform_sql(STG, sql)
    with pytest.raises(ValueError):  # and propose_patch (the only way a patch is made) refuses it too
        repair.propose_patch(STG, sql, "hostile")


def test_a_legitimate_ctas_fix_is_accepted():
    repair.validate_transform_sql(STG, _CENTS_FIX)
    p = repair.propose_patch(STG, _CENTS_FIX, "normalise cents")
    assert p.diff.startswith(f"--- a/{STG}")
    for f in sorted((ROOT / "pipeline" / "transforms").glob("*.sql")):  # every shipped transform passes
        repair.validate_transform_sql(f"pipeline/transforms/{f.name}", f.read_text())


def _pipeline_run():
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import run as pipeline_run
    finally:
        sys.path.pop(0)
    return pipeline_run


def test_the_build_cannot_reach_files_and_a_failed_build_keeps_the_last_good_warehouse(tmp_path):
    import duckdb

    run = _pipeline_run()
    tdir, wdir = tmp_path / "t", tmp_path / "w"
    tdir.mkdir()
    for f in (ROOT / "pipeline" / "transforms").glob("*.sql"):
        (tdir / f.name).write_text(f.read_text())
    run.build(ROOT / "data" / "sources", wdir, tdir)  # a good build first
    good = (wdir / "faultline.duckdb").read_bytes()
    snap = (wdir / "metric_snapshot.json").read_text()
    (tdir / "stg_orders.sql").write_text(
        "CREATE OR REPLACE TABLE staging.stg_orders AS SELECT * FROM read_text('/etc/passwd');\n")
    with pytest.raises(duckdb.Error, match="disabled by configuration"):
        run.build(ROOT / "data" / "sources", wdir, tdir)
    assert (wdir / "faultline.duckdb").read_bytes() == good  # the last good warehouse is still there, untouched
    assert (wdir / "metric_snapshot.json").read_text() == snap
    assert sorted(p.name for p in wdir.iterdir()) == ["faultline.duckdb", "metric_snapshot.json"]  # no temp left
    (tdir / "stg_orders.sql").write_text(
        "SET enable_external_access = true;\nCREATE OR REPLACE TABLE staging.stg_orders AS SELECT 1 AS x;\n")
    with pytest.raises(duckdb.Error):  # the configuration is locked: a transform cannot switch access back on
        run.build(ROOT / "data" / "sources", wdir, tdir)


def test_pipeline_steps_run_with_this_interpreter_and_a_scrubbed_environment(monkeypatch):
    names = ("ANTHROPIC_API_" + "KEY", "FALKORDB_" + "PASSWORD")
    for n in names:
        monkeypatch.setenv(n, "not-a-real-value-0000")
    env = warehouse.scrubbed_env()
    assert not set(names) & set(env) and set(env) <= {"PATH", "HOME", "LANG", "PYTHONDONTWRITEBYTECODE", "TMPDIR"}
    out = warehouse.run_step([sys.executable, "-c", "import os, sys; print(sorted(os.environ)); print(sys.executable)"],
                             what="probe")
    assert not any(n in out.stdout for n in names) and sys.executable in out.stdout
    with pytest.raises(RuntimeError) as e:  # stderr (paths, SQL) is logged, never in the message
        warehouse.run_step([sys.executable, "-c", "import sys; sys.stderr.write('/secret/path boom'); sys.exit(3)"],
                           what="probe")
    assert "exit 3" in str(e.value) and "request id" in str(e.value) and "/secret/path" not in str(e.value)


def test_rebuild_and_invariants_never_call_uv():
    import inspect

    for fn in (warehouse.rebuild_warehouse, warehouse.run_invariants, scenario.set_pipeline_mode):
        src = inspect.getsource(fn)
        assert '"uv"' not in src and "sys.executable" in src


# ------------------------------------------------------------------ M3: pristine transforms, backups, atomic writes
@pytest.fixture
def transforms(tmp_path, monkeypatch):
    """A private copy of the transforms (the repo's own files are never touched by these tests)."""
    t = tmp_path / "transforms"
    t.mkdir()
    for f in (ROOT / "pipeline" / "transforms").glob("*.sql"):
        (t / f.name).write_text(f.read_text())
    monkeypatch.setattr(settings, "transforms_dir", t)
    return t


def test_the_pristine_set_matches_its_pinned_digest():
    sums = (ROOT / "pipeline" / "transforms_pristine" / "SHA256SUMS").read_bytes()
    assert hashlib.sha256(sums).hexdigest() == repair.PRISTINE_DIGEST
    for name, f in repair._pristine_files().items():
        assert (ROOT / "pipeline" / "transforms" / name).read_text() == f.read_text(), \
            f"pipeline/transforms/{name} differs from its pristine copy (a repair left it patched?)"


def test_restore_pristine_undoes_an_applied_repair_and_drops_backups(transforms):
    p = repair.propose_patch(STG, _CENTS_FIX, "fix")
    repair.apply_patch(p, _CENTS_FIX)
    repair.mark_unverified(STG, {"incident": "inc-x"})
    assert (transforms / "stg_orders.sql").read_text() == _CENTS_FIX
    assert repair.restore_pristine() == ["stg_orders.sql"]
    assert (transforms / "stg_orders.sql").read_text() == (ROOT / STG).read_text()
    assert not list(transforms.glob("*.orig")) and not list(transforms.glob("*.unverified.json"))
    assert repair.restore_pristine() == []


def test_a_tampered_pristine_copy_is_refused(tmp_path, monkeypatch, transforms):
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    for f in (ROOT / "pipeline" / "transforms_pristine").iterdir():
        (pristine / f.name).write_bytes(f.read_bytes())
    (pristine / "stg_orders.sql").write_text("CREATE OR REPLACE TABLE staging.stg_orders AS SELECT 1 AS evil;\n")
    monkeypatch.setattr(settings, "transforms_pristine_dir", pristine)
    with pytest.raises(repair.PristineMismatch):
        repair.restore_pristine()


def test_each_patch_has_its_own_backup_so_a_later_revert_never_undoes_an_earlier_fix(transforms):
    first = repair.propose_patch(STG, _CENTS_FIX, "the approved fix")
    repair.apply_patch(first, _CENTS_FIX)
    second_sql = _CENTS_FIX.replace("-- stg_orders: cleaned order stream.", "-- stg_orders: cleaned order stream (v2).")
    second = repair.propose_patch(STG, second_sql, "a later, wrong patch")
    repair.apply_patch(second, second_sql)
    repair.revert_patch(second, rebuild=False)
    assert (transforms / "stg_orders.sql").read_text() == _CENTS_FIX  # the earlier approved fix survives
    with pytest.raises(FileNotFoundError):  # a patch with no backup of its own is never guessed back
        repair.revert_patch(repair.ProposedPatch(file=STG, diff="unrelated", reasoning="", status="applied"), rebuild=False)


def test_revert_to_restores_before_only_from_after_and_never_overwrites_a_foreign_change(transforms):
    before = (transforms / "stg_orders.sql").read_text()
    (transforms / "stg_orders.sql").write_text(_CENTS_FIX)
    assert repair.revert_to(STG, before=before, after=_CENTS_FIX, rebuild=False)["state"] == "reverted"
    assert (transforms / "stg_orders.sql").read_text() == before
    (transforms / "stg_orders.sql").write_text("-- someone else's edit\n" + before)
    assert repair.revert_to(STG, before=before, after=_CENTS_FIX, rebuild=False)["state"] == "changed-elsewhere"
    assert (transforms / "stg_orders.sql").read_text().startswith("-- someone else's edit")


def test_writes_are_atomic(transforms, monkeypatch):
    target = transforms / "stg_orders.sql"
    old = target.read_text()

    def crash(*a, **k):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError):
        repair._atomic_write(target, "half")
    assert target.read_text() == old and not [p for p in transforms.iterdir() if ".tmp-" in p.name]


def test_only_allowlisted_transforms_resolve():
    for bad in ("backend/faultline/api.py", "pipeline/transforms/../../Makefile", "pipeline/run.py",
                "pipeline/transforms/x/../stg_orders.sql"):
        with pytest.raises((ValueError, FileNotFoundError)):
            repair._resolve_transform(bad)


# ------------------------------------------------------------------ minor 7: client-visible error text
def test_client_text_hides_engine_os_and_subprocess_text():
    from faultline.graph.errors import GraphQueryError, GraphUnavailable
    from faultline.public_errors import client_text

    for e in (OSError("/home/x/.config: permission denied"), GraphQueryError("errMsg: ... at host:6379"),
              subprocess.CalledProcessError(1, ["python", "/srv/pipeline/run.py"], stderr="Traceback /srv"),
              GraphUnavailable("FalkorDB unreachable (ConnectionError: 10.0.0.5:6379)")):
        t = client_text(e)
        assert "request id" in t and "/home" not in t and "6379" not in t and "/srv" not in t, t
    assert client_text(PermissionError("plan hash changed")) == "PermissionError: plan hash changed"
    assert client_text(scenario.WarehouseBusy("in mode 'x'")).endswith("in mode 'x'")
    assert "request id" in client_text(AttributeError("'NoneType' object has no attribute 'x'"))


# ------------------------------------------------------------------ minor 8: simulated worlds
def test_sim_worlds_of_collected_graphs_are_dropped_and_memory_worlds_are_ephemeral(monkeypatch):
    from faultline.actions import github as gh

    monkeypatch.delenv("FAULTLINE_SIM_GITHUB_DIR", raising=False)
    monkeypatch.setenv("FAULTLINE_GITHUB", "sim")
    a, b = gh.client("eval_acme_api_v2_zz_1_aaaa1111"), gh.client("eval_acme_api_v2_zz_2_bbbb2222")
    assert gh.ephemeral(a) and not gh.ephemeral(gh.FileSimGitHub(path="/tmp/x.json"))
    gone = gh.prune_sims({"eval_acme_api_v2_zz_2_bbbb2222"})
    assert "eval_acme_api_v2_zz_1_aaaa1111" in gone and gh.client("eval_acme_api_v2_zz_2_bbbb2222") is b
    gh.reset_sim("eval_acme_api_v2_zz_2_bbbb2222")


# ------------------------------------------------------------------ minor 9: eval honesty
def _evals(name: str):
    sys.path.insert(0, str(ROOT / "evals"))
    try:
        return __import__(name)
    finally:
        sys.path.pop(0)


def test_gate_bench_ids_are_opaque_and_titles_identical_for_causes_and_distractors():
    gate_bench = _evals("gate_bench")
    cases = gate_bench.generate()
    assert {x["title"].split(": ", 1)[1] for c in cases for x in c["spec"]["inject"]} == {"change"}
    assert all("cause" not in x["change"] and "gb" not in x["change"] for c in cases for x in c["spec"]["inject"])
    assert all(not c["spec"]["id"].lower().startswith("gb") for c in cases)
    # the cause is not systematically first in id order (a tie-break by id cannot favour it)
    multi = [c for c in cases if c["expected"]["cause"] and len(c["spec"]["inject"]) > 1]
    first = [min(x["change"] for x in c["spec"]["inject"]) == c["expected"]["cause"] for c in multi]
    assert 0.2 < sum(first) / len(first) < 0.8
    # the cases themselves are the ones the regression tests pin (the case stream is unchanged)
    assert [(c["id"], c["category"]) for c in cases][:3] == [("gb001", "G2"), ("gb002", "G2"), ("gb003", "G2")]
    role = gate_bench.blame_role
    assert role({"cause": None}) is None
    assert role({"cause": "D-a", "expected": {"cause": "D-a"}}) == "cause"
    assert role({"cause": "D-b", "expected": {"cause": "D-a"}}) == "distractor"


def test_results_label_false_blame_as_measured_on_scenarios_with_a_true_cause():
    import inspect

    report = _evals("report")
    assert "false blame (on scenarios with a true cause)" in inspect.getsource(report.markdown)
    assert "False blame (on scenarios with a true cause)" in (ROOT / "README.md").read_text()


# ------------------------------------------------------------------ minor 5: the CLI collector's in-flight exclusions
def test_make_gc_leaves_fresh_brain_copies_and_rearm_temps_alone():
    from faultline.graph import copy as gcopy

    now = 2_000_000_000
    names = [f"scratch_acme_brain_{now - 60:010d}_abcdef", f"scratch_acme_brain_{now - 10 * 3600:010d}_abcdef",
             f"scratch_acme_rearm_{now - 30:010d}_0123abcd", f"scratch_acme_rearm_{now - 3600:010d}_0123abcd",
             "eval_acme_x_1", "scratch_acme_brain_weird", "tenant_acme"]

    class _Db:
        def list_graphs(self):
            return names

    doomed = gcopy.gc_eval_graphs(_Db(), "acme", keep=set(), dry_run=True, now_s=now)
    assert doomed == sorted([names[1], names[3], "eval_acme_x_1"])
