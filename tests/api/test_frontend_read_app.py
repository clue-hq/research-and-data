"""FI-2 slice 1, Task 1 — the frontend-read router foundation.

Covers the four things the foundation owes every later slice-1 endpoint: the default-off flag gate
(routes absent → 404 when off, mounted when on), the FI-1 error envelope
``{error: {code, message, requestId}}`` on this router's error paths only, the per-request id echoed
in a response header, and the config-driven CORS middleware (absent unless origins are configured).
Plus the FI-1 L2 index the accounts-list status aggregation needs (DB-gated).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from clue_api.frontend_read import (
    FRONTEND_READ_PREFIX,
    REQUEST_ID_HEADER,
    build_frontend_read_router,
)
from clue_api.projections_app import create_projections_app
from clue_config import Settings, load_settings
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, **kwargs)


def _paths(settings: Settings) -> set[tuple[str, str]]:
    router = build_frontend_read_router(settings=settings, conn_factory=None)  # type: ignore[arg-type]
    return {(method, route.path) for route in router.routes for method in (route.methods or ())}  # type: ignore[attr-defined]


def _app(settings: Settings) -> FastAPI:
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=settings,
        conn_factory=None,  # type: ignore[arg-type]
        manage_db_lifespan=False,
    )


# --- flag gating ---------------------------------------------------------------------------


def test_the_router_exposes_nothing_by_default() -> None:
    assert _paths(_settings()) == set()


def test_the_flag_mounts_the_router() -> None:
    assert _paths(_settings(frontend_read_enabled=True)) == {
        ("GET", f"{FRONTEND_READ_PREFIX}/health")
    }


def test_flag_off_the_app_serves_no_frontend_routes() -> None:
    with TestClient(_app(_settings())) as client:
        assert client.get(f"{FRONTEND_READ_PREFIX}/health").status_code == 404


def test_flag_on_the_app_serves_the_router_health_probe() -> None:
    with TestClient(_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers[REQUEST_ID_HEADER]


# --- the FI-1 error envelope ---------------------------------------------------------------


def _envelope_app() -> FastAPI:
    """The router mounted, plus two throwaway routes that force a 422 and a 500 under the prefix."""
    app = _app(_settings(frontend_read_enabled=True))

    @app.get(f"{FRONTEND_READ_PREFIX}/_probe")
    async def _probe(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get(f"{FRONTEND_READ_PREFIX}/_boom")
    async def _boom() -> dict[str, str]:
        raise RuntimeError("boom")

    return app


def _assert_envelope(payload: object, *, code: str) -> str:
    assert isinstance(payload, dict)
    assert set(payload) == {"error"}
    error = payload["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "requestId"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    request_id = error["requestId"]
    assert isinstance(request_id, str) and len(request_id) == 32
    return request_id


def test_an_unknown_route_under_the_prefix_serves_the_envelope() -> None:
    with TestClient(_envelope_app()) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/nope")
        assert response.status_code == 404
        request_id = _assert_envelope(response.json(), code="NOT_FOUND")
        assert response.headers[REQUEST_ID_HEADER] == request_id


def test_a_validation_failure_serves_the_envelope() -> None:
    with TestClient(_envelope_app()) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_probe", params={"n": "abc"})
        assert response.status_code == 422
        request_id = _assert_envelope(response.json(), code="VALIDATION_ERROR")
        assert response.headers[REQUEST_ID_HEADER] == request_id


def test_an_unhandled_error_serves_the_envelope_without_leaking_the_cause() -> None:
    with TestClient(_envelope_app(), raise_server_exceptions=False) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_boom")
        assert response.status_code == 500
        _assert_envelope(response.json(), code="INTERNAL_ERROR")
        assert "boom" not in response.text


def test_routes_outside_the_router_keep_their_own_error_shape() -> None:
    """The handlers are router-scoped: the B4 projection routes still answer ``{"detail": …}``."""
    with TestClient(_envelope_app()) as client:
        response = client.get("/project_runs/00000000-0000-0000-0000-000000000000/overview")
        assert response.status_code == 401
        assert "detail" in response.json()
        assert "error" not in response.json()
        assert REQUEST_ID_HEADER not in response.headers


# --- CORS ----------------------------------------------------------------------------------


def test_no_cors_middleware_without_configured_origins() -> None:
    with TestClient(_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(
            f"{FRONTEND_READ_PREFIX}/health", headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


def test_configured_origins_add_the_cors_middleware() -> None:
    settings = _settings(
        frontend_read_enabled=True,
        frontend_cors_allow_origins=("http://localhost:3000",),
    )
    with TestClient(_app(settings)) as client:
        response = client.get(
            f"{FRONTEND_READ_PREFIX}/health", headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

        preflight = client.options(
            f"{FRONTEND_READ_PREFIX}/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Workspace-Id",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_origins_accept_both_env_spellings() -> None:
    comma = _settings(frontend_cors_allow_origins="http://a.test, http://b.test")
    assert comma.frontend_cors_allow_origins == ("http://a.test", "http://b.test")
    as_json = _settings(frontend_cors_allow_origins='["http://a.test","http://b.test"]')
    assert as_json.frontend_cors_allow_origins == ("http://a.test", "http://b.test")


# --- the FI-1 L2 index (DB-gated) ----------------------------------------------------------


@pytest.mark.usefixtures("require_profiling_db")
def test_the_l2_subject_entity_index_exists() -> None:
    async def _check() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            indexdef = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE tablename = 'entity_research_job' "
                        "AND indexname = 'entity_research_job_subject_entity'"
                    )
                )
            ).scalar_one_or_none()
        assert indexdef is not None, "FI-1 L2 index is missing"
        assert "subject_entity_id" in indexdef

    run_async(_check())
