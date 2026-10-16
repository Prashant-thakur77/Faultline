"""No answer leakage: the product package must not know any scenario's answer.

Fails if any text file under backend/faultline/ (Python, Cypher templates, YAML, JSON, …; M18 audit: it used to
scan only *.py)
* reads a ground-truth file (`*.truth.json`, `["truth"]`, `.get("truth")`, the brain question truth), or
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


TRUTH_READ = re.compile(r"truth\.json|\[\s*['\"]truth['\"]\s*\]|\.get\(\s*['\"]truth['\"]|questions\.truth|paraphrases\.truth")


def text_files() -> list[Path]:
    out = []
    for p in sorted(PKG.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix in (".pyc", ".so", ".bin", ".onnx", ".npy"):
            continue
        try:
            p.read_text()
        except UnicodeDecodeError:
            continue
        out.append(p)
    return out


def main() -> int:
    lits = literals()
    rx = re.compile("|".join(re.escape(x) for x in sorted(lits, key=len, reverse=True)))
    bad: list[str] = []
    files = text_files()
    for p in files:
        rel = p.relative_to(ROOT)
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if TRUTH_READ.search(line):
                bad.append(f"{rel}:{n} reads ground truth")
            m = rx.search(line)
            if m:
                bad.append(f"{rel}:{n} scenario literal {m.group(0)!r}")
    if bad:
        print("no-leaks lint FAILED:\n  " + "\n  ".join(bad))
        return 1
    print(f"no-leaks lint PASS ({len(lits)} scenario literals checked across {len(files)} text files of every type)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
