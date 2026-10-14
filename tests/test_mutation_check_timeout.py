"""scripts/mutation_check.py: a pytest run that hits the timeout is an ERROR for that mutant, never an abort of the run."""

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mutation_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("mutation_check_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def test_a_timeout_records_error_and_the_remaining_mutants_still_run(monkeypatch):
    mc = _load()
    calls = []

    def hang(cmd, **kw):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"), output="collected 1 item\n")

    monkeypatch.setattr(mc, "_capped", lambda: [])
    monkeypatch.setattr(mc.subprocess, "run", hang)
    ids = [m.id for m in mc.MUTANTS[:2]]
    out = mc.run(ids)
    assert out["mutants"] == 2 and out["errors"] == 2 and out["killed"] == 0
    assert all(r["status"] == "ERROR" and "timed out" in r["detail"] for r in out["rows"])
    assert len(calls) == 2  # one baseline per mutant: the first timeout did not stop the second mutant


def test_a_mutant_run_that_times_out_is_error_not_killed(monkeypatch):
    mc = _load()
    seq = iter([(0, "1 passed"), (mc.TIMED_OUT, "timed out after 900 s")])
    monkeypatch.setattr(mc, "_pytest", lambda *a, **k: next(seq))
    monkeypatch.setattr(mc, "_copy", lambda m: Path("/nonexistent-mutant-copy"))
    out = mc.run([mc.MUTANTS[0].id])
    assert out["rows"][0]["status"] == "ERROR" and out["killed"] == 0
