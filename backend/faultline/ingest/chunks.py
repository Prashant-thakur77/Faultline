"""Document text as searchable chunks (track T3: the company brain reads what the documents SAY, not only their titles).

Every `(:Doc)` already in the graph (ADRs, runbooks, incident-channel chats, issues) points at its file (`url`). Its
body (front matter removed) is split into paragraph chunks of at most `MAX_CHARS` characters, each written as
`(:Chunk {id: "<doc>#c<n>", doc, ord, text, digest, embedding})-[:PART_OF]->(:Doc)`, with a `vecf32` embedding (the
same local model as every other vector) and the Chunk full-text and vector indexes of schema.cypher. Q-KNOW-1 then
searches them by meaning and by words in one query, fused by reciprocal rank inside the engine.

Applied by scripts/seed.py AFTER the bundle, the derived runbooks and the policies (idempotent MERGE through
graph/writes.py), on a new or a reused golden graph alike, so no existing node or edge id moves (some algorithms break
ties by id) and the eval graphs keep every number they had. A chunk is derived data: its digest is the text's sha256,
and chunks of a document that shrank are removed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MAX_CHARS = 600          # one or two paragraphs: a citable passage, small enough for a precise embedding
MIN_CHARS = 40           # a heading or a one-word line is merged into the next paragraph


def body(md: str) -> str:
    """The markdown body without its YAML front matter."""
    m = re.match(r"^---\n.*?\n---\n", md, re.S)
    return md[m.end():] if m else md


def chunk_text(md: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Paragraphs (blank-line separated) with markdown emphasis removed; headings and short lines lead the next
    paragraph, long ones are split at sentence ends. Deterministic."""
    raw = [p for p in re.split(r"\n\s*\n", body(md)) if p.strip()]
    # a heading: a `#` line, or a line that is bold from end to end (the transcripts' "**Synthetic … (excerpt).**")
    paras = [(p.lstrip().startswith("#") or bool(re.fullmatch(r"\s*\*\*[^*]+\*\*\s*", p)),
              re.sub(r"\s+", " ", re.sub(r"[*_`#>]+", "", p)).strip()) for p in raw]
    out: list[str] = []
    carry = ""
    for heading, p in paras:
        p = f"{carry} {p}".strip() if carry else p
        carry = ""
        if heading or len(p) < MIN_CHARS:   # a heading or a short line leads the next paragraph
            carry = p
            continue
        while len(p) > max_chars:
            cut = max(p.rfind(". ", 0, max_chars), p.rfind("; ", 0, max_chars))
            cut = cut + 1 if cut > MIN_CHARS else max_chars
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    if carry:
        if out:
            out[-1] = f"{out[-1]} {carry}"
        else:
            out.append(carry)
    return out


def rows(docs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """[(doc id, file path relative to the repo)] → chunk rows with embeddings. A missing file fails loudly."""
    from ..memory.embed import embed

    out: list[dict[str, Any]] = []
    for doc, url in sorted(docs):
        path = ROOT / url
        if not path.is_file():
            raise FileNotFoundError(f"Doc {doc} points at {url}, which does not exist")
        for i, text in enumerate(chunk_text(path.read_text())):
            out.append({"id": f"{doc}#c{i}", "doc": doc, "ord": i, "text": text,
                        "digest": hashlib.sha256(text.encode()).hexdigest()})
    if out:
        for r, v in zip(out, embed([r["text"] for r in out])):
            r["v"] = v
    return out


def apply(g, tenant: str) -> dict[str, int]:
    """Chunk every Doc of graph `g` (read through the RO wrapper, Q-DOC-URLS) and write the chunks (graph/writes)."""
    from ..graph import writes
    from ..graph.ro import RO

    res = RO(tenant, g.name).run("Q-DOC-URLS", {})
    if res.truncated:   # never chunk a silent subset of the documents
        raise RuntimeError(f"{g.name} has more documents than Q-DOC-URLS returns; page the read before chunking")
    docs = [(r["id"], r["url"]) for r in res.rows]
    rs = rows(docs)
    return {"docs": len(docs), "chunks": writes.upsert_chunks(g, rs, docs=[d for d, _ in docs])}


__all__ = ["MAX_CHARS", "apply", "body", "chunk_text", "rows"]
