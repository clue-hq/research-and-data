"""W1.3 — the artifact→design-document read seam (DB-gated).

The v1 seam: design documents are not yet registered as platform artifacts, so
``GET /api/v1/projects/{project_id}/design-artifacts/{artifact_id}`` resolves
the artifact id AS the design-document id behind a typed wire — workspace
scoping enforced fail-closed on both the project and the document. The
project↔document containment gap is recorded on ``DesignArtifactWire``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api import build_tool_invoker, create_projections_app
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_config import Settings, load_settings
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import fixture_membership_id, seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_w13_test"
_AUTHENTICATED_AT = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


def _settings() -> Settings:
    return load_settings(_env_file=None, chat_enabled=True)


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_AUTHENTICATED_AT,
    )


def _app(conn, *, settings: Settings):
    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=cf,
        ),
        settings=settings,
        conn_factory=cf,
        manage_db_lifespan=False,
        chat_principal_resolver=_principal,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _seed_design_document(
    conn,
    *,
    workspace_id: str,
    document_id: str,
    doc_kind: str = "web",
    title: str = "Landing page",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_document"
            " (id, workspace_id, title, status, doc_kind, current_scene_json, current_version)"
            " VALUES (:id, :w, :title, 'draft', :kind, CAST(:scene AS jsonb), 0)"
        ),
        {"id": document_id, "w": workspace_id, "title": title, "kind": doc_kind, "scene": "{}"},
    )


def test_the_seam_resolves_a_web_document_with_real_metadata(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-w13-web", name="W13 web")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=project.workspace_id, document_id="doc_web_1"
            )
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                response = await client.get(
                    f"/api/v1/projects/{project.project_id}/design-artifacts/doc_web_1",
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            assert data == {
                "id": "doc_web_1",
                "project_id": project.project_id,
                "document_id": "doc_web_1",
                "kind": "web",
                "title": "Landing page",
                "status": "draft",
                "current_version_id": "0",
            }

    run_async(scenario())


def test_a_scene_document_maps_to_the_ad_kind(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-w13-scene", name="W13 scene")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn,
                workspace_id=project.workspace_id,
                document_id="doc_scene_1",
                doc_kind="scene",
                title="Ad set",
            )
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                response = await client.get(
                    f"/api/v1/projects/{project.project_id}/design-artifacts/doc_scene_1",
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert response.status_code == 200, response.text
            assert response.json()["data"]["kind"] == "ad"

    run_async(scenario())


def test_missing_project_and_missing_document_refuse_with_typed_404s(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_project_row(conn, "ws-w13-404", name="W13 404")
            await seed_principal(conn, workspace_id=project.workspace_id, user_id=USER_ID)
            app = _app(conn, settings=_settings())
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                no_project = await client.get(
                    "/api/v1/projects/prj_missing/design-artifacts/doc_x",
                    headers=headers,
                )
                no_document = await client.get(
                    f"/api/v1/projects/{project.project_id}/design-artifacts/doc_missing",
                    headers=headers,
                )
            assert no_project.status_code == 404
            assert no_project.json()["error"]["code"] == "PROJECT_NOT_FOUND"
            assert no_document.status_code == 404
            assert no_document.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"

    run_async(scenario())


def test_a_foreign_workspace_document_is_invisible(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ours = await _seed_project_row(conn, "ws-w13-ours", name="W13 ours")
            theirs = await _seed_project_row(conn, "ws-w13-theirs", name="W13 theirs")
            await seed_principal(conn, workspace_id=ours.workspace_id, user_id=USER_ID)
            await _seed_design_document(
                conn, workspace_id=theirs.workspace_id, document_id="doc_foreign"
            )
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                response = await client.get(
                    f"/api/v1/projects/{ours.project_id}/design-artifacts/doc_foreign",
                    headers={"X-Workspace-Id": ours.workspace_id},
                )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"

    run_async(scenario())
