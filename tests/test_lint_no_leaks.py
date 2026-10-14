"""Unit: the product package contains no scenario answers."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _lint():
    spec = importlib.util.spec_from_file_location("lint_no_leaks", ROOT / "scripts" / "lint_no_leaks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repo_has_no_leaks():
    assert _lint().main() == 0


def test_lint_catches_a_literal(tmp_path, monkeypatch):
    lint = _lint()
    pkg = tmp_path / "backend" / "faultline"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text("CAUSE = 'D-pay-417'\n")
    (tmp_path / "data" / "scenarios").mkdir(parents=True)
    (tmp_path / "data" / "scenarios" / "scenarios.yaml").write_text((ROOT / "data" / "scenarios" / "scenarios.yaml").read_text())
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "PKG", pkg)
    assert lint.main() == 1
