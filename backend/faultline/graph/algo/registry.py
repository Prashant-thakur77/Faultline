"""The only place `algo.*` procedure names and call forms live.

`CANDIDATES` lists the names tried by the smoke suite; `resolved.json` (written by
`scripts/render_compat.py` from the pinned engine's smoke run) records what actually works.
Templates refer to procedures as `{algo:<key>}` and the template loader fills in the resolved name.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RESOLVED_PATH = Path(__file__).with_name("resolved.json")

CANDIDATES: dict[str, list[str]] = {
    "bfs": ["algo.BFS", "algo.bfs"],
    "sppaths": ["algo.SPpaths"],
    "sspaths": ["algo.SSpaths"],
    "pagerank": ["algo.pageRank", "algo.PageRank"],
    "betweenness": ["algo.betweenness"],
    "harmonic": ["algo.HarmonicCentrality", "algo.harmonicCentrality"],
    "wcc": ["algo.WCC", "algo.wcc"],
    "cdlp": ["algo.labelPropagation", "algo.CDLP"],
    "maxflow": ["algo.maxFlow"],
    "msf": ["algo.MSF"],
}


class UnresolvedAlgorithm(LookupError):
    """A template asked for an algorithm the pinned engine does not provide."""


@lru_cache(maxsize=1)
def resolved() -> dict[str, dict]:
    if not RESOLVED_PATH.exists():
        raise UnresolvedAlgorithm(f"{RESOLVED_PATH} missing; run `make smoke` on the pinned engine")
    return json.loads(RESOLVED_PATH.read_text())["procedures"]


def name(key: str) -> str:
    try:
        return resolved()[key]["name"]
    except KeyError as e:
        raise UnresolvedAlgorithm(f"algorithm {key!r} not resolved on the pinned engine") from e


def allowed_procedures() -> set[str]:
    """Lower-cased procedure names the text2cypher guard may let through (read-only algorithms
    plus the index query procedures)."""
    return {v["name"].lower() for v in resolved().values()} | {
        "db.idx.fulltext.querynodes",
        "db.idx.vector.querynodes",
    }


def resolved_meta() -> dict:
    """Engine tag and digest recorded with the resolved names."""
    data = json.loads(RESOLVED_PATH.read_text())
    return {"engine": data.get("engine"), "digest": data.get("digest")}
