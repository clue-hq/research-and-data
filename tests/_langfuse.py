"""Langfuse installed against an in-memory exporter (lane 3 slice 3). No network, ever."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clue_obs.langfuse import flush_langfuse, install_langfuse, shutdown_langfuse


@contextmanager
def langfuse_installed(
    *, provider: TracerProvider | None = None
) -> Iterator[tuple[InMemorySpanExporter, TracerProvider]]:
    """Install the client on ``provider`` (a fresh one by default) with an in-memory exporter.

    The SDK keeps one resource manager per public key for the life of the process; the exit
    shuts the client down and clears that registry so the next test starts clean.
    """
    tracer_provider = provider if provider is not None else TracerProvider()
    exporter = InMemorySpanExporter()
    installed = install_langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://127.0.0.1:9",
        environment="lane-test",
        release="test",
        tracer_provider=tracer_provider,
        process_name="clue-test",
        span_exporter=exporter,
    )
    assert installed
    try:
        yield exporter, tracer_provider
    finally:
        shutdown_langfuse()
        LangfuseResourceManager.reset()


def finished_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    flush_langfuse()
    return list(exporter.get_finished_spans())
