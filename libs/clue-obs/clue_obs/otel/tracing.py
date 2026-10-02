"""The tracing wrapper (M0.5) — OpenTelemetry-shaped.

``traced_step(name, **attrs)`` opens a named span carrying the standard, redacted attributes. It is
the stable seam: every pipeline component calls it; the concrete OTel backend (and its exporter —
console for dev, OTLP to a collector, in-memory for tests) sits behind it and is swapped via
:func:`configure_tracing` without touching any caller.

We own a module-local ``TracerProvider`` (rather than the process-global one) so the exporter can be
reconfigured freely — notably by the test helper — without fighting OTel's set-the-global-once rule.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import ParamSpec, TypeVar

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Tracer

from clue_obs.otel.attributes import safe_attributes

_INSTRUMENTATION = "clue_research"

_provider: TracerProvider | None = None
_tracer: Tracer | None = None

P = ParamSpec("P")
R = TypeVar("R")


def configure_tracing(
    *, exporter: SpanExporter | None = None, console: bool = False
) -> TracerProvider:
    """(Re)configure the tracing backend behind the wrapper.

    With an ``exporter`` (or ``console=True``) spans are exported; with neither, spans are still
    created (and usable) but go nowhere — the safe library default. Returns the provider.
    """
    global _provider, _tracer
    provider = TracerProvider()
    chosen = exporter or (ConsoleSpanExporter() if console else None)
    if chosen is not None:
        provider.add_span_processor(SimpleSpanProcessor(chosen))
    _provider = provider
    _tracer = provider.get_tracer(_INSTRUMENTATION)
    return provider


def _get_tracer() -> Tracer:
    if _tracer is None:
        configure_tracing()
    assert _tracer is not None  # configure_tracing always sets it
    return _tracer


def use_provider(provider: TracerProvider) -> TracerProvider:
    """Make an externally built provider the one behind :func:`traced_step` (the process-root
    install, lane 3 slice 2), so our spans and the instrumentors' spans are one trace."""
    global _provider, _tracer
    _provider = provider
    _tracer = provider.get_tracer(_INSTRUMENTATION)
    return provider


def get_tracer() -> Tracer:
    """The tracer behind :func:`traced_step`, for callers that need a parent ``context``."""
    return _get_tracer()


@contextmanager
def traced_step(name: str, **attrs: object) -> Iterator[Span]:
    """Run a pipeline step inside a named span with the standard (redacted) attributes."""
    tracer = _get_tracer()
    with tracer.start_as_current_span(name) as span:
        apply_attributes(span, attrs)
        yield span


def apply_attributes(span: Span, attrs: Mapping[str, object]) -> None:
    """Set redacted, OTel-coerced attributes on an **already-open** span.

    The post-hoc analogue of :func:`traced_step`'s open-time handling, for attributes only known
    after the step runs (e.g. a gateway call's token usage / cost). Routes through
    :func:`~clue_obs.otel.attributes.safe_attributes` so *every* attribute — whenever set —
    passes the one redaction chokepoint, never a second ad-hoc path.
    """
    for key, value in safe_attributes(attrs).items():
        span.set_attribute(key, value)


def traced(
    name: str | None = None, **static_attrs: object
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator form of :func:`traced_step`. ``name`` defaults to the function's qualified name."""

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with traced_step(span_name, **static_attrs):
                return fn(*args, **kwargs)

        return wrapper

    return decorate
