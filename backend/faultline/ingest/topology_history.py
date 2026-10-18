"""Synthetic topology history (M14 #7): some service calls did not always exist; a historical PR introduced them.

Deterministic per tenant (seeded stream "topohist:<tenant>"). For a quarter of the service-domain failure edges
(server → client, PROPAGATES_TO and its DEPENDS_ON twin), pick a merged PR that touched the CLIENT's files (the
caller adds the call) from the middle third of that client's PR history, and stamp:
  * the edge pair: `valid_from` = that PR's `merged_at`, `introduced_by` = its id;
  * the PR: `introduces_calls` += "<client> → <server>".
Consistent with the incident history: a call that a past incident propagated over (both its
ends were AFFECTED by that incident) existed before that incident, so it is only ever dated to a PR merged before the
earliest such incident, and left undated (always there) when the caller has no such PR. Edges without `valid_from`
existed throughout. Every scenario incident is later than the whole history, so reads "now" are unchanged; only as-of
reads (the preflight backtest, Q-PRE-1-ASOF) see a smaller past topology.
This is generated data, labelled as such (README "What's real vs synthetic", docs/HONEST_LIMITS.md); it closes the
backtest's "topology read as it is now" gap only for this synthetic history.
"""

from __future__ import annotations

import random

from .bundle import Bundle

SHARE = 0.25
SOURCES = ("Service", "Datastore", "ExternalDependency")


def annotate(b: Bundle, tenant: str) -> dict:
    rnd = random.Random(f"topohist:{tenant}")
    prs = {r["id"]: r for r in b.nodes.get("PR", []) if r.get("merged_at") is not None}
    file_comp = {e["src"]: e["dst"] for k, es in b.edges.items() if k[0] == "PART_OF" and k[1] == "File" for e in es}
    by_client: dict[str, list[dict]] = {}
    for k, es in b.edges.items():
        if k[0] == "TOUCHES" and k[1] == "PR":
            for e in es:
                comp = file_comp.get(e["dst"])
                if comp and e["src"] in prs:
                    by_client.setdefault(comp, []).append(prs[e["src"]])
    onset = {r["id"]: r.get("onset_at") or r.get("opened_at") for r in b.nodes.get("Incident", [])}
    touched: dict[str, set[str]] = {}
    for k, es in b.edges.items():
        if k[0] == "AFFECTED" and k[1] == "Incident":
            for e in es:
                touched.setdefault(e["src"], set()).add(e["dst"])
    # the earliest incident that involved both ends of a call: the call existed before it
    must_exist_by: dict[tuple[str, str], int] = {}
    for inc, comps in touched.items():
        if onset.get(inc) is None:
            continue
        for u in comps:
            for v in comps:
                if u != v:
                    key = (u, v)
                    must_exist_by[key] = min(must_exist_by.get(key, onset[inc]), int(onset[inc]))
    stamped = 0
    for key in sorted(k for k in b.edges if k[0] == "PROPAGATES_TO" and k[1] in SOURCES and k[2] == "Service"):
        twin = ("DEPENDS_ON", key[2], key[1])
        twins = {(e["src"], e["dst"]): e for e in b.edges.get(twin, [])}
        for e in sorted(b.edges[key], key=lambda x: (x["src"], x["dst"])):
            if rnd.random() >= SHARE:
                continue
            limit = must_exist_by.get((e["src"], e["dst"]))
            hist = sorted((p for p in {p["id"]: p for p in by_client.get(e["dst"], [])}.values()
                           if limit is None or p["merged_at"] < limit), key=lambda p: (p["merged_at"], p["id"]))
            if len(hist) < 3:
                continue
            third = len(hist) // 3
            pr = hist[third + rnd.randrange(max(1, third))]
            stamp = {"valid_from": int(pr["merged_at"]), "introduced_by": pr["id"]}
            e["props"] = {**e.get("props", {}), **stamp}
            t = twins.get((e["dst"], e["src"]))
            if t is not None:
                t["props"] = {**t.get("props", {}), **stamp}
            pr["introduces_calls"] = sorted(set(pr.get("introduces_calls") or []) | {f"{e['dst']} → {e['src']}"})
            stamped += 1
    return {"edges_dated": stamped}
