"""Lane 3 slice 2, Task 2: one provider per process, run context on every span, both
instrumentors behind one install."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import structlog
from fastapi import APIRouter, FastAPI
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from clue_obs import bound_context
from clue_obs.otel import (
    RUN_CONTEXT_KEYS,
    RunContextSpanProcessor,
    bind_and_annotate,
    install_tracing,
    parse_otlp_headers,
    traced_step,
)


def _runtime(**kwargs: object):  # type: ignore[no-untyped-def]
    runtime = install_tracing(
        process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=False, **kwargs
    )
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))
    return runtime, exporter


def test_the_processor_copies_only_run_context_keys_through_the_redaction_chokepoint() -> None:
    runtime, exporter = _runtime()
    with (
        bound_context(workspace_id="ws_1", turn_id="turn_1", api_key="sk-secret", note="x"),
        traced_step("unit"),
    ):
        pass
    (span,) = exporter.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["workspace_id"] == "ws_1"
    assert span.attributes["turn_id"] == "turn_1"
    assert "api_key" not in span.attributes and "note" not in span.attributes
    assert {"workspace_id", "turn_id", "request_id", "fleet_kind"} <= RUN_CONTEXT_KEYS


def test_install_without_an_endpoint_exports_nothing_and_names_the_service() -> None:
    runtime, exporter = _runtime()
    assert runtime.exporting is False
    with traced_step("unit"):
        pass
    (span,) = exporter.get_finished_spans()
    assert span.resource.attributes["service.name"] == "clue-test"


class _Ping(BaseHTTPRequestHandler):
    """A loopback endpoint, because the instrumentation wraps ``httpx.HTTPTransport``.

    ``HTTPXClientInstrumentor`` (0.63b1) wraps ``httpx.HTTPTransport.handle_request`` and
    ``AsyncHTTPTransport.handle_async_request`` — it no longer wraps the client's transport
    object, so a client built on ``httpx.MockTransport`` produces **no** client span. Driving a
    real transport at 127.0.0.1 is what actually exercises the seam this test is about.
    """

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler's contract)
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return None


def test_httpx_client_spans_nest_under_the_current_span() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    runtime = install_tracing(
        process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=True
    )
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ping)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        with traced_step("parent") as parent, httpx.Client() as client:
            assert client.get(f"http://127.0.0.1:{port}/ping").status_code == 200
        client_span = next(s for s in exporter.get_finished_spans() if s.kind is SpanKind.CLIENT)
        assert client_span.parent is not None
        assert client_span.parent.span_id == parent.get_span_context().span_id
        assert client_span.attributes is not None
        assert client_span.attributes["http.method"] == "GET"
    finally:
        server.shutdown()
        server.server_close()
        HTTPXClientInstrumentor().uninstrument()


def test_instrument_app_yields_a_server_span_carrying_the_bound_context() -> None:
    runtime, exporter = _runtime()
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "yes"}

    runtime.instrument_app(app)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            with bound_context(request_id="req-1"):
                response = await client.get("/ping")
        assert response.status_code == 200

    asyncio.run(scenario())
    server = next(s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER)
    assert server.attributes is not None
    assert server.attributes.get("http.route") == "/ping"
    assert server.attributes.get("request_id") == "req-1"


def test_instrument_app_survives_a_partial_match_on_an_included_router() -> None:
    """FastAPI 0.138 keeps ``include_router`` sub-routers in ``app.routes`` as entries that can
    match a request but carry no ``path``. The OTel FastAPI instrumentation (0.63b1 through
    0.65b0) guards that on a full match and reads ``.path`` unguarded on a partial one, so a
    request whose path matches such a router with the wrong method took the whole request down
    with a 500 (the live thread-page failure of 2026-09-15). The span falls back to the raw path,
    exactly as the library already does for a full match, and the app answers as it would
    uninstrumented."""
    runtime, exporter = _runtime()
    app = FastAPI()
    router = APIRouter()

    @router.post("/things/{thing_id}")
    async def create_thing(thing_id: str) -> dict[str, str]:
        return {"thing": thing_id}

    app.include_router(router, prefix="/api/v1")
    runtime.instrument_app(app)

    async def scenario() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return (await client.get("/api/v1/things/42")).status_code

    assert asyncio.run(scenario()) == 405
    server = next(s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER)
    assert server.attributes is not None
    assert server.attributes.get("http.route") == "/api/v1/things/42"


def test_bind_and_annotate_reaches_a_span_that_is_already_open() -> None:
    runtime, exporter = _runtime()
    with traced_step("server") as span:
        bind_and_annotate(workspace_id="ws_late", note="free text")
        assert span.is_recording()
    (finished,) = exporter.get_finished_spans()
    assert finished.attributes is not None
    assert finished.attributes["workspace_id"] == "ws_late"
    assert "note" not in finished.attributes
    assert structlog.contextvars.get_contextvars().get("workspace_id") == "ws_late"
    structlog.contextvars.clear_contextvars()


def test_parse_otlp_headers() -> None:
    assert parse_otlp_headers("a=b, c=d=e") == {"a": "b", "c": "d=e"}
    assert parse_otlp_headers("") == {} and parse_otlp_headers(None) == {}
    with pytest.raises(ValueError):
        parse_otlp_headers("novalue")


def test_the_run_context_processor_satisfies_the_sdk_processor_contract() -> None:
    assert issubclass(RunContextSpanProcessor, SpanProcessor)
