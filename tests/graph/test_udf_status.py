"""GRAPH.UDF LIST parsing: a pinned library is "loaded" only when the engine holds it at the pinned sha256."""

import hashlib

import pytest

from faultline.graph import udf


class _R:
    def __init__(self, libs):
        self.libs, self.loaded = libs, []

    def execute_command(self, *args):
        if args[:2] == ("GRAPH.UDF", "LIST"):
            return [[b"library_name", n.encode(), b"functions", [], b"library_code", c] for n, c in self.libs.items()]
        self.loaded.append(args)
        return b"OK"


def test_missing_mismatch_and_loaded():
    pinned = (udf.ROOT / udf.UDF_LIBS["flex"][0]).read_bytes()
    assert udf.udf_status(_R({}))["flex"]["state"] == "missing"
    assert udf.udf_status(_R({"flex": b"falkor.register('x', () => 1);"}))["flex"]["state"] == "mismatch"
    ok = udf.udf_status(_R({"flex": pinned}))["flex"]
    assert ok["state"] == "loaded" and ok["loaded_sha"] == hashlib.sha256(pinned).hexdigest()[:12]


def test_load_refuses_a_changed_file(tmp_path):
    bad = tmp_path / "flex.js"
    bad.write_text("falkor.register('text.levenshtein', (a, b) => 0);")
    r = _R({})
    with pytest.raises(udf.UdfMismatch, match="sha256"):
        udf.load_udfs(r, {"flex": (str(bad), udf.UDF_LIBS["flex"][1])})
    assert r.loaded == []
    assert udf.load_udfs(r) == {lib: sha[:12] for lib, (_p, sha) in udf.UDF_LIBS.items()}
    assert [c[:4] for c in r.loaded] == [("GRAPH.UDF", "LOAD", "REPLACE", lib) for lib in udf.UDF_LIBS]


def test_faultline_library_is_pure_arithmetic():
    """Our own library is reviewed like a vendored one: pure functions, nothing that reaches outside the engine."""
    src = (udf.ROOT / udf.UDF_LIBS["faultline"][0]).read_text()
    for banned in ("require", "eval(", "Function(", "fetch", "import ", "graph.", "getNeighbors"):
        assert banned not in src.split("*/", 1)[1], banned
    assert hashlib.sha256(src.encode()).hexdigest() == udf.UDF_LIBS["faultline"][1]
