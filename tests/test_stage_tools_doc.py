"""docs/STAGE_TOOLS.md is generated from agent/phases.py and must match it (regenerate with scripts/gen_stage_tools.py)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stage_tools_doc_is_current():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "gen_stage_tools.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (ROOT / "docs" / "STAGE_TOOLS.md").read_text() == gen.render(), "run scripts/gen_stage_tools.py"
