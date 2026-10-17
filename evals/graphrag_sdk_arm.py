"""Company brain vs FalkorDB's GraphRAG-SDK on the same questions (eval only; PREREGISTRATION addendum 2026-10-17,
"GraphRAG-SDK arm").

Two arms answer the same questions about the acme organisation:
  FL   the shipped company brain (`faultline.brain.ask`, deterministic router, no model), on a fresh GRAPH.COPY of
       golden_acme, deleted afterwards;
  SDK  GraphRAG-SDK 1.4.0 with its default ingestion and retrieval, building its own knowledge graph in FalkorDB (a
       fresh `graphrag_acme` graph, deleted afterwards) from the brain's source documents plus the brain's facts
       rendered as text, and answering with `completion()` on claude-haiku-4-5. It runs in an isolated venv
       (scripts/graphrag_sdk_venv.sh) through evals/graphrag_sdk_worker.py, which never sees a truth file.

This file builds the corpus, runs FL, drives the worker, and grades both arms with one content rule (below).

    scripts/graphrag_sdk_venv.sh                                         # once: isolated venv, the #344 patch
    PYTHONPATH=backend uv run python evals/graphrag_sdk_arm.py --dry-run  # corpus + cost estimate; no API call
    PYTHONPATH=backend uv run python evals/graphrag_sdk_arm.py --smoke    # SDK pipeline with a stub model; no spend
    PYTHONPATH=backend uv run python evals/graphrag_sdk_arm.py --run --reason "..."   # paid; hard cap --cap

Grading (pre-registered):
- cited ids of an answer: FL, the ids its citation guard accepted (as brain_heldout); SDK, every graph id written in
  the answer (whole word, any case) plus every id whose exact name or title is written in it (whole word, any case;
  names for Service, Datastore, Table, KPI, Dashboard, Team, Person, Customer, SLO; titles for Decision, Policy,
  Runbook). Each name→id mapping is reported.
- answerable: correct when every expected id is cited (FL also needs its guard to pass, as brain_heldout).
- unanswerable: FL, no citations (brain_heldout's rule); SDK, the answer says the information is not there (a fixed
  phrase list, ABSTAIN). Stricter variant, reported: that phrase and no cited id at all.
- citations: names its sources (at least one graph id written verbatim); every id-shaped token exists in the graph.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

WORK = ROOT / "tmp" / "graphrag_sdk"
VENV_PY = WORK / "venv" / "bin" / "python"
WORKER = ROOT / "evals" / "graphrag_sdk_worker.py"
CORPUS = WORK / "corpus"
RAW = ROOT / "evals" / "results" / "graphrag_sdk_raw"
OUT = ROOT / "evals" / "results" / "graphrag_sdk.json"
DOCS = ROOT / "data" / "gen" / "docs"
SDK_GRAPH = "graphrag_acme"
TENANT = "acme"
CAP_USD = 1.50
SETS = {"s2": "heldout_blind2.truth.json", "orig": "questions.truth.json"}   # s2 primary, orig secondary

NAME_LABELS = ("Service", "Datastore", "Table", "KPI", "Dashboard", "Team", "Person", "Customer", "SLO")
TITLE_LABELS = ("Decision", "Policy", "Runbook")
ID_SHAPES = re.compile(r"(?<![A-Za-z0-9_.-])(ADR-\d+|POL-[a-z0-9-]+|p-\d{3}|team-[a-z]+|rb-[a-z0-9-]+|inc-[a-z0-9]+|"
                       r"pm-[a-z0-9]+|slo-[a-z-]+|cust-[a-z-]+|doc-[a-z0-9-]+|dep-\d+|pr-\d+)(?![A-Za-z0-9_-])")
ABSTAIN = re.compile(
    r"\b(no (information|info|record|records|mention|data|details?|decision|documentation|evidence|such|recorded|"
    r"documented|relevant)|not (mentioned|specified|documented|recorded|found|available|provided|included|contained|"
    r"covered|stated|described|listed|present|in the (context|graph|documents?))|(doesn't|does not|do not|don't|did not|"
    r"didn't) (mention|specify|contain|include|provide|have|say|state|describe|list|cover|show|record)|(isn't|is not|"
    r"aren't|are not) (any|mentioned|documented|recorded|specified|covered|in the)|there (is|are) no|there's no|"
    r"(cannot|can't|could not|couldn't|unable to) (find|determine|answer|identify|locate|confirm|see)|insufficient|"
    r"nothing (in|about))\b", re.I)


# ------------------------------------------------------------------ corpus: what the SDK is fed
def _day(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d") if ms is not None else ""


def _minute(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _rows(g, q: str, params: dict | None = None) -> list[list]:
    return g.ro_query(q, params or {}, timeout=10_000).result_set


def _sym(sid: str, syms: dict) -> str:
    s = syms.get(sid)
    return f"the {s[0].replace('_', ' ')} symptom on {s[1]} ({sid})" if s else sid


def render_facts(g) -> dict[str, str]:
    """The brain's facts as plain English, one document per topic, read from golden_acme (read-only). One sentence
    per entity (a person, a component's committers, an incident), each ending in a full stop, so the SDK's sentence
    chunker never splits a fact. Components are named once in facts-services and by id elsewhere."""
    name = {r[0]: r[1] for r in _rows(g, "MATCH (n) WHERE n.name IS NOT NULL RETURN n.id, n.name")}
    syms = {r[0]: (r[1], r[2]) for r in _rows(g, "MATCH (s:Symptom) RETURN s.id, s.kind, s.target_id")}
    who = lambda p: f"{name.get(p, p)} ({p})"  # noqa: E731
    docs: dict[str, str] = {}

    # services, datastores and data assets; failure propagation
    L = ["# Acme services, datastores and data assets", "",
         "These facts are exported from Acme's operational records; ids are given as written.", ""]
    for i, labels, nm, tier, rev, kind in _rows(g, "MATCH (n) WHERE n:Service OR n:Datastore OR n:Table OR n:KPI OR "
                                                  "n:Dashboard OR n:Transform RETURN n.id, labels(n), n.name, n.tier, "
                                                  "n.revenue_path, n.kind ORDER BY n.id"):
        what = next((x for x in labels if x != "Node"), "component").lower()
        bits = [f"{i} is a {what}" + (f" named \"{nm}\"" if nm and nm != i else "")]
        if kind:
            bits.append(f"of kind {kind}")
        if tier is not None:
            bits.append(f"at tier {tier}")
        if rev is not None:
            bits.append("on the revenue path" if rev else "not on the revenue path")
        L.append(", ".join(bits) + ".")
    L += ["", "## Failure propagation (what depends on what)", ""]
    for a, b, why in _rows(g, "MATCH (a)-[e:PROPAGATES_TO]->(b) RETURN a.id, b.id, e.cap_why ORDER BY a.id, b.id"):
        L.append(f"If {a} fails, {b} is affected because {b} depends on {a}" + (f" ({why})" if why else "") + ".")
    docs["facts-services"] = "\n".join(L)

    # ownership now and over time
    L = ["# Acme ownership: which team owns which component, now and in the past", ""]
    owns = {}
    for t, tn, c in _rows(g, "MATCH (t:Team)-[:OWNS]->(c) RETURN t.id, t.name, c.id ORDER BY t.id, c.id"):
        owns.setdefault((t, tn), []).append(c)
    for (t, tn), cs in owns.items():
        L.append(f"Team {tn} ({t}) currently owns {', '.join(cs)}.")
    L += ["", "## Ownership history", ""]
    for c, t, tn, f, to in _rows(g, "MATCH (t:Team)-[e:OWNED_AT]->(c) RETURN c.id, t.id, t.name, e.from, e.to "
                                    "ORDER BY c.id, e.from"):
        L.append(f"{c} was owned by team {tn} ({t}) from {_day(f)} to {_day(to)}." if to is not None else
                 f"{c} has been owned by team {tn} ({t}) since {_day(f)}.")
    docs["facts-ownership"] = "\n".join(L)

    # people: role, team, still here or left, manager; then who committed to what
    L = ["# Acme people: roles, teams, who has left, and who worked on what", ""]
    member = {}
    for p, t, tn, f, to in _rows(g, "MATCH (p:Person)-[e:MEMBER_OF]->(t:Team) RETURN p.id, t.id, t.name, e.from, e.to "
                                    "ORDER BY p.id, e.from"):
        member.setdefault(p, []).append(f"team {tn} ({t}) from {_day(f)} to {_day(to)}" if to is not None else
                                        f"team {tn} ({t}) since {_day(f)}")
    boss = {r[0]: r[1] for r in _rows(g, "MATCH (p:Person)-[:REPORTS_TO]->(b:Person) RETURN p.id, b.id")}
    for p, nm, role, active, valid_to in _rows(g, "MATCH (p:Person) RETURN p.id, p.name, p.role, p.active, p.valid_to "
                                                  "ORDER BY p.id"):
        bits = [f"{nm} ({p}) is a {role}"]
        if member.get(p):
            bits.append("member of " + "; then ".join(member[p]))
        if p in boss:
            bits.append(f"reports to {who(boss[p])}")
        bits.append("still at Acme (active)" if active else
                    "has left Acme" + (f" (inactive since {_day(valid_to)})" if valid_to else " (inactive)"))
        L.append(", ".join(bits) + ".")
    L += ["", "## Commits: who has worked on which component", ""]
    com = {}
    for p, c, n in _rows(g, "MATCH (p:Person)-[e:COMMITTED]->(c) RETURN p.id, c.id, e.n ORDER BY c.id, e.n DESC, p.id"):
        com.setdefault(c, []).append(f"{who(p)} {n}")
    for c, xs in com.items():
        L.append(f"Commits to {c}, by person: {', '.join(xs)}.")
    docs["facts-people"] = "\n".join(L)

    # decisions and policies
    L = ["# Acme decisions and policies: what was decided, by whom, and what it constrains", ""]
    deciders = {}
    for d, p in _rows(g, "MATCH (p:Person)-[:DECIDED]->(d) RETURN d.id, p.id ORDER BY d.id, p.id"):
        deciders.setdefault(d, []).append(who(p))
    cons = {}
    for d, c in _rows(g, "MATCH (d)-[:CONSTRAINS|FREEZES]->(c) RETURN d.id, c.id ORDER BY d.id, c.id"):
        cons.setdefault(d, []).append(c)
    for d, title, status, at, why, labels in _rows(g, "MATCH (d) WHERE d:Decision OR d:Policy RETURN d.id, d.title, "
                                                      "d.status, d.decided_at, d.why, labels(d) ORDER BY d.id"):
        kind = "policy" if "Policy" in labels else "decision"
        L.append(f"{d} is a {kind} titled \"{title}\", status {status}, decided on {_day(at)}"
                 + (f" by {' and '.join(deciders[d])}" if d in deciders else "")
                 + (f", constraining {', '.join(cons[d])}" if d in cons else "") + ".")
        if why:
            L.append(f"The reason for {d}: {why}")
    for a, b, at in _rows(g, "MATCH (a)-[e:SUPERSEDES]->(b) RETURN a.id, b.id, e.at"):
        L.append(f"{a} supersedes {b} since {_day(at)}, so {b} is superseded.")
    docs["facts-decisions"] = "\n".join(L)

    # runbooks
    L = ["# Acme runbooks: which runbook covers which service or symptom", ""]
    rbf = {}
    for r, x in _rows(g, "MATCH (r:Runbook)-[:RUNBOOK_FOR]->(x) RETURN r.id, x.id ORDER BY r.id, x.id"):
        rbf.setdefault(r, []).append(_sym(x, syms) if x in syms else x)
    for r, title, vf, src in _rows(g, "MATCH (r:Runbook) RETURN r.id, r.title, r.valid_from, r.source ORDER BY r.id"):
        L.append(f"{r} is a {'derived ' if src == 'derived' else ''}runbook titled \"{title}\""
                 + (f", valid from {_day(vf)}" if vf else "")
                 + (f", for {' and '.join(rbf[r])}" if r in rbf else "") + ".")
    docs["facts-runbooks"] = "\n".join(L)

    # incidents and their postmortems
    L = ["# Acme incident history: when, where it started, what it hit, who fixed it, and the postmortem", ""]
    aff, res, cause, pm, act = {}, {}, {}, {}, {}
    for i, x, role in _rows(g, "MATCH (i:Incident)-[e:AFFECTED]->(x) RETURN i.id, x.id, e.role ORDER BY i.id, x.id"):
        aff.setdefault(i, []).append((x, role))
    for p, i in _rows(g, "MATCH (p:Person)-[:RESOLVED]->(i:Incident) RETURN p.id, i.id ORDER BY p.id"):
        res.setdefault(i, []).append(who(p))
    for d, i in _rows(g, "MATCH (d:Deploy)-[:CAUSED]->(i:Incident) RETURN d.id, i.id ORDER BY d.id"):
        cause.setdefault(i, []).append(d)
    for m, s, i in _rows(g, "MATCH (m:Postmortem)-[:DOCUMENTS]->(i:Incident) RETURN m.id, m.summary, i.id"):
        pm[i] = (m, s)
    for i, k, tgt, v in _rows(g, "MATCH (i:Incident)-[:RESOLVED_BY]->(a:Action) RETURN i.id, a.kind, a.target_id, "
                                 "a.verdict ORDER BY a.id"):
        act.setdefault(i, []).append(f"{k.replace('_', ' ')} {tgt} ({v})")
    for i, title, onset, resolved in _rows(g, "MATCH (i:Incident) RETURN i.id, i.title, i.onset_at, i.resolved_at "
                                              "ORDER BY i.id"):
        bits = [f"Incident {i} \"{title}\" began {_minute(onset)}" + (f", resolved {_minute(resolved)}" if resolved else "")]
        causes = [x for x, r in aff.get(i, []) if r == "cause"]
        hit = [x for x, r in aff.get(i, []) if r != "cause"]
        if causes:
            bits.append(f"started in {', '.join(causes)}")
        if hit:
            bits.append(f"impacted {', '.join(hit)}")
        if cause.get(i):
            bits.append(f"caused by deploy {', '.join(cause[i])}")
        if res.get(i):
            bits.append(f"resolved by {', '.join(res[i])}")
        if act.get(i):
            bits.append(f"fix: {'; '.join(act[i])}")
        L.append("; ".join(bits) + ".")
        if i in pm:
            L.append(f"Postmortem {pm[i][0]} for {i}: {pm[i][1]}")
    docs["facts-incidents"] = "\n".join(L)

    # customers, SLOs and feature flags
    L = ["# Acme customers, service-level objectives and feature flags", ""]
    uses = {}
    for c, s, via in _rows(g, "MATCH (c:Customer)-[e:CONSUMES]->(s) RETURN c.id, s.id, e.via ORDER BY c.id, s.id"):
        uses.setdefault(c, []).append(s + (f" (via {via})" if via else ""))
    for c, nm, tier, mrr in _rows(g, "MATCH (c:Customer) RETURN c.id, c.name, c.tier, c.mrr ORDER BY c.id"):
        L.append(f"Customer {nm} ({c}) is tier {tier} with monthly recurring revenue {mrr:g} USD"
                 + (f" and uses {', '.join(uses[c])}" if c in uses else "") + ".")
    for s, nm, x in _rows(g, "MATCH (s:SLO)-[:FOR]->(x) RETURN s.id, s.name, x.id ORDER BY s.id"):
        L.append(f"{s} (\"{nm}\") is the service-level objective for {x}.")
    gates = {}
    for f, x in _rows(g, "MATCH (f:FeatureFlag)-[:GATES]->(x) RETURN f.id, x.id ORDER BY f.id, x.id"):
        gates.setdefault(f, []).append(x)
    for f, state in _rows(g, "MATCH (f:FeatureFlag) RETURN f.id, f.state ORDER BY f.id"):
        L.append(f"Feature flag {f} is {state}" + (f" and gates {', '.join(gates[f])}" if f in gates else "") + ".")
    docs["facts-customers-slos-flags"] = "\n".join(L)
    return docs


def build_corpus(g) -> dict:
    """Write the corpus the SDK ingests (inputs, not results) and return its manifest."""
    if CORPUS.exists():
        shutil.rmtree(CORPUS)
    CORPUS.mkdir(parents=True)
    docs = [(p.stem, p.read_text()) for p in sorted(DOCS.glob("*.md"))]   # acme's 13 documents (globex/ excluded)
    docs += sorted(render_facts(g).items())
    man = []
    for did, text in docs:
        (CORPUS / f"{did}.md").write_text(text)
        man.append({"id": did, "file": f"{did}.md", "kind": "facts" if did.startswith("facts-") else "document",
                    "words": len(text.split()), "chars": len(text),
                    "sha256": hashlib.sha256(text.encode()).hexdigest()})
    (CORPUS / "manifest.json").write_text(json.dumps({"docs": man}, indent=1) + "\n")
    return {"docs": man, "documents": sum(1 for d in man if d["kind"] == "document"),
            "facts_docs": sum(1 for d in man if d["kind"] == "facts"), "words": sum(d["words"] for d in man)}


# ------------------------------------------------------------------ questions (the grader reads the truth files)
def load_set(s: str) -> list[dict]:
    t = json.loads((ROOT / "data" / "brain" / SETS[s]).read_text())
    out = []
    for n, q in enumerate(t["questions"], 1):
        if "expect_ids" in q:
            out.append({"set": s, "id": q["id"], "q": q["question"], "expect": list(q["expect_ids"])})
        else:
            out.append({"set": s, "id": f"O{n:02d}", "q": q["q"], "expect": list(q["must_cite"])})
    return out


# ------------------------------------------------------------------ grading
def _norm(s: str) -> str:
    """Case-insensitive, and hyphen / underscore / space are one separator ("fraud detection" = "fraud-detection")."""
    return re.sub(r"[-_ ]+", "-", str(s).lower())


class IdIndex:
    """Every node id of golden_acme (except the router's IntentExemplar nodes), and the name/title → id map."""

    def __init__(self, g=None, rows: list | None = None) -> None:
        rows = rows if rows is not None else _rows(g, "MATCH (n) WHERE n.id IS NOT NULL AND NOT n:IntentExemplar AND "
                                                      "NOT n:Meta RETURN n.id, labels(n), n.name, n.title")
        self.ids = {str(r[0]) for r in rows}
        self.by_norm: dict[str, set[str]] = {}
        for i in self.ids:
            self.by_norm.setdefault(_norm(i), set()).add(i)
        self.names: dict[str, set[str]] = {}   # normalised name or title -> ids
        texts: set[str] = set()
        for i, labels, nm, title in rows:
            for text, ok in ((nm, any(x in labels for x in NAME_LABELS)), (title, any(x in labels for x in TITLE_LABELS))):
                if ok and text and len(str(text)) >= 3 and _norm(text) != _norm(i):
                    self.names.setdefault(_norm(text), set()).add(str(i))
                    texts.add(str(text))
        self._id_rx = _alternation(self.ids)
        self._name_rx = _alternation(texts)

    def verbatim(self, text: str) -> set[str]:
        return {i for m in self._id_rx.findall(text or "") for i in self.by_norm.get(_norm(m), ())}

    def by_name(self, text: str) -> dict[str, list[str]]:
        return {_norm(m): sorted(self.names[_norm(m)]) for m in self._name_rx.findall(text or "") if _norm(m) in self.names}


def _alternation(words) -> re.Pattern:
    ws = sorted({str(w) for w in words}, key=len, reverse=True)
    alts = [re.sub(r"(\\-|_|\\ )+", "[-_ ]+", re.escape(w)) for w in ws]
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(alts) + r")(?![A-Za-z0-9_-])", re.I)


def fabricated(text: str, idx: IdIndex) -> list[str]:
    """Id-shaped tokens (the corpus's id grammar) that are not ids in the graph."""
    return sorted({m for m in ID_SHAPES.findall(text or "") if _norm(m) not in idx.by_norm})


def text_cited(text: str, idx: IdIndex) -> tuple[set[str], dict[str, list[str]]]:
    names = idx.by_name(text)
    return idx.verbatim(text) | {i for ids in names.values() for i in ids}, names


def grade(q: dict, answer: str, cited: set[str], guard_ok: bool, idx: IdIndex, rule: str) -> dict:
    """rule 'fl': brain_heldout (expected ⊆ cited and guard; unanswerable = no citations).
    rule 'sdk': expected ⊆ cited; unanswerable = an abstention phrase (strict: and nothing cited)."""
    want = set(q["expect"])
    abst = bool(ABSTAIN.search(answer or ""))
    if want:
        ok = want <= cited and (guard_ok if rule == "fl" else True)
        strict = ok
    elif rule == "fl":
        ok = strict = not cited
    else:
        ok, strict = abst, abst and not cited
    verb = idx.verbatim(answer)
    fab = fabricated(answer, idx)
    return {"ok": ok, "ok_strict": strict, "abstained": abst, "missing": sorted(want - cited),
            "cited": sorted(cited), "names_sources": bool(verb) if rule == "sdk" else bool(cited),
            "fabricated": fab, "precision": (round(len(want & cited) / len(cited), 4) if want and cited else None)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar (binomial on the discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 4)


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))], 1)


