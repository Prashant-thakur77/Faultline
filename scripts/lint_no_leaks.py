"""No answer leakage: the product package must not know any scenario's answer.

Fails if backend/faultline/**/*.py
* reads a ground-truth file (`*.truth.json`, `truth:` keys), or
* contains a scenario literal: an injected change id, alert id or fact key from data/scenarios/scenarios.yaml.
Scenario *config* is read at runtime by scenario.py (that is how the simulated world is set up), which is allowed;
hard-coding its answers is not.

    uv run python scripts/lint_no_leaks.py
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "backend" / "faultline"


def literals() -> set[str]:
    out: set[str] = set()
    for s in yaml.safe_load((ROOT / "data" / "scenarios" / "scenarios.yaml").read_text()):
        for c in s.get("inject", []):
            out.add(c["change"])
        for a in s.get("alerts", []):
            out.add(a["id"])
        for f in s.get("facts", []):
            out.add(f["key"])
    return out


def main() -> int:
    lits = literals()
    rx = re.compile("|".join(re.escape(x) for x in sorted(lits, key=len, reverse=True)))
    bad: list[str] = []
    for p in sorted(PKG.rglob("*.py")):
        rel = p.relative_to(ROOT)
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if "truth.json" in line or re.search(r"\[\s*['\"]truth['\"]\s*\]", line):
                bad.append(f"{rel}:{n} reads ground truth")
            m = rx.search(line)
            if m:
                bad.append(f"{rel}:{n} scenario literal {m.group(0)!r}")
    if bad:
        print("no-leaks lint FAILED:\n  " + "\n  ".join(bad))
        return 1
    print(f"no-leaks lint PASS ({len(lits)} scenario literals checked across {sum(1 for _ in PKG.rglob('*.py'))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
