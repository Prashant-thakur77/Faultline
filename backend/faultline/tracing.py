"""Optional OpenTelemetry / Arize Phoenix tracing for the incident lifecycle.

One Faultline investigation should read as ONE trace: report → graph discovery (FalkorDB) →
lineage → hypotheses → evidence → root-cause gate → repair → execution →
verification → git artifact → graph write-back.

Design constraints:

* **Entirely optional.** Without the `tracing` extra installed, or with
  `FAULTLINE_TRACING=false`, every helper here is a no-op context manager and the
  product behaves exactly as before. No import of this module may fail.
* **Self-hosted.** Points at a local Phoenix collector; no cloud credentials.
* **No secrets.** We record stage names, counts, durations, and deterministic
  verification outcomes — never the API key, never raw row data.

Enable:  pip install -e '.[tracing]'  &&  phoenix serve   (UI on :6006)
         FAULTLINE_TRACING=true  in .env
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger(__name__)

_state: dict[str, Any] = {"provider": None, "tracer": None, "enabled": None}

# OpenInference span kinds we use (string values, so the module imports even
# without the package installed).
CHAIN = "CHAIN"
AGENT = "AGENT"
TOOL = "TOOL"
LLM = "LLM"
_SPAN_KIND_ATTR = "openinference.span.kind"


def enabled() -> bool:
    """True only when explicitly switched on AND the packages import cleanly."""
    if _state["enabled"] is not None:
        return bool(_state["enabled"])
    if os.getenv("FAULTLINE_TRACING", "").lower() not in ("1", "true", "yes"):
        _state["enabled"] = False
        return False
    try:
        from phoenix.otel import register

        endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
        provider = register(
            project_name=os.getenv("PHOENIX_PROJECT_NAME", "faultline"),
            endpoint=endpoint,
            batch=True,
            auto_instrument=False,
            verbose=False,
        )
        try:  # instrument the Anthropic SDK so model calls nest inside our spans
            from openinference.instrumentation.anthropic import AnthropicInstrumentor

            AnthropicInstrumentor().instrument(tracer_provider=provider)
        except Exception as e:  # tracing still useful without LLM auto-instrumentation
            log.debug("anthropic instrumentation unavailable: %s", e)
        _state["provider"] = provider
        _state["tracer"] = provider.get_tracer("faultline")
        _state["enabled"] = True
    except Exception as e:
        log.info("tracing disabled (%s: %s)", type(e).__name__, e)
        _state["enabled"] = False
    return bool(_state["enabled"])


def _tracer():
    return _state["tracer"] if enabled() else None


@contextmanager
def span(name: str, kind: str = CHAIN, **attributes: Any) -> Iterator[Any]:
    """A span, or a transparent no-op when tracing is off.

    Yields an object with `.set_attribute()` in both modes so callers never
    branch on whether tracing is enabled.
    """
    tracer = _tracer()
    cm = None
    sp: Any = _NullSpan()
    if tracer is not None:
        # Only span *creation* is guarded. Body exceptions must propagate
        # untouched — swallowing them here (or yielding twice) would both
        # corrupt the contextmanager protocol and hide real failures.
        try:
            cm = tracer.start_as_current_span(name)
            sp = cm.__enter__()
            sp.set_attribute(_SPAN_KIND_ATTR, kind)
            for k, v in attributes.items():
                if v is not None:
                    sp.set_attribute(k, _safe(v))
        except Exception:
            cm, sp = None, _NullSpan()

    if cm is None:
        yield sp  # exactly one yield on this path
        return

    try:
        yield sp
    except Exception as e:
        try:
            from opentelemetry.trace import Status, StatusCode

            sp.set_status(Status(StatusCode.ERROR, str(e)[:200]))
            sp.record_exception(e)
        except Exception:
            pass
        try:
            cm.__exit__(type(e), e, e.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass


def capture_context() -> Any:
    """Grab the current OTel context so a worker thread can continue this trace.

    FastAPI hands the investigation to a background thread; without this the
    worker's spans would be orphaned into a separate trace.
    """
    if not enabled():
        return None
    try:
        from opentelemetry import context as otel_context

        return otel_context.get_current()
    except Exception:
        return None


@contextmanager
def continue_context(token: Any) -> Iterator[None]:
    """Re-attach a captured context inside the worker thread."""
    if token is None or not enabled():
        yield
        return
    try:
        from opentelemetry import context as otel_context

        attached = otel_context.attach(token)
        try:
            yield
        finally:
            otel_context.detach(attached)
    except Exception:
        yield


def annotate(**attributes: Any) -> None:
    """Attach deterministic facts (gate passed, N/N invariants, KPI ratio) to the
    current span."""
    if not enabled():
        return
    try:
        from opentelemetry import trace

        sp = trace.get_current_span()
        for k, v in attributes.items():
            if v is not None:
                sp.set_attribute(k, _safe(v))
    except Exception:
        pass


def shutdown() -> None:
    """Flush pending spans (batch exporter) at process end or after a run."""
    provider = _state.get("provider")
    if provider is not None:
        try:
            provider.force_flush()
        except Exception:
            pass


def _safe(v: Any) -> Any:
    if isinstance(v, (str, bool, int, float)):
        return v
    return str(v)[:500]


class _NullSpan:
    def set_attribute(self, *_a, **_k) -> None: ...
    def set_status(self, *_a, **_k) -> None: ...
    def record_exception(self, *_a, **_k) -> None: ...
    def add_event(self, *_a, **_k) -> None: ...
