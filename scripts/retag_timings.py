"""After `make eval`: update the claim tags that are timings or repository counts to evals/results/latest.json, and
refuse (exit 1, listing them) when any OTHER tagged claim drifted. A drifted verdict, count or rate is a finding to
read and re-word by hand, never something to retag mechanically. Run as `make retag` (it also regenerates the query
catalogue, whose PROFILE timings are tagged)."""

from __future__ import annotations

import glob
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMING = re.compile(r"(_ms|ms_|_p50|_p95|\.p50|\.p95|seconds|_s$|run_s)")
COUNTS = {"repo.templates", "repo.mcp_tools", "repo.mcp_tools_hosted", "repo.algorithms", "mutation.killed",
          "mutation.mutants"}
DRIFT = re.compile(r"^\s*(\S+?):(\d+) claim (\S+) = '([^']*)' but latest.json says (.*)$", re.M)


def main() -> int:
    latest = json.loads((ROOT / "evals" / "results" / "latest.json").read_text())
    files = ["README.md", *sorted(glob.glob("docs/*.md"))]
    out = subprocess.run([sys.executable, "scripts/check_claims.py", *files], cwd=ROOT, capture_output=True, text=True).stdout
    drift = DRIFT.findall(out)
    mech = [d for d in drift if TIMING.search(d[2]) or d[2] in COUNTS]
    other = [d for d in drift if d not in mech]
    for f in sorted({d[0] for d in mech}):
        p = ROOT / f
        t = p.read_text()
        for _, _, k, _, _ in [d for d in mech if d[0] == f]:
            t = re.sub(rf"(<!-- claim:{re.escape(k)} -->)[^<]*(<!-- /claim -->)",
                       lambda m, k=k: f"{m.group(1)}{latest[k]}{m.group(2)}", t)
        p.write_text(t)
    print(f"retagged {len(mech)} timing/count claims in {len({d[0] for d in mech})} files")
    if other:
        print("NOT retagged (a result moved: read it and re-word by hand):", file=sys.stderr)
        for f, line, k, old, new in other:
            print(f"  {f}:{line} {k}: {old} -> {new}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
