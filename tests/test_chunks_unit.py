"""Document chunking (ingest/chunks.py) and the knowledge search's full-text query (mcp_server/tools.py)."""

from faultline.ingest.chunks import MAX_CHARS, chunk_text
from faultline.mcp_server.tools import _kq_query

MD = """---
id: ADR-1
title: x
---
# ADR-1: A heading

**Synthetic transcript (excerpt).**

First paragraph is long enough to stand on its own as a passage of text.

Short.

""" + "A sentence that keeps going. " * 40


def test_headings_lead_and_long_text_splits_at_sentences():
    cs = chunk_text(MD)
    assert cs[0].startswith("ADR-1: A heading Synthetic transcript (excerpt). First paragraph")
    assert all(len(c) <= MAX_CHARS for c in cs)
    assert all(c.endswith(".") for c in cs[1:])
    assert "id: ADR-1" not in " ".join(cs)          # front matter never becomes text
    assert chunk_text(MD) == cs                    # deterministic


def test_knowledge_query_keeps_topic_words_only():
    assert _kq_query("What happens when the confirmation email provider is down?") == \
        "happens* | confirmation* | email* | provider* | down*"
    assert _kq_query("what is the of") == ""
    assert _kq_query("api SLO for the ad service") == "api | slo | service*"
