"""FalkorDB UDF libraries (GRAPH.UDF): FLEX, vendored, and our own `faultline`, both pinned by sha256.

See deploy/udf/README.md. `load_udfs` is what `make up`, seed and API startup run (REPLACE is idempotent);
`udf_status` is what /api/status and judge-check report. Both are engine-operator commands on the engine
connection, never tenant data reads.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
# flex: FalkorDB's FLEX, vendored unmodified. faultline: ours, the in-engine scoring (tierWeight, impact, capImpact,
# noteScore, round4).
UDF_LIBS = {
    "flex": ("deploy/udf/flex-1.0.1.js", "e7e833ba87f88c1e31913b58bb9bdeab231714f8af4b43b437d84277ee653ece"),
    "faultline": ("deploy/udf/faultline-1.0.0.js",
                  "55cd126a097dbea6e402b297c3ace79f827cb68a9455784c5bdbf09a0354ee7f"),
}


class UdfMismatch(RuntimeError):
    """A vendored library does not match its pinned sha256: refuse to load it (fail loudly)."""


def load_udfs(r: Any, libs: dict[str, tuple[str, str]] | None = None) -> dict[str, str]:
    """Load each pinned UDF library (REPLACE is idempotent); a changed file fails loudly instead of loading.
    `r` is a redis client on the engine connection (FalkorDB().connection)."""
    out = {}
    for lib, (rel, sha) in (libs or UDF_LIBS).items():
        path = Path(rel) if Path(rel).is_absolute() else ROOT / rel
        src = path.read_bytes()
        if hashlib.sha256(src).hexdigest() != sha:
            raise UdfMismatch(f"UDF library {rel} does not match its pinned sha256; refusing to load it")
        r.execute_command("GRAPH.UDF", "LOAD", "REPLACE", lib, src.decode())
        out[lib] = sha[:12]
    return out


def _s(x: Any) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _templates_using(lib: str) -> tuple[list[str], list[str]]:
    """(template ids whose Cypher calls `<lib>.` functions, the functions they call), read from the catalogue."""
    import re

    from .templates import catalogue

    ids, used = [], set()
    for t in catalogue().values():
        calls = re.findall(rf"\b{re.escape(lib)}\.([A-Za-z_][\w.]*)\s*\(", t.text)
        if calls:
            ids.append(t.id)
            used.update(calls)
    return sorted(ids), sorted(used)


def udf_status(r: Any) -> dict[str, dict[str, Any]]:
    """Per pinned library: "loaded" (present at the pinned sha), "mismatch" (present, different code) or "missing",
    read from GRAPH.UDF LIST WITHCODE, with the functions the engine registered for it and the templates that call
    them."""
    loaded: dict[str, str] = {}
    funcs: dict[str, list[str]] = {}
    for entry in r.execute_command("GRAPH.UDF", "LIST", "WITHCODE") or []:
        d = {_s(entry[i]): entry[i + 1] for i in range(0, len(entry) - 1, 2)}
        code = d.get("library_code")
        name = _s(d.get("library_name"))
        loaded[name] = hashlib.sha256(code if isinstance(code, bytes) else _s(code).encode()).hexdigest()
        funcs[name] = sorted(_s(f) for f in (d.get("functions") or []))
    out = {}
    for lib, (_rel, sha) in UDF_LIBS.items():
        got = loaded.get(lib)
        ids, used = _templates_using(lib)
        out[lib] = {"state": "missing" if got is None else ("loaded" if got == sha else "mismatch"),
                    "pinned_sha": sha[:12], "loaded_sha": got[:12] if got else None,
                    "functions": funcs.get(lib, []), "used": used, "templates": ids}
    return out


__all__ = ["UDF_LIBS", "UdfMismatch", "load_udfs", "udf_status"]
