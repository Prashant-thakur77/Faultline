"""Stored payloads are always valid JSON, however large the tool result (writes.capped_json). Cutting the JSON text at
a fixed length once stored an unterminated string and broke every read of that run's plan."""

import json

from faultline.graph.writes import capped_json


def test_small_payload_is_unchanged_canonical_json():
    obj = {"b": 1, "a": [1, 2]}
    assert capped_json(obj, cap=100) == json.dumps(obj, sort_keys=True)


def test_large_rows_keep_a_prefix_that_fits_and_say_how_many_were_dropped():
    obj = {"template": "Q-X", "rows": [{"id": f"n{i}", "text": "x" * 50} for i in range(500)]}
    out = capped_json(obj, cap=2000)
    assert len(out) <= 2000
    back = json.loads(out)
    assert back["template"] == "Q-X"
    assert 0 < len(back["rows"]) < 500
    assert back["rows"] == obj["rows"][: len(back["rows"])]
    assert back["rows_truncated"] == 500 - len(back["rows"])


def test_anything_else_becomes_a_valid_marker():
    out = capped_json({"blob": "y" * 10_000}, cap=1000)
    back = json.loads(out)
    assert back["truncated"] is True and back["chars"] > 1000 and isinstance(back["head"], str)
    assert len(out) <= 1000
