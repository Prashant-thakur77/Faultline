"""Tracing must be invisible when off and transparent when on.

The bug these tests exist for: an early version of `span()` yielded twice on the
error path, so any exception raised inside a traced block surfaced as
`RuntimeError: generator didn't stop after throw()` — which took down a whole
investigation. Tracing is an observability layer; it must never alter control
flow.
"""

import pytest

from faultline import tracing


@pytest.fixture(autouse=True)
def _reset_tracing_state(monkeypatch):
    tracing._state.update({"provider": None, "tracer": None, "enabled": None})
    monkeypatch.delenv("FAULTLINE_TRACING", raising=False)
    yield
    tracing._state.update({"provider": None, "tracer": None, "enabled": None})


# ------------------------------------------------------------------ disabled


def test_disabled_by_default():
    assert tracing.enabled() is False


def test_all_helpers_are_no_ops_when_disabled():
    with tracing.span("x", kind=tracing.TOOL, a=1) as sp:
        sp.set_attribute("b", 2)
        sp.add_event("e")
    tracing.annotate(c=3)
    tracing.shutdown()
    assert tracing.capture_context() is None
    with tracing.continue_context(None):
        pass


def test_exceptions_propagate_unchanged_when_disabled():
    with pytest.raises(ValueError, match="boom"):
        with tracing.span("x"):
            raise ValueError("boom")


# ------------------------------------------------------------------- enabled


class _FakeSpan:
    def __init__(self):
        self.attributes, self.status, self.exceptions = {}, None, []

    def set_attribute(self, k, v):
        self.attributes[k] = v

    def set_status(self, s):
        self.status = s

    def record_exception(self, e):
        self.exceptions.append(e)


class _FakeCM:
    def __init__(self, span):
        self.span, self.exited = span, False

    def __enter__(self):
        return self.span

    def __exit__(self, *exc):
        self.exited = True
        return False


class _FakeTracer:
    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name):
        sp = _FakeSpan()
        sp.attributes["__name__"] = name
        self.spans.append(sp)
        return _FakeCM(sp)


def _enable(monkeypatch) -> _FakeTracer:
    tracer = _FakeTracer()
    tracing._state.update({"enabled": True, "tracer": tracer, "provider": None})
    return tracer


def test_span_records_kind_and_attributes(monkeypatch):
    tracer = _enable(monkeypatch)
    with tracing.span("tool.profile_column", kind=tracing.TOOL, **{"tool.name": "profile"}) as sp:
        sp.set_attribute("tool.result_chars", 42)
    rec = tracer.spans[0]
    assert rec.attributes["openinference.span.kind"] == "TOOL"
    assert rec.attributes["tool.name"] == "profile"
    assert rec.attributes["tool.result_chars"] == 42


def test_exception_propagates_and_is_recorded_when_enabled(monkeypatch):
    """The regression: the error path must re-raise the ORIGINAL exception."""
    tracer = _enable(monkeypatch)
    with pytest.raises(ValueError, match="kaboom"):
        with tracing.span("failing"):
            raise ValueError("kaboom")
    rec = tracer.spans[0]
    assert rec.exceptions and isinstance(rec.exceptions[0], ValueError)


def test_span_creation_failure_degrades_to_noop(monkeypatch):
    """A broken tracer must not break the traced code."""

    class _Broken:
        def start_as_current_span(self, name):
            raise RuntimeError("collector exploded")

    tracing._state.update({"enabled": True, "tracer": _Broken(), "provider": None})
    ran = []
    with tracing.span("x") as sp:
        sp.set_attribute("k", "v")
        ran.append(True)
    assert ran == [True]


def test_none_attributes_are_skipped(monkeypatch):
    tracer = _enable(monkeypatch)
    with tracing.span("x", present="yes", absent=None):
        pass
    assert "present" in tracer.spans[0].attributes
    assert "absent" not in tracer.spans[0].attributes
