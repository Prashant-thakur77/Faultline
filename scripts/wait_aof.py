"""Wait until FalkorDB's AOF rewrite (BGREWRITEAOF) has finished, so `make compact` never restarts mid-rewrite."""

from __future__ import annotations

import sys
import time

from faultline.graph import client


def main(timeout_s: float = 300.0) -> int:
    c = client.engine().connection
    t0 = time.time()
    while True:
        p = c.info("persistence")
        if not int(p.get("aof_rewrite_in_progress", 0)) and not int(p.get("aof_rewrite_scheduled", 0)):
            print(f"AOF rewrite done ({time.time() - t0:.1f} s)")
            return 0
        if time.time() - t0 > timeout_s:
            print(f"AOF rewrite still running after {timeout_s:.0f} s", file=sys.stderr)
            return 1
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
