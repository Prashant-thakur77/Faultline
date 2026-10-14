"""Exercise the real ACL path in judge-check: create the shipped ro_<tenant> users for one run, run the isolation suite
(S7) through them, delete them.

The users get exactly the rules in deploy/users.acl.template (the `user ro_*` lines), with a random password made
here, held in memory, handed to the test process through its environment and never printed or written to disk. The
default user is left as it is (a dev engine), so this proves the ro_<tenant> rules, not a hardened deployment
(deploy/LIVE.md does that). The users are deleted in a `finally`, also when the tests fail.

    PYTHONPATH=backend uv run python scripts/acl_ephemeral.py [pytest args…]   (default: tests/isolation)
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.graph import client  # noqa: E402


def ro_rules(password: str) -> dict[str, list[str]]:
    """{user: [rule tokens]} for every `user ro_*` line of the template, the password substituted."""
    out = {}
    for line in (ROOT / "deploy/users.acl.template").read_text().splitlines():
        m = re.match(r"user\s+(ro_\w+)\s+(.*)$", line.strip())
        if m:
            out[m.group(1)] = [">" + password if t == ">${FALKORDB_RO_PASSWORD}" else t for t in m.group(2).split()]
    if not out:
        raise SystemExit("acl_ephemeral: no `user ro_*` line in deploy/users.acl.template")
    if any("${" in t for rules in out.values() for t in rules):
        raise SystemExit("acl_ephemeral: an unexpected template variable is left in a ro_* rule")
    return out


def main(argv: list[str]) -> int:
    password = secrets.token_urlsafe(32)
    rules = ro_rules(password)
    conn = client.engine().connection
    existing = set(conn.execute_command("ACL", "USERS"))
    if existing & set(rules):  # never overwrite users someone configured (a real ACL deploy)
        print(f"acl_ephemeral: {', '.join(sorted(existing & set(rules)))} already exist here; not touching them",
              file=sys.stderr)
        return 2
    try:
        for user, toks in rules.items():
            conn.execute_command("ACL", "SETUSER", user, "reset", *toks)
        env = dict(os.environ, FALKORDB_RO_PASSWORD=password, PYTHONPATH=str(ROOT / "backend"))
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", *(argv or ["tests/isolation"])]
        return subprocess.call(cmd, cwd=ROOT, env=env)
    finally:
        for user in rules:
            conn.execute_command("ACL", "DELUSER", user)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
