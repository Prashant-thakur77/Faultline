"""GraphRAG-SDK arm, the worker. It runs ONLY in the isolated SDK venv (tmp/graphrag_sdk/venv, built by
scripts/graphrag_sdk_venv.sh) and is driven by evals/graphrag_sdk_arm.py, which grades its answers.

It never sees a truth file: it gets the corpus directory (a manifest plus text documents) and a question file holding
only ids and question texts. Everything the SDK knows lives in FalkorDB, in its own fresh graph (and the SDK's
`<graph>__ontology` side graph), which this worker deletes before it exits.

Modes:
  estimate  chunk the corpus with the SDK's own default chunker and estimate tokens and US$ (no API call, no graph)
  smoke     the whole SDK pipeline against the pinned engine with a stub model (no API call, no spend) on a throwaway
            graph, to catch engine incompatibilities before any paid call
  run       ingest the corpus, finalize, answer every question with `completion()`; a hard spend cap

Spend guard (run): every model call goes through litellm.acompletion, which is wrapped. Before a call, its worst case
(input estimated at 2.5 characters per token, plus max_tokens of output) is reserved; a call whose reservation would
take spent + reserved past the cap is refused and never sent. After a call, the real usage from the response is
added. So real spend can never pass the cap. Before each question set and each question, the projected cost of the
rest of the set (mean real cost per question so far, x 1.25) must fit too, or the set stops there.

The Anthropic key comes from the process environment (ANTHROPIC_API_KEY, set by the caller). It is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

MODEL = "anthropic/claude-haiku-4-5"
MAX_TOKENS = 8192            # spend guard; litellm's default for this model is 64,000
PRICE_IN, PRICE_OUT = 1.00e-6, 5.00e-6   # claude-haiku-4-5, US$ per token (Anthropic price table)
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
CLAUDE_VS_CL100K = 1.25      # estimate only: Claude's tokenizer yields more tokens than tiktoken's cl100k
CHARS_PER_TOKEN_WORST = 2.5  # reservation only: deliberately pessimistic
BACKOFF_S = (5, 10, 20, 40, 60)   # transport retries on rate limit / overload / connection errors (not billed)


def _retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    code = getattr(exc, "status_code", None)
    return (name in ("RateLimitError", "InternalServerError", "ServiceUnavailableError", "APIConnectionError",
                     "Timeout", "APITimeoutError") or code in (429, 500, 502, 503, 529)
            or "overloaded" in str(exc).lower())


class BudgetRefused(Exception):
    """A model call that would have taken spend past the cap; it was never sent."""


class Meter:
    def __init__(self, cap: float) -> None:
        self.cap = cap
        self.spent = 0.0
        self.reserved = 0.0
        self.refused = 0
        self.truncated = 0
        self.retries = 0
        self.phase = "init"
        self.calls: list[dict] = []

    def _worst(self, kw: dict) -> float:
        chars = sum(len(str(m.get("content", ""))) for m in kw.get("messages", []))
        return chars / CHARS_PER_TOKEN_WORST * PRICE_IN + int(kw.get("max_tokens") or MAX_TOKENS) * PRICE_OUT

    def _record(self, resp, t0: float) -> None:
        u = getattr(resp, "usage", None)
        tin = int(getattr(u, "prompt_tokens", 0) or 0)
        tout = int(getattr(u, "completion_tokens", 0) or 0)
        cost = tin * PRICE_IN + tout * PRICE_OUT
        self.spent += cost
        fr = None
        try:
            fr = resp.choices[0].finish_reason
        except Exception:  # noqa: BLE001 - a malformed response is still billed; keep counting
            pass
        if fr == "length":
            self.truncated += 1
        self.calls.append({"phase": self.phase, "in": tin, "out": tout, "usd": round(cost, 6),
                           "ms": round((time.perf_counter() - t0) * 1000, 1), "finish": fr})

    def wrap(self, litellm) -> None:
        orig_async, orig_sync = litellm.acompletion, litellm.completion
        meter = self

        async def acompletion(**kw):
            w = meter._worst(kw)
            if meter.spent + meter.reserved + w > meter.cap:
                meter.refused += 1
                raise BudgetRefused(f"refused: spent {meter.spent:.4f} + reserved {meter.reserved:.4f} + worst {w:.4f} "
                                    f"> cap {meter.cap:.2f}")
            meter.reserved += w
            t0 = time.perf_counter()
            try:
                for attempt in range(len(BACKOFF_S) + 1):
                    try:
                        resp = await orig_async(**kw)
                        break
                    except Exception as exc:  # noqa: BLE001 - only transport errors are retried, the rest re-raised
                        if attempt < len(BACKOFF_S) and _retryable(exc):
                            meter.retries += 1
                            await asyncio.sleep(BACKOFF_S[attempt])
                            continue
                        raise
            finally:
                meter.reserved -= w
            meter._record(resp, t0)
            return resp

        def completion(**kw):
            w = meter._worst(kw)
            if meter.spent + meter.reserved + w > meter.cap:
                meter.refused += 1
                raise BudgetRefused("refused (sync call)")
            t0 = time.perf_counter()
            resp = orig_sync(**kw)
            meter._record(resp, t0)
            return resp

        litellm.acompletion, litellm.completion = acompletion, completion

    def phase_sum(self, prefix: str, exact: bool = False) -> dict:
        xs = [c for c in self.calls if (c["phase"] == prefix if exact else c["phase"].startswith(prefix))]
        return {"calls": len(xs), "in": sum(c["in"] for c in xs), "out": sum(c["out"] for c in xs),
                "usd": round(sum(c["usd"] for c in xs), 6)}


class LogTap(logging.Handler):
    """Keeps the SDK's warnings (a failed extraction step falls back silently otherwise)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append({"logger": record.name, "level": record.levelname, "msg": record.getMessage()[:500]})


