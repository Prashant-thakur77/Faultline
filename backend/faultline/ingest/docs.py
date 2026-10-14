"""Authored knowledge corpus (`data/gen/docs/*.md`: ADRs, runbooks, incident-channel chats and issues) → Bundle.

Each file is YAML front matter plus 1–3 paragraphs of synthetic prose. Pure and deterministic: the files
are read in sorted order, dates in front matter become epoch ms (UTC midnight), nothing reads the clock
and nothing touches FalkorDB. `seed` is accepted for the common producer contract and is not used.

Nodes: Doc {kind adr|runbook, title, url, digest = sha256(file bytes), reviewed_at},
Decision {title, status, rule_key, rule_op, rule_value, decided_at, url},
Runbook {title, body, source, salience, valid_from, reviewed_at, url}.
Edges: Doc -PRODUCED-> Decision | Runbook; Decision -CONSTRAINS-> Service | Datastore;
Decision -SUPERSEDES-> Decision; Decision -CITES-> Doc (its own source, plus `cites`); Person -DECIDED-> Decision (`decided_by`);
Runbook -RUNBOOK_FOR-> Service and -> Symptom (symptom ids come from `history.symptom_id`);
Doc {kind chat|issue} -ABOUT-> component | Incident (decisions cite the conversation they came from).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from . import org_gen
from .bundle import Bundle

TENANT = org_gen.TENANT
DOCS_DIR = org_gen.REPO_ROOT / "data" / "gen" / "docs"

RULE_OPS = frozenset({"<=", ">=", "==", "required"})
DECISION_STATUS = frozenset({"active", "superseded", "revoked"})
RUNBOOK_SOURCES = frozenset({"human", "derived"})


class DocError(ValueError):
    """A corpus file violates the front-matter contract."""


def _split(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise DocError(f"{path.name}: missing YAML front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise DocError(f"{path.name}: unterminated front matter")
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise DocError(f"{path.name}: front matter must be a mapping")
    return meta, text[end + 5:].strip()


def _ms(value: Any, field: str, name: str) -> int:
    if isinstance(value, dt.datetime):
        d = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    elif isinstance(value, dt.date):
        d = dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    elif isinstance(value, str):
        try:
            d = dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except ValueError as e:
            raise DocError(f"{name}: {field} must be YYYY-MM-DD, got {value!r}") from e
    else:
        raise DocError(f"{name}: {field} missing or not a date")
    return int(d.timestamp() * 1000)


def _req(meta: dict[str, Any], key: str, name: str) -> Any:
    if meta.get(key) in (None, ""):
        raise DocError(f"{name}: front matter needs {key!r}")
    return meta[key]


def _list(meta: dict[str, Any], key: str) -> list[str]:
    v = meta.get(key) or []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


def _rule(meta: dict[str, Any], name: str) -> tuple[str, str, bool | int | float | str]:
    key, op, value = _req(meta, "rule_key", name), _req(meta, "rule_op", name), meta.get("rule_value")
    if op not in RULE_OPS:
        raise DocError(f"{name}: rule_op {op!r} not in {sorted(RULE_OPS)}")
    if op in ("<=", ">=") and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise DocError(f"{name}: rule_op {op} needs a numeric rule_value, got {value!r}")
    if op == "==" and not isinstance(value, (bool, int, float, str)):
        raise DocError(f"{name}: rule_value must be a scalar, got {value!r}")
    if op == "required" and value is None:
        value = True
    return str(key), str(op), value


def _url(path: Path) -> str:
    """Repo-relative path of a corpus file (what a Doc/Decision/Runbook `url` points at)."""
    try:
        return path.resolve().relative_to(org_gen.REPO_ROOT).as_posix()
    except ValueError:  # a corpus outside the repo (tests): keep the historical prefix
        return f"data/gen/docs/{path.name}"


def build(seed: int = 42, docs_dir: Path = DOCS_DIR, tenant: str = TENANT,  # noqa: ARG001 - common producer contract
          components: dict[str, str] | None = None) -> Bundle:
    """`tenant`/`components` (component id -> Service | Datastore) let another tenant reuse the parser
    (ingest/globex/docs.py); the defaults are acme's."""
    if components is None:
        topo = org_gen.load_topology()
        comp_label = {s["id"]: "Service" for s in topo["services"]}
        comp_label.update({d["id"]: "Datastore" for d in topo["datastores"]})
    else:
        comp_label = dict(components)

    b = Bundle()
    decisions: dict[str, dict[str, Any]] = {}
    supersedes: list[tuple[str, str]] = []
    doc_ids: list[str] = []
    for path in sorted(docs_dir.glob("*.md")):
        meta, body = _split(path)
        name = path.name
        kind = _req(meta, "kind", name)
        nid, title = str(_req(meta, "id", name)), str(_req(meta, "title", name))
        doc_id = f"doc-{path.stem}"
        url = _url(path)
        reviewed_at = _ms(_req(meta, "reviewed_at", name), "reviewed_at", name)
        b.node("Doc", doc_id, tenant=tenant, kind=kind, title=title, url=url, reviewed_at=reviewed_at,
               digest=hashlib.sha256(path.read_bytes()).hexdigest(),
               **({"body": body[:4000]} if kind in ("chat", "issue") else {}))
        doc_ids.append(doc_id)

        if kind == "adr":
            status = _req(meta, "status", name)
            if status not in DECISION_STATUS:
                raise DocError(f"{name}: status {status!r} not in {sorted(DECISION_STATUS)}")
            key, op, value = _rule(meta, name)
            decided_at = _ms(_req(meta, "decided_at", name), "decided_at", name)
            b.node("Decision", nid, tenant=tenant, title=title, status=status, rule_key=key, rule_op=op,
                   rule_value=value, decided_at=decided_at, url=url)
            decisions[nid] = {"status": status, "decided_at": decided_at}
            b.edge("PRODUCED", "Doc", doc_id, "Decision", nid, at=decided_at)
            b.edge("CITES", "Decision", nid, "Doc", doc_id, at=decided_at)
            for cited in _list(meta, "cites"):
                if cited != doc_id:
                    b.edge("CITES", "Decision", nid, "Doc", cited, at=decided_at)
            for pid in _list(meta, "decided_by"):   # optional: who took the decision (Person ids from the org)
                if not re.fullmatch(r"p-\d{3}", str(pid)):
                    raise DocError(f"{name}: decided_by {pid!r} is not a person id (p-NNN)")
                b.edge("DECIDED", "Person", str(pid), "Decision", nid, at=decided_at)
            for comp in _list(meta, "constrains"):
                if comp not in comp_label:
                    raise DocError(f"{name}: constrains unknown component {comp!r}")
                b.edge("CONSTRAINS", "Decision", nid, comp_label[comp], comp, at=decided_at)
            supersedes += [(nid, old) for old in _list(meta, "supersedes")]
        elif kind == "runbook":
            source = _req(meta, "source", name)
            if source not in RUNBOOK_SOURCES:
                raise DocError(f"{name}: source {source!r} not in {sorted(RUNBOOK_SOURCES)}")
            valid_from = _ms(meta.get("valid_from", meta["reviewed_at"]), "valid_from", name)
            b.node("Runbook", nid, tenant=tenant, title=title, body=body, source=source, salience=1.0,
                   valid_from=valid_from, reviewed_at=reviewed_at, url=url)
            b.edge("PRODUCED", "Doc", doc_id, "Runbook", nid, at=valid_from)
            services, symptoms = _list(meta, "services"), _list(meta, "symptoms")
            if not services and not symptoms:
                raise DocError(f"{name}: a runbook needs services and/or symptoms")
            for comp in services:
                if comp_label.get(comp) != "Service":
                    raise DocError(f"{name}: runbook service {comp!r} is not a Service in the topology")
                b.edge("RUNBOOK_FOR", "Runbook", nid, "Service", comp)
            for sym in symptoms:
                if not sym.startswith("sym-"):
                    raise DocError(f"{name}: symptom id {sym!r} must look like sym-<kind>-<target>")
                b.edge("RUNBOOK_FOR", "Runbook", nid, "Symptom", sym)
        elif kind in ("chat", "issue"):
            # incident-channel chats and tickets: provenance for decisions (Decision -CITES-> Doc) and for the brain
            for comp in _list(meta, "about"):
                if comp not in comp_label:
                    raise DocError(f"{name}: about unknown component {comp!r}")
                b.edge("ABOUT", "Doc", doc_id, comp_label[comp], comp, at=reviewed_at)
            for inc in _list(meta, "incidents"):
                if not inc.startswith("inc-"):
                    raise DocError(f"{name}: incident id {inc!r} must look like inc-…")
                b.edge("ABOUT", "Doc", doc_id, "Incident", inc, at=reviewed_at)
        else:
            raise DocError(f"{name}: kind {kind!r} must be adr, runbook, chat or issue")

    for new, old in supersedes:
        if old not in decisions:
            raise DocError(f"{new} supersedes unknown decision {old}")
        if decisions[old]["status"] != "superseded":
            raise DocError(f"{old} is superseded by {new} but its status is {decisions[old]['status']!r}")
        b.edge("SUPERSEDES", "Decision", new, "Decision", old, at=decisions[new]["decided_at"])
    orphans = sorted(d for d, v in decisions.items()
                     if v["status"] == "superseded" and d not in {o for _, o in supersedes})
    if orphans:
        raise DocError(f"decisions marked superseded with no superseding decision: {orphans}")
    for (rel, _, dst_label), rows in b.edges.items():
        if rel == "CITES" and dst_label == "Doc":
            missing = sorted(r["dst"] for r in rows if r["dst"] not in doc_ids)
            if missing:
                raise DocError(f"CITES points at unknown docs: {missing}")
    return b
