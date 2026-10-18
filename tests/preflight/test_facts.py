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


def test_code_constants_are_literals_only():
    from faultline.preflight.facts import constants

    src = """const CLIENT_TIMEOUT_MS = 2000;
export const retries: number = 2;
TIMEOUT = 2 * 1000
x = foo(bar=3)
if x == 3:
ENABLED = True  # on
name := "payments"
private static final int MAX_POOL = 50;
val cacheTtl = 30
"""
    assert constants(src) == {"CLIENT_TIMEOUT_MS": 2000, "retries": 2, "ENABLED": True, "name": "payments",
                              "MAX_POOL": 50, "cacheTtl": 30}            # computed values and calls are never read


def test_a_code_constant_takes_the_decisions_rule_key():
    from faultline.preflight.facts import ChangedFile, extract

    f = [ChangedFile(path="svc/pay/client.py", before="CLIENT_TIMEOUT_MS = 2000\nPOOL = 4\n",
                     after="CLIENT_TIMEOUT_MS = 8000\nPOOL = 4\nNEW_FLAG = true\n")]
    facts, notes = extract(f, {"svc/pay/client.py": "payment"}, {"payment": ["payment.client.timeout_ms"]})
    assert {(x.key, x.value) for x in facts} == {("payment.client.timeout_ms", 8000), ("payment.NEW_FLAG", True)}
    assert "2 literal constant(s) changed" in notes[0]
    facts, notes = extract(f, {}, {})
    assert facts == [] and "not mapped to a component" in notes[0]
