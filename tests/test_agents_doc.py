"""docs/AGENTS.md is generated from agent/crew.py and agent/phases.py and must match them (regenerate with
scripts/gen_agents_doc.py)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agents_doc_matches_the_code():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "gen_agents_doc.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (ROOT / "docs" / "AGENTS.md").read_text() == gen.render(), "run scripts/gen_agents_doc.py"
