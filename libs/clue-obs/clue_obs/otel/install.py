"""The process-root tracing install (lane 3 slice 2).

One :class:`TracerProvider` per process, named after the process, exporting over OTLP/HTTP only
when an endpoint is configured — otherwise spans are created and go nowhere, the library default
since M0.5. The provider becomes both OTel's global provider (the FastAPI and httpx instrumentors
read that) and the one behind :func:`~clue_obs.otel.tracing.traced_step`, so a request span, the
handler's own steps and every outbound HTTP call are one trace. :class:`RunContextSpanProcessor`
copies the structlog-bound run context onto every span through the one redaction chokepoint.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from clue_obs.context import bind_context
from clue_obs.otel import tracing
from clue_obs.otel.attributes import (
    ATTR_ACCOUNT_ID,
    ATTR_ACTOR,
    ATTR_FLEET_KIND,
    ATTR_JOB_ID,
    ATTR_PROFILE_VERSION,
    ATTR_PROJECT_ID,
    ATTR_REQUEST_ID,
    ATTR_RUN_ID,
    ATTR_TASK_ATTEMPT,
    ATTR_TASK_ID,
    ATTR_THREAD_ID,
    ATTR_TURN_ID,
    ATTR_WORK_ID,
    ATTR_WORKER_ID,
    ATTR_WORKSPACE_ID,
    safe_attributes,
)

__all__ = [
    "RUN_CONTEXT_KEYS",
    "RunContextSpanProcessor",
    "TracingRuntime",
    "bind_and_annotate",
    "bound_run_context",
    "install_tracing",
    "parse_otlp_headers",
]

#: The bound-context keys that ride onto spans (and Sentry tags): identifiers and closed
#: vocabularies the roots bind, never free text.
RUN_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        ATTR_REQUEST_ID,
        ATTR_WORKSPACE_ID,
        ATTR_PROJECT_ID,
        ATTR_RUN_ID,
        ATTR_THREAD_ID,
        ATTR_TURN_ID,
        ATTR_JOB_ID,
        ATTR_ACCOUNT_ID,
        ATTR_ACTOR,
        ATTR_PROFILE_VERSION,
        ATTR_TASK_ID,
        ATTR_WORK_ID,
        ATTR_FLEET_KIND,
        ATTR_TASK_ATTEMPT,
        ATTR_WORKER_ID,
    }
)


def bound_run_context() -> dict[str, object]:
    """The currently bound run context, restricted to :data:`RUN_CONTEXT_KEYS`."""
    bound = structlog.contextvars.get_contextvars()
    return {key: value for key, value in bound.items() if key in RUN_CONTEXT_KEYS}


def bind_and_annotate(**fields: object) -> None:
    """Bind run-context fields for the rest of the current context AND stamp them on the
    current span. ``RunContextSpanProcessor`` copies the context at span *start*; a field learnt
    later (the workspace id, resolved inside a route dependency after the server span opened)
    needs this second write to reach the span that is already open."""
    bind_context(**fields)
    span = trace.get_current_span()
    if not span.is_recording():
        return
    subset = {key: value for key, value in fields.items() if key in RUN_CONTEXT_KEYS}
    for key, value in safe_attributes(subset).items():
        span.set_attribute(key, value)


class RunContextSpanProcessor(SpanProcessor):
    """Copy the bound run context onto every span at start, through ``safe_attributes``."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        attrs = bound_run_context()
        if not attrs:
            return
        for key, value in safe_attributes(attrs).items():
            span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def parse_otlp_headers(raw: str | None) -> dict[str, str]:
    """``"k=v,k2=v2"`` → a header mapping. The value may itself contain ``=`` (base64 padding)."""
    if raw is None or not raw.strip():
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"OTLP header pair without a value: {pair!r}")
        headers[key.strip()] = value.strip()
    return headers


@dataclass(frozen=True)
class TracingRuntime:
    """What a root holds after :func:`install_tracing`: the provider, and the two hooks."""

    provider: TracerProvider
    process_name: str
    exporting: bool

    def instrument_app(self, app: Any) -> None:
        """Server spans for one FastAPI app. Call at construction — Starlette refuses new
        middleware once the app has started."""
        import opentelemetry.instrumentation.fastapi as fastapi_instrumentation

        _install_safe_route_details(fastapi_instrumentation)
        fastapi_instrumentation.FastAPIInstrumentor.instrument_app(
            app, tracer_provider=self.provider
        )

    def shutdown(self) -> None:
        """Flush the batch exporter and stop the provider (graceful shutdown)."""
        self.provider.force_flush()
        self.provider.shutdown()


def _route_details(scope: MutableMapping[str, Any]) -> str | None:
    """The route template a request matched, for the server span's name and ``http.route``.

    This is the instrumentation's own ``_get_route_details`` with one difference: a matched
    route that carries no ``path`` falls back to the request's raw path on a *partial* match as
    well as on a full one. FastAPI 0.138 keeps every ``include_router`` sub-router in
    ``app.routes`` as an ``_IncludedRouter`` — it can match a request but has no ``path`` — and
    the library (0.63b1 through 0.65b0) reads ``.path`` unguarded on the partial branch, so a
    request whose path matched such a router with the wrong method failed with a 500 before it
    reached any handler (the live thread-page failure of 2026-09-15).
    """
    from starlette.routing import Match, Route

    route: str | None = None
    for starlette_route in scope["app"].routes:
        match, _ = (
            Route.matches(starlette_route, scope)
            if isinstance(starlette_route, Route)
            else starlette_route.matches(scope)
        )
        if match == Match.FULL:
            return getattr(starlette_route, "path", None) or scope.get("path")
        if match == Match.PARTIAL:
            route = getattr(starlette_route, "path", None) or scope.get("path")
    return route


def _install_safe_route_details(fastapi_instrumentation: Any) -> None:
    """Point the instrumentation's span-details callback at :func:`_route_details`.

    ``_get_default_span_details`` (the callback the instrumentor wires into its middleware)
    resolves ``_get_route_details`` through its module at call time, so replacing that name is
    the whole intervention. The name is checked so an upstream rename fails at boot, where a
    human sees it, rather than silently restoring the crash on the next request.
    """
    if not callable(getattr(fastapi_instrumentation, "_get_route_details", None)):
        raise RuntimeError(
            "opentelemetry-instrumentation-fastapi no longer exposes _get_route_details; "
            "revisit clue_obs.otel.install._route_details against the installed version"
        )
    fastapi_instrumentation._get_route_details = _route_details


def install_tracing(
    *,
    process_name: str,
    endpoint: str | None = None,
    headers: Mapping[str, str] | None = None,
    instrument_httpx: bool = True,
    set_global: bool = True,
) -> TracingRuntime:
    """Build the process's provider, make it the one every span uses, instrument httpx.

    ``endpoint`` empty/None → no exporter (spans stay in-process). ``set_global=False`` and
    ``instrument_httpx=False`` are for tests: OTel accepts one global provider per process and
    the httpx instrumentation is process-wide.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": process_name}))
    provider.add_span_processor(RunContextSpanProcessor())
    exporting = bool(endpoint)
    if exporting:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=dict(headers or {})))
        )
    if set_global:
        trace.set_tracer_provider(provider)
    tracing.use_provider(provider)
    if instrument_httpx:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    return TracingRuntime(provider=provider, process_name=process_name, exporting=exporting)
