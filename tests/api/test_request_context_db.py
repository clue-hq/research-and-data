"""Lane 3 slice 2, Task 5: a request through the projections app binds its request id and
workspace, echoes the id, and (when the app is instrumented) its server span carries them."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_obs.otel import install_tracing
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _app(conn: AsyncConnection, tracing: Any = None):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
        tracing=tracing,
    )


def test_the_request_id_is_echoed_and_a_safe_incoming_one_is_kept() -> None:
    async def scenario() -> tuple[str, str]:
        async with rollback_conn(seed_pack=False) as conn:
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn)), base_url="http://t"
            ) as client:
                kept = await client.get(
                    "/cost/report",
                    headers={"X-Workspace-Id": "ws_ctx", "X-Request-Id": "req-abc.1"},
                )
                minted = await client.get("/cost/report", headers={"X-Workspace-Id": "ws_ctx"})
            return kept.headers["X-Request-Id"], minted.headers["X-Request-Id"]

    kept, minted = run_async(scenario())
    assert kept == "req-abc.1"
    assert len(minted) == 32 and minted != kept


def test_the_server_span_carries_the_bound_request_and_workspace_ids() -> None:
    runtime = install_tracing(
        process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=False
    )
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            app = _app(conn, tracing=runtime)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                response = await client.get(
                    "/cost/report",
                    headers={"X-Workspace-Id": "ws_span", "X-Request-Id": "req-span"},
                )
                assert response.status_code == 200

    run_async(scenario())
    server = next(s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER)
    assert server.attributes.get("request_id") == "req-span"
    assert server.attributes.get("workspace_id") == "ws_span"
