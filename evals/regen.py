"""Regenerate evals/RESULTS.md, evals/results/latest.json and docs/NAIVE_VS_FAULTLINE.md from the newest
evals/results/run_*.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import report  # noqa: E402


def main() -> int:
    runs = sorted((ROOT / "evals" / "results").glob("run_*.json"))
    if not runs:
        print("no runs yet: make eval")
        return 1
    out = json.loads(runs[-1].read_text())
    s = report.summarize(out)
    (ROOT / "evals" / "results" / "latest.json").write_text(json.dumps({"run": runs[-1].name, **s}, indent=2) + "\n")
    (ROOT / "evals" / "RESULTS.md").write_text(report.markdown(out, s, runs[-1].name))
    (ROOT / "docs" / "NAIVE_VS_FAULTLINE.md").write_text(report.naive_vs_markdown(out, runs[-1].name, s))
    print(f"regenerated from {runs[-1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
