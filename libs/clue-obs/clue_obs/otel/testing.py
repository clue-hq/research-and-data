"""Test/dev helpers for the observability layer (M0.5).

``collect_spans()`` swaps the tracing backend for an in-memory exporter for the duration of a block
and yields it, so a test (or a dev probe) can assert exactly which spans were emitted, with which
names and attributes — without a live collector. The previous backend is restored on exit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clue_obs.otel import tracing


@contextmanager
def collect_spans() -> Iterator[InMemorySpanExporter]:
    """Capture spans emitted within the block into an :class:`InMemorySpanExporter`."""
    exporter = InMemorySpanExporter()
    saved_provider, saved_tracer = tracing._provider, tracing._tracer
    tracing.configure_tracing(exporter=exporter)
    try:
        yield exporter
    finally:
        tracing._provider, tracing._tracer = saved_provider, saved_tracer
