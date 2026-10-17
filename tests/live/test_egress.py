"""Live (M20 #9): in the prod topology (FalkorDB alone on an internal Docker network) the engine cannot fetch from the
internet: `LOAD CSV FROM 'https://…'` under GRAPH.RO_QUERY fails, by host name and by IP literal. Runs
scripts/egress_check.py --docker (a throwaway container of the pinned digest, 384 MB, removed afterwards)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


def test_load_csv_https_fails_on_the_internal_network():
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker not available")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "egress_check.py"), "--docker", "--json"],
                       capture_output=True, text=True, timeout=300, cwd=ROOT)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["pass"] and out["internal"]["refused"], out
    assert out["query_mem_capacity_load_time"] and int(out["query_mem_capacity_load_time"][0]) > 0
    left = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    assert out["network"] not in left                                   # cleaned up
