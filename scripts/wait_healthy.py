"""Wait until FalkorDB answers PING and has the graph module loaded (fail loudly on timeout)."""

from __future__ import annotations

import argparse
import sys
import time

import redis

from faultline.config import settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args()
    deadline = time.time() + a.timeout
    last = ""
    while time.time() < deadline:
        try:
            r = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port,
                            username=settings.falkordb_engine_user or None,
                            password=settings.falkordb_engine_password or None, socket_timeout=2)
            r.ping()
            r.execute_command("GRAPH.LIST")
            print(f"FalkorDB healthy at {settings.falkordb_host}:{settings.falkordb_port}")
            return 0
        except Exception as e:  # keep polling until the deadline
            last = f"{type(e).__name__}: {e}"
            time.sleep(1)
    print(f"FalkorDB not healthy after {a.timeout:.0f}s: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