# ------------------------------------------------------------------ the Faultline arm
def faultline_arm(qs: list[dict]) -> list[dict]:
    from faultline.brain.ask import ask
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.tenant import golden_graph

    db = gclient.engine()
    room = f"eval_{TENANT}_graphragcmp_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, golden_graph(TENANT), room)
    rows = []
    try:
        for q in qs:
            t0 = time.perf_counter()
            a = ask(q["q"], TENANT, graph=room)
            rows.append({"set": q["set"], "id": q["id"], "answer": a.answer, "citations": sorted(set(a.citations)),
                         "guard_ok": bool(a.guard.get("ok")), "intent": a.intent,
                         "ms": round((time.perf_counter() - t0) * 1000, 1)})
    finally:
        gcopy.delete_if_exists(db, room)
    return rows


# ------------------------------------------------------------------ the SDK worker
def _key() -> str:
    from faultline.config import settings

    return settings.anthropic_api_key or ""


def worker(mode: str, qfile: Path, out: Path, cap: float = 0.0, est_q: float = 0.02, contexts: Path | None = None,
           graph: str = SDK_GRAPH, mem_mb: int = 4000, chunks: int = 0) -> dict:
    from faultline.config import settings

    if not VENV_PY.exists():
        raise SystemExit(f"no SDK venv at {VENV_PY}: run scripts/graphrag_sdk_venv.sh first")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "PYTHONPATH")}
    env.update({"HF_HOME": str(WORK / "hf"), "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false",
                "TIKTOKEN_CACHE_DIR": str(WORK / "tiktoken"), "LITELLM_LOG": "ERROR", "PYTHONNOUSERSITE": "1",
                "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "MALLOC_ARENA_MAX": "2"})   # memory, not results
    key = ""
    if mode == "run":
        key = _key()
        if not key:
            raise SystemExit("run: no Anthropic key in the project settings (.env ANTHROPIC_API_KEY)")
        env["ANTHROPIC_API_KEY"] = key   # into the child's environment only; never printed or written
    cmd = [str(VENV_PY), "-I", str(WORKER), mode, "--corpus", str(CORPUS), "--questions", str(qfile), "--out", str(out),
           "--graph", graph, "--host", settings.falkordb_host, "--port", str(settings.falkordb_port),
           "--cap", f"{cap:.4f}", "--est-per-question", f"{est_q:.5f}", "--chunks-total", str(chunks),
           "--embed-cache", str(ROOT / ".cache" / "fastembed")]
    if contexts:
        cmd += ["--contexts", str(contexts)]
    if mode != "estimate":
        cmd = [str(ROOT / "scripts" / "memguard.sh"), str(mem_mb), *cmd]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(WORK))
    scrub = (lambda s: s.replace(key, "[redacted]")) if key else (lambda s: s)  # noqa: E731
    log = scrub(p.stdout + p.stderr)
    (WORK / f"worker_{mode}.log").write_text(log)
    if out.exists():
        out.write_text(scrub(out.read_text()))
    if p.returncode != 0:
        if mode != "estimate":   # a killed worker (memguard: SIGKILL) never reaches its own cleanup
            from faultline.graph import client as gclient
            from faultline.graph import copy as gcopy

            db = gclient.engine()
            for gname in (graph, f"{graph}__ontology"):
                gcopy.delete_if_exists(db, gname)
        raise SystemExit(f"worker {mode} failed (exit {p.returncode}); log: {WORK / f'worker_{mode}.log'}\n{log[-2000:]}")
    return json.loads(out.read_text())


# ------------------------------------------------------------------ summary
def summarise(qs: list[dict], fl: list[dict], sdk: dict | None, idx: IdIndex) -> dict:
    by_fl = {(r["set"], r["id"]): r for r in fl}
    by_sdk = {(r["set"], r["id"]): r for r in (sdk or {}).get("answers", [])}
    rows, sets = [], {}
    for q in qs:
        k = (q["set"], q["id"])
        f = by_fl[k]
        g_fl = grade(q, f["answer"], set(f["citations"]), f["guard_ok"], idx, "fl")
        t_cited, _ = text_cited(f["answer"], idx)
        g_fl_text = grade(q, f["answer"], t_cited, True, idx, "sdk")   # the SDK's rule on FL's text, for symmetry
        row = {"set": q["set"], "id": q["id"], "q": q["q"], "expect": q["expect"],
               "fl": {**g_fl, "ok_textrule": g_fl_text["ok"], "ms": f["ms"], "answer": f["answer"], "intent": f["intent"]}}
        s = by_sdk.get(k)
        if s is not None:
            cited, names = text_cited(s.get("answer", ""), idx)
            g = grade(q, s.get("answer", ""), cited, True, idx, "sdk")
            g_ids = grade(q, s.get("answer", ""), idx.verbatim(s.get("answer", "")), True, idx, "sdk")
            row["sdk"] = {**g, "ok_ids_only": g_ids["ok"], "name_map": names, "ms": s["ms"], "answer": s.get("answer", ""),
                          "error": s.get("error"), "usd": s.get("usd"), "in": s.get("in"), "out": s.get("out"),
                          "context_items": s.get("context_items")}
        rows.append(row)
    for s in dict.fromkeys(q["set"] for q in qs):
        rs = [r for r in rows if r["set"] == s]
        ans = [r for r in rs if r["expect"]]
        una = [r for r in rs if not r["expect"]]
        x: dict = {"questions": len(rs), "answerable": len(ans), "unanswerable": len(una)}
        for arm in ("fl", "sdk"):
            have = [r for r in rs if arm in r]
            if len(have) != len(rs):
                x[arm] = {"answered": len(have), "complete": False}
                continue
            a = {"answered": len(have), "complete": True,
                 "correct": sum(r[arm]["ok"] for r in rs),
                 "answerable_correct": sum(r[arm]["ok"] for r in ans),
                 "unanswerable_honest": sum(r[arm]["ok"] for r in una),
                 "unanswerable_honest_strict": sum(r[arm]["ok_strict"] for r in una),
                 "names_sources": sum(r[arm]["names_sources"] for r in ans),
                 "answers_with_fabricated_ids": sum(bool(r[arm]["fabricated"]) for r in rs),
                 "false_abstain": sum(1 for r in ans if r[arm]["abstained"] and not r[arm]["ok"]),
                 "ms_p50": _pct([r[arm]["ms"] for r in rs], 0.5), "ms_p95": _pct([r[arm]["ms"] for r in rs], 0.95),
                 "precision_mean": (round(statistics.fmean(ps), 4) if (ps := [r[arm]["precision"] for r in ans
                                                                              if r[arm]["precision"] is not None]) else None)}
            ci = wilson(a["correct"], len(rs))
            a["correct_ci"] = list(ci) if ci else None
            if arm == "fl":
                a["correct_textrule"] = sum(r["fl"]["ok_textrule"] for r in rs)
            else:
                a["correct_ids_only"] = sum(r["sdk"]["ok_ids_only"] for r in rs)
                a["answers_with_name_mapping"] = sum(bool(r["sdk"]["name_map"]) for r in rs)
                a["errors"] = sum(bool(r["sdk"]["error"]) for r in rs)
                a["usd"] = round(sum(r["sdk"]["usd"] or 0 for r in rs), 4)
                a["usd_per_question"] = round(a["usd"] / len(rs), 5)
                a["tokens_in"] = sum(r["sdk"]["in"] or 0 for r in rs)
                a["tokens_out"] = sum(r["sdk"]["out"] or 0 for r in rs)
            x[arm] = a
        if x["fl"].get("complete") and x["sdk"].get("complete"):
            b = sum(1 for r in rs if r["fl"]["ok"] and not r["sdk"]["ok"])
            c = sum(1 for r in rs if r["sdk"]["ok"] and not r["fl"]["ok"])
            x["paired"] = {"both": sum(1 for r in rs if r["fl"]["ok"] and r["sdk"]["ok"]), "fl_only": b, "sdk_only": c,
                           "neither": sum(1 for r in rs if not r["fl"]["ok"] and not r["sdk"]["ok"]),
                           "mcnemar_p": mcnemar_exact(b, c)}
        by_kind: dict[str, dict] = {}
        truth = json.loads((ROOT / "data" / "brain" / SETS[s]).read_text())["questions"]
        kind = {(q.get("id") or ""): q.get("kind") or q.get("intent") for q in truth}
        for n, r in enumerate(rs, 1):
            kd = kind.get(r["id"]) or truth[n - 1].get("intent", "?")
            e = by_kind.setdefault(kd, {"n": 0, "fl": 0, "sdk": 0})
            e["n"] += 1
            e["fl"] += r["fl"]["ok"]
            e["sdk"] += bool(r.get("sdk", {}).get("ok"))
        x["by_kind"] = by_kind
        sets[s] = x
    return {"sets": sets, "rows": rows}


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument("--dry-run", action="store_true", help="corpus + cost estimate; no API call, no SDK graph")
    m.add_argument("--smoke", action="store_true", help="SDK pipeline with a stub model on a throwaway graph; no spend")
    m.add_argument("--run", action="store_true", help="the paid run (hard cap --cap)")
    ap.add_argument("--sets", default="s2,orig", help="question sets in order (s2 primary, orig secondary)")
    ap.add_argument("--cap", type=float, default=CAP_USD, help="hard cap on model spend for this run, US$")
    ap.add_argument("--reason", default="")
    ap.add_argument("--min-avail-mb", type=int, default=4500)
    ap.add_argument("--mem-mb", type=int, default=4000, help="memguard cap for the SDK worker (smoke peak: 3,163 MB)")
    a = ap.parse_args()
    from faultline.graph import client as gclient

    sets = [s for s in a.sets.split(",") if s]
    for s in sets:
        if s not in SETS:
            raise SystemExit(f"unknown set {s!r}")
    db = gclient.engine()
    golden = db.select_graph(f"golden_{TENANT}")
    corpus = build_corpus(golden)
    qs = [q for s in sets for q in load_set(s)]
    RAW.mkdir(parents=True, exist_ok=True)
    qfile = WORK / "questions.json"   # ids and texts only: the worker never sees an expected answer
    qfile.write_text(json.dumps([{"set": q["set"], "id": q["id"], "q": q["q"]} for q in qs], indent=1) + "\n")
    est = worker("estimate", qfile, WORK / "estimate.json")
    proj = {"ingest_usd": est["ingest"]["usd"], **{f"{s}_usd": est["sets"][s]["usd"] for s in sets}}
    proj["total_usd"] = round(sum(proj.values()), 4)
    print(json.dumps({"corpus": {k: v for k, v in corpus.items() if k != "docs"}, "chunks": est["chunks"],
                      "estimate": proj, "cap": a.cap}, indent=1))
    if a.dry_run:
        (RAW / "dry_run.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "corpus": corpus,
                                                      "estimate": est, "projection": proj, "cap": a.cap}, indent=1) + "\n")
        return 0
    if a.smoke:
        qs_smoke = [{"set": "smoke", "id": q["id"], "q": q["q"]} for q in qs[:2]]
        qf = WORK / "questions_smoke.json"
        qf.write_text(json.dumps(qs_smoke) + "\n")
        r = worker("smoke", qf, WORK / "smoke.json", graph=f"graphrag_smoke_{os.getpid()}", mem_mb=a.mem_mb)
        print(json.dumps({"stopped": r["stopped"], "kg": r.get("kg"), "answers": [x.get("answer") for x in r["answers"]],
                          "warnings": r["warning_count"], "graphs_deleted": r["graphs_deleted"],
                          "maxrss_mb": r.get("maxrss_mb"), "ingest_s": r["ingest"].get("seconds"),
                          "docs_failed": [d["id"] for d in r["ingest"]["docs"] if d["error"]]}, indent=1))
        return 0
    # ---- the paid run
    if not a.reason:
        raise SystemExit("--run needs --reason")
    first = est["ingest"]["usd"] + est["sets"][sets[0]]["usd"]
    if first > a.cap:
        raise SystemExit(f"refusing: the estimate for ingestion + set {sets[0]} is US${first:.2f} > cap US${a.cap:.2f}")
    avail = int(next(ln.split()[1] for ln in Path("/proc/meminfo").read_text().splitlines()
                     if ln.startswith("MemAvailable"))) // 1024
    if avail < a.min_avail_mb:
        raise SystemExit(f"refusing: {avail} MB available < {a.min_avail_mb} MB (wait for other heavy jobs)")
    if any(gname in db.list_graphs() for gname in (SDK_GRAPH, f"{SDK_GRAPH}__ontology")):
        raise SystemExit(f"refusing: {SDK_GRAPH} already exists; it must be created fresh")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    fl = faultline_arm(qs)
    raw_path = RAW / "worker_run.json"
    sdk = worker("run", qfile, raw_path, cap=a.cap, est_q=est["per_question"]["usd"],
                 contexts=RAW / "contexts.json.gz", mem_mb=a.mem_mb, chunks=est["chunks"])
    idx = IdIndex(golden)
    summ = summarise(qs, fl, sdk, idx)
    ing = sdk.get("ingest", {})
    out = {"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason,
           "config": {k: sdk.get(k) for k in ("sdk_version", "model", "max_tokens", "temperature", "embedder",
                                              "embedding_dimension", "graph", "cap_usd")},
           "corpus": corpus, "chunks": est["chunks"], "estimate": proj,
           "ingest": {"docs": len(ing.get("docs", [])), "seconds": ing.get("seconds"),
                      "s_per_doc": (round(ing["seconds"] / len(ing["docs"]), 2) if ing.get("seconds") and ing.get("docs") else None),
                      "cost": ing.get("cost"), "finalize": ing.get("finalize"),
                      "doc_errors": [d["id"] for d in ing.get("docs", []) if d.get("error")]},
           "kg": sdk.get("kg"), "meter": sdk.get("meter"), "stopped": sdk.get("stopped"),
           "skipped_sets": sdk.get("skipped_sets", []), "warning_count": sdk.get("warning_count"),
           "step_failures": sum(1 for w in sdk.get("warnings", []) if "Step 2" in w["msg"] or "Step 1" in w["msg"]),
           "graphs_deleted": sdk.get("graphs_deleted"),
           "name_map_universe": {"name_labels": NAME_LABELS, "title_labels": TITLE_LABELS, "names": len(idx.names)},
           **summ}
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({s: {arm: {k: v for k, v in x[arm].items() if k in ("correct", "answered", "unanswerable_honest",
                                                                          "usd", "ms_p50")} for arm in ("fl", "sdk")}
                      for s, x in summ["sets"].items()}, indent=1))
    print(json.dumps({"spent_usd": (sdk.get("meter") or {}).get("spent_usd"), "stopped": sdk.get("stopped"),
                      "graphs_deleted": sdk.get("graphs_deleted")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
