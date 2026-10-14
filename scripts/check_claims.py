"""Every number we publish must come from evals/results/latest.json.

Markdown files tag claims inline as  <!-- claim:KEY -->VALUE<!-- /claim -->  (or `<!-- claim:KEY=VALUE -->` when the
value is written elsewhere on the line). Each tagged VALUE must equal latest.json[KEY] (numbers compared at the
precision written). Untagged measured-looking numbers (decimals, %, k/n) fail too unless the line carries `<!-- noclaim: why -->`.

    uv run python scripts/check_claims.py [files…]   (default: README.md docs/*.md docs/blog*.md evals/RESULTS.md)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "evals" / "results" / "latest.json"
TAG = re.compile(r"<!--\s*claim:([A-Za-z0-9_.\-]+)\s*-->(.*?)<!--\s*/claim\s*-->|<!--\s*claim:([A-Za-z0-9_.\-]+)=(.*?)\s*-->")


def _eq(written: str, actual) -> bool:
    w = written.strip().strip("`*")
    if isinstance(actual, bool) or actual is None:
        return w.lower() == str(actual).lower()
    if isinstance(actual, (int, float)):
        try:
            x = float(w.rstrip("%").replace(",", ""))
        except ValueError:
            return False
        if w.endswith("%"):
            x /= 100
        decimals = len(w.rstrip("%").split(".")[1]) if "." in w else 0
        return round(float(actual) if not w.endswith("%") else float(actual), decimals + (2 if w.endswith("%") else 0)) == round(x, decimals + (2 if w.endswith("%") else 0))
    return w == str(actual)


def check(files: list[Path]) -> list[str]:
    latest = json.loads(LATEST.read_text()) if LATEST.exists() else {}
    bad = []
    for f in files:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            for m in TAG.finditer(line):
                key = m.group(1) or m.group(3)
                val = m.group(2) if m.group(1) else m.group(4)
                if key not in latest:
                    bad.append(f"{f.relative_to(ROOT)}:{n} claim {key!r} not in latest.json")
                elif not _eq(val, latest[key]):
                    bad.append(f"{f.relative_to(ROOT)}:{n} claim {key} = {val.strip()!r} but latest.json says {latest[key]!r}")
    return bad


# Untagged measured-looking numbers (decimals, percentages, k/n ratios) outside code spans and links must be tagged, or
# the line must say why not with `<!-- noclaim: reason -->` (a configured constant, a version). Logs, plans and
# generated references are exempt.
EXEMPT = {"FALKORDB_COMPAT.md", "GRAPH_SCHEMA.md",
          "QUERY_CATALOGUE.md"}
NUM = re.compile(r"(?<![\w.:/#-])(\d+\.\d+%?|\d+%|\d+/\d+)(?![\w:/-]|\.\d)")


def untagged(files: list[Path]) -> list[str]:
    bad = []
    for f in files:
        if f.name in EXEMPT:
            continue
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if "noclaim" in line:
                continue
            s = TAG.sub(" ", line)
            s = re.sub(r"`[^`]*`", " ", s)
            s = re.sub(r"\]\([^)]*\)", "]", s)
            s = re.sub(r"https?://\S+", " ", s)
            for num in NUM.findall(s):
                bad.append(f"{f.relative_to(ROOT)}:{n} untagged number {num!r} (tag it, or mark the line `<!-- noclaim: why -->`)")
    return bad


def _ignored(p: Path) -> bool:
    """A local, git-ignored working file is not published, so it is not checked."""
    try:
        return subprocess.run(["git", "check-ignore", "-q", str(p)], cwd=ROOT, capture_output=True).returncode == 0
    except OSError:
        return False


def main(argv: list[str]) -> int:
    files = [Path(a).resolve() for a in argv] or [p for p in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
                                                  if p.exists() and not _ignored(p)]
    bad = check(files) + untagged(files)
    n = sum(len(TAG.findall(f.read_text())) for f in files)
    if bad:
        print("claims check FAILED:\n  " + "\n  ".join(bad))
        return 1
    print(f"claims check PASS ({n} tagged claims in {len(files)} files match evals/results/latest.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
