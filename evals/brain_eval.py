"""Company-brain eval (T3): questions with expected citations (grader-only truth in data/brain/questions.truth.json).

Scores, per question: intent routed correctly; every expected id cited (and the citation guard passed); for
questions the graph cannot answer: NO citations and an honest phrase. Also latency, and that answering never
changes the tenant's knowledge (Service/Decision/Runbook/Person/Doc counts identical before and after; each
question's own Run/ToolCall records are its evidence, by design).

The questions are asked in a fresh clean room (a GRAPH.COPY of golden_<t>, deleted afterwards), never in the live
tenant graph (review round 5, minor 5): the eval leaves no Run, tool call or turn behind in tenant_<t>, and its
answers do not depend on what earlier questions or visitors recorded there.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.brain.ask import ask  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.tenant import golden_graph  # noqa: E402

KNOWLEDGE = ("Service", "Decision", "Runbook", "Person", "Doc", "Team", "Incident")


def _knowledge(tenant: str, graph: str) -> dict:
    return {r["label"]: r["n"] for r in RO(tenant, graph).run("Q-COUNT-2", {}).rows if r["label"] in KNOWLEDGE}


def run() -> dict:
    import uuid

    truth = json.loads((ROOT / "data" / "brain" / "questions.truth.json").read_text())
    tenant = truth["tenant"]
    db = gclient.engine()
    room = f"eval_{tenant}_braineval_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, golden_graph(tenant), room)
    try:
        before = _knowledge(tenant, room)
        rows, ms = [], []
        for item in truth["questions"]:
            t0 = time.perf_counter()
            a = ask(item["q"], tenant, graph=room)
            ms.append((time.perf_counter() - t0) * 1000)
            cited = set(a.citations)
            if item["must_cite"]:
                ok = set(item["must_cite"]) <= cited and a.guard["ok"] and a.intent == item["intent"]
                ok = ok and (item.get("must_say", "").lower() in a.answer.lower())
            else:
                ok = not cited and item["must_say"].lower() in a.answer.lower()
            rows.append({"q": item["q"], "intent": a.intent, "expected_intent": item["intent"], "ok": ok,
                         "missing": sorted(set(item["must_cite"]) - cited), "guard_ok": a.guard["ok"], "tier": a.tier})
        after = _knowledge(tenant, room)
    finally:
        gcopy.delete_if_exists(db, room)
    return {"questions": len(rows), "correct": sum(r["ok"] for r in rows), "graph": "clean room (copy of golden)",
            "answerable": sum(1 for i in truth["questions"] if i["must_cite"]),
            "unanswerable_honest": sum(1 for r, i in zip(rows, truth["questions"]) if not i["must_cite"] and r["ok"]),
            "unanswerable": sum(1 for i in truth["questions"] if not i["must_cite"]),
            "intent_correct": sum(r["intent"] == r["expected_intent"] for r in rows),
            "guard_ok": sum(r["guard_ok"] for r in rows),
            "ms_p50": round(statistics.median(ms), 1), "ms_max": round(max(ms), 1),
            "knowledge_unchanged": before == after, "failures": [r for r in rows if not r["ok"]]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