def _embedder(cache_dir: str):
    from fastembed import TextEmbedding
    from graphrag_sdk import Embedder

    class LocalEmbedder(Embedder):
        """The SDK's documented extension point: a local model (no API key), the one Faultline itself uses."""

        def __init__(self) -> None:
            self._m = TextEmbedding(EMBED_MODEL, cache_dir=cache_dir)

        @property
        def model_name(self) -> str:
            return f"fastembed/{EMBED_MODEL}"

        def embed_query(self, text: str, **kwargs) -> list[float]:
            return [float(x) for x in next(iter(self._m.embed([text])))]

        def embed_documents(self, texts: list[str], **kwargs) -> list[list[float]]:
            return [[float(x) for x in v] for v in self._m.embed(list(texts))]

    return LocalEmbedder()


def _corpus(corpus_dir: Path) -> list[dict]:
    man = json.loads((corpus_dir / "manifest.json").read_text())
    return [{**d, "text": (corpus_dir / d["file"]).read_text()} for d in man["docs"]]


# ------------------------------------------------------------------ estimate (no API, no graph)
async def estimate(corpus_dir: Path, questions: list[dict]) -> dict:
    import tiktoken
    from graphrag_sdk import Context
    from graphrag_sdk.ingestion.chunking_strategies.sentence_token_cap import SentenceTokenCapChunking
    from graphrag_sdk.ingestion.extraction_strategies.entity_extractors import DEFAULT_ENTITY_TYPES
    from graphrag_sdk.ingestion.extraction_strategies.graph_extraction import (
        _DEFAULT_JSON_EXAMPLE, VERIFY_EXTRACT_RELS_PROMPT)

    enc = tiktoken.get_encoding("cl100k_base")
    chunker = SentenceTokenCapChunking()   # the SDK's default for ingest()
    template = VERIFY_EXTRACT_RELS_PROMPT.format(entity_types=", ".join(DEFAULT_ENTITY_TYPES), relation_patterns="",
                                                 attribute_block="", relationship_type_instruction="",
                                                 entities_json="", text="", json_example=_DEFAULT_JSON_EXAMPLE)
    t_tmpl = len(enc.encode(template))
    docs, chunks_total, tin, tout = [], 0, 0, 0
    for d in _corpus(corpus_dir):
        ch = await chunker.chunk(d["text"], Context())
        toks = [len(enc.encode(c.text)) for c in ch.chunks]
        # step 2 input: template + chunk + the step-1 entities as JSON (about 1.5x the chunk on dense fact text);
        # output: verified entities with descriptions + relationships with descriptions (about 5x the chunk)
        d_in = sum(t_tmpl + t + int(1.5 * t) for t in toks)
        d_out = sum(min(MAX_TOKENS, 5 * t) for t in toks)
        docs.append({"id": d["id"], "chunks": len(toks), "tokens": sum(toks)})
        chunks_total += len(toks)
        tin += d_in
        tout += d_out
    tin, tout = int(tin * CLAUDE_VS_CL100K), int(tout * CLAUDE_VS_CL100K)
    ingest_usd = tin * PRICE_IN + tout * PRICE_OUT
    # one question = a keyword call (~120 in, ~40 out) + completion: system prompt + up to 15 passages (chunk_top_k) of
    # this corpus's mean chunk size + entity / relationship / fact sections (~2,500) + the question; ~300 out
    mean_chunk = min(512, sum(d["tokens"] for d in docs) / max(1, chunks_total))
    q_in = int((120 + 300 + 15 * mean_chunk + 2500) * CLAUDE_VS_CL100K)
    q_out = int((40 + 300) * CLAUDE_VS_CL100K)
    per_q = q_in * PRICE_IN + q_out * PRICE_OUT
    by_set: dict[str, int] = {}
    for q in questions:
        by_set[q["set"]] = by_set.get(q["set"], 0) + 1
    return {"docs": docs, "chunks": chunks_total, "ingest": {"in": tin, "out": tout, "usd": round(ingest_usd, 4)},
            "per_question": {"in": q_in, "out": q_out, "usd": round(per_q, 5)},
            "sets": {s: {"questions": n, "usd": round(n * per_q, 4)} for s, n in by_set.items()},
            "mean_chunk_tokens": round(mean_chunk, 1),
            "assumptions": {"claude_vs_cl100k": CLAUDE_VS_CL100K, "step2_in": "template + chunk + 1.5x chunk",
                            "step2_out": "5x chunk", "price_in": PRICE_IN, "price_out": PRICE_OUT}}


