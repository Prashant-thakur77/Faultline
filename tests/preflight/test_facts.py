"""Unit: deterministic ChangeFact extraction and the PR comment policy."""

import json

import pytest

from faultline.preflight.comment import exit_code, render
from faultline.preflight.facts import ChangedFile, extract, flatten


def test_flatten_and_extract_changed_keys():
    before = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}, "x": [1]})
    after = json.dumps({"client": {"timeout_ms": 5000}, "x": [1]})
    facts, notes = extract([ChangedFile(path="src/payment/config.json", before=before, after=after)],
                           {"src/payment/config.json": "payment"})
    got = {f.key: f.value for f in facts}
    assert got == {"payment.client.timeout_ms": 5000, "payment.client.retries": None} and not notes
    assert flatten({"a": {"b": 1}}) == {"a.b": 1}


def test_unmapped_or_bad_config_is_noted_not_guessed():
    facts, notes = extract([ChangedFile(path="conf/x.yaml", before="a: 1", after="a: 2"),
                            ChangedFile(path="src/p/c.json", before="{", after="{}")], {"src/p/c.json": "p"})
    assert facts == [] and len(notes) == 2


def test_paths_must_be_repo_relative():
    with pytest.raises(ValueError):
        ChangedFile(path="../etc/passwd", after="x")


def test_comment_is_quiet_on_allow():
    base = {"pr": "pr:o/r#1", "risk": 0.1, "terms": {}, "evidence": {"evidence_id": "ev", "template": "T"}}
    assert render({**base, "verdict": "allow"}) is None
    assert exit_code({**base, "verdict": "block"}) == 1 and exit_code({**base, "verdict": "require_review"}) == 0


def test_hostile_configs_are_refused_not_expanded():
    """Review round 4 (B2): the anonymous preflight must survive a YAML alias bomb, deep nesting and huge lists."""
    import time

    from faultline.preflight.facts import ChangedFile, extract

    bomb = "a: &a [x,x,x,x,x,x,x,x,x,x]\\n" + "".join(
        f"{c}: &{c} [{','.join(['*' + p] * 10)}]\\n" for p, c in zip("abcdefgh", "bcdefghi"))
    deep = "{" * 5000 + "}" * 5000
    many = "{" + ",".join(f'"k{i}": {i}' for i in range(6000)) + "}"
    for path, text in (("svc/config.yaml", bomb), ("svc/config.json", deep), ("svc/config.json", many)):
        t0 = time.perf_counter()
        facts, notes = extract([ChangedFile(path=path, before=None, after=text)], {path: "payment"})
        assert facts == [] and "unparseable config" in notes[0], notes
        assert time.perf_counter() - t0 < 2.0
    ok, _ = extract([ChangedFile(path="svc/config.yaml", before="a: 1\\n", after="a: 2\\n")], {"svc/config.yaml": "payment"})
    assert [f.key for f in ok] == ["payment.a"]                       # ordinary configs still work
