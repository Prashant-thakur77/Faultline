"""`make doctor`: environment check before demos/evals (ports, tools, FalkorDB, seeded graphs).
Never prints secret values; reports only whether they are set."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys

from faultline.config import settings


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'ok' if ok else '!!'}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    good = True
    print("Faultline doctor")
    for tool in ("docker", "uv", "node", "npm", "gh"):
        good &= check(f"{tool} on PATH", shutil.which(tool) is not None)
    try:
        socket.create_connection((settings.falkordb_host, settings.falkordb_port), timeout=2).close()
        good &= check("FalkorDB port reachable", True, f"{settings.falkordb_host}:{settings.falkordb_port}")
    except OSError as e:
        good &= check("FalkorDB port reachable", False, f"{e} — run `make up`")
    try:
        import redis

        r = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port,
                        username=settings.falkordb_engine_user or None, password=settings.falkordb_engine_password or None)
        graphs = sorted(g.decode() if isinstance(g, bytes) else g for g in r.execute_command("GRAPH.LIST"))
        check("graphs present", True, ", ".join(graphs) or "none yet — run `make seed`")
    except Exception as e:  # report, never hide
        good &= check("GRAPH.LIST", False, str(e)[:120])
    check("ANTHROPIC_API_KEY set", bool(settings.anthropic_api_key), "needed only for live agent runs")
    check("RO ACL password set", bool(settings.falkordb_ro_password), "unset = RO via default user (dev)")
    check("FAULTLINE_DISABLE_GRAPH", True, str(settings.faultline_disable_graph))
    try:
        out = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=10)
        check("gh authenticated", out.returncode == 0)
    except Exception:
        check("gh authenticated", False)
    print("doctor:", "OK" if good else "PROBLEMS FOUND")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
