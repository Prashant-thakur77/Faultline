"""check_claims fails measured-looking numbers that carry no claim tag (unless the line says why with noclaim)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_claims", ROOT / "scripts" / "check_claims.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def _doc(tmp_path, text):
    d = ROOT / "tmp" / "claims_test"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "probe.md"
    f.write_text(text)
    return f


def test_untagged_decimal_ratio_and_percent_are_flagged(tmp_path):
    f = _doc(tmp_path, "top-1 was 0.8 and write-back 7/7, recall 95%.\n")
    assert len(cc.untagged([f])) == 3


def test_tagged_code_noclaim_and_versions_pass(tmp_path):
    f = _doc(tmp_path, "top-1 <!-- claim:arm.A3.top1 -->1.0<!-- /claim -->; `cap = 0.02` in code; FalkorDB 6.0.2 pinned;\n"
                       "caps 1.0 and 0.02 <!-- noclaim: configured -->\n[link](https://x.y/1.5)\n")
    assert cc.untagged([f]) == []
