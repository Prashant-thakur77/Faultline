"""FalkorDB UDF libraries (GRAPH.UDF): vendored, pinned by sha256 (deploy/udf/README.md).

`load_udfs` is what `make up`, seed and API startup run (REPLACE is idempotent); `udf_status` is what /api/status
and judge-check report. Both are engine-operator commands on the engine connection, never tenant data reads.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
UDF_LIBS = {"flex": ("deploy/udf/flex-1.0.1.js", "e7e833ba87f88c1e31913b58bb9bdeab231714f8af4b43b437d84277ee653ece")}


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


def udf_status(r: Any) -> dict[str, dict[str, Any]]:
    """Per pinned library: "loaded" (present at the pinned sha), "mismatch" (present, different code) or "missing",
    read from GRAPH.UDF LIST WITHCODE."""
    loaded: dict[str, str] = {}
    for entry in r.execute_command("GRAPH.UDF", "LIST", "WITHCODE") or []:
        d = {_s(entry[i]): entry[i + 1] for i in range(0, len(entry) - 1, 2)}
        code = d.get("library_code")
        loaded[_s(d.get("library_name"))] = hashlib.sha256(code if isinstance(code, bytes) else _s(code).encode()).hexdigest()
    out = {}
    for lib, (_rel, sha) in UDF_LIBS.items():
        got = loaded.get(lib)
        out[lib] = {"state": "missing" if got is None else ("loaded" if got == sha else "mismatch"),
                    "pinned_sha": sha[:12], "loaded_sha": got[:12] if got else None}
    return out


__all__ = ["UDF_LIBS", "UdfMismatch", "load_udfs", "udf_status"]
