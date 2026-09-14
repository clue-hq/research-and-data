"""Process lifecycle for tracing and error reporting at the roots (lane 3 slice 2).

Beside :mod:`clue_api.production_metrics`: the root reads the settings once, installs the
process's tracer provider (and Sentry when enabled), and flushes on graceful shutdown. Every
switch is off by default, so an unconfigured process behaves exactly as before.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from clue_config import Secrets, Settings
from clue_obs import get_logger, install_sentry
from clue_obs.langfuse import flush_langfuse, install_langfuse, shutdown_langfuse
from clue_obs.otel import TracingRuntime, install_tracing, parse_otlp_headers

__all__ = [
    "install_production_langfuse",
    "install_production_sentry",
    "install_production_tracing",
    "production_tracing_lifespan",
]

log = get_logger("clue_api.tracing")

#: Test seam: an exporter handed to the SDK instead of the host (never set in production).
_span_exporter_override: Any | None = None


def install_production_tracing(
    settings: Settings, secrets: Secrets, *, service_name: str
) -> TracingRuntime:
    """Install the process's tracer provider from the settings; exports only with an endpoint."""
    raw_headers = (
        secrets.otel_traces_headers.get_secret_value()
        if secrets.otel_traces_headers is not None
        else None
    )
    endpoint = (settings.otel_traces_endpoint or "").strip() or None
    runtime = install_tracing(
        process_name=service_name,
        endpoint=endpoint,
        headers=parse_otlp_headers(raw_headers),
        instrument_httpx=settings.otel_instrument_httpx,
    )
    log.info(
        "tracing.installed",
        service_name=service_name,
        exporting=runtime.exporting,
        instrument_httpx=settings.otel_instrument_httpx,
        instrument_fastapi=settings.otel_instrument_fastapi,
    )
    return runtime


def install_production_sentry(settings: Settings, secrets: Secrets, *, service_name: str) -> bool:
    """Install Sentry when enabled. Enabled with no DSN refuses loudly at composition."""
    dsn = secrets.sentry_dsn.get_secret_value().strip() if secrets.sentry_dsn is not None else ""
    if not settings.sentry_enabled:
        log.info("sentry.not_installed", reason="CLUE_SENTRY_ENABLED is off")
        return False
    if not dsn:
        raise RuntimeError("CLUE_SENTRY_ENABLED=true requires CLUE_SENTRY_DSN")
    installed = install_sentry(
        dsn=dsn,
        environment=settings.sentry_environment,
        release=settings.release or None,
        process_name=service_name,
    )
    log.info(
        "sentry.installed",
        service_name=service_name,
        environment=settings.sentry_environment,
        release=settings.release or None,
    )
    return installed


def install_production_langfuse(
    settings: Settings, secrets: Secrets, *, runtime: TracingRuntime, service_name: str
) -> bool:
    """Install Langfuse on the process's provider when enabled. Enabled with a missing key
    refuses loudly at composition (the Sentry posture); disabled installs nothing."""
    if not settings.langfuse_enabled:
        log.info("langfuse.not_installed", reason="CLUE_LANGFUSE_ENABLED is off")
        return False
    public_key = (
        secrets.langfuse_public_key.get_secret_value().strip()
        if secrets.langfuse_public_key is not None
        else ""
    )
    secret_key = (
        secrets.langfuse_secret_key.get_secret_value().strip()
        if secrets.langfuse_secret_key is not None
        else ""
    )
    if not public_key:
        raise RuntimeError("CLUE_LANGFUSE_ENABLED=true requires CLUE_LANGFUSE_PUBLIC_KEY")
    if not secret_key:
        raise RuntimeError("CLUE_LANGFUSE_ENABLED=true requires CLUE_LANGFUSE_SECRET_KEY")
    installed = install_langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=settings.langfuse_host,
        environment=settings.langfuse_environment,
        release=settings.release or None,
        tracer_provider=runtime.provider,
        process_name=service_name,
        span_exporter=_span_exporter_override,
    )
    log.info(
        "langfuse.installed",
        service_name=service_name,
        host=settings.langfuse_host,
        environment=settings.langfuse_environment,
        release=settings.release or None,
    )
    return installed


@asynccontextmanager
async def production_tracing_lifespan(runtime: TracingRuntime | None) -> AsyncIterator[None]:
    """Flush and stop the provider on graceful shutdown; ``None`` is a process without one."""
    try:
        yield
    finally:
        flush_langfuse()
        shutdown_langfuse()
        if runtime is not None:
            runtime.shutdown()
            log.info("tracing.stopped", service_name=runtime.process_name)