# ------------------------------------------------------------------ smoke (stub model, no spend)
def _stub_litellm(litellm) -> None:
    """Replace the model with canned replies shaped like the real ones; usage is reported as zero."""
    import re

    def reply(messages: list[dict]) -> str:
        text = "\n".join(str(m.get("content", "")) for m in messages)
        if "expert knowledge graph builder" in text:
            body = text.split("## Text", 1)[-1]
            names = sorted(set(re.findall(r"\b(ADR-\d+|p-\d{3}|team-[a-z]+)\b", body)))[:4] or ["ADR-021"]
            ents = [{"name": n, "type": "Concept", "description": f"{n} as named in the text."} for n in names]
            rels = [{"source": names[0], "target": n, "type": "RELATED_TO", "description": f"{names[0]} relates to {n}.",
                     "span_start": 0, "span_end": 10} for n in names[1:]]
            return json.dumps({"entities": ents, "relationships": rels})
        if "Extract ALL proper nouns" in text:
            return "ADR-021, team-catalog"
        return "stub answer naming ADR-021"

    async def acompletion(**kw):
        return litellm.ModelResponse(choices=[{"index": 0, "finish_reason": "stop",
                                               "message": {"role": "assistant", "content": reply(kw["messages"])}}],
                                     usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    def completion(**kw):
        raise RuntimeError("smoke: no sync model calls expected")

    litellm.acompletion, litellm.completion = acompletion, completion


# ------------------------------------------------------------------ the pipeline (smoke and run)
def _graph_names(host: str, port: int) -> list[str]:
    from falkordb import FalkorDB

    return list(FalkorDB(host=host, port=port).list_graphs())


def _delete_graphs(host: str, port: int, names: list[str]) -> dict:
    from falkordb import FalkorDB

    db = FalkorDB(host=host, port=port)
    out = {}
    for n in names:
        if n in db.list_graphs():
            db.select_graph(n).delete()
        out[n] = n not in db.list_graphs()
    return out


async def _kg_stats(rag) -> dict:
    q = rag._graph_store.query_raw
    labels = (await q("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) ORDER BY l")).result_set
    rels = (await q("MATCH ()-[e]->() RETURN type(e), count(*) ORDER BY type(e)")).result_set
    return {"labels": {str(a): int(b) for a, b in labels}, "relationships": {str(a): int(b) for a, b in rels}}


def _write(path: Path, out: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, default=str) + "\n")
    tmp.replace(path)


