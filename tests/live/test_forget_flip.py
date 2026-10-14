"""Live (M17 W2.4): forgetting a document changes the answer to the same question, asked before and after, and the
question is asked on throwaway copies so the forget token (bound to relationship counts) stays valid."""

import uuid

import pytest

from faultline import api
from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.memory import forget

pytestmark = pytest.mark.live


def test_same_question_before_and_after_forgetting_a_decision():
    db = client.engine()
    room = f"eval_acme_flip_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", room)
    try:
        dry = forget.dry_run("acme", "doc-adr-009", graph=room)
        q = api._forget_question(dry["doc"])
        before = api._ask_on_copy("acme", room, q)
        assert forget.dry_run("acme", "doc-adr-009", graph=room)["token"] == dry["token"]   # asking did not touch the room
        forget.execute("acme", "doc-adr-009", dry["token"], "p-030", graph=room)
        flip = api._flip(before, api._ask_on_copy("acme", room, q), q)
        assert "ADR-009" in before["citations"] and "ADR-009" in flip["no_longer_cited"] and flip["answer_changed"]
    finally:
        gcopy.delete_if_exists(db, room)
