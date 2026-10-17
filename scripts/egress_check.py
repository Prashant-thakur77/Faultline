"""The engine has no internet egress in the prod topology (M20 #9; SECURITY.md).

Defence in depth: prod puts FalkorDB on an `internal: true` Docker network (deploy/docker-compose.prod.yml), so no query
can fetch from the internet or send data out. This script checks that with a remote `LOAD CSV`.

    uv run python scripts/egress_check.py --docker     # throwaway same-digest container on an internal network
    docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml exec falkordb \\
        redis-cli GRAPH.QUERY egress_probe "LOAD CSV FROM 'https://example.com/' AS r RETURN count(r)"   # after a deploy

`--docker` starts the pinned image (the digest in deploy/docker-compose.yml) on a fresh `docker network create --internal`
network with a 384 MB cap, asserts that the LOAD CSV fails (PASS = it fails; the text is not asserted), then connects the
same container to the default bridge as a control (fetched = the host has internet and egress was the only thing
stopping it; anything else is reported as an inconclusive control). It also checks that QUERY_MEM_CAPACITY works as a
load-time FALKORDB_ARGS value (the compose files pass it there). Container and network are always removed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = {"name": "LOAD CSV FROM 'https://example.com/' AS r RETURN count(r)",
          # an IP literal: no DNS involved, so a refusal means there is no route out, not only no resolver
          "ip": "LOAD CSV FROM 'https://1.1.1.1/' AS r RETURN count(r)"}


def pinned_image() -> str:
    m = re.search(r"FALKORDB_IMAGE:-([^}]+)\}", (ROOT / "deploy" / "docker-compose.yml").read_text())
    if not m or "@sha256:" not in m.group(1):
        raise SystemExit("no digest-pinned FalkorDB image in deploy/docker-compose.yml")
    return m.group(1)


def sh(*args: str, check: bool = True, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, check=check, timeout=timeout)


def cli(container: str, *args: str, timeout: float = 30) -> str:
    """redis-cli inside the container; its output (redis-cli prints a server error as plain text and exits 0)."""
    r = sh("docker", "exec", container, "redis-cli", *args, check=False, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def fetched(reply: str) -> bool:
    """The probe returned its result row (header `count(r)`, then a count): the engine fetched the URL."""
    lines = reply.splitlines()
    return len(lines) >= 2 and lines[0].strip() == "count(r)" and lines[1].strip().isdigit()


def docker_check(mem_cap: int) -> dict:
    tag = uuid.uuid4().hex[:8]
    net, name = f"faultline-egress-{tag}", f"faultline-egress-{tag}"
    out: dict = {"image": pinned_image(), "network": net}
    try:
        sh("docker", "network", "create", "--internal", net)
        sh("docker", "run", "-d", "--name", name, "--network", net, "--memory", "384m", "--memory-swap", "384m",
           "-e", f"FALKORDB_ARGS=QUERY_MEM_CAPACITY {mem_cap}", out["image"])
        for _ in range(60):
            if cli(name, "PING") == "PONG":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("the throwaway engine did not answer PING")
        out["query_mem_capacity_load_time"] = cli(name, "GRAPH.CONFIG", "GET", "QUERY_MEM_CAPACITY").split()[-1:]
        cli(name, "GRAPH.QUERY", "egress_probe", "CREATE (:X)")
        replies = {k: cli(name, "GRAPH.QUERY", "egress_probe", q, timeout=60) for k, q in PROBES.items()}
        out["internal"] = {"refused": not any(fetched(t) for t in replies.values()),
                           "reply": "; ".join(f"{k}: {t[:90]}" for k, t in replies.items())}
        sh("docker", "network", "connect", "bridge", name)                    # control: the same engine WITH egress
        ctl = {k: cli(name, "GRAPH.QUERY", "egress_probe", q, timeout=60) for k, q in PROBES.items()}
        out["control"] = {"fetched": any(fetched(t) for t in ctl.values()),
                          "by_probe": {k: fetched(t) for k, t in ctl.items()}}
    finally:
        sh("docker", "rm", "-f", name, check=False)
        sh("docker", "network", "rm", net, check=False)
    out["pass"] = bool(out.get("internal", {}).get("refused"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docker", action="store_true", help="throwaway same-digest container on an internal network")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.docker:
        ap.error("use --docker (or the docker compose exec line in the docstring for a deployed stack)")
    sys.path.insert(0, str(ROOT / "backend"))
    from faultline.agent.weights import weights

    res = docker_check(int(weights()["engine"]["query_mem_capacity_mb"]) * 1024 * 1024)
    if a.json:
        print(json.dumps(res))
    else:
        ctl = res.get("control", {})
        print(f"egress check {'PASS' if res['pass'] else 'FAIL'}: LOAD CSV https on an internal network "
              f"{'refused' if res['pass'] else 'FETCHED'} ({res.get('internal', {}).get('reply', '')[:160]}); control with "
              f"egress: {'fetched' if ctl.get('fetched') else 'not fetched (inconclusive control)'}; QUERY_MEM_CAPACITY "
              f"at load time: {res.get('query_mem_capacity_load_time')}")
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
