"""Render deploy/users.acl from deploy/users.acl.template using env values (never printed)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    tpl = (ROOT / "deploy/users.acl.template").read_text()
    missing = sorted({m for m in re.findall(r"\$\{(\w+)\}", tpl) if not os.environ.get(m)})
    if missing:
        print(f"render_acl: missing env values: {', '.join(missing)}", file=sys.stderr)
        return 1
    out = re.sub(r"\$\{(\w+)\}", lambda m: os.environ[m.group(1)], tpl)
    path = ROOT / "deploy/users.acl"
    path.write_text(out)
    path.chmod(0o600)
    print(f"wrote {path.relative_to(ROOT)} ({len(out.splitlines())} lines; values not shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