async def pipeline(a, questions: list[dict], smoke: bool) -> dict:
    import litellm
    from graphrag_sdk import ConnectionConfig, GraphExtraction, GraphRAG, LiteLLM, __version__

    litellm.suppress_debug_info = True
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    tap = LogTap()
    logging.getLogger().addHandler(tap)
    meter = Meter(a.cap)
    if smoke:
        _stub_litellm(litellm)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("run: ANTHROPIC_API_KEY is not set in the environment")
        meter.wrap(litellm)

    graphs = [a.graph, f"{a.graph}__ontology"]
    present = [g for g in graphs if g in _graph_names(a.host, a.port)]
    if present:
        raise SystemExit(f"refusing: graph(s) {present} already exist; the SDK's graph must be created fresh")
    out_path = Path(a.out)
    out: dict = {"mode": "smoke" if smoke else "run", "sdk_version": __version__, "model": MODEL,
                 "max_tokens": MAX_TOKENS, "temperature": 0.0, "embedder": f"fastembed/{EMBED_MODEL}",
                 "embedding_dimension": EMBED_DIM, "graph": a.graph, "cap_usd": a.cap, "started": time.time(),
                 "ingest": {"docs": []}, "answers": [], "stopped": None}
    contexts: list[dict] = []
    llm = LiteLLM(MODEL, max_tokens=MAX_TOKENS)
    rag = GraphRAG(connection=ConnectionConfig(host=a.host, port=a.port, graph_name=a.graph), llm=llm,
                   embedder=_embedder(a.embed_cache), embedding_dimension=EMBED_DIM)
    # The SDK's default extractor (what ingest() builds when none is passed, with no ontology): GLiNER step 1 + the LLM
    # verify/relationship step 2. Built ONCE and passed to every ingest(): left to the SDK, every ingest() call builds a
    # new GLiNERExtractor and reloads the ~800 MB model, and memory grows per document until the process is killed.
    extractor = GraphExtraction(llm=llm)
    try:
        # ---- ingestion: every document, in manifest order, with the SDK's default strategies
        t_ing = time.perf_counter()
        n_q = {}
        for q in questions:
            n_q[q["set"]] = n_q.get(q["set"], 0) + 1
        first_set_usd = a.est_per_question * (n_q[questions[0]["set"]] if questions else 0)
        chunks_done = 0
        for d in _corpus(Path(a.corpus)):
            meter.phase = f"ingest:{d['id']}"
            t0 = time.perf_counter()
            err = None
            try:
                r = await rag.ingest(text=d["text"], document_id=d["id"], extractor=extractor)
                res = r.model_dump() if hasattr(r, "model_dump") else dict(vars(r))
            except Exception as exc:  # noqa: BLE001 - recorded; a failed document invalidates the run below
                err, res = f"{type(exc).__name__}: {exc}"[:500], {}
            out["ingest"]["docs"].append({"id": d["id"], "s": round(time.perf_counter() - t0, 2), "error": err,
                                          "result": res, **meter.phase_sum(f"ingest:{d['id']}")})
            _write(out_path, {**out, "meter": {"spent": meter.spent, "refused": meter.refused}})
            if err or meter.refused:
                out["stopped"] = f"ingestion: {err or 'budget guard refused a call'}"
                return out
            # projection: the rest of ingestion at the real cost per chunk so far, plus the first question set
            chunks_done += int((res or {}).get("chunks_indexed") or 0)
            if not smoke and chunks_done and a.chunks_total:
                ing = meter.phase_sum("ingest:")["usd"]
                proj = meter.spent + ing / chunks_done * max(0, a.chunks_total - chunks_done) + first_set_usd
                out["ingest"]["projection_usd"] = round(proj, 4)
                if proj > a.cap:
                    out["stopped"] = f"ingestion: projection {proj:.4f} (rest of ingestion + first set) > cap {a.cap}"
                    return out
        meter.phase = "finalize"
        t0 = time.perf_counter()
        fin = await rag.finalize()
        out["ingest"]["finalize"] = {"s": round(time.perf_counter() - t0, 2),
                                     "result": fin.model_dump() if hasattr(fin, "model_dump") else dict(vars(fin)),
                                     **meter.phase_sum("finalize")}
        out["ingest"]["seconds"] = round(time.perf_counter() - t_ing, 2)
        out["ingest"]["cost"] = meter.phase_sum("ingest:")
        out["kg"] = await _kg_stats(rag)
        _write(out_path, {**out, "meter": {"spent": meter.spent, "refused": meter.refused}})

        # ---- questions, one set after another. Projection = spent + (mean real cost per answered question, or the
        # estimate before the first answer) x questions left; it must fit under the cap before each set and question.
        def per_question() -> float:
            done = [x["usd"] for x in out["answers"] if x.get("usd") is not None and not x.get("error")]
            return statistics.fmean(done) if done else a.est_per_question

        sets: list[str] = list(dict.fromkeys(q["set"] for q in questions))
        for s in sets:
            qs = [q for q in questions if q["set"] == s]
            proj = meter.spent + per_question() * len(qs)
            if not smoke and proj > a.cap:
                out.setdefault("skipped_sets", []).append({"set": s, "projection_usd": round(proj, 4), "cap": a.cap})
                continue
            for q in qs:
                left = len(qs) - sum(1 for x in out["answers"] if x["set"] == s)
                proj = meter.spent + per_question() * left
                if not smoke and proj > a.cap:
                    out["stopped"] = f"set {s}: projection {proj:.4f} > cap {a.cap} with {left} questions left"
                    return out
                meter.phase = f"q:{s}:{q['id']}"
                t0 = time.perf_counter()
                row = {"set": s, "id": q["id"], "q": q["q"]}
                try:
                    r = await rag.completion(q["q"], return_context=True)
                    row["answer"] = r.answer
                    items = r.retriever_result.items if r.retriever_result else []
                    row["context_items"] = len(items)
                    row["context_sections"] = [str((it.metadata or {}).get("section", "")) for it in items]
                    contexts.append({"set": s, "id": q["id"], "items": [{"section": (it.metadata or {}).get("section"),
                                                                         "content": it.content} for it in items]})
                except Exception as exc:  # noqa: BLE001 - recorded as an error answer, graded as wrong
                    row["answer"], row["error"] = "", f"{type(exc).__name__}: {exc}"[:500]
                row["ms"] = round((time.perf_counter() - t0) * 1000, 1)
                row.update(meter.phase_sum(meter.phase, exact=True))
                out["answers"].append(row)
                _write(out_path, {**out, "meter": {"spent": meter.spent, "refused": meter.refused}})
                if meter.refused:
                    out["stopped"] = "budget guard refused a call"
                    return out
        return out
    finally:
        out["finished"] = time.time()
        out["meter"] = {"spent_usd": round(meter.spent, 6), "refused": meter.refused, "truncated": meter.truncated,
                        "transport_retries": meter.retries,
                        "calls": len(meter.calls), "in": sum(c["in"] for c in meter.calls),
                        "out": sum(c["out"] for c in meter.calls)}
        out["calls"] = meter.calls
        out["warnings"] = tap.records[:400]
        out["warning_count"] = len(tap.records)
        try:
            await rag.close()
        except Exception:  # noqa: BLE001 - closing must not mask the result
            pass
        out["graphs_deleted"] = _delete_graphs(a.host, a.port, graphs)
        import resource

        out["maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        if contexts and a.contexts:
            with gzip.open(a.contexts, "wt") as f:
                json.dump(contexts, f)
        _write(out_path, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["estimate", "smoke", "run"])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--contexts", default="")
    ap.add_argument("--graph", default="graphrag_acme")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--cap", type=float, default=0.0)
    ap.add_argument("--est-per-question", type=float, default=0.02)
    ap.add_argument("--chunks-total", type=int, default=0, help="the corpus's chunk count (from estimate)")
    ap.add_argument("--embed-cache", default="")
    a = ap.parse_args()
    questions = json.loads(Path(a.questions).read_text())
    if a.mode == "estimate":
        _write(Path(a.out), asyncio.run(estimate(Path(a.corpus), questions)))
        return 0
    if a.mode == "smoke":
        a.cap = 0.0
        os.environ.pop("ANTHROPIC_API_KEY", None)
    elif a.cap <= 0:
        raise SystemExit("run needs --cap > 0")
    out = asyncio.run(pipeline(a, questions, smoke=a.mode == "smoke"))
    print(json.dumps({"mode": out["mode"], "stopped": out["stopped"], "answers": len(out["answers"]),
                      "spent_usd": out["meter"]["spent_usd"], "refused": out["meter"]["refused"],
                      "warnings": out["warning_count"], "graphs_deleted": out["graphs_deleted"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
