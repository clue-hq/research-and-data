"""FI-2 slice 1, Task 1 — the frontend-read router foundation.

Covers what the foundation owes every later slice-1 endpoint: the default-off flag gate (routes
absent → 404 when off, mounted when on), the **structural** workspace dependency on the scoped
router (with the health probe deliberately outside it), the FI-1 error envelope
``{error: {code, message, requestId}}`` on this surface's error paths only, the per-request id
echoed in a response header, and the config-driven CORS middleware — including that the 500 envelope
is produced *inside* the CORS layer so a cross-origin browser can actually read it. Plus the FI-1 L2
index the accounts-list status aggregation needs (DB-gated).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from clue_api.frontend_read import (
    FRONTEND_READ_PREFIX,
    REQUEST_ID_HEADER,
    build_frontend_read_probe_router,
    build_frontend_read_router,
)
from clue_api.projections_app import create_projections_app
from clue_api.research_view_governance import safe_public_url
from clue_config import Settings, load_settings
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

ORIGIN = "http://localhost:3000"


def test_public_evidence_urls_are_http_only_and_credential_free() -> None:
    assert safe_public_url("https://evidence.example/report/1?version=2#claim")
    assert safe_public_url("http://evidence.example/")
    assert not safe_public_url("javascript:alert(1)")
    assert not safe_public_url("file:///tmp/evidence")
    assert not safe_public_url("https://user:secret@evidence.example/report")
    assert not safe_public_url("https:///missing-host")


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, **kwargs)


def _router_paths(router: object) -> set[tuple[str, str]]:
    return {
        (method, route.path)  # type: ignore[attr-defined]
        for route in router.routes  # type: ignore[attr-defined]
        for method in (route.methods or ())  # type: ignore[attr-defined]
    }


def _scoped_paths(settings: Settings) -> set[tuple[str, str]]:
    return _router_paths(build_frontend_read_router(settings=settings, conn_factory=None))  # type: ignore[arg-type]


def _probe_paths(settings: Settings) -> set[tuple[str, str]]:
    return _router_paths(build_frontend_read_probe_router(settings=settings))


def _app(settings: Settings) -> FastAPI:
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=settings,
        conn_factory=None,  # type: ignore[arg-type]
        manage_db_lifespan=False,
    )


def _probe_app(settings: Settings) -> FastAPI:
    """The app plus throwaway routes that exercise each error path: a scoped route (workspace
    dependency), a 422, an in-prefix 500, and an off-prefix 500 for the parity assertions."""

    app = _app(settings)

    scoped = build_frontend_read_router(settings=settings, conn_factory=None)  # type: ignore[arg-type]

    @scoped.get("/_scoped")
    async def _scoped_route() -> dict[str, str]:
        return {"scoped": "ok"}

    app.include_router(scoped)

    @app.get(f"{FRONTEND_READ_PREFIX}/_probe")
    async def _probe(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get(f"{FRONTEND_READ_PREFIX}/_boom")
    async def _boom() -> dict[str, str]:
        raise RuntimeError("boom")

    @app.get("/_offprefix_boom")
    async def _offprefix_boom() -> dict[str, str]:
        raise RuntimeError("off-prefix boom")

    return app


# --- flag gating ---------------------------------------------------------------------------


def test_neither_router_exposes_anything_by_default() -> None:
    assert _scoped_paths(_settings()) == set()
    assert _probe_paths(_settings()) == set()


def test_the_flag_mounts_the_probe_router() -> None:
    enabled = _settings(frontend_read_enabled=True)
    assert _probe_paths(enabled) == {("GET", f"{FRONTEND_READ_PREFIX}/health")}
    # The scoped router is where Tasks 2-4 register; Task 2 added the accounts list.
    scoped = _scoped_paths(enabled)
    assert ("GET", f"{FRONTEND_READ_PREFIX}/accounts") in scoped
    # ARV2 O5 — the brand-context Knowledge reads.
    assert ("GET", f"{FRONTEND_READ_PREFIX}/brand-context/knowledge") in scoped
    assert (
        "GET",
        f"{FRONTEND_READ_PREFIX}/brand-context/knowledge/documents/{{document_id}}",
    ) in scoped
    assert ("GET", f"{FRONTEND_READ_PREFIX}/brand-context/onboarding/current") in scoped


def test_flag_off_keeps_routes_absent_but_returns_a_correlatable_error() -> None:
    with TestClient(_app(_settings())) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/health")
        assert response.status_code == 404
        request_id = _assert_envelope(response.json(), code="NOT_FOUND")
        assert response.headers[REQUEST_ID_HEADER] == request_id


def test_flag_off_error_ownership_remains_prefix_scoped() -> None:
    with TestClient(_app(_settings())) as client:
        response = client.get(
            "/not-a-frontend-read-route", headers={REQUEST_ID_HEADER: "off-prefix-not-found"}
        )
        assert response.status_code == 404
        assert "detail" in response.json()
        assert "error" not in response.json()
        # App-wide telemetry echoes request ids without changing this route's error envelope.
        assert response.headers[REQUEST_ID_HEADER] == "off-prefix-not-found"


def test_flag_on_the_app_serves_the_router_health_probe() -> None:
    with TestClient(_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers[REQUEST_ID_HEADER]


# --- structural workspace scoping ----------------------------------------------------------


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


def test_a_scoped_route_refuses_a_request_without_the_workspace_header() -> None:
    with TestClient(_probe_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_scoped")
        assert response.status_code == 401
        request_id = _assert_envelope(response.json(), code="UNAUTHORIZED")
        assert response.headers[REQUEST_ID_HEADER] == request_id


def test_a_scoped_route_serves_with_the_workspace_header() -> None:
    with TestClient(_probe_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_scoped", headers={"X-Workspace-Id": "ws-1"})
        assert response.status_code == 200
        assert response.json() == {"scoped": "ok"}


def test_the_health_probe_needs_no_workspace_header() -> None:
    """It lives outside the scoped router on purpose — a liveness probe carries no tenant."""
    with TestClient(_probe_app(_settings(frontend_read_enabled=True))) as client:
        assert client.get(f"{FRONTEND_READ_PREFIX}/health").status_code == 200


# --- the FI-1 error envelope ---------------------------------------------------------------


def test_an_unknown_route_under_the_prefix_serves_the_envelope() -> None:
    with TestClient(_probe_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/nope")
        assert response.status_code == 404
        request_id = _assert_envelope(response.json(), code="NOT_FOUND")
        assert response.headers[REQUEST_ID_HEADER] == request_id


def test_a_validation_failure_serves_the_envelope() -> None:
    with TestClient(_probe_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_probe", params={"n": "abc"})
        assert response.status_code == 422
        request_id = _assert_envelope(response.json(), code="VALIDATION_ERROR")
        assert response.headers[REQUEST_ID_HEADER] == request_id


def test_an_unhandled_error_serves_the_envelope_without_leaking_the_cause() -> None:
    with TestClient(
        _probe_app(_settings(frontend_read_enabled=True)), raise_server_exceptions=False
    ) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_boom")
        assert response.status_code == 500
        _assert_envelope(response.json(), code="INTERNAL_ERROR")
        assert "boom" not in response.text


def test_routes_outside_the_router_keep_their_own_error_shape() -> None:
    """The handlers are path-scoped: the B4 projection routes still answer ``{"detail": …}``."""
    with TestClient(_probe_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(
            "/project_runs/00000000-0000-0000-0000-000000000000/overview",
            headers={REQUEST_ID_HEADER: "off-prefix-unauthorized"},
        )
        assert response.status_code == 401
        assert "detail" in response.json()
        assert "error" not in response.json()
        assert response.headers[REQUEST_ID_HEADER] == "off-prefix-unauthorized"


def test_an_off_prefix_unhandled_error_still_propagates_to_the_server() -> None:
    """Parity: installing this surface must not change how an unrelated route's crash behaves."""
    settings = _settings(frontend_read_enabled=True)
    with (
        TestClient(_probe_app(settings)) as client,
        pytest.raises(RuntimeError, match="off-prefix boom"),
    ):
        client.get("/_offprefix_boom")
    with TestClient(_probe_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/_offprefix_boom")
        assert response.status_code == 500
        assert "error" not in response.text
        assert REQUEST_ID_HEADER not in response.headers


# --- CORS ----------------------------------------------------------------------------------


def test_no_cors_middleware_without_configured_origins() -> None:
    with TestClient(_app(_settings(frontend_read_enabled=True))) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/health", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


def test_configured_origins_add_the_cors_middleware() -> None:
    settings = _settings(frontend_read_enabled=True, frontend_cors_allow_origins=(ORIGIN,))
    with TestClient(_app(settings)) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/health", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN
        exposed = response.headers["access-control-expose-headers"].lower()
        assert REQUEST_ID_HEADER.lower() in exposed

        preflight = client.options(
            f"{FRONTEND_READ_PREFIX}/health",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Workspace-Id",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == ORIGIN


def test_cross_origin_writes_are_not_allowed() -> None:
    """Slice 1 is a read surface; widening the verb list must be a deliberate later decision."""
    settings = _settings(frontend_read_enabled=True, frontend_cors_allow_origins=(ORIGIN,))
    with TestClient(_app(settings)) as client:
        preflight = client.options(
            "/tools/some_tool",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
        )
        # Starlette answers a disallowed-method preflight 400 ("Disallowed CORS method") and
        # advertises only the verbs it will accept — so the browser never sends the POST.
        assert preflight.status_code == 400
        assert preflight.headers["access-control-allow-methods"] == "GET, OPTIONS"


def test_the_500_envelope_is_produced_inside_the_cors_layer() -> None:
    """Otherwise the browser drops the response and the frontend never sees code/requestId."""
    settings = _settings(frontend_read_enabled=True, frontend_cors_allow_origins=(ORIGIN,))
    with TestClient(_probe_app(settings), raise_server_exceptions=False) as client:
        response = client.get(f"{FRONTEND_READ_PREFIX}/_boom", headers={"Origin": ORIGIN})
        assert response.status_code == 500
        _assert_envelope(response.json(), code="INTERNAL_ERROR")
        assert response.headers["access-control-allow-origin"] == ORIGIN
        exposed = response.headers["access-control-expose-headers"].lower()
        assert REQUEST_ID_HEADER.lower() in exposed
        assert response.headers[REQUEST_ID_HEADER]


# --- the CORS origins setting --------------------------------------------------------------


def test_cors_origins_accept_both_env_spellings() -> None:
    comma = _settings(frontend_cors_allow_origins="http://a.test, http://b.test")
    assert comma.frontend_cors_allow_origins == ("http://a.test", "http://b.test")
    as_json = _settings(frontend_cors_allow_origins='["http://a.test","http://b.test"]')
    assert as_json.frontend_cors_allow_origins == ("http://a.test", "http://b.test")


@pytest.mark.parametrize("value", ["*", "http://a.test,*", '["*"]', ("*",)])
def test_a_wildcard_origin_is_refused(value: object) -> None:
    """Starlette does NOT refuse ``*`` + credentials — it echoes the caller's Origin back. With
    trusted-header tenancy that would make the whole app any-origin credentialed, so the wildcard
    dies at config load with an explanation."""
    with pytest.raises(ValidationError, match='must not contain "\\*"'):
        _settings(frontend_cors_allow_origins=value)


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
