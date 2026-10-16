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


def _bad_pkg(tmp_path, monkeypatch, name: str, text: str):
    lint = _lint()
    pkg = tmp_path / "backend" / "faultline"
    pkg.mkdir(parents=True)
    (pkg / name).write_text(text)
    (tmp_path / "data" / "scenarios").mkdir(parents=True)
    (tmp_path / "data" / "scenarios" / "scenarios.yaml").write_text((ROOT / "data" / "scenarios" / "scenarios.yaml").read_text())
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    monkeypatch.setattr(lint, "PKG", pkg)
    return lint


def test_lint_scans_templates_not_only_python(tmp_path, monkeypatch):   # M18 audit: it used to scan *.py only
    assert _bad_pkg(tmp_path, monkeypatch, "q.cypher", "MATCH (d:Deploy {id:'D-pay-417'}) RETURN d LIMIT 1\n").main() == 1


def test_lint_catches_get_truth(tmp_path, monkeypatch):
    assert _bad_pkg(tmp_path, monkeypatch, "bad.py", "answer = spec.get('truth')\n").main() == 1
