"""CLI: preflight a PR described as JSON (the GitHub Action builds it from the PR's changed files).

    PYTHONPATH=backend python -m faultline.preflight pr.json [--tenant acme] [--comment out.md]
Exit status 1 = block (fails the status check).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comment import exit_code, render
from .engine import PreflightIn, run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pr_json")
    ap.add_argument("--tenant", default="acme")
    ap.add_argument("--comment", default="")
    ap.add_argument("--ui-base", default="")
    a = ap.parse_args()
    pr = PreflightIn.model_validate_json(Path(a.pr_json).read_text())
    res = run(a.tenant, pr)
    md = render(res, a.ui_base)
    if a.comment:
        Path(a.comment).write_text(md or "")
    print(json.dumps({k: res[k] for k in ("pr", "verdict", "risk", "reviewers", "decision_links")}, indent=2))
    return exit_code(res)


if __name__ == "__main__":
    sys.exit(main())
