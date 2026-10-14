"""M14 #7: synthetic topology history. A dated call edge carries the merge time of a PR that touched the CALLER's
files, its DEPENDS_ON twin carries the same time, and the whole thing is deterministic."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
seed = importlib.import_module("seed")


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_dated_calls_come_from_a_pr_on_the_caller_and_are_deterministic(tenant):
    b = seed.build_bundle(tenant)
    assert seed.data_hash(b) == seed.data_hash(seed.build_bundle(tenant))
    prs = {p["id"]: p for p in b.nodes["PR"]}
    file_comp = {e["src"]: e["dst"] for k, es in b.edges.items() if k[0] == "PART_OF" and k[1] == "File" for e in es}
    touched = {}
    for k, es in b.edges.items():
        if k[0] == "TOUCHES" and k[1] == "PR":
            for e in es:
                touched.setdefault(e["src"], set()).add(file_comp.get(e["dst"]))
    intro = {c: p for p in prs.values() for c in p.get("introduces_calls") or []}
    dated = [(k, e) for k, es in b.edges.items() if k[0] == "PROPAGATES_TO" for e in es if "valid_from" in e["props"]]
    assert dated and len(dated) == len(intro)
    twins = {(k[1], k[2], e["src"], e["dst"]): e for k, es in b.edges.items() if k[0] == "DEPENDS_ON" for e in es}
    for k, e in dated:
        pr = intro[f"{e['dst']} → {e['src']}"]
        assert e["props"]["valid_from"] == pr["merged_at"] and e["dst"] in touched[pr["id"]]
        assert twins[(k[2], k[1], e["dst"], e["src"])]["props"]["valid_from"] == pr["merged_at"]
    history = sorted(p["merged_at"] for p in prs.values() if p.get("merged_at"))
    assert all(history[0] < e["props"]["valid_from"] for _, e in dated)   # never the oldest PR: earlier PRs miss it


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_no_call_is_dated_after_an_incident_that_used_it(tenant):
    """Prejudge 2026-10-13: a call both of whose ends a past incident affected existed before that incident."""
    b = seed.build_bundle(tenant)
    onset = {r["id"]: r.get("onset_at") for r in b.nodes["Incident"]}
    touched: dict = {}
    for k, es in b.edges.items():
        if k[0] == "AFFECTED" and k[1] == "Incident":
            for e in es:
                touched.setdefault(e["src"], set()).add(e["dst"])
    for k, es in b.edges.items():
        if k[0] != "PROPAGATES_TO":
            continue
        for e in es:
            vf = e["props"].get("valid_from")
            if vf is None:
                continue
            for inc, comps in touched.items():
                if {e["src"], e["dst"]} <= comps and onset[inc] is not None:
                    assert vf < onset[inc], (e, inc)
