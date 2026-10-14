"""Unit (no engine): the context pack's packing rule (M16.1)."""

from faultline.mcp_server.tools import _ctx_item, pack_items


def test_pack_takes_the_highest_ranked_items_that_fit_in_rank_order():
    pool = [_ctx_item("similar", "s" * 400, ["x"], (5, 0, "x"), "T"),     # 100 tokens, lowest tier
            _ctx_item("change", "c" * 80, ["D-1"], (1, 0, "D-1"), "T"),    # 20 tokens
            _ctx_item("path", "p" * 2000, ["D-1"], (2, 0, "D-1"), "T"),    # 500 tokens: does not fit, is skipped
            _ctx_item("alert", "a" * 8, ["s"], (0, 0, "s"), "T")]          # 2 tokens
    got = pack_items(pool, 150)
    assert [it["kind"] for it in got] == ["alert", "change", "similar"]
    assert sum(it["tokens"] for it in got) <= 150
    assert pack_items(pool, 1) == []


def test_items_count_tokens_as_characters_over_four_and_dedupe_ids():
    it = _ctx_item("change", "x" * 9, ["b", "a", "a", None], (1, 0, "a"), "Q-SUS-1")
    assert it["tokens"] == 3 and it["ids"] == ["a", "b"] and it["template"] == "Q-SUS-1"
