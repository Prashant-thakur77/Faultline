"""Company rules as data (M20 #6): change-freeze policies from data/gen/policies/<tenant>.yaml.

Each policy becomes (:Policy {id, kind, status, title, why, effect, from_day, from_hour, to_day, to_hour, utc_offset_min,
decided_at, url}) -[:FREEZES]-> each frozen component, and (:Person) -[:DECIDED]-> (:Policy) when the decider exists.
The preflight gate reads them with Q-PRE-FREEZE: FalkorDB turns the evaluation instant into the policy's local wall
clock (`localdatetime('1970-01-01T00:00:00') + duration({seconds: …})`; never `{epochMillis}` or `{milliseconds}`,
which 6.0.2 silently gets wrong) and checks `.dayOfWeek` / `.hour` / `.minute` against the weekly window.

Applied by scripts/seed.py AFTER the bundle and the derived runbooks (writes.upsert_nodes / upsert_edges, idempotent
MERGE), so existing node and edge ids, which some algorithms break ties by, never move.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
POLICY_DIR = ROOT / "data" / "gen" / "policies"
KINDS = ("change_freeze",)
EFFECTS = ("block", "require_review")


class PolicyError(ValueError):
    pass


def _ms(day: str) -> int:
    return int(dt.datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp() * 1000)


def load(tenant: str) -> list[dict[str, Any]]:
    """The validated policies of a tenant ([] when it has no policy file)."""
    p = POLICY_DIR / f"{tenant}.yaml"
    if not p.exists():
        return []
    out = []
    for x in (yaml.safe_load(p.read_text()) or {}).get("policies") or []:
        if x.get("kind") not in KINDS or x.get("effect") not in EFFECTS or x.get("status") not in ("active", "retired"):
            raise PolicyError(f"{x.get('id')}: bad kind, effect or status")
        for k, lo, hi in (("from_day", 1, 7), ("to_day", 1, 7), ("from_hour", 0, 23), ("to_hour", 0, 24)):
            if not isinstance(x.get(k), int) or not lo <= x[k] <= hi:
                raise PolicyError(f"{x.get('id')}: {k} must be an integer in {lo}..{hi}")
        if not isinstance(x.get("utc_offset_min"), int) or not -840 <= x["utc_offset_min"] <= 840:
            raise PolicyError(f"{x.get('id')}: utc_offset_min must be an integer in -840..840")
        if not x.get("freezes"):
            raise PolicyError(f"{x.get('id')}: freezes nothing")
        out.append(x)
    return out


def rows(tenant: str) -> dict[str, Any]:
    """{nodes: [...], freezes: {label: [{src, dst}]}, decided: [{src, dst}]} for the writers."""
    nodes, freezes, decided = [], {}, []
    for x in load(tenant):
        nodes.append({"id": x["id"], "kind": x["kind"], "status": x["status"], "title": x["title"], "why": x.get("why", ""),
                      "effect": x["effect"], "from_day": x["from_day"], "from_hour": x["from_hour"], "to_day": x["to_day"],
                      "to_hour": x["to_hour"], "utc_offset_min": x["utc_offset_min"],
                      "decided_at": _ms(str(x["decided_at"])), "decided_by": x.get("decided_by", ""), "url": x["url"],
                      "tenant": tenant})
        for c in x["freezes"]:
            freezes.setdefault(c["label"], []).append({"src": x["id"], "dst": c["id"]})
        if x.get("decided_by"):
            decided.append({"src": x["decided_by"], "dst": x["id"]})
    return {"nodes": nodes, "freezes": freezes, "decided": decided}


def apply(g, tenant: str) -> dict[str, int]:
    """Write the tenant's policies into graph `g` through graph/writes (idempotent)."""
    from ..graph import writes

    r = rows(tenant)
    if not r["nodes"]:
        return {"policies": 0, "freezes": 0}
    writes.upsert_nodes(g, "Policy", r["nodes"])
    n = sum(writes.upsert_edges(g, "FREEZES", "Policy", label, pairs) for label, pairs in sorted(r["freezes"].items()))
    if r["decided"]:
        writes.upsert_edges(g, "DECIDED", "Person", "Policy", r["decided"])
    return {"policies": len(r["nodes"]), "freezes": n}
